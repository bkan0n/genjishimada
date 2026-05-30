# Phase 6: Submission Flow & Leaderboard - Research

**Researched:** 2026-05-29
**Domain:** Tournament completion submission, speed enforcement, cross-write, leaderboard/history endpoints
**Confidence:** HIGH

## Summary

Phase 6 adds three new service methods and three new controller endpoints to the existing `TournamentService` and `TournamentsController`, plus two new domain exceptions and one new SDK response struct. The repository layer is fully built (Phase 3) with all needed SQL methods: `create_tournament_completion`, `cross_write_to_core`, `fetch_leaderboard`, `fetch_user_completion`, `fetch_active_cycle`, and `fetch_cycle_history`. The service layer from Phase 4/5 (`TournamentService`) already has the DI wiring, `BaseService` inheritance, and the connection-acquire-then-transaction pattern needed for the transactional submission flow.

The primary technical risk is the cross-write interaction with `core.enforce_speed_rules_nonlegacy_only()` trigger on `core.completions`. The existing `cross_write_to_core` CTE already handles this by pre-checking current best time before inserting, making the trigger a safety net rather than the primary guard. The CTE returns `NULL` when the tournament time is not faster, so the cross-write is a no-op in that case.

The cycles listing endpoint (D-09/D-10/D-11) requires a new or modified repository method since the existing `fetch_cycle_history` only filters by `category_id` and does not support optional `status` or cross-category listing. The CONTEXT.md decision calls for `GET /tournaments/cycles` with optional `status` and `category_id` query params, which differs from the existing method signature. A new `fetch_cycles` repository method or an extension of the existing one is needed.

**Primary recommendation:** Implement in 2 plans -- (1) SDK/exceptions/service methods, (2) controller endpoints and integration tests. The repository layer is complete; no new SQL methods are needed except potentially a modified cycle listing query.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Per-cycle speed enforcement rejects slower re-submissions with `SlowerTimeError(TournamentsError)` domain exception (409 Conflict)
- **D-02:** Single transaction: acquire -> check speed -> insert `tournaments.completions` -> cross-write to `core.completions` (CTE) -> commit
- **D-03:** Full validation before insert: cycle active, map matches cycle's map_id, user exists. Domain exceptions: `CycleNotActiveError`, `MapMismatchError`
- **D-04:** Submission endpoint: `POST /tournaments/cycles/{cycle_id}/submit`. Body: `TournamentCompletionCreateRequest` with `user_id`, `time`, `screenshot`, optional `video`
- **D-05:** Leaderboard endpoint: `GET /tournaments/cycles/{cycle_id}/leaderboard`. Uses existing `fetch_leaderboard` repo method
- **D-06:** Bot-only submission endpoint, authenticated via API key with `tournaments:write` scope
- **D-07:** No user submission lookup endpoint in this phase
- **D-08:** No RabbitMQ event publishing in Phase 6 (deferred to Phase 9)
- **D-09:** Cycle listing endpoint: `GET /tournaments/cycles` with `status` and `category_id` query params
- **D-10:** Offset-based pagination via `limit` and `offset` query params
- **D-11:** Each cycle entry returns metadata plus rank-1 winner info

### Claude's Discretion
- Exact exception class signatures for SlowerTimeError, CycleNotActiveError, MapMismatchError
- Response struct for cycle listing with winner info (new struct or extend existing)
- Whether `GET /tournaments/cycles` needs a dedicated repo method or reuses `fetch_cycle_history` with filters
- Service method names (`submit_completion` or `create_tournament_completion`)
- Pagination defaults (limit=20 typical in codebase)
- Whether cycles list endpoint returns active/pending/completed or just completed cycles

