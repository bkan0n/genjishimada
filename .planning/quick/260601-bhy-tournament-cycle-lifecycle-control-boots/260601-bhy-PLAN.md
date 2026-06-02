---
phase: quick-260601-bhy
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - apps/api/migrations/0023_tournament_cycle_lifecycle_control.sql
  - libs/sdk/src/genjishimada_sdk/tournaments.py
  - apps/api/services/exceptions/tournaments.py
  - apps/api/repository/tournaments_repository.py
  - apps/api/services/tournament_service.py
  - apps/api/routes/v3/tournaments.py
  - apps/api/tests/repository/tournaments/test_lifecycle_control.py
  - apps/api/tests/services/test_tournament_lifecycle.py
autonomous: true
requirements: []
must_haves:
  truths:
    - "An admin can bootstrap the first cycle for a category, which becomes active and then rolls over automatically on schedule"
    - "Bootstrapping a category that already has an active/finalizing/pending+active cycle returns a clear domain error (no double-start)"
    - "An admin can pause automatic cycle transitions for a category; paused categories are skipped by the pg_cron transition function"
    - "An admin can resume a paused category; the normal weekly/biweekly cadence resumes (started_at preserved)"
    - "A debug-only route can override a category's cycle length to a short duration so the next transition recomputes from the override"
  artifacts:
    - path: apps/api/migrations/0023_tournament_cycle_lifecycle_control.sql
      provides: "transitions_paused + debug_cycle_seconds columns on tournaments.categories; updated process_cycle_transitions() honoring both"
      contains: "transitions_paused"
    - path: apps/api/routes/v3/tournaments.py
      provides: "bootstrap, pause, resume, and debug-cycle-length admin routes"
      contains: "bootstrap"
  key_links:
    - from: apps/api/routes/v3/tournaments.py
      to: apps/api/services/tournament_service.py
      via: "controller calls service methods"
      pattern: "tournament_service\\.(bootstrap_cycle|set_transitions_paused|set_debug_cycle_length)"
    - from: apps/api/migrations/0023_tournament_cycle_lifecycle_control.sql
      to: tournaments.process_cycle_transitions
      via: "CREATE OR REPLACE FUNCTION with paused skip + debug interval"
      pattern: "transitions_paused = FALSE"
---

<objective>
Add three admin-only tournament cycle lifecycle control capabilities to the existing tournaments API:
1. **Bootstrap** — manually activate the FIRST cycle for a category so it then rolls over automatically via the existing pg_cron machinery.
2. **Pause / Resume** — halt and restart automatic cycle transitions for a category via a DB-state flag the transition function checks (no cron job manipulation).
3. **Debug cycle length override** — set a short per-category cycle duration (seconds) so transitions can be tested without waiting a full week.

Purpose: The original design (PROJECT.md "Out of Scope: manual cycle transitions") is intentionally amended ONLY for first-cycle bootstrap and for testing — the weekly automatic rotation remains the production path. Without bootstrap there is no route that ever sets a cycle `active`; without a debug override, every end-to-end test of the rotation requires real-time waits.

Output: one additive migration (0023), new SDK request/response structs, two new domain exceptions, repository methods, service methods, and four controller routes, plus repository + service tests.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/PROJECT.md
@./CLAUDE.md

@apps/api/migrations/0021_tournament_cycle_transitions.sql
@apps/api/routes/v3/tournaments.py
@apps/api/services/tournament_service.py
@apps/api/repository/tournaments_repository.py
@apps/api/services/exceptions/tournaments.py
@libs/sdk/src/genjishimada_sdk/tournaments.py
@apps/api/tests/repository/tournaments/conftest.py
@apps/api/tests/repository/tournaments/test_cycle_transitions.py

<integration_notes>
KEY FINDINGS FROM INVESTIGATION (do not re-derive — implement against these):

- Cycle lifecycle is `pending -> active -> finalizing -> completed` (CHECK constraint on tournaments.cycles.status, migration 0020). select_map/reroll/choose_map only ever create `pending` cycles. The ONLY thing that sets a cycle `active` today is `tournaments.process_cycle_transitions()` (pg_cron, every minute, 0021), which promotes a `pending` cycle when a due `active` cycle finalizes. THERE IS NO FIRST-CYCLE ACTIVATION PATH — that is exactly the bootstrap gap.

