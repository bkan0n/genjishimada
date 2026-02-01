"""Base service class with RabbitMQ publishing capability."""

from __future__ import annotations

import typing
import uuid
from logging import getLogger
from uuid import uuid4

import aio_pika
import aio_pika.exceptions
import msgspec
from asyncpg import Pool
from asyncpg.exceptions import PostgresError
from genjishimada_sdk.internal import JobStatusResponse
from litestar.datastructures import Headers, State

log = getLogger(__name__)


class RabbitMessageBody(msgspec.Struct):
    """RabbitMQ message body structure."""

    type: str
    data: typing.Any


IGNORE_IDEMPOTENCY = {
    "api.completion.upvote",
    "api.completion.verification.delete",
    "api.notification.delivery",
    "api.playtest.vote.cast",
    "api.playtest.vote.remove",
    "api.xp.grant",
    "api.completion.autoverification.failed",
}


class BaseService:
    """Base class for all services.

    Services contain business logic and orchestrate repository calls.
    They manage transaction boundaries and can publish messages to RabbitMQ.
    """

    def __init__(self, pool: Pool, state: State) -> None:
        """Initialize service.

        Args:
            pool: AsyncPG connection pool.
            state: Application state (for RabbitMQ, etc.).
        """
        self._pool = pool
        self._state = state

    async def publish_message(
        self,
        *,
        routing_key: str,
        data: msgspec.Struct | list[msgspec.Struct],
        headers: Headers,
        idempotency_key: str | None = None,
    ) -> JobStatusResponse:
        """Publish a message to RabbitMQ.

        Args:
            routing_key: The RabbitMQ message routing key.
            data: The message data.
            headers: Request headers.
            idempotency_key: The idempotency key for this transaction.

        Returns:
            JobStatusResponse with job ID and status.
        """
        if routing_key not in IGNORE_IDEMPOTENCY and not idempotency_key:
            raise ValueError(f"idempotency_key required for routing_key='{routing_key}'")

        message_body = msgspec.json.encode(data)

        if headers.get("X-PYTEST-ENABLED") == "1":
            log.debug("Pytest in progress, skipping queue.")
            return JobStatusResponse(uuid4(), "succeeded")

        log.info("[→] Preparing to publish RabbitMQ message")
        log.info("Routing key: %s", routing_key)
        log.info("Headers: %s", headers)
        log.info("Payload: %s", message_body.decode("utf-8", errors="ignore"))

        job_id = uuid.uuid4()
        async with self._state.mq_channel_pool.acquire() as channel:
            try:
                async with self._pool.acquire() as conn:
                    await conn.execute(
                        "INSERT INTO public.jobs (id, action) VALUES ($1, $2);",
                        job_id,
                        routing_key,
                    )
                message = aio_pika.Message(
                    message_body,
                    correlation_id=str(job_id),
                    message_id=idempotency_key or str(job_id),
                    delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                    headers=headers.dict(),  # pyright: ignore[reportArgumentType]
                )
                await channel.default_exchange.publish(
                    message,
                    routing_key=routing_key,
                )
                log.info("[✓] Published RabbitMQ message to queue '%s'", routing_key)
                return JobStatusResponse(id=job_id, status="queued")
            except (PostgresError, aio_pika.exceptions.AMQPError):
                log.exception("[!] Failed to publish message to RabbitMQ queue '%s'", routing_key)
                return JobStatusResponse(job_id, "failed", "", "Failed to send message.")
