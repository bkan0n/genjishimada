"""Unit tests for AuthService."""

from datetime import datetime, timedelta, timezone

import pytest
from genjishimada_sdk.auth import (
    EmailLoginRequest,
    EmailRegisterRequest,
    EmailVerifyRequest,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
)

from repository.exceptions import (
    ForeignKeyViolationError,
    UniqueConstraintViolationError,
)
from services.auth_service import AuthService
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

pytestmark = [
    pytest.mark.domain_auth,
]


class TestAuthServiceValidation:
    """Test validation methods."""

    def test_validate_email_valid(self):
        """Valid email passes validation."""
        AuthService.validate_email("user@example.com")

    def test_validate_email_invalid_no_at(self):
        """Email without @ raises EmailValidationError."""
        with pytest.raises(EmailValidationError):
            AuthService.validate_email("not-an-email")

    def test_validate_email_invalid_no_domain(self):
        """Email without domain raises EmailValidationError."""
        with pytest.raises(EmailValidationError):
            AuthService.validate_email("user@")

    def test_validate_email_invalid_no_tld(self):
        """Email without TLD raises EmailValidationError."""
        with pytest.raises(EmailValidationError):
            AuthService.validate_email("user@domain")

    def test_validate_password_too_short(self):
        """Password under 8 chars raises PasswordValidationError."""
        with pytest.raises(PasswordValidationError, match="at least 8 characters"):
            AuthService.validate_password("Short1!")

    def test_validate_password_missing_lowercase(self):
        """Password without lowercase raises PasswordValidationError."""
        with pytest.raises(PasswordValidationError, match="lowercase letter"):
            AuthService.validate_password("UPPERCASE123!")

    def test_validate_password_missing_uppercase(self):
        """Password without uppercase raises PasswordValidationError."""
        with pytest.raises(PasswordValidationError, match="uppercase letter"):
            AuthService.validate_password("lowercase123!")

    def test_validate_password_missing_number(self):
        """Password without number raises PasswordValidationError."""
        with pytest.raises(PasswordValidationError, match="number"):
            AuthService.validate_password("Password!")

    def test_validate_password_missing_special(self):
        """Password without special char raises PasswordValidationError."""
        with pytest.raises(PasswordValidationError, match="special character"):
            AuthService.validate_password("Password123")

    def test_validate_password_valid(self):
        """Valid password passes validation."""
        AuthService.validate_password("ValidPass123!")

    def test_validate_username_too_short(self):
        """Username with 0 chars raises UsernameValidationError."""
        with pytest.raises(UsernameValidationError, match="between 1 and 20 characters"):
            AuthService.validate_username("")

    def test_validate_username_too_long(self):
        """Username over 20 chars raises UsernameValidationError."""
        with pytest.raises(UsernameValidationError, match="between 1 and 20 characters"):
            AuthService.validate_username("a" * 21)

    def test_validate_username_invalid_chars(self):
        """Username with invalid chars raises UsernameValidationError."""
        with pytest.raises(
            UsernameValidationError, match="can only contain letters, numbers"
        ):
            AuthService.validate_username("user@name")

    def test_validate_username_only_whitespace(self):
        """Username with only whitespace raises UsernameValidationError."""
        with pytest.raises(UsernameValidationError, match="cannot be empty or only whitespace"):
            AuthService.validate_username("   ")

    def test_validate_username_valid_alphanumeric(self):
        """Valid alphanumeric username passes."""
        AuthService.validate_username("testuser123")

    def test_validate_username_valid_with_underscore(self):
        """Valid username with underscore passes."""
        AuthService.validate_username("test_user")

    def test_validate_username_valid_with_hyphen(self):
        """Valid username with hyphen passes."""
        AuthService.validate_username("test-user")

    def test_validate_username_valid_with_space(self):
        """Valid username with space passes."""
        AuthService.validate_username("test user")


