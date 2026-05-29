# Phase 4: Config & Category Management - Research

**Researched:** 2026-05-29
**Domain:** Litestar service + controller layer for tournament config singleton and category CRUD
**Confidence:** HIGH

## Summary

Phase 4 builds the service and controller layer on top of the existing repository (Phase 3) and SDK types (Phase 2) for tournament configuration and category management. This is a straightforward "wire up the layers" phase with no external dependencies, no new packages to install, and no architectural novelty -- every pattern this phase needs already exists in the codebase with multiple reference implementations.

The primary complexity is the PATCH-with-UNSET pattern for partial updates (well-established in `MapsService`, `StoreService`) and the active-cycle guard for category mutations (repository method already exists, service just needs to call it and raise the appropriate domain exception). The scope is narrow: one service file, one controller file, and one small exception addition. No RabbitMQ publishing is needed.

**Primary recommendation:** Follow the `StoreController`/`StoreService` pattern exactly -- single controller with nested paths, single service with injected repository, PATCH fields filtered via `is not msgspec.UNSET` checks, domain exceptions caught in controller and mapped to `CustomHTTPException`.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Tournament endpoints use `tournaments:read` for GET operations and `tournaments:write` for all mutations (POST/PATCH/DELETE). Follows the existing `maps:read`/`maps:write` and `store:read`/`store:write` pattern. Superusers bypass scope checks as usual.
- **D-02:** Single `TournamentsController(Controller)` at path `/tournaments` in `apps/api/routes/v3/tournaments.py`. Config endpoints under `/tournaments/config`, category endpoints under `/tournaments/categories` and `/tournaments/categories/{category_id}`. Matches single-controller-per-domain pattern (StoreController at `/store`).
- **D-03:** Endpoints to implement:
  - `GET /tournaments/config` -- Read config singleton
  - `PATCH /tournaments/config` -- Update config fields
  - `POST /tournaments/categories` -- Create category
  - `GET /tournaments/categories` -- List all categories
  - `GET /tournaments/categories/{category_id}` -- Get single category
  - `PATCH /tournaments/categories/{category_id}` -- Update category
  - `DELETE /tournaments/categories/{category_id}` -- Delete category
- **D-04:** Single `TournamentService(BaseService)` in `apps/api/services/tournament_service.py`. Receives `Pool`, `State`, and `TournamentRepository` via constructor. Provider function `provide_tournament_service(state, tournament_repo)` at file bottom. One service per domain matching existing pattern.
- **D-05:** For category update and delete, the service acquires a pool connection, calls `check_active_cycle_for_category(category_id)` within the same connection, and raises `CategoryLockedError(category_id, cycle_id)` if an active cycle exists. Only then does it proceed with the mutation. This prevents TOCTOU races by using the same connection.
- **D-06:** Category creation does NOT require an active cycle check -- new categories start without cycles.
- **D-07:** Category delete is a hard DELETE. The active cycle guard prevents deletion of categories with running cycles.
- **D-08:** Service iterates `TournamentConfigPatchRequest` fields, builds a dict of non-UNSET values, passes to `repository.update_config(updates)`. Matches existing store config PATCH pattern.
- **D-09:** Config row is assumed to always exist -- seeded by migration `0020_tournaments.sql`. No empty-config fallback needed.
- **D-10:** Controller catches domain exceptions and maps to HTTP status codes:
  - `CategoryNotFoundError` -> 404 Not Found
  - `CategoryLockedError` -> 409 Conflict
  - Category name uniqueness violation -> Service catches `UniqueConstraintViolationError` from repo, translates to `CategoryNameExistsError`, controller maps to 409 Conflict
- **D-11:** A new `CategoryNameExistsError(TournamentsError)` should be added to `services/exceptions/tournaments.py`.

