---
phase: 12-overhaul-of-tournaments
plan: 01
subsystem: tournaments-db
tags: [migration, plpgsql, pg_cron, grid-time, outbox, fresh-restart]
requires: []
provides:
  - "tournaments.editions parent entity (shared grid-anchored timing)"
  - "tournaments.cycles.edition_id child FK"
  - "global cadence/anchor/transitions_paused/debug_cycle_seconds on tournaments.config"
  - "tournaments.next_grid_boundary() DST-correct grid helper"
  - "tournaments.process_edition_transitions() status-only flip (drift fix)"
  - "edition_rollover outbox row {results, started, edition_id}"
  - "fresh-restart wipe preserving core.completions PBs"
affects:
  - "12-02 (SDK TournamentRolloverEvent + edition structs)"
  - "12-03 (repo/service edition CRUD, global pause/debug, bootstrap snap)"
  - "12-04 (GET /editions/active read surface)"
tech-stack:
  added: []
  patterns:
    - "grid-time PL/pgSQL via AT TIME ZONE + EXTRACT(DOW) (DST-correct)"
    - "status-only cron flip under advisory lock 2025070100 (no now() into timestamps)"
    - "one combined outbox row keyed by edition_id"
    - "ordered row-level DELETE wipe (NOT TRUNCATE CASCADE) to honor ON DELETE SET NULL"
key-files:
  created:
    - apps/api/migrations/0024_tournament_editions_overhaul.sql
    - apps/api/tests/repository/tournaments/test_grid_boundary.py
    - apps/api/tests/repository/tournaments/test_edition_transitions.py
  modified:
    - apps/api/tests/repository/tournaments/conftest.py
    - apps/api/tests/integration/test_tournaments_schema.py
decisions:
  - "Single migration file 0024 (RESEARCH OQ2)"
  - "Outbox carries edition_rollover via nullable edition_id + nullable cycle_id + extended CHECK (A3a)"
  - "Wipe uses ordered DELETEs, not TRUNCATE CASCADE, to avoid structurally truncating core.completions"
metrics:
  duration: ~35m
  completed: 2026-06-01
  tasks: 3
  files: 5
---

# Phase 12 Plan 01: Tournament Editions Overhaul (DB Foundation) Summary

Migration 0024 introduces the single-edition grid-anchored tournament model: a
`tournaments.editions` parent entity owning one shared `started_at`/`ends_at`,
global cadence/anchor/pause/debug config, a DST-correct `next_grid_boundary()`
helper, and a rewritten `process_edition_transitions()` that flips status only and
chains `next.started_at = prev.ends_at` (never `now()`) — eliminating the
cross-category drift bug at its root. Plus the Wave 0 test scaffolds proving
drift-immunity, grid-boundary/DST correctness, hiatus semantics, and a
PB-preserving fresh-restart wipe.

## What Was Built

- **`tournaments.editions`** (D-05): `id`/`started_at`/`ends_at`/`status`/`created_at`,
  status CHECK `('active','completed')`, indexes on status + ends_at. Child link
  `tournaments.cycles.edition_id` (FK ON DELETE CASCADE) + index (D-01).
- **Global config columns** on the `tournaments.config` singleton (D-02/03/06/07):
  `cadence`, `anchor_weekday` (EXTRACT(DOW) 0=Sun..6=Sat), `anchor_time`,
  `anchor_tz` (service-validated, not CHECK), `transitions_paused`,
  `debug_cycle_seconds`. Per-category `cycle_frequency`/`transitions_paused`/
  `debug_cycle_seconds` migrated to global then dropped.
- **Outbox schema** for the combined event (A3a): nullable `cycle_id`, new nullable
  `edition_id` FK, `event_type` CHECK extended to include `edition_rollover`.
- **`next_grid_boundary()`** (D-06/D-07): wall-clock composition via `AT TIME ZONE`
  for DST correctness; steps one period if the candidate is already past.
- **`process_edition_transitions()`** (D-01/05/08/12): advisory lock `2025070100`,
  detects the single active edition past `ends_at`, finalizes child cycles with the
  verbatim tier-then-time RANK() snapshot, flips edition status, creates the next
  edition inheriting `started_at = prev.ends_at` (NO `now()`), pre-rolls one child
  cycle per active category via `select_eligible_map`, and writes ONE
  `edition_rollover` outbox row with payload `{results, started, edition_id}`.
  `transitions_paused` suppresses the next edition (hiatus).
