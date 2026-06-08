# Phase 6: Submission Flow & Leaderboard - Pattern Map

**Mapped:** 2026-05-29
**Files analyzed:** 8 (new/modified files)
**Analogs found:** 8 / 8

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `apps/api/services/tournament_service.py` | service | CRUD + transaction | `apps/api/services/tournament_service.py` (self, existing methods) | exact |
| `apps/api/routes/v3/tournaments.py` | controller | request-response | `apps/api/routes/v3/tournaments.py` (self, existing endpoints) | exact |
| `apps/api/services/exceptions/tournaments.py` | domain-exception | N/A | `apps/api/services/exceptions/tournaments.py` (self) | exact |
| `libs/sdk/src/genjishimada_sdk/tournaments.py` | model | N/A | `libs/sdk/src/genjishimada_sdk/tournaments.py` (self) | exact |
| `apps/api/repository/tournaments_repository.py` | repository | CRUD | `apps/api/repository/tournaments_repository.py` (self) | exact |
| `apps/api/tests/services/test_tournament_service.py` | test (unit) | mock-based | `apps/api/tests/services/test_tournament_service.py` (self) | exact |
| `apps/api/tests/integration/test_tournaments_integration.py` | test (integration) | HTTP client | `apps/api/tests/integration/test_tournaments_integration.py` (self) | exact |
| `apps/api/tests/services/conftest.py` | test (fixture) | N/A | `apps/api/tests/services/conftest.py` (self) | exact |

## Pattern Assignments

### `apps/api/services/tournament_service.py` (service, CRUD + transaction)

**Analog:** Same file -- extending with `submit_completion`, `get_leaderboard`, `list_cycles` methods.

**Imports pattern** (lines 1-33):
```python
from __future__ import annotations

import re
from logging import getLogger

import msgspec
from asyncpg import Pool
from genjishimada_sdk.tournaments import (
    TournamentCategoryCreateRequest,
    # ... add new imports here:
    TournamentCompletionCreateRequest,
    TournamentCompletionResponse,
    TournamentLeaderboardEntryResponse,
    # ... new response struct for cycle listing
)
from litestar.datastructures import State

from repository.exceptions import UniqueConstraintViolationError
from repository.tournaments_repository import TournamentRepository
from services.base import BaseService
from services.exceptions.tournaments import (
    # ... add new exception imports:
    CycleNotActiveError,
    CycleNotFoundError,
    SlowerTimeError,
    MapMismatchError,
)

log = getLogger(__name__)
```

**Constructor pattern** (lines 37-54):
```python
class TournamentService(BaseService):
    """Service for tournament config and category business logic."""

    def __init__(
        self,
        pool: Pool,
        state: State,
        tournament_repo: TournamentRepository,
    ) -> None:
        super().__init__(pool, state)
        self._tournament_repo = tournament_repo
```

**Transactional check-then-mutate pattern** -- copy from `update_category` (lines 139-201) and `select_map` (lines 231-295):
```python
# Pattern: acquire connection -> validate -> mutate -> return
async with self._pool.acquire() as conn, conn.transaction():
    # 1. Validate preconditions on same connection
    cycle = await self._tournament_repo.fetch_cycle(
        cycle_id,
        conn=conn,  # type: ignore[arg-type]
    )
    if cycle is None:
        raise CycleNotFoundError(cycle_id)

    # 2. Business rule check
    existing = await self._tournament_repo.fetch_user_completion(
        cycle_id, data.user_id,
        conn=conn,  # type: ignore[arg-type]
    )
    if existing and data.time >= existing["time"]:
        raise SlowerTimeError(...)

    # 3. Mutate
    row = await self._tournament_repo.create_tournament_completion(
        ...,
        conn=conn,  # type: ignore[arg-type]
    )

    # 4. Cross-write
    await self._tournament_repo.cross_write_to_core(
        ...,
        conn=conn,  # type: ignore[arg-type]
    )

return msgspec.convert(row, TournamentCompletionResponse)
```

