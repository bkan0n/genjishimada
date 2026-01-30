"""Tests for UsersRepository read operations."""

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
# CHECK USER EXISTS TESTS
# ==============================================================================


class TestCheckUserExists:
    """Test check_user_exists method."""

    async def test_check_existing_user_returns_true(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test checking existing user returns True."""
        # Arrange
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())

        # Act
        exists = await repository.check_user_exists(unique_user_id)

        # Assert
        assert exists is True

    async def test_check_non_existent_user_returns_false(
        self,
        repository: UsersRepository,
    ):
        """Test checking non-existent user returns False."""
        # Arrange
        fake_user_id = 999999999999999999

        # Act
        exists = await repository.check_user_exists(fake_user_id)

        # Assert
        assert exists is False


# ==============================================================================
# CHECK IF USER IS CREATOR TESTS
# ==============================================================================


class TestCheckIfUserIsCreator:
    """Test check_if_user_is_creator method."""

    async def test_check_creator_returns_true(
        self,
        repository: UsersRepository,
        unique_user_id: int,
        create_test_map,
        global_code_tracker: set[str],
        asyncpg_conn,
    ):
        """Test checking user who is a creator returns True."""
        # Arrange
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())

        # Create a map with this user as creator
        code = f"T{uuid4().hex[:5].upper()}"
        global_code_tracker.add(code)
        map_id = await create_test_map(code)

        # Insert user as creator
        await asyncpg_conn.execute(
            "INSERT INTO maps.creators (map_id, user_id) VALUES ($1, $2)",
            map_id,
            unique_user_id,
        )

        # Act
        is_creator = await repository.check_if_user_is_creator(unique_user_id)

        # Assert
        assert is_creator is True

    async def test_check_non_creator_returns_false(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test checking user who is not a creator returns False."""
        # Arrange
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())

        # Act
        is_creator = await repository.check_if_user_is_creator(unique_user_id)

        # Assert
        assert is_creator is False


# ==============================================================================
# FETCH USER TESTS
# ==============================================================================


