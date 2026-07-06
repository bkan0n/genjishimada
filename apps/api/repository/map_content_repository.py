"""Map content repository for dynamic Overwatch map-name data access."""

from __future__ import annotations

from asyncpg import Connection
from litestar.datastructures import State

from .base import BaseRepository


class MapContentRepository(BaseRepository):
    """Repository for the dynamic `maps.names` table.

    Backs the runtime map-name validation/creation that replaced the removed
    `OverwatchMap` Literal (phase 15). All queries use `$1` positional params.
    """

    async def insert_map_name(
        self,
        name: str,
        *,
        conn: Connection | None = None,
    ) -> dict:
        """Insert a map name idempotently.

        Uses `ON CONFLICT DO NOTHING` so re-inserting an existing name is a no-op
        rather than a unique-violation error (Open Q2 default: 201 + inserted flag,
        NOT 409). `RETURNING name` yields a row only when a row was actually inserted;
        a pre-existing name yields `None`.

        Args:
            name: The map name to insert.
            conn: Optional connection for transaction participation.

        Returns:
            dict: `{"name": name, "inserted": bool}` — `inserted` is False when the
                name already existed.
        """
        _conn = self._get_connection(conn)
        query = """
        INSERT INTO maps.names (name)
        VALUES ($1)
        ON CONFLICT DO NOTHING
        RETURNING name
        """
        row = await _conn.fetchrow(query, name)
        return {"name": name, "inserted": row is not None}

    async def fetch_all_map_names(
        self,
        *,
        conn: Connection | None = None,
    ) -> list[str]:
        """Fetch all known map names ordered ascending.

        Args:
            conn: Optional connection for transaction participation.

        Returns:
            list[str]: All `maps.names` rows sorted ascending.
        """
        _conn = self._get_connection(conn)
        query = """
        SELECT name
        FROM maps.names
        ORDER BY name
        """
        rows = await _conn.fetch(query)
        return [r["name"] for r in rows]


async def provide_map_content_repository(state: State) -> MapContentRepository:
    """Litestar DI provider for MapContentRepository."""
    return MapContentRepository(state.db_pool)
