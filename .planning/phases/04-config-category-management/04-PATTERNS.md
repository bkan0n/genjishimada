# Phase 4: Config & Category Management - Pattern Map

**Mapped:** 2026-05-29
**Files analyzed:** 3 (2 new, 1 modify)
**Analogs found:** 3 / 3

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `apps/api/services/tournament_service.py` | service | CRUD | `apps/api/services/store_service.py` | exact |
| `apps/api/routes/v3/tournaments.py` | controller | request-response | `apps/api/routes/v3/store.py` | exact |
| `apps/api/services/exceptions/tournaments.py` | domain-exception | N/A | `apps/api/services/exceptions/maps.py` | exact |

## Pattern Assignments

### `apps/api/services/tournament_service.py` (service, CRUD) -- NEW

**Analog:** `apps/api/services/store_service.py` + `apps/api/services/maps_service.py`

**Imports pattern** (store_service.py lines 1-8, maps_service.py lines 1-2, 15-16, 65-68, 91):
```python
"""Service for tournament domain business logic."""

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

**Service class + constructor pattern** (store_service.py lines 1-8 concept, maps_service.py lines 113-124):
```python
# maps_service.py lines 113-124
class MapsService(BaseService):
    """Service for maps business logic."""

    def __init__(
        self,
        pool: Pool,
        state: State,
        maps_repo: MapsRepository,
    ) -> None:
        """Initialize service."""
        super().__init__(pool, state)
        self._maps_repo = maps_repo
```

**Config GET pattern** (store_service.py lines 139-146):
```python
    async def get_config(self) -> StoreConfigResponse:
        """Get store configuration.

        Returns:
            Store configuration.
        """
        config = await self._store_repo.fetch_config()
        return msgspec.convert(config, StoreConfigResponse)
```

**PATCH with UNSET filtering pattern** (maps_service.py lines 332-357):
```python
        core_updates = {}
        if data.code is not msgspec.UNSET:
            core_updates["code"] = data.code
        if data.map_name is not msgspec.UNSET:
            core_updates["map_name"] = data.map_name
        if data.category is not msgspec.UNSET:
            core_updates["category"] = data.category
        if data.checkpoints is not msgspec.UNSET:
            core_updates["checkpoints"] = data.checkpoints
        if data.difficulty is not msgspec.UNSET:
            core_updates["difficulty"] = data.difficulty
            core_updates["raw_difficulty"] = DIFFICULTY_MIDPOINTS[data.difficulty]
        # ... etc
```

**Transaction + same-connection guard pattern** (maps_service.py lines 359-366):
```python
        async with self._pool.acquire() as conn, conn.transaction():
            try:
                if core_updates:
                    await self._maps_repo.update_core_map(
                        code,
                        core_updates,
                        conn=conn,  # type: ignore[arg-type]
                    )
```

**UniqueConstraint -> domain exception translation** (maps_service.py lines 436-439):
```python
            except UniqueConstraintViolationError as e:
                if "maps_code_key" in e.constraint_name:
                    new_code = data.code if data.code is not msgspec.UNSET else code
                    raise MapCodeExistsError(new_code) from e
```

**Provider function pattern** (maps_service.py lines 1979-1984):
```python
async def provide_maps_service(
    state: State,
    maps_repo: MapsRepository,
) -> MapsService:
    """Litestar DI provider for service."""
    return MapsService(state.db_pool, state, maps_repo)
```

---

### `apps/api/routes/v3/tournaments.py` (controller, request-response) -- NEW

**Analog:** `apps/api/routes/v3/store.py`

**Imports pattern** (store.py lines 1-59):
```python
"""Tournaments v3 controller."""

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
from litestar.params import Body
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

**Controller class + dependencies pattern** (store.py lines 62-71):
```python
class StoreController(litestar.Controller):
    """Store v3 controller."""

    tags = ["Store"]
    path = "/store"
    dependencies = {
        "store_repo": Provide(provide_store_repository),
        "store_service": Provide(provide_store_service),
    }
```

