"""Supervised PGQueuer consumer with recoverable cancellation and fenced writes."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import random
import re
import time
from collections.abc import Awaitable, Callable
from datetime import timedelta
from http import HTTPStatus
from typing import Any
from uuid import UUID

import asyncpg
import msgspec
from pgqueuer.db import AsyncpgDriver
from pgqueuer.errors import RetryRequested
from pgqueuer.models import Job, TracebackRecord
from pgqueuer.ports.repository import EntrypointExecutionParameter
from pgqueuer.qm import QueueManager
from pgqueuer.queries import Queries
from pgqueuer.types import JOB_STATUS, JobId

from genjishimada_sdk.queue import (
    API_ENTRYPOINTS,
    BOT_ENTRYPOINTS,
    DependencyFailed,
    DependencyUnavailable,
    HoldJobError,
    JobContext,
    JobEnvelope,
    LostOwnershipError,
    current_job,
)

log = logging.getLogger(__name__)
Handler = Callable[[JobContext], Awaitable[None]]
SUSTAINED_OUTAGE_SECONDS = 60


def safe_error(error: BaseException | str) -> str:
    """Keep operational diagnostics without storing bearer tokens or URL passwords."""
    value = str(error)
    value = re.sub(
        r"(?i)(authorization[=:]\s*(?:(?:bearer|basic)\s+)?|bearer\s+|"
        r"(?:token|password|api[_-]?key)[=:]\s*)[^\s,;]+",
        r"\1[redacted]",
        value,
    )
    value = re.sub(r"(://[^:/\s]+:)[^@\s]+@", r"\1[redacted]@", value)
    return value[:1500]


class BoundedQueueDriver(AsyncpgDriver):
    """Break stalled queue connections so the supervisor cancels their executions."""

    def __init__(self, connection: asyncpg.Connection, timeout_seconds: float) -> None:
        super().__init__(connection)
        self.connection = connection
        self.timeout_seconds = timeout_seconds

    async def _query[T](self, operation: Awaitable[T]) -> T:
        try:
            # Include waits for PGQueuer's shared connection lock, not just time
            # executing SQL. An expired connection cannot keep renewing claims.
            async with asyncio.timeout(self.timeout_seconds):
                return await operation
        except (TimeoutError, asyncpg.LockNotAvailableError, asyncpg.QueryCanceledError):
            self.connection.terminate()
            raise DependencyUnavailable("Queue database command timed out; reconnecting") from None

    async def fetch(self, query: str, *args: object) -> list[dict[str, Any]]:
        """Bound reads and claims, including time waiting for the driver lock."""
        return await self._query(super().fetch(query, *args))

    async def execute(self, query: str, *args: object) -> str:
        """Bound heartbeat and status writes and abort the connection on timeout."""
        return await self._query(super().execute(query, *args))

    async def notify(self, channel: str, payload: str) -> None:
        """Keep listener probes from waiting behind a blocked command forever."""
        await self._query(super().notify(channel, payload))

    async def add_listener(self, channel: str, callback: Callable[[str | bytes | bytearray], None]) -> None:
        """Bound listener registration during startup."""
        await self._query(super().add_listener(channel, callback))


class FencedQueries(Queries):
    """Adapt the pinned library's unfenced terminal/retry/heartbeat persistence."""

    def __post_init__(self) -> None:
        """Initialize application claim tracking beside the library's query state."""
        self.claims: dict[int, Job] = {}

    can_claim: Callable[[], bool] | None = None
    on_ready: Callable[[], None] | None = None

    def _claims(self) -> dict[int, Job]:
        if not hasattr(self, "claims"):
            self.claims = {}
        return self.claims

    async def dequeue(
        self,
        batch_size: int,
        entrypoints: dict[str, EntrypointExecutionParameter],
        queue_manager_id: UUID,
        global_concurrency_limit: int | None,
        heartbeat_timeout: timedelta,
    ) -> list[Job]:
        """Retain each execution's ownership and pause claiming during shared outages."""
        if self.can_claim is not None and not self.can_claim():
            return []
        await self.driver.execute("SELECT public.release_ready_job_dependencies($1::text[])", list(entrypoints))
        jobs = await super().dequeue(
            batch_size,
            entrypoints,
            queue_manager_id,
            global_concurrency_limit,
            heartbeat_timeout,
        )
        self._claims().update({job.id: job for job in jobs})
        if self.on_ready is not None:
            self.on_ready()
            self.on_ready = None
        return jobs

    async def update_heartbeat(self, job_ids: list[JobId]) -> None:
        """Extend only claims belonging to these executions."""
        for job_id in set(job_ids):
            job = self._claims().get(job_id)
            if job is not None:
                await self.driver.execute(
                    """UPDATE public.pgqueuer SET heartbeat=now()
                       WHERE id=$1 AND queue_manager_id=$2 AND updated=$3 AND status='picked'""",
                    job.id,
                    job.queue_manager_id,
                    job.updated,
                )

    async def retry_job(self, job: Job, delay: timedelta, traceback_record: TracebackRecord | None) -> None:
        """Atomically defer the owned row and record its retry."""
        await self.driver.execute(
            """WITH owned AS (
                UPDATE public.pgqueuer SET status='queued',execute_after=now()+$4,updated=now(),
                    queue_manager_id=NULL,attempts=attempts+1
                WHERE id=$1 AND queue_manager_id=$2 AND updated=$3 AND status='picked'
                RETURNING id,entrypoint,priority
            ) INSERT INTO public.pgqueuer_log(job_id,status,entrypoint,priority,traceback)
              SELECT id,'queued',entrypoint,priority,$5::jsonb FROM owned""",
            job.id,
            job.queue_manager_id,
            job.updated,
            delay,
            self._trace(traceback_record),
        )

    @staticmethod
    def _trace(trace: TracebackRecord | None) -> str | None:
        if trace is None:
            return None
        return trace.model_copy(
            update={
                "exception_message": safe_error(trace.exception_message),
                "traceback": "",
                "additional_context": None,
            }
        ).model_dump_json()

    async def log_jobs(self, job_status: list[tuple[Job, JOB_STATUS, TracebackRecord | None]]) -> None:
        """Fence terminal writes and make library cancellation recoverable."""
        for job, status, trace in job_status:
            if status == "canceled":
                await self.retry_job(job, timedelta(), None)
                continue
            if status == "successful":
                mutation = """DELETE FROM public.pgqueuer
                    WHERE id=$1 AND queue_manager_id=$2 AND updated=$3 AND status='picked'
                    RETURNING id,entrypoint,priority"""
                terminal_status = "successful"
            else:
                mutation = """UPDATE public.pgqueuer SET status='failed',updated=now(),queue_manager_id=NULL
                    WHERE id=$1 AND queue_manager_id=$2 AND updated=$3 AND status='picked'
                    RETURNING id,entrypoint,priority"""
                terminal_status = "failed"
            await self.driver.execute(
                f"""WITH owned AS ({mutation})
                    INSERT INTO public.pgqueuer_log(job_id,status,entrypoint,priority,traceback)
                    SELECT id,$4::pgqueuer_status,entrypoint,priority,$5::jsonb FROM owned""",
                job.id,
                job.queue_manager_id,
                job.updated,
                terminal_status,
                self._trace(trace),
            )
            if self._claims().get(job.id) is job:
                self._claims().pop(job.id, None)

    async def record_failure(self, job: Job, error: Exception, *, count: bool, code: str) -> int:
        """Persist a sanitized failure without charging outages to the handler budget."""
        rows = await self.driver.fetch(
            """UPDATE public.pgqueuer SET handler_failures=handler_failures+$4,
                   failure_code=$5,failure_message=$6
               WHERE id=$1 AND queue_manager_id=$2 AND updated=$3 AND status='picked'
               RETURNING handler_failures""",
            job.id,
            job.queue_manager_id,
            job.updated,
            int(count),
            code,
            safe_error(error),
        )
        if not rows:
            raise LostOwnershipError("Queue execution no longer owns its claim")
        return rows[0]["handler_failures"]


