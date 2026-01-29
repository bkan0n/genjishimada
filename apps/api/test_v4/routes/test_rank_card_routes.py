"""Tests for v4 rank_card routes."""

import pytest


class TestRankCardEndpoints:
    """Test endpoints."""

    @pytest.mark.asyncio
    async def test_get_background_returns_200(self, test_client):
        """Test endpoint returns success."""
        response = await test_client.get("/api/v4/users/1/rank-card/background")
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
