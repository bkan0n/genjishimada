---
phase: 06-submission-flow-leaderboard
plan: 02
subsystem: tournament-controller-tests
tags: [endpoints, submission, leaderboard, cycles, integration-tests, service-tests]
dependency_graph:
  requires: [06-01]
  provides: [submit-completion-endpoint, get-leaderboard-endpoint, list-cycles-endpoint, tournament-test-coverage]
  affects: []
tech_stack:
  added: []
  patterns: [exception-to-http-translation, scope-guarded-endpoints, factory-fixture-setup]
key_files:
  created: []
  modified:
    - apps/api/routes/v3/tournaments.py
    - apps/api/tests/services/test_tournament_service.py
    - apps/api/tests/integration/test_tournaments_integration.py
decisions:
  - "SlowerTimeError and CycleNotActiveError both map to 409 Conflict (not 400 or 422)"
  - "Leaderboard endpoint returns empty list (not 404) for cycles with no submissions"
  - "Integration tests use helper method _setup_active_cycle for DRY cycle/user setup"
metrics:
  duration: 6min
  completed: 2026-05-30
---

# Phase 06 Plan 02: Controller Endpoints & Test Coverage Summary

Three new REST endpoints (submit completion, leaderboard, cycle listing) with 20 new tests covering full service and HTTP stack validation including cross-write FK verification.

## Commits

| Task | Name | Commit | Key Changes |
|------|------|--------|-------------|
| 1 | Add three controller endpoints | 5a38151 | POST /cycles/{id}/submit, GET /cycles/{id}/leaderboard, GET /cycles with pagination |
| 2 | Add service unit tests and integration tests | 3aeecb8 | 10 service tests + 10 integration tests covering submission, leaderboard, cycles |

## What Was Built

### Controller Endpoints (apps/api/routes/v3/tournaments.py)

- **POST /tournaments/cycles/{cycle_id}/submit** (201): Submits tournament completion. Requires `tournaments:write` scope. Catches `CycleNotFoundError` (404), `CycleNotActiveError` (409), `SlowerTimeError` (409).
- **GET /tournaments/cycles/{cycle_id}/leaderboard** (200): Returns ranked leaderboard entries. Requires `tournaments:read` scope. Empty cycles return empty list.
- **GET /tournaments/cycles** (200): Lists cycles with optional `status` and `category_id` filters. Supports `limit` (1-100, default 20) and `offset` (>=0) pagination. Requires `tournaments:read` scope.

### Service Unit Tests (apps/api/tests/services/test_tournament_service.py)

- **TestSubmitCompletion** (6 tests): Happy path, faster-replaces, rejects-slower, rejects-equal, cycle-not-active, cycle-not-found.
- **TestGetLeaderboard** (2 tests): Ranked entries, empty leaderboard.
- **TestListCycles** (2 tests): Paginated results with winner info, filter passthrough verification.

### Integration Tests (apps/api/tests/integration/test_tournaments_integration.py)

- **TestSubmitCompletionEndpoint** (5 tests): 201 on valid submit, faster time accepted, slower time rejected (409), completed cycle rejected (409), cross-write FK verification (SUB-04).
- **TestLeaderboardEndpoint** (2 tests): 200 with ranked entries after submission, 200 with empty list for no submissions.
- **TestCycleListingEndpoint** (3 tests): 200 with total/cycles, status filter returns only matching, pagination limits results.

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check: PASSED
