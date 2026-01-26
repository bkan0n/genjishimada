"""Tests for v4 community routes."""

import pytest


class TestLeaderboardEndpoint:
    """Test GET /api/v4/community/leaderboard."""

    @pytest.mark.asyncio
    async def test_get_leaderboard_returns_200(self, test_client) -> None:  # type: ignore[no-untyped-def]
        """Test that leaderboard endpoint returns 200."""
        response = await test_client.get("/api/v4/community/leaderboard")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
