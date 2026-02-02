"""Unit tests for UsersService."""

import pytest
from genjishimada_sdk.users import (
    UserCreateRequest,
    UserUpdateRequest,
)

from repository.exceptions import UniqueConstraintViolationError
from services.exceptions.users import InvalidUserIdError, UserAlreadyExistsError
from services.users_service import UsersService

pytestmark = [
    pytest.mark.domain_users,
]


class TestUsersServiceValidation:
    """Test validation logic in UsersService."""

    async def test_create_user_valid_id_succeeds(self, mock_pool, mock_state, mock_users_repo):
        """User ID >= 100000000 passes validation."""
        service = UsersService(mock_pool, mock_state, mock_users_repo)
        mock_users_repo.create_user.return_value = None

        data = UserCreateRequest(
            id=100_000_000,
            nickname="testuser",
            global_name="Test User",
        )

        result = await service.create_user(data)

        assert result.id == 100_000_000
        assert result.nickname == "testuser"
        assert result.global_name == "Test User"
        mock_users_repo.create_user.assert_called_once_with(
            user_id=100_000_000,
            nickname="testuser",
            global_name="Test User",
        )

    async def test_create_user_invalid_id_raises_error(self, mock_pool, mock_state, mock_users_repo):
        """User ID < 100000000 raises InvalidUserIdError."""
        service = UsersService(mock_pool, mock_state, mock_users_repo)

        data = UserCreateRequest(
            id=99_999_999,
            nickname="testuser",
            global_name="Test User",
        )

        with pytest.raises(InvalidUserIdError):
            await service.create_user(data)

        # Repository should NOT be called
        mock_users_repo.create_user.assert_not_called()


class TestUsersServiceUserCreation:
    """Test user creation business logic."""

    async def test_create_user_success_returns_response(self, mock_pool, mock_state, mock_users_repo):
        """Successful user creation returns UserResponse."""
        service = UsersService(mock_pool, mock_state, mock_users_repo)
        mock_users_repo.create_user.return_value = None

        data = UserCreateRequest(
            id=123_456_789,
            nickname="newuser",
            global_name="New User",
        )

        result = await service.create_user(data)

        assert result.id == 123_456_789
        assert result.nickname == "newuser"
        assert result.global_name == "New User"
        assert result.coins == 0
        assert result.overwatch_usernames == []
        assert result.coalesced_name == "newuser"

    async def test_create_user_duplicate_raises_user_already_exists_error(self, mock_pool, mock_state, mock_users_repo):
        """Duplicate user ID raises UserAlreadyExistsError."""
        service = UsersService(mock_pool, mock_state, mock_users_repo)
        mock_users_repo.create_user.side_effect = UniqueConstraintViolationError("users_pkey", "users")

        data = UserCreateRequest(
            id=123_456_789,
            nickname="duplicate",
            global_name="Duplicate User",
        )

        with pytest.raises(UserAlreadyExistsError):
            await service.create_user(data)


class TestUsersServiceErrorTranslation:
    """Test repository exception translation to domain exceptions."""

    async def test_create_user_unique_constraint_on_pkey_raises_user_already_exists(
        self, mock_pool, mock_state, mock_users_repo
    ):
        """UniqueConstraintViolationError on users_pkey raises UserAlreadyExistsError."""
        service = UsersService(mock_pool, mock_state, mock_users_repo)
        mock_users_repo.create_user.side_effect = UniqueConstraintViolationError("users_pkey", "users")

        data = UserCreateRequest(
            id=100_000_001,
            nickname="testuser",
            global_name="Test",
        )

        with pytest.raises(UserAlreadyExistsError):
            await service.create_user(data)

    async def test_create_user_unique_constraint_other_reraises(self, mock_pool, mock_state, mock_users_repo):
        """UniqueConstraintViolationError on other constraint re-raises."""
        service = UsersService(mock_pool, mock_state, mock_users_repo)
        mock_users_repo.create_user.side_effect = UniqueConstraintViolationError("some_other_constraint", "users")

        data = UserCreateRequest(
            id=100_000_001,
            nickname="testuser",
            global_name="Test",
        )

        with pytest.raises(UniqueConstraintViolationError):
            await service.create_user(data)


