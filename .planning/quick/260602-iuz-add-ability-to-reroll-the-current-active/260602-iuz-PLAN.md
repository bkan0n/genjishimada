---
phase: quick-260602-iuz
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - libs/sdk/src/genjishimada_sdk/tournaments.py
  - apps/api/repository/tournaments_repository.py
  - apps/api/services/tournament_service.py
  - apps/api/services/exceptions/tournaments.py
  - apps/api/routes/v3/tournaments.py
  - apps/bot/extensions/api_service.py
  - apps/bot/extensions/tournaments.py
  - apps/api/tests/integration/test_tournaments_integration.py
  - apps/api/tests/bot/test_tournament_commands.py
autonomous: true
requirements: [IUZ-REROLL-ACTIVE]
must_haves:
  truths:
    - "A mod can run /tournament-reroll with the cycle target set to current/active and get a fresh map on the live cycle (per D: extend existing command)"
    - "Omitting the target reruns the unchanged upcoming-cycle reroll (reroll_next_cycle -> POST .../reroll) byte-for-byte"
    - "An active-cycle reroll deletes ONLY the active cycle's submissions, scoped by that cycle's id (per D: wipe scoped by cycle_id)"
    - "The replacement cycle is status='active', stays attached to the SAME edition, so the original started_at/ends_at deadline is preserved (per D: preserve window, do not reset timer)"
    - "The live tournament channel is notified of the new map via the existing api.tournament.rollover event/consumer (per D: announce via existing event)"
    - "Eligible-map selection reuses fetch_eligible_maps (blacklist + exclude old map) with LRU fallback, same as upcoming reroll (per D: reuse eligibility logic)"
  artifacts:
    - path: "apps/api/services/tournament_service.py"
      provides: "reroll_active_cycle(category_id) service method"
      contains: "async def reroll_active_cycle"
    - path: "apps/api/repository/tournaments_repository.py"
      provides: "delete_cycle_completions(cycle_id) + create_active_cycle_for_edition(...) carrying edition_id"
      contains: "async def delete_cycle_completions"
    - path: "apps/api/routes/v3/tournaments.py"
      provides: "POST /categories/{category_id}/reroll-active route"
      contains: "reroll-active"
    - path: "apps/bot/extensions/tournaments.py"
      provides: "cycle target param on /tournament-reroll dispatching to active path"
  key_links:
    - from: "apps/bot/extensions/tournaments.py"
      to: "apps/bot/extensions/api_service.py"
      via: "api.reroll_active_cycle(category)"
      pattern: "reroll_active_cycle"
    - from: "apps/api/services/tournament_service.py"
      to: "api.tournament.rollover"
      via: "self.publish_message rollover event"
      pattern: "api.tournament.rollover"
    - from: "apps/api/services/tournament_service.py"
      to: "tournaments.completions"
      via: "delete_cycle_completions(active_cycle_id)"
      pattern: "delete_cycle_completions"
---

<objective>
Add the ability to reroll the CURRENT (`status='active'`) tournament cycle, extending the existing `/tournament-reroll` command. Today the command only rerolls the pre-staged `status='pending'` cycle; this adds a target so mods can swap the live cycle's map.

On a current-cycle reroll: wipe the active cycle's submissions (scoped by that cycle's id) and the cycle row, select a new eligible map (reusing the existing eligibility/LRU logic), recreate the cycle as `status='active'` attached to the SAME edition (so the original deadline is preserved — the edition owns the timing window), and announce the new map via the existing `api.tournament.rollover` event so the live channel updates.

Purpose: Mods need to fix/replace a live tournament map without waiting for the next rotation, accepting the intentional destruction of in-progress runs.
Output: New SDK target param, repo methods, service method, API route, bot client method, and the extended bot command — plus integration + bot unit tests.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/quick/260602-iuz-add-ability-to-reroll-the-current-active/260602-iuz-CONTEXT.md

