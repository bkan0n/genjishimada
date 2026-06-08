---
phase: quick-260602-dpm-bootstrap-ux
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - apps/api/repository/tournaments_repository.py
  - apps/api/services/tournament_service.py
  - apps/api/tests/services/test_tournament_lifecycle.py
autonomous: true
requirements: [BOOTSTRAP-UX]

must_haves:
  truths:
    - "Bootstrapping with debug_cycle_seconds set starts the first edition at server-now (not a future grid boundary)"
    - "Bootstrapping without debug_cycle_seconds still uses the next_grid_boundary path unchanged"
    - "A single bootstrap call clears transitions_paused=false atomically with edition creation"
  artifacts:
    - path: "apps/api/repository/tournaments_repository.py"
      provides: "fetch_db_now() returning SQL now()"
      contains: "async def fetch_db_now"
    - path: "apps/api/services/tournament_service.py"
      provides: "debug-now anchoring + transitions_paused clear in bootstrap_edition"
      contains: "debug_cycle_seconds"
  key_links:
    - from: "apps/api/services/tournament_service.py"
      to: "apps/api/repository/tournaments_repository.py"
      via: "service calls fetch_db_now() and set_transitions_paused(False) on the bootstrap conn"
      pattern: "fetch_db_now|set_transitions_paused"
---

<objective>
Two debug-UX changes scoped strictly to `bootstrap_edition`:
1. When `debug_cycle_seconds` is set, anchor the first edition's `started_at` at server-now (not `next_grid_boundary`), so a 5-minute debug edition starts immediately instead of days out.
2. Bootstrap clears `transitions_paused=false` in the same transaction, so one bootstrap call both starts the first edition AND makes auto-rotation live.

Purpose: Eliminate the manual "re-anchor the config to ~now, then unpause" dance before every debug bootstrap.
Output: A repo `fetch_db_now()` helper, two behavior branches in `bootstrap_edition`, and extended bootstrap tests.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@./CLAUDE.md

<interfaces>
<!-- Key contracts the executor needs. Extracted from the codebase — no exploration required. -->

bootstrap_edition (apps/api/services/tournament_service.py ~380-492) currently:
- Opens `async with self._pool.acquire() as conn, conn.transaction():`
- Guards on fetch_active_edition (raises CycleAlreadyLiveError)
- `config = await self._tournament_repo.fetch_config(conn=conn)` — config dict already has `debug_cycle_seconds` and `transitions_paused`.
- `period = self._period_from_config(config)` — already returns `timedelta(seconds=debug_cycle_seconds)` when debug is set.
- `started_at = await self._tournament_repo.next_grid_boundary(anchor_weekday, anchor_time, anchor_tz, period, conn=conn)`
- `ends_at = started_at + period`
- Then create_edition(started_at, ends_at, conn=conn), per-category child cycles, and ONE create_pending_transition rollover row.

_period_from_config (~365): static, debug_seconds wins → timedelta(seconds=debug_seconds), else 14/7 days.

Repo helpers (apps/api/repository/tournaments_repository.py):
- next_grid_boundary(...) (~736): `SELECT tournaments.next_grid_boundary(now(), $1,$2,$3,$4)` — DO NOT TOUCH.
- set_transitions_paused(paused, *, conn=None) (~397): wraps _set_global_config({"transitions_paused": paused}, conn=conn), returns dict.
- create_edition (~629), is_valid_timezone (~710) — show the established pattern: `_conn = self._get_connection(conn)` then `await _conn.fetchval(...)`.

