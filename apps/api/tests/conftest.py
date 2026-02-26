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

from app import _async_pg_init, create_app
from genjishimada_sdk import difficulties

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
    config.addinivalue_line("markers", "domain_autocomplete: Tests for autocomplete domain")
    config.addinivalue_line("markers", "domain_change_requests: Tests for change_requests domain")
    config.addinivalue_line("markers", "domain_jobs: Tests for jobs domain")
    config.addinivalue_line("markers", "domain_newsfeed: Tests for newsfeed domain")
    config.addinivalue_line("markers", "domain_utilities: Tests for utilities domain")
    config.addinivalue_line("markers", "domain_store: Tests for store domain")


MIGRATIONS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "migrations"))

SEEDS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "seeds"))


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
    await _async_pg_init(conn)
    yield conn
    await conn.close()


@pytest.fixture(scope="function")
async def asyncpg_pool(postgres_service: PostgresService) -> AsyncIterator[asyncpg.Pool]:
    """Shared asyncpg pool for factory fixtures within a single test.

    Uses small pool size to limit connections. Each test gets its own pool
    that is shared across all factory fixture calls within that test.
    """
    pool = await asyncpg.create_pool(
        user=postgres_service.user,
        password=postgres_service.password,
        host=postgres_service.host,
        port=postgres_service.port,
        database=postgres_service.database,
        min_size=1,
        max_size=3,
        init=_async_pg_init,
    )
    yield pool
    await pool.close()


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


@pytest.fixture(scope="session")
def global_message_id_tracker() -> set[int]:
    """Session-wide tracker for all used message IDs.

    Prevents collisions across all tests in the session.
    """
    return set()


@pytest.fixture(scope="session")
def global_email_tracker() -> set[str]:
    """Session-wide tracker for all used email addresses.

    Prevents collisions across all tests in the session.
    """
    return set()


@pytest.fixture(scope="session")
def global_session_id_tracker() -> set[str]:
    """Session-wide tracker for all used session IDs.

    Prevents collisions across all tests in the session.
    """
    return set()


@pytest.fixture(scope="session")
def global_token_hash_tracker() -> set[str]:
    """Session-wide tracker for all used token hashes.

    Prevents collisions across all tests in the session.
    """
    return set()


@pytest.fixture(scope="session")
def global_job_id_tracker() -> set:
    """Session-wide tracker for all used job IDs (UUIDs).

    Prevents collisions across all tests in the session.
    """
    return set()


@pytest.fixture(scope="session")
def global_idempotency_key_tracker() -> set[str]:
    """Session-wide tracker for all used idempotency keys.

    Prevents collisions across all tests in the session.
    """
    return set()


@pytest.fixture(scope="session")
def global_ip_hash_tracker() -> set[str]:
    """Session-wide tracker for all used IP hashes.

    Prevents collisions across all tests in the session.
    """
    return set()


# ==============================================================================
# SHARED CODE GENERATION FIXTURES (used by 3+ domains)
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


@pytest.fixture
def unique_message_id(global_message_id_tracker: set[int]) -> int:
    """Generate a unique Discord message ID.

    Message IDs are 18-digit integers (snowflakes), same as user/thread IDs.
    We generate random IDs in the valid range and track them.
    """
    while True:
        message_id = fake.random_int(min=100000000000000000, max=999999999999999999)
        if message_id not in global_message_id_tracker:
            global_message_id_tracker.add(message_id)
            return message_id


@pytest.fixture
def unique_ip_hash(global_ip_hash_tracker: set[str]) -> str:
    """Generate a unique IP hash guaranteed not to collide.

    Uses UUID-based generation for guaranteed uniqueness across
    parallel test execution and multiple test runs.

    Format: SHA256 hex digest (64 lowercase hex chars)
    """
    import hashlib

    ip_hash = hashlib.sha256(uuid4().bytes).hexdigest()
    global_ip_hash_tracker.add(ip_hash)
    return ip_hash


# ==============================================================================
# SHARED HELPER FACTORY FIXTURES (used by 3+ domains)
# ==============================================================================


