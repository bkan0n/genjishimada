"""Unit tests for NotificationsService."""

from datetime import datetime, timezone

import msgspec
import pytest
from genjishimada_sdk.notifications import (
    NotificationChannel,
    NotificationCreateRequest,
    NotificationEventType,
)

from repository.exceptions import ForeignKeyViolationError
from services.exceptions.users import UserNotFoundError
from services.notifications_service import DISCORD_USER_ID_LOWER_LIMIT, NotificationsService

pytestmark = [
    pytest.mark.domain_notifications,
]


class TestNotificationsServiceCreateAndDispatch:
    """Test create_and_dispatch business logic and error translation."""

    async def test_create_and_dispatch_foreign_key_violation_user_id(
        self, mock_pool, mock_state, mock_notifications_repo, mock_users_repo
    ):
        """ForeignKeyViolationError on user_id raises UserNotFoundError."""
        # Arrange
        service = NotificationsService(mock_pool, mock_state, mock_notifications_repo, mock_users_repo)
        mock_notifications_repo.insert_event.side_effect = ForeignKeyViolationError(
            constraint_name="notifications_events_user_id_fkey",
            table="notifications_events",
        )

        request = NotificationCreateRequest(
            user_id=999,
            event_type=NotificationEventType.MAP_EDIT_APPROVED.value,
            title="Test",
            body="Test body",
        )

        # Act & Assert
        with pytest.raises(UserNotFoundError):
            await service.create_and_dispatch(request, headers={})

    async def test_create_and_dispatch_success_no_discord_channels(
        self, mock_pool, mock_state, mock_notifications_repo, mock_users_repo, mocker
    ):
        """Successful creation without Discord channels does not publish to RabbitMQ."""
        # Arrange
        service = NotificationsService(mock_pool, mock_state, mock_notifications_repo, mock_users_repo)

        # Mock insert_event to return an event_id
        mock_notifications_repo.insert_event.return_value = 1

        # Mock fetch_event_by_id to return event data
        mock_notifications_repo.fetch_event_by_id.return_value = {
            "id": 1,
            "user_id": 123456789,
            "event_type": NotificationEventType.MAP_EDIT_APPROVED.value,
            "title": "Test",
            "body": "Test body",
            "metadata": None,
            "created_at": datetime.now(timezone.utc),
            "read_at": None,
            "dismissed_at": None,
        }

        # Mock _get_enabled_channels to return only WEB channel
        mock_notifications_repo.fetch_preferences.return_value = [
            {"event_type": NotificationEventType.MAP_EDIT_APPROVED.value, "channel": "web", "enabled": True}
        ]

        # Spy on publish_message
        publish_spy = mocker.spy(service, "publish_message")

        request = NotificationCreateRequest(
            user_id=123456789,
            event_type=NotificationEventType.MAP_EDIT_APPROVED.value,
            title="Test",
            body="Test body",
        )

        # Act
        result = await service.create_and_dispatch(request, headers={})

        # Assert
        assert result.id == 1
        assert result.user_id == 123456789
        publish_spy.assert_not_called()

    async def test_create_and_dispatch_with_discord_channels_above_limit(
        self, mock_pool, mock_state, mock_notifications_repo, mock_users_repo, mocker
    ):
        """Creation with Discord channels and user_id >= limit publishes to RabbitMQ."""
        # Arrange
        from litestar.datastructures import Headers

        service = NotificationsService(mock_pool, mock_state, mock_notifications_repo, mock_users_repo)

        mock_notifications_repo.insert_event.return_value = 1
        mock_notifications_repo.fetch_event_by_id.return_value = {
            "id": 1,
            "user_id": DISCORD_USER_ID_LOWER_LIMIT,
            "event_type": NotificationEventType.MAP_EDIT_APPROVED.value,
            "title": "Test",
            "body": "Test body",
            "metadata": None,
            "created_at": datetime.now(timezone.utc),
            "read_at": None,
            "dismissed_at": None,
        }

        # Mock preferences: Discord DM enabled
        mock_notifications_repo.fetch_preferences.return_value = [
            {"event_type": NotificationEventType.MAP_EDIT_APPROVED.value, "channel": "discord_dm", "enabled": True}
        ]

        publish_spy = mocker.spy(service, "publish_message")

        request = NotificationCreateRequest(
            user_id=DISCORD_USER_ID_LOWER_LIMIT,
            event_type=NotificationEventType.MAP_EDIT_APPROVED.value,
            title="Test",
            body="Test body",
        )

        # Act - use pytest header to skip actual RabbitMQ publishing
        headers = Headers({"X-PYTEST-ENABLED": "1"})
        result = await service.create_and_dispatch(request, headers=headers)

        # Assert
        assert result.id == 1
        publish_spy.assert_called_once()
        # Verify routing key
        assert publish_spy.call_args[1]["routing_key"] == "api.notification.delivery"

    async def test_create_and_dispatch_with_discord_channels_below_limit(
        self, mock_pool, mock_state, mock_notifications_repo, mock_users_repo, mocker
    ):
        """Creation with Discord channels but user_id < limit does not publish."""
        # Arrange
        service = NotificationsService(mock_pool, mock_state, mock_notifications_repo, mock_users_repo)

        mock_notifications_repo.insert_event.return_value = 1
        mock_notifications_repo.fetch_event_by_id.return_value = {
            "id": 1,
            "user_id": DISCORD_USER_ID_LOWER_LIMIT - 1,
            "event_type": NotificationEventType.MAP_EDIT_APPROVED.value,
            "title": "Test",
            "body": "Test body",
            "metadata": None,
            "created_at": datetime.now(timezone.utc),
            "read_at": None,
            "dismissed_at": None,
        }

        # Mock preferences: Discord DM enabled
        mock_notifications_repo.fetch_preferences.return_value = [
            {"event_type": NotificationEventType.MAP_EDIT_APPROVED.value, "channel": "discord_dm", "enabled": True}
        ]

        publish_spy = mocker.spy(service, "publish_message")

        request = NotificationCreateRequest(
            user_id=DISCORD_USER_ID_LOWER_LIMIT - 1,
            event_type=NotificationEventType.MAP_EDIT_APPROVED.value,
            title="Test",
            body="Test body",
        )

        # Act
        result = await service.create_and_dispatch(request, headers={})

        # Assert
        assert result.id == 1
        publish_spy.assert_not_called()


