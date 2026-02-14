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

    VERIFICATION_APPROVED = "verification_approved"
    VERIFICATION_REJECTED = "verification_rejected"
    RECORD_REMOVED = "record_removed"
    RECORD_EDITED = "record_edited"
    AUTO_VERIFY_FAILED = "auto_verify_failed"

    SKILL_ROLE_UPDATE = "skill_role_update"
    XP_GAIN = "xp_gain"
    RANK_UP = "rank_up"
    PRESTIGE = "prestige"
    MASTERY_EARNED = "mastery_earned"

    LOOTBOX_EARNED = "lootbox_earned"

    PLAYTEST_UPDATE = "playtest_update"

    MAP_EDIT_APPROVED = "map_edit_approved"
    MAP_EDIT_REJECTED = "map_edit_rejected"

    QUEST_COMPLETE = "quest_complete"
    QUEST_ROTATION = "quest_rotation"


NOTIFICATION_EVENT_TYPE = Literal[
    "verification_approved",
    "verification_rejected",
    "record_removed",
    "record_edited",
    "auto_verify_failed",
    "skill_role_update",
    "xp_gain",
    "rank_up",
    "prestige",
    "mastery_earned",
    "lootbox_earned",
    "playtest_update",
    "map_edit_approved",
    "map_edit_rejected",
    "quest_complete",
    "quest_rotation",
]

NOTIFICATION_CHANNEL = Literal["discord_dm", "discord_ping", "web"]


EVENT_TYPE_DEFAULT_CHANNELS: dict[NotificationEventType, list[NotificationChannel]] = {
    NotificationEventType.VERIFICATION_APPROVED: [NotificationChannel.DISCORD_DM, NotificationChannel.WEB],
    NotificationEventType.VERIFICATION_REJECTED: [NotificationChannel.DISCORD_DM, NotificationChannel.WEB],
    NotificationEventType.RECORD_REMOVED: [NotificationChannel.DISCORD_DM, NotificationChannel.WEB],
    NotificationEventType.AUTO_VERIFY_FAILED: [NotificationChannel.DISCORD_DM, NotificationChannel.WEB],
    NotificationEventType.SKILL_ROLE_UPDATE: [NotificationChannel.DISCORD_DM, NotificationChannel.WEB],
    NotificationEventType.XP_GAIN: [NotificationChannel.DISCORD_PING, NotificationChannel.WEB],
    NotificationEventType.RANK_UP: [NotificationChannel.DISCORD_PING, NotificationChannel.WEB],
    NotificationEventType.PRESTIGE: [NotificationChannel.DISCORD_PING, NotificationChannel.WEB],
    NotificationEventType.MASTERY_EARNED: [NotificationChannel.DISCORD_PING, NotificationChannel.WEB],
    NotificationEventType.LOOTBOX_EARNED: [NotificationChannel.DISCORD_DM, NotificationChannel.WEB],
    NotificationEventType.PLAYTEST_UPDATE: [NotificationChannel.DISCORD_DM, NotificationChannel.WEB],
    NotificationEventType.MAP_EDIT_APPROVED: [NotificationChannel.DISCORD_DM, NotificationChannel.WEB],
    NotificationEventType.MAP_EDIT_REJECTED: [NotificationChannel.DISCORD_DM, NotificationChannel.WEB],
    NotificationEventType.QUEST_COMPLETE: [NotificationChannel.DISCORD_DM, NotificationChannel.WEB],
    NotificationEventType.QUEST_ROTATION: [NotificationChannel.WEB],
}


class NotificationDeliveryEvent(Struct):
    """Event published to RabbitMQ when a notification needs Discord delivery.

    Routing key: api.notification.delivery
    """

    event_id: int
    user_id: int
    event_type: NOTIFICATION_EVENT_TYPE
    title: str
    body: str
    discord_message: str | None
    metadata: dict | None
    channels_to_deliver: list[NOTIFICATION_CHANNEL]


class NotificationCreateRequest(Struct):
    """Request to create a notification event."""

    user_id: int
    event_type: NOTIFICATION_EVENT_TYPE
    title: str
    body: str
    discord_message: str | None = None
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
    channels: dict[str, bool]


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