### Claude's Discretion
- Exact method signatures on the service (parameter names, return types) -- follow existing service patterns
- Whether `list_categories` returns all categories or supports optional `is_active` filter -- either approach is fine, filter is a bonus
- Controller docstrings and summary/description text -- follow existing style
- Whether to add `tags = ["Tournaments"]` or `tags = ["Tournament"]` on the controller -- pick whichever reads better

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CYCLE-02 | Configurable tournament categories with admin-defined difficulty groupings | Service + controller CRUD for categories; SDK types `TournamentCategoryCreateRequest`/`TournamentCategoryResponse` already defined; repo methods `create_category`/`fetch_categories`/`update_category`/`delete_category` ready |
| CYCLE-03 | Per-category cycle frequency (weekly or biweekly) | `cycle_frequency` field in `TournamentCategoryCreateRequest`/`TournamentCategoryPatchRequest` with `CycleFrequency = Literal["weekly", "biweekly"]`; CHECK constraint in DB enforces valid values |
| CYCLE-08 | Category configuration locked during active cycles, changeable between cycles | `check_active_cycle_for_category()` repo method exists; service raises `CategoryLockedError` when active cycle detected; controller maps to 409 Conflict |
| ADM-01 | Admin API endpoints for tournament configuration CRUD | GET/PATCH `/tournaments/config` with `tournaments:read`/`tournaments:write` scopes; scope guard rejects non-admin; config singleton seeded by migration |
| ADM-02 | Admin API endpoints for category management | POST/GET/PATCH/DELETE `/tournaments/categories` with appropriate scopes; full CRUD through controller -> service -> repository |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Config GET/PATCH | API (Controller + Service) | Database | Controller handles HTTP, service wraps repo calls, DB stores singleton |
| Category CRUD | API (Controller + Service) | Database | Standard REST CRUD through three-tier hierarchy |
| Active cycle guard | API (Service) | Database | Service-layer business rule check using repo query on same connection |
| Scope-based auth | API (Middleware) | -- | Existing scope guard middleware handles authorization |
| Request validation | API (Litestar/msgspec) | -- | Litestar auto-deserializes msgspec Structs; CHECK constraints catch invalid enums |
| PATCH partial updates | API (Service) | -- | Service filters UNSET fields, builds update dict, delegates to repo |

## Standard Stack

### Core (All existing -- no new packages)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| litestar | >=2.16.0 | Controller, routing, DI, scope guard | Already in use, D-02 mandates Litestar Controller [VERIFIED: `apps/api/pyproject.toml`] |
| asyncpg | via litestar-asyncpg >=0.4.0 | Database access via pool | Already in use, all repo methods use it [VERIFIED: codebase] |
| msgspec | >=0.19.0 | SDK Structs, UNSET pattern, JSONB codec | Already in use, D-08 requires UNSET pattern [VERIFIED: codebase] |

### Supporting (All existing -- no new packages)

No additional packages needed. This phase uses only existing codebase infrastructure.

### Alternatives Considered

None. All decisions are locked.

**Installation:**
```bash
# No installation needed -- all dependencies are already in the workspace
```

## Package Legitimacy Audit

No new packages are introduced in this phase. All dependencies (`litestar`, `asyncpg`, `msgspec`) are already installed and verified as part of the existing monorepo workspace.

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
HTTP Request
    |
    v
[Litestar Middleware: Auth + Scope Guard]
    |  Validates X-API-KEY, checks tournaments:read/tournaments:write scopes
    v
[TournamentsController]  (apps/api/routes/v3/tournaments.py)
    |  Extracts params, delegates to service, catches domain exceptions
    |  Maps exceptions -> CustomHTTPException (404, 409, 400)
    v
[TournamentService]  (apps/api/services/tournament_service.py)
    |  Business logic: UNSET filtering, active-cycle guard
    |  Translates repo exceptions -> domain exceptions
    v
[TournamentRepository]  (apps/api/repository/tournaments_repository.py)
    |  Raw SQL via asyncpg, constraint error translation
    v
[PostgreSQL: tournaments.config + tournaments.categories + tournaments.cycles]
```

### Recommended Project Structure (new files only)

```
apps/api/
  services/
    tournament_service.py           # NEW: TournamentService + provide_tournament_service
  services/exceptions/
    tournaments.py                  # MODIFY: add CategoryNameExistsError
  routes/v3/
    tournaments.py                  # NEW: TournamentsController (auto-discovered)
```

### Pattern 1: Service with Repository Injection

**What:** Service class extends `BaseService`, receives repository via constructor, provider function wired at file bottom.
**When to use:** Every service in this codebase.
**Example:**
```python
# Source: apps/api/services/store_service.py (verified pattern)
class TournamentService(BaseService):
    """Service for tournament domain business logic."""

    def __init__(
        self,
        pool: Pool,
        state: State,
        tournament_repo: TournamentRepository,
    ) -> None:
        super().__init__(pool, state)
        self._tournament_repo = tournament_repo


