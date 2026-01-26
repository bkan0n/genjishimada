# Controller-Service-Repository Pattern

## Overview

This document describes the three-layer architecture pattern used in v4 API routes. This pattern provides clear separation of concerns, improved testability, and consistent error handling across all domains.

## Architecture Layers

### Controller (routes-new/v4/*.py)

**Responsibility:** HTTP request/response handling

**What it does:**
- Receives HTTP requests
- Extracts and validates request parameters
- Calls service methods
- Translates domain exceptions to HTTP exceptions
- Returns HTTP responses

**What it does NOT do:**
- Business logic
- Database access
- Transaction management

**Example:**
```python
@post("/register")
async def register_endpoint(data: EmailRegisterRequest, auth_service: AuthService) -> Response:
    try:
        user, token = await auth_service.register(data)
        return Response(user, status_code=HTTP_201_CREATED)
    except EmailAlreadyExistsError as e:
        raise CustomHTTPException(detail=e.message, status_code=HTTP_400_BAD_REQUEST)
    except RateLimitExceededError as e:
        raise CustomHTTPException(detail=e.message, status_code=HTTP_429_TOO_MANY_REQUESTS)
```

### Service (services/*_service.py)

**Responsibility:** Business logic and orchestration

**What it does:**
- Implements business rules
- Validates input according to domain rules
- Orchestrates repository calls
- Manages transaction boundaries
- Translates repository exceptions to domain exceptions
- Can publish messages to RabbitMQ

**What it does NOT do:**
- Direct SQL queries (uses repository)
- HTTP-specific logic (status codes, headers)

**Example:**
```python
async def register(self, data: EmailRegisterRequest) -> tuple[AuthUserResponse, str]:
    # Validation
    self.validate_email(data.email)
    self.validate_password(data.password)

    # Check business rule
    if await self._repo.check_email_exists(data.email):
        raise EmailAlreadyExistsError(data.email)

    # Pre-compute
    password_hash = self.hash_password(data.password)
    token, token_hash = self.generate_token()

    # Transaction
    async with self._pool.acquire() as conn:
        async with conn.transaction():
            user_id = await self._repo.generate_next_user_id(conn=conn)
            await self._repo.create_core_user(user_id, data.username, conn=conn)
            await self._repo.create_email_auth(user_id, data.email, password_hash, conn=conn)

    return user, token
```

### Repository (repository/*_repository.py)

**Responsibility:** Data access

**What it does:**
- Executes SQL queries
- Accepts optional connection for transaction participation
- Catches asyncpg exceptions and raises repository exceptions
- Returns data as dicts or primitives

