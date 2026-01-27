"""Service layer for users domain business logic."""

from __future__ import annotations

import logging

import msgspec
from genjishimada_sdk.users import (
    UserCreateRequest,
    UserResponse,
    UserUpdateRequest,
)
from litestar.status_codes import HTTP_400_BAD_REQUEST

from repository.exceptions import UniqueConstraintViolationError
from repository.users_repository import UsersRepository
from services.base import BaseService
from utilities.errors import CustomHTTPException

log = logging.getLogger(__name__)


class UsersService(BaseService):
    """Service for users domain business logic."""

    def __init__(self, users_repo: UsersRepository) -> None:
        """Initialize service.

        Args:
            users_repo: Users repository instance.
        """
        self._users_repo = users_repo

    async def check_if_user_is_creator(self, user_id: int) -> bool:
        """Check if user is a creator.

        Args:
            user_id: The user ID to check.

        Returns:
            True if user is a creator, False otherwise.
        """
        return await self._users_repo.check_if_user_is_creator(user_id)

    async def update_user_names(self, user_id: int, data: UserUpdateRequest) -> None:
        """Update user names.

        Args:
            user_id: The user ID to update.
            data: Update payload with nickname and/or global_name.
        """
        is_nick_set = data.nickname is not msgspec.UNSET
        nick_val: str | None = None
        if is_nick_set:
            nick_val = data.nickname  # type: ignore[assignment]

        is_glob_set = data.global_name is not msgspec.UNSET
        glob_val: str | None = None
        if is_glob_set:
            glob_val = data.global_name  # type: ignore[assignment]

        if not (is_nick_set or is_glob_set):
            return

        await self._users_repo.update_user_names(
            user_id=user_id,
            nickname=nick_val,
            global_name=glob_val,
            update_nickname=is_nick_set,
            update_global_name=is_glob_set,
        )

    async def list_users(self) -> list[UserResponse] | None:
        """List all users with aggregated Overwatch usernames.

        Returns:
            List of users, or None if no users exist.
        """
        rows = await self._users_repo.fetch_users()
        return msgspec.convert(rows, list[UserResponse])

    async def get_user(self, user_id: int) -> UserResponse | None:
        """Get a single user by ID.

        Args:
            user_id: The user ID.

        Returns:
            User record, or None if not found.
        """
        row = await self._users_repo.fetch_user(user_id)
        if not row:
            return None
        return UserResponse(
            id=row["id"],
            nickname=row["nickname"],
            global_name=row["global_name"],
            coins=row["coins"],
            overwatch_usernames=row["overwatch_usernames"],
            coalesced_name=row["coalesced_name"],
        )

    async def user_exists(self, user_id: int) -> bool:
        """Check if a user exists.

        Args:
            user_id: The user ID.

        Returns:
            True if user exists, False otherwise.
        """
        return await self._users_repo.check_user_exists(user_id)

    async def create_user(self, data: UserCreateRequest) -> UserResponse:
        """Create a new user.

        Args:
            data: User creation payload.

        Returns:
            The created user record.

        Raises:
            CustomHTTPException: If user_id < 100000000 (use fake member endpoint).
            CustomHTTPException: If user_id already exists (users_pkey).
        """
        fake_user_id_limit = 100_000_000
        if data.id < fake_user_id_limit:
            raise CustomHTTPException(
                detail="Please use create fake member endpoint for user ids less than 100000000.",
                status_code=HTTP_400_BAD_REQUEST,
            )

        try:
            await self._users_repo.create_user(
                user_id=data.id,
                nickname=data.nickname,
                global_name=data.global_name,
            )
        except UniqueConstraintViolationError as e:
            if e.constraint_name == "users_pkey":
                raise CustomHTTPException(
                    detail="Provided user_id already exists.",
                    status_code=HTTP_400_BAD_REQUEST,
                    extra={"detail": e.detail},
                ) from e
            raise

        return UserResponse(
            id=data.id,
            nickname=data.nickname,
            global_name=data.global_name,
            coins=0,
            overwatch_usernames=[],
            coalesced_name=data.nickname,
        )
