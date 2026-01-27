"""Tests for v4 notifications routes."""

import pytest
from litestar.status_codes import HTTP_200_OK, HTTP_201_CREATED, HTTP_204_NO_CONTENT


class TestNotificationsEndpoints:
    """Test notifications endpoints."""

    @pytest.mark.asyncio
    async def test_create_notification_returns_201(self, test_client):
        """Test creating notification returns 201."""
        response = await test_client.post(
            "/api/v4/notifications/events",
            json={
                "user_id": 300,
                "event_type": "xp_gain",
                "title": "XP Gained",
                "body": "You gained 100 XP",
                "discord_message": "🎉 +100 XP",
                "metadata": {"xp_amount": 100},
            },
        )
        assert response.status_code == HTTP_201_CREATED
        data = response.json()
        assert "id" in data
        assert data["user_id"] == 300

    @pytest.mark.asyncio
    async def test_list_user_events_returns_200(self, test_client):
        """Test listing user events returns 200."""
        response = await test_client.get("/api/v4/notifications/users/300/events")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_get_unread_count_returns_200(self, test_client):
        """Test getting unread count returns 200."""
        response = await test_client.get("/api/v4/notifications/users/300/unread-count")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert "count" in data

    @pytest.mark.asyncio
    async def test_mark_read_returns_204(self, test_client):
        """Test marking as read returns 204."""
        response = await test_client.patch("/api/v4/notifications/events/1/read")
        assert response.status_code == HTTP_204_NO_CONTENT
