"""Repository for notifications domain database operations."""

from __future__ import annotations

import json
from typing import Any, Literal

from asyncpg import Connection, Pool

from repository.base import BaseRepository


class NotificationsRepository(BaseRepository):
    """Repository for notifications domain."""

    def __init__(self, pool: Pool) -> None:
        """Initialize repository.

        Args:
            pool: AsyncPG connection pool.
        """
        super().__init__(pool)

    async def insert_event(
        self,
        *,
        user_id: int,
        event_type: str,
        title: str,
        body: str,
        metadata: dict[str, Any] | None,
        conn: Connection | None = None,
    ) -> int:
        """Insert a notification event and return its ID.

        Args:
            user_id: Target user ID.
            event_type: Type of notification event.
            title: Notification title.
            body: Notification body text.
            metadata: Optional JSON metadata.
            conn: Optional connection for transaction participation.

        Returns:
            ID of the newly created event.
        """
        _conn = self._get_connection(conn)
        query = """
            INSERT INTO notifications.events (user_id, event_type, title, body, metadata)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
        """
        # Convert metadata dict to JSON string for asyncpg
        metadata_json = json.dumps(metadata) if metadata is not None else None
        event_id = await _conn.fetchval(query, user_id, event_type, title, body, metadata_json)
        return event_id

    async def fetch_event_by_id(
        self,
        event_id: int,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Fetch a single notification event by ID.

        Args:
            event_id: The event ID to fetch.
            conn: Optional connection for transaction participation.

        Returns:
            Dict with event data, or None if not found.
        """
        _conn = self._get_connection(conn)
        query = """
            SELECT id, user_id, event_type, title, body, metadata,
                   created_at, read_at, dismissed_at
            FROM notifications.events
            WHERE id = $1
        """
        row = await _conn.fetchrow(query, event_id)

        if not row:
            return None

        return dict(row)

    async def fetch_user_events(
        self,
        *,
        user_id: int,
        unread_only: bool,
        limit: int,
        offset: int,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch notification events for a user's notification tray.

        Args:
            user_id: Target user ID.
            unread_only: Only return unread notifications.
            limit: Maximum number of events to return.
            offset: Number of events to skip.
            conn: Optional connection for transaction participation.

        Returns:
            List of event dicts ordered by most recent first.
        """
        _conn = self._get_connection(conn)

        query = """
            SELECT id, user_id, event_type, title, body, metadata,
                   created_at, read_at, dismissed_at
            FROM notifications.events
            WHERE user_id = $1 AND dismissed_at IS NULL
        """
        params: list[Any] = [user_id]

        if unread_only:
            query += " AND read_at IS NULL"

        query += " ORDER BY created_at DESC LIMIT $2 OFFSET $3"
        params.extend([limit, offset])

        rows = await _conn.fetch(query, *params)
        return [dict(row) for row in rows]

    async def fetch_unread_count(
        self,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> int:
        """Get count of unread notifications for a user.

        Args:
            user_id: Target user ID.
            conn: Optional connection for transaction participation.

        Returns:
            Count of unread notifications.
        """
        _conn = self._get_connection(conn)

        query = """
            SELECT COUNT(*) FROM notifications.events
            WHERE user_id = $1 AND read_at IS NULL AND dismissed_at IS NULL
        """
        count = await _conn.fetchval(query, user_id)
        return count or 0

    async def mark_event_read(
        self,
        event_id: int,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Mark a single notification as read.

        Args:
            event_id: ID of the notification event.
            conn: Optional connection for transaction participation.
        """
        _conn = self._get_connection(conn)

        query = "UPDATE notifications.events SET read_at = now() WHERE id = $1"
        await _conn.execute(query, event_id)

    async def mark_all_events_read(
        self,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> int:
        """Mark all notifications as read and return count.

        Args:
            user_id: Target user ID.
            conn: Optional connection for transaction participation.

        Returns:
            Count of notifications marked as read.
        """
        _conn = self._get_connection(conn)

        query = """
            UPDATE notifications.events
            SET read_at = now()
            WHERE user_id = $1 AND read_at IS NULL
            RETURNING id
        """
        result = await _conn.fetch(query, user_id)
        return len(result)

    async def dismiss_event(
        self,
        event_id: int,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Dismiss a notification from the tray.

        Args:
            event_id: ID of the notification event.
            conn: Optional connection for transaction participation.
        """
        _conn = self._get_connection(conn)

        query = "UPDATE notifications.events SET dismissed_at = now() WHERE id = $1"
        await _conn.execute(query, event_id)

    async def record_delivery_result(
        self,
        *,
        event_id: int,
        channel: str,
        status: Literal["delivered", "failed", "skipped"],
        error_message: str | None,
        conn: Connection | None = None,
    ) -> None:
        """Record the result of a delivery attempt.

        Args:
            event_id: ID of the notification event.
            channel: Delivery channel.
            status: Delivery status.
            error_message: Optional error message if failed.
            conn: Optional connection for transaction participation.
        """
        _conn = self._get_connection(conn)

        query = """
            INSERT INTO notifications.delivery_log
                (event_id, channel, status, attempted_at, delivered_at, error_message)
            VALUES ($1, $2, $3, now(),
                    CASE WHEN $3 = 'delivered' THEN now() END,
                    $4)
            ON CONFLICT (event_id, channel) DO UPDATE SET
                status = $3,
                delivered_at = CASE WHEN $3 = 'delivered' THEN now() END,
                error_message = $4
        """
        await _conn.execute(query, event_id, channel, status, error_message)

    async def fetch_preferences(
        self,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch all preferences for a user.

        Args:
            user_id: Target user ID.
            conn: Optional connection for transaction participation.

        Returns:
            List of preference dicts.
        """
        _conn = self._get_connection(conn)

        query = """
            SELECT event_type, channel, enabled
            FROM notifications.preferences
            WHERE user_id = $1
        """
        rows = await _conn.fetch(query, user_id)
        return [dict(row) for row in rows]

    async def upsert_preference(
        self,
        *,
        user_id: int,
        event_type: str,
        channel: str,
        enabled: bool,
        conn: Connection | None = None,
    ) -> None:
        """Update a single preference (insert or update).

        Args:
            user_id: Target user ID.
            event_type: Event type string.
            channel: Channel string.
            enabled: Whether the preference is enabled.
            conn: Optional connection for transaction participation.
        """
        _conn = self._get_connection(conn)

        query = """
            INSERT INTO notifications.preferences (user_id, event_type, channel, enabled)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id, event_type, channel)
            DO UPDATE SET enabled = $4
        """
        await _conn.execute(query, user_id, event_type, channel, enabled)
