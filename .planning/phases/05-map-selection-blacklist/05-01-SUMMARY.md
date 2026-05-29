---
phase: 05-map-selection-blacklist
plan: 01
subsystem: api
tags: [msgspec, asyncpg, sdk, repository, domain-exceptions, map-selection]

# Dependency graph
requires:
  - phase: 04-config-category-management
    provides: TournamentRepository with fetch_eligible_maps, domain exception hierarchy
provides:
  - TournamentNextCycleResponse and TournamentChooseMapRequest SDK structs
  - NoEligibleMapsError, PendingCycleAlreadyExistsError, PendingCycleNotFoundError domain exceptions
  - fetch_pending_cycle, delete_cycle, fetch_map_by_code repository methods
  - Modified fetch_eligible_maps with pending exclusion and exclude_map_ids support
affects: [05-02-PLAN, 05-03-PLAN]

# Tech tracking
tech-stack:
  added: []
  patterns: [conditional SQL query building for optional exclusion parameters]

key-files:
  created: []
  modified:
    - libs/sdk/src/genjishimada_sdk/tournaments.py
    - apps/api/services/exceptions/tournaments.py
    - apps/api/services/exceptions/__init__.py
    - apps/api/repository/tournaments_repository.py

key-decisions:
  - "Used implicit string concatenation for long error messages to satisfy 120-char line limit"
  - "Built fetch_eligible_maps query conditionally using string append for exclude_map_ids rather than two separate queries"

patterns-established:
  - "Conditional SQL query building: base query + optional clause append with dynamic args list"

requirements-completed: [CYCLE-04, CYCLE-05, CYCLE-06, CYCLE-07]

# Metrics
duration: 3min
completed: 2026-05-29
---

# Phase 5 Plan 1: SDK Structs, Domain Exceptions, and Repository Methods Summary

**TournamentNextCycleResponse and TournamentChooseMapRequest SDK structs, three map-selection domain exceptions, and three new repository methods with modified fetch_eligible_maps excluding pending cycles**

## Performance

- **Duration:** 3 min
- **Started:** 2026-05-29T23:47:19Z
- **Completed:** 2026-05-29T23:50:34Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Added TournamentNextCycleResponse (8-field admin preview struct with joined map details) and TournamentChooseMapRequest (single map_code field) to the SDK
- Added NoEligibleMapsError, PendingCycleAlreadyExistsError, and PendingCycleNotFoundError to the tournament domain exception hierarchy with barrel exports
- Added fetch_pending_cycle (JOIN to core.maps), delete_cycle (RETURNING id pattern), and fetch_map_by_code methods to TournamentRepository
- Modified fetch_eligible_maps to exclude maps in pending cycles and support an exclude_map_ids parameter for reroll

## Task Commits

Each task was committed atomically:

1. **Task 1: Add SDK structs and domain exceptions** - `740a59d` (feat)
2. **Task 2: Add repository methods and modify fetch_eligible_maps** - `3b29d87` (feat)

## Files Created/Modified
- `libs/sdk/src/genjishimada_sdk/tournaments.py` - Added TournamentNextCycleResponse and TournamentChooseMapRequest structs, updated __all__
- `apps/api/services/exceptions/tournaments.py` - Added NoEligibleMapsError, PendingCycleAlreadyExistsError, PendingCycleNotFoundError
- `apps/api/services/exceptions/__init__.py` - Added barrel imports and __all__ entries for three new exceptions
- `apps/api/repository/tournaments_repository.py` - Added fetch_pending_cycle, delete_cycle, fetch_map_by_code; modified fetch_eligible_maps

## Decisions Made
- Used implicit string concatenation for the NoEligibleMapsError message to stay within 120-char line limit (Ruff E501)
- Built the fetch_eligible_maps query conditionally using string append and dynamic args list for the optional exclude_map_ids parameter, avoiding duplicate query definitions
- Placed new repository methods in the Map Selection section after fetch_least_recently_used_map, before Streaks, following the plan's placement guidance

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed __all__ sort order in services/exceptions/__init__.py**
- **Found during:** Task 1
- **Issue:** PendingCycleAlreadyExistsError and PendingCycleNotFoundError were placed after TokenInvalidError, violating Ruff RUF022 sort order
- **Fix:** Moved both entries to correct alphabetical position between PasswordValidationError and PendingEditRequestExistsError
- **Files modified:** apps/api/services/exceptions/__init__.py
- **Verification:** ruff check passes
- **Committed in:** 740a59d (part of Task 1 commit)

**2. [Rule 1 - Bug] Fixed line length in NoEligibleMapsError message**
- **Found during:** Task 1
- **Issue:** Error message string exceeded 120-char line limit (130 chars)
- **Fix:** Split into implicit string concatenation across two lines
- **Files modified:** apps/api/services/exceptions/tournaments.py
- **Verification:** ruff check passes
- **Committed in:** 740a59d (part of Task 1 commit)

---

**Total deviations:** 2 auto-fixed (2 Rule 1 bugs)
**Impact on plan:** Both auto-fixes were linting corrections. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All SDK structs, domain exceptions, and repository methods are in place for Plan 02 (service business logic and controller endpoints)
- fetch_eligible_maps now correctly handles pending cycle exclusion and reroll exclusion
- No blockers for Plan 02

---
*Phase: 05-map-selection-blacklist*
*Completed: 2026-05-29*
