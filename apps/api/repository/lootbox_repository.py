"""Repository for lootbox domain database operations."""

from __future__ import annotations

from asyncpg import Connection, Pool
from genjishimada_sdk.lootbox import LootboxKeyType
from litestar.datastructures import State

from repository.base import BaseRepository


class LootboxRepository(BaseRepository):
    """Repository for lootbox domain."""

    def __init__(self, pool: Pool) -> None:
        """Initialize repository.

        Args:
            pool: AsyncPG connection pool.
        """
        super().__init__(pool)

    async def fetch_all_rewards(
        self,
        reward_type: str | None = None,
        key_type: LootboxKeyType | None = None,
        rarity: str | None = None,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch all possible rewards with optional filters.

        Args:
            reward_type: Optional filter by reward type.
            key_type: Optional filter by key type.
            rarity: Optional filter by rarity.
            conn: Optional connection for transaction support.

        Returns:
            List of reward records as dicts.
        """
        _conn = self._get_connection(conn)
        query = """
            SELECT *
            FROM lootbox.reward_types
            WHERE
                ($1::text IS NULL OR type = $1::text) AND
                ($2::text IS NULL OR key_type = $2::text) AND
                ($3::text IS NULL OR rarity = $3::text)
            ORDER BY key_type, name
        """
        rows = await _conn.fetch(query, reward_type, key_type, rarity)
        return [dict(row) for row in rows]

    async def fetch_all_key_types(
        self,
        key_type: LootboxKeyType | None = None,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch all possible key types with optional filter.

        Args:
            key_type: Optional filter by key type name.
            conn: Optional connection for transaction support.

        Returns:
            List of key type records as dicts.
        """
        _conn = self._get_connection(conn)
        query = """
            SELECT *
            FROM lootbox.key_types
            WHERE
                ($1::text IS NULL OR name = $1::text)
            ORDER BY name
        """
        rows = await _conn.fetch(query, key_type)
        return [dict(row) for row in rows]

    async def fetch_user_rewards(
        self,
        user_id: int,
        reward_type: str | None = None,
        key_type: LootboxKeyType | None = None,
        rarity: str | None = None,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch all rewards earned by a specific user.

        Combines user_rewards with mastery achievements.

        Args:
            user_id: Target user ID.
            reward_type: Optional filter by reward type.
            key_type: Optional filter by key type.
            rarity: Optional filter by rarity.
            conn: Optional connection for transaction support.

        Returns:
            List of user reward records as dicts.
        """
        _conn = self._get_connection(conn)
        query = """
            SELECT DISTINCT ON (rt.name, rt.key_type, rt.type)
                ur.user_id,
                ur.earned_at,
                rt.name,
                rt.type,
                NULL as medal,
                rt.rarity
            FROM lootbox.user_rewards ur
            LEFT JOIN lootbox.reward_types rt ON ur.reward_name = rt.name
                AND ur.reward_type = rt.type
                AND ur.key_type = rt.key_type
            WHERE
                ur.user_id = $1::bigint AND
                ($2::text IS NULL OR rt.type = $2::text) AND
                ($3::text IS NULL OR ur.key_type = $3::text) AND
                ($4::text IS NULL OR rarity = $4::text)

            UNION ALL

            SELECT
                user_id,
                now() as earned_at,
                map_name as name,
                'mastery' as type,
                medal,
                'common' as rarity
            FROM maps.mastery
            WHERE user_id = $1::bigint AND medal != 'Placeholder' AND ($2::text IS NULL OR medal = $2::text)
        """
        rows = await _conn.fetch(query, user_id, reward_type, key_type, rarity)
        return [dict(row) for row in rows]

    async def fetch_user_keys(
        self,
        user_id: int,
        key_type: LootboxKeyType | None = None,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch keys owned by a user grouped by key type.

        Args:
            user_id: Target user ID.
            key_type: Optional filter by key type.
            conn: Optional connection for transaction support.

        Returns:
            List of key count records as dicts with 'amount' and 'key_type' fields.
        """
        _conn = self._get_connection(conn)
        query = """
            SELECT count(*) as amount, key_type
            FROM lootbox.user_keys
            WHERE
                ($1::bigint = user_id) AND
                ($2::text IS NULL OR key_type = $2::text)
            GROUP BY key_type
        """
        rows = await _conn.fetch(query, user_id, key_type)
        return [dict(row) for row in rows]

    async def fetch_user_key_count(
        self,
        user_id: int,
        key_type: LootboxKeyType,
        *,
        conn: Connection | None = None,
    ) -> int:
        """Get the number of keys a user has of a given type.

        Args:
            user_id: Target user ID.
            key_type: Key type to count.
            conn: Optional connection for transaction support.

        Returns:
            Number of keys (0 if none found).
        """
        _conn = self._get_connection(conn)
        query = "SELECT count(*) as keys FROM lootbox.user_keys WHERE key_type = $1 AND user_id = $2"
        result = await _conn.fetchval(query, key_type, user_id)
        return result or 0

    async def fetch_user_coins(
        self,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> int:
        """Get the number of coins a user has.

        Args:
            user_id: Target user ID.
            conn: Optional connection for transaction support.

        Returns:
            Coin amount (0 if no record exists).
        """
        _conn = self._get_connection(conn)
        query = "SELECT coins FROM core.users WHERE id = $1;"
        result = await _conn.fetchval(query, user_id)
        return result or 0

    async def fetch_xp_tier_change(
        self,
        old_xp: int,
        new_xp: int,
        *,
        conn: Connection | None = None,
    ) -> dict:
        """Calculate tier change when XP is updated.

        Determines whether the user has ranked up, sub-ranked up,
        or achieved a prestige level change.

        Args:
            old_xp: Previous XP amount.
            new_xp: New XP amount.
            conn: Optional connection for transaction support.

        Returns:
            Dict with tier and prestige change details, or empty dict if not found.
        """
        _conn = self._get_connection(conn)
        query = """
            WITH old_tier AS (
                SELECT
                    $1::int AS old_xp,
                    (($1 / 100) % 100) AS old_normalized_tier,
                    (($1 / 100) / 100) AS old_prestige_level,
                    x.name AS old_main_tier_name,
                    s.name AS old_sub_tier_name
                FROM lootbox.main_tiers x
                LEFT JOIN lootbox.sub_tiers s ON (($1 / 100) % 5) = s.threshold
                WHERE (($1 / 100) % 100) / 5 = x.threshold
            ),
            new_tier AS (
                SELECT
                    $2::int AS new_xp,
                    (($2 / 100) % 100) AS new_normalized_tier,
                    (($2 / 100) / 100) AS new_prestige_level,
                    x.name AS new_main_tier_name,
                    s.name AS new_sub_tier_name
                FROM lootbox.main_tiers x
                LEFT JOIN lootbox.sub_tiers s ON (($2 / 100) % 5) = s.threshold
                WHERE (($2 / 100) % 100) / 5 = x.threshold
            )
            SELECT
                o.old_xp,
                n.new_xp,
                o.old_main_tier_name,
                n.new_main_tier_name,
                o.old_sub_tier_name,
                n.new_sub_tier_name,
                old_prestige_level,
                new_prestige_level,
                CASE
                    WHEN o.old_main_tier_name != n.new_main_tier_name THEN 'Main Tier Rank Up'
                    WHEN o.old_sub_tier_name != n.new_sub_tier_name THEN 'Sub-Tier Rank Up'
                END AS rank_change_type,
                o.old_prestige_level != n.new_prestige_level AS prestige_change
            FROM old_tier o
            JOIN new_tier n ON TRUE;
        """
        row = await _conn.fetchrow(query, old_xp, new_xp)
        return dict(row) if row else {}

    async def fetch_xp_multiplier(
        self,
        *,
        conn: Connection | None = None,
    ) -> float | int:
        """Get the XP multiplier that is currently set.

        Args:
            conn: Optional connection for transaction support.

        Returns:
            The XP multiplier value (may be returned as Decimal from database).
        """
        _conn = self._get_connection(conn)
        query = "SELECT * FROM lootbox.xp_multiplier LIMIT 1;"
        result = await _conn.fetchval(query)
        return result or 1.0


async def provide_lootbox_repository(state: State) -> LootboxRepository:
    """Provide LootboxRepository DI.

    Args:
        state: Application state containing the database pool.

    Returns:
        LootboxRepository: New repository instance.
    """
    return LootboxRepository(state.db_pool)
