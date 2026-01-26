"""Tests for v4 auth routes."""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest


def unique_email() -> str:
    """Generate unique email for testing."""
    return f"test-{uuid.uuid4().hex[:8]}@test.com"


async def create_email_user(conn, email: str, username: str = "testuser") -> int:
    """Create a core user and email auth record."""
    user_id = await conn.fetchval("SELECT nextval('users.email_user_id_seq')")
    await conn.execute(
        "INSERT INTO core.users (id, nickname, global_name) VALUES ($1, $2, $2)",
        user_id,
        username,
    )
    await conn.execute(
        "INSERT INTO users.email_auth (user_id, email, password_hash) VALUES ($1, $2, $3)",
        user_id,
        email,
        "hash",
    )
    return user_id


async def insert_email_token(
    conn,
    user_id: int,
    token: str,
    token_type: str,
    expires_at: datetime,
) -> None:
    """Insert an email token with a known plaintext token."""
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    await conn.execute(
        "INSERT INTO users.email_tokens (user_id, token_hash, token_type, expires_at) VALUES ($1, $2, $3, $4)",
        user_id,
        token_hash,
        token_type,
        expires_at,
    )


async def mark_token_used(conn, token: str) -> None:
    """Mark a token as used by plaintext token."""
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    await conn.execute(
        "UPDATE users.email_tokens SET used_at = now() WHERE token_hash = $1",
        token_hash,
    )


async def mark_email_verified(conn, user_id: int) -> None:
    """Mark email as verified for a user."""
    await conn.execute(
        "UPDATE users.email_auth SET email_verified_at = now() WHERE user_id = $1",
        user_id,
    )


class TestRegisterEndpoint:
    """Test POST /api/v4/auth/register."""

    @pytest.mark.asyncio
    async def test_register_returns_201_on_success(self, test_client):
        """Test that registration returns 201 with user data."""
        response = await test_client.post(
            "/api/v4/auth/register",
            json={
                "email": unique_email(),
                "username": "newuser",
                "password": "Test123!@#",
            },
        )

        assert response.status_code == 201
        data = response.json()
        # v4 wraps response in {"user": {...}, "verification_email_sent": bool}
        assert "user" in data
        assert "verification_email_sent" in data
        assert data["user"]["username"] == "newuser"
        assert data["user"]["email_verified"] is False

    @pytest.mark.asyncio
    async def test_register_returns_400_on_duplicate_email(self, test_client):
        """Test that duplicate email returns 400."""
        email = unique_email()

        # Register once
        await test_client.post(
            "/api/v4/auth/register",
            json={
                "email": email,
                "username": "user1",
                "password": "Test123!@#",
            },
        )

        # Try to register again
        response = await test_client.post(
            "/api/v4/auth/register",
            json={
                "email": email,
                "username": "user2",
                "password": "Test123!@#",
            },
        )

        assert response.status_code == 400
        response_data = response.json()
        assert "already exists" in response_data["error"]

    @pytest.mark.asyncio
    async def test_register_returns_400_on_invalid_email(self, test_client):
        """Test that invalid email returns 400."""
        response = await test_client.post(
            "/api/v4/auth/register",
            json={
                "email": "not-an-email",
                "username": "testuser",
                "password": "Test123!@#",
            },
        )

        assert response.status_code == 400
        response_data = response.json()
        assert "email" in response_data["error"].lower()


class TestLoginEndpoint:
    """Test POST /api/v4/auth/login."""

    @pytest.mark.asyncio
    async def test_login_returns_200_on_valid_credentials(self, test_client):
        """Test that login returns 200 with valid credentials."""
        email = unique_email()

        # First register a user
        await test_client.post(
            "/api/v4/auth/register",
            json={
                "email": email,
                "username": "loginuser",
                "password": "Test123!@#",
            },
        )

        # Then login
        response = await test_client.post(
            "/api/v4/auth/login",
            json={
                "email": email,
                "password": "Test123!@#",
            },
        )

        assert response.status_code == 200
        data = response.json()
        # v4 wraps response in {"user": {...}}
        assert "user" in data
        assert data["user"]["email"] == email
        assert data["user"]["username"] == "loginuser"

    @pytest.mark.asyncio
    async def test_login_returns_401_on_invalid_password(self, test_client):
        """Test that login returns 401 with wrong password."""
        email = unique_email()

        # First register a user
        await test_client.post(
            "/api/v4/auth/register",
            json={
                "email": email,
                "username": "wrongpassuser",
                "password": "Test123!@#",
            },
        )

        # Try to login with wrong password
        response = await test_client.post(
            "/api/v4/auth/login",
            json={
                "email": email,
                "password": "WrongPassword!",
            },
        )

        assert response.status_code == 401
        response_data = response.json()
        assert "Invalid" in response_data["error"]


