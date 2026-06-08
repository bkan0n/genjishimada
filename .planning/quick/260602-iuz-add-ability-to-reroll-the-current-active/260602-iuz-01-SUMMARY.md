---
phase: quick-260602-iuz
plan: 01
subsystem: api
tags: [tournaments, reroll, asyncpg, msgspec, discord, rabbitmq, litestar]

# Dependency graph
requires:
  - phase: feat/tournaments-pr (Phase 4/10/12.1)
    provides: tournament editions/cycles model, fetch_active_cycle, create_cycle_for_edition, api.tournament.rollover pipeline, /tournament-reroll command
provides:
  - Active-cycle reroll API (POST /tournaments/categories/{id}/reroll-active)
  - reroll_active_cycle service (scoped wipe + preserved-window recreate + rollover announce)
  - delete_cycle_completions / fetch_active_cycle_with_map / fetch_edition repo methods
  - reroll_active_cycle bot API client + cycle target param on /tournament-reroll
  - RerollTarget SDK Literal alias
affects: [tournaments, bot-tournament-commands, tournament-rollover-consumer]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Active-cycle reroll mirrors reroll_map but reads/preserves the parent edition's timing window (edition owns the deadline; cycle row has no ends_at)"
    - "Post-commit rollover publish with reroll-scoped idempotency_key, headers threaded from request so X-PYTEST-ENABLED no-ops under tests"

key-files:
  created: []
  modified:
    - apps/api/repository/tournaments_repository.py
    - apps/api/services/tournament_service.py
    - apps/api/routes/v3/tournaments.py
    - apps/bot/extensions/api_service.py
    - apps/bot/extensions/tournaments.py
    - libs/sdk/src/genjishimada_sdk/tournaments.py
    - apps/api/tests/integration/test_tournaments_integration.py
    - apps/api/tests/bot/test_tournament_commands.py

key-decisions:
  - "Extended existing /tournament-reroll with a cycle Literal[upcoming,current] param (default upcoming) — upcoming path byte-for-byte unchanged"
  - "Reused NoCycleActiveError for the 404 instead of adding a new exception (its message already fits)"
  - "Reused create_cycle_for_edition for the replacement active cycle (re-attaches to the SAME edition, preserves started_at/ends_at)"
  - "Explicit delete_cycle_completions BEFORE delete_cycle even though the FK cascades — makes the destructive wipe observable and order-safe re: core.completions ON DELETE SET NULL"
  - "current + explicit code is rejected with a clean UserFacingError (out-of-scope/ambiguous); the random active reroll is the must-have"

patterns-established:
  - "Active reroll = wipe scoped completions -> delete cycle -> reuse eligibility/LRU -> create_cycle_for_edition(preserved started_at) -> post-commit TournamentRolloverEvent(results=[], started=[event])"

requirements-completed: [IUZ-REROLL-ACTIVE]

# Metrics
duration: ~75min
completed: 2026-06-02
---

# Quick Task 260602-iuz Plan 01: Reroll the current (active) tournament cycle Summary

**Mods can now reroll the LIVE tournament cycle via `/tournament-reroll cycle:current` — the active cycle's submissions are wiped (scoped by cycle id), a new eligible map is swapped in on the SAME edition (deadline preserved, never reset), and the live channel is announced via the existing `api.tournament.rollover` event.**

## Performance

- **Duration:** ~75 min
- **Completed:** 2026-06-02T18:55:55Z
- **Tasks:** 3/3
- **Files modified:** 8

## Accomplishments
- Added the full three-layer API path for active-cycle reroll (repo wipe/read methods, `reroll_active_cycle` service, `POST /reroll-active` route) with TDD integration coverage proving the map swaps, the edition window is preserved, the submission wipe is scoped to the rerolled cycle only, and a missing active cycle returns 404.
- Extended the `/tournament-reroll` bot command with a `cycle` target (default `upcoming`, byte-for-byte unchanged) that dispatches the `current` path to `reroll_active_cycle`, keeps the authoritative Mod/Sensei gate ahead of every API call, and rejects an explicit code for the current cycle.
- Ran the TRUE no-testmon full suite and all three linters; my 12 new tests pass and there are zero NEW failures.

## Task Commits

Each task was committed atomically (code/tests only; docs handled by the orchestrator):

1. **Task 1: API layer — repo wipe/create + reroll_active_cycle service + route** - `5b3f06e` (feat)
2. **Task 2: Bot layer — client method + cycle target param** - `51afde7` (feat)
3. **Task 3: TRUE full-suite + lint gate** - verification-only, no source changes (no commit)

_Note: Tasks 1 & 2 were TDD (RED tests written first, then implemented to green); each was committed as a single feat commit containing the new tests + implementation._