async def provide_tournament_service(
    state: State,
    tournament_repo: TournamentRepository,
) -> TournamentService:
    return TournamentService(state.db_pool, state, tournament_repo)
```

### Pattern 2: PATCH with UNSET Filtering

**What:** Iterate msgspec Struct fields, skip UNSET values, build update dict, pass to repository.
**When to use:** Any PATCH endpoint that supports partial updates.
**Example:**
```python
# Source: apps/api/services/maps_service.py (verified pattern)
import msgspec

async def update_config(self, data: TournamentConfigPatchRequest) -> TournamentConfigResponse:
    updates = {}
    if data.blacklist_weeks is not msgspec.UNSET:
        updates["blacklist_weeks"] = data.blacklist_weeks
    if updates:
        await self._tournament_repo.update_config(updates)
    config = await self._tournament_repo.fetch_config()
    return msgspec.convert(config, TournamentConfigResponse)
```

### Pattern 3: Active Cycle Guard (Same-Connection Check)

**What:** Before mutating a category, check for active cycles on the same connection.
**When to use:** Category update and delete operations (per D-05).
**Example:**
```python
# Source: CONTEXT.md D-05 + repository method signature
async def update_category(self, category_id: int, data: TournamentCategoryPatchRequest) -> TournamentCategoryResponse:
    # Build updates dict (UNSET filtering)
    updates = {}
    # ... filter fields ...

    async with self._pool.acquire() as conn:
        # Check active cycle on same connection
        has_active = await self._tournament_repo.check_active_cycle_for_category(category_id, conn=conn)
        if has_active:
            raise CategoryLockedError(category_id, cycle_id=0)  # cycle_id unknown at this point

        row = await self._tournament_repo.update_category(category_id, updates, conn=conn)
        if row is None:
            raise CategoryNotFoundError(category_id)
        return msgspec.convert(row, TournamentCategoryResponse)
```

**Note on cycle_id in CategoryLockedError:** The `check_active_cycle_for_category()` method returns a boolean, not the cycle_id. Two options: (1) change the repo method to return the cycle_id, or (2) use a sentinel value. The planner should decide -- option (1) is cleaner and requires a small repo tweak (return `int | None` instead of `bool`), option (2) avoids modifying Phase 3 output.

### Pattern 4: Controller Exception-to-HTTP Mapping

**What:** Controller catches domain exceptions in try/except, raises CustomHTTPException.
**When to use:** Every controller method that can raise domain errors.
**Example:**
```python
# Source: apps/api/routes/v3/store.py (verified pattern)
from utilities.errors import CustomHTTPException
from litestar.status_codes import HTTP_404_NOT_FOUND, HTTP_409_CONFLICT

try:
    return await tournament_service.update_category(category_id, data)
except CategoryNotFoundError as e:
    raise CustomHTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e)) from e
except CategoryLockedError as e:
    raise CustomHTTPException(status_code=HTTP_409_CONFLICT, detail=str(e)) from e
except CategoryNameExistsError as e:
    raise CustomHTTPException(status_code=HTTP_409_CONFLICT, detail=str(e)) from e
