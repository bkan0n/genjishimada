# Testing Patterns

**Analysis Date:** 2026-05-29

## Overview

The API test suite contains ~1,373 individual test functions across 91 test files (~35,800 lines total), organized into three tiers: repository tests (data access), service tests (business logic), and integration tests (full HTTP stack). Tests use pytest with async support, parallel execution, Docker-managed PostgreSQL, and smart test selection via testmon.

## Test Framework

**Runner:**
- pytest `>=8.3.5`
- Config: `apps/api/pyproject.toml` `[tool.pytest.ini_options]`

**Plugins:**
- `pytest-asyncio >=1.2.0` - Async test support, mode: `auto` (all async tests auto-discovered)
- `pytest-xdist >=3.8.0` - Parallel execution (4 workers locally, `auto` in CI)
- `pytest-databases[postgres] >=0.14.0` - Docker PostgreSQL fixtures
- `pytest-testmon >=2.1.0` - Smart test selection (only re-runs affected tests)
- `pytest-mock >=3.15.1` - `mocker` fixture for mocking

**Assertion Library:** Built-in `assert` statements (no external assertion library)

**Run Commands:**
```bash
just test-api              # Run with 4 workers + testmon (default)
just test-api-all          # Full suite, bypassing testmon
just test-api-v3           # Only tests/ directory

# Targeted test run (disable parallel for debugging):
uv run --directory apps/api pytest tests/path/to/test.py -v -p no:xdist

# CI command (in .github/workflows/tests.yml):
uv run --project apps/api --group dev-api pytest --testmon -n auto apps/api
```

**Configuration in `apps/api/pyproject.toml`:**
```toml
[tool.pytest.ini_options]
addopts = "--testmon"
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
markers = [
    "integration: Integration tests with real database and HTTP layer",
    "domain_auth: Auth domain tests",
    "domain_maps: Maps domain tests",
    # ... 15+ domain markers
]
```

## Test File Organization

**Location:** `apps/api/tests/` - all tests co-located under the API app

**Directory structure:**
```
apps/api/tests/
├── conftest.py                          # Root fixtures: DB setup, factories, test client
├── test_conftest.py                     # Smoke tests for fixture health
├── di/                                  # (legacy, appears empty)
├── integration/
│   ├── conftest.py                      # Integration-specific fixtures (auth headers, unauthenticated client)
│   ├── services/
│   │   └── test_store_service_quests.py
│   ├── test_auth_integration.py
│   ├── test_maps_integration.py
│   ├── test_completions_integration.py
│   ├── test_content_integration.py
│   └── ... (20+ domain integration files)
├── repository/
│   ├── auth/
│   │   ├── conftest.py
│   │   ├── test_auth_repository_sessions.py
│   │   └── test_auth_repository_*.py   # 6 files
│   ├── maps/
│   │   ├── conftest.py
│   │   ├── test_maps_repository_fetch_maps.py
│   │   └── test_maps_repository_*.py   # 17 files
│   ├── users/
│   │   └── test_users_repository_*.py  # 5 files
│   └── ... (10+ domain subdirectories)
├── services/
│   ├── conftest.py                      # Mock fixtures for all repositories/services
│   ├── tags/
│   │   └── test_tags_service_mutate.py
│   ├── test_maps_service.py
│   ├── test_completions_service.py
│   └── ... (12+ service test files)
├── routes/
│   └── tags/
│       └── test_tags_routes.py
└── utilities/
    └── test_map_search_builder.py
```

**Naming:**
- Test files: `test_{domain}_{layer}_{focus}.py` or `test_{domain}_{purpose}.py`
- Repository tests: `test_{domain}_repository_{operation}.py` (e.g., `test_maps_repository_fetch_maps.py`)
- Service tests: `test_{domain}_service.py`
- Integration tests: `test_{domain}_integration.py`

## Test Structure

**Marker usage:**
Every test file starts with `pytestmark` to assign domain and layer markers:
```python
pytestmark = [
    pytest.mark.integration,
    pytest.mark.domain_maps,
]
```

**Class-based organization:**
Tests are grouped by endpoint or behavior using classes (no `TestCase` base):
```python
class TestSearchMaps:
    """GET /api/v3/maps/"""

    async def test_happy_path(self, test_client):
        """Search maps returns list with valid structure."""
        response = await test_client.get("/api/v3/maps/")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    async def test_requires_auth(self, unauthenticated_client):
        """Search maps without auth returns 401."""
        response = await unauthenticated_client.get("/api/v3/maps/")
        assert response.status_code == 401
```

