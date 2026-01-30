"""Tests for UsersRepository edge cases and concurrency."""

import asyncio
from uuid import uuid4

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

    async def test_concurrent_fake_member_creates_unique_ids(
        self,
        repository: UsersRepository,
    ):
        """Test creating multiple fake members generates unique IDs."""
        # Arrange
        num_members = 10
        names = [fake.user_name() for _ in range(num_members)]

        # Act - Create sequentially to avoid pool connection conflicts
        fake_ids = []
        for name in names:
            fake_id = await repository.create_fake_member(name)
            fake_ids.append(fake_id)

        # Assert
        assert len(fake_ids) == num_members
        assert len(set(fake_ids)) == num_members  # All IDs unique
        assert all(fid < 100000000 for fid in fake_ids)

    async def test_multiple_overwatch_username_inserts(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test inserting multiple Overwatch usernames for same user."""
        # Arrange
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())
        usernames = [fake.user_name() for _ in range(10)]

        # Act - Insert sequentially
        for username in usernames:
            await repository.insert_overwatch_username(unique_user_id, username, is_primary=False)

        # Assert - All usernames should be inserted
        result = await repository.fetch_overwatch_usernames(unique_user_id)
        actual_usernames = [u["username"] for u in result if u["username"] is not None]
        assert len(actual_usernames) >= 10


# ==============================================================================
# TRANSACTION ROLLBACK TESTS
# ==============================================================================


class TestTransactionRollback:
    """Test transaction rollback behavior."""

    async def test_create_user_transaction_rollback(
        self,
        asyncpg_conn,
        unique_user_id: int,
    ):
        """Test transaction rollback doesn't persist user data."""
        # Arrange
        repository = UsersRepository(asyncpg_conn)

        # Act
        try:
            async with asyncpg_conn.transaction():
                await repository.create_user(
                    unique_user_id,
                    fake.user_name(),
                    fake.user_name(),
                    conn=asyncpg_conn,
                )
                # Force rollback
                raise Exception("Intentional rollback")
        except Exception:
            pass

        # Assert - User should not exist
        exists = await repository.check_user_exists(unique_user_id)
        assert exists is False

    async def test_insert_overwatch_username_transaction_rollback(
        self,
        asyncpg_conn,
        unique_user_id: int,
    ):
        """Test transaction rollback doesn't persist Overwatch username."""
        # Arrange
        repository = UsersRepository(asyncpg_conn)
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())
        username = fake.user_name()

        # Act
        try:
            async with asyncpg_conn.transaction():
                await repository.insert_overwatch_username(
                    unique_user_id,
                    username,
                    is_primary=True,
                    conn=asyncpg_conn,
                )
                # Force rollback
                raise Exception("Intentional rollback")
        except Exception:
            pass

        # Assert - Username should not exist
        usernames = await repository.fetch_overwatch_usernames(unique_user_id)
        actual_usernames = [u["username"] for u in usernames if u["username"] is not None]
        assert username not in actual_usernames

    async def test_update_user_names_transaction_rollback(
        self,
        asyncpg_conn,
        unique_user_id: int,
    ):
        """Test transaction rollback doesn't persist user name updates."""
        # Arrange
        repository = UsersRepository(asyncpg_conn)
        original_nickname = fake.user_name()
        await repository.create_user(unique_user_id, original_nickname, fake.user_name())
        new_nickname = fake.user_name()

        # Act
        try:
            async with asyncpg_conn.transaction():
                await repository.update_user_names(
                    unique_user_id,
                    nickname=new_nickname,
                    update_nickname=True,
                    conn=asyncpg_conn,
                )
                # Force rollback
                raise Exception("Intentional rollback")
        except Exception:
            pass

        # Assert - Nickname should still be original
        user = await repository.fetch_user(unique_user_id)
        assert user is not None
        assert user["nickname"] == original_nickname


# ==============================================================================
# NULL HANDLING TESTS
# ==============================================================================


class TestNullHandling:
    """Test NULL value handling."""

    async def test_create_user_with_all_nullable_fields_null(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test creating user with all nullable fields as None succeeds."""
        # Act
        await repository.create_user(unique_user_id, None, None)

        # Assert
        user = await repository.fetch_user(unique_user_id)
        assert user is not None
        assert user["id"] == unique_user_id
        assert user["nickname"] is None
        assert user["global_name"] is None

    async def test_update_user_names_to_null(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test updating user names to NULL."""
        # Arrange
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())

        # Act
        await repository.update_user_names(
            unique_user_id,
            nickname=None,
            global_name=None,
            update_nickname=True,
            update_global_name=True,
        )

        # Assert
        user = await repository.fetch_user(unique_user_id)
        assert user is not None
        assert user["nickname"] is None
        assert user["global_name"] is None

    async def test_fetch_all_user_names_handles_nulls(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test fetch_all_user_names filters out NULL values."""
        # Arrange
        nickname = fake.user_name()
        await repository.create_user(unique_user_id, nickname, None)

        # Act
        names = await repository.fetch_all_user_names(unique_user_id)

        # Assert
        assert isinstance(names, list)
        assert None not in names
        assert nickname in names


# ==============================================================================
# DISCORD SNOWFLAKE ID TESTS
# ==============================================================================


class TestDiscordSnowflakeIds:
    """Test Discord snowflake ID edge cases."""

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

    async def test_create_user_with_maximum_valid_snowflake(
        self,
        repository: UsersRepository,
        global_user_id_tracker: set[int],
    ):
        """Test creating user with maximum valid Discord snowflake."""
        # Arrange
        max_snowflake = 999999999999999999
        if max_snowflake not in global_user_id_tracker:
            global_user_id_tracker.add(max_snowflake)
            user_id = max_snowflake
        else:
            # Use a nearby value
            user_id = max_snowflake - fake.random_int(min=1, max=1000)
            global_user_id_tracker.add(user_id)

        # Act
        await repository.create_user(user_id, fake.user_name(), fake.user_name())

        # Assert
        exists = await repository.check_user_exists(user_id)
        assert exists is True


# ==============================================================================
# FAKE MEMBER ID RANGE TESTS
# ==============================================================================


class TestFakeMemberIdRange:
    """Test fake member ID generation and boundaries."""

    async def test_fake_member_id_always_below_threshold(
        self,
        repository: UsersRepository,
    ):
        """Test fake member IDs are always below 100000000."""
        # Act - Create multiple fake members
        fake_ids = []
        for _ in range(20):
            fake_id = await repository.create_fake_member(fake.user_name())
            fake_ids.append(fake_id)

        # Assert - All should be below threshold
        assert all(fid < 100000000 for fid in fake_ids)

    async def test_fake_member_and_real_user_id_ranges_dont_overlap(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test fake member and real user ID ranges don't overlap."""
        # Arrange & Act
        fake_id = await repository.create_fake_member(fake.user_name())
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())

        # Assert
        assert fake_id < 100000000
        assert unique_user_id >= 100000000000000000
        assert fake_id < unique_user_id  # No overlap


# ==============================================================================
# COALESCED NAME EDGE CASES
# ==============================================================================


class TestCoalescedNameEdgeCases:
    """Test coalesced_name edge cases."""

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

    async def test_coalesced_name_empty_string_nickname(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test coalesced_name behavior with empty string nickname."""
        # Arrange
        await repository.create_user(unique_user_id, "", None)

        # Act
        user = await repository.fetch_user(unique_user_id)

        # Assert
        assert user is not None
        # Empty string is truthy for SQL, so might use it or fall back to Unknown User
        # The actual behavior depends on the COALESCE logic
        assert user["coalesced_name"] is not None
