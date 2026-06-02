# Coding Conventions

**Analysis Date:** 2026-05-29

## Overview

This codebase follows a strict, Python 3.13+ convention set enforced by Ruff (linter + formatter) and BasedPyright (type checker). All three packages (API, bot, SDK) share the same Ruff rule set. Test files are explicitly exempt from all lint rules. Google-style docstrings are required on all public functions and methods.

## Naming Patterns

**Files:**
- Use `snake_case` for all Python files
- Repository files: `{domain}_repository.py` (e.g., `repository/maps_repository.py`)
- Service files: `{domain}_service.py` (e.g., `services/maps_service.py`)
- Route files: `{domain}.py` under versioned directory (e.g., `routes/v3/maps.py`)
- Domain exception files: `services/exceptions/{domain}.py` (e.g., `services/exceptions/maps.py`)
- SDK model files: `libs/sdk/src/genjishimada_sdk/{domain}.py` (e.g., `genjishimada_sdk/maps.py`)
- Bot extension files: `extensions/{feature}.py`

**Classes:**
- `PascalCase` for all classes
- SDK structs: `{Domain}{Action}{Suffix}` where suffix is `Request`, `Response`, or `Event`
  - Request: `MapCreateRequest`, `CompletionPatchRequest`, `QualityValueRequest`
  - Response: `MapResponse`, `MapPartialResponse`, `CompletionSubmissionJobResponse`
  - Event: `CompletionCreatedEvent`, `PlaytestCreatedEvent`, `PlaytestForceDeniedEvent`
- Domain exceptions: `{Description}Error` (e.g., `MapNotFoundError`, `DuplicateCreatorError`)
- Repository exceptions: `{Constraint}ViolationError` (e.g., `UniqueConstraintViolationError`, `ForeignKeyViolationError`)
- Base domain exception per domain: `{Domain}Error` (e.g., `MapsError extends DomainError`)

**Functions/Methods:**
- Use `snake_case` for all functions and methods
- Repository methods: verb-first naming (`fetch_maps`, `create_core_map`, `lookup_map_id`, `check_code_exists`)
- Service methods: action-oriented (`create_map`, `update_map`, `send_to_playtest`)
- DI provider functions: `provide_{class_name}` (e.g., `provide_maps_service`, `provide_maps_repository`)
- Private helpers: prefix with underscore (`_normalize_custom_banner`, `_get_connection`)

**Variables:**
- Use `snake_case` for all variables
- Connection pool: `self._pool` (private)
- Application state: `self._state` (private)
- Repository references: `self._maps_repo`, `self._completions_repo` (private)
- Logger: `log = getLogger(__name__)` at module level
- Constants: `UPPER_SNAKE_CASE` (e.g., `IGNORE_IDEMPOTENCY`, `DLQ_HEADER_KEY`, `BOT_USER_ID`)
- Private module constants: prefix with underscore (`_PREVIEW_MAX_LENGTH`, `_ASSET_BANNER_PATH`)

**Literal Types:**
- Use `Literal[...]` for constrained string values in SDK
- `DifficultyTop`, `DifficultyAll`, `MapCategory`, `OverwatchMap` defined in SDK
- `Annotated[str, Meta(...)]` for validated string types (e.g., `OverwatchCode`, `GuideURL`)

## Code Style

**Formatting:**
- Tool: Ruff (`ruff format`)
- Line length: 120 characters
- Target: Python 3.13

**Linting:**
- Tool: Ruff with extensive rule selection
- Config: Root `pyproject.toml` (shared) + per-app `pyproject.toml` (overrides)
- Enabled rules: `E`, `F`, `W`, `A`, `PL`, `I`, `SIM`, `RUF`, `ASYNC`, `C4`, `INP`, `ERA`, `SLF`, `PIE`, `PYI`, `ANN`, `N`, `D`
- Ignored rules:
  - `ANN002`, `ANN003` - no annotation required for `*args`/`**kwargs`
  - `D203` - no blank line before docstring
  - `D100`, `D101`, `D104`, `D107` - no docstrings required on modules, classes, packages, `__init__`
  - `D213` - multi-line docstring summary on first line (Google style)
  - `RUF012` - mutable class variable annotations
  - `TC001`, `TC002` - type checking imports