**Parametrized tests:**
```python
@pytest.mark.parametrize("page_size", [10, 20, 25, 50])
@pytest.mark.parametrize("page_number", [1, 2])
async def test_pagination_variants(self, test_client, page_size, page_number):
    """Pagination parameters work without 500s."""
    response = await test_client.get(
        "/api/v3/maps/",
        params={"page_size": page_size, "page_number": page_number},
    )
    assert response.status_code == 200
```

## Database Fixtures

**PostgreSQL provisioning:**
- `pytest-databases` manages Docker PostgreSQL containers automatically
- Plugin registered via `pytest_plugins = ["pytest_databases.docker.postgres"]` in root `conftest.py`
- Provides `postgres_service: PostgresService` and `postgres_connection` fixtures

**Session-scoped DB setup** (runs once per test session):
```python
@pytest.fixture(scope="session", autouse=True)
def setup_test_db(postgres_connection: Any) -> Generator[None, Any, None]:
    """Set up test database with migrations and seed data."""
    _apply_sql_dir(postgres_connection, MIGRATIONS_DIR)
    _apply_sql_dir(postgres_connection, SEEDS_DIR)
    yield
```

Migrations from `apps/api/migrations/*.sql` and seeds from `apps/api/seeds/0001-init_seed.sql` are applied once per session.

**Function-scoped connection fixtures:**
```python
@pytest.fixture(scope="function", autouse=False)
async def asyncpg_conn(postgres_service: PostgresService) -> AsyncIterator[asyncpg.Connection]:
    """Provide an asyncpg connection to the test database."""
    conn = await asyncpg.connect(...)
    await _async_pg_init(conn)  # Register custom type codecs
    yield conn
    await conn.close()

@pytest.fixture(scope="function")
async def asyncpg_pool(postgres_service: PostgresService) -> AsyncIterator[asyncpg.Pool]:
    """Shared asyncpg pool for factory fixtures within a single test."""
    pool = await asyncpg.create_pool(..., min_size=1, max_size=3, init=_async_pg_init)
    yield pool
    await pool.close()
```

## Test Client

**Authenticated test client** (from root `conftest.py`):
```python
@pytest.fixture
async def test_client(postgres_service: PostgresService) -> AsyncIterator[AsyncTestClient[Litestar]]:
    """Create async test client with database connection and required headers."""
    app = create_app(psql_dsn=f"postgresql://...")
    async with AsyncTestClient(app=app) as client:
        client.headers.update({
            "x-pytest-enabled": "1",    # Skip queue publishing
            "X-API-KEY": "testing",     # Auth header
        })
        yield client
```

**Unauthenticated client** (from `apps/api/tests/integration/conftest.py`):
```python
@pytest.fixture
async def unauthenticated_client(postgres_service: PostgresService) -> AsyncIterator[AsyncTestClient[Litestar]]:
    """Create async test client WITHOUT authentication headers."""
    app = create_app(psql_dsn=f"postgresql://...")
    async with AsyncTestClient(app=app) as client:
        client.headers.update({"x-pytest-enabled": "1"})  # Only pytest header, NO X-API-KEY
        yield client
```

## Queue Publishing Skip

The `X-PYTEST-ENABLED` header prevents RabbitMQ message publishing during tests. In `apps/api/services/base.py`:
```python
if headers.get("X-PYTEST-ENABLED") == "1":
    log.debug("Pytest in progress, skipping queue.")
    return JobStatusResponse(uuid4(), "succeeded")
```

The `test_client` fixture automatically sets this header. All integration tests go through the full HTTP stack but skip the async message queue side-effects.

## Unique Value Generation (Collision Prevention)

Tests run in parallel (pytest-xdist), so unique values are critical. Session-scoped tracker sets prevent collisions:

**Global trackers** (root `conftest.py`):
```python
@pytest.fixture(scope="session")
def global_code_tracker() -> set[str]:
    """Session-wide tracker for all used map codes."""
    return set()

@pytest.fixture(scope="session")
def global_user_id_tracker() -> set[int]:
    """Session-wide tracker for all used user IDs."""
    return set()
```

**Unique value fixtures:**
```python
@pytest.fixture
def unique_map_code(global_code_tracker: set[str]) -> str:
    """Format: T{5 uppercase hex chars} (e.g., 'TF3A2B')"""
    code = f"T{uuid4().hex[:5].upper()}"
    global_code_tracker.add(code)
    return code

@pytest.fixture
def unique_user_id(global_user_id_tracker: set[int]) -> int:
    """Discord user IDs are 18-digit snowflakes."""
    while True:
        user_id = fake.random_int(min=100000000000000000, max=999999999999999999)
        if user_id not in global_user_id_tracker:
            global_user_id_tracker.add(user_id)
            return user_id
```

