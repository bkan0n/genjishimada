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
import datetime as dt
import os
from http import HTTPStatus
from logging import getLogger
from typing import TYPE_CHECKING, Any, Sequence, cast

import discord
from discord import AllowedMentions, ButtonStyle, MediaGalleryItem, TextChannel, app_commands, ui
from discord.ext import commands
from genjishimada_sdk.maps import OverwatchCode
from genjishimada_sdk.tournaments import (
    TournamentCategoryResponse,
    TournamentChooseMapRequest,
    TournamentCompletionCreatedEvent,
    TournamentCycleCompletedEvent,
    TournamentCycleStartedEvent,
    TournamentLeaderboardEntryResponse,
    TournamentVerificationChangedEvent,
)

from extensions._queue_registry import queue_consumer
from utilities import transformers
from utilities.base import BaseCog, BaseHandler
from utilities.errors import APIHTTPError, APIUnavailableError, UserFacingError
from utilities.extra import poll_job_until_complete
from utilities.paginator import StaticPaginatorView

if TYPE_CHECKING:
    from aio_pika.abc import AbstractIncomingMessage

    import core
    from utilities._types import GenjiItx

log = getLogger(__name__)

# Courtesy throttle between per-member role edits to stay well under Discord's
# 50 req/s global limit on simultaneous category transitions (Pitfall 2). discord.py
# auto-handles 429s; this stagger is the safety margin success criterion 4 requires.
_ROLE_OP_DELAY: float = 1.0

# Community host for Overwatch workshop codes (clickable link in the new-cycle embed).
_WORKSHOP_URL = "https://workshop.codes/{code}"

# Top-N standings shown on the results podium (D-03 — compact embed).
_PODIUM_SIZE = 3


class TournamentRejectionReasonModal(ui.Modal):
    """Collects an optional free-text reason when a mod rejects a tournament run.

    The tournament reject endpoint (Plan 11-03) takes no reason payload — the row is
    simply left unverified — so the reason is surfaced back to the moderator only and not
    forwarded to the API. The modal exists to mirror the completions reject UX and to give
    the reject a confirmation gate (an empty submit cancels the reject).
    """

    reason = ui.TextInput(label="Reason", style=discord.TextStyle.paragraph)

    def __init__(self) -> None:
        """Initialize the tournament rejection-reason modal."""
        super().__init__(title="Rejection Reason")

    async def on_submit(self, itx: GenjiItx) -> None:
        """Acknowledge the submitted reason ephemerally.

        Args:
            itx: The Discord interaction context.
        """
        await itx.response.send_message(f"Sent the rejection reason as:\n>>> {self.reason.value}", ephemeral=True)


class TournamentVerificationAcceptButton(ui.Button):
    """Accept a non-PB tournament run — routes the verdict to the verify API.

    The custom_id ``tournament:accept`` is deliberately DISTINCT from the completions
    view's ``completions:accept`` (P3 / T-11-18) so the two persistent components never
    collide. The bot NEVER writes the DB (T-11-17 / CLAUDE.md): the verdict only takes
    effect through ``bot.api.verify_tournament_completion`` (the ``tournaments:verify``
    endpoint from 11-03).
    """

    view: "TournamentVerificationView"

    def __init__(self) -> None:
        """Initialize the Accept button for verifying a tournament run."""
        super().__init__(style=ButtonStyle.green, label="Accept", custom_id="tournament:accept")

    async def callback(self, itx: GenjiItx) -> None:
        """Verify the tournament completion via the API and poll the job to completion.

        Args:
            itx: The Discord interaction context.
        """
        await itx.response.defer(ephemeral=True, thinking=True)

        # WR-04: call the API BEFORE disabling the card. If the call raises, the
        # card stays interactive so the moderator can retry; disabling first
        # would permanently lock a card whose verdict never took effect.
        try:
            job_status = await self.view.bot.api.verify_tournament_completion(self.view.completion_id)
        except (APIHTTPError, APIUnavailableError):
            await itx.edit_original_response(
                content="There was an error reaching the API. Please try again."
            )
            return

        for c in self.view.walk_children():
            if isinstance(c, ui.Button):
                c.disabled = True
        if itx.message:
            await itx.message.edit(view=self.view)

        job = await poll_job_until_complete(itx.client.api, job_status.id)

        if not job:
            await itx.edit_original_response(
                content=(
                    "There was an unknown error while processing. "
                    "Please do not try again until it has been resolved."
                )
            )
        elif job.status == "succeeded":
            await itx.edit_original_response(content="Successfully verified the tournament run.")
        else:
            await itx.edit_original_response(
                content=(
                    "There was an error while processing. Please do not try again until it has been resolved."
                )
            )