## Files Created/Modified
- `apps/api/repository/tournaments_repository.py` — added `delete_cycle_completions(cycle_id)` (deliberate scoped wipe, `WHERE cycle_id=$1`), `fetch_active_cycle_with_map(category_id)` (joined read for the response), `fetch_edition(edition_id)` (read preserved window).
- `apps/api/services/tournament_service.py` — added `reroll_active_cycle(category_id, *, headers)`: atomic wipe + delete + eligibility/LRU select + `create_cycle_for_edition(preserved started_at)`, then post-commit `TournamentRolloverEvent(results=[], started=[started_event])` publish with `idempotency_key=f"tournament:active-reroll:{new_cycle_id}"`.
- `apps/api/routes/v3/tournaments.py` — added `POST /categories/{id}/reroll-active` (404 on CategoryNotFound/NoCycleActive, 422 on NoEligibleMaps), threading `request.headers` to the service.
- `apps/bot/extensions/api_service.py` — added `reroll_active_cycle(category_id)` client -> `POST /reroll-active`.
- `apps/bot/extensions/tournaments.py` — added `cycle: Literal["upcoming","current"]` param to `/tournament-reroll`; current dispatches to `reroll_active_cycle`, rejects explicit code, heading switches to "Current-Cycle Map Updated"; gate unchanged and runs before any API call.
- `libs/sdk/src/genjishimada_sdk/tournaments.py` — added `RerollTarget = Literal["upcoming","current"]` and exported it.
- `apps/api/tests/integration/test_tournaments_integration.py` — `TestRerollActiveEndpoint` (swap+preserved window, scoped wipe vs unrelated cycle, 404 no active) + `_seed_active_edition_cycle` helper.
- `apps/api/tests/bot/test_tournament_commands.py` — default-upcoming unchanged, current->reroll_active_cycle, current+code rejected, gate blocks current path + `_active_cycle` helper.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing critical functionality] Guard against a NULL/None edition link on the active cycle**
- **Found during:** Task 1 (basedpyright flagged `Object of type "None" is not subscriptable` on `fetch_edition`).
- **Issue:** A live active cycle could in principle have a NULL `edition_id` (legacy `create_active_cycle` rows without an edition link); subscripting the `fetch_edition` result would crash, and there would be no preservable window.
- **Fix:** If `edition_id is None` or the edition row is missing, raise `NoCycleActiveError(category_id)` (mapped to 404) — there is no rerollable active edition window. Keeps the path correct and type-safe.
- **Files modified:** `apps/api/services/tournament_service.py`
- **Commit:** `5b3f06e`

### Plan assumption adapted

- The plan suggested optionally adding `ActiveCycleNotFoundError`. The existing `NoCycleActiveError(category_id)` ("No active cycle exists for this category.") already fits the 404, so no new exception was added (plan explicitly allowed reuse — "executor's discretion, keep it minimal").
- The plan referenced `create_cycle_for_edition(edition_id, category_id, map_id, started_at)` — confirmed against real code and used as-is (it INSERTs `status='active'` with the edition link and inherited `started_at`).

## Deferred Issues (out of scope — NOT regressions)

The TRUE no-testmon full suite (`pytest -n 4 --no-testmon`) surfaced **4 pre-existing failures**, all **proven to fail identically at the base commit `5d4e850`** with zero IUZ changes present (verified by checking out base versions of the source/test files and re-running):

- `tests/bot/test_tournaments_handler.py::test_verification_changed_surfaces_verdict`
- `tests/bot/test_tournaments_handler.py::test_rollover_normal_renders_both_sections_and_transfers_champion`
- `tests/bot/test_tournaments_handler.py::test_on_edition_results_empty_standings_posts_no_winner_card_no_transfer`
- `tests/bot/test_tournament_commands.py::test_info_renders_card_for_active_cycle`

Root cause: the `feat/tournaments-pr` branch deliberately dropped the per-run verdict / adjusted announcement-card copy (commit `d2554d6` "drop per-run verification verdict message") without updating these bot-handler tests. Unrelated to active-cycle reroll. Logged in `deferred-items.md`; recommend a follow-up to reconcile those tests with the current card/announcement copy.

The documented pre-existing flakes from project memory (`test_difficulty_exact_filter`, `test_filter_by_single_category` under `-n 4`) did not surface as failures in this run.

## Threat Surface

The threat register dispositions were honored:
- **T-iuz-01 (EoP):** Mod/Sensei `is_mod` gate runs before any API call on the active path (bot unit test `test_reroll_gate_rejects_non_admin_on_current_path` asserts no API write).
- **T-iuz-02 (Tampering/DoS):** `delete_cycle_completions` is scoped strictly by `cycle_id`; integration test proves an unrelated cycle's completions survive; `core.completions` rows preserved via the existing `ON DELETE SET NULL` FK.
- **T-iuz-04 (Tampering):** rollover published post-commit with `idempotency_key=tournament:active-reroll:{new_cycle_id}` (consumer is idempotent).

No new security surface beyond the planned threat model.

## Self-Check: PASSED

- FOUND: `260602-iuz-01-SUMMARY.md`
- FOUND: `deferred-items.md`
- FOUND commit `5b3f06e` (Task 1 API layer)
- FOUND commit `51afde7` (Task 2 bot layer)
- FOUND `reroll_active_cycle` service method, `reroll-active` route, bot client method