# Reference implementation to mirror (upcoming-cycle reroll) — verified locations:
@apps/api/services/tournament_service.py        # reroll_map (~L675-747): fetch pending -> delete_cycle -> fetch_eligible_maps(exclude old) -> LRU fallback -> create_cycle
@apps/api/routes/v3/tournaments.py              # POST /categories/{id}/reroll (~L400-440)
@apps/api/repository/tournaments_repository.py  # fetch_active_cycle (L834), check_active_cycle_for_category (L283, returns int|None), delete_cycle (L1129), create_active_cycle (L588), create_cycle_for_edition (L669), fetch_eligible_maps (L1018), fetch_least_recently_used_map, fetch_config, fetch_category, fetch_active_edition_started_cycles (L1668)
@libs/sdk/src/genjishimada_sdk/tournaments.py   # CycleStatus, TournamentNextCycleResponse, TournamentCycleStartedEvent, TournamentRolloverEvent, TournamentChooseMapRequest
@apps/bot/extensions/tournaments.py             # TournamentRerollCog.tournament_reroll (~L900-951), _on_edition_rollover consumer (~L305) which renders a "New Cycle" card when event.started is non-empty
@apps/bot/extensions/api_service.py             # reroll_next_cycle (~L1809), choose_next_cycle, _request pattern

<interfaces>
<!-- GROUNDED FACTS from the actual code — executor must use these, no re-exploration needed. -->

KEY SCHEMA FACT (migration 0020 + 0024):
- `tournaments.completions.cycle_id` -> `tournaments.cycles(id) ON DELETE CASCADE`.
  Deleting the cycle row ALREADY cascade-deletes its completions. The plan still adds an
  EXPLICIT scoped `delete_cycle_completions(cycle_id)` call BEFORE delete_cycle so the wipe
  is deliberate, observable, and order-safe re: the `core.completions.tournament_completion_id`
  FK (which is `ON DELETE SET NULL` — non-tournament completion rows are NOT destroyed).
- `tournaments.cycles` has `edition_id int REFERENCES tournaments.editions(id) ON DELETE CASCADE` (0024).
- An ACTIVE cycle's timing window (started_at / ends_at deadline) lives on the PARENT EDITION,
  NOT on the cycle row. The cycle row's `ended_at` is NULL while active. THEREFORE preserving
  the window = re-attaching the new cycle to the SAME `edition_id` and NOT touching the edition.
  Do NOT recreate or modify the edition. Do NOT call any reset-timer path.

check_active_cycle_for_category(category_id) -> int | None  # cycle_id or None (Phase-4 contract, NOT a bool)
fetch_active_cycle(category_id) -> dict | None              # row includes id, category_id, map_id, edition_id, status, started_at, ended_at
create_cycle_for_edition(edition_id, category_id, map_id, started_at) -> dict  # INSERT ... status='active', started_at=$4 — REUSE this for the replacement cycle

TournamentRolloverEvent(edition_id: int, results: list[TournamentCycleCompletedEvent],
                        started: list[TournamentCycleStartedEvent], results_pending: bool = False)
  # routing key: "api.tournament.rollover". The bot's _on_edition_rollover renders a
  # "New Cycle" section iff `started` is non-empty (results=[] -> no results section,
  # no champion transfer). This is the existing pipeline to reuse for the announcement.

TournamentCycleStartedEvent(cycle_id, category_id, map_id, map_code, map_name,
                            started_at: datetime, ends_at: datetime)
  # ends_at MUST come from the edition window (fetch_active_edition_started_cycles sources
  # started_at/ends_at from tournaments.editions). For the reroll announcement, read the new
  # cycle's started_at/ends_at from its edition (the preserved window).

BaseService.publish_message(routing_key, data, headers, idempotency_key)
  # api.tournament.rollover is NOT in IGNORE_IDEMPOTENCY -> an idempotency_key is REQUIRED.
  # Use a reroll-scoped key, e.g. f"tournament:active-reroll:{new_cycle_id}".

