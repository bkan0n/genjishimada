---
phase: 02-sdk-types-domain-exceptions
plan: 02
subsystem: api
tags: [exceptions, domain-errors, tournaments, python]

# Dependency graph
requires:
  - phase: 01-database-schema-migrations
    provides: Tournament schema defining business rules that exceptions represent
provides:
  - Tournament domain exception hierarchy (TournamentsError base + 8 specific subclasses)
  - Barrel re-exports with TournamentsCategoryNotFoundError alias
affects: [04-api-service-layer, 05-api-controllers, 06-submission-cross-write]

# Tech tracking
tech-stack:
  added: []
  patterns: [three-tier-exception-hierarchy, domain-exception-aliasing]

key-files:
  created:
    - apps/api/services/exceptions/tournaments.py
  modified:
    - apps/api/services/exceptions/__init__.py

key-decisions:
  - "Used aliased import (CategoryNotFoundError as TournamentsCategoryNotFoundError) in barrel __init__.py to match existing CompletionsMapNotFoundError pattern"
  - "Followed completions.py exception style (no __init__ docstrings) for consistency over store.py style (has __init__ docstrings)"

patterns-established:
  - "Tournament exception naming: TournamentsError base with {Description}Error subclasses"
  - "Aliasing pattern for cross-domain name collisions: {Domain}{OriginalName} in barrel exports"

requirements-completed: []

# Metrics
duration: 3min
completed: 2026-05-29
---

# Phase 02 Plan 02: Domain Exceptions Summary

**TournamentsError(DomainError) base with 8 specific business-rule exception subclasses and aliased barrel exports avoiding content.CategoryNotFoundError collision**

## Performance

- **Duration:** 3 min
- **Started:** 2026-05-29T20:01:33Z
- **Completed:** 2026-05-29T20:04:42Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Created tournament domain exception hierarchy with 1 base + 8 specific exception classes
- All exceptions follow three-tier pattern with typed context kwargs for Sentry/logging
- Resolved CategoryNotFoundError naming collision with content domain via TournamentsCategoryNotFoundError alias
- All 9 exception names importable from services.exceptions barrel

## Task Commits

Each task was committed atomically:

1. **Task 1: Create tournaments.py domain exception module** - `be8755b` (feat)
2. **Task 2: Update exceptions __init__.py with tournament imports and aliasing** - `d1c9b9f` (feat)

## Files Created/Modified
- `apps/api/services/exceptions/tournaments.py` - Tournament domain exception hierarchy (TournamentsError base + CategoryLockedError, CategoryNotFoundError, CycleAlreadyActiveError, CycleNotActiveError, CycleNotFoundError, DuplicateTournamentCompletionError, MapNotEligibleError, NoCycleActiveError)
- `apps/api/services/exceptions/__init__.py` - Added tournament exception imports, aliased CategoryNotFoundError as TournamentsCategoryNotFoundError, updated __all__ with 9 new entries

## Decisions Made
- Used aliased import pattern (approach b from RESEARCH.md Pitfall 1) rather than renaming the class itself, matching established CompletionsMapNotFoundError / ChangeRequestsMapNotFoundError / UsersUserNotFoundError conventions
- Followed completions.py exception style (no __init__ docstrings, D107 ignored) rather than store.py style (has __init__ docstrings) for cleaner, more consistent code within the domain

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed line-too-long in CategoryLockedError.__init__**
- **Found during:** Task 1 (Create tournaments.py)
- **Issue:** super().__init__() call exceeded 120-character line limit (124 chars)
- **Fix:** Wrapped the super().__init__() call with multi-line formatting matching the CycleNotActiveError and DuplicateTournamentCompletionError pattern
- **Files modified:** apps/api/services/exceptions/tournaments.py
- **Verification:** ruff check passed after fix
- **Committed in:** be8755b (part of Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Trivial formatting fix, no scope change.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Domain exception classes ready for TournamentsService (Phase 4+) to raise
- Controllers (Phase 5+) can catch TournamentsError subclasses and translate to HTTP responses
- Barrel __init__.py exports enable clean imports from services.exceptions

## Self-Check: PASSED

- [x] apps/api/services/exceptions/tournaments.py exists
- [x] apps/api/services/exceptions/__init__.py exists
- [x] 02-02-SUMMARY.md exists
- [x] Commit be8755b found in git log
- [x] Commit d1c9b9f found in git log

---
*Phase: 02-sdk-types-domain-exceptions*
*Completed: 2026-05-29*