### Deferred Ideas (OUT OF SCOPE)
None
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SUB-01 | Tournament completion submission with tier-then-time ranking | Repo's `create_tournament_completion` inserts records; `fetch_leaderboard` uses `RANK() OVER (ORDER BY verified DESC, time ASC)` for tier-then-time |
| SUB-02 | Separate tournaments.completions with per-cycle speed enforcement | Service checks `fetch_user_completion` for existing best, raises `SlowerTimeError` if new time is not faster |
| SUB-03 | Cross-write to core.completions only when strictly faster | Repo's `cross_write_to_core` CTE pre-checks current best and conditionally inserts |
| SUB-04 | tournament_completion_id FK on core.completions for linking | CTE sets `tournament_completion_id` on inserted row; FK column already exists from Phase 1 migration |
| SUB-05 | Per-cycle tournament leaderboard endpoint | `GET /tournaments/cycles/{cycle_id}/leaderboard` using `fetch_leaderboard` |
| SUB-06 | Tournament history/archive endpoint | `GET /tournaments/cycles` with status/category_id filters and winner info |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Completion submission | API / Backend | Database | Service orchestrates validation + transaction; repo executes SQL |
| Speed enforcement | API / Backend | Database | Service checks via repo; trigger on core.completions is safety net |
| Cross-write | Database | API / Backend | CTE runs entirely in DB; service calls repo method within transaction |
| Leaderboard ranking | Database | API / Backend | SQL RANK() window function computes ranks; service converts to structs |
| Cycle listing/history | API / Backend | Database | Service queries repo with filters; controller handles pagination params |
| Authentication/scopes | API / Backend | -- | Litestar auth middleware + scope guard (`tournaments:write`, `tournaments:read`) |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| asyncpg | >=0.30.0 | PostgreSQL async driver for all DB ops | Already in use, project standard [VERIFIED: pyproject.toml] |
| litestar | >=2.16.0 | REST API framework for controller endpoints | Already in use, project standard [VERIFIED: pyproject.toml] |
| msgspec | >=0.19.0 | Struct serialization/deserialization | Already in use for all SDK types [VERIFIED: pyproject.toml] |
| pytest | >=8.3.5 | Test runner | Already in use [VERIFIED: pyproject.toml] |
| pytest-mock | >=3.15.1 | Mock utilities for unit tests | Already in use [VERIFIED: pyproject.toml] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest-databases[postgres] | >=0.14.0 | DB fixtures for integration tests | Integration tests needing real PostgreSQL |
| pytest-xdist | >=3.8.0 | Parallel test execution | Running full test suite |

**Installation:** No new packages needed. All dependencies are already installed.

## Package Legitimacy Audit

No new packages are being installed in this phase. All libraries are already project dependencies.

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
Bot (Discord.py)
    |
    | POST /tournaments/cycles/{cycle_id}/submit
    | (API key + tournaments:write scope)
    v
TournamentsController
    |
    | delegates to
    v
TournamentService.submit_completion()
    |
    | 1. Fetch cycle -> validate active + map matches
    | 2. Fetch user's best for this cycle -> speed check
    | 3. Insert tournaments.completions
    | 4. Cross-write CTE -> core.completions (if faster)
    | 5. All in single transaction
    v
TournamentRepository
    |  create_tournament_completion()
    |  cross_write_to_core()
    v
PostgreSQL
    |  tournaments.completions (INSERT)
    |  core.completions (conditional INSERT via CTE)
    |  enforce_speed_rules_nonlegacy_only() trigger (safety net)
```

```
Any Client
    |
    | GET /tournaments/cycles/{cycle_id}/leaderboard
    | GET /tournaments/cycles?status=completed&category_id=3&limit=20&offset=0
    v
TournamentsController
    |
    v
TournamentService.get_leaderboard() / list_cycles()
    |
    v
TournamentRepository.fetch_leaderboard() / fetch_cycles()
    |
    v
PostgreSQL (RANK() OVER window function / paginated query with JOINs)
```

### Recommended Project Structure

No new files beyond what is modified:

```
apps/api/
  services/
    tournament_service.py          # ADD: submit_completion, get_leaderboard, list_cycles
    exceptions/
      tournaments.py               # ADD: SlowerTimeError, MapMismatchError
  routes/v3/
    tournaments.py                 # ADD: 3 new endpoint handlers
  repository/
    tournaments_repository.py      # MODIFY: possibly add fetch_cycles or extend fetch_cycle_history
libs/sdk/src/genjishimada_sdk/
  tournaments.py                   # ADD: TournamentCycleWithWinnerResponse (new response struct)
apps/api/tests/
  services/
    test_tournament_service.py     # ADD: submission flow unit tests
  integration/
    test_tournaments_integration.py # ADD: submission + leaderboard + cycles integration tests
