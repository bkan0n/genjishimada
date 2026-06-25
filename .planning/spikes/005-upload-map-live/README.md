---
spike: 005
name: upload-map-live
type: standard
validates: "Given a running server with no restart, when an admin POSTs a map name + banner image, then the banner lands in MinIO, the name lands in the DB, and all three surfaces (website read, map submission, bot autocomplete) reflect the new map live"
verdict: VALIDATED
related: [004, 006]
tags: [maps, ui, s3, upload, litestar-shaped]
---

# Spike 005: upload-map-live

## What This Validates

> **Given** a running server with **no restart**,
> **when** an admin POSTs a new map's name + banner image to one endpoint,
> **then** the banner lands in MinIO, the name lands in the DB, and **all three surfaces update
> live**: the website browse view renders it, a map submission with that name is accepted, and the
> bot-style autocomplete returns it.

This is the headline "feel the dream" spike. It composes the decisions from 004 (str + runtime
`maps.names` validation) and 006 (endpoint writes to the DB only; banner to object storage) into one
clickable demo, run against the **real** local Docker Postgres + MinIO.

## How to Run

```bash
# from this directory
uv run --env-file ../../../.env.local --with asyncpg --with boto3 python server.py
# then open http://localhost:8077  — Ctrl-C to stop (auto-cleans schema + MinIO objects)
```

Prereqs: `docker compose -f docker-compose.local.yml up -d postgres-local minio-local`.

**Isolation:** on startup it creates a throwaway `spike005` schema seeded from the real
`maps.names` (63 maps), and writes banners under a `spike005/` MinIO prefix. On Ctrl-C it drops the
schema and deletes those objects — the real data is never touched.

## What to Expect

1. **① Admin** — type a new map name, optionally pick any image as its banner, click *Upload map*.
2. **② Website read** — the browse grid (reads `SELECT name FROM maps.names`) instantly shows the
   new map, with its uploaded banner (served from MinIO) and an "uploaded ✓" badge; the card pulses.
3. **③ Map submission** — type the new name and *Submit*: accepted (runtime-validated against the
   DB). Type a typo: rejected with a "did you mean" suggestion.
4. **④ Bot autocomplete** — type part of the new name: it appears (mirrors the bot's DB-backed
   `MapNameTransformer.autocomplete`).

No process is restarted between steps — the map appears everywhere because every surface reads the
live DB. That is the whole feature, felt.

## Observability

A forensic event log (in-memory, ISO-timestamped, categorized: `setup` / `upload` / `submit` /
`bot`) is shown live in the page and served at `GET /api/log`. It records every endpoint hit with
metadata (inserted?, banner key, result counts) so the data flow is auditable while you click.

Endpoints: `GET /api/maps`, `POST /api/maps` (name + base64 banner), `GET /api/banner?name=`
(proxies MinIO — no public bucket policy needed), `GET /api/autocomplete?q=`, `POST /api/submit`,
`GET /api/log`.

## Investigation Trail

1. **Built the three surfaces over one live DB table.** All read `spike005.names`, so a single
   `INSERT` makes the map appear in all of them with no restart — proving "appears automatically."
2. **Banner serving via proxy, not public bucket.** First instinct was a public-read bucket policy
   so `<img>` could hit MinIO directly. Simpler and self-contained: a `GET /api/banner` endpoint
   fetches the object via boto3 and streams it. No CORS, no policy. Mirrors how the real app already
   has `get_map_banner()` deriving a CDN URL — here we prove the upload→store→serve loop.
3. **Smoke-tested every endpoint** (curl): baseline 63 maps; submit unknown → rejected with
   suggestions; POST a 1×1 PNG banner → inserted + stored; autocomplete finds it; submit accepts it;
   `GET /api/banner` returns 200 with bytes. All green.
4. **Teardown bug (surprise), fixed.** First cut cleaned up via `atexit` → on shutdown it raised
   `cannot schedule new futures after interpreter shutdown` (can't `asyncio.run` during interpreter
   teardown). Moved cleanup into `main()`'s `finally` (runs before shutdown). Re-verified: schema
   present during the run, dropped to 0 on Ctrl-C.

## Results

**VALIDATED.** One endpoint + three live-reading surfaces deliver automatic appearance with no
restart, against real infrastructure. Evidence: full curl smoke test passed; banner round-trips
through MinIO; submission validates at runtime per Spike 004; autocomplete mirrors the bot path;
verified clean teardown.

**Signal for the build:**
- The real implementation mirrors the **movement-tech content CMS** pattern (Controller → Service →
  Repository, `opt={"required_scopes": {"content:admin"}}`). Add `POST /api/v3/content/maps`
  taking name + banner (multipart in the real app via Litestar `UploadFile`, vs base64 here).
- Reuse the existing `ImageStorageService` upload pattern; store the banner under a stable
  `assets/map_banners/<sanitized>.png` key so the existing `get_map_banner()` derivation keeps
  working (or store the returned URL in a new `maps.names.banner_url` column — decide at plan time).
- Endpoint does: validate name non-empty → `INSERT INTO maps.names ON CONFLICT DO NOTHING` → upload
  banner. Submission/autocomplete already read the DB, so they need no change once the Literal is
  gone (Spike 004).
- The one bot spot still reading `get_args(OverwatchMap)` (moderator `MapNameSelect`) must switch to
  a DB/API-fed list — small, known cleanup (noted from the codebase exploration).
