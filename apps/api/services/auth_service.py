"""Authentication service for business logic."""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from asyncpg import Pool
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

from repository.auth_repository import AuthRepository
from repository.exceptions import (
    ForeignKeyViolationError,
    UniqueConstraintViolationError,
)

from .base import BaseService
from .exceptions.auth import (
    EmailAlreadyExistsError,
    EmailAlreadyVerifiedError,
    EmailValidationError,
    InvalidCredentialsError,
    PasswordValidationError,
    RateLimitExceededError,
    TokenAlreadyUsedError,
    TokenExpiredError,
    TokenInvalidError,
    UsernameValidationError,
    UserNotFoundError,
)

log = logging.getLogger(__name__)

# Constants
VERIFICATION_TOKEN_EXPIRY_HOURS = 24
PASSWORD_RESET_TOKEN_EXPIRY_HOURS = 1
SESSION_LIFETIME_MINUTES = 120
BCRYPT_ROUNDS = 12
REMEMBER_TOKEN_LIFETIME_DAYS = 30

RATE_LIMITS = {
    "register": (5, 3600),
    "login": (10, 900),
    "password_reset": (3, 3600),
    "verification_resend": (3, 3600),
}

PASSWORD_MIN_LENGTH = 8
PASSWORD_REQUIREMENTS = [
    (r"[a-z]", "at least one lowercase letter"),
    (r"[A-Z]", "at least one uppercase letter"),
    (r"[0-9]", "at least one number"),
    (r"[!@#$%^&*(),.?\":{}|<>_\-\[\]\\;'`~+=]", "at least one special character"),
]

USERNAME_PATTERN = re.compile(
    r"^[\u4e00-\u9fff\u3400-\u4dbf\u3040-\u309f\u30a0-\u30ff\uac00-\ud7af"
    r"a-zA-Z0-9_\- ]+$"
)
USERNAME_MIN_LENGTH = 1
USERNAME_MAX_LENGTH = 20

# Constraint mappings for repository exception translation
UNIQUE_CONSTRAINT_MESSAGES = {
    "email_auth_email_key": "An account with this email already exists.",
    "sessions_pkey": "Session already exists.",
    "sessions_token_key": "Session token already exists.",
    "api_keys_pkey": "API key already exists.",
}

FK_CONSTRAINT_MESSAGES = {
    "sessions_user_id_fkey": "User does not exist.",
    "api_keys_user_id_fkey": "User does not exist.",
}


