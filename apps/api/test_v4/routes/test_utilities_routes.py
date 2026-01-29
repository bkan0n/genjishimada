"""Tests for v4 utilities routes."""

import pytest


class TestUtilitiesEndpoints:
    """Test endpoints."""

    @pytest.mark.asyncio
    async def test_log_map_click_returns_204(self, test_client):
        """Test log map click endpoint."""
        response = await test_client.post(
            "/api/v4/utilities/log-map-click",
            json={
                "code": "TEST123",
                "ip_address": "127.0.0.1",
                "user_id": None,
                "source": "web",
            },
        )
        assert response.status_code == 204