class TestNotificationsServiceGetPreferences:
    """Test get_preferences business logic."""

    async def test_get_preferences_with_explicit_preferences(self, mock_pool, mock_state, mock_notifications_repo, mock_users_repo):
        """Returns explicit preferences when set."""
        # Arrange
        service = NotificationsService(mock_pool, mock_state, mock_notifications_repo, mock_users_repo)

        # User has explicitly disabled discord_dm for MAP_APPROVED
        mock_notifications_repo.fetch_preferences.return_value = [
            {"event_type": NotificationEventType.MAP_EDIT_APPROVED.value, "channel": "discord_dm", "enabled": False}
        ]

        # Act
        result = await service.get_preferences(user_id=123)

        # Assert
        # Find MAP_APPROVED preference
        map_approved_pref = next(
            (p for p in result if p.event_type == NotificationEventType.MAP_EDIT_APPROVED.value), None
        )
        assert map_approved_pref is not None
        assert map_approved_pref.channels["discord_dm"] is False

    async def test_get_preferences_with_defaults(self, mock_pool, mock_state, mock_notifications_repo, mock_users_repo):
        """Returns default channels when no explicit preference."""
        # Arrange
        service = NotificationsService(mock_pool, mock_state, mock_notifications_repo, mock_users_repo)

        # No explicit preferences
        mock_notifications_repo.fetch_preferences.return_value = []

        # Act
        result = await service.get_preferences(user_id=123)

        # Assert
        # All event types should be present
        assert len(result) == len(NotificationEventType)

        # Verify structure
        for pref in result:
            assert isinstance(pref.event_type, str)
            assert isinstance(pref.channels, dict)
            # All channels should be present
            assert len(pref.channels) == len(NotificationChannel)

    async def test_get_preferences_mixed_explicit_and_defaults(
        self, mock_pool, mock_state, mock_notifications_repo, mock_users_repo
    ):
        """Merges explicit preferences with defaults."""
        # Arrange
        service = NotificationsService(mock_pool, mock_state, mock_notifications_repo, mock_users_repo)

        # User has set discord_dm=False for MAP_APPROVED, but no preference for web
        mock_notifications_repo.fetch_preferences.return_value = [
            {"event_type": NotificationEventType.MAP_EDIT_APPROVED.value, "channel": "discord_dm", "enabled": False}
        ]

        # Act
        result = await service.get_preferences(user_id=123)

        # Assert
        map_approved_pref = next(
            (p for p in result if p.event_type == NotificationEventType.MAP_EDIT_APPROVED.value), None
        )
        assert map_approved_pref is not None
        # discord_dm should be False (explicit)
        assert map_approved_pref.channels["discord_dm"] is False
        # web should be True (default for MAP_APPROVED)
        assert map_approved_pref.channels["web"] is True


