"""Repository for newsfeed domain database operations."""

from __future__ import annotations

import datetime as dt
import json

from asyncpg import Connection, Pool
from litestar.datastructures import State

from repository.base import BaseRepository


class NewsfeedRepository(BaseRepository):
    """Repository for newsfeed domain."""

    def __init__(self, pool: Pool) -> None:
        """Initialize repository.

        Args:
            pool: AsyncPG connection pool.
        """
        super().__init__(pool)

    async def insert_event(
        self,
        timestamp: dt.datetime,
        payload: dict,
        *,
        conn: Connection | None = None,
    ) -> int:
        """Insert a newsfeed event and return its ID.

        Args:
            timestamp: Event timestamp.
            payload: Event payload as dict.
            conn: Optional connection for transaction support.

        Returns:
            The newly created event ID.
        """
        _conn = self._get_connection(conn)
        query = """
            INSERT INTO public.newsfeed (timestamp, payload)
            VALUES ($1, $2::jsonb)
            RETURNING id
        """
        return await _conn.fetchval(query, timestamp, payload)

    async def fetch_event_by_id(
        self,
        event_id: int,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Fetch a single newsfeed event by ID.

        Args:
            event_id: The event ID to fetch.
            conn: Optional connection for transaction support.

        Returns:
            Event record as dict with keys: id, timestamp, payload, event_type.
            Returns None if not found.
        """
        _conn = self._get_connection(conn)
        query = """
            SELECT id, timestamp, payload, event_type
            FROM public.newsfeed
            WHERE id = $1
        """
        row = await _conn.fetchrow(query, event_id)
        if not row:
            return None
        result = dict(row)
        if isinstance(result["payload"], str):
            result["payload"] = json.loads(result["payload"])
        return result

    async def fetch_events(
        self,
        limit: int,
        offset: int,
        event_type: str | None = None,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch newsfeed events with pagination and optional type filter.

        Args:
            limit: Maximum number of events to return.
            offset: Number of events to skip.
            event_type: Optional event type filter.
            conn: Optional connection for transaction support.

        Returns:
            List of event records as dicts, ordered by timestamp DESC, id DESC.
        """
        _conn = self._get_connection(conn)
        query = """
            SELECT id, timestamp, payload, event_type
            FROM public.newsfeed
            WHERE ($1::text IS NULL OR event_type = $1)
            ORDER BY timestamp DESC, id DESC
            LIMIT $2 OFFSET $3
        """
        rows = await _conn.fetch(query, event_type, limit, offset)
        result = []
        for row in rows:
            row_dict = dict(row)
            if isinstance(row_dict["payload"], str):
                row_dict["payload"] = json.loads(row_dict["payload"])
            result.append(row_dict)
        return result


async def provide_newsfeed_repository(state: State) -> NewsfeedRepository:
    """Provide NewsfeedRepository DI.

    Args:
        state: Application state containing the database pool.

    Returns:
        NewsfeedRepository: New repository instance.
    """
    return NewsfeedRepository(state.db_pool)