class TournamentVerificationRejectButton(ui.Button):
    """Reject a non-PB tournament run — routes the verdict to the reject API.

    The custom_id ``tournament:reject`` is DISTINCT from ``completions:reject`` (P3 /
    T-11-18). A reason modal gates the reject (an empty submit cancels it); the reject
    endpoint takes no reason payload, so the reason is shown back to the moderator only.
    The bot NEVER writes the DB — the reject takes effect through
    ``bot.api.reject_tournament_completion`` (T-11-17).
    """

    view: "TournamentVerificationView"

    def __init__(self) -> None:
        """Initialize the Reject button for denying a tournament run."""
        super().__init__(style=ButtonStyle.red, label="Reject", custom_id="tournament:reject")

    async def callback(self, itx: GenjiItx) -> None:
        """Open the reason modal, then reject the tournament completion via the API.

        Args:
            itx: The Discord interaction context.
        """
        modal = TournamentRejectionReasonModal()
        await itx.response.send_modal(modal)
        await modal.wait()
        if not modal.reason.value:
            return

        # WR-04: call the API BEFORE disabling the card so a failed reject leaves
        # a retryable card instead of a permanently-disabled one.
        try:
            job_status = await self.view.bot.api.reject_tournament_completion(self.view.completion_id)
        except (APIHTTPError, APIUnavailableError):
            await itx.followup.send(
                content="There was an error reaching the API. Please try again.", ephemeral=True
            )
            return

        for c in self.view.walk_children():
            if isinstance(c, ui.Button):
                c.disabled = True
        if itx.message:
            await itx.message.edit(view=self.view)

        # WR-05: poll the job like Accept does, so a failed reject is reported as
        # a failure rather than a premature "Successfully rejected".
        job = await poll_job_until_complete(itx.client.api, job_status.id)
        if not job:
            await itx.followup.send(
                content=(
                    "There was an unknown error while processing. "
                    "Please do not try again until it has been resolved."
                ),
                ephemeral=True,
            )
        elif job.status == "succeeded":
            await itx.followup.send(content="Successfully rejected the tournament run.", ephemeral=True)
        else:
            await itx.followup.send(
                content=(
                    "There was an error while processing. Please do not try again until it has been resolved."
                ),
                ephemeral=True,
            )


class TournamentVerificationView(ui.LayoutView):
    """Mod Accept/Reject card for a non-PB tournament run (D-04 video path).

    Renders the run's screenshot/video/time/user from the
    ``TournamentCompletionCreatedEvent`` (no extra fetch — the event carries everything,
    Plan 11-01). The submitting user is referenced ONLY by numeric ``<@user_id>`` and the
    view is sent with ``AllowedMentions(everyone=False, roles=False)`` (Phase-9
    mention-injection mitigation / T-11-19). The Accept/Reject verdict routes to the
    ``tournaments:verify`` API — the bot never writes the DB (T-11-17).
    """

    def __init__(self, event: TournamentCompletionCreatedEvent, bot: core.Genji) -> None:
        """Initialize the tournament verification view from a completion-created event.

        Args:
            event: The tournament completion-created event to render.
            bot: The bot instance used for the verify/reject API calls.
        """
        self.completion_id = event.completion_id
        self.event = event
        self.bot = bot
        super().__init__(timeout=None)
        self._rebuild_components()

    def _rebuild_components(self) -> None:
        """Build the container with the run details, screenshot gallery, and action row."""
        details = (
            f"New Tournament Submission from <@{self.event.user_id}>\n"
            f"**Time:** {self.event.time:.2f}s\n"
            f"**Cycle:** {self.event.cycle_id}\n"
            + (f"**Video:** {self.event.video}\n" if self.event.video else "")
        )
        container = ui.Container(
            ui.TextDisplay(details),
            ui.Separator(),
            ui.MediaGallery(MediaGalleryItem(self.event.screenshot)),
            ui.ActionRow(
                TournamentVerificationAcceptButton(),
                TournamentVerificationRejectButton(),
            ),
        )
        self.add_item(container)

    async def on_error(self, itx: GenjiItx, error: Exception, item: ui.Item[Any], /) -> None:
        """Delegate component errors to the application command tree handler.

        Args:
            itx: The Discord interaction context.
            error: The raised exception.
            item: The UI item that raised.
        """
        await itx.client.tree.on_error(itx, cast("app_commands.AppCommandError", error))


