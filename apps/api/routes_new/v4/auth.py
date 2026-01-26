"""V4 Authentication routes."""

from __future__ import annotations

import logging
import os
from typing import Annotated

import httpx
from genjishimada_sdk.auth import (
    EmailAuthStatus,
    EmailLoginRequest,
    EmailRegisterRequest,
    EmailVerifyRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    SessionReadResponse,
    SessionWriteRequest,
)
from litestar import Router, delete, get, post, put
from litestar.connection import Request
from litestar.di import Provide
from litestar.params import Body
from litestar.response import Response
from litestar.status_codes import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
    HTTP_404_NOT_FOUND,
    HTTP_429_TOO_MANY_REQUESTS,
)

from repository.auth_repository import provide_auth_repository
from services.auth_service import AuthService, provide_auth_service
from services.exceptions.auth import (
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
from utilities.errors import CustomHTTPException

log = logging.getLogger(__name__)

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
SITE_URL = os.getenv("SITE_URL", "https://genji.pk")
FROM_EMAIL = os.getenv("FROM_EMAIL", "noreply@notifications.genji.pk")


async def send_email_via_resend(to: str, subject: str, html: str) -> bool:
    """Send an email using Resend API.

    Args:
        to: Recipient email address.
        subject: Email subject.
        html: HTML content of the email.

    Returns:
        True if email was sent successfully.
    """
    if not RESEND_API_KEY:
        log.warning("RESEND_API_KEY not configured, skipping email send")
        return False

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {RESEND_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": FROM_EMAIL,
                    "to": [to],
                    "subject": subject,
                    "html": html,
                },
            )
            response.raise_for_status()
            log.info(f"Email sent successfully to {to}")
            return True
        except Exception as e:
            log.error(f"Failed to send email to {to}: {e}")
            return False


@post("/register", opt={"exclude_from_auth": True})
async def register_endpoint(
    data: Annotated[EmailRegisterRequest, Body(title="Registration data")],
    auth_service: AuthService,
    request: Request,
) -> Response:
    """Register a new email-based user account.

    Args:
        data: Registration payload with email, password, and username.
        auth_service: Authentication service.
        request: Current request (for client IP).

    Returns:
        Response with user data and verification_email_sent flag with 201 status.

    Raises:
        CustomHTTPException: On validation, rate limit, or duplicate email errors.
    """
    try:
        client_ip = request.client.host if request.client else None
        user, token = await auth_service.register(data, client_ip=client_ip)

        # Send verification email
        verification_url = f"{SITE_URL}/verify-email?token={token}"
        html = f"""
        <h1>Welcome to Genji Parkour!</h1>
        <p>Hi {user.username},</p>
        <p>Thank you for registering. Please verify your email address by clicking the link below:</p>
        <p><a href="{verification_url}">Verify Email</a></p>
        <p>This link will expire in 24 hours.</p>
        """
        email_sent = await send_email_via_resend(user.email, "Verify your email", html)

        # Match v3 response format
        return Response(
            {
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "username": user.username,
                    "email_verified": user.email_verified,
                },
                "verification_email_sent": email_sent,
            },
            status_code=HTTP_201_CREATED,
        )

    except EmailValidationError as e:
        raise CustomHTTPException(detail=e.message, status_code=HTTP_400_BAD_REQUEST)
    except PasswordValidationError as e:
        raise CustomHTTPException(detail=e.message, status_code=HTTP_400_BAD_REQUEST)
    except UsernameValidationError as e:
        raise CustomHTTPException(detail=e.message, status_code=HTTP_400_BAD_REQUEST)
    except EmailAlreadyExistsError as e:
        raise CustomHTTPException(detail=e.message, status_code=HTTP_400_BAD_REQUEST)
    except RateLimitExceededError as e:
        raise CustomHTTPException(detail=e.message, status_code=HTTP_429_TOO_MANY_REQUESTS)


