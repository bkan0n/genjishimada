"""Tests for UsersRepository delete operations."""

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
