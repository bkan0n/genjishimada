---
phase: quick-260602-dpm-bootstrap-ux
plan: 01
subsystem: tournaments
tags: [bootstrap, debug, lifecycle, transitions-paused]
requires:
  - apps/api/services/tournament_service.py::bootstrap_edition
  - apps/api/repository/tournaments_repository.py
provides:
  - "fetch_db_now() repo helper (server-now for debug bootstrap anchoring)"
  - "bootstrap_edition debug-now anchoring branch"
  - "bootstrap_edition clears transitions_paused atomically"
affects:
  - "Production bootstrap now unpauses auto-rotation (intended behavior change)"
tech-stack:
  added: []
  patterns: ["repo _get_connection conn-injection", "branch on config debug_cycle_seconds"]
key-files:
  created: []
  modified:
    - apps/api/repository/tournaments_repository.py
    - apps/api/services/tournament_service.py
    - apps/api/tests/services/test_tournament_lifecycle.py
decisions:
  - "Debug-now started_at is a deliberate, production-disabled D-08 exception (no drift; subsequent editions inherit prev.ends_at)"
  - "Bootstrap clearing transitions_paused=false is intended in production too (starting a tournament means running it)"
metrics:
  duration: ~12m
  completed: 2026-06-02
---

# Phase quick-260602-dpm Plan 01: Bootstrap UX (debug-now anchor + clear paused) Summary

Two debug-UX changes scoped strictly to `bootstrap_edition`: a `fetch_db_now()` repo helper plus a branch that anchors a debug edition at server-now, and an atomic `transitions_paused=false` clear so a single bootstrap call both starts the first edition and makes auto-rotation live.

## What Was Built

- **Task 1 — `fetch_db_now()` repo helper** (`apps/api/repository/tournaments_repository.py`, near `next_grid_boundary`): `async def fetch_db_now(self, *, conn=None) -> dt.datetime` returning `SELECT now()` (tz-aware), via `self._get_connection(conn)` so it participates in the bootstrap transaction. Google-style docstring documents it as the debug-only anchoring source and the explicit D-08 exception. Commit `5b1fd17`.
- **Task 2 — `bootstrap_edition` branch + unpause** (`apps/api/services/tournament_service.py`): branch on `config["debug_cycle_seconds"]` — if set, `started_at = await fetch_db_now(conn=conn)`; else the existing `next_grid_boundary` call is preserved byte-for-byte. `ends_at = started_at + period` in both branches. Added `await set_transitions_paused(False, conn=conn)` immediately after `create_edition`, inside the existing `async with self._pool.acquire() as conn, conn.transaction()` block, so the unpause rolls back with the edition on failure. Comments mark both the D-08 debug exception and the intended-in-prod unpause; docstring updated. Commit `8dda063`.
- **Task 3 — tests** (`apps/api/tests/services/test_tournament_lifecycle.py`): rewrote the old `test_bootstrap_ends_at_uses_debug_period` (which asserted `next_grid_boundary` received the debug period — now incorrect) into `test_bootstrap_debug_anchors_at_server_now`: asserts `create_edition` got `started_at == _DEBUG_NOW`, `ends_at == _DEBUG_NOW + 300s`, `fetch_db_now.assert_called_once()`, and `next_grid_boundary.assert_not_called()`. Added `fetch_db_now.assert_not_called()` + `next_grid_boundary.assert_called()` to the production `test_bootstrap_grid_snaps_start_no_now`. Added `test_bootstrap_clears_transitions_paused` asserting `set_transitions_paused.assert_called_once_with(False, conn=mocker.ANY)` even when config had `transitions_paused=True`. Commit `d9ec95c`.

## Production-Applicable Behavior Change (call-out)

**Bootstrapping now clears `transitions_paused` (unpauses auto-rotation) in production.** Previously a separate unpause step was required after bootstrap. This is intended (per plan + threat register T-QUICK-02, disposition *accept*): "starting a tournament means running it," gated behind the existing admin auth on the bootstrap route. The debug-now `started_at` anchoring is production-disabled (only fires when `debug_cycle_seconds` is set, which is blocked in prod), so the production timing path through `next_grid_boundary` is unchanged.

## Verification

Test command (targeted):
```
uv run --directory apps/api pytest tests/services/test_tournament_lifecycle.py -p no:xdist -v
```
Result: **14 passed in 0.16s.** Proves:
- debug-now anchoring — `test_bootstrap_debug_anchors_at_server_now` (started_at == server-now, ends_at +300s, next_grid_boundary not called).
- preserved production path — `test_bootstrap_grid_snaps_start_no_now` (grid boundary used, fetch_db_now not called) + `test_bootstrap_biweekly_period`.
- paused cleared — `test_bootstrap_clears_transitions_paused` (`set_transitions_paused(False, conn=ANY)` even when paused was True).

Lint + typecheck:
```
uv run --directory apps/api ruff check .                      -> All checks passed!
uv run --directory apps/api basedpyright services/tournament_service.py repository/tournaments_repository.py -> 0 errors, 0 warnings, 0 notes
```

True full suite (per auto-memory; testmon can hide failures):
```
uv run --directory apps/api pytest -n 4 --no-testmon
```
Result: **1845 passed, 2 skipped, 2 xfailed, 0 failures** in 92s (up from the 1839 baseline; the known `-n 4` flake passed this run).

## Deviations from Plan

None — plan executed as written. The one judgment call (rewriting the existing `test_bootstrap_ends_at_uses_debug_period`, whose old `next_grid_boundary`-received-debug-period assertion is invalidated by the new debug-now branch) is explicitly anticipated by Task 3's behavior spec, so it is in-scope rather than a deviation.

## Scope Adherence

`next_grid_boundary`, the cron rollover, drain/poller, verification, and rewards were untouched. No new dependencies. No absolute-anchor/configurable-cadence rework attempted.

## Self-Check: PASSED
- `apps/api/repository/tournaments_repository.py` contains `async def fetch_db_now` — FOUND
- `apps/api/services/tournament_service.py` contains the `debug_cycle_seconds` branch + `set_transitions_paused(False, conn=conn)` — FOUND
- Commits `5b1fd17`, `8dda063`, `d9ec95c` — present in git log
