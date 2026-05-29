# Phase 5: Map Selection & Blacklist - Research

**Researched:** 2026-05-29
**Domain:** Service/controller layer for map selection logic with PostgreSQL-backed blacklist, pending cycle management, and admin override endpoints
**Confidence:** HIGH

## Summary

Phase 5 extends the existing `TournamentService` and `TournamentsController` with map selection business logic and 4 new API endpoints. All repository methods needed for map selection (`fetch_eligible_maps`, `fetch_least_recently_used_map`, `create_cycle`) already exist from Phase 3. This phase adds: (1) new repository methods for pending cycle management (`fetch_pending_cycle`, `delete_cycle`), (2) service methods that orchestrate the selection flow with transaction safety, (3) new SDK structs for request/response, (4) controller endpoints, and (5) a new domain exception (`NoEligibleMapsError`).

The codebase is well-established with clear patterns from Phase 4. The service layer follows check-then-mutate under `async with self._pool.acquire() as conn:` for atomicity. The controller layer catches domain exceptions and maps them to HTTP status codes. All existing patterns are directly applicable.

**Primary recommendation:** Follow the Phase 4 pattern exactly -- extend `TournamentService` with 4 new methods, extend `TournamentsController` with 4 new endpoint handlers, add 2 new repository methods, add 1-2 SDK structs, and add 1-2 domain exceptions.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Pre-rolled next-cycle maps are stored as `tournaments.cycles` records with `status = 'pending'`. No new table needed.
- **D-02:** Each category has at most one pending cycle at a time.
- **D-03:** Selection flow: fetch config -> fetch category -> fetch_eligible_maps -> take first result (randomized) -> if empty use LRU fallback -> if still None raise NoEligibleMapsError -> create pending cycle.
- **D-04:** Map cooldown is global across ALL categories.
- **D-05:** Endpoints nested under existing category paths in TournamentsController:
  - `GET /tournaments/categories/{category_id}/next-cycle`
  - `POST /tournaments/categories/{category_id}/select-map`
  - `POST /tournaments/categories/{category_id}/reroll`
  - `PATCH /tournaments/categories/{category_id}/next-cycle`
- **D-06:** Write endpoints require `tournaments:write`, preview requires `tournaments:read`.
- **D-07:** Reroll = delete pending + create new. Excluded map stays in blacklist window.
- **D-08:** LRU fallback when pool exhausted, `NoEligibleMapsError` when LRU also returns None.
- **D-09:** `NoEligibleMapsError(TournamentsError)` mapped to 422 in controller.
- **D-10:** Service methods: `select_map`, `get_next_cycle`, `reroll_map`, `choose_map`.
- **D-11:** `select_map` acquires a connection and runs within a transaction.

### Claude's Discretion
- Exact response struct for next-cycle preview (could reuse `TournamentCycleResponse` or create a lighter struct with map details joined)
- Whether `choose_map` accepts `map_code` (string) or `map_id` (int) or both
- Whether to add `PendingCycleAlreadyExistsError` or reuse a generic conflict error
- SQL for fetching pending cycle with joined map info (simple JOIN or CTE)
- Logging format for pool exhaustion warning

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.

</user_constraints>

<phase_requirements>

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CYCLE-04 | Map blacklist with configurable N-week cooldown window | `fetch_eligible_maps()` already implements the `WHERE cy.started_at > now() - make_interval(weeks => $2)` filter. Service reads `blacklist_weeks` from config. |
| CYCLE-05 | Random map selection from eligible pool per category each cycle | `fetch_eligible_maps()` uses `ORDER BY random()`. Service takes first result. Category difficulties filter the pool. |
| CYCLE-06 | Pre-rolled next-cycle maps generated at cycle transition | Pending cycles stored as `tournaments.cycles` with `status = 'pending'`. `create_cycle()` defaults to pending. |
| CYCLE-07 | Admin can preview, reroll, or explicitly choose next-cycle maps | Four new endpoints: GET preview, POST select, POST reroll, PATCH choose. All scoped to `tournaments:write`/`tournaments:read`. |

