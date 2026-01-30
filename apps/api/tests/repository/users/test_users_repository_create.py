"""Tests for UsersRepository create operations.

Following Users domain test reduction strategy:
- Focus on contract verification - does user creation work with various data?
- Trust database constraints (unique constraints, foreign keys)
- Keep 7 core tests that verify the contract
"""

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


def test_unique_user_id_fixture(unique_user_id: int):
    """Verify unique user ID generation works."""
    assert isinstance(unique_user_id, int)
    assert 100000000000000000 <= unique_user_id <= 999999999999999999
    assert len(str(unique_user_id)) == 18


# ==============================================================================
# CREATE USER TESTS
# ==============================================================================


class TestCreateUser:
    """Test create_user method - contract verification."""

    async def test_create_user_with_valid_data(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test creating a user with valid data succeeds."""
        # Arrange
        nickname = fake.user_name()
        global_name = fake.user_name()

        # Act
        await repository.create_user(unique_user_id, nickname, global_name)

        # Assert - Verify user was created
        exists = await repository.check_user_exists(unique_user_id)
        assert exists is True

    async def test_create_user_with_none_fields(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test creating a user with None nickname and global_name succeeds (defaults)."""
        # Act
        await repository.create_user(unique_user_id, None, None)

        # Assert
        user = await repository.fetch_user(unique_user_id)
        assert user is not None
        assert user["nickname"] is None
        assert user["global_name"] is None

    async def test_create_user_stores_all_fields_and_applies_defaults(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test creating a user stores all fields correctly and applies default values."""
        # Arrange
        nickname = fake.user_name()
        global_name = fake.user_name()

        # Act
        await repository.create_user(unique_user_id, nickname, global_name)

        # Assert - Verify all fields stored and defaults applied
        user = await repository.fetch_user(unique_user_id)
        assert user is not None
        assert user["id"] == unique_user_id
        assert user["nickname"] == nickname
        assert user["global_name"] == global_name
        assert user["coins"] == 0  # Default value


# ==============================================================================
# CREATE FAKE MEMBER TESTS
# ==============================================================================


class TestCreateFakeMember:
    """Test create_fake_member method - contract verification."""

    async def test_create_fake_member_generates_valid_id(
        self,
        repository: UsersRepository,
    ):
        """Test creating a fake member returns ID < 100000000 and sets name correctly."""
        # Arrange
        name = fake.user_name()

        # Act
        fake_user_id = await repository.create_fake_member(name)

        # Assert - Verify ID is in fake member range
        assert isinstance(fake_user_id, int)
        assert fake_user_id < 100000000

        # Verify user was created with correct data
        user = await repository.fetch_user(fake_user_id)
        assert user is not None
        assert user["nickname"] == name
        assert user["global_name"] == name


# ==============================================================================
# INSERT OVERWATCH USERNAME TESTS
# ==============================================================================


class TestInsertOverwatchUsername:
    """Test insert_overwatch_username method - contract verification."""

    async def test_insert_overwatch_username_with_profile_data(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test inserting Overwatch username creates profile association."""
        # Arrange
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())
        ow_username = fake.user_name()

        # Act
        await repository.insert_overwatch_username(unique_user_id, ow_username, is_primary=True)

        # Assert
        usernames = await repository.fetch_overwatch_usernames(unique_user_id)
        assert len(usernames) >= 1
        inserted = next((u for u in usernames if u["username"] == ow_username), None)
        assert inserted is not None
        assert inserted["is_primary"] is True

    async def test_insert_overwatch_username_with_settings(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test inserting Overwatch username with different is_primary settings."""
        # Arrange
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())
        primary_username = fake.user_name()
        secondary_username = fake.user_name()

        # Act
        await repository.insert_overwatch_username(unique_user_id, primary_username, is_primary=True)
        await repository.insert_overwatch_username(unique_user_id, secondary_username, is_primary=False)

        # Assert
        usernames = await repository.fetch_overwatch_usernames(unique_user_id)
        assert len(usernames) >= 2
        primary = next((u for u in usernames if u["username"] == primary_username), None)
        secondary = next((u for u in usernames if u["username"] == secondary_username), None)
        assert primary is not None and primary["is_primary"] is True
        assert secondary is not None and secondary["is_primary"] is False
