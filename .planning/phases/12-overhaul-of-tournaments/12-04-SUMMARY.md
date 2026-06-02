---
phase: 12-overhaul-of-tournaments
plan: 04
subsystem: tournaments-routes
tags: [routes, litestar, scope-guard, edition-read, config-level, cycle-frequency-cleanup]
requires:
  - "12-02 (SDK TournamentEditionResponse, global cadence/anchor/pause/debug structs, TournamentLifecycleResponse)"
  - "12-03 (service bootstrap_edition, global set_transitions_paused/set_debug_cycle_length, set_cadence/set_anchor via update_config, fetch_active_edition; InvalidTimezoneError; production debug guard)"
provides:
  - "Config-level mutation routes: PATCH /tournaments/pause + PATCH /tournaments/debug-cycle-length (global, tournaments:write); cadence/anchor via PATCH /tournaments/config"
  - "POST /tournaments/bootstrap (config-level, tournaments:write) -> bootstrap_edition"
  - "GET /tournaments/editions/active (tournaments:read) -> fetch_active_edition, surfacing stored started_at/ends_at (D-05/D-08)"
  - "NoActiveEditionError domain exception (404 mapping)"
  - "cycle_frequency removed from category SDK structs + repo create_category + service create/update (cadence is GLOBAL since 0024)"
  - "Bot api.get_active_edition + /tournament info reads stored edition ends_at"
affects:
  - "12-05 (bot rollover consumer; bot info already reads stored edition ends_at)"
  - "frontend (frontend-spec §8: ends_at is now a stored read on GET /editions/active, not derived)"
tech-stack:
  added: []
  patterns:
    - "thin controller -> service; every config MUTATION declares opt={required_scopes: {tournaments:write}}, reads tournaments:read"
    - "per-cycle endpoints kept cycle-scoped (A5): /cycles, /cycles/{id}/leaderboard, /categories/{id}/next-cycle unchanged"
    - "stored edition timing read replaces client-side derivation (D-08, frontend-spec §8)"
    - "scoped non-superuser token fixture proves wrong-scope rejection (the seeded testing token is superuser)"
key-files:
  created:
    - apps/api/tests/integration/test_config_tournament.py
  modified:
    - apps/api/routes/v3/tournaments.py
    - apps/api/services/exceptions/tournaments.py
    - apps/api/services/tournament_service.py
    - apps/api/repository/tournaments_repository.py
    - libs/sdk/src/genjishimada_sdk/tournaments.py
    - apps/bot/extensions/api_service.py
    - apps/bot/extensions/tournaments.py
    - apps/api/tests/integration/test_tournaments_integration.py
    - apps/api/tests/repository/tournaments/test_tournaments_repository.py
    - apps/api/tests/bot/test_tournament_commands.py
    - apps/api/tests/bot/conftest.py
decisions:
  - "Pause/debug moved to dedicated config-level routes (PATCH /pause, PATCH /debug-cycle-length); cadence/anchor flow through the existing PATCH /config (update_config already wired them in 12-03)"
  - "GET /editions/active returns 404 (NoActiveEditionError) when no edition is active, since the shared timing only exists while running"
  - "InvalidTimezoneError -> 422 on PATCH /config (validation), DebugRouteDisabledError -> 403 (production guard preserved)"
  - "cycle_frequency cleanup (the 12-04-owned deferred item) completed here: dropped from SDK category structs + repo + service, fixing the 26 POST /categories 500 cascade and un-xfailing repo TestCreateCategory"
  - "Bot /tournament info reads the stored edition ends_at via new get_active_edition instead of deriving from cadence (D-08); a 404 omits the Ends line gracefully"
metrics:
  duration: ~40m
  completed: 2026-06-01
  tasks: 1
  files: 12
---

# Phase 12 Plan 04: Config-Level Tournament Mutations + Edition Read Summary

