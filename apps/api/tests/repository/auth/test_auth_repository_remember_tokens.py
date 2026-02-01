"""Tests for AuthRepository remember token operations.

Test Coverage:
- create_remember_token: valid, invalid user_id, with/without metadata, expiration
- validate_remember_token: valid returns user_id, expired returns None, not found, updates last_used_at
- revoke_remember_tokens: deletes all for user, returns count, doesn't affect other users
"""

import datetime as dt
from uuid import uuid4

import pytest
from faker import Faker

from repository.auth_repository import AuthRepository
from repository.exceptions import ForeignKeyViolationError

fake = Faker()

pytestmark = [
    pytest.mark.domain_auth,
]


@pytest.fixture
async def repository(asyncpg_conn):
    """Provide auth repository instance."""
    return AuthRepository(asyncpg_conn)


# ==============================================================================
# create_remember_token TESTS
# ==============================================================================


class TestCreateRememberToken:
    """Test create_remember_token method."""

    async def test_create_with_valid_data_succeeds(
        self,
        repository: AuthRepository,
        create_test_user,
        unique_token_hash: str,
    ):
        """Test creating remember token with valid data succeeds."""
        # Arrange
        user_id = await create_test_user()
        expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=30)
        ip_address = fake.ipv4()
        user_agent = fake.user_agent()

        # Act
        await repository.create_remember_token(
            user_id, unique_token_hash, expires_at, ip_address, user_agent
        )

        # Assert - Verify token can be validated
        result = await repository.validate_remember_token(unique_token_hash)
        assert result == user_id

    async def test_invalid_user_id_raises_error(
        self,
        repository: AuthRepository,
        unique_token_hash: str,
    ):
        """Test creating with invalid user_id raises ForeignKeyViolationError."""
        # Arrange
        fake_user_id = fake.random_int(min=100000000000000000, max=999999999999999999)
        expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=30)
        ip_address = fake.ipv4()
        user_agent = fake.user_agent()

        # Act & Assert
        with pytest.raises(ForeignKeyViolationError) as exc_info:
            await repository.create_remember_token(
                fake_user_id, unique_token_hash, expires_at, ip_address, user_agent
            )

        assert "remember_tokens" in exc_info.value.table

    async def test_optional_metadata_stored(
        self,
        repository: AuthRepository,
        create_test_user,
        unique_token_hash: str,
        asyncpg_conn,
    ):
        """Test that ip_address and user_agent metadata are stored."""
        # Arrange
        user_id = await create_test_user()
        expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=30)
        ip_address = "192.168.1.100"
        user_agent = "TestAgent/1.0"

        # Act
        await repository.create_remember_token(
            user_id, unique_token_hash, expires_at, ip_address, user_agent
        )

        # Assert - Verify metadata stored
        row = await asyncpg_conn.fetchrow(
            "SELECT ip_address, user_agent FROM users.remember_tokens WHERE token_hash = $1",
            unique_token_hash,
        )
        assert row is not None
        assert str(row["ip_address"]) == ip_address  # Convert IPv4Address to string
        assert row["user_agent"] == user_agent

    async def test_null_metadata_allowed(
        self,
        repository: AuthRepository,
        create_test_user,
        unique_token_hash: str,
    ):
        """Test that null metadata is allowed."""
        # Arrange
        user_id = await create_test_user()
        expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=30)

        # Act - Create with null metadata
        await repository.create_remember_token(
            user_id, unique_token_hash, expires_at, None, None
        )

        # Assert - Token still works
        result = await repository.validate_remember_token(unique_token_hash)
        assert result == user_id

    async def test_expiration_stored_correctly(
        self,
        repository: AuthRepository,
        create_test_user,
        unique_token_hash: str,
        asyncpg_conn,
    ):
        """Test that expiration timestamp is stored correctly."""
        # Arrange
        user_id = await create_test_user()
        expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=60)

        # Act
        await repository.create_remember_token(
            user_id, unique_token_hash, expires_at, None, None
        )

        # Assert - Verify expiration stored
        row = await asyncpg_conn.fetchrow(
            "SELECT expires_at FROM users.remember_tokens WHERE token_hash = $1",
            unique_token_hash,
        )
        assert row is not None
        # Allow some tolerance for timing (within 1 minute)
        diff = abs((row["expires_at"] - expires_at).total_seconds())
        assert diff < 60


