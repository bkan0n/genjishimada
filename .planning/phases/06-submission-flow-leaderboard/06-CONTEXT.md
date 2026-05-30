# Phase 6: Submission Flow & Leaderboard - Context

**Gathered:** 2026-05-29
**Status:** Ready for planning

<domain>
## Phase Boundary

Build the tournament completion submission service and controller endpoints. Players submit times for active tournament cycles, with per-cycle speed enforcement rejecting slower re-submissions. Faster tournament times cross-write to `core.completions` atomically. Leaderboard and cycle listing endpoints expose ranked standings and tournament history.

</domain>

<decisions>
## Implementation Decisions

### Per-Cycle Speed Enforcement
- **D-01:** The service rejects submissions where the player already has a faster time for the same cycle. A new `SlowerTimeError(TournamentsError)` domain exception is raised with context (`current_best`, `submitted_time`). Controller maps to 409 Conflict with a message like "Submitted time (45.2s) is not faster than your current best (42.1s)".
- **D-02:** The full submission flow runs in a single transaction: acquire connection -> check speed against existing best -> insert `tournaments.completions` -> cross-write to `core.completions` (CTE, only if faster than global best) -> commit. All-or-nothing.
- **D-03:** Full validation before insert: (1) cycle exists and status is `active`, (2) submitted map matches the cycle's `map_id`, (3) user exists. Specific domain exceptions for each case: `CycleNotActiveError`, `MapMismatchError`. These are added to `services/exceptions/tournaments.py`.

### Submission Endpoint Design
- **D-04:** Submission endpoint: `POST /tournaments/cycles/{cycle_id}/submit`. Explicit cycle reference in the URL path. The `TournamentCompletionCreateRequest` body contains `user_id`, `time`, `screenshot`, and optional `video`.
- **D-05:** Leaderboard endpoint: `GET /tournaments/cycles/{cycle_id}/leaderboard`. Works for both active and completed cycles. Returns ranked standings using the repo's existing `fetch_leaderboard` method.
- **D-06:** The submission endpoint is called by the bot only, using its API key with `tournaments:write` scope. The bot passes the player's Discord `user_id` in the request body. Same authentication pattern as existing completion submissions.
- **D-07:** No user submission lookup endpoint (`GET /cycles/{cycle_id}/submissions/{user_id}`) in this phase. The speed enforcement check in the service handles the "already submitted faster" case.

### RabbitMQ Event Publishing
- **D-08:** No RabbitMQ event publishing in Phase 6. The `TournamentCompletionCreatedEvent` publish call will be added in Phase 9 alongside the bot consumer. This keeps Phase 6 focused on the data flow without touching `BaseService.publish_message()`.

### History & Archive
- **D-09:** Cycle listing endpoint: `GET /tournaments/cycles` with query params for filtering and pagination. Supports `status` filter (e.g., `?status=completed`) and optional `category_id` filter (e.g., `?category_id=3`).
- **D-10:** Offset-based pagination via `limit` and `offset` query params. Matches existing codebase patterns.
- **D-11:** Each cycle entry returns metadata plus winner info: cycle_id, category, map name/code, start/end dates, status, and rank-1 user name. Full standings for any cycle are available via the leaderboard endpoint.

### Claude's Discretion
- Exact new domain exception class signatures (SlowerTimeError, CycleNotActiveError, MapMismatchError) — follow existing TournamentsError pattern
- Response struct for cycle listing with winner info — may need a new `TournamentCycleWithWinnerResponse` or extend existing `TournamentCycleResponse`
- Whether `GET /tournaments/cycles` needs a dedicated repo method or reuses `fetch_cycle_history` with added filters
- Service method names for submission flow (`submit_completion` or `create_tournament_completion`)
- Pagination defaults (limit=20 is typical in the codebase)
- Whether the cycles list endpoint also returns active/pending cycles or just completed ones (the status filter handles this flexibly)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Tournament Code (from prior phases)
- `apps/api/repository/tournaments_repository.py` — `create_tournament_completion()`, `cross_write_to_core()`, `fetch_leaderboard()`, `fetch_cycle_history()`, `fetch_user_completion()`, `fetch_active_cycle()` methods
- `apps/api/services/tournament_service.py` — Existing `TournamentService` with config/category/map-selection methods to extend with submission flow
- `apps/api/routes/v3/tournaments.py` — Existing `TournamentsController` to extend with submission, leaderboard, and cycles list endpoints
- `apps/api/services/exceptions/tournaments.py` — Domain exceptions to extend with `SlowerTimeError`, `CycleNotActiveError`, `MapMismatchError`
- `libs/sdk/src/genjishimada_sdk/tournaments.py` — `TournamentCompletionCreateRequest`, `TournamentCompletionResponse`, `TournamentCompletionCreatedEvent` (event deferred to Phase 9)

