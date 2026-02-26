"""Users v3 controller."""

from __future__ import annotations

import logging
from typing import Annotated

import litestar
from asyncpg import Connection
from genjishimada_sdk.users import (
    OverwatchUsernamesResponse,
    OverwatchUsernamesUpdateRequest,
    RankDetailResponse,
    UserCreateRequest,
    UserResponse,
    UserUpdateRequest,
)
from litestar.di import Provide
from litestar.exceptions import HTTPException
from litestar.params import Body
from litestar.response import Response
from litestar.status_codes import HTTP_200_OK, HTTP_400_BAD_REQUEST, HTTP_404_NOT_FOUND, HTTP_409_CONFLICT
from msgspec import UNSET

from repository.users_repository import provide_users_repository
from services.exceptions.users import (
    DuplicateOverwatchUsernameError,
    InvalidUserIdError,
    UserAlreadyExistsError,
    UserNotFoundError,
)
from services.users_service import UsersService, provide_users_service
from utilities.errors import CustomHTTPException

log = logging.getLogger(__name__)


class UsersController(litestar.Controller):
    """Users v3 controller."""

    tags = ["Users"]
    path = "/users"
    dependencies = {
        "users_repo": Provide(provide_users_repository),
        "svc": Provide(provide_users_service),
    }

    @litestar.get(
        path="/{user_id:int}/creator",
        summary="Check If User Is Creator",
        description="Check if user is a creator.",
    )
    async def check_if_user_is_creator(self, svc: UsersService, user_id: int) -> bool:
        """Check if user is a creator.

        Args:
            svc: Users service.
            user_id: The user ID to check.

        Returns:
            True if user is a creator.
        """
        return await svc.check_if_user_is_creator(user_id)

    @litestar.patch(
        path="/{user_id:int}",
        summary="Update User Names",
        description="Update the global name and nickname for a user.",
    )
    async def update_user_names(self, user_id: int, data: UserUpdateRequest, svc: UsersService) -> None:
        """Update user names.

        Args:
            user_id: The user ID to edit.
            data: The payload for updating user names.
            svc: Users service.

        Raises:
            HTTPException: If data has no set values.
        """
        if data.global_name == UNSET and data.nickname == UNSET:
            raise HTTPException(
                detail="You must set either nickname or global_name.",
                status_code=HTTP_400_BAD_REQUEST,
            )
        return await svc.update_user_names(user_id, data)

    @litestar.get(
        path="/",
        summary="List Users",
        description="Fetch all users with their basic fields and aggregated Overwatch usernames.",
    )
    async def get_users(self, svc: UsersService) -> list[UserResponse] | None:
        """Get all users.

        Args:
            svc: Users service.

        Returns:
            List of users with aggregated Overwatch usernames; None only if no rows.
        """
        return await svc.list_users()

    @litestar.get(
        path="/{user_id:int}",
        summary="Get User",
        description=(
            "Fetch a single user by ID. Returns nickname, global name, coins, aggregated Overwatch usernames, "
            "and a `coalesced_name` preferring primary OW username, then nickname, then global name."
        ),
    )
    async def get_user(self, svc: UsersService, user_id: int) -> UserResponse | None:
        """Get user.

        Args:
            svc: Users service.
            user_id: The user ID.

        Returns:
            The user if found; otherwise None.
        """
        return await svc.get_user(user_id)

    @litestar.get(
        path="/{user_id:int}/exists",
        summary="Check User Exists",
        description="Return a boolean indicating whether a user with the given ID exists.",
    )
    async def check_user_exists(self, svc: UsersService, user_id: int) -> bool:
        """Check if a user exists.

        Args:
            svc: Users service.
            user_id: The user ID.

        Returns:
            True if the user exists; otherwise False.
        """
        return await svc.user_exists(user_id)

    @litestar.post(
        path="/",
        summary="Create User",
        description=(
            "Create a new user with the provided ID, nickname, and global name. "
            "If the user already exists, this is a no-op. Duplicate primary keys are reported with a 400."
        ),
    )
    async def create_user(self, svc: UsersService, data: UserCreateRequest) -> UserResponse:
        """Create new user.

        Args:
            svc: Users service.
            data: The user payload.

        Returns:
            The created (or existing) user with default fields.

        Raises:
            HTTPException: 400 if user_id is invalid (< 100000000).
            HTTPException: 409 if user already exists.
        """
        try:
            return await svc.create_user(data)
        except InvalidUserIdError as e:
            raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(e)) from e
        except UserAlreadyExistsError as e:
            raise HTTPException(status_code=HTTP_409_CONFLICT, detail=str(e)) from e

    @litestar.put(
        path="/{user_id:int}/overwatch",
        summary="Replace Overwatch Usernames",
        description=(
            "Replace the Overwatch usernames for a user. "
            "This clears all existing entries and inserts the provided list. "
            "Use `is_primary` on exactly one entry to mark it as primary."
        ),
    )
    async def update_overwatch_usernames(
        self,
        svc: UsersService,
        user_id: int,
        data: Annotated[OverwatchUsernamesUpdateRequest, Body(title="User Overwatch Usernames")],
    ) -> Response:
        """Update the Overwatch usernames for a specific user.

        Args:
            svc: The user service.
            user_id: The user ID.
            data: The new usernames payload.

        Returns:
            Response with success status.
        """
        try:
            log.debug("Set Overwatch usernames for user %s: %s", user_id, data.usernames)
            await svc.set_overwatch_usernames(user_id, data.usernames)
            return Response({"success": True}, status_code=HTTP_200_OK)
        except UserNotFoundError as e:
            raise HTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=str(e),
            ) from e
        except DuplicateOverwatchUsernameError as e:
            raise HTTPException(
                status_code=HTTP_400_BAD_REQUEST,
                detail=str(e),
            ) from e

    @litestar.get(
        path="/{user_id:int}/overwatch",
        summary="Get Overwatch Usernames",
        description=(
            "Retrieve Overwatch usernames for a user. Responds with 404 if the user does not exist. "
            "Includes `username` and `is_primary` fields."
        ),
    )
    async def get_overwatch_usernames(self, svc: UsersService, user_id: int) -> OverwatchUsernamesResponse:
        """Retrieve the Overwatch usernames for a specific user.

        Args:
            svc: The user service.
            user_id: The user ID.

        Returns:
            The user's Overwatch usernames.
        """
        return await svc.get_overwatch_usernames_response(user_id)

    @litestar.get(
        path="/{user_id:int}/rank",
        summary="Get User Rank Details",
        description=(
            "Compute per-difficulty completion counts and medal thresholds for the given user. "
            "Uses verified, latest-per-user runs and Global maps only."
        ),
    )
    async def get_user_rank_data(self, svc: UsersService, user_id: int, conn: Connection) -> list[RankDetailResponse]:
        """Get rank details for a user.

        Args:
            svc: The user service.
            user_id: The user ID.
            conn: Database connection.

        Returns:
            A list of rank detail rows by difficulty.
        """
        return await svc.get_user_rank_data(user_id, conn)

    @litestar.post(
        "/fake",
        summary="Create fake member",
        description="Create a placeholder user with an auto-generated ID and return the new user ID.",
    )
    async def create_fake_member(self, svc: UsersService, name: str) -> int:
        """Create a placeholder (fake) member and return the new user ID.

        Args:
            svc: User service dependency.
            name: Display name to assign to the fake user.

        Returns:
            The newly created fake user ID.
        """
        return await svc.create_fake_member(name)

    @litestar.put(
        "/fake/{fake_user_id:int}/link/{real_user_id:int}",
        summary="Link fake member to real user",
        description="Reassign references from the fake user to the real user and delete the fake user row.",
    )
    async def link_fake_member_id_to_real_user_id(
        self,
        svc: UsersService,
        fake_user_id: int,
        real_user_id: int,
        conn: Connection,
    ) -> None:
        """Link a fake member to a real user and remove the fake user.

        Args:
            svc: User service dependency.
            fake_user_id: The placeholder user ID to migrate from and delete.
            real_user_id: The real user ID to migrate references to.
            conn: Database connection.
        """
        try:
            return await svc.link_fake_member_id_to_real_user_id(fake_user_id, real_user_id, conn)
        except UserNotFoundError as e:
            raise CustomHTTPException(detail=e.message, status_code=HTTP_404_NOT_FOUND)
