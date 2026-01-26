"""Community repository for statistics and leaderboard queries."""

from __future__ import annotations

from typing import Literal

from asyncpg import Connection
from litestar.datastructures import State

from .base import BaseRepository


class CommunityRepository(BaseRepository):
    """Repository for community statistics data access."""

    async def fetch_community_leaderboard(  # noqa: PLR0913
        self,
        name: str | None = None,
        tier_name: str | None = None,
        skill_rank: str | None = None,
        sort_column: Literal[
            "xp_amount",
            "nickname",
            "prestige_level",
            "wr_count",
            "map_count",
            "playtest_count",
            "discord_tag",
            "skill_rank",
        ] = "xp_amount",
        sort_direction: Literal["asc", "desc"] = "asc",
        page_size: Literal[10, 20, 25, 50] = 10,
        page_number: int = 1,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch the community leaderboard with filtering, sorting, and pagination.

        Filters by optional `name` (nickname/global name ILIKE), `tier_name` (XP tier),
        and `skill_rank` (derived rank: Ninja → God). Sorts by the given column and
        direction; when `sort_column='skill_rank'` a fixed rank ordering is applied
        (God > Grandmaster > Master > Pro > Skilled > Jumper > Ninja).

        Args:
            name: Optional search string for nickname or global name.
            tier_name: Exact XP tier label to match (e.g., "Bronze II").
            skill_rank: Exact derived skill rank to match (e.g., "Master").
            sort_column: Column to sort by. One of:
                "xp_amount", "nickname", "prestige_level", "wr_count", "map_count",
                "playtest_count", "discord_tag", "skill_rank".
            sort_direction: Sort direction, "asc" or "desc".
            page_size: Page size; one of 10, 20, 25, 50.
            page_number: 1-based page number.
            conn: Optional connection for transaction participation.

        Returns:
            list[dict]: Paged leaderboard rows including XP, tiers, WR count, map count,
            playtest count, Discord tag, and derived skill rank.
        """
        _conn = self._get_connection(conn)

        if sort_column == "skill_rank":
            sort_values = """
                CASE
                    WHEN rank_name = 'Ninja' THEN 7
                    WHEN rank_name = 'Jumper' THEN 6
                    WHEN rank_name = 'Skilled' THEN 5
                    WHEN rank_name = 'Pro' THEN 4
                    WHEN rank_name = 'Master' THEN 3
                    WHEN rank_name = 'Grandmaster' THEN 2
                    WHEN rank_name = 'God' THEN 1
                END
            """
        else:
            sort_values = sort_column

        query = f"""
        WITH unioned_records AS (
            SELECT DISTINCT ON (map_id, user_id)
                map_id,
                user_id,
                time,
                screenshot,
                video,
                verified,
                message_id,
                completion,
                NULL AS medal
            FROM core.completions
            ORDER BY map_id,
                user_id,
                inserted_at DESC
        ), thresholds AS (
            SELECT *
            FROM (
                VALUES ('Easy',10),
                       ('Medium', 10),
                       ('Hard', 10),
                       ('Very Hard', 10),
                       ('Extreme', 7),
                       ('Hell', 3)
            ) AS t(name, threshold)
        ), map_data AS (
            SELECT DISTINCT ON (m.id, r.user_id)
                r.user_id,
                regexp_replace(m.difficulty, '\\s*[-+]\\s*$', '', '') AS base_difficulty
            FROM unioned_records r
            LEFT JOIN core.maps m ON r.map_id = m.id
            WHERE m.official = TRUE
        ), skill_rank_data AS (
            SELECT
                base_difficulty AS difficulty,
                md.user_id,
                coalesce(sum(CASE WHEN md.base_difficulty IS NOT NULL THEN 1 ELSE 0 END), 0) AS completions,
                coalesce(sum(CASE WHEN md.base_difficulty IS NOT NULL THEN 1 ELSE 0 END), 0) >= t.threshold AS rank_met
            FROM map_data md
            LEFT JOIN thresholds t ON base_difficulty=t.name
            GROUP BY base_difficulty,
                t.threshold,
                md.user_id
        ), first_rank AS (
            SELECT
                difficulty,
                user_id,
                CASE
                    WHEN difficulty = 'Easy' THEN 'Jumper'
                    WHEN difficulty = 'Medium' THEN 'Skilled'
                    WHEN difficulty = 'Hard' THEN 'Pro'
                    WHEN difficulty = 'Very Hard' THEN 'Master'
                    WHEN difficulty = 'Extreme' THEN 'Grandmaster'
                    WHEN difficulty = 'Hell' THEN 'God'
                END AS rank_name,
                row_number() OVER (
                    PARTITION BY user_id ORDER BY CASE difficulty
                        WHEN 'Easy' THEN 1
                        WHEN 'Medium' THEN 2
                        WHEN 'Hard' THEN 3
                        WHEN 'Very Hard' THEN 4
                        WHEN 'Extreme' THEN 5
                        WHEN 'Hell' THEN 6
                END DESC ) AS rank_order
            FROM skill_rank_data
            WHERE rank_met
        ), all_users AS (
            SELECT DISTINCT
                user_id
            FROM unioned_records
        ), highest_ranks AS (
            SELECT
                u.user_id,
                coalesce(fr.rank_name, 'Ninja') AS rank_name
            FROM all_users u
            LEFT JOIN first_rank fr ON u.user_id = fr.user_id AND fr.rank_order = 1
        ), ranks AS (
            SELECT
                r.user_id,
                r.map_id,
                rank() OVER (PARTITION BY r.map_id ORDER BY time) AS rank_num
            FROM core.completions r
            JOIN core.users u ON r.user_id = u.id
            WHERE u.id > 1000
              AND r.time < 99999999
              AND r.verified = TRUE
        ), world_records AS (
            SELECT
                r.user_id,
                count(r.user_id) AS amount
            FROM ranks r
            WHERE rank_num = 1
            GROUP BY r.user_id
        ), map_counts AS (
            SELECT
                user_id,
                count(*) AS amount
            FROM maps.creators
            GROUP BY user_id
        ), xp_tiers AS (
            SELECT
                u.id,
                coalesce(own.username, nickname) AS nickname,
                u.global_name,
                coalesce(xp.amount, 0) AS xp,
                (coalesce(xp.amount, 0) / 100) AS raw_tier,               -- Integer division for raw tier
                ((coalesce(xp.amount, 0) / 100) % 100) AS normalized_tier,-- Normalized tier, resetting every 100 tiers
                (coalesce(xp.amount, 0) / 100) / 100 AS prestige_level,-- Prestige level based on multiples of 100 tiers
                x.name AS main_tier_name,                                 -- Main tier label without sub-tier levels
                s.name AS sub_tier_name,
                x.name || ' ' || s.name AS full_tier_name                 -- Sub-tier label
            FROM core.users u
            LEFT JOIN users.overwatch_usernames own ON u.id = own.user_id AND own.is_primary = TRUE
            LEFT JOIN lootbox.xp xp ON u.id = xp.user_id
            LEFT JOIN lootbox.main_tiers x ON (((coalesce(xp.amount, 0) / 100) % 100)) / 5 = x.threshold
            LEFT JOIN lootbox.sub_tiers s ON (coalesce(xp.amount, 0) / 100) % 5 = s.threshold

            WHERE u.id > 100000
        ),
        playtest_counts AS (
            SELECT pv.user_id, count(*) + dc.count AS amount
            FROM playtests.votes pv
            LEFT JOIN playtests.deprecated_count dc ON pv.user_id = dc.user_id
            GROUP BY pv.user_id, dc.count
        )
        SELECT
            u.id as user_id,
            u.nickname AS nickname,
            xp AS xp_amount,
            raw_tier,
            normalized_tier,
            prestige_level,
            full_tier_name AS tier_name,
            coalesce(wr.amount, 0) AS wr_count,
            coalesce(mc.amount, 0) AS map_count,
            coalesce(ptc.amount, 0) AS playtest_count,
            coalesce(u.global_name, 'Unknown Username') AS discord_tag,
            coalesce(rank_name, 'Ninja') AS skill_rank,
            count(*) OVER () AS total_results
        FROM xp_tiers u
        LEFT JOIN playtest_counts ptc ON u.id = ptc.user_id
        LEFT JOIN map_counts mc ON u.id = mc.user_id
        LEFT JOIN world_records wr ON u.id = wr.user_id
        LEFT JOIN highest_ranks hr ON u.id = hr.user_id
        WHERE ($3::text IS NULL OR (nickname ILIKE $3::text OR u.global_name ILIKE $3::text))
          AND ($4::text IS NULL OR full_tier_name = $4::text)
          AND ($5::text IS NULL OR rank_name = $5::text)
        ORDER BY {sort_values} {sort_direction}
        LIMIT $1::int OFFSET $2::int
        """
        offset = (page_number - 1) * page_size
        _name = f"%{name}%" if name else name
        rows = await _conn.fetch(query, page_size, offset, _name, tier_name, skill_rank)
        return [dict(row) for row in rows]

    async def fetch_players_per_xp_tier(
        self,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Compute player counts per main XP tier.

        Groups users into XP main tiers and returns the number of players in each tier.

        Returns:
            list[dict]: Count of players for every main XP tier.
        """
        _conn = self._get_connection(conn)

        query = """
        WITH player_xp AS (
            SELECT
                x.name AS tier,
                x.threshold
            FROM core.users u
            LEFT JOIN lootbox.xp xp ON u.id = xp.user_id
            LEFT JOIN lootbox.main_tiers x ON ((coalesce(xp.amount, 0) / 100) % 100) / 5 = x.threshold
            WHERE xp.amount > 500
        ),
            tier_counts AS (
                SELECT
                    tier,
                    threshold,
                    COUNT(*) AS amount
                FROM player_xp
                GROUP BY tier, threshold
            )
        SELECT
            mxt.name AS tier,
            COALESCE(tc.amount, 0) AS amount
        FROM lootbox.main_tiers mxt
        LEFT JOIN tier_counts tc ON mxt.name = tc.tier
        ORDER BY mxt.threshold;
        """
        rows = await _conn.fetch(query)
        return [dict(row) for row in rows]

    async def fetch_players_per_skill_tier(
        self,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Compute player counts per derived skill tier.

        Derives a player's highest skill rank (Ninja → God) from official map
        completions versus thresholds, then returns counts by rank.

        Returns:
            list[dict]: Count of players per skill rank.
        """
        _conn = self._get_connection(conn)

        query = """
        WITH all_completions AS (
            SELECT DISTINCT ON (map_id, user_id)
                map_id,
                user_id,
                time,
                screenshot,
                video,
                verified,
                message_id,
                completion,
                NULL AS medal
            FROM core.completions
            ORDER BY map_id, user_id, inserted_at DESC
        ),
        thresholds AS (
            SELECT * FROM (
                VALUES
                    ('Easy', 10),
                    ('Medium', 10),
                    ('Hard', 10),
                    ('Very Hard', 10),
                    ('Extreme', 7),
                    ('Hell', 3)
            ) AS t(name, threshold)
        ),
        map_data AS (
            SELECT DISTINCT ON (m.id, c.user_id)
                c.user_id,
                m.difficulty
            FROM all_completions c
            LEFT JOIN core.maps m ON c.map_id = m.id
            WHERE m.official = TRUE
        ),
        skill_rank_data AS (
            SELECT
                md.difficulty,
                md.user_id,
                COALESCE(SUM(CASE WHEN md.difficulty IS NOT NULL THEN 1 ELSE 0 END), 0) AS completions,
                COALESCE(SUM(CASE WHEN md.difficulty IS NOT NULL THEN 1 ELSE 0 END), 0) >= t.threshold AS rank_met
            FROM map_data md
            LEFT JOIN thresholds t ON md.difficulty = t.name
            GROUP BY md.difficulty, t.threshold, md.user_id
        ),
        first_rank AS (
            SELECT
                difficulty,
                user_id,
                CASE
                    WHEN difficulty = 'Easy' THEN 'Jumper'
                    WHEN difficulty = 'Medium' THEN 'Skilled'
                    WHEN difficulty = 'Hard' THEN 'Pro'
                    WHEN difficulty = 'Very Hard' THEN 'Master'
                    WHEN difficulty = 'Extreme' THEN 'Grandmaster'
                    WHEN difficulty = 'Hell' THEN 'God'
                END AS rank_name,
                        ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY
                    CASE difficulty
                        WHEN 'Easy' THEN 1
                        WHEN 'Medium' THEN 2
                        WHEN 'Hard' THEN 3
                        WHEN 'Very Hard' THEN 4
                        WHEN 'Extreme' THEN 5
                        WHEN 'Hell' THEN 6
                    END DESC
                    ) AS rank_order
            FROM skill_rank_data
            WHERE rank_met
        ),
        all_users AS (
            SELECT DISTINCT id FROM core.users
        ),
        highest_ranks AS (
            SELECT coalesce(fr.rank_name, 'Ninja') AS rank_name
            FROM all_users u
            LEFT JOIN first_rank fr ON u.id = fr.user_id AND fr.rank_order = 1
        )
        SELECT count(*) AS amount, rank_name as tier FROM highest_ranks GROUP BY rank_name
        ORDER BY CASE
            WHEN rank_name = 'Ninja' THEN 7
            WHEN rank_name = 'Jumper' THEN 6
            WHEN rank_name = 'Skilled' THEN 5
            WHEN rank_name = 'Pro' THEN 4
            WHEN rank_name = 'Master' THEN 3
            WHEN rank_name = 'Grandmaster' THEN 2
            WHEN rank_name = 'God' THEN 1
        END DESC;
        """
        rows = await _conn.fetch(query)
        return [dict(row) for row in rows]


async def provide_community_repository(state: State) -> CommunityRepository:
    """Litestar DI provider for CommunityRepository."""
    return CommunityRepository(state.db_pool)