@pytest.fixture
async def create_test_map(
    asyncpg_pool: asyncpg.Pool,
    global_code_tracker: set[str],
    global_user_id_tracker: set[int],
):
    """Factory fixture for creating complete test maps with related data.

    Creates a full map with auto-calculated raw_difficulty and at least one primary creator.

    Args:
        code: Map code (generated if not provided)
        creator_id: User ID for primary creator (generated if not provided)
        mechanics: List of mechanic IDs to link (optional)
        restrictions: List of restriction IDs to link (optional)
        tags: List of tag IDs to link (optional)
        medals: Dict with gold/silver/bronze times (optional)
        **overrides: Override any core.maps field

    Usage:
        map_id = await create_test_map()
        map_id = await create_test_map(code="ABC123", difficulty="Hard")
        map_id = await create_test_map(creator_id=user_id, mechanics=[1, 2])
        map_id = await create_test_map(medals={"gold": 30.0, "silver": 45.0, "bronze": 60.0})
    """

    async def _create(
        code: str | None = None,
        creator_id: int | None = None,
        mechanics: list[int] | None = None,
        restrictions: list[int] | None = None,
        tags: list[int] | None = None,
        medals: dict[str, float] | None = None,
        **overrides: Any,
    ) -> int:
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
            "hidden": False,
            "archived": False,
        }

        # Apply overrides
        data.update(overrides)

        # Auto-calculate raw_difficulty from difficulty (ignores any explicit raw_difficulty)
        difficulty = data["difficulty"]
        raw_min, raw_max = difficulties.DIFFICULTY_RANGES_ALL[difficulty]
        data["raw_difficulty"] = fake.pyfloat(min_value=raw_min, max_value=raw_max - 0.1, right_digits=2)

        async with asyncpg_pool.acquire() as conn:
            # Create core map
            map_id = await conn.fetchval(
                """
                INSERT INTO core.maps (
                    code, map_name, category, checkpoints, official,
                    playtesting, difficulty, raw_difficulty, hidden, archived
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
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
                data["hidden"],
                data["archived"],
            )

            # Create primary creator
            if creator_id is None:
                # Generate unique user ID
                while True:
                    creator_id = fake.random_int(min=100000000000000000, max=999999999999999999)
                    if creator_id not in global_user_id_tracker:
                        global_user_id_tracker.add(creator_id)
                        break

                # Create user
                await conn.execute(
                    """
                    INSERT INTO core.users (id, nickname, global_name)
                    VALUES ($1, $2, $3)
                    """,
                    creator_id,
                    fake.user_name(),
                    fake.user_name(),
                )

            # Link creator to map
            await conn.execute(
                """
                INSERT INTO maps.creators (map_id, user_id, is_primary)
                VALUES ($1, $2, $3)
                """,
                map_id,
                creator_id,
                True,
            )

            # Link mechanics if provided
            if mechanics:
                for mechanic_id in mechanics:
                    await conn.execute(
                        """
                        INSERT INTO maps.mechanic_links (map_id, mechanic_id)
                        VALUES ($1, $2)
                        """,
                        map_id,
                        mechanic_id,
                    )

            # Link restrictions if provided
            if restrictions:
                for restriction_id in restrictions:
                    await conn.execute(
                        """
                        INSERT INTO maps.restriction_links (map_id, restriction_id)
                        VALUES ($1, $2)
                        """,
                        map_id,
                        restriction_id,
                    )

            # Link tags if provided
            if tags:
                for tag_id in tags:
                    await conn.execute(
                        """
                        INSERT INTO maps.tag_links (map_id, tag_id)
                        VALUES ($1, $2)
                        """,
                        map_id,
                        tag_id,
                    )

            # Create medals if provided
            if medals:
                await conn.execute(
                    """
                    INSERT INTO maps.medals (map_id, gold, silver, bronze)
                    VALUES ($1, $2, $3, $4)
                    """,
                    map_id,
                    medals.get("gold"),
                    medals.get("silver"),
                    medals.get("bronze"),
                )

        return map_id

    return _create


@pytest.fixture
async def create_test_user(asyncpg_pool: asyncpg.Pool, global_user_id_tracker: set[int]):
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

        async with asyncpg_pool.acquire() as conn:
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

    return _create


@pytest.fixture
async def grant_user_coins(asyncpg_pool: asyncpg.Pool):
    """Factory fixture for granting coins to users.

    Returns a function that adds coins to a user's balance.

    Usage:
        balance = await grant_user_coins(user_id, 1000)
        balance = await grant_user_coins(user_id, 500)
    """

    async def _grant(user_id: int, amount: int) -> int:
        async with asyncpg_pool.acquire() as conn:
            result = await conn.fetchval(
                """
                UPDATE core.users
                SET coins = coins + $2
                WHERE id = $1
                RETURNING coins
                """,
                user_id,
                amount,
            )
        return result

    return _grant


@pytest.fixture
async def create_test_playtest(asyncpg_pool: asyncpg.Pool, global_thread_id_tracker: set[int]):
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

        async with asyncpg_pool.acquire() as conn:
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

    return _create


@pytest.fixture
async def create_test_completion(asyncpg_pool: asyncpg.Pool):
    """Factory fixture for creating test completions.

    Returns a function that creates a verified completion for a user and map.

    Usage:
        completion_id = await create_test_completion(user_id, map_id)
        completion_id = await create_test_completion(user_id, map_id, verified=False)
    """

    async def _create(user_id: int, map_id: int, **overrides: Any) -> int:
        # Default values
        data = {
            "verified": True,
            "legacy": False,
            "time": 30.5,
            "screenshot": "https://example.com/screenshot.png",
            "completion": True,
            "message_id": None,
            "verified_by": None,
            "reason": None,
        }

        # Apply overrides
        data.update(overrides)

        async with asyncpg_pool.acquire() as conn:
            completion_id = await conn.fetchval(
                """
                INSERT INTO core.completions (
                    user_id, map_id, verified, legacy, time, screenshot,
                    completion, message_id, verified_by, reason
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
                RETURNING id
                """,
                user_id,
                map_id,
                data["verified"],
                data["legacy"],
                data["time"],
                data["screenshot"],
                data["completion"],
                data["message_id"],
                data["verified_by"],
                data["reason"],
            )
        return completion_id

    return _create


@pytest.fixture
async def create_test_vote(asyncpg_pool: asyncpg.Pool):
    """Factory fixture for creating test playtest votes.

    Returns a function that creates a vote for a playtest.

    Usage:
        vote_id = await create_test_vote(user_id, map_id, thread_id)
        vote_id = await create_test_vote(user_id, map_id, thread_id, difficulty=7.5)
    """

    async def _create(user_id: int, map_id: int, thread_id: int, **overrides: Any) -> int:
        # Default values
        data = {
            "difficulty": 5.0,
        }

        # Apply overrides
        data.update(overrides)

        async with asyncpg_pool.acquire() as conn:
            vote_id = await conn.fetchval(
                """
                INSERT INTO playtests.votes (
                    user_id, map_id, playtest_thread_id, difficulty
                )
                VALUES ($1, $2, $3, $4)
                RETURNING id
                """,
                user_id,
                map_id,
                thread_id,
                data["difficulty"],
            )
        return vote_id

    return _create
