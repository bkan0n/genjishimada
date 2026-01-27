"""Tests for v4 lootbox routes."""

import pytest


class TestLootboxEndpoints:
    """Test lootbox endpoints."""

    @pytest.mark.asyncio
    async def test_view_all_rewards_returns_200(self, test_client):
        """Test rewards endpoint returns success."""
        response = await test_client.get("/api/v4/lootbox/rewards")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_view_all_keys_returns_200(self, test_client):
        """Test keys endpoint returns success."""
        response = await test_client.get("/api/v4/lootbox/keys")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


class TestRewardEndpoints:
    """Test reward endpoints."""

    @pytest.mark.asyncio
    async def test_view_user_rewards_returns_200(self, test_client):
        """Test user rewards endpoint returns success."""
        response = await test_client.get("/api/v4/lootbox/users/1/rewards")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_grant_reward_returns_200(self, test_client):
        """Test granting reward returns success."""
        headers = {"x-test-mode": "1"}
        response = await test_client.post(
            "/api/v4/lootbox/users/1/Classic/background/New Queen Street",
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "name" in data


class TestKeyEndpoints:
    """Test key endpoints."""

    @pytest.mark.asyncio
    async def test_view_user_keys_returns_200(self, test_client):
        """Test user keys endpoint returns success."""
        response = await test_client.get("/api/v4/lootbox/users/1/keys")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_grant_key_returns_204(self, test_client):
        """Test granting key returns success."""
        response = await test_client.post("/api/v4/lootbox/users/1/keys/Classic")
        assert response.status_code == 204


class TestXPEndpoints:
    """Test XP endpoints."""

    @pytest.mark.asyncio
    async def test_grant_xp_returns_200(self, test_client):
        """Test granting XP returns success."""
        response = await test_client.post(
            "/api/v4/lootbox/users/1/xp",
            json={"amount": 100, "type": "Completion"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "new_amount" in data

    @pytest.mark.asyncio
    async def test_get_xp_tier_returns_200(self, test_client):
        """Test getting XP tier change returns success."""
        response = await test_client.get("/api/v4/lootbox/xp/tier?old_xp=0&new_xp=100")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_get_xp_multiplier_returns_200(self, test_client):
        """Test getting XP multiplier returns success."""
        response = await test_client.get("/api/v4/lootbox/xp/multiplier")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_update_xp_multiplier_returns_204(self, test_client):
        """Test updating XP multiplier returns success."""
        response = await test_client.post("/api/v4/lootbox/xp/multiplier", json={"value": 1.5})
        assert response.status_code == 204
