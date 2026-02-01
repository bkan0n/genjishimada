"""Tests for AuthRepository email authentication operations.

Test Coverage:
- check_email_exists: exists, not exists, case insensitive
- create_email_auth: valid, duplicate email, invalid user_id
- get_user_by_email: found, not found, case insensitive, verified/unverified
- mark_email_verified: sets timestamp, idempotent
- update_password: updates hash, persists
- create_core_user: valid, duplicate user_id
- generate_next_user_id: increments sequence, unique
- get_auth_status: returns data, not found
"""

import datetime as dt
from uuid import uuid4

import bcrypt
import pytest
from faker import Faker

from repository.auth_repository import AuthRepository
from repository.exceptions import ForeignKeyViolationError, UniqueConstraintViolationError

fake = Faker()

pytestmark = [
    pytest.mark.domain_auth,
]


@pytest.fixture
async def repository(asyncpg_conn):
    """Provide auth repository instance."""
    return AuthRepository(asyncpg_conn)


# ==============================================================================
# check_email_exists TESTS
# ==============================================================================


class TestCheckEmailExists:
    """Test check_email_exists method."""

    async def test_email_exists_returns_true(
        self,
        repository: AuthRepository,
        create_test_email_user,
    ):
        """Test that existing email returns True."""
        # Arrange
        _, email, _ = await create_test_email_user()

        # Act
        result = await repository.check_email_exists(email)

        # Assert
        assert result is True

    async def test_email_not_exists_returns_false(
        self,
        repository: AuthRepository,
        unique_email: str,
    ):
        """Test that non-existent email returns False."""
        # Act
        result = await repository.check_email_exists(unique_email)

        # Assert
        assert result is False

    async def test_email_exists_case_insensitive(
        self,
        repository: AuthRepository,
        create_test_email_user,
    ):
        """Test that email check is case-insensitive."""
        # Arrange
        _, email, _ = await create_test_email_user()

        # Act - Check with different case
        result_upper = await repository.check_email_exists(email.upper())
        result_lower = await repository.check_email_exists(email.lower())
        result_mixed = await repository.check_email_exists(email.swapcase())

        # Assert
        assert result_upper is True
        assert result_lower is True
        assert result_mixed is True


# ==============================================================================
# create_email_auth TESTS
# ==============================================================================


class TestCreateEmailAuth:
    """Test create_email_auth method."""

    async def test_create_with_valid_data_succeeds(
        self,
        repository: AuthRepository,
        create_test_user,
        unique_email: str,
    ):
        """Test creating email auth with valid data succeeds."""
        # Arrange
        user_id = await create_test_user()
        password_hash = bcrypt.hashpw(b"password123", bcrypt.gensalt()).decode()

        # Act
        await repository.create_email_auth(user_id, unique_email, password_hash)

        # Assert - Verify email exists
        exists = await repository.check_email_exists(unique_email)
        assert exists is True

    async def test_create_duplicate_email_raises_error(
        self,
        repository: AuthRepository,
        create_test_email_user,
        create_test_user,
    ):
        """Test creating duplicate email raises UniqueConstraintViolationError."""
        # Arrange
        _, email, password_hash = await create_test_email_user()
        another_user_id = await create_test_user()

        # Act & Assert
        with pytest.raises(UniqueConstraintViolationError) as exc_info:
            await repository.create_email_auth(another_user_id, email, password_hash)

        assert "email_auth" in exc_info.value.table

    async def test_create_duplicate_email_case_insensitive_raises_error(
        self,
        repository: AuthRepository,
        create_test_email_user,
        create_test_user,
    ):
        """Test creating duplicate email with different case raises error."""
        # Arrange
        _, email, password_hash = await create_test_email_user()
        another_user_id = await create_test_user()

        # Act & Assert - Try with uppercase
        with pytest.raises(UniqueConstraintViolationError):
            await repository.create_email_auth(another_user_id, email.upper(), password_hash)

    async def test_create_invalid_user_id_raises_error(
        self,
        repository: AuthRepository,
        unique_email: str,
    ):
        """Test creating with invalid user_id raises ForeignKeyViolationError."""
        # Arrange
        fake_user_id = fake.random_int(min=100000000000000000, max=999999999999999999)
        password_hash = bcrypt.hashpw(b"password123", bcrypt.gensalt()).decode()

        # Act & Assert
        with pytest.raises(ForeignKeyViolationError) as exc_info:
            await repository.create_email_auth(fake_user_id, unique_email, password_hash)

        assert "email_auth" in exc_info.value.table

    async def test_create_duplicate_user_id_raises_error(
        self,
        repository: AuthRepository,
        create_test_email_user,
        global_email_tracker: set[str],
    ):
        """Test creating duplicate user_id raises UniqueConstraintViolationError."""
        # Arrange
        user_id, _, password_hash = await create_test_email_user()
        another_email = f"test-{uuid4().hex[:8]}@example.com"
        global_email_tracker.add(another_email)

        # Act & Assert
        with pytest.raises(UniqueConstraintViolationError):
            await repository.create_email_auth(user_id, another_email, password_hash)