@post("/login", opt={"exclude_from_auth": True})
async def login_endpoint(
    data: Annotated[EmailLoginRequest, Body(title="Login credentials")],
    auth_service: AuthService,
    request: Request,
) -> Response:
    """Login with email and password.

    Args:
        data: Login payload with email and password.
        auth_service: Authentication service.
        request: Current request (for client IP).

    Returns:
        AuthUserResponse with 200 status.

    Raises:
        CustomHTTPException: On invalid credentials or rate limit errors.
    """
    try:
        client_ip = request.client.host if request.client else None
        user = await auth_service.login(data, client_ip=client_ip)

        # Wrap response to match v3 API contract
        return Response(
            {
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "username": user.username,
                    "email_verified": user.email_verified,
                    "coins": user.coins,
                    "is_mod": user.is_mod,
                },
            },
            status_code=HTTP_200_OK,
        )

    except InvalidCredentialsError as e:
        raise CustomHTTPException(detail=e.message, status_code=HTTP_401_UNAUTHORIZED)
    except RateLimitExceededError as e:
        raise CustomHTTPException(detail=e.message, status_code=HTTP_429_TOO_MANY_REQUESTS)


@post("/verify", opt={"exclude_from_auth": True})
async def verify_email_endpoint(
    data: Annotated[EmailVerifyRequest, Body(title="Verification token")],
    auth_service: AuthService,
) -> Response:
    """Verify email address with token.

    Args:
        data: Verification payload with token.
        auth_service: Authentication service.

    Returns:
        Response with message and user data with 200 status (matching v3 format).

    Raises:
        CustomHTTPException: On invalid, expired, used, or already verified errors.
    """
    try:
        user = await auth_service.verify_email(data)

        # Wrap response to match v3 API contract
        return Response(
            {
                "message": "Email verified successfully.",
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "username": user.username,
                    "email_verified": user.email_verified,
                    "coins": user.coins,
                    "is_mod": user.is_mod,
                },
            },
            status_code=HTTP_200_OK,
        )

    except TokenInvalidError as e:
        raise CustomHTTPException(detail=e.message, status_code=HTTP_400_BAD_REQUEST)
    except TokenAlreadyUsedError as e:
        raise CustomHTTPException(detail=e.message, status_code=HTTP_400_BAD_REQUEST)
    except TokenExpiredError as e:
        raise CustomHTTPException(detail=e.message, status_code=HTTP_400_BAD_REQUEST)
    except EmailAlreadyVerifiedError as e:
        raise CustomHTTPException(detail=e.message, status_code=HTTP_400_BAD_REQUEST)


# v3-compatible alias for /verify endpoint
@post("/verify-email", opt={"exclude_from_auth": True})
async def verify_email_endpoint_v3_alias(
    data: Annotated[EmailVerifyRequest, Body(title="Verification token")],
    auth_service: AuthService,
) -> Response:
    """v3-compatible alias for verify endpoint (v3 path: /verify-email)."""
    try:
        user = await auth_service.verify_email(data)

        # Wrap response to match v3 API contract
        return Response(
            {
                "message": "Email verified successfully.",
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "username": user.username,
                    "email_verified": user.email_verified,
                    "coins": user.coins,
                    "is_mod": user.is_mod,
                },
            },
            status_code=HTTP_200_OK,
        )

    except TokenInvalidError as e:
        raise CustomHTTPException(detail=e.message, status_code=HTTP_400_BAD_REQUEST)
    except TokenAlreadyUsedError as e:
        raise CustomHTTPException(detail=e.message, status_code=HTTP_400_BAD_REQUEST)
    except TokenExpiredError as e:
        raise CustomHTTPException(detail=e.message, status_code=HTTP_400_BAD_REQUEST)
    except EmailAlreadyVerifiedError as e:
        raise CustomHTTPException(detail=e.message, status_code=HTTP_400_BAD_REQUEST)


