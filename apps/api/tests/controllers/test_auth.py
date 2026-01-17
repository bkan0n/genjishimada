import pytest
from litestar import Litestar
from litestar.status_codes import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_400_BAD_REQUEST,
    HTTP_401_UNAUTHORIZED,
)
from litestar.testing import AsyncTestClient

# ruff: noqa: D102, D103, ANN001, ANN201


class TestAuthEndpoints:
    """Tests for authentication endpoints."""

    # =========================================================================
    # LOGIN TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_login_valid_credentials(self, test_client: AsyncTestClient[Litestar]):
        """Test login with valid email and password."""
        response = await test_client.post(
            "/api/v3/auth/login",
            json={"email": "verified@test.com", "password": "TestPassword1!"},
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data["user"]["id"] == 100
        assert data["user"]["email"] == "verified@test.com"
        assert data["user"]["username"] == "EmailAuthUser"
        assert data["user"]["email_verified"] is True

    @pytest.mark.asyncio
    async def test_login_invalid_password(self, test_client: AsyncTestClient[Litestar]):
        """Test login with wrong password returns 401."""
        response = await test_client.post(
            "/api/v3/auth/login",
            json={"email": "verified@test.com", "password": "WrongPassword1!"},
        )
        assert response.status_code == HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_login_nonexistent_email(self, test_client: AsyncTestClient[Litestar]):
        """Test login with non-existent email returns 401."""
        response = await test_client.post(
            "/api/v3/auth/login",
            json={"email": "nonexistent@test.com", "password": "TestPassword1!"},
        )
        assert response.status_code == HTTP_401_UNAUTHORIZED

    @pytest.mark.asyncio
    async def test_login_unverified_user(self, test_client: AsyncTestClient[Litestar]):
        """Test login works for unverified user but shows unverified status."""
        response = await test_client.post(
            "/api/v3/auth/login",
            json={"email": "unverified@test.com", "password": "TestPassword1!"},
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data["user"]["id"] == 101
        assert data["user"]["email_verified"] is False

    # =========================================================================
    # REGISTRATION TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_register_new_user(self, test_client: AsyncTestClient[Litestar]):
        """Test registering a new user with valid data."""
        response = await test_client.post(
            "/api/v3/auth/register",
            json={
                "email": "newuser@test.com",
                "password": "ValidPassword1!",
                "username": "NewTestUser",
            },
        )
        assert response.status_code == HTTP_201_CREATED
        data = response.json()
        assert data["user"]["email"] == "newuser@test.com"
        assert data["user"]["username"] == "NewTestUser"
        assert data["user"]["email_verified"] is False

    @pytest.mark.asyncio
    async def test_register_duplicate_email(self, test_client: AsyncTestClient[Litestar]):
        """Test registration with existing email fails."""
        response = await test_client.post(
            "/api/v3/auth/register",
            json={
                "email": "verified@test.com",
                "password": "ValidPassword1!",
                "username": "DuplicateUser",
            },
        )
        assert response.status_code == HTTP_400_BAD_REQUEST

    @pytest.mark.asyncio
    async def test_register_weak_password(self, test_client: AsyncTestClient[Litestar]):
        """Test registration with weak password fails."""
        response = await test_client.post(
            "/api/v3/auth/register",
            json={
                "email": "weakpass@test.com",
                "password": "weak",
                "username": "WeakPassUser",
            },
        )
        assert response.status_code == HTTP_400_BAD_REQUEST

    @pytest.mark.asyncio
    async def test_register_invalid_email(self, test_client: AsyncTestClient[Litestar]):
        """Test registration with invalid email format fails."""
        response = await test_client.post(
            "/api/v3/auth/register",
            json={
                "email": "not-an-email",
                "password": "ValidPassword1!",
                "username": "InvalidEmailUser",
            },
        )
        assert response.status_code == HTTP_400_BAD_REQUEST

    # =========================================================================
    # SESSION TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_session_read_existing(self, test_client: AsyncTestClient[Litestar]):
        """Test reading an existing session."""
        response = await test_client.get("/api/v3/auth/sessions/test-session-id-123")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data["payload"] == "eyJ0ZXN0IjoidmFsdWUifQ=="
        assert data["is_mod"] is True

    @pytest.mark.asyncio
    async def test_session_read_nonexistent(self, test_client: AsyncTestClient[Litestar]):
        """Test reading non-existent session returns null payload."""
        response = await test_client.get("/api/v3/auth/sessions/nonexistent-session")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data["payload"] is None

    @pytest.mark.asyncio
    async def test_session_write_new(self, test_client: AsyncTestClient[Litestar]):
        """Test writing a new session."""
        response = await test_client.put(
            "/api/v3/auth/sessions/new-test-session",
            json={"payload": "eyJ0ZXN0IjoibmV3In0=", "user_id": 102},
        )
        assert response.status_code == HTTP_200_OK
        assert response.json()["success"] is True

        # Verify it was created
        response = await test_client.get("/api/v3/auth/sessions/new-test-session")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data["payload"] == "eyJ0ZXN0IjoibmV3In0="

    @pytest.mark.asyncio
    async def test_session_destroy(self, test_client: AsyncTestClient[Litestar]):
        """Test destroying a session."""
        # First create a session to destroy
        await test_client.put(
            "/api/v3/auth/sessions/session-to-destroy",
            json={"payload": "eyJ0ZXN0IjoidGVtcCJ9", "user_id": 103},
        )

        # Destroy it
        response = await test_client.delete("/api/v3/auth/sessions/session-to-destroy")
        assert response.status_code == HTTP_200_OK
        assert response.json()["deleted"] is True

        # Verify it's gone
        response = await test_client.get("/api/v3/auth/sessions/session-to-destroy")
        assert response.json()["payload"] is None

    @pytest.mark.asyncio
    async def test_get_user_sessions(self, test_client: AsyncTestClient[Litestar]):
        """Test getting all sessions for a user."""
        response = await test_client.get("/api/v3/auth/sessions/user/102")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert "sessions" in data
        # User 102 has 2 pre-seeded sessions
        assert len(data["sessions"]) >= 2

    @pytest.mark.asyncio
    async def test_destroy_all_user_sessions(self, test_client: AsyncTestClient[Litestar]):
        """Test destroying all sessions for a user except one."""
        # First, create some test sessions
        await test_client.put(
            "/api/v3/auth/sessions/user103-session1",
            json={"payload": "eyJ0ZXN0IjoiMSJ9", "user_id": 103},
        )
        await test_client.put(
            "/api/v3/auth/sessions/user103-session2",
            json={"payload": "eyJ0ZXN0IjoiMiJ9", "user_id": 103},
        )

        # Destroy all except one
        response = await test_client.delete(
            "/api/v3/auth/sessions/user/103?except_session_id=user103-session1"
        )
        assert response.status_code == HTTP_200_OK
        assert response.json()["destroyed_count"] >= 1

    # =========================================================================
    # SESSION GC TEST
    # =========================================================================

    @pytest.mark.asyncio
    async def test_session_gc(self, test_client: AsyncTestClient[Litestar]):
        """Test session garbage collection."""
        response = await test_client.post("/api/v3/auth/sessions/gc")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert "deleted_count" in data

    # =========================================================================
    # AUTH STATUS TEST
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_auth_status_verified(self, test_client: AsyncTestClient[Litestar]):
        """Test getting auth status for verified user."""
        response = await test_client.get("/api/v3/auth/status/100")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data["email_verified"] is True
        # Email should be masked
        assert "***" in data["email"]

    @pytest.mark.asyncio
    async def test_get_auth_status_unverified(self, test_client: AsyncTestClient[Litestar]):
        """Test getting auth status for unverified user."""
        response = await test_client.get("/api/v3/auth/status/101")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data["email_verified"] is False

    @pytest.mark.asyncio
    async def test_get_auth_status_no_email_auth(self, test_client: AsyncTestClient[Litestar]):
        """Test getting auth status for user without email auth returns null."""
        response = await test_client.get("/api/v3/auth/status/1")
        assert response.status_code == HTTP_200_OK
        assert response.json() is None

    # =========================================================================
    # PASSWORD RESET REQUEST TEST
    # =========================================================================

    @pytest.mark.asyncio
    async def test_forgot_password_existing_email(self, test_client: AsyncTestClient[Litestar]):
        """Test password reset request for existing email."""
        response = await test_client.post(
            "/api/v3/auth/forgot-password",
            json={"email": "verified@test.com"},
        )
        assert response.status_code == HTTP_200_OK
        # Should always return same message to prevent email enumeration
        assert "message" in response.json()

    @pytest.mark.asyncio
    async def test_forgot_password_nonexistent_email(self, test_client: AsyncTestClient[Litestar]):
        """Test password reset request for non-existent email still returns 200."""
        response = await test_client.post(
            "/api/v3/auth/forgot-password",
            json={"email": "nonexistent@test.com"},
        )
        # Should return 200 to prevent email enumeration
        assert response.status_code == HTTP_200_OK
        assert "message" in response.json()

    # =========================================================================
    # REMEMBER TOKEN TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_create_remember_token(self, test_client: AsyncTestClient[Litestar]):
        """Test creating a remember token."""
        response = await test_client.post(
            "/api/v3/auth/remember-token",
            json={"user_id": 100},
        )
        assert response.status_code == HTTP_201_CREATED
        data = response.json()
        assert "token" in data
        assert len(data["token"]) > 0

    @pytest.mark.asyncio
    async def test_validate_remember_token(self, test_client: AsyncTestClient[Litestar]):
        """Test validating a remember token."""
        # First create a token
        create_response = await test_client.post(
            "/api/v3/auth/remember-token",
            json={"user_id": 100},
        )
        token = create_response.json()["token"]

        # Then validate it
        response = await test_client.post(
            "/api/v3/auth/remember-token/validate",
            json={"token": token},
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data["valid"] is True
        assert data["user_id"] == 100

    @pytest.mark.asyncio
    async def test_validate_invalid_remember_token(self, test_client: AsyncTestClient[Litestar]):
        """Test validating an invalid remember token."""
        response = await test_client.post(
            "/api/v3/auth/remember-token/validate",
            json={"token": "invalid-token-that-does-not-exist"},
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data["valid"] is False
        assert data["user_id"] is None

    @pytest.mark.asyncio
    async def test_revoke_remember_tokens(self, test_client: AsyncTestClient[Litestar]):
        """Test revoking all remember tokens for a user."""
        # First create some tokens
        await test_client.post("/api/v3/auth/remember-token", json={"user_id": 100})
        await test_client.post("/api/v3/auth/remember-token", json={"user_id": 100})

        # Revoke all
        response = await test_client.delete("/api/v3/auth/remember-token/user/100")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert "revoked_count" in data
        assert data["revoked_count"] >= 2