class QueueWorker:
    """Run application handlers without giving the consumer domain-table access."""

    def __init__(  # noqa: PLR0913 - independently configurable lifecycle limits
        self,
        dsn: str,
        *,
        owner: str,
        before_job: Handler | None = None,
        heartbeat_seconds: float = 60,
        drain_seconds: float = 30,
        poll_seconds: float = 5,
        timeout_seconds: float = 120,
        command_timeout_seconds: float = 10,
        retry_delays: tuple[float, ...] = (5, 15, 60, 300, 900),
    ) -> None:
        if owner not in {"api", "bot"}:
            raise ValueError("Unknown worker owner")
        if command_timeout_seconds <= 0:
            raise ValueError("Queue command timeout must be positive")
        self.dsn = dsn
        self.owner = owner
        self.before_job = before_job
        self.heartbeat_seconds = heartbeat_seconds
        self.drain_seconds = drain_seconds
        self.poll_seconds = poll_seconds
        self.timeout_seconds = timeout_seconds
        self.command_timeout_seconds = command_timeout_seconds
        self.retry_delays = retry_delays
        self.handlers: dict[str, Handler] = {}
        self._stop = asyncio.Event()
        self._manager: QueueManager | None = None
        self._active: set[asyncio.Task] = set()
        self.state = "stopped"
        self._dependency_until = 0.0
        self._dependency_started = 0.0
        self._dependency_delay = poll_seconds
        self._dependency_reported = False

    def _defer_dependency(self, error: Exception) -> float:
        now = time.monotonic()
        if not self._dependency_started:
            self._dependency_started = now
            log.warning("Worker dependency unavailable: owner=%s error=%s", self.owner, safe_error(error))
        elif now - self._dependency_started >= SUSTAINED_OUTAGE_SECONDS and not self._dependency_reported:
            log.error("Sustained worker dependency outage: owner=%s error=%s", self.owner, safe_error(error))
            self._dependency_reported = True
        delay = max(self._dependency_delay, float(getattr(error, "retry_after", 0) or 0))
        self._dependency_until = max(self._dependency_until, now + delay)
        self._dependency_delay = min(self._dependency_delay * 2, 30)
        self.state = "degraded"
        return delay

    def add_handler(self, name: str, handler: Handler) -> None:
        """Register a single owner for a known event."""
        allowed = API_ENTRYPOINTS if self.owner == "api" else BOT_ENTRYPOINTS
        if name not in allowed:
            raise ValueError(f"Entrypoint {name} has a different or unknown owner")
        if name in self.handlers:
            raise ValueError(f"Entrypoint {name} is already registered")
        self.handlers[name] = handler

    def stop(self) -> None:
        """Stop claiming immediately; run() drains and cancels unfinished handlers."""
        self._stop.set()
        if self._manager is not None:
            self._manager.shutdown.set()

    @staticmethod
    def _outage(error: Exception) -> bool:
        status = getattr(error, "status", getattr(error, "status_code", None))
        return (
            isinstance(
                error,
                (
                    DependencyUnavailable,
                    ConnectionError,
                    OSError,
                    asyncpg.PostgresConnectionError,
                    asyncpg.CannotConnectNowError,
                    asyncpg.InterfaceError,
                ),
            )
            or (
                isinstance(status, int)
                and (status >= HTTPStatus.INTERNAL_SERVER_ERROR or status == HTTPStatus.TOO_MANY_REQUESTS)
            )
            or type(error).__name__ in {"APIUnavailableError", "ClientConnectionError", "ServerDisconnectedError"}
        )

    async def _execute(self, queries: FencedQueries, handler: Handler, job: Job) -> None:
        task = asyncio.current_task()
        assert task is not None
        self._active.add(task)
        token = None
        deadline = None
        try:
            if job.queue_manager_id is None:
                raise LostOwnershipError("Job has no execution owner")
            envelope = msgspec.json.decode(job.payload or b"", type=JobEnvelope)
            if envelope.schema_version != 1 or envelope.event_name != job.entrypoint:
                raise HoldJobError("Unsupported job envelope version or event")
            context = JobContext(
                envelope.job_id,
                envelope.event_name,
                envelope.event_key,
                job.id,
                job.queue_manager_id,
                job.updated,
                envelope.payload,
                envelope.schema_version,
            )
            token = current_job.set(context)
            async with asyncio.timeout(self.timeout_seconds) as deadline:
                if self.before_job is not None:
                    await self.before_job(context)
                await handler(context)
            if self._dependency_started:
                log.info("Worker dependency recovered: owner=%s", self.owner)
            self._dependency_started = 0.0
            self._dependency_reported = False
            self._dependency_delay = self.poll_seconds
            self.state = "running"
        except asyncio.CancelledError:
            # _dispatch and our log adapter retain this as a recoverable interruption.
            raise
        except Exception as error:
            if isinstance(error, RetryRequested):
                raise
            if isinstance(error, LostOwnershipError):
                raise RetryRequested(timedelta(seconds=self.poll_seconds), reason="ownership lost") from error
            held = isinstance(error, (HoldJobError, msgspec.DecodeError, msgspec.ValidationError))
            outage = self._outage(error) and not (deadline is not None and deadline.expired())
            code = "dependency_failed" if isinstance(error, DependencyFailed) else type(error).__name__
            failures = await queries.record_failure(job, error, count=not outage and not held, code=code)
            if outage:
                # Entity/dependency ordering waits are local to a job; an actual
                # shared transport outage pauses further claims across this worker.
                delay = self.poll_seconds if isinstance(error, DependencyUnavailable) else self._defer_dependency(error)
                raise RetryRequested(timedelta(seconds=float(delay)), reason="dependency unavailable") from error
            if not held and failures <= len(self.retry_delays):
                raise RetryRequested(
                    timedelta(seconds=self.retry_delays[failures - 1]), reason=safe_error(error)
                ) from error
            # PGQueuer emits the one terminal error. Never expose transport headers
            # or a raw chained HTTP exception through its traceback logger.
            raise HoldJobError(f"{type(error).__name__}: {safe_error(error)}") from None
        finally:
            if token is not None:
                current_job.reset(token)
            self._active.discard(task)

    def _build_manager(
        self, connection: asyncpg.Connection, *, on_ready: Callable[[], None] | None = None
    ) -> QueueManager:
        queries = FencedQueries(BoundedQueueDriver(connection, self.command_timeout_seconds))
        queries.can_claim = lambda: not self._stop.is_set() and time.monotonic() >= self._dependency_until
        queries.on_ready = on_ready
        manager = QueueManager(queries)
        for name, handler in self.handlers.items():

            def register(callback: Handler, event: str) -> None:
                @manager.entrypoint(event, concurrency_limit=1, on_failure="hold")
                async def invoke(job: Job) -> None:
                    await self._execute(queries, callback, job)

            register(handler, name)
        return manager

    async def _cancel_active(self) -> None:
        active = list(self._active)
        for task in active:
            task.cancel()
        await asyncio.gather(*active, return_exceptions=True)

    async def run(self) -> None:  # noqa: PLR0912, PLR0915 - ordered connection, drain, and cleanup lifecycle
        """Reconnect, supervise handlers, and drain before the caller closes transports."""
        if not self.handlers:
            raise ValueError("No entrypoints registered")
        delay = 1.0
        in_outage = False
        outage_started = 0.0
        outage_reported = False

        def ready() -> None:
            # A connection alone does not prove the queue schema, grants, or
            # listener work. Dequeue runs only after manager initialization.
            nonlocal delay, in_outage, outage_reported
            if in_outage:
                log.info("Queue dependency recovered: %s", self.owner)
            in_outage = False
            outage_reported = False
            self.state = "degraded" if self._dependency_started else "running"
            delay = 1

        while not self._stop.is_set():
            connection = None
            runner = None
            waiters: list[asyncio.Task] = []
            try:
                self.state = "connecting"
                connection = await asyncpg.connect(self.dsn, timeout=10, command_timeout=self.command_timeout_seconds)
                disconnected = asyncio.Event()
                connection.add_termination_listener(lambda _: disconnected.set())
                manager = self._build_manager(connection, on_ready=ready)
                self._manager = manager
                if self._stop.is_set():
                    break
                runner = asyncio.create_task(
                    manager.run(
                        batch_size=1,
                        max_concurrent_tasks=2,
                        dequeue_timeout=timedelta(seconds=self.poll_seconds),
                        heartbeat_timeout=timedelta(seconds=self.heartbeat_seconds),
                        shutdown_on_listener_failure=True,
                    )
                )
                waiters = [asyncio.create_task(self._stop.wait()), asyncio.create_task(disconnected.wait())]
                await asyncio.wait([runner, *waiters], return_when=asyncio.FIRST_COMPLETED)
                manager.shutdown.set()
                if disconnected.is_set():
                    await self._cancel_active()
                try:
                    await asyncio.wait_for(asyncio.shield(runner), timeout=self.drain_seconds)
                except TimeoutError:
                    await self._cancel_active()
                    await asyncio.wait_for(runner, timeout=5)
                if not self._stop.is_set():
                    raise ConnectionError("Queue manager stopped; rebuilding its connection")
            except asyncio.CancelledError:
                self.stop()
                await self._cancel_active()
                raise
            except Exception as error:
                if not in_outage:
                    log.warning("Queue dependency unavailable: %s: %s", self.owner, safe_error(error))
                    outage_started = time.monotonic()
                elif time.monotonic() - outage_started >= SUSTAINED_OUTAGE_SECONDS and not outage_reported:
                    log.error("Sustained queue connection outage: owner=%s error=%s", self.owner, safe_error(error))
                    outage_reported = True
                in_outage = True
                self.state = "degraded"
            finally:
                self._manager = None
                for task in waiters:
                    task.cancel()
                await asyncio.gather(*waiters, return_exceptions=True)
                await self._cancel_active()
                if runner is not None and not runner.done():
                    runner.cancel()
                    await asyncio.gather(runner, return_exceptions=True)
                if connection is not None:
                    with contextlib.suppress(Exception):
                        await connection.close(timeout=5)
            if not self._stop.is_set():
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=delay + random.random() * delay / 4)
                delay = min(delay * 2, 30)
        self.state = "stopped"
