"""Integration tests for Notifications v4 controller.

Tests HTTP interface: request/response serialization,
error translation, and full stack flow through real database.

Note: The test_client from root conftest.py includes auth headers by default,
so these tests verify authenticated requests. Auth middleware is tested separately.
"""

import pytest
from genjishimada_sdk.notifications import NotificationEventType

pytestmark = [
    pytest.mark.integration,
    pytest.mark.domain_notifications,
]


class TestCreateNotification:
    """POST /api/v4/notifications/events"""

    async def test_happy_path(self, test_client, create_test_user):
        """Create notification returns 201 with event data."""
        user_id = await create_test_user()
        payload = {
            "user_id": user_id,
            "event_type": NotificationEventType.MAP_EDIT_APPROVED.value,
            "title": "Your map was approved!",
            "body": "Congratulations!",
        }

        response = await test_client.post(
            "/api/v4/notifications/events",
            json=payload,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["user_id"] == user_id
        assert data["event_type"] == NotificationEventType.MAP_EDIT_APPROVED.value
        assert data["title"] == "Your map was approved!"
        assert data["id"] is not None
        assert data["created_at"] is not None

    async def test_with_optional_fields(self, test_client, create_test_user):
        """Create notification with discord_message and metadata."""
        user_id = await create_test_user()
        payload = {
            "user_id": user_id,
            "event_type": NotificationEventType.VERIFICATION_APPROVED.value,
            "title": "Record verified!",
            "body": "Your record has been verified.",
            "discord_message": "🎉 Your record was verified!",
            "metadata": {"map_code": "ABC-123"},
        }

        response = await test_client.post(
            "/api/v4/notifications/events",
            json=payload,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["metadata"] == {"map_code": "ABC-123"}

    async def test_user_not_found_returns_404(self, test_client):
        """Non-existent user returns 404."""
        payload = {
            "user_id": 999999999999999999,
            "event_type": NotificationEventType.MAP_EDIT_APPROVED.value,
            "title": "Test",
            "body": "Test",
        }

        response = await test_client.post(
            "/api/v4/notifications/events",
            json=payload,
        )

        assert response.status_code == 404
        assert "not found" in response.json()["error"].lower()

    @pytest.mark.parametrize(
        "event_type",
        [
            NotificationEventType.MAP_EDIT_APPROVED.value,
            NotificationEventType.VERIFICATION_APPROVED.value,
            NotificationEventType.RANK_UP.value,
            NotificationEventType.LOOTBOX_EARNED.value,
        ],
    )
    async def test_all_event_types(self, test_client, create_test_user, event_type):
        """All event types serialize correctly."""
        user_id = await create_test_user()
        payload = {
            "user_id": user_id,
            "event_type": event_type,
            "title": f"Test {event_type}",
            "body": "Test body",
        }

        response = await test_client.post(
            "/api/v4/notifications/events",
            json=payload,
        )

        assert response.status_code == 201
        assert response.json()["event_type"] == event_type


class TestGetUserEvents:
    """GET /api/v4/notifications/users/{user_id}/events"""

    async def test_happy_path(self, test_client, create_test_user):
        """Get events returns 200 with list."""
        user_id = await create_test_user()

        response = await test_client.get(
            f"/api/v4/notifications/users/{user_id}/events",
        )

        assert response.status_code == 200
        assert isinstance(response.json(), list)

    async def test_with_events(self, test_client, create_test_user):
        """Get events returns created notifications."""
        user_id = await create_test_user()

        # Create a notification
        create_payload = {
            "user_id": user_id,
            "event_type": NotificationEventType.XP_GAIN.value,
            "title": "You gained XP!",
            "body": "+100 XP",
        }
        await test_client.post("/api/v4/notifications/events", json=create_payload)

        # Get events
        response = await test_client.get(
            f"/api/v4/notifications/users/{user_id}/events",
        )

        assert response.status_code == 200
        events = response.json()
        assert len(events) >= 1
        assert any(e["title"] == "You gained XP!" for e in events)

    @pytest.mark.parametrize("unread_only", [True, False])
    @pytest.mark.parametrize("limit", [10, 50, 100])
    @pytest.mark.parametrize("offset", [0, 5])
    async def test_query_param_variants(
        self,
        test_client,
        create_test_user,
        unread_only,
        limit,
        offset,
    ):
        """Query params serialize correctly without 500s."""
        user_id = await create_test_user()

        response = await test_client.get(
            f"/api/v4/notifications/users/{user_id}/events",
            params={"unread_only": unread_only, "limit": limit, "offset": offset},
        )

        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestGetUnreadCount:
    """GET /api/v4/notifications/users/{user_id}/unread-count"""

    async def test_happy_path(self, test_client, create_test_user):
        """Get unread count returns 200 with count."""
        user_id = await create_test_user()

        response = await test_client.get(
            f"/api/v4/notifications/users/{user_id}/unread-count",
        )

        assert response.status_code == 200
        data = response.json()
        assert "count" in data
        assert isinstance(data["count"], int)
        assert data["count"] >= 0


class TestMarkRead:
    """PATCH /api/v4/notifications/events/{event_id}/read"""

    async def test_happy_path(self, test_client, create_test_user):
        """Mark read returns 204."""
        user_id = await create_test_user()

        # Create a notification first
        create_response = await test_client.post(
            "/api/v4/notifications/events",
            json={
                "user_id": user_id,
                "event_type": NotificationEventType.PRESTIGE.value,
                "title": "Prestige!",
                "body": "You hit prestige!",
            },
        )
        event_id = create_response.json()["id"]

        # Mark it as read
        response = await test_client.patch(
            f"/api/v4/notifications/events/{event_id}/read",
        )

        assert response.status_code == 204


class TestMarkAllRead:
    """PATCH /api/v4/notifications/users/{user_id}/read-all"""

    async def test_happy_path(self, test_client, create_test_user):
        """Mark all read returns 200 with count."""
        user_id = await create_test_user()

        response = await test_client.patch(
            f"/api/v4/notifications/users/{user_id}/read-all",
        )

        assert response.status_code == 200
        data = response.json()
        assert "marked_read" in data
        assert isinstance(data["marked_read"], int)


class TestDismissEvent:
    """PATCH /api/v4/notifications/events/{event_id}/dismiss"""

    async def test_happy_path(self, test_client, create_test_user):
        """Dismiss event returns 204."""
        user_id = await create_test_user()

        # Create a notification first
        create_response = await test_client.post(
            "/api/v4/notifications/events",
            json={
                "user_id": user_id,
                "event_type": NotificationEventType.PLAYTEST_UPDATE.value,
                "title": "Playtest update",
                "body": "New playtest available",
            },
        )
        event_id = create_response.json()["id"]

        # Dismiss it
        response = await test_client.patch(
            f"/api/v4/notifications/events/{event_id}/dismiss",
        )

        assert response.status_code == 204


class TestRecordDeliveryResult:
    """POST /api/v4/notifications/events/{event_id}/delivery-result"""

    async def test_happy_path(self, test_client, create_test_user):
        """Record delivery result returns 204."""
        user_id = await create_test_user()

        # Create a notification first
        create_response = await test_client.post(
            "/api/v4/notifications/events",
            json={
                "user_id": user_id,
                "event_type": NotificationEventType.MASTERY_EARNED.value,
                "title": "Mastery!",
                "body": "You earned mastery",
            },
        )
        event_id = create_response.json()["id"]

        # Record delivery result
        response = await test_client.post(
            f"/api/v4/notifications/events/{event_id}/delivery-result",
            json={
                "channel": "discord_dm",
                "status": "delivered",
            },
        )

        assert response.status_code == 204

    @pytest.mark.parametrize("status", ["delivered", "failed", "skipped"])
    @pytest.mark.parametrize("channel", ["discord_dm", "discord_ping", "web"])
    async def test_all_status_channel_combinations(
        self,
        test_client,
        create_test_user,
        status,
        channel,
    ):
        """All status and channel combinations work."""
        user_id = await create_test_user()

        # Create a notification
        create_response = await test_client.post(
            "/api/v4/notifications/events",
            json={
                "user_id": user_id,
                "event_type": NotificationEventType.RANK_UP.value,
                "title": "Rank up!",
                "body": "New rank",
            },
        )
        event_id = create_response.json()["id"]

        # Record delivery result
        payload = {"channel": channel, "status": status}
        if status == "failed":
            payload["error_message"] = "Test error"

        response = await test_client.post(
            f"/api/v4/notifications/events/{event_id}/delivery-result",
            json=payload,
        )

        assert response.status_code == 204


class TestGetPreferences:
    """GET /api/v4/notifications/users/{user_id}/preferences"""

    async def test_happy_path(self, test_client, create_test_user):
        """Get preferences returns 200 with list."""
        user_id = await create_test_user()

        response = await test_client.get(
            f"/api/v4/notifications/users/{user_id}/preferences",
        )

        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)


class TestUpdatePreference:
    """PUT /api/v4/notifications/users/{user_id}/preferences/{event_type}/{channel}"""

    async def test_happy_path(self, test_client, create_test_user):
        """Update preference returns 204."""
        user_id = await create_test_user()

        response = await test_client.put(
            f"/api/v4/notifications/users/{user_id}/preferences/map_edit_approved/discord_dm",
            params={"enabled": True},
        )

        assert response.status_code == 204

    async def test_disable_preference(self, test_client, create_test_user):
        """Can disable a preference."""
        user_id = await create_test_user()

        response = await test_client.put(
            f"/api/v4/notifications/users/{user_id}/preferences/rank_up/web",
            params={"enabled": False},
        )

        assert response.status_code == 204

    async def test_user_not_found_returns_404(self, test_client):
        """Non-existent user returns 404."""
        response = await test_client.put(
            "/api/v4/notifications/users/999999999999999999/preferences/map_edit_approved/discord_dm",
            params={"enabled": True},
        )

        assert response.status_code == 404

    @pytest.mark.parametrize(
        "event_type",
        [
            "map_edit_approved",
            "verification_approved",
            "rank_up",
            "lootbox_earned",
        ],
    )
    @pytest.mark.parametrize("channel", ["discord_dm", "discord_ping", "web"])
    @pytest.mark.parametrize("enabled", [True, False])
    async def test_enum_variants(
        self,
        test_client,
        create_test_user,
        event_type,
        channel,
        enabled,
    ):
        """All enum combinations work without 500s."""
        user_id = await create_test_user()

        response = await test_client.put(
            f"/api/v4/notifications/users/{user_id}/preferences/{event_type}/{channel}",
            params={"enabled": enabled},
        )

        assert response.status_code in (204, 404)
        assert response.status_code != 500


class TestBulkUpdatePreferences:
    """PUT /api/v4/notifications/users/{user_id}/preferences/bulk"""

    async def test_happy_path(self, test_client, create_test_user):
        """Bulk update preferences returns 204."""
        user_id = await create_test_user()

        payload = [
            {"event_type": "map_edit_approved", "channel": "discord_dm", "enabled": True},
            {"event_type": "rank_up", "channel": "web", "enabled": False},
        ]

        response = await test_client.put(
            f"/api/v4/notifications/users/{user_id}/preferences/bulk",
            json=payload,
        )

        assert response.status_code == 204

    async def test_empty_list(self, test_client, create_test_user):
        """Empty preference list works."""
        user_id = await create_test_user()

        response = await test_client.put(
            f"/api/v4/notifications/users/{user_id}/preferences/bulk",
            json=[],
        )

        assert response.status_code == 204


class TestShouldDeliver:
    """GET /api/v4/notifications/users/{user_id}/should-deliver"""

    async def test_happy_path(self, test_client, create_test_user):
        """Should deliver returns 200 with boolean."""
        user_id = await create_test_user()

        response = await test_client.get(
            f"/api/v4/notifications/users/{user_id}/should-deliver",
            params={"event_type": "map_edit_approved", "channel": "discord_dm"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "should_deliver" in data
        assert isinstance(data["should_deliver"], bool)

    @pytest.mark.parametrize("event_type", ["map_edit_approved", "rank_up", "verification_approved"])
    @pytest.mark.parametrize("channel", ["discord_dm", "discord_ping", "web"])
    async def test_all_combinations(self, test_client, create_test_user, event_type, channel):
        """All event type and channel combinations work."""
        user_id = await create_test_user()

        response = await test_client.get(
            f"/api/v4/notifications/users/{user_id}/should-deliver",
            params={"event_type": event_type, "channel": channel},
        )

        assert response.status_code == 200
        assert "should_deliver" in response.json()