class TestAuthServiceCryptography:
    """Test password hashing and token generation."""

    def test_hash_password_returns_bcrypt_hash(self):
        """hash_password returns bcrypt hash string."""
        password = "TestPassword123!"
        password_hash = AuthService.hash_password(password)
        assert password_hash.startswith("$2b$")

    def test_hash_password_unique_salts(self):
        """hash_password generates unique hashes for same password."""
        password = "TestPassword123!"
        hash1 = AuthService.hash_password(password)
        hash2 = AuthService.hash_password(password)
        assert hash1 != hash2  # Different salts

    def test_verify_password_correct(self):
        """verify_password returns True for correct password."""
        password = "TestPassword123!"
        password_hash = AuthService.hash_password(password)
        assert AuthService.verify_password(password, password_hash) is True

    def test_verify_password_incorrect(self):
        """verify_password returns False for incorrect password."""
        password = "TestPassword123!"
        password_hash = AuthService.hash_password(password)
        assert AuthService.verify_password("WrongPassword123!", password_hash) is False

    def test_generate_token_returns_tuple(self):
        """generate_token returns (token, hash) tuple."""
        token, token_hash = AuthService.generate_token()
        assert isinstance(token, str)
        assert isinstance(token_hash, str)
        assert len(token) > 0
        assert len(token_hash) == 64  # SHA256 hex is 64 chars

    def test_generate_token_unique(self):
        """generate_token creates unique tokens."""
        token1, hash1 = AuthService.generate_token()
        token2, hash2 = AuthService.generate_token()
        assert token1 != token2
        assert hash1 != hash2

    def test_hash_token_deterministic(self):
        """hash_token produces same hash for same token."""
        token = "test_token"
        hash1 = AuthService.hash_token(token)
        hash2 = AuthService.hash_token(token)
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA256 hex


