"""Tests for AuthRepository."""

from typing import AsyncGenerator
import uuid
import pytest
from datetime import datetime, timedelta, timezone

import asyncpg
from pytest_databases.docker.postgres import PostgresService

from repository.auth_repository import AuthRepository
from repository.exceptions import UniqueConstraintViolationError, ForeignKeyViolationError


def unique_email() -> str:
    """Generate a unique email for testing."""
    return f"test-{uuid.uuid4()}@test.com"


@pytest.fixture
async def db_pool(postgres_service: PostgresService) -> AsyncGenerator[asyncpg.Pool]:
    """Create asyncpg pool for tests."""
    pool = await asyncpg.create_pool(
        user=postgres_service.user,
        password=postgres_service.password,
        host=postgres_service.host,
        port=postgres_service.port,
        database=postgres_service.database,
    )
    yield pool
    await pool.close()


@pytest.fixture
async def auth_repo(db_pool: asyncpg.Pool) -> AuthRepository:
    """Create auth repository instance."""
    return AuthRepository(db_pool)


class TestRateLimiting:
    """Test rate limiting repository methods."""

    async def test_fetch_rate_limit_count_returns_zero_initially(self, auth_repo: AuthRepository) -> None:
        """Test that rate limit count is zero for new identifier."""
        window_start = datetime.now(timezone.utc) - timedelta(hours=1)
        count = await auth_repo.fetch_rate_limit_count(unique_email(), "register", window_start)
        assert count == 0

    async def test_record_attempt_increments_count(self, auth_repo: AuthRepository) -> None:
        """Test that recording an attempt increases count."""
        identifier = unique_email()
        action = "register"
        window_start = datetime.now(timezone.utc) - timedelta(hours=1)

        await auth_repo.record_attempt(identifier, action, success=False)
        count = await auth_repo.fetch_rate_limit_count(identifier, action, window_start)
        assert count == 1


class TestEmailChecks:
    """Test email existence checks."""

    async def test_check_email_exists_returns_false_for_new_email(self, auth_repo: AuthRepository) -> None:
        """Test that new email doesn't exist."""
        exists = await auth_repo.check_email_exists(unique_email())
        assert exists is False


class TestUserCreation:
    """Test user creation methods."""

    async def test_generate_next_user_id_returns_integer(self, auth_repo: AuthRepository) -> None:
        """Test that user ID generation returns an integer."""
        user_id = await auth_repo.generate_next_user_id()
        assert isinstance(user_id, int)
        assert user_id > 0

    async def test_create_core_user_succeeds(self, auth_repo: AuthRepository) -> None:
        """Test creating a user in core.users."""
        user_id = await auth_repo.generate_next_user_id()
        await auth_repo.create_core_user(user_id, "testuser")

        # Verify user was created
        async with auth_repo._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM core.users WHERE id = $1", user_id)
            assert row is not None
            assert row["nickname"] == "testuser"

    async def test_create_email_auth_succeeds(self, auth_repo: AuthRepository) -> None:
        """Test creating email auth record."""
        user_id = await auth_repo.generate_next_user_id()
        email = unique_email()
        await auth_repo.create_core_user(user_id, "testuser")
        await auth_repo.create_email_auth(user_id, email, "hash123")

        # Verify email auth was created
        async with auth_repo._pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users.email_auth WHERE user_id = $1", user_id)
            assert row is not None
            assert row["email"] == email
            assert row["password_hash"] == "hash123"

    async def test_create_email_auth_raises_on_duplicate_email(self, auth_repo: AuthRepository) -> None:
        """Test that duplicate email raises UniqueConstraintViolationError."""
        user_id_1 = await auth_repo.generate_next_user_id()
        user_id_2 = await auth_repo.generate_next_user_id()
        email = unique_email()

        await auth_repo.create_core_user(user_id_1, "user1")
        await auth_repo.create_core_user(user_id_2, "user2")
        await auth_repo.create_email_auth(user_id_1, email, "hash1")

        with pytest.raises(UniqueConstraintViolationError):
            await auth_repo.create_email_auth(user_id_2, email, "hash2")


