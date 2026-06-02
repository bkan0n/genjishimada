---
phase: 12-overhaul-of-tournaments
plan: 03
subsystem: tournaments-service-outbox
tags: [service, outbox, grid-time, edition, pause-hiatus, idempotency, tdd]
requires:
  - "12-01 (migration 0024: editions, global config, next_grid_boundary(), edition_rollover payload {results, started, edition_id})"
  - "12-02 (SDK TournamentRolloverEvent/TournamentEditionResponse/TournamentLifecycleResponse; repo create_edition/create_cycle_for_edition/fetch_active_edition/global setters/create_pending_transition(edition_id))"
provides:
  - "TournamentService.bootstrap_edition (grid-snapped, no stored now()) — one edition + one child cycle per active category + ONE start-only edition_rollover outbox row"
  - "Global TournamentService.set_transitions_paused/set_debug_cycle_length (config-level, production guard preserved)"
  - "TournamentService.fetch_active_edition wrapper (Plan 04 GET /editions/active binds to it — three-layer)"
  - "Outbox publish_pending_transitions: ONE TournamentRolloverEvent per rollover keyed by tournament:rollover:{edition_id}; reward side-effects per child cycle"
  - "Repo next_grid_boundary() + is_valid_timezone() raw-SQL helpers"
  - "InvalidTimezoneError domain exception (anchor_tz validation, T-12-04)"
affects:
  - "12-04 (routes bind bootstrap_edition + global setters + fetch_active_edition → GET /editions/active; re-paths pause/debug to config-level)"
  - "12-05 (bot consumes the single TournamentRolloverEvent on api.tournament.rollover)"
tech-stack:
  added: []
  patterns:
    - "grid-snapped bootstrap: now() consulted only to pick the boundary via next_grid_boundary(), never stored (D-08/D-13a)"
    - "single combined outbox row → one publish keyed by edition_id; reward/streak per child cycle (Pattern 4)"
    - "publish-before-mark FOR UPDATE SKIP LOCKED loop preserved; deferred publish_xp_events after commit (CR-02)"
    - "deprecated cross-wave shims (bootstrap_cycle) to keep routes type-clean until 12-04"
key-files:
  created: []
  modified:
    - apps/api/services/tournament_service.py
    - apps/api/services/tournament_outbox_service.py
    - apps/api/tests/services/test_tournament_lifecycle.py
    - apps/api/tests/repository/tournaments/test_outbox_poller.py
    - apps/api/repository/tournaments_repository.py
    - apps/api/services/exceptions/tournaments.py
    - apps/api/routes/v3/tournaments.py
    - apps/api/tests/integration/test_tournament_rewards.py
decisions:
  - "bootstrap_edition computes period DB-side via next_grid_boundary(now(),...) and stores the returned grid value; now() never stored into started_at/ends_at (D-08/D-13a)"
  - "Single idempotency key tournament:rollover:{edition_id} (D-11); reward side-effects iterate event.results keyed on entry.cycle_id (D-10/Pattern 4)"
  - "Pause = hiatus (suppress next edition); resume does not itself create an edition (D-12)"
  - "Added repo next_grid_boundary/is_valid_timezone helpers (three-layer: raw SQL stays in repo) — outside files_modified but required for the service to honor CLAUDE.md no-raw-SQL-in-service"
  - "Kept deprecated bootstrap_cycle shim + thin route updates so just lint-api stays clean until 12-04 re-paths the routes"
metrics:
  duration: ~15m
  completed: 2026-06-01
  tasks: 2
  files: 8
---

# Phase 12 Plan 03: Service + Outbox Edition Re-wiring Summary

Re-wired the tournament service and outbox publisher to the single-edition
grid-anchored model. The service now bootstraps ONE grid-snapped edition (the
start comes from `next_grid_boundary()`; `now()` is consulted only to pick the
boundary and is NEVER stored — the drift fix), moves pause/debug off categories
onto the global config (pause = hiatus, production guard preserved), and exposes
the `fetch_active_edition` wrapper Plan 04's `GET /editions/active` depends on.
The outbox collapses to ONE `TournamentRolloverEvent` per rollover keyed by
`edition_id`, with reward/streak side-effects retained per child cycle.

## What Was Built

- **`bootstrap_edition`** (replaces per-category `bootstrap_cycle`): on one acquired
  connection + transaction it (1) refuses if an active edition already exists, (2)
  derives the period (debug_cycle_seconds wins; else weekly/biweekly), (3) computes
  the grid-snapped `started_at` via the repo `next_grid_boundary()` helper, (4)
  `create_edition(started_at, started_at+period)`, (5) creates one ACTIVE child
  cycle per active category via `create_cycle_for_edition` sharing the edition's
  exact start, and (6) writes ONE start-only `edition_rollover` outbox row
  (`results=[]`, `started=[...]`). Source gate: no `now()` is stored into any
  edition/cycle timestamp (it appears only as the `p_from` argument to
  `next_grid_boundary`).
