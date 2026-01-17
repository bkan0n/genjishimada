from logging import getLogger

import pytest
from litestar import Litestar
from litestar.status_codes import HTTP_200_OK, HTTP_201_CREATED, HTTP_204_NO_CONTENT
from litestar.testing import AsyncTestClient

# ruff: noqa: D102, D103, ANN001, ANN201

log = getLogger(__name__)


class TestNotificationsEndpoints:
    """Tests for notification management endpoints."""

    # Test users from seed
    USER_WITH_NOTIFICATIONS = 300  # Has 3 notifications (1 read, 2 unread)
    USER_WITH_DISMISSED = 301  # Has 1 dismissed notification + preferences
    USER_NO_NOTIFICATIONS = 302  # Has no notifications or preferences

    # =========================================================================
    # CREATE NOTIFICATION TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_create_notification_completion_verified(self, test_client: AsyncTestClient[Litestar]):
        """Test creating a completion_verified notification."""
        response = await test_client.post(
            "/api/v3/notifications/events",
            json={
                "user_id": self.USER_NO_NOTIFICATIONS,
                "event_type": "verification_approved",
                "title": "Completion Verified",
                "body": "Your completion was verified!",
                "discord_message": "✅ Your completion was verified!",
                "metadata": {"map_code": "1EASY"},
            },
        )
        assert response.status_code == HTTP_201_CREATED
        data = response.json()
        assert data["user_id"] == self.USER_NO_NOTIFICATIONS
        assert data["event_type"] == "verification_approved"
        assert data["id"] is not None

    @pytest.mark.asyncio
    async def test_create_notification_xp_gain(self, test_client: AsyncTestClient[Litestar]):
        """Test creating an xp_gain notification."""
        response = await test_client.post(
            "/api/v3/notifications/events",
            json={
                "user_id": self.USER_NO_NOTIFICATIONS,
                "event_type": "xp_gain",
                "title": "XP Gained",
                "body": "You gained 500 XP!",
                "discord_message": "🎉 +500 XP",
                "metadata": {"xp_amount": 500},
            },
        )
        assert response.status_code == HTTP_201_CREATED
        data = response.json()
        assert data["event_type"] == "xp_gain"

    # =========================================================================
    # GET USER NOTIFICATIONS TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_user_notifications_all(self, test_client: AsyncTestClient[Litestar]):
        """Test getting all notifications for a user."""
        response = await test_client.get(f"/api/v3/notifications/users/{self.USER_WITH_NOTIFICATIONS}/events")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        # User 300 has 3 notifications
        assert len(data) == 3

    @pytest.mark.asyncio
    async def test_get_user_notifications_unread_only(self, test_client: AsyncTestClient[Litestar]):
        """Test getting only unread notifications."""
        response = await test_client.get(
            f"/api/v3/notifications/users/{self.USER_WITH_NOTIFICATIONS}/events?unread_only=true"
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        # User 300 has 2 unread notifications
        assert len(data) == 2
        # All should be unread
        for notif in data:
            assert notif["read_at"] is None

    @pytest.mark.asyncio
    async def test_get_user_notifications_with_pagination(self, test_client: AsyncTestClient[Litestar]):
        """Test pagination for notifications."""
        response = await test_client.get(
            f"/api/v3/notifications/users/{self.USER_WITH_NOTIFICATIONS}/events?limit=2&offset=0"
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert len(data) <= 2

        # Get next page
        response = await test_client.get(
            f"/api/v3/notifications/users/{self.USER_WITH_NOTIFICATIONS}/events?limit=2&offset=2"
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert len(data) <= 2

    @pytest.mark.asyncio
    async def test_get_user_notifications_empty(self, test_client: AsyncTestClient[Litestar]):
        """Test getting notifications for user with none."""
        response = await test_client.get(f"/api/v3/notifications/users/{self.USER_NO_NOTIFICATIONS}/events")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data == [] or data is None

    # =========================================================================
    # GET UNREAD COUNT TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_unread_count_with_unread(self, test_client: AsyncTestClient[Litestar]):
        """Test getting unread count for user with unread notifications."""
        response = await test_client.get(f"/api/v3/notifications/users/{self.USER_WITH_NOTIFICATIONS}/unread-count")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert "count" in data
        # User 300 has 2 unread
        assert data["count"] == 2

    @pytest.mark.asyncio
    async def test_get_unread_count_none(self, test_client: AsyncTestClient[Litestar]):
        """Test getting unread count for user with no unread."""
        response = await test_client.get(f"/api/v3/notifications/users/{self.USER_NO_NOTIFICATIONS}/unread-count")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data["count"] == 0

    # =========================================================================
    # MARK READ TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_mark_notification_read(self, test_client: AsyncTestClient[Litestar]):
        """Test marking a notification as read."""
        # Get an unread notification ID
        notifs_resp = await test_client.get(
            f"/api/v3/notifications/users/{self.USER_WITH_NOTIFICATIONS}/events?unread_only=true"
        )
        unread_notifs = notifs_resp.json()
        if unread_notifs:
            event_id = unread_notifs[0]["id"]

            response = await test_client.patch(f"/api/v3/notifications/events/{event_id}/read")
            assert response.status_code == HTTP_204_NO_CONTENT

            # Verify it's marked read
            check_resp = await test_client.get(f"/api/v3/notifications/users/{self.USER_WITH_NOTIFICATIONS}/events")
            all_notifs = check_resp.json()
            marked_notif = next((n for n in all_notifs if n["id"] == event_id), None)
            assert marked_notif["read_at"] is not None

    @pytest.mark.asyncio
    async def test_mark_already_read_notification(self, test_client: AsyncTestClient[Litestar]):
        """Test marking already read notification (no error)."""
        # Event ID 1 is already read from seed
        response = await test_client.patch("/api/v3/notifications/events/1/read")
        assert response.status_code == HTTP_204_NO_CONTENT

    # =========================================================================
    # MARK ALL READ TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_mark_all_read(self, test_client: AsyncTestClient[Litestar]):
        """Test marking all notifications as read."""
        response = await test_client.patch(f"/api/v3/notifications/users/{self.USER_WITH_NOTIFICATIONS}/read-all")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert "marked_read" in data
        # Should have marked at least the 2 unread ones
        assert data["marked_read"] >= 2

        # Verify unread count is now 0
        count_resp = await test_client.get(f"/api/v3/notifications/users/{self.USER_WITH_NOTIFICATIONS}/unread-count")
        count_data = count_resp.json()
        assert count_data["count"] == 0

    # =========================================================================
    # DISMISS NOTIFICATION TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_dismiss_notification(self, test_client: AsyncTestClient[Litestar]):
        """Test dismissing a notification."""
        # Create a notification to dismiss
        create_resp = await test_client.post(
            "/api/v3/notifications/events",
            json={
                "user_id": self.USER_NO_NOTIFICATIONS,
                "event_type": "verification_approved",
                "title": "Test",
                "body": "Test notification",
                "discord_message": "Test",
                "metadata": {},
            },
        )
        event_id = create_resp.json()["id"]

        # Dismiss it
        response = await test_client.patch(f"/api/v3/notifications/events/{event_id}/dismiss")
        assert response.status_code == HTTP_204_NO_CONTENT

    # =========================================================================
    # DELIVERY RESULT TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_record_delivery_result_success(self, test_client: AsyncTestClient[Litestar]):
        """Test recording successful delivery."""
        response = await test_client.post(
            "/api/v3/notifications/events/1/delivery-result",
            json={
                "channel": "discord_dm",
                "status": "delivered",
                "error_message": None,
            },
        )
        assert response.status_code == HTTP_204_NO_CONTENT

    @pytest.mark.asyncio
    async def test_record_delivery_result_failure(self, test_client: AsyncTestClient[Litestar]):
        """Test recording failed delivery with error."""
        response = await test_client.post(
            "/api/v3/notifications/events/2/delivery-result",
            json={
                "channel": "discord_dm",
                "status": "failed",
                "error_message": "User has DMs disabled",
            },
        )
        assert response.status_code == HTTP_204_NO_CONTENT

    # =========================================================================
    # PREFERENCES TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_preferences(self, test_client: AsyncTestClient[Litestar]):
        """Test getting all notification preferences."""
        response = await test_client.get(f"/api/v3/notifications/users/{self.USER_WITH_DISMISSED}/preferences")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        # User 301 has custom preferences
        assert len(data) > 0

    @pytest.mark.asyncio
    async def test_get_preferences_no_custom(self, test_client: AsyncTestClient[Litestar]):
        """Test getting preferences for user with defaults."""
        response = await test_client.get(f"/api/v3/notifications/users/{self.USER_NO_NOTIFICATIONS}/preferences")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        # May return defaults or empty
        assert isinstance(data, list)

    @pytest.mark.asyncio
    async def test_update_single_preference(self, test_client: AsyncTestClient[Litestar]):
        """Test updating a single notification preference."""
        response = await test_client.put(
            f"/api/v3/notifications/users/{self.USER_NO_NOTIFICATIONS}/preferences/verification_approved/discord_dm?enabled=true"
        )
        assert response.status_code == HTTP_204_NO_CONTENT

        # Verify the update
        prefs_resp = await test_client.get(f"/api/v3/notifications/users/{self.USER_NO_NOTIFICATIONS}/preferences")
        prefs = prefs_resp.json()
        # Should have the preference set

    @pytest.mark.asyncio
    async def test_update_single_preference_disable(self, test_client: AsyncTestClient[Litestar]):
        """Test disabling a notification preference."""
        response = await test_client.put(
            f"/api/v3/notifications/users/{self.USER_WITH_DISMISSED}/preferences/verification_approved/discord_dm?enabled=false"
        )
        assert response.status_code == HTTP_204_NO_CONTENT

    @pytest.mark.asyncio
    async def test_bulk_update_preferences(self, test_client: AsyncTestClient[Litestar]):
        """Test bulk updating preferences."""
        response = await test_client.put(
            f"/api/v3/notifications/users/{self.USER_NO_NOTIFICATIONS}/preferences/bulk",
            json=[
                {
                    "event_type": "verification_approved",
                    "channel": "discord_dm",
                    "enabled": True,
                },
                {
                    "event_type": "xp_gain",
                    "channel": "web",
                    "enabled": False,
                },
                {
                    "event_type": "skill_role_update",
                    "channel": "discord_dm",
                    "enabled": True,
                },
            ],
        )
        assert response.status_code == HTTP_204_NO_CONTENT

    # =========================================================================
    # SHOULD DELIVER TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_should_deliver_enabled(self, test_client: AsyncTestClient[Litestar]):
        """Test checking if notification should be delivered (enabled)."""
        # User 301 has completion_verified/discord_dm enabled
        response = await test_client.get(
            f"/api/v3/notifications/users/{self.USER_WITH_DISMISSED}/should-deliver"
            "?event_type=verification_approved&channel=discord_dm"
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data["should_deliver"] is False

    @pytest.mark.asyncio
    async def test_should_deliver_disabled(self, test_client: AsyncTestClient[Litestar]):
        """Test checking if notification should be delivered (disabled)."""
        # User 301 has skill_role_update/discord_dm disabled
        response = await test_client.get(
            f"/api/v3/notifications/users/{self.USER_WITH_DISMISSED}/should-deliver"
            "?event_type=skill_role_update&channel=discord_dm"
        )
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert data["should_deliver"] is False

    # =========================================================================
    # LEGACY BITMASK TESTS
    # =========================================================================

    @pytest.mark.asyncio
    async def test_get_legacy_bitmask(self, test_client: AsyncTestClient[Litestar]):
        """Test getting legacy bitmask value."""
        response = await test_client.get(f"/api/v3/notifications/users/{self.USER_WITH_DISMISSED}/legacy-bitmask")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert "bitmask" in data
        assert isinstance(data["bitmask"], int)

    @pytest.mark.asyncio
    async def test_get_legacy_bitmask_no_preferences(self, test_client: AsyncTestClient[Litestar]):
        """Test getting legacy bitmask for user with no preferences."""
        response = await test_client.get(f"/api/v3/notifications/users/{self.USER_NO_NOTIFICATIONS}/legacy-bitmask")
        assert response.status_code == HTTP_200_OK
        data = response.json()
        assert "bitmask" in data
        # Default bitmask
        assert isinstance(data["bitmask"], int)