@post("/resend-verification", opt={"exclude_from_auth": True})
async def resend_verification_endpoint(
    data: Annotated[PasswordResetRequest, Body(title="Email address")],
    auth_service: AuthService,
    request: Request,
) -> Response:
    """Resend verification email.

    Args:
        data: Request containing email address.
        auth_service: Authentication service.
        request: Current request (for client IP).

    Returns:
        Success message with 200 status.

    Raises:
        CustomHTTPException: On errors.
    """
    try:
        client_ip = request.client.host if request.client else None
        token, username = await auth_service.resend_verification(data.email, client_ip=client_ip)

        # Send verification email
        verification_url = f"{SITE_URL}/verify-email?token={token}"
        html = f"""
        <h1>Verify Your Email</h1>
        <p>Hi {username},</p>
        <p>Please verify your email address by clicking the link below:</p>
        <p><a href="{verification_url}">Verify Email</a></p>
        <p>This link will expire in 24 hours.</p>
        """
        await send_email_via_resend(data.email, "Verify your email", html)

        return Response({"message": "Verification email sent."}, status_code=HTTP_200_OK)

    except UserNotFoundError as e:
        raise CustomHTTPException(detail=e.message, status_code=HTTP_404_NOT_FOUND)
    except EmailAlreadyVerifiedError as e:
        raise CustomHTTPException(detail=e.message, status_code=HTTP_400_BAD_REQUEST)
    except RateLimitExceededError as e:
        raise CustomHTTPException(detail=e.message, status_code=HTTP_429_TOO_MANY_REQUESTS)


@post("/request-password-reset", opt={"exclude_from_auth": True})
async def request_password_reset_endpoint(
    data: Annotated[PasswordResetRequest, Body(title="Password reset request")],
    auth_service: AuthService,
    request: Request,
) -> Response:
    """Request a password reset token.

    Args:
        data: Password reset request with email.
        auth_service: Authentication service.
        request: Current request (for client IP).

    Returns:
        Success message with 200 status (always, even if email not found for security).

    Raises:
        CustomHTTPException: On rate limit errors.
    """
    try:
        client_ip = request.client.host if request.client else None
        result = await auth_service.request_password_reset(data, client_ip=client_ip)

        if result:
            token, username = result
            # Send password reset email
            reset_url = f"{SITE_URL}/reset-password?token={token}"
            html = f"""
            <h1>Reset Your Password</h1>
            <p>Hi {username},</p>
            <p>You requested to reset your password. Click the link below to continue:</p>
            <p><a href="{reset_url}">Reset Password</a></p>
            <p>This link will expire in 1 hour.</p>
            <p>If you didn't request this, please ignore this email.</p>
            """
            await send_email_via_resend(data.email, "Reset your password", html)

        # Always return success to prevent email enumeration
        return Response(
            {"message": "If an account with that email exists, a password reset link has been sent."},
            status_code=HTTP_200_OK,
        )

    except RateLimitExceededError as e:
        raise CustomHTTPException(detail=e.message, status_code=HTTP_429_TOO_MANY_REQUESTS)


# v3-compatible alias for /request-password-reset endpoint
@post("/forgot-password", opt={"exclude_from_auth": True})
async def request_password_reset_endpoint_v3_alias(
    data: Annotated[PasswordResetRequest, Body(title="Password reset request")],
    auth_service: AuthService,
    request: Request,
) -> Response:
    """v3-compatible alias for request-password-reset endpoint (v3 path: /forgot-password)."""
    try:
        client_ip = request.client.host if request.client else None
        result = await auth_service.request_password_reset(data, client_ip=client_ip)

        if result:
            token, username = result
            # Send password reset email
            reset_url = f"{SITE_URL}/reset-password?token={token}"
            html = f"""
            <h1>Reset Your Password</h1>
            <p>Hi {username},</p>
            <p>You requested to reset your password. Click the link below to continue:</p>
            <p><a href="{reset_url}">Reset Password</a></p>
            <p>This link will expire in 1 hour.</p>
            <p>If you didn't request this, please ignore this email.</p>
            """
            await send_email_via_resend(data.email, "Reset your password", html)

        # Always return success to prevent email enumeration
        return Response(
            {"message": "If an account with that email exists, a password reset link has been sent."},
            status_code=HTTP_200_OK,
        )

    except RateLimitExceededError as e:
        raise CustomHTTPException(detail=e.message, status_code=HTTP_429_TOO_MANY_REQUESTS)


