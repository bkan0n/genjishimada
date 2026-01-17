# apps/bot/extensions/notifications.py
"""Notification service for processing and delivering notifications.

This service:
1. Consumes notification delivery events from RabbitMQ
2. Delivers notifications via Discord (DM or channel ping)
3. Reports delivery status back to the API
4. Maintains backwards compatibility with legacy notification methods
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Literal

import discord
from aio_pika.abc import AbstractIncomingMessage
from genjishimada_sdk.notifications import (
    NOTIFICATION_CHANNEL,
    NotificationChannel,
    NotificationDeliveryEvent,
    NotificationEventType,
)
from genjishimada_sdk.users import Notification

from extensions._queue_registry import queue_consumer
from utilities.base import BaseService

if TYPE_CHECKING:
    import core

logger = logging.getLogger(__name__)

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


class NotificationService(BaseService):
    """Service for processing and delivering notifications.

    This service handles both the new RabbitMQ-based notification system
    and maintains backwards compatibility with legacy methods.
    """

    async def _resolve_channels(self) -> None:
        """No channels to resolve for notifications service."""

    @queue_consumer("api.notification.delivery", struct_type=NotificationDeliveryEvent)
    async def _process_notification_delivery(
        self,
        event: NotificationDeliveryEvent,
        _: AbstractIncomingMessage,
    ) -> None:
        """Process a notification delivery event from RabbitMQ.

        This is triggered when the API creates a notification that needs
        Discord delivery.
        """
        logger.debug(
            "[x] [RabbitMQ] Processing notification delivery: "
            f"event_id={event.event_id}, user_id={event.user_id}, type={event.event_type}"
        )

        # Skip non-Discord users
        if event.user_id < DISCORD_USER_ID_LOWER_LIMIT:
            logger.debug(f"Skipping non-Discord user {event.user_id}")
            return

        message = event.discord_message or event.body

        for channel in event.channels_to_deliver:
            status = "skipped"
            error = None

            try:
                if channel == NotificationChannel.DISCORD_DM.value:
                    success = await self._send_dm(event.user_id, message)
                    status = "delivered" if success else "failed"
                    if not success:
                        error = "Failed to send DM"

                elif channel == NotificationChannel.DISCORD_PING.value:
                    # Channel pings are handled at call-site since they need
                    # the specific channel. Mark as skipped here.
                    status = "skipped"
                    error = "Channel pings handled at trigger site"

            except Exception as e:
                logger.exception(f"Error delivering notification {event.event_id}: {e}")
                status = "failed"
                error = str(e)

            # Report delivery result back to API
            await self._report_delivery_result(event.event_id, channel, status, error)

    async def _report_delivery_result(
        self,
        event_id: int,
        channel: NOTIFICATION_CHANNEL,
        status: Literal["delivered", "failed", "skipped"],
        error_message: str | None,
    ) -> None:
        """Report delivery result back to the API."""
        try:
            await self.bot.api.record_notification_delivery_result(
                event_id=event_id,
                channel=channel,
                status=status,
                error_message=error_message,
            )
        except Exception as e:
            logger.exception(f"Failed to report delivery result: {e}")

    async def _send_dm(self, user_id: int, message: str) -> bool:
        """Send a DM to a user."""
        try:
            user = self.bot.get_user(user_id)
            if not user:
                user = await self.bot.fetch_user(user_id)
            if not user:
                return False
            with contextlib.suppress(discord.Forbidden, discord.NotFound, discord.HTTPException):
                await user.send(message)
                logger.debug("Sent DM to user %s", user_id)
            return True
        except Exception as e:
            logger.error("Failed to send DM to user %s: %s", user_id, e)
            return False

    async def should_deliver_new(
        self,
        user_id: int,
        event_type: NotificationEventType,
        channel: NotificationChannel,
    ) -> bool:
        """Check if notification should be delivered to a specific channel.

        Uses the new API endpoint to check preferences.
        """
        return await self.bot.api.should_deliver_notification(user_id, event_type.value, channel.value)

    async def notify_with_channel_ping(  # noqa: PLR0913
        self,
        channel: discord.TextChannel | discord.Thread,
        user_id: int,
        event_type: NotificationEventType,
        title: str,
        body: str,
        *,
        metadata: dict | None = None,
        ping_message: str,
        fallback_message: str,
        **kwargs,
    ) -> None:
        """Create notification via API and optionally ping in channel.

        Use this for notifications that need channel pings (XP gain, rank up, etc.)
        The API will store the notification and handle DM delivery via RabbitMQ.
        This method handles the channel ping directly since it needs the channel object.

        Args:
            channel: Discord channel to send the message.
            user_id: Target user.
            event_type: Type of notification.
            title: Notification title (for web tray).
            body: Notification body (for web tray).
            metadata: Additional context data.
            ping_message: Message to send with ping if enabled.
            fallback_message: Message to send without ping if disabled.
            **kwargs: Additional arguments for channel.send().
        """
        # Create notification via API (stores for web, triggers DM via RabbitMQ)
        await self.bot.api.create_notification(
            user_id=user_id,
            event_type=event_type.value,
            title=title,
            body=body,
            metadata=metadata,
        )

        # Handle channel ping directly (since we have the channel object)
        if user_id < DISCORD_USER_ID_LOWER_LIMIT:
            # Email user - just send without mention
            await channel.send(fallback_message, **kwargs)
            return

        should_ping = await self.should_deliver_new(user_id, event_type, NotificationChannel.DISCORD_PING)

        try:
            if should_ping:
                await channel.send(f"<@{user_id}> {ping_message}", **kwargs)
            else:
                await channel.send(fallback_message, **kwargs)
        except Exception as e:
            logger.exception("Failed to send channel notification: %s", e)

    async def notify_dm_only(  # noqa: PLR0913
        self,
        user_id: int,
        event_type: NotificationEventType,
        title: str,
        body: str,
        *,
        discord_message: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Create a notification that only needs DM delivery.

        Use this for notifications like verification results, skill role updates,
        lootbox gains, etc. that don't need a channel ping.

        The API will store the notification and trigger DM delivery via RabbitMQ.
        """
        await self.bot.api.create_notification(
            user_id=user_id,
            event_type=event_type.value,
            title=title,
            body=body,
            discord_message=discord_message,
            metadata=metadata,
        )

    async def _get_notification_flags(self, user_id: int) -> Notification:
        """Get notification flags using the legacy API endpoint."""
        return await self.bot.api.get_notification_flags(user_id)

    async def should_notify(self, user_id: int, notification: Notification) -> bool:
        """Check if a user has allowed notifications for this particular process.

        Legacy method - uses the old bitmask-based preferences.
        """
        flags = await self.bot.api.get_notification_flags(user_id)
        result = bool(flags & notification)
        logger.debug("User %s: Checking %s: %s", user_id, notification.name, result)
        return result

    async def notify_dm(self, user_id: int, notification: Notification, message: str) -> bool:
        """Send a DM to the user if the given notification type is enabled.

        Legacy method - prefer notify_dm_only() for new code.
        """
        if user_id < DISCORD_USER_ID_LOWER_LIMIT:
            return False
        if await self.should_notify(user_id, notification):
            try:
                user = self.bot.get_user(user_id)
                if not user:
                    user = await self.bot.fetch_user(user_id)
                if not user:
                    return False
                with contextlib.suppress(discord.Forbidden, discord.NotFound, discord.HTTPException):
                    await user.send(message)
                    logger.debug("Sent DM to user %s for %s", user_id, notification.name)
                return True
            except Exception as e:
                logger.error("Failed to send DM to user %s: %s", user_id, e)
        else:
            logger.debug("User %s does not have %s enabled; DM not sent.", user_id, notification.name)
        return False

    async def notify_channel(
        self,
        channel: discord.TextChannel | discord.Thread,
        user_id: int,
        notification: Notification,
        message: str,
        **kwargs,
    ) -> bool:
        """Send a message in the channel that pings the user if the notification is enabled.

        Legacy method - prefer notify_with_channel_ping() for new code.
        """
        if user_id < DISCORD_USER_ID_LOWER_LIMIT:
            return False
        if await self.should_notify(user_id, notification):
            try:
                await channel.send(f"<@{user_id}> {message}", **kwargs)
                logger.debug("Sent channel notification to user %s for %s", user_id, notification.name)
                return True
            except Exception as e:
                logger.error("Failed to send channel notification for user %s: %s", user_id, e)
        else:
            logger.debug("User %s does not have %s enabled; channel notification not sent.", user_id, notification.name)
        return False

    async def notify_channel_default_to_no_ping(
        self,
        channel: discord.TextChannel | discord.Thread,
        user_id: int,
        notification: Notification,
        message: str,
        **kwargs,
    ) -> None:
        """Send a message in the channel that pings the user, or sends message without a ping.

        Legacy method - prefer notify_with_channel_ping() for new code.
        """
        if user_id < DISCORD_USER_ID_LOWER_LIMIT:
            await channel.send(message, **kwargs)
            return
        success = await self.notify_channel(channel, user_id, notification, message, **kwargs)
        if not success and channel:
            await channel.send(message, **kwargs)


async def setup(bot: core.Genji) -> None:
    """Setup Notification extension."""
    bot.notifications = NotificationService(bot)