# ==============================================================================
# get_user_by_email TESTS
# ==============================================================================


class TestGetUserByEmail:
    """Test get_user_by_email method."""

    async def test_found_returns_complete_user_data(
        self,
        repository: AuthRepository,
        create_test_email_user,
    ):
        """Test that found email returns complete user data."""
        # Arrange
        user_id, email, password_hash = await create_test_email_user()

        # Act
        result = await repository.get_user_by_email(email)

        # Assert
        assert result is not None
        assert result["user_id"] == user_id
        assert result["email"].lower() == email.lower()
        assert result["password_hash"] == password_hash
        assert "nickname" in result
        assert "coins" in result
        assert "is_mod" in result

    async def test_not_found_returns_none(
        self,
        repository: AuthRepository,
        unique_email: str,
    ):
        """Test that non-existent email returns None."""
        # Act
        result = await repository.get_user_by_email(unique_email)

        # Assert
        assert result is None

    async def test_case_insensitive_lookup(
        self,
        repository: AuthRepository,
        create_test_email_user,
    ):
        """Test that email lookup is case-insensitive."""
        # Arrange
        user_id, email, _ = await create_test_email_user()

        # Act
        result_upper = await repository.get_user_by_email(email.upper())
        result_lower = await repository.get_user_by_email(email.lower())

        # Assert
        assert result_upper is not None
        assert result_lower is not None
        assert result_upper["user_id"] == user_id
        assert result_lower["user_id"] == user_id

    async def test_unverified_user_has_null_verified_at(
        self,
        repository: AuthRepository,
        create_test_email_user,
    ):
        """Test that unverified user has null email_verified_at."""
        # Arrange
        _, email, _ = await create_test_email_user(email_verified=False)

        # Act
        result = await repository.get_user_by_email(email)

        # Assert
        assert result is not None
        assert result["email_verified_at"] is None

    async def test_verified_user_has_timestamp(
        self,
        repository: AuthRepository,
        create_test_email_user,
    ):
        """Test that verified user has email_verified_at timestamp."""
        # Arrange
        _, email, _ = await create_test_email_user(email_verified=True)

        # Act
        result = await repository.get_user_by_email(email)

        # Assert
        assert result is not None
        assert result["email_verified_at"] is not None
        assert isinstance(result["email_verified_at"], dt.datetime)


# ==============================================================================
# mark_email_verified TESTS
# ==============================================================================


class TestMarkEmailVerified:
    """Test mark_email_verified method."""

    async def test_sets_email_verified_timestamp(
        self,
        repository: AuthRepository,
        create_test_email_user,
    ):
        """Test that mark_email_verified sets timestamp."""
        # Arrange
        user_id, email, _ = await create_test_email_user(email_verified=False)

        # Verify initially not verified
        before = await repository.get_user_by_email(email)
        assert before["email_verified_at"] is None

        # Act
        await repository.mark_email_verified(user_id)

        # Assert
        after = await repository.get_user_by_email(email)
        assert after["email_verified_at"] is not None
        assert isinstance(after["email_verified_at"], dt.datetime)

    async def test_idempotent_can_call_multiple_times(
        self,
        repository: AuthRepository,
        create_test_email_user,
    ):
        """Test that mark_email_verified is idempotent."""
        # Arrange
        user_id, email, _ = await create_test_email_user(email_verified=False)

        # Act - Call multiple times
        await repository.mark_email_verified(user_id)
        first_timestamp = (await repository.get_user_by_email(email))["email_verified_at"]

        await repository.mark_email_verified(user_id)
        second_timestamp = (await repository.get_user_by_email(email))["email_verified_at"]

        # Assert - Both calls succeed, timestamp exists
        assert first_timestamp is not None
        assert second_timestamp is not None


# ==============================================================================
# update_password TESTS
# ==============================================================================


class TestUpdatePassword:
    """Test update_password method."""

    async def test_updates_password_hash(
        self,
        repository: AuthRepository,
        create_test_email_user,
    ):
        """Test that update_password updates the hash."""
        # Arrange
        user_id, email, old_hash = await create_test_email_user()
        new_hash = bcrypt.hashpw(b"newpassword456", bcrypt.gensalt()).decode()

        # Act
        await repository.update_password(user_id, new_hash)

        # Assert
        result = await repository.get_user_by_email(email)
        assert result["password_hash"] == new_hash
        assert result["password_hash"] != old_hash

    async def test_new_hash_persists(
        self,
        repository: AuthRepository,
        create_test_email_user,
    ):
        """Test that new password hash persists."""
        # Arrange
        user_id, email, _ = await create_test_email_user()
        new_hash = bcrypt.hashpw(b"newpassword789", bcrypt.gensalt()).decode()

        # Act
        await repository.update_password(user_id, new_hash)

        # Assert - Fetch again to verify persistence
        result = await repository.get_user_by_email(email)
        assert result["password_hash"] == new_hash