- **Fresh-restart wipe** (D-13/14/15): NULL `core.completions.tournament_completion_id`
  first, then ordered row-level DELETEs of completions → cycles → editions →
  pending_transitions.
- **Idempotent pg_cron re-registration** guarded on `pg_extension` (test DBs no-op),
  job name retained, pointing at `process_edition_transitions()`.
- **Wave 0 tests**: `test_grid_boundary.py` (5 cases incl. spring-forward DST),
  `test_edition_transitions.py` (`drift`, `single_edition`, `hiatus`), conftest
  fixtures (`set_global_config`, `create_test_edition`, `create_test_child_cycle`,
  `advance_past_ends_at`, `simulate_late_cron`), and `test_tournaments_schema.py`
  `overhaul` + `preserve_pbs` cases.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fresh-restart wipe destroyed core.completions PBs via TRUNCATE CASCADE**
- **Found during:** Task 2 (preserve_pbs test failed: core row count 0, expected 1).
- **Issue:** `TRUNCATE tournaments.completions ... CASCADE` structurally truncates
  `core.completions` because it has an FK into `tournaments.completions` — TRUNCATE
  CASCADE ignores per-row `ON DELETE SET NULL`, so it deleted the PB rows the wipe
  is required to preserve (violates D-15 / T-12-01).
- **Fix:** Replaced the single `TRUNCATE ... CASCADE` with ordered row-level
  `DELETE FROM` (completions → cycles → editions). Row-level DELETE honors
  `ON DELETE SET NULL`, so deleting tournament completions only NULLs the
  (already-NULLed) core link and never deletes a `core.completions` row.
- **Files modified:** `apps/api/migrations/0024_tournament_editions_overhaul.sql`
- **Commit:** be742dc

**2. [Rule 3 - Blocking] Stale conftest `create_test_category` fixture inserted dropped column**
- **Found during:** Task 0 (the new tests depend on this fixture).
- **Issue:** The shared fixture inserted `cycle_frequency`, which migration 0024
  drops; every new edition test would fail at fixture setup.
- **Fix:** Removed `cycle_frequency` from the fixture INSERT and silently drop any
  stale override.
- **Files modified:** `apps/api/tests/repository/tournaments/conftest.py`
- **Commit:** ebf4509

**3. [Rule 1 - Bug] Table-count assertion broke on the new editions table**
- **Found during:** wave-merge full-suite run.
- **Issue:** `test_tournaments_tables_exist` asserted exactly 7 tables; 0024 adds
  `editions` (8).
- **Fix:** Added `editions` to the expected set (in-scope: same file this plan owns).
- **Files modified:** `apps/api/tests/integration/test_tournaments_schema.py`
- **Commit:** f25c15f

### Test-isolation refinements (not plan deviations)
The edition-transition tests were made robust against the session-scoped shared
test DB by selecting the rolled-over edition via the chain key
(`next.started_at == prev.ends_at`) and ticking the fn until the target edition is
finalized, rather than assuming a single global active edition.

## Deferred Issues (out of scope — owned by downstream plans)

The overhaul intentionally drops per-category columns and replaces the old
transition function, leaving 11 pre-existing tests asserting the OLD model stale.
They are NOT in this plan's `files_modified` and depend on SDK/repo/service
rewrites scheduled for 12-02/12-03. Logged in
`.planning/phases/12-overhaul-of-tournaments/deferred-items.md`:
- `test_cycle_transitions.py` (all) — old `process_cycle_transitions` + `cycle_frequency`
- `test_lifecycle_control.py::TestSetCategoryPaused`/`TestSetCategoryDebugCycleSeconds` — per-category pause/debug repo methods
- `test_tournaments_repository.py::TestCreateCategory` — `create_category` still references `cycle_frequency`

## Authentication Gates

None.

## Verification

- Source gates: `started_at = now()` → 0; `'started'` key → 1; `'next'` key → 0;
  `UPDATE core.completions ... = NULL` precedes the wipe DELETEs.
- Targeted suite (grid + edition + schema, all selectors): **13 passed**.
- `test_tournaments_schema.py` full file: **15 passed**.
- Behavior proven: drift-immune under late cron (next.started_at == prev.ends_at),
  one-edition-per-rollover with one child per active category, hiatus
  (results-only, no next edition), DST-preserving grid boundary, PB preservation
  with NULLed FK.

## Self-Check: PASSED