- Test files exempt from ALL rules (`tests/**` in per-file-ignores)

**Type Checking:**
- Tool: BasedPyright (strict mode in root config, basic in per-app)
- Test directories excluded from type checking
- Config: Root `pyproject.toml` `[tool.basedpyright]` section

## Import Organization

**Order (enforced by Ruff `I` rules):**
1. `from __future__ import annotations` (when needed for forward references)
2. Standard library imports
3. Third-party imports
4. Local application imports

**Patterns:**
- Use `from typing import TYPE_CHECKING` with `if TYPE_CHECKING:` blocks for imports only needed at type-check time
- Absolute imports within each app (e.g., `from repository.maps_repository import MapsRepository`)
- Relative imports within same package only (e.g., `from .base import BaseService`)

**Example from `apps/api/services/maps_service.py`:**
```python
from __future__ import annotations

import asyncio
import datetime as dt
import logging
from typing import TYPE_CHECKING, Any

import msgspec
from asyncpg import Pool
from genjishimada_sdk.maps import MapCreateRequest, MapResponse
from litestar.datastructures import Headers, State

from repository.exceptions import ForeignKeyViolationError, UniqueConstraintViolationError
from repository.maps_repository import MapsRepository
from services.exceptions.maps import MapCodeExistsError, MapNotFoundError

from .base import BaseService

if TYPE_CHECKING:
    from services.lootbox_service import LootboxService
    from services.newsfeed_service import NewsfeedService
```

## Docstrings

**Convention:** Google style (`[tool.ruff.lint.pydocstyle] convention = "google"`)

**Required on:**
- All public functions and methods

**NOT required on:**
- Modules (`D100` ignored)
- Classes (`D101` ignored)
- Packages (`D104` ignored)
- `__init__` methods (`D107` ignored)

**Format:**
```python
async def create_map(
    self,
    data: MapCreateRequest,
    headers: Headers,
) -> MapCreationJobResponse:
    """Create a map.

    Within a transaction, inserts the core map row and all related data
    (creators, guide, mechanics, restrictions, medals).

    Args:
        data: Map creation request.
        headers: Request headers for idempotency.

    Returns:
        Map creation response with optional job status.

    Raises:
        MapCodeExistsError: If code already exists.
        DuplicateMechanicError: If duplicate mechanic in request.
    """
```

## Type Annotations

**Requirements:**
- All function parameters must have type annotations (enforced by `ANN` rules)
- All return types must be annotated
- `*args` and `**kwargs` exempt (`ANN002`, `ANN003` ignored)

**Patterns:**
- Union types: `str | None` (Python 3.10+ syntax, never `Optional[str]`)
- Annotated parameters: `Annotated[str | None, Parameter(description="...")]` for Litestar route params
- Connection parameters: `conn: Connection | None = None` (keyword-only via `*`)
- Async iterators: `AsyncIterator[asyncpg.Connection]` for fixture return types
- `typing.Any` used sparingly with `# noqa: ANN401` suppression when needed
- `UNSET` for optional PATCH fields: `field: int | UnsetType = UNSET`

## Error Handling

**Three-tier exception hierarchy:**

```
asyncpg exceptions (database layer)
    -> repository.exceptions (RepositoryError, UniqueConstraintViolationError, etc.)
        -> services.exceptions.{domain} (DomainError subclasses)
            -> HTTPException / CustomHTTPException (controller layer)
```

**Repository Layer** (`apps/api/repository/exceptions.py`):
- `RepositoryError` base with `message` and `context` kwargs
- `UniqueConstraintViolationError` - carries `constraint_name`, `table`, `detail`
- `ForeignKeyViolationError` - carries `constraint_name`, `table`, `detail`
- `CheckConstraintViolationError` - carries `constraint_name`, `table`, `detail`
- Repositories catch `asyncpg` exceptions and re-raise with structured context

