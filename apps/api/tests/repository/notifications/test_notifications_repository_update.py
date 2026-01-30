"""Tests for NotificationsRepository update operations."""

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
# mark_event_read TESTS
# ==============================================================================


class TestMarkEventReadHappyPath:
    """Test happy path scenarios for mark_event_read."""

    @pytest.mark.asyncio
    async def test_mark_event_read_sets_read_at_timestamp(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_notification_event,
    ) -> None:
        """Test marking event as read sets read_at timestamp."""
        # Arrange
        event_id = await create_test_notification_event()

        # Verify initially unread
        row = await asyncpg_conn.fetchrow(
            "SELECT read_at FROM notifications.events WHERE id = $1",
            event_id,
        )
        assert row["read_at"] is None

        # Act
        await repository.mark_event_read(event_id, conn=asyncpg_conn)

        # Assert
        row = await asyncpg_conn.fetchrow(
            "SELECT read_at FROM notifications.events WHERE id = $1",
            event_id,
        )
        assert row["read_at"] is not None

    @pytest.mark.asyncio
    async def test_mark_event_read_does_not_modify_other_fields(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_notification_event,
    ) -> None:
        """Test marking event as read does not modify other fields."""
        # Arrange
        event_id = await create_test_notification_event()

        # Get original data
        original = await asyncpg_conn.fetchrow(
            "SELECT user_id, event_type, title, body, metadata, dismissed_at FROM notifications.events WHERE id = $1",
            event_id,
        )

        # Act
        await repository.mark_event_read(event_id, conn=asyncpg_conn)

        # Assert - other fields unchanged
        after = await asyncpg_conn.fetchrow(
            "SELECT user_id, event_type, title, body, metadata, dismissed_at FROM notifications.events WHERE id = $1",
            event_id,
        )
        assert after["user_id"] == original["user_id"]
        assert after["event_type"] == original["event_type"]
        assert after["title"] == original["title"]
        assert after["body"] == original["body"]
        assert after["metadata"] == original["metadata"]
        assert after["dismissed_at"] == original["dismissed_at"]


class TestMarkEventReadIdempotent:
    """Test idempotent behavior for mark_event_read."""

    @pytest.mark.asyncio
    async def test_mark_event_read_already_read_updates_timestamp(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_notification_event,
    ) -> None:
        """Test marking already read event updates read_at to new timestamp."""
        # Arrange
        event_id = await create_test_notification_event()

        # Mark as read first time
        await repository.mark_event_read(event_id, conn=asyncpg_conn)
        first_read_at = await asyncpg_conn.fetchval(
            "SELECT read_at FROM notifications.events WHERE id = $1",
            event_id,
        )

        # Act - mark as read second time
        await repository.mark_event_read(event_id, conn=asyncpg_conn)

        # Assert - timestamp updated
        second_read_at = await asyncpg_conn.fetchval(
            "SELECT read_at FROM notifications.events WHERE id = $1",
            event_id,
        )
        assert second_read_at >= first_read_at

    @pytest.mark.asyncio
    async def test_mark_event_read_non_existent_no_error(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
    ) -> None:
        """Test marking non-existent event as read does not raise error."""
        # Arrange
        non_existent_id = 999999999

        # Act - should not raise exception
        await repository.mark_event_read(non_existent_id, conn=asyncpg_conn)

        # Assert - no exception raised (implicit)


class TestMarkEventReadTransactions:
    """Test transaction behavior for mark_event_read."""

    @pytest.mark.asyncio
    async def test_mark_event_read_within_transaction_commits(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_notification_event,
    ) -> None:
        """Test marking event as read within transaction persists after commit."""
        # Arrange
        event_id = await create_test_notification_event()

        # Act
        async with asyncpg_conn.transaction():
            await repository.mark_event_read(event_id, conn=asyncpg_conn)

        # Assert - change persisted
        row = await asyncpg_conn.fetchrow(
            "SELECT read_at FROM notifications.events WHERE id = $1",
            event_id,
        )
        assert row["read_at"] is not None

    @pytest.mark.asyncio
    async def test_mark_event_read_within_transaction_rollback(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_notification_event,
    ) -> None:
        """Test marking event as read within rolled back transaction discards change."""
        # Arrange
        event_id = await create_test_notification_event()

        # Act
        try:
            async with asyncpg_conn.transaction():
                await repository.mark_event_read(event_id, conn=asyncpg_conn)
                raise Exception("Force rollback")
        except Exception:
            pass

        # Assert - change discarded
        row = await asyncpg_conn.fetchrow(
            "SELECT read_at FROM notifications.events WHERE id = $1",
            event_id,
        )
        assert row["read_at"] is None


# ==============================================================================
# mark_all_events_read TESTS
# ==============================================================================