</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Map selection algorithm | API / Backend | Database / Storage | Business logic in service, eligible map query in repository |
| Blacklist cooldown filtering | Database / Storage | -- | Pure SQL window filter in `fetch_eligible_maps` |
| Pending cycle management | API / Backend | Database / Storage | Service orchestrates create/delete, DB stores state |
| Admin preview endpoint | API / Backend | -- | Read-only endpoint returning joined cycle + map data |
| Admin reroll/choose | API / Backend | Database / Storage | Service validates then mutates via repo |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Litestar | >=2.16.0 | REST framework for controller endpoints | Already used by all API routes [VERIFIED: pyproject.toml] |
| asyncpg | >=0.30.0 | PostgreSQL async driver for repository queries | Already used throughout repository layer [VERIFIED: pyproject.toml] |
| msgspec | >=0.19.0 | Request/response struct serialization | Already used for all SDK types [VERIFIED: pyproject.toml] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest | >=8.3.5 | Test runner | All service and integration tests [VERIFIED: pyproject.toml] |
| pytest-asyncio | >=1.2.0 | Async test support | All async test methods [VERIFIED: pyproject.toml] |
| pytest-mock | >=3.15.1 | Mock utilities for service unit tests | Service layer unit tests [VERIFIED: pyproject.toml] |

**Installation:** No new packages required. All dependencies already installed.

## Package Legitimacy Audit

No new packages are introduced in this phase. All code uses existing project dependencies.

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
Admin HTTP Request
        |
        v
TournamentsController (routes/v3/tournaments.py)
   |--- GET  .../next-cycle     -> get_next_cycle()
   |--- POST .../select-map     -> select_map()
   |--- POST .../reroll         -> reroll_map()
   |--- PATCH .../next-cycle    -> choose_map()
        |
        v
TournamentService (services/tournament_service.py)
   |--- Reads config (blacklist_weeks)
   |--- Reads category (difficulties)
   |--- Checks for existing pending cycle
   |--- Calls selection or validation logic
   |--- Creates/deletes pending cycle records
        |
        v
TournamentRepository (repository/tournaments_repository.py)
   |--- fetch_config()           [EXISTS]
   |--- fetch_category()         [EXISTS]
   |--- fetch_eligible_maps()    [EXISTS]
   |--- fetch_least_recently_used_map()  [EXISTS]
   |--- create_cycle()           [EXISTS]
   |--- fetch_pending_cycle()    [NEW - needs map JOIN]
   |--- delete_cycle()           [NEW]
   |--- fetch_map_by_code()      [NEW - for choose_map validation]
        |
        v
PostgreSQL (tournaments.cycles, tournaments.config, core.maps)
```

### Recommended Project Structure

No new files beyond extending existing ones:
```
apps/api/
  repository/tournaments_repository.py    # Add 3 new methods
  services/tournament_service.py          # Add 4 new service methods
  services/exceptions/tournaments.py      # Add 1-2 new exception classes
  routes/v3/tournaments.py                # Add 4 new endpoint handlers
libs/sdk/src/genjishimada_sdk/
  tournaments.py                          # Add 1-2 new structs
apps/api/tests/
  services/test_tournament_service.py     # NEW - service unit tests
  integration/test_tournaments_integration.py  # Extend with 4 endpoint test classes
