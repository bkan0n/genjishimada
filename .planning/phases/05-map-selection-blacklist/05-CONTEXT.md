# Phase 5: Map Selection & Blacklist - Context

**Gathered:** 2026-05-29
**Status:** Ready for planning

<domain>
## Phase Boundary

Build the map selection engine and admin management endpoints. The system randomly selects eligible maps for each category while respecting the global blacklist cooldown window. Pre-rolled next-cycle maps are stored as pending cycle records so admins can preview, reroll, or explicitly choose maps via the API.

</domain>

<decisions>
## Implementation Decisions

### Pre-roll Storage
- **D-01:** Pre-rolled next-cycle maps are stored as `tournaments.cycles` records with `status = 'pending'`. No new table needed — the existing schema already supports this lifecycle (`pending -> active -> finalizing -> completed`). A pending cycle holds the `category_id` and `map_id` for admin preview.
- **D-02:** Each category has at most one pending cycle at a time. The selection service enforces this by checking for an existing pending cycle before creating a new one.

### Selection Algorithm
- **D-03:** The selection flow is: (1) fetch config for `blacklist_weeks`, (2) fetch category for `difficulties`, (3) call `fetch_eligible_maps(difficulties, blacklist_weeks)`, (4) if non-empty take the first result (already randomized by `ORDER BY random()`), (5) if empty call `fetch_least_recently_used_map(difficulties)` as fallback and log a warning, (6) if fallback also returns None raise `NoEligibleMapsError`, (7) create a pending cycle record.
- **D-04:** Map cooldown is global — a map used in ANY category goes on cooldown for ALL categories (carried forward from Phase 1 D-03). No per-category cooldown option.

### API Endpoint Design
- **D-05:** New endpoints are nested under existing category paths in `TournamentsController`:
  - `GET /tournaments/categories/{category_id}/next-cycle` — preview the pending cycle (map info, when it was selected). Returns 404 if no pending cycle exists.
  - `POST /tournaments/categories/{category_id}/select-map` — trigger map selection, creates a pending cycle. Returns 409 if a pending cycle already exists for this category.
  - `POST /tournaments/categories/{category_id}/reroll` — delete the current pending cycle and create a new one with a freshly selected map. Returns 404 if no pending cycle to reroll.
  - `PATCH /tournaments/categories/{category_id}/next-cycle` — explicitly set the next map by providing a `map_code` or `map_id`. Validates the map exists and matches category difficulties. Updates the pending cycle's map_id (or deletes + recreates).
- **D-06:** All map selection endpoints require `tournaments:write` scope. The preview endpoint (`GET .../next-cycle`) requires `tournaments:read`.

### Reroll Behavior
- **D-07:** Reroll deletes the existing pending cycle and creates a new one. This produces a clean record and avoids UPDATE on identity columns. The newly selected map excludes the just-deleted map's `map_id` from the eligible pool (it's still within the blacklist window from its original use).

