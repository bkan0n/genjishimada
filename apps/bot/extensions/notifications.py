"""Notification service for processing and delivering notifications.

This service:
1. Consumes notification delivery events from the work queue
2. Delivers notifications via Discord (DM or channel ping)
3. Reports delivery status back to the API
4. Maintains backwards compatibility with legacy notification methods
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

import discord
from genjishimada_sdk.notifications import (
    NOTIFICATION_CHANNEL,
    NotificationChannel,
    NotificationDeliveryEvent,
    NotificationEventType,
)
from genjishimada_sdk.queue import JobContext

from extensions._queue_registry import queue_consumer
from utilities.base import BaseHandler
from utilities.job_effects import send_once

if TYPE_CHECKING:
    import core

logger = logging.getLogger(__name__)

DISCORD_USER_ID_LOWER_LIMIT = 1_000_000_000_000_000


class NotificationHandler(BaseHandler):
    """Service for processing and delivering notifications.

    This service handles both the new durable notification system
    and maintains backwards compatibility with legacy methods.
    """

    xp_channel: discord.TextChannel | None

    async def _resolve_channels(self) -> None:
        """Resolve channels used by notification delivery."""
        xp_channel = self.bot.get_channel(self.bot.config.channels.updates.xp)
        if isinstance(xp_channel, discord.TextChannel):
            self.xp_channel = xp_channel
        else:
            self.xp_channel = None

    @queue_consumer("api.notification.delivery", struct_type=NotificationDeliveryEvent)
    async def _process_notification_delivery(
        self,
        event: NotificationDeliveryEvent,
        _: JobContext,
    ) -> None:
        """Process a notification delivery event from the work queue.

        This is triggered when the API creates a notification that needs
        Discord delivery.
        """
        logger.debug(
            "[x] [Queue] Processing notification delivery: "
            f"event_id={event.event_id}, user_id={event.user_id}, type={event.event_type}"
        )

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
                    if event.event_type in ("quest_complete",):
                        status, error = await self._handle_quest_ping(event)
                    else:
                        status = "skipped"
                        error = "Channel pings handled at trigger site"

            except (discord.Forbidden, discord.NotFound) as e:
                logger.warning("Notification %s was rejected by its destination: %s", event.event_id, e)
                status = "failed"
                error = str(e)

            await self._report_delivery_result(event.event_id, channel, status, error)

    async def _handle_quest_ping(
        self, event: NotificationDeliveryEvent
    ) -> tuple[Literal["delivered", "failed", "skipped"], str | None]:
        """Handle DISCORD_PING delivery for quest completion events.

        Posts a message in the XP channel announcing the quest completion.
        Handles rival mention logic for beat_rival quests.

        Returns:
            Tuple of (status, error_message).
        """
        if not self.xp_channel:
            raise RuntimeError("XP channel not configured")

        metadata = event.metadata or {}
        quest_name = metadata.get("quest_name", "a quest")
        quest_difficulty = metadata.get("quest_difficulty", "")
        rival_user_id = metadata.get("rival_user_id")
        rival_display_name = metadata.get("rival_display_name")

        should_ping_completer = await self.should_deliver_new(
            event.user_id, NotificationEventType.QUEST_COMPLETE, NotificationChannel.DISCORD_PING
        )
        if should_ping_completer:
            completer_text = f"<@{event.user_id}>"
        else:
            user_data = await self.bot.api.get_user(event.user_id)
            completer_text = user_data.coalesced_name if user_data else "Unknown User"

        # Read enriched metadata
        bounty_type = metadata.get("bounty_type")
        map_code = metadata.get("map_code")
        completion_time = metadata.get("completion_time")
        rival_time = metadata.get("rival_time")
        target_time = metadata.get("target_time")
        quest_description = metadata.get("quest_description", "")

        difficulty_text = f" {quest_difficulty.capitalize()}" if quest_difficulty else ""

        if bounty_type == "rival_challenge" and rival_user_id:
            # Resolve rival text (ping or display name)
            should_ping_rival = await self.should_deliver_new(
                rival_user_id, NotificationEventType.QUEST_RIVAL_MENTION, NotificationChannel.DISCORD_PING
            )
            rival_text = f"<@{rival_user_id}>" if should_ping_rival else (rival_display_name or "Unknown User")

            ping_message = (
                f"<:_:976917981009440798> {completer_text} beat {rival_text}'s time on "
                f"**{map_code}** ({rival_time:.2f}s \u2192 {completion_time:.2f}s)!"
            )
        elif bounty_type == "personal_improvement":
            ping_message = (
                f"<:_:976917981009440798> {completer_text} improved their time on "
                f"**{map_code}** ({target_time:.2f}s \u2192 {completion_time:.2f}s)!"
            )
        elif bounty_type == "gap_filling":
            ping_message = f"<:_:976917981009440798> {completer_text} completed **{map_code}**!"
        else:
            # Global quest (no bounty_type)
            desc_part = f" ({quest_description})" if quest_description else ""
            ping_message = (
                f"<:_:976917981009440798> {completer_text} completed the{difficulty_text} "
                f"quest **{quest_name}**{desc_part}!"
            )

        await send_once(self.bot, self.xp_channel, "notification-quest-ping", ping_message)
        return "delivered", None

    async def _report_delivery_result(
        self,
        event_id: int,
        channel: NOTIFICATION_CHANNEL,
        status: Literal["delivered", "failed", "skipped"],
        error_message: str | None,
    ) -> None:
        """Report delivery result back to the API."""
        await self.bot.api.record_notification_delivery_result(
            event_id=event_id,
            channel=channel,
            status=status,
            error_message=error_message,
        )

    async def _send_dm(self, user_id: int, message: str) -> bool:
        """Send a durable DM; only a definite destination rejection is permanent."""
        user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
        try:
            await send_once(self.bot, user, "notification-dm", message)
        except (discord.Forbidden, discord.NotFound):
            logger.info("Cannot deliver DM to user %s", user_id)
            return False
        return True

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
        The API will store the notification and handle DM delivery via the work queue.
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
        await self.bot.api.create_notification(
            user_id=user_id,
            event_type=event_type.value,
            title=title,
            body=body,
            metadata=metadata,
        )

        effect_key = f"notification-ping:{user_id}:{event_type.value}:{title}:{(metadata or {}).get('map_name', '')}"
        if user_id < DISCORD_USER_ID_LOWER_LIMIT:
            await send_once(self.bot, channel, effect_key, fallback_message, **kwargs)
            return

        should_ping = await self.should_deliver_new(user_id, event_type, NotificationChannel.DISCORD_PING)
        content = f"<@{user_id}> {ping_message}" if should_ping else fallback_message
        await send_once(self.bot, channel, effect_key, content, **kwargs)

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

        The API will store the notification and trigger DM delivery via the work queue.
        """
        await self.bot.api.create_notification(
            user_id=user_id,
            event_type=event_type.value,
            title=title,
            body=body,
            discord_message=discord_message,
            metadata=metadata,
        )


async def setup(bot: core.Genji) -> None:
    """Setup Notification extension."""
    bot.notifications = NotificationHandler(bot)
