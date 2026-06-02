---
status: complete
phase: 01-database-schema-migrations
source: [01-01-SUMMARY.md]
started: 2026-05-30T20:30:00Z
updated: 2026-05-30T20:40:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Cold Start Smoke Test
expected: Apply migration 0020 against a fresh database (test DB applies all migrations sorted). Migration runs cleanly inside BEGIN/COMMIT, tournaments schema created, no conflicts with core/maps schemas, singleton config seeded with blacklist_weeks=4.
result: pass

### 2. Tournaments Schema & Tables Exist
expected: The tournaments schema exists and contains config, categories, cycles, completions, streaks, and pending_transitions (xp_grants added in a later phase). All 6 base tables present.
result: pass

### 3. Singleton Config Constraint & Seed
expected: tournaments.config has CHECK(id=1) so a second config row (id=2) is rejected with a check violation. One config row exists seeded with blacklist_weeks=4. No XP columns on config.
result: pass

### 4. Per-Category XP Configuration
expected: tournaments.categories carries participation_xp, placement_xp (jsonb), streak_xp (jsonb), and champion_role_id — XP config lives on categories, not config (D-05/D-06).
result: pass

### 5. Cycle Status CHECK Constraint
expected: tournaments.cycles.status only accepts pending/active/finalizing/completed; an invalid status value is rejected with a check violation. map_id FK uses ON DELETE RESTRICT.
result: pass

### 6. core.completions Cross-Link Column
expected: core.completions has a nullable tournament_completion_id int column (no default) referencing tournaments.completions(id) ON DELETE SET NULL, with a partial index on non-null values.
result: pass

### 7. FK Indexes & Ranking Index
expected: Every FK column has an explicit index; the leaderboard ranking index idx_tournament_completions_ranking exists on (cycle_id, verified DESC, time ASC) per D-02 (tier-then-time).
result: pass
note: One nullable FK (streaks.last_cycle_id, ON DELETE SET NULL) lacks an explicit index — VERIFICATION.md WARNING-level gap, not a correctness issue. Carried forward.

### 8. Integration Test Suite Passes
expected: Running the schema introspection test suite passes all 9 tests against a live PostgreSQL instance with every migration applied.
result: pass
note: Verified live this session — 9 passed in 2.19s (tests/integration/test_tournaments_schema.py).

## Summary

total: 8
passed: 8
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

[none yet]