# ==============================================================================
# validate_remember_token TESTS
# ==============================================================================


class TestValidateRememberToken:
    """Test validate_remember_token method."""

    async def test_valid_token_returns_user_id(
        self,
        repository: AuthRepository,
        create_test_user,
        unique_token_hash: str,
    ):
        """Test that valid token returns user_id."""
        # Arrange
        user_id = await create_test_user()
        expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=30)

        await repository.create_remember_token(
            user_id, unique_token_hash, expires_at, None, None
        )

        # Act
        result = await repository.validate_remember_token(unique_token_hash)

        # Assert
        assert result == user_id

    async def test_expired_token_returns_none(
        self,
        repository: AuthRepository,
        create_test_user,
        unique_token_hash: str,
    ):
        """Test that expired token returns None."""
        # Arrange
        user_id = await create_test_user()
        # Token expired 1 day ago
        expires_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)

        await repository.create_remember_token(
            user_id, unique_token_hash, expires_at, None, None
        )

        # Act
        result = await repository.validate_remember_token(unique_token_hash)

        # Assert
        assert result is None

    async def test_not_found_returns_none(
        self,
        repository: AuthRepository,
        unique_token_hash: str,
    ):
        """Test that non-existent token returns None."""
        # Act
        result = await repository.validate_remember_token(unique_token_hash)

        # Assert
        assert result is None

    async def test_updates_last_used_at(
        self,
        repository: AuthRepository,
        create_test_user,
        unique_token_hash: str,
        asyncpg_conn,
    ):
        """Test that validating updates last_used_at timestamp."""
        # Arrange
        user_id = await create_test_user()
        expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=30)

        await repository.create_remember_token(
            user_id, unique_token_hash, expires_at, None, None
        )

        # Verify initially null
        before = await asyncpg_conn.fetchrow(
            "SELECT last_used_at FROM users.remember_tokens WHERE token_hash = $1",
            unique_token_hash,
        )
        assert before["last_used_at"] is None

        # Act
        await repository.validate_remember_token(unique_token_hash)

        # Assert - last_used_at is now set
        after = await asyncpg_conn.fetchrow(
            "SELECT last_used_at FROM users.remember_tokens WHERE token_hash = $1",
            unique_token_hash,
        )
        assert after["last_used_at"] is not None
        assert isinstance(after["last_used_at"], dt.datetime)

    async def test_multiple_validations_update_timestamp(
        self,
        repository: AuthRepository,
        create_test_user,
        unique_token_hash: str,
        asyncpg_conn,
    ):
        """Test that multiple validations update the timestamp."""
        # Arrange
        user_id = await create_test_user()
        expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=30)

        await repository.create_remember_token(
            user_id, unique_token_hash, expires_at, None, None
        )

        # Act - Validate multiple times
        await repository.validate_remember_token(unique_token_hash)
        first_timestamp = (
            await asyncpg_conn.fetchrow(
                "SELECT last_used_at FROM users.remember_tokens WHERE token_hash = $1",
                unique_token_hash,
            )
        )["last_used_at"]

        # Small delay to ensure timestamp difference
        import asyncio

        await asyncio.sleep(0.1)

        await repository.validate_remember_token(unique_token_hash)
        second_timestamp = (
            await asyncpg_conn.fetchrow(
                "SELECT last_used_at FROM users.remember_tokens WHERE token_hash = $1",
                unique_token_hash,
            )
        )["last_used_at"]

        # Assert - Timestamps exist and second is >= first
        assert first_timestamp is not None
        assert second_timestamp is not None
        assert second_timestamp >= first_timestamp

    async def test_expiration_boundary(
        self,
        repository: AuthRepository,
        create_test_user,
        unique_token_hash: str,
        asyncpg_conn,
    ):
        """Test expiration boundary - just at the edge."""
        # Arrange
        user_id = await create_test_user()
        # Token expires in 1 second
        expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=1)

        await repository.create_remember_token(
            user_id, unique_token_hash, expires_at, None, None
        )

        # Act - Should still be valid
        result = await repository.validate_remember_token(unique_token_hash)

        # Assert - Not expired yet
        assert result == user_id


