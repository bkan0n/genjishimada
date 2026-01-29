"""Repository for rank_card data access."""

from __future__ import annotations

from asyncpg import Connection
from litestar.datastructures import State

from .base import BaseRepository


class RankCardRepository(BaseRepository):
    """Repository for rank_card data access."""

    async def fetch_background(
        self,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Fetch user's rank card background.

        Args:
            user_id: User ID.
            conn: Optional connection for transaction participation.

        Returns:
            Dict with background name, or None if not set.
        """
        _conn = self._get_connection(conn)

        query = "SELECT name FROM rank_card.background WHERE user_id = $1"
        row = await _conn.fetchrow(query, user_id)
        return dict(row) if row else None

    async def upsert_background(
        self,
        user_id: int,
        background: str,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Set user's rank card background.

        Args:
            user_id: User ID.
            background: Background name.
            conn: Optional connection for transaction participation.
        """
        _conn = self._get_connection(conn)

        query = """
            INSERT INTO rank_card.background (user_id, name) VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET name = EXCLUDED.name
        """
        await _conn.execute(query, user_id, background)

    async def fetch_avatar(
        self,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Fetch user's avatar skin and pose.

        Args:
            user_id: User ID.
            conn: Optional connection for transaction participation.

        Returns:
            Dict with skin and pose, or None if not set.
        """
        _conn = self._get_connection(conn)

        query = "SELECT skin, pose FROM rank_card.avatar WHERE user_id = $1"
        row = await _conn.fetchrow(query, user_id)
        return dict(row) if row else None

    async def upsert_avatar_skin(
        self,
        user_id: int,
        skin: str,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Set user's avatar skin.

        Args:
            user_id: User ID.
            skin: Skin name.
            conn: Optional connection for transaction participation.
        """
        _conn = self._get_connection(conn)

        query = """
            INSERT INTO rank_card.avatar (user_id, skin) VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET skin = EXCLUDED.skin
        """
        await _conn.execute(query, user_id, skin)

    async def upsert_avatar_pose(
        self,
        user_id: int,
        pose: str,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Set user's avatar pose.

        Args:
            user_id: User ID.
            pose: Pose name.
            conn: Optional connection for transaction participation.
        """
        _conn = self._get_connection(conn)

        query = """
            INSERT INTO rank_card.avatar (user_id, pose) VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET pose = EXCLUDED.pose
        """
        await _conn.execute(query, user_id, pose)

    async def fetch_badges(
        self,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Fetch user's badge settings.

        Args:
            user_id: User ID.
            conn: Optional connection for transaction participation.

        Returns:
            Dict with badge settings (without user_id), or None if not set.
        """
        _conn = self._get_connection(conn)

        query = "SELECT * FROM rank_card.badges WHERE user_id = $1"
        row = await _conn.fetchrow(query, user_id)
        if not row:
            return None
        row_dict = dict(row)
        row_dict.pop("user_id", None)
        return row_dict

    async def upsert_badges(  # noqa: PLR0913
        self,
        user_id: int,
        badge_name1: str | None,
        badge_type1: str | None,
        badge_name2: str | None,
        badge_type2: str | None,
        badge_name3: str | None,
        badge_type3: str | None,
        badge_name4: str | None,
        badge_type4: str | None,
        badge_name5: str | None,
        badge_type5: str | None,
        badge_name6: str | None,
        badge_type6: str | None,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Set user's badge settings.

        Args:
            user_id: User ID.
            badge_name1: Badge 1 name.
            badge_type1: Badge 1 type.
            badge_name2: Badge 2 name.
            badge_type2: Badge 2 type.
            badge_name3: Badge 3 name.
            badge_type3: Badge 3 type.
            badge_name4: Badge 4 name.
            badge_type4: Badge 4 type.
            badge_name5: Badge 5 name.
            badge_type5: Badge 5 type.
            badge_name6: Badge 6 name.
            badge_type6: Badge 6 type.
            conn: Optional connection for transaction participation.
        """
        _conn = self._get_connection(conn)

        query = """
            INSERT INTO rank_card.badges (
                user_id,
                badge_name1, badge_type1,
                badge_name2, badge_type2,
                badge_name3, badge_type3,
                badge_name4, badge_type4,
                badge_name5, badge_type5,
                badge_name6, badge_type6
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            ON CONFLICT (user_id) DO UPDATE SET
                badge_name1 = EXCLUDED.badge_name1,
                badge_type1 = EXCLUDED.badge_type1,
                badge_name2 = EXCLUDED.badge_name2,
                badge_type2 = EXCLUDED.badge_type2,
                badge_name3 = EXCLUDED.badge_name3,
                badge_type3 = EXCLUDED.badge_type3,
                badge_name4 = EXCLUDED.badge_name4,
                badge_type4 = EXCLUDED.badge_type4,
                badge_name5 = EXCLUDED.badge_name5,
                badge_type5 = EXCLUDED.badge_type5,
                badge_name6 = EXCLUDED.badge_name6,
                badge_type6 = EXCLUDED.badge_type6
        """
        await _conn.execute(
            query,
            user_id,
            badge_name1,
            badge_type1,
            badge_name2,
            badge_type2,
            badge_name3,
            badge_type3,
            badge_name4,
            badge_type4,
            badge_name5,
            badge_type5,
            badge_name6,
            badge_type6,
        )

    async def fetch_nickname(
        self,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> str:
        """Fetch user's nickname or primary Overwatch username.

        Args:
            user_id: User ID.
            conn: Optional connection for transaction participation.

        Returns:
            User's nickname or primary username, or "Unknown User" if not found.
        """
        _conn = self._get_connection(conn)

        query = """
            WITH default_name AS (
                SELECT nickname, id as user_id
                FROM core.users
            )
            SELECT coalesce(own.username, dn.nickname) AS nickname
            FROM default_name dn
            LEFT JOIN users.overwatch_usernames own ON own.user_id = dn.user_id AND own.is_primary = TRUE
            WHERE dn.user_id = $1
        """
        return await _conn.fetchval(query, user_id) or "Unknown User"

    async def fetch_map_totals(
        self,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Get total count of official, non-archived maps by difficulty.

        Args:
            conn: Optional connection for transaction participation.

        Returns:
            List of dicts with base_difficulty and total.
        """
        _conn = self._get_connection(conn)

        query = r"""
            SELECT
                regexp_replace(m.difficulty::text, '\s*[-+]\s*$', '') AS base_difficulty,
                count(*) AS total
            FROM core.maps AS m
            WHERE m.official = TRUE
                AND m.archived = FALSE
                AND m.playtesting = 'Approved'
            GROUP BY base_difficulty
            ORDER BY base_difficulty
        """
        rows = await _conn.fetch(query)
        return [dict(row) for row in rows]

    async def fetch_world_record_count(
        self,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> int:
        """Count how many world records a user currently holds.

        Args:
            user_id: User ID.
            conn: Optional connection for transaction participation.

        Returns:
            Number of world records held.
        """
        _conn = self._get_connection(conn)

        query = """
            WITH all_records AS (
                SELECT
                    user_id,
                    m.code,
                    time,
                    rank() OVER (
                        PARTITION BY m.code
                        ORDER BY time
                    ) as pos
                FROM core.completions c
                LEFT JOIN core.maps m on c.map_id = m.id
                WHERE m.official = TRUE AND time < 99999999 AND video IS NOT NULL AND completion IS FALSE
            )
            SELECT count(*) FROM all_records WHERE user_id = $1 AND pos = 1
        """
        return await _conn.fetchval(query, user_id) or 0

    async def fetch_maps_created_count(
        self,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> int:
        """Count how many official maps a user has created.

        Args:
            user_id: User ID.
            conn: Optional connection for transaction participation.

        Returns:
            Total maps created by the user.
        """
        _conn = self._get_connection(conn)

        query = """
            SELECT count(*)
            FROM core.maps m
            LEFT JOIN maps.creators mc ON m.id = mc.map_id
            WHERE user_id = $1 AND official = TRUE
        """
        return await _conn.fetchval(query, user_id) or 0

    async def fetch_playtests_voted_count(
        self,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> int:
        """Count how many playtests a user has voted in.

        Args:
            user_id: User ID.
            conn: Optional connection for transaction participation.

        Returns:
            Number of playtest votes.
        """
        _conn = self._get_connection(conn)

        query = "SELECT count(*) FROM playtests.votes WHERE user_id=$1"
        return await _conn.fetchval(query, user_id) or 0

    async def fetch_community_rank_xp(
        self,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> dict:
        """Fetch XP and prestige data for a user.

        Args:
            user_id: User ID.
            conn: Optional connection for transaction participation.

        Returns:
            Dict with xp, prestige_level, and community_rank.
        """
        _conn = self._get_connection(conn)

        query = """
            SELECT
                coalesce(xp.amount, 0) AS xp,
                (coalesce(xp.amount, 0) / 100) / 100 AS prestige_level,
                x.name || ' ' || s.name AS community_rank
            FROM core.users u
            LEFT JOIN lootbox.xp xp ON u.id = xp.user_id
            LEFT JOIN lootbox.main_tiers x ON (((coalesce(xp.amount, 0) / 100) % 100)) / 5 = x.threshold
            LEFT JOIN lootbox.sub_tiers s ON (coalesce(xp.amount, 0) / 100) % 5 = s.threshold
            WHERE u.id = $1
        """
        row = await _conn.fetchrow(query, user_id)
        assert row, f"User {user_id} not found"
        return dict(row)


async def provide_rank_card_repository(state: State) -> RankCardRepository:
    """Litestar DI provider for repository.

    Args:
        state: Application state.

    Returns:
        Repository instance.
    """
    return RankCardRepository(state.db_pool)
