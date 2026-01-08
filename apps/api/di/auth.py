"""Authentication service for email-based users."""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from asyncpg import Connection
from genjishimada_sdk.auth import (
    AuthUserResponse,
    EmailAuthStatus,
    EmailLoginRequest,
    EmailRegisterRequest,
    EmailVerifyRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
)
from litestar.datastructures import State
from litestar.status_codes import (
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_404_NOT_FOUND,
    HTTP_429_TOO_MANY_REQUESTS,
)

from utilities.errors import CustomHTTPException

from .base import BaseService

log = logging.getLogger(__name__)

VERIFICATION_TOKEN_EXPIRY_HOURS = 24
PASSWORD_RESET_TOKEN_EXPIRY_HOURS = 1
SESSION_LIFETIME_MINUTES = 120  # 2 hours, matching Laravel default
BCRYPT_ROUNDS = 12

# Rate limit configuration: (max_attempts, window_seconds)
RATE_LIMITS = {
    "register": (5, 3600),  # 5 attempts per hour
    "login": (10, 900),  # 10 attempts per 15 minutes
    "password_reset": (3, 3600),  # 3 attempts per hour
    "verification_resend": (3, 3600),  # 3 attempts per hour
}

# Password complexity requirements
PASSWORD_MIN_LENGTH = 8
PASSWORD_REQUIREMENTS = [
    (r"[a-z]", "at least one lowercase letter"),
    (r"[A-Z]", "at least one uppercase letter"),
    (r"[0-9]", "at least one number"),
    (r"[!@#$%^&*(),.?\":{}|<>_\-\[\]\\;'`~+=]", "at least one special character"),
]

# Username validation: CJK characters + Latin alphanumeric + some punctuation
# CJK Unified Ideographs: \u4e00-\u9fff
# CJK Extension A: \u3400-\u4dbf
# Hiragana: \u3040-\u309f
# Katakana: \u30a0-\u30ff
# Hangul: \uac00-\ud7af
# Latin alphanumeric + underscore, hyphen, space
USERNAME_PATTERN = re.compile(
    r"^[\u4e00-\u9fff\u3400-\u4dbf\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af"
    r"a-zA-Z0-9_\- ]+$"
)
USERNAME_MIN_LENGTH = 1
USERNAME_MAX_LENGTH = 20


