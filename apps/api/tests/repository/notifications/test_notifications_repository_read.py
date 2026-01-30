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

    @pytest.mark.asyncio
    async def test_fetch_event_by_id_with_null_metadata(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_notification_event,
    ) -> None:
        """Test fetching event with null metadata returns None for metadata field."""
        # Arrange
        event_id = await create_test_notification_event(metadata=None)

        # Act
        result = await repository.fetch_event_by_id(event_id, conn=asyncpg_conn)

        # Assert
        assert result is not None
        assert result["metadata"] is None

    @pytest.mark.asyncio
    async def test_fetch_event_by_id_returns_timestamps(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_notification_event,
    ) -> None:
        """Test fetching event by ID returns timestamp fields correctly."""
        # Arrange
        event_id = await create_test_notification_event()

        # Act
        result = await repository.fetch_event_by_id(event_id, conn=asyncpg_conn)

        # Assert
        assert result is not None
        assert result["created_at"] is not None
        assert result["read_at"] is None  # Not yet read
        assert result["dismissed_at"] is None  # Not yet dismissed


class TestFetchEventByIdNotFound:
    """Test fetch_event_by_id when event does not exist."""

    @pytest.mark.asyncio
    async def test_fetch_event_by_id_non_existent_returns_none(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
    ) -> None:
        """Test fetching non-existent event returns None."""
        # Arrange
        non_existent_id = 999999999

        # Act
        result = await repository.fetch_event_by_id(non_existent_id, conn=asyncpg_conn)

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_event_by_id_negative_id_returns_none(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
    ) -> None:
        """Test fetching event with negative ID returns None."""
        # Arrange
        negative_id = -1

        # Act
        result = await repository.fetch_event_by_id(negative_id, conn=asyncpg_conn)

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_event_by_id_zero_returns_none(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
    ) -> None:
        """Test fetching event with ID zero returns None."""
        # Act
        result = await repository.fetch_event_by_id(0, conn=asyncpg_conn)

        # Assert
        assert result is None


class TestFetchEventByIdTransactions:
    """Test transaction behavior for fetch_event_by_id."""

    @pytest.mark.asyncio
    async def test_fetch_event_by_id_within_transaction(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_notification_event,
    ) -> None:
        """Test fetching event within transaction works correctly."""
        # Arrange
        event_id = await create_test_notification_event()

        # Act
        async with asyncpg_conn.transaction():
            result = await repository.fetch_event_by_id(event_id, conn=asyncpg_conn)

        # Assert
        assert result is not None
        assert result["id"] == event_id


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


class TestFetchUserEventsPagination:
    """Test pagination for fetch_user_events."""

    @pytest.mark.asyncio
    async def test_fetch_user_events_respects_limit(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
        create_test_notification_event,
    ) -> None:
        """Test fetching user events respects limit parameter."""
        # Arrange
        user_id = await create_test_user()
        for _ in range(5):
            await create_test_notification_event(user_id=user_id)

        # Act
        result = await repository.fetch_user_events(
            user_id=user_id,
            unread_only=False,
            limit=2,
            offset=0,
            conn=asyncpg_conn,
        )

        # Assert
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_fetch_user_events_respects_offset(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
        create_test_notification_event,
    ) -> None:
        """Test fetching user events respects offset parameter."""
        # Arrange
        user_id = await create_test_user()
        for _ in range(5):
            await create_test_notification_event(user_id=user_id)

        # Act - get first page
        page1 = await repository.fetch_user_events(
            user_id=user_id,
            unread_only=False,
            limit=2,
            offset=0,
            conn=asyncpg_conn,
        )

        # Act - get second page
        page2 = await repository.fetch_user_events(
            user_id=user_id,
            unread_only=False,
            limit=2,
            offset=2,
            conn=asyncpg_conn,
        )

        # Assert - pages should have different events
        assert len(page1) == 2
        assert len(page2) == 2
        assert page1[0]["id"] != page2[0]["id"]

    @pytest.mark.asyncio
    async def test_fetch_user_events_limit_zero_returns_empty(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
        create_test_notification_event,
    ) -> None:
        """Test fetching user events with limit=0 returns empty list."""
        # Arrange
        user_id = await create_test_user()
        await create_test_notification_event(user_id=user_id)

        # Act
        result = await repository.fetch_user_events(
            user_id=user_id,
            unread_only=False,
            limit=0,
            offset=0,
            conn=asyncpg_conn,
        )

        # Assert
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_user_events_offset_beyond_results_returns_empty(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
        create_test_notification_event,
    ) -> None:
        """Test fetching user events with offset beyond results returns empty list."""
        # Arrange
        user_id = await create_test_user()
        await create_test_notification_event(user_id=user_id)

        # Act
        result = await repository.fetch_user_events(
            user_id=user_id,
            unread_only=False,
            limit=10,
            offset=100,
            conn=asyncpg_conn,
        )

        # Assert
        assert result == []