Available unique fixtures: `unique_map_code`, `unique_user_id`, `unique_thread_id`, `unique_message_id`, `unique_email`, `unique_session_id`, `unique_token_hash`, `unique_job_id`, `unique_idempotency_key`, `unique_ip_hash`.

## Factory Fixtures

Factory fixtures create test data in the database. They return async callables with sensible defaults and `**overrides`:

**Pattern from `apps/api/tests/conftest.py`:**
```python
@pytest.fixture
async def create_test_map(
    asyncpg_pool: asyncpg.Pool,
    global_code_tracker: set[str],
    global_user_id_tracker: set[int],
):
    """Factory fixture for creating complete test maps."""

    async def _create(
        code: str | None = None,
        creator_id: int | None = None,
        mechanics: list[int] | None = None,
        **overrides: Any,
    ) -> int:
        if code is None:
            code = f"T{uuid4().hex[:5].upper()}"
            global_code_tracker.add(code)

        data = {
            "map_name": "Hanamura",
            "category": "Classic",
            "checkpoints": fake.random_int(min=1, max=50),
            "difficulty": "Medium",
            # ... more defaults
        }
        data.update(overrides)

        async with asyncpg_pool.acquire() as conn:
            map_id = await conn.fetchval("""INSERT INTO core.maps ...""", ...)
        return map_id

    return _create
```

**Available factory fixtures:**
- `create_test_map` - creates map + primary creator + optional mechanics/restrictions/tags/medals
- `create_test_user` - creates `core.users` row
- `create_test_playtest` - creates `playtests.meta` row
- `create_test_completion` - creates `core.completions` row
- `create_test_vote` - creates `playtests.votes` row
- `create_test_email_user` - creates user + email_auth row
- `create_test_session` - creates `users.sessions` row
- `create_test_change_request` - creates change request row
- `create_test_edit_request` - creates `maps.edit_requests` row (domain-specific conftest)
- `create_test_job` - creates `public.jobs` row
- `create_test_claim` - creates `public.processed_messages` row
- `create_test_newsfeed_event` - creates `public.newsfeed` row
- `create_test_notification_event` - creates `notifications.events` row
- `grant_user_coins` - updates coin balance

## Mocking

**Framework:** pytest-mock (`mocker` fixture)

**Service unit tests use `AsyncMock(spec=...)` for all dependencies.** Shared fixtures in `apps/api/tests/services/conftest.py`:

```python
@pytest.fixture
def mock_pool(mocker):
    """Mock AsyncPG pool with acquire() context manager."""
    pool = mocker.MagicMock(spec=Pool)
    conn = mocker.MagicMock()
    # Configure async context managers for pool.acquire() and conn.transaction()
    ...
    return pool

@pytest.fixture
def mock_state(mocker):
    """Mock Litestar State with mq_channel_pool."""
    state = mocker.Mock(spec=State)
    # Configure channel pool mock
    ...
    return state

@pytest.fixture
def mock_maps_repo(mocker):
    """Mock MapsRepository."""
    return mocker.AsyncMock(spec=MapsRepository)
```

**Service test pattern:**
```python
class TestMapsServiceErrorTranslation:
    """Test repository exception translation to domain exceptions."""

    async def test_create_map_duplicate_code_constraint(
        self, mock_pool, mock_state, mock_maps_repo, mocker
    ):
        service = MapsService(mock_pool, mock_state, mock_maps_repo)

        data = MapCreateRequest(code="ABCDE", ...)

        # Mock repository to raise constraint violation
        mock_maps_repo.create_core_map.side_effect = UniqueConstraintViolationError(
            "maps_code_key", "maps"
        )

        with pytest.raises(MapCodeExistsError) as exc_info:
            await service.create_map(data, Headers(), mocker.AsyncMock(), mocker.AsyncMock())

        assert exc_info.value.context["code"] == "ABCDE"
```

**What to mock:**
- Repository dependencies in service tests
- External services (RabbitMQ, image storage)
- Other services when testing service-to-service interactions

**What NOT to mock:**
- Database in repository tests (use real PostgreSQL via pytest-databases)
- Database in integration tests (full stack through real DB)
- The test client HTTP layer

**Service tests skip DB setup** via override in `apps/api/tests/services/conftest.py`:
```python
@pytest.fixture(scope="session", autouse=True)
def setup_test_db() -> None:
    """Skip database setup for service unit tests."""
    return None
```

