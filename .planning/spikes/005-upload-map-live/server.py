"""Spike 005 — upload-map-live.

The headline experiential spike. Prove the whole dream in something you can click:
upload a map (name + banner) via an endpoint and watch it appear AUTOMATICALLY across
all three surfaces with NO restart — website reads, map submission, and bot autocomplete.

Embodies the decisions from 004 (str + runtime maps.names validation) and 006 (endpoint
writes to the DB only; banner to object storage). Runs against the real local Docker
Postgres + MinIO, but isolated in a throwaway `spike005` schema (seeded from the real
maps.names) and a `spike005/` MinIO prefix — the real data is never touched.

Run:
    uv run --env-file ../../../.env.local --with asyncpg --with boto3 python server.py

Then open http://localhost:8077
"""

from __future__ import annotations

import asyncio
import base64
import datetime as dt
import json
import os
import re
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import asyncpg
import boto3

PORT = 8077
SCHEMA = "spike005"
BUCKET = "genji-parkour-images"
PREFIX = "spike005/map_banners"
HERE = Path(__file__).parent

s3 = boto3.client(
    "s3", endpoint_url=os.environ.get("S3_ENDPOINT_URL", "http://localhost:9000"),
    aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID", "genji"),
    aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY", "local_dev_password"),
    region_name="us-east-1",
)

EVENTS: list[dict] = []


def log_event(category: str, message: str, **meta) -> None:
    EVENTS.append({"ts": dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds"),
                   "category": category, "message": message, **meta})


def sanitize(map_name: str) -> str:
    """Mirror libs/sdk get_map_banner(): strip non-alnum, lowercase, drop spaces."""
    return re.sub(r"[^a-zA-Z0-9]", "", map_name).lower().strip().replace(" ", "")


def banner_key(map_name: str) -> str:
    return f"{PREFIX}/{sanitize(map_name)}.png"


# --- DB helpers (sync wrappers around asyncpg) -----------------------------
def run_db(coro_fn):
    async def _wrap():
        conn = await asyncpg.connect(
            host=os.environ.get("POSTGRES_HOST", "localhost"),
            port=int(os.environ.get("POSTGRES_PORT", "5432")),
            user=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"],
            database=os.environ["POSTGRES_DB"])
        try:
            return await coro_fn(conn)
        finally:
            await conn.close()
    return asyncio.run(_wrap())


def setup_schema() -> None:
    async def _s(conn: asyncpg.Connection):
        await conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        await conn.execute(f"CREATE SCHEMA {SCHEMA}")
        await conn.execute(f"CREATE TABLE {SCHEMA}.names (name text PRIMARY KEY)")
        await conn.execute(f"INSERT INTO {SCHEMA}.names SELECT name FROM maps.names")
        n = await conn.fetchval(f"SELECT count(*) FROM {SCHEMA}.names")
        return n
    n = run_db(_s)
    log_event("setup", f"throwaway schema {SCHEMA} seeded from real maps.names", count=n)
    print(f"  seeded {SCHEMA}.names with {n} real maps")


def teardown_schema() -> None:
    try:
        run_db(lambda c: c.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE"))
        # best-effort MinIO cleanup of the spike prefix
        objs = s3.list_objects_v2(Bucket=BUCKET, Prefix=PREFIX).get("Contents", [])
        for o in objs:
            s3.delete_object(Bucket=BUCKET, Key=o["Key"])
        print(f"\n  cleaned up schema {SCHEMA} and {len(objs)} MinIO object(s)")
    except Exception as e:  # noqa: BLE001 - best effort on shutdown
        print(f"  cleanup warning: {e}")


# --- request handlers ------------------------------------------------------
def list_maps() -> list[dict]:
    async def _q(conn: asyncpg.Connection):
        rows = await conn.fetch(f"SELECT name FROM {SCHEMA}.names ORDER BY name")
        return [r["name"] for r in rows]
    names = run_db(_q)
    have_banner = {o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET, Prefix=PREFIX).get("Contents", [])}
    return [{"name": n, "has_banner": banner_key(n) in have_banner} for n in names]