class TestFetchUserEventsFiltering:
    """Test filtering for fetch_user_events."""

    @pytest.mark.asyncio
    async def test_fetch_user_events_unread_only_filters_read_events(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
        create_test_notification_event,
    ) -> None:
        """Test fetching user events with unread_only=True excludes read events."""
        # Arrange
        user_id = await create_test_user()
        unread_event_id = await create_test_notification_event(user_id=user_id)
        read_event_id = await create_test_notification_event(user_id=user_id)

        # Mark one event as read
        await asyncpg_conn.execute(
            "UPDATE notifications.events SET read_at = now() WHERE id = $1",
            read_event_id,
        )

        # Act
        result = await repository.fetch_user_events(
            user_id=user_id,
            unread_only=True,
            limit=10,
            offset=0,
            conn=asyncpg_conn,
        )

        # Assert
        event_ids = [event["id"] for event in result]
        assert unread_event_id in event_ids
        assert read_event_id not in event_ids

    @pytest.mark.asyncio
    async def test_fetch_user_events_unread_only_false_includes_read(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
        create_test_notification_event,
    ) -> None:
        """Test fetching user events with unread_only=False includes read events."""
        # Arrange
        user_id = await create_test_user()
        unread_event_id = await create_test_notification_event(user_id=user_id)
        read_event_id = await create_test_notification_event(user_id=user_id)

        # Mark one event as read
        await asyncpg_conn.execute(
            "UPDATE notifications.events SET read_at = now() WHERE id = $1",
            read_event_id,
        )

        # Act
        result = await repository.fetch_user_events(
            user_id=user_id,
            unread_only=False,
            limit=10,
            offset=0,
            conn=asyncpg_conn,
        )

        # Assert
        event_ids = [event["id"] for event in result]
        assert unread_event_id in event_ids
        assert read_event_id in event_ids

    @pytest.mark.asyncio
    async def test_fetch_user_events_excludes_dismissed_events(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
        create_test_notification_event,
    ) -> None:
        """Test fetching user events always excludes dismissed events."""
        # Arrange
        user_id = await create_test_user()
        active_event_id = await create_test_notification_event(user_id=user_id)
        dismissed_event_id = await create_test_notification_event(user_id=user_id)

        # Dismiss one event
        await asyncpg_conn.execute(
            "UPDATE notifications.events SET dismissed_at = now() WHERE id = $1",
            dismissed_event_id,
        )

        # Act
        result = await repository.fetch_user_events(
            user_id=user_id,
            unread_only=False,
            limit=10,
            offset=0,
            conn=asyncpg_conn,
        )

        # Assert
        event_ids = [event["id"] for event in result]
        assert active_event_id in event_ids
        assert dismissed_event_id not in event_ids


class TestFetchUserEventsOrdering:
    """Test ordering for fetch_user_events."""

    @pytest.mark.asyncio
    async def test_fetch_user_events_ordered_by_created_at_desc(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
        create_test_notification_event,
    ) -> None:
        """Test fetching user events returns events ordered by created_at DESC."""
        # Arrange
        user_id = await create_test_user()
        event_ids = []
        for _ in range(3):
            event_id = await create_test_notification_event(user_id=user_id)
            event_ids.append(event_id)

        # Act
        result = await repository.fetch_user_events(
            user_id=user_id,
            unread_only=False,
            limit=10,
            offset=0,
            conn=asyncpg_conn,
        )

        # Assert - most recent first
        assert len(result) >= 3
        for i in range(len(result) - 1):
            assert result[i]["created_at"] >= result[i + 1]["created_at"]


