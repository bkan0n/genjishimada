---
phase: 09-bot-queue-consumers-announcements
plan: 01
subsystem: bot-config-and-test-scaffold
tags: [bot, config, api-service, tournaments, test-scaffold, wave-0]
requires:
  - "genjishimada_sdk.tournaments.TournamentCategoryResponse (SDK, defined Phase 7)"
  - "GET /api/v3/tournaments/categories/{category_id} (API route, Phase 7)"
provides:
  - "config.channels.tournament.announcements (repointable per-environment knob, D-01)"
  - "APIService.get_tournament_category(category_id) (D-08)"
  - "apps/api/tests/bot/ package + shared fakes + config decode test + handler stubs (Wave 0)"
affects:
  - "Plan 09-02 (tournament announcement handler) consumes all three artifacts"
tech-stack:
  added: []
  patterns:
    - "msgspec Base(forbid_unknown_fields=True) config struct + matching TOML block land together"
    - "sync-return Route + _request get-by-id APIService wrapper"
    - "path-loaded bot Config module in apps/api tests (avoids utilities package collision)"
key-files:
  created:
    - apps/api/tests/bot/__init__.py
    - apps/api/tests/bot/conftest.py
    - apps/api/tests/bot/test_config_tournament.py
    - apps/api/tests/bot/test_tournaments_handler.py
  modified:
    - apps/bot/utilities/config.py
    - apps/bot/configs/dev.toml
    - apps/bot/configs/prod.toml
    - apps/bot/extensions/api_service.py
decisions:
  - "D-01: dedicated channels.tournament.announcements key initialized to existing announcements channel id per environment"
  - "D-08: thin get_tournament_category wrapper following sync-return get-by-id precedent"
  - "Wave 0: bot Config loaded by file path (registered in sys.modules) so msgspec resolves forward-ref annotations under `from __future__ import annotations`"
metrics:
  duration: 9min
  completed: 2026-05-30
---

# Phase 9 Plan 01: Bot Config + APIService Wiring & Wave 0 Test Scaffold Summary

Added the repointable `channels.tournament.announcements` config key (struct + both TOMLs), the `APIService.get_tournament_category` wrapper, and the `apps/api/tests/bot/` Wave 0 scaffolding (shared guild/role/member fakes + mock APIService, a green config-decode test, and six `-k`-selectable xfail handler stubs) that unblocks Plan 09-02.

## What Was Built

**Task 1 — Tournament config struct + TOML blocks (commit 7b94178)**
- Added `class Tournament(Base): announcements: int` and a `tournament: Tournament` field on `Channels` in `apps/bot/utilities/config.py`.
- Added `[channels.tournament] announcements = 1377808369997447254` to `dev.toml` and `= 975820285343301674` to `prod.toml` (each equal to that environment's existing `[channels.updates].announcements`, per D-01).
- Both TOMLs decode into `Config` with `forbid_unknown_fields=True` honored (struct + both blocks landed together to avoid the startup ValidationError, Pitfall 4).

**Task 2 — APIService.get_tournament_category wrapper (commit 21c9be5)**
- Added `get_tournament_category(self, category_id: int) -> Response[TournamentCategoryResponse]` building `Route("GET", "/tournaments/categories/{category_id}", category_id=category_id)` and calling `self._request(r, response_model=TournamentCategoryResponse)`, matching the sync-return get-by-id precedent (`get_upvotes_from_message_id`).
- Imported `TournamentCategoryResponse` from `genjishimada_sdk.tournaments` (new per-domain import group, isort-ordered after `tags`).
- Route verified against `apps/api/routes/v3/tournaments.py` `GET /categories/{category_id:int}` → `TournamentCategoryResponse` (scope `tournaments:read`).

**Task 3 — Wave 0 bot test package (commit 5ccf6f5, TDD)**
- Created `apps/api/tests/bot/` package: `__init__.py`, `conftest.py`, `test_config_tournament.py`, `test_tournaments_handler.py`.
- `conftest.py`: path-loads the bot `Config` module (registered in `sys.modules` so msgspec resolves forward-ref annotations), a fake guild (`get_role`/`get_member`), fake role (mutable `members`), fake member (records `add_roles`/`remove_roles` with reason), and a mock `APIService` returning a sample `TournamentCategoryResponse` + a MapModel-shaped object (`.difficulty`/`.map_name`/`.map_banner`).
- `test_config_tournament.py`: decodes both TOMLs (asserts the int announcements id per env) and asserts `forbid_unknown_fields` raises `msgspec.ValidationError` — all 3 pass green.
- `test_tournaments_handler.py`: six `@pytest.mark.xfail(strict=False)` stubs, each selectable by exactly one of `-k cycle_started|results_embed|champion_role|champion_vacant|stagger|idempotency` — collect-and-skip-red for Plan 09-02 to fill in.

## Verification Results

- Task 1: `uv run --directory apps/bot python -c "...decode dev+prod into Config..."` → `OK`.
- Task 2: `APIService` has `get_tournament_category` (import + attr check) → `OK`; `ruff check` + `ruff format --check` clean; `basedpyright` 0 errors on config.py + api_service.py.
- Task 3: `pytest tests/bot/test_config_tournament.py --no-testmon -p no:xdist` → 3 passed; `pytest tests/bot/test_tournaments_handler.py --no-testmon -p no:xdist` → 6 xfailed; each `-k` selector resolves to exactly 1 test.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Path-loaded bot Config module must be registered in sys.modules**
- **Found during:** Task 3 (first config-test run failed with `NameError: name 'Roles' is not defined`).
- **Issue:** `apps/api` and `apps/bot` both ship a `utilities` package, so importing `utilities.config` would shadow with apps/api's. Loading the bot config by file path avoided the collision, but the bot module uses `from __future__ import annotations`; msgspec resolves forward-ref struct field types via `sys.modules[cls.__module__]` at convert time, which failed because the path-loaded module was not registered.
- **Fix:** Register the loaded module in `sys.modules` under its synthetic name before `exec_module` so msgspec can resolve the forward refs.
- **Files modified:** `apps/api/tests/bot/conftest.py`
- **Commit:** 5ccf6f5

**2. [Plan-intent clarification] TDD RED phase folded into a single test commit**
- Task 3 is marked `tdd="true"`, but its only must-pass assertion (the config decode) depends on Task 1 already landing the struct+TOML. The handler stubs are intentionally xfail (RED held for Plan 09-02). A separate failing-then-passing RED/GREEN split for the config test would have been redundant since the implementation (Task 1) preceded the test. Committed as a single `test(...)` commit. Noted under TDD Gate Compliance below.

## TDD Gate Compliance

Plan type is `execute` (not a plan-level `type: tdd`); only Task 3 carries `tdd="true"`. The behavior under test (config decode) was implemented in Task 1 and verified green in Task 3; the handler behaviors remain RED (xfail) by design, to be turned GREEN in Plan 09-02. No GREEN-gate violation: the sole pass-required test passes.

## Known Stubs

The six handler stubs in `test_tournaments_handler.py` are intentional Wave 0 placeholders (xfail), to be implemented by Plan 09-02. Documented in the plan; not blocking — they do not affect runtime behavior and the suite stays green (xfailed, not failed).

## Self-Check: PASSED

- All 8 plan files present on disk (verified).
- All 3 task commits present in git history: 7b94178, 21c9be5, 5ccf6f5 (verified).