**Service Layer** (`apps/api/services/exceptions/{domain}.py`):
- Per-domain exception modules, all extend `DomainError` from `apps/api/utilities/errors.py`
- Base domain exception: `class MapsError(DomainError):`
- Specific errors: `class MapNotFoundError(MapsError):`
- Services catch repository exceptions and translate to domain exceptions

**Controller Layer** (`apps/api/routes/v3/*.py`):
- Controllers catch domain exceptions in try/except blocks
- Convert to `CustomHTTPException` with appropriate status code and detail
- Pattern:

```python
try:
    return await maps_service.create_map(data, request.headers)
except MapCodeExistsError as e:
    raise CustomHTTPException(
        detail="Provided code already exists.",
        status_code=HTTP_400_BAD_REQUEST,
    ) from e
except CreatorNotFoundError as e:
    raise CustomHTTPException(
        detail="There is no user associated with supplied ID.",
        status_code=HTTP_400_BAD_REQUEST,
    ) from e
```

**Legacy decorator** (`apps/api/utilities/errors.py`):
- `handle_db_exceptions` decorator catches asyncpg violations directly in route handlers
- Being superseded by the three-tier hierarchy above
- Still present on some older endpoints

**Key principles:**
- Always use `from e` to preserve the exception chain
- Catch specific exception types, not broad `Exception`
- Use `e.constraint_name` to determine which constraint failed
- Use `raise` to re-raise unmatched constraints
- Let unexpected errors propagate to global exception handlers

## Logging

**Setup:**
- Variable name: always `log` (never `logger`)
- Declaration: `log = getLogger(__name__)` at module level (`apps/api/app.py:45`, `apps/api/services/base.py:18`)

**Formatting:**
- Use `%s`-style formatting (not f-strings): `log.info("Processing map %s", code)`
- Use `log.exception()` for caught exceptions (auto-includes traceback)
- Use `log.debug()` for development/tracing messages

**RabbitMQ operations use emoji prefixes:**
- `[->]` or `[→]` for publishing messages
- `[x]` for failures
- `[!]` for errors/warnings
- `[✓]` for success

**Example from `apps/api/services/base.py`:**
```python
log.info("[→] Preparing to publish RabbitMQ message")
log.info("Routing key: %s", routing_key)
log.exception("[!] Failed to publish message to RabbitMQ queue '%s'", routing_key)
```

**Sentry integration:**
- API: `sentry_sdk.init()` in `apps/api/app.py`
- Bot: `sentry_sdk.init()` in `apps/bot/main.py`
- Full traces, profiling, PII enabled
- Environment-aware (`development`/`production`)

## Database Query Patterns

**Parameter style:**
- Use `$1, $2, ...` positional parameters (asyncpg style)
- Never use f-string interpolation in SQL

**Query formatting:**
- Multi-line SQL strings with triple quotes, indented for readability
- Use CTEs (`WITH ... AS`) for complex multi-step queries

**Fetch methods:**
- `fetchval()` for single scalar values (e.g., `SELECT COUNT(*)`, `RETURNING id`)
- `fetchrow()` for single rows (returns `Record` or `None`)
- `fetch()` for multiple rows (returns `list[Record]`)
- Convert records to dicts: `dict(row)` or `[dict(row) for row in rows]`

**Connection handling:**
- Repository methods accept `conn: Connection | None = None` as keyword-only param
- Use `self._get_connection(conn)` to get either the injected connection or fall back to pool
- Services acquire connections from pool for transactions:

```python
async with self._pool.acquire() as conn, conn.transaction():
    map_id = await self._maps_repo.create_core_map(map_data, conn=conn)
    await self._maps_repo.insert_creators(map_id, creators, conn=conn)
```

**Example repository method from `apps/api/repository/maps_repository.py`:**
```python
async def fetch_partial_map(
    self,
    code: str,
    *,
    conn: Connection | None = None,
) -> dict | None:
    _conn = self._get_connection(conn)
    row = await _conn.fetchrow(
        """
        SELECT m.id AS map_id, m.code, m.map_name, m.checkpoints
        FROM core.maps AS m
        WHERE m.code = $1
        """,
        code,
    )
    return dict(row) if row else None
```

