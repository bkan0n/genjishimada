# Phase 5: Map Selection & Blacklist - Pattern Map

**Mapped:** 2026-05-29
**Files analyzed:** 7 (5 modified, 2 new)
**Analogs found:** 7 / 7

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `apps/api/repository/tournaments_repository.py` | repository | CRUD | self (existing methods) | exact |
| `apps/api/services/tournament_service.py` | service | CRUD | self (`update_category`, `delete_category`) | exact |
| `apps/api/routes/v3/tournaments.py` | controller | request-response | self (`get_category`, `delete_category`) | exact |
| `apps/api/services/exceptions/tournaments.py` | exception | -- | self (`CategoryLockedError`, `MapNotEligibleError`) | exact |
| `libs/sdk/src/genjishimada_sdk/tournaments.py` | model | -- | self (`TournamentCycleResponse`, `TournamentCompletionCreateRequest`) | exact |
| `apps/api/tests/services/test_tournament_service.py` | test | unit | `tests/services/test_maps_service.py` | role-match |
| `apps/api/tests/integration/test_tournaments_integration.py` | test | integration | self (`TestCategoryLockedGuard`) | exact |

## Pattern Assignments

### `apps/api/repository/tournaments_repository.py` (repository, CRUD) -- MODIFY

**Analog:** self -- existing methods in same file

**3 new methods needed:** `fetch_pending_cycle`, `delete_cycle`, `fetch_map_by_code`

**Imports pattern** (lines 1-21) -- no new imports needed, everything already imported:
```python
from __future__ import annotations

from logging import getLogger

from asyncpg import Connection, Pool
from asyncpg.exceptions import CheckViolationError, ForeignKeyViolationError, UniqueViolationError
from litestar.datastructures import State

from repository.base import BaseRepository
from repository.exceptions import (
    CheckConstraintViolationError,
    UniqueConstraintViolationError,
    extract_constraint_name,
)
from repository.exceptions import (
    ForeignKeyViolationError as RepoFKError,
)

log = getLogger(__name__)
```

**Read-with-JOIN pattern** -- copy from `fetch_active_cycle` (lines 340-362):
```python
async def fetch_active_cycle(
    self,
    category_id: int,
    *,
    conn: Connection | None = None,
) -> dict | None:
    _conn = self._get_connection(conn)
    query = """
        SELECT * FROM tournaments.cycles
        WHERE category_id = $1 AND status = 'active'
        LIMIT 1
    """
    row = await _conn.fetchrow(query, category_id)
    return dict(row) if row else None
```
New `fetch_pending_cycle` should follow this pattern but add a JOIN to `core.maps` for map details (map_code, map_name, difficulty).

**Delete pattern** -- copy from `delete_category` (lines 237-255):
```python
async def delete_category(
    self,
    category_id: int,
    *,
    conn: Connection | None = None,
) -> bool:
    _conn = self._get_connection(conn)
    query = "DELETE FROM tournaments.categories WHERE id = $1 RETURNING id"
    result = await _conn.fetchval(query, category_id)
    return result is not None
```
New `delete_cycle` should follow this exact pattern.

**Simple fetch pattern** -- copy from `fetch_category` (lines 148-166):
```python
async def fetch_category(
    self,
    category_id: int,
    *,
    conn: Connection | None = None,
) -> dict | None:
    _conn = self._get_connection(conn)
    query = "SELECT * FROM tournaments.categories WHERE id = $1"
    row = await _conn.fetchrow(query, category_id)
    return dict(row) if row else None
```
New `fetch_map_by_code` should follow this pattern, querying `core.maps` by code.

---

### `apps/api/services/tournament_service.py` (service, CRUD) -- MODIFY

**Analog:** self -- existing methods in same file

**4 new methods needed:** `select_map`, `get_next_cycle`, `reroll_map`, `choose_map`

**Imports pattern** (lines 1-23) -- will need additions for new SDK types and exceptions:
```python
from __future__ import annotations

import msgspec
from asyncpg import Pool
from genjishimada_sdk.tournaments import (
    TournamentCategoryCreateRequest,
    TournamentCategoryPatchRequest,
    TournamentCategoryResponse,
    TournamentConfigPatchRequest,
    TournamentConfigResponse,
)
from litestar.datastructures import State

from repository.exceptions import UniqueConstraintViolationError
from repository.tournaments_repository import TournamentRepository
from services.base import BaseService
from services.exceptions.tournaments import (
    CategoryLockedError,
    CategoryNameExistsError,
    CategoryNotFoundError,
)
```

