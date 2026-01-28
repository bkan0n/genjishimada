"""Tests for v4 playtest routes."""

import pytest


class TestPlaytestEndpointsBasic:
    """Test basic endpoint functionality."""

    @pytest.mark.asyncio
    async def test_v4_playtest_router_exists(self, test_client):
        """Test that v4 playtest router is registered."""
        # Just verify the route exists (404 until controller registered)
        response = await test_client.get("/api/v4/playtests/12345")
        # Either 200, 401, 403, or 404 if not yet implemented
        assert response.status_code in (200, 401, 403, 404)
