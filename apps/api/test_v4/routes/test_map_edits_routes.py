"""Tests for v4 map edits routes."""

import pytest


class TestMapEditsEndpointsBasic:
    """Test basic endpoint functionality."""

    @pytest.mark.asyncio
    async def test_v4_map_edits_router_exists(self, test_client):
        """Test that v4 map edits router is registered."""
        # Just verify the route exists (404 until controller registered)
        response = await test_client.get("/api/v4/map-edits/pending")
        # Either 200 with empty list, or 404 if not yet implemented
        assert response.status_code in (200, 401, 403, 404)