Re-pathed tournament configuration mutation off the per-category routes onto
global config-level routes and added the edition read surface the frontend needs.
Pause and debug-cycle-length are now `PATCH /tournaments/pause` and
`PATCH /tournaments/debug-cycle-length`; cadence/anchor mutate through the existing
`PATCH /tournaments/config`; bootstrap is the config-level `POST /tournaments/bootstrap`.
`GET /tournaments/editions/active` exposes the single active edition's STORED
`started_at`/`ends_at` (D-05/D-08), so the frontend (and the bot) stop deriving
`ends_at` from cadence — closing frontend-spec §8. Every config mutation keeps its
`tournaments:write` scope guard; the edition read uses `tournaments:read`. The
plan-owned `cycle_frequency` cleanup (cadence is global since migration 0024) was
also completed, resolving the 26-test `POST /categories` 500 cascade.

## What Was Built

- **`routes/v3/tournaments.py`**
  - `POST /bootstrap` (config-level, was `/categories/{id}/bootstrap`) → `bootstrap_edition()`; 409 if an active edition exists, 422 on no eligible maps.
  - `PATCH /pause` (config-level, was `/categories/{id}/pause`) → `set_transitions_paused(paused)`, returns `TournamentLifecycleResponse`.
  - `PATCH /debug-cycle-length` (config-level, was `/categories/{id}/debug-cycle-length`) → `set_debug_cycle_length(seconds)`; `DebugRouteDisabledError` → 403 (T-12-07).
  - `PATCH /config` now maps `InvalidTimezoneError` → 422 (T-12-10) and carries cadence (D-02) + anchor (D-07) mutation (the service `update_config` wired them in 12-03).
  - `GET /editions/active` (tournaments:read) → `fetch_active_edition()`, returns `TournamentEditionResponse`; 404 (`NoActiveEditionError`) when none active (D-05/D-08).
  - Per-cycle endpoints unchanged and cycle-scoped (A5): `/cycles`, `/cycles/{id}/leaderboard`, `/categories/{id}/next-cycle`, select/reroll/choose.
  - All four config mutations declare `opt={"required_scopes": {"tournaments:write"}}`; the edition read declares `tournaments:read` (T-12-09).
- **`services/exceptions/tournaments.py`**: added `NoActiveEditionError` (404 mapping for the edition read).
- **NEW `tests/integration/test_config_tournament.py`** (16 tests): a `read_only_client` fixture seeds a NON-superuser token holding only `tournaments:read` (the seeded `testing` token is a superuser and bypasses scope checks). Asserts every config mutation rejects unauthenticated (401) and wrong-scope (401/403) callers and accepts a write-scope caller; the debug route is rejected in a production-simulated env (`monkeypatch APP_ENVIRONMENT=production` → 403); an invalid anchor_tz → 422; `GET /editions/active` requires auth and returns the STORED started_at + ends_at (verbatim, not derived) and 404 when no edition is active.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `create_category` 500 cascade — the 12-04-owned `cycle_frequency` cleanup**
- **Found during:** Task 1 verification — the verify command runs `test_tournaments_integration.py`, where 26 tests failed because `POST /categories` returned 500 (`UndefinedColumnError: column "cycle_frequency" of relation "categories" does not exist`). Migration 0024 dropped per-category `cycle_frequency` (cadence is global), but the SDK category structs + repo `create_category` + service still bound it. `deferred-items.md` explicitly assigns this cleanup to **12-04 (the route wave)**.
- **Fix:** Dropped `cycle_frequency` from `TournamentCategoryResponse` / `…CreateRequest` / `…PatchRequest`, the repo `create_category` INSERT (and its params), and the service `create_category` / `update_category`. Updated the integration assertions (`cycle_frequency` no longer in the response) and un-xfailed the repo `TestCreateCategory`.
- **Files modified:** `libs/sdk/.../tournaments.py`, `repository/tournaments_repository.py`, `services/tournament_service.py`, `tests/integration/test_tournaments_integration.py`, `tests/repository/tournaments/test_tournaments_repository.py`
- **Commit:** 5156f19

