---
phase: 03-repository-layer
plan: 02
subsystem: api/tests/repository
tags: [tests, pytest, repository, tournaments, integration]
dependency_graph:
  requires:
    - "03-01: TournamentRepository class with 24 data access methods"
    - "01-01: tournaments schema migration (tournaments.config/categories/cycles/completions/streaks/pending_transitions)"
  provides:
    - "39 integration tests covering all TournamentRepository method groups"
    - "Tournament-specific test fixtures (category, cycle, completion factories)"
  affects:
    - "Phase 4+: service layer tests can reuse tournament conftest fixtures"
    - "CI: new tests added to test suite for regression detection"
tech_stack:
  added: []
  patterns:
    - "Factory fixture pattern with asyncpg_pool.acquire() for test data creation"
    - "Repository instantiation with asyncpg_conn as pool fallback"
key_files:
  created:
    - apps/api/tests/repository/tournaments/__init__.py
    - apps/api/tests/repository/tournaments/conftest.py
    - apps/api/tests/repository/tournaments/test_tournaments_repository.py
  modified:
    - apps/api/tests/conftest.py
    - apps/api/repository/tournaments_repository.py
decisions:
  - "39 tests instead of minimum 25: added thorough coverage for all edge cases in cross-write, leaderboard, and transitions"
  - "Registered domain_tournaments marker in global conftest for consistency with existing domain markers"
metrics:
  duration: 7min
  completed: "2026-05-29T22:25:00Z"
  tasks_completed: 2
  tasks_total: 2
  files_created: 3
  files_modified: 2
---

# Phase 03 Plan 02: Tournament Repository Tests Summary

39 integration tests covering all TournamentRepository method groups, including cross-write CTE conditional insert behavior and tier-then-time leaderboard ranking verification, with factory fixtures for tournament test data.

## What Was Built

### Task 1: Tournament test package with conftest fixtures (bdb0371)

Created `apps/api/tests/repository/tournaments/` package with:

- **`__init__.py`:** Package docstring
- **`conftest.py`:** Four fixtures:
  - `repository(asyncpg_conn)` -- returns `TournamentRepository(asyncpg_conn)` matching store test pattern
  - `create_test_category(asyncpg_pool)` -- factory with defaults for name, difficulties, cycle_frequency, XP fields
  - `create_test_cycle(asyncpg_pool)` -- factory requiring category_id and map_id, defaults to "pending" status
  - `create_test_tournament_completion(asyncpg_pool)` -- factory requiring cycle_id, user_id, map_id with time/screenshot defaults

### Task 2: 39 tests across all method groups (99623a3)

Created `test_tournaments_repository.py` with 19 test classes covering all 7 method groups:

- **Config (2 tests):** `TestFetchConfig`, `TestUpdateConfig` -- singleton read/write
- **Categories (11 tests):** `TestCreateCategory`, `TestFetchCategory`, `TestFetchCategories`, `TestUpdateCategory`, `TestDeleteCategory`, `TestCheckActiveCycleForCategory` -- CRUD + active cycle detection + UniqueConstraintViolationError on duplicate name
- **Cycles (7 tests):** `TestCreateCycle`, `TestFetchCycle`, `TestFetchActiveCycle`, `TestUpdateCycleStatus`, `TestFetchCycleHistory` -- lifecycle status transitions + pagination
- **Completions (7 tests):** `TestCreateTournamentCompletion`, `TestCrossWriteToCore`, `TestFetchLeaderboard`, `TestFetchUserCompletion` -- cross-write inserts when faster, skips when slower/equal; leaderboard verified-beats-unverified ranking
- **Streaks (3 tests):** `TestFetchStreak`, `TestUpsertStreak` -- new streak creation + increment behavior
- **Map Selection (3 tests):** `TestFetchEligibleMaps`, `TestFetchLeastRecentlyUsedMap` -- blacklist exclusion + difficulty filtering
- **Pending Transitions (6 tests):** `TestCreatePendingTransition`, `TestFetchUnpublishedTransitions`, `TestMarkTransitionPublished` -- outbox pattern: create, filter unpublished, mark published, idempotent re-mark

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed fetch_eligible_maps int-to-text type mismatch**
- **Found during:** Task 2
- **Issue:** `fetch_eligible_maps` SQL used `($2 || ' weeks')::interval` which concatenates with `||` operator expecting text, but `blacklist_weeks` is passed as `int`. asyncpg's prepared statement protocol validates parameter types client-side and rejected `int` for a `text` parameter.
- **Fix:** Changed to `make_interval(weeks => $2)` which accepts an integer parameter natively.
- **Files modified:** `apps/api/repository/tournaments_repository.py`
- **Commit:** 99623a3

**2. [Rule 2 - Missing functionality] Registered domain_tournaments marker**
- **Found during:** Task 2
- **Issue:** The global conftest `pytest_configure` did not include `domain_tournaments` marker, which would cause pytest warnings.
- **Fix:** Added `config.addinivalue_line("markers", "domain_tournaments: Tests for tournaments domain")` to global conftest.
- **Files modified:** `apps/api/tests/conftest.py`
- **Commit:** 99623a3

## Verification Results

- All 39 tests pass (`pytest tests/repository/tournaments/ -v -p no:xdist`)
- Full project test suite passes (`just test-api`) with no regressions
- ruff check passes on all new files
- ruff format --check passes on all new files

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | bdb0371 | test(03-02): add tournament test package with conftest fixtures |
| 2 | 99623a3 | test(03-02): add 39 tests covering all TournamentRepository method groups |

## Self-Check: PASSED

```
FOUND: apps/api/tests/repository/tournaments/__init__.py
FOUND: apps/api/tests/repository/tournaments/conftest.py
FOUND: apps/api/tests/repository/tournaments/test_tournaments_repository.py
FOUND: bdb0371
FOUND: 99623a3
```
