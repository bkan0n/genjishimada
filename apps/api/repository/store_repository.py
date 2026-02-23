"""Repository for store domain database operations."""

from __future__ import annotations

from uuid import UUID

import asyncpg
from asyncpg import Connection, Pool
from litestar.datastructures import State

from repository.base import BaseRepository
from repository.exceptions import ForeignKeyViolationError, extract_constraint_name


def _initial_progress(requirements: dict) -> dict:
    req_type = requirements.get("type")
    if req_type == "complete_maps":
        return {
            "current": 0,
            "target": requirements.get("count", 0),
            "completed_map_ids": [],
            "details": {},
        }
    if req_type == "earn_medals":
        return {
            "current": 0,
            "target": requirements.get("count", 0),
            "counted_map_ids": [],
            "medals": [],
        }
    if req_type == "complete_difficulty_range":
        return {
            "current": 0,
            "target": requirements.get("min_count", 0),
            "completed_map_ids": [],
        }
    if req_type in {"beat_time", "beat_rival"}:
        progress = {
            "map_id": requirements.get("map_id"),
            "target_time": requirements.get("target_time"),
            "target_type": requirements.get("target_type"),
        }
        if req_type == "beat_rival":
            progress["rival_user_id"] = requirements.get("rival_user_id")
            progress["rival_time"] = requirements.get("rival_time")
        return progress
    if req_type == "complete_map":
        return {
            "map_id": requirements.get("map_id"),
            "target": requirements.get("target"),
            "completed": False,
            "medal_earned": None,
        }
    return {"current": 0, "target": 0}


