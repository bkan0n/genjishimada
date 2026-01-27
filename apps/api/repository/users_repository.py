"""Repository for users domain database operations."""

from __future__ import annotations

from asyncpg import Connection, Pool
from asyncpg.exceptions import UniqueViolationError

from repository.base import BaseRepository
from repository.exceptions import UniqueConstraintViolationError, extract_constraint_name


class UsersRepository(BaseRepository):
    """Repository for users domain."""

    def __init__(self, pool: Pool) -> None:
        """Initialize repository.

        Args:
            pool: AsyncPG connection pool.
        """
        super().__init__(pool)

    async def check_if_user_is_creator(
        self,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> bool:
        """Check if user is a creator.

        Args:
            user_id: The user ID to check.
            conn: Optional connection for transaction support.

        Returns:
            True if user is a creator, False otherwise.
        """
        _conn = self._get_connection(conn)
        query = "SELECT EXISTS(SELECT 1 FROM maps.creators WHERE user_id=$1);"
        return await _conn.fetchval(query, user_id)

    async def update_user_names(  # noqa: PLR0913
        self,
        user_id: int,
        *,
        nickname: str | None = None,
        global_name: str | None = None,
        update_nickname: bool = False,
        update_global_name: bool = False,
        conn: Connection | None = None,
    ) -> None:
        """Update user names.

        Args:
            user_id: The user ID to update.
            nickname: New nickname value (only used if update_nickname=True).
            global_name: New global_name value (only used if update_global_name=True).
            update_nickname: Whether to update nickname.
            update_global_name: Whether to update global_name.
            conn: Optional connection for transaction support.
        """
        _conn = self._get_connection(conn)
        query = """
            UPDATE core.users AS u
            SET
                nickname    = CASE WHEN $2 THEN $3::text ELSE u.nickname END,
                global_name = CASE WHEN $4 THEN $5::text ELSE u.global_name END
            WHERE u.id = $1
              AND (
                    ($2 AND u.nickname    IS DISTINCT FROM $3::text) OR
                    ($4 AND u.global_name IS DISTINCT FROM $5::text)
                  )
            RETURNING u.nickname, u.global_name;
        """
        await _conn.execute(query, user_id, update_nickname, nickname, update_global_name, global_name)

    async def fetch_users(
        self,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch all users with aggregated Overwatch usernames.

        Args:
            conn: Optional connection for transaction support.

        Returns:
            List of user records as dicts.
        """
        _conn = self._get_connection(conn)
        query = """
            SELECT
                u.id,
                u.nickname,
                coalesce(u.global_name, 'Unknown Username') AS global_name,
                u.coins,
                NULLIF(array_agg(owu.username), '{NULL}') AS overwatch_usernames
            FROM core.users u
            LEFT JOIN users.overwatch_usernames owu ON u.id = owu.user_id
            GROUP BY u.id, u.nickname, u.global_name, u.coins
            ;
        """
        rows = await _conn.fetch(query)
        return [dict(row) for row in rows]

    async def fetch_user(
        self,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Fetch a single user with coalesced display name.

        Args:
            user_id: The user ID.
            conn: Optional connection for transaction support.

        Returns:
            User record as dict, or None if not found.
        """
        _conn = self._get_connection(conn)
        query = """
            SELECT
                u.id,
                u.nickname,
                u.global_name,
                u.coins,
                NULLIF(array_agg(owu.username ORDER BY owu.is_primary DESC), '{NULL}') AS overwatch_usernames,
                COALESCE(
                    (array_remove(array_agg(owu.username ORDER BY owu.is_primary DESC), NULL))[1],
                    u.nickname,
                    u.global_name,
                    'Unknown User'
                ) AS coalesced_name
            FROM core.users u
            LEFT JOIN users.overwatch_usernames owu
                ON u.id = owu.user_id
            WHERE u.id = $1
            GROUP BY u.id, u.nickname, u.global_name, u.coins;
        """
        row = await _conn.fetchrow(query, user_id)
        return dict(row) if row else None

    async def check_user_exists(
        self,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> bool:
        """Check if a user exists.

        Args:
            user_id: The user ID.
            conn: Optional connection for transaction support.

        Returns:
            True if user exists, False otherwise.
        """
        _conn = self._get_connection(conn)
        query = "SELECT EXISTS(SELECT 1 FROM core.users WHERE id = $1);"
        return await _conn.fetchval(query, user_id)

    async def create_user(
        self,
        user_id: int,
        nickname: str | None,
        global_name: str | None,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Create a new user.

        Args:
            user_id: The user ID.
            nickname: User nickname.
            global_name: User global name.
            conn: Optional connection for transaction support.

        Raises:
            UniqueConstraintViolationError: If user_id already exists (users_pkey).
        """
        _conn = self._get_connection(conn)
        query = "INSERT INTO core.users (id, nickname, global_name) VALUES ($1, $2, $3);"
        try:
            await _conn.execute(query, user_id, nickname, global_name)
        except UniqueViolationError as e:
            constraint = extract_constraint_name(e)
            raise UniqueConstraintViolationError(
                constraint_name=constraint or "unknown",
                table="core.users",
                detail=e.detail,
            ) from e
