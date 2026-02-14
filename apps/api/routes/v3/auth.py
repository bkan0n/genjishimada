"""V4 Authentication routes."""

from __future__ import annotations

import ipaddress
import logging
from typing import Annotated

from genjishimada_sdk.auth import (
    CreateRememberTokenResponse,
    DestroyUserSessionsResponse,
    EmailAuthStatus,
    EmailLoginRequest,
    EmailRegisterRequest,
    EmailVerifyRequest,
    LoginResponse,
    PasswordResetConfirmRequest,
    PasswordResetConfirmResponse,
    PasswordResetRequest,
    PasswordResetRequestResponse,
    RegisterResponse,
    ResendVerificationResponse,
    RevokeRememberTokensResponse,
    SessionDestroyResponse,
    SessionGcResponse,
    SessionReadResponse,
    SessionWriteRequest,
    SessionWriteResponse,
    UserSessionsResponse,
    ValidateRememberTokenResponse,
    VerifyEmailResponse,
)
from litestar import Controller, delete, get, post, put
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


class AuthController(Controller):
    """Email-based authentication and Discord OAuth endpoints."""

    tags = ["Authentication"]
    path = "/auth"
    dependencies = {
        "auth_repo": Provide(provide_auth_repository),
        "auth_service": Provide(provide_auth_service),
    }

    @staticmethod
    def _safe_client_ip(request: Request) -> str | None:
        """Return client IP if it's a valid IP address, else None."""
        if not request.client:
            return None
        host = request.client.host
        try:
            ipaddress.ip_address(host)
            return host
        except ValueError:
            return None

    @post("/register")
    async def register_endpoint(
        self,
        data: Annotated[EmailRegisterRequest, Body(title="Registration data")],
        auth_service: AuthService,
        request: Request,
    ) -> Response[RegisterResponse]:
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
            client_ip = self._safe_client_ip(request)
            resp, event = await auth_service.register(data, client_ip=client_ip)
            try:
                request.app.emit("auth.verification.requested", event)
                resp.verification_email_sent = True
            except Exception as exc:
                log.warning("Failed to emit verification email event: %s", exc)
            return Response(resp, status_code=HTTP_201_CREATED)

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

    @post("/login")
    async def login_endpoint(
        self,
        data: Annotated[EmailLoginRequest, Body(title="Login credentials")],
        auth_service: AuthService,
        request: Request,
    ) -> Response[LoginResponse]:
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
            client_ip = self._safe_client_ip(request)
            resp = await auth_service.login(data, client_ip=client_ip)

            return Response(resp, status_code=HTTP_200_OK)

        except InvalidCredentialsError as e:
            raise CustomHTTPException(detail=e.message, status_code=HTTP_401_UNAUTHORIZED)
        except RateLimitExceededError as e:
            raise CustomHTTPException(detail=e.message, status_code=HTTP_429_TOO_MANY_REQUESTS)

    @post("/verify-email")
    async def verify_email_endpoint(
        self,
        data: Annotated[EmailVerifyRequest, Body(title="Verification token")],
        auth_service: AuthService,
    ) -> Response[VerifyEmailResponse]:
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
            resp = await auth_service.verify_email(data)

            return Response(resp, status_code=HTTP_200_OK)

        except TokenInvalidError as e:
            raise CustomHTTPException(detail=e.message, status_code=HTTP_400_BAD_REQUEST)
        except TokenAlreadyUsedError as e:
            raise CustomHTTPException(detail=e.message, status_code=HTTP_400_BAD_REQUEST)
        except TokenExpiredError as e:
            raise CustomHTTPException(detail=e.message, status_code=HTTP_400_BAD_REQUEST)
        except EmailAlreadyVerifiedError as e:
            raise CustomHTTPException(detail=e.message, status_code=HTTP_400_BAD_REQUEST)

    @post("/resend-verification")
    async def resend_verification_endpoint(
        self,
        data: Annotated[PasswordResetRequest, Body(title="Email address")],
        auth_service: AuthService,
        request: Request,
    ) -> Response[ResendVerificationResponse]:
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
            client_ip = self._safe_client_ip(request)
            resp, event = await auth_service.resend_verification(data.email, client_ip=client_ip)
            try:
                request.app.emit("auth.verification.resend", event)
            except Exception as exc:
                log.warning("Failed to emit verification resend event: %s", exc)
            return Response(resp, status_code=HTTP_200_OK)

        except UserNotFoundError as e:
            raise CustomHTTPException(detail=e.message, status_code=HTTP_404_NOT_FOUND)
        except EmailAlreadyVerifiedError as e:
            raise CustomHTTPException(detail=e.message, status_code=HTTP_400_BAD_REQUEST)
        except RateLimitExceededError as e:
            raise CustomHTTPException(detail=e.message, status_code=HTTP_429_TOO_MANY_REQUESTS)

    @post("/forgot-password")
    async def request_password_reset_endpoint(
        self,
        data: Annotated[PasswordResetRequest, Body(title="Password reset request")],
        auth_service: AuthService,
        request: Request,
    ) -> Response[PasswordResetRequestResponse]:
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
            client_ip = self._safe_client_ip(request)
            resp, event = await auth_service.request_password_reset(data, client_ip=client_ip)
            if event:
                try:
                    request.app.emit("auth.password_reset.requested", event)
                except Exception as exc:
                    log.warning("Failed to emit password reset event: %s", exc)
            return Response(resp, status_code=HTTP_200_OK)

        except RateLimitExceededError as e:
            raise CustomHTTPException(detail=e.message, status_code=HTTP_429_TOO_MANY_REQUESTS)

    @post("/reset-password")
    async def reset_password_endpoint(
        self,
        data: Annotated[PasswordResetConfirmRequest, Body(title="Password reset confirmation")],
        auth_service: AuthService,
    ) -> Response[PasswordResetConfirmResponse]:
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
            resp = await auth_service.confirm_password_reset(data)

            return Response(resp, status_code=HTTP_200_OK)

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
        self,
        user_id: int,
        auth_service: AuthService,
    ) -> Response[EmailAuthStatus]:
        """Get email authentication status for a user.

        Args:
            user_id: The user ID.
            auth_service: Authentication service.

        Returns:
            EmailAuthStatus with masked email and 200 status, or 404 if user has no email auth.
        """
        try:
            resp = await auth_service.get_auth_status(user_id)
            return Response(resp, status_code=HTTP_200_OK)

        except UserNotFoundError:
            raise CustomHTTPException(
                detail="User does not have email authentication.",
                status_code=HTTP_404_NOT_FOUND,
            )

    @get("/sessions/{session_id:str}")
    async def session_read_endpoint(
        self,
        session_id: str,
        auth_service: AuthService,
    ) -> Response[SessionReadResponse]:
        """Read session data by ID. Includes is_mod flag. Used by Laravel session driver.

        Args:
            session_id: The session ID.
            auth_service: Authentication service.

        Returns:
            SessionReadResponse with payload and is_mod flag with 200 status.
        """
        resp = await auth_service.session_read(session_id)
        return Response(resp, status_code=HTTP_200_OK)

    @put("/sessions/{session_id:str}")
    async def session_write_endpoint(
        self,
        session_id: str,
        data: Annotated[SessionWriteRequest, Body(title="Session Data")],
        auth_service: AuthService,
        request: Request,
    ) -> Response[SessionWriteResponse]:
        """Write session data. Used by Laravel session driver.

        Args:
            session_id: The session ID.
            data: Session write payload.
            auth_service: Authentication service.
            request: Current request (for client IP and user agent).

        Returns:
            Success response with 200 status.
        """
        client_ip = self._safe_client_ip(request)
        user_agent = request.headers.get("User-Agent")

        resp = await auth_service.session_write(
            session_id=session_id,
            payload=data.payload,
            user_id=data.user_id,
            ip_address=client_ip,
            user_agent=user_agent,
        )
        return Response(resp, status_code=HTTP_200_OK)

    @delete("/sessions/{session_id:str}", status_code=HTTP_200_OK)
    async def session_destroy_endpoint(
        self,
        session_id: str,
        auth_service: AuthService,
    ) -> Response[SessionDestroyResponse]:
        """Destroy a session. Used by Laravel session driver.

        Args:
            session_id: The session ID.
            auth_service: Authentication service.

        Returns:
            Response indicating whether session was deleted with 200 status.
        """
        resp = await auth_service.session_destroy(session_id)
        return Response(resp, status_code=HTTP_200_OK)

    @post("/sessions/gc")
    async def session_gc_endpoint(
        self,
        auth_service: AuthService,
    ) -> Response[SessionGcResponse]:
        """Garbage collect expired sessions. Should be called periodically.

        Args:
            auth_service: Authentication service.

        Returns:
            Response with count of deleted sessions with 200 status.
        """
        resp = await auth_service.session_gc()
        return Response(resp, status_code=HTTP_200_OK)

    @get("/sessions/user/{user_id:int}")
    async def get_user_sessions_endpoint(
        self,
        user_id: int,
        auth_service: AuthService,
    ) -> Response[UserSessionsResponse]:
        """Get all active sessions for a user.

        Args:
            user_id: The user ID.
            auth_service: Authentication service.

        Returns:
            Response with list of sessions with 200 status.
        """
        resp = await auth_service.session_get_user_sessions(user_id)
        return Response(resp, status_code=HTTP_200_OK)

    @delete("/sessions/user/{user_id:int}", status_code=HTTP_200_OK)
    async def destroy_user_sessions_endpoint(
        self,
        user_id: int,
        auth_service: AuthService,
        except_session_id: str | None = None,
    ) -> Response[DestroyUserSessionsResponse]:
        """Destroy all sessions for a user. Logout user from all devices.

        Args:
            user_id: The user ID.
            auth_service: Authentication service.
            except_session_id: Optional session to keep.

        Returns:
            Response with count of destroyed sessions with 200 status.
        """
        resp = await auth_service.session_destroy_all_for_user(user_id, except_session_id)
        return Response(resp, status_code=HTTP_200_OK)

    @post("/remember-token")
    async def create_remember_token_endpoint(
        self,
        data: Annotated[dict, Body(title="User ID")],
        auth_service: AuthService,
        request: Request,
    ) -> Response[CreateRememberTokenResponse]:
        """Create a long-lived token for persistent login.

        Args:
            data: Request containing user_id.
            auth_service: Authentication service.
            request: Current request (for client IP and user agent).

        Returns:
            Response with token with 201 status.
        """
        client_ip = self._safe_client_ip(request)
        user_agent = request.headers.get("User-Agent")

        resp = await auth_service.create_remember_token(
            user_id=data["user_id"],
            ip_address=client_ip,
            user_agent=user_agent,
        )

        return Response(resp, status_code=HTTP_201_CREATED)

    @post("/remember-token/validate")
    async def validate_remember_token_endpoint(
        self,
        data: Annotated[dict, Body(title="Token")],
        auth_service: AuthService,
    ) -> Response[ValidateRememberTokenResponse]:
        """Check if a remember token is valid and return user_id.

        Args:
            data: Request containing token.
            auth_service: Authentication service.

        Returns:
            Response with valid flag and user_id with 200 status.
        """
        resp = await auth_service.validate_remember_token(data["token"])
        return Response(resp, status_code=HTTP_200_OK)

    @delete("/remember-token/user/{user_id:int}", status_code=HTTP_200_OK)
    async def revoke_remember_tokens_endpoint(
        self,
        user_id: int,
        auth_service: AuthService,
    ) -> Response[RevokeRememberTokensResponse]:
        """Revoke all remember tokens for a user. Logout user from all devices.

        Args:
            user_id: The user ID.
            auth_service: Authentication service.

        Returns:
            Response with count of revoked tokens with 200 status.
        """
        model = await auth_service.revoke_remember_tokens(user_id)
        return Response(model, status_code=HTTP_200_OK)