- **Global `set_transitions_paused(paused)` / `set_debug_cycle_length(seconds)`**:
  call the global repo setters and return `TournamentLifecycleResponse`. The debug
  lever keeps the `APP_ENVIRONMENT == 'production'` reject verbatim (T-12-07),
  before any DB mutation. Pause is documented as a hiatus lever (D-12).
- **`fetch_active_edition() -> TournamentEditionResponse | None`**: thin Service
  wrapper over the repo method (three-layer; the Plan 04 route must not call the
  repo directly).
- **`update_config`** extended to apply the new `cadence`/`anchor_weekday`/
  `anchor_time`/`anchor_tz` PATCH fields, validating `anchor_tz` against
  `pg_timezone_names` before persisting (T-12-04) — a bad tz would otherwise crash
  the grid PL/pgSQL `AT TIME ZONE` on every cron tick.
- **Outbox `publish_pending_transitions`**: `_EVENT_ROUTING` collapsed to one entry
  (`edition_rollover` → `api.tournament.rollover` / `TournamentRolloverEvent`). The
  `(event_type, created_at)` grouping is gone — one row → one publish. Idempotency
  key is `tournament:rollover:{edition_id}` (D-11). Reward side-effects iterate
  `event.results`, calling `award_cycle_end(entry, conn)` + `_reset_non_participant_streaks`
  ONCE PER ENTRY keyed on `entry.cycle_id` (Pattern 4 — not re-keyed to the edition).
  Preserved verbatim: the `FOR UPDATE SKIP LOCKED` publish-before-mark loop, the
  `msgspec.convert(payload, TournamentRolloverEvent)` round-trip (Pitfall 5), and
  the deferred `publish_xp_events` after commit (CR-02).
- **Repo helpers** (`next_grid_boundary`, `is_valid_timezone`) — raw SQL kept in the
  repository layer per CLAUDE.md (no raw SQL in services).
- **`InvalidTimezoneError`** domain exception.
- **Routes**: thin compatibility updates — `bootstrap_cycle` handler now returns
  `TournamentEditionResponse` and delegates to the deprecated `bootstrap_cycle`
  shim; pause/debug handlers drop the ignored `category_id` from the service call.
  (12-04 re-paths these to config-level.)

## TDD Gate Compliance