**Simple read-and-convert pattern** -- copy from `list_categories` (lines 113-120) and `get_category` (lines 122-137):
```python
# For get_leaderboard:
async def get_leaderboard(self, cycle_id: int) -> list[TournamentLeaderboardEntryResponse]:
    rows = await self._tournament_repo.fetch_leaderboard(cycle_id)
    return [msgspec.convert(row, TournamentLeaderboardEntryResponse) for row in rows]

# For list_cycles (with not-found check):
async def list_cycles(self, ...) -> SomeResponse:
    total, rows = await self._tournament_repo.fetch_cycles(...)
    return ...
```

**DI provider pattern** (lines 461-474):
```python
async def provide_tournament_service(
    state: State,
    tournament_repo: TournamentRepository,
) -> TournamentService:
    return TournamentService(state.db_pool, state, tournament_repo)
```

---

### `apps/api/routes/v3/tournaments.py` (controller, request-response)

**Analog:** Same file -- extending with submit, leaderboard, and cycles list endpoints.

**Imports pattern** (lines 1-40):
```python
from __future__ import annotations

from typing import Annotated

import litestar
from genjishimada_sdk.tournaments import (
    # ... add new SDK types:
    TournamentCompletionCreateRequest,
    TournamentCompletionResponse,
    TournamentLeaderboardEntryResponse,
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
    HTTP_422_UNPROCESSABLE_ENTITY,
)

from repository.tournaments_repository import provide_tournament_repository
from services.exceptions.tournaments import (
    # ... add new exception imports:
    CycleNotActiveError,
    CycleNotFoundError,
    SlowerTimeError,
    MapMismatchError,
)
from services.tournament_service import TournamentService, provide_tournament_service
from utilities.errors import CustomHTTPException
```

**Controller class with dependencies** (lines 43-51):
```python
class TournamentsController(litestar.Controller):
    """Tournaments v3 controller."""

    tags = ["Tournaments"]
    path = "/tournaments"
    dependencies = {
        "tournament_repo": Provide(provide_tournament_repository),
        "tournament_service": Provide(provide_tournament_service),
    }
```

**POST endpoint with exception handling** -- copy from `create_category` (lines 96-126) and `select_map` (lines 292-332):
```python
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
    """Submit a tournament completion.

    Args:
        tournament_service: Tournament service.
        cycle_id: Cycle ID.
        data: Submission request.

    Returns:
        Created tournament completion.

    Raises:
        CustomHTTPException: 404 if cycle not found, 409 if not active or slower time.
    """
    try:
        return await tournament_service.submit_completion(cycle_id, data)
    except CycleNotFoundError as e:
        raise CustomHTTPException(
            status_code=HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e
    except (CycleNotActiveError, SlowerTimeError) as e:
        raise CustomHTTPException(
            status_code=HTTP_409_CONFLICT,
            detail=str(e),
        ) from e
```

**GET endpoint pattern** -- copy from `list_categories` (lines 128-146) and `get_category` (lines 148-177):
```python
@litestar.get(
    path="/cycles/{cycle_id:int}/leaderboard",
    summary="Get Tournament Leaderboard",
    opt={"required_scopes": {"tournaments:read"}},
)
async def get_leaderboard(
    self,
    tournament_service: TournamentService,
    cycle_id: Annotated[int, Parameter(description="Cycle ID")],
) -> list[TournamentLeaderboardEntryResponse]:
    """Get ranked leaderboard for a cycle."""
    return await tournament_service.get_leaderboard(cycle_id)
```

**GET with query params** -- inferred from existing patterns using `Parameter`:
```python
@litestar.get(
    path="/cycles",
    summary="List Tournament Cycles",
    opt={"required_scopes": {"tournaments:read"}},
)
async def list_cycles(
    self,
    tournament_service: TournamentService,
    status: Annotated[str | None, Parameter(description="Filter by cycle status", required=False)] = None,
    category_id: Annotated[int | None, Parameter(description="Filter by category ID", required=False)] = None,
    limit: Annotated[int, Parameter(description="Max results", ge=1, le=100)] = 20,
    offset: Annotated[int, Parameter(description="Result offset", ge=0)] = 0,
) -> SomeListResponse:
    """List tournament cycles with pagination."""
    return await tournament_service.list_cycles(
        status=status, category_id=category_id, limit=limit, offset=offset,
    )
```

