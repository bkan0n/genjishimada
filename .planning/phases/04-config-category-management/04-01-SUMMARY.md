---
phase: 04-config-category-management
plan: 01
subsystem: api
tags: [msgspec, asyncpg, litestar, service-layer, domain-exceptions, UNSET-filtering]

# Dependency graph
requires:
  - phase: 03-repository-testing
    provides: TournamentRepository with category CRUD and active cycle check
provides:
  - TournamentService class with 7 methods for config and category management
  - CategoryNameExistsError domain exception
  - check_active_cycle_for_category returning cycle_id (int | None) instead of bool
  - provide_tournament_service DI provider function
affects: [04-02-PLAN (controller layer), future tournament service methods]

# Tech tracking
tech-stack:
  added: []
  patterns: [same-connection active cycle guard, UNSET filtering for PATCH, JSONB pre-serialization]

key-files:
  created:
    - apps/api/services/tournament_service.py
  modified:
    - apps/api/services/exceptions/tournaments.py
    - apps/api/services/exceptions/__init__.py
    - apps/api/repository/tournaments_repository.py

key-decisions:
  - "check_active_cycle_for_category returns int | None (cycle_id) instead of bool, so CategoryLockedError carries the actual cycle_id"
  - "Category creation has no active cycle guard per plan design decision D-06"
  - "Same-connection pattern for update_category and delete_category to prevent TOCTOU race conditions per D-05"

patterns-established:
  - "Active cycle guard: acquire connection, check cycle, then mutate on same connection"
  - "JSONB pre-serialization: msgspec.json.encode(struct_list).decode() before passing to repository"
  - "UNSET filtering: iterate fields with `is not msgspec.UNSET` to build partial update dict"

requirements-completed: [CYCLE-02, CYCLE-03, CYCLE-08, ADM-01, ADM-02]

# Metrics
duration: 3min
completed: 2026-05-29
---

# Phase 4 Plan 1: Config & Category Service Summary

**TournamentService with 7 methods for config GET/PATCH and category CRUD, plus CategoryNameExistsError and cycle_id-aware active cycle guard**

## Performance

- **Duration:** 2m 37s
- **Started:** 2026-05-29T23:06:48Z
- **Completed:** 2026-05-29T23:09:25Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Created TournamentService with full config and category business logic (get_config, update_config, create_category, list_categories, get_category, update_category, delete_category)
- Added CategoryNameExistsError domain exception with barrel export
- Changed check_active_cycle_for_category to return actual cycle_id instead of boolean, enabling richer error context
- Same-connection guard on update and delete prevents TOCTOU race conditions

## Task Commits

Each task was committed atomically:

1. **Task 1: Add CategoryNameExistsError and tweak repo return type** - `4fc56b6` (feat)
2. **Task 2: Create TournamentService with config and category business logic** - `e7fce5b` (feat)

## Files Created/Modified
- `apps/api/services/tournament_service.py` - TournamentService class with 7 methods and DI provider
- `apps/api/services/exceptions/tournaments.py` - Added CategoryNameExistsError
- `apps/api/services/exceptions/__init__.py` - Barrel export for CategoryNameExistsError
- `apps/api/repository/tournaments_repository.py` - check_active_cycle_for_category returns int | None

## Decisions Made
- check_active_cycle_for_category returns `int | None` (cycle_id) instead of `bool` so CategoryLockedError receives the real cycle_id for better error context
- Category creation bypasses active cycle guard (per D-06: new categories should always be creatable)
- Same-connection pattern used for update/delete to prevent TOCTOU race conditions between cycle check and mutation

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- basedpyright fails on SDK imports in worktree due to workspace-level editable install resolution -- this is a known worktree environment limitation (same error on all existing service files like store_service.py), not a code defect. ruff check passes cleanly.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- TournamentService is ready for Plan 02 (controller layer) to wire into route handlers
- provide_tournament_service DI provider is ready for Controller dependencies dict
- All domain exceptions (CategoryNotFoundError, CategoryLockedError, CategoryNameExistsError) are exported and ready for controller exception mapping

## Self-Check: PASSED

All files exist, all commits verified, all key code elements confirmed.

---
*Phase: 04-config-category-management*
*Completed: 2026-05-29*
