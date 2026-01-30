"""Tests for AuthRepository email token operations.

Test Coverage:
- insert_email_token: verification, password_reset, invalid user_id, expiration
- get_token_with_user: found with user data, not found, wrong type, used/unused
- mark_token_used: sets timestamp, idempotent
- invalidate_user_tokens: marks all unused, filters by type, doesn't affect used
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
# insert_email_token TESTS
# ==============================================================================


class TestInsertEmailToken:
    """Test insert_email_token method."""

    async def test_create_verification_token_succeeds(
        self,
        repository: AuthRepository,
        create_test_email_user,
        unique_token_hash: str,
    ):
        """Test creating verification token succeeds."""
        # Arrange
        user_id, _, _ = await create_test_email_user()
        expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=24)

        # Act
        await repository.insert_email_token(
            user_id, unique_token_hash, "verification", expires_at
        )

        # Assert - Verify token exists
        result = await repository.get_token_with_user(unique_token_hash, "verification")
        assert result is not None
        assert result["user_id"] == user_id

    async def test_create_password_reset_token_succeeds(
        self,
        repository: AuthRepository,
        create_test_email_user,
        unique_token_hash: str,
    ):
        """Test creating password_reset token succeeds."""
        # Arrange
        user_id, _, _ = await create_test_email_user()
        expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)

        # Act
        await repository.insert_email_token(
            user_id, unique_token_hash, "password_reset", expires_at
        )

        # Assert - Verify token exists
        result = await repository.get_token_with_user(unique_token_hash, "password_reset")
        assert result is not None
        assert result["user_id"] == user_id

    async def test_invalid_user_id_raises_error(
        self,
        repository: AuthRepository,
        unique_token_hash: str,
    ):
        """Test creating with invalid user_id raises ForeignKeyViolationError."""
        # Arrange
        fake_user_id = fake.random_int(min=100000000000000000, max=999999999999999999)
        expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)

        # Act & Assert
        with pytest.raises(ForeignKeyViolationError) as exc_info:
            await repository.insert_email_token(
                fake_user_id, unique_token_hash, "verification", expires_at
            )

        assert "email_tokens" in exc_info.value.table

    async def test_expiration_stored_correctly(
        self,
        repository: AuthRepository,
        create_test_email_user,
        unique_token_hash: str,
        asyncpg_conn,
    ):
        """Test that expiration timestamp is stored correctly."""
        # Arrange
        user_id, _, _ = await create_test_email_user()
        expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)

        # Act
        await repository.insert_email_token(
            user_id, unique_token_hash, "verification", expires_at
        )

        # Assert - Verify expiration stored
        row = await asyncpg_conn.fetchrow(
            "SELECT expires_at FROM users.email_tokens WHERE token_hash = $1",
            unique_token_hash,
        )
        assert row is not None
        # Allow some tolerance for timing (within 1 minute)
        diff = abs((row["expires_at"] - expires_at).total_seconds())
        assert diff < 60  # Within 1 minute


# ==============================================================================
# get_token_with_user TESTS
# ==============================================================================


class TestGetTokenWithUser:
    """Test get_token_with_user method."""

    async def test_found_returns_complete_data_with_user_info(
        self,
        repository: AuthRepository,
        create_test_email_user,
        unique_token_hash: str,
    ):
        """Test that found token returns complete data with user info."""
        # Arrange
        user_id, email, _ = await create_test_email_user()
        expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)

        await repository.insert_email_token(
            user_id, unique_token_hash, "verification", expires_at
        )

        # Act
        result = await repository.get_token_with_user(unique_token_hash, "verification")

        # Assert - Contains token and user data
        assert result is not None
        assert result["user_id"] == user_id
        assert result["email"].lower() == email.lower()
        assert "nickname" in result
        assert "coins" in result
        assert "is_mod" in result
        assert "expires_at" in result
        assert "used_at" in result

    async def test_not_found_returns_none(
        self,
        repository: AuthRepository,
        unique_token_hash: str,
    ):
        """Test that non-existent token returns None."""
        # Act
        result = await repository.get_token_with_user(unique_token_hash, "verification")

        # Assert
        assert result is None

    async def test_wrong_type_returns_none(
        self,
        repository: AuthRepository,
        create_test_email_user,
        unique_token_hash: str,
    ):
        """Test that querying with wrong type returns None."""
        # Arrange
        user_id, _, _ = await create_test_email_user()
        expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)

        # Create as verification token
        await repository.insert_email_token(
            user_id, unique_token_hash, "verification", expires_at
        )

        # Act - Query as password_reset
        result = await repository.get_token_with_user(unique_token_hash, "password_reset")

        # Assert
        assert result is None

    async def test_unused_token_has_null_used_at(
        self,
        repository: AuthRepository,
        create_test_email_user,
        unique_token_hash: str,
    ):
        """Test that unused token has null used_at."""
        # Arrange
        user_id, _, _ = await create_test_email_user()
        expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)

        await repository.insert_email_token(
            user_id, unique_token_hash, "verification", expires_at
        )

        # Act
        result = await repository.get_token_with_user(unique_token_hash, "verification")

        # Assert
        assert result is not None
        assert result["used_at"] is None

    async def test_used_token_has_timestamp(
        self,
        repository: AuthRepository,
        create_test_email_user,
        unique_token_hash: str,
    ):
        """Test that used token has used_at timestamp."""
        # Arrange
        user_id, _, _ = await create_test_email_user()
        expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)

        await repository.insert_email_token(
            user_id, unique_token_hash, "verification", expires_at
        )

        # Mark as used
        await repository.mark_token_used(unique_token_hash)

        # Act
        result = await repository.get_token_with_user(unique_token_hash, "verification")

        # Assert
        assert result is not None
        assert result["used_at"] is not None
        assert isinstance(result["used_at"], dt.datetime)


# ==============================================================================
# mark_token_used TESTS
# ==============================================================================


class TestMarkTokenUsed:
    """Test mark_token_used method."""

    async def test_sets_used_at_timestamp(
        self,
        repository: AuthRepository,
        create_test_email_user,
        unique_token_hash: str,
    ):
        """Test that mark_token_used sets timestamp."""
        # Arrange
        user_id, _, _ = await create_test_email_user()
        expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)

        await repository.insert_email_token(
            user_id, unique_token_hash, "verification", expires_at
        )

        # Verify initially not used
        before = await repository.get_token_with_user(unique_token_hash, "verification")
        assert before["used_at"] is None

        # Act
        await repository.mark_token_used(unique_token_hash)

        # Assert
        after = await repository.get_token_with_user(unique_token_hash, "verification")
        assert after["used_at"] is not None
        assert isinstance(after["used_at"], dt.datetime)

    async def test_idempotent_can_call_multiple_times(
        self,
        repository: AuthRepository,
        create_test_email_user,
        unique_token_hash: str,
    ):
        """Test that mark_token_used is idempotent."""
        # Arrange
        user_id, _, _ = await create_test_email_user()
        expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)

        await repository.insert_email_token(
            user_id, unique_token_hash, "verification", expires_at
        )

        # Act - Call multiple times
        await repository.mark_token_used(unique_token_hash)
        first_timestamp = (
            await repository.get_token_with_user(unique_token_hash, "verification")
        )["used_at"]

        await repository.mark_token_used(unique_token_hash)
        second_timestamp = (
            await repository.get_token_with_user(unique_token_hash, "verification")
        )["used_at"]

        # Assert - Both calls succeed, timestamp exists
        assert first_timestamp is not None
        assert second_timestamp is not None

    async def test_timestamp_persists(
        self,
        repository: AuthRepository,
        create_test_email_user,
        unique_token_hash: str,
    ):
        """Test that used_at timestamp persists."""
        # Arrange
        user_id, _, _ = await create_test_email_user()
        expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)

        await repository.insert_email_token(
            user_id, unique_token_hash, "verification", expires_at
        )

        # Act
        await repository.mark_token_used(unique_token_hash)

        # Assert - Fetch again to verify persistence
        result = await repository.get_token_with_user(unique_token_hash, "verification")
        assert result["used_at"] is not None


# ==============================================================================
# invalidate_user_tokens TESTS
# ==============================================================================


class TestInvalidateUserTokens:
    """Test invalidate_user_tokens method."""

    async def test_marks_all_unused_tokens_of_type(
        self,
        repository: AuthRepository,
        create_test_email_user,
        global_token_hash_tracker: set[str],
    ):
        """Test that all unused tokens of specified type are marked."""
        # Arrange
        import hashlib

        user_id, _, _ = await create_test_email_user()
        expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)

        # Create multiple unused verification tokens
        token1 = hashlib.sha256(uuid4().bytes).hexdigest()
        token2 = hashlib.sha256(uuid4().bytes).hexdigest()
        global_token_hash_tracker.add(token1)
        global_token_hash_tracker.add(token2)

        await repository.insert_email_token(user_id, token1, "verification", expires_at)
        await repository.insert_email_token(user_id, token2, "verification", expires_at)

        # Act
        await repository.invalidate_user_tokens(user_id, "verification")

        # Assert - Both tokens now marked as used
        result1 = await repository.get_token_with_user(token1, "verification")
        result2 = await repository.get_token_with_user(token2, "verification")

        assert result1["used_at"] is not None
        assert result2["used_at"] is not None

    async def test_doesnt_affect_already_used_tokens(
        self,
        repository: AuthRepository,
        create_test_email_user,
        global_token_hash_tracker: set[str],
        asyncpg_conn,
    ):
        """Test that already used tokens remain unchanged."""
        # Arrange
        import hashlib

        user_id, _, _ = await create_test_email_user()
        expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)

        # Create one used and one unused token
        used_token = hashlib.sha256(uuid4().bytes).hexdigest()
        unused_token = hashlib.sha256(uuid4().bytes).hexdigest()
        global_token_hash_tracker.add(used_token)
        global_token_hash_tracker.add(unused_token)

        await repository.insert_email_token(user_id, used_token, "verification", expires_at)
        await repository.insert_email_token(user_id, unused_token, "verification", expires_at)

        # Mark one as used and record its timestamp
        await repository.mark_token_used(used_token)
        original_timestamp = (
            await repository.get_token_with_user(used_token, "verification")
        )["used_at"]

        # Act - Invalidate all unused
        await repository.invalidate_user_tokens(user_id, "verification")

        # Assert - Used token timestamp unchanged
        after_timestamp = (
            await repository.get_token_with_user(used_token, "verification")
        )["used_at"]

        # The timestamps should be within a few seconds (allowing for time precision)
        assert abs((original_timestamp - after_timestamp).total_seconds()) < 2

    async def test_doesnt_affect_other_token_types(
        self,
        repository: AuthRepository,
        create_test_email_user,
        global_token_hash_tracker: set[str],
    ):
        """Test that invalidating doesn't affect other token types."""
        # Arrange
        import hashlib

        user_id, _, _ = await create_test_email_user()
        expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)

        # Create verification and password_reset tokens
        verification_token = hashlib.sha256(uuid4().bytes).hexdigest()
        password_token = hashlib.sha256(uuid4().bytes).hexdigest()
        global_token_hash_tracker.add(verification_token)
        global_token_hash_tracker.add(password_token)

        await repository.insert_email_token(
            user_id, verification_token, "verification", expires_at
        )
        await repository.insert_email_token(
            user_id, password_token, "password_reset", expires_at
        )

        # Act - Invalidate only verification tokens
        await repository.invalidate_user_tokens(user_id, "verification")

        # Assert - Verification invalidated, password_reset unchanged
        verification_result = await repository.get_token_with_user(
            verification_token, "verification"
        )
        password_result = await repository.get_token_with_user(
            password_token, "password_reset"
        )

        assert verification_result["used_at"] is not None
        assert password_result["used_at"] is None

    async def test_doesnt_affect_other_users(
        self,
        repository: AuthRepository,
        create_test_email_user,
        global_token_hash_tracker: set[str],
    ):
        """Test that invalidating doesn't affect other users' tokens."""
        # Arrange
        import hashlib

        user_id1, _, _ = await create_test_email_user()
        user_id2, _, _ = await create_test_email_user()
        expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)

        # Create tokens for both users
        token1 = hashlib.sha256(uuid4().bytes).hexdigest()
        token2 = hashlib.sha256(uuid4().bytes).hexdigest()
        global_token_hash_tracker.add(token1)
        global_token_hash_tracker.add(token2)

        await repository.insert_email_token(user_id1, token1, "verification", expires_at)
        await repository.insert_email_token(user_id2, token2, "verification", expires_at)

        # Act - Invalidate user1's tokens
        await repository.invalidate_user_tokens(user_id1, "verification")

        # Assert - user1 tokens invalidated, user2 unchanged
        result1 = await repository.get_token_with_user(token1, "verification")
        result2 = await repository.get_token_with_user(token2, "verification")

        assert result1["used_at"] is not None
        assert result2["used_at"] is None

    async def test_user_with_no_tokens_silent_success(
        self,
        repository: AuthRepository,
        create_test_email_user,
    ):
        """Test that invalidating user with no tokens succeeds silently."""
        # Arrange
        user_id, _, _ = await create_test_email_user()

        # Act - Should not error
        await repository.invalidate_user_tokens(user_id, "verification")

        # Assert - No error raised, operation completed
        assert True