---

### `apps/api/services/exceptions/tournaments.py` (domain-exception)

**Analog:** Same file -- adding `SlowerTimeError`, `MapMismatchError`. `CycleNotActiveError` and `CycleNotFoundError` already exist.

**Exception class pattern** -- copy from `CategoryLockedError` (lines 14-22) and `CycleNotActiveError` (lines 46-54):
```python
class SlowerTimeError(TournamentsError):
    """Submitted time is not faster than the user's current best for this cycle."""

    def __init__(self, current_best: float, submitted_time: float) -> None:
        super().__init__(
            f"Submitted time ({submitted_time}s) is not faster than your current best ({current_best}s).",
            current_best=current_best,
            submitted_time=submitted_time,
        )


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

**Key pattern:** All exception classes follow:
1. Inherit from `TournamentsError`
2. Google-style docstring (single line)
3. `__init__` with typed parameters
4. `super().__init__(message_string, **kwargs)` passing all context as keyword args

---

### `libs/sdk/src/genjishimada_sdk/tournaments.py` (model)

**Analog:** Same file -- adding `TournamentCycleWithWinnerResponse` (or similar).

**Response struct pattern** -- copy from `TournamentCycleResponse` (lines 175-194) and `TournamentLeaderboardEntryResponse` (lines 236-253):
```python
class TournamentCycleWithWinnerResponse(Struct):
    """Cycle entry for listing, including rank-1 winner info.

    Attributes:
        id: Cycle identifier.
        category_id: Category this cycle belongs to.
        map_id: Map selected for this cycle.
        map_code: Workshop code of the selected map.
        map_name: Display name of the selected map.
        map_difficulty: Difficulty rating of the selected map.
        status: Current lifecycle status.
        started_at: When the cycle became active.
        ended_at: When the cycle was finalized.
        created_at: When the cycle record was created.
        winner_name: Display name of the rank-1 user, or None.
        winner_user_id: User ID of the rank-1 user, or None.
    """

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

**`__all__` tuple pattern** (lines 8-30) -- add new struct names to the existing tuple.

**List wrapper pattern** -- if a paginated wrapper is needed:
```python
class TournamentCycleListResponse(Struct):
    """Paginated cycle listing.

    Attributes:
        total: Total number of matching cycles.
        cycles: Page of cycle entries.
    """

    total: int
    cycles: list[TournamentCycleWithWinnerResponse]
```

---

### `apps/api/repository/tournaments_repository.py` (repository, CRUD)

**Analog:** Same file -- potentially adding `fetch_cycles` method.

**Paginated query pattern** -- copy from `fetch_cycle_history` (lines 404-440):
```python
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
    # Dynamic WHERE clause building
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
    # Count + fetch
    total = await _conn.fetchval(f"SELECT COUNT(*) FROM tournaments.cycles cy {where_clause}", *args) or 0
    # Data query with JOINs
    rows = await _conn.fetch(data_query, *args, limit, offset)
    return total, [dict(row) for row in rows]
```

**Connection injection pattern** (used everywhere, e.g., lines 52-55):
```python
_conn = self._get_connection(conn)
```

---

### `apps/api/tests/services/test_tournament_service.py` (test, unit)

**Analog:** Same file -- adding `TestSubmitCompletion`, `TestGetLeaderboard`, `TestListCycles` classes.

**Test file structure** (lines 1-15):
```python
"""Unit tests for TournamentService map selection logic."""

import pytest

from genjishimada_sdk.tournaments import TournamentCompletionCreateRequest
from services.exceptions.tournaments import (
    CycleNotActiveError,
    CycleNotFoundError,
    SlowerTimeError,
)
from services.tournament_service import TournamentService

pytestmark = [pytest.mark.domain_tournaments]
```

