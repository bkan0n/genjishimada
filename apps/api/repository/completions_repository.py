"""Repository for completions domain database operations."""

from __future__ import annotations

from asyncpg import Connection, Pool

from repository.base import BaseRepository


class CompletionsRepository(BaseRepository):
    """Repository for completions domain."""

    def __init__(self, pool: Pool) -> None:
        """Initialize repository.

        Args:
            pool: AsyncPG connection pool.
        """
        super().__init__(pool)

    async def fetch_user_completions(
        self,
        user_id: int,
        difficulty: str | None,
        page_size: int,
        page_number: int,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch verified completions for a user.

        Args:
            user_id: User ID to fetch completions for.
            difficulty: Optional difficulty filter.
            page_size: Number of results per page.
            page_number: Page number (1-indexed).
            conn: Optional connection for transaction support.

        Returns:
            List of completion records as dicts.
        """
        _conn = self._get_connection(conn)
        query = """
        WITH target_map AS (
            SELECT
                id AS map_id,
                code,
                map_name,
                difficulty,
                raw_difficulty
            FROM core.maps
        ), latest_per_user_all AS (
            SELECT DISTINCT ON (c.user_id, c.map_id)
                c.user_id,
                c.map_id,
                c.time,
                c.completion,
                c.verified,
                c.screenshot,
                c.video,
                c.legacy,
                c.legacy_medal,
                c.message_id,
                c.inserted_at
            FROM core.completions c
            WHERE c.verified = TRUE
            ORDER BY c.user_id,
                c.map_id,
                c.inserted_at DESC
        ), split AS (
            SELECT
                l.user_id,
                l.map_id,
                l.time,
                l.completion,
                l.verified,
                l.screenshot,
                l.video,
                l.legacy,
                l.legacy_medal,
                l.message_id,
                l.inserted_at
            FROM latest_per_user_all l
        ), rankable AS (
            SELECT
                s.*,
                rank() OVER (PARTITION BY s.map_id ORDER BY s.time) AS rank
            FROM split s
            WHERE s.completion = FALSE
        ), nonrankable AS (
            SELECT
                s.*,
                NULL::integer AS rank
            FROM split s
            WHERE s.completion = TRUE
        ), combined AS (
            SELECT *
            FROM rankable
            UNION ALL
            SELECT *
            FROM nonrankable
        ), with_map AS (
            SELECT
                tm.code,
                tm.map_name,
                tm.difficulty,
                tm.raw_difficulty,
                cb.user_id,
                cb.time,
                cb.completion,
                cb.verified,
                cb.screenshot,
                cb.video,
                cb.legacy,
                cb.legacy_medal,
                cb.message_id,
                cb.inserted_at,
                cb.rank,
                md.gold,
                md.silver,
                md.bronze
            FROM combined cb
            JOIN target_map tm ON tm.map_id = cb.map_id
            LEFT JOIN maps.medals md ON md.map_id = cb.map_id
        ), user_names AS (
            SELECT
                u.id AS user_id,
                max(owu.username) FILTER (WHERE owu.is_primary) AS primary_ow,
                array_remove(array_agg(owu.username), NULL) AS all_ow_names,
                u.nickname,
                u.global_name
            FROM with_map wm
            JOIN core.users u ON u.id = wm.user_id
            LEFT JOIN users.overwatch_usernames owu ON owu.user_id = u.id
            GROUP BY u.id,
                u.nickname,
                u.global_name
        ), name_split AS (
            SELECT
                un.user_id,
                coalesce(nullif(un.primary_ow, ''), nullif(un.nickname, ''), nullif(un.global_name, ''),
                         'Unknown User') AS name,
                nullif(array_to_string(array(SELECT DISTINCT
                                                 x
                                             FROM unnest(un.all_ow_names) x
                                             WHERE x IS NOT NULL
                                               AND x <> coalesce(un.primary_ow, '')), ', '), '') AS also_known_as
            FROM user_names un
        )
        SELECT
            wm.code AS code,
            wm.user_id AS user_id,
            ns.name AS name,
            ns.also_known_as AS also_known_as,
            wm.time AS time,
            wm.screenshot AS screenshot,
            wm.video AS video,
            wm.completion AS completion,
            wm.verified AS verified,
            wm.rank AS rank,
            CASE
                WHEN wm.rank IS NOT NULL AND wm.gold   IS NOT NULL AND wm.time <= wm.gold   THEN 'Gold'
                WHEN wm.rank IS NOT NULL AND wm.silver IS NOT NULL AND wm.time <= wm.silver THEN 'Silver'
                WHEN wm.rank IS NOT NULL AND wm.bronze IS NOT NULL AND wm.time <= wm.bronze THEN 'Bronze'
            END AS medal,
            wm.legacy,
            wm.legacy_medal,
            wm.message_id,
            FALSE as suspicious,
            (SELECT COUNT(*) FROM completions.upvotes WHERE message_id=wm.message_id) AS upvotes,
            COUNT(*) OVER() AS total_results
        FROM with_map wm
        JOIN name_split ns ON ns.user_id = wm.user_id
        WHERE wm.user_id = $1
        AND ($2::text IS NULL OR wm.difficulty = $2::text)
        ORDER BY
            wm.raw_difficulty,
            (wm.rank IS NULL),
            wm.time,
            wm.inserted_at
        LIMIT $3 OFFSET $4;
        """
        offset = (page_number - 1) * page_size
        rows = await _conn.fetch(query, user_id, difficulty, page_size, offset)
        return [dict(row) for row in rows]

    async def fetch_world_records_per_user(
        self,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch all world records (rank 1) for a user.

        Args:
            user_id: User ID to fetch world records for.
            conn: Optional connection for transaction support.

        Returns:
            List of world record completions as dicts.
        """
        _conn = self._get_connection(conn)
        query = """
        WITH latest_per_user_per_map AS (
            SELECT DISTINCT ON (c.user_id, c.map_id)
                c.id,
                c.user_id,
                c.map_id,
                c.time,
                c.completion,
                c.verified,
                c.screenshot,
                c.video,
                c.legacy,
                c.legacy_medal,
                c.message_id,
                c.inserted_at
            FROM core.completions c
            WHERE c.verified = TRUE AND c.legacy = FALSE
            ORDER BY c.user_id, c.map_id, c.inserted_at DESC
        ),
            ranked AS (
                SELECT
                    l.*,
                    CASE
                        WHEN l.completion = FALSE THEN
                                    RANK() OVER (
                                PARTITION BY l.map_id
                                ORDER BY l.time, l.inserted_at
                                )
                        ELSE NULL::int
                    END AS rank
                FROM latest_per_user_per_map l
            ),
            with_map AS (
                SELECT
                    r.id,
                    m.code,
                    m.map_name,
                    m.difficulty,
                    m.raw_difficulty,
                    r.user_id,
                    r.time,
                    r.completion,
                    r.verified,
                    r.screenshot,
                    r.video,
                    r.message_id,
                    r.inserted_at,
                    r.legacy,
                    r.legacy_medal,
                    r.rank,
                    md.gold,
                    md.silver,
                    md.bronze
                FROM ranked r
                JOIN core.maps m ON m.id = r.map_id
                LEFT JOIN maps.medals md ON md.map_id = r.map_id
            ),
            user_names AS (
                SELECT
                    u.id AS user_id,
                            MAX(owu.username) FILTER (WHERE owu.is_primary) AS primary_ow,
                    ARRAY_REMOVE(ARRAY_AGG(DISTINCT owu.username), NULL) AS all_ow_names,
                    u.nickname,
                    u.global_name
                FROM core.users u
                LEFT JOIN users.overwatch_usernames owu ON owu.user_id = u.id
                WHERE u.id = $1
                GROUP BY u.id, u.nickname, u.global_name
            ),
            name_split AS (
                SELECT
                    un.user_id,
                    COALESCE(
                            NULLIF(un.primary_ow, ''),
                            NULLIF(un.nickname, ''),
                            NULLIF(un.global_name, ''),
                            'Unknown User'
                    ) AS name,
                    NULLIF((
                               SELECT string_agg(DISTINCT v, ', ')
                               FROM unnest(
                                       ARRAY[
                                           NULLIF(un.global_name, ''),
                                           NULLIF(un.nickname, '')
                                           ] || COALESCE(un.all_ow_names, '{}')
                                    ) AS v
                               WHERE v IS NOT NULL
                                 AND v <> ''
                                 AND v <> COALESCE(
                                       NULLIF(un.primary_ow, ''),
                                       NULLIF(un.nickname, ''),
                                       NULLIF(un.global_name, ''),
                                       'Unknown User'
                                          )
                           ), '') AS also_known_as
                FROM user_names un
            )
        SELECT
            wm.code                             AS code,
            wm.user_id                          AS user_id,
            ns.name                             AS name,
            ns.also_known_as                    AS also_known_as,
            wm.time                             AS time,
            wm.screenshot                       AS screenshot,
            wm.video                            AS video,
            wm.completion                       AS completion,
            wm.verified                         AS verified,
            wm.rank                             AS rank,
            CASE
                WHEN wm.rank = 1 AND wm.gold   IS NOT NULL AND wm.time <= wm.gold   THEN 'Gold'
                WHEN wm.rank = 1 AND wm.silver IS NOT NULL AND wm.time <= wm.silver THEN 'Silver'
                WHEN wm.rank = 1 AND wm.bronze IS NOT NULL AND wm.time <= wm.bronze THEN 'Bronze'
            END                                  AS medal,
            wm.map_name                          AS map_name,
            wm.difficulty                        AS difficulty,
            wm.message_id,
            (SELECT COUNT(*) FROM completions.upvotes WHERE message_id=wm.message_id) AS upvotes,
            wm.legacy,
            wm.legacy_medal,
            FALSE AS suspicious
        FROM with_map wm
        JOIN name_split ns ON ns.user_id = wm.user_id
        WHERE wm.user_id = $1
          AND wm.completion = FALSE
          AND wm.rank = 1
        ORDER BY
            wm.raw_difficulty,
            wm.time,
            wm.inserted_at;
        """
        rows = await _conn.fetch(query, user_id)
        return [dict(row) for row in rows]