```

### Pattern 1: Check-Then-Mutate Under Transaction

**What:** Acquire a connection, check precondition, mutate state -- all on the same connection to prevent TOCTOU races.
**When to use:** `select_map` (check no pending exists, then create), `reroll_map` (check pending exists, delete, create new).
**Example:**
```python
# Source: apps/api/services/tournament_service.py (existing update_category pattern)
async def select_map(self, category_id: int) -> TournamentCycleResponse:
    async with self._pool.acquire() as conn:
        # Check no pending cycle already exists
        existing = await self._tournament_repo.fetch_pending_cycle(
            category_id, conn=conn
        )
        if existing is not None:
            raise PendingCycleAlreadyExistsError(category_id)

        # Fetch config and category for selection params
        config = await self._tournament_repo.fetch_config(conn=conn)
        category = await self._tournament_repo.fetch_category(category_id, conn=conn)
        if category is None:
            raise CategoryNotFoundError(category_id)

        # Select map
        eligible = await self._tournament_repo.fetch_eligible_maps(
            category["difficulties"],
            config["blacklist_weeks"],
            conn=conn,
        )
        if eligible:
            selected = eligible[0]
        else:
            log.warning("[!] Eligible map pool exhausted for category %s, using LRU fallback", category_id)
            selected = await self._tournament_repo.fetch_least_recently_used_map(
                category["difficulties"], conn=conn
            )
            if selected is None:
                raise NoEligibleMapsError(category_id)

        # Create pending cycle
        cycle = await self._tournament_repo.create_cycle(
            category_id, selected["id"], conn=conn
        )
        return msgspec.convert(cycle, TournamentCycleResponse)
```
[VERIFIED: existing pattern in tournament_service.py update_category/delete_category methods]

### Pattern 2: Controller Exception Mapping

**What:** Controller catches domain exceptions in try/except and maps them to `CustomHTTPException` with appropriate status codes.
**When to use:** All 4 new endpoint handlers.
**Example:**
```python
# Source: apps/api/routes/v3/tournaments.py (existing pattern)
except CategoryNotFoundError as e:
    raise CustomHTTPException(
        status_code=HTTP_404_NOT_FOUND,
        detail=str(e),
    ) from e
except PendingCycleAlreadyExistsError as e:
    raise CustomHTTPException(
        status_code=HTTP_409_CONFLICT,
        detail=str(e),
    ) from e
except NoEligibleMapsError as e:
    raise CustomHTTPException(
        status_code=HTTP_422_UNPROCESSABLE_ENTITY,
        detail=str(e),
    ) from e
```
[VERIFIED: existing pattern in tournaments controller]

### Pattern 3: Service Unit Tests with Mocked Repository

**What:** Service tests use `AsyncMock(spec=TournamentRepository)` to test business logic in isolation.
**When to use:** Testing select_map flow, reroll logic, choose_map validation.
**Example:**
```python
# Source: apps/api/tests/services/conftest.py pattern
@pytest.fixture
def mock_tournament_repo(mocker):
    return mocker.AsyncMock(spec=TournamentRepository)