```

### Pattern 1: Transactional Check-Then-Mutate (Submission Flow)

**What:** Acquire a single connection, run validation checks and mutations in one transaction
**When to use:** Any multi-step operation that must be atomic (speed check + insert + cross-write)
**Example:**
```python
# Source: apps/api/services/tournament_service.py (existing pattern from update_category)
async def submit_completion(
    self,
    cycle_id: int,
    data: TournamentCompletionCreateRequest,
) -> TournamentCompletionResponse:
    async with self._pool.acquire() as conn, conn.transaction():
        # 1. Validate cycle is active
        cycle = await self._tournament_repo.fetch_cycle(cycle_id, conn=conn)
        if cycle is None:
            raise CycleNotFoundError(cycle_id)
        if cycle["status"] != "active":
            raise CycleNotActiveError(cycle_id, cycle["status"])

        # 2. Validate map matches
        if data.map_id != cycle["map_id"]:  # (or however map is referenced)
            raise MapMismatchError(...)

        # 3. Check speed enforcement
        existing = await self._tournament_repo.fetch_user_completion(
            cycle_id, data.user_id, conn=conn
        )
        if existing and data.time >= existing["time"]:
            raise SlowerTimeError(
                current_best=existing["time"],
                submitted_time=data.time,
            )

        # 4. Insert tournament completion
        row = await self._tournament_repo.create_tournament_completion(
            cycle_id=cycle_id,
            user_id=data.user_id,
            map_id=cycle["map_id"],
            time=data.time,
            screenshot=data.screenshot,
            video=data.video,
            conn=conn,
        )

        # 5. Cross-write to core.completions (CTE handles faster-check)
        await self._tournament_repo.cross_write_to_core(
            tournament_completion_id=row["id"],
            user_id=data.user_id,
            map_id=cycle["map_id"],
            time=data.time,
            screenshot=data.screenshot,
            video=data.video,
            conn=conn,
        )

    return msgspec.convert(row, TournamentCompletionResponse)
```

### Pattern 2: Controller Exception-to-HTTP Translation

**What:** Controller catches domain exceptions and maps to HTTP status codes
**When to use:** Every new endpoint handler
**Example:**
```python
# Source: apps/api/routes/v3/tournaments.py (existing pattern)
@litestar.post(
    path="/cycles/{cycle_id:int}/submit",
    summary="Submit Tournament Completion",
    status_code=HTTP_201_CREATED,
    opt={"required_scopes": {"tournaments:write"}},
)
async def submit_completion(
    self,
    tournament_service: TournamentService,
    cycle_id: Annotated[int, Parameter(description="Cycle ID")],
    data: Annotated[TournamentCompletionCreateRequest, Body(title="Submission")],
) -> TournamentCompletionResponse:
    try:
        return await tournament_service.submit_completion(cycle_id, data)
    except CycleNotFoundError as e:
        raise CustomHTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e)) from e
    except CycleNotActiveError as e:
        raise CustomHTTPException(status_code=HTTP_409_CONFLICT, detail=str(e)) from e
    except SlowerTimeError as e:
        raise CustomHTTPException(status_code=HTTP_409_CONFLICT, detail=str(e)) from e
    except MapMismatchError as e:
        raise CustomHTTPException(status_code=HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e)) from e
```

### Pattern 3: New Repository Method for Cycle Listing

**What:** A query that supports optional filters (status, category_id) with pagination
**When to use:** The cycles listing endpoint needs cross-category listing with optional filtering
**Example:**
```python
# Source: Pattern derived from existing fetch_cycle_history + conditional SQL from fetch_eligible_maps
async def fetch_cycles(
    self,
    *,
    status: str | None = None,
    category_id: int | None = None,
    limit: int = 20,
    offset: int = 0,
    conn: Connection | None = None,
) -> tuple[int, list[dict]]:
    _conn = self._get_connection(conn)
    conditions = []
    args: list[object] = []
    idx = 1

    if status is not None:
        conditions.append(f"cy.status = ${idx}")
        args.append(status)
        idx += 1
    if category_id is not None:
        conditions.append(f"cy.category_id = ${idx}")
        args.append(category_id)
        idx += 1

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    count_query = f"SELECT COUNT(*) FROM tournaments.cycles cy {where_clause}"
    total = await _conn.fetchval(count_query, *args) or 0

    # Main query with JOIN to get winner info (rank-1 user)
    data_query = f"""
        SELECT cy.*, m.code AS map_code, m.map_name, m.difficulty AS map_difficulty,
               winner.name AS winner_name, winner.user_id AS winner_user_id
        FROM tournaments.cycles cy
        JOIN core.maps m ON m.id = cy.map_id
        LEFT JOIN LATERAL (
            SELECT bpu.user_id, COALESCE(u.global_name, u.nickname, 'Unknown') AS name
            FROM tournaments.completions tc
            JOIN (
                SELECT DISTINCT ON (tc2.user_id) tc2.user_id, tc2.verified, tc2.time
                FROM tournaments.completions tc2
                WHERE tc2.cycle_id = cy.id
                ORDER BY tc2.user_id, tc2.verified DESC, tc2.time ASC
            ) bpu ON TRUE
            JOIN core.users u ON u.id = bpu.user_id
            ORDER BY bpu.verified DESC, bpu.time ASC
            LIMIT 1
        ) winner ON TRUE
        {where_clause}
        ORDER BY cy.created_at DESC
        LIMIT ${idx} OFFSET ${idx + 1}
    """
    args.extend([limit, offset])
    rows = await _conn.fetch(data_query, *args)
    return total, [dict(row) for row in rows]
