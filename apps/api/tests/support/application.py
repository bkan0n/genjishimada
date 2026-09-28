"""Application fixtures with explicit pools and deterministic in-process events.

HTTP tests execute real business listeners before returning each response. Only
outbound email delivery and screenshot OCR are recorded without invoking their
external services. Tests of those listeners can invoke them directly or supply
an emitter subclass with an empty ``record_only_events`` set.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
from types import TracebackType
from typing import Any, ClassVar

import httpx
from litestar import Litestar
from litestar.events.emitter import BaseEventEmitterBackend
from litestar.events.listener import EventListener
from litestar.exceptions import ImproperlyConfiguredException
from litestar.logging.config import LoggingConfig
from litestar.testing import AsyncTestClient
from litestar_asyncpg import PoolConfig

from app import _async_pg_init, create_app


@dataclass(frozen=True)
class EmittedEvent:
    """An observed event, retaining the same arguments passed to its listener."""

    event_id: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]


class DeterministicEventEmitter(BaseEventEmitterBackend):
    """Queue events until the test client drains them on the application's loop."""

    record_only_events: ClassVar[frozenset[str]] = frozenset(
        {
            "auth.verification.requested",
            "auth.verification.resend",
            "auth.password_reset.requested",
            "completion.ocr.requested",
            "tournament.ocr.requested",
        }
    )

    def __init__(self, listeners: Sequence[EventListener]) -> None:
        super().__init__(listeners=listeners)
        self.emissions: list[EmittedEvent] = []
        self._pending: deque[EmittedEvent] = deque()
        self._drain_lock: asyncio.Lock | None = None

    async def __aenter__(self) -> DeterministicEventEmitter:
        self._drain_lock = asyncio.Lock()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self._drain_lock = None
        self._pending.clear()

    def emit(self, event_id: str, *args: Any, **kwargs: Any) -> None:
        """Record every emission, queuing listeners that do not call external services."""
        if self._drain_lock is None:
            raise RuntimeError("Emitter not initialized")
        if not self.listeners.get(event_id):
            raise ImproperlyConfiguredException(f"no event listeners are registered for event ID: {event_id}")
        event = EmittedEvent(event_id=event_id, args=args, kwargs=kwargs)
        self.emissions.append(event)
        if event_id not in self.record_only_events:
            self._pending.append(event)

    async def drain(self) -> None:
        """Await real listeners, including events they emit, before the next assertion."""
        if self._drain_lock is None:
            raise RuntimeError("Emitter not initialized")
        async with self._drain_lock:
            while self._pending:
                event = self._pending.popleft()
                for listener in self.listeners[event.event_id]:
                    await listener.fn(*event.args, **event.kwargs)


def create_test_app(
    dsn: str,
    *,
    event_emitter_backend: type[BaseEventEmitterBackend] = DeterministicEventEmitter,
) -> Litestar:
    """Build an API app with bounded connections and no scheduled background work."""
    return create_app(
        psql_dsn=dsn,
        run_pollers=False,
        pool_config=PoolConfig(
            dsn=dsn,
            min_size=1,
            max_size=3,
            init=_async_pg_init,
            connect_kwargs={"command_timeout": 30, "server_settings": {"lock_timeout": "5s"}},
        ),
        event_emitter_backend=event_emitter_backend,
        configure_sentry=False,
        logging_config=LoggingConfig(
            # Litestar installs a default queue listener unless this exact
            # handler name is overridden. Keep logging synchronous so repeated
            # test applications do not accumulate logging monitor threads.
            handlers={
                "queue_listener": {
                    "class": "logging.StreamHandler",
                    "level": "INFO",
                    "formatter": "standard",
                },
            },
            log_exceptions="always",
        ),
    )


class TestClient(AsyncTestClient[Litestar]):
    """Wait for business events on the app loop while its pool remains available."""

    __test__ = False

    def drain_events(self) -> None:
        """Drain through the portal to avoid using app connections from pytest's loop."""
        emitter = self.app.event_emitter
        if isinstance(emitter, DeterministicEventEmitter):
            self.blocking_portal.call(emitter.drain)

    async def send(self, request: httpx.Request, **kwargs: Any) -> httpx.Response:
        """Finish request-triggered events before exposing the response to the test."""
        try:
            return await super().send(request, **kwargs)
        finally:
            self.drain_events()

    async def __aexit__(self, *args: Any) -> None:
        try:
            self.drain_events()
        finally:
            await super().__aexit__(*args)
