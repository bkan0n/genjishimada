from __future__ import annotations

import asyncio
import logging
from http import HTTPStatus
from typing import TYPE_CHECKING

from genjishimada_sdk.queue import BOT_ENTRYPOINTS, DependencyFailed, DependencyUnavailable, JobContext
from genjishimada_sdk.queue_worker import QueueWorker

from extensions._queue_registry import QueueHandler
from utilities.errors import APIHTTPError
from utilities.queue_config import queue_database_url

if TYPE_CHECKING:
    import core

log = logging.getLogger(__name__)


class QueueHandlerService:
    """Run bot-owned jobs with a database credential limited to queue tables."""

    def __init__(self, bot: core.Genji) -> None:
        """Create the queue worker, leaving network connections to its supervisor."""
        self.bot = bot
        self.worker = QueueWorker(queue_database_url(), owner="bot", before_job=self._prepare_job)
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._closing = False
        self.failure: BaseException | None = None
        self._shutdown_task: asyncio.Task[None] | None = None

    async def _prepare_job(self, context: JobContext) -> None:
        try:
            await self.bot.api.job_operation("POST", f"/{context.job_id}/prepare")
        except APIHTTPError as exc:
            if exc.status == HTTPStatus.FAILED_DEPENDENCY:
                raise DependencyFailed("Job dependency requires operator intervention") from exc
            if exc.status == HTTPStatus.LOCKED:
                raise DependencyUnavailable("Job dependency is not ready") from exc
            raise

    def _collect_handlers(self) -> dict[str, QueueHandler]:
        handlers: dict[str, QueueHandler] = {}
        for instance in (
            self.bot.completions,
            self.bot.playtest,
            self.bot.newsfeed,
            self.bot.notifications,
            self.bot.tournaments,
            self.bot.xp,
            self.bot.map_editor,
        ):
            for name in dir(instance):
                candidate = getattr(instance, name)
                event_name = getattr(candidate, "_queue_name", None)
                if event_name:
                    if event_name in handlers:
                        raise RuntimeError(f"Duplicate handler for {event_name}")
                    handlers[event_name] = candidate
        return handlers

    def start(self) -> None:
        """Register handlers after all application extensions have loaded."""
        handlers = self._collect_handlers()
        if handlers.keys() != BOT_ENTRYPOINTS:
            raise RuntimeError(f"Queue handler inventory mismatch: {handlers.keys() ^ BOT_ENTRYPOINTS}")
        for name, handler in handlers.items():
            self.worker.add_handler(name, handler)
        self._task = asyncio.create_task(self._run(), name="bot-queue-worker")
        self._task.add_done_callback(self._worker_stopped)

    def _worker_stopped(self, task: asyncio.Task[None]) -> None:
        if self._closing:
            return
        error = None if task.cancelled() else task.exception()
        self.failure = error or RuntimeError("Queue worker stopped unexpectedly")
        log.critical("Queue worker stopped; closing the bot for process restart", exc_info=error)
        self._shutdown_task = asyncio.create_task(self.bot.close(), name="failed-queue-shutdown")

    async def _run(self) -> None:
        await self.bot.wait_until_ready()
        self._running = True
        await self.worker.run()

    async def close(self) -> None:
        """Drain jobs before closing the HTTP and Discord clients they use."""
        self._closing = True
        self.worker.stop()
        if self._task:
            if not self._running:
                self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)


async def setup(bot: core.Genji) -> None:
    """Attach the durable queue service to the bot."""
    bot.queue = QueueHandlerService(bot)
