"""Authentication models for email-based users."""

from msgspec import Struct

__all__ = (
    "AuthUserPublic",
    "AuthUserResponse",
    "AuthUserVerify",
    "CreateRememberTokenResponse",
    "DestroyUserSessionsResponse",
    "EmailAuthStatus",
    "EmailLoginRequest",
    "EmailRegisterRequest",
    "EmailVerifyRequest",
    "LoginResponse",
    "PasswordResetConfirmRequest",
    "PasswordResetConfirmResponse",
    "PasswordResetEmailEvent",
    "PasswordResetRequest",
    "PasswordResetRequestResponse",
    "RegisterResponse",
    "ResendVerificationResponse",
    "RevokeRememberTokensResponse",
    "SessionDestroyResponse",
    "SessionGcResponse",
    "SessionInfo",
    "SessionReadResponse",
    "SessionWriteRequest",
    "SessionWriteResponse",
    "UserSessionsResponse",
    "ValidateRememberTokenResponse",
    "VerificationEmailEvent",
    "VerifyEmailResponse",
)


class EmailRegisterRequest(Struct):
    """Payload for registering a new email-based user.

    Attributes:
        email: User's email address.
        password: Plaintext password (will be hashed server-side).
        username: Display name (stored in global_name/nickname).
    """

    email: str
    password: str
    username: str


class EmailLoginRequest(Struct):
    """Payload for email-based login.

    Attributes:
        email: User's email address.
        password: Plaintext password to verify.
    """

    email: str
    password: str


class EmailVerifyRequest(Struct):
    """Payload for email verification.

    Attributes:
        token: The verification token from the email link.
    """

    token: str


class PasswordResetRequest(Struct):
    """Payload for initiating password reset.

    Attributes:
        email: User's email address.
    """

    email: str


class PasswordResetConfirmRequest(Struct):
    """Payload for completing password reset.

    Attributes:
        token: The reset token from the email link.
        password: New plaintext password.
    """

    token: str
    password: str


class EmailAuthStatus(Struct):
    """Email verification status for a user.

    Attributes:
        email_verified: Whether the user's email is verified.
        email: The user's email address (partially masked).
    """

    email_verified: bool
    email: str  # Masked, e.g., "u***@example.com"


class AuthUserResponse(Struct):
    """Response after successful authentication.

    Attributes:
        id: User ID (9-15 digits for email users, 17-19 for Discord).
        email: User's email address.
        username: Display name.
        email_verified: Whether email is verified.
        coins: Current coin balance.
        is_mod: Whether user has moderator/admin permissions.
    """

    id: int
    email: str
    username: str
    email_verified: bool
    coins: int = 0
    is_mod: bool = False


class AuthUserPublic(Struct):
    """Public-facing user info for registration responses.

    Attributes:
        id: User ID.
        email: User's email address.
        username: Display name.
        email_verified: Whether email is verified.
    """

    id: int
    email: str
    username: str
    email_verified: bool


class AuthUserVerify(Struct):
    """User info returned from verification and password reset flows.

    Attributes:
        id: User ID.
        email: User's email address.
        username: Display name.
        email_verified: Whether email is verified.
        is_mod: Whether user has moderator/admin permissions.
    """

    id: int
    email: str
    username: str
    email_verified: bool
    is_mod: bool = False


class VerificationEmailEvent(Struct):
    """Payload for verification email events."""

    email: str
    username: str
    token: str


class PasswordResetEmailEvent(Struct):
    """Payload for password reset email events."""

    email: str
    username: str
    token: str


class RegisterResponse(Struct):
    """Response for user registration."""

    user: AuthUserPublic
    verification_email_sent: bool


class LoginResponse(Struct):
    """Response for user login."""

    user: AuthUserResponse


class VerifyEmailResponse(Struct):
    """Response for email verification."""

    message: str
    user: AuthUserVerify


class ResendVerificationResponse(Struct):
    """Response for resend verification."""

    message: str


class PasswordResetRequestResponse(Struct):
    """Response for password reset request."""

    message: str


class PasswordResetConfirmResponse(Struct):
    """Response for password reset confirmation."""

    message: str
    user: AuthUserVerify


class SessionWriteRequest(Struct):
    """Payload for writing session data.

    Attributes:
        payload: Base64-encoded session data.
        user_id: Optional authenticated user ID.
    """

    payload: str
    user_id: int | None = None


class SessionInfo(Struct):
    """Information about an active session.

    Attributes:
        id: Session ID.
        last_activity: Last activity timestamp (ISO format).
        ip_address: Client IP address.
        user_agent: Client user agent string.
    """

    id: str
    last_activity: str | None
    ip_address: str | None
    user_agent: str | None


class SessionReadResponse(Struct):
    """Response from reading a session.

    Attributes:
        payload: Base64-encoded session data (null if not found).
        is_mod: Whether the authenticated user has moderator permissions.
    """

    payload: str | None
    is_mod: bool = False


class SessionWriteResponse(Struct):
    """Response for session write."""

    success: bool


class SessionDestroyResponse(Struct):
    """Response for session destroy."""

    deleted: bool


class SessionGcResponse(Struct):
    """Response for session garbage collection."""

    deleted_count: int


class UserSessionsResponse(Struct):
    """Response for user sessions list."""

    sessions: list[SessionInfo]


class DestroyUserSessionsResponse(Struct):
    """Response for destroying all user sessions."""

    destroyed_count: int


class CreateRememberTokenResponse(Struct):
    """Response for creating remember token."""

    token: str


class ValidateRememberTokenResponse(Struct):
    """Response for validating remember token."""

    valid: bool
    user_id: int | None


class RevokeRememberTokensResponse(Struct):
    """Response for revoking remember tokens."""

    revoked_count: int