**Dict factory pattern** (lines 22-37):
```python
_config = lambda **kw: {"blacklist_weeks": 4, **kw}
_category = lambda **kw: {"id": 1, "name": "Test", "difficulties": ["Easy"], **kw}
_map = lambda **kw: {"id": 10, "code": "ABC12", "map_name": "TestMap", "difficulty": "Easy", **kw}
_pending = lambda **kw: {
    "id": 100,
    "category_id": 1,
    "map_id": 10,
    ...
    **kw,
}

# Add new factory for completions:
_completion = lambda **kw: {
    "id": 1, "cycle_id": 1, "user_id": 100, "map_id": 10,
    "time": 42.5, "screenshot": "https://example.com/s.png",
    "video": None, "verified": False, "completion": False,
    "inserted_at": "2026-01-01T00:00:00",
    **kw,
}
```

**Test class and method pattern** (lines 40-68):
```python
class TestSubmitCompletion:
    """Tests for TournamentService.submit_completion."""

    async def test_submit_happy_path(self, mock_pool, mock_state, mock_tournament_repo):
        """Happy path: submits completion and cross-writes."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_cycle.return_value = {"id": 1, "status": "active", "map_id": 10, ...}
        mock_tournament_repo.fetch_user_completion.return_value = None
        mock_tournament_repo.create_tournament_completion.return_value = _completion()
        mock_tournament_repo.cross_write_to_core.return_value = 999

        result = await service.submit_completion(1, TournamentCompletionCreateRequest(...))

        assert result.id == 1
        mock_tournament_repo.create_tournament_completion.assert_called_once()
        mock_tournament_repo.cross_write_to_core.assert_called_once()

    async def test_rejects_slower_time(self, mock_pool, mock_state, mock_tournament_repo):
        """Raises SlowerTimeError when new time is not faster."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_cycle.return_value = {"id": 1, "status": "active", "map_id": 10}
        mock_tournament_repo.fetch_user_completion.return_value = _completion(time=30.0)

        with pytest.raises(SlowerTimeError):
            await service.submit_completion(1, TournamentCompletionCreateRequest(
                user_id=100, time=35.0, screenshot="https://example.com/s.png"
            ))
```

**Key fixture:** `mock_pool`, `mock_state`, `mock_tournament_repo` from `apps/api/tests/services/conftest.py`.

---

### `apps/api/tests/integration/test_tournaments_integration.py` (test, integration)

**Analog:** Same file -- adding `TestSubmitCompletion`, `TestLeaderboard`, `TestCycleListing` classes.

**Integration test markers** (lines 1-16):
```python
"""Integration tests for Tournaments v3 controller."""

from uuid import uuid4

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.domain_tournaments,
]

BASE = "/api/v3/tournaments"
```

**Test class with HTTP client** (lines 19-30):
```python
class TestSubmitCompletion:
    """POST /api/v3/tournaments/cycles/{id}/submit"""

    async def test_submit_happy_path(self, test_client, asyncpg_pool, create_test_map):
        """Submission returns 201 with completion record."""
        # 1. Create category
        name = f"Submit {uuid4().hex[:8]}"
        create_resp = await test_client.post(
            f"{BASE}/categories",
            json={"name": name, "difficulties": ["Easy"]},
        )
        category_id = create_resp.json()["id"]

        # 2. Create map and active cycle via direct DB setup
        map_id = await create_test_map(difficulty="Easy")
        async with asyncpg_pool.acquire() as conn:
            cycle_id = await conn.fetchval(
                """
                INSERT INTO tournaments.cycles (category_id, map_id, status, started_at)
                VALUES ($1, $2, 'active', now())
                RETURNING id
                """,
                category_id, map_id,
            )
            # Create a user for the submission
            user_id = await conn.fetchval(
                "INSERT INTO core.users (nickname) VALUES ($1) RETURNING id",
                f"testuser_{uuid4().hex[:8]}",
            )

        # 3. Submit
        response = await test_client.post(
            f"{BASE}/cycles/{cycle_id}/submit",
            json={"user_id": user_id, "time": 42.5, "screenshot": "https://example.com/s.png"},
        )

        assert response.status_code == 201
```

**Pattern for direct DB setup** -- copy from `TestCategoryLockedGuard` (lines 248-301):
```python
# Create test data via asyncpg_pool, then call endpoints via test_client
map_id = await create_test_map(difficulty="Easy")
async with asyncpg_pool.acquire() as conn:
    await conn.execute(
        """INSERT INTO tournaments.cycles (category_id, map_id, status)
        VALUES ($1, $2, 'active')""",
        category_id, map_id,
    )
```

