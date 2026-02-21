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
                WHERE ($1::text IS NULL OR type = $1::text)
                  AND ($2::text IS NULL OR key_type = $2::text)
                  AND ($3::text IS NULL OR rarity = $3::text)
                ORDER BY key_type, name \
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
                WHERE ($1::text IS NULL OR name = $1::text)
                ORDER BY name \
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
                    NULL AS medal,
                    rt.rarity
                FROM lootbox.user_rewards ur
                LEFT JOIN lootbox.reward_types rt
                    ON ur.reward_name = rt.name AND ur.reward_type = rt.type AND ur.key_type = rt.key_type
                WHERE ur.user_id = $1::bigint
                  AND ($2::text IS NULL OR rt.type = $2::text)
                  AND ($3::text IS NULL OR ur.key_type = $3::text)
                  AND ($4::text IS NULL OR rarity = $4::text)

                UNION ALL

                SELECT user_id, now() AS earned_at, map_name AS name, 'mastery' AS type, medal, 'common' AS rarity
                FROM maps.mastery
                WHERE user_id = $1::bigint AND medal != 'Placeholder' AND ($2::text IS NULL OR medal = $2::text) \
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
                SELECT count(*) AS amount, key_type
                FROM lootbox.user_keys
                WHERE ($1::bigint = user_id) AND ($2::text IS NULL OR key_type = $2::text)
                GROUP BY key_type \
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
        query = "SELECT count(*) AS keys FROM lootbox.user_keys WHERE key_type = $1 AND user_id = $2"
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
                ), new_tier AS (
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
                        WHEN o.old_main_tier_name != n.new_main_tier_name
                            THEN 'Main Tier Rank Up'
                        WHEN o.old_sub_tier_name != n.new_sub_tier_name
                            THEN 'Sub-Tier Rank Up'
                    END AS rank_change_type,
                    o.old_prestige_level != n.new_prestige_level AS prestige_change
                FROM old_tier o
                JOIN new_tier n ON TRUE; \
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

    async def delete_oldest_user_key(
        self,
        user_id: int,
        key_type: LootboxKeyType,
        *,
        conn: Connection | None = None,
    ) -> bool:
        """Delete the oldest key of a given type for a user.

        Args:
            user_id: Target user ID.
            key_type: Key type to delete.
            conn: Optional connection for transaction participation.

        Returns:
            True if a key was deleted, False if no key existed to delete.
        """
        _conn = self._get_connection(conn)

        query = """
                DELETE
                FROM lootbox.user_keys
                WHERE earned_at = (
                    SELECT min(earned_at)
                    FROM lootbox.user_keys
                    WHERE user_id = $1::bigint AND key_type = $2::text
                )
                  AND user_id = $1::bigint
                  AND key_type = $2::text \
                """
        result = await _conn.execute(query, user_id, key_type)
        return result != "DELETE 0"

    async def check_user_has_reward(
        self,
        user_id: int,
        reward_type: str,
        key_type: LootboxKeyType,
        reward_name: str,
        *,
        conn: Connection | None = None,
    ) -> str | None:
        """Check if user already has a reward and return its rarity.

        Args:
            user_id: Target user ID.
            reward_type: Reward type.
            key_type: Key type.
            reward_name: Reward name.
            conn: Optional connection for transaction participation.

        Returns:
            Rarity string if reward exists, None otherwise.
        """
        _conn = self._get_connection(conn)

        query = """
                SELECT rt.rarity
                FROM lootbox.user_rewards ur
                JOIN lootbox.reward_types rt
                    ON ur.reward_name = rt.name AND ur.reward_type = rt.type AND ur.key_type = rt.key_type
                WHERE ur.user_id = $1::bigint
                  AND ur.reward_type = $2::text
                  AND ur.key_type = $3::text
                  AND ur.reward_name = $4::text \
                """
        return await _conn.fetchval(query, user_id, reward_type, key_type, reward_name)

    async def insert_user_reward(
        self,
        user_id: int,
        reward_type: str,
        key_type: LootboxKeyType,
        reward_name: str,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Insert a reward for a user.

        Args:
            user_id: Target user ID.
            reward_type: Reward type.
            key_type: Key type.
            reward_name: Reward name.
            conn: Optional connection for transaction participation.
        """
        _conn = self._get_connection(conn)

        query = """
                INSERT INTO lootbox.user_rewards (
                    user_id, reward_type, key_type, reward_name
                )
                VALUES (
                    $1, $2, $3, $4
                ) \
                """
        await _conn.execute(query, user_id, reward_type, key_type, reward_name)

    async def add_user_coins(
        self,
        user_id: int,
        amount: int,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Add coins to a user's balance.

        Args:
            user_id: Target user ID.
            amount: Coin amount to add.
            conn: Optional connection for transaction participation.
        """
        _conn = self._get_connection(conn)

        query = """
                INSERT INTO core.users (
                    id, coins
                )
                VALUES (
                    $1, $2
                )
                ON CONFLICT (id) DO UPDATE SET coins = users.coins + excluded.coins \
                """
        await _conn.execute(query, user_id, amount)

    async def deduct_user_coins(
        self,
        user_id: int,
        amount: int,
        *,
        conn: Connection | None = None,
    ) -> int | None:
        """Deduct coins if balance is sufficient, return new balance.

        Args:
            user_id: Target user ID.
            amount: Amount to deduct.
            conn: Optional connection for transaction participation.

        Returns:
            New balance, or None if insufficient.
        """
        _conn = self._get_connection(conn)
        query = """
                UPDATE core.users
                SET coins = coins - $2
                WHERE id = $1 AND coins >= $2
                RETURNING coins
                """
        return await _conn.fetchval(query, user_id, amount)

    async def insert_user_key(
        self,
        user_id: int,
        key_type: LootboxKeyType,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Insert a key for a user.

        Args:
            user_id: Target user ID.
            key_type: Key type to grant.
            conn: Optional connection for transaction participation.
        """
        _conn = self._get_connection(conn)

        query = "INSERT INTO lootbox.user_keys (user_id, key_type) VALUES ($1, $2)"
        await _conn.execute(query, user_id, key_type)

    async def insert_active_key(
        self,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Insert the currently active key for a user.

        Args:
            user_id: Target user ID.
            conn: Optional connection for transaction participation.
        """
        _conn = self._get_connection(conn)

        query = """
                INSERT INTO lootbox.user_keys (
                    user_id, key_type
                )
                SELECT $1, key
                FROM lootbox.active_key
                LIMIT 1 \
                """
        await _conn.execute(query, user_id)

    async def fetch_random_reward(
        self,
        rarity: str,
        key_type: LootboxKeyType,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> dict:
        """Fetch a random reward with duplicate and coin calculation.

        Args:
            rarity: Reward rarity to select.
            key_type: Key type filter.
            user_id: Use1r ID for duplicate check.
            conn: Optional connection for transaction participation.

        Returns:
            Dict with reward info including duplicate flag and coin_amount.
        """
        _conn = self._get_connection(conn)

        query = """
                WITH selected_rewards AS (
                    SELECT *
                    FROM lootbox.reward_types
                    WHERE rarity = $1::text AND key_type = $2::text
                    ORDER BY random()
                    LIMIT 1
                )
                SELECT
                    sr.*,
                    exists(
                        SELECT 1
                        FROM lootbox.user_rewards ur
                        WHERE ur.user_id = $3::bigint
                          AND ur.reward_name = sr.name
                          AND ur.reward_type = sr.type
                          AND ur.key_type = $2::text
                    ) AS duplicate,
                    CASE
                        WHEN exists(
                            SELECT 1
                            FROM lootbox.user_rewards ur
                            WHERE ur.user_id = $3::bigint
                              AND ur.reward_name = sr.name
                              AND ur.reward_type = sr.type
                              AND ur.key_type = $2::text
                        )
                            THEN CASE
                                     WHEN sr.rarity = 'common'
                                         THEN 100
                                     WHEN sr.rarity = 'rare'
                                         THEN 250
                                     WHEN sr.rarity = 'epic'
                                         THEN 500
                                     WHEN sr.rarity = 'legendary'
                                         THEN 1000
                                     ELSE 0
                                 END
                        ELSE 0
                    END AS coin_amount
                FROM selected_rewards sr \
                """
        row = await _conn.fetchrow(query, rarity.lower(), key_type, user_id)
        return dict(row) if row else {}

    async def upsert_user_xp(
        self,
        user_id: int,
        xp_amount: int,
        multiplier: float,
        *,
        conn: Connection | None = None,
    ) -> dict:
        """Upsert user XP with multiplier applied.

        Args:
            user_id: Target user ID.
            xp_amount: Base XP amount to grant.
            multiplier: XP multiplier to apply.
            conn: Optional connection for transaction participation.

        Returns:
            Dict with previous_amount and new_amount.
        """
        _conn = self._get_connection(conn)

        query = """
                WITH old_values AS (
                    SELECT amount
                    FROM lootbox.xp
                    WHERE user_id = $1
                ), upsert_result
                    AS (
                        INSERT INTO lootbox.xp (user_id, amount)
                            SELECT $1,
                                floor($2::numeric * $3::numeric)::bigint
                            ON CONFLICT (user_id) DO UPDATE SET amount = lootbox.xp.amount + excluded.amount
                            RETURNING lootbox.xp.amount
                    )
                SELECT
                    coalesce((
                                 SELECT amount
                                 FROM old_values
                             ), 0) AS previous_amount,
                    (
                        SELECT amount
                        FROM upsert_result
                    ) AS new_amount \
                """
        row = await _conn.fetchrow(query, user_id, xp_amount, multiplier)
        return dict(row) if row else {}

    async def update_xp_multiplier(
        self,
        multiplier: float,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Update the global XP multiplier.

        Args:
            multiplier: New multiplier value.
            conn: Optional connection for transaction participation.
        """
        _conn = self._get_connection(conn)

        query = "UPDATE lootbox.xp_multiplier SET value=$1"
        await _conn.execute(query, multiplier)

    async def fetch_user_xp_summary(
        self,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Fetch a user's complete XP progression summary.

        Computes current tier, next tier, and XP requirements from raw XP amount.

        Args:
            user_id: Target user ID.
            conn: Optional connection for transaction support.

        Returns:
            Dict with all tier and XP fields, or None if user does not exist.
        """
        _conn = self._get_connection(conn)
        query = """
                WITH user_xp AS (
                    SELECT coalesce(xp.amount, 0) AS xp
                    FROM core.users u
                    LEFT JOIN lootbox.xp xp ON u.id = xp.user_id
                    WHERE u.id = $1
                ), computed AS (
                    SELECT
                        xp,
                        (xp / 100) AS raw_tier,
                        ((xp / 100) % 100) AS normalized_tier,
                        ((xp / 100) / 100) AS prestige_level
                    FROM user_xp
                )
                SELECT
                    c.xp,
                    c.raw_tier,
                    c.normalized_tier,
                    c.prestige_level,
                    cm.name AS current_main_tier_name,
                    cs.name AS current_sub_tier_name,
                    cm.name || ' ' || cs.name AS current_full_tier_name,
                    nm.name AS next_main_tier_name,
                    ns.name AS next_sub_tier_name,
                    CASE
                        WHEN (c.raw_tier % 5) = 4 THEN nm.name || ' ' || ns.name
                        ELSE cm.name || ' ' || ns.name
                    END AS next_full_tier_name,
                    ((c.raw_tier + 1) * 100) - c.xp AS next_sub_tier_xp_required,
                    (c.raw_tier + 1) * 100 AS next_sub_tier_xp_total,
                    (((c.normalized_tier / 5 + 1) * 5 + c.prestige_level * 100) * 100) - c.xp
                        AS next_main_tier_xp_required,
                    ((c.normalized_tier / 5 + 1) * 5 + c.prestige_level * 100) * 100
                        AS next_main_tier_xp_total
                FROM computed c
                LEFT JOIN lootbox.main_tiers cm ON (c.normalized_tier / 5) = cm.threshold
                LEFT JOIN lootbox.sub_tiers cs ON (c.raw_tier % 5) = cs.threshold
                LEFT JOIN lootbox.main_tiers nm ON ((c.normalized_tier / 5 + 1) % 20) = nm.threshold
                LEFT JOIN lootbox.sub_tiers ns ON ((c.raw_tier + 1) % 5) = ns.threshold \
                """
        row = await _conn.fetchrow(query, user_id)
        return dict(row) if row else None

    async def update_active_key(
        self,
        key_type: LootboxKeyType,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Update the globally active key.

        Args:
            key_type: Key type to set as active.
            conn: Optional connection for transaction participation.
        """
        _conn = self._get_connection(conn)

        query = "UPDATE lootbox.active_key SET key = $1"
        await _conn.execute(query, key_type)


async def provide_lootbox_repository(state: State) -> LootboxRepository:
    """Provide LootboxRepository DI.

    Args:
        state: Application state containing the database pool.

    Returns:
        LootboxRepository: New repository instance.
    """
    return LootboxRepository(state.db_pool)
