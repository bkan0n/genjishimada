"""Persistent operator controls and a queue-independent failure alert supervisor."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
from datetime import datetime, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, Any
from urllib.parse import quote
from uuid import UUID

import aiohttp
import discord
from discord import ui

from utilities.base import BaseCog
from utilities.errors import APIHTTPError, APIUnavailableError

if TYPE_CHECKING:
    import core
    from utilities._types import GenjiItx

log = logging.getLogger(__name__)
POLL_SECONDS = 15
MAX_BACKOFF_SECONDS = 120
ALERT_PAGE_SIZE = 100
MAX_DIAGNOSTIC_LENGTH = 1400
OPERATORS = frozenset(
    int(value.strip()) for value in os.getenv("QUEUE_OPERATOR_IDS", "141372217677053952").split(",") if value.strip()
)


def _summary(job: dict[str, Any]) -> str:
    """Render only operational metadata, never an unrestricted job payload."""
    effects = job.get("effects") or []
    completed = sum(effect.get("state", effect.get("status")) == "completed" for effect in effects)
    error = discord.utils.escape_mentions(str(job.get("error_msg") or "No recorded error."))
    error = re.sub(r"(?i)(authorization|password|token|secret)\s*[:=]\s*\S+", r"\1=[redacted]", error)
    error = re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1[redacted]@", error)
    return (
        f"**Event:** {job['event_name']}\n"
        f"**Job:** `{job['job_id']}`\n"
        f"**Status:** {job['status']} · **Generation:** {job['retry_generation']}\n"
        f"**Failures:** {job.get('handler_failures', 0)} · **Completed effects:** {completed}/{len(effects)}\n"
        f"**Failed at:** {job.get('failed_at') or '—'}\n"
        f"**Last error:** {error[:500]}"
    )


def _has_uncertain_effect(job: dict[str, Any]) -> bool:
    return any(
        effect.get("state", effect.get("status")) in {"uncertain", "claimed", "pending", "started"}
        and not str(effect.get("effect_key", "")).startswith("alert:")
        for effect in job.get("effects") or []
    )


def _shared_outage(error: Exception) -> bool:
    return isinstance(error, (APIUnavailableError, aiohttp.ClientError, OSError, TimeoutError)) or (
        isinstance(error, (APIHTTPError, discord.HTTPException))
        and (error.status >= HTTPStatus.INTERNAL_SERVER_ERROR or error.status == HTTPStatus.TOO_MANY_REQUESTS)
    )


class JobAction(
    ui.DynamicItem[ui.Button[ui.View]],
    template=r"job:(?P<action>retry|details):v1:(?P<id>[0-9a-f-]{36}):(?P<generation>[0-9]+)",
):
    """Reconstruct controls from stable job identities after any bot restart."""

    def __init__(self, job_id: UUID, generation: int, action: str, *, disabled: bool = False) -> None:
        """Create a compact button whose authority remains entirely in the API."""
        self.job_id = job_id
        self.generation = generation
        self.action = action
        super().__init__(
            ui.Button(
                label="Retry job" if action == "retry" else "Details",
                style=discord.ButtonStyle.primary if action == "retry" else discord.ButtonStyle.secondary,
                custom_id=f"job:{action}:v1:{job_id}:{generation}",
                disabled=disabled,
            )
        )

    @classmethod
    async def from_custom_id(
        cls,
        interaction: GenjiItx,
        item: ui.Item[Any],
        match: re.Match[str],
    ) -> JobAction:
        """Decode the identity without delaying Discord's interaction acknowledgement."""
        return cls(UUID(match["id"]), int(match["generation"]), match["action"])

    async def callback(self, interaction: GenjiItx) -> None:
        """Ask the API to validate the operator, current generation, and bound message."""
        await interaction.response.defer(ephemeral=True)
        if interaction.user.id not in OPERATORS:
            await interaction.followup.send("This action is restricted to queue operators.", ephemeral=True)
            return
        if interaction.guild_id is None or interaction.channel_id is None or interaction.message is None:
            await interaction.followup.send("This control requires its original operator alert.", ephemeral=True)
            return
        context = {
            "operator_id": interaction.user.id,
            "guild_id": interaction.guild_id,
            "channel_id": interaction.channel_id,
            "message_id": interaction.message.id,
        }
        api = interaction.client.api
        try:
            if self.action == "details":
                job = await api.job_operation("GET", f"/{self.job_id}/operations", params=context)
                detail = _summary(job)
                if _has_uncertain_effect(job):
                    detail += "\n\nAn external effect needs reconciliation before this job can be retried."
                await interaction.followup.send(
                    detail[:MAX_DIAGNOSTIC_LENGTH],
                    ephemeral=True,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
                return
            result = await api.job_operation(
                "POST",
                f"/{self.job_id}/retry",
                data={
                    **context,
                    "expected_generation": self.generation,
                    "request_id": str(interaction.id),
                },
            )
        except (APIUnavailableError, APIHTTPError, aiohttp.ClientError, TimeoutError) as exc:
            # A lost response does not mean that the committed operation failed. Read
            # authoritative state instead of issuing a different retry request.
            with contextlib.suppress(APIUnavailableError, APIHTTPError, aiohttp.ClientError, TimeoutError):
                job = await api.job_operation("GET", f"/{self.job_id}/operations", params=context)
                if job["retry_generation"] > self.generation and job["status"] in {"queued", "processing", "succeeded"}:
                    await interaction.followup.send(f"Job is {job['status']}.", ephemeral=True)
                    return
            log.warning("Job control could not read its result for %s: %s", self.job_id, type(exc).__name__)
            await interaction.followup.send(
                "The job's current result is unavailable. Use Details after the API recovers.",
                ephemeral=True,
            )
            return
        outcomes = {
            "queued": "Job queued. Completed steps will be preserved.",
            "requeued": "Job queued. Completed steps will be preserved.",
            "already_queued": "This job is already queued.",
            "running": "This job is already running.",
            "succeeded": "This job has already succeeded.",
            "stale": "This alert refers to an older attempt. Use the updated alert.",
            "reconciliation_required": "An external effect needs reconciliation before retry.",
            "requires_reconciliation": "An external effect needs reconciliation before retry.",
        }
        await interaction.followup.send(outcomes.get(result["outcome"], f"Job is {result['status']}."), ephemeral=True)
        # The supervisor renders the committed state. An edit failure here cannot make
        # an accepted retry appear rejected or undo its audit record.


def _view(job: dict[str, Any]) -> ui.View:
    view = ui.View(timeout=None)
    job_id, generation = UUID(str(job["job_id"])), job["retry_generation"]
    view.add_item(
        JobAction(
            job_id, generation, "retry", disabled=job["status"] not in {"failed", "held"} or _has_uncertain_effect(job)
        )
    )
    view.add_item(JobAction(job_id, generation, "details"))
    sentry_url = job.get("sentry_url")
    if isinstance(sentry_url, str) and sentry_url.startswith("https://"):
        view.add_item(ui.Button(label="Sentry", url=sentry_url))
    return view


class JobOperationsCog(BaseCog):
    """Deliver durable operational alerts without depending on the failed work queue."""

    async def cog_load(self) -> None:
        """Register restart-safe buttons and supervise alert delivery separately."""
        self.bot.add_dynamic_items(JobAction)
        self._task = asyncio.create_task(self._supervise(), name="job-failure-alerts")

    async def cog_unload(self) -> None:
        """Stop the alert task before its HTTP client closes."""
        self._task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._task
        self.bot.remove_dynamic_items(JobAction)

    async def _supervise(self) -> None:
        await self.bot.wait_until_ready()
        delay = POLL_SECONDS
        unavailable = False
        failed_jobs: set[str] = set()
        seen_jobs: set[str] = set()
        after: str | None = None
        while True:
            try:
                jobs = await self.bot.api.job_operation("GET", "/alerts", params={"after": after} if after else None)
                seen_jobs.update(str(job["job_id"]) for job in jobs)
                for job in jobs:
                    job_id = str(job["job_id"])
                    try:
                        await self._render(job)
                    except Exception as error:
                        if _shared_outage(error):
                            raise
                        if job_id not in failed_jobs:
                            log.exception("Could not update queue alert for job %s", job_id)
                            failed_jobs.add(job_id)
                    else:
                        if job_id in failed_jobs:
                            log.info("Queue alert for job %s recovered", job_id)
                            failed_jobs.remove(job_id)
                if len(jobs) == ALERT_PAGE_SIZE:
                    after = str(jobs[-1]["job_id"])
                else:
                    after = None
                    failed_jobs.intersection_update(seen_jobs)
                    seen_jobs.clear()
                if unavailable:
                    log.info("Queue failure alert delivery recovered")
                unavailable = False
                delay = POLL_SECONDS
            except Exception:
                if not unavailable:
                    log.warning("Queue failure alerts unavailable; delivery will resume after recovery", exc_info=True)
                unavailable = True
                delay = min(delay * 2, MAX_BACKOFF_SECONDS)
            await asyncio.sleep(delay)

    async def _find_marker(
        self,
        channel: discord.TextChannel,
        job: dict[str, Any],
        marker: str,
    ) -> discord.Message | None:
        since = job.get("failed_at")
        after = None
        if since:
            after = datetime.fromisoformat(str(since).replace("Z", "+00:00")) - timedelta(minutes=1)
        # Fully inspect the relevant interval. A history permission failure propagates;
        # an inaccessible or partial history must not authorize another send.
        async for message in channel.history(limit=None, after=after, oldest_first=False):
            if self.bot.user and message.author.id == self.bot.user.id and marker in message.content:
                return message
        return None

    async def _ensure_message(
        self,
        channel: discord.TextChannel,
        job: dict[str, Any],
        key: str,
        marker: str,
        content: str,
        **kwargs: Any,  # noqa: ANN401
    ) -> discord.Message:
        path = f"/{job['job_id']}/effects/{quote(key, safe='')}"
        claim = await self.bot.api.job_operation("POST", path + "/claim", data={"destination": str(channel.id)})
        if claim["state"] == "completed":
            try:
                return await channel.fetch_message(int(claim["result"]["message_id"]))
            except discord.NotFound:
                # A definite 404 permits a new replacement effect, never an unbound
                # repost while the original result remains ambiguous.
                return await self._ensure_message(
                    channel,
                    job,
                    f"alert:card:{claim['result']['message_id']}",
                    marker,
                    content,
                    **kwargs,
                )
        if claim["state"] == "uncertain":
            message = await self._find_marker(channel, job, marker)
            if message is None:
                raise RuntimeError("An alert send is unresolved")
        else:
            try:
                message = await channel.send(content + "\n" + marker, **kwargs)
            except discord.HTTPException as exc:
                if exc.status in {400, 401, 403, 404, 405, 429}:
                    await self.bot.api.job_operation("POST", path + "/release")
                raise
        await self.bot.api.job_operation(
            "POST",
            path + "/complete",
            data={
                "result": {"channel_id": channel.id, "message_id": message.id},
            },
        )
        return message

    async def _render(self, job: dict[str, Any]) -> None:
        channel = self.bot.get_channel(self.bot.config.channels.updates.job_alerts)
        if not isinstance(channel, discord.TextChannel):
            raise RuntimeError("Job alerts channel is unavailable")
        recipient = self.bot.config.channels.updates.job_alert_user_id
        mentions = discord.AllowedMentions(
            users=[discord.Object(recipient)], everyone=False, roles=False, replied_user=False
        )
        marker = f"-# job-alert:{job['job_id']}"
        body = "### Queue job\n" + _summary(job)
        newly_bound = job.get("message_id") is None
        if newly_bound:
            message = await self._ensure_message(
                channel,
                job,
                "alert:card",
                marker,
                (f"<@{recipient}>\n" if job["retry_generation"] == 0 else "") + body,
                view=_view(job),
                allowed_mentions=mentions,
            )
        else:
            try:
                message = await channel.fetch_message(int(job["message_id"]))
            except discord.NotFound:
                message = await self._ensure_message(
                    channel,
                    job,
                    f"alert:card:{job['message_id']}",
                    marker,
                    body,
                    view=_view(job),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            await message.edit(
                content=body + "\n" + marker, view=_view(job), allowed_mentions=discord.AllowedMentions.none()
            )
        generation = job["retry_generation"]
        notified = job.get("notified_generation")
        if newly_bound and generation == 0:
            notified = generation
        if job["status"] in {"failed", "held"} and notified != generation:
            await self._ensure_message(
                channel,
                job,
                f"alert:notification:{generation}",
                f"-# job-failure:{job['job_id']}:{generation}",
                f"<@{recipient}> Job `{job['job_id']}` failed again (generation {generation}).",
                reference=message,
                allowed_mentions=mentions,
            )
            notified = generation
        await self.bot.api.job_operation(
            "POST",
            f"/{job['job_id']}/alert",
            data={
                "guild_id": channel.guild.id,
                "channel_id": channel.id,
                "message_id": message.id,
                "notified_generation": notified,
                "expected_generation": generation,
                "rendered_status": job["status"],
                "observed_at": job["observed_at"],
            },
        )


async def setup(bot: core.Genji) -> None:
    """Load operational controls independently of consumer initialization."""
    await bot.add_cog(JobOperationsCog(bot))
