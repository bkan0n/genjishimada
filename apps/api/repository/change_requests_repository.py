"""Change requests repository for data access."""

from __future__ import annotations

import asyncpg
from asyncpg import Connection
from litestar.datastructures import State

from .base import BaseRepository
from .exceptions import (
    ForeignKeyViolationError,
    UniqueConstraintViolationError,
    extract_constraint_name,
)


class ChangeRequestsRepository(BaseRepository):
    """Repository for change request data access."""

    async def fetch_creator_mentions(
        self,
        thread_id: int,
        code: str,
        *,
        conn: Connection | None = None,
    ) -> str | None:
        """Fetch creator mentions for a change request.

        Args:
            thread_id: Discord thread ID.
            code: Overwatch map code.
            conn: Optional connection for transaction participation.

        Returns:
            Comma-separated string of creator user IDs, or None if not found.
        """
        _conn = self._get_connection(conn)

        query = """
            SELECT creator_mentions FROM change_requests
            WHERE thread_id = $1 AND code = $2;
        """
        return await _conn.fetchval(query, thread_id, code)

    async def create_request(  # noqa: PLR0913
        self,
        thread_id: int,
        code: str,
        user_id: int,
        content: str,
        change_request_type: str,
        creator_mentions: str,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Create a new change request.

        Args:
            thread_id: Discord thread ID.
            code: Overwatch map code.
            user_id: User who created the request.
            content: Request description.
            change_request_type: Type of change requested.
            creator_mentions: Comma-separated creator user IDs.
            conn: Optional connection for transaction participation.

        Raises:
            ForeignKeyViolationError: If code or user_id doesn't exist.
        """
        _conn = self._get_connection(conn)

        query = """
        INSERT INTO change_requests (
            thread_id,
            code,
            user_id,
            content,
            creator_mentions,
            change_request_type
        )
        SELECT $1, $2, $3, $4, $5, $6
        FROM core.maps AS m
        WHERE m.code = $2;
        """
        try:
            await _conn.execute(
                query,
                thread_id,
                code,
                user_id,
                content,
                creator_mentions,
                change_request_type,
            )
        except asyncpg.UniqueViolationError as e:
            constraint = extract_constraint_name(e)
            raise UniqueConstraintViolationError(
                constraint_name=constraint or "unknown",
                table="change_requests",
                detail=str(e),
            )
        except asyncpg.ForeignKeyViolationError as e:
            constraint = extract_constraint_name(e)
            raise ForeignKeyViolationError(
                constraint_name=constraint or "unknown",
                table="change_requests",
                detail=str(e),
            )

    async def mark_resolved(
        self,
        thread_id: int,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Mark a change request as resolved.

        Args:
            thread_id: Discord thread ID.
            conn: Optional connection for transaction participation.
        """
        _conn = self._get_connection(conn)

        query = """
            UPDATE change_requests
            SET resolved = TRUE
            WHERE thread_id = $1;
        """
        await _conn.execute(query, thread_id)

    async def fetch_unresolved_requests(
        self,
        code: str,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch unresolved change requests for a map code.

        Args:
            code: Overwatch map code.
            conn: Optional connection for transaction participation.

        Returns:
            List of unresolved change request dicts, newest first.
        """
        _conn = self._get_connection(conn)

        query = """
            SELECT *
            FROM change_requests
            WHERE code = $1 AND resolved IS FALSE
            ORDER BY created_at DESC, resolved DESC;
        """
        rows = await _conn.fetch(query, code)
        return [dict(row) for row in rows]

    async def fetch_stale_requests(
        self,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch stale change requests (>2 weeks, not alerted, not resolved).

        Args:
            conn: Optional connection for transaction participation.

        Returns:
            List of stale change request dicts.
        """
        _conn = self._get_connection(conn)

        query = """
            SELECT thread_id, user_id, creator_mentions
            FROM change_requests
            WHERE created_at < NOW() - INTERVAL '2 weeks'
                AND alerted IS FALSE AND resolved IS FALSE;
        """
        rows = await _conn.fetch(query)
        return [dict(row) for row in rows]

    async def mark_alerted(
        self,
        thread_id: int,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Mark a change request as alerted.

        Args:
            thread_id: Discord thread ID.
            conn: Optional connection for transaction participation.
        """
        _conn = self._get_connection(conn)

        query = """
            UPDATE change_requests
            SET alerted = TRUE
            WHERE thread_id = $1;
        """
        await _conn.execute(query, thread_id)


async def provide_change_requests_repository(state: State) -> ChangeRequestsRepository:
    """Litestar DI provider for ChangeRequestsRepository.

    Args:
        state: Application state.

    Returns:
        ChangeRequestsRepository instance.
    """
    return ChangeRequestsRepository(state.db_pool)
