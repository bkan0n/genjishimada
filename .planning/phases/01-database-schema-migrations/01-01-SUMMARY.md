---
phase: 01-database-schema-migrations
plan: 01
subsystem: database
tags: [schema, migration, postgresql, tournaments]
dependency_graph:
  requires: []
  provides:
    - tournaments schema with 6 tables
    - core.completions tournament_completion_id FK column
    - singleton config with blacklist_weeks
  affects:
    - core.completions (added nullable FK column)
tech_stack:
  added: []
  patterns:
    - singleton config CHECK(id=1) -- reused from store.config
    - text CHECK(...IN(...)) for status columns -- no ENUM types
    - IF NOT EXISTS on all tables and indexes -- re-runnable migration
key_files:
  created:
    - apps/api/migrations/0020_tournaments.sql
    - apps/api/tests/integration/test_tournaments_schema.py
  modified: []
decisions:
  - "Used text CHECK constraint for cycle status instead of CREATE TYPE ENUM (matches codebase convention, avoids ALTER TYPE issues in transactions)"
  - "Used ON DELETE RESTRICT for cycles.map_id FK (prevents map deletion while used in active tournament)"
  - "Added IF NOT EXISTS on ALTER TABLE ADD COLUMN for idempotent re-runs"
metrics:
  duration: 4m 10s
  completed: 2026-05-29T19:29:15Z
---

# Phase 01 Plan 01: Tournament Schema Migration Summary

Tournament schema migration with 6 tables (config, categories, cycles, completions, streaks, pending_transitions), singleton config seeded with blacklist_weeks=4, per-category XP configuration via JSONB columns, tier-then-time ranking index, and nullable tournament_completion_id FK on core.completions.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Write 0020_tournaments.sql migration | ddf5a54 | apps/api/migrations/0020_tournaments.sql |
| 2 | Write integration tests for tournament schema | f7c86ae | apps/api/tests/integration/test_tournaments_schema.py |

## Verification Results

- Migration file contains 6 CREATE TABLE, 13 CREATE INDEX, BEGIN/COMMIT wrapping
- CHECK(id=1) singleton constraint on tournaments.config verified
- Singleton config seeded with blacklist_weeks=4
- XP columns (participation_xp, placement_xp, streak_xp) on categories, not config
- No ENUM types -- all status columns use text CHECK constraint
- All FK columns to core.users use bigint, all FK columns to core.maps use int
- Every FK column has corresponding CREATE INDEX
- ALTER TABLE core.completions adds nullable tournament_completion_id with no DEFAULT
- All 9 integration tests pass

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test_cycles_status_check_constraint test**
- **Found during:** Task 2 test execution
- **Issue:** Test assumed seed data exists in core.maps, but the test database has no map seed data. Test failed with `assert None is not None` when querying for a map_id.
- **Fix:** Insert a test user and test map inline within the test using ON CONFLICT DO NOTHING/UPDATE for idempotency. No seed data dependency.
- **Files modified:** apps/api/tests/integration/test_tournaments_schema.py
- **Commit:** f7c86ae (included in Task 2 commit)

## Threat Flags

No new threat surface beyond what the plan's threat model covers. All mitigations from T-01-01 through T-01-05 are implemented:
- T-01-01: CHECK(id=1) constraint present on tournaments.config
- T-01-02: CHECK constraint on cycles.status restricts to valid values
- T-01-03: tournament_completion_id is nullable with no DEFAULT (metadata-only ADD COLUMN)
- T-01-04: ON DELETE RESTRICT on cycles.map_id prevents map deletion; CASCADE on user FKs preserves referential integrity

## Known Stubs

None -- this is a pure DDL migration with no application code stubs.

## Self-Check: PASSED