Test fixtures (apps/api/tests/services/conftest.py):
- mock_tournament_repo = AsyncMock(spec=TournamentRepository) — new repo methods auto-mock once added to the real class.
- mock_pool exposes `conn` via acquire(); conn.transaction() is a working async CM.
- Test helpers in test_tournament_lifecycle.py: `_config(**kw)`, `_NEXT_MONDAY`, `_edition(**kw)`, `_category`, `_map`, `_child_cycle`.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Add fetch_db_now() repo helper</name>
  <files>apps/api/repository/tournaments_repository.py</files>
  <behavior>
    - fetch_db_now() returns the server instant via `SELECT now()` (a timezone-aware datetime).
    - Accepts optional `conn: Connection | None = None` and uses `self._get_connection(conn)` like sibling methods, so it participates in the bootstrap transaction.
  </behavior>
  <action>Add an async method `fetch_db_now(self, *, conn: Connection | None = None) -> dt.datetime` near `next_grid_boundary` (~736). Follow the established pattern: `_conn = self._get_connection(conn)` then `return await _conn.fetchval("SELECT now()")`. Google-style docstring explaining it returns the server's current instant for debug-only bootstrap anchoring (the only intended caller is bootstrap_edition); note it deliberately reads now() so the caller can store it (the "never store now()" D-08 rule applies to the auto-rotation chain, not the first debug edition). %s-style logging not needed (no log calls). Type hints required.</action>
  <verify>
    <automated>uv run --directory apps/api ruff check repository/tournaments_repository.py && uv run --directory apps/api basedpyright repository/tournaments_repository.py</automated>
  </verify>
  <done>fetch_db_now exists with type hints, docstring, and uses _get_connection; lint + typecheck clean.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Branch bootstrap_edition for debug-now anchoring + clear transitions_paused</name>
  <files>apps/api/services/tournament_service.py</files>
  <behavior>
    - When config["debug_cycle_seconds"] is not None: started_at = await fetch_db_now(conn=conn); ends_at = started_at + period. next_grid_boundary is NOT called.
    - When debug_cycle_seconds is None: the existing next_grid_boundary path runs unchanged; started_at/ends_at identical to today.
    - In both branches, before the transaction closes, set_transitions_paused(False, conn=conn) is called on the same conn so the flag clear is atomic with edition creation.
  </behavior>
  <action>In `bootstrap_edition` (~403-492), replace the unconditional `next_grid_boundary` block (~415-424) with a branch on `config["debug_cycle_seconds"]`. If not None: `started_at = await self._tournament_repo.fetch_db_now(conn=conn)` and `ends_at = started_at + period`. Else: keep the EXISTING next_grid_boundary call and `ends_at = started_at + period` exactly as-is. Add a clear comment on the debug branch: this is a deliberate, debug-only exception to the "never store now() in started_at" rule (D-08) — that rule prevents DRIFT in auto-rotation, and the first debug edition starting at now() is intended; subsequent editions still inherit prev.ends_at exactly (no drift). debug_cycle_seconds is production-disabled so this branch never runs in prod. Do NOT modify next_grid_boundary or _period_from_config. Separately, inside the same `async with self._pool.acquire() as conn, conn.transaction()` block, add `await self._tournament_repo.set_transitions_paused(False, conn=conn)` (order it alongside edition creation, e.g. right after create_edition or just before the rollover write) so a failure rolls back both. Add a brief comment that bootstrapping unpauses auto-rotation (intended; applies in prod too — call out in SUMMARY). Keep three-layer: no inline SQL in the service. Use %s-style logging if any new log line is added.</action>
  <verify>
    <automated>uv run --directory apps/api ruff check services/tournament_service.py && uv run --directory apps/api basedpyright services/tournament_service.py</automated>
  </verify>
  <done>Debug branch anchors at fetch_db_now; production branch unchanged; set_transitions_paused(False, conn=conn) called within the bootstrap transaction; lint + typecheck clean.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Extend bootstrap tests (debug-now, prod-grid, unpause)</name>
  <files>apps/api/tests/services/test_tournament_lifecycle.py</files>
  <behavior>
    - Test (a): with debug_cycle_seconds set, started_at passed to create_edition == the server-now value fetch_db_now returned, ends_at == started_at + debug period, and next_grid_boundary was NOT called.
    - Test (b): without debug, next_grid_boundary IS called and started_at == _NEXT_MONDAY (existing path preserved). (Covered by existing test_bootstrap_grid_snaps_start_no_now; add an explicit assert that fetch_db_now was NOT called in that test, or a focused new test.)
    - Test (c): bootstrap calls set_transitions_paused(False, conn=...) even when transitions_paused was True in config beforehand.
  </behavior>
  <action>In TestBootstrapEdition, add tests using the existing mock pattern (set mock_tournament_repo return values like the sibling tests). For (a): `mock_tournament_repo.fetch_config.return_value = _config(debug_cycle_seconds=300)`; set `_DEBUG_NOW = dt.datetime(2026, 6, 2, 12, 0, 0, tzinfo=dt.UTC)` and `mock_tournament_repo.fetch_db_now.return_value = _DEBUG_NOW`; mock create_edition/create_cycle_for_edition/create_pending_transition/fetch_categories/fetch_eligible_maps like other tests; after `await service.bootstrap_edition()`, assert create_edition was called with started_at == _DEBUG_NOW and ends_at == _DEBUG_NOW + timedelta(seconds=300), and `mock_tournament_repo.next_grid_boundary.assert_not_called()`. For (b): in the existing no-debug test (or a new one), add `mock_tournament_repo.next_grid_boundary.assert_called()` and `mock_tournament_repo.fetch_db_now.assert_not_called()`. For (c): use `_config(transitions_paused=True)` (no debug), run bootstrap, then assert `mock_tournament_repo.set_transitions_paused.assert_called_once_with(False, conn=mocker.ANY)` (or assert call args [0]==False) — accept that conn is the mock conn. Do not assert exact conn identity beyond ANY. Reuse existing helpers; tests are exempt from lint.</action>
  <verify>
    <automated>uv run --directory apps/api pytest tests/services/test_tournament_lifecycle.py -p no:xdist -v</automated>
  </verify>
  <done>All three new/extended assertions pass; existing TestBootstrapEdition tests still green.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| admin → bootstrap endpoint | Only authenticated admin scope can trigger bootstrap_edition; no untrusted input reaches the changed code (no new params). |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-QUICK-01 | Tampering | started_at anchoring | accept | Debug branch reads SQL now() server-side; no client-supplied time. Production path unchanged. |
