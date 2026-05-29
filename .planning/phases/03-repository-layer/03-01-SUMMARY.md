---
phase: 03-repository-layer
plan: 01
subsystem: api/repository
tags: [repository, asyncpg, sql, tournaments, crud]
dependency_graph:
  requires:
    - "01-01: tournaments schema migration (tournaments.config/categories/cycles/completions/streaks/pending_transitions)"
    - "02-01: SDK tournament types (response/request/event structs)"
    - "02-02: domain exceptions (TournamentsCategoryNotFoundError, etc.)"
  provides:
    - "TournamentRepository class with 24 data access methods"
    - "provide_tournament_repository DI provider function"
  affects:
    - "Phase 4+: service layer will import TournamentRepository"
    - "Phase 6: submission service calls cross_write_to_core"
    - "Phase 7: cycle transition service calls create_pending_transition"
tech_stack:
  added: []
  patterns:
    - "CTE-based conditional INSERT for cross-write to core.completions"
    - "DISTINCT ON + RANK() OVER for two-stage leaderboard ranking"
    - "Dynamic UPDATE with JSONB/text[] casts"
    - "Upsert with ON CONFLICT DO UPDATE for streak tracking"
key_files:
  created:
    - apps/api/repository/tournaments_repository.py
  modified: []
decisions:
  - "24 methods instead of 22: plan objective said 22 but D-09 lists 24 distinct methods across all groups"
  - "Completions methods placed between streaks and pending transitions in class body for logical grouping"
  - "cross_write_to_core does not wrap in try/except -- CTE handles the conditional logic, trigger is safety net"
metrics:
  duration: 3min
  completed: "2026-05-29T22:15:00Z"
  tasks_completed: 2
  tasks_total: 2
  files_created: 1
  files_modified: 0
---

# Phase 03 Plan 01: Tournament Repository Summary

TournamentRepository with 24 raw SQL methods covering all tournament tables, including CTE-based cross-write to core.completions and two-stage DISTINCT ON + RANK() OVER leaderboard query.

## What Was Built

### Task 1: Config, Categories, Cycles, Map Selection, Streaks, and Transitions (ba1d3b7)

Created `apps/api/repository/tournaments_repository.py` with `TournamentRepository(BaseRepository)` class containing 18 methods across 6 table groups:

- **Config (2):** `fetch_config`, `update_config` -- singleton pattern with `WHERE id = 1`
- **Categories (6):** `create_category`, `fetch_category`, `fetch_categories`, `update_category`, `delete_category`, `check_active_cycle_for_category` -- dynamic UPDATE with JSONB/text[] casts, full constraint handling
- **Cycles (5):** `create_cycle`, `fetch_cycle`, `fetch_active_cycle`, `update_cycle_status`, `fetch_cycle_history` -- paginated history returns `tuple[int, list[dict]]`, COALESCE for timestamps
- **Map Selection (2):** `fetch_eligible_maps`, `fetch_least_recently_used_map` -- regexp_replace difficulty matching, blacklist window via interval cast
- **Streaks (2):** `fetch_streak`, `upsert_streak` -- INSERT ON CONFLICT DO UPDATE with GREATEST for max_streak
- **Pending Transitions (3):** `create_pending_transition`, `fetch_unpublished_transitions`, `mark_transition_published` -- outbox pattern, JSONB payload

Plus `provide_tournament_repository(state: State)` DI provider at bottom of file.

### Task 2: Completions Methods with Cross-Write CTE and Leaderboard (f3f3007)

Added 4 completions methods:

- **`create_tournament_completion`:** INSERT into tournaments.completions with UniqueViolation/FK error handling
- **`cross_write_to_core`:** CTE with 4 stages (current_best, should_insert, map_flags, computed) conditionally inserts into core.completions only when tournament time < user's best. Sets `tournament_completion_id` FK. Computes `completion_flag` from map metadata (official, playtesting, video presence). Returns new core.completions id or None if skipped.
- **`fetch_leaderboard`:** Two-stage query -- `DISTINCT ON (user_id)` selects best-per-user submission (verified DESC, time ASC), outer query applies `RANK() OVER (ORDER BY verified DESC, time ASC)` with `COALESCE(u.global_name, u.nickname, 'Unknown')` display name
- **`fetch_user_completion`:** Returns user's best submission for a cycle (verified DESC, time ASC)

## Deviations from Plan

None -- plan executed exactly as written. The plan objective stated "22 methods" but D-09 enumerates 24 distinct methods across all groups; all 24 were implemented.

## Decisions Made

1. **24 methods, not 22:** The plan objective says "22 raw SQL data access methods" but the D-09 method listing contains 24 distinct methods. Implemented all 24 as specified in D-09.
2. **Completions placed between streaks and transitions:** Per plan instruction "Insert them after the streaks section and before pending transitions."
3. **No try/except on cross_write_to_core:** The CTE handles conditional insertion (no-op when time is not faster), making the trigger a safety net. No constraint violations are expected from this method's normal operation.

## Verification Results

- ruff check: 0 errors
- ruff format --check: already formatted
- basedpyright: 0 errors, 0 warnings, 0 notes
- All 24 class methods + 1 provider function present
- Cross-write CTE contains `tournament_completion_id`, `should_insert`, `do_insert = TRUE`
- Leaderboard uses `DISTINCT ON (tc.user_id)` + `RANK() OVER`
- Every method has `conn: Connection | None = None` parameter
- Every method has `_conn = self._get_connection(conn)` as first executable line

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | ba1d3b7 | feat(03-01): add TournamentRepository with config, categories, cycles, map selection, streaks, and transitions methods |
| 2 | f3f3007 | feat(03-01): add tournament completions methods with cross-write CTE and leaderboard query |

## Self-Check: PASSED

```
FOUND: apps/api/repository/tournaments_repository.py
FOUND: ba1d3b7
FOUND: f3f3007
```