```

### Anti-Patterns to Avoid

- **Validating speed in SQL trigger alone:** The `enforce_speed_rules_nonlegacy_only()` trigger on `core.completions` will fire on the cross-write INSERT. The CTE pre-checks to avoid triggering an error, but the trigger acts as a safety net. Never rely on the trigger as the primary speed check -- it does not cover `tournaments.completions` at all.

- **Separate transactions for insert and cross-write:** The tournament completion insert and cross-write to core MUST be in the same transaction. If the cross-write fails after the tournament completion was committed, the system would be in an inconsistent state.

- **Using `BaseService.publish_message()` in this phase:** D-08 explicitly defers RabbitMQ publishing to Phase 9. Do not import or call `publish_message` for submission events.

- **Checking `verified` field in speed enforcement:** Per the DB schema, tournament completions start with `verified = FALSE`. The speed check compares by `time` only (the user's best for the cycle, regardless of verification status). The tier-then-time ranking only applies to leaderboard display, not speed enforcement.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Leaderboard ranking | Custom Python sorting logic | SQL `RANK() OVER (ORDER BY verified DESC, time ASC)` | Already built in repo's `fetch_leaderboard`; DB-side ranking is correct and performant |
| Cross-write best-time check | Python-side comparison with separate queries | Single CTE with `should_insert` logic | Avoids race conditions; CTE is atomic within the transaction |
| Pagination | Custom cursor-based pagination | `LIMIT $N OFFSET $M` with `COUNT(*)` | Matches existing codebase pattern (limit/offset), per D-10 |
| Speed enforcement | Trigger-based rejection | Service-layer pre-check via `fetch_user_completion` | Trigger on `core.completions` does not protect `tournaments.completions`; service must enforce |

**Key insight:** The repository layer built in Phase 3 already contains all the complex SQL (CTE cross-write, RANK() leaderboard, DISTINCT ON best-per-user). Phase 6 is purely service orchestration and HTTP wiring.

## Common Pitfalls

### Pitfall 1: Speed Enforcement Trigger on Cross-Write

**What goes wrong:** The cross-write CTE inserts into `core.completions`, which has the `enforce_speed_rules_nonlegacy_only()` trigger. If the CTE tries to insert a time that is not faster than the user's existing best non-legacy record, the trigger raises an exception and the entire transaction rolls back.
**Why it happens:** The CTE's `should_insert` check uses `$4 < cb.best_time` (strictly less than), but the trigger checks `new.time >= best_time` (greater than or equal). They are logically aligned. However, a TOCTOU race could theoretically occur if another transaction inserts a faster time between the CTE check and the actual INSERT.
**How to avoid:** The CTE's `should_insert` clause prevents the INSERT from executing when the time is not faster, so the trigger never fires on an invalid row. The transaction isolation level (default READ COMMITTED) is sufficient because the CTE subquery and INSERT happen in a single statement.
**Warning signs:** `CheckViolationError` with message containing `completion=TRUE time % must be strictly faster` during cross-write.

### Pitfall 2: Missing Map Validation in Submission

**What goes wrong:** A user submits a completion for cycle X but references a map that is not the cycle's assigned map. The FK constraint on `tournaments.completions.map_id` would catch an invalid map, but it would not catch a valid map that simply is not the one assigned to this cycle.
**Why it happens:** The service must explicitly check `cycle["map_id"]` matches the submission. The `TournamentCompletionCreateRequest` does NOT include `map_id` -- it only has `user_id`, `time`, `screenshot`, `video`. The service must extract `map_id` from the fetched cycle.
**How to avoid:** Do not accept `map_id` from the request body. Fetch the cycle, extract its `map_id`, and pass it to `create_tournament_completion` and `cross_write_to_core`. This eliminates the `MapMismatchError` validation entirely -- the map is always correct because it comes from the cycle.
**Warning signs:** If the request body includes `map_id`, the validation gap exists.

### Pitfall 3: fetch_cycle_history vs. fetch_cycles

**What goes wrong:** The existing `fetch_cycle_history(category_id, limit, offset)` requires `category_id` as a mandatory parameter. D-09 specifies `GET /tournaments/cycles` with `category_id` as an optional filter. Using `fetch_cycle_history` directly would require `category_id` to always be provided.
**Why it happens:** The method was designed for Phase 3's needs (per-category history), not for the cross-category listing endpoint.
**How to avoid:** Either create a new `fetch_cycles` method with optional filters, or modify `fetch_cycle_history` to accept `category_id` as optional. The new method is cleaner since it also needs to JOIN for winner info (D-11).
**Warning signs:** 404 or validation errors when calling cycles list without `category_id`.

### Pitfall 4: Winner Info for Active/Pending Cycles

**What goes wrong:** The cycle listing includes winner info (rank-1 user), but active/pending cycles may have zero submissions. The `LEFT JOIN LATERAL` for winner must handle NULL gracefully.
**Why it happens:** Only completed cycles have finalized winners. Active cycles have evolving leaderboards. Pending cycles have no submissions.
**How to avoid:** Use `LEFT JOIN LATERAL` so cycles without submissions still appear in results. The `winner_name` and `winner_user_id` will be NULL for cycles with no submissions.
**Warning signs:** Missing cycles in listing results, or exceptions when trying to access winner fields.

## Code Examples

### Domain Exception: SlowerTimeError

```python
# Source: Pattern from existing tournaments.py exceptions
class SlowerTimeError(TournamentsError):
    """Submitted time is not faster than the user's current best for this cycle."""

    def __init__(self, current_best: float, submitted_time: float) -> None:
        super().__init__(
            f"Submitted time ({submitted_time}s) is not faster than your current best ({current_best}s).",
            current_best=current_best,
            submitted_time=submitted_time,
        )
