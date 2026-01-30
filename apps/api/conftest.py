"""Pytest configuration for v4 tests."""

import glob
import os
from typing import Any, AsyncIterator, Generator
from uuid import uuid4

import asyncpg
import pytest
from faker import Faker
from litestar import Litestar
from litestar.testing import AsyncTestClient
from pytest_databases.docker.postgres import PostgresService

from app import create_app

pytest_plugins = [
    "pytest_databases.docker.postgres",
]

fake = Faker()


# ==============================================================================
# PYTEST CONFIGURATION
# ==============================================================================


def pytest_configure(config: Any) -> None:
    """Register custom markers for test organization."""
    # Domain markers
    config.addinivalue_line("markers", "domain_maps: Tests for maps domain")
    config.addinivalue_line("markers", "domain_users: Tests for users domain")
    config.addinivalue_line("markers", "domain_completions: Tests for completions domain")
    config.addinivalue_line("markers", "domain_playtests: Tests for playtests domain")
    config.addinivalue_line("markers", "domain_notifications: Tests for notifications domain")
    config.addinivalue_line("markers", "domain_auth: Tests for auth domain")
    config.addinivalue_line("markers", "domain_community: Tests for community domain")
    config.addinivalue_line("markers", "domain_lootbox: Tests for lootbox domain")
    config.addinivalue_line("markers", "domain_rank_card: Tests for rank_card domain")


MIGRATIONS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "migrations"))

SEEDS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "seeds"))


def _apply_sql_dir(conn: Any, directory: str) -> None:
    """Apply all SQL files from a directory in sorted order."""
    for path in sorted(glob.glob(os.path.join(directory, "*.sql"))):
        with open(path, "r", encoding="utf-8") as f:
            sql_text = f.read()
        try:
            conn.execute(sql_text, prepare=False)
        except Exception as exc:
            raise RuntimeError(f"Failed applying SQL file: {path}") from exc
        conn.commit()


@pytest.fixture(scope="session", autouse=True)
def setup_test_db(postgres_connection: Any) -> Generator[None, Any, None]:
    """Set up test database with migrations and seed data."""
    _apply_sql_dir(postgres_connection, MIGRATIONS_DIR)
    _apply_sql_dir(postgres_connection, SEEDS_DIR)
    yield


@pytest.fixture(scope="function", autouse=False)
async def asyncpg_conn(postgres_service: PostgresService) -> AsyncIterator[asyncpg.Connection]:
    """Provide an asyncpg connection to the test database."""
    conn = await asyncpg.connect(
        user=postgres_service.user,
        password=postgres_service.password,
        host=postgres_service.host,
        port=postgres_service.port,
        database=postgres_service.database,
    )
    yield conn
    await conn.close()


@pytest.fixture
async def test_client(postgres_service: PostgresService) -> AsyncIterator[AsyncTestClient[Litestar]]:
    """Create async test client with database connection and required headers."""
    app = create_app(
        psql_dsn=f"postgresql://{postgres_service.user}:{postgres_service.password}@{postgres_service.host}:{postgres_service.port}/{postgres_service.database}"
    )
    async with AsyncTestClient(app=app) as client:
        client.headers.update(
            {
                "x-pytest-enabled": "1",
                "X-API-KEY": "testing",
            },
        )
        yield client


# ==============================================================================
# GLOBAL TRACKING FIXTURES
# ==============================================================================


@pytest.fixture(scope="session")
def global_code_tracker() -> set[str]:
    """Session-wide tracker for all used map codes.

    Prevents collisions across all tests in the session.
    """
    return set()


@pytest.fixture(scope="session")
def global_user_id_tracker() -> set[int]:
    """Session-wide tracker for all used user IDs.

    Prevents collisions across all tests in the session.
    """
    return set()


@pytest.fixture(scope="session")
def global_thread_id_tracker() -> set[int]:
    """Session-wide tracker for all used thread IDs.

    Prevents collisions across all tests in the session.
    """
    return set()


# ==============================================================================
# CODE GENERATION FIXTURES
# ==============================================================================


@pytest.fixture
def unique_map_code(global_code_tracker: set[str]) -> str:
    """Generate a unique map code guaranteed not to collide.

    Uses UUID-based generation for guaranteed uniqueness across
    parallel test execution and multiple test runs.

    Format: T{5 uppercase hex chars} (e.g., "TF3A2B")
    """
    code = f"T{uuid4().hex[:5].upper()}"
    global_code_tracker.add(code)
    return code


@pytest.fixture
def unique_user_id(global_user_id_tracker: set[int]) -> int:
    """Generate a unique Discord user ID.

    Discord user IDs are 18-digit integers (snowflakes).
    We generate random IDs in the valid range and track them.
    """
    while True:
        user_id = fake.random_int(min=100000000000000000, max=999999999999999999)
        if user_id not in global_user_id_tracker:
            global_user_id_tracker.add(user_id)
            return user_id


@pytest.fixture
def unique_thread_id(global_thread_id_tracker: set[int]) -> int:
    """Generate a unique Discord thread ID.

    Thread IDs are 18-digit integers (snowflakes), same as user IDs.
    We generate random IDs in the valid range and track them.
    """
    while True:
        thread_id = fake.random_int(min=100000000000000000, max=999999999999999999)
        if thread_id not in global_thread_id_tracker:
            global_thread_id_tracker.add(thread_id)
            return thread_id


# ==============================================================================
# HELPER FACTORY FIXTURES
# ==============================================================================


