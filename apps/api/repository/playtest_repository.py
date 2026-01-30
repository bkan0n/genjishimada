"""Repository for playtest data access."""

from __future__ import annotations

from typing import Any

import asyncpg
from asyncpg import Connection
from litestar.datastructures import State

from .base import BaseRepository
from .exceptions import CheckConstraintViolationError, extract_constraint_name


class PlaytestRepository(BaseRepository):
    """Repository for playtest data access."""

    # Playtest metadata operations

    async def fetch_playtest(
        self,
        thread_id: int,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Fetch playtest metadata by thread ID.

        Args:
            thread_id: Forum thread ID.
            conn: Optional connection.

        Returns:
            Playtest row as dict, or None if not found.
        """
        _conn = self._get_connection(conn)

        row = await _conn.fetchrow(
            """
            SELECT
                me.id,
                me.thread_id,
                ma.code,
                me.verification_id,
                me.initial_difficulty,
                me.created_at,
                me.updated_at,
                me.completed
            FROM playtests.meta me
            LEFT JOIN core.maps ma ON me.map_id = ma.id
            WHERE me.thread_id = $1
            """,
            thread_id,
        )
        return dict(row) if row else None

    async def update_playtest_meta(
        self,
        thread_id: int,
        updates: dict[str, Any],
        *,
        conn: Connection | None = None,
    ) -> None:
        """Update playtest metadata fields dynamically.

        Args:
            thread_id: Forum thread ID.
            updates: Dict of field -> value to update.
            conn: Optional connection.
        """
        _conn = self._get_connection(conn)

        if not updates:
            return

        args = [thread_id, *list(updates.values())]
        set_clauses = [f"{col} = ${idx}" for idx, col in enumerate(updates.keys(), start=2)]
        query = f"UPDATE playtests.meta SET {', '.join(set_clauses)} WHERE thread_id = $1"

        await _conn.execute(query, *args)

    async def associate_thread(
        self,
        playtest_id: int,
        thread_id: int,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Associate a Discord thread with playtest metadata.

        Args:
            playtest_id: Playtest ID.
            thread_id: Discord thread ID.
            conn: Optional connection.
        """
        _conn = self._get_connection(conn)

        await _conn.execute(
            "UPDATE playtests.meta SET thread_id = $2 WHERE id = $1",
            playtest_id,
            thread_id,
        )

    # Vote operations

    async def fetch_playtest_votes(
        self,
        thread_id: int,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch all votes for a playtest with user names.

        Args:
            thread_id: Forum thread ID.
            conn: Optional connection.

        Returns:
            List of vote dicts with user info.
        """
        _conn = self._get_connection(conn)

        rows = await _conn.fetch(
            """
            SELECT
                v.difficulty,
                v.user_id,
                coalesce(
                    (
                        SELECT ou.username
                        FROM users.overwatch_usernames ou
                        WHERE ou.user_id = u.id AND ou.is_primary = TRUE
                        LIMIT 1
                    ),
                    u.nickname,
                    u.global_name,
                    'Unknown Name'
                ) AS name
            FROM playtests.votes v
            JOIN core.maps m ON m.id = v.map_id
            JOIN core.users u ON u.id = v.user_id
            WHERE v.playtest_thread_id = $1
            """,
            thread_id,
        )
        return [dict(row) for row in rows]

    async def cast_vote(
        self,
        thread_id: int,
        user_id: int,
        difficulty: float,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Cast or update a vote.

        Uses INSERT ... ON CONFLICT DO UPDATE pattern.

        Args:
            thread_id: Forum thread ID.
            user_id: Voter's user ID.
            difficulty: Difficulty value (0-10).
            conn: Optional connection.

        Raises:
            CheckConstraintViolationError: If vote fails constraint (no submission).
        """
        _conn = self._get_connection(conn)

        try:
            await _conn.execute(
                """
                WITH target_map AS (
                    SELECT map_id FROM playtests.meta WHERE thread_id = $2
                )
                INSERT INTO playtests.votes (user_id, playtest_thread_id, difficulty, map_id)
                SELECT $1, $2, $3, target_map.map_id
                FROM target_map
                ON CONFLICT (user_id, map_id, playtest_thread_id) DO UPDATE
                SET difficulty = EXCLUDED.difficulty, updated_at = now()
                """,
                user_id,
                thread_id,
                difficulty,
            )
        except asyncpg.CheckViolationError as e:
            constraint = extract_constraint_name(e)
            raise CheckConstraintViolationError(
                constraint_name=constraint or "difficulty_range",
                table="playtests.votes",
                detail=str(e),
            ) from e

    async def check_vote_exists(
        self,
        thread_id: int,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> bool:
        """Check if user has voted on playtest.

        Args:
            thread_id: Forum thread ID.
            user_id: User ID.
            conn: Optional connection.

        Returns:
            True if vote exists, False otherwise.
        """
        _conn = self._get_connection(conn)

        return await _conn.fetchval(
            """
            SELECT EXISTS(
                SELECT 1
                FROM playtests.votes
                WHERE playtest_thread_id = $1 AND user_id = $2
            )
            """,
            thread_id,
            user_id,
        )

    async def delete_vote(
        self,
        thread_id: int,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Delete a user's vote.

        Args:
            thread_id: Forum thread ID.
            user_id: User ID.
            conn: Optional connection.
        """
        _conn = self._get_connection(conn)

        await _conn.execute(
            "DELETE FROM playtests.votes WHERE playtest_thread_id = $1 AND user_id = $2",
            thread_id,
            user_id,
        )

    async def delete_all_votes(
        self,
        thread_id: int,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Delete all votes for a playtest.

        Args:
            thread_id: Forum thread ID.
            conn: Optional connection.
        """
        _conn = self._get_connection(conn)

        await _conn.execute(
            "DELETE FROM playtests.votes WHERE playtest_thread_id = $1",
            thread_id,
        )

    async def get_average_difficulty(
        self,
        thread_id: int,
        *,
        conn: Connection | None = None,
    ) -> float | None:
        """Calculate average difficulty from votes.

        Args:
            thread_id: Forum thread ID.
            conn: Optional connection.

        Returns:
            Average difficulty, or None if no votes.
        """
        _conn = self._get_connection(conn)

        return await _conn.fetchval(
            "SELECT avg(difficulty) FROM playtests.votes WHERE playtest_thread_id = $1",
            thread_id,
        )

    # Helper queries

    async def get_map_id_from_thread(
        self,
        thread_id: int,
        *,
        conn: Connection | None = None,
    ) -> int | None:
        """Get map ID from playtest thread.

        Args:
            thread_id: Forum thread ID.
            conn: Optional connection.

        Returns:
            Map ID, or None if not found.
        """
        _conn = self._get_connection(conn)

        return await _conn.fetchval(
            "SELECT map_id FROM playtests.meta WHERE thread_id = $1",
            thread_id,
        )

    async def get_primary_creator(
        self,
        map_id: int,
        *,
        conn: Connection | None = None,
    ) -> int | None:
        """Get primary creator for a map.

        Args:
            map_id: Map ID.
            conn: Optional connection.

        Returns:
            User ID of primary creator, or None.
        """
        _conn = self._get_connection(conn)

        return await _conn.fetchval(
            "SELECT user_id FROM maps.creators WHERE map_id = $1 AND is_primary = TRUE",
            map_id,
        )

    async def get_map_code(
        self,
        map_id: int,
        *,
        conn: Connection | None = None,
    ) -> str | None:
        """Get map code from map ID.

        Args:
            map_id: Map ID.
            conn: Optional connection.

        Returns:
            Map code, or None.
        """
        _conn = self._get_connection(conn)

        return await _conn.fetchval(
            "SELECT code FROM core.maps WHERE id = $1",
            map_id,
        )

    # State transition operations

    async def approve_playtest(
        self,
        map_id: int,
        thread_id: int,
        average_difficulty: float,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Approve playtest: update map and mark completed.

        Args:
            map_id: Map ID.
            thread_id: Forum thread ID.
            average_difficulty: Average difficulty from votes.
            conn: Optional connection.
        """
        _conn = self._get_connection(conn)

        await _conn.execute(
            "UPDATE core.maps SET playtesting='Approved'::playtest_status, raw_difficulty=$1 WHERE id=$2",
            average_difficulty,
            map_id,
        )
        await _conn.execute(
            "UPDATE playtests.meta SET completed=TRUE WHERE thread_id=$1",
            thread_id,
        )

    async def force_accept_playtest(
        self,
        map_id: int,
        thread_id: int,
        raw_difficulty: float,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Force accept playtest with custom difficulty.

        Args:
            map_id: Map ID.
            thread_id: Forum thread ID.
            raw_difficulty: Custom difficulty value.
            conn: Optional connection.
        """
        _conn = self._get_connection(conn)

        await _conn.execute(
            "UPDATE core.maps SET playtesting='Approved'::playtest_status, raw_difficulty=$1 WHERE id=$2",
            raw_difficulty,
            map_id,
        )
        await _conn.execute(
            "UPDATE playtests.meta SET completed=TRUE WHERE thread_id=$1",
            thread_id,
        )

    async def force_deny_playtest(
        self,
        map_id: int,
        thread_id: int,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Force deny playtest: mark rejected and hidden.

        Args:
            map_id: Map ID.
            thread_id: Forum thread ID.
            conn: Optional connection.
        """
        _conn = self._get_connection(conn)

        await _conn.execute(
            "UPDATE core.maps SET playtesting='Rejected'::playtest_status, hidden=TRUE WHERE id=$1",
            map_id,
        )
        await _conn.execute(
            "UPDATE playtests.meta SET completed=TRUE WHERE thread_id=$1",
            thread_id,
        )

    async def delete_completions_for_playtest(
        self,
        thread_id: int,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Delete all completions for a playtest.

        Deletes completions for the map that were submitted after the playtest started.

        Args:
            thread_id: Forum thread ID.
            conn: Optional connection.
        """
        _conn = self._get_connection(conn)

        await _conn.execute(
            """
            DELETE FROM core.completions
            WHERE map_id = (SELECT map_id FROM playtests.meta WHERE thread_id = $1)
              AND inserted_at >= (SELECT created_at FROM playtests.meta WHERE thread_id = $1)
            """,
            thread_id,
        )


async def provide_playtest_repository(state: State) -> PlaytestRepository:
    """Litestar DI provider for repository.

    Args:
        state: Application state.

    Returns:
        Repository instance.
    """
    return PlaytestRepository(state.db_pool)