**Check-then-mutate under transaction** -- copy from `update_category` (lines 128-190) and `delete_category` (lines 192-218):
```python
async def update_category(
    self,
    category_id: int,
    data: TournamentCategoryPatchRequest,
) -> TournamentCategoryResponse:
    # ... build updates dict ...

    async with self._pool.acquire() as conn:
        cycle_id = await self._tournament_repo.check_active_cycle_for_category(
            category_id,
            conn=conn,  # type: ignore[arg-type]
        )
        if cycle_id is not None:
            raise CategoryLockedError(category_id, cycle_id=cycle_id)

        try:
            row = await self._tournament_repo.update_category(
                category_id,
                updates,
                conn=conn,  # type: ignore[arg-type]
            )
        except UniqueConstraintViolationError as e:
            if "name" in (e.constraint_name or ""):
                name = str(updates.get("name", ""))
                raise CategoryNameExistsError(name) from e
            raise

    if row is None:
        raise CategoryNotFoundError(category_id)
    return msgspec.convert(row, TournamentCategoryResponse)
```
Key patterns to copy:
- `async with self._pool.acquire() as conn:` for transaction boundary
- `conn=conn,  # type: ignore[arg-type]` on every repo call inside the block
- Domain exception raising on precondition failure
- `msgspec.convert(row, ResponseStruct)` for return value conversion

**Simple read-through service method** -- copy from `get_category` (lines 111-126):
```python
async def get_category(self, category_id: int) -> TournamentCategoryResponse:
    row = await self._tournament_repo.fetch_category(category_id)
    if row is None:
        raise CategoryNotFoundError(category_id)
    return msgspec.convert(row, TournamentCategoryResponse)
```
New `get_next_cycle` should follow this pattern (fetch pending cycle, raise if None, convert and return).

**Service constructor** (lines 26-43) -- already accepts `tournament_repo`, no changes needed:
```python
class TournamentService(BaseService):
    def __init__(
        self,
        pool: Pool,
        state: State,
        tournament_repo: TournamentRepository,
    ) -> None:
        super().__init__(pool, state)
        self._tournament_repo = tournament_repo
```

---

### `apps/api/routes/v3/tournaments.py` (controller, request-response) -- MODIFY

**Analog:** self -- existing endpoint handlers in same file

**4 new endpoint handlers needed:** `get_next_cycle`, `select_map`, `reroll_map`, `choose_map`

**Imports pattern** (lines 1-33) -- will need additions for new status codes, SDK types, and exceptions:
```python
from __future__ import annotations

from typing import Annotated

import litestar
from genjishimada_sdk.tournaments import (
    TournamentCategoryCreateRequest,
    TournamentCategoryPatchRequest,
    TournamentCategoryResponse,
    TournamentConfigPatchRequest,
    TournamentConfigResponse,
)
from litestar.di import Provide
from litestar.params import Body, Parameter
from litestar.response import Response
from litestar.status_codes import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_204_NO_CONTENT,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
)

from repository.tournaments_repository import provide_tournament_repository
from services.exceptions.tournaments import (
    CategoryLockedError,
    CategoryNameExistsError,
    CategoryNotFoundError,
)
from services.tournament_service import TournamentService, provide_tournament_service
from utilities.errors import CustomHTTPException
```
New imports needed: `HTTP_422_UNPROCESSABLE_ENTITY`, new SDK structs, new domain exceptions.

**GET endpoint with exception mapping** -- copy from `get_category` (lines 141-170):
```python
@litestar.get(
    path="/categories/{category_id:int}",
    summary="Get Tournament Category",
    description="Get a single tournament category by ID.",
    opt={"required_scopes": {"tournaments:read"}},
)
async def get_category(
    self,
    tournament_service: TournamentService,
    category_id: Annotated[int, Parameter(description="Category ID")],
) -> TournamentCategoryResponse:
    try:
        return await tournament_service.get_category(category_id)
    except CategoryNotFoundError as e:
        raise CustomHTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
```
New `get_next_cycle` should use path `/categories/{category_id:int}/next-cycle` with `tournaments:read` scope.

**POST endpoint pattern** -- copy from `create_category` (lines 89-119):
```python
@litestar.post(
    path="/categories",
    summary="Create Tournament Category",
    description="Create a new tournament category with difficulty groupings.",
    status_code=HTTP_201_CREATED,
    opt={"required_scopes": {"tournaments:write"}},
)
async def create_category(
    self,
    tournament_service: TournamentService,
    data: Annotated[TournamentCategoryCreateRequest, Body(title="Category")],
) -> TournamentCategoryResponse:
    try:
        return await tournament_service.create_category(data)
    except CategoryNameExistsError as e:
        raise CustomHTTPException(
            status_code=HTTP_409_CONFLICT,
            detail=str(e),
        ) from e
```
New `select_map` and `reroll_map` should follow this pattern with `tournaments:write` scope.