## Data Serialization

**Framework:** msgspec throughout for JSON encoding/decoding

**Struct naming conventions:**
- Request models: `*Request` suffix (e.g., `MapCreateRequest`, `CompletionPatchRequest`)
- Response models: `*Response` suffix (e.g., `MapResponse`, `MapPartialResponse`)
- Event models: `*Event` suffix for RabbitMQ messages (e.g., `CompletionCreatedEvent`, `PlaytestCreatedEvent`)

**PATCH requests use UNSET pattern:**
```python
class CompletionPatchRequest(Struct):
    message_id: int | UnsetType = UNSET
    completion: bool | UnsetType = UNSET
    verification_id: int | UnsetType = UNSET
```

**Custom asyncpg type codecs** (registered in `apps/api/app.py:_async_pg_init`):
- `numeric` -> `float` (via text format)
- `jsonb` -> msgspec JSON encode/decode

**SDK location:** All shared structs in `libs/sdk/src/genjishimada_sdk/{domain}.py`

## Dependency Injection Pattern

**Provider functions:**
- Defined at bottom of repository/service files
- Pattern: `async def provide_{class_name}(state: State, ...) -> ClassName:`
- Repository providers receive `state: State`, use `state.db_pool`
- Service providers receive `state: State` + repository dependencies

**Example from `apps/api/repository/maps_repository.py`:**
```python
async def provide_maps_repository(state: State) -> MapsRepository:
    """Litestar DI provider for repository."""
    return MapsRepository(state.db_pool)
```

**Example from `apps/api/services/maps_service.py`:**
```python
async def provide_maps_service(
    state: State,
    maps_repo: MapsRepository,
) -> MapsService:
    """Litestar DI provider for service."""
    return MapsService(state.db_pool, state, maps_repo)
```

**Controller registration:**
```python
class MapsController(Controller):
    tags = ["Maps"]
    path = "/maps"
    dependencies = {
        "maps_repo": Provide(provide_maps_repository),
        "maps_service": Provide(provide_maps_service),
        "newsfeed_service": Provide(provide_newsfeed_service),
    }
```

## Route Conventions

**Controller structure:**
- Controllers extend `litestar.Controller`
- Class-level `tags`, `path`, `dependencies` attributes
- Auto-discovery in `apps/api/routes/v3/__init__.py` scans all modules for `Controller` subclasses

**Authentication & scopes:**
- Scope-based auth via `opt={"required_scopes": {"maps:read"}}` on route decorators
- Opt out of auth: `opt={"exclude_from_auth": True}`
- Superusers bypass all scope checks (enforced in `apps/api/middleware/guards.py`)

**Route decorators:**
```python
@get(
    "/",
    summary="Search Maps",
    description="Search and filter maps with comprehensive filtering options.",
    opt={"required_scopes": {"maps:read"}},
)
async def get_maps_endpoint(self, maps_service: MapsService, ...) -> list[MapResponse]:
```

**Parameters:**
- Use `Annotated[type, Parameter(description="...")]` for all query/path params
- Use `Annotated[type, Body(title="...")]` for request bodies
- Status codes: `status_code=HTTP_201_CREATED` for creation endpoints

**Route prefix:** All API routes under `/api/v3/`

## Module Design

**Exports:**
- SDK modules use `__all__` tuples to define public API
- Route handlers auto-discovered via `__init__.py` module scanning

**Barrel Files:**
- `apps/api/routes/v3/__init__.py` - auto-discovers all Controller subclasses
- `apps/api/events/__init__.py` - auto-discovers event listeners
- `libs/sdk/src/genjishimada_sdk/__init__.py` - package init

**Base Classes:**
- `BaseService` (`apps/api/services/base.py`) - pool, state, `publish_message()`
- `BaseRepository` (`apps/api/repository/base.py`) - pool, `_get_connection()`

---

*Convention analysis: 2026-05-29*
