"""Repository for utilities data access."""

from __future__ import annotations

import datetime as dt
import json

from asyncpg import Connection
from litestar.datastructures import State

from .base import BaseRepository


class UtilitiesRepository(BaseRepository):
    """Repository for utilities data access."""

    async def log_analytics(
        self,
        command_name: str,
        user_id: int,
        created_at: dt.datetime,
        namespace: dict,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Log analytics command usage.

        Args:
            command_name: Name of the command.
            user_id: User ID who executed the command.
            created_at: Timestamp of command execution.
            namespace: Additional metadata.
            conn: Optional connection for transaction participation.
        """
        _conn = self._get_connection(conn)

        query = """
            INSERT INTO public.analytics (command_name, user_id, created_at, namespace)
            VALUES ($1, $2, $3, $4::jsonb)
        """
        await _conn.execute(query, command_name, user_id, created_at, json.dumps(namespace))

    async def log_map_click(
        self,
        code: str,
        user_id: int | None,
        source: str,
        ip_hash: str,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Log map code click with deduplication.

        Args:
            code: Map code.
            user_id: Optional user ID.
            source: Click source (web/bot).
            ip_hash: Hashed IP address.
            conn: Optional connection for transaction participation.
        """
        _conn = self._get_connection(conn)

        query = """
            WITH target_map AS (
                SELECT id AS map_id FROM core.maps WHERE code = $1
            )
            INSERT INTO maps.clicks (map_id, user_id, source, ip_hash)
            VALUES ((SELECT map_id FROM target_map), $2, $3, $4)
            ON CONFLICT ON CONSTRAINT u_click_unique_per_day DO NOTHING
        """
        await _conn.execute(query, code, user_id, source, ip_hash)

    async def fetch_map_clicks_debug(
        self,
        limit: int = 100,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch recent map clicks for debugging.

        Args:
            limit: Maximum number of records.
            conn: Optional connection for transaction participation.

        Returns:
            List of dicts with click data.
        """
        _conn = self._get_connection(conn)

        query = """
            SELECT id, map_id, user_id, source, user_agent, ip_hash, inserted_at, day_bucket
            FROM maps.clicks
            ORDER BY inserted_at DESC
            LIMIT $1
        """
        rows = await _conn.fetch(query, limit)
        return [dict(row) for row in rows]


async def provide_utilities_repository(state: State) -> UtilitiesRepository:
    """Litestar DI provider for repository.

    Args:
        state: Application state.

    Returns:
        Repository instance.
    """
    return UtilitiesRepository(state.db_pool)