Existing reroll_map flow to mirror (tournament_service.py ~L691-747):
  async with self._pool.acquire() as conn:
    category = fetch_category(category_id) -> CategoryNotFoundError if None
    existing = fetch_pending_cycle(category_id) -> PendingCycleNotFoundError if None
    old_map_id, old_cycle_id = existing["map_id"], existing["id"]
    delete_cycle(old_cycle_id)
    config = fetch_config()
    eligible = fetch_eligible_maps(category["difficulties"], config["blacklist_weeks"], exclude_map_ids=[old_map_id])
    selected = eligible[0] if eligible else fetch_least_recently_used_map(...) (NoEligibleMapsError if None)
    create_cycle(category_id, selected["id"])

Existing service exceptions (apps/api/services/exceptions/tournaments.py):
  CategoryNotFoundError, NoEligibleMapsError, NoActiveEditionError, NoCycleActiveError, PendingCycleNotFoundError
  # Add NO new exception unless needed; reuse NoCycleActiveError (L157) or add ActiveCycleNotFoundError if a
  # distinct 404 message is clearer — executor's discretion, keep it minimal.

Bot command surface (TournamentRerollCog.tournament_reroll, ~L900):
  - app_commands.command(name="tournament-reroll"), guild-scoped, default_permissions(manage_guild=True)
  - AUTHORITATIVE Mod/Sensei gate is the in-body `is_mod` check (D-07) — keep it; it must run BEFORE any API call for the new path too.
  - Existing params: category (CategoryTransformer), code (CodeAllTransformer | None).
  - Dispatch today: code is None -> api.reroll_next_cycle(category); else api.choose_next_cycle(...).

api_service client pattern (api_service.py):
  def reroll_next_cycle(self, category_id): 
      r = Route("POST", "/tournaments/categories/{category_id}/reroll", category_id=category_id)
      return self._request(r, response_model=TournamentNextCycleResponse)
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: API layer — repo wipe/create + reroll_active_cycle service + route</name>
  <files>apps/api/repository/tournaments_repository.py, apps/api/services/tournament_service.py, apps/api/services/exceptions/tournaments.py, apps/api/routes/v3/tournaments.py, apps/api/tests/integration/test_tournaments_integration.py</files>
  <behavior>
    Integration tests (in test_tournaments_integration.py, new TestRerollActiveEndpoint class, mirroring TestRerollEndpoint):
    - POST /tournaments/categories/{id}/reroll-active on a category WITH an active cycle (seeded via bootstrap/select + an edition) returns 200/201, status='active', a new map_code, and the SAME edition window (started_at/ends_at unchanged from before the reroll).
    - The active cycle's submissions are gone after reroll: seed >=1 tournaments.completions on the active cycle, reroll, assert COUNT(*) for that old cycle_id is 0 AND any UNRELATED cycle's completions are untouched (scoping proof).
    - POST .../reroll-active with NO active cycle returns 404 (active-cycle-not-found).
    - Pre-existing TestRerollEndpoint (upcoming path) still passes unchanged.
  </behavior>
  <action>
Repository (tournaments_repository.py):
  - Add `delete_cycle_completions(cycle_id, *, conn=None) -> int`: `DELETE FROM tournaments.completions WHERE cycle_id = $1` returning the deleted row count (use `result = await _conn.execute(...)` and parse, or a `RETURNING id` + len). Scoped STRICTLY by the passed cycle_id. Docstring must state this is the deliberate active-reroll wipe and that core.completions rows are preserved via the existing ON DELETE SET NULL FK.
  - Reuse `create_cycle_for_edition(edition_id, category_id, map_id, started_at)` for the replacement active cycle (it already INSERTs status='active' with the edition link and started_at). Do NOT add a new create method unless create_cycle_for_edition cannot carry the needed columns.
  - If a helper is needed to read the active cycle's edition window for the announcement, reuse `fetch_active_cycle` (returns edition_id, started_at) and `fetch_active_edition_started_cycles` (sources started_at/ends_at from tournaments.editions) OR add a tiny `fetch_edition(edition_id)` read if neither exposes ends_at cleanly — executor's discretion, keep it minimal and raw-SQL.

