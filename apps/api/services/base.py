"""Shared transactional enqueue support for application services."""

from __future__ import annotations

from typing import cast
from uuid import UUID, uuid4

import msgspec
from asyncpg import Connection, Pool
from genjishimada_sdk.internal import JobStatusResponse
from genjishimada_sdk.queue_store import enqueue_job
from litestar.datastructures import Headers, State

from utilities.transactions import ContextPool, active_connection


class BaseService:
    """Services share the caller's transaction for domain writes and queue work."""

    def __init__(self, pool: Pool, state: State) -> None:
        """Bind the pool without allocating a separate transactional connection."""
        self._pool = cast("Pool", ContextPool(pool))
        self._state = state

    async def enqueue(  # noqa: PLR0913
        self,
        *,
        routing_key: str,
        data: msgspec.Struct | list[msgspec.Struct] | dict,
        headers: Headers | None = None,
        idempotency_key: str | None = None,
        conn: Connection | None = None,
        entity_key: str | None = None,
        depends_on: UUID | None = None,
    ) -> JobStatusResponse:
        """Persist work on the business transaction; request credentials stay in memory."""
        connection = conn or active_connection()
        if connection is None:
            raise RuntimeError("Queue work requires an enclosing service transaction")
        if entity_key is None:
            for attr, prefix in (
                ("completion_id", "completion"),
                ("thread_id", "playtest"),
                ("edit_request_id", "map_edit"),
                ("user_id", "user"),
            ):
                value = getattr(data, attr, None)
                if value is not None:
                    entity_key = f"{prefix}:{value}"
                    break
        return await enqueue_job(
            connection,
            event_name=routing_key,
            payload=data,
            event_key=idempotency_key or f"operation:{uuid4()}",
            entity_key=entity_key,
            depends_on=depends_on,
        )
