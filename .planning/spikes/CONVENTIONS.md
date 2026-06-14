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

## Tools & Libraries

- `asyncpg` (already a project dep) — DB reads. Pulled transiently via `uv run --with asyncpg`.
- stdlib only for everything else (`http.server`, `json`, `dataclasses`, `webbrowser`, `zipfile`/`zip`).
- **Avoid:** ORMs, web frameworks, JS build tooling, Docker-for-spikes. None were needed.

## Gotchas

- `rank() OVER (...) FILTER (WHERE ...)` is invalid in Postgres — `FILTER` is aggregate-only. Rank a
  filtered set in its own CTE and join back.
- Fish/zsh: `$UID` is read-only (don't assign to it); bare `(...)`/glob substitutions can error —
  prefer Python helpers or `uv run` scripts over shell command-substitution for DB work.
- Map `time` values are not comparable across maps (different units/lengths). Always score on
  *relative* time (percentile vs the map's field), never raw seconds.