- There is NO `next_transition_at` column. Due-detection is computed INLINE in process_cycle_transitions():
  `now() >= cy.started_at + make_interval(days => CASE cat.cycle_frequency WHEN 'biweekly' THEN 14 ELSE 7 END)`.
  The same weekly?7:14 interval is recomputed in TWO `ends_at` jsonb_build_object expressions (promote-pending and inline-create branches).

- Frequency is stored as `tournaments.categories.cycle_frequency text CHECK IN ('weekly','biweekly')`. There is no numeric length column.

- Pause state SHOULD live as a new boolean column on tournaments.categories. The transition function's due-detection FOR loop must add `AND cat.transitions_paused = FALSE`. Because started_at is preserved while paused, resume naturally resumes cadence (an overdue cycle transitions on the next tick after resume — correct behavior).

- Debug length override SHOULD be a new nullable `debug_cycle_seconds int` column. Replace the three weekly?7:14 interval expressions with:
  `COALESCE(make_interval(secs => cat.debug_cycle_seconds), make_interval(days => CASE cat.cycle_frequency WHEN 'biweekly' THEN 14 ELSE 7 END))`
  When debug_cycle_seconds IS NULL, behavior is identical to today.

- The cycle_started outbox payload's `ends_at` must use the SAME debug-aware interval so the bot's announced end time matches the actual transition time.

- Existing admin write routes use `opt={"required_scopes": {"tournaments:write"}}`. Read routes use `{"tournaments:read"}`. There is NO existing debug-gating convention in the codebase. DECISION (D-DEBUG): gate the debug route behind `tournaments:write` AND a non-production `APP_ENVIRONMENT` check (reject with 403 when `APP_ENVIRONMENT == "production"`). `APP_ENVIRONMENT` is read via `os.getenv("APP_ENVIRONMENT")` (see apps/api/app.py:32, completions_service.py:332).

