"""Authentication repository for data access."""

from __future__ import annotations

import datetime as dt
from logging import getLogger

import asyncpg
from asyncpg import Connection, Pool  # noqa: F401
from genjishimada_sdk.auth import EmailRegisterRequest  # noqa: F401

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