class TestAuthServiceRateLimiting:
    """Test rate limiting logic."""

    async def test_check_rate_limit_not_exceeded(
        self, mock_pool, mock_state, mock_auth_repo
    ):
        """check_rate_limit passes when under limit."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)
        mock_auth_repo.fetch_rate_limit_count.return_value = 2  # Under limit of 5

        await service.check_rate_limit("test@example.com", "register")

        mock_auth_repo.fetch_rate_limit_count.assert_called_once()

    async def test_check_rate_limit_exceeded(self, mock_pool, mock_state, mock_auth_repo):
        """check_rate_limit raises RateLimitExceededError when exceeded."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)
        mock_auth_repo.fetch_rate_limit_count.return_value = 10  # At limit of 10

        with pytest.raises(RateLimitExceededError):
            await service.check_rate_limit("test@example.com", "login")

    async def test_check_rate_limit_unknown_action(
        self, mock_pool, mock_state, mock_auth_repo
    ):
        """check_rate_limit passes for unknown action (no limit defined)."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        await service.check_rate_limit("test@example.com", "unknown_action")

        # Should not call repository at all
        mock_auth_repo.fetch_rate_limit_count.assert_not_called()


class TestAuthServiceRegistration:
    """Test user registration flow."""

    async def test_register_success(self, mock_pool, mock_state, mock_auth_repo):
        """Successful registration creates user and returns response."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        # Setup mocks
        mock_auth_repo.fetch_rate_limit_count.return_value = 0
        mock_auth_repo.check_email_exists.return_value = False
        mock_auth_repo.generate_next_user_id.return_value = 123456789

        data = EmailRegisterRequest(
            email="test@example.com",
            username="testuser",
            password="ValidPass123!",
        )

        response, event = await service.register(data)

        # Verify response
        assert response.user.id == 123456789
        assert response.user.email == "test@example.com"
        assert response.user.username == "testuser"
        assert response.user.email_verified is False

        # Verify event
        assert event.email == "test@example.com"
        assert event.username == "testuser"
        assert len(event.token) > 0

        # Verify repository calls
        mock_auth_repo.check_email_exists.assert_called_once_with("test@example.com")
        mock_auth_repo.create_core_user.assert_called_once()
        mock_auth_repo.create_email_auth.assert_called_once()
        mock_auth_repo.insert_email_token.assert_called_once()
        mock_auth_repo.record_attempt.assert_called_with("test@example.com", "register", success=True)

    async def test_register_duplicate_email(self, mock_pool, mock_state, mock_auth_repo):
        """Registration with duplicate email raises EmailAlreadyExistsError."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.fetch_rate_limit_count.return_value = 0
        mock_auth_repo.check_email_exists.return_value = True

        data = EmailRegisterRequest(
            email="existing@example.com",
            username="testuser",
            password="ValidPass123!",
        )

        with pytest.raises(EmailAlreadyExistsError):
            await service.register(data)

        mock_auth_repo.record_attempt.assert_called_with(
            "existing@example.com", "register", success=False
        )

    async def test_register_rate_limited(self, mock_pool, mock_state, mock_auth_repo):
        """Registration when rate limited raises RateLimitExceededError."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.fetch_rate_limit_count.return_value = 10  # Over limit

        data = EmailRegisterRequest(
            email="test@example.com",
            username="testuser",
            password="ValidPass123!",
        )

        with pytest.raises(RateLimitExceededError):
            await service.register(data)

    async def test_register_invalid_email(self, mock_pool, mock_state, mock_auth_repo):
        """Registration with invalid email raises EmailValidationError."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.fetch_rate_limit_count.return_value = 0

        data = EmailRegisterRequest(
            email="not-an-email",
            username="testuser",
            password="ValidPass123!",
        )

        with pytest.raises(EmailValidationError):
            await service.register(data)

    async def test_register_invalid_password(self, mock_pool, mock_state, mock_auth_repo):
        """Registration with invalid password raises PasswordValidationError."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.fetch_rate_limit_count.return_value = 0

        data = EmailRegisterRequest(
            email="test@example.com",
            username="testuser",
            password="short",
        )

        with pytest.raises(PasswordValidationError):
            await service.register(data)

    async def test_register_invalid_username(self, mock_pool, mock_state, mock_auth_repo):
        """Registration with invalid username raises UsernameValidationError."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.fetch_rate_limit_count.return_value = 0

        data = EmailRegisterRequest(
            email="test@example.com",
            username="a" * 21,  # Too long
            password="ValidPass123!",
        )

        with pytest.raises(UsernameValidationError):
            await service.register(data)


class TestAuthServiceLogin:
    """Test login flow."""

    async def test_login_success(self, mock_pool, mock_state, mock_auth_repo):
        """Successful login returns user data."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        # Create a valid bcrypt hash for "ValidPass123!"
        password_hash = AuthService.hash_password("ValidPass123!")

        mock_auth_repo.fetch_rate_limit_count.return_value = 0
        mock_auth_repo.get_user_by_email.return_value = {
            "user_id": 1,
            "email": "test@example.com",
            "password_hash": password_hash,
            "nickname": "testuser",
            "email_verified_at": datetime.now(timezone.utc),
            "coins": 100,
            "is_mod": False,
        }

        data = EmailLoginRequest(email="test@example.com", password="ValidPass123!")
        result = await service.login(data)

        assert result.user.id == 1
        assert result.user.email == "test@example.com"
        assert result.user.username == "testuser"
        assert result.user.email_verified is True
        assert result.user.coins == 100
        assert result.user.is_mod is False

        mock_auth_repo.record_attempt.assert_called_with("test@example.com", "login", success=True)

    async def test_login_user_not_found(self, mock_pool, mock_state, mock_auth_repo):
        """Login with non-existent email raises InvalidCredentialsError."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.fetch_rate_limit_count.return_value = 0
        mock_auth_repo.get_user_by_email.return_value = None

        data = EmailLoginRequest(email="wrong@example.com", password="ValidPass123!")

        with pytest.raises(InvalidCredentialsError):
            await service.login(data)

        mock_auth_repo.record_attempt.assert_called_with("wrong@example.com", "login", success=False)

    async def test_login_wrong_password(self, mock_pool, mock_state, mock_auth_repo):
        """Login with wrong password raises InvalidCredentialsError."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        password_hash = AuthService.hash_password("CorrectPass123!")

        mock_auth_repo.fetch_rate_limit_count.return_value = 0
        mock_auth_repo.get_user_by_email.return_value = {
            "user_id": 1,
            "email": "test@example.com",
            "password_hash": password_hash,
            "nickname": "testuser",
            "email_verified_at": datetime.now(timezone.utc),
            "coins": 100,
            "is_mod": False,
        }

        data = EmailLoginRequest(email="test@example.com", password="WrongPass123!")

        with pytest.raises(InvalidCredentialsError):
            await service.login(data)

        mock_auth_repo.record_attempt.assert_called_with("test@example.com", "login", success=False)

    async def test_login_rate_limited(self, mock_pool, mock_state, mock_auth_repo):
        """Login when rate limited raises RateLimitExceededError."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.fetch_rate_limit_count.return_value = 15  # Over limit

        data = EmailLoginRequest(email="test@example.com", password="ValidPass123!")

        with pytest.raises(RateLimitExceededError):
            await service.login(data)


class TestAuthServiceEmailVerification:
    """Test email verification flow."""

    async def test_verify_email_success(self, mock_pool, mock_state, mock_auth_repo):
        """Valid verification token marks email as verified."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        token, token_hash = AuthService.generate_token()

        mock_auth_repo.get_token_with_user.return_value = {
            "user_id": 1,
            "email": "test@example.com",
            "nickname": "testuser",
            "is_mod": False,
            "used_at": None,
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
            "email_verified_at": None,
        }

        data = EmailVerifyRequest(token=token)
        result = await service.verify_email(data)

        assert result.user.id == 1
        assert result.user.email == "test@example.com"
        assert result.user.username == "testuser"
        assert result.user.email_verified is True

        mock_auth_repo.mark_token_used.assert_called_once()
        mock_auth_repo.mark_email_verified.assert_called_once()
        mock_auth_repo.invalidate_user_tokens.assert_called_once()

    async def test_verify_email_token_not_found(self, mock_pool, mock_state, mock_auth_repo):
        """Invalid token raises TokenInvalidError."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.get_token_with_user.return_value = None

        data = EmailVerifyRequest(token="invalid_token")

        with pytest.raises(TokenInvalidError):
            await service.verify_email(data)

    async def test_verify_email_token_already_used(self, mock_pool, mock_state, mock_auth_repo):
        """Already used token raises TokenAlreadyUsedError."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.get_token_with_user.return_value = {
            "user_id": 1,
            "email": "test@example.com",
            "nickname": "testuser",
            "is_mod": False,
            "used_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
            "email_verified_at": None,
        }

        data = EmailVerifyRequest(token="already_used_token")

        with pytest.raises(TokenAlreadyUsedError):
            await service.verify_email(data)

    async def test_verify_email_token_expired(self, mock_pool, mock_state, mock_auth_repo):
        """Expired token raises TokenExpiredError."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.get_token_with_user.return_value = {
            "user_id": 1,
            "email": "test@example.com",
            "nickname": "testuser",
            "is_mod": False,
            "used_at": None,
            "expires_at": datetime.now(timezone.utc) - timedelta(hours=1),  # Expired
            "email_verified_at": None,
        }

        data = EmailVerifyRequest(token="expired_token")

        with pytest.raises(TokenExpiredError):
            await service.verify_email(data)

    async def test_verify_email_already_verified(self, mock_pool, mock_state, mock_auth_repo):
        """Already verified email raises EmailAlreadyVerifiedError."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.get_token_with_user.return_value = {
            "user_id": 1,
            "email": "test@example.com",
            "nickname": "testuser",
            "is_mod": False,
            "used_at": None,
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
            "email_verified_at": datetime.now(timezone.utc),  # Already verified
        }

        data = EmailVerifyRequest(token="valid_token")

        with pytest.raises(EmailAlreadyVerifiedError):
            await service.verify_email(data)

    async def test_resend_verification_success(self, mock_pool, mock_state, mock_auth_repo):
        """Resend verification creates new token."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.fetch_rate_limit_count.return_value = 0
        mock_auth_repo.get_user_by_email.return_value = {
            "user_id": 1,
            "email": "test@example.com",
            "nickname": "testuser",
            "email_verified_at": None,
        }

        response, event = await service.resend_verification("test@example.com")

        assert "verification email" in response.message.lower()
        assert event.email == "test@example.com"
        assert event.username == "testuser"
        assert len(event.token) > 0

        mock_auth_repo.invalidate_user_tokens.assert_called_once()
        mock_auth_repo.insert_email_token.assert_called_once()

    async def test_resend_verification_user_not_found(
        self, mock_pool, mock_state, mock_auth_repo
    ):
        """Resend verification for non-existent user raises UserNotFoundError."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.fetch_rate_limit_count.return_value = 0
        mock_auth_repo.get_user_by_email.return_value = None

        with pytest.raises(UserNotFoundError):
            await service.resend_verification("nonexistent@example.com")

    async def test_resend_verification_already_verified(
        self, mock_pool, mock_state, mock_auth_repo
    ):
        """Resend verification for already verified email raises EmailAlreadyVerifiedError."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.fetch_rate_limit_count.return_value = 0
        mock_auth_repo.get_user_by_email.return_value = {
            "user_id": 1,
            "email": "test@example.com",
            "nickname": "testuser",
            "email_verified_at": datetime.now(timezone.utc),
        }

        with pytest.raises(EmailAlreadyVerifiedError):
            await service.resend_verification("test@example.com")


class TestAuthServicePasswordReset:
    """Test password reset flow."""

    async def test_request_password_reset_success(
        self, mock_pool, mock_state, mock_auth_repo
    ):
        """Request password reset creates token and returns event."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.fetch_rate_limit_count.return_value = 0
        mock_auth_repo.get_user_by_email.return_value = {
            "user_id": 1,
            "email": "test@example.com",
            "nickname": "testuser",
        }

        data = PasswordResetRequest(email="test@example.com")
        response, event = await service.request_password_reset(data)

        assert "password reset link" in response.message.lower()
        assert event is not None
        assert event.email == "test@example.com"
        assert event.username == "testuser"
        assert len(event.token) > 0

        mock_auth_repo.invalidate_user_tokens.assert_called_once()
        mock_auth_repo.insert_email_token.assert_called_once()

    async def test_request_password_reset_user_not_found(
        self, mock_pool, mock_state, mock_auth_repo
    ):
        """Request password reset for non-existent user returns generic response."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.fetch_rate_limit_count.return_value = 0
        mock_auth_repo.get_user_by_email.return_value = None

        data = PasswordResetRequest(email="nonexistent@example.com")
        response, event = await service.request_password_reset(data)

        # Should return generic message and no event
        assert "password reset link" in response.message.lower()
        assert event is None

        mock_auth_repo.record_attempt.assert_called_with(
            "nonexistent@example.com", "password_reset", success=False
        )

    async def test_confirm_password_reset_success(
        self, mock_pool, mock_state, mock_auth_repo
    ):
        """Confirm password reset updates password."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        token, token_hash = AuthService.generate_token()

        mock_auth_repo.get_token_with_user.return_value = {
            "user_id": 1,
            "email": "test@example.com",
            "nickname": "testuser",
            "is_mod": False,
            "used_at": None,
            "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
            "email_verified_at": datetime.now(timezone.utc),
        }

        data = PasswordResetConfirmRequest(token=token, password="NewValidPass123!")
        result = await service.confirm_password_reset(data)

        assert result.user.id == 1
        assert result.user.email == "test@example.com"

        mock_auth_repo.mark_token_used.assert_called_once()
        mock_auth_repo.update_password.assert_called_once()
        mock_auth_repo.invalidate_user_tokens.assert_called_once()
        mock_auth_repo.revoke_remember_tokens.assert_called_once()

    async def test_confirm_password_reset_invalid_token(
        self, mock_pool, mock_state, mock_auth_repo
    ):
        """Confirm password reset with invalid token raises TokenInvalidError."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.get_token_with_user.return_value = None

        data = PasswordResetConfirmRequest(token="invalid", password="NewValidPass123!")

        with pytest.raises(TokenInvalidError):
            await service.confirm_password_reset(data)

    async def test_confirm_password_reset_expired_token(
        self, mock_pool, mock_state, mock_auth_repo
    ):
        """Confirm password reset with expired token raises TokenExpiredError."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.get_token_with_user.return_value = {
            "user_id": 1,
            "email": "test@example.com",
            "nickname": "testuser",
            "is_mod": False,
            "used_at": None,
            "expires_at": datetime.now(timezone.utc) - timedelta(hours=1),  # Expired
            "email_verified_at": datetime.now(timezone.utc),
        }

        data = PasswordResetConfirmRequest(token="expired", password="NewValidPass123!")

        with pytest.raises(TokenExpiredError):
            await service.confirm_password_reset(data)

    async def test_confirm_password_reset_invalid_new_password(
        self, mock_pool, mock_state, mock_auth_repo
    ):
        """Confirm password reset with invalid new password raises PasswordValidationError."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        data = PasswordResetConfirmRequest(token="valid", password="weak")

        with pytest.raises(PasswordValidationError):
            await service.confirm_password_reset(data)


class TestAuthServiceSessionManagement:
    """Test session management methods."""

    async def test_session_read_uses_90_day_lifetime(self, mock_pool, mock_state, mock_auth_repo):
        """session_read passes 90-day lifetime (129600 min) to repository."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.read_session.return_value = None

        await service.session_read("session123")

        mock_auth_repo.read_session.assert_called_once_with("session123", 129600)

    async def test_session_read_with_payload(self, mock_pool, mock_state, mock_auth_repo):
        """session_read returns payload and is_mod flag."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.read_session.return_value = "session_payload_data"
        mock_auth_repo.check_is_mod.return_value = True

        result = await service.session_read("session123")

        assert result.payload == "session_payload_data"
        assert result.is_mod is True

        mock_auth_repo.read_session.assert_called_once_with("session123", 129600)
        mock_auth_repo.check_is_mod.assert_called_once_with("session123")

    async def test_session_read_no_payload(self, mock_pool, mock_state, mock_auth_repo):
        """session_read with no payload returns None and is_mod=False."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.read_session.return_value = None

        result = await service.session_read("session123")

        assert result.payload is None
        assert result.is_mod is False

        mock_auth_repo.check_is_mod.assert_not_called()

    async def test_session_write(self, mock_pool, mock_state, mock_auth_repo):
        """session_write calls repository method."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        result = await service.session_write(
            "session123",
            "payload_data",
            user_id=1,
            ip_address="127.0.0.1",
            user_agent="Mozilla/5.0",
        )

        assert result.success is True

        mock_auth_repo.write_session.assert_called_once_with(
            "session123", "payload_data", 1, "127.0.0.1", "Mozilla/5.0"
        )

    async def test_session_destroy(self, mock_pool, mock_state, mock_auth_repo):
        """session_destroy calls repository and returns deleted status."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.delete_session.return_value = True

        result = await service.session_destroy("session123")

        assert result.deleted is True

        mock_auth_repo.delete_session.assert_called_once_with("session123")

    async def test_session_gc(self, mock_pool, mock_state, mock_auth_repo):
        """session_gc deletes expired sessions and returns count."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.delete_expired_sessions.return_value = 42

        result = await service.session_gc()

        assert result.deleted_count == 42

        mock_auth_repo.delete_expired_sessions.assert_called_once_with(129600)

    async def test_session_get_user_sessions(self, mock_pool, mock_state, mock_auth_repo):
        """session_get_user_sessions returns list of sessions."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.get_user_sessions.return_value = [
            {
                "id": "session1",
                "last_activity": datetime.now(timezone.utc).isoformat(),
                "ip_address": "127.0.0.1",
                "user_agent": "Mozilla/5.0",
            },
        ]

        result = await service.session_get_user_sessions(1)

        assert len(result.sessions) == 1
        assert result.sessions[0].id == "session1"

        mock_auth_repo.get_user_sessions.assert_called_once_with(1, 129600)

    async def test_session_destroy_all_for_user(
        self, mock_pool, mock_state, mock_auth_repo
    ):
        """session_destroy_all_for_user deletes sessions and returns count."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.delete_user_sessions.return_value = 3

        result = await service.session_destroy_all_for_user(1, except_session_id="keep_this")

        assert result.destroyed_count == 3

        mock_auth_repo.delete_user_sessions.assert_called_once_with(1, "keep_this")


class TestAuthServiceRememberTokens:
    """Test remember token management."""

    async def test_create_remember_token(self, mock_pool, mock_state, mock_auth_repo):
        """create_remember_token generates token and stores it."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        result = await service.create_remember_token(
            user_id=1,
            ip_address="127.0.0.1",
            user_agent="Mozilla/5.0",
        )

        assert len(result.token) > 0

        mock_auth_repo.create_remember_token.assert_called_once()

    async def test_validate_remember_token_valid(
        self, mock_pool, mock_state, mock_auth_repo
    ):
        """validate_remember_token returns user_id for valid token."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.validate_remember_token.return_value = 1

        token, _ = AuthService.generate_token()
        result = await service.validate_remember_token(token)

        assert result.valid is True
        assert result.user_id == 1

    async def test_validate_remember_token_invalid(
        self, mock_pool, mock_state, mock_auth_repo
    ):
        """validate_remember_token returns None for invalid token."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.validate_remember_token.return_value = None

        result = await service.validate_remember_token("invalid_token")

        assert result.valid is False
        assert result.user_id is None

    async def test_revoke_remember_tokens(self, mock_pool, mock_state, mock_auth_repo):
        """revoke_remember_tokens revokes all tokens for user."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.revoke_remember_tokens.return_value = 2

        result = await service.revoke_remember_tokens(1)

        assert result.revoked_count == 2

        mock_auth_repo.revoke_remember_tokens.assert_called_once_with(1)


class TestAuthServiceUserStatus:
    """Test user status methods."""

    async def test_get_auth_status_success(self, mock_pool, mock_state, mock_auth_repo):
        """get_auth_status returns masked email and verification status."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.get_auth_status.return_value = {
            "email": "testuser@example.com",
            "email_verified_at": datetime.now(timezone.utc),
        }

        result = await service.get_auth_status(1)

        assert result.email == "t***@example.com"  # Masked
        assert result.email_verified is True

    async def test_get_auth_status_user_not_found(
        self, mock_pool, mock_state, mock_auth_repo
    ):
        """get_auth_status raises UserNotFoundError if no auth data."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.get_auth_status.return_value = None

        with pytest.raises(UserNotFoundError):
            await service.get_auth_status(999)

    async def test_logout_all_sessions(self, mock_pool, mock_state, mock_auth_repo):
        """logout_all_sessions deletes all sessions for user."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.delete_user_sessions.return_value = 5

        count = await service.logout_all_sessions(1, except_session_id="keep_this")

        assert count == 5

        mock_auth_repo.delete_user_sessions.assert_called_once_with(1, "keep_this")

    async def test_revoke_all_remember_tokens(self, mock_pool, mock_state, mock_auth_repo):
        """revoke_all_remember_tokens revokes all tokens for user."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.revoke_remember_tokens.return_value = 3

        count = await service.revoke_all_remember_tokens(1)

        assert count == 3

        mock_auth_repo.revoke_remember_tokens.assert_called_once_with(1)


class TestAuthServiceErrorTranslation:
    """Test repository exception translation to domain exceptions."""

    async def test_register_unique_constraint_email(
        self, mock_pool, mock_state, mock_auth_repo
    ):
        """UniqueConstraintViolationError on email raises EmailAlreadyExistsError."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.fetch_rate_limit_count.return_value = 0
        mock_auth_repo.check_email_exists.return_value = False
        mock_auth_repo.generate_next_user_id.return_value = 123456789
        mock_auth_repo.create_email_auth.side_effect = UniqueConstraintViolationError(
            constraint_name="email_auth_email_key",
            table="email_auth",
        )

        data = EmailRegisterRequest(
            email="duplicate@example.com",
            username="testuser",
            password="ValidPass123!",
        )

        with pytest.raises(EmailAlreadyExistsError):
            await service.register(data)

    async def test_register_foreign_key_violation(
        self, mock_pool, mock_state, mock_auth_repo
    ):
        """ForeignKeyViolationError during registration raises EmailAlreadyExistsError."""
        service = AuthService(mock_pool, mock_state, mock_auth_repo)

        mock_auth_repo.fetch_rate_limit_count.return_value = 0
        mock_auth_repo.check_email_exists.return_value = False
        mock_auth_repo.generate_next_user_id.return_value = 123456789
        mock_auth_repo.create_core_user.side_effect = ForeignKeyViolationError(
            constraint_name="some_fkey",
            table="core.users",
        )

        data = EmailRegisterRequest(
            email="test@example.com",
            username="testuser",
            password="ValidPass123!",
        )

        with pytest.raises(EmailAlreadyExistsError):
            await service.register(data)
