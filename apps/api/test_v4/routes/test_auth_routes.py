"""Tests for v4 auth routes."""

import uuid

import pytest


def unique_email() -> str:
    """Generate unique email for testing."""
    return f"test-{uuid.uuid4().hex[:8]}@test.com"


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
