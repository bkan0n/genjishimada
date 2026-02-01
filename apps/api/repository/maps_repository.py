"""Repository for maps data access."""

from __future__ import annotations

import datetime as dt
from typing import Any

import asyncpg
import msgspec
from asyncpg import Connection
from genjishimada_sdk.difficulties import convert_raw_difficulty_to_difficulty_all
from genjishimada_sdk.maps import Mechanics, OverwatchMap, Restrictions, Tags
from litestar.datastructures import State

from utilities.map_search import MapSearchFilters, MapSearchSQLSpecBuilder
from utilities.shared_queries import get_map_mastery_data_raw

from .base import BaseRepository
from .exceptions import (
    ForeignKeyViolationError,
    UniqueConstraintViolationError,
    extract_constraint_name,
)


class MapsRepository(BaseRepository):
    """Repository for maps data access."""

    # Core map operations

    async def fetch_maps(
        self,
        *,
        single: bool = False,
        code: str | None = None,
        filters: MapSearchFilters | None = None,
        conn: Connection | None = None,
    ) -> dict | list[dict]:
        """Fetch maps with full filtering support using MapSearchSQLSpecBuilder.

        Args:
            single: If True, return single dict; if False, return list.
            code: Optional code filter for single map lookup (legacy, prefer filters).
            filters: MapSearchFilters struct with all filter criteria.
            conn: Optional connection.

        Returns:
            Single map dict if single=True, otherwise list of map dicts.
        """
        _conn = self._get_connection(conn)

        # Build filters struct
        if code and not filters:
            filters = MapSearchFilters(code=code, return_all=True)
        elif not filters:
            filters = MapSearchFilters(return_all=True)

        # Use MapSearchSQLSpecBuilder to generate query
        builder = MapSearchSQLSpecBuilder(filters)
        query_with_args = builder.build()

        # Execute query
        rows = await _conn.fetch(query_with_args.query, *query_with_args.args)

        # Convert to dicts
        result = [dict(row) for row in rows]

        if single:
            return result[0] if result else {}
        return result

    async def fetch_partial_map(
        self,
        code: str,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Fetch partial map data with playtest info.

        Useful when initializing a playtest where a subset of fields is sufficient.

        Args:
            code: Map code.
            conn: Optional connection.

        Returns:
            Dict with map data including initial_difficulty from playtest, or None if not found.
        """
        _conn = self._get_connection(conn)

        row = await _conn.fetchrow(
            """
            SELECT
                m.id AS map_id,
                m.code,
                m.map_name,
                m.checkpoints,
                pm.initial_difficulty AS difficulty,
                array_agg(DISTINCT u.nickname) AS creator_names
            FROM core.maps AS m
            LEFT JOIN maps.creators AS c ON c.map_id = m.id AND c.is_primary
            LEFT JOIN core.users AS u ON c.user_id = u.id
            LEFT JOIN playtests.meta AS pm ON m.id = pm.map_id
            WHERE m.code = $1
            GROUP BY m.id,
                m.code,
                m.map_name,
                m.checkpoints,
                pm.initial_difficulty
            """,
            code,
        )
        resp = dict(row) if row else None
        if resp:
            resp["creator_name"] = resp["creator_names"][0]
            resp["difficulty"] = convert_raw_difficulty_to_difficulty_all(resp["difficulty"])
        return resp

    async def lookup_map_id(
        self,
        code: str,
        *,
        conn: Connection | None = None,
    ) -> int | None:
        """Get map ID from code.

        Args:
            code: Map code.
            conn: Optional connection for transaction participation.

        Returns:
            Map ID if found, else None.
        """
        _conn = self._get_connection(conn)

        return await _conn.fetchval(
            "SELECT id FROM core.maps WHERE code = $1",
            code,
        )

    async def check_code_exists(
        self,
        code: str,
        *,
        conn: Connection | None = None,
    ) -> bool:
        """Check if map code exists.

        Args:
            code: Map code.
            conn: Optional connection.

        Returns:
            True if code exists, False otherwise.
        """
        _conn = self._get_connection(conn)

        return await _conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM core.maps WHERE code = $1)",
            code,
        )

    async def create_core_map(
        self,
        data: dict[str, Any],
        *,
        conn: Connection | None = None,
    ) -> int:
        """Create core map record.

        Args:
            data: Map data dict with all required fields.
            conn: Optional connection for transaction participation.

        Returns:
            Created map ID.

        Raises:
            UniqueConstraintViolationError: If code already exists.
        """
        _conn = self._get_connection(conn)

        try:
            map_id = await _conn.fetchval(
                """
                INSERT INTO core.maps (
                    code, map_name, category, checkpoints, official,
                    playtesting, hidden, archived, difficulty, raw_difficulty,
                    description, custom_banner, title
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
                RETURNING id
                """,
                data["code"],
                data["map_name"],
                data["category"],
                data["checkpoints"],
                data["official"],
                data["playtesting"],
                data.get("hidden", True),
                data.get("archived", False),
                data["difficulty"],
                data["raw_difficulty"],
                data.get("description"),
                data.get("custom_banner"),
                data.get("title"),
            )
            return map_id
        except asyncpg.UniqueViolationError as e:
            constraint = extract_constraint_name(e)
            raise UniqueConstraintViolationError(
                constraint_name=constraint or "unknown",
                table="core.maps",
                detail=str(e),
            ) from e

    async def update_core_map(
        self,
        code: str,
        data: dict[str, Any],
        *,
        conn: Connection | None = None,
    ) -> None:
        """Update core map record with dynamic fields.

        Args:
            code: Map code to update.
            data: Dict of fields to update (only provided fields are updated).
            conn: Optional connection for transaction participation.

        Raises:
            UniqueConstraintViolationError: If new code already exists.
        """
        _conn = self._get_connection(conn)

        if not data:
            return

        # Build dynamic UPDATE query
        set_clauses = []
        values = []
        param_idx = 1

        for field, value in data.items():
            set_clauses.append(f"{field} = ${param_idx}")
            values.append(value)
            param_idx += 1

        # Add code for WHERE clause
        values.append(code)
        where_param = f"${param_idx}"

        query = f"""
            UPDATE core.maps
            SET {", ".join(set_clauses)}
            WHERE code = {where_param}
        """

        try:
            await _conn.execute(query, *values)
        except asyncpg.UniqueViolationError as e:
            constraint = extract_constraint_name(e)
            raise UniqueConstraintViolationError(
                constraint_name=constraint or "unknown",
                table="core.maps",
                detail=str(e),
            ) from e

    # Related data operations - Creators

    async def insert_creators(
        self,
        map_id: int,
        creators: list[dict[str, Any]] | None,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Insert creators for a map.

        Args:
            map_id: Map ID.
            creators: List of creator dicts with user_id and is_primary.
            conn: Optional connection for transaction participation.

        Raises:
            UniqueConstraintViolationError: If duplicate creator.
            ForeignKeyViolationError: If user_id doesn't exist.
        """
        _conn = self._get_connection(conn)

        if not creators:
            return

        try:
            await _conn.executemany(
                """
                INSERT INTO maps.creators (map_id, user_id, is_primary)
                VALUES ($1, $2, $3)
                """,
                [(map_id, c["user_id"], c.get("is_primary", False)) for c in creators],
            )
        except asyncpg.UniqueViolationError as e:
            constraint = extract_constraint_name(e)
            raise UniqueConstraintViolationError(
                constraint_name=constraint or "unknown",
                table="maps.creators",
                detail=str(e),
            ) from e
        except asyncpg.ForeignKeyViolationError as e:
            constraint = extract_constraint_name(e)
            raise ForeignKeyViolationError(
                constraint_name=constraint or "unknown",
                table="maps.creators",
                detail=str(e),
            ) from e

    async def delete_creators(
        self,
        map_id: int,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Delete all creators for a map.

        Args:
            map_id: Map ID.
            conn: Optional connection.
        """
        _conn = self._get_connection(conn)

        await _conn.execute(
            "DELETE FROM maps.creators WHERE map_id = $1",
            map_id,
        )

    # Related data operations - Mechanics

    async def insert_mechanics(
        self,
        map_id: int,
        mechanics: list[Mechanics] | None,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Insert mechanic links for a map.

        Args:
            map_id: Map ID.
            mechanics: List of mechanic names.
            conn: Optional connection for transaction participation.

        Raises:
            UniqueConstraintViolationError: If duplicate mechanic.
        """
        _conn = self._get_connection(conn)

        if not mechanics:
            return

        # Lookup mechanic IDs
        mechanic_ids = await _conn.fetch(
            """
            SELECT id FROM maps.mechanics
            WHERE name = ANY($1::text[])
            """,
            mechanics,
        )

        if not mechanic_ids:
            return

        try:
            await _conn.executemany(
                """
                INSERT INTO maps.mechanic_links (map_id, mechanic_id)
                VALUES ($1, $2)
                """,
                [(map_id, row["id"]) for row in mechanic_ids],
            )
        except asyncpg.UniqueViolationError as e:
            constraint = extract_constraint_name(e)
            raise UniqueConstraintViolationError(
                constraint_name=constraint or "unknown",
                table="maps.mechanic_links",
                detail=str(e),
            ) from e

    async def delete_mechanics(
        self,
        map_id: int,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Delete all mechanic links for a map.

        Args:
            map_id: Map ID.
            conn: Optional connection.
        """
        _conn = self._get_connection(conn)

        await _conn.execute(
            "DELETE FROM maps.mechanic_links WHERE map_id = $1",
            map_id,
        )

    # Related data operations - Restrictions

    async def insert_restrictions(
        self,
        map_id: int,
        restrictions: list[Restrictions] | None,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Insert restriction links for a map.

        Args:
            map_id: Map ID.
            restrictions: List of restriction names.
            conn: Optional connection for transaction participation.

        Raises:
            UniqueConstraintViolationError: If duplicate restriction.
        """
        _conn = self._get_connection(conn)

        if not restrictions:
            return

        # Lookup restriction IDs
        restriction_ids = await _conn.fetch(
            """
            SELECT id FROM maps.restrictions
            WHERE name = ANY($1::text[])
            """,
            restrictions,
        )

        if not restriction_ids:
            return

        try:
            await _conn.executemany(
                """
                INSERT INTO maps.restriction_links (map_id, restriction_id)
                VALUES ($1, $2)
                """,
                [(map_id, row["id"]) for row in restriction_ids],
            )
        except asyncpg.UniqueViolationError as e:
            constraint = extract_constraint_name(e)
            raise UniqueConstraintViolationError(
                constraint_name=constraint or "unknown",
                table="maps.restriction_links",
                detail=str(e),
            ) from e

    async def delete_restrictions(
        self,
        map_id: int,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Delete all restriction links for a map.

        Args:
            map_id: Map ID.
            conn: Optional connection.
        """
        _conn = self._get_connection(conn)

        await _conn.execute(
            "DELETE FROM maps.restriction_links WHERE map_id = $1",
            map_id,
        )

    # Related data operations - Tags

    async def insert_tags(
        self,
        map_id: int,
        tags: list[Tags] | None,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Insert tag links for a map.

        Args:
            map_id: Map ID.
            tags: List of tag names.
            conn: Optional connection for transaction participation.

        Raises:
            UniqueConstraintViolationError: If duplicate tag.
        """
        _conn = self._get_connection(conn)

        if not tags:
            return

        # Lookup tag IDs
        tag_ids = await _conn.fetch(
            """
            SELECT id FROM maps.tags
            WHERE name = ANY($1::text[])
            """,
            tags,
        )

        if not tag_ids:
            return

        try:
            await _conn.executemany(
                """
                INSERT INTO maps.tag_links (map_id, tag_id)
                VALUES ($1, $2)
                """,
                [(map_id, row["id"]) for row in tag_ids],
            )
        except asyncpg.UniqueViolationError as e:
            constraint = extract_constraint_name(e)
            raise UniqueConstraintViolationError(
                constraint_name=constraint or "unknown",
                table="maps.tag_links",
                detail=str(e),
            ) from e

    async def delete_tags(
        self,
        map_id: int,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Delete all tag links for a map.

        Args:
            map_id: Map ID.
            conn: Optional connection.
        """
        _conn = self._get_connection(conn)

        await _conn.execute(
            "DELETE FROM maps.tag_links WHERE map_id = $1",
            map_id,
        )

    # Related data operations - Medals

    async def insert_medals(
        self,
        map_id: int,
        medals: dict[str, float] | None,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Insert or update medals for a map.

        Args:
            map_id: Map ID.
            medals: Dict with gold, silver, bronze times.
            conn: Optional connection for transaction participation.
        """
        _conn = self._get_connection(conn)

        if not medals:
            return

        await _conn.execute(
            """
            INSERT INTO maps.medals (map_id, gold, silver, bronze)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (map_id) DO UPDATE
            SET gold = EXCLUDED.gold,
                silver = EXCLUDED.silver,
                bronze = EXCLUDED.bronze
            """,
            map_id,
            medals.get("gold"),
            medals.get("silver"),
            medals.get("bronze"),
        )

    async def delete_medals(
        self,
        map_id: int,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Delete medals for a map.

        Args:
            map_id: Map ID.
            conn: Optional connection.
        """
        _conn = self._get_connection(conn)

        await _conn.execute(
            "DELETE FROM maps.medals WHERE map_id = $1",
            map_id,
        )

    # Related data operations - Guides

    async def insert_guide(
        self,
        map_id: int,
        url: str | None,
        user_id: int | None,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Insert a guide for a map.

        Args:
            map_id: Map ID.
            url: Guide URL.
            user_id: User ID who created the guide.
            conn: Optional connection for transaction participation.

        Raises:
            UniqueConstraintViolationError: If user already has guide for this map.
        """
        _conn = self._get_connection(conn)

        if not url or not user_id:
            return

        try:
            await _conn.execute(
                """
                INSERT INTO maps.guides (map_id, url, user_id)
                VALUES ($1, $2, $3)
                """,
                map_id,
                url,
                user_id,
            )
        except asyncpg.UniqueViolationError as e:
            constraint = extract_constraint_name(e)
            raise UniqueConstraintViolationError(
                constraint_name=constraint or "unknown",
                table="maps.guides",
                detail=str(e),
            ) from e

    async def check_guide_exists(
        self,
        map_id: int,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> bool:
        """Check if a guide exists for a user on a map.

        Args:
            map_id: Map ID.
            user_id: User ID.
            conn: Optional connection.

        Returns:
            True if guide exists, False otherwise.
        """
        _conn = self._get_connection(conn)

        return await _conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM maps.guides WHERE map_id = $1 AND user_id = $2)",
            map_id,
            user_id,
        )

    async def delete_guide(
        self,
        map_id: int,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> int:
        """Delete a user's guide for a map.

        Args:
            map_id: Map ID.
            user_id: User ID.
            conn: Optional connection.

        Returns:
            Number of rows deleted (0 or 1).
        """
        _conn = self._get_connection(conn)

        result = await _conn.execute(
            "DELETE FROM maps.guides WHERE map_id = $1 AND user_id = $2",
            map_id,
            user_id,
        )
        # Extract row count from result string like "DELETE 1"
        return int(result.split()[-1]) if result else 0

    async def update_guide(
        self,
        map_id: int,
        user_id: int,
        url: str,
        *,
        conn: Connection | None = None,
    ) -> int:
        """Update a guide URL.

        Args:
            map_id: Map ID.
            user_id: User ID.
            url: New URL.
            conn: Optional connection.

        Returns:
            Number of rows updated (0 or 1).
        """
        _conn = self._get_connection(conn)

        result = await _conn.execute(
            """
            UPDATE maps.guides
            SET url = $3
            WHERE map_id = $1 AND user_id = $2
            """,
            map_id,
            user_id,
            url,
        )
        return int(result.split()[-1]) if result else 0

    async def fetch_guides(
        self,
        code: str,
        include_records: bool = False,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch guides with optional record videos.

        Args:
            code: Map code.
            include_records: If True, includes completion record videos.
            conn: Optional connection.

        Returns:
            List of guides (and records if include_records=True).
        """
        _conn = self._get_connection(conn)

        # Query from v3 with UNION ALL for records when include_records=True
        query = """
        WITH m AS (
            SELECT id
            FROM core.maps
            WHERE code = $1
        )
        SELECT
            g.user_id,
            g.url,
            ARRAY_REMOVE(
                ARRAY[u.nickname, u.global_name]::text[]
                    || ARRAY(
                        SELECT owu.username::text
                        FROM users.overwatch_usernames owu
                        WHERE owu.user_id = g.user_id
                       ),
                NULL
            ) AS usernames
        FROM m
        JOIN maps.guides g ON g.map_id = m.id
        LEFT JOIN core.users u ON u.id = g.user_id
        UNION ALL
        SELECT
            c.user_id,
            c.video AS url,
            ARRAY_REMOVE(
                ARRAY[u.nickname, u.global_name]::text[]
                    || ARRAY(
                        SELECT owu.username::text
                        FROM users.overwatch_usernames owu
                        WHERE owu.user_id = c.user_id
                       ),
                NULL
            ) AS usernames
        FROM m
        JOIN LATERAL (
            SELECT DISTINCT ON (c.user_id)
                c.user_id, c.video, c.inserted_at, c.id
            FROM core.completions c
            WHERE c.map_id = m.id
              AND c.verified = TRUE
              AND c.completion = FALSE
              AND c.video IS NOT NULL
            ORDER BY c.user_id, c.inserted_at DESC, c.id DESC
            ) c ON TRUE
        LEFT JOIN core.users u ON u.id = c.user_id
        WHERE $2::bool IS TRUE
        """

        rows = await _conn.fetch(query, code, include_records)
        return [dict(row) for row in rows]

    # Archive operations

    async def set_archive_status(
        self,
        codes: list[str],
        archived: bool,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Set archive status for one or more maps.

        Args:
            codes: List of map codes.
            archived: Archive status to set.
            conn: Optional connection.
        """
        _conn = self._get_connection(conn)

        await _conn.execute(
            """
            UPDATE core.maps
            SET archived = $2
            WHERE code = ANY($1::text[])
            """,
            codes,
            archived,
        )

    # Mastery operations

    async def fetch_map_mastery(
        self,
        user_id: int,
        map_name: OverwatchMap | None = None,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch map mastery data for a user.

        Args:
            user_id: User ID.
            map_name: Optional map name filter. If None, returns all maps.
            conn: Optional connection.

        Returns:
            List of mastery records (all maps if map_name is None).
        """
        _conn = self._get_connection(conn)

        return await get_map_mastery_data_raw(_conn, user_id, map_name)

    async def upsert_map_mastery(
        self,
        map_name: OverwatchMap,
        user_id: int,
        level: str,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Insert or update map mastery record.

        Args:
            map_name (OverwatchMap): Map name.
            user_id (int): User ID.
            level (str): Mastery level.

        Returns:
            Dict with medal and operation_status ('inserted' or 'updated'), or None if no change.
        """
        _conn = self._get_connection(conn)

        query = """
                INSERT INTO maps.mastery (
                    user_id, map_name, medal
                )
                VALUES (
                    $1, $2, $3
                )
                ON CONFLICT (user_id, map_name) DO UPDATE SET medal = excluded.medal
                WHERE maps.mastery.medal IS DISTINCT FROM excluded.medal
                RETURNING
                    map_name,
                    medal,
                    CASE WHEN xmax::text::int = 0 THEN 'inserted' ELSE 'updated' END AS operation_status;
                """
        row = await _conn.fetchrow(query, user_id, map_name, level)

        if row is None:
            return None

        return dict(row)

    # Quality operations

    async def override_quality_votes(
        self,
        code: str,
        quality_value: int,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Override quality votes with a fixed value (admin operation).

        Updates all quality ratings for the map to the specified value.

        Args:
            code: Map code.
            quality_value: Quality value to set (1-6).
            conn: Optional connection.
        """
        _conn = self._get_connection(conn)

        # Look up map ID
        map_id = await self.lookup_map_id(code, conn=conn)
        if map_id is None:
            return

        # Update all quality ratings for this map
        await _conn.execute(
            """
            UPDATE maps.ratings SET quality = $2 WHERE map_id = $1
            """,
            map_id,
            quality_value,
        )

    # Trending maps

    async def fetch_trending_maps(
        self,
        limit: int = 10,
        window_days: int = 14,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch trending maps with complete scoring algorithm.

        Scoring factors:
        - Clicks: 0.2x weight
        - Completions: 1.0x weight
        - Upvotes: 1.5x weight
        - Average rating: 0.75x weight

        Args:
            limit: Maximum number of maps to return.
            window_days: Time window for trending calculation.
            conn: Optional connection.

        Returns:
            List of trending maps with scores.
        """
        _conn = self._get_connection(conn)

        # Calculate window start timestamp
        window_start = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=window_days)

        query = """
        WITH base AS (
            SELECT id, code, map_name
            FROM core.maps
            WHERE hidden IS NOT TRUE
              AND archived IS NOT TRUE
        ),

        clicks AS (
            SELECT
                c.map_id,
                COUNT(DISTINCT c.ip_hash) AS clicks
            FROM maps.clicks c
            WHERE c.inserted_at >= $1
            GROUP BY c.map_id
        ),

        completions AS (
            SELECT
                c.map_id,
                COUNT(*) AS completions
            FROM core.completions c
            WHERE c.inserted_at >= $1
              AND c.verified = TRUE
              AND COALESCE(c.legacy, FALSE) = FALSE
            GROUP BY c.map_id
        ),

        upvotes AS (
            SELECT
                c.map_id,
                COUNT(*) AS upvotes
            FROM completions.upvotes u
            JOIN core.completions c ON c.message_id = u.message_id
            WHERE u.inserted_at >= $1
            GROUP BY c.map_id
        ),

        metrics AS (
            SELECT
                b.id,
                b.code,
                b.map_name,
                COALESCE(cl.clicks, 0)       AS clicks,
                COALESCE(co.completions, 0)  AS completions,
                COALESCE(u.upvotes, 0)       AS upvotes
            FROM base b
            LEFT JOIN clicks      cl ON cl.map_id = b.id
            LEFT JOIN completions co ON co.map_id = b.id
            LEFT JOIN upvotes     u  ON u.map_id  = b.id
        ),

        ratings AS (
            SELECT
                mr.map_id,
                AVG(mr.quality) AS avg_rating,
                COUNT(*)        AS rating_count
            FROM maps.ratings mr
            WHERE mr.verified = TRUE
            GROUP BY mr.map_id
        ),

        metrics_scored AS (
            SELECT
                m.*,
                (
                    0.2 * m.clicks +
                    1.0 * m.completions +
                    1.5 * m.upvotes +
                    0.75 * COALESCE(r.avg_rating, 0)
                ) AS trend_score
            FROM metrics m
            LEFT JOIN ratings r ON r.map_id = m.id
            WHERE (m.clicks + m.completions + m.upvotes) > 0
        )

        SELECT
            ms.id,
            ms.code,
            ms.map_name,
            ms.clicks,
            ms.completions,
            ms.upvotes,
            ms.trend_score,
            r.avg_rating,
            r.rating_count
        FROM metrics_scored ms
        LEFT JOIN ratings r ON r.map_id = ms.id
        ORDER BY ms.trend_score DESC
        LIMIT $2
        """

        rows = await _conn.fetch(query, window_start, limit)
        return [dict(row) for row in rows]

    # Legacy conversion

    async def check_pending_verifications(
        self,
        code: str,
        *,
        conn: Connection | None = None,
    ) -> bool:
        """Check if map has pending playtest verifications.

        Args:
            code: Map code.
            conn: Optional connection.

        Returns:
            True if has pending verifications, False otherwise.
        """
        _conn = self._get_connection(conn)

        # Check if there are any unverified completions for this map
        return await _conn.fetchval(
            """
            SELECT EXISTS(
                SELECT 1
                FROM core.completions c
                JOIN core.maps m ON m.id = c.map_id
                WHERE m.code = $1
                    AND c.verified = FALSE
                    AND c.verified_by IS NOT NULL
            )
            """,
            code,
        )

    async def remove_map_medal_entries(
        self,
        code: str,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Remove medal records for a map.

        Args:
            code: Map code.
            conn: Optional connection.
        """
        _conn = self._get_connection(conn)

        await _conn.execute(
            """
            DELETE FROM maps.medals
            WHERE map_id = (SELECT id FROM core.maps WHERE code = $1)
            """,
            code,
        )

    async def convert_completions_to_legacy(
        self,
        code: str,
        *,
        conn: Connection | None = None,
    ) -> int:
        """Convert completions to legacy format.

        Args:
            code: Map code.
            conn: Optional connection.

        Returns:
            Number of completions converted.
        """
        _conn = self._get_connection(conn)

        # Mark completions as legacy (implementation depends on schema)
        result = await _conn.execute(
            """
            UPDATE core.completions
            SET legacy = TRUE
            WHERE map_id = (SELECT id FROM core.maps WHERE code = $1)
                AND legacy = FALSE
            """,
            code,
        )
        return int(result.split()[-1]) if result else 0

    # Map linking

    async def link_map_codes(
        self,
        code1: str,
        code2: str,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Link two map codes (official/unofficial pairing).

        Args:
            code1: First map code.
            code2: Second map code.
            conn: Optional connection.
        """
        _conn = self._get_connection(conn)

        # Link bidirectionally
        await _conn.execute(
            """
            UPDATE core.maps
            SET linked_code = $2
            WHERE code = $1
            """,
            code1,
            code2,
        )
        await _conn.execute(
            """
            UPDATE core.maps
            SET linked_code = $1
            WHERE code = $2
            """,
            code1,
            code2,
        )

    async def unlink_map_codes(
        self,
        code: str,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Unlink a map code from its linked map.

        Args:
            code: Map code to unlink.
            conn: Optional connection.
        """
        _conn = self._get_connection(conn)

        # Get linked code first
        linked_code = await _conn.fetchval(
            "SELECT linked_code FROM core.maps WHERE code = $1",
            code,
        )

        if linked_code:
            # Remove link from both maps (split into two statements to avoid trigger conflicts)
            await _conn.execute(
                "UPDATE core.maps SET linked_code = NULL WHERE code = $1",
                code,
            )
            await _conn.execute(
                "UPDATE core.maps SET linked_code = NULL WHERE code = $1",
                linked_code,
            )

    async def fetch_affected_users(
        self,
        code: str,
        *,
        conn: Connection | None = None,
    ) -> list[int]:
        """Get user IDs affected by map changes (those with completions).

        Args:
            code: Map code.
            conn: Optional connection.

        Returns:
            List of user IDs.
        """
        _conn = self._get_connection(conn)

        rows = await _conn.fetch(
            """
            SELECT DISTINCT c.user_id
            FROM core.completions c
            JOIN core.maps m ON m.id = c.map_id
            WHERE m.code = $1
            """,
            code,
        )
        return [row["user_id"] for row in rows]

    # Playtest operations (minimal for Phase 1)

    async def create_playtest_meta_partial(
        self,
        code: str,
        initial_difficulty: float,
        *,
        conn: Connection | None = None,
    ) -> int:
        """Create partial playtest metadata.

        Args:
            code: Map code.
            initial_difficulty: Initial difficulty estimate.
            conn: Optional connection.

        Returns:
            Created playtest ID.
        """
        _conn = self._get_connection(conn)

        playtest_id = await _conn.fetchval(
            """
            INSERT INTO playtests.meta (map_id, initial_difficulty)
            SELECT id, $2
            FROM core.maps
            WHERE code = $1
            RETURNING id
            """,
            code,
            initial_difficulty,
        )
        return playtest_id

    async def fetch_playtest_plot_data(
        self,
        thread_id: int,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Fetch playtest plot data (placeholder for Phase 3).

        Args:
            thread_id: Playtest thread ID.
            conn: Optional connection.

        Returns:
            Plot data dict or None.
        """
        _conn = self._get_connection(conn)

        # Placeholder - actual implementation in Phase 3
        return None

    # Edit request operations

    async def create_edit_request(  # noqa: PLR0913
        self,
        map_id: int,
        code: str,
        proposed_changes: dict[str, Any],
        reason: str,
        created_by: int,
        *,
        conn: Connection | None = None,
    ) -> dict:
        """Create a new edit request.

        Args:
            map_id: Map ID.
            code: Map code (denormalized).
            proposed_changes: Dict of field -> new_value.
            reason: Reason for the edit.
            created_by: User ID of submitter.
            conn: Optional connection for transaction.

        Returns:
            Created edit request row as dict.

        Raises:
            ForeignKeyViolationError: If map_id or created_by doesn't exist.
        """
        _conn = self._get_connection(conn)

        try:
            row = await _conn.fetchrow(
                """
                INSERT INTO maps.edit_requests (
                    map_id, code, proposed_changes, reason, created_by
                )
                VALUES ($1, $2, $3::jsonb, $4, $5)
                RETURNING
                    id, map_id, code, proposed_changes, reason, created_by,
                    created_at, message_id, resolved_at, accepted,
                    resolved_by, rejection_reason
                """,
                map_id,
                code,
                msgspec.json.encode(proposed_changes).decode(),
                reason,
                created_by,
            )
            return dict(row) if row else {}

        except asyncpg.ForeignKeyViolationError as e:
            constraint = extract_constraint_name(e)
            raise ForeignKeyViolationError(
                constraint_name=constraint or "unknown",
                table="maps.edit_requests",
                detail=str(e),
            ) from e

    async def check_pending_edit_request(
        self,
        map_id: int,
        *,
        conn: Connection | None = None,
    ) -> int | None:
        """Check if map has a pending edit request.

        Args:
            map_id: Map ID.
            conn: Optional connection.

        Returns:
            Edit request ID if pending, else None.
        """
        _conn = self._get_connection(conn)

        return await _conn.fetchval(
            """
            SELECT id
            FROM maps.edit_requests
            WHERE map_id = $1 AND accepted IS NULL
            """,
            map_id,
        )

    async def fetch_edit_request(
        self,
        edit_id: int,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Fetch a specific edit request.

        Args:
            edit_id: Edit request ID.
            conn: Optional connection.

        Returns:
            Edit request row as dict, or None if not found.
        """
        _conn = self._get_connection(conn)

        row = await _conn.fetchrow(
            """
            SELECT
                id, map_id, code, proposed_changes, reason, created_by,
                created_at, message_id, resolved_at, accepted,
                resolved_by, rejection_reason
            FROM maps.edit_requests
            WHERE id = $1
            """,
            edit_id,
        )
        return dict(row) if row else None

    async def fetch_pending_edit_requests(
        self,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch all pending edit requests.

        Args:
            conn: Optional connection.

        Returns:
            List of pending edit request dicts.
        """
        _conn = self._get_connection(conn)

        rows = await _conn.fetch(
            """
            SELECT id, code, message_id
            FROM maps.edit_requests
            WHERE accepted IS NULL
            ORDER BY created_at
            """
        )
        return [dict(row) for row in rows]

    async def fetch_edit_submission(
        self,
        edit_id: int,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Fetch enriched edit request with map data for verification queue.

        Args:
            edit_id: Edit request ID.
            conn: Optional connection.

        Returns:
            Enriched edit request dict with map info, or None if not found.
        """
        _conn = self._get_connection(conn)

        # Get edit request with map info
        edit_row = await _conn.fetchrow(
            """
            SELECT
                e.id, e.code, e.proposed_changes, e.reason,
                e.created_by, e.created_at, e.message_id,
                m.id AS map_id, m.map_name, m.difficulty
            FROM maps.edit_requests e
            JOIN core.maps m ON m.id = e.map_id
            WHERE e.id = $1
            """,
            edit_id,
        )
        if not edit_row:
            return None

        # Get submitter name
        user_row = await _conn.fetchrow(
            """
            SELECT COALESCE(nickname, global_name, 'Unknown User') as name
            FROM core.users
            WHERE id = $1
            """,
            edit_row["created_by"],
        )

        # Get current map data (for comparison)
        map_row = await _conn.fetchrow(
            """
            WITH target_map AS (
                SELECT
                    id, code, map_name, category, checkpoints, difficulty,
                    description, title, custom_banner, hidden, archived, official
                FROM core.maps
                WHERE code = $1
            ),
            mechanics AS (
                SELECT ml.map_id, array_agg(mech.name ORDER BY mech.position) AS mechanics
                FROM maps.mechanic_links ml
                JOIN maps.mechanics mech ON mech.id = ml.mechanic_id
                WHERE ml.map_id = (SELECT id FROM target_map)
                GROUP BY ml.map_id
            ),
            restrictions AS (
                SELECT rl.map_id, array_agg(res.name ORDER BY res.name) AS restrictions
                FROM maps.restriction_links rl
                JOIN maps.restrictions res ON res.id = rl.restriction_id
                WHERE rl.map_id = (SELECT id FROM target_map)
                GROUP BY rl.map_id
            ),
            tags AS (
                SELECT tl.map_id, array_agg(tag.name ORDER BY tag.position) AS tags
                FROM maps.tag_links tl
                JOIN maps.tags tag ON tag.id = tl.tag_id
                WHERE tl.map_id = (SELECT id FROM target_map)
                GROUP BY tl.map_id
            )
            SELECT
                tm.code, tm.map_name, tm.category, tm.checkpoints, tm.difficulty,
                tm.description, tm.title, tm.custom_banner, tm.hidden,
                tm.archived, tm.official,
                mech.mechanics, res.restrictions, tag.tags
            FROM target_map tm
            LEFT JOIN mechanics mech ON mech.map_id = tm.id
            LEFT JOIN restrictions res ON res.map_id = tm.id
            LEFT JOIN tags tag ON tag.map_id = tm.id
            """,
            edit_row["code"],
        )

        # Get creators
        creator_rows = await _conn.fetch(
            """
            SELECT user_id, is_primary
            FROM maps.creators
            WHERE map_id = $1
            ORDER BY is_primary DESC, user_id
            """,
            edit_row["map_id"],
        )

        # Get medals
        medals_row = await _conn.fetchrow(
            """
            SELECT gold, silver, bronze
            FROM maps.medals md
            JOIN core.maps m ON m.id = md.map_id
            WHERE m.code = $1
            """,
            edit_row["code"],
        )

        # Assemble enriched response
        return {
            "edit_request": dict(edit_row),
            "submitter_name": user_row["name"] if user_row else "Unknown User",
            "current_map": dict(map_row) if map_row else {},
            "current_creators": [dict(row) for row in creator_rows],
            "current_medals": dict(medals_row) if medals_row else None,
        }

    async def set_edit_request_message_id(
        self,
        edit_id: int,
        message_id: int,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Set Discord message ID for edit request.

        Args:
            edit_id: Edit request ID.
            message_id: Discord message ID.
            conn: Optional connection.
        """
        _conn = self._get_connection(conn)

        await _conn.execute(
            """
            UPDATE maps.edit_requests
            SET message_id = $2
            WHERE id = $1
            """,
            edit_id,
            message_id,
        )

    async def resolve_edit_request(
        self,
        edit_id: int,
        accepted: bool,
        resolved_by: int,
        rejection_reason: str | None = None,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Mark edit request as resolved.

        Args:
            edit_id: Edit request ID.
            accepted: Whether accepted or rejected.
            resolved_by: User ID of resolver.
            rejection_reason: Reason for rejection (if rejected).
            conn: Optional connection.
        """
        _conn = self._get_connection(conn)

        await _conn.execute(
            """
            UPDATE maps.edit_requests
            SET
                resolved_at = $2,
                accepted = $3,
                resolved_by = $4,
                rejection_reason = $5
            WHERE id = $1
            """,
            edit_id,
            dt.datetime.now(dt.timezone.utc),
            accepted,
            resolved_by,
            rejection_reason,
        )

    async def fetch_user_edit_requests(
        self,
        user_id: int,
        include_resolved: bool = False,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch edit requests submitted by a user.

        Args:
            user_id: User ID.
            include_resolved: Whether to include resolved requests.
            conn: Optional connection.

        Returns:
            List of edit request dicts.
        """
        _conn = self._get_connection(conn)

        query = """
            SELECT
                id, map_id, code, proposed_changes, reason, created_by,
                created_at, message_id, resolved_at, accepted,
                resolved_by, rejection_reason
            FROM maps.edit_requests
            WHERE created_by = $1
        """
        if not include_resolved:
            query += " AND accepted IS NULL"

        query += " ORDER BY created_at DESC"

        rows = await _conn.fetch(query, user_id)
        return [dict(row) for row in rows]


async def provide_maps_repository(state: State) -> MapsRepository:
    """Litestar DI provider for repository.

    Args:
        state: Application state.

    Returns:
        Repository instance.
    """
    return MapsRepository(state.db_pool)