```

### Pattern 5: Route Auto-Discovery

**What:** Any `Controller` subclass defined in `apps/api/routes/v3/*.py` is automatically discovered.
**When to use:** Always -- no manual registration needed.
**How it works:** `apps/api/routes/v3/__init__.py` scans all `.py` files, imports modules, finds `Controller` subclasses, and mounts them. [VERIFIED: `apps/api/routes/v3/__init__.py`]

### Anti-Patterns to Avoid

- **Using `handle_db_exceptions` decorator:** Per CLAUDE.md, this is the old pattern. New code uses the three-tier hierarchy: repo catches asyncpg -> raises repo exceptions; service catches repo exceptions -> raises domain exceptions; controller catches domain exceptions -> raises HTTPException.
- **Bot writing directly to DB:** Not applicable to this phase (API-only), but noting for completeness.
- **Catching broad `Exception`:** Always catch specific domain exception types.
- **Building SQL with f-strings:** Use positional parameters (`$1`, `$2`, ...) -- repo already does this correctly.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Request deserialization | Custom JSON parsing | Litestar + msgspec Structs | Automatic deserialization with type validation |
| Partial update detection | None/null checks | msgspec UNSET pattern | Distinguishes "field not sent" from "field set to null" |
| Scope-based authorization | Custom auth checks in handlers | `opt={"required_scopes": {...}}` | Global scope guard already handles this |
| Route registration | Manual route mounting | Auto-discovery in `routes/v3/__init__.py` | Drop a Controller class in the file, it's auto-mounted |
| JSONB encoding/decoding | Manual json.dumps/loads | asyncpg custom codec (`_async_pg_init`) | Codec handles msgspec encode/decode transparently |

**Key insight:** This phase is entirely "plumbing" -- connecting existing layers. Every piece (SDK types, repository methods, domain exceptions, base classes) already exists. The service and controller are thin wrappers.

## Common Pitfalls

### Pitfall 1: Forgetting JSONB Serialization for Category Fields

**What goes wrong:** `placement_xp` and `streak_xp` are typed as `list[PlacementXpTier]` / `list[StreakXpTier]` in the SDK but stored as JSONB in PostgreSQL. If you pass Python objects directly, asyncpg might not serialize them correctly.
**Why it happens:** The custom JSONB codec in `_async_pg_init` uses `msgspec.json.encode()` for encoding, which handles msgspec Structs. BUT the repository `create_category` and `update_category` methods expect the JSONB fields to already be serialized to JSON strings OR to be passable through the codec.
**How to avoid:** The service must convert `list[PlacementXpTier]` to a JSON string before passing to the repository. The repo already casts with `$5::jsonb`. Check the codec behavior: the `_jsonb_encoder` checks `isinstance(value, str)` first and returns it directly, otherwise calls `msgspec.json.encode(value).decode()`. So passing either a JSON string or a list of Struct objects should work -- but verify by looking at how the repo handles it. The repo uses `$5::jsonb` cast with the parameter value, which will go through the codec.
**Warning signs:** Serialization errors or incorrect data in DB when creating/updating categories.

### Pitfall 2: Not Checking Category Existence Before Active Cycle Guard

**What goes wrong:** If a category doesn't exist, `check_active_cycle_for_category()` returns `False` (no rows match). The service then proceeds to `update_category()` which returns `None`, and the "not found" error comes late.
**Why it happens:** Boolean check for active cycle doesn't verify category existence.
**How to avoid:** For update: the active cycle check runs first, then update. If update returns `None`, raise `CategoryNotFoundError`. This ordering is fine because: (1) if category doesn't exist, no active cycle exists, check passes, update returns None, error raised. The behavior is correct.
For delete: if `delete_category()` returns `False`, raise `CategoryNotFoundError`. Same logic applies.
**Warning signs:** Confusing error messages when operating on non-existent categories.

### Pitfall 3: UNSET vs None Confusion in PATCH

**What goes wrong:** Treating `None` and `UNSET` as equivalent in the PATCH handler, causing fields to be unexpectedly cleared or skipped.
**Why it happens:** `champion_role_id` can be `int | None | UnsetType`. UNSET means "don't change", None means "clear the value".
**How to avoid:** Always use `is not msgspec.UNSET` (identity check), not truthiness or equality. For nullable fields like `champion_role_id`, UNSET should skip the field, but None should explicitly set it to NULL.
**Warning signs:** Fields getting cleared when they shouldn't be, or nullable fields not accepting null values.

### Pitfall 4: CategoryLockedError Missing cycle_id

**What goes wrong:** `CategoryLockedError.__init__` expects both `category_id` and `cycle_id`, but `check_active_cycle_for_category()` returns only a boolean.
**Why it happens:** The repo method was designed to check existence, not return the specific cycle.
**How to avoid:** Either (a) modify the repo method to return `int | None` (the cycle_id) instead of `bool`, or (b) fetch the active cycle separately before raising, or (c) use a placeholder value (0 or -1). Option (a) is cleanest -- small change to `check_active_cycle_for_category()` to `SELECT id ... LIMIT 1` and return `fetchval()`.
**Warning signs:** Misleading `cycle_id=0` in error context.

### Pitfall 5: Missing scope in `public.api_tokens` Table

**What goes wrong:** The `tournaments:read` and `tournaments:write` scopes don't exist in the database yet, so scope guard always rejects non-superuser requests.
**Why it happens:** Scopes are stored in the `public.api_tokens` table per token. The test API key ("testing") might not have these scopes.
**How to avoid:** Two aspects: (1) The test conftest uses `X-API-KEY: testing` which presumably maps to a superuser token (superusers bypass scope checks), so tests should pass. (2) For production, an admin must add the new scopes to relevant API tokens. This is a deployment concern, not a code concern -- the scope guard already handles unknown scopes correctly (rejects if missing from token).
**Warning signs:** All non-superuser requests getting 403 even with correct scopes.

## Code Examples

### Config GET Handler (Verified Pattern)

```python
# Source: apps/api/routes/v3/store.py get_config pattern
@litestar.get(
    path="/config",
    summary="Get Tournament Config",
    description="Get global tournament configuration.",
    opt={"required_scopes": {"tournaments:read"}},
)
async def get_config(
    self,
    tournament_service: TournamentService,
) -> TournamentConfigResponse:
    """Get tournament configuration.

    Args:
        tournament_service: Tournament service.

    Returns:
        Tournament configuration.
    """
    return await tournament_service.get_config()
```

### Config PATCH Handler (Verified Pattern)

```python
# Source: Composite of store.py update_config + maps.py PATCH pattern
@litestar.patch(
    path="/config",
    summary="Update Tournament Config",
    description="Update global tournament configuration fields.",
    status_code=HTTP_200_OK,
    opt={"required_scopes": {"tournaments:write"}},
)
async def update_config(
    self,
    tournament_service: TournamentService,
    data: Annotated[TournamentConfigPatchRequest, Body(title="Config Update")],
) -> TournamentConfigResponse:
    """Update tournament configuration.

    Args:
        tournament_service: Tournament service.
        data: Partial config update.

    Returns:
        Updated tournament configuration.
    """
    return await tournament_service.update_config(data)
```

### Category Create Service Method (Verified Pattern)

```python
# Source: Store/Maps service create patterns + repo signature
async def create_category(
    self,
    data: TournamentCategoryCreateRequest,
) -> TournamentCategoryResponse:
    """Create a tournament category.

    Args:
        data: Category creation data.

    Returns:
        Created category.

    Raises:
        CategoryNameExistsError: If category name already exists.
    """
    try:
        row = await self._tournament_repo.create_category(
            name=data.name,
            difficulties=[str(d) for d in data.difficulties],
            cycle_frequency=data.cycle_frequency,
            participation_xp=data.participation_xp,
            placement_xp=msgspec.json.encode(data.placement_xp).decode(),
            streak_xp=msgspec.json.encode(data.streak_xp).decode(),
            champion_role_id=data.champion_role_id,
        )
        return msgspec.convert(row, TournamentCategoryResponse)
    except UniqueConstraintViolationError as e:
        if "name" in (e.constraint_name or ""):
            raise CategoryNameExistsError(data.name) from e
        raise
```

### CategoryNameExistsError Definition

```python
# Source: Follows existing exception patterns in services/exceptions/tournaments.py
class CategoryNameExistsError(TournamentsError):
    """Category name already exists."""

    def __init__(self, name: str) -> None:
        super().__init__(
            f"A tournament category named '{name}' already exists.",
            name=name,
        )
```

### Service PATCH Method with UNSET Filtering

```python
# Source: apps/api/services/maps_service.py update_map pattern
async def update_category(
    self,
    category_id: int,
    data: TournamentCategoryPatchRequest,
) -> TournamentCategoryResponse:
    updates: dict[str, object] = {}
    if data.name is not msgspec.UNSET:
        updates["name"] = data.name
    if data.difficulties is not msgspec.UNSET:
        updates["difficulties"] = [str(d) for d in data.difficulties]
    if data.cycle_frequency is not msgspec.UNSET:
        updates["cycle_frequency"] = data.cycle_frequency
    if data.participation_xp is not msgspec.UNSET:
        updates["participation_xp"] = data.participation_xp
    if data.placement_xp is not msgspec.UNSET:
        updates["placement_xp"] = msgspec.json.encode(data.placement_xp).decode()
    if data.streak_xp is not msgspec.UNSET:
        updates["streak_xp"] = msgspec.json.encode(data.streak_xp).decode()
    if data.champion_role_id is not msgspec.UNSET:
        updates["champion_role_id"] = data.champion_role_id
    if data.is_active is not msgspec.UNSET:
        updates["is_active"] = data.is_active

    async with self._pool.acquire() as conn:
        has_active = await self._tournament_repo.check_active_cycle_for_category(
            category_id, conn=conn
        )
        if has_active:
            raise CategoryLockedError(category_id, cycle_id=0)

        try:
            row = await self._tournament_repo.update_category(
                category_id, updates, conn=conn
            )
        except UniqueConstraintViolationError as e:
            if "name" in (e.constraint_name or ""):
                raise CategoryNameExistsError(updates.get("name", "")) from e
            raise

        if row is None:
            raise CategoryNotFoundError(category_id)

        return msgspec.convert(row, TournamentCategoryResponse)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `handle_db_exceptions` decorator | Three-tier exception hierarchy (repo -> service -> controller) | Current codebase migration | New code MUST use three-tier pattern per CLAUDE.md |
| Direct asyncpg error handling in routes | Repository wraps asyncpg, service translates, controller maps to HTTP | Current | Cleaner separation of concerns |
| `Optional[X]` for union types | `X \| None` (Python 3.10+ syntax) | Python 3.10 | All code uses pipe syntax |

**Deprecated/outdated:**
- `handle_db_exceptions` decorator: Still present in older endpoints but superseded by three-tier hierarchy. New code must not use it.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The test API key ("testing") is a superuser token that bypasses scope checks | Pitfalls (Pitfall 5) | Tests would fail due to missing `tournaments:read`/`tournaments:write` scopes on the token; fix is to verify test seed data |
| A2 | `msgspec.json.encode(data.placement_xp).decode()` produces valid JSON strings passable to asyncpg JSONB codec | Code Examples | JSONB fields could fail to serialize; verify with a simple test case |
| A3 | The `check_active_cycle_for_category` method returning `bool` is sufficient (vs returning cycle_id) | Pitfalls (Pitfall 4) | `CategoryLockedError` requires `cycle_id` param; would need to fetch cycle separately or change repo return type |

## Open Questions (RESOLVED)

1. **`check_active_cycle_for_category` return type** — RESOLVED: Changed to `int | None` per Plan 01 Task 1. One-line SQL change (`SELECT id` instead of `SELECT 1`) and one-line Python change.

2. **JSONB encoding for PlacementXpTier/StreakXpTier** — RESOLVED: Pre-serialize with `msgspec.json.encode(value).decode()` in service before passing to repository. Matches how other services handle complex data.

3. **`is_active` filter on list_categories** — RESOLVED: List all categories without filter per Claude's Discretion. Optional filter can be added later if needed.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest >= 8.3.5 with pytest-asyncio (auto mode) |
| Config file | `apps/api/pyproject.toml` [tool.pytest.ini_options] |
| Quick run command | `uv run --directory apps/api pytest tests/services/test_tournament_service.py -v -p no:xdist` |
| Full suite command | `just test-api` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ADM-01 | GET config returns singleton | unit + integration | `uv run --directory apps/api pytest tests/services/test_tournament_service.py::TestGetConfig -v -p no:xdist` | No (Wave 0) |
| ADM-01 | PATCH config updates fields | unit + integration | `uv run --directory apps/api pytest tests/services/test_tournament_service.py::TestUpdateConfig -v -p no:xdist` | No (Wave 0) |
| ADM-02 | POST category creates record | unit + integration | `uv run --directory apps/api pytest tests/services/test_tournament_service.py::TestCreateCategory -v -p no:xdist` | No (Wave 0) |
| ADM-02 | GET categories lists all | unit + integration | `uv run --directory apps/api pytest tests/services/test_tournament_service.py::TestListCategories -v -p no:xdist` | No (Wave 0) |
| ADM-02 | GET category by ID | unit + integration | `uv run --directory apps/api pytest tests/services/test_tournament_service.py::TestGetCategory -v -p no:xdist` | No (Wave 0) |
| ADM-02 | PATCH category updates fields | unit + integration | `uv run --directory apps/api pytest tests/services/test_tournament_service.py::TestUpdateCategory -v -p no:xdist` | No (Wave 0) |
| ADM-02 | DELETE category removes record | unit + integration | `uv run --directory apps/api pytest tests/services/test_tournament_service.py::TestDeleteCategory -v -p no:xdist` | No (Wave 0) |
| CYCLE-02 | Category has difficulty groupings | unit | covered by create/update tests | No (Wave 0) |
| CYCLE-03 | Category has cycle_frequency field | unit | covered by create/update tests | No (Wave 0) |
| CYCLE-08 | Update/delete rejected during active cycle | unit + integration | `uv run --directory apps/api pytest tests/services/test_tournament_service.py::TestCategoryLockedGuard -v -p no:xdist` | No (Wave 0) |
| CYCLE-08 | Non-admin requests rejected | integration | `uv run --directory apps/api pytest tests/integration/test_tournaments_integration.py::TestAuthRejection -v -p no:xdist` | No (Wave 0) |

### Sampling Rate
- **Per task commit:** `uv run --directory apps/api pytest tests/services/test_tournament_service.py -v -p no:xdist`
- **Per wave merge:** `just test-api`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/services/test_tournament_service.py` -- covers ADM-01, ADM-02, CYCLE-02, CYCLE-03, CYCLE-08 (service unit tests with mocked repo)
- [ ] `tests/integration/test_tournaments_integration.py` -- covers full HTTP stack (integration tests)
- [ ] `tests/services/conftest.py` -- needs `mock_tournament_repo` fixture added
- [ ] Service unit tests follow pattern from `tests/services/test_store_service.py`
- [ ] Integration tests follow pattern from `tests/integration/test_store_integration.py`

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | Yes (inherited) | Existing `CustomAuthenticationMiddleware` -- no changes needed |
| V3 Session Management | No | Not applicable to API key auth |
| V4 Access Control | Yes | Scope guard: `tournaments:read` / `tournaments:write` per D-01 |
| V5 Input Validation | Yes | msgspec Struct type validation + DB CHECK constraints |
| V6 Cryptography | No | No crypto operations in this phase |

### Known Threat Patterns for This Phase

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Unauthorized config modification | Elevation of Privilege | Scope guard requires `tournaments:write`; superuser bypass is intentional |
| SQL injection via PATCH fields | Tampering | asyncpg positional parameters ($1, $2...); no f-string SQL |
| TOCTOU in active cycle check | Tampering | Same-connection check + mutation per D-05; advisory lock in Phase 7 |
| Mass category deletion | Denial of Service | Active cycle guard prevents deleting in-use categories |
| Invalid cycle_frequency values | Tampering | DB CHECK constraint + Literal type in SDK |

## Sources

### Primary (HIGH confidence)
- `apps/api/services/store_service.py` -- Config PATCH pattern, service class structure
- `apps/api/routes/v3/store.py` -- Controller with scope guard, exception mapping pattern
- `apps/api/services/maps_service.py` -- UNSET filtering pattern for PATCH
- `apps/api/repository/tournaments_repository.py` -- All repo method signatures and SQL
- `libs/sdk/src/genjishimada_sdk/tournaments.py` -- All SDK type definitions
- `apps/api/services/exceptions/tournaments.py` -- Existing domain exceptions
- `apps/api/migrations/0020_tournaments.sql` -- Schema, constraints, seed data
- `apps/api/routes/v3/__init__.py` -- Auto-discovery mechanism
- `apps/api/middleware/guards.py` -- Scope guard implementation
- `apps/api/repository/exceptions.py` -- Repository exception hierarchy
- `apps/api/utilities/errors.py` -- DomainError, CustomHTTPException
- `apps/api/services/base.py` -- BaseService class
- `apps/api/repository/base.py` -- BaseRepository class
- `apps/api/app.py` -- JSONB codec configuration
- `apps/api/tests/services/conftest.py` -- Mock fixtures for service tests
- `apps/api/tests/integration/conftest.py` -- Integration test fixtures

### Secondary (MEDIUM confidence)
- None needed -- all patterns verified directly from codebase

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- no new packages, all existing
- Architecture: HIGH -- all patterns directly observed in codebase with multiple examples
- Pitfalls: HIGH -- derived from actual code review of existing implementations

**Research date:** 2026-05-29
**Valid until:** Indefinite (patterns are codebase-internal, not version-dependent)
