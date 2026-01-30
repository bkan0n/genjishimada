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
    config.addinivalue_line("markers", "domain_autocomplete: Tests for autocomplete domain")
    config.addinivalue_line("markers", "domain_change_requests: Tests for change_requests domain")
    config.addinivalue_line("markers", "domain_jobs: Tests for jobs domain")
    config.addinivalue_line("markers", "domain_newsfeed: Tests for newsfeed domain")


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


@pytest.fixture
def unique_email(global_email_tracker: set[str]) -> str:
    """Generate a unique email address guaranteed not to collide.

    Uses UUID-based generation for guaranteed uniqueness across
    parallel test execution and multiple test runs.

    Format: test-{8 lowercase hex chars}@example.com
    """
    email = f"test-{uuid4().hex[:8]}@example.com"
    global_email_tracker.add(email)
    return email


@pytest.fixture
def unique_session_id(global_session_id_tracker: set[str]) -> str:
    """Generate a unique session ID guaranteed not to collide.

    Uses UUID-based generation for guaranteed uniqueness across
    parallel test execution and multiple test runs.

    Format: Full UUID v4 hex string (32 chars)
    """
    session_id = uuid4().hex
    global_session_id_tracker.add(session_id)
    return session_id


@pytest.fixture
def unique_token_hash(global_token_hash_tracker: set[str]) -> str:
    """Generate a unique token hash guaranteed not to collide.

    Uses UUID-based generation for guaranteed uniqueness across
    parallel test execution and multiple test runs.

    Format: SHA256-like hex string (64 chars)
    """
    import hashlib

    token_hash = hashlib.sha256(uuid4().bytes).hexdigest()
    global_token_hash_tracker.add(token_hash)
    return token_hash


@pytest.fixture
def unique_job_id(global_job_id_tracker: set):
    """Generate a unique job ID (UUID) guaranteed not to collide.

    Uses UUID v4 for guaranteed uniqueness across
    parallel test execution and multiple test runs.

    Format: UUID (e.g., "550e8400-e29b-41d4-a716-446655440000")
    """
    import uuid

    job_id = uuid.uuid4()
    global_job_id_tracker.add(job_id)
    return job_id


@pytest.fixture
def unique_idempotency_key(global_idempotency_key_tracker: set[str]) -> str:
    """Generate a unique idempotency key guaranteed not to collide.

    Uses UUID-based generation for guaranteed uniqueness across
    parallel test execution and multiple test runs.

    Format: idem-{16 lowercase hex chars} (e.g., "idem-a1b2c3d4e5f6g7h8")
    """
    key = f"idem-{uuid4().hex[:16]}"
    global_idempotency_key_tracker.add(key)
    return key


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
            "hidden": False,
            "archived": False,
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


@pytest.fixture
async def create_test_email_user(
    postgres_service: PostgresService, global_user_id_tracker: set[int], global_email_tracker: set[str]
):
    """Factory fixture for creating test users with email authentication.

    Returns a function that creates a user with email_auth and returns (user_id, email, password_hash).

    Usage:
        user_id, email, password_hash = await create_test_email_user()
        user_id, email, password_hash = await create_test_email_user(nickname="TestUser", email="custom@example.com")
    """

    async def _create(
        nickname: str | None = None,
        email: str | None = None,
        password_hash: str | None = None,
        email_verified: bool = False,
    ) -> tuple[int, str, str]:
        import bcrypt

        if nickname is None:
            nickname = fake.user_name()

        if email is None:
            email = f"test-{uuid4().hex[:8]}@example.com"
            global_email_tracker.add(email)

        if password_hash is None:
            # Generate a bcrypt hash for "password123"
            password_hash = bcrypt.hashpw("password123".encode(), bcrypt.gensalt()).decode()

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
                # Create core user
                await conn.execute(
                    """
                    INSERT INTO core.users (id, nickname, global_name)
                    VALUES ($1, $2, $3)
                    """,
                    user_id,
                    nickname,
                    nickname,
                )

                # Create email auth
                if email_verified:
                    await conn.execute(
                        """
                        INSERT INTO users.email_auth (user_id, email, password_hash, email_verified_at)
                        VALUES ($1, $2, $3, now())
                        """,
                        user_id,
                        email,
                        password_hash,
                    )
                else:
                    await conn.execute(
                        """
                        INSERT INTO users.email_auth (user_id, email, password_hash)
                        VALUES ($1, $2, $3)
                        """,
                        user_id,
                        email,
                        password_hash,
                    )

            return user_id, email, password_hash
        finally:
            await pool.close()

    return _create


