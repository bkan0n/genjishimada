"""Tests for NotificationsRepository read operations."""

from uuid import uuid4

import pytest
from faker import Faker

from repository.notifications_repository import NotificationsRepository

fake = Faker()

pytestmark = [
    pytest.mark.domain_notifications,
]


@pytest.fixture
async def repository(asyncpg_conn):
    """Provide notifications repository instance."""
    return NotificationsRepository(asyncpg_conn)


# ==============================================================================
# fetch_event_by_id TESTS
# ==============================================================================


class TestFetchEventByIdHappyPath:
    """Test happy path scenarios for fetch_event_by_id."""

    @pytest.mark.asyncio
    async def test_fetch_event_by_id_returns_event_dict(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_notification_event,
    ) -> None:
        """Test fetching event by ID returns event dict with all fields."""
        # Arrange
        event_id = await create_test_notification_event()

        # Act
        result = await repository.fetch_event_by_id(event_id, conn=asyncpg_conn)

        # Assert
        assert result is not None
        assert isinstance(result, dict)
        assert result["id"] == event_id
        assert "user_id" in result
        assert "event_type" in result
        assert "title" in result
        assert "body" in result
        assert "metadata" in result
        assert "created_at" in result
        assert "read_at" in result
        assert "dismissed_at" in result

    @pytest.mark.asyncio
    async def test_fetch_event_by_id_returns_correct_data(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
        create_test_notification_event,
    ) -> None:
        """Test fetching event by ID returns correct event data."""
        # Arrange
        user_id = await create_test_user()
        event_type = "test_event"
        title = "Test Title"
        body = "Test Body"
        metadata = {"key": "value", "number": 42}

        event_id = await create_test_notification_event(
            user_id=user_id,
            event_type=event_type,
            title=title,
            body=body,
            metadata=metadata,
        )

        # Act
        result = await repository.fetch_event_by_id(event_id, conn=asyncpg_conn)

        # Assert
        assert result is not None
        assert result["user_id"] == user_id
        assert result["event_type"] == event_type
        assert result["title"] == title
        assert result["body"] == body
        # Metadata is returned as JSON string, parse it
        import json
        metadata_parsed = json.loads(result["metadata"]) if isinstance(result["metadata"], str) else result["metadata"]
        assert metadata_parsed == metadata

# ==============================================================================
# fetch_user_events TESTS
# ==============================================================================


class TestFetchUserEventsHappyPath:
    """Test happy path scenarios for fetch_user_events."""

    @pytest.mark.asyncio
    async def test_fetch_user_events_returns_user_events(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
        create_test_notification_event,
    ) -> None:
        """Test fetching user events returns events for that user."""
        # Arrange
        user_id = await create_test_user()
        event_id_1 = await create_test_notification_event(user_id=user_id)
        event_id_2 = await create_test_notification_event(user_id=user_id)

        # Act
        result = await repository.fetch_user_events(
            user_id=user_id,
            unread_only=False,
            limit=10,
            offset=0,
            conn=asyncpg_conn,
        )

        # Assert
        assert isinstance(result, list)
        assert len(result) >= 2
        event_ids = [event["id"] for event in result]
        assert event_id_1 in event_ids
        assert event_id_2 in event_ids

    @pytest.mark.asyncio
    async def test_fetch_user_events_empty_when_no_events(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
    ) -> None:
        """Test fetching user events returns empty list when user has no events."""
        # Arrange
        user_id = await create_test_user()

        # Act
        result = await repository.fetch_user_events(
            user_id=user_id,
            unread_only=False,
            limit=10,
            offset=0,
            conn=asyncpg_conn,
        )

        # Assert
        assert result == []

# ==============================================================================
# fetch_unread_count TESTS
# ==============================================================================