class TestNotificationsServiceUpdatePreference:
    """Test update_preference error translation."""

    async def test_update_preference_foreign_key_violation_user_id(
        self, mock_pool, mock_state, mock_notifications_repo, mock_users_repo
    ):
        """ForeignKeyViolationError on user_id raises UserNotFoundError."""
        # Arrange
        service = NotificationsService(mock_pool, mock_state, mock_notifications_repo, mock_users_repo)
        mock_notifications_repo.upsert_preference.side_effect = ForeignKeyViolationError(
            constraint_name="notification_preferences_user_id_fkey",
            table="notification_preferences",
        )

        # Act & Assert
        with pytest.raises(UserNotFoundError):
            await service.update_preference(
                user_id=999,
                event_type=NotificationEventType.MAP_EDIT_APPROVED.value,
                channel=NotificationChannel.WEB.value,
                enabled=True,
            )

    async def test_update_preference_success(self, mock_pool, mock_state, mock_notifications_repo, mock_users_repo):
        """Successful preference update."""
        # Arrange
        service = NotificationsService(mock_pool, mock_state, mock_notifications_repo, mock_users_repo)

        # Act
        await service.update_preference(
            user_id=123,
            event_type=NotificationEventType.MAP_EDIT_APPROVED.value,
            channel=NotificationChannel.WEB.value,
            enabled=False,
        )

        # Assert
        mock_notifications_repo.upsert_preference.assert_called_once_with(
            user_id=123,
            event_type=NotificationEventType.MAP_EDIT_APPROVED.value,
            channel=NotificationChannel.WEB.value,
            enabled=False,
        )


class TestNotificationsServiceGetEnabledChannels:
    """Test _get_enabled_channels business logic."""

    async def test_get_enabled_channels_explicit_enabled(self, mock_pool, mock_state, mock_notifications_repo, mock_users_repo):
        """Returns explicitly enabled channels."""
        # Arrange
        service = NotificationsService(mock_pool, mock_state, mock_notifications_repo, mock_users_repo)

        mock_notifications_repo.fetch_preferences.return_value = [
            {"event_type": NotificationEventType.MAP_EDIT_APPROVED.value, "channel": "discord_dm", "enabled": True}
        ]

        # Act
        result = await service._get_enabled_channels(user_id=123, event_type=NotificationEventType.MAP_EDIT_APPROVED.value)

        # Assert
        assert "discord_dm" in result

    async def test_get_enabled_channels_explicit_disabled(self, mock_pool, mock_state, mock_notifications_repo, mock_users_repo):
        """Excludes explicitly disabled channels."""
        # Arrange
        service = NotificationsService(mock_pool, mock_state, mock_notifications_repo, mock_users_repo)

        mock_notifications_repo.fetch_preferences.return_value = [
            {"event_type": NotificationEventType.MAP_EDIT_APPROVED.value, "channel": "web", "enabled": False}
        ]

        # Act
        result = await service._get_enabled_channels(user_id=123, event_type=NotificationEventType.MAP_EDIT_APPROVED.value)

        # Assert
        assert "web" not in result

    async def test_get_enabled_channels_defaults_when_no_explicit(
        self, mock_pool, mock_state, mock_notifications_repo, mock_users_repo
    ):
        """Includes default channels when no explicit preference."""
        # Arrange
        service = NotificationsService(mock_pool, mock_state, mock_notifications_repo, mock_users_repo)

        # No preferences for this event type
        mock_notifications_repo.fetch_preferences.return_value = []

        # Act
        result = await service._get_enabled_channels(user_id=123, event_type=NotificationEventType.MAP_EDIT_APPROVED.value)

        # Assert
        # MAP_APPROVED defaults include WEB
        assert "web" in result

    async def test_get_enabled_channels_invalid_event_type(self, mock_pool, mock_state, mock_notifications_repo, mock_users_repo):
        """Handles invalid event_type gracefully with empty defaults."""
        # Arrange
        service = NotificationsService(mock_pool, mock_state, mock_notifications_repo, mock_users_repo)

        mock_notifications_repo.fetch_preferences.return_value = []

        # Act
        result = await service._get_enabled_channels(user_id=123, event_type="invalid_event_type")

        # Assert
        assert result == []


