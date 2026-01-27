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