| T-QUICK-02 | Elevation | transitions_paused clear in prod | accept | Bootstrapping unpausing is intended ("starting a tournament means running it"); gated behind existing admin auth on the bootstrap route. Called out in SUMMARY. |
| T-QUICK-SC | Tampering | npm/pip/cargo installs | mitigate | No new dependencies added; nothing to verify. |
</threat_model>

<verification>
- Targeted suite: `uv run --directory apps/api pytest tests/services/test_tournament_lifecycle.py -p no:xdist -v` (all bootstrap tests green).
- Lint + typecheck: `uv run --directory apps/api ruff check . && uv run --directory apps/api basedpyright services/tournament_service.py repository/tournaments_repository.py`.
- True full suite (per auto-memory; testmon can hide failures): `uv run --directory apps/api pytest -n 4 --no-testmon`.
</verification>

<success_criteria>
- Debug bootstrap (`debug_cycle_seconds` set) anchors started_at at server-now via fetch_db_now; ends_at == started_at + debug period; next_grid_boundary not called.
- Production bootstrap (debug None) unchanged: next_grid_boundary path preserved exactly.
- Bootstrap clears transitions_paused=false atomically inside the existing transaction, even when it was true.
- next_grid_boundary, the cron rollover, drain/poller, verification, and rewards are untouched.
- Three atomic commits (repo helper / service branch / tests), or one cohesive commit if executor prefers; tests green.
</success_criteria>

<output>
Create `.planning/quick/260602-dpm-bootstrap-ux-debug-cycle-seconds-anchors/260602-dpm-SUMMARY.md` when done. Call out in the SUMMARY that bootstrapping now unpauses auto-rotation in production (intended behavior change).
</output>