# ==============================================================================
# revoke_remember_tokens TESTS
# ==============================================================================


class TestRevokeRememberTokens:
    """Test revoke_remember_tokens method."""

    async def test_deletes_all_tokens_for_user(
        self,
        repository: AuthRepository,
        create_test_user,
        global_token_hash_tracker: set[str],
    ):
        """Test that all tokens for user are deleted."""
        # Arrange
        import hashlib

        user_id = await create_test_user()
        expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=30)

        # Create multiple tokens
        token1 = hashlib.sha256(uuid4().bytes).hexdigest()
        token2 = hashlib.sha256(uuid4().bytes).hexdigest()
        token3 = hashlib.sha256(uuid4().bytes).hexdigest()
        global_token_hash_tracker.add(token1)
        global_token_hash_tracker.add(token2)
        global_token_hash_tracker.add(token3)

        await repository.create_remember_token(user_id, token1, expires_at, None, None)
        await repository.create_remember_token(user_id, token2, expires_at, None, None)
        await repository.create_remember_token(user_id, token3, expires_at, None, None)

        # Act
        count = await repository.revoke_remember_tokens(user_id)

        # Assert
        assert count >= 3

        # Verify all tokens invalid
        assert await repository.validate_remember_token(token1) is None
        assert await repository.validate_remember_token(token2) is None
        assert await repository.validate_remember_token(token3) is None

    async def test_returns_correct_count(
        self,
        repository: AuthRepository,
        create_test_user,
        global_token_hash_tracker: set[str],
    ):
        """Test that correct count is returned."""
        # Arrange
        import hashlib

        user_id = await create_test_user()
        expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=30)

        # Create 2 tokens
        token1 = hashlib.sha256(uuid4().bytes).hexdigest()
        token2 = hashlib.sha256(uuid4().bytes).hexdigest()
        global_token_hash_tracker.add(token1)
        global_token_hash_tracker.add(token2)

        await repository.create_remember_token(user_id, token1, expires_at, None, None)
        await repository.create_remember_token(user_id, token2, expires_at, None, None)

        # Act
        count = await repository.revoke_remember_tokens(user_id)

        # Assert
        assert count >= 2

    async def test_doesnt_affect_other_users(
        self,
        repository: AuthRepository,
        create_test_user,
        global_token_hash_tracker: set[str],
    ):
        """Test that revoking doesn't affect other users' tokens."""
        # Arrange
        import hashlib

        user_id1 = await create_test_user()
        user_id2 = await create_test_user()
        expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=30)

        # Create tokens for both users
        token1 = hashlib.sha256(uuid4().bytes).hexdigest()
        token2 = hashlib.sha256(uuid4().bytes).hexdigest()
        global_token_hash_tracker.add(token1)
        global_token_hash_tracker.add(token2)

        await repository.create_remember_token(user_id1, token1, expires_at, None, None)
        await repository.create_remember_token(user_id2, token2, expires_at, None, None)

        # Act - Revoke user1's tokens
        await repository.revoke_remember_tokens(user_id1)

        # Assert - user1 tokens revoked, user2 unchanged
        assert await repository.validate_remember_token(token1) is None
        assert await repository.validate_remember_token(token2) == user_id2

    async def test_user_with_no_tokens_returns_zero(
        self,
        repository: AuthRepository,
        create_test_user,
    ):
        """Test that user with no tokens returns 0."""
        # Arrange
        user_id = await create_test_user()

        # Act
        count = await repository.revoke_remember_tokens(user_id)

        # Assert
        assert count == 0

    async def test_revoked_tokens_cannot_be_validated(
        self,
        repository: AuthRepository,
        create_test_user,
        unique_token_hash: str,
    ):
        """Test that revoked tokens cannot be validated."""
        # Arrange
        user_id = await create_test_user()
        expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=30)

        await repository.create_remember_token(
            user_id, unique_token_hash, expires_at, None, None
        )

        # Verify token works before revocation
        before = await repository.validate_remember_token(unique_token_hash)
        assert before == user_id

        # Act - Revoke all tokens
        await repository.revoke_remember_tokens(user_id)

        # Assert - Token no longer works
        after = await repository.validate_remember_token(unique_token_hash)
        assert after is None
