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
from genjishimada_sdk.auth import EmailRegisterRequest, EmailLoginRequest


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
def auth_service(mock_repo, mock_state, test_client):
    """Create auth service with mocked repository."""
    return AuthService(test_client.app.state.db_pool, mock_state, mock_repo)


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

        user = await auth_service.login(
            EmailLoginRequest(email="test@test.com", password="Test123!@#")
        )

        assert user.id == 123
        assert user.email == "test@test.com"
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