### Pool Exhaustion
- **D-08:** When `fetch_eligible_maps` returns empty, the service calls `fetch_least_recently_used_map` as a fallback (per success criteria #5). If the LRU fallback also returns None (no maps exist matching the category's difficulties at all), the service raises `NoEligibleMapsError`.
- **D-09:** A new `NoEligibleMapsError(TournamentsError)` domain exception is added to `services/exceptions/tournaments.py`. The controller maps it to 422 Unprocessable Entity with a message explaining the admin should adjust `blacklist_weeks` or add more maps matching the category's difficulties.

### Service Method Design
- **D-10:** New methods on the existing `TournamentService`:
  - `select_map(category_id)` — full selection flow (check no pending exists, select, create pending cycle)
  - `get_next_cycle(category_id)` — fetch pending cycle with map details
  - `reroll_map(category_id)` — delete pending + select new
  - `choose_map(category_id, map_code_or_id)` — validate map, delete pending if exists, create pending with chosen map
- **D-11:** The `select_map` method acquires a connection and runs within a transaction to ensure atomicity of the check-then-create flow.

### Claude's Discretion
- Exact response struct for next-cycle preview (could reuse `TournamentCycleResponse` or create a lighter struct with map details joined)
- Whether `choose_map` accepts `map_code` (string) or `map_id` (int) or both — pick whichever is most convenient for admin workflows
- Whether to add a `PendingCycleAlreadyExistsError` or reuse a generic conflict error
- SQL for fetching pending cycle with joined map info (simple JOIN or CTE)
- Logging format for pool exhaustion warning

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Tournament Code (from prior phases)
- `apps/api/repository/tournaments_repository.py` — `fetch_eligible_maps()`, `fetch_least_recently_used_map()`, `create_cycle()`, `fetch_active_cycle()`, `check_active_cycle_for_category()` methods
- `apps/api/services/tournament_service.py` — Existing `TournamentService` with config/category CRUD to extend with map selection methods
- `apps/api/routes/v3/tournaments.py` — Existing `TournamentsController` to extend with new endpoints
- `apps/api/services/exceptions/tournaments.py` — Domain exceptions to extend with `NoEligibleMapsError`
- `libs/sdk/src/genjishimada_sdk/tournaments.py` — SDK structs (may need new request/response types for next-cycle preview and choose-map)

### Database Schema
- `apps/api/migrations/0020_tournaments.sql` — `tournaments.cycles` table definition (pending status, map_id FK), `tournaments.config` (blacklist_weeks)

### Existing Patterns
- `apps/api/services/base.py` — `BaseService` base class
- `apps/api/routes/v3/maps.py` — Reference for nested endpoints and scope patterns
- `apps/api/repository/exceptions.py` — Repository exception types

### Prior Phase Context
- `.planning/phases/01-database-schema-migrations/01-CONTEXT.md` — D-03 (global cooldown), D-04 (cooldown from cycle history)
- `.planning/phases/03-repository-layer/03-CONTEXT.md` — D-09 (map selection repo methods already built)
- `.planning/phases/04-config-category-management/04-CONTEXT.md` — D-02 (single controller), D-04 (single service), D-05 (active cycle check pattern)

### Project Planning
- `.planning/PROJECT.md` — Constraints section (no ORM, bot never writes to DB, existing patterns)
- `.planning/REQUIREMENTS.md` — CYCLE-04, CYCLE-05, CYCLE-06, CYCLE-07 (requirements this phase covers)
- `.planning/ROADMAP.md` — Phase 5 success criteria (5 items)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `TournamentRepository.fetch_eligible_maps(difficulties, blacklist_weeks)` — returns random-ordered eligible maps with blacklist filtering already built
- `TournamentRepository.fetch_least_recently_used_map(difficulties)` — LRU fallback already built
- `TournamentRepository.create_cycle(category_id, map_id)` — creates cycle record (defaults to `pending` status)
- `TournamentService.get_config()` / `TournamentService.get_category()` — already exist for fetching config and category data
- `TournamentRepository.fetch_active_cycle(category_id)` — checks for active cycle (need analogous pending cycle fetch)

### Established Patterns
- Service acquires connection for check-then-mutate operations: `async with self._pool.acquire() as conn:` (see `update_category`, `delete_category` in tournament_service.py)
- Domain exceptions with context: `CategoryLockedError(category_id, cycle_id=cycle_id)` pattern
- Controller catches domain exceptions and maps to HTTP status codes
- `msgspec.convert(row, ResponseStruct)` for converting repo dicts to SDK structs

### Integration Points
- `apps/api/services/tournament_service.py` — add `select_map`, `get_next_cycle`, `reroll_map`, `choose_map` methods
- `apps/api/routes/v3/tournaments.py` — add 4 new endpoint handlers
- `apps/api/services/exceptions/tournaments.py` — add `NoEligibleMapsError`
- `apps/api/repository/tournaments_repository.py` — may need `fetch_pending_cycle(category_id)` and `delete_cycle(cycle_id)` methods
- `libs/sdk/src/genjishimada_sdk/tournaments.py` — may need `TournamentNextCycleResponse` and `TournamentChooseMapRequest` structs

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches following existing codebase patterns.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 5-Map Selection & Blacklist*
*Context gathered: 2026-05-29*