```

### Domain Exception: MapMismatchError

```python
# Source: Pattern from existing tournaments.py exceptions
class MapMismatchError(TournamentsError):
    """Submitted map does not match the cycle's assigned map."""

    def __init__(self, cycle_id: int, expected_map_id: int, submitted_map_id: int) -> None:
        super().__init__(
            f"Map mismatch: cycle {cycle_id} uses map {expected_map_id}, not {submitted_map_id}.",
            cycle_id=cycle_id,
            expected_map_id=expected_map_id,
            submitted_map_id=submitted_map_id,
        )
```

### SDK: TournamentCycleWithWinnerResponse

```python
# Source: Pattern from existing TournamentCycleResponse + winner fields per D-11
class TournamentCycleWithWinnerResponse(Struct):
    """Cycle entry for listing, including rank-1 winner info."""

    id: int
    category_id: int
    map_id: int
    map_code: str
    map_name: str
    map_difficulty: str
    status: CycleStatus
    started_at: dt.datetime | None
    ended_at: dt.datetime | None
    created_at: dt.datetime
    winner_name: str | None
    winner_user_id: int | None
```

### Service Unit Test Pattern (Mock-based)

```python
# Source: Pattern from existing test_tournament_service.py
_completion = lambda **kw: {
    "id": 1, "cycle_id": 1, "user_id": 100, "map_id": 10,
    "time": 42.5, "screenshot": "https://example.com/s.png",
    "video": None, "verified": False, "completion": False,
    "inserted_at": "2026-01-01T00:00:00",
    **kw,
}

