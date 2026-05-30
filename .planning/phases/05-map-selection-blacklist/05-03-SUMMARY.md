---
phase: 05-map-selection-blacklist
plan: 03
subsystem: api
tags: [pytest, service-tests, integration-tests, tournament, map-selection]

# Dependency graph
requires:
  - phase: 05-map-selection-blacklist
    provides: TournamentService with select_map, get_next_cycle, reroll_map, choose_map methods and 4 controller endpoints
provides:
  - 14 service unit tests validating all map selection business logic paths
  - 11 integration tests verifying full HTTP stack for all 4 map selection endpoints
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns: [dict factory lambdas for mock return values, side_effect lists for sequential mock returns]

key-files:
  created:
    - apps/api/tests/services/test_tournament_service.py
  modified:
    - apps/api/tests/services/conftest.py
    - apps/api/tests/integration/test_tournaments_integration.py

key-decisions:
  - "Used lambda dict factories (_config, _category, _map, _pending) for concise mock return value construction with override support"
  - "Used side_effect lists on fetch_pending_cycle to simulate sequential calls (first returns None, second returns pending dict)"

patterns-established:
  - "Dict factory pattern for mock data: _entity = lambda **kw: {defaults, **kw} for compact test setup"

requirements-completed: [CYCLE-04, CYCLE-05, CYCLE-06, CYCLE-07]

# Metrics
duration: 5min
completed: 2026-05-29
---

# Phase 5 Plan 3: Service Unit Tests and Integration Tests for Map Selection Summary

**14 service unit tests covering select_map/reroll_map/choose_map/get_next_cycle business logic, plus 11 integration tests verifying all 4 map selection endpoints through the full HTTP stack**

## Performance

- **Duration:** 5 min
- **Started:** 2026-05-29T23:58:56Z
- **Completed:** 2026-05-30T00:04:11Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Added mock_tournament_repo fixture to services conftest using AsyncMock(spec=TournamentRepository)
- Created 14 service unit tests across 4 test classes: TestSelectMap (5 tests), TestRerollMap (2 tests), TestChooseMap (4 tests), TestGetNextCycle (3 tests)
- Added 11 integration tests across 4 test classes: TestSelectMapEndpoint (3 tests), TestGetNextCycleEndpoint (3 tests), TestRerollEndpoint (2 tests), TestChooseMapEndpoint (3 tests)
- Service tests verify: happy paths, PendingCycleAlreadyExistsError, CategoryNotFoundError, LRU fallback when pool exhausted, NoEligibleMapsError, exclude_map_ids for reroll, MapNotEligibleError for bad code and difficulty mismatch, silent replace of existing pending in choose_map
- Integration tests verify: 201/200/409/404/422 status codes for all endpoint success and error paths
- All 43 tournament tests pass (14 service + 29 integration)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add mock fixture and service unit tests** - `d806352` (test)
2. **Task 2: Add integration tests for map selection endpoints** - `37fe3ac` (test)

## Files Created/Modified
- `apps/api/tests/services/test_tournament_service.py` - New file: 14 service unit tests for map selection business logic
- `apps/api/tests/services/conftest.py` - Added TournamentRepository import and mock_tournament_repo fixture
- `apps/api/tests/integration/test_tournaments_integration.py` - Added 4 new test classes with 11 integration tests

## Decisions Made
- Used lambda dict factories for mock return values to keep test setup concise while allowing per-test overrides
- Used side_effect lists on fetch_pending_cycle mock to simulate the sequential call pattern (first call checks existence, second call returns created pending cycle)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

### Pre-existing Test Failures (Out of Scope)

Two pre-existing test failures exist in `apps/api/tests/repository/tournaments/test_tournaments_repository.py::TestCheckActiveCycleForCategory`:
- `test_no_active_cycle_returns_false` asserts `result is False` but method returns `None`
- `test_active_cycle_returns_true` asserts `result is True` but method returns `int` (cycle ID)

These tests were created in phase 03-02 (commit 99623a3) and are not caused by this plan's changes. The `check_active_cycle_for_category` repository method returns `int | None`, not `bool`. Logged as deferred item.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 05 (Map Selection & Blacklist) is fully complete across all 3 plans
- All SDK structs, domain exceptions, repository methods, service logic, controller endpoints, and tests are in place
- Ready for Phase 06 (Submission + Cross-Write)

## Self-Check: PASSED

All files verified present, all commit hashes confirmed in git log.

---
*Phase: 05-map-selection-blacklist*
*Completed: 2026-05-29*
