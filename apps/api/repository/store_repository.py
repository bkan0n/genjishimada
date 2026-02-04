"""Repository for store domain database operations."""

from __future__ import annotations

from uuid import UUID

import asyncpg
from asyncpg import Connection, Pool
from litestar.datastructures import State

from repository.base import BaseRepository
from repository.exceptions import (
    ForeignKeyViolationError,
    extract_constraint_name,
)


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
            SELECT rotation_id, item_name, item_type, key_type, rarity, price, available_until
            FROM store.rotations
            WHERE available_from <= now() AND available_until > now()
            ORDER BY rarity DESC, item_name
        """
        rows = await _conn.fetch(query)
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
            SELECT rotation_id, item_name, item_type, key_type, rarity, price, available_until
            FROM store.rotations
            WHERE item_name = $1
              AND item_type = $2
              AND key_type = $3
              AND available_from <= now()
              AND available_until > now()
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


async def provide_store_repository(state: State) -> StoreRepository:
    """Provide StoreRepository DI.

    Args:
        state: Application state containing the database pool.

    Returns:
        StoreRepository instance.
    """
    return StoreRepository(state.db_pool)