class TestTokenOperations:
    """Test token operations."""

    async def test_insert_email_token_succeeds(self, auth_repo: AuthRepository) -> None:
        """Test inserting email verification token."""
        user_id = await auth_repo.generate_next_user_id()
        await auth_repo.create_core_user(user_id, "testuser")

        token_hash = "abc123"
        expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

        await auth_repo.insert_email_token(user_id, token_hash, "verification", expires_at)

        # Verify token was created
        async with auth_repo._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM users.email_tokens WHERE user_id = $1 AND token_hash = $2",
                user_id,
                token_hash,
            )
            assert row is not None
            assert row["token_type"] == "verification"

    async def test_mark_token_used_updates_used_at(self, auth_repo: AuthRepository) -> None:
        """Test marking token as used."""
        user_id = await auth_repo.generate_next_user_id()
        await auth_repo.create_core_user(user_id, "testuser")

        token_hash = "abc123"
        expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
        await auth_repo.insert_email_token(user_id, token_hash, "verification", expires_at)

        await auth_repo.mark_token_used(token_hash)

        # Verify used_at is set
        async with auth_repo._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT used_at FROM users.email_tokens WHERE token_hash = $1",
                token_hash,
            )
            assert row is not None
            assert row["used_at"] is not None


class TestAuthStatus:
    """Test auth status helpers."""

    async def test_get_auth_status_returns_email(self, auth_repo: AuthRepository) -> None:
        """Test that auth status returns email for user."""
        user_id = await auth_repo.generate_next_user_id()
        await auth_repo.create_core_user(user_id, "statususer")
        await auth_repo.create_email_auth(user_id, "status@test.com", "hash")

        status = await auth_repo.get_auth_status(user_id)
        assert status is not None
        assert status["email"] == "status@test.com"


class TestSessionOperations:
    """Test session repository methods."""

    async def test_write_and_read_session(self, auth_repo: AuthRepository) -> None:
        """Test writing and reading a session."""
        await auth_repo.write_session("sess-1", "payload", None, None, None)
        payload = await auth_repo.read_session("sess-1", 120)
        assert payload == "payload"

    async def test_delete_session(self, auth_repo: AuthRepository) -> None:
        """Test deleting a session."""
        await auth_repo.write_session("sess-2", "payload", None, None, None)
        deleted = await auth_repo.delete_session("sess-2")
        assert deleted is True

    async def test_delete_expired_sessions(self, auth_repo: AuthRepository) -> None:
        """Test deleting expired sessions."""
        async with auth_repo._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO users.sessions (id, payload, last_activity) VALUES ($1, $2, now() - interval '3 hours')",
                "expired-1",
                "payload",
            )

        count = await auth_repo.delete_expired_sessions(120)
        assert count >= 1

    async def test_get_user_sessions_returns_rows(self, auth_repo: AuthRepository) -> None:
        """Test fetching sessions for a user."""
        user_id = await auth_repo.generate_next_user_id()
        await auth_repo.create_core_user(user_id, "sessionuser")
        await auth_repo.create_email_auth(user_id, unique_email(), "hash")

        await auth_repo.write_session("sess-a", "payload", user_id, None, None)
        await auth_repo.write_session("sess-b", "payload", user_id, None, None)

        sessions = await auth_repo.get_user_sessions(user_id, 120)
        assert len(sessions) >= 2


class TestRememberTokens:
    """Test remember token operations."""

    async def test_create_validate_revoke_remember_token(self, auth_repo: AuthRepository) -> None:
        """Test remember token lifecycle."""
        user_id = await auth_repo.generate_next_user_id()
        await auth_repo.create_core_user(user_id, "rememberuser")
        await auth_repo.create_email_auth(user_id, unique_email(), "hash")

        token_hash = "abc123"
        expires_at = datetime.now(timezone.utc) + timedelta(days=1)
        await auth_repo.create_remember_token(user_id, token_hash, expires_at, None, None)

        validated_user_id = await auth_repo.validate_remember_token(token_hash)
        assert validated_user_id == user_id

        revoked = await auth_repo.revoke_remember_tokens(user_id)
        assert revoked >= 1


class TestModeratorChecks:
    """Test moderator session checks."""

    async def test_check_is_mod_returns_true(self, auth_repo: AuthRepository) -> None:
        """Test that check_is_mod returns True for mod session."""
        user_id = await auth_repo.generate_next_user_id()
        await auth_repo.create_core_user(user_id, "moduser")
        await auth_repo.create_email_auth(user_id, unique_email(), "hash")

        async with auth_repo._pool.acquire() as conn:
            await conn.execute("UPDATE core.users SET is_mod = true WHERE id = $1", user_id)

        await auth_repo.write_session("mod-session", "payload", user_id, None, None)
        is_mod = await auth_repo.check_is_mod("mod-session")
        assert is_mod is True
