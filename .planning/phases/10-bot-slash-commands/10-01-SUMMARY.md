---
phase: 10-bot-slash-commands
plan: 01
subsystem: api
tags: [tournaments, streaks, endpoint, tdd]
requires:
  - "TournamentRepository.fetch_streak (Phase 8)"
  - "TournamentStreakResponse SDK struct (Phase 8)"
provides:
  - "GET /api/v3/tournaments/streaks/{user_id} (tournaments:read)"
  - "TournamentService.get_streak(user_id) -> TournamentStreakResponse"
  - "StreakNotFoundError(TournamentsError) domain exception"
affects:
  - "Plan 10-03 bot /tournament streak command (runtime dependency)"
tech-stack:
  added: []
  patterns:
    - "Three-tier exception hierarchy: service raises domain error, route converts to CustomHTTPException(404) — mirrors get_category"
key-files:
  created: []
  modified:
    - apps/api/services/exceptions/tournaments.py
    - apps/api/services/tournament_service.py
    - apps/api/routes/v3/tournaments.py
    - apps/api/tests/services/test_tournament_service.py
    - apps/api/tests/integration/test_tournaments_integration.py
decisions:
  - "D-01: streak endpoint path /tournaments/streaks/{user_id}, tournaments:read scope"
  - "D-04: endpoint 404s on absent record; zero-state presentation is bot-side (Plan 10-03)"
  - "get_streak mirrors get_category's service-raises / route-converts hierarchy (not a None return)"
metrics:
  duration: 13min
  completed: 2026-05-30
requirements: [ADM-03]
---

# Phase 10 Plan 01: Streak Read Endpoint Summary

Added `GET /api/v3/tournaments/streaks/{user_id}` (tournaments:read) plus `TournamentService.get_streak` and a `StreakNotFoundError(TournamentsError)` domain exception — the one missing backing endpoint for the bot's `/tournament streak` command, built TDD-first and mirroring the live `get_category` three-tier pattern exactly.

## What Was Built

- **`StreakNotFoundError(TournamentsError)`** (`services/exceptions/tournaments.py`) — domain exception carrying `user_id`, mirroring `CategoryNotFoundError`.
- **`TournamentService.get_streak(user_id)`** (`services/tournament_service.py`) — fetches via the existing `TournamentRepository.fetch_streak`; raises `StreakNotFoundError` when the repo returns `None` (the SERVICE raises, not returns `None`); otherwise `msgspec.convert` to `TournamentStreakResponse`.
- **`GET /streaks/{user_id:int}` route** (`routes/v3/tournaments.py`) — `tournaments:read` scope; catches `StreakNotFoundError` and converts to `CustomHTTPException(HTTP_404_NOT_FOUND)`. No zero-struct synthesis (D-04 zero-mapping is bot-side, Plan 10-03).
- **Tests** — `TestGetStreak` unit class (struct-on-row, raises-when-absent) and `TestGetStreak` integration class (200 on seeded row, 404 when absent, 401 without auth).

## How It Works

The repository method (`fetch_streak`) and SDK struct (`TournamentStreakResponse`) already existed from Phase 8 — only the service method, exception, and route were missing. The endpoint reads any `user_id`'s streak; the self-only constraint (D-02) is enforced bot-side in Plan 10-03 by passing the invoker's own id (threat T-10-01 accepted: streak data is public competition stats).

## TDD Gate Compliance

- RED gate: `test(10-01)` commit `1122f87` — tests failed with `ImportError: cannot import name 'StreakNotFoundError'`.
- GREEN gate: `feat(10-01)` commit `55d36e3` — all 5 streak tests pass.
- No REFACTOR needed (implementation mirrors the existing `get_category` pattern verbatim).

## Verification

- `pytest tests/services/test_tournament_service.py -k GetStreak` — 2 passed
- `pytest tests/integration/test_tournaments_integration.py -k GetStreak` — 3 passed (200/404/401)
- `ruff format` (3 files unchanged), `ruff check` (all passed), `basedpyright` (0 errors) on the three source files.

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None.

## Self-Check: PASSED

- SUMMARY.md present
- Commits 1122f87 (RED), 55d36e3 (GREEN) present in git log