class TestSubmitCompletion:
    async def test_rejects_slower_time(self, mock_pool, mock_state, mock_tournament_repo):
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)
        mock_tournament_repo.fetch_cycle.return_value = {"id": 1, "status": "active", "map_id": 10}
        mock_tournament_repo.fetch_user_completion.return_value = _completion(time=30.0)

        with pytest.raises(SlowerTimeError):
            await service.submit_completion(1, TournamentCompletionCreateRequest(
                user_id=100, time=35.0, screenshot="https://example.com/s.png"
            ))
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `handle_db_exceptions` decorator | Three-tier exception hierarchy (repo -> service -> controller) | Phase 2 decision | All new endpoints use catch-translate pattern, not decorator |
| `fetch_cycle_history(category_id)` | New `fetch_cycles` with optional filters | Phase 6 (this phase) | Enables cross-category listing with optional status filter |

**Deprecated/outdated:**
- `handle_db_exceptions` decorator: Still present on older endpoints but NOT used for new tournament code. All new endpoints follow the three-tier catch-translate pattern.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `MapMismatchError` may be unnecessary if service extracts `map_id` from cycle rather than accepting it in the request | Pitfall 2 | Slight over-engineering; exception exists but is never raised. Low risk. |
| A2 | The winner info query using `LEFT JOIN LATERAL` with a subquery is the right approach for D-11 | Pattern 3 | Could use a simpler approach (separate query per cycle), but LATERAL is more performant for batch listing |
| A3 | `CycleNotFoundError` already exists in the exceptions module | Common across code | If missing, needs to be added alongside SlowerTimeError and MapMismatchError |

## Open Questions (RESOLVED)

1. **Should `MapMismatchError` be kept or dropped?**
   - RESOLVED: Add the exception class for completeness (it is cheap), but the service method extracts `map_id` from the cycle and does not accept it from the request body. Plan 01 Task 1 creates the class; Plan 01 Task 2 service method uses `cycle["map_id"]` directly. If future phases need to validate a submitted map_id, the exception is ready.

2. **fetch_cycles: New method or modify fetch_cycle_history?**
   - RESOLVED: Add a new `fetch_cycles` method. Plan 01 Task 2 creates this as a separate repository method with optional `status` and `category_id` filters plus winner info JOIN. The existing `fetch_cycle_history` is preserved for other callers.

3. **Pagination response format: total count or not?**
   - RESOLVED: Return the total count in a wrapper struct. Plan 01 Task 1 creates `TournamentCycleListResponse` with `total: int` and `cycles: list[TournamentCycleWithWinnerResponse]` fields. Plan 01 Task 2 service method returns this struct.

## Project Constraints (from CLAUDE.md)

The following CLAUDE.md directives constrain implementation:

