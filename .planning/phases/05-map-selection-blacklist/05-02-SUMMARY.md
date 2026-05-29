---
phase: 05-map-selection-blacklist
plan: 02
subsystem: api
tags: [litestar, asyncpg, msgspec, service-layer, controller, map-selection, tournament]

# Dependency graph
requires:
  - phase: 05-map-selection-blacklist
    provides: SDK structs (TournamentNextCycleResponse, TournamentChooseMapRequest), domain exceptions, repository methods (fetch_pending_cycle, delete_cycle, fetch_map_by_code, fetch_eligible_maps)
provides:
  - select_map, get_next_cycle, reroll_map, choose_map service methods on TournamentService
  - 4 new controller endpoints for map selection preview, select, reroll, and explicit choice
affects: [05-03-PLAN]

# Tech tracking
tech-stack:
  added: []
  patterns: [LRU fallback pattern for exhausted eligible map pool, difficulty-strip validation with regex]

key-files:
  created: []
  modified:
    - apps/api/services/tournament_service.py
    - apps/api/routes/v3/tournaments.py

key-decisions:
  - "Used re.sub to strip trailing +/- modifiers from map difficulty before matching against category difficulties"
  - "choose_map silently replaces existing pending cycle rather than requiring explicit reroll first"

patterns-established:
  - "LRU fallback: when eligible pool is exhausted, fall back to least-recently-used map with log warning"
  - "Difficulty normalization: re.sub(r'\\s*[-+]\\s*$', '', difficulty) for base difficulty comparison"

requirements-completed: [CYCLE-04, CYCLE-05, CYCLE-06, CYCLE-07]

# Metrics
duration: 2min
completed: 2026-05-29
---

# Phase 5 Plan 2: Service Business Logic and Controller Endpoints for Map Selection Summary

**4 service methods (select_map, get_next_cycle, reroll_map, choose_map) with transaction safety and LRU fallback, plus 4 controller endpoints with scope guards and exception-to-HTTP mapping**

## Performance

- **Duration:** 2 min
- **Started:** 2026-05-29T23:53:29Z
- **Completed:** 2026-05-29T23:56:04Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Added select_map with random selection, LRU fallback on pool exhaustion, and TOCTOU-safe single-connection transaction boundary
- Added get_next_cycle, reroll_map (excludes previous map), and choose_map (validates map existence and difficulty match) service methods
- Added 4 controller endpoints with proper scope guards (tournaments:read for preview, tournaments:write for mutations) and exception-to-HTTP status mapping (404, 409, 422)
- All linting passes: ruff format, ruff check, and basedpyright with 0 errors

## Task Commits

Each task was committed atomically:

1. **Task 1: Add 4 service methods to TournamentService** - `18db7f8` (feat)
2. **Task 2: Add 4 controller endpoints to TournamentsController** - `c62b367` (feat)

## Files Created/Modified
- `apps/api/services/tournament_service.py` - Added select_map, get_next_cycle, reroll_map, choose_map methods with imports for re, logging, new SDK types, and domain exceptions
- `apps/api/routes/v3/tournaments.py` - Added GET next-cycle, POST select-map, POST reroll, PATCH next-cycle endpoints with scope guards and exception handling

## Decisions Made
- Used `re.sub(r"\s*[-+]\s*$", "", difficulty)` in choose_map to normalize map difficulty before comparing against category difficulties, matching the same regexp_replace pattern used in the SQL query
- choose_map silently replaces any existing pending cycle rather than requiring the caller to explicitly delete it first, reducing API round-trips for admin workflows

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All service and controller layers for map selection are complete
- Ready for Plan 03 (tests) to verify the full request path
- No blockers

---
*Phase: 05-map-selection-blacklist*
*Completed: 2026-05-29*