class StoreRepository(BaseRepository):
    """Repository for store domain."""

    def __init__(self, pool: Pool) -> None:
        """Initialize repository.

        Args:
            pool: AsyncPG connection pool.
        """
        super().__init__(pool)

    async def fetch_config(
        self,
        *,
        conn: Connection | None = None,
    ) -> dict:
        """Fetch store configuration.

        Args:
            conn: Optional connection for transaction support.

        Returns:
            Config dict or empty dict if not found.
        """
        _conn = self._get_connection(conn)
        query = "SELECT * FROM store.config WHERE id = 1"
        row = await _conn.fetchrow(query)
        return dict(row) if row else {}

    async def fetch_quest_config(self, *, conn: Connection | None = None) -> dict:
        """Fetch quest configuration."""
        _conn = self._get_connection(conn)
        row = await _conn.fetchrow("SELECT * FROM store.quest_config WHERE id = 1")
        return dict(row) if row else {}

    async def update_quest_config(
        self,
        updates: dict,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Update quest configuration fields."""
        if not updates:
            return
        _conn = self._get_connection(conn)
        set_clauses = []
        values: list[object] = []
        for idx, (field, value) in enumerate(updates.items(), start=1):
            set_clauses.append(f"{field} = ${idx}")
            values.append(value)
        query = f"UPDATE store.quest_config SET {', '.join(set_clauses)} WHERE id = 1"
        await _conn.execute(query, *values)

    async def fetch_current_rotation(
        self,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch current rotation items.

        Args:
            conn: Optional connection for transaction support.

        Returns:
            List of rotation item dicts.
        """
        _conn = self._get_connection(conn)
        query = """
            WITH current_rotation AS (
                SELECT rotation_id
                FROM store.rotations
                WHERE available_from <= now() AND available_until > now()
                GROUP BY rotation_id
                ORDER BY max(available_from) DESC
                LIMIT 1
            )
            SELECT r.rotation_id, r.item_name, r.item_type, r.key_type, r.rarity, r.price, r.available_until
            FROM store.rotations r
            JOIN current_rotation c ON r.rotation_id = c.rotation_id
            WHERE r.available_from <= now() AND r.available_until > now()
            ORDER BY r.rarity DESC, r.item_name
        """
        rows = await _conn.fetch(query)
        return [dict(row) for row in rows]

    async def get_rotation_window(
        self,
        rotation_id: UUID,
        *,
        conn: Connection | None = None,
    ) -> dict:
        """Get available window for a rotation.

        Args:
            rotation_id: Rotation UUID.
            conn: Optional connection for transaction support.

        Returns:
            Dict with available_from/available_until or empty dict.
        """
        _conn = self._get_connection(conn)
        row = await _conn.fetchrow(
            """
            SELECT available_from, available_until
            FROM store.quest_rotation
            WHERE rotation_id = $1 AND user_id IS NULL
            ORDER BY id
            LIMIT 1
            """,
            rotation_id,
        )
        return dict(row) if row else {}

    async def get_active_rotation(self, *, conn: Connection | None = None) -> dict:
        """Get the current quest rotation and its window."""
        _conn = self._get_connection(conn)
        config = await _conn.fetchrow(
            """
            SELECT current_rotation_id
            FROM store.quest_config
            WHERE id = 1
            """,
        )
        if not config or not config["current_rotation_id"]:
            return {}

        rotation_id = config["current_rotation_id"]
        window = await _conn.fetchrow(
            """
            SELECT available_from, available_until
            FROM store.quest_rotation
            WHERE rotation_id = $1 AND user_id IS NULL
            ORDER BY id
            LIMIT 1
            """,
            rotation_id,
        )
        data = {"rotation_id": rotation_id}
        if window:
            data.update(dict(window))
        return data

    async def has_progress_rows(
        self,
        user_id: int,
        rotation_id: UUID,
        *,
        conn: Connection | None = None,
    ) -> bool:
        """Check if user has any progress rows for a rotation."""
        _conn = self._get_connection(conn)
        exists = await _conn.fetchval(
            """
            SELECT 1
            FROM store.user_quest_progress
            WHERE user_id = $1 AND rotation_id = $2
            LIMIT 1
            """,
            user_id,
            rotation_id,
        )
        return bool(exists)

    async def get_global_quests(
        self,
        rotation_id: UUID,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch global quests for a rotation."""
        _conn = self._get_connection(conn)
        rows = await _conn.fetch(
            """
            SELECT quest_id, quest_data
            FROM store.quest_rotation
            WHERE rotation_id = $1 AND user_id IS NULL
            ORDER BY quest_id
            """,
            rotation_id,
        )
        return [{"quest_id": row["quest_id"], "quest_data": row["quest_data"]} for row in rows]

    async def get_bounty_for_user(
        self,
        rotation_id: UUID,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Fetch user's bounty quest for a rotation."""
        _conn = self._get_connection(conn)
        row = await _conn.fetchrow(
            """
            SELECT quest_data
            FROM store.quest_rotation
            WHERE rotation_id = $1 AND user_id = $2 AND quest_id IS NULL
            LIMIT 1
            """,
            rotation_id,
            user_id,
        )
        if not row:
            return None
        return {"quest_data": row["quest_data"]}

    async def insert_bounty(
        self,
        rotation_id: UUID,
        user_id: int,
        quest_data: dict,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Insert a personalized bounty into quest_rotation."""
        _conn = self._get_connection(conn)
        window = await _conn.fetchrow(
            """
            SELECT available_from, available_until
            FROM store.quest_rotation
            WHERE rotation_id = $1 AND user_id IS NULL
            ORDER BY id
            LIMIT 1
            """,
            rotation_id,
        )
        if not window:
            raise ValueError("Rotation window not found for bounty insert.")
        await _conn.execute(
            """
            INSERT INTO store.quest_rotation (
                rotation_id,
                user_id,
                quest_data,
                available_from,
                available_until
            )
            VALUES ($1, $2, $3::jsonb, $4, $5)
            ON CONFLICT DO NOTHING
            """,
            rotation_id,
            user_id,
            quest_data,
            window["available_from"],
            window["available_until"],
        )

    async def seed_global_progress(
        self,
        user_id: int,
        rotation_id: UUID,
        global_quests: list[dict],
        *,
        conn: Connection | None = None,
    ) -> None:
        """Seed progress rows for global quests."""
        _conn = self._get_connection(conn)
        records: list[tuple] = []
        for quest in global_quests:
            quest_data = quest["quest_data"]
            requirements = quest_data.get("requirements", {})
            progress = _initial_progress(requirements)
            records.append(
                (
                    user_id,
                    rotation_id,
                    quest["quest_id"],
                    quest_data,
                    progress,
                )
            )

        if not records:
            return

        await _conn.executemany(
            """
            INSERT INTO store.user_quest_progress (
                user_id,
                rotation_id,
                quest_id,
                quest_data,
                progress
            )
            VALUES ($1, $2, $3, $4::jsonb, $5::jsonb)
            ON CONFLICT DO NOTHING
            """,
            records,
        )

    async def seed_bounty_progress(
        self,
        user_id: int,
        rotation_id: UUID,
        quest_data: dict,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Seed progress row for personalized bounty."""
        _conn = self._get_connection(conn)
        requirements = quest_data.get("requirements", {})
        progress = _initial_progress(requirements)
        await _conn.execute(
            """
            INSERT INTO store.user_quest_progress (
                user_id,
                rotation_id,
                quest_data,
                progress
            )
            VALUES ($1, $2, $3::jsonb, $4::jsonb)
            ON CONFLICT DO NOTHING
            """,
            user_id,
            rotation_id,
            quest_data,
            progress,
        )

    async def get_active_user_quests(
        self,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch active quest progress rows for a user."""
        _conn = self._get_connection(conn)
        rows = await _conn.fetch(
            """
            SELECT id AS progress_id,
                   quest_id,
                   quest_data,
                   progress,
                   completed_at,
                   claimed_at
            FROM store.user_quest_progress
            WHERE user_id = $1
              AND rotation_id = (SELECT current_rotation_id FROM store.quest_config WHERE id = 1)
            ORDER BY id
            """,
            user_id,
        )
        return [dict(row) for row in rows]

    async def update_quest_progress(
        self,
        progress_id: int,
        new_progress: dict,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Update progress json for a quest row."""
        _conn = self._get_connection(conn)
        await _conn.execute(
            """
            UPDATE store.user_quest_progress
            SET progress = $2::jsonb
            WHERE id = $1
            """,
            progress_id,
            new_progress,
        )

    async def mark_quest_complete(self, progress_id: int, *, conn: Connection | None = None) -> None:
        """Mark quest as completed if not already complete."""
        _conn = self._get_connection(conn)
        await _conn.execute(
            """
            UPDATE store.user_quest_progress
            SET completed_at = now()
            WHERE id = $1 AND completed_at IS NULL
            """,
            progress_id,
        )

    async def unmark_quest_complete(self, progress_id: int, *, conn: Connection | None = None) -> None:
        """Clear quest completion if it has not been claimed."""
        _conn = self._get_connection(conn)
        await _conn.execute(
            """
            UPDATE store.user_quest_progress
            SET completed_at = NULL
            WHERE id = $1 AND claimed_at IS NULL
            """,
            progress_id,
        )

    async def fetch_quest_history(
        self,
        user_id: int,
        limit: int = 20,
        offset: int = 0,
        *,
        conn: Connection | None = None,
    ) -> tuple[int, list[dict]]:
        """Fetch completed quest history for a user."""
        _conn = self._get_connection(conn)
        total = await _conn.fetchval(
            """
            SELECT COUNT(*)
            FROM store.user_quest_progress
            WHERE user_id = $1 AND completed_at IS NOT NULL
            """,
            user_id,
        )
        rows = await _conn.fetch(
            """
            SELECT id AS progress_id,
                   quest_id,
                   quest_data,
                   progress,
                   completed_at,
                   claimed_at,
                   coins_rewarded,
                   xp_rewarded,
                   rotation_id
            FROM store.user_quest_progress
            WHERE user_id = $1 AND completed_at IS NOT NULL
            ORDER BY completed_at DESC
            LIMIT $2 OFFSET $3
            """,
            user_id,
            limit,
            offset,
        )
        return total or 0, [dict(row) for row in rows]

    async def get_user_completions(self, user_id: int, *, conn: Connection | None = None) -> list[dict]:
        """Get user's map completions for bounty generation."""
        _conn = self._get_connection(conn)
        rows = await _conn.fetch(
            """
            SELECT
                c.map_id,
                m.code,
                m.map_name,
                c.time::float AS time,
                m.difficulty,
                m.category,
                c.inserted_at
            FROM core.completions c
            JOIN core.maps m ON m.id = c.map_id
            WHERE c.user_id = $1 AND c.verified = TRUE AND c.legacy = FALSE
            ORDER BY c.inserted_at DESC
            """,
            user_id,
        )
        return [dict(row) for row in rows]

    async def get_medal_thresholds(self, map_id: int, *, conn: Connection | None = None) -> dict | None:
        """Get medal thresholds for a map."""
        _conn = self._get_connection(conn)
        row = await _conn.fetchrow(
            """
            SELECT gold, silver, bronze
            FROM maps.medals
            WHERE map_id = $1
            """,
            map_id,
        )
        return dict(row) if row else None

    async def get_percentile_target_time(
        self,
        map_id: int,
        percentile: float = 0.6,
        *,
        conn: Connection | None = None,
    ) -> float | None:
        """Get percentile target time for a map."""
        _conn = self._get_connection(conn)
        return await _conn.fetchval(
            """
            SELECT percentile_cont($2) WITHIN GROUP (ORDER BY time)
            FROM core.completions
            WHERE map_id = $1 AND verified = TRUE AND legacy = FALSE
            """,
            map_id,
            percentile,
        )

    async def get_user_skill_rank(self, user_id: int, *, conn: Connection | None = None) -> str:
        """Compute user's skill rank from verified completions."""
        _conn = self._get_connection(conn)
        row = await _conn.fetchrow(
            """
            WITH unioned_records AS (
                SELECT DISTINCT ON (map_id)
                    map_id,
                    user_id,
                    inserted_at
                FROM core.completions
                WHERE user_id = $1 AND verified = TRUE AND legacy = FALSE
                ORDER BY map_id, inserted_at DESC
            ), thresholds AS (
                SELECT * FROM (
                    VALUES ('Easy',10),
                           ('Medium', 10),
                           ('Hard', 10),
                           ('Very Hard', 10),
                           ('Extreme', 7),
                           ('Hell', 3)
                ) AS t(name, threshold)
            ), map_data AS (
                SELECT DISTINCT ON (m.id)
                    r.user_id,
                    regexp_replace(m.difficulty, '\\s*[-+]\\s*$', '', '') AS base_difficulty
                FROM unioned_records r
                LEFT JOIN core.maps m ON r.map_id = m.id
                WHERE m.official = TRUE
            ), skill_rank_data AS (
                SELECT
                    base_difficulty AS difficulty,
                    coalesce(sum(CASE WHEN base_difficulty IS NOT NULL THEN 1 ELSE 0 END), 0) AS completions,
                    coalesce(sum(CASE WHEN base_difficulty IS NOT NULL THEN 1 ELSE 0 END), 0) >= t.threshold AS rank_met
                FROM map_data md
                LEFT JOIN thresholds t ON base_difficulty=t.name
                GROUP BY base_difficulty, t.threshold
            ), first_rank AS (
                SELECT
                    difficulty,
                    CASE
                        WHEN difficulty = 'Easy' THEN 'Jumper'
                        WHEN difficulty = 'Medium' THEN 'Skilled'
                        WHEN difficulty = 'Hard' THEN 'Pro'
                        WHEN difficulty = 'Very Hard' THEN 'Master'
                        WHEN difficulty = 'Extreme' THEN 'Grandmaster'
                        WHEN difficulty = 'Hell' THEN 'God'
                    END AS rank_name,
                    row_number() OVER (
                        ORDER BY CASE difficulty
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
            )
            SELECT COALESCE((SELECT rank_name FROM first_rank WHERE rank_order = 1), 'Ninja') AS skill_rank
            """,
            user_id,
        )
        return row["skill_rank"] if row else "Ninja"

    async def find_rivals(
        self,
        user_id: int,
        skill_rank: str,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Find potential rivals with matching skill rank."""
        _conn = self._get_connection(conn)
        rows = await _conn.fetch(
            """
            WITH unioned_records AS (
                SELECT DISTINCT ON (map_id, user_id)
                    map_id,
                    user_id,
                    inserted_at
                FROM core.completions
                WHERE verified = TRUE AND legacy = FALSE
                ORDER BY map_id, user_id, inserted_at DESC
            ), thresholds AS (
                SELECT * FROM (
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
                    coalesce(
                        sum(CASE WHEN md.base_difficulty IS NOT NULL THEN 1 ELSE 0 END),
                        0
                    ) >= t.threshold AS rank_met
                FROM map_data md
                LEFT JOIN thresholds t ON base_difficulty=t.name
                GROUP BY base_difficulty, t.threshold, md.user_id
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
                        END DESC
                    ) AS rank_order
                FROM skill_rank_data
                WHERE rank_met
            ), all_users AS (
                SELECT id AS user_id FROM core.users
            ), highest_ranks AS (
                SELECT
                    u.user_id,
                    coalesce(fr.rank_name, 'Ninja') AS rank_name
                FROM all_users u
                LEFT JOIN first_rank fr ON u.user_id = fr.user_id AND fr.rank_order = 1
            )
            SELECT
                u.id AS user_id,
                coalesce(u.global_name, u.nickname, 'Unknown') AS username
            FROM core.users u
            JOIN highest_ranks hr ON u.id = hr.user_id
            WHERE u.id <> $1 AND hr.rank_name = $2
            ORDER BY random()
            LIMIT 50
            """,
            user_id,
            skill_rank,
        )
        return [dict(row) for row in rows]

    async def find_beatable_rival_map(
        self,
        user_id: int,
        rival_id: int,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Find a map where rival is 10-20% faster than user."""
        _conn = self._get_connection(conn)
        row = await _conn.fetchrow(
            """
            WITH user_times AS (
                SELECT map_id, min(time) AS user_time
                FROM core.completions
                WHERE user_id = $1 AND verified = TRUE AND legacy = FALSE
                GROUP BY map_id
            ), rival_times AS (
                SELECT map_id, min(time) AS rival_time
                FROM core.completions
                WHERE user_id = $2 AND verified = TRUE AND legacy = FALSE
                GROUP BY map_id
            )
            SELECT rt.map_id, m.code, m.map_name, rt.rival_time, ut.user_time
            FROM rival_times rt
            JOIN user_times ut ON ut.map_id = rt.map_id
            JOIN core.maps m ON m.id = rt.map_id
            WHERE rt.rival_time < ut.user_time
              AND rt.rival_time >= ut.user_time * 0.8
            ORDER BY random()
            LIMIT 1
            """,
            user_id,
            rival_id,
        )
        return dict(row) if row else None

    async def get_uncompleted_maps(self, user_id: int, *, conn: Connection | None = None) -> list[dict]:
        """Get maps user hasn't completed yet."""
        _conn = self._get_connection(conn)
        rows = await _conn.fetch(
            """
            SELECT
                m.id AS map_id,
                m.code,
                m.map_name,
                m.difficulty,
                m.category
            FROM core.maps m
            WHERE NOT EXISTS (
                SELECT 1 FROM core.completions c
                WHERE c.user_id = $1 AND c.map_id = m.id AND c.verified = TRUE AND c.legacy = FALSE
            )
            ORDER BY random()
            LIMIT 50
            """,
            user_id,
        )
        return [dict(row) for row in rows]

    async def fetch_rotation_item(
        self,
        item_name: str,
        item_type: str,
        key_type: str,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Fetch specific rotation item if it's currently active.

        Args:
            item_name: Item name.
            item_type: Item type.
            key_type: Key type.
            conn: Optional connection for transaction support.

        Returns:
            Item dict or None if not in current rotation.
        """
        _conn = self._get_connection(conn)
        query = """
            WITH current_rotation AS (
                SELECT rotation_id
                FROM store.rotations
                WHERE available_from <= now() AND available_until > now()
                GROUP BY rotation_id
                ORDER BY max(available_from) DESC
                LIMIT 1
            )
            SELECT r.rotation_id, r.item_name, r.item_type, r.key_type, r.rarity, r.price, r.available_until
            FROM store.rotations r
            JOIN current_rotation c ON r.rotation_id = c.rotation_id
            WHERE r.item_name = $1
              AND r.item_type = $2
              AND r.key_type = $3
              AND r.available_from <= now()
              AND r.available_until > now()
            LIMIT 1
        """
        row = await _conn.fetchrow(query, item_name, item_type, key_type)
        return dict(row) if row else None

    async def insert_purchase(  # noqa: PLR0913
        self,
        user_id: int,
        purchase_type: str,
        key_type: str,
        quantity: int,
        price_paid: int,
        *,
        item_name: str | None = None,
        item_type: str | None = None,
        rotation_id: UUID | None = None,
        conn: Connection | None = None,
    ) -> None:
        """Insert purchase record.

        Args:
            user_id: User ID.
            purchase_type: 'key' or 'item'.
            key_type: Key type.
            quantity: Quantity purchased.
            price_paid: Coins spent.
            item_name: Item name (for item purchases).
            item_type: Item type (for item purchases).
            rotation_id: Rotation UUID (for item purchases).
            conn: Optional connection for transaction support.

        Raises:
            ForeignKeyViolationError: If user_id or key_type doesn't exist.
        """
        _conn = self._get_connection(conn)
        query = """
            INSERT INTO store.purchases (
                user_id, purchase_type, item_name, item_type,
                key_type, quantity, price_paid, rotation_id
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        """
        try:
            await _conn.execute(
                query,
                user_id,
                purchase_type,
                item_name,
                item_type,
                key_type,
                quantity,
                price_paid,
                rotation_id,
            )
        except asyncpg.ForeignKeyViolationError as e:
            constraint = extract_constraint_name(e)
            raise ForeignKeyViolationError(
                constraint_name=constraint or "unknown",
                table="store.purchases",
                detail=str(e),
            ) from e

    async def fetch_user_purchases(
        self,
        user_id: int,
        limit: int = 50,
        offset: int = 0,
        *,
        conn: Connection | None = None,
    ) -> tuple[int, list[dict]]:
        """Fetch user's purchase history.

        Args:
            user_id: User ID.
            limit: Max results.
            offset: Result offset.
            conn: Optional connection for transaction support.

        Returns:
            Tuple of (total_count, purchases_list).
        """
        _conn = self._get_connection(conn)

        count_query = "SELECT count(*) FROM store.purchases WHERE user_id = $1"
        total = await _conn.fetchval(count_query, user_id) or 0

        query = """
            SELECT id, purchase_type, item_name, item_type, key_type,
                   quantity, price_paid, purchased_at
            FROM store.purchases
            WHERE user_id = $1
            ORDER BY purchased_at DESC
            LIMIT $2 OFFSET $3
        """
        rows = await _conn.fetch(query, user_id, limit, offset)

        return total, [dict(row) for row in rows]

    async def generate_rotation(
        self,
        item_count: int = 5,
        *,
        conn: Connection | None = None,
    ) -> dict:
        """Call database function to generate new rotation.

        Args:
            item_count: Number of items to generate.
            conn: Optional connection for transaction support.

        Returns:
            Dict with rotation_id, items_generated, available_until.
        """
        _conn = self._get_connection(conn)
        query = "SELECT * FROM store.generate_rotation($1)"
        row = await _conn.fetchrow(query, item_count)
        return dict(row) if row else {}

    async def update_config(
        self,
        *,
        rotation_period_days: int | None = None,
        active_key_type: str | None = None,
        conn: Connection | None = None,
    ) -> None:
        """Update store configuration.

        Args:
            rotation_period_days: New rotation period.
            active_key_type: New active key type.
            conn: Optional connection for transaction support.
        """
        _conn = self._get_connection(conn)

        updates = []
        params = []
        param_idx = 1

        if rotation_period_days is not None:
            updates.append(f"rotation_period_days = ${param_idx}")
            params.append(rotation_period_days)
            param_idx += 1

        if active_key_type is not None:
            updates.append(f"active_key_type = ${param_idx}")
            params.append(active_key_type)
            param_idx += 1

        if updates:
            query = f"UPDATE store.config SET {', '.join(updates)} WHERE id = 1"
            await _conn.execute(query, *params)

    async def update_quest(
        self,
        quest_id: int,
        updates: dict,
        *,
        conn: Connection | None = None,
    ) -> list[str]:
        """Update quest pool entry fields."""
        if not updates:
            return []
        _conn = self._get_connection(conn)
        set_clauses = []
        values: list[object] = []
        for idx, (field, value) in enumerate(updates.items(), start=1):
            if field == "requirements":
                set_clauses.append(f"{field} = ${idx}::jsonb")
                values.append(value)
            else:
                set_clauses.append(f"{field} = ${idx}")
                values.append(value)
        query = f"UPDATE store.quests SET {', '.join(set_clauses)} WHERE id = ${len(values) + 1}"
        values.append(quest_id)
        await _conn.execute(query, *values)
        return list(updates.keys())


async def provide_store_repository(state: State) -> StoreRepository:
    """Provide StoreRepository DI.

    Args:
        state: Application state containing the database pool.

    Returns:
        StoreRepository instance.
    """
    return StoreRepository(state.db_pool)