**Multi-exception controller pattern** -- copy from `update_category` (lines 172-209):
```python
async def update_category(
    self,
    tournament_service: TournamentService,
    category_id: Annotated[int, Parameter(description="Category ID")],
    data: Annotated[TournamentCategoryPatchRequest, Body(title="Category Update")],
) -> TournamentCategoryResponse:
    try:
        return await tournament_service.update_category(category_id, data)
    except CategoryNotFoundError as e:
        raise CustomHTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except (CategoryLockedError, CategoryNameExistsError) as e:
        raise CustomHTTPException(
            status_code=HTTP_409_CONFLICT,
            detail=str(e),
        ) from e
```
New endpoints with multiple failure modes (404 not found, 409 conflict, 422 unprocessable) should follow this stacked `except` pattern.

**Controller class-level config** (lines 36-44) -- DI dependencies already wired:
```python
class TournamentsController(litestar.Controller):
    tags = ["Tournaments"]
    path = "/tournaments"
    dependencies = {
        "tournament_repo": Provide(provide_tournament_repository),
        "tournament_service": Provide(provide_tournament_service),
    }
```

---

### `apps/api/services/exceptions/tournaments.py` (exception, --) -- MODIFY

**Analog:** self -- existing exceptions in same file

**2-3 new exceptions needed:** `NoEligibleMapsError`, `PendingCycleAlreadyExistsError`, `PendingCycleNotFoundError`

**Exception with context kwargs** -- copy from `CategoryLockedError` (lines 14-22):
```python
class CategoryLockedError(TournamentsError):
    """Category cannot be modified while a cycle is active."""

    def __init__(self, category_id: int, cycle_id: int) -> None:
        super().__init__(
            "Category cannot be modified while a cycle is active.",
            category_id=category_id,
            cycle_id=cycle_id,
        )
```

**Exception with single context arg** -- copy from `CategoryNotFoundError` (lines 32-36):
```python
class CategoryNotFoundError(TournamentsError):
    """Tournament category does not exist."""

    def __init__(self, category_id: int) -> None:
        super().__init__("Tournament category not found.", category_id=category_id)
```

**Exception with reason string** -- copy from `MapNotEligibleError` (lines 75-82):
```python
class MapNotEligibleError(TournamentsError):
    """Map is not eligible for tournament selection."""

    def __init__(self, map_id: int, reason: str = "") -> None:
        message = "Map is not eligible for tournament selection."
        if reason:
            message = f"{message} {reason}"
        super().__init__(message, map_id=map_id, reason=reason)
```

**Base class import** (line 7):
```python
from utilities.errors import DomainError
```

---

### `libs/sdk/src/genjishimada_sdk/tournaments.py` (model, --) -- MODIFY

**Analog:** self -- existing Struct definitions in same file

**1-2 new structs needed:** `TournamentNextCycleResponse`, `TournamentChooseMapRequest`

**Response struct pattern** -- copy from `TournamentCycleResponse` (lines 173-192):
```python
class TournamentCycleResponse(Struct):
    """Tournament cycle with status and timing.

    Attributes:
        id: Cycle identifier.
        category_id: Category this cycle belongs to.
        map_id: Map selected for this cycle.
        status: Current lifecycle status.
        started_at: When the cycle became active.
        ended_at: When the cycle was finalized.
        created_at: When the cycle record was created.
    """

    id: int
    category_id: int
    map_id: int
    status: CycleStatus
    started_at: dt.datetime | None
    ended_at: dt.datetime | None
    created_at: dt.datetime
```
New `TournamentNextCycleResponse` extends this with map detail fields (map_code, map_name, map_difficulty).

**Request struct pattern** -- copy from `TournamentCompletionCreateRequest` (lines 249-262):
```python
class TournamentCompletionCreateRequest(Struct):
    """Request payload for submitting a tournament completion.

    Attributes:
        user_id: Identifier of the submitting user.
        time: Completion time in seconds.
        screenshot: Proof screenshot URL.
        video: Optional video proof URL.
    """

    user_id: int
    time: float
    screenshot: str
    video: str | None = None
```
New `TournamentChooseMapRequest` should follow this pattern with a single `map_code: str` field.

**`__all__` tuple** (lines 8-28) -- must be updated with new type names:
```python
__all__ = (
    "CycleFrequency",
    "CycleStatus",
    # ... existing entries ...
)
```

