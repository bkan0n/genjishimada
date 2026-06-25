"""Spike 007 — multipart banner upload via a REAL Litestar endpoint.

The headline question: can ONE Litestar multipart endpoint decode a *mixed* body —
a map-name text field AND a banner file (UploadFile) — together, then store the banner
under a STABLE key (`assets/map_banners/<sanitized>.png`) so the app's existing
`get_map_banner()` derivation keeps resolving it, and INSERT the name — no restart?

Spike 005 used base64-in-JSON. The real app uses multipart/form-data. A pure single-file
endpoint already exists (apps/api/routes/v3/utilities.py:upload_image). The UNPROVEN part is
the *mixed* form: a msgspec.Struct field + UploadFile in one body.

Deviation from CONVENTIONS (which say stdlib http.server): justified — the question is
literally about Litestar's multipart decoder, so we run real Litestar (a project dep,
`litestar[standard]` ships uvicorn). Everything else follows conventions: real local Postgres
+ MinIO, throwaway `spike007` schema seeded from `maps.names`, `spike007/` MinIO prefix,
cleanup in lifespan shutdown, forensic in-memory event log served at GET /api/log.

Run:
    uv run --env-file ../../../.env.local \
      --with 'litestar[standard]' --with asyncpg --with boto3 --with msgspec \
      python app.py
Then open http://localhost:8077  (Ctrl-C to stop — auto-cleans schema + MinIO objects).
"""

from __future__ import annotations

import datetime as dt
import io
import os
import re
from contextlib import asynccontextmanager
from typing import Annotated, Any, AsyncGenerator

import asyncpg
import boto3
import msgspec
from botocore.config import Config
from litestar import Litestar, MediaType, Request, Response, get, post
from litestar.datastructures import State, UploadFile
from litestar.enums import RequestEncodingType
from litestar.params import Body

# ---------------------------------------------------------------------------
# Config — read from .env.local exactly like the real app / prior spikes.
# ---------------------------------------------------------------------------
PG = {
    "host": os.environ.get("POSTGRES_HOST", "localhost"),
    "port": int(os.environ.get("POSTGRES_PORT", "5432")),
    "user": os.environ["POSTGRES_USER"],
    "password": os.environ["POSTGRES_PASSWORD"],
    "database": os.environ["POSTGRES_DB"],
}
S3_ENDPOINT = os.environ.get("S3_ENDPOINT_URL", "http://localhost:9000")
S3_KEY = os.environ.get("AWS_ACCESS_KEY_ID", "genji")
S3_SECRET = os.environ.get("AWS_SECRET_ACCESS_KEY", "local_dev_password")
S3_BUCKET = os.environ.get("S3_BUCKET_NAME", "genji-parkour-images")

SCHEMA = "spike007"
MINIO_PREFIX = "spike007"
PORT = 8077

# Mirrors the real `get_map_banner()` key derivation (reference: dynamic-map-management.md).
_ASSET_BANNER_PATH = "assets/map_banners"


def sanitize(map_name: str) -> str:
    """Stable banner-key stem derived from the map name (matches the real derivation)."""
    return re.sub(r"[^a-zA-Z0-9]", "", map_name).lower().strip()


def banner_key(map_name: str) -> str:
    """The STABLE key the real `get_map_banner()` would resolve to. No date, no digest."""
    return f"{MINIO_PREFIX}/{_ASSET_BANNER_PATH}/{sanitize(map_name)}.png"


# ---------------------------------------------------------------------------
# Forensic event log (convention: in-memory, ISO-timestamped, categorized).
# ---------------------------------------------------------------------------
EVENTS: list[dict[str, Any]] = []


def log_event(category: str, message: str, **meta: Any) -> None:
    EVENTS.append(
        {
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
            "category": category,
            "message": message,
            **meta,
        }
    )
    print(f"[{category}] {message} {meta if meta else ''}", flush=True)


# ---------------------------------------------------------------------------
# The mixed-multipart request model — THE thing under test.
# A msgspec.Struct with a plain text field AND an UploadFile field, decoded from
# one multipart/form-data body. This is what Spike 005's base64 path sidestepped.
# ---------------------------------------------------------------------------
class MapBannerUpload(msgspec.Struct):
    name: str
    banner: UploadFile


def s3_client() -> Any:
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_KEY,
        aws_secret_access_key=S3_SECRET,
        region_name="auto",
        config=Config(s3={"addressing_style": "path"}),
    )


