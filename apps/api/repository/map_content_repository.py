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

    async def lock_names(self, *, exclusive: bool = False) -> None:
        """Protect ownership changes, or keep a resolved reference stable until commit.

        Call inside a service transaction. Readers/writers of map references use
        the shared lock; canonical-name/banner writers use the exclusive lock.
        """
        function = "pg_advisory_xact_lock" if exclusive else "pg_advisory_xact_lock_shared"
        await self._get_connection().execute(f"SELECT {function}(hashtextextended('maps.names ownership', 0))")

    async def resolve_name(self, name: str) -> str:
        """Resolve exact canonical names and aliases; leave unknown names for validation."""
        value = await self._get_connection().fetchval(
            """SELECT name FROM maps.names WHERE name=$1
               UNION ALL SELECT canonical_name FROM maps.name_aliases WHERE previous_name=$1
               LIMIT 1""",
            name,
        )
        return value if value is not None else name

    async def fetch_name_owners(self) -> dict[str, str]:
        """Return canonical and compatibility names mapped to their current owner."""
        rows = await self._get_connection().fetch(
            """SELECT name AS spelling, name AS owner FROM maps.names
               UNION ALL SELECT previous_name, canonical_name FROM maps.name_aliases"""
        )
        return {row["spelling"]: row["owner"] for row in rows}

    async def rename_map_name(self, old_name: str, name: str) -> None:
        """Rename one row, reserve its old spelling and update equipped mastery badges.

        The caller owns the exclusive map-name lock and transaction. Removing
        the destination alias first allows a map to reclaim its own old name.
        """
        conn = self._get_connection()
        await conn.execute("DELETE FROM maps.name_aliases WHERE previous_name=$1 AND canonical_name=$2", name, old_name)
        await conn.execute("UPDATE maps.names SET name=$2 WHERE name=$1", old_name, name)
        await conn.execute("INSERT INTO maps.name_aliases(previous_name, canonical_name) VALUES($1,$2)", old_name, name)
        for slot in range(1, 7):
            await conn.execute(
                f"""UPDATE rank_card.badges SET badge_name{slot}=$2
                    WHERE badge_type{slot}='mastery' AND badge_name{slot}=$1""",
                old_name,
                name,
            )

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
