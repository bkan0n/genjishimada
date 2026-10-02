"""Checkpoint external sends before execution and retain their durable destinations."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Awaitable, Callable
from urllib.parse import quote

import discord
from genjishimada_sdk.queue import UncertainEffectError, current_job

if TYPE_CHECKING:
    import core


async def execute_effect(
    bot: core.Genji,
    key: str,
    destination: str,
    operation: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    """Resume completed effects and hold ambiguous sends for explicit reconciliation.

    Only definite request rejection releases the reservation. A timeout, connection
    failure, process death, or lost completion response may follow an accepted send.
    """
    context = current_job.get()
    if context is None:
        return await operation()
    path = f"/{context.job_id}/effects/{quote(key, safe='')}"
    claim = await bot.api.job_operation("POST", path + "/claim", data={"destination": destination})
    if claim["state"] == "completed":
        return claim["result"]
    if claim["state"] != "claimed":
        raise UncertainEffectError(f"External effect {key} requires reconciliation")
    try:
        result = await operation()
    except discord.HTTPException as exc:
        if exc.status in {400, 401, 403, 404, 405, 429}:
            await bot.api.job_operation("POST", path + "/release")
            raise
        raise UncertainEffectError(f"External effect {key} may have completed") from exc
    except Exception as exc:
        raise UncertainEffectError(f"External effect {key} may have completed") from exc
    await bot.api.job_operation("POST", path + "/complete", data={"result": result})
    return result


async def send_once(
    bot: core.Genji,
    destination: discord.abc.Messageable,
    key: str,
    *args: Any,  # noqa: ANN401
    **kwargs: Any,  # noqa: ANN401
) -> discord.PartialMessage:
    """Send a message once per job/effect/destination and reuse its binding on replay."""
    if isinstance(destination, (discord.User, discord.Member)):
        destination = await destination.create_dm()
    channel = await destination._get_channel()  # noqa: SLF001
    channel_id = channel.id

    async def send() -> dict[str, Any]:
        message = await destination.send(*args, **kwargs)
        return {"channel_id": message.channel.id, "message_id": message.id}

    result = await execute_effect(bot, f"{key}:{channel_id}", str(channel_id), send)
    view = kwargs.get("view")
    if isinstance(view, (discord.ui.View, discord.ui.LayoutView)) and view.is_persistent():
        bot.add_view(view, message_id=int(result["message_id"]))
    channel = bot.get_partial_messageable(int(result["channel_id"]))
    return channel.get_partial_message(int(result["message_id"]))


async def create_thread_once(
    bot: core.Genji,
    forum: discord.ForumChannel,
    key: str,
    **kwargs: Any,  # noqa: ANN401
) -> tuple[discord.Thread, discord.PartialMessage]:
    """Persist a forum's thread and starter message as one external effect."""

    async def create() -> dict[str, Any]:
        thread, message = await forum.create_thread(**kwargs)
        return {"channel_id": thread.id, "thread_id": thread.id, "message_id": message.id}

    result = await execute_effect(bot, f"{key}:{forum.id}", str(forum.id), create)
    thread_id = int(result["thread_id"])
    thread = forum.get_thread(thread_id) or await bot.fetch_channel(thread_id)
    if not isinstance(thread, discord.Thread):
        raise RuntimeError(f"Effect {key} does not reference a forum thread")
    view = kwargs.get("view")
    if isinstance(view, (discord.ui.View, discord.ui.LayoutView)) and view.is_persistent():
        bot.add_view(view, message_id=int(result["message_id"]))
    return thread, thread.get_partial_message(int(result["message_id"]))


async def forward_once(
    bot: core.Genji,
    message: discord.PartialMessage,
    destination: discord.TextChannel,
    key: str,
) -> None:
    """Checkpoint a forwarded message independently of edits to its source."""

    async def forward() -> dict[str, Any]:
        sent = await message.forward(destination)
        return {"channel_id": sent.channel.id, "message_id": sent.id}

    await execute_effect(bot, f"{key}:{destination.id}", str(destination.id), forward)
