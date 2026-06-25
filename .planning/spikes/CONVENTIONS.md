# Spike Conventions

Patterns and stack choices established across the skill-score spike session. New spikes follow these
unless the question requires otherwise.

## Stack

- **Language:** Python 3.13 (project standard). Spikes are plain stdlib + `asyncpg` only.
- **DB access:** real local Docker Postgres (`docker-compose.local.yml`, imported from VPS), reached
  via `asyncpg.connect()` reading `POSTGRES_*` from `.env.local`. Run with
  `uv run --env-file .env.local --with asyncpg python <script>`. Never hardcode credentials.
- **No ORM, raw SQL** — mirrors the real codebase. CTE + window-function style.
- **UI spikes:** stdlib `http.server` (`ThreadingHTTPServer`) + a single vanilla-JS `index.html`.
  No framework, no build step, no npm. Port 8077.
- **Object storage spikes:** real local MinIO from `docker-compose.local.yml` via `boto3`
  (`endpoint_url=http://localhost:9000`, key/secret `genji` / `local_dev_password`, bucket
  `genji-parkour-images`). Pulled transiently via `uv run --with boto3`.

## Structure

- One directory per spike: `.planning/spikes/NNN-name/` with a `README.md` (YAML frontmatter) and code.
- **Data handoff between spikes via JSON.** Spike 001 exports `skill_inputs.json` (one DB read);
  002 and 003 consume it — no spike re-queries the DB. The expensive read happens once.
- **Scorer is a single shared module** (`002/score.py`). 003's server imports it via `sys.path`
  rather than duplicating logic — the scorer has exactly one source of truth.
- **Distributable bundles** go in `NNN-name/dist/<bundle>/` and zip to a flat, dependency-free
  folder (data baked in, sibling-path imports flattened, `python3 <entry>.py` is the only step).

## Patterns

- **Verify schema semantics against ground truth, never a summary.** The `completion` flag's meaning
  (verification depth, not practice-vs-real) was misread by an exploration agent and only caught by
  counting rows + reading the migration COMMENT and the real repo SQL. Always confirm load-bearing
  assumptions directly.
- **Re-center on signal density.** Pick scoring inputs by how much of the data they cover
  (difficulty 100%, time-percentile 99.6%) over what sounds good but is sparse (leaderboard rank
  236 runs, medals 90 maps). Sparse signals are *bonus layers*, never the backbone.
- **Diminishing returns via `Σ s_i / i**gamma`** over a player's descending-sorted per-map scores.
  `gamma` is the anti-farm dial; always expose it as the headline knob and demonstrate break-even.
- **Make the abstract felt.** Farming resistance is proved by assertions (002) *and* made tangible
  by a live slider that lets a human watch farm profiles climb at gamma=0 and sink as it rises (003).
- **Validate "feel" with a real domain expert**, not just self-assertion — ship a standalone bundle,
  collect their tuned weights, adopt as defaults.
- **Throwaway-schema isolation for spikes that WRITE.** When a spike must mutate the DB (inserts,
  ALTERs), never touch the real tables. Either (a) wrap everything in a transaction that is
  rolled back (read-only-ish probes, FK tests), or (b) `CREATE SCHEMA spikeNNN`, seed it from the
  real table (`INSERT ... SELECT FROM maps.names`), work there, and `DROP SCHEMA ... CASCADE` at the
  end. Established in 004 (rollback) and 005/006 (throwaway schema).
- **Proxy object storage through the spike server.** To render MinIO objects in the browser, add a
  `GET /api/banner?...` endpoint that fetches via boto3 and streams the bytes — avoids public-bucket
  policies and CORS. (Spike 005.)
- **Sync HTTP handler + asyncpg:** wrap each DB call in a `run_db(fn)` helper that does
  `asyncio.run(connect → fn → close)`. Fine for a low-traffic spike; no pool needed.
- **Use the REAL framework when the question is about the framework's own behaviour.** The stdlib
  `http.server` default is for spikes about *our* logic. When the spike asks "how does Litestar/X
  decode/behave?" (Spike 007: mixed multipart `Struct + UploadFile`), run real Litestar
  (`uv run --with 'litestar[standard]'` — ships uvicorn) and POST to it; empirical framework behaviour
  beats reading docs. Document the deviation in the README. Everything else still follows conventions
  (real PG/MinIO, throwaway schema, forensic log).
- **Port the real code verbatim, swap only the variable under test.** Spike 008 copied
  `MapNameSelect`'s pagination math line-for-line and changed only the *source* of `all_maps`
  (Literal → DB). The spike then proves the swap is behaviour-preserving, and the diff for the real
  build is unmistakable (one line).
- **Probe real-shaped inputs, not toy ones.** The decisive Spike 007 finding (banner-key collision)
  only surfaced by feeding *actual* map-name shapes — apostrophes (`King's Row`) and accents
  (`Château Guillard`) — through the derivation. Always test with values that look like production data.

## Tools & Libraries

- `asyncpg` (already a project dep) — DB reads/writes. Pulled transiently via `uv run --with asyncpg`.
- `msgspec` (project dep) — when a spike needs to reproduce request decode/validation behaviour.
- `boto3` (project dep) — S3/MinIO object storage. `uv run --with boto3`.
- stdlib only for everything else (`http.server`, `json`, `base64`, `difflib`, `dataclasses`,
  `webbrowser`, `zipfile`/`zip`).
- Compose multiple: `uv run --env-file .env.local --with asyncpg --with boto3 --with msgspec python …`
- **Avoid:** ORMs, web frameworks, JS build tooling, Docker-for-spikes. None were needed.

## Gotchas

- `rank() OVER (...) FILTER (WHERE ...)` is invalid in Postgres — `FILTER` is aggregate-only. Rank a
  filtered set in its own CTE and join back.
- Fish/zsh: `$UID` is read-only (don't assign to it); bare `(...)`/glob substitutions can error —
  prefer Python helpers or `uv run` scripts over shell command-substitution for DB work.
- Map `time` values are not comparable across maps (different units/lengths). Always score on
  *relative* time (percentile vs the map's field), never raw seconds.
- **A caught constraint error aborts the whole Postgres transaction** (`InFailedSQLTransactionError`
  on the next statement). To catch-and-continue, wrap the fallible statement in a SAVEPOINT
  (`async with conn.transaction():` nested). (Spike 004.)
- **`asyncio.run()` cannot run inside an `atexit` handler** (`cannot schedule new futures after
  interpreter shutdown`). Do spike DB teardown in `main()`'s `finally`, not `atexit`. (Spike 005.)
- **`uv run python …` parent PID ≠ the python child.** To stop a backgrounded spike server
  gracefully, SIGINT the listener PID (`lsof -ti tcp:8077`), not the `uv` wrapper PID — otherwise the
  `finally`/cleanup never runs. Run with `python -u` so logs flush before exit.