class TournamentHandler(BaseHandler):
    """Posts tournament announcements and transfers the per-category champion role."""

    announcement_channel: TextChannel
    verification_channel: TextChannel

    async def _resolve_channels(self) -> None:
        """Resolve the announcement channel and the (shared) mod verification channel.

        The non-PB tournament Accept/Reject card reuses the EXISTING mod verification
        queue (``channels.submission.verification_queue``) rather than a dedicated channel
        — mods already watch this queue for completion review (CONTEXT discretion default).
        """
        channel = self.bot.get_channel(self.bot.config.channels.tournament.announcements)
        assert isinstance(channel, TextChannel)
        self.announcement_channel = channel

        verification_channel = self.bot.get_channel(self.bot.config.channels.submission.verification_queue)
        assert isinstance(verification_channel, TextChannel)
        self.verification_channel = verification_channel

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
                f"**Map:** [{event.map_name}]({_WORKSHOP_URL.format(code=event.map_code)}) (`{event.map_code}`)"
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
        """Transfer the champion role, then post the single results embed.

        Ordering (Pitfall 5): the role transfer runs FIRST and the single
        ``channel.send`` LAST, so a role-op failure retries (claim released) before any
        message posts — a re-stripped/re-granted role is effectively idempotent whereas a
        duplicate ``send`` is visible spam.

        Champion transfer (D-04 / D-05): the role is stripped from ALL current holders
        (self-healing), then granted to the winner — or left vacant when ``winner_user_id``
        is None. Member edits are staggered with ``_ROLE_OP_DELAY`` (Pitfall 2). A winner
        who left the guild (``get_member`` None) is logged and skipped, never crashed
        (Pitfall 3 — crashing would DLQ a valid event).

        Security: the winner is mentioned only by numeric ``<@user_id>``; the free-text
        standings ``name`` is never used in a mention, and ``allowed_mentions`` restricts
        pings to the winner (no ``@everyone``/role mentions). The embed deliberately omits
        any experience-points line (D-03 deviation — XP is delivered separately via
        ``api.xp.grant``).
        """
        log.debug("[→] [Tournament] cycle_completed cycle=%s category=%s", event.cycle_id, event.category_id)
        category = await self.bot.api.get_tournament_category(event.category_id)

        # 1) Champion role transfer FIRST (Pitfall 5).
        await self._transfer_champion_role(event, category)

        # 2) Build + post the single results embed LAST.
        embed = discord.Embed(title=f"{category.name} — Cycle Results", color=discord.Color.gold())
        podium_lines = [
            f"`#{entry.rank}` <@{entry.user_id}> — {entry.time:.2f}s" for entry in event.standings[:_PODIUM_SIZE]
        ]
        embed.add_field(name="Podium", value="\n".join(podium_lines) or "No submissions", inline=False)

        # The announcement (embed field, content ping, and allow-list) is driven by the
        # EVENT's winner — the source of truth for who won — not by the role-transfer side
        # effect, so the ping stays consistent even if the role grant could not complete.
        content: str | None = None
        allowed_users: list[discord.abc.Snowflake] = []
        if event.winner_user_id is not None:
            embed.add_field(
                name="Champion",
                value=f"<@{event.winner_user_id}> crowned Champion of {category.name}!",
                inline=False,
            )
            content = f"<@{event.winner_user_id}>"
            allowed_users = [discord.Object(id=event.winner_user_id)]

        allowed_mentions = discord.AllowedMentions(users=allowed_users, everyone=False, roles=False)
        await self.announcement_channel.send(content=content, embed=embed, allowed_mentions=allowed_mentions)
        log.info("[✓] [Tournament] posted results embed for cycle=%s", event.cycle_id)

    @queue_consumer(
        "api.tournament.completion.created",
        struct_type=TournamentCompletionCreatedEvent,
        idempotent=True,
    )
    async def _on_completion_created(
        self, event: TournamentCompletionCreatedEvent, _: AbstractIncomingMessage
    ) -> None:
        """Render the mod Accept/Reject card for a non-PB video tournament run (D-04).

        The event carries the run's screenshot/video/time/user (Plan 11-01), so the card
        renders without any extra API fetch. The card is posted to the shared mod
        verification queue. Idempotent — the outbox ``message_id``
        (``tournament:submission:{user_id}:{tc_id}``) is the dedupe key, no hand-rolled key
        (Phase-9 pattern / T-11-20).
        """
        log.debug(
            "[→] [Tournament] completion_created completion=%s cycle=%s user=%s",
            event.completion_id,
            event.cycle_id,
            event.user_id,
        )
        view = TournamentVerificationView(event, self.bot)
        await self.verification_channel.send(
            view=view,
            allowed_mentions=AllowedMentions(everyone=False, roles=False),
        )
        log.info("[✓] [Tournament] posted Accept/Reject card for completion=%s", event.completion_id)

    @queue_consumer(
        "api.tournament.verification.changed",
        struct_type=TournamentVerificationChangedEvent,
        idempotent=True,
    )
    async def _on_verification_changed(
        self, event: TournamentVerificationChangedEvent, _: AbstractIncomingMessage
    ) -> None:
        """Surface the verdict of a tournament verification to the verification channel.

        On verify the moderator gets a confirmation post; a reject leaves the row
        unverified and is announced as such. The submitting user is referenced ONLY by
        numeric ``<@user_id>`` with ``AllowedMentions(everyone=False, roles=False)``
        (T-11-19). Idempotent — the outbox ``message_id``
        (``tournament:verify|reject:{tc_id}``) is the dedupe key (T-11-20).
        """
        log.debug(
            "[→] [Tournament] verification_changed completion=%s verified=%s user=%s",
            event.tournament_completion_id,
            event.verified,
            event.user_id,
        )
        verdict = "verified" if event.verified else "rejected"
        await self.verification_channel.send(
            content=(
                f"Tournament run from <@{event.user_id}> ({event.time:.2f}s) was **{verdict}** "
                f"(completion `{event.tournament_completion_id}`, cycle `{event.cycle_id}`)."
            ),
            allowed_mentions=AllowedMentions(everyone=False, roles=False),
        )
        log.info(
            "[✓] [Tournament] surfaced %s verdict for completion=%s",
            verdict,
            event.tournament_completion_id,
        )

    async def _transfer_champion_role(
        self,
        event: TournamentCycleCompletedEvent,
        category: TournamentCategoryResponse,
    ) -> discord.Member | None:
        """Strip the champion role from all holders then grant it to the winner.

        Returns the winner ``Member`` when the role was granted, else None (no role
        configured, no winner, or the winner left the guild).
        """
        # No champion role configured for this category (champion_role_id is int | None):
        # nothing to transfer. This is a configuration state, NOT an operational fault, so
        # it is logged distinctly from a configured-but-missing role below.
        if category.champion_role_id is None:
            log.info(
                "[✓] [Tournament] no champion role configured for category %s; skipping transfer (cycle=%s)",
                category.name,
                event.cycle_id,
            )
            return None

        role = self.guild.get_role(category.champion_role_id)
        if role is None:
            log.warning(
                "[!] [Tournament] champion role %s not found in guild; skipping transfer (cycle=%s)",
                category.champion_role_id,
                event.cycle_id,
            )
            return None

        # D-04: strip from ALL current holders (self-healing), staggered (Pitfall 2). Each
        # strip is isolated: a single member that can't be edited (role hierarchy / transient
        # 403) is logged and skipped rather than crashing the handler — crashing would DLQ a
        # valid event and re-strip every holder on each retry (Pitfall 3).
        reason_reset = f"Tournament {category.name} cycle {event.cycle_id} reset"
        for holder in list(role.members):
            try:
                await holder.remove_roles(role, reason=reason_reset)
            except discord.HTTPException:
                log.warning(
                    "[!] [Tournament] failed to strip champion role from %s; continuing (cycle=%s)",
                    holder.id,
                    event.cycle_id,
                )
            await asyncio.sleep(_ROLE_OP_DELAY)

        # D-05: no winner → leave the role vacant.
        if event.winner_user_id is None:
            log.info("[✓] [Tournament] champion role left vacant for cycle=%s (no winner)", event.cycle_id)
            return None

        winner = self.guild.get_member(event.winner_user_id)
        if winner is None:
            # Pitfall 3: member left between submission and finalization — leave vacant.
            log.warning(
                "[!] [Tournament] winner %s not in guild cache; champion role left vacant (cycle=%s)",
                event.winner_user_id,
                event.cycle_id,
            )
            return None

        try:
            await winner.add_roles(role, reason=f"Champion of {category.name}, cycle {event.cycle_id}")
        except discord.HTTPException:
            log.warning(
                "[!] [Tournament] failed to grant champion role to %s; role left vacant (cycle=%s)",
                event.winner_user_id,
                event.cycle_id,
            )
            return None

        log.info("[✓] [Tournament] granted champion role to %s for cycle=%s", event.winner_user_id, event.cycle_id)
        return winner


