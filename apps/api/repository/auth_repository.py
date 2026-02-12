"""Authentication repository for data access."""

from __future__ import annotations

import datetime as dt
from logging import getLogger

import asyncpg
from asyncpg import Connection, Pool  # noqa: F401
from genjishimada_sdk.auth import EmailRegisterRequest  # noqa: F401
from litestar.datastructures import State

from .base import BaseRepository
from .exceptions import (  # noqa: F401
    CheckConstraintViolationError,
    ForeignKeyViolationError,
    UniqueConstraintViolationError,
    extract_constraint_name,
)

log = getLogger(__name__)


class AuthRepository(BaseRepository):
    """Repository for authentication data access."""

    async def fetch_rate_limit_count(
        self,
        identifier: str,
        action: str,
        window_start: dt.datetime,
        *,
        conn: Connection | None = None,
    ) -> int:
        """Get rate limit attempt count for identifier and action.

        Args:
            identifier: Email or IP address.
            action: The action being rate limited.
            window_start: Start of the rate limit window.
            conn: Optional connection for transaction participation.

        Returns:
            Number of attempts in the window.
        """
        _conn = self._get_connection(conn)

        query = """
            SELECT COUNT(*) FROM users.auth_rate_limits
            WHERE identifier = LOWER($1)
              AND action = $2
              AND attempt_at > $3
        """
        count = await _conn.fetchval(query, identifier, action, window_start)
        return count or 0

    async def record_attempt(
        self,
        identifier: str,
        action: str,
        success: bool = False,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Record an authentication attempt.

        Args:
            identifier: Email or IP address.
            action: The action being attempted.
            success: Whether the attempt was successful.
            conn: Optional connection for transaction participation.
        """
        _conn = self._get_connection(conn)

        query = """
            INSERT INTO users.auth_rate_limits (identifier, action, success)
            VALUES (LOWER($1), $2, $3)
        """
        await _conn.execute(query, identifier, action, success)

    async def check_email_exists(
        self,
        email: str,
        *,
        conn: Connection | None = None,
    ) -> bool:
        """Check if an email address is already registered.

        Args:
            email: Email address to check.
            conn: Optional connection for transaction participation.

        Returns:
            True if email exists, False otherwise.
        """
        _conn = self._get_connection(conn)

        query = """
            SELECT EXISTS(
                SELECT 1 FROM users.email_auth
                WHERE LOWER(email) = LOWER($1)
            )
        """
        exists = await _conn.fetchval(query, email)
        return exists or False

    async def get_user_by_email(
        self,
        email: str,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Get user auth data by email.

        Args:
            email: Email address.
            conn: Optional connection for transaction participation.

        Returns:
            User data dict or None if not found.
        """
        _conn = self._get_connection(conn)

        query = """
            SELECT
                e.user_id,
                e.email,
                e.password_hash,
                e.email_verified_at,
                u.nickname,
                u.coins,
                u.is_mod
            FROM users.email_auth e
            JOIN core.users u ON e.user_id = u.id
            WHERE LOWER(e.email) = LOWER($1)
        """
        row = await _conn.fetchrow(query, email)
        return dict(row) if row else None

    async def generate_next_user_id(
        self,
        *,
        conn: Connection | None = None,
    ) -> int:
        """Generate next user ID from sequence.

        Args:
            conn: Optional connection for transaction participation.

        Returns:
            Next user ID.
        """
        _conn = self._get_connection(conn)
        user_id = await _conn.fetchval("SELECT nextval('users.email_user_id_seq')")
        return user_id

    async def create_core_user(
        self,
        user_id: int,
        nickname: str,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Create a user in core.users table.

        Args:
            user_id: The user ID.
            nickname: The user's nickname.
            conn: Optional connection for transaction participation.

        Raises:
            UniqueConstraintViolationError: If user_id already exists.
        """
        _conn = self._get_connection(conn)

        try:
            await _conn.execute(
                "INSERT INTO core.users (id, nickname, global_name) VALUES ($1, $2, $2)",
                user_id,
                nickname,
            )
        except asyncpg.UniqueViolationError as e:
            constraint = extract_constraint_name(e)
            raise UniqueConstraintViolationError(
                constraint_name=constraint or "unknown",
                table="core.users",
                detail=str(e),
            )

    async def create_email_auth(
        self,
        user_id: int,
        email: str,
        password_hash: str,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Create email auth record.

        Args:
            user_id: The user ID.
            email: Email address.
            password_hash: Bcrypt password hash.
            conn: Optional connection for transaction participation.

        Raises:
            UniqueConstraintViolationError: If email already exists.
            ForeignKeyViolationError: If user_id doesn't exist.
        """
        _conn = self._get_connection(conn)

        try:
            await _conn.execute(
                """
                INSERT INTO users.email_auth (user_id, email, password_hash)
                VALUES ($1, $2, $3)
                """,
                user_id,
                email,
                password_hash,
            )
        except asyncpg.UniqueViolationError as e:
            constraint = extract_constraint_name(e)
            raise UniqueConstraintViolationError(
                constraint_name=constraint or "unknown",
                table="users.email_auth",
                detail=str(e),
            )
        except asyncpg.ForeignKeyViolationError as e:
            constraint = extract_constraint_name(e)
            raise ForeignKeyViolationError(
                constraint_name=constraint or "unknown",
                table="users.email_auth",
                detail=str(e),
            )

    async def insert_email_token(
        self,
        user_id: int,
        token_hash: str,
        token_type: str,
        expires_at: dt.datetime,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Insert email verification or password reset token.

        Args:
            user_id: The user ID.
            token_hash: SHA256 hash of the token.
            token_type: Type of token ('verification' or 'password_reset').
            expires_at: Token expiration datetime.
            conn: Optional connection for transaction participation.

        Raises:
            ForeignKeyViolationError: If user_id doesn't exist.
        """
        _conn = self._get_connection(conn)

        try:
            await _conn.execute(
                """
                INSERT INTO users.email_tokens (user_id, token_hash, token_type, expires_at)
                VALUES ($1, $2, $3, $4)
                """,
                user_id,
                token_hash,
                token_type,
                expires_at,
            )
        except asyncpg.ForeignKeyViolationError as e:
            constraint = extract_constraint_name(e)
            raise ForeignKeyViolationError(
                constraint_name=constraint or "unknown",
                table="users.email_tokens",
                detail=str(e),
            )

    async def get_token_with_user(
        self,
        token_hash: str,
        token_type: str,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Get token and associated user data.

        Args:
            token_hash: SHA256 hash of the token.
            token_type: Type of token ('verification' or 'password_reset').
            conn: Optional connection for transaction participation.

        Returns:
            Token and user data dict or None if not found.
        """
        _conn = self._get_connection(conn)

        query = """
            SELECT
                t.user_id,
                t.expires_at,
                t.used_at,
                e.email,
                e.email_verified_at,
                u.nickname,
                u.coins,
                u.is_mod
            FROM users.email_tokens t
            JOIN users.email_auth e ON t.user_id = e.user_id
            JOIN core.users u ON t.user_id = u.id
            WHERE t.token_hash = $1 AND t.token_type = $2
        """
        row = await _conn.fetchrow(query, token_hash, token_type)
        return dict(row) if row else None

    async def mark_token_used(
        self,
        token_hash: str,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Mark a token as used.

        Args:
            token_hash: SHA256 hash of the token.
            conn: Optional connection for transaction participation.
        """
        _conn = self._get_connection(conn)

        await _conn.execute(
            "UPDATE users.email_tokens SET used_at = now() WHERE token_hash = $1",
            token_hash,
        )

    async def mark_email_verified(
        self,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Mark user's email as verified.

        Args:
            user_id: The user ID.
            conn: Optional connection for transaction participation.
        """
        _conn = self._get_connection(conn)

        await _conn.execute(
            "UPDATE users.email_auth SET email_verified_at = now() WHERE user_id = $1",
            user_id,
        )

    async def invalidate_user_tokens(
        self,
        user_id: int,
        token_type: str,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Invalidate all unused tokens of a type for a user.

        Args:
            user_id: The user ID.
            token_type: Type of token ('verification' or 'password_reset').
            conn: Optional connection for transaction participation.
        """
        _conn = self._get_connection(conn)

        await _conn.execute(
            """
            UPDATE users.email_tokens
            SET used_at = now()
            WHERE user_id = $1 AND token_type = $2 AND used_at IS NULL
            """,
            user_id,
            token_type,
        )

    async def update_password(
        self,
        user_id: int,
        password_hash: str,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Update user's password hash.

        Args:
            user_id: The user ID.
            password_hash: New bcrypt password hash.
            conn: Optional connection for transaction participation.
        """
        _conn = self._get_connection(conn)

        await _conn.execute(
            "UPDATE users.email_auth SET password_hash = $1 WHERE user_id = $2",
            password_hash,
            user_id,
        )

    async def read_session(
        self,
        session_id: str,
        session_lifetime_minutes: int,
        *,
        conn: Connection | None = None,
    ) -> str | None:
        """Read session payload if not expired and refresh last activity.

        Args:
            session_id: The session ID.
            session_lifetime_minutes: Session lifetime in minutes.
            conn: Optional connection for transaction participation.

        Returns:
            Session payload (base64) or None if not found/expired.
        """
        _conn = self._get_connection(conn)

        query = """
            UPDATE users.sessions
            SET last_activity = now()
            WHERE id = $1
              AND last_activity > now() - ($2 * INTERVAL '1 minute')
            RETURNING payload
        """
        return await _conn.fetchval(query, session_id, session_lifetime_minutes)

    async def write_session(  # noqa: PLR0913
        self,
        session_id: str,
        payload: str,
        user_id: int | None,
        ip_address: str | None,
        user_agent: str | None,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Create or update session.

        Args:
            session_id: The session ID.
            payload: Base64-encoded session data.
            user_id: Optional user ID if authenticated.
            ip_address: Client IP address.
            user_agent: Client user agent.
            conn: Optional connection for transaction participation.

        Raises:
            UniqueConstraintViolationError: If session_id conflicts.
        """
        _conn = self._get_connection(conn)

        try:
            await _conn.execute(
                """
                INSERT INTO users.sessions (id, user_id, payload, last_activity, ip_address, user_agent)
                VALUES ($1, $2, $3, now(), $4, $5)
                ON CONFLICT (id) DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    payload = EXCLUDED.payload,
                    last_activity = now(),
                    ip_address = EXCLUDED.ip_address,
                    user_agent = EXCLUDED.user_agent
                """,
                session_id,
                user_id,
                payload,
                ip_address,
                user_agent,
            )
        except asyncpg.UniqueViolationError as e:
            constraint = extract_constraint_name(e)
            raise UniqueConstraintViolationError(
                constraint_name=constraint or "unknown",
                table="users.sessions",
                detail=str(e),
            )

    async def delete_session(
        self,
        session_id: str,
        *,
        conn: Connection | None = None,
    ) -> bool:
        """Delete a session.

        Args:
            session_id: The session ID.
            conn: Optional connection for transaction participation.

        Returns:
            True if session was deleted, False if not found.
        """
        _conn = self._get_connection(conn)

        result = await _conn.execute(
            "DELETE FROM users.sessions WHERE id = $1",
            session_id,
        )
        return result == "DELETE 1"

    async def delete_expired_sessions(
        self,
        session_lifetime_minutes: int,
        *,
        conn: Connection | None = None,
    ) -> int:
        """Delete expired sessions (garbage collection).

        Args:
            session_lifetime_minutes: Session lifetime in minutes.
            conn: Optional connection for transaction participation.

        Returns:
            Number of sessions deleted.
        """
        _conn = self._get_connection(conn)

        result = await _conn.execute(
            f"""
            DELETE FROM users.sessions
            WHERE last_activity < now() - INTERVAL '{session_lifetime_minutes} minutes'
            """
        )
        try:
            return int(result.split()[1])
        except (IndexError, ValueError):
            return 0

    async def get_user_sessions(
        self,
        user_id: int,
        session_lifetime_minutes: int,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Get all active sessions for a user.

        Args:
            user_id: The user ID.
            session_lifetime_minutes: Session lifetime in minutes.
            conn: Optional connection for transaction participation.

        Returns:
            List of session info dicts.
        """
        _conn = self._get_connection(conn)

        query = f"""
            SELECT id, last_activity, ip_address, user_agent
            FROM users.sessions
            WHERE user_id = $1 AND last_activity > now() - INTERVAL '{session_lifetime_minutes} minutes'
            ORDER BY last_activity DESC
        """
        rows = await _conn.fetch(query, user_id)
        return [dict(row) for row in rows]

    async def delete_user_sessions(
        self,
        user_id: int,
        except_session_id: str | None = None,
        *,
        conn: Connection | None = None,
    ) -> int:
        """Delete all sessions for a user.

        Args:
            user_id: The user ID.
            except_session_id: Optional session ID to preserve.
            conn: Optional connection for transaction participation.

        Returns:
            Number of sessions deleted.
        """
        _conn = self._get_connection(conn)

        if except_session_id:
            result = await _conn.execute(
                "DELETE FROM users.sessions WHERE user_id = $1 AND id != $2",
                user_id,
                except_session_id,
            )
        else:
            result = await _conn.execute(
                "DELETE FROM users.sessions WHERE user_id = $1",
                user_id,
            )

        try:
            return int(result.split()[1])
        except (IndexError, ValueError):
            return 0

    async def create_remember_token(  # noqa: PLR0913
        self,
        user_id: int,
        token_hash: str,
        expires_at: dt.datetime,
        ip_address: str | None,
        user_agent: str | None,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Create a remember token for persistent login.

        Args:
            user_id: The user ID.
            token_hash: SHA256 hash of the token.
            expires_at: Token expiration datetime.
            ip_address: Client IP address.
            user_agent: Client user agent.
            conn: Optional connection for transaction participation.

        Raises:
            ForeignKeyViolationError: If user_id doesn't exist.
        """
        _conn = self._get_connection(conn)

        try:
            await _conn.execute(
                """
                INSERT INTO users.remember_tokens (user_id, token_hash, expires_at, ip_address, user_agent)
                VALUES ($1, $2, $3, $4, $5)
                """,
                user_id,
                token_hash,
                expires_at,
                ip_address,
                user_agent,
            )
        except asyncpg.ForeignKeyViolationError as e:
            constraint = extract_constraint_name(e)
            raise ForeignKeyViolationError(
                constraint_name=constraint or "unknown",
                table="users.remember_tokens",
                detail=str(e),
            )

    async def validate_remember_token(
        self,
        token_hash: str,
        *,
        conn: Connection | None = None,
    ) -> int | None:
        """Validate remember token and return user_id.

        Args:
            token_hash: SHA256 hash of the token.
            conn: Optional connection for transaction participation.

        Returns:
            User ID if token is valid, None otherwise.
        """
        _conn = self._get_connection(conn)

        row = await _conn.fetchrow(
            """
            SELECT user_id FROM users.remember_tokens
            WHERE token_hash = $1 AND expires_at > now()
            """,
            token_hash,
        )

        if not row:
            return None

        # Update last_used_at
        await _conn.execute(
            "UPDATE users.remember_tokens SET last_used_at = now() WHERE token_hash = $1",
            token_hash,
        )

        return row["user_id"]

    async def revoke_remember_tokens(
        self,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> int:
        """Revoke all remember tokens for a user.

        Args:
            user_id: The user ID.
            conn: Optional connection for transaction participation.

        Returns:
            Number of tokens revoked.
        """
        _conn = self._get_connection(conn)

        result = await _conn.execute(
            "DELETE FROM users.remember_tokens WHERE user_id = $1",
            user_id,
        )
        try:
            return int(result.split()[1])
        except (IndexError, ValueError):
            return 0

    async def get_auth_status(
        self,
        user_id: int,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Get email auth status for a user.

        Args:
            user_id: The user ID.
            conn: Optional connection for transaction participation.

        Returns:
            Dict with email and email_verified_at, or None if no email auth.
        """
        _conn = self._get_connection(conn)

        query = """
            SELECT email, email_verified_at FROM users.email_auth WHERE user_id = $1
        """
        row = await _conn.fetchrow(query, user_id)
        return dict(row) if row else None

    async def check_is_mod(
        self,
        session_id: str,
        *,
        conn: Connection | None = None,
    ) -> bool:
        """Check if a session belongs to a moderator.

        Args:
            session_id: The session ID.
            conn: Optional connection for transaction participation.

        Returns:
            True if session user is a moderator, False otherwise.
        """
        _conn = self._get_connection(conn)

        query = """
            SELECT u.is_mod
            FROM users.sessions s
            JOIN core.users u ON s.user_id = u.id
            WHERE s.id = $1 AND s.user_id IS NOT NULL
        """
        is_mod = await _conn.fetchval(query, session_id)
        return bool(is_mod)


async def provide_auth_repository(state: State) -> AuthRepository:
    """Litestar DI provider for AuthRepository.

    Args:
        state: Application state.

    Returns:
        AuthRepository instance.
    """
    return AuthRepository(state.db_pool)
