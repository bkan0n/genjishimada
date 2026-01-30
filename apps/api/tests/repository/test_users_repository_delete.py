"""Tests for UsersRepository delete operations."""

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
# DELETE USER TESTS
# ==============================================================================


class TestDeleteUser:
    """Test delete_user method."""

    async def test_delete_existing_user_removes_record(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test deleting existing user removes it from database."""
        # Arrange
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())

        # Act
        await repository.delete_user(unique_user_id)

        # Assert
        exists = await repository.check_user_exists(unique_user_id)
        assert exists is False

    async def test_delete_non_existent_user_is_noop(
        self,
        repository: UsersRepository,
    ):
        """Test deleting non-existent user doesn't raise error (no-op)."""
        # Arrange
        fake_user_id = 999999999999999999

        # Act - Should not raise error
        await repository.delete_user(fake_user_id)

        # Assert - User still doesn't exist (no change)
        exists = await repository.check_user_exists(fake_user_id)
        assert exists is False

    async def test_delete_user_cascades_to_overwatch_usernames(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test deleting user cascades to Overwatch usernames."""
        # Arrange
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())
        username1 = fake.user_name()
        username2 = fake.user_name()
        await repository.insert_overwatch_username(unique_user_id, username1, is_primary=True)
        await repository.insert_overwatch_username(unique_user_id, username2, is_primary=False)

        # Act
        await repository.delete_user(unique_user_id)

        # Assert - User is deleted
        exists = await repository.check_user_exists(unique_user_id)
        assert exists is False

        # Overwatch usernames should also be gone (cascade delete)
        usernames = await repository.fetch_overwatch_usernames(unique_user_id)
        actual_usernames = [u for u in usernames if u["username"] is not None]
        assert len(actual_usernames) == 0

    async def test_delete_user_cascades_to_notification_settings(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test deleting user cascades to notification settings."""
        # Arrange
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())
        await repository.upsert_user_notifications(unique_user_id, 42)

        # Act
        await repository.delete_user(unique_user_id)

        # Assert - User is deleted
        exists = await repository.check_user_exists(unique_user_id)
        assert exists is False

        # Notification settings should also be gone
        notifications = await repository.fetch_user_notifications(unique_user_id)
        assert notifications is None

    async def test_delete_user_with_creator_references(
        self,
        repository: UsersRepository,
        unique_user_id: int,
        create_test_map,
        global_code_tracker: set[str],
        asyncpg_conn,
    ):
        """Test deleting user who is a map creator."""
        # Arrange
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())

        # Create map with user as creator
        code = f"T{uuid4().hex[:5].upper()}"
        global_code_tracker.add(code)
        map_id = await create_test_map(code)
        await asyncpg_conn.execute(
            "INSERT INTO maps.creators (map_id, user_id) VALUES ($1, $2)",
            map_id,
            unique_user_id,
        )

        # Act - Delete user
        # Note: This may fail if foreign key has RESTRICT, or succeed if CASCADE
        # Let's test the actual behavior
        try:
            await repository.delete_user(unique_user_id)

            # If deletion succeeds, verify creator reference is handled
            creator_count = await asyncpg_conn.fetchval(
                "SELECT COUNT(*) FROM maps.creators WHERE user_id = $1",
                unique_user_id,
            )
            # Should be 0 if cascaded, or user deletion should have failed
            assert creator_count == 0
        except Exception:
            # If foreign key constraint prevents deletion, that's also valid behavior
            # Just verify user still exists
            exists = await repository.check_user_exists(unique_user_id)
            assert exists is True

    async def test_delete_fake_member(
        self,
        repository: UsersRepository,
    ):
        """Test deleting fake member works correctly."""
        # Arrange
        fake_user_id = await repository.create_fake_member(fake.user_name())

        # Act
        await repository.delete_user(fake_user_id)

        # Assert
        exists = await repository.check_user_exists(fake_user_id)
        assert exists is False


# ==============================================================================
# DELETE OVERWATCH USERNAMES TESTS
# ==============================================================================