class TournamentLeaderboardPaginator(StaticPaginatorView[Any]):
    """Static, in-memory leaderboard paginator (10 entries per page — D-13).

    Pages are built eagerly in ``__init__`` (``StaticPaginatorView`` calls
    ``rebuild_data`` + ``rebuild_components`` immediately, no separate ``.initialize()``).
    Rows render numeric ``<@user_id>`` mentions ONLY — the free-text ``entry.name`` is
    never interpolated into a mention (OQ2 / threat T-10-10: mention-injection
    mitigation, matching the Phase-9 results embed).
    """

    def __init__(self, title: str, entries: Sequence[TournamentLeaderboardEntryResponse]) -> None:
        """Initialize the leaderboard paginator.

        Args:
            title: Heading shown at the top of every page.
            entries: Full ranked leaderboard (must be non-empty — callers
                short-circuit the empty case before constructing the view to avoid a
                zero-page modulo-by-zero on navigation).
        """
        super().__init__(title, entries, page_size=10)

    def build_page_body(self) -> Sequence[ui.Item]:
        """Render the current page as a single text block of ranked rows.

        Returns:
            Sequence[ui.Item]: One ``TextDisplay`` with the page's rows.
        """
        lines = [
            f"`#{entry.rank}` <@{entry.user_id}> — {entry.time:.2f}s" for entry in self.get_current_page_data()
        ]
        return [ui.TextDisplay("\n".join(lines))]


