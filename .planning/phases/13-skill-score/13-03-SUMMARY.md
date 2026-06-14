---
phase: 13-skill-score
plan: 03
subsystem: skill-score
tags: [repository, asyncpg, raw-sql, skill, port]
requires:
  - "skill.snapshot (lean per-player table) — for fetch_snapshot/replace_snapshot"
  - "skill.weight_config (single-row typed config) — for fetch_weights/update_weights"
  - "spike 001 input query (best->field->video_ranked->fully) — port source"
provides:
  - "SkillRepository (input query port + snapshot read/upsert + weights read/write)"
  - "provide_skill_repository DI provider"
  - "SKILL_INPUT_QUERY module constant (verbatim spike port)"
affects:
  - "apps/api/repository"
tech-stack:
  added: []
  patterns:
    - "BaseRepository subclass with self._get_connection(conn) optional-conn idiom"
    - "Verbatim spike SQL port into a module-level triple-quoted constant"
    - "Transactional bulk replace via acquire-if-Pool + conn.transaction() + executemany"
    - "Allow-listed dynamic UPDATE SET clause built from a frozenset (no caller column names)"
key-files:
  created:
    - apps/api/repository/skill_repository.py
  modified: []
decisions:
  - "fetch_skill_inputs drops suspicious rows in Python (mirrors spike harness query.py:105-106), not in SQL — keeps the SQL a verbatim port and the exclusion explicit at the boundary."
  - "replace_snapshot follows the tags_repository acquire-if-Pool transaction pattern (a bare Pool has no .transaction()); acquires a connection from the pool when no conn is injected, else participates in the caller's transaction."
  - "update_weights builds its SET clause exclusively from the _WEIGHT_COLUMNS frozenset allow-list (T-13-07); values bound positionally; empty/all-unknown update returns the current row unchanged."
  - "fetch_weights/update_weights/fetch_snapshot guard the asyncpg Record|None return with `dict(row) if row else ...` for type-clean reads."
metrics:
  duration: "~2.5m"
  completed: 2026-06-12
  tasks: 2
  files: 1
---

# Phase 13 Plan 03: Skill Repository (Data-Access Layer) Summary

`apps/api/repository/skill_repository.py` — the only place raw SQL for skill lives.
Ports the spike's 4-CTE input query (`best → field → video_ranked → fully`) verbatim
into `fetch_skill_inputs`, and adds the lean-snapshot read/bulk-upsert plus the
single-row weight config read/write, all on Genji's `BaseRepository` + `$1,$2`
positional-param conventions.

## What Was Built

**`SkillRepository(BaseRepository)`** with five async methods + a `provide_skill_repository`
DI provider (mirroring `community_repository.py:720`):

1. **`fetch_skill_inputs`** — runs the module-level `SKILL_INPUT_QUERY` (a verbatim port
   of `sources/001-skill-input-query/query.py:24-92`) and returns one fastest verified,
   non-legacy run per `(user, map)` as dicts, with **suspicious rows filtered out in
   Python** (`if not row["suspicious"]`, mirroring the spike harness). Every load-bearing
   gotcha is preserved in the SQL:
   - eligibility WHERE in `best`: `c.verified = TRUE AND c.legacy = FALSE AND
     m.archived = FALSE AND m.code IS NOT NULL`, with `DISTINCT ON (c.user_id, c.map_id)
     ORDER BY c.user_id, c.map_id, c.time ASC`.
   - a distinct `video_ranked` CTE (ranks only `completion = FALSE` rows) LEFT JOINed
     back — **no** `rank() OVER (...) FILTER (...)` window construct (FILTER-is-aggregate-only).
   - emits `raw_difficulty::float8` (never the text tier) and `time_pct`
     (`percent_rank() ... ORDER BY time DESC`, 1.0 = fastest) — never raw time across maps.
   - computed `medal` CASE, `has_medal_thresholds`, and the `suspicious` EXISTS column.