class TestMarkAllEventsReadHappyPath:
    """Test happy path scenarios for mark_all_events_read."""

    @pytest.mark.asyncio
    async def test_mark_all_events_read_returns_count(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
        create_test_notification_event,
    ) -> None:
        """Test marking all events read returns count of marked events."""
        # Arrange
        user_id = await create_test_user()
        await create_test_notification_event(user_id=user_id)
        await create_test_notification_event(user_id=user_id)
        await create_test_notification_event(user_id=user_id)

        # Act
        count = await repository.mark_all_events_read(user_id, conn=asyncpg_conn)

        # Assert
        assert count == 3

    @pytest.mark.asyncio
    async def test_mark_all_events_read_sets_read_at_for_all(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
        create_test_notification_event,
    ) -> None:
        """Test marking all events read sets read_at for all user events."""
        # Arrange
        user_id = await create_test_user()
        event_id_1 = await create_test_notification_event(user_id=user_id)
        event_id_2 = await create_test_notification_event(user_id=user_id)

        # Act
        await repository.mark_all_events_read(user_id, conn=asyncpg_conn)

        # Assert - both events marked as read
        rows = await asyncpg_conn.fetch(
            "SELECT id, read_at FROM notifications.events WHERE user_id = $1",
            user_id,
        )
        assert len(rows) == 2
        assert all(row["read_at"] is not None for row in rows)

    @pytest.mark.asyncio
    async def test_mark_all_events_read_zero_unread_returns_zero(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
    ) -> None:
        """Test marking all events read with no unread events returns 0."""
        # Arrange
        user_id = await create_test_user()

        # Act
        count = await repository.mark_all_events_read(user_id, conn=asyncpg_conn)

        # Assert
        assert count == 0


class TestMarkAllEventsReadFiltering:
    """Test filtering behavior for mark_all_events_read."""

    @pytest.mark.asyncio
    async def test_mark_all_events_read_excludes_already_read(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
        create_test_notification_event,
    ) -> None:
        """Test marking all events read only marks unread events."""
        # Arrange
        user_id = await create_test_user()
        unread_event = await create_test_notification_event(user_id=user_id)
        already_read_event = await create_test_notification_event(user_id=user_id)

        # Mark one as already read
        await asyncpg_conn.execute(
            "UPDATE notifications.events SET read_at = '2024-01-01 00:00:00'::timestamp WHERE id = $1",
            already_read_event,
        )

        # Act
        count = await repository.mark_all_events_read(user_id, conn=asyncpg_conn)

        # Assert - only 1 event marked (the previously unread one)
        assert count == 1

    @pytest.mark.asyncio
    async def test_mark_all_events_read_includes_dismissed_events(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
        create_test_notification_event,
    ) -> None:
        """Test marking all events read includes dismissed events."""
        # Arrange
        user_id = await create_test_user()
        active_event = await create_test_notification_event(user_id=user_id)
        dismissed_event = await create_test_notification_event(user_id=user_id)

        # Dismiss one event
        await asyncpg_conn.execute(
            "UPDATE notifications.events SET dismissed_at = now() WHERE id = $1",
            dismissed_event,
        )

        # Act
        count = await repository.mark_all_events_read(user_id, conn=asyncpg_conn)

        # Assert - both events marked (dismissed events still counted)
        assert count == 2


class TestMarkAllEventsReadIsolation:
    """Test user isolation for mark_all_events_read."""

    @pytest.mark.asyncio
    async def test_mark_all_events_read_isolates_different_users(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
        create_test_notification_event,
    ) -> None:
        """Test marking all events read only affects specified user."""
        # Arrange
        user1_id = await create_test_user()
        user2_id = await create_test_user()

        user1_event = await create_test_notification_event(user_id=user1_id)
        user2_event = await create_test_notification_event(user_id=user2_id)

        # Act - mark all for user1
        count = await repository.mark_all_events_read(user1_id, conn=asyncpg_conn)

        # Assert
        assert count == 1

        # Verify user1's event is read
        user1_row = await asyncpg_conn.fetchrow(
            "SELECT read_at FROM notifications.events WHERE id = $1",
            user1_event,
        )
        assert user1_row["read_at"] is not None

        # Verify user2's event is still unread
        user2_row = await asyncpg_conn.fetchrow(
            "SELECT read_at FROM notifications.events WHERE id = $1",
            user2_event,
        )
        assert user2_row["read_at"] is None


# ==============================================================================
# dismiss_event TESTS
# ==============================================================================


class TestDismissEventHappyPath:
    """Test happy path scenarios for dismiss_event."""

    @pytest.mark.asyncio
    async def test_dismiss_event_sets_dismissed_at_timestamp(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_notification_event,
    ) -> None:
        """Test dismissing event sets dismissed_at timestamp."""
        # Arrange
        event_id = await create_test_notification_event()

        # Verify initially not dismissed
        row = await asyncpg_conn.fetchrow(
            "SELECT dismissed_at FROM notifications.events WHERE id = $1",
            event_id,
        )
        assert row["dismissed_at"] is None

        # Act
        await repository.dismiss_event(event_id, conn=asyncpg_conn)

        # Assert
        row = await asyncpg_conn.fetchrow(
            "SELECT dismissed_at FROM notifications.events WHERE id = $1",
            event_id,
        )
        assert row["dismissed_at"] is not None

    @pytest.mark.asyncio
    async def test_dismiss_event_does_not_modify_other_fields(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_notification_event,
    ) -> None:
        """Test dismissing event does not modify other fields."""
        # Arrange
        event_id = await create_test_notification_event()

        # Get original data
        original = await asyncpg_conn.fetchrow(
            "SELECT user_id, event_type, title, body, metadata, read_at FROM notifications.events WHERE id = $1",
            event_id,
        )

        # Act
        await repository.dismiss_event(event_id, conn=asyncpg_conn)

        # Assert - other fields unchanged
        after = await asyncpg_conn.fetchrow(
            "SELECT user_id, event_type, title, body, metadata, read_at FROM notifications.events WHERE id = $1",
            event_id,
        )
        assert after["user_id"] == original["user_id"]
        assert after["event_type"] == original["event_type"]
        assert after["title"] == original["title"]
        assert after["body"] == original["body"]
        assert after["metadata"] == original["metadata"]
        assert after["read_at"] == original["read_at"]