@app_commands.guilds(int(os.getenv("DISCORD_GUILD_ID", "0")))
class TournamentCommandCog(commands.GroupCog, group_name="tournament"):
    """Player-facing ``/tournament`` slash commands (info, leaderboard, streak — D-05).

    All responses are ephemeral (D-10): each subcommand defers ``ephemeral=True`` as its
    first line so per-user data is only ever visible to the invoker (threats T-10-08 /
    T-10-09).
    """

    def __init__(self, bot: core.Genji) -> None:
        """Store the running bot instance.

        Args:
            bot: The running Genji bot.
        """
        self.bot = bot

    @app_commands.command(name="info")
    async def info(
        self,
        itx: GenjiItx,
        category: app_commands.Transform[int, transformers.CategoryTransformer],
    ) -> None:
        """Show the active cycle's rich card for a category (D-08 / D-11 / D-12).

        Args:
            itx: The interaction context.
            category: The tournament category (resolved to its id by the transformer).
        """
        await itx.response.defer(ephemeral=True)
        log.debug("[→] [Tournament] /tournament info category=%s user=%s", category, itx.user.id)

        category_data = await itx.client.api.get_tournament_category(category)
        cycles = (await itx.client.api.list_tournament_cycles(status="active", category_id=category)).cycles
        if not cycles:
            await itx.edit_original_response(content=f"No active cycle for {category_data.name} right now.")
            return

        active = cycles[0]
        map_data = await itx.client.api.get_map(code=active.map_code)

        embed = discord.Embed(
            title=f"Active Tournament Cycle: {category_data.name}",
            description=(
                f"**Map:** [{active.map_name}]({_WORKSHOP_URL.format(code=active.map_code)}) (`{active.map_code}`)"
            ),
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Difficulty", value=str(map_data.difficulty), inline=True)
        embed.add_field(name="Category", value=category_data.name, inline=True)

        # OQ1: the cycles list has no ends_at — compute it locally from started_at and the
        # category's cadence (weekly → 7d, biweekly → 14d). No API change required.
        if active.started_at is not None:
            ends_at = active.started_at + dt.timedelta(days=7 if category_data.cycle_frequency == "weekly" else 14)
            embed.add_field(
                name="Ends",
                value=f"{discord.utils.format_dt(ends_at, 'R')} ({discord.utils.format_dt(ends_at, 'F')})",
                inline=False,
            )

        if map_data.map_banner:
            embed.set_thumbnail(url=map_data.map_banner)

        await itx.edit_original_response(embed=embed)
        log.info("[✓] [Tournament] /tournament info rendered for cycle=%s", active.id)

    @app_commands.command(name="leaderboard")
    async def leaderboard(
        self,
        itx: GenjiItx,
        category: app_commands.Transform[int, transformers.CategoryTransformer],
    ) -> None:
        """Show the active cycle leaderboard, paginated 10-per-page (D-16).

        Args:
            itx: The interaction context.
            category: The tournament category (resolved to its id by the transformer).
        """
        await itx.response.defer(ephemeral=True)
        log.debug("[→] [Tournament] /tournament leaderboard category=%s user=%s", category, itx.user.id)

        category_data = await itx.client.api.get_tournament_category(category)
        cycles = (await itx.client.api.list_tournament_cycles(status="active", category_id=category)).cycles
        if not cycles:
            await itx.edit_original_response(content="No active cycle for that category right now.")
            return

        active = cycles[0]
        entries = await itx.client.api.get_tournament_leaderboard(active.id)

        # Pitfall 1: an empty leaderboard would build a zero-page StaticPaginatorView,
        # and navigation does modulo by the page count → ZeroDivisionError. Short-circuit
        # the friendly empty message BEFORE constructing the view.
        if not entries:
            await itx.edit_original_response(content="No submissions yet — be the first!")
            return

        view = TournamentLeaderboardPaginator(f"{category_data.name} — Leaderboard", entries)
        await itx.edit_original_response(view=view)
        view.original_interaction = itx
        log.info("[✓] [Tournament] /tournament leaderboard rendered for cycle=%s", active.id)

    @app_commands.command(name="streak")
    async def streak(self, itx: GenjiItx) -> None:
        """Show the invoker's own participation streak (self-only — D-02 / D-03).

        The streak endpoint 404s when no record exists (Plan 10-01); the bot owns the
        zero-state mapping (D-04): a 404 renders current 0 / max 0 with encouraging copy.
        Any other status propagates.

        Args:
            itx: The interaction context.
        """
        await itx.response.defer(ephemeral=True)
        log.debug("[→] [Tournament] /tournament streak user=%s", itx.user.id)

        current = 0
        maximum = 0
        try:
            streak_data = await itx.client.api.get_tournament_streak(itx.user.id)
            current = streak_data.current_streak
            maximum = streak_data.max_streak
        except APIHTTPError as e:
            # D-04: only the documented "no streak record" 404 maps to zero-state; any
            # other HTTP error is a genuine fault and must NOT be swallowed.
            if e.status != HTTPStatus.NOT_FOUND:
                raise

        embed = discord.Embed(title="Your Tournament Streak", color=discord.Color.green())
        embed.add_field(name="Current Streak", value=str(current), inline=True)
        embed.add_field(name="Max Streak", value=str(maximum), inline=True)
        if current == 0 and maximum == 0:
            embed.description = "Submit in a cycle to start your streak!"

        await itx.edit_original_response(embed=embed)
        log.info("[✓] [Tournament] /tournament streak rendered for user=%s", itx.user.id)


class TournamentRerollCog(BaseCog):
    """Hosts the flat ``/tournament-reroll`` admin command (D-06).

    Kept OUT of the ``/tournament`` group: ``default_member_permissions`` applies at the
    top-level command/group and cannot cleanly mix open player subcommands with a locked
    admin one, so reroll is a separate flat guild command.
    """

    @app_commands.command(name="tournament-reroll")
    @app_commands.guilds(int(os.getenv("DISCORD_GUILD_ID", "0")))
    @app_commands.default_permissions(manage_guild=True)
    async def tournament_reroll(
        self,
        itx: GenjiItx,
        category: app_commands.Transform[int, transformers.CategoryTransformer],
        code: app_commands.Transform[OverwatchCode, transformers.CodeAllTransformer] | None = None,
    ) -> None:
        """Reroll (random) or explicitly choose the next-cycle map for a category.

        The authoritative access control is the bot-side Mod/Sensei role check below
        (D-07 / threat T-10-07): the bot's single full-scope API key does NOT distinguish
        Discord callers, and ``default_member_permissions`` is only a UI hint.

        Args:
            itx: The interaction context.
            category: The tournament category (resolved to its id by the transformer).
            code: Optional explicit map code (D-15); when omitted a random reroll runs (D-14).
        """
        await itx.response.defer(ephemeral=True)

        assert isinstance(itx.user, discord.Member) and itx.guild
        is_mod = (
            itx.user.get_role(itx.client.config.roles.admin.mod) is not None
            or itx.user.get_role(itx.client.config.roles.admin.sensei) is not None
        )
        if not is_mod:
            # D-07: THE authoritative gate. Raised before any API write so a non-admin
            # never triggers a reroll (asserted by the reroll_gate unit test).
            raise UserFacingError("This command is for moderators only.")

        log.debug("[→] [Tournament] /tournament-reroll category=%s code=%s by=%s", category, code, itx.user.id)
        if code is None:
            result = await itx.client.api.reroll_next_cycle(category)  # D-14: random
        else:
            result = await itx.client.api.choose_next_cycle(category, TournamentChooseMapRequest(map_code=code))

        embed = discord.Embed(title="Next-Cycle Map Updated", color=discord.Color.blurple())
        embed.description = (
            f"**Map:** [{result.map_name}]({_WORKSHOP_URL.format(code=result.map_code)}) (`{result.map_code}`)"
        )
        embed.add_field(name="Difficulty", value=str(result.map_difficulty), inline=True)
        await itx.edit_original_response(embed=embed)
        log.info("[✓] [Tournament] /tournament-reroll set next-cycle map %s for category=%s", result.map_code, category)


async def setup(bot: core.Genji) -> None:
    """Register the tournament handler + slash command cogs.

    Keeps the PUBLIC ``bot.tournaments`` handler attribute (Pitfall 1 — RabbitHandler
    discovers queue consumers by walking ``dir(bot)``) and adds the player command group
    and the flat reroll command as SEPARATE cogs (Pitfall 7 — never assign a cog over
    ``bot.tournaments``). Staying in this module keeps both cogs inside the EXTENSIONS
    sort that loads before ``rabbit.py``.
    """
    bot.tournaments = TournamentHandler(bot)
    await bot.add_cog(TournamentCommandCog(bot))
    await bot.add_cog(TournamentRerollCog(bot))
