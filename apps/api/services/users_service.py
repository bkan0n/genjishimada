"""Service layer for users domain business logic."""

from __future__ import annotations

import logging

import msgspec
from asyncpg import Connection
from genjishimada_sdk.users import (
    NOTIFICATION_TYPES,
    Notification,
    OverwatchUsernameItem,
    OverwatchUsernamesResponse,
    RankDetailResponse,
    SettingsUpdateRequest,
    UserCreateRequest,
    UserResponse,
    UserUpdateRequest,
)

from repository.exceptions import UniqueConstraintViolationError
from repository.users_repository import UsersRepository
from services.base import BaseService
from services.exceptions.users import InvalidUserIdError, UserAlreadyExistsError
from utilities.shared_queries import get_user_rank_data

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
            InvalidUserIdError: If user_id < 100000000 (use fake member endpoint).
            UserAlreadyExistsError: If user_id already exists (users_pkey).
        """
        fake_user_id_limit = 100_000_000
        if data.id < fake_user_id_limit:
            raise InvalidUserIdError(data.id)

        try:
            await self._users_repo.create_user(
                user_id=data.id,
                nickname=data.nickname,
                global_name=data.global_name,
            )
        except UniqueConstraintViolationError as e:
            if e.constraint_name == "users_pkey":
                raise UserAlreadyExistsError(data.id) from e
            raise

        return UserResponse(
            id=data.id,
            nickname=data.nickname,
            global_name=data.global_name,
            coins=0,
            overwatch_usernames=[],
            coalesced_name=data.nickname,
        )

    async def set_overwatch_usernames(self, user_id: int, new_usernames: list[OverwatchUsernameItem]) -> None:
        """Replace all Overwatch usernames for a user.

        Args:
            user_id: The user ID.
            new_usernames: List of new usernames to set.
        """
        await self._users_repo.delete_overwatch_usernames(user_id)

        for item in new_usernames:
            await self._users_repo.insert_overwatch_username(
                user_id=user_id,
                username=item.username,
                is_primary=item.is_primary,
            )

    async def fetch_overwatch_usernames(self, user_id: int) -> list[OverwatchUsernameItem]:
        """Fetch Overwatch usernames for a user.

        Args:
            user_id: The user ID.

        Returns:
            List of Overwatch username items.
        """
        rows = await self._users_repo.fetch_overwatch_usernames(user_id)
        return msgspec.convert(rows, list[OverwatchUsernameItem])

    async def fetch_all_user_names(self, user_id: int) -> list[str]:
        """Fetch all display names for a user.

        Args:
            user_id: The user ID.

        Returns:
            List of display names.
        """
        return await self._users_repo.fetch_all_user_names(user_id)

    async def get_overwatch_usernames_response(self, user_id: int) -> OverwatchUsernamesResponse:
        """Build Overwatch usernames response for a user.

        Args:
            user_id: The user ID.

        Returns:
            Response with primary, secondary, tertiary usernames.
        """
        usernames = await self.fetch_overwatch_usernames(user_id)
        primary = usernames[0].username if usernames else None
        secondary = usernames[1].username if len(usernames) > 1 else None
        tertiary = usernames[2].username if len(usernames) > 2 else None  # noqa: PLR2004

        return OverwatchUsernamesResponse(
            user_id=user_id,
            primary=primary,
            secondary=secondary,
            tertiary=tertiary,
        )

    async def fetch_user_notifications(self, user_id: int) -> int | None:
        """Get notification bitmask for a user.

        Args:
            user_id: The user ID.

        Returns:
            Bitmask value, or None if not set.
        """
        return await self._users_repo.fetch_user_notifications(user_id)

    async def update_user_notifications(self, user_id: int, notifications_bitmask: int) -> bool:
        """Update notification bitmask for a user.

        Args:
            user_id: The user ID.
            notifications_bitmask: New bitmask value.

        Returns:
            True if successful, False otherwise.
        """
        log.debug(f"Updating user {user_id} settings to bitmask: {notifications_bitmask}")
        try:
            await self._users_repo.upsert_user_notifications(user_id, notifications_bitmask)
            return True
        except Exception:
            return False

    async def get_user_notifications_payload(self, user_id: int, to_bitmask: bool = False) -> dict:
        """Get notification payload for a user.

        Args:
            user_id: The user ID.
            to_bitmask: If True, return bitmask; if False, return notification names.

        Returns:
            Dict with user_id and either bitmask or notifications list.
        """
        bitmask = await self.fetch_user_notifications(user_id)
        if bitmask is None:
            log.debug("User %s not found.", user_id)
            bitmask = 0

        if to_bitmask:
            return {"user_id": user_id, "bitmask": bitmask}

        notifications = [notif.name for notif in Notification if bitmask & notif]
        log.debug("User %s settings: %s", user_id, notifications)
        return {"user_id": user_id, "notifications": notifications}

    async def apply_notifications_bulk(
        self,
        user_id: int,
        data: SettingsUpdateRequest,
    ) -> tuple[bool, int | None, str | None]:
        """Apply bulk notifications update.

        Args:
            user_id: The user ID.
            data: Settings update request.

        Returns:
            Tuple of (success, bitmask_or_none, error_message_or_none).
        """
        try:
            bitmask = data.to_bitmask()
            log.debug(f"User {user_id} notifications bitmask: {bitmask}")
            ok = await self.update_user_notifications(user_id, bitmask)
            if ok:
                return True, bitmask, None
            return False, None, "Update failed"
        except ValueError as ve:
            log.error(f"Validation error: {ve}")
            return False, None, str(ve)

    async def apply_single_notification(
        self,
        user_id: int,
        notification_type: NOTIFICATION_TYPES,
        enable: bool,
    ) -> tuple[bool, int | None, str | None]:
        """Toggle a single notification flag.

        Args:
            user_id: The user ID.
            notification_type: Notification name.
            enable: True to enable, False to disable.

        Returns:
            Tuple of (success, new_bitmask_or_none, error_message_or_none).
        """
        valid_notification_names = {flag.name for flag in Notification}
        if notification_type not in valid_notification_names:
            return False, None, f"Invalid notification type: {notification_type}"

        try:
            current_bitmask = await self.fetch_user_notifications(user_id)
            if current_bitmask is None:
                current_bitmask = 0
            current_flags = Notification(current_bitmask)
            notification_flag = Notification[notification_type]

            new_flags = current_flags | notification_flag if enable else current_flags & ~notification_flag

            log.debug(
                "User %s: updating %s to %s, bitmask: %s -> %s",
                user_id,
                notification_type,
                "enabled" if enable else "disabled",
                current_flags.value,
                new_flags.value,
            )

            ok = await self.update_user_notifications(user_id=user_id, notifications_bitmask=new_flags.value)  # type: ignore[call-arg]
            if ok:
                return True, new_flags.value, None
            return False, None, "Update failed"
        except Exception as e:
            log.error("Error updating single notification: %s", e)
            return False, None, str(e)

    async def get_user_rank_data(self, user_id: int, conn: Connection) -> list[RankDetailResponse]:
        """Get rank details for a user.

        Args:
            user_id: The user ID.
            conn: Database connection.

        Returns:
            List of rank detail responses by difficulty.
        """
        return await get_user_rank_data(conn, user_id)

    async def create_fake_member(self, name: str) -> int:
        """Create a fake member and return the new ID.

        Args:
            name: Display name for the fake user.

        Returns:
            The newly created fake user ID.
        """
        return await self._users_repo.create_fake_member(name)

    async def link_fake_member_id_to_real_user_id(self, fake_user_id: int, real_user_id: int, conn: Connection) -> None:
        """Link a fake member to a real user.

        This operation is transactional: updates maps.creators references,
        then deletes the fake user.

        Args:
            fake_user_id: The placeholder user ID.
            real_user_id: The real user ID.
            conn: Database connection.
        """
        async with conn.transaction():
            await self._users_repo.update_maps_creators_for_fake_member(
                fake_user_id=fake_user_id,
                real_user_id=real_user_id,
                conn=conn,
            )
            await self._users_repo.delete_user(user_id=fake_user_id, conn=conn)