class TestFetchUserEventsIsolation:
    """Test user isolation for fetch_user_events."""

    @pytest.mark.asyncio
    async def test_fetch_user_events_isolates_different_users(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
        create_test_notification_event,
    ) -> None:
        """Test fetching user events only returns events for specified user."""
        # Arrange
        user1_id = await create_test_user()
        user2_id = await create_test_user()

        user1_event = await create_test_notification_event(user_id=user1_id)
        user2_event = await create_test_notification_event(user_id=user2_id)

        # Act
        user1_events = await repository.fetch_user_events(
            user_id=user1_id,
            unread_only=False,
            limit=10,
            offset=0,
            conn=asyncpg_conn,
        )

        # Assert
        user1_event_ids = [event["id"] for event in user1_events]
        assert user1_event in user1_event_ids
        assert user2_event not in user1_event_ids


# ==============================================================================
# fetch_unread_count TESTS
# ==============================================================================


class TestFetchUnreadCountHappyPath:
    """Test happy path scenarios for fetch_unread_count."""

    @pytest.mark.asyncio
    async def test_fetch_unread_count_returns_zero_when_no_events(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
    ) -> None:
        """Test fetching unread count returns 0 when user has no events."""
        # Arrange
        user_id = await create_test_user()

        # Act
        count = await repository.fetch_unread_count(user_id, conn=asyncpg_conn)

        # Assert
        assert count == 0

    @pytest.mark.asyncio
    async def test_fetch_unread_count_counts_unread_events(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
        create_test_notification_event,
    ) -> None:
        """Test fetching unread count returns correct count of unread events."""
        # Arrange
        user_id = await create_test_user()
        await create_test_notification_event(user_id=user_id)
        await create_test_notification_event(user_id=user_id)
        await create_test_notification_event(user_id=user_id)

        # Act
        count = await repository.fetch_unread_count(user_id, conn=asyncpg_conn)

        # Assert
        assert count == 3


class TestFetchUnreadCountFiltering:
    """Test filtering for fetch_unread_count."""

    @pytest.mark.asyncio
    async def test_fetch_unread_count_excludes_read_events(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
        create_test_notification_event,
    ) -> None:
        """Test fetching unread count excludes read events."""
        # Arrange
        user_id = await create_test_user()
        await create_test_notification_event(user_id=user_id)
        read_event_id = await create_test_notification_event(user_id=user_id)

        # Mark one as read
        await asyncpg_conn.execute(
            "UPDATE notifications.events SET read_at = now() WHERE id = $1",
            read_event_id,
        )

        # Act
        count = await repository.fetch_unread_count(user_id, conn=asyncpg_conn)

        # Assert
        assert count == 1

    @pytest.mark.asyncio
    async def test_fetch_unread_count_excludes_dismissed_events(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
        create_test_notification_event,
    ) -> None:
        """Test fetching unread count excludes dismissed events."""
        # Arrange
        user_id = await create_test_user()
        await create_test_notification_event(user_id=user_id)
        dismissed_event_id = await create_test_notification_event(user_id=user_id)

        # Dismiss one event
        await asyncpg_conn.execute(
            "UPDATE notifications.events SET dismissed_at = now() WHERE id = $1",
            dismissed_event_id,
        )

        # Act
        count = await repository.fetch_unread_count(user_id, conn=asyncpg_conn)

        # Assert
        assert count == 1

    @pytest.mark.asyncio
    async def test_fetch_unread_count_excludes_read_and_dismissed(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
        create_test_notification_event,
    ) -> None:
        """Test fetching unread count excludes both read and dismissed events."""
        # Arrange
        user_id = await create_test_user()
        unread_event = await create_test_notification_event(user_id=user_id)
        read_event = await create_test_notification_event(user_id=user_id)
        dismissed_event = await create_test_notification_event(user_id=user_id)

        # Mark as read
        await asyncpg_conn.execute(
            "UPDATE notifications.events SET read_at = now() WHERE id = $1",
            read_event,
        )

        # Dismiss
        await asyncpg_conn.execute(
            "UPDATE notifications.events SET dismissed_at = now() WHERE id = $1",
            dismissed_event,
        )

        # Act
        count = await repository.fetch_unread_count(user_id, conn=asyncpg_conn)

        # Assert
        assert count == 1