# In test:
service = TournamentService(mock_pool, mock_state, mock_tournament_repo)
mock_tournament_repo.fetch_pending_cycle.return_value = None
mock_tournament_repo.fetch_config.return_value = {"blacklist_weeks": 4}
mock_tournament_repo.fetch_category.return_value = {"difficulties": ["Medium"]}
mock_tournament_repo.fetch_eligible_maps.return_value = [{"id": 1, "code": "ABC", ...}]
```
[VERIFIED: existing pattern in tests/services/conftest.py and test_maps_service.py]

### Anti-Patterns to Avoid

- **Using handle_db_exceptions decorator:** Per CLAUDE.md, this is being superseded by the three-tier exception hierarchy. Use explicit try/except in services/controllers instead. [VERIFIED: CLAUDE.md]
- **Skipping the transaction boundary:** The `select_map` method MUST use `async with self._pool.acquire() as conn:` to prevent TOCTOU between checking for existing pending cycle and creating a new one. [VERIFIED: existing pattern in tournament_service.py]
- **Querying maps table by code without validation:** The `choose_map` endpoint must verify the chosen map exists AND matches the category's difficulty grouping before creating a pending cycle.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Random map selection | Custom random logic in Python | `ORDER BY random()` in PostgreSQL query | Already implemented in `fetch_eligible_maps`, database-level randomization is simpler and avoids loading all maps into memory [VERIFIED: repository code] |
| Blacklist window filtering | Manual date math in Python | `cy.started_at > now() - make_interval(weeks => $2)` in SQL | Already implemented, SQL handles timezone correctly [VERIFIED: repository code] |
| LRU map fallback | Custom sorting in Python | `ORDER BY cy.started_at ASC NULLS FIRST LIMIT 1` in SQL | Already implemented, database-level sort is correct [VERIFIED: repository code] |
| Request validation | Manual field checks | msgspec Struct type hints | Litestar auto-validates request bodies against Struct schemas [VERIFIED: SDK pattern] |

**Key insight:** The heavy lifting (random selection, blacklist filtering, LRU fallback) was already done in Phase 3's repository layer. This phase is pure orchestration and HTTP wiring.

## Common Pitfalls

### Pitfall 1: Pending Cycles Not Excluded from Eligible Pool
**What goes wrong:** A map assigned to a pending cycle in category A could be selected again for category B's pending cycle, since `fetch_eligible_maps` only checks `started_at` (NULL for pending cycles).
**Why it happens:** The blacklist query filters on `cy.started_at > now() - interval`, and pending cycles have `started_at = NULL`.
**How to avoid:** The service layer should also exclude maps that are currently in any pending cycle. Either: (a) modify the `fetch_eligible_maps` query to also exclude `WHERE status = 'pending'`, or (b) add a post-selection check in the service. Option (a) is cleaner -- add `AND cy.status != 'pending'` to the NOT IN subquery, or use a separate subquery `AND m.id NOT IN (SELECT map_id FROM tournaments.cycles WHERE status = 'pending')`.
**Warning signs:** Two categories showing the same map in their next-cycle preview.

### Pitfall 2: Reroll Re-selects the Same Map
**What goes wrong:** After deleting the pending cycle and re-running selection, `ORDER BY random()` could return the same map.
**Why it happens:** The deleted pending cycle's map is no longer excluded by the blacklist (it was never started, so it has no `started_at`).
**How to avoid:** Per D-07, "The newly selected map excludes the just-deleted map's map_id from the eligible pool." The service should pass the old `map_id` as an exclusion parameter to the selection query. Option: add an `exclude_map_ids: list[int] | None` parameter to `fetch_eligible_maps`, or handle exclusion in the service by filtering the result list.
**Warning signs:** Admin rerolls and gets the exact same map back.

### Pitfall 3: Category Not Found vs Pending Cycle Not Found
**What goes wrong:** Preview endpoint returns 404 but it's unclear whether the category doesn't exist or there's just no pending cycle.
**Why it happens:** Both conditions map to 404 if not distinguished.
**How to avoid:** Check category existence first (raise 404 with "Category not found"), then check pending cycle (raise 404 with "No pending cycle for this category"). Use separate domain exceptions or different error messages.
**Warning signs:** Admin confusion about why 404 is returned.

### Pitfall 4: Missing conn Parameter Passthrough
**What goes wrong:** Service acquires a connection for transaction safety but forgets to pass `conn=conn` to one of the repository calls, causing that call to use a different connection from the pool.
**Why it happens:** Easy to forget the `conn=conn` kwarg when adding new repository calls within an `async with self._pool.acquire() as conn:` block.
**How to avoid:** Every repository call within the transaction block MUST include `conn=conn`. Review each call during implementation.
**Warning signs:** Intermittent TOCTOU bugs under concurrent access.

### Pitfall 5: Type Annotation on conn Parameter
**What goes wrong:** BasedPyright complains about `conn` type mismatch because `pool.acquire()` returns `PoolConnectionProxy`, not `Connection`.
**Why it happens:** The repository method signatures use `conn: Connection | None` but the proxy isn't exactly `Connection`.
**How to avoid:** Use `# type: ignore[arg-type]` on the `conn=conn` kwarg, matching the existing pattern in `update_category` and `delete_category`.
**Warning signs:** Type check failures in CI.

