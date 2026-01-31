"""Repository for users domain database operations."""

from __future__ import annotations

from asyncpg import Connection, Pool
from asyncpg.exceptions import UniqueViolationError
from litestar.datastructures import State

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

    async def delete_overwatch_usernames(
        self,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Delete all Overwatch usernames for a user.

        Args:
            user_id: The user ID.
            conn: Optional connection for transaction support.
        """
        _conn = self._get_connection(conn)
        await _conn.execute("DELETE FROM users.overwatch_usernames WHERE user_id = $1", user_id)

    async def insert_overwatch_username(
        self,
        user_id: int,
        username: str,
        is_primary: bool,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Insert a single Overwatch username for a user.

        Args:
            user_id: The user ID.
            username: The Overwatch username.
            is_primary: Whether this is the primary username.
            conn: Optional connection for transaction support.
        """
        _conn = self._get_connection(conn)
        query = """
            INSERT INTO users.overwatch_usernames (user_id, username, is_primary)
            VALUES ($1, $2, $3)
        """
        await _conn.execute(query, user_id, username, is_primary)

    async def fetch_overwatch_usernames(
        self,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch Overwatch usernames for a user.

        Args:
            user_id: The user ID.
            conn: Optional connection for transaction support.

        Returns:
            List of username records as dicts (username, is_primary).
        """
        _conn = self._get_connection(conn)
        query = """
            SELECT username, is_primary
            FROM core.users u
            LEFT JOIN users.overwatch_usernames owu ON u.id = owu.user_id
            WHERE user_id = $1
            ORDER BY is_primary DESC;
        """
        rows = await _conn.fetch(query, user_id)
        return [dict(row) for row in rows]

    async def fetch_all_user_names(
        self,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> list[str]:
        """Fetch all display names for a user.

        Includes Overwatch usernames, global_name, and nickname.

        Args:
            user_id: The user ID.
            conn: Optional connection for transaction support.

        Returns:
            List of display names.
        """
        _conn = self._get_connection(conn)
        query = """
            SELECT DISTINCT name
            FROM (
                SELECT username AS name
                FROM core.users u
                LEFT JOIN users.overwatch_usernames owu ON u.id = owu.user_id
                WHERE u.id = $1 AND username IS NOT NULL

                UNION

                SELECT global_name AS name
                FROM core.users
                WHERE id = $1 AND global_name IS NOT NULL

                UNION

                SELECT nickname AS name
                FROM core.users
                WHERE id = $1 AND nickname IS NOT NULL
            ) all_names;
        """
        rows = await _conn.fetch(query, user_id)
        return [row["name"] for row in rows]

    async def fetch_user_notifications(
        self,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> int | None:
        """Fetch notification flags bitmask for a user.

        Args:
            user_id: The user ID.
            conn: Optional connection for transaction support.

        Returns:
            Bitmask value, or None if not set.
        """
        _conn = self._get_connection(conn)
        query = "SELECT flags FROM users.notification_settings WHERE user_id = $1;"
        return await _conn.fetchval(query, user_id)

    async def upsert_user_notifications(
        self,
        user_id: int,
        flags: int,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Upsert notification flags for a user.

        Args:
            user_id: The user ID.
            flags: Bitmask value.
            conn: Optional connection for transaction support.
        """
        _conn = self._get_connection(conn)
        query = """
            INSERT INTO users.notification_settings (user_id, flags) VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET flags = $2;
        """
        await _conn.execute(query, user_id, flags)

    async def create_fake_member(
        self,
        name: str,
        *,
        conn: Connection | None = None,
    ) -> int:
        """Create a fake member and return the new ID.

        Args:
            name: Display name for the fake user.
            conn: Optional connection for transaction support.

        Returns:
            The newly created fake user ID.
        """
        _conn = self._get_connection(conn)
        query = """
            WITH next_id AS (
              SELECT COALESCE(MAX(id) + 1, 1) AS id
              FROM core.users
              WHERE id < 100000000
            )
            INSERT INTO core.users (id, nickname, global_name)
            SELECT id, $1, $1
            FROM next_id
            RETURNING id;
        """
        return await _conn.fetchval(query, name)

    async def update_maps_creators_for_fake_member(
        self,
        fake_user_id: int,
        real_user_id: int,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Update maps.creators references from fake to real user.

        Args:
            fake_user_id: The placeholder user ID.
            real_user_id: The real user ID.
            conn: Optional connection for transaction support.
        """
        _conn = self._get_connection(conn)
        query = "UPDATE maps.creators SET user_id=$2 WHERE user_id=$1"
        await _conn.execute(query, fake_user_id, real_user_id)

    async def delete_user(
        self,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Delete a user.

        Args:
            user_id: The user ID to delete.
            conn: Optional connection for transaction support.
        """
        _conn = self._get_connection(conn)
        query = "DELETE FROM core.users WHERE id=$1"
        await _conn.execute(query, user_id)


async def provide_users_repository(state: State) -> UsersRepository:
    """Provide users repository.

    Args:
        state: Application state.

    Returns:
        UsersRepository instance.
    """
    return UsersRepository(pool=state.db_pool)