### Database Schema & Triggers
- `apps/api/migrations/0020_tournaments.sql` — `tournaments.completions` table definition (UNIQUE on cycle_id/user_id/inserted_at), `core.completions.tournament_completion_id` FK
- `apps/api/migrations/0017_fix_speed_trigger_check_verified.sql` — `enforce_speed_rules_nonlegacy_only()` trigger on `core.completions` that the cross-write CTE must avoid triggering on error

### Existing Patterns
- `apps/api/services/completions_service.py` — Reference for existing completion submission flow (submit_completion method)
- `apps/api/routes/v3/completions.py` — Reference for existing submission endpoint pattern
- `apps/api/services/base.py` — `BaseService` base class (publish_message NOT used in this phase)
- `apps/api/repository/exceptions.py` — Repository exception types (UniqueConstraintViolationError, ForeignKeyViolationError)

### Prior Phase Context
- `.planning/phases/01-database-schema-migrations/01-CONTEXT.md` — D-01 (boolean verified), D-02 (tier-then-time ranking), D-03 (global cooldown)
- `.planning/phases/03-repository-layer/03-CONTEXT.md` — D-03 to D-05 (cross-write CTE design), D-06/D-07 (leaderboard query), D-10/D-11 (exception handling)
- `.planning/phases/04-config-category-management/04-CONTEXT.md` — D-01 (auth scopes), D-02 (single controller), D-04 (single service), D-05 (active cycle check pattern)
- `.planning/phases/05-map-selection-blacklist/05-CONTEXT.md` — D-06 (tournaments:write scope)

### Project Planning
- `.planning/PROJECT.md` — Constraints section (no ORM, bot never writes to DB, existing patterns)
- `.planning/REQUIREMENTS.md` — SUB-01 through SUB-06 (requirements this phase covers)
- `.planning/ROADMAP.md` — Phase 6 success criteria (5 items)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `TournamentRepository.create_tournament_completion()` — inserts into `tournaments.completions` with full exception handling
- `TournamentRepository.cross_write_to_core()` — CTE that checks current best, conditionally inserts to `core.completions` with `tournament_completion_id` link, computes `completion` flag from map metadata
- `TournamentRepository.fetch_leaderboard(cycle_id)` — `DISTINCT ON` + `RANK() OVER` query with user name JOIN
- `TournamentRepository.fetch_user_completion(cycle_id, user_id)` — needed for speed enforcement check
- `TournamentRepository.fetch_active_cycle(category_id)` — validates cycle is active
- `TournamentRepository.fetch_cycle_history(category_id, limit, offset)` — base for cycles list endpoint
- `TournamentService` — existing service with config/category/map-selection methods to extend

### Established Patterns
- Service acquires connection for check-then-mutate: `async with self._pool.acquire() as conn, conn.transaction():`
- Domain exceptions with context: `SlowerTimeError(current_best, submitted_time)` pattern
- Controller catches domain exceptions and maps to HTTP status codes
- `msgspec.convert(row, ResponseStruct)` for converting repo dicts to SDK structs
- Bot-called endpoints use `user_id` in request body, authenticated via API key

### Integration Points
- `apps/api/services/tournament_service.py` — add `submit_completion`, `get_leaderboard`, `list_cycles` methods
- `apps/api/routes/v3/tournaments.py` — add 3 new endpoint handlers (submit, leaderboard, cycles list)
- `apps/api/services/exceptions/tournaments.py` — add `SlowerTimeError`, `CycleNotActiveError`, `MapMismatchError`
- `libs/sdk/src/genjishimada_sdk/tournaments.py` — may need `TournamentLeaderboardEntryResponse`, `TournamentCycleListResponse` structs

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

*Phase: 6-Submission Flow & Leaderboard*
*Context gathered: 2026-05-29*