## Code Examples

### New Repository Method: fetch_pending_cycle

```python
# Discretion area: use JOIN to include map details for the preview endpoint
async def fetch_pending_cycle(
    self,
    category_id: int,
    *,
    conn: Connection | None = None,
) -> dict | None:
    """Fetch the pending cycle for a category with map details.

    Args:
        category_id: Category ID.
        conn: Optional connection for transaction support.

    Returns:
        Pending cycle dict with map fields, or None if no pending cycle.
    """
    _conn = self._get_connection(conn)
    query = """
        SELECT cy.id, cy.category_id, cy.map_id, cy.status,
               cy.started_at, cy.ended_at, cy.created_at,
               m.code AS map_code, m.map_name, m.difficulty AS map_difficulty
        FROM tournaments.cycles cy
        JOIN core.maps m ON m.id = cy.map_id
        WHERE cy.category_id = $1 AND cy.status = 'pending'
        LIMIT 1
    """
    row = await _conn.fetchrow(query, category_id)
    return dict(row) if row else None
```
[Pattern source: existing fetch_active_cycle in tournaments_repository.py]

### New Repository Method: delete_cycle

```python
async def delete_cycle(
    self,
    cycle_id: int,
    *,
    conn: Connection | None = None,
) -> bool:
    """Delete a tournament cycle.

    Args:
        cycle_id: Cycle ID to delete.
        conn: Optional connection for transaction support.

    Returns:
        True if a cycle was deleted, False if not found.
    """
    _conn = self._get_connection(conn)
    result = await _conn.fetchval(
        "DELETE FROM tournaments.cycles WHERE id = $1 RETURNING id",
        cycle_id,
    )
    return result is not None
```
[Pattern source: existing delete_category in tournaments_repository.py]

### New SDK Struct: TournamentNextCycleResponse

```python
# Discretion area: create a dedicated response struct with map details
class TournamentNextCycleResponse(Struct):
    """Pending cycle preview with map information.

    Attributes:
        id: Cycle identifier.
        category_id: Category this cycle belongs to.
        map_id: Map selected for this cycle.
        map_code: Overwatch Workshop code.
        map_name: Map display name.
        map_difficulty: Map difficulty level.
        status: Current lifecycle status (always 'pending').
        created_at: When the pending cycle was created.
    """

    id: int
    category_id: int
    map_id: int
    map_code: str
    map_name: str
    map_difficulty: str
    status: CycleStatus
    created_at: dt.datetime
```

### New SDK Struct: TournamentChooseMapRequest

```python
# Discretion area: accept map_code (string) since admins think in codes, not IDs
class TournamentChooseMapRequest(Struct):
    """Request payload for explicitly choosing a map for next cycle.

    Attributes:
        map_code: Workshop code of the map to set.
    """

    map_code: str
```

### New Domain Exception: NoEligibleMapsError

```python
class NoEligibleMapsError(TournamentsError):
    """No eligible maps exist for selection."""

    def __init__(self, category_id: int) -> None:
        super().__init__(
            "No eligible maps found. Consider reducing blacklist_weeks or adding more maps matching the category's difficulties.",
            category_id=category_id,
        )
```
[Pattern source: existing exceptions in services/exceptions/tournaments.py]

### New Domain Exception: PendingCycleAlreadyExistsError

```python
class PendingCycleAlreadyExistsError(TournamentsError):
    """A pending cycle already exists for this category."""

    def __init__(self, category_id: int) -> None:
        super().__init__(
            "A pending cycle already exists for this category. Use reroll to replace it.",
            category_id=category_id,
        )
```

### New Domain Exception: PendingCycleNotFoundError