def add_map(name: str, banner_b64: str | None, content_type: str | None) -> dict:
    name = name.strip()
    if not name:
        return {"ok": False, "error": "Map name is required."}
    # 006: endpoint writes to the DB only (instant). ON CONFLICT keeps it idempotent.
    async def _ins(conn: asyncpg.Connection):
        return await conn.fetchval(
            f"INSERT INTO {SCHEMA}.names (name) VALUES ($1) "
            f"ON CONFLICT (name) DO NOTHING RETURNING name", name)
    inserted = run_db(_ins)
    uploaded = False
    if banner_b64:
        raw = base64.b64decode(banner_b64.split(",", 1)[-1])
        s3.put_object(Bucket=BUCKET, Key=banner_key(name), Body=raw,
                      ContentType=content_type or "image/png",
                      CacheControl="public, max-age=31536000, immutable")
        uploaded = True
    log_event("upload", f"added map {name!r}", inserted=bool(inserted),
              banner_uploaded=uploaded, key=banner_key(name))
    return {"ok": True, "name": name, "was_new": bool(inserted), "banner_uploaded": uploaded}


def autocomplete(q: str) -> list[str]:
    """Mirrors the bot's MapNameTransformer.autocomplete (DB-backed, fuzzy)."""
    async def _q(conn: asyncpg.Connection):
        rows = await conn.fetch(
            f"SELECT name FROM {SCHEMA}.names WHERE name ILIKE $1 ORDER BY name LIMIT 25",
            f"%{q}%")
        return [r["name"] for r in rows]
    res = run_db(_q)
    log_event("bot", f"autocomplete({q!r}) -> {len(res)} result(s)")
    return res


def submit_map(map_name: str) -> dict:
    """Simulate a map submission. 004: validate map_name at runtime against the DB."""
    import difflib
    async def _q(conn: asyncpg.Connection):
        return {r["name"] for r in await conn.fetch(f"SELECT name FROM {SCHEMA}.names")}
    known = run_db(_q)
    if map_name in known:
        log_event("submit", f"submission accepted for {map_name!r}")
        return {"ok": True, "message": f"Submission accepted — '{map_name}' is a known map."}
    sug = difflib.get_close_matches(map_name, known, n=3, cutoff=0.6)
    hint = f" Did you mean: {', '.join(sug)}?" if sug else ""
    log_event("submit", f"submission REJECTED for {map_name!r}")
    return {"ok": False, "message": f"'{map_name}' is not a known Overwatch map.{hint}"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence default noise
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(code, json.dumps(obj).encode(), "application/json")

    def do_GET(self) -> None:  # noqa: N802
        url = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(url.query)
        if url.path == "/":
            self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif url.path == "/api/maps":
            self._json(200, list_maps())
        elif url.path == "/api/autocomplete":
            self._json(200, autocomplete(qs.get("q", [""])[0]))
        elif url.path == "/api/banner":
            name = qs.get("name", [""])[0]
            try:
                obj = s3.get_object(Bucket=BUCKET, Key=banner_key(name))
                self._send(200, obj["Body"].read(), obj.get("ContentType", "image/png"))
            except Exception:  # noqa: BLE001
                self._json(404, {"error": "no banner"})
        elif url.path == "/api/log":
            self._json(200, EVENTS[-200:])
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        url = urllib.parse.urlparse(self.path)
        body = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
        data = json.loads(body or b"{}")
        if url.path == "/api/maps":
            self._json(200, add_map(data.get("name", ""), data.get("banner"),
                                    data.get("content_type")))
        elif url.path == "/api/submit":
            self._json(200, submit_map(data.get("map_name", "")))
        else:
            self._json(404, {"error": "not found"})


def main() -> None:
    print("=" * 70)
    print(" SPIKE 005 — upload-map-live")
    print("=" * 70)
    setup_schema()
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"\n  ▶ open http://localhost:{PORT}\n  (Ctrl-C to stop; schema + MinIO objects auto-cleaned)\n")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  shutting down ...")
    finally:
        httpd.server_close()
        teardown_schema()  # in finally (not atexit) so asyncio.run still works


if __name__ == "__main__":
    main()