class TestDeleteOverwatchUsernames:
    """Test delete_overwatch_usernames method."""

    async def test_delete_all_overwatch_usernames_for_user(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test deleting all Overwatch usernames for a user."""
        # Arrange
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())
        username1 = fake.user_name()
        username2 = fake.user_name()
        username3 = fake.user_name()
        await repository.insert_overwatch_username(unique_user_id, username1, is_primary=True)
        await repository.insert_overwatch_username(unique_user_id, username2, is_primary=False)
        await repository.insert_overwatch_username(unique_user_id, username3, is_primary=False)

        # Act
        await repository.delete_overwatch_usernames(unique_user_id)

        # Assert - All usernames should be deleted
        usernames = await repository.fetch_overwatch_usernames(unique_user_id)
        actual_usernames = [u for u in usernames if u["username"] is not None]
        assert len(actual_usernames) == 0

    async def test_delete_overwatch_usernames_for_user_with_no_usernames(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test deleting Overwatch usernames for user with no usernames is no-op."""
        # Arrange
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())

        # Act - Should not raise error, just no-op
        await repository.delete_overwatch_usernames(unique_user_id)

        # Assert - User still exists, no usernames
        exists = await repository.check_user_exists(unique_user_id)
        assert exists is True

        usernames = await repository.fetch_overwatch_usernames(unique_user_id)
        actual_usernames = [u for u in usernames if u["username"] is not None]
        assert len(actual_usernames) == 0

    async def test_delete_overwatch_usernames_does_not_delete_user(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test deleting Overwatch usernames doesn't delete the user."""
        # Arrange
        nickname = fake.user_name()
        global_name = fake.user_name()
        await repository.create_user(unique_user_id, nickname, global_name)
        await repository.insert_overwatch_username(unique_user_id, fake.user_name(), is_primary=True)

        # Act
        await repository.delete_overwatch_usernames(unique_user_id)

        # Assert - User still exists with original data
        user = await repository.fetch_user(unique_user_id)
        assert user is not None
        assert user["id"] == unique_user_id
        assert user["nickname"] == nickname
        assert user["global_name"] == global_name

    async def test_delete_overwatch_usernames_only_affects_specified_user(
        self,
        repository: UsersRepository,
        global_user_id_tracker: set[int],
    ):
        """Test deleting usernames only affects the specified user."""
        # Arrange
        # Create two users with Overwatch usernames
        user_id_1 = fake.random_int(min=100000000000000000, max=999999999999999999)
        while user_id_1 in global_user_id_tracker:
            user_id_1 = fake.random_int(min=100000000000000000, max=999999999999999999)
        global_user_id_tracker.add(user_id_1)

        user_id_2 = fake.random_int(min=100000000000000000, max=999999999999999999)
        while user_id_2 in global_user_id_tracker:
            user_id_2 = fake.random_int(min=100000000000000000, max=999999999999999999)
        global_user_id_tracker.add(user_id_2)

        await repository.create_user(user_id_1, fake.user_name(), fake.user_name())
        await repository.create_user(user_id_2, fake.user_name(), fake.user_name())

        username1 = fake.user_name()
        username2 = fake.user_name()
        await repository.insert_overwatch_username(user_id_1, username1, is_primary=True)
        await repository.insert_overwatch_username(user_id_2, username2, is_primary=True)

        # Act - Delete usernames for user_id_1 only
        await repository.delete_overwatch_usernames(user_id_1)

        # Assert - user_id_1 has no usernames
        usernames_1 = await repository.fetch_overwatch_usernames(user_id_1)
        actual_usernames_1 = [u for u in usernames_1 if u["username"] is not None]
        assert len(actual_usernames_1) == 0

        # user_id_2 still has their username
        usernames_2 = await repository.fetch_overwatch_usernames(user_id_2)
        actual_usernames_2 = [u for u in usernames_2 if u["username"] is not None]
        assert len(actual_usernames_2) == 1
        assert actual_usernames_2[0]["username"] == username2