class TestVerifyEmailEndpoint:
    """Test POST /api/v4/auth/verify-email."""

    @pytest.mark.asyncio
    async def test_verify_email_returns_200_on_valid_token(self, test_client, asyncpg_conn):
        """Test that verify-email returns 200 with valid token."""
        email = unique_email()
        user_id = await create_email_user(asyncpg_conn, email, username="verifyuser")
        token = "verify-token-123"
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        await insert_email_token(asyncpg_conn, user_id, token, "verification", expires_at)

        response = await test_client.post(
            "/api/v4/auth/verify-email",
            json={"token": token},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Email verified successfully."
        assert data["user"]["email"] == email

    @pytest.mark.asyncio
    async def test_verify_email_returns_400_on_invalid_token(self, test_client):
        """Test that invalid token returns 400."""
        response = await test_client.post(
            "/api/v4/auth/verify-email",
            json={"token": "bad-token"},
        )

        assert response.status_code == 400
        data = response.json()
        assert "Invalid" in data["error"]

    @pytest.mark.asyncio
    async def test_verify_email_returns_400_on_expired_token(self, test_client, asyncpg_conn):
        """Test that expired token returns 400."""
        email = unique_email()
        user_id = await create_email_user(asyncpg_conn, email, username="expireuser")
        token = "expired-token-123"
        expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        await insert_email_token(asyncpg_conn, user_id, token, "verification", expires_at)

        response = await test_client.post(
            "/api/v4/auth/verify-email",
            json={"token": token},
        )

        assert response.status_code == 400
        data = response.json()
        assert "expired" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_verify_email_returns_400_on_used_token(self, test_client, asyncpg_conn):
        """Test that used token returns 400."""
        email = unique_email()
        user_id = await create_email_user(asyncpg_conn, email, username="useduser")
        token = "used-token-123"
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        await insert_email_token(asyncpg_conn, user_id, token, "verification", expires_at)
        await mark_token_used(asyncpg_conn, token)

        response = await test_client.post(
            "/api/v4/auth/verify-email",
            json={"token": token},
        )

        assert response.status_code == 400
        data = response.json()
        assert "already been used" in data["error"].lower()


class TestResendVerificationEndpoint:
    """Test POST /api/v4/auth/resend-verification."""

    @pytest.mark.asyncio
    async def test_resend_verification_returns_200_on_valid_email(self, test_client, asyncpg_conn):
        """Test resend verification returns 200 for existing user."""
        email = unique_email()
        await create_email_user(asyncpg_conn, email, username="resenduser")

        response = await test_client.post(
            "/api/v4/auth/resend-verification",
            json={"email": email},
        )

        assert response.status_code == 200
        data = response.json()
        assert "verification email has been sent" in data["message"]

    @pytest.mark.asyncio
    async def test_resend_verification_returns_404_when_missing(self, test_client):
        """Test resend verification returns 404 for missing user."""
        response = await test_client.post(
            "/api/v4/auth/resend-verification",
            json={"email": "missing@test.com"},
        )

        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_resend_verification_returns_400_when_already_verified(self, test_client, asyncpg_conn):
        """Test resend verification returns 400 when already verified."""
        email = unique_email()
        user_id = await create_email_user(asyncpg_conn, email, username="verifieduser")
        await mark_email_verified(asyncpg_conn, user_id)

        response = await test_client.post(
            "/api/v4/auth/resend-verification",
            json={"email": email},
        )

        assert response.status_code == 400


class TestPasswordResetEndpoints:
    """Test password reset routes."""

    @pytest.mark.asyncio
    async def test_forgot_password_returns_200(self, test_client, asyncpg_conn):
        """Test forgot-password returns 200."""
        email = unique_email()
        await create_email_user(asyncpg_conn, email, username="resetuser")

        response = await test_client.post(
            "/api/v4/auth/forgot-password",
            json={"email": email},
        )

        assert response.status_code == 200
        data = response.json()
        assert "password reset link has been sent" in data["message"]

    @pytest.mark.asyncio
    async def test_reset_password_returns_200_on_valid_token(self, test_client, asyncpg_conn):
        """Test reset-password returns 200 with valid token."""
        email = unique_email()
        user_id = await create_email_user(asyncpg_conn, email, username="resetuser")
        token = "reset-token-123"
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        await insert_email_token(asyncpg_conn, user_id, token, "password_reset", expires_at)

        response = await test_client.post(
            "/api/v4/auth/reset-password",
            json={"token": token, "password": "NewPass123!"},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Password reset successfully."
        assert data["user"]["email"] == email

    @pytest.mark.asyncio
    async def test_reset_password_returns_400_on_expired_token(self, test_client, asyncpg_conn):
        """Test reset-password returns 400 with expired token."""
        email = unique_email()
        user_id = await create_email_user(asyncpg_conn, email, username="resetuser")
        token = "reset-expired-123"
        expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
        await insert_email_token(asyncpg_conn, user_id, token, "password_reset", expires_at)

        response = await test_client.post(
            "/api/v4/auth/reset-password",
            json={"token": token, "password": "NewPass123!"},
        )

        assert response.status_code == 400
        data = response.json()
        assert "expired" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_reset_password_returns_400_on_used_token(self, test_client, asyncpg_conn):
        """Test reset-password returns 400 with used token."""
        email = unique_email()
        user_id = await create_email_user(asyncpg_conn, email, username="resetuser")
        token = "reset-used-123"
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        await insert_email_token(asyncpg_conn, user_id, token, "password_reset", expires_at)
        await mark_token_used(asyncpg_conn, token)

        response = await test_client.post(
            "/api/v4/auth/reset-password",
            json={"token": token, "password": "NewPass123!"},
        )

        assert response.status_code == 400
        data = response.json()
        assert "already been used" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_reset_password_returns_400_on_invalid_token(self, test_client):
        """Test reset-password returns 400 with invalid token."""
        response = await test_client.post(
            "/api/v4/auth/reset-password",
            json={"token": "invalid", "password": "NewPass123!"},
        )

        assert response.status_code == 400
        data = response.json()
        assert "invalid" in data["error"].lower()


class TestAuthStatusEndpoint:
    """Test GET /api/v4/auth/status/{user_id}."""

    @pytest.mark.asyncio
    async def test_get_auth_status_masks_email(self, test_client, asyncpg_conn):
        """Test that auth status masks email."""
        email = unique_email()
        user_id = await create_email_user(asyncpg_conn, email, username="statususer")

        response = await test_client.get(f"/api/v4/auth/status/{user_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["email"] != email
        assert "***@" in data["email"]

    @pytest.mark.asyncio
    async def test_get_auth_status_returns_404_when_missing(self, test_client):
        """Test status returns 404 for missing user."""
        response = await test_client.get("/api/v4/auth/status/999999")

        assert response.status_code == 404


class TestSessionEndpoints:
    """Test session endpoints."""

    @pytest.mark.asyncio
    async def test_session_write_read_destroy_flow(self, test_client):
        """Test session write/read/destroy flow."""
        session_id = "sess-123"

        write_resp = await test_client.put(
            f"/api/v4/auth/sessions/{session_id}",
            json={"payload": "abc", "user_id": None},
        )
        assert write_resp.status_code == 200
        assert write_resp.json()["success"] is True

        read_resp = await test_client.get(f"/api/v4/auth/sessions/{session_id}")
        assert read_resp.status_code == 200
        read_data = read_resp.json()
        assert read_data["payload"] == "abc"

        delete_resp = await test_client.delete(f"/api/v4/auth/sessions/{session_id}")
        assert delete_resp.status_code == 200
        assert delete_resp.json()["deleted"] is True

    @pytest.mark.asyncio
    async def test_session_gc_endpoint(self, test_client, asyncpg_conn):
        """Test session gc endpoint deletes expired sessions."""
        async with asyncpg_conn.transaction():
            await asyncpg_conn.execute(
                "INSERT INTO users.sessions (id, payload, last_activity) VALUES ($1, $2, now() - interval '3 hours')",
                "expired-gc",
                "payload",
            )

        response = await test_client.post("/api/v4/auth/sessions/gc")
        assert response.status_code == 200
        assert response.json()["deleted_count"] >= 1

    @pytest.mark.asyncio
    async def test_get_user_sessions_endpoint(self, test_client, asyncpg_conn):
        """Test get user sessions endpoint returns sessions."""
        email = unique_email()
        user_id = await create_email_user(asyncpg_conn, email, username="sessionuser")
        await asyncpg_conn.execute(
            "INSERT INTO users.sessions (id, user_id, payload, last_activity) VALUES ($1, $2, $3, now())",
            "sess-user-a",
            user_id,
            "payload",
        )

        response = await test_client.get(f"/api/v4/auth/sessions/user/{user_id}")
        assert response.status_code == 200
        data = response.json()
        assert len(data["sessions"]) >= 1


class TestRememberTokenEndpoints:
    """Test remember token endpoints."""

    @pytest.mark.asyncio
    async def test_remember_token_lifecycle(self, test_client, asyncpg_conn):
        """Test create/validate/revoke remember token flow."""
        email = unique_email()
        user_id = await create_email_user(asyncpg_conn, email, username="rememberuser")

        create_resp = await test_client.post(
            "/api/v4/auth/remember-token",
            json={"user_id": user_id},
        )
        assert create_resp.status_code == 201
        token = create_resp.json()["token"]

        validate_resp = await test_client.post(
            "/api/v4/auth/remember-token/validate",
            json={"token": token},
        )
        assert validate_resp.status_code == 200
        assert validate_resp.json()["valid"] is True
        assert validate_resp.json()["user_id"] == user_id

        revoke_resp = await test_client.delete(f"/api/v4/auth/remember-token/user/{user_id}")
        assert revoke_resp.status_code == 200
        assert revoke_resp.json()["revoked_count"] >= 1
