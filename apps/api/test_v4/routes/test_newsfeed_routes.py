"""Tests for v4 newsfeed routes."""

import pytest
from litestar.status_codes import HTTP_200_OK, HTTP_201_CREATED


class TestNewsfeedEndpoints:
    """Test newsfeed endpoints."""

    @pytest.mark.asyncio
    async def test_create_newsfeed_event_returns_201(self, test_client):
        """Test creating newsfeed event returns 201."""
        response = await test_client.post(
            "/api/v4/newsfeed/",
            json={
                "id": None,
                "timestamp": "2024-01-01T00:00:00Z",
                "event_type": "guide",
                "payload": {
                    "code": "TEST1",
                    "guide_url": "https://youtube.com/watch?v=test123",
                    "name": "TestCreator",
                    "type": "guide",
                },
            },
        )
        assert response.status_code == HTTP_201_CREATED
        data = response.json()
        assert "newsfeed_id" in data
        assert "job_status" in data

    @pytest.mark.asyncio
    async def test_list_newsfeed_events_returns_200(self, test_client):
        """Test listing newsfeed events returns 200."""
        response = await test_client.get("/api/v4/newsfeed/")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list) or data is None

    @pytest.mark.asyncio
    async def test_get_single_newsfeed_event_returns_200(self, test_client):
        """Test getting single event returns 200."""
        # Use seed data ID
        response = await test_client.get("/api/v4/newsfeed/1")
        assert response.status_code == HTTP_200_OK