class TestNotificationsServiceRowToEventResponse:
    """Test _row_to_event_response data transformation."""

    def test_row_to_event_response_with_string_metadata(self, mock_pool, mock_state, mock_notifications_repo, mock_users_repo):
        """Converts row with JSON string metadata correctly."""
        # Arrange
        service = NotificationsService(mock_pool, mock_state, mock_notifications_repo, mock_users_repo)

        row = {
            "id": 1,
            "user_id": 123,
            "event_type": NotificationEventType.MAP_EDIT_APPROVED.value,
            "title": "Test",
            "body": "Test body",
            "metadata": '{"map_id": 456}',
            "created_at": datetime(2026, 1, 30, 12, 0, 0, tzinfo=timezone.utc),
            "read_at": None,
            "dismissed_at": None,
        }

        # Act
        result = service._row_to_event_response(row)

        # Assert
        assert result.id == 1
        assert result.user_id == 123
        assert result.metadata == {"map_id": 456}
        assert result.created_at == "2026-01-30T12:00:00+00:00"
        assert result.read_at is None
        assert result.dismissed_at is None

    def test_row_to_event_response_with_dict_metadata(self, mock_pool, mock_state, mock_notifications_repo, mock_users_repo):
        """Converts row with dict metadata correctly."""
        # Arrange
        service = NotificationsService(mock_pool, mock_state, mock_notifications_repo, mock_users_repo)

        row = {
            "id": 1,
            "user_id": 123,
            "event_type": NotificationEventType.MAP_EDIT_APPROVED.value,
            "title": "Test",
            "body": "Test body",
            "metadata": {"map_id": 456},
            "created_at": datetime(2026, 1, 30, 12, 0, 0, tzinfo=timezone.utc),
            "read_at": None,
            "dismissed_at": None,
        }

        # Act
        result = service._row_to_event_response(row)

        # Assert
        assert result.metadata == {"map_id": 456}

    def test_row_to_event_response_with_none_metadata(self, mock_pool, mock_state, mock_notifications_repo, mock_users_repo):
        """Handles None metadata correctly."""
        # Arrange
        service = NotificationsService(mock_pool, mock_state, mock_notifications_repo, mock_users_repo)

        row = {
            "id": 1,
            "user_id": 123,
            "event_type": NotificationEventType.MAP_EDIT_APPROVED.value,
            "title": "Test",
            "body": "Test body",
            "metadata": None,
            "created_at": datetime(2026, 1, 30, 12, 0, 0, tzinfo=timezone.utc),
            "read_at": None,
            "dismissed_at": None,
        }

        # Act
        result = service._row_to_event_response(row)

        # Assert
        assert result.metadata is None

    def test_row_to_event_response_with_datetimes(self, mock_pool, mock_state, mock_notifications_repo, mock_users_repo):
        """Formats datetime fields correctly."""
        # Arrange
        service = NotificationsService(mock_pool, mock_state, mock_notifications_repo, mock_users_repo)

        created = datetime(2026, 1, 30, 12, 0, 0, tzinfo=timezone.utc)
        read = datetime(2026, 1, 30, 13, 0, 0, tzinfo=timezone.utc)
        dismissed = datetime(2026, 1, 30, 14, 0, 0, tzinfo=timezone.utc)

        row = {
            "id": 1,
            "user_id": 123,
            "event_type": NotificationEventType.MAP_EDIT_APPROVED.value,
            "title": "Test",
            "body": "Test body",
            "metadata": None,
            "created_at": created,
            "read_at": read,
            "dismissed_at": dismissed,
        }

        # Act
        result = service._row_to_event_response(row)

        # Assert
        assert result.created_at == "2026-01-30T12:00:00+00:00"
        assert result.read_at == "2026-01-30T13:00:00+00:00"
        assert result.dismissed_at == "2026-01-30T14:00:00+00:00"
