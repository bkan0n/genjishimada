"""Tests for AuthService."""

import pytest
from unittest.mock import AsyncMock, Mock

from services.auth_service import AuthService
from services.exceptions.auth import (
    EmailAlreadyExistsError,
    EmailValidationError,
    InvalidCredentialsError,
    PasswordValidationError,
    UsernameValidationError,
)
from genjishimada_sdk.auth import EmailLoginRequest, EmailRegisterRequest, PasswordResetRequest


class _FakeTransaction:
    async def __aenter__(self):  # noqa: D401 - simple stub
        return self

    async def __aexit__(self, exc_type, exc, tb):  # noqa: D401 - simple stub
        return False


class _FakeConn:
    def transaction(self) -> _FakeTransaction:
        return _FakeTransaction()


class _FakeAcquire:
    def __init__(self, conn: _FakeConn) -> None:
        self._conn = conn

    async def __aenter__(self) -> _FakeConn:
        return self._conn

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


@pytest.fixture
def mock_repo():
    """Create mock auth repository."""
    repo = Mock()
    # Mock rate limiting to always return 0 by default (not rate limited)
    repo.fetch_rate_limit_count = AsyncMock(return_value=0)
    return repo


@pytest.fixture
def mock_state(test_client):
    """Create mock state."""
    return test_client.app.state


@pytest.fixture
def mock_pool():
    """Create mock pool with acquire stub."""
    pool = Mock()
    pool.acquire = Mock(return_value=_FakeAcquire(_FakeConn()))
    return pool


@pytest.fixture
def auth_service(mock_repo, mock_state, mock_pool):
    """Create auth service with mocked repository."""
    return AuthService(mock_pool, mock_state, mock_repo)


class TestValidation:
    """Test validation methods."""

    def test_validate_email_accepts_valid_email(self, auth_service):
        """Test that valid email passes validation."""
        auth_service.validate_email("test@example.com")  # Should not raise

    def test_validate_email_rejects_invalid_email(self, auth_service):
        """Test that invalid email raises EmailValidationError."""
        with pytest.raises(EmailValidationError):
            auth_service.validate_email("not-an-email")

    def test_validate_password_accepts_valid_password(self, auth_service):
        """Test that valid password passes validation."""
        auth_service.validate_password("Test123!@#")  # Should not raise

    def test_validate_password_rejects_short_password(self, auth_service):
        """Test that short password raises PasswordValidationError."""
        with pytest.raises(PasswordValidationError):
            auth_service.validate_password("Short1!")

    def test_validate_password_rejects_password_without_uppercase(self, auth_service):
        """Test that password without uppercase raises PasswordValidationError."""
        with pytest.raises(PasswordValidationError):
            auth_service.validate_password("test123!@#")

    def test_validate_username_accepts_valid_username(self, auth_service):
        """Test that valid username passes validation."""
        auth_service.validate_username("TestUser123")  # Should not raise

    def test_validate_username_rejects_too_long_username(self, auth_service):
        """Test that too long username raises UsernameValidationError."""
        with pytest.raises(UsernameValidationError):
            auth_service.validate_username("a" * 21)


class TestRegistration:
    """Test user registration."""

    @pytest.mark.asyncio
    async def test_register_validates_email(self, auth_service, mock_repo):
        """Test that registration validates email."""
        mock_repo.check_email_exists = AsyncMock(return_value=False)

        with pytest.raises(EmailValidationError):
            await auth_service.register(
                EmailRegisterRequest(
                    email="invalid-email",
                    username="testuser",
                    password="Test123!@#",
                )
            )

        mock_repo.check_email_exists.assert_not_called()

    @pytest.mark.asyncio
    async def test_register_checks_email_exists(self, auth_service, mock_repo):
        """Test that registration checks if email exists."""
        mock_repo.check_email_exists = AsyncMock(return_value=True)
        mock_repo.record_attempt = AsyncMock()

        with pytest.raises(EmailAlreadyExistsError):
            await auth_service.register(
                EmailRegisterRequest(
                    email="test@test.com",
                    username="testuser",
                    password="Test123!@#",
                )
            )

        mock_repo.check_email_exists.assert_called_once()
        mock_repo.record_attempt.assert_called_once_with(
            "test@test.com", "register", success=False
        )

    @pytest.mark.asyncio
    async def test_register_returns_response_and_event(self, auth_service, mock_repo):
        """Test that register returns response and event payload."""
        mock_repo.check_email_exists = AsyncMock(return_value=False)
        mock_repo.record_attempt = AsyncMock()
        mock_repo.generate_next_user_id = AsyncMock(return_value=123)
        mock_repo.create_core_user = AsyncMock()
        mock_repo.create_email_auth = AsyncMock()
        mock_repo.insert_email_token = AsyncMock()

        resp, event = await auth_service.register(
            EmailRegisterRequest(
                email="test@test.com",
                username="testuser",
                password="Test123!@#",
            )
        )

        assert resp.user.email == "test@test.com"
        assert event.email == "test@test.com"
        assert event.username == "testuser"
        assert event.token


