---
phase: 15-dynamic-overwatch-map-management
plan: 02
subsystem: database
tags: [postgres, asyncpg, migration, foreign-key, idempotent-seed, pytest, durability]

# Dependency graph
requires:
  - phase: 15-01
    provides: "OverwatchMap aliased to str + the 70 verbatim map names captured in 15-01-SUMMARY (canonical seed set)"
provides:
  - "Migration 0032: core.maps.map_name -> maps.names.name FK (ON UPDATE CASCADE) with a loud orphan pre-flight (REQ-11/D-11)"
  - "Idempotent ON CONFLICT DO NOTHING maps.names seed in 0001_init.sql, one block of all 70 reconciled names (REQ-12/D-09)"
  - "7 phantom Literal-only maps reconciled into maps.names — present after a fresh from-migrations apply (REQ-13/D-08)"
  - "scripts/export_map_names_seed.py — standalone on-demand seed export, unreferenced by app code (REQ-14/D-10)"
  - "0003_stadium_maps_1.sql made idempotent (latent duplicate-PK bug fixed by the seed rewrite)"
affects: [15-03 (FK backstops the runtime maps.names validation that replaces the lost enum gate), 15-04, 15-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Idempotent seed: one INSERT ... VALUES (...) ON CONFLICT DO NOTHING block replaces N plain INSERTs — replay-safe, fresh-bootstrap parity"
    - "Migration FK with orphan pre-flight: reconcile-known-rows -> DO $$ RAISE EXCEPTION on orphans -> ADD CONSTRAINT (fail loud, never silently skip)"
    - "core.maps.map_name FK mirrors the existing maps.mastery.map_name FK shape (REFERENCES maps.names (name) ON UPDATE CASCADE)"

key-files:
  created:
    - apps/api/migrations/0032_dynamic_map_management.sql
    - scripts/export_map_names_seed.py
    - apps/api/tests/integration/test_map_management_schema.py
  modified:
    - apps/api/migrations/0001_init.sql
    - apps/api/migrations/0003_stadium_maps_1.sql
    - apps/api/tests/integration/test_tournaments_schema.py

key-decisions:
  - "Sourced the 70 seed names from 15-01-SUMMARY and verified by set-equality that they equal (old 63 seed names) ∪ (7 phantom maps) — exact, no drift."
  - "Made 0003_stadium_maps_1.sql idempotent (it pre-seeded 6 of the 7 phantoms with plain INSERTs) — required, or the rewritten 0001 seed makes a fresh apply raise duplicate-PK at 0003."
  - "Fixed the 4 tournaments-schema tests that inserted fictional core.maps.map_name values by seeding the name into maps.names first — the new FK correctly rejected them; keeps the tests' map-row intent intact."
  - "FK introspection asserts pg_constraint.confupdtype == b'c' (asyncpg returns the Postgres \"char\" column as a byte)."

patterns-established:
  - "Pattern 1: When making a long-lived seed idempotent, audit ALL later migrations that re-insert the same rows — non-idempotent downstream INSERTs become duplicate-PK failures once the canonical seed includes their rows."
  - "Pattern 2: A new FK on an existing column surfaces every test fixture that used a fictional value for that column; those are in-scope to fix (directly caused by the FK)."

requirements-completed: [REQ-11, REQ-12, REQ-13, REQ-14, D-08, D-09, D-10, D-11]

# Metrics
duration: 11min
completed: 2026-06-26
---

# Phase 15 Plan 02: Map-Names Durability & Integrity Summary

**Idempotent `ON CONFLICT` seed of all 70 reconciled map names in `0001_init.sql` plus migration `0032`'s orphan-guarded `core.maps.map_name → maps.names.name` FK — giving the now-dynamic `maps.names` table replay-safe bootstrap parity and a DB backstop for the runtime validation that replaces the dropped `OverwatchMap` Literal.**

## Performance

- **Duration:** ~11 min
- **Started:** 2026-06-26T02:21:05Z
- **Completed:** 2026-06-26T02:31:19Z
- **Tasks:** 3
- **Files modified:** 6 (3 created, 3 modified)

## Accomplishments

- Collapsed the 63 separate `INSERT INTO maps.names (name) VALUES ('X');` statements in `0001_init.sql` into ONE `INSERT ... VALUES (...) ON CONFLICT DO NOTHING;` block of all **70** reconciled names (63 live + 7 phantom). Cross-checked by set-equality that the 70 equal `(old 63 seed) ∪ (7 phantom)` — exact, zero drift. Fixes the latent replay bug (the old seed raised duplicate-PK on a second apply) and gives fresh-bootstrap parity with the reconciled live DB (REQ-12/D-09/D-08).
- Shipped `0032_dynamic_map_management.sql` with the load-bearing three-step sequence: (1) reconcile the 7 phantom maps `ON CONFLICT DO NOTHING`, (2) a `DO $$ ... RAISE EXCEPTION ... $$` orphan pre-flight that fails LOUDLY (with the offending names) if any `core.maps.map_name` is absent from `maps.names`, (3) `ALTER TABLE core.maps ADD CONSTRAINT maps_map_name_names_fk FOREIGN KEY (map_name) REFERENCES maps.names (name) ON UPDATE CASCADE` — mirroring the existing `maps.mastery` FK (REQ-11/D-11).
- Added `scripts/export_map_names_seed.py` — a dependency-light `asyncpg.connect` standalone script that reads `SELECT name FROM maps.names ORDER BY name` and emits the same `ON CONFLICT DO NOTHING` block to stdout. Module docstring states the D-10 constraints (on-demand only, never imported by app code, never on the request path, not in the nightly backup); confirmed unreferenced by `apps/` (REQ-14/D-10).
- Added 5 schema tests (`test_map_management_schema.py`): `phantom_maps` (7 present), `seed_idempotent` (re-apply raises no error, count unchanged), and three `map_name_fk` tests (FK exists with `ON UPDATE CASCADE`; orphan insert → `ForeignKeyViolationError`; known-name insert succeeds). All `-k` filters from 15-VALIDATION (`phantom_maps` / `seed_idempotent` / `map_name_fk`) resolve.
- **No `banner_url` column added anywhere** — `grep -c banner_url apps/api/migrations/0001_init.sql` == 0 (D-06 honored).
- Full API suite green: **1921 passed, 2 skipped, 2 xfailed, 0 failures** (`pytest -n 4 --no-testmon`); `just lint-api` clean.

## Task Commits

Each task was committed atomically on `feat/better-ow-map-management`:

1. **Task 1: Rewrite the maps.names seed to one idempotent block** - `f84d193` (fix)
2. **Task 2: Migration 0032 (reconcile + orphan guard + FK) and the export script** - `d040e2e` (feat)
3. **Task 3: Schema tests + deviation fixes (0003 idempotency, tournament-schema fixtures)** - `46ca360` (test)

## Files Created/Modified

- `apps/api/migrations/0001_init.sql` - `maps.names` seed rewritten from 63 plain INSERTs to one `ON CONFLICT DO NOTHING` block of 70 names; no other block touched; no `banner_url`.
- `apps/api/migrations/0032_dynamic_map_management.sql` - NEW. Phantom reconcile → orphan pre-flight `RAISE EXCEPTION` → `maps_map_name_names_fk` FK.
- `scripts/export_map_names_seed.py` - NEW. Standalone on-demand seed export (D-10).
- `apps/api/tests/integration/test_map_management_schema.py` - NEW. 5 schema tests (REQ-11/12/13).
- `apps/api/migrations/0003_stadium_maps_1.sql` - Made idempotent (`ON CONFLICT DO NOTHING`) — deviation, see below.
- `apps/api/tests/integration/test_tournaments_schema.py` - Seed fictional map names into `maps.names` before two `core.maps` inserts — deviation, see below.

## Decisions Made

- Used the 70-name list from `15-01-SUMMARY.md` (captured verbatim from the pre-flip Literal) as the canonical seed set, and machine-verified it equals `(old 63 seed) ∪ (7 phantom)` before committing.
- Asserted the FK's `ON UPDATE CASCADE` via `pg_constraint.confupdtype == b'c'` (asyncpg returns Postgres `"char"` as a byte).
- Kept `0003`'s seed as a single idempotent block rather than deleting it — it documents the stadium-maps batch and now safely no-ops against the canonical 0001 seed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Made `0003_stadium_maps_1.sql` idempotent**
- **Found during:** Task 3 (running the new schema tests, which apply all migrations on a fresh DB)
- **Issue:** `0003` pre-seeded 6 of the 7 phantom maps with plain `INSERT INTO maps.names VALUES (...)`. Once Task 1 added those same names to the canonical `0001` seed, a fresh from-migrations apply raised a duplicate-PK violation at `0003`, blocking every migration (and thus the whole test session) from applying.
- **Fix:** Collapsed `0003` into one `INSERT INTO maps.names (name) VALUES (...) ON CONFLICT DO NOTHING;` block. Consistent with D-09's replay-safety intent; the names now safely no-op against the 0001 seed.
- **Files modified:** `apps/api/migrations/0003_stadium_maps_1.sql`
- **Verification:** Migrations apply cleanly; `test_phantom_maps`/`test_seed_idempotent` pass.
- **Committed in:** `46ca360` (Task 3 commit)

**2. [Rule 1 - Bug] Seeded fictional map names in 4 tournaments-schema tests**
- **Found during:** Task 3 (full-suite run after the FK landed)
- **Issue:** Four tests in `test_tournaments_schema.py` insert a `core.maps` row with a fictional `map_name` (`'Tournament Test Map'`, `'Verification Aware Test Map'`). The new `maps_map_name_names_fk` FK correctly rejected those names with `ForeignKeyViolationError` — failures directly caused by this plan's FK (in scope per the SCOPE BOUNDARY rule).
- **Fix:** Insert the fictional name into `maps.names` (`ON CONFLICT DO NOTHING`) immediately before each `core.maps` insert, satisfying the FK while preserving the tests' intent (they just need a map row).
- **Files modified:** `apps/api/tests/integration/test_tournaments_schema.py`
- **Verification:** `test_tournaments_schema.py` → 22 passed; full suite → 1921 passed / 0 failures.
- **Committed in:** `46ca360` (Task 3 commit)

**3. [Rule 1 - Bug] FK introspection assertion type**
- **Found during:** Task 3 (first schema-test run)
- **Issue:** `test_map_name_fk_constraint_exists` asserted `confupdtype == "c"`, but asyncpg returns the Postgres `"char"` column as a byte (`b'c'`).
- **Fix:** Changed the assertion to `== b"c"` with an explanatory comment.
- **Files modified:** `apps/api/tests/integration/test_map_management_schema.py` (pre-commit, same task)
- **Verification:** All 5 schema tests pass.
- **Committed in:** `46ca360` (Task 3 commit)

---

**Total deviations:** 3 auto-fixed (1 blocking, 2 bug — 1 of which was a self-introduced test assertion fixed pre-commit).
**Impact on plan:** All necessary for correctness. Deviations #1 and #2 are direct, expected consequences of making the seed idempotent and adding the FK — both are exactly the durability/integrity intent of the plan, applied to surfaces the plan did not enumerate. No scope creep beyond the maps.names seed/FK story.

## Issues Encountered

- `just test-api` uses `pytest-testmon`, which selected 0 tests because the changed files (SQL migrations, the new schema-test file) are outside testmon's Python dependency graph. Ran `pytest -n 4 --no-testmon` to get a true full-suite signal (1921 passed).

## Known Stubs

None — this plan is migrations, a standalone script, and schema tests. No UI/data-flow stubs.

## Threat Flags

None — the FK (`maps_map_name_names_fk`) and the orphan pre-flight are precisely the planned T-15-03 (tampering backstop) and T-15-04 (loud-fail migration) mitigations from the plan's threat register. The export script is the accepted T-15-05 surface (no new packages, unreferenced by app code, off the request path). No new security-relevant surface introduced.

## Next Phase Readiness

- **15-03 (runtime validation):** Ready — the `core.maps.map_name → maps.names.name` FK is in place to backstop the service-layer `maps.names` check that replaces the dropped enum gate (REQ-02/T-15-01).
- **15-04/15-05:** The reconciled, durable `maps.names` (70 names, idempotent seed) is the canonical source all three surfaces read; new maps inserted at runtime are now FK-protected.
- Verification environment: `just lint-api` clean; full API suite (`pytest -n 4 --no-testmon`) 1921 passed / 0 failures.

## Self-Check: PASSED

- FOUND: `apps/api/migrations/0032_dynamic_map_management.sql`
- FOUND: `scripts/export_map_names_seed.py`
- FOUND: `apps/api/tests/integration/test_map_management_schema.py`
- FOUND: `apps/api/migrations/0001_init.sql` (idempotent seed, 0 banner_url)
- FOUND commit `f84d193` (Task 1)
- FOUND commit `d040e2e` (Task 2)
- FOUND commit `46ca360` (Task 3)

---
*Phase: 15-dynamic-overwatch-map-management*
*Completed: 2026-06-26*
