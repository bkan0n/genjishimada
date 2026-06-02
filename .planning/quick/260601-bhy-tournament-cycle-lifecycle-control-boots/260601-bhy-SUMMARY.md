---
phase: quick-260601-bhy
plan: 01
subsystem: tournaments
tags: [tournaments, cycle-lifecycle, pg_cron, admin, debug]
requires:
  - tournaments schema (migrations 0020-0022)
  - tournaments.process_cycle_transitions() (migration 0021)
provides:
  - tournaments.categories.transitions_paused + debug_cycle_seconds columns
  - debug-aware / pause-aware process_cycle_transitions()
  - bootstrap / pause / debug-cycle-length admin routes
affects:
  - apps/api/migrations
  - libs/sdk tournaments structs
  - tournaments repository / service / controller
tech-stack:
  added: []
  patterns:
    - additive migration (nullable/defaulted columns + CREATE OR REPLACE function)
    - TOCTOU-safe single-connection transaction for bootstrap + outbox write
    - production-gated debug route via APP_ENVIRONMENT
key-files:
  created:
    - apps/api/migrations/0023_tournament_cycle_lifecycle_control.sql
    - apps/api/tests/repository/tournaments/test_lifecycle_control.py
    - apps/api/tests/services/test_tournament_lifecycle.py
  modified:
    - libs/sdk/src/genjishimada_sdk/tournaments.py
    - apps/api/services/exceptions/tournaments.py
    - apps/api/repository/tournaments_repository.py
    - apps/api/services/tournament_service.py
    - apps/api/routes/v3/tournaments.py
decisions:
  - "Bootstrap creates an ACTIVE cycle + writes the same cycle_started outbox row the pg_cron promote-pending branch writes, so the existing outbox poller publishes it unchanged."
  - "Debug cycle-length route gated behind tournaments:write AND non-production APP_ENVIRONMENT (D-DEBUG); 403 in production."
  - "Pause is a DB-state flag checked inside process_cycle_transitions() (AND cat.transitions_paused = FALSE) — no pg_cron job manipulation; started_at preserved so resume naturally resumes cadence."
metrics:
  duration: ~25m
  completed: 2026-06-01
---

# Phase quick-260601-bhy Plan 01: Tournament Cycle Lifecycle Control Summary

Adds admin-only bootstrap, pause/resume, and debug cycle-length-override controls to the tournaments cycle lifecycle, backed by an additive migration (0023) that teaches `process_cycle_transitions()` to skip paused categories and honor a per-category seconds override while leaving non-paused, non-debug behavior identical to 0021.

## What Was Built

**Task 1 — Migration 0023 (`feat` 0a4e66a)**
- Additive columns on `tournaments.categories`: `transitions_paused boolean NOT NULL DEFAULT FALSE` and `debug_cycle_seconds int` (nullable, `CHECK > 0`), each with a `COMMENT`.
- `CREATE OR REPLACE FUNCTION tournaments.process_cycle_transitions()` copied verbatim from 0021 with exactly three edits: (a) due-detection FOR loop adds `AND cat.transitions_paused = FALSE`, selects `debug_cycle_seconds`, and uses `COALESCE(make_interval(secs => ...), make_interval(days => weekly?7:14))`; (b) promote-pending `ends_at` uses the same COALESCE; (c) inline-create (D-07) `ends_at` uses the same COALESCE. Advisory lock, placement snapshot, outbox INSERTs, and pre-roll unchanged. pg_cron registration untouched.

**Task 2 — SDK / exceptions / repository (`test` 82f846b, `feat` d84d27e)**
- SDK: `TournamentPauseRequest`, `TournamentDebugCycleLengthRequest`, `TournamentCategoryLifecycleResponse` (all registered in `__all__`, isort-sorted per RUF022).
- Exceptions: `CycleAlreadyLiveError` (carries category_id + cycle_id), `DebugRouteDisabledError`.
- Repository: `check_any_live_cycle` (active/finalizing/pending), `create_active_cycle` (FK-translating), `set_category_paused`, `set_category_debug_cycle_seconds` — all with `*, conn` injection.

**Task 3 — Service / controller (`test` 42f56bc, `feat` 0df17d6)**
- Service: `bootstrap_cycle` (TOCTOU-safe single-connection transaction: category check -> live-cycle guard -> eligible-map selection with LRU fallback -> create active cycle -> write `cycle_started` outbox row shaped exactly like `TournamentCycleStartedEvent` with a debug-aware `ends_at`); `set_transitions_paused`; `set_debug_cycle_length` (production-gated).
- Controller: `POST /categories/{id}/bootstrap` (201; 404/409/422), `POST /categories/{id}/pause` (200; 404), `PATCH /categories/{id}/debug-cycle-length` (200; 403/404). All `tournaments:write`.

## Verification (real command output)

`uv run --directory apps/api pytest tests/repository/tournaments/test_lifecycle_control.py tests/services/test_tournament_lifecycle.py --no-testmon -p no:xdist`
```
tests/repository/tournaments/test_lifecycle_control.py ..........        [ 50%]
tests/services/test_tournament_lifecycle.py ..........                   [100%]
============================== 20 passed in 1.30s ==============================
```

Regression — `uv run --directory apps/api pytest tests/repository/tournaments/test_cycle_transitions.py --no-testmon -p no:xdist`
```
collected 7 items
tests/repository/tournaments/test_cycle_transitions.py .......           [100%]
============================== 7 passed in 1.29s ===============================
```

Task 1 migration verify — `grep -v '^--' 0023_*.sql | grep -c "transitions_paused = FALSE"` => `1`.

Lint:
- `ruff check` on every file I edited (migration N/A, SDK, exceptions, repository, service, controller): **All checks passed!**
- `basedpyright` (API + SDK): **0 errors, 0 warnings, 0 notes**.

## Deviations from Plan

None affecting behavior. One mechanical adjustment:
- **[Rule 3 - Blocking] `__all__` ordering.** The plan said "add alphabetically," but the repo enforces RUF022 isort-style (case-sensitive) `__all__` sorting, which placed `TournamentDebugCycleLengthRequest` after the `TournamentCycles*` block rather than plain-alphabetically. Applied `ruff check --fix` to satisfy the linter. No API change.

## Known Issues / Pre-existing (not introduced by this work)

`just lint-api` / `just lint-sdk` report 7 `N999 Invalid module name` errors for untracked `"… 2.py"` duplicate-file artifacts (e.g. `tournaments_repository 2.py`, `tournament_service 2.py`). These are macOS/git copy artifacts present in the starting `git status` snapshot (all shown as `??` untracked), unrelated to this plan. `ruff check` and `basedpyright` on the actual files I created/modified are fully clean. I did not delete them (outside scope; destructive-file-op caution).

## Self-Check: PASSED
- Files: all 3 created files FOUND.
- Commits: 0a4e66a, 82f846b, d84d27e, 42f56bc, 0df17d6 all FOUND.