Both tasks were executed RED → GREEN:
- Task 1: `test(12-03)` 853ba04 (13 failing service tests) → `feat(12-03)` cc5ba0c.
- Task 2: `test(12-03)` 956e7e5 (7 failing outbox tests) → `feat(12-03)` 0922ce6.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Service cannot run grid SQL without raw SQL in the service layer**
- **Found during:** Task 1 (bootstrap_edition needs `tournaments.next_grid_boundary`).
- **Issue:** Computing the grid-snapped start requires a raw `SELECT
  tournaments.next_grid_boundary(...)`; CLAUDE.md forbids raw SQL in services
  (three-layer). The repo had no such method (not in this plan's `files_modified`).
- **Fix:** Added `next_grid_boundary()` (delegates to the 0024 PL/pgSQL fn, binds
  `now()` as `p_from`) and `is_valid_timezone()` (checks `pg_timezone_names`) to
  `tournaments_repository.py`.
- **Files modified:** `apps/api/repository/tournaments_repository.py`
- **Commit:** cc5ba0c

**2. [Rule 2 - Security] anchor_tz not validated before persist (T-12-04)**
- **Found during:** Task 1 (threat register assigns `mitigate` to invalid anchor_tz).
- **Issue:** A bad `anchor_tz` would crash the grid `AT TIME ZONE` on every cron
  tick (DoS of transitions). No validation existed.
- **Fix:** Added `InvalidTimezoneError` and validated `anchor_tz` against
  `pg_timezone_names` in `update_config` before persisting.
- **Files modified:** `apps/api/services/exceptions/tournaments.py`,
  `apps/api/services/tournament_service.py`
- **Commit:** cc5ba0c

**3. [Rule 3 - Blocking] Routes referenced the old per-category service signatures (lint gate)**
- **Found during:** Task 1 (`just lint-api` is a required gate).
- **Issue:** `routes/v3/tournaments.py` called `bootstrap_cycle(category_id) ->
  TournamentCycleResponse` and `set_transitions_paused(category_id, paused)` /
  `set_debug_cycle_length(category_id, seconds)`; the new global signatures broke
  basedpyright. Routes are 12-04's territory.
- **Fix:** Kept a deprecated `bootstrap_cycle` shim (delegates to `bootstrap_edition`,
  ignores `category_id`) and made minimal route-handler edits (return
  `TournamentEditionResponse`, drop `category_id` from pause/debug calls) so the
  controller binds the new surface; 12-04 re-paths.
- **Files modified:** `apps/api/services/tournament_service.py`,
  `apps/api/routes/v3/tournaments.py`
- **Commit:** cc5ba0c

**4. [Rule 1 - Bug] Outbox rewrite broke the reward integration tests**
- **Found during:** wave-merge full-suite run.
- **Issue:** `tests/integration/test_tournament_rewards.py` seeds `cycle_completed`
  outbox rows and drives `publish_pending_transitions`; dropping `cycle_completed`
  routing made the poll raise `KeyError: 'cycle_completed'`. The breakage was
  directly caused by this plan's Task 2 change; the reward/streak/ledger behavior
  under test is preserved (it now arrives via an `edition_rollover` row's `results`).
- **Fix:** `_seed_completed_transition` now seeds an `edition_rollover` row
  (throwaway edition for the FK + idempotency key) wrapping the completed entry in
  `results`; `_clear_unpublished_except` scopes its purge via a `payload->'results'`
  containment check (our rollover row has `cycle_id` NULL).
- **Files modified:** `apps/api/tests/integration/test_tournament_rewards.py`
- **Commit:** 79d4f5f

## Deferred Issues (out of scope — pre-existing, not caused by this plan)

35 full-suite failures remain, ALL pre-existing at this plan's base (12-02 tip) or
documented flakes — none are regressions from Task 1/Task 2. Logged in
`deferred-items.md`:
- `tests/integration/test_tournaments_integration.py` (27) — every failure traces to
  `create_category` still binding the dropped `cycle_frequency` column (`POST
  /categories` 500). Fully resolving requires reshaping the category SDK structs
  (`cycle_frequency` → global `cadence`) + repo + integration assertions, spanning
  the SDK (12-02) and route (12-04) waves; NOT directly caused by this plan and not
  in its `files_modified`.
- `tests/repository/tournaments/test_cycle_transitions.py` (5) — invoke the removed
  `process_cycle_transitions()` + `cycle_frequency`; edition behavior is covered by
  `test_edition_transitions.py`. Deferred-by-design (12-01 doc).
- `tests/repository/tournaments/test_lifecycle_control.py` (2) — per-category repo
  shims now return the config singleton (dict), not None. Deferred-by-design.
- `tests/repository/maps/test_maps_repository_fetch_maps.py::...test_filter_by_single_category`
  (1) — documented `-n 4` parallel flake (MEMORY); passes in isolation (verified).

## Authentication Gates

None.

## Verification

- TDD RED gates: 853ba04 (13 failing service tests), 956e7e5 (7 failing outbox tests).
- Targeted suite (plan verification):
  `pytest tests/services/test_tournament_service.py tests/services/test_tournament_lifecycle.py tests/repository/tournaments/test_outbox_poller.py` → **46 passed**.
- Reward integration suite: `tests/integration/test_tournament_rewards.py` → **5 passed**.
- Source gates: `grep "next_grid_boundary" tournament_service.py` present; `now()` in
  the service appears only in docstring/comments + as `next_grid_boundary`'s `p_from`,
  never stored. `grep "tournament:rollover:" tournament_outbox_service.py` present;
  `api.tournament.rollover` present; no `TournamentCyclesStartedEvent`/`...Completed`/
  `cycles_started`/`cycles_completed`/`_SINGLE_EVENT_STRUCT`/`_TransitionGroup` remain.
- Lint: `just lint-api` clean (ruff format + ruff check + basedpyright 0 errors).
- Full suite (`pytest -n 4 --no-testmon`): **35 failed / 1754 passed / 2 skipped /
  4 xfailed** — all 35 failures are the deferred-by-design set + 1 known flake; none
  are regressions (the plan's two task files and the directly-impacted reward tests
  are green).

## Threat Flags

None — no new security surface beyond the plan's threat register. T-12-07
(production debug guard) preserved; T-12-04 (invalid anchor_tz) mitigated via
`is_valid_timezone`/`InvalidTimezoneError`; T-12-08 (duplicate rollover) mitigated
via the single `tournament:rollover:{edition_id}` key + unchanged
publish-before-mark loop + the `xp_grants` ledger; T-12-03 (bootstrap now() leak)
mitigated (grep gate).

## Self-Check: PASSED