Service (tournament_service.py), new `reroll_active_cycle(self, category_id) -> TournamentNextCycleResponse` mirroring reroll_map but for the active cycle (per CONTEXT decisions):
  - `async with self._pool.acquire() as conn:` wrap the whole mutation atomically.
  - fetch_category -> CategoryNotFoundError if None.
  - fetch_active_cycle(category_id) -> if None raise NoCycleActiveError (or a new ActiveCycleNotFoundError; reuse existing if message fits) -> route maps to 404.
  - Capture old_cycle_id, old_map_id, edition_id, and the edition's started_at (the PRESERVED window).
  - `delete_cycle_completions(old_cycle_id, conn=conn)` FIRST (deliberate scoped wipe), THEN `delete_cycle(old_cycle_id, conn=conn)`.
  - Select new map: fetch_config + fetch_eligible_maps(category["difficulties"], config["blacklist_weeks"], exclude_map_ids=[old_map_id]) -> eligible[0]; else fetch_least_recently_used_map(...) -> NoEligibleMapsError if None. (Reuse — do NOT reimplement eligibility.)
  - Create replacement: `create_cycle_for_edition(edition_id, category_id, selected["id"], started_at=<preserved edition started_at>, conn=conn)` so it is status='active', SAME edition, preserved window.
  - AFTER the transaction commits (outside the `async with` or after acquiring the result), publish the announcement: build a `TournamentCycleStartedEvent` for the new cycle (started_at/ends_at from the preserved edition window, map_code/map_name from the selected map) and emit `TournamentRolloverEvent(edition_id=edition_id, results=[], started=[started_event], results_pending=False)` via `self.publish_message(routing_key="api.tournament.rollover", data=event, headers=Headers(), idempotency_key=f"tournament:active-reroll:{new_cycle_id}")`. Mirror the post-commit publish + log.exception-on-failure pattern already used by `_set_verified` (~L1019-1034). Skip publish when X-PYTEST-ENABLED (publish_message already no-ops in tests).
  - Return the new active cycle as `TournamentNextCycleResponse` (msgspec.convert of a row that includes map_code/map_name/map_difficulty — fetch via the same joined read used for the active cycle, or fetch_active_cycle + map join; reuse an existing joined fetch if available, else a minimal joined read).
  - Use %s-style logging, `log` variable, Google docstrings, type hints — per project conventions.

Exceptions (services/exceptions/tournaments.py): only add `ActiveCycleNotFoundError(TournamentsError)` if NoCycleActiveError's message is wrong for this 404; otherwise reuse.