**Imports** (lines 1-6):
```python
import datetime as dt
from typing import Literal

from msgspec import UNSET, Struct, UnsetType

from .difficulties import DifficultyTop
```

---

### `apps/api/tests/services/test_tournament_service.py` (test, unit) -- NEW

**Analog:** `apps/api/tests/services/test_maps_service.py`

**Module docstring and imports** (lines 1-38):
```python
"""Unit tests for MapsService.

This test module focuses on business logic validation and error translation
in the maps service layer. Simple pass-through methods are covered by integration tests.
"""

import datetime as dt

from genjishimada_sdk.users import CreatorFull
import pytest
from genjishimada_sdk.maps import (
    # ... SDK types ...
)
from litestar.datastructures import Headers

from repository.exceptions import ForeignKeyViolationError, UniqueConstraintViolationError
from services.exceptions.maps import (
    # ... domain exceptions ...
)
from services.maps_service import MapsService

pytestmark = [
    pytest.mark.domain_maps,
]
```
New test file should import `TournamentService`, tournament SDK types, and tournament domain exceptions. Use `pytestmark = [pytest.mark.domain_tournaments]`.

**Service instantiation in test** (line 48):
```python
service = MapsService(mock_pool, mock_state, mock_maps_repo)
```
New tests should use: `service = TournamentService(mock_pool, mock_state, mock_tournament_repo)`

**Mock setup and assertion** (lines 44-75):
```python
async def test_create_map_duplicate_code_constraint(
    self, mock_pool, mock_state, mock_maps_repo, mocker
):
    """UniqueConstraintViolationError on maps_code_key raises MapCodeExistsError."""
    service = MapsService(mock_pool, mock_state, mock_maps_repo)

    # ... setup request data ...

    # Mock repository to raise constraint violation
    mock_maps_repo.create_core_map.side_effect = UniqueConstraintViolationError("maps_code_key", "maps")

    # Act & Assert
    with pytest.raises(MapCodeExistsError) as exc_info:
        await service.create_map(data, mock_headers, mock_newsfeed_service, mock_lootbox_service)

    assert exc_info.value.context["code"] == "ABCDE"
```

**Required conftest fixture** -- add to `tests/services/conftest.py` (copy pattern from line 106-109):
```python
@pytest.fixture
def mock_maps_repo(mocker):
    """Mock MapsRepository."""
    return mocker.AsyncMock(spec=MapsRepository)
```
New fixture: `mock_tournament_repo` using `mocker.AsyncMock(spec=TournamentRepository)`.

---

### `apps/api/tests/integration/test_tournaments_integration.py` (test, integration) -- MODIFY

**Analog:** self -- existing test classes in same file

**4 new test classes needed:** `TestSelectMap`, `TestGetNextCycle`, `TestReroll`, `TestChooseMap`

**Module header** (lines 1-16):
```python
"""Integration tests for Tournaments v3 controller.

Tests HTTP interface: request/response serialization,
error translation, and full stack flow through real database.
"""

from uuid import uuid4

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.domain_tournaments,
]

BASE = "/api/v3/tournaments"
```

**Test class with DB setup** -- copy from `TestCategoryLockedGuard` (lines 248-302):
```python
class TestCategoryLockedGuard:
    """Tests for CYCLE-08: categories with active cycles cannot be modified."""

    async def test_update_locked_during_active_cycle(self, test_client, asyncpg_pool, create_test_map):
        """PATCH returns 409 when category has an active cycle."""
        name = f"Locked {uuid4().hex[:8]}"
        create_resp = await test_client.post(
            f"{BASE}/categories",
            json={"name": name, "difficulties": ["Easy"]},
        )
        category_id = create_resp.json()["id"]

        map_id = await create_test_map()

        async with asyncpg_pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO tournaments.cycles (category_id, map_id, status)
                VALUES ($1, $2, 'active')
                """,
                category_id,
                map_id,
            )

        response = await test_client.patch(
            f"{BASE}/categories/{category_id}",
            json={"name": f"NewName {uuid4().hex[:8]}"},
        )

        assert response.status_code == 409
```
Key pattern: create category via API, create test map via fixture, insert cycle via direct DB, then test endpoint behavior. New test classes for map selection endpoints should follow this exact setup pattern using `test_client`, `asyncpg_pool`, and `create_test_map` fixtures.