@post("/reset-password", opt={"exclude_from_auth": True})
async def reset_password_endpoint(
    data: Annotated[PasswordResetConfirmRequest, Body(title="Password reset confirmation")],
    auth_service: AuthService,
) -> Response:
    """Reset password with token.

    Args:
        data: Password reset confirmation with token and new password.
        auth_service: Authentication service.

    Returns:
        Response with message and user data with 200 status (matching v3 format).

    Raises:
        CustomHTTPException: On validation or token errors.
    """
    try:
        user = await auth_service.confirm_password_reset(data)

        # Wrap response to match v3 API contract
        return Response(
            {
                "message": "Password reset successfully.",
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "username": user.username,
                    "email_verified": user.email_verified,
                    "coins": user.coins,
                    "is_mod": user.is_mod,
                },
            },
            status_code=HTTP_200_OK,
        )

    except PasswordValidationError as e:
        raise CustomHTTPException(detail=e.message, status_code=HTTP_400_BAD_REQUEST)
    except TokenInvalidError as e:
        raise CustomHTTPException(detail=e.message, status_code=HTTP_400_BAD_REQUEST)
    except TokenAlreadyUsedError as e:
        raise CustomHTTPException(detail=e.message, status_code=HTTP_400_BAD_REQUEST)
    except TokenExpiredError as e:
        raise CustomHTTPException(detail=e.message, status_code=HTTP_400_BAD_REQUEST)


@get("/status/{user_id:int}")
async def get_auth_status_endpoint(
    user_id: int,
    auth_service: AuthService,
) -> Response:
    """Get email authentication status for a user.

    Args:
        user_id: The user ID.
        auth_service: Authentication service.

    Returns:
        EmailAuthStatus with masked email and 200 status, or 404 if user has no email auth.
    """
    try:
        status = await auth_service.get_auth_status(user_id)

        # Mask email for privacy (matching v3 behavior)
        local, domain = status.email.split("@")
        masked_local = local[0] + "***" if len(local) > 1 else "***"
        masked_email = f"{masked_local}@{domain}"

        # Return with masked email
        masked_status = EmailAuthStatus(
            email_verified=status.email_verified,
            email=masked_email,
        )

        return Response(masked_status, status_code=HTTP_200_OK)

    except UserNotFoundError:
        raise CustomHTTPException(
            detail="User does not have email authentication.",
            status_code=HTTP_404_NOT_FOUND,
        )


# ===== Session Management Endpoints =====


@get("/sessions/{session_id:str}", opt={"exclude_from_auth": True})
async def session_read_endpoint(
    session_id: str,
    auth_service: AuthService,
) -> Response:
    """Read session data by ID. Includes is_mod flag. Used by Laravel session driver.

    Args:
        session_id: The session ID.
        auth_service: Authentication service.

    Returns:
        SessionReadResponse with payload and is_mod flag with 200 status.
    """
    payload = await auth_service.session_read(session_id)

    # Get is_mod from user's record
    is_mod = False
    if payload:
        is_mod = await auth_service.check_if_mod(session_id)

    return Response(SessionReadResponse(payload=payload, is_mod=is_mod), status_code=HTTP_200_OK)


@put("/sessions/{session_id:str}", opt={"exclude_from_auth": True})
async def session_write_endpoint(
    session_id: str,
    data: Annotated[SessionWriteRequest, Body(title="Session Data")],
    auth_service: AuthService,
    request: Request,
) -> Response:
    """Write session data. Used by Laravel session driver.

    Args:
        session_id: The session ID.
        data: Session write payload.
        auth_service: Authentication service.
        request: Current request (for client IP and user agent).

    Returns:
        Success response with 200 status.
    """
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")

    await auth_service.session_write(
        session_id=session_id,
        payload=data.payload,
        user_id=data.user_id,
        ip_address=client_ip,
        user_agent=user_agent,
    )

    return Response({"success": True}, status_code=HTTP_200_OK)


@delete("/sessions/{session_id:str}", status_code=HTTP_200_OK, opt={"exclude_from_auth": True})
async def session_destroy_endpoint(
    session_id: str,
    auth_service: AuthService,
) -> Response:
    """Destroy a session. Used by Laravel session driver.

    Args:
        session_id: The session ID.
        auth_service: Authentication service.

    Returns:
        Response indicating whether session was deleted with 200 status.
    """
    deleted = await auth_service.session_destroy(session_id)
    return Response({"deleted": deleted}, status_code=HTTP_200_OK)


@post("/sessions/gc", opt={"exclude_from_auth": True})
async def session_gc_endpoint(
    auth_service: AuthService,
) -> Response:
    """Garbage collect expired sessions. Should be called periodically.

    Args:
        auth_service: Authentication service.

    Returns:
        Response with count of deleted sessions with 200 status.
    """
    count = await auth_service.session_gc()
    return Response({"deleted_count": count}, status_code=HTTP_200_OK)