class TestFetchUnreadCountIsolation:
    """Test user isolation for fetch_unread_count."""

    @pytest.mark.asyncio
    async def test_fetch_unread_count_isolates_different_users(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
        create_test_notification_event,
    ) -> None:
        """Test fetching unread count only counts events for specified user."""
        # Arrange
        user1_id = await create_test_user()
        user2_id = await create_test_user()

        await create_test_notification_event(user_id=user1_id)
        await create_test_notification_event(user_id=user1_id)
        await create_test_notification_event(user_id=user2_id)

        # Act
        user1_count = await repository.fetch_unread_count(user1_id, conn=asyncpg_conn)

        # Assert
        assert user1_count == 2


# ==============================================================================
# fetch_preferences TESTS
# ==============================================================================


class TestFetchPreferencesHappyPath:
    """Test happy path scenarios for fetch_preferences."""

    @pytest.mark.asyncio
    async def test_fetch_preferences_returns_empty_when_no_preferences(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
    ) -> None:
        """Test fetching preferences returns empty list when user has no preferences."""
        # Arrange
        user_id = await create_test_user()

        # Act
        result = await repository.fetch_preferences(user_id, conn=asyncpg_conn)

        # Assert
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_preferences_returns_user_preferences(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
    ) -> None:
        """Test fetching preferences returns all preferences for user."""
        # Arrange
        user_id = await create_test_user()

        # Insert preferences
        await asyncpg_conn.execute(
            """
            INSERT INTO notifications.preferences (user_id, event_type, channel, enabled)
            VALUES ($1, $2, $3, $4)
            """,
            user_id,
            "completion_submitted",
            "discord",
            True,
        )
        await asyncpg_conn.execute(
            """
            INSERT INTO notifications.preferences (user_id, event_type, channel, enabled)
            VALUES ($1, $2, $3, $4)
            """,
            user_id,
            "map_approved",
            "email",
            False,
        )

        # Act
        result = await repository.fetch_preferences(user_id, conn=asyncpg_conn)

        # Assert
        assert len(result) == 2
        assert all("event_type" in pref for pref in result)
        assert all("channel" in pref for pref in result)
        assert all("enabled" in pref for pref in result)

    @pytest.mark.asyncio
    async def test_fetch_preferences_returns_all_fields(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
    ) -> None:
        """Test fetching preferences returns all expected fields."""
        # Arrange
        user_id = await create_test_user()
        await asyncpg_conn.execute(
            """
            INSERT INTO notifications.preferences (user_id, event_type, channel, enabled)
            VALUES ($1, $2, $3, $4)
            """,
            user_id,
            "test_event",
            "test_channel",
            True,
        )

        # Act
        result = await repository.fetch_preferences(user_id, conn=asyncpg_conn)

        # Assert
        assert len(result) == 1
        pref = result[0]
        assert pref["event_type"] == "test_event"
        assert pref["channel"] == "test_channel"
        assert pref["enabled"] is True


class TestFetchPreferencesIsolation:
    """Test user isolation for fetch_preferences."""

    @pytest.mark.asyncio
    async def test_fetch_preferences_isolates_different_users(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
    ) -> None:
        """Test fetching preferences only returns preferences for specified user."""
        # Arrange
        user1_id = await create_test_user()
        user2_id = await create_test_user()

        # Insert preferences for both users
        await asyncpg_conn.execute(
            """
            INSERT INTO notifications.preferences (user_id, event_type, channel, enabled)
            VALUES ($1, $2, $3, $4)
            """,
            user1_id,
            "test_event",
            "discord",
            True,
        )
        await asyncpg_conn.execute(
            """
            INSERT INTO notifications.preferences (user_id, event_type, channel, enabled)
            VALUES ($1, $2, $3, $4)
            """,
            user2_id,
            "test_event",
            "email",
            False,
        )

        # Act
        user1_prefs = await repository.fetch_preferences(user1_id, conn=asyncpg_conn)

        # Assert
        assert len(user1_prefs) == 1
        assert user1_prefs[0]["channel"] == "discord"