class AuthService(BaseService):
    """Service for authentication business logic."""

    def __init__(self, pool: Pool, state: State, auth_repo: AuthRepository) -> None:
        """Initialize auth service.

        Args:
            pool: AsyncPG connection pool.
            state: Application state.
            auth_repo: Authentication repository.
        """
        super().__init__(pool, state)
        self._auth_repo = auth_repo

    # ===== Validation Methods =====

    @staticmethod
    def validate_email(email: str) -> None:
        """Validate email format.

        Args:
            email: Email address to validate.

        Raises:
            EmailValidationError: If email format is invalid.
        """
        email_pattern = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
        if not email_pattern.match(email):
            raise EmailValidationError()

    @staticmethod
    def validate_password(password: str) -> None:
        """Validate password meets complexity requirements.

        Args:
            password: Plaintext password to validate.

        Raises:
            PasswordValidationError: If password doesn't meet requirements.
        """
        if len(password) < PASSWORD_MIN_LENGTH:
            raise PasswordValidationError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters.")

        missing = []
        for pattern, description in PASSWORD_REQUIREMENTS:
            if not re.search(pattern, password):
                missing.append(description)

        if missing:
            raise PasswordValidationError(f"Password must contain {', '.join(missing)}.")

    @staticmethod
    def validate_username(username: str) -> None:
        """Validate username meets requirements.

        Args:
            username: Username to validate.

        Raises:
            UsernameValidationError: If username is invalid.
        """
        if len(username) < USERNAME_MIN_LENGTH or len(username) > USERNAME_MAX_LENGTH:
            raise UsernameValidationError(
                f"Username must be between {USERNAME_MIN_LENGTH} and {USERNAME_MAX_LENGTH} characters."
            )

        if not USERNAME_PATTERN.match(username):
            raise UsernameValidationError(
                "Username can only contain letters, numbers, Chinese/Japanese/Korean characters, "
                "underscores, hyphens, and spaces."
            )

        if not username.strip():
            raise UsernameValidationError("Username cannot be empty or only whitespace.")

    # ===== Cryptographic Helpers =====

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

    # ===== Rate Limiting =====

    async def check_rate_limit(self, identifier: str, action: str) -> None:
        """Check if an action is rate-limited.

        Args:
            identifier: Email or IP address.
            action: The action being performed.

        Raises:
            RateLimitExceededError: If rate limit exceeded.
        """
        if action not in RATE_LIMITS:
            return

        max_attempts, window_seconds = RATE_LIMITS[action]
        window_start = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)

        count = await self._auth_repo.fetch_rate_limit_count(identifier, action, window_start)

        if count >= max_attempts:
            raise RateLimitExceededError(action)

    # ===== Registration =====

    async def register(
        self,
        data: EmailRegisterRequest,
        client_ip: str | None = None,
    ) -> tuple[AuthUserResponse, str]:
        """Register a new email-based user.

        Args:
            data: Registration payload.
            client_ip: Client IP for rate limiting.

        Returns:
            Tuple of (AuthUserResponse, verification_token).

        Raises:
            EmailValidationError: If email format is invalid.
            PasswordValidationError: If password doesn't meet requirements.
            UsernameValidationError: If username is invalid.
            EmailAlreadyExistsError: If email is already registered.
            RateLimitExceededError: If rate limit exceeded.
        """
        identifier = data.email.lower()

        # Rate limiting
        await self.check_rate_limit(identifier, "register")
        if client_ip:
            await self.check_rate_limit(client_ip, "register")

        # Validation
        self.validate_email(data.email)
        self.validate_password(data.password)
        self.validate_username(data.username)

        # Check if email exists
        if await self._auth_repo.check_email_exists(data.email):
            await self._auth_repo.record_attempt(identifier, "register", success=False)
            raise EmailAlreadyExistsError(data.email)

        # Pre-compute hashes and tokens
        password_hash = self.hash_password(data.password)
        token, token_hash = self.generate_token()
        expires_at = datetime.now(timezone.utc) + timedelta(hours=VERIFICATION_TOKEN_EXPIRY_HOURS)

        # Transactional user creation
        async with self._pool.acquire() as conn, conn.transaction():
            try:
                user_id = await self._auth_repo.generate_next_user_id(conn=conn)  # type: ignore[arg-type]
                await self._auth_repo.create_core_user(user_id, data.username, conn=conn)  # type: ignore[arg-type]
                await self._auth_repo.create_email_auth(user_id, data.email, password_hash, conn=conn)  # type: ignore[arg-type]
                await self._auth_repo.insert_email_token(user_id, token_hash, "verification", expires_at, conn=conn)  # type: ignore[arg-type]
            except UniqueConstraintViolationError as e:
                # Translate repository exception to domain exception
                log.warning(f"Unique constraint violation during registration: {e.constraint_name}")
                raise EmailAlreadyExistsError(data.email) from e
            except ForeignKeyViolationError as e:
                log.error(f"Foreign key violation during registration: {e.constraint_name}")
                raise EmailAlreadyExistsError(data.email) from e

        # Record successful attempt
        await self._auth_repo.record_attempt(identifier, "register", success=True)

        return (
            AuthUserResponse(
                id=user_id,
                email=data.email,
                username=data.username,
                email_verified=False,
                coins=0,
                is_mod=False,
            ),
            token,
        )

    # ===== Login =====

    async def login(
        self,
        data: EmailLoginRequest,
        client_ip: str | None = None,
    ) -> AuthUserResponse:
        """Authenticate user with email and password.

        Args:
            data: Login payload.
            client_ip: Client IP for rate limiting.

        Returns:
            AuthUserResponse with user data.

        Raises:
            InvalidCredentialsError: If credentials are invalid.
            RateLimitExceededError: If rate limit exceeded.
        """
        identifier = data.email.lower()

        # Rate limiting
        await self.check_rate_limit(identifier, "login")
        if client_ip:
            await self.check_rate_limit(client_ip, "login")

        # Fetch user
        user_data = await self._auth_repo.get_user_by_email(data.email)
        if not user_data:
            await self._auth_repo.record_attempt(identifier, "login", success=False)
            raise InvalidCredentialsError(identifier)

        # Verify password
        if not self.verify_password(data.password, user_data["password_hash"]):
            await self._auth_repo.record_attempt(identifier, "login", success=False)
            raise InvalidCredentialsError(identifier)

        # Record success
        await self._auth_repo.record_attempt(identifier, "login", success=True)

        return AuthUserResponse(
            id=user_data["user_id"],
            email=user_data["email"],
            username=user_data["nickname"],
            email_verified=user_data["email_verified_at"] is not None,
            coins=user_data["coins"],
            is_mod=user_data["is_mod"],
        )

    # ===== Email Verification =====

    async def verify_email(self, data: EmailVerifyRequest) -> AuthUserResponse:
        """Verify user's email address.

        Args:
            data: Email verification payload with token.

        Returns:
            AuthUserResponse with updated verification status.

        Raises:
            TokenInvalidError: If token is not found.
            TokenExpiredError: If token has expired.
            TokenAlreadyUsedError: If token has already been used.
            EmailAlreadyVerifiedError: If email is already verified.
        """
        token_hash = self.hash_token(data.token)
        token_data = await self._auth_repo.get_token_with_user(token_hash, "verification")

        if not token_data:
            raise TokenInvalidError("verification")

        # Check if already used
        if token_data["used_at"] is not None:
            raise TokenAlreadyUsedError("verification")

        # Check if expired
        if token_data["expires_at"] < datetime.now(timezone.utc):
            raise TokenExpiredError("verification")

        # Check if already verified
        if token_data["email_verified_at"] is not None:
            raise EmailAlreadyVerifiedError()

        # Transactional verification
        async with self._pool.acquire() as conn, conn.transaction():
            await self._auth_repo.mark_token_used(token_hash, conn=conn)  # type: ignore[arg-type]
            await self._auth_repo.mark_email_verified(token_data["user_id"], conn=conn)  # type: ignore[arg-type]
            # Invalidate any other verification tokens
            await self._auth_repo.invalidate_user_tokens(token_data["user_id"], "verification", conn=conn)  # type: ignore[arg-type]

        return AuthUserResponse(
            id=token_data["user_id"],
            email=token_data["email"],
            username=token_data["nickname"],
            email_verified=True,
            coins=token_data["coins"],
            is_mod=token_data["is_mod"],
        )

    async def resend_verification(self, email: str, client_ip: str | None = None) -> tuple[str, str]:
        """Resend email verification token.

        Args:
            email: User's email address.
            client_ip: Client IP for rate limiting.

        Returns:
            Tuple of (verification_token, username).

        Raises:
            UserNotFoundError: If no user with this email exists.
            EmailAlreadyVerifiedError: If email is already verified.
            RateLimitExceededError: If rate limit exceeded.
        """
        identifier = email.lower()

        # Rate limiting
        await self.check_rate_limit(identifier, "verification_resend")
        if client_ip:
            await self.check_rate_limit(client_ip, "verification_resend")

        # Fetch user
        user_data = await self._auth_repo.get_user_by_email(email)
        if not user_data:
            raise UserNotFoundError(email)

        # Check if already verified
        if user_data["email_verified_at"] is not None:
            raise EmailAlreadyVerifiedError()

        # Generate new token
        token, token_hash = self.generate_token()
        expires_at = datetime.now(timezone.utc) + timedelta(hours=VERIFICATION_TOKEN_EXPIRY_HOURS)

        # Transactional token creation
        async with self._pool.acquire() as conn, conn.transaction():
            # Invalidate old tokens
            await self._auth_repo.invalidate_user_tokens(user_data["user_id"], "verification", conn=conn)  # type: ignore[arg-type]
            # Create new token
            await self._auth_repo.insert_email_token(
                user_data["user_id"],
                token_hash,
                "verification",
                expires_at,
                conn=conn,  # type: ignore[arg-type]
            )

        # Record attempt
        await self._auth_repo.record_attempt(identifier, "verification_resend", success=True)

        return token, user_data["nickname"]

    # ===== Password Reset =====

    async def request_password_reset(
        self, data: PasswordResetRequest, client_ip: str | None = None
    ) -> tuple[str, str] | None:
        """Request a password reset token.

        Args:
            data: Password reset request with email.
            client_ip: Client IP for rate limiting.

        Returns:
            Tuple of (password_reset_token, username) if user exists, None otherwise (for security).

        Raises:
            RateLimitExceededError: If rate limit exceeded.
        """
        identifier = data.email.lower()

        # Rate limiting
        await self.check_rate_limit(identifier, "password_reset")
        if client_ip:
            await self.check_rate_limit(client_ip, "password_reset")

        # Fetch user (silently fail if not found)
        user_data = await self._auth_repo.get_user_by_email(data.email)
        if not user_data:
            # Still record the attempt to prevent enumeration timing attacks
            await self._auth_repo.record_attempt(identifier, "password_reset", success=False)
            return None

        # Generate token
        token, token_hash = self.generate_token()
        expires_at = datetime.now(timezone.utc) + timedelta(hours=PASSWORD_RESET_TOKEN_EXPIRY_HOURS)

        # Transactional token creation
        async with self._pool.acquire() as conn, conn.transaction():
            # Invalidate old tokens
            await self._auth_repo.invalidate_user_tokens(user_data["user_id"], "password_reset", conn=conn)  # type: ignore[arg-type]
            # Create new token
            await self._auth_repo.insert_email_token(
                user_data["user_id"],
                token_hash,
                "password_reset",
                expires_at,
                conn=conn,  # type: ignore[arg-type]
            )

        # Record attempt
        await self._auth_repo.record_attempt(identifier, "password_reset", success=True)

        return token, user_data["nickname"]

    async def confirm_password_reset(self, data: PasswordResetConfirmRequest) -> AuthUserResponse:
        """Confirm password reset and set new password.

        Args:
            data: Password reset confirmation with token and new password.

        Returns:
            AuthUserResponse after password reset.

        Raises:
            TokenInvalidError: If token is not found.
            TokenExpiredError: If token has expired.
            TokenAlreadyUsedError: If token has already been used.
            PasswordValidationError: If new password doesn't meet requirements.
        """
        # Validate new password
        self.validate_password(data.password)

        token_hash = self.hash_token(data.token)
        token_data = await self._auth_repo.get_token_with_user(token_hash, "password_reset")

        if not token_data:
            raise TokenInvalidError("password_reset")

        # Check if already used
        if token_data["used_at"] is not None:
            raise TokenAlreadyUsedError("password_reset")

        # Check if expired
        if token_data["expires_at"] < datetime.now(timezone.utc):
            raise TokenExpiredError("password_reset")

        # Hash new password
        password_hash = self.hash_password(data.password)

        # Transactional password update
        async with self._pool.acquire() as conn, conn.transaction():
            await self._auth_repo.mark_token_used(token_hash, conn=conn)  # type: ignore[arg-type]
            await self._auth_repo.update_password(token_data["user_id"], password_hash, conn=conn)  # type: ignore[arg-type]
            # Invalidate any other password reset tokens
            await self._auth_repo.invalidate_user_tokens(token_data["user_id"], "password_reset", conn=conn)  # type: ignore[arg-type]
            # Revoke all remember tokens for security
            await self._auth_repo.revoke_remember_tokens(token_data["user_id"], conn=conn)  # type: ignore[arg-type]

        return AuthUserResponse(
            id=token_data["user_id"],
            email=token_data["email"],
            username=token_data["nickname"],
            email_verified=token_data["email_verified_at"] is not None,
            coins=token_data["coins"],
            is_mod=token_data["is_mod"],
        )

    # ===== Session Management =====

    async def session_read(self, session_id: str) -> str | None:
        """Read session payload.

        Args:
            session_id: The session ID.

        Returns:
            Base64-encoded session payload or None if not found.
        """
        return await self._auth_repo.read_session(session_id, SESSION_LIFETIME_MINUTES)

    async def session_write(
        self,
        session_id: str,
        payload: str,
        user_id: int | None,
        ip_address: str | None,
        user_agent: str | None,
    ) -> None:
        """Write session data.

        Args:
            session_id: The session ID.
            payload: Base64-encoded session data.
            user_id: Optional authenticated user ID.
            ip_address: Client IP address.
            user_agent: Client user agent.
        """
        await self._auth_repo.write_session(session_id, payload, user_id, ip_address, user_agent)

    async def session_destroy(self, session_id: str) -> bool:
        """Destroy a session.

        Args:
            session_id: The session ID.

        Returns:
            True if session was deleted, False if not found.
        """
        return await self._auth_repo.delete_session(session_id)

    async def session_gc(self) -> int:
        """Garbage collect expired sessions.

        Returns:
            Number of sessions deleted.
        """
        return await self._auth_repo.delete_expired_sessions(SESSION_LIFETIME_MINUTES)

    async def session_get_user_sessions(self, user_id: int) -> list[dict]:
        """Get all active sessions for a user.

        Args:
            user_id: The user ID.

        Returns:
            List of session info dicts.
        """
        return await self._auth_repo.get_user_sessions(user_id, SESSION_LIFETIME_MINUTES)

    async def session_destroy_all_for_user(self, user_id: int, except_session_id: str | None = None) -> int:
        """Destroy all sessions for a user.

        Args:
            user_id: The user ID.
            except_session_id: Optional session ID to preserve.

        Returns:
            Number of sessions destroyed.
        """
        return await self._auth_repo.delete_user_sessions(user_id, except_session_id)

    async def check_if_mod(self, session_id: str) -> bool:
        """Check if a session belongs to a moderator.

        Args:
            session_id: The session ID.

        Returns:
            True if session user is a moderator, False otherwise.
        """
        return await self._auth_repo.check_is_mod(session_id)

    # ===== Remember Token Management =====

    async def create_remember_token(
        self,
        user_id: int,
        ip_address: str | None,
        user_agent: str | None,
    ) -> str:
        """Create a remember token for persistent login.

        Args:
            user_id: The user ID.
            ip_address: Client IP address.
            user_agent: Client user agent.

        Returns:
            The plaintext remember token.
        """
        token, token_hash = self.generate_token()
        expires_at = datetime.now(timezone.utc) + timedelta(days=REMEMBER_TOKEN_LIFETIME_DAYS)

        await self._auth_repo.create_remember_token(
            user_id,
            token_hash,
            expires_at,
            ip_address,
            user_agent,
        )

        return token

    async def validate_remember_token(self, token: str) -> int | None:
        """Validate a remember token and return user ID.

        Args:
            token: The plaintext remember token.

        Returns:
            User ID if token is valid, None otherwise.
        """
        token_hash = self.hash_token(token)
        return await self._auth_repo.validate_remember_token(token_hash)

    async def revoke_remember_tokens(self, user_id: int) -> int:
        """Revoke all remember tokens for a user.

        Args:
            user_id: The user ID.

        Returns:
            Number of tokens revoked.
        """
        return await self._auth_repo.revoke_remember_tokens(user_id)

    # ===== User Status =====

    async def get_auth_status(self, user_id: int) -> EmailAuthStatus:
        """Get email authentication status for a user.

        Args:
            user_id: The user ID.

        Returns:
            EmailAuthStatus with email and verification status.

        Raises:
            UserNotFoundError: If user has no email auth.
        """
        auth_data = await self._auth_repo.get_auth_status(user_id)
        if not auth_data:
            raise UserNotFoundError(user_id)

        return EmailAuthStatus(
            email=auth_data["email"],
            email_verified=auth_data["email_verified_at"] is not None,
        )

    async def logout_all_sessions(self, user_id: int, except_session_id: str | None = None) -> int:
        """Logout user from all sessions.

        Args:
            user_id: The user ID.
            except_session_id: Optional session ID to preserve.

        Returns:
            Number of sessions deleted.
        """
        return await self._auth_repo.delete_user_sessions(user_id, except_session_id)

    async def revoke_all_remember_tokens(self, user_id: int) -> int:
        """Revoke all remember tokens for a user.

        Args:
            user_id: The user ID.

        Returns:
            Number of tokens revoked.
        """
        return await self._auth_repo.revoke_remember_tokens(user_id)


async def provide_auth_service(state: State, auth_repo: AuthRepository) -> AuthService:
    """Litestar DI provider for AuthService.

    Args:
        state: Application state.
        auth_repo: Authentication repository instance.

    Returns:
        AuthService instance.
    """
    return AuthService(state.db_pool, state, auth_repo)
