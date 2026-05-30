"""Tournament announcement handler.

Consumes the Phase-7 tournament lifecycle events and turns them into Discord
announcements:

- ``api.tournament.cycle_started`` → a rich new-cycle embed (DSC-01).
- ``api.tournament.cycle_completed`` → one results embed with the Top-3 podium and the
  winner highlight (DSC-02), folding in the champion-role transfer (DSC-03 / RWD-03).

The bot is consumer-only: data missing from the events (category name +
``champion_role_id``, map difficulty + banner) is sourced from existing API endpoints on
event receipt (D-07). Both consumers are cycle-scoped idempotent — the Phase-7 outbox sets
``message_id=tournament:{event_type}:{cycle_id}`` and ``@queue_consumer(idempotent=True)``
claims on that id, so no key is hand-rolled here.

The handler is registered as a PUBLIC ``bot.tournaments`` attribute; ``RabbitHandler``
discovers queue consumers by walking ``dir(bot)`` and skips ``_``-prefixed attributes, so a
private attribute would silently never register the consumers.
"""

from __future__ import annotations

import asyncio
from logging import getLogger
from typing import TYPE_CHECKING

import discord
from discord import TextChannel
from genjishimada_sdk.tournaments import (
    TournamentCycleCompletedEvent,
    TournamentCycleStartedEvent,
)

from extensions._queue_registry import queue_consumer
from utilities.base import BaseHandler

if TYPE_CHECKING:
    from aio_pika.abc import AbstractIncomingMessage

    import core

log = getLogger(__name__)

# Courtesy throttle between per-member role edits to stay well under Discord's
# 50 req/s global limit on simultaneous category transitions (Pitfall 2). discord.py
# auto-handles 429s; this stagger is the safety margin success criterion 4 requires.
_ROLE_OP_DELAY: float = 1.0

# Community host for Overwatch workshop codes (clickable link in the new-cycle embed).
_WORKSHOP_URL = "https://workshop.codes/{code}"

# Top-N standings shown on the results podium (D-03 — compact embed).
_PODIUM_SIZE = 3


class TournamentHandler(BaseHandler):
    """Posts tournament announcements and transfers the per-category champion role."""

    announcement_channel: TextChannel

    async def _resolve_channels(self) -> None:
        """Resolve the configured tournament announcement channel."""
        channel = self.bot.get_channel(self.bot.config.channels.tournament.announcements)
        assert isinstance(channel, TextChannel)
        self.announcement_channel = channel

    @queue_consumer(
        "api.tournament.cycle_started",
        struct_type=TournamentCycleStartedEvent,
        idempotent=True,
    )
    async def _on_cycle_started(self, event: TournamentCycleStartedEvent, _: AbstractIncomingMessage) -> None:
        """Post the new-cycle announcement embed (DSC-01 / D-02).

        Sources the category name and the map difficulty/banner from the API on receipt
        (D-07). A missing map raises ``ValueError`` from ``get_map`` — let it propagate to
        the DLQ rather than posting a broken embed.
        """
        log.debug("[→] [Tournament] cycle_started cycle=%s category=%s", event.cycle_id, event.category_id)
        category = await self.bot.api.get_tournament_category(event.category_id)
        map_data = await self.bot.api.get_map(code=event.map_code)

        embed = discord.Embed(
            title=f"New Tournament Cycle: {category.name}",
            description=(
                f"**Map:** [{event.map_name}]({_WORKSHOP_URL.format(code=event.map_code)}) "
                f"(`{event.map_code}`)"
            ),
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Difficulty", value=str(map_data.difficulty), inline=True)
        embed.add_field(name="Category", value=category.name, inline=True)
        embed.add_field(name="Ends", value=discord.utils.format_dt(event.ends_at, "R"), inline=False)
        if map_data.map_banner:
            embed.set_thumbnail(url=map_data.map_banner)

        await self.announcement_channel.send(embed=embed)
        log.info("[✓] [Tournament] posted new-cycle embed for cycle=%s", event.cycle_id)

    @queue_consumer(
        "api.tournament.cycle_completed",
        struct_type=TournamentCycleCompletedEvent,
        idempotent=True,
    )
    async def _on_cycle_completed(self, event: TournamentCycleCompletedEvent, _: AbstractIncomingMessage) -> None:
        """Transfer the champion role then post the results embed (filled in Task 2)."""
        log.debug("[→] [Tournament] cycle_completed cycle=%s category=%s", event.cycle_id, event.category_id)


async def setup(bot: core.Genji) -> None:
    """Register the tournament handler as a PUBLIC bot attribute (Pitfall 1)."""
    bot.tournaments = TournamentHandler(bot)