- Test DB auto-applies every migrations/*.sql in sorted glob order (apps/api/tests/conftest.py:60), so 0023 is picked up automatically. pg_cron is absent in tests; transition tests invoke `SELECT tournaments.process_cycle_transitions()` directly (see test_cycle_transitions.py).

- Repository convention: every method takes `*, conn: Connection | None = None` and uses `self._get_connection(conn)`. Services acquire from `self._pool` and pass `conn` for TOCTOU-safe multi-step ops (see select_map/update_category). Controllers catch domain exceptions and raise CustomHTTPException.

- SDK structs live in libs/sdk/src/genjishimada_sdk/tournaments.py and MUST be added to its module `__all__` tuple (the package __init__.py re-exports the whole `tournaments` module).
</integration_notes>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Migration 0023 — paused + debug-length columns and debug-aware transition function</name>
  <files>apps/api/migrations/0023_tournament_cycle_lifecycle_control.sql</files>
  <action>
Create an additive migration wrapped in BEGIN/COMMIT, following the 0020/0022 header-comment style.

(a) ALTER TABLE tournaments.categories:
  - ADD COLUMN IF NOT EXISTS transitions_paused boolean NOT NULL DEFAULT FALSE
  - ADD COLUMN IF NOT EXISTS debug_cycle_seconds int  (nullable; CHECK (debug_cycle_seconds IS NULL OR debug_cycle_seconds > 0))
  Add COMMENT ON COLUMN for both: transitions_paused = "When TRUE, process_cycle_transitions() skips this category (admin pause)"; debug_cycle_seconds = "DEBUG/TEST ONLY: overrides cycle length in seconds; NULL = normal weekly/biweekly cadence".

(b) CREATE OR REPLACE FUNCTION tournaments.process_cycle_transitions() — copy the body verbatim from 0021 and make exactly these three edits (all referencing the joined `cat` row, which is already in scope):
  1. In the due-detection FOR loop: add `cat.transitions_paused`, `cat.debug_cycle_seconds` to the SELECT list, add `AND cat.transitions_paused = FALSE` to the WHERE, and change the due predicate interval to:
     `now() >= cy.started_at + COALESCE(make_interval(secs => cat.debug_cycle_seconds), make_interval(days => CASE cat.cycle_frequency WHEN 'biweekly' THEN 14 ELSE 7 END))`
     Capture debug_cycle_seconds into the v_due record (add a column to the record select) so it is usable in the ends_at expressions below.
  2. In the promote-pending branch (f) `ends_at` expression: replace the weekly?7:14 make_interval with the same COALESCE(make_interval(secs => v_due.debug_cycle_seconds), make_interval(days => CASE v_due.cycle_frequency WHEN 'biweekly' THEN 14 ELSE 7 END)).
  3. In the inline-create branch (D-07 fallback) `ends_at` expression: apply the identical COALESCE replacement.
  Keep the advisory-lock gate (2025070100), the placement snapshot, the outbox INSERTs, and the pre-roll logic UNCHANGED. Keep the COMMENT ON FUNCTION (update its text to mention pause + debug override).

DO NOT touch the pg_cron DO-block registration in 0021 — the cron job already calls the function by name, so CREATE OR REPLACE is sufficient; no re-scheduling is needed and pause is handled inside the function.
  </action>
  <verify>
    <automated>cd /Users/nebula/Documents/coding/parkour/genji/genjishimada && grep -v '^--' apps/api/migrations/0023_tournament_cycle_lifecycle_control.sql | grep -c "transitions_paused = FALSE"</automated>
  </verify>
  <done>Migration adds both nullable/defaulted columns additively, and process_cycle_transitions() skips paused categories and honors debug_cycle_seconds in all three interval computations while leaving non-debug, non-paused behavior identical to 0021.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: SDK structs, exceptions, and repository methods</name>
  <files>libs/sdk/src/genjishimada_sdk/tournaments.py, apps/api/services/exceptions/tournaments.py, apps/api/repository/tournaments_repository.py, apps/api/tests/repository/tournaments/test_lifecycle_control.py</files>
  <behavior>
    - bootstrap repo path: given a category with NO non-completed cycle, activate_first_cycle creates a new `active` cycle (started_at = now()) for a selected eligible map and returns it; writing a `cycle_started` pending_transition row is the service's job, repo just creates the active cycle.
    - set_category_paused(category_id, paused) updates transitions_paused and returns the updated category row (None if category missing).
    - set_category_debug_cycle_seconds(category_id, seconds|None) updates debug_cycle_seconds and returns updated row (None if missing).
    - check_any_live_cycle(category_id) returns a cycle_id if the category has ANY cycle in status active/finalizing/pending, else None (used to make bootstrap idempotent — bootstrap must not double-start when a cycle is already live or pre-rolled).
  </behavior>
  <action>
SDK (libs/sdk/src/genjishimada_sdk/tournaments.py): add and register in `__all__`:
  - `TournamentPauseRequest(Struct)` with `paused: bool`.
  - `TournamentDebugCycleLengthRequest(Struct)` with `seconds: int | None` (None clears the override; restores normal cadence).
  - Reuse existing `TournamentCycleResponse` for bootstrap output (it already covers id/category_id/map_id/status/started_at). Add a small `TournamentCategoryLifecycleResponse(Struct)` with `id: int`, `transitions_paused: bool`, `debug_cycle_seconds: int | None` for pause/resume/debug responses. Add all new struct names to the `__all__` tuple alphabetically.

Exceptions (apps/api/services/exceptions/tournaments.py): add
  - `CycleAlreadyLiveError(TournamentsError)` raised when bootstrap is attempted but a live/pending cycle already exists (carries category_id and cycle_id). Message: "Category already has a live or pending cycle; cannot bootstrap." (Reuse CategoryNotFoundError / NoEligibleMapsError which already exist — do NOT duplicate them.)
  - `DebugRouteDisabledError(TournamentsError)` raised when the debug route is hit in production. Message: "Debug cycle-length override is disabled in production." (carries no ids.)

Repository (apps/api/repository/tournaments_repository.py): add, each with `*, conn: Connection | None = None` and `self._get_connection(conn)`:
  - `check_any_live_cycle(category_id) -> int | None`: SELECT id FROM tournaments.cycles WHERE category_id=$1 AND status IN ('active','finalizing','pending') LIMIT 1.
  - `create_active_cycle(category_id, map_id) -> dict`: INSERT INTO tournaments.cycles (category_id, map_id, status, started_at) VALUES ($1,$2,'active',now()) RETURNING *. Catch ForeignKeyViolationError -> RepoFKError like create_cycle does.
  - `set_category_paused(category_id, paused) -> dict | None`: UPDATE tournaments.categories SET transitions_paused=$2, updated_at=now() WHERE id=$1 RETURNING id, transitions_paused, debug_cycle_seconds.
  - `set_category_debug_cycle_seconds(category_id, seconds) -> dict | None`: UPDATE tournaments.categories SET debug_cycle_seconds=$2, updated_at=now() WHERE id=$1 RETURNING id, transitions_paused, debug_cycle_seconds.

Tests (apps/api/tests/repository/tournaments/test_lifecycle_control.py): mirror the existing repository test style and fixtures (create_test_category, create_test_cycle, create_test_map from conftest). Cover: check_any_live_cycle returns None for a fresh category, returns the id for active/finalizing/pending cycles; create_active_cycle produces status='active' with non-null started_at; set_category_paused flips the flag and round-trips; set_category_debug_cycle_seconds sets and clears (None) the value. Use `pytestmark = [pytest.mark.domain_tournaments]` to match the suite.
  </action>
  <verify>
    <automated>cd /Users/nebula/Documents/coding/parkour/genji/genjishimada && just fix >/dev/null 2>&1; uv run --directory apps/api pytest tests/repository/tournaments/test_lifecycle_control.py -v -p no:xdist</automated>
  </verify>
  <done>SDK structs exported in __all__; two new exceptions added; four repository methods added following the conn-injection + exception-translation conventions; repository tests pass.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Service methods + controller routes (bootstrap, pause/resume, debug length)</name>
  <files>apps/api/services/tournament_service.py, apps/api/routes/v3/tournaments.py, apps/api/tests/services/test_tournament_lifecycle.py</files>
  <behavior>
    - bootstrap_cycle(category_id): raises CategoryNotFoundError if category missing; raises CycleAlreadyLiveError if check_any_live_cycle returns a cycle id; otherwise selects an eligible map (fetch_eligible_maps -> LRU fallback -> NoEligibleMapsError, same pattern as select_map), creates an ACTIVE cycle, writes a `cycle_started` pending_transition row (so the bot announces it and the outbox path matches the automatic rotation), and returns TournamentCycleResponse. All steps on ONE acquired connection inside a transaction (TOCTOU-safe + atomic outbox write).
    - set_transitions_paused(category_id, paused): set_category_paused; None -> CategoryNotFoundError; returns TournamentCategoryLifecycleResponse.
    - set_debug_cycle_length(category_id, seconds): in production raises DebugRouteDisabledError; else set_category_debug_cycle_seconds; None row -> CategoryNotFoundError; returns TournamentCategoryLifecycleResponse.
  </behavior>
  <action>
Service (apps/api/services/tournament_service.py):
  - `bootstrap_cycle(self, category_id: int) -> TournamentCycleResponse`: acquire `self._pool` connection + `conn.transaction()`. Fetch category (CategoryNotFoundError). Call check_any_live_cycle; if not None raise CycleAlreadyLiveError(category_id, cycle_id=...). Select eligible map via fetch_eligible_maps(category["difficulties"], config["blacklist_weeks"]) with LRU fallback to fetch_least_recently_used_map, else NoEligibleMapsError — copy the exact selection block from select_map. create_active_cycle. Build the cycle_started payload as a dict whose keys EXACTLY match TournamentCycleStartedEvent (cycle_id, category_id, map_id, map_code, map_name, started_at, ends_at) — compute ends_at in Python as started_at + timedelta(seconds=debug_cycle_seconds) when set else timedelta(days=14 if biweekly else 7); fetch map_code/map_name from the created cycle's map (join or fetch_map_by_code). Write it via create_pending_transition(cycle_id, "cycle_started", msgspec.json.encode(payload).decode()). Return msgspec.convert(created_cycle_row, TournamentCycleResponse). Note in a code comment: this is the SAME outbox row the pg_cron promote-pending branch writes, so the existing TournamentOutboxService publishes it with no changes.
  - `set_transitions_paused(self, category_id, paused) -> TournamentCategoryLifecycleResponse`: call set_category_paused; None -> CategoryNotFoundError; convert row.
  - `set_debug_cycle_length(self, category_id, seconds) -> TournamentCategoryLifecycleResponse`: if `os.getenv("APP_ENVIRONMENT") == "production"` raise DebugRouteDisabledError; call set_category_debug_cycle_seconds; None -> CategoryNotFoundError; convert row. Add `import os` and the datetime import as needed at the top of the module.

Controller (apps/api/routes/v3/tournaments.py): add four routes on TournamentsController, importing the new structs/exceptions:
  - POST `/categories/{category_id:int}/bootstrap`, status 201, scope `{"tournaments:write"}` -> bootstrap_cycle. Catch CategoryNotFoundError->404, CycleAlreadyLiveError->409, NoEligibleMapsError->422.
  - POST `/categories/{category_id:int}/pause`, status 200, scope `{"tournaments:write"}`, body TournamentPauseRequest -> set_transitions_paused(category_id, data.paused). (A single pause endpoint with a bool body covers both pause and resume; document in the route description that paused=false resumes the normal cadence.) Catch CategoryNotFoundError->404.
  - PATCH `/categories/{category_id:int}/debug-cycle-length`, status 200, scope `{"tournaments:write"}`, body TournamentDebugCycleLengthRequest -> set_debug_cycle_length(category_id, data.seconds). Mark the summary/description clearly as DEBUG/TEST ONLY. Catch DebugRouteDisabledError->403 (HTTP_403_FORBIDDEN, add the import), CategoryNotFoundError->404.

Tests (apps/api/tests/services/test_tournament_lifecycle.py): follow the existing service-test construction (TournamentService built with pool/state/repo; see test_tournament_service patterns). Cover: bootstrap on a fresh category creates an active cycle + a cycle_started pending_transition row and returns it; bootstrap raises CycleAlreadyLiveError when an active/pending cycle exists; bootstrap raises NoEligibleMapsError when no maps match; set_transitions_paused True then False round-trips and CategoryNotFoundError on a missing id; set_debug_cycle_length sets/clears seconds, CategoryNotFoundError on missing id, and DebugRouteDisabledError when APP_ENVIRONMENT is monkeypatched to "production". Use X-PYTEST-ENABLED semantics if any publish is triggered — bootstrap writes an outbox ROW (no broker publish), so no header needed, but assert the row exists via the repository/SQL. `pytestmark = [pytest.mark.domain_tournaments]`.
  </action>
  <verify>
    <automated>cd /Users/nebula/Documents/coding/parkour/genji/genjishimada && uv run --directory apps/api pytest tests/services/test_tournament_lifecycle.py -v -p no:xdist</automated>
  </verify>
  <done>Three service methods exist with TOCTOU-safe connection handling and correct exception mapping; bootstrap writes a TournamentCycleStartedEvent-shaped outbox row so the existing outbox poller announces it; four routes added with correct scopes, status codes, and exception->HTTP mappings; the debug route is blocked in production; service tests pass.</done>
</task>

</tasks>

<verification>
- `uv run --directory apps/api pytest tests/repository/tournaments/test_lifecycle_control.py tests/services/test_tournament_lifecycle.py --no-testmon -p no:xdist` passes.
- Existing transition tests still pass (no regression in non-debug, non-paused path): `uv run --directory apps/api pytest tests/repository/tournaments/test_cycle_transitions.py --no-testmon -p no:xdist`.
- `just lint-api` and `just lint-sdk` clean (new structs in __all__, full type annotations, Google docstrings on public methods).
</verification>

<success_criteria>
- Admin can POST bootstrap to activate the first cycle; it then auto-rotates via the unchanged pg_cron + outbox path.
- Bootstrap is idempotent-safe: a category with any live/pending cycle returns 409, never double-starts.
- Pause (paused=true) makes process_cycle_transitions() skip the category; resume (paused=false) restores cadence using preserved started_at.
- Debug-cycle-length route overrides the per-category interval to seconds (NULL clears it), recomputing the next transition and the announced ends_at; route is rejected in production.
- Migration is additive (nullable/defaulted columns) and CREATE OR REPLACE on the function; non-debug, non-paused behavior is byte-for-byte equivalent to 0021.
</success_criteria>

<output>
Create `.planning/quick/260601-bhy-tournament-cycle-lifecycle-control-boots/260601-bhy-SUMMARY.md` when done.
</output>