```python
class PendingCycleNotFoundError(TournamentsError):
    """No pending cycle exists for this category."""

    def __init__(self, category_id: int) -> None:
        super().__init__(
            "No pending cycle exists for this category.",
            category_id=category_id,
        )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `handle_db_exceptions` decorator | Three-tier exception hierarchy (repo -> domain -> HTTP) | Phase 2+ | All new code uses explicit try/except, not the decorator [VERIFIED: CLAUDE.md] |
| N/A (greenfield) | Pending cycles as `tournaments.cycles` with `status = 'pending'` | Phase 1 | No separate table needed for pre-roll storage [VERIFIED: CONTEXT.md D-01] |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `choose_map` should accept `map_code` (string) rather than `map_id` (int) because admins think in workshop codes | Code Examples | Low -- both approaches work, `map_code` requires a lookup query but is more user-friendly |
| A2 | Pending cycles should also be excluded from the eligible pool (pitfall 1) to avoid duplicate selections across categories | Common Pitfalls | Medium -- if not excluded, two categories could select the same pending map |
| A3 | Reroll should exclude the just-deleted map from the new selection (pitfall 2) | Common Pitfalls | Low -- without this, reroll might return the same map, which is annoying but not broken |

## Open Questions (RESOLVED)

1. **Should pending cycles exclude maps from the eligible pool?**
   - **RESOLVED:** Yes. Add `OR cy.status = 'pending'` to the NOT IN subquery in `fetch_eligible_maps`. This prevents two categories from selecting the same pending map simultaneously.

2. **How should `fetch_eligible_maps` handle reroll exclusion?**
   - **RESOLVED:** Add an optional `exclude_map_ids: list[int] | None = None` parameter to `fetch_eligible_maps` with `AND m.id != ALL($N)` when provided. Keeps the logic in SQL.

3. **Map validation for choose_map: should it check difficulty match?**
   - **RESOLVED:** Yes, per D-05. Reuse `MapNotEligibleError` for difficulty mismatch. Use a lookup query on `core.maps` to fetch the map and validate its difficulty against the category.

## Environment Availability

Step 2.6: SKIPPED (no external dependencies identified -- this phase is purely code/config changes to existing project).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.3.5+ with pytest-asyncio, pytest-mock |
| Config file | `apps/api/pyproject.toml` |
| Quick run command | `uv run --directory apps/api pytest tests/services/test_tournament_service.py -v -p no:xdist` |
| Full suite command | `just test-api` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CYCLE-04 | Maps within blacklist window excluded from selection | integration | `uv run --directory apps/api pytest tests/integration/test_tournaments_integration.py::TestSelectMap -v -p no:xdist` | Wave 0 |
| CYCLE-05 | Random map selected from eligible pool per category | integration | `uv run --directory apps/api pytest tests/integration/test_tournaments_integration.py::TestSelectMap -v -p no:xdist` | Wave 0 |
| CYCLE-06 | Pre-rolled maps stored as pending cycles | integration | `uv run --directory apps/api pytest tests/integration/test_tournaments_integration.py::TestGetNextCycle -v -p no:xdist` | Wave 0 |
| CYCLE-07 | Admin preview, reroll, choose next-cycle map | integration | `uv run --directory apps/api pytest tests/integration/test_tournaments_integration.py -k "Reroll or Choose or NextCycle" -v -p no:xdist` | Wave 0 |
| -- | Service business logic (select, reroll, choose, error paths) | unit | `uv run --directory apps/api pytest tests/services/test_tournament_service.py -v -p no:xdist` | Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run --directory apps/api pytest tests/services/test_tournament_service.py tests/integration/test_tournaments_integration.py -v -p no:xdist`
- **Per wave merge:** `just test-api`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/services/test_tournament_service.py` -- service unit tests for select_map, reroll_map, choose_map, get_next_cycle (NEW file)
- [ ] `tests/services/conftest.py` -- add `mock_tournament_repo` fixture
- [ ] `tests/integration/test_tournaments_integration.py` -- add TestSelectMap, TestGetNextCycle, TestReroll, TestChooseMap classes (extend existing file)

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | Existing `CustomAuthenticationMiddleware` handles API key validation [VERIFIED: middleware/auth.py] |
| V3 Session Management | no | No session management in this phase |
| V4 Access Control | yes | Existing scope guard with `tournaments:read` / `tournaments:write` scopes [VERIFIED: middleware/guards.py] |
| V5 Input Validation | yes | msgspec Struct type hints auto-validate request bodies [VERIFIED: SDK pattern] |
| V6 Cryptography | no | No cryptographic operations in this phase |

### Known Threat Patterns for This Phase

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Unauthorized map selection | Elevation of Privilege | Scope guard requires `tournaments:write` for all mutation endpoints [VERIFIED: existing pattern] |
| SQL injection via map_code | Tampering | asyncpg positional parameters ($1, $2) prevent SQL injection [VERIFIED: repository pattern] |
| TOCTOU race on pending cycle check | Tampering | Single-connection transaction boundary prevents concurrent creation [VERIFIED: D-11 decision] |

## Project Constraints (from CLAUDE.md)

- **No ORM** -- all database access uses raw SQL via asyncpg with positional `$N` parameters [VERIFIED: CLAUDE.md]
- **Bot never writes to DB** -- only API writes; not relevant for this phase but guides future design [VERIFIED: CLAUDE.md]
- **Three-tier exception hierarchy** -- repository exceptions -> domain exceptions -> HTTP exceptions; do NOT use `handle_db_exceptions` decorator for new code [VERIFIED: CLAUDE.md]
- **Line length 120**, Google docstrings, `log = getLogger(__name__)` at module level [VERIFIED: CLAUDE.md]
- **`%s`-style log formatting**, not f-strings in log calls [VERIFIED: CLAUDE.md]
- **Type annotations required** on all function signatures [VERIFIED: CLAUDE.md]
- **Logging markers:** `[!]` for warnings, `[->]` for publishing, `[x]` for failures, `[checkmark]` for success [VERIFIED: CLAUDE.md]
- **`conn: Connection | None = None` as keyword-only** parameter on repository methods [VERIFIED: CLAUDE.md]
- **`type: ignore[arg-type]`** on `conn=conn` kwargs in service layer [VERIFIED: existing pattern]

## Sources

### Primary (HIGH confidence)
- `apps/api/repository/tournaments_repository.py` -- verified all existing methods, SQL queries, and patterns
- `apps/api/services/tournament_service.py` -- verified service patterns (check-then-mutate, msgspec.convert, exception handling)
- `apps/api/routes/v3/tournaments.py` -- verified controller patterns (exception mapping, scope guards, DI wiring)
- `apps/api/services/exceptions/tournaments.py` -- verified exception hierarchy and constructor patterns
- `libs/sdk/src/genjishimada_sdk/tournaments.py` -- verified existing Struct definitions and `__all__` tuple
- `apps/api/migrations/0020_tournaments.sql` -- verified schema: cycles table, pending status, constraints
- `apps/api/tests/` -- verified test infrastructure, conftest fixtures, and test patterns across repository/service/integration layers

### Secondary (MEDIUM confidence)
- `.planning/phases/05-map-selection-blacklist/05-CONTEXT.md` -- all decisions (D-01 through D-11) verified against codebase implementation

### Tertiary (LOW confidence)
- None -- all findings verified against codebase

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries already in use, no new dependencies
- Architecture: HIGH -- directly extending existing patterns from Phase 4
- Pitfalls: HIGH -- identified from reading actual SQL queries and understanding NULL behavior in WHERE clauses

**Research date:** 2026-05-29
**Valid until:** 2026-06-29 (stable -- extending existing codebase patterns with no external dependency changes)