- **No ORM:** All database access uses raw SQL via asyncpg
- **Bot never writes directly to DB:** Bot calls API endpoints (submission endpoint is bot-called)
- **Three-tier exception pattern:** Repository exceptions -> Domain exceptions -> HTTP exceptions
- **Line length:** 120 characters
- **Docstring convention:** Google style
- **Type annotations:** Required for all function signatures
- **`log = getLogger(__name__)`** at module level
- **`%s`-style formatting** in log calls
- **Connection pattern:** `async with self._pool.acquire() as conn, conn.transaction():`
- **Test markers:** `pytestmark = [pytest.mark.domain_tournaments]` for service tests, plus `pytest.mark.integration` for integration tests
- **Test headers:** `X-PYTEST-ENABLED=1` to skip queue publishing
- **Scope guards:** Use `opt={"required_scopes": {"tournaments:write"}}` on mutation endpoints
- **`from e` pattern:** Always use `from e` when re-raising exceptions
- **`CustomHTTPException`** for HTTP error responses (not `HTTPException`)

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.3.5+ with pytest-asyncio (mode: auto) |
| Config file | `apps/api/pyproject.toml` |
| Quick run command | `uv run --directory apps/api pytest tests/services/test_tournament_service.py -v -p no:xdist` |
| Full suite command | `just test-api` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SUB-01 | Submit tournament completion, stored in tournaments.completions | unit + integration | `uv run --directory apps/api pytest tests/services/test_tournament_service.py::TestSubmitCompletion -v -p no:xdist` | Wave 0 |
| SUB-02 | Per-cycle speed enforcement rejects slower re-submissions | unit | `uv run --directory apps/api pytest tests/services/test_tournament_service.py::TestSubmitCompletion::test_rejects_slower_time -v -p no:xdist` | Wave 0 |
| SUB-03 | Cross-write to core.completions when tournament time is strictly faster | integration | `uv run --directory apps/api pytest tests/integration/test_tournaments_integration.py::TestSubmitCompletionEndpoint::test_cross_write -v -p no:xdist` | Wave 0 |
| SUB-04 | tournament_completion_id FK set on core.completions | integration | `uv run --directory apps/api pytest tests/integration/test_tournaments_integration.py::TestSubmitCompletionEndpoint::test_cross_write_sets_fk -v -p no:xdist` | Wave 0 |
| SUB-05 | Leaderboard endpoint returns ranked standings | integration | `uv run --directory apps/api pytest tests/integration/test_tournaments_integration.py::TestLeaderboardEndpoint -v -p no:xdist` | Wave 0 |
| SUB-06 | Cycle listing endpoint with status/category filters | integration | `uv run --directory apps/api pytest tests/integration/test_tournaments_integration.py::TestCycleListingEndpoint -v -p no:xdist` | Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run --directory apps/api pytest tests/services/test_tournament_service.py tests/integration/test_tournaments_integration.py -v -p no:xdist`
- **Per wave merge:** `just test-api`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/services/test_tournament_service.py::TestSubmitCompletion` -- service unit tests for submission flow
- [ ] `tests/services/test_tournament_service.py::TestGetLeaderboard` -- service unit tests for leaderboard retrieval
- [ ] `tests/services/test_tournament_service.py::TestListCycles` -- service unit tests for cycle listing
- [ ] `tests/integration/test_tournaments_integration.py::TestSubmitCompletionEndpoint` -- integration tests for submission endpoint (includes test_cross_write_sets_fk for SUB-04)
- [ ] `tests/integration/test_tournaments_integration.py::TestLeaderboardEndpoint` -- integration tests for leaderboard endpoint
- [ ] `tests/integration/test_tournaments_integration.py::TestCycleListingEndpoint` -- integration tests for cycle listing endpoint

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | Litestar CustomAuthenticationMiddleware validates API key in `X-API-KEY` header |
| V3 Session Management | no | No session management in this phase (API key auth only) |
| V4 Access Control | yes | Scope guard: `tournaments:write` for submission, `tournaments:read` for leaderboard/listing |
| V5 Input Validation | yes | msgspec Struct type validation (automatic deserialization); service-layer business rule validation |
| V6 Cryptography | no | No cryptographic operations in this phase |

### Known Threat Patterns for This Phase

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Unauthorized submission (spoofed user_id) | Spoofing | Bot-only endpoint with API key + `tournaments:write` scope; bot passes user_id |
| SQL injection via cycle_id/user_id | Tampering | asyncpg positional parameters ($1, $2) -- never string interpolation |
| Race condition on speed check | Tampering | Single transaction with connection-level isolation; CTE atomic check-then-insert |
| Enumeration via leaderboard | Information Disclosure | Low risk -- leaderboard data is intentionally public within the community |

## Sources

### Primary (HIGH confidence)
- `apps/api/repository/tournaments_repository.py` -- all repo methods verified by reading source
- `apps/api/services/tournament_service.py` -- existing service patterns verified
- `apps/api/routes/v3/tournaments.py` -- existing controller patterns verified
- `apps/api/services/exceptions/tournaments.py` -- existing exception hierarchy verified
- `libs/sdk/src/genjishimada_sdk/tournaments.py` -- all SDK structs verified
- `apps/api/migrations/0020_tournaments.sql` -- schema verified
- `apps/api/migrations/0017_fix_speed_trigger_check_verified.sql` -- trigger behavior verified
- `apps/api/migrations/0001_init.sql` -- `core.completions` schema verified
- `.planning/phases/06-submission-flow-leaderboard/06-CONTEXT.md` -- all locked decisions

### Secondary (MEDIUM confidence)
- `.planning/phases/03-repository-layer/03-CONTEXT.md` -- cross-write CTE design decisions
- `apps/api/services/completions_service.py` -- existing completion submission pattern reference
- `apps/api/routes/v3/completions.py` -- existing endpoint exception handling reference

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - all libraries already in use, no new dependencies
- Architecture: HIGH - extends existing patterns (service, controller, repo) with no novel components
- Pitfalls: HIGH - trigger behavior verified by reading migration SQL; race conditions addressed by CTE design

**Research date:** 2026-05-29
**Valid until:** 2026-06-29 (stable -- no external dependencies changing)
