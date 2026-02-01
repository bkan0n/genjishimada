"""Integration tests for Auth v4 controller.

Tests HTTP interface: request/response serialization,
error translation, and full stack flow through real database.
"""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.domain_auth,
]


class TestRegister:
    """POST /api/v3/auth/register"""

    async def test_happy_path(self, test_client):
        """Register with valid data creates user."""
        payload = {
            "email": "newuser@example.com",
            "password": "SecurePassword123!",
            "username": "newuser",
        }

        response = await test_client.post("/api/v3/auth/register", json=payload)

        assert response.status_code == 201
        data = response.json()
        assert "user" in data
        assert "verification_email_sent" in data

        # Validate user structure
        user = data["user"]
        assert "id" in user
        assert isinstance(user["id"], int)
        assert user["email"] == "newuser@example.com"
        assert user["username"] == "newuser"
        assert user["email_verified"] is False
        assert isinstance(data["verification_email_sent"], bool)

    async def test_duplicate_email_returns_400(self, test_client):
        """Registering with duplicate email returns 400."""
        payload = {
            "email": "duplicate@example.com",
            "password": "SecurePassword123!",
            "username": "user1",
        }

        # First registration
        await test_client.post("/api/v3/auth/register", json=payload)

        # Second registration with same email
        payload["username"] = "user2"
        response = await test_client.post("/api/v3/auth/register", json=payload)

        assert response.status_code == 400

    async def test_invalid_email_format_returns_400(self, test_client):
        """Registration with invalid email format returns 400."""
        payload = {
            "email": "not-an-email",
            "password": "SecurePassword123!",
            "username": "testuser",
        }

        response = await test_client.post("/api/v3/auth/register", json=payload)

        assert response.status_code == 400

    async def test_weak_password_returns_400(self, test_client):
        """Registration with weak password returns 400."""
        payload = {
            "email": "test@example.com",
            "password": "weak",
            "username": "testuser",
        }

        response = await test_client.post("/api/v3/auth/register", json=payload)

        assert response.status_code == 400

    async def test_invalid_username_returns_400(self, test_client):
        """Registration with invalid username returns 400."""
        payload = {
            "email": "test@example.com",
            "password": "SecurePassword123!",
            "username": "",  # Empty username
        }

        response = await test_client.post("/api/v3/auth/register", json=payload)

        assert response.status_code == 400


class TestLogin:
    """POST /api/v3/auth/login"""

    async def test_happy_path(self, test_client):
        """Login with valid credentials returns user."""
        # Register user first
        register_payload = {
            "email": "logintest@example.com",
            "password": "SecurePassword123!",
            "username": "loginuser",
        }
        await test_client.post("/api/v3/auth/register", json=register_payload)

        # Login
        login_payload = {
            "email": "logintest@example.com",
            "password": "SecurePassword123!",
        }
        response = await test_client.post("/api/v3/auth/login", json=login_payload)

        assert response.status_code == 200
        data = response.json()
        assert "user" in data

        # Validate user structure
        user = data["user"]
        assert "id" in user
        assert isinstance(user["id"], int)
        assert user["email"] == "logintest@example.com"
        assert user["username"] == "loginuser"
        assert "email_verified" in user
        assert isinstance(user["email_verified"], bool)
        assert "coins" in user
        assert "is_mod" in user

    async def test_invalid_credentials_returns_401(self, test_client):
        """Login with invalid password returns 401."""
        payload = {
            "email": "nonexistent@example.com",
            "password": "wrongpassword",
        }

        response = await test_client.post("/api/v3/auth/login", json=payload)

        assert response.status_code == 401

    async def test_wrong_password_returns_401(self, test_client):
        """Login with correct email but wrong password returns 401."""
        # Register user first
        register_payload = {
            "email": "rightuser@example.com",
            "password": "CorrectPassword123!",
            "username": "rightuser",
        }
        await test_client.post("/api/v3/auth/register", json=register_payload)

        # Login with wrong password
        login_payload = {
            "email": "rightuser@example.com",
            "password": "WrongPassword123!",
        }
        response = await test_client.post("/api/v3/auth/login", json=login_payload)

        assert response.status_code == 401