class TestUsersServiceOverwatchUsernames:
    """Test Overwatch username data transformation."""

    async def test_get_overwatch_usernames_response_empty_list(self, mock_pool, mock_state, mock_users_repo):
        """Empty username list returns all None."""
        service = UsersService(mock_pool, mock_state, mock_users_repo)
        mock_users_repo.fetch_overwatch_usernames.return_value = []

        result = await service.get_overwatch_usernames_response(user_id=123)

        assert result.user_id == 123
        assert result.primary is None
        assert result.secondary is None
        assert result.tertiary is None

    async def test_get_overwatch_usernames_response_one_username(self, mock_pool, mock_state, mock_users_repo):
        """One username sets primary only."""
        service = UsersService(mock_pool, mock_state, mock_users_repo)
        mock_users_repo.fetch_overwatch_usernames.return_value = [
            {"username": "Player1", "is_primary": True},
        ]

        result = await service.get_overwatch_usernames_response(user_id=123)

        assert result.primary == "Player1"
        assert result.secondary is None
        assert result.tertiary is None

    async def test_get_overwatch_usernames_response_two_usernames(self, mock_pool, mock_state, mock_users_repo):
        """Two usernames sets primary and secondary."""
        service = UsersService(mock_pool, mock_state, mock_users_repo)
        mock_users_repo.fetch_overwatch_usernames.return_value = [
            {"username": "Player1", "is_primary": True},
            {"username": "Player2", "is_primary": False},
        ]

        result = await service.get_overwatch_usernames_response(user_id=123)

        assert result.primary == "Player1"
        assert result.secondary == "Player2"
        assert result.tertiary is None

    async def test_get_overwatch_usernames_response_three_usernames(self, mock_pool, mock_state, mock_users_repo):
        """Three usernames sets all fields."""
        service = UsersService(mock_pool, mock_state, mock_users_repo)
        mock_users_repo.fetch_overwatch_usernames.return_value = [
            {"username": "Player1", "is_primary": True},
            {"username": "Player2", "is_primary": False},
            {"username": "Player3", "is_primary": False},
        ]

        result = await service.get_overwatch_usernames_response(user_id=123)

        assert result.primary == "Player1"
        assert result.secondary == "Player2"
        assert result.tertiary == "Player3"


class TestUsersServiceUpdateNames:
    """Test user name update logic with msgspec.UNSET handling."""

    async def test_update_user_names_both_fields_set(self, mock_pool, mock_state, mock_users_repo):
        """Both nickname and global_name update when set."""
        service = UsersService(mock_pool, mock_state, mock_users_repo)
        mock_users_repo.update_user_names.return_value = None

        data = UserUpdateRequest(
            nickname="newnick",
            global_name="New Global",
        )

        await service.update_user_names(user_id=123, data=data)

        mock_users_repo.update_user_names.assert_called_once_with(
            user_id=123,
            nickname="newnick",
            global_name="New Global",
            update_nickname=True,
            update_global_name=True,
        )

    async def test_update_user_names_only_nickname_set(self, mock_pool, mock_state, mock_users_repo):
        """Only nickname updates when global_name is UNSET."""
        service = UsersService(mock_pool, mock_state, mock_users_repo)
        mock_users_repo.update_user_names.return_value = None

        data = UserUpdateRequest(nickname="newnick")

        await service.update_user_names(user_id=123, data=data)

        mock_users_repo.update_user_names.assert_called_once_with(
            user_id=123,
            nickname="newnick",
            global_name=None,
            update_nickname=True,
            update_global_name=False,
        )

    async def test_update_user_names_only_global_name_set(self, mock_pool, mock_state, mock_users_repo):
        """Only global_name updates when nickname is UNSET."""
        service = UsersService(mock_pool, mock_state, mock_users_repo)
        mock_users_repo.update_user_names.return_value = None

        data = UserUpdateRequest(global_name="New Global")

        await service.update_user_names(user_id=123, data=data)

        mock_users_repo.update_user_names.assert_called_once_with(
            user_id=123,
            nickname=None,
            global_name="New Global",
            update_nickname=False,
            update_global_name=True,
        )

    async def test_update_user_names_both_unset_does_nothing(self, mock_pool, mock_state, mock_users_repo):
        """When both fields are UNSET, no repository call is made."""
        service = UsersService(mock_pool, mock_state, mock_users_repo)

        data = UserUpdateRequest()

        await service.update_user_names(user_id=123, data=data)

        mock_users_repo.update_user_names.assert_not_called()

    async def test_update_user_names_null_values_allowed(self, mock_pool, mock_state, mock_users_repo):
        """Null values can be set explicitly."""
        service = UsersService(mock_pool, mock_state, mock_users_repo)
        mock_users_repo.update_user_names.return_value = None

        data = UserUpdateRequest(nickname=None, global_name=None)

        await service.update_user_names(user_id=123, data=data)

        mock_users_repo.update_user_names.assert_called_once_with(
            user_id=123,
            nickname=None,
            global_name=None,
            update_nickname=True,
            update_global_name=True,
        )