# ==============================================================================
# create_core_user TESTS
# ==============================================================================


class TestCreateCoreUser:
    """Test create_core_user method."""

    async def test_create_with_valid_data_succeeds(
        self,
        repository: AuthRepository,
        unique_user_id: int,
        asyncpg_conn,
    ):
        """Test creating core user with valid data succeeds."""
        # Arrange
        nickname = fake.user_name()

        # Act
        await repository.create_core_user(unique_user_id, nickname)

        # Assert - Verify user exists
        row = await asyncpg_conn.fetchrow(
            "SELECT id, nickname, global_name FROM core.users WHERE id = $1",
            unique_user_id,
        )
        assert row is not None
        assert row["id"] == unique_user_id
        assert row["nickname"] == nickname
        assert row["global_name"] == nickname

    async def test_duplicate_user_id_raises_error(
        self,
        repository: AuthRepository,
        create_test_user,
    ):
        """Test creating duplicate user_id raises UniqueConstraintViolationError."""
        # Arrange
        user_id = await create_test_user()
        another_nickname = fake.user_name()

        # Act & Assert
        with pytest.raises(UniqueConstraintViolationError) as exc_info:
            await repository.create_core_user(user_id, another_nickname)

        assert "core.users" in exc_info.value.table


# ==============================================================================
# generate_next_user_id TESTS
# ==============================================================================


class TestGenerateNextUserId:
    """Test generate_next_user_id method."""

    async def test_returns_unique_integer(
        self,
        repository: AuthRepository,
    ):
        """Test that generate_next_user_id returns unique integer."""
        # Act
        user_id = await repository.generate_next_user_id()

        # Assert
        assert isinstance(user_id, int)
        assert user_id > 0

    async def test_sequential_calls_return_different_ids(
        self,
        repository: AuthRepository,
    ):
        """Test that sequential calls return different IDs."""
        # Act
        id1 = await repository.generate_next_user_id()
        id2 = await repository.generate_next_user_id()
        id3 = await repository.generate_next_user_id()

        # Assert
        assert id1 != id2
        assert id2 != id3
        assert id1 != id3

    async def test_sequential_calls_generate_unique_ids(
        self,
        repository: AuthRepository,
    ):
        """Test that multiple sequential calls generate unique IDs."""
        # Act - Generate multiple IDs sequentially
        results = []
        for _ in range(10):
            user_id = await repository.generate_next_user_id()
            results.append(user_id)

        # Assert - All IDs are unique
        assert len(results) == 10
        assert len(set(results)) == 10  # All unique


# ==============================================================================
# get_auth_status TESTS
# ==============================================================================


class TestGetAuthStatus:
    """Test get_auth_status method."""

    async def test_returns_email_and_verification_status(
        self,
        repository: AuthRepository,
        create_test_email_user,
    ):
        """Test that get_auth_status returns email data."""
        # Arrange
        user_id, email, _ = await create_test_email_user(email_verified=True)

        # Act
        result = await repository.get_auth_status(user_id)

        # Assert
        assert result is not None
        assert result["email"].lower() == email.lower()
        assert result["email_verified_at"] is not None

    async def test_unverified_user_has_null_timestamp(
        self,
        repository: AuthRepository,
        create_test_email_user,
    ):
        """Test that unverified user has null email_verified_at."""
        # Arrange
        user_id, _, _ = await create_test_email_user(email_verified=False)

        # Act
        result = await repository.get_auth_status(user_id)

        # Assert
        assert result is not None
        assert result["email_verified_at"] is None

    async def test_user_without_email_auth_returns_none(
        self,
        repository: AuthRepository,
        create_test_user,
    ):
        """Test that user without email auth returns None."""
        # Arrange - Create user without email auth
        user_id = await create_test_user()

        # Act
        result = await repository.get_auth_status(user_id)

        # Assert
        assert result is None

    async def test_non_existent_user_returns_none(
        self,
        repository: AuthRepository,
    ):
        """Test that non-existent user returns None."""
        # Arrange
        fake_user_id = fake.random_int(min=100000000000000000, max=999999999999999999)

        # Act
        result = await repository.get_auth_status(fake_user_id)

        # Assert
        assert result is None