class AuthService(BaseService):
    """Service for email-based authentication."""

    @staticmethod
    def validate_password(password: str) -> None:
        """Validate password meets complexity requirements.

        Args:
            password: Plaintext password to validate.

        Raises:
            CustomHTTPException: If password doesn't meet requirements.
        """
        if len(password) < PASSWORD_MIN_LENGTH:
            raise CustomHTTPException(
                detail=f"Password must be at least {PASSWORD_MIN_LENGTH} characters.",
                status_code=HTTP_400_BAD_REQUEST,
            )

        missing = []
        for pattern, description in PASSWORD_REQUIREMENTS:
            if not re.search(pattern, password):
                missing.append(description)

        if missing:
            raise CustomHTTPException(
                detail=f"Password must contain {', '.join(missing)}.",
                status_code=HTTP_400_BAD_REQUEST,
            )

    @staticmethod
    def validate_username(username: str) -> None:
        """Validate username meets requirements.

        Allows: Chinese (CJK), Japanese (Hiragana/Katakana), Korean (Hangul),
        Latin letters, numbers, underscores, hyphens, and spaces.

        Args:
            username: Username to validate.

        Raises:
            CustomHTTPException: If username is invalid.
        """
        if len(username) < USERNAME_MIN_LENGTH or len(username) > USERNAME_MAX_LENGTH:
            raise CustomHTTPException(
                detail=f"Username must be between {USERNAME_MIN_LENGTH} and {USERNAME_MAX_LENGTH} characters.",
                status_code=HTTP_400_BAD_REQUEST,
            )

        if not USERNAME_PATTERN.match(username):
            raise CustomHTTPException(
                detail="Username can only contain letters, numbers, Chinese/Japanese/Korean characters, "
                "underscores, hyphens, and spaces.",
                status_code=HTTP_400_BAD_REQUEST,
            )

        # Prevent usernames that are only whitespace
        if not username.strip():
            raise CustomHTTPException(
                detail="Username cannot be empty or only whitespace.",
                status_code=HTTP_400_BAD_REQUEST,
            )

    @staticmethod
    def validate_email(email: str) -> None:
        """Validate email format.

        Args:
            email: Email address to validate.

        Raises:
            CustomHTTPException: If email format is invalid.
        """
        # Basic but reasonable email validation
        email_pattern = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
        if not email_pattern.match(email):
            raise CustomHTTPException(
                detail="Invalid email format.",
                status_code=HTTP_400_BAD_REQUEST,
            )

    @staticmethod
    def hash_password(password: str) -> str:
        """Hash a password using bcrypt.

        Args:
            password: Plaintext password.

        Returns:
            Bcrypt hash string.
        """
        salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
        return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        """Verify a password against its hash.

        Args:
            password: Plaintext password to verify.
            password_hash: Stored bcrypt hash.

        Returns:
            True if password matches, False otherwise.
        """
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))

    @staticmethod
    def generate_token() -> tuple[str, str]:
        """Generate a secure token and its hash.

        Returns:
            Tuple of (plaintext_token, token_hash).
        """
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return token, token_hash

    @staticmethod
    def hash_token(token: str) -> str:
        """Hash a token for storage/lookup.

        Args:
            token: Plaintext token.

        Returns:
            SHA256 hash of the token.
        """
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    async def check_rate_limit(self, identifier: str, action: str) -> None:
        """Check if an action is rate-limited.

        Args:
            identifier: Email or IP address.
            action: The action being performed.

        Raises:
            CustomHTTPException: If rate limit exceeded.
        """
        if action not in RATE_LIMITS:
            return

        max_attempts, window_seconds = RATE_LIMITS[action]
        window_start = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)

        query = """
            SELECT COUNT(*) FROM users.auth_rate_limits
            WHERE identifier = LOWER($1)
              AND action = $2
              AND attempt_at > $3
        """
        count = await self._conn.fetchval(query, identifier, action, window_start)

        if count >= max_attempts:
            raise CustomHTTPException(
                detail=f"Too many {action.replace('_', ' ')} attempts. Please try again later.",
                status_code=HTTP_429_TOO_MANY_REQUESTS,
            )

    async def record_attempt(self, identifier: str, action: str, success: bool = False) -> None:
        """Record an authentication attempt.

        Args:
            identifier: Email or IP address.
            action: The action being performed.
            success: Whether the attempt was successful.
        """
        query = """
            INSERT INTO users.auth_rate_limits (identifier, action, success)
            VALUES (LOWER($1), $2, $3)
        """
        await self._conn.execute(query, identifier, action, success)

    async def register(self, data: EmailRegisterRequest, client_ip: str | None = None) -> tuple[AuthUserResponse, str]:
        """Register a new email-based user.

        Args:
            data: Registration payload.
            client_ip: Client IP for rate limiting.

        Returns:
            Tuple of (AuthUserResponse, verification_token).

        Raises:
            CustomHTTPException: If email already exists or validation fails.
        """
        identifier = data.email.lower()
        await self.check_rate_limit(identifier, "register")
        if client_ip:
            await self.check_rate_limit(client_ip, "register")

        # Validate all inputs
        self.validate_email(data.email)
        self.validate_password(data.password)
        self.validate_username(data.username)

        # Check if email already exists
        exists_query = """
            SELECT user_id FROM users.email_auth WHERE LOWER(email) = LOWER($1)
        """
        existing = await self._conn.fetchval(exists_query, data.email)
        if existing:
            await self.record_attempt(identifier, "register", success=False)
            raise CustomHTTPException(
                detail="An account with this email already exists.",
                status_code=HTTP_400_BAD_REQUEST,
            )

        async with self._conn.transaction():
            # Generate user ID from sequence
            user_id = await self._conn.fetchval("SELECT nextval('users.email_user_id_seq')")

            # Create core user
            await self._conn.execute(
                "INSERT INTO core.users (id, nickname, global_name) VALUES ($1, $2, $2)",
                user_id,
                data.username,
            )

            # Create email auth record
            password_hash = self.hash_password(data.password)
            await self._conn.execute(
                """
                INSERT INTO users.email_auth (user_id, email, password_hash)
                VALUES ($1, $2, $3)
                """,
                user_id,
                data.email,
                password_hash,
            )

            # Generate verification token
            token, token_hash = self.generate_token()
            expires_at = datetime.now(timezone.utc) + timedelta(hours=VERIFICATION_TOKEN_EXPIRY_HOURS)

            await self._conn.execute(
                """
                INSERT INTO users.email_tokens (user_id, token_hash, token_type, expires_at)
                VALUES ($1, $2, 'verification', $3)
                """,
                user_id,
                token_hash,
                expires_at,
            )

        await self.record_attempt(identifier, "register", success=True)

        return (
            AuthUserResponse(
                id=user_id,
                email=data.email,
                username=data.username,
                email_verified=False,
                coins=0,
            ),
            token,
        )

    async def verify_email(self, data: EmailVerifyRequest) -> AuthUserResponse:
        """Verify a user's email address.

        Args:
            data: Verification payload with token.

        Returns:
            AuthUserResponse for the verified user.

        Raises:
            CustomHTTPException: If token is invalid or expired.
        """
        token_hash = self.hash_token(data.token)

        query = """
            SELECT t.user_id, t.expires_at, t.used_at, e.email, u.nickname, u.coins
            FROM users.email_tokens t
            JOIN users.email_auth e ON t.user_id = e.user_id
            JOIN core.users u ON t.user_id = u.id
            WHERE t.token_hash = $1 AND t.token_type = 'verification'
        """
        row = await self._conn.fetchrow(query, token_hash)

        if not row:
            raise CustomHTTPException(
                detail="Invalid verification token.",
                status_code=HTTP_400_BAD_REQUEST,
            )

        if row["used_at"] is not None:
            raise CustomHTTPException(
                detail="This verification link has already been used.",
                status_code=HTTP_400_BAD_REQUEST,
            )

        if row["expires_at"] < datetime.now(timezone.utc):
            raise CustomHTTPException(
                detail="This verification link has expired. Please request a new one.",
                status_code=HTTP_400_BAD_REQUEST,
            )

        async with self._conn.transaction():
            # Mark token as used
            await self._conn.execute(
                "UPDATE users.email_tokens SET used_at = now() WHERE token_hash = $1",
                token_hash,
            )

            # Mark email as verified
            await self._conn.execute(
                "UPDATE users.email_auth SET email_verified_at = now() WHERE user_id = $1",
                row["user_id"],
            )

        return AuthUserResponse(
            id=row["user_id"],
            email=row["email"],
            username=row["nickname"],
            email_verified=True,
            coins=row["coins"],
        )

    async def resend_verification(self, email: str, client_ip: str | None = None) -> tuple[str, str]:
        """Resend verification email.

        Args:
            email: User's email address.
            client_ip: Client IP for rate limiting.

        Returns:
            Tuple of (verification_token, username).

        Raises:
            CustomHTTPException: If user not found or already verified.
        """
        identifier = email.lower()
        await self.check_rate_limit(identifier, "verification_resend")
        if client_ip:
            await self.check_rate_limit(client_ip, "verification_resend")

        query = """
            SELECT e.user_id, e.email_verified_at, u.nickname
            FROM users.email_auth e
            JOIN core.users u ON e.user_id = u.id
            WHERE LOWER(e.email) = LOWER($1)
        """
        row = await self._conn.fetchrow(query, email)

        if not row:
            await self.record_attempt(identifier, "verification_resend", success=False)
            raise CustomHTTPException(
                detail="No account found with this email.",
                status_code=HTTP_404_NOT_FOUND,
            )

        if row["email_verified_at"] is not None:
            raise CustomHTTPException(
                detail="Email is already verified.",
                status_code=HTTP_400_BAD_REQUEST,
            )

        # Invalidate existing verification tokens
        await self._conn.execute(
            """
            UPDATE users.email_tokens
            SET used_at = now()
            WHERE user_id = $1 AND token_type = 'verification' AND used_at IS NULL
            """,
            row["user_id"],
        )

        # Generate new token
        token, token_hash = self.generate_token()
        expires_at = datetime.now(timezone.utc) + timedelta(hours=VERIFICATION_TOKEN_EXPIRY_HOURS)

        await self._conn.execute(
            """
            INSERT INTO users.email_tokens (user_id, token_hash, token_type, expires_at)
            VALUES ($1, $2, 'verification', $3)
            """,
            row["user_id"],
            token_hash,
            expires_at,
        )

        await self.record_attempt(identifier, "verification_resend", success=True)
        return token, row["nickname"]

    async def login(self, data: EmailLoginRequest, client_ip: str | None = None) -> AuthUserResponse:
        """Authenticate a user with email and password.

        Args:
            data: Login payload.
            client_ip: Client IP for rate limiting.

        Returns:
            AuthUserResponse for the authenticated user.

        Raises:
            CustomHTTPException: If credentials are invalid.
        """
        identifier = data.email.lower()
        await self.check_rate_limit(identifier, "login")
        if client_ip:
            await self.check_rate_limit(client_ip, "login")

        query = """
            SELECT e.user_id, e.email, e.password_hash, e.email_verified_at,
                   u.nickname, u.coins
            FROM users.email_auth e
            JOIN core.users u ON e.user_id = u.id
            WHERE LOWER(e.email) = LOWER($1)
        """
        row = await self._conn.fetchrow(query, data.email)

        if not row:
            await self.record_attempt(identifier, "login", success=False)
            raise CustomHTTPException(
                detail="Invalid email or password.",
                status_code=HTTP_401_UNAUTHORIZED,
            )

        if not self.verify_password(data.password, row["password_hash"]):
            await self.record_attempt(identifier, "login", success=False)
            raise CustomHTTPException(
                detail="Invalid email or password.",
                status_code=HTTP_401_UNAUTHORIZED,
            )

        await self.record_attempt(identifier, "login", success=True)

        return AuthUserResponse(
            id=row["user_id"],
            email=row["email"],
            username=row["nickname"],
            email_verified=row["email_verified_at"] is not None,
            coins=row["coins"],
        )

    async def request_password_reset(
        self, data: PasswordResetRequest, client_ip: str | None = None
    ) -> tuple[str, str] | None:
        """Request a password reset.

        Args:
            data: Password reset request payload.
            client_ip: Client IP for rate limiting.

        Returns:
            Tuple of (reset_token, username) if user exists, None otherwise.
        """
        identifier = data.email.lower()
        await self.check_rate_limit(identifier, "password_reset")
        if client_ip:
            await self.check_rate_limit(client_ip, "password_reset")

        query = """
            SELECT e.user_id, u.nickname
            FROM users.email_auth e
            JOIN core.users u ON e.user_id = u.id
            WHERE LOWER(e.email) = LOWER($1)
        """
        row = await self._conn.fetchrow(query, data.email)

        await self.record_attempt(identifier, "password_reset", success=row is not None)

        if not row:
            # Don't reveal whether email exists
            return None

        # Invalidate existing reset tokens
        await self._conn.execute(
            """
            UPDATE users.email_tokens
            SET used_at = now()
            WHERE user_id = $1 AND token_type = 'password_reset' AND used_at IS NULL
            """,
            row["user_id"],
        )

        # Generate new token
        token, token_hash = self.generate_token()
        expires_at = datetime.now(timezone.utc) + timedelta(hours=PASSWORD_RESET_TOKEN_EXPIRY_HOURS)

        await self._conn.execute(
            """
            INSERT INTO users.email_tokens (user_id, token_hash, token_type, expires_at)
            VALUES ($1, $2, 'password_reset', $3)
            """,
            row["user_id"],
            token_hash,
            expires_at,
        )

        return token, row["nickname"]

    async def reset_password(self, data: PasswordResetConfirmRequest) -> AuthUserResponse:
        """Reset a user's password.

        Args:
            data: Password reset confirmation payload.

        Returns:
            AuthUserResponse for the user.

        Raises:
            CustomHTTPException: If token is invalid or expired.
        """
        self.validate_password(data.password)

        token_hash = self.hash_token(data.token)

        query = """
            SELECT t.user_id, t.expires_at, t.used_at, e.email, u.nickname, u.coins, e.email_verified_at
            FROM users.email_tokens t
            JOIN users.email_auth e ON t.user_id = e.user_id
            JOIN core.users u ON t.user_id = u.id
            WHERE t.token_hash = $1 AND t.token_type = 'password_reset'
        """
        row = await self._conn.fetchrow(query, token_hash)

        if not row:
            raise CustomHTTPException(
                detail="Invalid password reset token.",
                status_code=HTTP_400_BAD_REQUEST,
            )

        if row["used_at"] is not None:
            raise CustomHTTPException(
                detail="This reset link has already been used.",
                status_code=HTTP_400_BAD_REQUEST,
            )

        if row["expires_at"] < datetime.now(timezone.utc):
            raise CustomHTTPException(
                detail="This reset link has expired. Please request a new one.",
                status_code=HTTP_400_BAD_REQUEST,
            )

        password_hash = self.hash_password(data.password)

        async with self._conn.transaction():
            # Mark token as used
            await self._conn.execute(
                "UPDATE users.email_tokens SET used_at = now() WHERE token_hash = $1",
                token_hash,
            )

            # Update password
            await self._conn.execute(
                "UPDATE users.email_auth SET password_hash = $1 WHERE user_id = $2",
                password_hash,
                row["user_id"],
            )

        return AuthUserResponse(
            id=row["user_id"],
            email=row["email"],
            username=row["nickname"],
            email_verified=row["email_verified_at"] is not None,
            coins=row["coins"],
        )

    async def get_auth_status(self, user_id: int) -> EmailAuthStatus | None:
        """Get email authentication status for a user.

        Args:
            user_id: The user ID.

        Returns:
            EmailAuthStatus if user has email auth, None otherwise.
        """
        query = """
            SELECT email, email_verified_at FROM users.email_auth WHERE user_id = $1
        """
        row = await self._conn.fetchrow(query, user_id)

        if not row:
            return None

        # Mask email for privacy
        email = row["email"]
        local, domain = email.split("@")
        masked_local = local[0] + "***" if len(local) > 1 else "***"
        masked_email = f"{masked_local}@{domain}"

        return EmailAuthStatus(
            email_verified=row["email_verified_at"] is not None,
            email=masked_email,
        )

    async def session_read(self, session_id: str) -> str | None:
        """Read session data by ID.

        Args:
            session_id: The session ID.

        Returns:
            Session payload (base64 encoded) or None if not found/expired.
        """
        query = f"""
            SELECT payload FROM users.sessions
            WHERE id = $1 AND last_activity > now() - INTERVAL '{SESSION_LIFETIME_MINUTES} minutes'
        """
        return await self._conn.fetchval(query, session_id)

    async def session_write(
        self,
        session_id: str,
        payload: str,
        user_id: int | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Write session data.

        Args:
            session_id: The session ID.
            payload: Base64-encoded session data.
            user_id: Optional user ID if authenticated.
            ip_address: Client IP address.
            user_agent: Client user agent.
        """
        query = """
            INSERT INTO users.sessions (id, user_id, payload, last_activity, ip_address, user_agent)
            VALUES ($1, $2, $3, now(), $4, $5)
            ON CONFLICT (id) DO UPDATE SET
                user_id = EXCLUDED.user_id,
                payload = EXCLUDED.payload,
                last_activity = now(),
                ip_address = EXCLUDED.ip_address,
                user_agent = EXCLUDED.user_agent
        """
        await self._conn.execute(query, session_id, user_id, payload, ip_address, user_agent)

    async def session_destroy(self, session_id: str) -> bool:
        """Destroy a session.

        Args:
            session_id: The session ID to destroy.

        Returns:
            True if session was deleted, False if not found.
        """
        result = await self._conn.execute(
            "DELETE FROM users.sessions WHERE id = $1",
            session_id,
        )
        return result == "DELETE 1"

    async def session_gc(self) -> int:
        """Garbage collect expired sessions.

        Returns:
            Number of sessions deleted.
        """
        result = await self._conn.execute(
            f"""
            DELETE FROM users.sessions
            WHERE last_activity < now() - INTERVAL '{SESSION_LIFETIME_MINUTES} minutes'
            """
        )
        # Parse "DELETE X" to get count
        try:
            return int(result.split()[1])
        except (IndexError, ValueError):
            return 0

    async def session_get_user_sessions(self, user_id: int) -> list[dict]:
        """Get all active sessions for a user.

        Args:
            user_id: The user ID.

        Returns:
            List of session info dicts.
        """
        query = f"""
            SELECT id, last_activity, ip_address, user_agent
            FROM users.sessions
            WHERE user_id = $1 AND last_activity > now() - INTERVAL '{SESSION_LIFETIME_MINUTES} minutes'
            ORDER BY last_activity DESC
        """
        rows = await self._conn.fetch(query, user_id)
        return [
            {
                "id": row["id"],
                "last_activity": row["last_activity"].isoformat() if row["last_activity"] else None,
                "ip_address": row["ip_address"],
                "user_agent": row["user_agent"],
            }
            for row in rows
        ]

    async def session_destroy_all_for_user(self, user_id: int, except_session_id: str | None = None) -> int:
        """Destroy all sessions for a user (logout everywhere).

        Args:
            user_id: The user ID.
            except_session_id: Optional session ID to keep (current session).

        Returns:
            Number of sessions destroyed.
        """
        if except_session_id:
            result = await self._conn.execute(
                "DELETE FROM users.sessions WHERE user_id = $1 AND id != $2",
                user_id,
                except_session_id,
            )
        else:
            result = await self._conn.execute(
                "DELETE FROM users.sessions WHERE user_id = $1",
                user_id,
            )

        try:
            return int(result.split()[1])
        except (IndexError, ValueError):
            return 0


async def provide_auth_service(conn: Connection, state: State) -> AuthService:
    """Litestar DI provider for AuthService.

    Args:
        conn: Active asyncpg connection.
        state: Application state.

    Returns:
        AuthService instance.
    """
    return AuthService(conn, state)