@pytest.fixture
async def create_test_map(postgres_service: PostgresService, global_code_tracker: set[str]):
    """Factory fixture for creating test maps.

    Returns a function that creates a map with the given code.

    Usage:
        map_id = await create_test_map(unique_map_code)
        map_id = await create_test_map(unique_map_code, checkpoints=25)
    """

    async def _create(code: str | None = None, **overrides: Any) -> int:
        from typing import get_args

        from genjishimada_sdk.maps import MapCategory, OverwatchMap

        # Generate code if not provided
        if code is None:
            code = f"T{uuid4().hex[:5].upper()}"
            global_code_tracker.add(code)

        # Default values
        data = {
            "map_name": fake.random_element(elements=get_args(OverwatchMap)),
            "category": fake.random_element(elements=get_args(MapCategory)),
            "checkpoints": fake.random_int(min=1, max=50),
            "official": True,
            "playtesting": "Approved",
            "difficulty": "Medium",
            "raw_difficulty": 5.0,
        }

        # Apply overrides
        data.update(overrides)

        pool = await asyncpg.create_pool(
            user=postgres_service.user,
            password=postgres_service.password,
            host=postgres_service.host,
            port=postgres_service.port,
            database=postgres_service.database,
        )
        try:
            async with pool.acquire() as conn:
                map_id = await conn.fetchval(
                    """
                    INSERT INTO core.maps (
                        code, map_name, category, checkpoints, official,
                        playtesting, difficulty, raw_difficulty
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    RETURNING id
                    """,
                    code,
                    data["map_name"],
                    data["category"],
                    data["checkpoints"],
                    data["official"],
                    data["playtesting"],
                    data["difficulty"],
                    data["raw_difficulty"],
                )
            return map_id
        finally:
            await pool.close()

    return _create


@pytest.fixture
async def create_test_user(postgres_service: PostgresService, global_user_id_tracker: set[int]):
    """Factory fixture for creating test users.

    Returns a function that creates a user with optional nickname.

    Usage:
        user_id = await create_test_user()
        user_id = await create_test_user(nickname="TestUser")
    """

    async def _create(nickname: str | None = None) -> int:
        if nickname is None:
            nickname = fake.user_name()

        # Generate unique user ID
        while True:
            user_id = fake.random_int(min=100000000000000000, max=999999999999999999)
            if user_id not in global_user_id_tracker:
                global_user_id_tracker.add(user_id)
                break

        pool = await asyncpg.create_pool(
            user=postgres_service.user,
            password=postgres_service.password,
            host=postgres_service.host,
            port=postgres_service.port,
            database=postgres_service.database,
        )
        try:
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO core.users (id, nickname, global_name)
                    VALUES ($1, $2, $3)
                    """,
                    user_id,
                    nickname,
                    nickname,
                )
            return user_id
        finally:
            await pool.close()

    return _create


@pytest.fixture
async def create_test_playtest(postgres_service: PostgresService, global_thread_id_tracker: set[int]):
    """Factory fixture for creating test playtest metadata.

    Returns a function that creates a playtest with the given map_id and optional thread_id.

    Usage:
        playtest_id = await create_test_playtest(map_id)
        playtest_id = await create_test_playtest(map_id, thread_id=unique_thread_id)
    """

    async def _create(map_id: int, thread_id: int | None = None, **overrides: Any) -> int:
        # Generate thread_id if not provided
        if thread_id is None:
            while True:
                thread_id = fake.random_int(min=100000000000000000, max=999999999999999999)
                if thread_id not in global_thread_id_tracker:
                    global_thread_id_tracker.add(thread_id)
                    break

        # Default values
        data = {
            "verification_id": None,
            "initial_difficulty": 5.0,  # Default mid-range difficulty
            "completed": False,
        }

        # Apply overrides
        data.update(overrides)

        pool = await asyncpg.create_pool(
            user=postgres_service.user,
            password=postgres_service.password,
            host=postgres_service.host,
            port=postgres_service.port,
            database=postgres_service.database,
        )
        try:
            async with pool.acquire() as conn:
                playtest_id = await conn.fetchval(
                    """
                    INSERT INTO playtests.meta (
                        thread_id, map_id, verification_id, initial_difficulty, completed
                    )
                    VALUES ($1, $2, $3, $4, $5)
                    RETURNING id
                    """,
                    thread_id,
                    map_id,
                    data["verification_id"],
                    data["initial_difficulty"],
                    data["completed"],
                )
            return playtest_id
        finally:
            await pool.close()

    return _create


@pytest.fixture
async def create_test_edit_request(postgres_service: PostgresService):
    """Factory fixture for creating test edit requests.

    Returns a function that creates an edit request with the given parameters.

    Usage:
        edit_id = await create_test_edit_request(map_id, code, created_by)
        edit_id = await create_test_edit_request(map_id, code, created_by, reason="Custom reason")
    """

    async def _create(
        map_id: int,
        code: str,
        created_by: int,
        **overrides: Any,
    ) -> int:
        # Default values
        data = {
            "proposed_changes": {"difficulty": "Hard", "checkpoints": 10},
            "reason": fake.sentence(nb_words=10),
        }

        # Apply overrides
        data.update(overrides)

        pool = await asyncpg.create_pool(
            user=postgres_service.user,
            password=postgres_service.password,
            host=postgres_service.host,
            port=postgres_service.port,
            database=postgres_service.database,
        )
        try:
            async with pool.acquire() as conn:
                import msgspec

                edit_id = await conn.fetchval(
                    """
                    INSERT INTO maps.edit_requests (
                        map_id, code, proposed_changes, reason, created_by
                    )
                    VALUES ($1, $2, $3::jsonb, $4, $5)
                    RETURNING id
                    """,
                    map_id,
                    code,
                    msgspec.json.encode(data["proposed_changes"]).decode(),
                    data["reason"],
                    created_by,
                )
            return edit_id
        finally:
            await pool.close()

    return _create