**Simple endpoint test** -- copy from `TestGetCategory` (lines 145-167):
```python
class TestGetCategory:
    """GET /api/v3/tournaments/categories/{id}"""

    async def test_get_existing_category(self, test_client):
        name = f"GetOne {uuid4().hex[:8]}"
        create_resp = await test_client.post(
            f"{BASE}/categories",
            json={"name": name, "difficulties": ["Medium"]},
        )
        category_id = create_resp.json()["id"]

        response = await test_client.get(f"{BASE}/categories/{category_id}")

        assert response.status_code == 200
        assert response.json()["id"] == category_id
        assert response.json()["name"] == name

    async def test_get_nonexistent_returns_404(self, test_client):
        response = await test_client.get(f"{BASE}/categories/999999")
        assert response.status_code == 404
```

---

## Shared Patterns

### Authentication / Scope Guard
**Source:** `apps/api/routes/v3/tournaments.py` lines 50-51, 71-72
**Apply to:** All 4 new controller endpoints
```python
# Read-only endpoint
opt={"required_scopes": {"tournaments:read"}},

# Mutation endpoint
opt={"required_scopes": {"tournaments:write"}},
```

### Error Handling: Controller Exception-to-HTTP Mapping
**Source:** `apps/api/routes/v3/tournaments.py` lines 164-170, 204-209
**Apply to:** All 4 new controller endpoints
```python
except CategoryNotFoundError as e:
    raise CustomHTTPException(
        status_code=HTTP_404_NOT_FOUND,
        detail=str(e),
    ) from e
```
Pattern: catch domain exception, wrap in `CustomHTTPException` with appropriate status code, use `from e` to preserve chain.

### Error Handling: Service Domain Exception Raising
**Source:** `apps/api/services/tournament_service.py` lines 123-126
**Apply to:** All 4 new service methods
```python
row = await self._tournament_repo.fetch_category(category_id)
if row is None:
    raise CategoryNotFoundError(category_id)
```
Pattern: check repository result, raise domain exception if precondition violated.

### Transaction Boundary
**Source:** `apps/api/services/tournament_service.py` lines 168-181
**Apply to:** `select_map`, `reroll_map`, `choose_map` service methods
```python
async with self._pool.acquire() as conn:
    cycle_id = await self._tournament_repo.check_active_cycle_for_category(
        category_id,
        conn=conn,  # type: ignore[arg-type]
    )
    if cycle_id is not None:
        raise CategoryLockedError(category_id, cycle_id=cycle_id)

    row = await self._tournament_repo.update_category(
        category_id,
        updates,
        conn=conn,  # type: ignore[arg-type]
    )
```
Critical: every repository call inside the `async with` block MUST pass `conn=conn,  # type: ignore[arg-type]`.

### Repository Method Signature
**Source:** `apps/api/repository/tournaments_repository.py` lines 148-153
**Apply to:** All 3 new repository methods
```python
async def fetch_category(
    self,
    category_id: int,
    *,
    conn: Connection | None = None,
) -> dict | None:
```
Pattern: positional params, then `*` keyword-only separator, then `conn: Connection | None = None`.

### Repository Connection Resolution
**Source:** `apps/api/repository/tournaments_repository.py` lines 163-166
**Apply to:** All 3 new repository methods
```python
_conn = self._get_connection(conn)
query = "SELECT * FROM tournaments.categories WHERE id = $1"
row = await _conn.fetchrow(query, category_id)
return dict(row) if row else None
```

### SDK Struct Conventions
**Source:** `libs/sdk/src/genjishimada_sdk/tournaments.py` lines 1-6
**Apply to:** New SDK structs
```python
import datetime as dt
from typing import Literal

from msgspec import UNSET, Struct, UnsetType

from .difficulties import DifficultyTop
```
- Google-style docstrings with `Attributes:` section
- Update `__all__` tuple with new type names
- Response structs: `*Response` suffix
- Request structs: `*Request` suffix

### Logging
**Source:** `apps/api/services/base.py` line 18
**Apply to:** Service file (for pool exhaustion warning)
```python
log = getLogger(__name__)
```
Use `%s` formatting: `log.warning("[!] Eligible map pool exhausted for category %s, using LRU fallback", category_id)`

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| -- | -- | -- | All files have exact analogs within the existing tournament codebase from Phases 3-4 |

No files lack analogs. Every file being created or modified has a direct pattern to copy from within the existing `tournaments_repository.py`, `tournament_service.py`, `tournaments.py` controller, tournament exceptions, and tournament SDK module.

## Metadata

**Analog search scope:** `apps/api/repository/`, `apps/api/services/`, `apps/api/routes/v3/`, `apps/api/services/exceptions/`, `libs/sdk/src/genjishimada_sdk/`, `apps/api/tests/`
**Files scanned:** 12
**Pattern extraction date:** 2026-05-29
