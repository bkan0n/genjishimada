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
from genjishimada_sdk.users import Notification  # Legacy enum
from litestar.datastructures import Headers
from litestar.status_codes import HTTP_404_NOT_FOUND

from repository.notifications_repository import NotificationsRepository
from services.base import BaseService
from utilities.errors import ConstraintHandler, handle_db_exceptions

if TYPE_CHECKING:
    from asyncpg import Pool
    from litestar.datastructures import State


DISCORD_USER_ID_LOWER_LIMIT = 1_000_000_000_000_000

# Mapping from legacy Notification enum to new system
LEGACY_TO_NEW_MAPPING: dict[Notification, tuple[NotificationEventType, NotificationChannel]] = {
    Notification.DM_ON_VERIFICATION: (NotificationEventType.VERIFICATION_APPROVED, NotificationChannel.DISCORD_DM),
    Notification.DM_ON_SKILL_ROLE_UPDATE: (NotificationEventType.SKILL_ROLE_UPDATE, NotificationChannel.DISCORD_DM),
    Notification.DM_ON_LOOTBOX_GAIN: (NotificationEventType.LOOTBOX_EARNED, NotificationChannel.DISCORD_DM),
    Notification.DM_ON_RECORDS_REMOVAL: (NotificationEventType.RECORD_REMOVED, NotificationChannel.DISCORD_DM),
    Notification.DM_ON_PLAYTEST_ALERTS: (NotificationEventType.PLAYTEST_UPDATE, NotificationChannel.DISCORD_DM),
    Notification.PING_ON_XP_GAIN: (NotificationEventType.XP_GAIN, NotificationChannel.DISCORD_PING),
    Notification.PING_ON_MASTERY: (NotificationEventType.MASTERY_EARNED, NotificationChannel.DISCORD_PING),
    Notification.PING_ON_COMMUNITY_RANK_UPDATE: (NotificationEventType.RANK_UP, NotificationChannel.DISCORD_PING),
}

# Constraint error mappings for notifications operations
NOTIFICATIONS_FK_CONSTRAINTS = {
    "events_user_id_fkey": ConstraintHandler(
        message="User does not exist.",
        status_code=HTTP_404_NOT_FOUND,
    ),
    "preferences_user_id_fkey": ConstraintHandler(
        message="User does not exist.",
        status_code=HTTP_404_NOT_FOUND,
    ),
    "delivery_log_event_id_fkey": ConstraintHandler(
        message="Notification event does not exist.",
        status_code=HTTP_404_NOT_FOUND,
    ),
}


class NotificationsService(BaseService):
    """Service for notifications business logic."""

    def __init__(self, pool: Pool, state: State, notifications_repo: NotificationsRepository) -> None:
        """Initialize service.

        Args:
            pool: Database connection pool.
            state: Application state.
            notifications_repo: Notifications repository instance.
        """
        super().__init__(pool, state)
        self._notifications_repo = notifications_repo

    @handle_db_exceptions(fk_constraints=NOTIFICATIONS_FK_CONSTRAINTS)
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
        """
        # 1. Store notification in database
        event_id = await self._notifications_repo.insert_event(
            user_id=data.user_id,
            event_type=data.event_type,
            title=data.title,
            body=data.body,
            metadata=data.metadata,
        )

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
        """
        await self._notifications_repo.record_delivery_result(
            event_id=event_id,
            channel=channel,
            status=status,
            error_message=error_message,
        )

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

    @handle_db_exceptions(fk_constraints=NOTIFICATIONS_FK_CONSTRAINTS)
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
        """
        await self._notifications_repo.upsert_preference(
            user_id=user_id,
            event_type=event_type,
            channel=channel,
            enabled=enabled,
        )

    @handle_db_exceptions(fk_constraints=NOTIFICATIONS_FK_CONSTRAINTS)
    async def bulk_update_preferences(self, user_id: int, preferences: list[NotificationPreference]) -> None:
        """Bulk update preferences.

        Args:
            user_id: Target user ID.
            preferences: List of preference updates.
        """
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

    async def get_legacy_bitmask(self, user_id: int) -> int:
        """Convert new preferences to legacy bitmask for bot compatibility.

        Args:
            user_id: Target user ID.

        Returns:
            Legacy bitmask value.
        """
        bitmask = 0

        for legacy_flag, (event_type, channel) in LEGACY_TO_NEW_MAPPING.items():
            if await self.should_deliver(user_id, event_type.value, channel.value):
                bitmask |= legacy_flag.value

        return bitmask

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


async def provide_notifications_service(state: State) -> NotificationsService:
    """Provide NotificationsService DI.

    Args:
        state: Application state.

    Returns:
        NotificationsService instance.
    """
    from repository.notifications_repository import NotificationsRepository  # noqa: PLC0415

    notifications_repo = NotificationsRepository(state.db_pool)
    return NotificationsService(state.db_pool, state, notifications_repo)