# ---------------------------------------------------------------------------
# Lifespan: build throwaway schema seeded from real maps.names; tear it down.
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncGenerator[None, None]:
    pool = await asyncpg.create_pool(**PG, min_size=1, max_size=4)
    app.state.pool = pool
    app.state.s3 = s3_client()
    async with pool.acquire() as conn:
        await conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        await conn.execute(f"CREATE SCHEMA {SCHEMA}")
        await conn.execute(
            f"CREATE TABLE {SCHEMA}.names (name text PRIMARY KEY)"
        )
        seeded = await conn.execute(
            f"INSERT INTO {SCHEMA}.names (name) SELECT name FROM maps.names ON CONFLICT DO NOTHING"
        )
        count = await conn.fetchval(f"SELECT count(*) FROM {SCHEMA}.names")
    log_event("setup", f"throwaway schema {SCHEMA}.names seeded from maps.names", rows=count, exec=seeded)
    try:
        yield
    finally:
        # Cleanup MinIO objects under our prefix, then drop the schema.
        try:
            s3 = app.state.s3
            resp = s3.list_objects_v2(Bucket=S3_BUCKET, Prefix=f"{MINIO_PREFIX}/")
            keys = [{"Key": o["Key"]} for o in resp.get("Contents", [])]
            if keys:
                s3.delete_objects(Bucket=S3_BUCKET, Delete={"Objects": keys})
            log_event("teardown", "deleted MinIO objects", count=len(keys))
        except Exception as e:  # noqa: BLE001 — best-effort cleanup
            log_event("teardown", f"MinIO cleanup error: {e}")
        async with pool.acquire() as conn:
            await conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        await pool.close()
        log_event("teardown", f"dropped schema {SCHEMA}")


# ---------------------------------------------------------------------------
# THE endpoint under test — mixed multipart: struct field `name` + file `banner`.
# Mirrors the real CMS shape: validate → upload banner to stable key → INSERT name.
# ---------------------------------------------------------------------------
@post(
    "/api/maps",
    request_max_body_size=1024 * 1024 * 25,
    media_type=MediaType.JSON,
)
async def create_map(
    data: Annotated[MapBannerUpload, Body(media_type=RequestEncodingType.MULTI_PART)],
    state: State,
) -> dict[str, Any]:
    """Decode the mixed multipart body, store banner at a stable key, insert the name."""
    name = data.name.strip()
    content = await data.banner.read()
    content_type = data.banner.content_type or "image/png"
    log_event(
        "upload",
        "decoded mixed multipart body",
        name=name,
        banner_filename=data.banner.filename,
        banner_bytes=len(content),
        content_type=content_type,
    )
    if not name:
        return {"ok": False, "error": "name is required"}

    key = banner_key(name)
    state.s3.upload_fileobj(
        io.BytesIO(content),
        S3_BUCKET,
        key,
        ExtraArgs={"ContentType": content_type, "CacheControl": "public, max-age=31536000, immutable"},
    )
    log_event("upload", "banner stored at STABLE key (get_map_banner-resolvable)", key=key)

    pool: asyncpg.Pool = state.pool
    async with pool.acquire() as conn:
        result = await conn.execute(
            f"INSERT INTO {SCHEMA}.names (name) VALUES ($1) ON CONFLICT DO NOTHING", name
        )
    inserted = result.endswith("1")
    log_event("upload", "name inserted", name=name, inserted=inserted)
    return {"ok": True, "name": name, "banner_key": key, "inserted": inserted}


@get("/api/maps")
async def list_maps(state: State) -> list[str]:
    pool: asyncpg.Pool = state.pool
    async with pool.acquire() as conn:
        rows = await conn.fetch(f"SELECT name FROM {SCHEMA}.names ORDER BY name")
    return [r["name"] for r in rows]


@get("/api/banner", media_type="image/png")
async def get_banner(name: str, state: State) -> Response:
    """Proxy the stored object by deriving the SAME stable key from the name.

    This is the proof that storage-by-stable-key round-trips: we never persist the URL,
    we re-derive the key from the name — exactly what the real `get_map_banner()` does.
    """
    key = banner_key(name)
    try:
        obj = state.s3.get_object(Bucket=S3_BUCKET, Key=key)
        return Response(content=obj["Body"].read(), media_type="image/png")
    except Exception:  # noqa: BLE001
        return Response(content=b"", media_type="image/png", status_code=404)


@get("/api/log")
async def get_log() -> list[dict[str, Any]]:
    return EVENTS