**GET endpoint with scope guard** (store.py lines 329-347):
```python
    @litestar.get(
        path="/admin/config",
        summary="Get Store Config (Admin)",
        description="View current store configuration.",
        opt={"required_scopes": {"store:admin"}},
    )
    async def get_config(
        self,
        store_service: StoreService,
    ) -> StoreConfigResponse:
        """Get store config.

        Args:
            store_service: Store service.

        Returns:
            Store configuration.
        """
        return await store_service.get_config()
```

**PATCH endpoint with exception mapping** (store.py lines 349-383):
```python
    @litestar.put(
        path="/admin/config",
        summary="Update Store Config (Admin)",
        description="Update store configuration.",
        status_code=HTTP_200_OK,
        opt={"required_scopes": {"store:admin"}},
    )
    async def update_config(
        self,
        store_service: StoreService,
        data: Annotated[UpdateConfigRequest, Body()],
    ) -> StoreConfigResponse:
        """Update store config.

        Args:
            store_service: Store service.
            data: Config update request.

        Returns:
            Updated configuration.

        Raises:
            CustomHTTPException: On validation errors.
        """
        try:
            await store_service.update_config(
                rotation_period_days=data.rotation_period_days,
                active_key_type=data.active_key_type,
            )
            return await store_service.get_config()
        except InvalidKeyTypeError as e:
            raise CustomHTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=str(e),
            ) from e
```

**POST endpoint with validation** (store.py lines 120-164, purchase_keys handler):
```python
    @litestar.post(
        path="/purchase/keys",
        summary="Purchase Keys",
        description="Purchase lootbox keys with coins.",
        status_code=HTTP_200_OK,
        opt={"required_scopes": {"store:write"}},
    )
    async def purchase_keys(
        self,
        store_service: StoreService,
        data: Annotated[KeyPurchaseRequest, Body()],
    ) -> KeyPurchaseResponse:
        """Purchase keys.

        Args:
            store_service: Store service.
            data: Purchase request.

        Returns:
            Purchase response.

        Raises:
            CustomHTTPException: On validation or business logic errors.
        """
        try:
            return await store_service.purchase_keys(...)
        except InvalidQuantityError as e:
            raise CustomHTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail=str(e),
            ) from e
```

**DELETE endpoint with 204 response** (maps.py lines 586-625):
```python
    @delete(
        "/{code:str}/guides/{user_id:int}",
        summary="Delete Guide",
        status_code=HTTP_204_NO_CONTENT,
        opt={"required_scopes": {"maps:write"}},
    )
    async def delete_guide_endpoint(
        self,
        code: OverwatchCode,
        user_id: int,
        maps_service: MapsService,
    ) -> Response[None]:
        """Delete a guide.

        Args:
            code: Map code.
            user_id: User ID who owns the guide.
            maps_service: Maps service.

        Returns:
            Empty response with 204 status.

        Raises:
            CustomHTTPException: On error.
        """
        try:
            await maps_service.delete_guide(code, user_id)
            return Response(None, status_code=HTTP_204_NO_CONTENT)

        except MapNotFoundError as e:
            raise CustomHTTPException(
                detail=f"No map found with code: {code}",
                status_code=HTTP_404_NOT_FOUND,
            ) from e
```

---

### `apps/api/services/exceptions/tournaments.py` (domain-exception, N/A) -- MODIFY

**Analog:** `apps/api/services/exceptions/maps.py`

**Existing file** (tournaments.py lines 1-30 -- already contains TournamentsError, CategoryLockedError, CategoryNotFoundError):
```python
"""Tournaments domain exceptions.

These exceptions represent business rule violations in the tournaments domain.
They are raised by TournamentsService and caught by controllers.
"""

from utilities.errors import DomainError


class TournamentsError(DomainError):
    """Base for tournaments domain errors."""


class CategoryLockedError(TournamentsError):
    """Category cannot be modified while a cycle is active."""

    def __init__(self, category_id: int, cycle_id: int) -> None:
        super().__init__(
            "Category cannot be modified while a cycle is active.",
            category_id=category_id,
            cycle_id=cycle_id,
        )


class CategoryNotFoundError(TournamentsError):
    """Tournament category does not exist."""

    def __init__(self, category_id: int) -> None:
        super().__init__("Tournament category not found.", category_id=category_id)
```