class TestDismissEventIdempotent:
    """Test idempotent behavior for dismiss_event."""

    @pytest.mark.asyncio
    async def test_dismiss_event_already_dismissed_updates_timestamp(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_notification_event,
    ) -> None:
        """Test dismissing already dismissed event updates dismissed_at to new timestamp."""
        # Arrange
        event_id = await create_test_notification_event()

        # Dismiss first time
        await repository.dismiss_event(event_id, conn=asyncpg_conn)
        first_dismissed_at = await asyncpg_conn.fetchval(
            "SELECT dismissed_at FROM notifications.events WHERE id = $1",
            event_id,
        )

        # Act - dismiss second time
        await repository.dismiss_event(event_id, conn=asyncpg_conn)

        # Assert - timestamp updated
        second_dismissed_at = await asyncpg_conn.fetchval(
            "SELECT dismissed_at FROM notifications.events WHERE id = $1",
            event_id,
        )
        assert second_dismissed_at >= first_dismissed_at

    @pytest.mark.asyncio
    async def test_dismiss_event_non_existent_no_error(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
    ) -> None:
        """Test dismissing non-existent event does not raise error."""
        # Arrange
        non_existent_id = 999999999

        # Act - should not raise exception
        await repository.dismiss_event(non_existent_id, conn=asyncpg_conn)

        # Assert - no exception raised (implicit)


class TestDismissEventIntegration:
    """Test integration with other operations for dismiss_event."""

    @pytest.mark.asyncio
    async def test_dismiss_event_excluded_from_fetch_user_events(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
        create_test_notification_event,
    ) -> None:
        """Test dismissed events are excluded from fetch_user_events."""
        # Arrange
        user_id = await create_test_user()
        active_event = await create_test_notification_event(user_id=user_id)
        dismissed_event = await create_test_notification_event(user_id=user_id)

        # Act - dismiss one event
        await repository.dismiss_event(dismissed_event, conn=asyncpg_conn)

        # Fetch user events
        events = await repository.fetch_user_events(
            user_id=user_id,
            unread_only=False,
            limit=10,
            offset=0,
            conn=asyncpg_conn,
        )

        # Assert - only active event returned
        event_ids = [event["id"] for event in events]
        assert active_event in event_ids
        assert dismissed_event not in event_ids

    @pytest.mark.asyncio
    async def test_dismiss_event_excluded_from_unread_count(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
        create_test_notification_event,
    ) -> None:
        """Test dismissed events are excluded from unread count."""
        # Arrange
        user_id = await create_test_user()
        active_event = await create_test_notification_event(user_id=user_id)
        dismissed_event = await create_test_notification_event(user_id=user_id)

        # Act - dismiss one event
        await repository.dismiss_event(dismissed_event, conn=asyncpg_conn)

        # Get unread count
        count = await repository.fetch_unread_count(user_id, conn=asyncpg_conn)

        # Assert - only active event counted
        assert count == 1


class TestDismissEventTransactions:
    """Test transaction behavior for dismiss_event."""

    @pytest.mark.asyncio
    async def test_dismiss_event_within_transaction_commits(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_notification_event,
    ) -> None:
        """Test dismissing event within transaction persists after commit."""
        # Arrange
        event_id = await create_test_notification_event()

        # Act
        async with asyncpg_conn.transaction():
            await repository.dismiss_event(event_id, conn=asyncpg_conn)

        # Assert - change persisted
        row = await asyncpg_conn.fetchrow(
            "SELECT dismissed_at FROM notifications.events WHERE id = $1",
            event_id,
        )
        assert row["dismissed_at"] is not None

    @pytest.mark.asyncio
    async def test_dismiss_event_within_transaction_rollback(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_notification_event,
    ) -> None:
        """Test dismissing event within rolled back transaction discards change."""
        # Arrange
        event_id = await create_test_notification_event()

        # Act
        try:
            async with asyncpg_conn.transaction():
                await repository.dismiss_event(event_id, conn=asyncpg_conn)
                raise Exception("Force rollback")
        except Exception:
            pass

        # Assert - change discarded
        row = await asyncpg_conn.fetchrow(
            "SELECT dismissed_at FROM notifications.events WHERE id = $1",
            event_id,
        )
        assert row["dismissed_at"] is None