## Test Types

**Repository Tests** (`apps/api/tests/repository/`):
- Test raw SQL queries against real PostgreSQL
- Use `asyncpg_conn` or `asyncpg_pool` + `MapsRepository(pool)` directly
- Verify query correctness, filters, pagination, constraint handling
- Some have domain-specific conftest with local factory helpers

**Service Tests** (`apps/api/tests/services/`):
- Test business logic in isolation with mocked repositories
- Focus on exception translation (repository errors -> domain errors)
- Verify validation logic, PATCH dict building, business rules
- Do NOT require database

**Integration Tests** (`apps/api/tests/integration/`):
- Test full HTTP request/response through `AsyncTestClient`
- Verify serialization, error status codes, auth enforcement
- Use factory fixtures to create test data, then call endpoints
- Include auth tests (`test_requires_auth`, unauthenticated client)

**Utility Tests** (`apps/api/tests/utilities/`):
- Test standalone utility classes (e.g., SQL search builder)

## Common Patterns

**Happy path + auth test for every endpoint:**
```python
class TestGetPartialMap:
    async def test_happy_path(self, test_client, create_test_map, unique_map_code):
        code = unique_map_code
        await create_test_map(code=code)
        response = await test_client.get(f"/api/v3/maps/{code}/partial")
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == code

    async def test_requires_auth(self, unauthenticated_client):
        response = await unauthenticated_client.get("/api/v3/maps/AAAAA/partial")
        assert response.status_code == 401
```

**Error path testing (service layer):**
```python
async def test_create_map_creator_not_found(self, mock_pool, mock_state, mock_maps_repo, mocker):
    service = MapsService(mock_pool, mock_state, mock_maps_repo)
    mock_maps_repo.create_core_map.return_value = 1
    mock_maps_repo.insert_creators.side_effect = ForeignKeyViolationError(
        "creators_user_id_fkey", "creators"
    )
    with pytest.raises(CreatorNotFoundError):
        await service.create_map(data, Headers(), mocker.AsyncMock(), mocker.AsyncMock())
```

**Response structure validation (integration):**
```python
async def test_happy_path(self, test_client):
    response = await test_client.get("/api/v3/maps/")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    for map_obj in data:
        assert "id" in map_obj
        assert "code" in map_obj
        assert "map_name" in map_obj
        assert isinstance(map_obj["checkpoints"], int)
```

## CI Pipeline

**GitHub Actions** (`.github/workflows/tests.yml`):
- Runs on PRs to `main`/`dev` and pushes to `main`/`dev`
- Uses `astral-sh/setup-uv@v5` for Python 3.13 + uv
- Testmon cache saved/restored per branch for incremental test selection
- Command: `uv run --project apps/api --group dev-api pytest --testmon -n auto apps/api`
- Workers: `auto` in CI (scales to available cores), `4` locally

## Coverage

**Requirements:** No coverage threshold enforced
**Coverage tool:** Not configured (no pytest-cov in dependencies)
**Smart selection:** testmon tracks which tests are affected by code changes and skips unaffected tests

## Test Coverage Gaps

**Bot tests:** No test files exist under `apps/bot/tests/`. The bot is untested.
**SDK tests:** No test files exist for `libs/sdk/`. SDK structs rely on type checking only.
**E2E tests:** No end-to-end tests that exercise the full API-to-bot flow via RabbitMQ.
**Coverage reporting:** No pytest-cov configured; actual line coverage is unknown.
**Pre-existing failure:** `test_difficulty_exact_filter` fails due to `Hard +` vs `Hard` mismatch (known, not a regression).

## Fixtures and Factories Summary

**Location hierarchy:**
- `apps/api/conftest.py` - Root: DB setup, global trackers, unique fixtures, shared factory fixtures
- `apps/api/tests/conftest.py` - Additional shared fixtures (mirrors root with newer pool-based factories)
- `apps/api/tests/integration/conftest.py` - Auth header fixtures, unauthenticated client
- `apps/api/tests/services/conftest.py` - Mock pool/state/repository/service fixtures
- `apps/api/tests/repository/{domain}/conftest.py` - Domain-specific factory fixtures

**Two conftest generations:**
There are two root conftest files: `apps/api/conftest.py` (older, creates individual pools per factory call) and `apps/api/tests/conftest.py` (newer, uses shared `asyncpg_pool` fixture). The newer conftest is more efficient. New tests should follow the pattern in `apps/api/tests/conftest.py`.

---

*Testing analysis: 2026-05-29*
