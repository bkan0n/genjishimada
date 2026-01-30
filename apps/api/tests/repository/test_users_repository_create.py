"""Tests for UsersRepository create operations."""

from uuid import uuid4

import pytest
from faker import Faker

from repository.exceptions import UniqueConstraintViolationError
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
    """Test create_user method."""

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

    async def test_create_user_with_none_nickname(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test creating a user with None nickname succeeds."""
        # Arrange
        global_name = fake.user_name()

        # Act
        await repository.create_user(unique_user_id, None, global_name)

        # Assert
        user = await repository.fetch_user(unique_user_id)
        assert user is not None
        assert user["nickname"] is None
        assert user["global_name"] == global_name

    async def test_create_user_with_none_global_name(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test creating a user with None global_name succeeds."""
        # Arrange
        nickname = fake.user_name()

        # Act
        await repository.create_user(unique_user_id, nickname, None)

        # Assert
        user = await repository.fetch_user(unique_user_id)
        assert user is not None
        assert user["nickname"] == nickname
        assert user["global_name"] is None

    async def test_create_user_with_both_none(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test creating a user with both nickname and global_name as None succeeds."""
        # Act
        await repository.create_user(unique_user_id, None, None)

        # Assert
        user = await repository.fetch_user(unique_user_id)
        assert user is not None
        assert user["nickname"] is None
        assert user["global_name"] is None

    async def test_create_user_duplicate_id_raises_error(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test creating a user with duplicate ID raises UniqueConstraintViolationError."""
        # Arrange
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())

        # Act & Assert
        with pytest.raises(UniqueConstraintViolationError) as exc_info:
            await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())

        assert "users_pkey" in exc_info.value.constraint_name


# ==============================================================================
# CREATE FAKE MEMBER TESTS
# ==============================================================================


class TestCreateFakeMember:
    """Test create_fake_member method."""

    async def test_create_fake_member_returns_id_less_than_100m(
        self,
        repository: UsersRepository,
    ):
        """Test creating a fake member returns ID < 100000000."""
        # Arrange
        name = fake.user_name()

        # Act
        fake_user_id = await repository.create_fake_member(name)

        # Assert
        assert isinstance(fake_user_id, int)
        assert fake_user_id < 100000000

    async def test_create_fake_member_sets_name_correctly(
        self,
        repository: UsersRepository,
    ):
        """Test creating a fake member sets nickname and global_name to provided name."""
        # Arrange
        name = fake.user_name()

        # Act
        fake_user_id = await repository.create_fake_member(name)

        # Assert
        user = await repository.fetch_user(fake_user_id)
        assert user is not None
        assert user["nickname"] == name
        assert user["global_name"] == name

    async def test_create_multiple_fake_members_get_unique_ids(
        self,
        repository: UsersRepository,
    ):
        """Test creating multiple fake members generates unique IDs."""
        # Arrange
        num_members = 5
        fake_ids = []

        # Act
        for _ in range(num_members):
            name = fake.user_name()
            fake_id = await repository.create_fake_member(name)
            fake_ids.append(fake_id)

        # Assert
        assert len(fake_ids) == num_members
        assert len(set(fake_ids)) == num_members  # All IDs are unique
        assert all(fid < 100000000 for fid in fake_ids)


# ==============================================================================
# INSERT OVERWATCH USERNAME TESTS
# ==============================================================================


class TestInsertOverwatchUsername:
    """Test insert_overwatch_username method."""

    async def test_insert_overwatch_username_with_valid_user(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test inserting Overwatch username for valid user succeeds."""
        # Arrange
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())
        ow_username = fake.user_name()

        # Act
        await repository.insert_overwatch_username(unique_user_id, ow_username, is_primary=True)

        # Assert
        usernames = await repository.fetch_overwatch_usernames(unique_user_id)
        assert len(usernames) >= 1
        assert any(u["username"] == ow_username for u in usernames)

    async def test_insert_overwatch_username_with_invalid_user_id_raises_error(
        self,
        repository: UsersRepository,
    ):
        """Test inserting Overwatch username with non-existent user_id raises error."""
        # Arrange
        fake_user_id = 999999999999999999
        ow_username = fake.user_name()

        # Act & Assert
        with pytest.raises(Exception):  # asyncpg will raise ForeignKeyViolationError or similar
            await repository.insert_overwatch_username(fake_user_id, ow_username, is_primary=True)

    async def test_insert_multiple_overwatch_usernames_for_same_user(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test inserting multiple Overwatch usernames for same user succeeds."""
        # Arrange
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())
        username1 = fake.user_name()
        username2 = fake.user_name()
        username3 = fake.user_name()

        # Act
        await repository.insert_overwatch_username(unique_user_id, username1, is_primary=True)
        await repository.insert_overwatch_username(unique_user_id, username2, is_primary=False)
        await repository.insert_overwatch_username(unique_user_id, username3, is_primary=False)

        # Assert
        usernames = await repository.fetch_overwatch_usernames(unique_user_id)
        assert len(usernames) >= 3
        username_strs = [u["username"] for u in usernames]
        assert username1 in username_strs
        assert username2 in username_strs
        assert username3 in username_strs

    async def test_insert_overwatch_username_as_primary(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test inserting Overwatch username with is_primary=True sets flag correctly."""
        # Arrange
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())
        ow_username = fake.user_name()

        # Act
        await repository.insert_overwatch_username(unique_user_id, ow_username, is_primary=True)

        # Assert
        usernames = await repository.fetch_overwatch_usernames(unique_user_id)
        primary_username = next((u for u in usernames if u["username"] == ow_username), None)
        assert primary_username is not None
        assert primary_username["is_primary"] is True

    async def test_insert_overwatch_username_as_non_primary(
        self,
        repository: UsersRepository,
        unique_user_id: int,
    ):
        """Test inserting Overwatch username with is_primary=False sets flag correctly."""
        # Arrange
        await repository.create_user(unique_user_id, fake.user_name(), fake.user_name())
        ow_username = fake.user_name()

        # Act
        await repository.insert_overwatch_username(unique_user_id, ow_username, is_primary=False)

        # Assert
        usernames = await repository.fetch_overwatch_usernames(unique_user_id)
        non_primary_username = next((u for u in usernames if u["username"] == ow_username), None)
        assert non_primary_username is not None
        assert non_primary_username["is_primary"] is False