Route (routes/v3/tournaments.py), new handler near reroll_map:
  - `@litestar.post(path="/categories/{category_id:int}/reroll-active", summary="Reroll Active Cycle", status_code=HTTP_201_CREATED, opt={"required_scopes": {"tournaments:write"}})`
  - Calls `tournament_service.reroll_active_cycle(category_id)`; try/except mapping CategoryNotFoundError->404, NoCycleActiveError/ActiveCycleNotFoundError->404, NoEligibleMapsError->422 (mirror reroll_map's except blocks). Returns TournamentNextCycleResponse.
  - DO NOT touch the existing /reroll or /next-cycle routes — default upcoming behavior stays byte-for-byte.
  </action>
  <verify>
    <automated>uv run --directory apps/api pytest tests/integration/test_tournaments_integration.py -k "Reroll" --no-testmon -p no:xdist -v</automated>
  </verify>
  <done>New reroll-active integration tests pass (active reroll swaps map, wipes scoped completions, preserves edition window, 404 with no active cycle); pre-existing TestRerollEndpoint upcoming-path tests still pass; `just lint-api` clean.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Bot layer — client method + cycle target param on /tournament-reroll</name>
  <files>apps/bot/extensions/api_service.py, apps/bot/extensions/tournaments.py, libs/sdk/src/genjishimada_sdk/tournaments.py, apps/api/tests/bot/test_tournament_commands.py</files>
  <behavior>
    Bot unit tests (test_tournament_commands.py, mirroring existing reroll_gate / reroll_dispatch tests):
    - Default (cycle target omitted / = upcoming), code=None -> still calls api.reroll_next_cycle(category) exactly once; api.reroll_active_cycle NOT called (upcoming path unchanged).
    - Default, code given -> still calls api.choose_next_cycle(...) (unchanged).
    - cycle target = current/active, code=None -> calls api.reroll_active_cycle(category) exactly once; reroll_next_cycle NOT called.
    - The Mod/Sensei gate still rejects a non-admin (reroll_active_cycle NOT called) — extend the existing reroll_gate test to assert the active path is also gated.
  </behavior>
  <action>
SDK (libs/sdk/src/genjishimada_sdk/tournaments.py): add a `RerollTarget = Literal["upcoming", "current"]` type alias near `CycleStatus` and export it in `__all__`. (Optional — the bot may use a discord app_commands choice instead; if the param is a pure discord Choice, no SDK change is needed. Executor's discretion per CONTEXT "Claude's Discretion" on param type. Prefer the clearest, consistent with existing transformer/param patterns.) If no SDK change is made, drop tournaments.py from this task's files and run `just fix` is NOT needed.

api_service.py: add `reroll_active_cycle(self, category_id) -> Response[TournamentNextCycleResponse]` mirroring `reroll_next_cycle`:
    r = Route("POST", "/tournaments/categories/{category_id}/reroll-active", category_id=category_id)
    return self._request(r, response_model=TournamentNextCycleResponse)
  Google docstring, type hints.

tournaments.py (TournamentRerollCog.tournament_reroll): add a new param `cycle` defaulting to upcoming.
  - Prefer a `app_commands.Choice[str]` / Literal-style choice param `cycle: Literal["upcoming","current"] = "upcoming"` (or `@app_commands.choices(...)`) so default-omitted == "upcoming". Pick whatever matches the existing param/choice patterns in this file.
  - Keep the AUTHORITATIVE in-body Mod/Sensei `is_mod` gate EXACTLY as-is, running BEFORE any API call for ALL paths.
  - Dispatch:
      * cycle == "upcoming" (default): UNCHANGED — code is None -> api.reroll_next_cycle(category); else api.choose_next_cycle(...). (Existing behavior must stay byte-for-byte.)
      * cycle == "current": call `api.reroll_active_cycle(category)`. Per CONTEXT, the explicit-`code` path for current is OUT OF SCOPE/ambiguous — if `code` is provided with cycle="current", raise a clean UserFacingError ("Choosing an explicit map for the current cycle is not supported; omit the code to reroll the live map.") rather than silently ignoring it. The random reroll of the current cycle is the must-have.
  - Render the result card: reuse the existing LayoutView/Container/TextDisplay block; adjust the heading for the current-cycle case (e.g. "# Current-Cycle Map Updated") so mods see which cycle changed. Keep the upcoming heading text unchanged for the upcoming path.
  - Use `log` + %s-style logging, Google docstrings, type hints.
  </action>
  <verify>
    <automated>uv run --directory apps/api pytest tests/bot/test_tournament_commands.py -k "reroll" --no-testmon -p no:xdist -v</automated>
  </verify>
  <done>Bot tests pass: default/upcoming dispatch unchanged (reroll_next_cycle/choose_next_cycle), current dispatch calls reroll_active_cycle, Mod gate still blocks the active path; `just lint-bot` (and `just lint-sdk` if SDK changed) clean.</done>
</task>

<task type="auto">
  <name>Task 3: TRUE full-suite + lint gate (no testmon)</name>
  <files>(verification only — no source changes expected)</files>
  <action>
Run the TRUE full test suite WITHOUT testmon (a green `just test-api`/testmon run can hide failures per project memory) and all linters. Fix any regression surfaced. Confirm zero NEW failures vs the STATE.md baseline (1839 passed / 2 skipped / 2 xfailed; the `test_filter_by_single_category` `-n 4` flake and `test_difficulty_exact_filter` are pre-existing per project memory — not regressions).
  </action>
  <verify>
    <automated>uv run --directory apps/api pytest -n 4 --no-testmon -q && just lint-api && just lint-bot && just lint-sdk</automated>
  </verify>
  <done>Full no-testmon suite shows no NEW failures beyond the documented pre-existing flakes; lint-api, lint-bot, lint-sdk all clean.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Discord user -> bot command | A non-mod Discord user could invoke /tournament-reroll; the bot's single API key does not distinguish callers |
| bot -> API (POST /reroll-active) | A destructive op (wipes live submissions) crosses into the API with the bot's full-scope key |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-iuz-01 | Elevation of Privilege | tournament_reroll command (active path) | mitigate | AUTHORITATIVE in-body Mod/Sensei `is_mod` gate runs BEFORE api.reroll_active_cycle for ALL paths (reuses D-07 gate; bot unit test asserts non-admin is rejected on the active path too). `default_permissions(manage_guild=True)` is only a UI hint. |
| T-iuz-02 | Tampering/DoS | delete_cycle_completions wipe | mitigate | DELETE is scoped STRICTLY by the active cycle_id (`WHERE cycle_id = $1`); integration test proves an unrelated cycle's completions are untouched. core.completions rows preserved via existing ON DELETE SET NULL FK (no PB loss). |
| T-iuz-03 | Repudiation | irreversible live wipe | accept | Destructive reset is the intended, documented behavior (CONTEXT decision); mod-only + logged at info level. No undo by design. |
| T-iuz-04 | Tampering | rollover announcement publish | mitigate | Published post-commit with a reroll-scoped idempotency_key (`tournament:active-reroll:{new_cycle_id}`); a re-delivery dedupes downstream (consumer is `@queue_consumer(idempotent=True)`). |
| T-iuz-SC | Tampering | npm/pip/cargo installs | n/a | No new package installs in this task. |
</threat_model>

<verification>
- Active-cycle reroll: new map on a status='active' cycle, SAME edition window (started_at/ends_at) preserved, old cycle's completions wiped (scoped), unrelated completions untouched.
- Upcoming-cycle reroll (default, target omitted): byte-for-byte unchanged (reroll_next_cycle -> POST /reroll; choose path -> PATCH /next-cycle).
- Live channel notified via existing api.tournament.rollover consumer (started section rendered).
- TRUE full suite (`-n 4 --no-testmon`) shows no new failures; lint-api/bot/sdk clean.
</verification>

<success_criteria>
- [ ] /tournament-reroll gains a cycle target; default == upcoming (unchanged behavior).
- [ ] Current-cycle reroll wipes the active cycle's submissions scoped by cycle_id, swaps to a new eligible map, stays status='active' on the SAME edition (deadline preserved), and announces via the existing rollover event.
- [ ] Mod/Sensei gate enforced before any API call on the active path.
- [ ] New integration + bot unit tests pass; pre-existing upcoming-reroll tests unchanged-green.
- [ ] TRUE no-testmon full suite + all three linters clean.
</success_criteria>

<output>
Create `.planning/quick/260602-iuz-add-ability-to-reroll-the-current-active/260602-iuz-01-SUMMARY.md` when done
</output>
