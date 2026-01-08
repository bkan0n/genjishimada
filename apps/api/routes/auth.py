"""Authentication routes for email-based users."""

from __future__ import annotations

import logging
import os
from typing import Annotated

import httpx
import litestar
from genjishimada_sdk.auth import (
    AuthUserResponse,
    EmailAuthStatus,
    EmailLoginRequest,
    EmailRegisterRequest,
    EmailVerifyRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
    SessionWriteRequest,
)
from litestar.di import Provide
from litestar.params import Body
from litestar.response import Response
from litestar.status_codes import HTTP_200_OK, HTTP_201_CREATED

from di.auth import AuthService, provide_auth_service

log = logging.getLogger(__name__)

# =============================================================================
# Configuration
# =============================================================================

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
SITE_URL = os.getenv("SITE_URL", "https://genji.pk")
FROM_EMAIL = os.getenv("FROM_EMAIL", "noreply@genji.pk")


# =============================================================================
# Email Helpers
# =============================================================================


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


def build_verification_email(username: str, token: str) -> str:
    """Build verification email HTML.

    Args:
        username: User's display name.
        token: Verification token.

    Returns:
        HTML string for the email.
    """
    verify_url = f"{SITE_URL}/verify-email?token={token}"
    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
        <h1 style="color: #10b981;">Welcome to Genji Parkour!</h1>
        <p>Hi {username},</p>
        <p>Thank you for registering. Please verify your email address by clicking the button below:</p>
        <p style="text-align: center; margin: 30px 0;">
            <a href="{verify_url}"
               style="background-color: #10b981; color: white; padding: 12px 24px;
                      text-decoration: none; border-radius: 4px; display: inline-block;
                      font-weight: bold;">
                Verify Email
            </a>
        </p>
        <p>Or copy this link: <a href="{verify_url}">{verify_url}</a></p>
        <p>This link expires in 24 hours.</p>
        <p>If you didn't create this account, you can ignore this email.</p>
        <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
        <p style="color: #888; font-size: 12px;">Genji Parkour Community</p>
    </body>
    </html>
    """


def build_password_reset_email(username: str, token: str) -> str:
    """Build password reset email HTML.

    Args:
        username: User's display name.
        token: Reset token.

    Returns:
        HTML string for the email.
    """
    reset_url = f"{SITE_URL}/reset-password?token={token}"
    return f"""
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 600px; margin: 0 auto; padding: 20px;">
        <h1 style="color: #10b981;">Password Reset Request</h1>
        <p>Hi {username},</p>
        <p>We received a request to reset your password. Click the button below to create a new password:</p>
        <p style="text-align: center; margin: 30px 0;">
            <a href="{reset_url}"
               style="background-color: #10b981; color: white; padding: 12px 24px;
                      text-decoration: none; border-radius: 4px; display: inline-block;
                      font-weight: bold;">
                Reset Password
            </a>
        </p>
        <p>Or copy this link: <a href="{reset_url}">{reset_url}</a></p>
        <p>This link expires in 1 hour.</p>
        <p>If you didn't request this, you can ignore this email. Your password won't be changed.</p>
        <hr style="border: none; border-top: 1px solid #eee; margin: 30px 0;">
        <p style="color: #888; font-size: 12px;">Genji Parkour Community</p>
    </body>
    </html>
    """


# =============================================================================
# Auth Controller
# =============================================================================


class AuthController(litestar.Controller):
    """Email-based authentication endpoints."""

    tags = ["Authentication"]
    path = "/auth"
    dependencies = {"svc": Provide(provide_auth_service)}
    # =========================================================================
    # Registration & Login
    # =========================================================================

    @litestar.post(
        path="/register",
        summary="Register New User",
        description="Create a new account with email and password. Sends verification email.",
    )
    async def register(
        self,
        svc: AuthService,
        request: litestar.Request,
        data: Annotated[EmailRegisterRequest, Body(title="Registration Data")],
    ) -> Response:
        """Register a new email-based user.

        Args:
            svc: Auth service.
            request: Current request (for client IP).
            data: Registration payload.

        Returns:
            Response with user data and email status.
        """
        client_ip = request.client.host if request.client else None
        user, token = await svc.register(data, client_ip)

        # Send verification email
        email_html = build_verification_email(user.username, token)
        email_sent = await send_email_via_resend(
            to=user.email,
            subject="Verify your email - Genji Parkour",
            html=email_html,
        )

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

    @litestar.post(
        path="/login",
        summary="Login",
        description="Authenticate with email and password.",
    )
    async def login(
        self,
        svc: AuthService,
        request: litestar.Request,
        data: Annotated[EmailLoginRequest, Body(title="Login Credentials")],
    ) -> Response:
        """Authenticate a user.

        Args:
            svc: Auth service.
            request: Current request (for client IP).
            data: Login payload.

        Returns:
            Response with user data.
        """
        client_ip = request.client.host if request.client else None
        user = await svc.login(data, client_ip)

        return Response(
            {
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "username": user.username,
                    "email_verified": user.email_verified,
                    "coins": user.coins,
                },
            },
            status_code=HTTP_200_OK,
        )

    # =========================================================================
    # Email Verification
    # =========================================================================

    @litestar.post(
        path="/verify-email",
        summary="Verify Email",
        description="Verify email address using token from verification email.",
    )
    async def verify_email(
        self,
        svc: AuthService,
        data: Annotated[EmailVerifyRequest, Body(title="Verification Token")],
    ) -> Response:
        """Verify a user's email.

        Args:
            svc: Auth service.
            data: Verification payload.

        Returns:
            Response with verified user data.
        """
        user = await svc.verify_email(data)

        return Response(
            {
                "message": "Email verified successfully.",
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "username": user.username,
                    "email_verified": user.email_verified,
                },
            },
            status_code=HTTP_200_OK,
        )

    @litestar.post(
        path="/resend-verification",
        summary="Resend Verification Email",
        description="Resend the verification email to a user.",
    )
    async def resend_verification(
        self,
        svc: AuthService,
        request: litestar.Request,
        data: Annotated[PasswordResetRequest, Body(title="Email Address")],
    ) -> Response:
        """Resend verification email.

        Args:
            svc: Auth service.
            request: Current request (for client IP).
            data: Request containing email address.

        Returns:
            Response indicating email was sent.
        """
        client_ip = request.client.host if request.client else None
        token, username = await svc.resend_verification(data.email, client_ip)

        # Send verification email
        email_html = build_verification_email(username, token)
        await send_email_via_resend(
            to=data.email,
            subject="Verify your email - Genji Parkour",
            html=email_html,
        )

        return Response(
            {"message": "If an account exists with this email, a verification email has been sent."},
            status_code=HTTP_200_OK,
        )

    # =========================================================================
    # Password Reset
    # =========================================================================

    @litestar.post(
        path="/forgot-password",
        summary="Request Password Reset",
        description="Send a password reset email.",
    )
    async def forgot_password(
        self,
        svc: AuthService,
        request: litestar.Request,
        data: Annotated[PasswordResetRequest, Body(title="Password Reset Request")],
    ) -> Response:
        """Request a password reset.

        Args:
            svc: Auth service.
            request: Current request (for client IP).
            data: Password reset request payload.

        Returns:
            Response indicating email was sent (always same message to prevent enumeration).
        """
        client_ip = request.client.host if request.client else None
        result = await svc.request_password_reset(data, client_ip)

        if result:
            token, username = result
            email_html = build_password_reset_email(username, token)
            await send_email_via_resend(
                to=data.email,
                subject="Reset your password - Genji Parkour",
                html=email_html,
            )

        # Always return same message to prevent email enumeration
        return Response(
            {"message": "If an account exists with this email, a password reset link has been sent."},
            status_code=HTTP_200_OK,
        )

    @litestar.post(
        path="/reset-password",
        summary="Reset Password",
        description="Set a new password using the reset token.",
    )
    async def reset_password(
        self,
        svc: AuthService,
        data: Annotated[PasswordResetConfirmRequest, Body(title="Password Reset Confirmation")],
    ) -> Response:
        """Reset a user's password.

        Args:
            svc: Auth service.
            data: Password reset confirmation payload.

        Returns:
            Response with user data.
        """
        user = await svc.reset_password(data)

        return Response(
            {
                "message": "Password reset successfully.",
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "username": user.username,
                    "email_verified": user.email_verified,
                },
            },
            status_code=HTTP_200_OK,
        )

    # =========================================================================
    # Auth Status
    # =========================================================================

    @litestar.get(
        path="/status/{user_id:int}",
        summary="Get Auth Status",
        description="Get email authentication status for a user.",
    )
    async def get_auth_status(self, svc: AuthService, user_id: int) -> EmailAuthStatus | None:
        """Get authentication status for a user.

        Args:
            svc: Auth service.
            user_id: The user ID.

        Returns:
            EmailAuthStatus if user has email auth, None otherwise.
        """
        return await svc.get_auth_status(user_id)

    # =========================================================================
    # Session Management (for Laravel custom session driver)
    # =========================================================================

    @litestar.get(
        path="/sessions/{session_id:str}",
        summary="Read Session",
        description="Read session data by ID. Used by Laravel session driver.",
    )
    async def session_read(self, svc: AuthService, session_id: str) -> Response:
        """Read session data.

        Args:
            svc: Auth service.
            session_id: The session ID.

        Returns:
            Response with session payload or empty if not found.
        """
        payload = await svc.session_read(session_id)
        return Response(
            {"payload": payload},
            status_code=HTTP_200_OK,
        )

    @litestar.put(
        path="/sessions/{session_id:str}",
        summary="Write Session",
        description="Write session data. Used by Laravel session driver.",
    )
    async def session_write(
        self,
        svc: AuthService,
        request: litestar.Request,
        session_id: str,
        data: Annotated[SessionWriteRequest, Body(title="Session Data")],
    ) -> Response:
        """Write session data.

        Args:
            svc: Auth service.
            request: Current request.
            session_id: The session ID.
            data: Session write payload.

        Returns:
            Response indicating success.
        """
        client_ip = request.client.host if request.client else None
        user_agent = request.headers.get("User-Agent")

        await svc.session_write(
            session_id=session_id,
            payload=data.payload,
            user_id=data.user_id,
            ip_address=client_ip,
            user_agent=user_agent,
        )

        return Response({"success": True}, status_code=HTTP_200_OK)

    @litestar.delete(
        path="/sessions/{session_id:str}",
        summary="Destroy Session",
        description="Destroy a session. Used by Laravel session driver.",
    )
    async def session_destroy(self, svc: AuthService, session_id: str) -> Response:
        """Destroy a session.

        Args:
            svc: Auth service.
            session_id: The session ID.

        Returns:
            Response indicating success.
        """
        deleted = await svc.session_destroy(session_id)
        return Response(
            {"deleted": deleted},
            status_code=HTTP_200_OK,
        )

    @litestar.post(
        path="/sessions/gc",
        summary="Garbage Collect Sessions",
        description="Remove expired sessions. Should be called periodically.",
    )
    async def session_gc(self, svc: AuthService) -> Response:
        """Garbage collect expired sessions.

        Args:
            svc: Auth service.

        Returns:
            Response with count of deleted sessions.
        """
        count = await svc.session_gc()
        return Response(
            {"deleted_count": count},
            status_code=HTTP_200_OK,
        )

    @litestar.get(
        path="/sessions/user/{user_id:int}",
        summary="Get User Sessions",
        description="Get all active sessions for a user.",
    )
    async def get_user_sessions(self, svc: AuthService, user_id: int) -> Response:
        """Get all sessions for a user.

        Args:
            svc: Auth service.
            user_id: The user ID.

        Returns:
            Response with list of sessions.
        """
        sessions = await svc.session_get_user_sessions(user_id)
        return Response({"sessions": sessions}, status_code=HTTP_200_OK)

    @litestar.delete(
        path="/sessions/user/{user_id:int}",
        summary="Destroy All User Sessions",
        description="Logout user from all devices.",
    )
    async def destroy_user_sessions(
        self,
        svc: AuthService,
        user_id: int,
        except_session_id: str | None = None,
    ) -> Response:
        """Destroy all sessions for a user.

        Args:
            svc: Auth service.
            user_id: The user ID.
            except_session_id: Optional session to keep.

        Returns:
            Response with count of destroyed sessions.
        """
        count = await svc.session_destroy_all_for_user(user_id, except_session_id)
        return Response(
            {"destroyed_count": count},
            status_code=HTTP_200_OK,
        )
