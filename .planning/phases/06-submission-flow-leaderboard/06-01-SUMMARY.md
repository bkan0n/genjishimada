---
phase: 06-submission-flow-leaderboard
plan: 01
subsystem: tournament-service-layer
tags: [domain-exceptions, sdk-structs, repository, service, submission, leaderboard, cycles]
dependency_graph:
  requires: [02-01, 02-02, 03-01, 03-02, 05-01, 05-02, 05-03]
  provides: [tournament-submit-completion, tournament-get-leaderboard, tournament-list-cycles, slower-time-error, map-mismatch-error, cycle-with-winner-response, cycle-list-response]
  affects: [06-02]
tech_stack:
  added: []
  patterns: [dynamic-where-clause, lateral-join-winner, transactional-submit-flow]
key_files:
  created: []
  modified:
    - apps/api/services/exceptions/tournaments.py
    - libs/sdk/src/genjishimada_sdk/tournaments.py
    - apps/api/repository/tournaments_repository.py
    - apps/api/services/tournament_service.py
decisions:
  - "No RabbitMQ publishing in submit_completion (per D-08)"
  - "map_id extracted from cycle, not request body (per RESEARCH Pitfall 2)"
  - "LEFT JOIN LATERAL subquery for winner info in fetch_cycles"
metrics:
  duration: 3min
  completed: 2026-05-30
---

# Phase 06 Plan 01: Submission Flow & Leaderboard Service Layer Summary

Domain exceptions, SDK structs, repository method, and service methods for tournament completion submission, leaderboard retrieval, and cycle listing with winner info.

## Commits

| Task | Name | Commit | Key Changes |
|------|------|--------|-------------|
| 1 | Add domain exceptions and SDK response structs | d4a0755 | SlowerTimeError, MapMismatchError, TournamentCycleWithWinnerResponse, TournamentCycleListResponse |
| 2 | Add fetch_cycles repo and three service methods | 9ec8cd4 | fetch_cycles with dynamic WHERE + LATERAL winner JOIN, submit_completion transactional flow, get_leaderboard, list_cycles |

## What Was Built

### Domain Exceptions (apps/api/services/exceptions/tournaments.py)
- **SlowerTimeError**: Raised when submitted time >= current best. Carries `current_best` and `submitted_time` context.
- **MapMismatchError**: Raised when submitted map doesn't match cycle's assigned map. Carries `cycle_id`, `expected_map_id`, `submitted_map_id` context.

### SDK Response Structs (libs/sdk/src/genjishimada_sdk/tournaments.py)
- **TournamentCycleWithWinnerResponse**: 12-field struct with cycle details, joined map info (code, name, difficulty), and rank-1 winner info (name, user_id).
- **TournamentCycleListResponse**: Pagination wrapper with `total` count and `cycles` list.

### Repository Method (apps/api/repository/tournaments_repository.py)
- **fetch_cycles**: Dynamic WHERE clause for optional `status` and `category_id` filters. JOINs `core.maps` for map details. Uses LEFT JOIN LATERAL subquery to find rank-1 winner per cycle (DISTINCT ON user_id for best-per-user, then ordered by verified DESC, time ASC). Returns `tuple[int, list[dict]]`.

### Service Methods (apps/api/services/tournament_service.py)
- **submit_completion**: Single-transaction flow: fetch cycle -> validate active status -> check user's current best -> insert tournament completion -> cross-write to core.completions. No RabbitMQ publishing (per D-08).
- **get_leaderboard**: Delegates to `fetch_leaderboard` and converts rows to `TournamentLeaderboardEntryResponse` structs.
- **list_cycles**: Delegates to `fetch_cycles` with optional filters and returns `TournamentCycleListResponse` pagination wrapper.

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check: PASSED