**What it does NOT do:**
- Business logic
- Validation
- Transaction management (participates but doesn't manage)

**Example:**
```python
async def create_email_auth(
    self,
    user_id: int,
    email: str,
    password_hash: str,
    *,
    conn: Connection | None = None,
) -> None:
    _conn = self._get_connection(conn)

    try:
        await _conn.execute(
            "INSERT INTO users.email_auth (user_id, email, password_hash) VALUES ($1, $2, $3)",
            user_id, email, password_hash
        )
    except asyncpg.UniqueViolationError as e:
        constraint = extract_constraint_name(e)
        raise UniqueConstraintViolation(constraint, "users.email_auth", str(e))
```

## Exception Flow

Exceptions flow upward through layers, being translated at each level:

```
Database Error (asyncpg)
    ↓
Repository Exception (UniqueConstraintViolation, ForeignKeyViolation)
    ↓
Domain Exception (EmailAlreadyExistsError, InvalidCredentialsError)
    ↓
HTTP Exception (CustomHTTPException with status code)
```

### Repository Exceptions (`repository/exceptions.py`)

Base: `RepositoryError`

Subtypes:
- `UniqueConstraintViolation` - Unique constraint violated
- `ForeignKeyViolation` - Foreign key constraint violated
- `CheckConstraintViolation` - Check constraint violated

### Domain Exceptions (`services/exceptions/<domain>.py`)

Base: `DomainError` (from `utilities/exceptions.py`)

Domain-specific bases (e.g., `AuthError`, `MapError`)

Domain-specific errors (e.g., `EmailAlreadyExistsError`, `MapNotFoundError`)

### HTTP Exceptions

`CustomHTTPException` with appropriate status code

## Dependency Injection

DI flows: `State → Repository → Service → Controller`

**Provider functions:**
```python
# Repository
async def provide_auth_repository(state: State) -> AuthRepository:
    return AuthRepository(state.db_pool)

# Service
async def provide_auth_service(state: State, auth_repo: AuthRepository) -> AuthService:
    return AuthService(state.db_pool, state, auth_repo)
```

**Router configuration:**
```python
router = Router(
    path="/v4/auth",
    route_handlers=[...],
    dependencies={
        "auth_repo": Provide(provide_auth_repository),
        "auth_service": Provide(provide_auth_service),
    },
)
```

## Transaction Management

Services manage transactions. Repositories participate via optional `conn` parameter.

**Pattern:**
```python
# In service
async with self._pool.acquire() as conn:
    async with conn.transaction():
        await self._repo.method1(param1, conn=conn)
        await self._repo.method2(param2, conn=conn)
        # If any repo method raises, transaction rolls back
```

## Base Classes

### BaseRepository

```python
class BaseRepository:
    def __init__(self, pool: Pool) -> None:
        self._pool = pool

    def _get_connection(self, conn: Connection | None = None) -> Connection | Pool:
        return conn or self._pool
```

### BaseService

```python
class BaseService:
    def __init__(self, pool: Pool, state: State) -> None:
        self._pool = pool
        self._state = state

    async def publish_message(self, routing_key: str, data: msgspec.Struct, ...) -> JobStatusResponse:
        # RabbitMQ publishing logic
```

## Migrating a New Domain

### 1. Create Domain Exceptions

`services/exceptions/<domain>.py`:
```python
from utilities.exceptions import DomainError

class MapError(DomainError):
    """Base for map domain errors."""

class MapNotFoundError(MapError):
    def __init__(self, map_id: int):
        super().__init__("Map not found.", map_id=map_id)
```

### 2. Create Repository

`repository/<domain>_repository.py`:
```python
from .base import BaseRepository
from .exceptions import UniqueConstraintViolation, extract_constraint_name

class MapRepository(BaseRepository):
    async def get_map_by_id(self, map_id: int, *, conn: Connection | None = None) -> dict | None:
        _conn = self._get_connection(conn)
        row = await _conn.fetchrow("SELECT * FROM maps.maps WHERE id = $1", map_id)
        return dict(row) if row else None
```

### 3. Create Service

`services/<domain>_service.py`:
```python
from .base import BaseService
from repository.<domain>_repository import MapRepository
from .exceptions.<domain> import MapNotFoundError

class MapService(BaseService):
    def __init__(self, pool: Pool, state: State, map_repo: MapRepository):
        super().__init__(pool, state)
        self._map_repo = map_repo

    async def get_map(self, map_id: int) -> MapResponse:
        map_data = await self._map_repo.get_map_by_id(map_id)
        if not map_data:
            raise MapNotFoundError(map_id)
        return MapResponse(**map_data)
```

### 4. Create Routes

`routes-new/v4/<domain>.py`:
```python
from litestar import Router, get
from services.<domain>_service import MapService
from services.exceptions.<domain> import MapNotFoundError

@get("/{map_id:int}")
async def get_map_endpoint(map_id: int, map_service: MapService) -> Response:
    try:
        map_data = await map_service.get_map(map_id)
        return Response(map_data, status_code=HTTP_200_OK)
    except MapNotFoundError as e:
        raise CustomHTTPException(detail=e.message, status_code=HTTP_404_NOT_FOUND)

router = Router(
    path="/v4/maps",
    route_handlers=[get_map_endpoint],
    dependencies={
        "map_repo": Provide(provide_map_repository),
        "map_service": Provide(provide_map_service),
    },
)
```

### 5. Register Routes

In `app.py`, v4 routes are auto-discovered via `routes_new.v4.__init__.py`.

## Testing Strategy

**Test Location:** All v4 tests live in `apps/api/tests-v4/` (separate from v3 tests in `apps/api/tests/`)

**Running Tests:**
- `just test-api` - Runs v3 tests only (apps/api/tests/)
- `just test-api-v4` - Runs v4 tests only (apps/api/tests-v4/)

### Repository Tests (`tests-v4/repository/`)

Test data access with real database:
```python
async def test_create_email_auth(auth_repo):
    user_id = await auth_repo.generate_next_user_id()
    await auth_repo.create_core_user(user_id, "testuser")
    await auth_repo.create_email_auth(user_id, "test@test.com", "hash")

    # Verify in database
    async with auth_repo._pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM users.email_auth WHERE user_id = $1", user_id)
        assert row is not None
```

### Service Tests (`tests-v4/services/`)

Mock repository, test business logic:
```python
@pytest.mark.asyncio
async def test_register_validates_email(auth_service, mock_repo):
    mock_repo.check_email_exists = AsyncMock(return_value=False)

    with pytest.raises(EmailValidationError):
        await auth_service.register(EmailRegisterRequest(
            email="invalid",
            password="ValidPass1!",
            username="test"
        ))

    mock_repo.check_email_exists.assert_not_called()
```

### Route Tests (`tests-v4/routes/`)

Test HTTP layer with real service (integration tests):
```python
@pytest.mark.asyncio
async def test_register_endpoint_returns_201(test_client):
    response = await test_client.post("/v4/auth/register", json={
        "email": "test@test.com",
        "username": "testuser",
        "password": "Test123!@#"
    })
    assert response.status_code == 201
```

## Hybrid Domain Example: Change Requests

The change_requests domain demonstrates a simple write-enabled domain:

**Characteristics:**
- Mix of reads and writes
- NO validation (data pre-validated by bot)
- NO events (notifications handled externally)
- NO transactions (single-table operations)
- Light business logic (permission check with string comparison)

**Code Metrics:**
- Repository: ~150 lines (6 methods)
- Service: ~100 lines (6 methods, 1 with logic)
- Controller: ~120 lines (6 endpoints)
- Tests: ~300 lines total

**Business Logic Example:**
```python
# Service handles permission check logic
async def check_permission(self, thread_id: int, user_id: int, code: str) -> bool:
    creator_mentions = await self._repo.fetch_creator_mentions(thread_id, code)
    if not creator_mentions:
        return False
    return str(user_id) in creator_mentions  # String comparison
```

**Write Pattern:**
```python
# Repository raises FK violations
async def create_request(...) -> None:
    try:
        await _conn.execute(query, ...)
    except asyncpg.ForeignKeyViolationError as e:
        raise ForeignKeyViolationError(...)

# Service passes through (no translation needed, internal API)
async def create_request(self, data: Request) -> None:
    await self._repo.create_request(...)

# Controller returns None with 201 status
async def create_endpoint(self, data: Request, service: Service) -> Response[None]:
    await service.create_request(data)
    return Response(None, status_code=HTTP_201_CREATED)
```

**Migration effort:** ~2 hours for 6 endpoints

## Read-Only Domain Example: Community

The community domain demonstrates the simplest v4 pattern:

**Characteristics:**
- No validation (query parameters only)
- No events (no async operations)
- No transactions (single queries)
- Service is pure pass-through with SDK conversion

**Code Metrics:**
- Repository: 759 lines (12 methods, all SQL)
- Service: 150 lines (12 pass-through methods)
- Controller: 248 lines (12 endpoint methods)
- Tests: ~200 lines total

**Pattern:**

```python
# Repository: Return dicts
async def fetch_something(self, *, conn: Connection | None = None) -> list[dict]:
    _conn = self._get_connection(conn)
    rows = await _conn.fetch(query)
    return [dict(row) for row in rows]

# Service: Convert to SDK
async def get_something(self) -> list[SomeResponse]:
    rows = await self._repo.fetch_something()
    return msgspec.convert(rows, list[SomeResponse])

# Controller: Pass through
async def get_something_endpoint(self, service: Service) -> list[SomeResponse]:
    return await service.get_something()
```

**Testing:**
- Repository tests use real database (verify SQL)
- Service tests use mocks (verify conversion)
- Route tests use real database (integration)

**Migration effort:** ~4 hours for 12 endpoints

## Key Principles

- **DRY**: Share patterns across domains
- **YAGNI**: Don't add features until needed
- **Explicit over implicit**: Clear error handling, no magic
- **Testability**: Each layer independently testable
- **Consistency**: Same user-facing errors as v3

## Constraint Error Mappings

Keep constraint mappings in services for reference:

```python
UNIQUE_CONSTRAINT_MESSAGES = {
    "email_auth_email_key": "An account with this email already exists.",
}

FK_CONSTRAINT_MESSAGES = {
    "sessions_user_id_fkey": "User does not exist.",
}
```

These ensure v4 returns same error messages as v3.