**2. [Rule 3 - Blocking] SDK struct change broke the bot at runtime + lint**
- **Found during:** Task 1 (dropping `TournamentCategoryResponse.cycle_frequency` broke `apps/bot/extensions/tournaments.py:632`, which derived the cycle `ends_at` from `category_data.cycle_frequency` — the exact frontend-spec §8 anti-pattern this plan closes). A required `TournamentCategoryResponse` field cannot just be left on the struct because the DB row no longer has the column (`msgspec.convert` would fail).
- **Fix:** Added `api.get_active_edition()` to the bot `APIService` (binds `GET /tournaments/editions/active`) and rewired `/tournament info` to read the STORED edition `ends_at` (D-08), wrapping a 404 to gracefully omit the Ends line. Removed the now-unused `datetime as dt` import. Updated the bot test + conftest fixtures (dropped `cycle_frequency`, mocked `get_active_edition`).
- **Files modified:** `apps/bot/extensions/api_service.py`, `apps/bot/extensions/tournaments.py`, `tests/bot/test_tournament_commands.py`, `tests/bot/conftest.py`
- **Commit:** 5156f19

## Deferred Issues (out of scope — pre-existing, not caused by this plan)

7 full-suite failures remain, ALL deferred-by-design from the 12-03 base and NOT
in this plan's `files_modified` (logged in `deferred-items.md`):

- `tests/repository/tournaments/test_cycle_transitions.py` (5) — invoke the removed
  `tournaments.process_cycle_transitions()` + `cat.cycle_frequency`; edition behavior
  is covered by `test_edition_transitions.py`.
- `tests/repository/tournaments/test_lifecycle_control.py::TestSetCategoryPaused`,
  `TestSetCategoryDebugCycleSeconds` (2 `*_returns_none`) — per-category shims return
  the config singleton, not None; covered by `test_tournament_lifecycle.py`.

Net: the full API suite went from 35 failing (12-03 tip) to **7 failing** — this
plan resolved 28 (26 integration + 2 repo xfails) and introduced none.

## Frontend-Spec Flag (for /gsd-transition)

frontend-spec §8 is CLOSED on the API: the stored edition `ends_at` is now read via
`GET /api/v3/tournaments/editions/active` (`TournamentEditionResponse.ends_at`). The
frontend MUST stop deriving `ends_at` from started_at + cadence and read it from this
endpoint. The bot was already migrated to this read in `/tournament info`.

## Authentication Gates

None.

## Verification

- Targeted (plan verify): `pytest tests/integration/test_tournaments_integration.py tests/integration/test_config_tournament.py --no-testmon -p no:xdist` → **60 passed, 1 xfailed** (the xfail is the pre-existing CR-01 reject integration test).
- New file collected: `tests/integration/test_config_tournament.py` → **16 passed** in isolation.
- Source gate: `grep -n required_scopes routes/v3/tournaments.py` — `/config` PATCH, `/bootstrap`, `/pause`, `/debug-cycle-length` all declare `tournaments:write`; `/editions/active` declares `tournaments:read`.
- Adjacent suites: `test_tournaments_repository.py` + `test_tournaments_schema.py` + `test_tournament_commands.py` → **80 passed**; `test_tournament_service.py` + `test_tournaments_handler.py` → **39 passed**.
- Lint: `just lint-api` clean (ruff format + check + basedpyright 0 errors); `just lint-sdk` clean; `just lint-bot` clean.
- Wave-merge full suite: `pytest -n 4 --no-testmon` → **7 failed / 1800 passed / 2 skipped / 2 xfailed** — all 7 failures are the documented deferred-by-design set; none are regressions.

## Threat Flags

None — no new security surface beyond the plan's threat register. T-12-09
(scope guard on every config mutation) verified by source gate + integration tests;
T-12-07 (production debug guard) → 403 covered; T-12-10 (invalid anchor_tz) → 422
covered.

## Self-Check: PASSED

- Files: `routes/v3/tournaments.py`, `tests/integration/test_config_tournament.py`,
  `services/exceptions/tournaments.py`, SDK `tournaments.py`, bot `api_service.py` /
  `tournaments.py` — all present.
- Commit: 5156f19 — FOUND.