@pytest.fixture
async def create_test_session(postgres_service: PostgresService, global_session_id_tracker: set[str]):
    """Factory fixture for creating test sessions.

    Returns a function that creates a session and returns session_id.

    Usage:
        session_id = await create_test_session(user_id=123)
        session_id = await create_test_session(user_id=None)  # Anonymous session
        session_id = await create_test_session(user_id=123, payload="custom_payload")
    """

    async def _create(
        user_id: int | None = None,
        payload: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> str:
        import base64

        session_id = uuid4().hex
        global_session_id_tracker.add(session_id)

        if payload is None:
            # Create a simple base64-encoded payload
            payload = base64.b64encode(f'{{"session_id": "{session_id}"}}'.encode()).decode()

        if ip_address is None:
            ip_address = fake.ipv4()

        if user_agent is None:
            user_agent = fake.user_agent()

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
                    INSERT INTO users.sessions (id, user_id, payload, last_activity, ip_address, user_agent)
                    VALUES ($1, $2, $3, now(), $4, $5)
                    """,
                    session_id,
                    user_id,
                    payload,
                    ip_address,
                    user_agent,
                )

            return session_id
        finally:
            await pool.close()

    return _create


@pytest.fixture
async def create_test_change_request(postgres_service: PostgresService, global_thread_id_tracker: set[int]):
    """Factory fixture for creating test change requests.

    Returns a function that creates a change request with the given parameters.

    Usage:
        thread_id = await create_test_change_request(map_code, user_id)
        thread_id = await create_test_change_request(map_code, user_id, change_request_type="Bug Fix")
    """

    async def _create(
        code: str,
        user_id: int,
        thread_id: int | None = None,
        content: str | None = None,
        change_request_type: str | None = None,
        creator_mentions: str | None = None,
        **overrides: Any,
    ) -> int:
        # Generate thread_id if not provided
        if thread_id is None:
            while True:
                thread_id = fake.random_int(min=100000000000000000, max=999999999999999999)
                if thread_id not in global_thread_id_tracker:
                    global_thread_id_tracker.add(thread_id)
                    break

        # Default values
        if content is None:
            content = fake.sentence(nb_words=20)

        if change_request_type is None:
            change_request_type = fake.random_element(
                elements=["Bug Fix", "Feature Request", "Improvement", "Balance Change"]
            )

        if creator_mentions is None:
            creator_mentions = ""

        data = {
            "content": content,
            "change_request_type": change_request_type,
            "creator_mentions": creator_mentions,
            "resolved": False,
            "alerted": False,
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
                await conn.execute(
                    """
                    INSERT INTO change_requests (
                        thread_id, code, user_id, content, change_request_type,
                        creator_mentions, resolved, alerted
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    """,
                    thread_id,
                    code,
                    user_id,
                    data["content"],
                    data["change_request_type"],
                    data["creator_mentions"],
                    data["resolved"],
                    data["alerted"],
                )
            return thread_id
        finally:
            await pool.close()

    return _create


@pytest.fixture
async def create_test_job(postgres_service: PostgresService, global_job_id_tracker: set):
    """Factory fixture for creating test jobs.

    Returns a function that creates a job with optional parameters.

    Usage:
        job_id = await create_test_job()
        job_id = await create_test_job(action="test_action", status="processing")
    """

    async def _create(
        job_id: Any | None = None,
        action: str | None = None,
        status: str = "queued",
        error_code: str | None = None,
        error_msg: str | None = None,
        **overrides: Any,
    ):
        import uuid

        # Generate job_id if not provided
        if job_id is None:
            job_id = uuid.uuid4()
            global_job_id_tracker.add(job_id)

        # Generate action if not provided
        if action is None:
            action = fake.word()

        data = {
            "action": action,
            "status": status,
            "error_code": error_code,
            "error_msg": error_msg,
            "attempts": 0,
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
                await conn.execute(
                    """
                    INSERT INTO public.jobs (
                        id, action, status, error_code, error_msg, attempts
                    )
                    VALUES ($1, $2, $3, $4, $5, $6)
                    """,
                    job_id,
                    data["action"],
                    data["status"],
                    data["error_code"],
                    data["error_msg"],
                    data["attempts"],
                )
            return job_id
        finally:
            await pool.close()

    return _create


@pytest.fixture
async def create_test_claim(postgres_service: PostgresService, global_idempotency_key_tracker: set[str]):
    """Factory fixture for creating test idempotency claims.

    Returns a function that creates an idempotency claim.

    Usage:
        key = await create_test_claim()
        key = await create_test_claim(key="custom-key")
    """

    async def _create(key: str | None = None) -> str:
        # Generate key if not provided
        if key is None:
            key = f"idem-{uuid4().hex[:16]}"
            global_idempotency_key_tracker.add(key)

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
                    INSERT INTO public.processed_messages (idempotency_key)
                    VALUES ($1)
                    """,
                    key,
                )
            return key
        finally:
            await pool.close()

    return _create


@pytest.fixture
async def create_test_newsfeed_event(postgres_service: PostgresService):
    """Factory fixture for creating test newsfeed events.

    Returns a function that creates a newsfeed event with optional parameters.

    Usage:
        event_id = await create_test_newsfeed_event()
        event_id = await create_test_newsfeed_event(payload={"type": "custom", "data": "value"})
    """

    async def _create(
        timestamp: Any | None = None,
        payload: dict | None = None,
    ) -> int:
        import datetime as dt
        import json

        # Generate timestamp if not provided
        if timestamp is None:
            timestamp = dt.datetime.now(dt.timezone.utc)

        # Generate payload if not provided
        if payload is None:
            payload = {
                "type": fake.word(),
                "data": fake.sentence(),
            }

        pool = await asyncpg.create_pool(
            user=postgres_service.user,
            password=postgres_service.password,
            host=postgres_service.host,
            port=postgres_service.port,
            database=postgres_service.database,
        )
        try:
            async with pool.acquire() as conn:
                event_id = await conn.fetchval(
                    """
                    INSERT INTO public.newsfeed (timestamp, payload)
                    VALUES ($1, $2::jsonb)
                    RETURNING id
                    """,
                    timestamp,
                    json.dumps(payload),
                )
            return event_id
        finally:
            await pool.close()

    return _create