@get("/", media_type=MediaType.HTML)
async def index() -> str:
    return INDEX_HTML


INDEX_HTML = """<!doctype html>
<html><head><meta charset=utf-8><title>Spike 007 — multipart banner upload</title>
<style>
 body{font:14px/1.5 system-ui;margin:0;background:#0e1116;color:#e6edf3}
 header{padding:18px 24px;background:#161b22;border-bottom:1px solid #30363d}
 h1{margin:0;font-size:18px} .sub{color:#8b949e;font-size:13px;margin-top:4px}
 main{padding:24px;max-width:1100px;margin:auto}
 .card{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:18px;margin-bottom:20px}
 label{display:block;color:#8b949e;font-size:12px;margin:8px 0 4px}
 input[type=text],input[type=file]{width:100%;padding:8px;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#e6edf3}
 button{margin-top:12px;padding:9px 16px;background:#238636;border:0;border-radius:6px;color:#fff;font-weight:600;cursor:pointer}
 .grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px}
 .map{background:#0d1117;border:1px solid #30363d;border-radius:8px;overflow:hidden;text-align:center}
 .map img{width:100%;height:84px;object-fit:cover;background:#21262d}
 .map .n{padding:6px;font-size:12px}
 .map.new{border-color:#238636;box-shadow:0 0 0 2px #23863633}
 pre{background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:10px;max-height:220px;overflow:auto;font-size:11px}
 .ok{color:#3fb950}.err{color:#f85149}
</style></head><body>
<header><h1>Spike 007 · multipart banner upload (real Litestar)</h1>
<div class=sub>One mixed multipart request → name field + banner file decoded together → banner stored at a stable key → name inserted. No restart.</div></header>
<main>
 <div class=card>
  <b>① Upload a map (multipart/form-data — real browser encoding)</b>
  <form id=f>
   <label>Map name</label><input type=text id=name placeholder="e.g. Spike Test Map" required>
   <label>Banner image (any png/jpg)</label><input type=file id=banner accept="image/*">
   <button type=submit>Upload map →</button>
  </form>
  <div id=res></div>
 </div>
 <div class=card>
  <b>② Live map list</b> <span class=sub id=count></span>
  <div class=grid id=grid></div>
 </div>
 <div class=card>
  <b>Forensic log</b> <button onclick=refreshLog() style="background:#30363d">refresh</button>
  <pre id=log></pre>
 </div>
</main>
<script>
let lastNew=null;
async function refresh(){
 const maps=await (await fetch('/api/maps')).json();
 document.getElementById('count').textContent='('+maps.length+' maps)';
 document.getElementById('grid').innerHTML=maps.map(m=>{
   const isNew=m===lastNew?' new':'';
   return `<div class="map${isNew}"><img src="/api/banner?name=${encodeURIComponent(m)}&t=${Date.now()}" onerror="this.style.opacity=.2"><div class=n>${m}</div></div>`;
 }).join('');
}
async function refreshLog(){
 const log=await (await fetch('/api/log')).json();
 document.getElementById('log').textContent=log.slice(-40).map(e=>`${e.ts.slice(11,19)} [${e.category}] ${e.message} ${JSON.stringify(Object.fromEntries(Object.entries(e).filter(([k])=>!['ts','category','message'].includes(k))))}`).join('\\n');
}
document.getElementById('f').addEventListener('submit',async ev=>{
 ev.preventDefault();
 const name=document.getElementById('name').value;
 const file=document.getElementById('banner').files[0];
 const fd=new FormData();
 fd.append('name',name);
 if(file) fd.append('banner',file); else fd.append('banner',new Blob([new Uint8Array([137,80,78,71,13,10,26,10])],{type:'image/png'}),'placeholder.png');
 const r=await (await fetch('/api/maps',{method:'POST',body:fd})).json();
 const res=document.getElementById('res');
 if(r.ok){res.innerHTML=`<span class=ok>✓ stored at ${r.banner_key} (inserted=${r.inserted})</span>`;lastNew=r.name;}
 else res.innerHTML=`<span class=err>✗ ${r.error}</span>`;
 await refresh();await refreshLog();
});
refresh();refreshLog();setInterval(refreshLog,3000);
</script>
</body></html>"""


app = Litestar(
    route_handlers=[create_map, list_maps, get_banner, get_log, index],
    lifespan=[lifespan],
)


if __name__ == "__main__":
    import uvicorn

    print(f"\n→ Spike 007 on http://localhost:{PORT}  (Ctrl-C to stop, auto-cleans)\n", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