@get("/sessions/user/{user_id:int}")
async def get_user_sessions_endpoint(
    user_id: int,
    auth_service: AuthService,
) -> Response:
    """Get all active sessions for a user.

    Args:
        user_id: The user ID.
        auth_service: Authentication service.

    Returns:
        Response with list of sessions with 200 status.
    """
    sessions = await auth_service.session_get_user_sessions(user_id)
    return Response({"sessions": sessions}, status_code=HTTP_200_OK)


@delete("/sessions/user/{user_id:int}", status_code=HTTP_200_OK)
async def destroy_user_sessions_endpoint(
    user_id: int,
    auth_service: AuthService,
    except_session_id: str | None = None,
) -> Response:
    """Destroy all sessions for a user. Logout user from all devices.

    Args:
        user_id: The user ID.
        auth_service: Authentication service.
        except_session_id: Optional session to keep.

    Returns:
        Response with count of destroyed sessions with 200 status.
    """
    count = await auth_service.session_destroy_all_for_user(user_id, except_session_id)
    return Response({"destroyed_count": count}, status_code=HTTP_200_OK)


# ===== Remember Token Endpoints =====


@post("/remember-token", opt={"exclude_from_auth": True})
async def create_remember_token_endpoint(
    data: Annotated[dict, Body(title="User ID")],
    auth_service: AuthService,
    request: Request,
) -> Response:
    """Create a long-lived token for persistent login.

    Args:
        data: Request containing user_id.
        auth_service: Authentication service.
        request: Current request (for client IP and user agent).

    Returns:
        Response with token with 201 status.
    """
    client_ip = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")

    token = await auth_service.create_remember_token(
        user_id=data["user_id"],
        ip_address=client_ip,
        user_agent=user_agent,
    )

    return Response({"token": token}, status_code=HTTP_201_CREATED)


@post("/remember-token/validate", opt={"exclude_from_auth": True})
async def validate_remember_token_endpoint(
    data: Annotated[dict, Body(title="Token")],
    auth_service: AuthService,
) -> Response:
    """Check if a remember token is valid and return user_id.

    Args:
        data: Request containing token.
        auth_service: Authentication service.

    Returns:
        Response with valid flag and user_id with 200 status.
    """
    user_id = await auth_service.validate_remember_token(data["token"])

    if user_id is None:
        return Response({"valid": False, "user_id": None}, status_code=HTTP_200_OK)

    return Response({"valid": True, "user_id": user_id}, status_code=HTTP_200_OK)


@delete("/remember-token/user/{user_id:int}", status_code=HTTP_200_OK, opt={"exclude_from_auth": True})
async def revoke_remember_tokens_endpoint(
    user_id: int,
    auth_service: AuthService,
) -> Response:
    """Revoke all remember tokens for a user. Logout user from all devices.

    Args:
        user_id: The user ID.
        auth_service: Authentication service.

    Returns:
        Response with count of revoked tokens with 200 status.
    """
    count = await auth_service.revoke_remember_tokens(user_id)
    return Response({"revoked_count": count}, status_code=HTTP_200_OK)


# Create router with /v4/auth prefix
router = Router(
    path="/v4/auth",
    route_handlers=[
        register_endpoint,
        login_endpoint,
        verify_email_endpoint,
        verify_email_endpoint_v3_alias,  # v3 compatibility: /verify-email
        resend_verification_endpoint,
        request_password_reset_endpoint,
        request_password_reset_endpoint_v3_alias,  # v3 compatibility: /forgot-password
        reset_password_endpoint,
        get_auth_status_endpoint,
        # Session management
        session_read_endpoint,
        session_write_endpoint,
        session_destroy_endpoint,
        session_gc_endpoint,
        get_user_sessions_endpoint,
        destroy_user_sessions_endpoint,
        # Remember token
        create_remember_token_endpoint,
        validate_remember_token_endpoint,
        revoke_remember_tokens_endpoint,
    ],
    dependencies={
        "auth_repo": Provide(provide_auth_repository),
        "auth_service": Provide(provide_auth_service),
    },
)