class TestLogin:
    """Test user login."""

    @pytest.mark.asyncio
    async def test_login_returns_user_on_valid_credentials(self, auth_service, mock_repo):
        """Test that login returns user with valid credentials."""
        mock_repo.get_user_by_email = AsyncMock(
            return_value={
                "user_id": 123,
                "email": "test@test.com",
                "password_hash": auth_service.hash_password("Test123!@#"),
                "email_verified_at": None,
                "nickname": "testuser",
                "coins": 0,
                "is_mod": False,
            }
        )
        mock_repo.record_attempt = AsyncMock()

        resp = await auth_service.login(
            EmailLoginRequest(email="test@test.com", password="Test123!@#")
        )

        assert resp.user.id == 123
        assert resp.user.email == "test@test.com"
        mock_repo.record_attempt.assert_called_once_with(
            "test@test.com", "login", success=True
        )

    @pytest.mark.asyncio
    async def test_login_raises_on_invalid_credentials(self, auth_service, mock_repo):
        """Test that login raises InvalidCredentialsError on wrong password."""
        mock_repo.get_user_by_email = AsyncMock(
            return_value={
                "user_id": 123,
                "email": "test@test.com",
                "password_hash": auth_service.hash_password("Test123!@#"),
                "email_verified_at": None,
                "nickname": "testuser",
                "coins": 0,
                "is_mod": False,
            }
        )
        mock_repo.record_attempt = AsyncMock()

        with pytest.raises(InvalidCredentialsError):
            await auth_service.login(
                EmailLoginRequest(email="test@test.com", password="WrongPassword!")
            )

        mock_repo.record_attempt.assert_called_once_with(
            "test@test.com", "login", success=False
        )


class TestPasswordReset:
    """Test password reset service methods."""

    @pytest.mark.asyncio
    async def test_request_password_reset_returns_event_when_user_exists(self, auth_service, mock_repo):
        """Test password reset returns event when user exists."""
        mock_repo.get_user_by_email = AsyncMock(
            return_value={
                "user_id": 123,
                "email": "test@test.com",
                "email_verified_at": None,
                "nickname": "testuser",
                "coins": 0,
                "is_mod": False,
            }
        )
        mock_repo.invalidate_user_tokens = AsyncMock()
        mock_repo.insert_email_token = AsyncMock()
        mock_repo.record_attempt = AsyncMock()

        resp, event = await auth_service.request_password_reset(
            PasswordResetRequest(email="test@test.com")
        )

        assert "password reset link has been sent" in resp.message
        assert event is not None
        assert event.email == "test@test.com"

    @pytest.mark.asyncio
    async def test_request_password_reset_returns_none_event_when_missing(self, auth_service, mock_repo):
        """Test password reset returns None event when user missing."""
        mock_repo.get_user_by_email = AsyncMock(return_value=None)
        mock_repo.record_attempt = AsyncMock()

        resp, event = await auth_service.request_password_reset(
            PasswordResetRequest(email="missing@test.com")
        )

        assert "password reset link has been sent" in resp.message
        assert event is None


class TestStatusAndSessions:
    """Test status and session helpers."""

    @pytest.mark.asyncio
    async def test_get_auth_status_masks_email(self, auth_service, mock_repo):
        """Test that status masks email."""
        mock_repo.get_auth_status = AsyncMock(
            return_value={"email": "user@example.com", "email_verified_at": None}
        )

        resp = await auth_service.get_auth_status(123)

        assert resp.email != "user@example.com"
        assert "***@" in resp.email

    @pytest.mark.asyncio
    async def test_session_read_includes_is_mod(self, auth_service, mock_repo):
        """Test session read includes is_mod flag."""
        mock_repo.read_session = AsyncMock(return_value="payload")
        mock_repo.check_is_mod = AsyncMock(return_value=True)

        resp = await auth_service.session_read("sess-1")

        assert resp.payload == "payload"
        assert resp.is_mod is True

    @pytest.mark.asyncio
    async def test_session_write_returns_success(self, auth_service, mock_repo):
        """Test session write returns success response."""
        mock_repo.write_session = AsyncMock()

        resp = await auth_service.session_write("sess-1", "payload", None, None, None)

        assert resp.success is True

    @pytest.mark.asyncio
    async def test_session_get_user_sessions_returns_models(self, auth_service, mock_repo):
        """Test session list returns session models."""
        mock_repo.get_user_sessions = AsyncMock(
            return_value=[
                {"id": "s1", "last_activity": None, "ip_address": None, "user_agent": None}
            ]
        )

        resp = await auth_service.session_get_user_sessions(123)

        assert len(resp.sessions) == 1
        assert resp.sessions[0].id == "s1"
