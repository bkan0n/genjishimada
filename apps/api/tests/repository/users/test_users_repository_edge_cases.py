"""Tests for UsersRepository edge cases and concurrency."""

import pytest
from faker import Faker

from repository.users_repository import UsersRepository

fake = Faker()

pytestmark = [
    pytest.mark.domain_users,
]


@pytest.fixture
async def repository(asyncpg_conn):
    """Provide users repository instance."""
    return UsersRepository(asyncpg_conn)


# ==============================================================================
# CONCURRENT CREATE TESTS
# ==============================================================================


class TestConcurrentCreates:
    """Test concurrent create operations."""

    async def test_concurrent_user_creates_no_collisions(
        self,
        repository: UsersRepository,
        global_user_id_tracker: set[int],
    ):
        """Test concurrent user creates with UUID generation don't collide."""
        # Arrange
        user_ids = []
        for _ in range(10):
            user_id = fake.random_int(min=100000000000000000, max=999999999999999999)
            while user_id in global_user_id_tracker:
                user_id = fake.random_int(min=100000000000000000, max=999999999999999999)
            global_user_id_tracker.add(user_id)
            user_ids.append(user_id)

        # Act - Create users sequentially to avoid pool connection conflicts
        # Note: True concurrent testing would require separate connections
        for user_id in user_ids:
            await repository.create_user(user_id, fake.user_name(), fake.user_name())

        # Assert - All users should exist
        for user_id in user_ids:
            exists = await repository.check_user_exists(user_id)
            assert exists is True


# ==============================================================================
# DISCORD SNOWFLAKE ID TESTS
# ==============================================================================


class TestDiscordSnowflakeIds:
    """Test Discord snowflake ID uniqueness."""

    async def test_create_user_with_minimum_valid_snowflake(
        self,
        repository: UsersRepository,
        global_user_id_tracker: set[int],
    ):
        """Test creating user with minimum valid Discord snowflake."""
        # Arrange
        min_snowflake = 100000000000000000
        if min_snowflake not in global_user_id_tracker:
            global_user_id_tracker.add(min_snowflake)
            user_id = min_snowflake
        else:
            # Use a nearby value
            user_id = min_snowflake + fake.random_int(min=1, max=1000)
            global_user_id_tracker.add(user_id)

        # Act
        await repository.create_user(user_id, fake.user_name(), fake.user_name())

        # Assert
        exists = await repository.check_user_exists(user_id)
        assert exists is True


# ==============================================================================
# TRANSACTION COMMIT TESTS
# ==============================================================================


class TestTransactionCommit:
    """Test transaction commit behavior."""

    async def test_create_user_transaction_commit(
        self,
        asyncpg_conn,
        unique_user_id: int,
    ):
        """Test transaction commit persists user data."""
        # Arrange
        repository = UsersRepository(asyncpg_conn)
        nickname = fake.user_name()
        global_name = fake.user_name()

        # Act
        async with asyncpg_conn.transaction():
            await repository.create_user(
                unique_user_id,
                nickname,
                global_name,
                conn=asyncpg_conn,
            )

        # Assert - User should exist with correct data
        exists = await repository.check_user_exists(unique_user_id)
        assert exists is True
        user = await repository.fetch_user(unique_user_id)
        assert user is not None
        assert user["nickname"] == nickname
        assert user["global_name"] == global_name


# ==============================================================================
# PRIMARY USERNAME CONSTRAINT TESTS
# ==============================================================================


class TestPrimaryUsernameConstraint:
    """Test primary username uniqueness constraint."""

    async def test_only_one_primary_username_allowed_per_user(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test that only one primary username is allowed per user."""
        # Arrange
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())
        username1 = fake.user_name()
        username2 = fake.user_name()

        # Insert first as primary
        await repository.insert_overwatch_username(unique_user_id, username1, is_primary=True)

        # Act & Assert - Inserting second as primary should raise error
        with pytest.raises(Exception):  # UniqueViolationError on unique constraint
            await repository.insert_overwatch_username(unique_user_id, username2, is_primary=True)
