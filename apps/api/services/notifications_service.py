"""Service for notifications business logic."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import msgspec
from genjishimada_sdk.notifications import (
    EVENT_TYPE_DEFAULT_CHANNELS,
    NOTIFICATION_CHANNEL,
    NOTIFICATION_EVENT_TYPE,
    NotificationChannel,
    NotificationCreateRequest,
    NotificationDeliveryEvent,
    NotificationEventResponse,
    NotificationEventType,
    NotificationPreference,
    NotificationPreferencesResponse,
)
from litestar.datastructures import Headers

from repository.exceptions import ForeignKeyViolationError
from repository.notifications_repository import NotificationsRepository
from repository.users_repository import UsersRepository
from services.base import BaseService
from services.exceptions.notifications import NotificationEventNotFoundError
from services.exceptions.users import UserNotFoundError

if TYPE_CHECKING:
    from asyncpg import Pool
    from litestar.datastructures import State


DISCORD_USER_ID_LOWER_LIMIT = 1_000_000_000_000_000


class NotificationsService(BaseService):
    """Service for notifications business logic."""

    def __init__(
        self, pool: Pool, state: State, notifications_repo: NotificationsRepository, users_repo: UsersRepository
    ) -> None:
        """Initialize service.

        Args:
            pool: Database connection pool.
            state: Application state.
            notifications_repo: Notifications repository instance.
            users_repo: Users repository instance.
        """
        super().__init__(pool, state)
        self._notifications_repo = notifications_repo
        self._users_repo = users_repo

    async def create_and_dispatch(
        self,
        data: NotificationCreateRequest,
        headers: Headers,
    ) -> NotificationEventResponse:
        """Create a notification event and dispatch it for delivery.

        This is the primary method for creating notifications. It:
        1. Stores the notification in the database (for web tray)
        2. Determines which channels should receive it based on preferences
        3. Publishes a RabbitMQ message for Discord delivery (if applicable)

        Args:
            data: The notification to create.
            headers: Request headers for RabbitMQ publishing.

        Returns:
            The created notification event.

        Raises:
            UserNotFoundError: If user does not exist.
        """
        # 1. Store notification in database
        try:
            event_id = await self._notifications_repo.insert_event(
                user_id=data.user_id,
                event_type=data.event_type,
                title=data.title,
                body=data.body,
                metadata=data.metadata,
            )
        except ForeignKeyViolationError as e:
            if "user_id" in e.constraint_name:
                raise UserNotFoundError(data.user_id) from e
            raise

        # Fetch the created event to return
        event_row = await self._notifications_repo.fetch_event_by_id(event_id)
        if not event_row:
            raise RuntimeError(f"Failed to fetch newly created notification event {event_id}")
        event = self._row_to_event_response(event_row)

        # 2. Determine which channels should receive this notification
        channels_to_deliver = await self._get_enabled_channels(data.user_id, data.event_type)

        # 3. If Discord delivery is needed, publish to RabbitMQ
        discord_channels: list[NOTIFICATION_CHANNEL] = [
            c
            for c in channels_to_deliver
            if c in (NotificationChannel.DISCORD_DM.value, NotificationChannel.DISCORD_PING.value)
        ]

        if discord_channels and data.user_id >= DISCORD_USER_ID_LOWER_LIMIT:
            delivery_event = NotificationDeliveryEvent(
                event_id=event.id,
                user_id=data.user_id,
                event_type=data.event_type,
                title=data.title,
                body=data.body,
                discord_message=data.discord_message,
                metadata=data.metadata,
                channels_to_deliver=discord_channels,
            )

            await self.publish_message(
                routing_key="api.notification.delivery",
                data=delivery_event,
                headers=headers,
                # No idempotency key needed - notifications can be duplicated safely
            )

        return event

    async def get_user_events(
        self,
        user_id: int,
        *,
        unread_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[NotificationEventResponse]:
        """Get notifications for the notification tray.

        Args:
            user_id: Target user ID.
            unread_only: Only return unread notifications.
            limit: Maximum number of results.
            offset: Pagination offset.

        Returns:
            List of notification events.
        """
        rows = await self._notifications_repo.fetch_user_events(
            user_id=user_id,
            unread_only=unread_only,
            limit=limit,
            offset=offset,
        )
        return [self._row_to_event_response(row) for row in rows]

    async def get_unread_count(self, user_id: int) -> int:
        """Get count of unread notifications.

        Args:
            user_id: Target user ID.

        Returns:
            Count of unread notifications.
        """
        return await self._notifications_repo.fetch_unread_count(user_id)

    async def mark_read(self, event_id: int) -> None:
        """Mark a single notification as read.

        Args:
            event_id: ID of the notification event.
        """
        await self._notifications_repo.mark_event_read(event_id)

    async def mark_all_read(self, user_id: int) -> int:
        """Mark all notifications as read and return count.

        Args:
            user_id: Target user ID.

        Returns:
            Count of notifications marked as read.
        """
        return await self._notifications_repo.mark_all_events_read(user_id)

    async def dismiss_all(self, user_id: int) -> int:
        """Dismiss all notifications and return count.

        Args:
            user_id: Target user ID.

        Returns:
            Count of notifications dismissed.
        """
        return await self._notifications_repo.dismiss_all_events(user_id)

    async def dismiss_event(self, event_id: int) -> None:
        """Dismiss a notification from the tray.

        Args:
            event_id: ID of the notification event.
        """
        await self._notifications_repo.dismiss_event(event_id)

    async def record_delivery_result(
        self,
        event_id: int,
        channel: NOTIFICATION_CHANNEL,
        status: Literal["delivered", "failed", "skipped"],
        error_message: str | None = None,
    ) -> None:
        """Record the result of a delivery attempt.

        Args:
            event_id: ID of the notification event.
            channel: Delivery channel.
            status: Delivery status.
            error_message: Optional error message if failed.

        Raises:
            NotificationEventNotFoundError: If event does not exist.
        """
        try:
            await self._notifications_repo.record_delivery_result(
                event_id=event_id,
                channel=channel,
                status=status,
                error_message=error_message,
            )
        except ForeignKeyViolationError as e:
            if "event_id" in e.constraint_name:
                raise NotificationEventNotFoundError(event_id) from e
            raise

    async def get_preferences(self, user_id: int) -> list[NotificationPreferencesResponse]:
        """Get all preferences for a user, returning defaults for unset ones.

        Args:
            user_id: Target user ID.

        Returns:
            List of preferences grouped by event type.
        """
        rows = await self._notifications_repo.fetch_preferences(user_id)

        # Build a map of existing preferences
        existing: dict[str, dict[str, bool]] = {}
        for row in rows:
            if row["event_type"] not in existing:
                existing[row["event_type"]] = {}
            existing[row["event_type"]][row["channel"]] = row["enabled"]

        # Build response with defaults for missing preferences
        result = []
        for event_type in NotificationEventType:
            default_channels = EVENT_TYPE_DEFAULT_CHANNELS.get(event_type, [])
            channels: dict[str, bool] = {}

            for channel in NotificationChannel:
                if event_type.value in existing and channel.value in existing[event_type.value]:
                    channels[channel.value] = existing[event_type.value][channel.value]
                else:
                    # Default: enabled if channel is in default list
                    channels[channel.value] = channel in default_channels

            result.append(
                NotificationPreferencesResponse(
                    event_type=event_type.value,
                    channels=channels,
                )
            )

        return result

    async def update_preference(
        self,
        user_id: int,
        event_type: NOTIFICATION_EVENT_TYPE,
        channel: NOTIFICATION_CHANNEL,
        enabled: bool,
    ) -> None:
        """Update a single preference.

        Args:
            user_id: Target user ID.
            event_type: Event type string.
            channel: Channel string.
            enabled: Whether the preference is enabled.

        Raises:
            UserNotFoundError: If user does not exist.
        """
        if not await self._users_repo.check_user_exists(user_id):
            raise UserNotFoundError(user_id)
        try:
            await self._notifications_repo.upsert_preference(
                user_id=user_id,
                event_type=event_type,
                channel=channel,
                enabled=enabled,
            )
        except ForeignKeyViolationError as e:
            if "user_id" in e.constraint_name:
                raise UserNotFoundError(user_id) from e
            raise

    async def bulk_update_preferences(self, user_id: int, preferences: list[NotificationPreference]) -> None:
        """Bulk update preferences.

        Args:
            user_id: Target user ID.
            preferences: List of preference updates.
        """
        if not await self._users_repo.check_user_exists(user_id):
            raise UserNotFoundError(user_id)
        for pref in preferences:
            await self.update_preference(user_id, pref.event_type, pref.channel, pref.enabled)

    async def should_deliver(
        self,
        user_id: int,
        event_type: NOTIFICATION_EVENT_TYPE,
        channel: NOTIFICATION_CHANNEL,
    ) -> bool:
        """Check if a notification should be delivered to a channel.

        Args:
            user_id: Target user ID.
            event_type: Event type to check.
            channel: Channel to check.

        Returns:
            Whether notification should be delivered.
        """
        enabled_channels = await self._get_enabled_channels(user_id, event_type)
        return channel in enabled_channels

    async def _get_enabled_channels(self, user_id: int, event_type: NOTIFICATION_EVENT_TYPE) -> list[str]:
        """Get list of enabled channels for a user and event type.

        Args:
            user_id: Target user ID.
            event_type: Event type to check.

        Returns:
            List of enabled channel strings.
        """
        rows = await self._notifications_repo.fetch_preferences(user_id)

        # Build preference map
        explicit_prefs = {}
        for row in rows:
            if row["event_type"] == event_type:
                explicit_prefs[row["channel"]] = row["enabled"]

        # Determine defaults
        try:
            event_enum = NotificationEventType(event_type)
            default_channels = EVENT_TYPE_DEFAULT_CHANNELS.get(event_enum, [])
        except ValueError:
            default_channels = []

        # Build final channel list
        enabled = []
        for channel in NotificationChannel:
            if channel.value in explicit_prefs:
                if explicit_prefs[channel.value]:
                    enabled.append(channel.value)
            elif channel in default_channels:
                enabled.append(channel.value)

        return enabled

    def _row_to_event_response(self, row: dict) -> NotificationEventResponse:
        """Convert a database row to NotificationEventResponse.

        Args:
            row: Database row dict.

        Returns:
            NotificationEventResponse instance.
        """
        metadata = None
        if row["metadata"]:
            if isinstance(row["metadata"], str):
                metadata = msgspec.json.decode(row["metadata"])
            else:
                metadata = dict(row["metadata"])

        return NotificationEventResponse(
            id=row["id"],
            user_id=row["user_id"],
            event_type=row["event_type"],
            title=row["title"],
            body=row["body"],
            metadata=metadata,
            created_at=row["created_at"].isoformat(),
            read_at=row["read_at"].isoformat() if row["read_at"] else None,
            dismissed_at=row["dismissed_at"].isoformat() if row["dismissed_at"] else None,
        )


async def provide_notifications_service(
    state: State,
    users_repo: UsersRepository,
) -> NotificationsService:
    """Litestar DI provider for notifications service.

    Args:
        state: Application state.
        users_repo: Users repository instance.

    Returns:
        NotificationsService instance.
    """
    notifications_repo = NotificationsRepository(pool=state.db_pool)
    return NotificationsService(
        pool=state.db_pool, state=state, notifications_repo=notifications_repo, users_repo=users_repo
    )
