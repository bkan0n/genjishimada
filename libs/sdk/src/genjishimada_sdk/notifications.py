from __future__ import annotations

from enum import Enum
from typing import Literal

from msgspec import Struct

__all__ = (
    "EVENT_TYPE_DEFAULT_CHANNELS",
    "NOTIFICATION_CHANNEL",
    "NOTIFICATION_EVENT_TYPE",
    "NotificationChannel",
    "NotificationCreateRequest",
    "NotificationDeliveryEvent",
    "NotificationDeliveryResultRequest",
    "NotificationEventResponse",
    "NotificationEventType",
    "NotificationPreference",
    "NotificationPreferencesResponse",
    "NotificationUnreadCountResponse",
    "ShouldDeliverResponse",
)


class NotificationChannel(str, Enum):
    """Available notification delivery channels."""

    DISCORD_DM = "discord_dm"
    DISCORD_PING = "discord_ping"
    WEB = "web"


class NotificationEventType(str, Enum):
    """Notification event types."""

    # Completion/Record events
    VERIFICATION_APPROVED = "verification_approved"
    VERIFICATION_REJECTED = "verification_rejected"
    RECORD_REMOVED = "record_removed"
    RECORD_EDITED = "record_edited"

    # Progression events
    SKILL_ROLE_UPDATE = "skill_role_update"
    XP_GAIN = "xp_gain"
    RANK_UP = "rank_up"
    PRESTIGE = "prestige"
    MASTERY_EARNED = "mastery_earned"

    # Reward events
    LOOTBOX_EARNED = "lootbox_earned"

    # Engagement events
    PLAYTEST_UPDATE = "playtest_update"

    # Map edit events
    MAP_EDIT_APPROVED = "map_edit_approved"
    MAP_EDIT_REJECTED = "map_edit_rejected"


NOTIFICATION_EVENT_TYPE = Literal[
    "verification_approved",
    "verification_rejected",
    "record_removed",
    "record_edited",
    "skill_role_update",
    "xp_gain",
    "rank_up",
    "prestige",
    "mastery_earned",
    "lootbox_earned",
    "playtest_update",
    "map_edit_approved",
    "map_edit_rejected",
]

NOTIFICATION_CHANNEL = Literal["discord_dm", "discord_ping", "web"]


# Default channels for each event type
EVENT_TYPE_DEFAULT_CHANNELS: dict[NotificationEventType, list[NotificationChannel]] = {
    NotificationEventType.VERIFICATION_APPROVED: [NotificationChannel.DISCORD_DM, NotificationChannel.WEB],
    NotificationEventType.VERIFICATION_REJECTED: [NotificationChannel.DISCORD_DM, NotificationChannel.WEB],
    NotificationEventType.RECORD_REMOVED: [NotificationChannel.DISCORD_DM, NotificationChannel.WEB],
    NotificationEventType.SKILL_ROLE_UPDATE: [NotificationChannel.DISCORD_DM, NotificationChannel.WEB],
    NotificationEventType.XP_GAIN: [NotificationChannel.DISCORD_PING, NotificationChannel.WEB],
    NotificationEventType.RANK_UP: [NotificationChannel.DISCORD_PING, NotificationChannel.WEB],
    NotificationEventType.PRESTIGE: [NotificationChannel.DISCORD_PING, NotificationChannel.WEB],
    NotificationEventType.MASTERY_EARNED: [NotificationChannel.DISCORD_PING, NotificationChannel.WEB],
    NotificationEventType.LOOTBOX_EARNED: [NotificationChannel.DISCORD_DM, NotificationChannel.WEB],
    NotificationEventType.PLAYTEST_UPDATE: [NotificationChannel.DISCORD_DM, NotificationChannel.WEB],
    NotificationEventType.MAP_EDIT_APPROVED: [NotificationChannel.DISCORD_DM, NotificationChannel.WEB],
    NotificationEventType.MAP_EDIT_REJECTED: [NotificationChannel.DISCORD_DM, NotificationChannel.WEB],
}


class NotificationDeliveryEvent(Struct):
    """Event published to RabbitMQ when a notification needs Discord delivery.

    Routing key: api.notification.delivery
    """

    event_id: int  # ID in notifications.events table
    user_id: int  # Target user
    event_type: NOTIFICATION_EVENT_TYPE  # Type for preference lookup
    title: str  # Notification title
    body: str  # Notification body
    discord_message: str | None  # Discord-specific formatted message
    metadata: dict | None  # Additional context (map_code, etc.)
    channels_to_deliver: list[NOTIFICATION_CHANNEL]  # Which channels to attempt


class NotificationCreateRequest(Struct):
    """Request to create a notification event."""

    user_id: int
    event_type: NOTIFICATION_EVENT_TYPE
    title: str
    body: str
    discord_message: str | None = None  # Override for Discord-specific formatting
    metadata: dict | None = None


class NotificationEventResponse(Struct):
    """Response for a notification event."""

    id: int
    user_id: int
    event_type: NOTIFICATION_EVENT_TYPE
    title: str
    body: str
    metadata: dict | None
    created_at: str
    read_at: str | None
    dismissed_at: str | None


class NotificationPreference(Struct):
    """User preference for a notification type and channel."""

    event_type: NOTIFICATION_EVENT_TYPE
    channel: NOTIFICATION_CHANNEL
    enabled: bool


class NotificationPreferencesResponse(Struct):
    """All preferences for a user for a single event type."""

    event_type: NOTIFICATION_EVENT_TYPE
    channels: dict[str, bool]  # channel -> enabled


class NotificationUnreadCountResponse(Struct):
    """Response for unread notification count."""

    count: int


class ShouldDeliverResponse(Struct):
    """Response for should_deliver check."""

    should_deliver: bool


class NotificationDeliveryResultRequest(Struct):
    """Request to record delivery result from bot."""

    channel: NOTIFICATION_CHANNEL
    status: Literal["delivered", "failed", "skipped"]
    error_message: str | None = None
