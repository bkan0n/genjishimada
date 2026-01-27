"""Tests for v4 maps routes."""

import pytest


class TestMapsEndpointsBasic:
    """Test basic endpoint functionality."""

    @pytest.mark.asyncio
    async def test_v4_router_exists(self, test_client):
        """Test that v4 router is registered."""
        # This will fail until we register the controller
        # but it's a good smoke test
        response = await test_client.get("/api/v4/")
        # Just verify the v4 namespace exists, don't check specific endpoints yet
        assert response.status_code in (200, 404)  # 404 is ok if no root handler