class TestFetchUser:
    """Test fetch_user method."""

    async def test_fetch_existing_user_returns_user(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test fetching existing user returns user dict."""
        # Arrange
        nickname = fake.user_name()
        global_name = fake.user_name()
        await repository.create_user(unique_user_id, nickname, global_name)

        # Act
        user = await repository.fetch_user(unique_user_id)

        # Assert
        assert user is not None
        assert user["id"] == unique_user_id
        assert user["nickname"] == nickname
        assert user["global_name"] == global_name
        assert "coins" in user
        assert "overwatch_usernames" in user
        assert "coalesced_name" in user

    async def test_fetch_non_existent_user_returns_none(
        self,
        repository: UsersRepository,
    ):
        """Test fetching non-existent user returns None."""
        # Arrange
        fake_user_id = 999999999999999999

        # Act
        user = await repository.fetch_user(fake_user_id)

        # Assert
        assert user is None

    async def test_fetch_user_with_overwatch_usernames(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test fetching user with Overwatch usernames includes them in result."""
        # Arrange
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())
        username1 = fake.user_name()
        username2 = fake.user_name()
        await repository.insert_overwatch_username(unique_user_id, username1, is_primary=True)
        await repository.insert_overwatch_username(unique_user_id, username2, is_primary=False)

        # Act
        user = await repository.fetch_user(unique_user_id)

        # Assert
        assert user is not None
        assert user["overwatch_usernames"] is not None
        assert len(user["overwatch_usernames"]) >= 2
        assert username1 in user["overwatch_usernames"]
        assert username2 in user["overwatch_usernames"]

    async def test_fetch_user_without_overwatch_usernames(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test fetching user without Overwatch usernames has None for usernames."""
        # Arrange
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())

        # Act
        user = await repository.fetch_user(unique_user_id)

        # Assert
        assert user is not None
        assert user["overwatch_usernames"] is None

    async def test_fetch_user_coalesced_name_uses_primary_username(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test coalesced_name uses primary Overwatch username when available."""
        # Arrange
        nickname = fake.user_name()
        global_name = fake.user_name()
        primary_username = fake.user_name()
        await repository.create_user(unique_user_id, nickname, global_name)
        await repository.insert_overwatch_username(unique_user_id, primary_username, is_primary=True)

        # Act
        user = await repository.fetch_user(unique_user_id)

        # Assert
        assert user is not None
        assert user["coalesced_name"] == primary_username

    async def test_fetch_user_coalesced_name_falls_back_to_nickname(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test coalesced_name falls back to nickname when no Overwatch username."""
        # Arrange
        nickname = fake.user_name()
        await repository.create_user(unique_user_id, nickname, None)

        # Act
        user = await repository.fetch_user(unique_user_id)

        # Assert
        assert user is not None
        assert user["coalesced_name"] == nickname

    async def test_fetch_user_coalesced_name_falls_back_to_global_name(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test coalesced_name falls back to global_name when no username or nickname."""
        # Arrange
        global_name = fake.user_name()
        await repository.create_user(unique_user_id, None, global_name)

        # Act
        user = await repository.fetch_user(unique_user_id)

        # Assert
        assert user is not None
        assert user["coalesced_name"] == global_name

    async def test_fetch_user_coalesced_name_defaults_to_unknown_user(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test coalesced_name defaults to 'Unknown User' when all fields are None."""
        # Arrange
        await repository.create_user(unique_user_id, None, None)

        # Act
        user = await repository.fetch_user(unique_user_id)

        # Assert
        assert user is not None
        assert user["coalesced_name"] == "Unknown User"


# ==============================================================================
# FETCH USERS TESTS
# ==============================================================================


class TestFetchUsers:
    """Test fetch_users method."""

    async def test_fetch_users_returns_all_users(
        self,
        repository: UsersRepository,
        global_user_id_tracker: set[int],
    ):
        """Test fetching users returns all users."""
        # Arrange
        user_ids = []
        for _ in range(3):
            user_id = fake.random_int(min=100000000000000000, max=999999999999999999)
            while user_id in global_user_id_tracker:
                user_id = fake.random_int(min=100000000000000000, max=999999999999999999)
            global_user_id_tracker.add(user_id)
            user_ids.append(user_id)
            await repository.create_user(user_id, fake.user_name(), fake.user_name())

        # Act
        users = await repository.fetch_users()

        # Assert
        assert isinstance(users, list)
        assert len(users) >= 3
        returned_ids = [u["id"] for u in users]
        for user_id in user_ids:
            assert user_id in returned_ids

    async def test_fetch_users_includes_overwatch_usernames(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test fetching users includes aggregated Overwatch usernames."""
        # Arrange
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())
        username = fake.user_name()
        await repository.insert_overwatch_username(unique_user_id, username, is_primary=True)

        # Act
        users = await repository.fetch_users()

        # Assert
        user = next((u for u in users if u["id"] == unique_user_id), None)
        assert user is not None
        assert user["overwatch_usernames"] is not None
        assert username in user["overwatch_usernames"]


# ==============================================================================
# FETCH OVERWATCH USERNAMES TESTS
# ==============================================================================


class TestFetchOverwatchUsernames:
    """Test fetch_overwatch_usernames method."""

    async def test_fetch_overwatch_usernames_returns_all_usernames(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test fetching Overwatch usernames returns all usernames for user."""
        # Arrange
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())
        username1 = fake.user_name()
        username2 = fake.user_name()
        username3 = fake.user_name()
        await repository.insert_overwatch_username(unique_user_id, username1, is_primary=True)
        await repository.insert_overwatch_username(unique_user_id, username2, is_primary=False)
        await repository.insert_overwatch_username(unique_user_id, username3, is_primary=False)

        # Act
        usernames = await repository.fetch_overwatch_usernames(unique_user_id)

        # Assert
        assert len(usernames) >= 3
        username_strs = [u["username"] for u in usernames]
        assert username1 in username_strs
        assert username2 in username_strs
        assert username3 in username_strs

    async def test_fetch_overwatch_usernames_ordered_by_is_primary(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test Overwatch usernames are ordered by is_primary DESC."""
        # Arrange
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())
        primary_username = fake.user_name()
        secondary_username = fake.user_name()
        await repository.insert_overwatch_username(unique_user_id, secondary_username, is_primary=False)
        await repository.insert_overwatch_username(unique_user_id, primary_username, is_primary=True)

        # Act
        usernames = await repository.fetch_overwatch_usernames(unique_user_id)

        # Assert
        assert len(usernames) >= 2
        # Primary username should be first
        assert usernames[0]["username"] == primary_username
        assert usernames[0]["is_primary"] is True

    async def test_fetch_overwatch_usernames_for_user_with_no_usernames(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test fetching Overwatch usernames for user with no usernames returns empty list."""
        # Arrange
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())

        # Act
        usernames = await repository.fetch_overwatch_usernames(unique_user_id)

        # Assert
        assert isinstance(usernames, list)
        # Note: The query has a LEFT JOIN so it might return one row with None values
        # We need to filter out rows where username is None
        actual_usernames = [u for u in usernames if u["username"] is not None]
        assert len(actual_usernames) == 0


# ==============================================================================
# FETCH ALL USER NAMES TESTS
# ==============================================================================


class TestFetchAllUserNames:
    """Test fetch_all_user_names method."""

    async def test_fetch_all_user_names_includes_all_sources(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test fetching all user names includes names from all sources."""
        # Arrange
        nickname = fake.user_name()
        global_name = fake.user_name()
        ow_username = fake.user_name()
        await repository.create_user(unique_user_id, nickname, global_name)
        await repository.insert_overwatch_username(unique_user_id, ow_username, is_primary=True)

        # Act
        names = await repository.fetch_all_user_names(unique_user_id)

        # Assert
        assert isinstance(names, list)
        assert len(names) >= 3
        assert nickname in names
        assert global_name in names
        assert ow_username in names

    async def test_fetch_all_user_names_removes_duplicates(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test fetching all user names removes duplicate names."""
        # Arrange
        same_name = fake.user_name()
        await repository.create_user(unique_user_id, same_name, same_name)
        await repository.insert_overwatch_username(unique_user_id, same_name, is_primary=True)

        # Act
        names = await repository.fetch_all_user_names(unique_user_id)

        # Assert
        assert isinstance(names, list)
        # Should only have one instance of the name despite it being in all fields
        assert names.count(same_name) == 1

    async def test_fetch_all_user_names_filters_none_values(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test fetching all user names filters out None values."""
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
# FETCH USER NOTIFICATIONS TESTS
# ==============================================================================


class TestFetchUserNotifications:
    """Test fetch_user_notifications method."""

    async def test_fetch_user_notifications_returns_flags(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test fetching user notifications returns bitmask flags."""
        # Arrange
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())
        flags = 42  # Example bitmask
        await repository.upsert_user_notifications(unique_user_id, flags)

        # Act
        result = await repository.fetch_user_notifications(unique_user_id)

        # Assert
        assert result == flags

    async def test_fetch_user_notifications_for_user_without_settings_returns_none(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test fetching notifications for user without settings returns None."""
        # Arrange
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())

        # Act
        result = await repository.fetch_user_notifications(unique_user_id)

        # Assert
        assert result is None
