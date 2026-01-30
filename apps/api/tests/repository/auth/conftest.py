"""Auth domain fixtures."""

from typing import AsyncIterator
from uuid import uuid4

import asyncpg
import bcrypt
import pytest
from faker import Faker
from pytest_databases.docker.postgres import PostgresService

fake = Faker()


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
