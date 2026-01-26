"""Repository for completions domain database operations."""

from __future__ import annotations

from typing import Any

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

    async def fetch_map_leaderboard(
        self,
        code: str,
        page_size: int,
        page_number: int,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch leaderboard for a map.

        Args:
            code: Map code.
            page_size: Number of results per page (0 for all).
            page_number: Page number (1-indexed).
            conn: Optional connection for transaction support.

        Returns:
            List of completion records as dicts.
        """
        _conn = self._get_connection(conn)
        query_template = """
        WITH target_map AS (
            SELECT
                id AS map_id,
                code,
                map_name,
                difficulty
            FROM core.maps
            WHERE code = $1
        ), latest_per_user_all AS (
            SELECT DISTINCT ON (c.user_id)
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
            JOIN target_map tm ON tm.map_id = c.map_id
            WHERE c.verified = TRUE
            ORDER BY c.user_id,
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
                rank() OVER (ORDER BY s.time) AS rank
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
                cb.user_id,
                cb.time,
                cb.completion,
                cb.verified,
                cb.screenshot,
                cb.video,
                cb.legacy,
                cb.legacy_medal,
                cb.inserted_at,
                cb.rank,
                cb.message_id,
                (cb.rank IS NULL) AS is_nonrankable,
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
            FROM (
                SELECT DISTINCT
                    user_id
                FROM with_map
            ) um
            JOIN core.users u ON u.id = um.user_id
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
            wm.message_id,
            (SELECT COUNT(*) FROM completions.upvotes WHERE message_id=wm.message_id) AS upvotes,
            wm.rank AS rank,
            CASE
                WHEN wm.rank IS NOT NULL AND wm.gold IS NOT NULL AND wm.time <= wm.gold
                    THEN 'Gold'
                WHEN wm.rank IS NOT NULL AND wm.silver IS NOT NULL AND wm.time <= wm.silver
                    THEN 'Silver'
                WHEN wm.rank IS NOT NULL AND wm.bronze IS NOT NULL AND wm.time <= wm.bronze
                    THEN 'Bronze'
            END AS medal,
            wm.map_name AS map_name,
            wm.difficulty AS difficulty,
            wm.legacy AS legacy,
            wm.legacy_medal AS legacy_medal,
            FALSE AS suspicious,
            COUNT(*) OVER() AS total_results
        FROM with_map wm
        JOIN name_split ns ON ns.user_id = wm.user_id
        ORDER BY wm.code,
            CASE
                WHEN wm.legacy = FALSE AND wm.rank IS NOT NULL THEN 0
                WHEN wm.legacy = FALSE AND wm.rank IS NULL     THEN 1
                WHEN wm.legacy = TRUE  AND wm.rank IS NOT NULL THEN 2
                ELSE 3
            END,
            wm.time,
            wm.inserted_at
        {limit_offset}
        """

        if page_size == 0:
            query = query_template.format(limit_offset="")
            rows = await _conn.fetch(query, code)
        else:
            query = query_template.format(limit_offset="LIMIT $2 OFFSET $3")
            offset = (page_number - 1) * page_size
            rows = await _conn.fetch(query, code, page_size, offset)

        return [dict(row) for row in rows]

    async def fetch_legacy_completions(
        self,
        code: str,
        page_size: int,
        page_number: int,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch legacy completions for a map.

        Args:
            code: Map code.
            page_size: Number of results per page.
            page_number: Page number (1-indexed).
            conn: Optional connection for transaction support.

        Returns:
            List of legacy completion records as dicts.
        """
        _conn = self._get_connection(conn)
        query = """
        WITH target_map AS (
            SELECT
                id AS map_id,
                code,
                map_name,
                difficulty
            FROM core.maps
            WHERE code = $1
        ),
            latest_legacy_per_user AS (
                SELECT DISTINCT ON (c.user_id)
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
                JOIN target_map tm ON tm.map_id = c.map_id
                WHERE c.legacy = TRUE
                ORDER BY c.user_id, c.inserted_at DESC
            ),
            ranked AS (
                SELECT
                    l.*,
                    CASE
                        WHEN l.completion = FALSE THEN
                                    RANK() OVER (ORDER BY l.time, l.inserted_at)
                        ELSE NULL::int
                    END AS rank
                FROM latest_legacy_per_user l
            ),
            with_map AS (
                SELECT
                    tm.code,
                    tm.map_name,
                    tm.difficulty,
                    r.user_id,
                    r.time,
                    r.screenshot,
                    r.video,
                    r.completion,
                    r.verified,
                    r.rank,
                    r.message_id,
                    r.inserted_at,
                    r.legacy,
                    r.legacy_medal
                FROM ranked r
                JOIN target_map tm ON tm.map_id = r.map_id
            ),
            user_names AS (
                SELECT
                    u.id AS user_id,
                            MAX(owu.username) FILTER (WHERE owu.is_primary) AS primary_ow,
                    ARRAY_REMOVE(ARRAY_AGG(DISTINCT owu.username), NULL) AS all_ow_names,
                    u.nickname,
                    u.global_name
                FROM (SELECT DISTINCT user_id FROM with_map) um
                JOIN core.users u ON u.id = um.user_id
                LEFT JOIN users.overwatch_usernames owu ON owu.user_id = u.id
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
            wm.code                               AS code,
            wm.user_id                            AS user_id,
            ns.name                               AS name,
            ns.also_known_as                      AS also_known_as,
            wm.time                               AS time,
            wm.screenshot                         AS screenshot,
            wm.video                              AS video,
            wm.completion                         AS completion,
            wm.verified                           AS verified,
            wm.rank                               AS rank,
            wm.legacy_medal                       AS medal,
            wm.map_name                           AS map_name,
            wm.difficulty                         AS difficulty,
            wm.message_id                         AS message_id,
            (SELECT COUNT(*) FROM completions.upvotes WHERE message_id=wm.message_id) AS upvotes,
            wm.legacy                             AS legacy,
            wm.legacy_medal                       AS legacy_medal,
            FALSE                                 AS suspicious
        FROM with_map wm
        JOIN name_split ns ON ns.user_id = wm.user_id
        ORDER BY
            wm.time,
            wm.inserted_at
        LIMIT $2
        OFFSET $3;
        """
        offset = (page_number - 1) * page_size
        rows = await _conn.fetch(query, code, page_size, offset)
        return [dict(row) for row in rows]

    async def fetch_completion_submission(
        self,
        record_id: int,
        *,
        conn: Connection | None = None,
    ) -> dict:
        """Fetch detailed submission info for a completion.

        Args:
            record_id: Completion record ID.
            conn: Optional connection for transaction support.

        Returns:
            Submission details as dict.
        """
        _conn = self._get_connection(conn)
        query = """
        WITH hypothetical_target AS (
            SELECT
                c.*,
                m.code        AS code,
                m.difficulty  AS difficulty,
                m.map_name
            FROM core.completions c
            JOIN core.maps m ON m.id = c.map_id
            WHERE c.id = $1
        ),
        latest_per_user AS (
            SELECT DISTINCT ON (c.user_id)
                c.user_id,
                c.time,
                c.inserted_at
            FROM core.completions c
            WHERE c.map_id = (SELECT map_id FROM hypothetical_target)
              AND c.verified = TRUE
              AND c.completion = FALSE
            ORDER BY c.user_id, c.inserted_at DESC
        ),
        eligible_ranked AS (
            SELECT user_id, time
            FROM latest_per_user

            UNION ALL

            SELECT ht.user_id, ht.time
            FROM hypothetical_target ht
            WHERE ht.completion = FALSE
                AND NOT EXISTS (
                SELECT 1
                FROM latest_per_user l
                WHERE l.user_id = ht.user_id
                    AND l.time = ht.time
                )
        ),
        ranked AS (
            SELECT
                user_id,
                time,
                RANK() OVER (ORDER BY time) AS rank
            FROM eligible_ranked
        ),
        final AS (
            SELECT
                ht.id,
                ht.user_id,
                ht.time,
                ht.screenshot,
                ht.video,
                ht.verified,
                ht.completion,
                ht.inserted_at,
                ht.code,
                ht.difficulty,
                ht.map_name,
                r.rank AS hypothetical_rank,
                md.gold,
                md.silver,
                md.bronze,
                ht.verified_by,
                ht.verification_id,
                ht.message_id
            FROM hypothetical_target ht
            LEFT JOIN ranked r
              ON r.user_id = ht.user_id AND r.time = ht.time
            LEFT JOIN maps.medals md
              ON md.map_id = ht.map_id
        ),
        user_names AS (
            SELECT
                u.id AS user_id,
                ARRAY_REMOVE(
                    COALESCE(
                        ARRAY_AGG(owu.username ORDER BY owu.is_primary DESC, owu.username),
                        ARRAY[]::text[]
                    )
                    || ARRAY[u.nickname, u.global_name],
                    NULL
                ) AS all_usernames
            FROM final f
            JOIN core.users u ON u.id = f.user_id
            LEFT JOIN users.overwatch_usernames owu ON owu.user_id = u.id
            GROUP BY u.id, u.nickname, u.global_name
        ),
        name_split AS (
            SELECT
                un.user_id,
                un.all_usernames[1] AS name,
                COALESCE(
                    array_to_string(
                        ARRAY(
                            SELECT DISTINCT x
                            FROM unnest(un.all_usernames[2:array_length(un.all_usernames, 1)]) AS x
                            WHERE x IS NOT NULL AND x <> ''
                        ),
                        ', '
                    ),
                    ''
                ) AS also_known_as
            FROM user_names un
        ),
        medal_eval AS (
            SELECT
                f.*,
                ns.name,
                ns.also_known_as,
                CASE
                    WHEN f.completion = FALSE AND f.gold   IS NOT NULL AND f.time <= f.gold   THEN 'Gold'
                    WHEN f.completion = FALSE AND f.silver IS NOT NULL AND f.time <= f.silver THEN 'Silver'
                    WHEN f.completion = FALSE AND f.bronze IS NOT NULL AND f.time <= f.bronze THEN 'Bronze'
                END AS hypothetical_medal
            FROM final f
            JOIN name_split ns ON ns.user_id = f.user_id
        )
        SELECT
            id,
            user_id,
            time,
            screenshot,
            video,
            verified,
            completion,
            inserted_at,
            code,
            difficulty,
            map_name,
            hypothetical_rank,
            hypothetical_medal,
            name,
            also_known_as,
            verified_by,
            verification_id,
            message_id,
            EXISTS (
              SELECT 1
              FROM users.suspicious_flags sf
              JOIN core.completions c2
                ON c2.id = sf.completion_id
              WHERE c2.user_id = me.user_id
            ) AS suspicious
        FROM medal_eval me;
        """
        row = await _conn.fetchrow(query, record_id)
        return dict(row) if row else {}

    async def fetch_pending_verifications(
        self,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch completions awaiting verification.

        Args:
            conn: Optional connection for transaction support.

        Returns:
            List of pending verification records as dicts.
        """
        _conn = self._get_connection(conn)
        query = """
            SELECT id, verification_id FROM core.completions
            WHERE verified=FALSE AND verified_by IS NULL AND verification_id IS NOT NULL
            ORDER BY inserted_at DESC;
        """
        rows = await _conn.fetch(query)
        return [dict(row) for row in rows]

    async def fetch_all_completions(
        self,
        page_size: int,
        page_number: int,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch all verified completions sorted by most recent.

        Args:
            page_size: Number of results per page.
            page_number: Page number (1-indexed).
            conn: Optional connection for transaction support.

        Returns:
            List of completion records as dicts.
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
                c.inserted_at
            FROM core.completions c
            WHERE c.verified
              AND c.legacy = FALSE
            ORDER BY c.user_id,
                c.map_id,
                c.inserted_at DESC
        ), current_ranks AS (
            SELECT
                l.map_id,
                l.user_id,
                CASE
                    WHEN l.completion = FALSE
                        THEN rank() OVER (PARTITION BY l.map_id ORDER BY l.time, l.inserted_at)
                    ELSE NULL::int
                END AS current_rank
            FROM latest_per_user_per_map l
        )
        SELECT
            m.code,
            c.user_id,
            coalesce(ow.username, u.nickname, u.global_name, 'Unknown Username') AS name,
            (
                SELECT
                    ou.username
                FROM users.overwatch_usernames ou
                WHERE ou.user_id = c.user_id
                  AND NOT ou.is_primary
                ORDER BY c.inserted_at DESC NULLS LAST
                LIMIT 1
            ) AS also_known_as,
            c.time,
            c.screenshot,
            c.video,
            c.completion,
            c.verified,
            CASE WHEN lp.id = c.id THEN r.current_rank END AS rank,
            CASE
                WHEN med.gold IS NOT NULL AND c.time <= med.gold
                    THEN 'Gold'
                WHEN med.silver IS NOT NULL AND c.time <= med.silver
                    THEN 'Silver'
                WHEN med.bronze IS NOT NULL AND c.time <= med.bronze
                    THEN 'Bronze'
            END AS medal,
            m.map_name,
            m.difficulty,
            c.message_id,
            (SELECT COUNT(*) FROM completions.upvotes WHERE message_id=c.message_id) AS upvotes,
            c.legacy,
            c.legacy_medal,
            FALSE AS suspicious,
            count(*) OVER () AS total_results
        FROM core.completions c
        JOIN core.maps m ON m.id = c.map_id
        JOIN core.users u ON u.id = c.user_id
        LEFT JOIN users.overwatch_usernames ow ON ow.user_id = u.id AND ow.is_primary
        LEFT JOIN maps.medals med ON med.map_id = m.id
        LEFT JOIN latest_per_user_per_map lp ON lp.user_id = c.user_id AND lp.map_id = c.map_id
        LEFT JOIN current_ranks r ON r.user_id = c.user_id AND r.map_id = c.map_id
        LEFT JOIN LATERAL (
            WITH ow AS (
                SELECT username, is_primary
                FROM users.overwatch_usernames
                WHERE user_id = c.user_id
            ),
                display AS (
                    SELECT COALESCE(
                            (SELECT username FROM ow WHERE is_primary LIMIT 1),
                            u.nickname,
                            u.global_name,
                            'Unknown Username'
                           ) AS name
                ),
                candidates AS (
                    SELECT u.global_name AS n
                    UNION ALL SELECT u.nickname
                    UNION ALL SELECT username FROM ow
                ),
                dedup AS (
                    SELECT DISTINCT ON (lower(btrim(n))) btrim(n) AS n
                    FROM candidates
                    WHERE n IS NOT NULL AND btrim(n) <> ''
                    ORDER BY lower(btrim(n))
                )
            SELECT
                (SELECT name FROM display) AS name,
                NULLIF(
                        array_to_string(
                                ARRAY(
                                        SELECT n
                                        FROM dedup
                                        WHERE lower(n) <> lower((SELECT name FROM display))
                                        ORDER BY n
                                ),
                                ', '
                        ),
                        ''
                ) AS also_known_as
            ) names ON TRUE

        WHERE TRUE
          AND c.verified
          AND c.legacy = FALSE
          AND c.message_id IS NOT NULL
        ORDER BY c.inserted_at DESC
        LIMIT $1 OFFSET $2;
        """
        offset = (page_number - 1) * page_size
        rows = await _conn.fetch(query, page_size, offset)
        return [dict(row) for row in rows]

    async def fetch_suspicious_flags(
        self,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch suspicious flags for a user.

        Args:
            user_id: User ID.
            conn: Optional connection for transaction support.

        Returns:
            List of suspicious flag records as dicts.
        """
        _conn = self._get_connection(conn)
        query = """
            SELECT
                usf.id, u.id AS user_id, usf.context, usf.flag_type, cc.message_id, cc.verification_id, usf.flagged_by
            FROM users.suspicious_flags usf
            LEFT JOIN core.completions cc ON cc.id = usf.completion_id
            LEFT JOIN core.users u ON cc.user_id = u.id
            WHERE u.id = $1
        """
        rows = await _conn.fetch(query, user_id)
        return [dict(row) for row in rows]

    async def fetch_upvote_count(
        self,
        message_id: int,
        *,
        conn: Connection | None = None,
    ) -> int:
        """Fetch upvote count for a message.

        Args:
            message_id: Discord message ID.
            conn: Optional connection for transaction support.

        Returns:
            Upvote count.
        """
        _conn = self._get_connection(conn)
        query = """SELECT count(*) as upvotes FROM completions.upvotes WHERE message_id=$1 GROUP BY message_id;"""
        val = await _conn.fetchval(query, message_id)
        return val or 0

    async def check_previous_world_record_xp(
        self,
        code: str,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> bool:
        """Check if user has ever received WR XP for this map.

        Args:
            code: Map code.
            user_id: User ID.
            conn: Optional connection for transaction support.

        Returns:
            True if user has received WR XP, False otherwise.
        """
        _conn = self._get_connection(conn)
        query = """
        WITH target_map AS (
            SELECT id AS map_id FROM core.maps WHERE code = $1
        )
        SELECT EXISTS(
            SELECT 1 FROM core.completions c
            LEFT JOIN target_map tm ON c.map_id = tm.map_id
            WHERE user_id=$2 AND NOT legacy AND wr_xp_check
        )
        """
        return await _conn.fetchval(query, code, user_id)

    async def fetch_records_filtered(  # noqa: PLR0913
        self,
        code: str | None,
        user_id: int | None,
        verification_status: str,
        latest_only: bool,
        page_size: int,
        page_number: int,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch records with filters for moderation.

        Args:
            code: Optional map code filter.
            user_id: Optional user ID filter.
            verification_status: "Verified", "Unverified", or "All".
            latest_only: Whether to only show latest per user per map.
            page_size: Number of results per page (0 for all).
            page_number: Page number (1-indexed).
            conn: Optional connection for transaction support.

        Returns:
            List of completion records as dicts.
        """
        _conn = self._get_connection(conn)

        params: list[Any] = []
        param_idx = 1
        where_clauses: list[str] = []

        if code:
            where_clauses.append(f"m.code = ${param_idx}")
            params.append(code)
            param_idx += 1

        if user_id:
            where_clauses.append(f"c.user_id = ${param_idx}")
            params.append(user_id)
            param_idx += 1

        if verification_status == "Verified":
            where_clauses.append("c.verified = TRUE")
        elif verification_status == "Unverified":
            where_clauses.append("c.verified = FALSE")

        where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        if latest_only:
            query = f"""
            WITH latest_per_user_per_map AS (
                SELECT DISTINCT ON (c.user_id, c.map_id)
                    c.id,
                    c.user_id,
                    c.map_id,
                    c.time,
                    c.screenshot,
                    c.video,
                    c.completion,
                    c.verified,
                    c.message_id,
                    c.legacy,
                    c.legacy_medal,
                    c.inserted_at
                FROM core.completions c
                JOIN core.maps m ON m.id = c.map_id
                {where_sql}
                ORDER BY c.user_id, c.map_id, c.inserted_at DESC
            ),
            name_split AS (
                SELECT
                    un.user_id,
                    un.name,
                    COALESCE(STRING_AGG(
                        CASE WHEN un.rn > 1 THEN un.name END,
                        ', '
                    ), '') AS also_known_as
                FROM (
                    SELECT
                        u.id AS user_id,
                        COALESCE(u.nickname, u.global_name) AS name,
                        ROW_NUMBER() OVER (PARTITION BY u.id ORDER BY
                            CASE WHEN u.nickname IS NOT NULL THEN 1
                                 WHEN u.global_name IS NOT NULL THEN 2
                            END
                        ) AS rn
                    FROM core.users u
                ) un
                GROUP BY un.user_id, un.name
            ),
            ranked AS (
                SELECT
                    l.*,
                    RANK() OVER (PARTITION BY l.map_id ORDER BY l.time, l.inserted_at) AS rank
                FROM latest_per_user_per_map l
            )
            SELECT
                m.code,
                r.user_id,
                ns.name,
                ns.also_known_as,
                r.time,
                r.screenshot,
                r.video,
                r.completion,
                r.verified,
                r.rank,
                CASE
                    WHEN r.legacy THEN r.legacy_medal
                    WHEN r.time <= md.gold THEN 'Gold'
                    WHEN r.time <= md.silver THEN 'Silver'
                    WHEN r.time <= md.bronze THEN 'Bronze'
                END AS medal,
                m.map_name,
                m.difficulty,
                r.message_id,
                r.legacy,
                r.legacy_medal,
                COALESCE(
                    (SELECT COUNT(*) > 0 FROM users.suspicious_flags WHERE completion_id = r.id), FALSE
                ) AS suspicious,
                (SELECT COUNT(*) FROM completions.upvotes WHERE message_id = r.message_id) AS upvotes,
                r.id
            FROM ranked r
            JOIN core.maps m ON m.id = r.map_id
            LEFT JOIN maps.medals md ON md.map_id = r.map_id
            JOIN name_split ns ON ns.user_id = r.user_id
            WHERE r.message_id IS NOT NULL
            ORDER BY r.time ASC, r.inserted_at ASC
            LIMIT ${param_idx} OFFSET ${param_idx + 1};
            """
        else:
            query = f"""
            WITH name_split AS (
                SELECT
                    un.user_id,
                    un.name,
                    COALESCE(STRING_AGG(
                        CASE WHEN un.rn > 1 THEN un.name END,
                        ', '
                    ), '') AS also_known_as
                FROM (
                    SELECT
                        u.id AS user_id,
                        COALESCE(u.nickname, u.global_name) AS name,
                        ROW_NUMBER() OVER (PARTITION BY u.id ORDER BY
                            CASE WHEN u.nickname IS NOT NULL THEN 1
                                 WHEN u.global_name IS NOT NULL THEN 2
                            END
                        ) AS rn
                    FROM core.users u
                ) un
                GROUP BY un.user_id, un.name
            ),
            ranked AS (
                SELECT
                    c.*,
                    RANK() OVER (PARTITION BY c.map_id ORDER BY c.time, c.inserted_at) AS rank
                FROM core.completions c
                JOIN core.maps m ON m.id = c.map_id
                {where_sql}
            )
            SELECT
                m.code,
                r.user_id,
                ns.name,
                ns.also_known_as,
                r.time,
                r.screenshot,
                r.video,
                r.completion,
                r.verified,
                r.rank,
                CASE
                    WHEN r.legacy THEN r.legacy_medal
                    WHEN r.time <= md.gold THEN 'Gold'
                    WHEN r.time <= md.silver THEN 'Silver'
                    WHEN r.time <= md.bronze THEN 'Bronze'
                END AS medal,
                m.map_name,
                m.difficulty,
                r.message_id,
                r.legacy,
                r.legacy_medal,
                COALESCE(
                    (SELECT COUNT(*) > 0 FROM users.suspicious_flags WHERE completion_id = r.id), FALSE
                ) AS suspicious,
                (SELECT COUNT(*) FROM completions.upvotes WHERE message_id = r.message_id) AS upvotes,
                r.id
            FROM ranked r
            JOIN core.maps m ON m.id = r.map_id
            LEFT JOIN maps.medals md ON md.map_id = r.map_id
            JOIN name_split ns ON ns.user_id = r.user_id
            WHERE r.message_id IS NOT NULL
            ORDER BY r.time ASC, r.inserted_at ASC
            LIMIT ${param_idx} OFFSET ${param_idx + 1};
            """

        if page_size == 0:
            query = query.replace(f"LIMIT ${param_idx} OFFSET ${param_idx + 1};", ";")
            rows = await _conn.fetch(query, *params)
        else:
            offset = (page_number - 1) * page_size
            params.extend([page_size, offset])
            rows = await _conn.fetch(query, *params)

        return [dict(row) for row in rows]
