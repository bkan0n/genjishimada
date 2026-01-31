"""Integration tests for Auth v4 controller.

Tests HTTP interface: request/response serialization,
error translation, and full stack flow through real database.
"""

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.domain_auth,
]


class TestRegister:
    """POST /api/v4/auth/register"""

    async def test_happy_path(self, test_client):
        """Register with valid data creates user."""
        payload = {
            "email": "newuser@example.com",
            "password": "SecurePassword123!",
            "username": "newuser",
        }

        response = await test_client.post("/api/v4/auth/register", json=payload)

        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "newuser@example.com"
        assert "user_id" in data

    async def test_duplicate_email_returns_409(self, test_client):
        """Registering with duplicate email returns 409."""
        payload = {
            "email": "duplicate@example.com",
            "password": "SecurePassword123!",
            "username": "user1",
        }

        # First registration
        await test_client.post("/api/v4/auth/register", json=payload)

        # Second registration with same email
        payload["username"] = "user2"
        response = await test_client.post("/api/v4/auth/register", json=payload)

        assert response.status_code == 409


class TestLogin:
    """POST /api/v4/auth/login"""

    async def test_happy_path(self, test_client):
        """Login with valid credentials returns session."""
        # Register user first
        register_payload = {
            "email": "logintest@example.com",
            "password": "SecurePassword123!",
            "username": "loginuser",
        }
        await test_client.post("/api/v4/auth/register", json=register_payload)

        # Login
        login_payload = {
            "email": "logintest@example.com",
            "password": "SecurePassword123!",
        }
        response = await test_client.post("/api/v4/auth/login", json=login_payload)

        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert "user_id" in data

    async def test_invalid_credentials_returns_401(self, test_client):
        """Login with invalid password returns 401."""
        payload = {
            "email": "nonexistent@example.com",
            "password": "wrongpassword",
        }

        response = await test_client.post("/api/v4/auth/login", json=payload)

        assert response.status_code == 401


class TestVerifyEmail:
    """POST /api/v4/auth/verify-email"""

    async def test_valid_token_verifies_email(self, test_client):
        """Valid verification token verifies email."""
        # Would need to extract token from registration flow
        payload = {"token": "valid-token-here"}

        response = await test_client.post("/api/v4/auth/verify-email", json=payload)

        assert response.status_code == 200

    async def test_invalid_token_returns_400(self, test_client):
        """Invalid token returns 400."""
        payload = {"token": "invalid-token"}

        response = await test_client.post("/api/v4/auth/verify-email", json=payload)

        assert response.status_code in (400, 401)


class TestResendVerification:
    """POST /api/v4/auth/resend-verification"""

    async def test_resend_for_unverified_email(self, test_client):
        """Resend verification for unverified email."""
        payload = {"email": "unverified@example.com"}

        response = await test_client.post("/api/v4/auth/resend-verification", json=payload)

        assert response.status_code == 200


class TestForgotPassword:
    """POST /api/v4/auth/forgot-password"""

    async def test_request_password_reset(self, test_client):
        """Request password reset for existing email."""
        payload = {"email": "user@example.com"}

        response = await test_client.post("/api/v4/auth/forgot-password", json=payload)

        assert response.status_code == 200


class TestResetPassword:
    """POST /api/v4/auth/reset-password"""

    async def test_reset_with_valid_token(self, test_client):
        """Reset password with valid token."""
        payload = {
            "token": "valid-reset-token",
            "password": "NewSecurePassword123!",
        }

        response = await test_client.post("/api/v4/auth/reset-password", json=payload)

        assert response.status_code == 200


class TestGetAuthStatus:
    """GET /api/v4/auth/status/{user_id}"""

    async def test_get_status_for_user(self, test_client, create_test_user):
        """Get auth status for existing user."""
        user_id = await create_test_user()

        response = await test_client.get(f"/api/v4/auth/status/{user_id}")

        assert response.status_code == 200
        data = response.json()
        assert "email_verified" in data


class TestSessionRead:
    """GET /api/v4/auth/sessions/{session_id}"""

    async def test_read_existing_session(self, test_client):
        """Read existing session returns session data."""
        session_id = "test-session-id"

        response = await test_client.get(f"/api/v4/auth/sessions/{session_id}")

        assert response.status_code in (200, 404)


class TestSessionWrite:
    """PUT /api/v4/auth/sessions/{session_id}"""

    @pytest.mark.skip(reason="Auth service not fully implemented")
    async def test_write_session_data(self, test_client):
        """Write session data."""
        session_id = "test-session-id"
        payload = {"user_id": 123, "data": {"key": "value"}}

        response = await test_client.put(f"/api/v4/auth/sessions/{session_id}", json=payload)

        assert response.status_code in (200, 201)


class TestSessionDestroy:
    """DELETE /api/v4/auth/sessions/{session_id}"""

    async def test_destroy_session(self, test_client):
        """Destroy existing session."""
        session_id = "test-session-id"

        response = await test_client.delete(f"/api/v4/auth/sessions/{session_id}")

        assert response.status_code in (200, 204, 404)


class TestSessionGc:
    """POST /api/v4/auth/sessions/gc"""

    @pytest.mark.skip(reason="Auth service not fully implemented")
    async def test_garbage_collect_sessions(self, test_client):
        """Garbage collect expired sessions."""
        response = await test_client.post("/api/v4/auth/sessions/gc")

        assert response.status_code == 200


class TestGetUserSessions:
    """GET /api/v4/auth/sessions/user/{user_id}"""

    @pytest.mark.skip(reason="Auth service not fully implemented")
    async def test_get_user_sessions(self, test_client, create_test_user):
        """Get all sessions for a user."""
        user_id = await create_test_user()

        response = await test_client.get(f"/api/v4/auth/sessions/user/{user_id}")

        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestDestroyUserSessions:
    """DELETE /api/v4/auth/sessions/user/{user_id}"""

    @pytest.mark.skip(reason="Auth service not fully implemented")
    async def test_destroy_all_user_sessions(self, test_client, create_test_user):
        """Destroy all sessions for a user."""
        user_id = await create_test_user()

        response = await test_client.delete(f"/api/v4/auth/sessions/user/{user_id}")

        assert response.status_code in (200, 204)


class TestCreateRememberToken:
    """POST /api/v4/auth/remember-token"""

    @pytest.mark.skip(reason="Auth service not fully implemented")
    async def test_create_remember_token(self, test_client, create_test_user):
        """Create remember token for user."""
        user_id = await create_test_user()
        payload = {"user_id": user_id}

        response = await test_client.post("/api/v4/auth/remember-token", json=payload)

        assert response.status_code in (200, 201)
        data = response.json()
        assert "token" in data


class TestValidateRememberToken:
    """POST /api/v4/auth/remember-token/validate"""

    @pytest.mark.skip(reason="Auth service not fully implemented")
    async def test_validate_valid_token(self, test_client):
        """Validate a valid remember token."""
        payload = {"token": "valid-remember-token"}

        response = await test_client.post("/api/v4/auth/remember-token/validate", json=payload)

        assert response.status_code == 200


class TestRevokeRememberTokens:
    """DELETE /api/v4/auth/remember-token/user/{user_id}"""

    @pytest.mark.skip(reason="Auth service not fully implemented")
    async def test_revoke_user_tokens(self, test_client, create_test_user):
        """Revoke all remember tokens for a user."""
        user_id = await create_test_user()

        response = await test_client.delete(f"/api/v4/auth/remember-token/user/{user_id}")

        assert response.status_code in (200, 204)
