from __future__ import annotations

import os
from logging import getLogger
from math import floor
from typing import TYPE_CHECKING

from aio_pika.abc import AbstractIncomingMessage
from discord import TextChannel, app_commands, utils
from discord.ext import commands
from genjishimada_sdk.notifications import NotificationEventType
from genjishimada_sdk.xp import XP_AMOUNTS, XP_TYPES, XpGrantEvent, XpGrantRequest

from extensions._queue_registry import queue_consumer
from utilities import transformers
from utilities.base import BaseHandler

if TYPE_CHECKING:
    import core
    from utilities._types import GenjiItx

log = getLogger(__name__)


class XPHandler(BaseHandler):
    xp_channel: TextChannel

    async def _resolve_channels(self) -> None:
        """Resolve and cache channels used by the XP system.

        Asserts that the configured XP channel exists and stores it on the
        instance for later use.
        """
        xp_channel = self.bot.get_channel(self.bot.config.channels.updates.xp)
        assert isinstance(xp_channel, TextChannel)
        self.xp_channel = xp_channel

    async def _update_xp_prestige_roles_for_user(
        self, user_id: int, old_prestige_level: int, new_prestige_level: int
    ) -> None:
        """Update a member's prestige role to reflect a prestige level change.

        Args:
            user_id (int): ID of the member to update.
            old_prestige_level (int): Previously held prestige level.
            new_prestige_level (int): Newly achieved prestige level.

        Raises:
            ValueError: If the prestige roles cannot be found.
        """
        old_prestige_role = utils.get(self.guild.roles, name=f"Prestige {old_prestige_level}")
        new_prestige_role = utils.get(self.guild.roles, name=f"Prestige {new_prestige_level}")
        if not (old_prestige_role or new_prestige_role):
            log.debug(
                f"Old prestige level: {old_prestige_level}\n"
                f"New prestige level: {new_prestige_level}\nUser ID: {user_id}"
            )
            raise ValueError("Can't update xp prestige roles for user.")
        assert old_prestige_role and new_prestige_role
        member = self.guild.get_member(user_id)
        if not member:
            return
        roles = set(member.roles)
        roles.discard(old_prestige_role)
        roles.add(new_prestige_role)
        await member.edit(roles=list(roles))

    async def _update_xp_roles_for_user(self, user_id: int, old_tier_name: str, new_tier_name: str) -> None:
        """Update a member's rank role to reflect a tier change.

        Args:
            user_id (int): ID of the member to update.
            old_tier_name (str): Name of the previous main tier role.
            new_tier_name (str): Name of the new main tier role.

        Raises:
            ValueError: If the rank roles cannot be found.
        """
        old_rank = utils.get(self.guild.roles, name=old_tier_name)
        new_rank = utils.get(self.guild.roles, name=new_tier_name)
        if not (old_rank or new_rank):
            log.debug(f"Old tier name: {old_tier_name}\nNew tier name: {new_tier_name}\nUser ID: {user_id}")
            raise ValueError("Can't update xp roles for user.")
        assert old_rank and new_rank
        member = self.guild.get_member(user_id)
        if not member:
            return
        roles = set(member.roles)
        roles.discard(old_rank)
        roles.add(new_rank)
        await member.edit(roles=list(roles))

    async def grant_user_xp_of_type(self, user_id: int, xp_type: XP_TYPES) -> None:
        """Grant XP of a specific type to a user and emit notifications.

        Creates an `XpGrantRequest` from the configured amount for the given type,
        applies it via the API, and triggers the notification flow.

        Args:
            user_id (int): ID of the user receiving XP.
            xp_type (XP_TYPES): Type/category of the XP grant.
        """
        data = XpGrantRequest(XP_AMOUNTS[xp_type], xp_type)
        await self.bot.api.grant_user_xp(user_id, data)

    @queue_consumer("api.xp.grant", struct_type=XpGrantEvent, idempotent=True)
    async def _process_xp_grant(self, event: XpGrantEvent, _: AbstractIncomingMessage) -> None:
        log.debug(f"[x] [RabbitMQ] Processing XP grant event: {event.user_id}")
        user = self.guild.get_member(event.user_id)
        if not user:
            return

        multiplier = await self.bot.api.get_xp_multiplier()
        amount = floor(event.amount * multiplier)

        await self.bot.notifications.notify_with_channel_ping(
            channel=self.xp_channel,
            user_id=event.user_id,
            event_type=NotificationEventType.XP_GAIN,
            title="XP Gained",
            body=f"You gained {amount} XP from {event.type}!",
            metadata={"amount": amount, "type": event.type},
            ping_message=f"<:_:976917981009440798> {user.display_name} has gained **{amount} XP** ({event.type})!",
            fallback_message=f"<:_:976917981009440798> {user.display_name} has gained **{amount} XP** ({event.type})!",
        )

        xp_data = await self.bot.api.get_xp_tier_change(event.previous_amount, event.new_amount)

        if xp_data.rank_change_type:
            old_rank = " ".join((xp_data.old_main_tier_name, xp_data.old_sub_tier_name))
            new_rank = " ".join((xp_data.new_main_tier_name, xp_data.new_sub_tier_name))

            await self.bot.api.grant_active_key_to_user(event.user_id)
            await self._update_xp_roles_for_user(event.user_id, xp_data.old_main_tier_name, xp_data.new_main_tier_name)

            await self.bot.notifications.notify_dm_only(
                user_id=event.user_id,
                event_type=NotificationEventType.LOOTBOX_EARNED,
                title="Lootbox Earned!",
                body=f"You ranked up to {new_rank} and earned a lootbox!",
                discord_message=(
                    f"Congratulations! You have ranked up to **{new_rank}**!\n"
                    "[Log into the website to open your lootbox!](https://genji.pk/lootbox)"
                ),
                metadata={"old_rank": old_rank, "new_rank": new_rank, "reason": "rank_up"},
            )

            await self.bot.notifications.notify_with_channel_ping(
                channel=self.xp_channel,
                user_id=event.user_id,
                event_type=NotificationEventType.RANK_UP,
                title="Rank Up!",
                body=f"You ranked up from {old_rank} to {new_rank}!",
                metadata={"old_rank": old_rank, "new_rank": new_rank},
                ping_message=(
                    f"<:_:976468395505614858> {user.display_name} has ranked up! **{old_rank}** -> **{new_rank}**"
                ),
                fallback_message=(
                    f"<:_:976468395505614858> {user.display_name} has ranked up! **{old_rank}** -> **{new_rank}**"
                ),
            )

        if xp_data.prestige_change:
            for __ in range(15):
                await self.bot.api.grant_active_key_to_user(event.user_id)

            old_rank = " ".join((xp_data.old_main_tier_name, xp_data.old_sub_tier_name))
            new_rank = " ".join((xp_data.new_main_tier_name, xp_data.new_sub_tier_name))

            await self._update_xp_roles_for_user(event.user_id, xp_data.old_main_tier_name, xp_data.new_main_tier_name)
            await self._update_xp_prestige_roles_for_user(
                event.user_id, xp_data.old_prestige_level, xp_data.new_prestige_level
            )

            await self.bot.notifications.notify_dm_only(
                user_id=event.user_id,
                event_type=NotificationEventType.LOOTBOX_EARNED,
                title="Prestige Lootboxes Earned!",
                body=f"You prestiged to level {xp_data.new_prestige_level} and earned 15 lootboxes!",
                discord_message=(
                    f"Congratulations! You have prestiged up to **{xp_data.new_prestige_level}**!\n"
                    "[Log into the website to open your 15 lootboxes!](https://genji.pk/lootbox)"
                ),
                metadata={
                    "old_prestige": xp_data.old_prestige_level,
                    "new_prestige": xp_data.new_prestige_level,
                    "lootbox_count": 15,
                },
            )

            await self.bot.notifications.notify_with_channel_ping(
                channel=self.xp_channel,
                user_id=event.user_id,
                event_type=NotificationEventType.PRESTIGE,
                title="Prestige!",
                body=f"You prestiged from level {xp_data.old_prestige_level} to {xp_data.new_prestige_level}!",
                metadata={
                    "old_prestige": xp_data.old_prestige_level,
                    "new_prestige": xp_data.new_prestige_level,
                },
                ping_message=(
                    f"<:_:976468395505614858><:_:976468395505614858><:_:976468395505614858> "
                    f"{user.display_name} has prestiged! "
                    f"**Prestige {xp_data.old_prestige_level}** -> **Prestige {xp_data.new_prestige_level}**"
                ),
                fallback_message=(
                    f"<:_:976468395505614858><:_:976468395505614858><:_:976468395505614858> "
                    f"{user.display_name} has prestiged! "
                    f"**Prestige {xp_data.old_prestige_level}** -> **Prestige {xp_data.new_prestige_level}**"
                ),
            )


@app_commands.guilds(int(os.getenv("DISCORD_GUILD_ID", "0")))
class XPCog(commands.GroupCog, group_name="xp"):
    def __init__(self, bot: core.Genji) -> None:
        """Initialize XPCog."""
        self.bot = bot

    @app_commands.command(name="grant")
    async def _command_grant_xp(
        self,
        itx: GenjiItx,
        user: app_commands.Transform[int, transformers.UserTransformer],
        amount: app_commands.Range[int, 1],
    ) -> None:
        """Grant user XP."""
        user_data = await self.bot.api.get_user(user)
        nickname = user_data.coalesced_name if user_data else "Unknown User"
        await itx.response.send_message(f"Granting user {nickname} {amount} XP.", ephemeral=True)
        data = XpGrantRequest(amount, "Other")
        await self.bot.api.grant_user_xp(user, data)


async def setup(bot: core.Genji) -> None:
    """Initialize and attach the XP manager to the bot.

    Args:
        bot (core.Genji): The running bot instance.
    """
    bot.xp = XPHandler(bot)
    await bot.add_cog(XPCog(bot))
