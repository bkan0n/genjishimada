"""Spike 008 — moderator MapNameSelect sourced from the live DB instead of the Literal.

The one bot spot the Literal removal would silently break: the moderator map-edit wizard's
`MapNameSelect` (apps/bot/extensions/moderator.py:756-779) builds its paginated dropdown from
`get_args(OverwatchMap)`. After the Literal is dropped (Spike 004), that dropdown would either be
empty/stale or — worse — never show dynamically-added maps. It must source the FULL sorted list from
the DB, 25/page (Discord's option cap), with no bot restart.

This spike reproduces the EXACT pagination math from the real `MapNameSelect.__init__`, but fed from
`SELECT name FROM <schema>.names ORDER BY name` instead of `get_args(OverwatchMap)`. It then inserts
a new map mid-session and proves the dropdown picks it up on the next render — no restart — including
when the new name spills onto a brand-new page.

It also confirms the API gap: there is **no** full-list names endpoint today. `/utilities/autocomplete/names`
requires a `search` arg, is similarity-ordered, defaults to `limit=5`, and returns `list[OverwatchMap]`
(Literal-typed) — unusable as a full paginated source. A new endpoint must be added.

Follows CONVENTIONS: stdlib http.server (port 8077), real local Postgres via asyncpg, throwaway
`spike008` schema seeded from `maps.names`, cleanup in main()'s finally (never atexit), run_db helper.

Run:
    uv run --env-file ../../../.env.local --with asyncpg python -u server.py
Then open http://localhost:8077  (Ctrl-C to stop — auto-drops the schema).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import signal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

import asyncpg

PG = {
    "host": os.environ.get("POSTGRES_HOST", "localhost"),
    "port": int(os.environ.get("POSTGRES_PORT", "5432")),
    "user": os.environ["POSTGRES_USER"],
    "password": os.environ["POSTGRES_PASSWORD"],
    "database": os.environ["POSTGRES_DB"],
}
SCHEMA = "spike008"
PORT = 8077

# Verbatim from apps/bot/extensions/moderator.py:461
_PAGINATED_SELECT_PAGE_SIZE = 25

EVENTS: list[dict[str, Any]] = []


def log_event(category: str, message: str, **meta: Any) -> None:
    EVENTS.append(
        {"ts": dt.datetime.now(dt.timezone.utc).isoformat(), "category": category, "message": message, **meta}
    )
    print(f"[{category}] {message} {meta if meta else ''}", flush=True)


def run_db(fn: Callable[[asyncpg.Connection], Any]) -> Any:
    """Convention: wrap each DB call in connect → fn → close (sync handler + asyncpg)."""

    async def _run() -> Any:
        conn = await asyncpg.connect(**PG)
        try:
            return await fn(conn)
        finally:
            await conn.close()

    return asyncio.run(_run())


# ---------------------------------------------------------------------------
# THE port under test: MapNameSelect.__init__ pagination, but DB-fed.
# Compare to the real code:
#     all_maps = list(get_args(OverwatchMap)); all_maps.sort()        # <- static Literal
#     start = page * SIZE; end = start + SIZE; page_maps = all_maps[start:end]
#     total_pages = (len(all_maps) + SIZE - 1) // SIZE
# Here `all_maps` comes from the live DB instead.
# ---------------------------------------------------------------------------
def build_select_page(all_maps: list[str], page: int) -> dict[str, Any]:
    all_maps = sorted(all_maps)  # mirror MapNameSelect's all_maps.sort()
    start_idx = page * _PAGINATED_SELECT_PAGE_SIZE
    end_idx = start_idx + _PAGINATED_SELECT_PAGE_SIZE
    page_maps = all_maps[start_idx:end_idx]
    total_pages = (len(all_maps) + _PAGINATED_SELECT_PAGE_SIZE - 1) // _PAGINATED_SELECT_PAGE_SIZE
    return {
        "options": page_maps,  # SelectOption(label=m, value=m) for m in page_maps
        "placeholder": f"Select map name (page {page + 1})...",
        "page": page,
        "total_pages": total_pages,
        "total_maps": len(all_maps),
    }


def fetch_names() -> list[str]:
    return run_db(lambda c: _fetch_names(c))


async def _fetch_names(c: asyncpg.Connection) -> list[str]:
    rows = await c.fetch(f"SELECT name FROM {SCHEMA}.names ORDER BY name")
    return [r["name"] for r in rows]


class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:  # silence default access log
        pass

    def do_GET(self) -> None:
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/":
            self._send(200, INDEX_HTML.encode(), "text/html")
        elif u.path == "/api/select":
            page = int(q.get("page", ["0"])[0])
            names = fetch_names()
            page_data = build_select_page(names, page)
            log_event("select", "rendered dropdown page (DB-fed)", page=page, shown=len(page_data["options"]), total=page_data["total_maps"])
            self._send(200, json.dumps(page_data).encode())
        elif u.path == "/api/log":
            self._send(200, json.dumps(EVENTS[-50:]).encode())
        else:
            self._send(404, b'{"error":"not found"}')

    def do_POST(self) -> None:
        u = urlparse(self.path)
        if u.path == "/api/add":
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            name = (payload.get("name") or "").strip()
            if not name:
                self._send(400, b'{"ok":false,"error":"name required"}')
                return
            result = run_db(lambda c: c.execute(f"INSERT INTO {SCHEMA}.names (name) VALUES ($1) ON CONFLICT DO NOTHING", name))
            inserted = result.endswith("1")
            log_event("add", "inserted map into live DB (no restart)", name=name, inserted=inserted)
            self._send(200, json.dumps({"ok": True, "name": name, "inserted": inserted}).encode())
        else:
            self._send(404, b'{"error":"not found"}')


INDEX_HTML = """<!doctype html><html><head><meta charset=utf-8><title>Spike 008 — moderator dropdown</title>
<style>
 body{font:14px/1.5 system-ui;margin:0;background:#0e1116;color:#e6edf3}
 header{padding:18px 24px;background:#161b22;border-bottom:1px solid #30363d}
 h1{margin:0;font-size:18px}.sub{color:#8b949e;font-size:13px;margin-top:4px}
 main{padding:24px;max-width:720px;margin:auto}
 .card{background:#161b22;border:1px solid #30363d;border-radius:10px;padding:18px;margin-bottom:20px}
 .disc{background:#313338;border-radius:8px;padding:14px;border:1px solid #232428}
 .disc .ph{color:#b5bac1;font-size:12px;margin-bottom:6px}
 select{width:100%;padding:9px;background:#1e1f22;border:1px solid #111;border-radius:4px;color:#dbdee1;font-size:14px}
 .nav{display:flex;justify-content:space-between;margin-top:10px}
 button{padding:8px 14px;background:#5865f2;border:0;border-radius:4px;color:#fff;font-weight:600;cursor:pointer}
 button:disabled{background:#3a3c43;cursor:not-allowed}
 input{padding:8px;background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#e6edf3;width:60%}
 .meta{color:#8b949e;font-size:12px;margin-top:8px}
 pre{background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:10px;max-height:200px;overflow:auto;font-size:11px}
 .add button{background:#248636}
</style></head><body>
<header><h1>Spike 008 · moderator MapNameSelect, DB-fed</h1>
<div class=sub>The real dropdown reads <code>get_args(OverwatchMap)</code>. Here it reads the live <code>maps.names</code> — add a map and watch it appear, no restart.</div></header>
<main>
 <div class=card>
  <b>Moderator map-name dropdown (mirrors MapEditWizard, 25/page)</b>
  <div class=disc style=margin-top:12px>
   <div class=ph id=ph></div>
   <select id=sel size=10></select>
   <div class=nav>
     <button id=prev onclick=go(-1)>◀ Previous</button>
     <span class=meta id=pageinfo></span>
     <button id=next onclick=go(1)>Next ▶</button>
   </div>
  </div>
  <div class=meta id=total></div>
 </div>
 <div class="card add">
  <b>Add a new map to the live DB (no bot restart)</b><br><br>
  <input id=name placeholder="e.g. Aatlis  (or 'ZZZ Edge Map' to force a new last page)">
  <button onclick=add()>Insert →</button>
  <div class=meta id=addres></div>
 </div>
 <div class=card><b>Forensic log</b><pre id=log></pre></div>
</main>
<script>
let page=0,totalPages=1;
async function render(){
 const d=await (await fetch('/api/select?page='+page)).json();
 totalPages=d.total_pages;
 document.getElementById('ph').textContent=d.placeholder;
 document.getElementById('sel').innerHTML=d.options.map(m=>`<option>${m}</option>`).join('');
 document.getElementById('pageinfo').textContent=`page ${d.page+1} / ${d.total_pages}`;
 document.getElementById('total').textContent=`${d.total_maps} maps total · ${d.options.length} on this page`;
 document.getElementById('prev').disabled=page<=0;
 document.getElementById('next').disabled=page>=totalPages-1;
 refreshLog();
}
function go(dir){page=Math.max(0,Math.min(totalPages-1,page+dir));render();}
async function add(){
 const name=document.getElementById('name').value;
 const r=await (await fetch('/api/add',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name})})).json();
 document.getElementById('addres').textContent=r.ok?`✓ inserted=${r.inserted} — '${r.name}' now live. Navigate to find it (no restart).`:('✗ '+r.error);
 render();
}
async function refreshLog(){
 const log=await (await fetch('/api/log')).json();
 document.getElementById('log').textContent=log.map(e=>`${e.ts.slice(11,19)} [${e.category}] ${e.message} ${JSON.stringify(Object.fromEntries(Object.entries(e).filter(([k])=>!['ts','category','message'].includes(k))))}`).join('\\n');
}
render();
</script>
</body></html>"""


async def setup() -> int:
    conn = await asyncpg.connect(**PG)
    try:
        await conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        await conn.execute(f"CREATE SCHEMA {SCHEMA}")
        await conn.execute(f"CREATE TABLE {SCHEMA}.names (name text PRIMARY KEY)")
        await conn.execute(f"INSERT INTO {SCHEMA}.names (name) SELECT name FROM maps.names ON CONFLICT DO NOTHING")
        return await conn.fetchval(f"SELECT count(*) FROM {SCHEMA}.names")
    finally:
        await conn.close()


async def teardown() -> None:
    conn = await asyncpg.connect(**PG)
    try:
        await conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
    finally:
        await conn.close()


def main() -> None:
    count = asyncio.run(setup())
    log_event("setup", f"{SCHEMA}.names seeded from maps.names", rows=count)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    stop = signal.SIGINT

    def _shutdown(*_: Any) -> None:
        raise KeyboardInterrupt

    signal.signal(stop, _shutdown)
    print(f"\n→ Spike 008 on http://localhost:{PORT}  (Ctrl-C to stop, auto-cleans)\n", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        asyncio.run(teardown())
        log_event("teardown", f"dropped schema {SCHEMA}")


if __name__ == "__main__":
    main()
