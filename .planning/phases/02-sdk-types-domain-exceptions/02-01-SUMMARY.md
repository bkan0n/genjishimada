---
phase: 02-sdk-types-domain-exceptions
plan: 01
subsystem: sdk
tags: [msgspec, structs, tournaments, types, literals]

# Dependency graph
requires:
  - phase: 01-database-schema-migrations
    provides: Tournament database schema (0020_tournaments.sql) defining column types
provides:
  - Tournament SDK types module (tournaments.py) with 17 Struct types and 2 Literal aliases
  - SDK package registration for tournaments module
affects: [03-repository-layer, 04-service-layer, 05-api-routes, 06-submission-cross-write, 07-cycle-transitions, 08-rewards-engine, 09-bot-consumers, 10-admin-cli]

# Tech tracking
tech-stack:
  added: []
  patterns: [JSONB sub-structs for typed validation, tournament event contract]

key-files:
  created:
    - libs/sdk/src/genjishimada_sdk/tournaments.py
  modified:
    - libs/sdk/src/genjishimada_sdk/__init__.py

key-decisions:
  - "All 4 RabbitMQ event types defined upfront to prevent SDK churn across phases 3-10"
  - "JSONB columns modeled as typed sub-structs (PlacementXpTier, StreakXpTier) instead of list[dict]"
  - "TournamentXpGrantEvent carries tournament-specific context (cycle_id, category_id, grant_reason) distinct from generic XpGrantEvent"

patterns-established:
  - "Tournament SDK prefix convention: all types use Tournament* prefix to avoid collision with existing domains"
  - "CycleFrequency and CycleStatus Literal aliases constrain valid values at decode time"

requirements-completed: []

# Metrics
duration: 2min
completed: 2026-05-29
---

# Phase 2 Plan 1: SDK Types Module Summary

**Tournament SDK types module with 17 msgspec Structs, 2 Literal type aliases, and 2 JSONB sub-structs covering config, categories, cycles, completions, streaks, and RabbitMQ events**

## Performance

- **Duration:** 2 min
- **Started:** 2026-05-29T20:01:29Z
- **Completed:** 2026-05-29T20:03:41Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Created tournaments.py SDK module with all request, response, and event types matching database schema
- Registered tournaments module in SDK __init__.py with clean imports
- All types validated via lint-sdk (Ruff format + check + BasedPyright) with zero errors

## Task Commits

Each task was committed atomically:

1. **Task 1: Create tournaments.py SDK module with all msgspec Structs** - `c0c8d9e` (feat)
2. **Task 2: Register tournaments module in SDK __init__.py** - `8ec08aa` (feat)

## Files Created/Modified
- `libs/sdk/src/genjishimada_sdk/tournaments.py` - 17 Struct types, 2 Literal type aliases, 2 JSONB sub-structs for tournament domain data contract
- `libs/sdk/src/genjishimada_sdk/__init__.py` - Added tournaments to import block and __all__ list

## Decisions Made
- All 4 RabbitMQ event types defined upfront (TournamentCycleStartedEvent, TournamentCycleCompletedEvent, TournamentCompletionCreatedEvent, TournamentXpGrantEvent) per D-03 to prevent SDK churn
- JSONB columns modeled as typed sub-structs (PlacementXpTier, StreakXpTier) for compile-time and decode-time validation
- TournamentXpGrantEvent uses tournament-specific fields (cycle_id, category_id, grant_reason) rather than reusing generic XpGrantEvent

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- SDK types are ready for import by downstream phases (repository, service, controller, bot consumers)
- Plan 02-02 (domain exceptions) can proceed immediately
- All type aliases (CycleFrequency, CycleStatus) and sub-structs (PlacementXpTier, StreakXpTier) are available for use

## Self-Check: PASSED

- libs/sdk/src/genjishimada_sdk/tournaments.py: FOUND
- libs/sdk/src/genjishimada_sdk/__init__.py: FOUND
- Commit c0c8d9e: FOUND
- Commit 8ec08aa: FOUND

---
*Phase: 02-sdk-types-domain-exceptions*
*Completed: 2026-05-29*