class TestVerifyEmail:
    """POST /api/v3/auth/verify-email"""

    async def test_valid_token_verifies_email(self, test_client, asyncpg_conn):
        """Valid verification token verifies email."""
        # Register user
        register_payload = {
            "email": "verifytest@example.com",
            "password": "SecurePassword123!",
            "username": "verifyuser",
        }
        register_response = await test_client.post("/api/v3/auth/register", json=register_payload)
        user_id = register_response.json()["user"]["id"]

        # Generate verification token and insert it into database
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

        # Delete existing verification tokens for this user
        await asyncpg_conn.execute(
            "DELETE FROM users.email_tokens WHERE user_id = $1 AND token_type = $2",
            user_id,
            "verification",
        )

        # Insert new token
        await asyncpg_conn.execute(
            """
            INSERT INTO users.email_tokens (user_id, token_hash, token_type, expires_at)
            VALUES ($1, $2, $3, $4)
            """,
            user_id,
            token_hash,
            "verification",
            expires_at,
        )

        # Verify email with real token
        payload = {"token": token}
        response = await test_client.post("/api/v3/auth/verify-email", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert "user" in data
        assert data["user"]["email_verified"] is True
        assert data["message"] == "Email verified successfully."

    async def test_already_verified_email_returns_400(self, test_client, asyncpg_conn):
        """Attempting to verify already verified email returns 400."""
        # Register user
        register_payload = {
            "email": "alreadyverified@example.com",
            "password": "SecurePassword123!",
            "username": "alreadyverified",
        }
        register_response = await test_client.post("/api/v3/auth/register", json=register_payload)
        user_id = register_response.json()["user"]["id"]

        # Generate and use verification token
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        expires_at = datetime.now(timezone.utc) + timedelta(hours=24)

        # Delete existing tokens
        await asyncpg_conn.execute(
            "DELETE FROM users.email_tokens WHERE user_id = $1 AND token_type = $2",
            user_id,
            "verification",
        )

        # Insert token
        await asyncpg_conn.execute(
            """
            INSERT INTO users.email_tokens (user_id, token_hash, token_type, expires_at)
            VALUES ($1, $2, $3, $4)
            """,
            user_id,
            token_hash,
            "verification",
            expires_at,
        )

        # Verify email first time
        payload = {"token": token}
        first_response = await test_client.post("/api/v3/auth/verify-email", json=payload)
        assert first_response.status_code == 200

        # Try to verify again with a new token
        token2 = secrets.token_urlsafe(32)
        token_hash2 = hashlib.sha256(token2.encode("utf-8")).hexdigest()

        # Delete existing tokens and insert new one
        await asyncpg_conn.execute(
            "DELETE FROM users.email_tokens WHERE user_id = $1 AND token_type = $2",
            user_id,
            "verification",
        )

        await asyncpg_conn.execute(
            """
            INSERT INTO users.email_tokens (user_id, token_hash, token_type, expires_at)
            VALUES ($1, $2, $3, $4)
            """,
            user_id,
            token_hash2,
            "verification",
            expires_at,
        )

        payload2 = {"token": token2}
        second_response = await test_client.post("/api/v3/auth/verify-email", json=payload2)
        assert second_response.status_code == 400

    async def test_invalid_token_returns_400(self, test_client):
        """Invalid token returns 400."""
        payload = {"token": "invalid-token"}

        response = await test_client.post("/api/v3/auth/verify-email", json=payload)

        assert response.status_code == 400


class TestResendVerification:
    """POST /api/v3/auth/resend-verification"""

    async def test_resend_for_registered_user(self, test_client):
        """Resend verification for registered unverified user."""
        # Register user first
        register_payload = {
            "email": "resendtest@example.com",
            "password": "SecurePassword123!",
            "username": "resenduser",
        }
        await test_client.post("/api/v3/auth/register", json=register_payload)

        # Resend verification
        payload = {"email": "resendtest@example.com"}
        response = await test_client.post("/api/v3/auth/resend-verification", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert "message" in data

    async def test_resend_for_nonexistent_email_returns_404(self, test_client):
        """Resend verification for non-existent email returns 404."""
        payload = {"email": "nonexistent@example.com"}

        response = await test_client.post("/api/v3/auth/resend-verification", json=payload)

        assert response.status_code == 404


class TestForgotPassword:
    """POST /api/v3/auth/forgot-password"""

    async def test_request_password_reset_for_existing_user(self, test_client):
        """Request password reset for existing email."""
        # Register user first
        register_payload = {
            "email": "resettest@example.com",
            "password": "SecurePassword123!",
            "username": "resetuser",
        }
        await test_client.post("/api/v3/auth/register", json=register_payload)

        # Request password reset
        payload = {"email": "resettest@example.com"}
        response = await test_client.post("/api/v3/auth/forgot-password", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert "message" in data

    async def test_request_for_nonexistent_email_returns_200(self, test_client):
        """Request password reset for non-existent email still returns 200 (security)."""
        payload = {"email": "nonexistent@example.com"}

        response = await test_client.post("/api/v3/auth/forgot-password", json=payload)

        # Returns 200 even for non-existent emails to prevent email enumeration
        assert response.status_code == 200
        data = response.json()
        assert "message" in data


class TestResetPassword:
    """POST /api/v3/auth/reset-password"""

    async def test_reset_with_valid_token(self, test_client, asyncpg_conn):
        """Reset password with valid token."""
        # Register user
        register_payload = {
            "email": "passwordreset@example.com",
            "password": "OldPassword123!",
            "username": "resetuser",
        }
        register_response = await test_client.post("/api/v3/auth/register", json=register_payload)
        user_id = register_response.json()["user"]["id"]

        # Generate password reset token and insert it into database
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        # Delete existing password reset tokens
        await asyncpg_conn.execute(
            "DELETE FROM users.email_tokens WHERE user_id = $1 AND token_type = $2",
            user_id,
            "password_reset",
        )

        # Insert new token
        await asyncpg_conn.execute(
            """
            INSERT INTO users.email_tokens (user_id, token_hash, token_type, expires_at)
            VALUES ($1, $2, $3, $4)
            """,
            user_id,
            token_hash,
            "password_reset",
            expires_at,
        )

        # Reset password with real token
        payload = {
            "token": token,
            "password": "NewSecurePassword123!",
        }
        response = await test_client.post("/api/v3/auth/reset-password", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert "user" in data
        assert data["message"] == "Password reset successfully."
        assert data["user"]["id"] == user_id

        # Verify can login with new password
        login_payload = {
            "email": "passwordreset@example.com",
            "password": "NewSecurePassword123!",
        }
        login_response = await test_client.post("/api/v3/auth/login", json=login_payload)
        assert login_response.status_code == 200

        # Verify old password doesn't work
        old_login_payload = {
            "email": "passwordreset@example.com",
            "password": "OldPassword123!",
        }
        old_login_response = await test_client.post("/api/v3/auth/login", json=old_login_payload)
        assert old_login_response.status_code == 401

    async def test_reset_with_invalid_token_returns_400(self, test_client):
        """Reset password with invalid token returns 400."""
        payload = {
            "token": "invalid-token",
            "password": "NewSecurePassword123!",
        }

        response = await test_client.post("/api/v3/auth/reset-password", json=payload)

        assert response.status_code == 400

    async def test_reset_with_weak_password_returns_400(self, test_client):
        """Reset password with weak password returns 400."""
        payload = {
            "token": "some-token",
            "password": "weak",
        }

        response = await test_client.post("/api/v3/auth/reset-password", json=payload)

        assert response.status_code == 400


class TestGetAuthStatus:
    """GET /api/v3/auth/status/{user_id}"""

    async def test_get_status_for_email_auth_user(self, test_client):
        """Get auth status for user with email authentication."""
        # Register user to create email auth
        register_payload = {
            "email": "statustest@example.com",
            "password": "SecurePassword123!",
            "username": "statususer",
        }
        register_response = await test_client.post("/api/v3/auth/register", json=register_payload)
        user_id = register_response.json()["user"]["id"]

        # Get auth status
        response = await test_client.get(f"/api/v3/auth/status/{user_id}")

        assert response.status_code == 200
        data = response.json()
        assert "email" in data
        assert "***" in data["email"]  # Email should be masked
        assert "email_verified" in data
        assert data["email_verified"] is False  # New users aren't verified yet

    async def test_get_status_for_nonexistent_user_returns_404(self, test_client):
        """Get auth status for non-existent user returns 404."""
        response = await test_client.get("/api/v3/auth/status/999999999")

        assert response.status_code == 404

    async def test_get_status_for_discord_only_user_returns_404(self, test_client, create_test_user):
        """Get auth status for Discord-only user (no email auth) returns 404."""
        user_id = await create_test_user()  # Creates Discord user, not email auth

        response = await test_client.get(f"/api/v3/auth/status/{user_id}")

        assert response.status_code == 404


class TestSessionRead:
    """GET /api/v3/auth/sessions/{session_id}"""

    async def test_read_nonexistent_session(self, test_client):
        """Read non-existent session returns empty payload."""
        session_id = "nonexistent-session-id"

        response = await test_client.get(f"/api/v3/auth/sessions/{session_id}")

        assert response.status_code == 200
        data = response.json()
        assert "payload" in data
        assert "is_mod" in data
        assert data["payload"] is None
        assert isinstance(data["is_mod"], bool)


class TestSessionWrite:
    """PUT /api/v3/auth/sessions/{session_id}"""

    async def test_write_session_data(self, test_client):
        """Write session data."""
        session_id = "test-session-id"
        payload = {"payload": "base64encodeddata", "user_id": None}

        response = await test_client.put(f"/api/v3/auth/sessions/{session_id}", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    async def test_write_and_read_session_roundtrip(self, test_client):
        """Write session data and read it back."""
        session_id = "roundtrip-session"
        payload = {"payload": "test-session-data", "user_id": None}

        # Write session
        write_response = await test_client.put(f"/api/v3/auth/sessions/{session_id}", json=payload)
        assert write_response.status_code == 200

        # Read session back
        read_response = await test_client.get(f"/api/v3/auth/sessions/{session_id}")
        assert read_response.status_code == 200
        data = read_response.json()
        assert data["payload"] == "test-session-data"


class TestSessionDestroy:
    """DELETE /api/v3/auth/sessions/{session_id}"""

    async def test_destroy_nonexistent_session(self, test_client):
        """Destroy non-existent session returns deleted=False."""
        session_id = "nonexistent-session-id"

        response = await test_client.delete(f"/api/v3/auth/sessions/{session_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["deleted"] is False


class TestSessionGc:
    """POST /api/v3/auth/sessions/gc"""

    async def test_garbage_collect_sessions(self, test_client):
        """Garbage collect expired sessions."""
        response = await test_client.post("/api/v3/auth/sessions/gc")

        assert response.status_code == 200
        data = response.json()
        assert "deleted_count" in data
        assert isinstance(data["deleted_count"], int)


class TestGetUserSessions:
    """GET /api/v3/auth/sessions/user/{user_id}"""

    async def test_get_user_sessions(self, test_client, create_test_user):
        """Get all sessions for a user."""
        user_id = await create_test_user()

        response = await test_client.get(f"/api/v3/auth/sessions/user/{user_id}")

        assert response.status_code == 200
        data = response.json()
        assert "sessions" in data
        assert isinstance(data["sessions"], list)


class TestDestroyUserSessions:
    """DELETE /api/v3/auth/sessions/user/{user_id}"""

    async def test_destroy_all_user_sessions(self, test_client, create_test_user):
        """Destroy all sessions for a user."""
        user_id = await create_test_user()

        response = await test_client.delete(f"/api/v3/auth/sessions/user/{user_id}")

        assert response.status_code == 200
        data = response.json()
        assert "destroyed_count" in data
        assert isinstance(data["destroyed_count"], int)


class TestCreateRememberToken:
    """POST /api/v3/auth/remember-token"""

    async def test_create_remember_token(self, test_client, create_test_user):
        """Create remember token for user."""
        user_id = await create_test_user()
        payload = {"user_id": user_id}

        response = await test_client.post("/api/v3/auth/remember-token", json=payload)

        assert response.status_code == 201
        data = response.json()
        assert "token" in data
        assert isinstance(data["token"], str)
        assert len(data["token"]) > 0

    async def test_create_and_validate_remember_token(self, test_client, create_test_user):
        """Create remember token and validate it."""
        user_id = await create_test_user()

        # Create token
        create_payload = {"user_id": user_id}
        create_response = await test_client.post("/api/v3/auth/remember-token", json=create_payload)
        token = create_response.json()["token"]

        # Validate token
        validate_payload = {"token": token}
        validate_response = await test_client.post("/api/v3/auth/remember-token/validate", json=validate_payload)

        assert validate_response.status_code == 200
        data = validate_response.json()
        assert data["valid"] is True
        assert data["user_id"] == user_id


class TestValidateRememberToken:
    """POST /api/v3/auth/remember-token/validate"""

    async def test_validate_invalid_token(self, test_client):
        """Validate an invalid remember token returns valid=False."""
        payload = {"token": "invalid-remember-token"}

        response = await test_client.post("/api/v3/auth/remember-token/validate", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["valid"] is False
        assert data["user_id"] is None


class TestRevokeRememberTokens:
    """DELETE /api/v3/auth/remember-token/user/{user_id}"""

    async def test_revoke_user_tokens(self, test_client, create_test_user):
        """Revoke all remember tokens for a user."""
        user_id = await create_test_user()

        response = await test_client.delete(f"/api/v3/auth/remember-token/user/{user_id}")

        assert response.status_code == 200
        data = response.json()
        assert "revoked_count" in data
        assert isinstance(data["revoked_count"], int)

    async def test_revoke_tokens_invalidates_them(self, test_client, create_test_user):
        """Revoked tokens become invalid."""
        user_id = await create_test_user()

        # Create token
        create_payload = {"user_id": user_id}
        create_response = await test_client.post("/api/v3/auth/remember-token", json=create_payload)
        token = create_response.json()["token"]

        # Revoke all tokens for user
        await test_client.delete(f"/api/v3/auth/remember-token/user/{user_id}")

        # Try to validate revoked token
        validate_payload = {"token": token}
        validate_response = await test_client.post("/api/v3/auth/remember-token/validate", json=validate_payload)

        assert validate_response.status_code == 200
        data = validate_response.json()
        assert data["valid"] is False
        assert data["user_id"] is None