2. **`fetch_snapshot(user_id)`** — `SELECT * FROM skill.snapshot WHERE user_id = $1`,
   returns the row as a dict or `None`; `breakdown` jsonb decodes to a Python list via
   the app codec (D-06).

3. **`replace_snapshot(rows)`** — atomic lean-snapshot replace (D-04/D-07): inside one
   `conn.transaction()`, `TRUNCATE skill.snapshot` then `executemany` bulk-insert the
   supplied rows. An empty list leaves the snapshot empty (truncate only) without error.
   Uses the acquire-if-`Pool` pattern so it works both standalone and inside a caller's
   transaction.

4. **`fetch_weights()`** — selects exactly the nine weight columns from the single
   `skill.weight_config` row (SPEC req 5: the only source of weights).

5. **`update_weights(weights)`** — partial PATCH (D-10): builds the SET clause from the
   `_WEIGHT_COLUMNS` allow-list (T-13-07), binds values positionally, RETURNs the full
   updated row; an empty/all-unknown update returns the current row unchanged.

## Verification Performed

- **Task 1 `<automated>`:** AST check — `SkillRepository`, `fetch_skill_inputs`,
  `provide_skill_repository` all present; SQL contains `video_ranked` and `percent_rank`,
  `raw_difficulty::float8`; **no `FILTER` before the first `SELECT`** (the
  FILTER-is-aggregate-only gotcha respected — the only `FILTER` is the legitimate
  `max(...) FILTER (WHERE owu.is_primary)` aggregate in the final SELECT). Printed `ok`.
- **Task 2 `<automated>`:** AST check — `fetch_snapshot`, `replace_snapshot`,
  `fetch_weights`, `update_weights` all present. Printed `ok`.
- **Lint:** `just lint-api` clean after each task (ruff format / ruff check: all passed /
  basedpyright: 0 errors).
- **Human-check (deferred):** the behavioral checks against a seeded test DB (one row per
  (user,map); excluded rows absent; `time_pct=1.0` for each field-fastest; weights
  round-trip; partial `update_weights`) require the migrated spike-fixture DB, which is
  not wired into this repository-only plan — they are exercised end-to-end by the
  SkillService plan (13-04) and its integration tests.

## Deviations from Plan

None — plan executed exactly as written.

Two small implementation choices the plan left to convention (not deviations):
- **Suspicious-row drop location:** kept in Python (per the plan `<action>` and the spike
  harness) rather than in SQL, so `SKILL_INPUT_QUERY` stays a verbatim port.
- **`replace_snapshot` transaction shape:** a bare `Pool` has no `.transaction()`, so the
  method follows the established `tags_repository.py:379-383` acquire-if-`Pool` pattern
  (the plan said "inside a single transaction" without prescribing the acquire mechanics).
  The `noqa` initially added on the dynamic UPDATE was removed — the relevant rule (S608)
  is not enabled in this project, and ruff flagged the directive as unused.

## Acceptance Criteria

- [x] `SkillRepository(BaseRepository)`, `fetch_skill_inputs`, `provide_skill_repository` exist.
- [x] SQL has a distinct `video_ranked` CTE and uses `percent_rank()` for `time_pct`; no `rank() OVER (...) FILTER (...)`.
- [x] SQL emits `raw_difficulty::float8` and `time_pct` (never raw time across maps).
- [x] Eligibility WHERE is exactly `verified=TRUE AND legacy=FALSE AND archived=FALSE AND code IS NOT NULL`; suspicious dropped in the Python post-filter.
- [x] `fetch_snapshot`, `replace_snapshot`, `fetch_weights`, `update_weights` exist.
- [x] `replace_snapshot` is one transaction (TRUNCATE + bulk insert); empty list is empty-safe.
- [x] `fetch_weights` returns exactly the 9 weight columns; `update_weights` is allow-listed + partial.
- [x] `just lint-api` clean.

## Self-Check: PASSED

- FOUND: apps/api/repository/skill_repository.py
- FOUND commit: 542c810 (Task 1 — SkillRepository + input query port)
- FOUND commit: ab6b981 (Task 2 — snapshot + weights read/write)