---

### `apps/api/tests/services/conftest.py` (test fixtures)

**Analog:** Same file -- no changes needed, `mock_tournament_repo` fixture already exists (line 216-218):
```python
@pytest.fixture
def mock_tournament_repo(mocker):
    """Mock TournamentRepository."""
    return mocker.AsyncMock(spec=TournamentRepository)
```

---

## Shared Patterns

### Authentication & Scopes
**Source:** `apps/api/routes/v3/tournaments.py` lines 53-57, and all endpoint decorators
**Apply to:** All new endpoints in the controller

```python
# Write endpoints (submit):
opt={"required_scopes": {"tournaments:write"}}

# Read endpoints (leaderboard, cycles list):
opt={"required_scopes": {"tournaments:read"}}
```

### Error Handling (Controller -> HTTP Translation)
**Source:** `apps/api/routes/v3/tournaments.py` lines 120-126 (all try/except blocks)
**Apply to:** All new controller endpoint handlers

```python
try:
    return await tournament_service.some_method(...)
except SomeDomainError as e:
    raise CustomHTTPException(
        status_code=HTTP_4XX,
        detail=str(e),
    ) from e
```

### Error Handling (Service -> Domain Exception)
**Source:** `apps/api/services/tournament_service.py` lines 134-136, 184-186, 254
**Apply to:** All new service methods

```python
# Null check -> not-found exception
row = await self._tournament_repo.fetch_cycle(cycle_id, conn=conn)
if row is None:
    raise CycleNotFoundError(cycle_id)

# Business rule check -> domain exception
if existing and data.time >= existing["time"]:
    raise SlowerTimeError(current_best=existing["time"], submitted_time=data.time)
```

### Domain Exception Hierarchy
**Source:** `apps/api/utilities/errors.py` lines 150-169 (`DomainError` base) + `apps/api/services/exceptions/tournaments.py`
**Apply to:** All new exception classes

```python
# Base: DomainError(message, **context)
# Domain: TournamentsError(DomainError)
# Specific: SlowerTimeError(TournamentsError) with typed __init__
```

### Connection Injection (`# type: ignore[arg-type]`)
**Source:** `apps/api/services/tournament_service.py` lines 180-183 (all `conn=conn` calls)
**Apply to:** All service calls to repository within `async with self._pool.acquire() as conn`

```python
# The conn from pool.acquire() is typed differently than the repo expects.
# All existing code uses this suppress:
await self._tournament_repo.some_method(
    arg1, arg2,
    conn=conn,  # type: ignore[arg-type]
)
```

### Response Serialization
**Source:** `apps/api/services/tournament_service.py` lines 63, 111, 120, 137, 201, 295
**Apply to:** All service methods returning SDK structs

```python
# Single record:
return msgspec.convert(row, SomeResponse)

# List of records:
return [msgspec.convert(row, SomeResponse) for row in rows]
```

### Test Fixture Injection
**Source:** `apps/api/tests/services/conftest.py` lines 38-101
**Apply to:** All new unit test classes

```python
# Three standard fixtures for service tests:
async def test_something(self, mock_pool, mock_state, mock_tournament_repo):
    service = TournamentService(mock_pool, mock_state, mock_tournament_repo)
    # mock_pool provides async context manager for pool.acquire() + conn.transaction()
    # mock_state provides mq_channel_pool for BaseService
    # mock_tournament_repo is AsyncMock(spec=TournamentRepository)
```

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| (none) | -- | -- | All files extend existing tournament domain code; every file has an exact self-analog |

## Metadata

**Analog search scope:** `apps/api/services/`, `apps/api/routes/v3/`, `apps/api/repository/`, `apps/api/services/exceptions/`, `libs/sdk/src/genjishimada_sdk/`, `apps/api/tests/`, `apps/api/utilities/`
**Files scanned:** 12 (direct reads of analog files)
**Pattern extraction date:** 2026-05-29