**New exception pattern to add** (modeled after maps.py lines 26-33, MapCodeExistsError):
```python
class MapCodeExistsError(MapsError):
    """Map code already exists."""

    def __init__(self, code: str) -> None:
        super().__init__(
            f"Provided code already exists: {code}",
            code=code,
        )
```

---

## Shared Patterns

### Authentication / Scope Guard
**Source:** `apps/api/middleware/guards.py` (existing, no changes)
**Apply to:** All controller endpoints in `routes/v3/tournaments.py`
```python
# Read endpoints use tournaments:read
opt={"required_scopes": {"tournaments:read"}}

# Write endpoints use tournaments:write
opt={"required_scopes": {"tournaments:write"}}
```

### Error Handling (Three-Tier Hierarchy)
**Source:** `apps/api/repository/exceptions.py`, `apps/api/services/exceptions/tournaments.py`, `apps/api/utilities/errors.py`
**Apply to:** Service and controller files

Repository layer (already implemented in Phase 3):
```python
# repository/exceptions.py -- repo catches asyncpg, raises structured errors
except UniqueViolationError as e:
    constraint_name = extract_constraint_name(e) or "unknown"
    raise UniqueConstraintViolationError(constraint_name, "tournaments.categories", str(e)) from e
```

Service layer (new in Phase 4):
```python
# Service catches repo exceptions, translates to domain exceptions
except UniqueConstraintViolationError as e:
    if "name" in (e.constraint_name or ""):
        raise CategoryNameExistsError(data.name) from e
    raise
```

Controller layer (new in Phase 4):
```python
# Controller catches domain exceptions, maps to HTTP responses
except CategoryNotFoundError as e:
    raise CustomHTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e)) from e
except CategoryLockedError as e:
    raise CustomHTTPException(status_code=HTTP_409_CONFLICT, detail=str(e)) from e
except CategoryNameExistsError as e:
    raise CustomHTTPException(status_code=HTTP_409_CONFLICT, detail=str(e)) from e
```

### DomainError Base Class
**Source:** `apps/api/utilities/errors.py` lines 150-169
**Apply to:** All domain exception classes
```python
class DomainError(Exception):
    """Base exception for domain-level business rule violations."""

    def __init__(self, message: str, **context: typing.Any) -> None:
        super().__init__(message)
        self.message = message
        self.context = context
```

### Dependency Injection Provider Pattern
**Source:** `apps/api/services/maps_service.py` lines 1979-1984
**Apply to:** Service file (bottom of `tournament_service.py`)
```python
async def provide_tournament_service(
    state: State,
    tournament_repo: TournamentRepository,
) -> TournamentService:
    """Litestar DI provider for tournament service."""
    return TournamentService(state.db_pool, state, tournament_repo)
```

### BaseService Inheritance
**Source:** `apps/api/services/base.py` lines 39-54
**Apply to:** `TournamentService`
```python
class BaseService:
    """Base class for all services."""

    def __init__(self, pool: Pool, state: State) -> None:
        self._pool = pool
        self._state = state
```

### Route Auto-Discovery
**Source:** `apps/api/routes/v3/__init__.py`
**Apply to:** `routes/v3/tournaments.py` (automatic -- no registration needed)

Any `Controller` subclass in `routes/v3/*.py` is auto-discovered by the `__init__.py` scanner. Just define the class and it gets mounted.

### msgspec.convert for Dict-to-Struct
**Source:** `apps/api/services/store_service.py` line 146
**Apply to:** All service methods that return SDK response structs from repository dicts
```python
config = await self._store_repo.fetch_config()
return msgspec.convert(config, StoreConfigResponse)
```

## No Analog Found

No files without analogs. All 3 files have exact matches in the existing codebase.

## Metadata

**Analog search scope:** `apps/api/services/`, `apps/api/routes/v3/`, `apps/api/services/exceptions/`, `apps/api/repository/`, `apps/api/utilities/`, `libs/sdk/`
**Files scanned:** 12
**Pattern extraction date:** 2026-05-29
