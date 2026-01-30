"""Tests for NotificationsRepository edge cases and integration scenarios."""

import asyncio
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
# CONCURRENT OPERATIONS TESTS
# ==============================================================================


class TestConcurrentOperations:
    """Test concurrent operation scenarios."""

    @pytest.mark.asyncio
    async def test_concurrent_insert_events_no_collisions(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
    ) -> None:
        """Test concurrent event inserts create separate events with unique IDs."""
        # Arrange
        user_id = await create_test_user()

        # Act - insert 10 events concurrently
        tasks = [
            repository.insert_event(
                user_id=user_id,
                event_type=f"event_{i}",
                title=fake.sentence(),
                body=fake.sentence(),
                metadata=None,
                conn=asyncpg_conn,
            )
            for i in range(10)
        ]
        event_ids = await asyncio.gather(*tasks)

        # Assert - all IDs are unique
        assert len(event_ids) == 10
        assert len(set(event_ids)) == 10

    @pytest.mark.asyncio
    async def test_concurrent_mark_read_on_same_event(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_notification_event,
    ) -> None:
        """Test concurrent mark_event_read calls on same event succeed."""
        # Arrange
        event_id = await create_test_notification_event()

        # Act - mark as read concurrently 5 times
        tasks = [
            repository.mark_event_read(event_id, conn=asyncpg_conn)
            for _ in range(5)
        ]
        await asyncio.gather(*tasks)

        # Assert - event is marked as read
        row = await asyncpg_conn.fetchrow(
            "SELECT read_at FROM notifications.events WHERE id = $1",
            event_id,
        )
        assert row["read_at"] is not None

    @pytest.mark.asyncio
    async def test_concurrent_upsert_preferences_converges(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
    ) -> None:
        """Test concurrent upsert_preference calls converge to final state."""
        # Arrange
        user_id = await create_test_user()

        # Act - upsert same preference concurrently with different values
        tasks = [
            repository.upsert_preference(
                user_id=user_id,
                event_type="test_event",
                channel="discord",
                enabled=(i % 2 == 0),
                conn=asyncpg_conn,
            )
            for i in range(10)
        ]
        await asyncio.gather(*tasks)

        # Assert - only one preference record exists
        count = await asyncpg_conn.fetchval(
            "SELECT COUNT(*) FROM notifications.preferences WHERE user_id = $1",
            user_id,
        )
        assert count == 1


# ==============================================================================
# INTEGRATION SCENARIO TESTS
# ==============================================================================


class TestIntegrationScenarios:
    """Test end-to-end integration scenarios."""

    @pytest.mark.asyncio
    async def test_full_notification_lifecycle(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
    ) -> None:
        """Test complete notification lifecycle: insert -> read -> dismiss."""
        # Arrange
        user_id = await create_test_user()

        # Step 1: Insert event
        event_id = await repository.insert_event(
            user_id=user_id,
            event_type="test_event",
            title="Test Notification",
            body="This is a test",
            metadata={"key": "value"},
            conn=asyncpg_conn,
        )
        assert event_id > 0

        # Step 2: Verify appears in user events (unread)
        events = await repository.fetch_user_events(
            user_id=user_id,
            unread_only=True,
            limit=10,
            offset=0,
            conn=asyncpg_conn,
        )
        assert len(events) == 1
        assert events[0]["id"] == event_id

        # Step 3: Verify unread count
        unread_count = await repository.fetch_unread_count(user_id, conn=asyncpg_conn)
        assert unread_count == 1

        # Step 4: Mark as read
        await repository.mark_event_read(event_id, conn=asyncpg_conn)

        # Step 5: Verify no longer in unread events
        unread_events = await repository.fetch_user_events(
            user_id=user_id,
            unread_only=True,
            limit=10,
            offset=0,
            conn=asyncpg_conn,
        )
        assert len(unread_events) == 0

        # Step 6: Verify still in all events
        all_events = await repository.fetch_user_events(
            user_id=user_id,
            unread_only=False,
            limit=10,
            offset=0,
            conn=asyncpg_conn,
        )
        assert len(all_events) == 1

        # Step 7: Dismiss event
        await repository.dismiss_event(event_id, conn=asyncpg_conn)

        # Step 8: Verify no longer in any user events
        final_events = await repository.fetch_user_events(
            user_id=user_id,
            unread_only=False,
            limit=10,
            offset=0,
            conn=asyncpg_conn,
        )
        assert len(final_events) == 0

        # Step 9: Verify event still exists but is dismissed
        event = await repository.fetch_event_by_id(event_id, conn=asyncpg_conn)
        assert event is not None
        assert event["read_at"] is not None
        assert event["dismissed_at"] is not None

    @pytest.mark.asyncio
    async def test_bulk_read_then_dismiss_workflow(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
        create_test_notification_event,
    ) -> None:
        """Test bulk workflow: mark all read, then dismiss individual events."""
        # Arrange
        user_id = await create_test_user()
        event_ids = [
            await create_test_notification_event(user_id=user_id)
            for _ in range(5)
        ]

        # Step 1: Verify all unread
        unread_count = await repository.fetch_unread_count(user_id, conn=asyncpg_conn)
        assert unread_count == 5

        # Step 2: Mark all as read
        marked_count = await repository.mark_all_events_read(user_id, conn=asyncpg_conn)
        assert marked_count == 5

        # Step 3: Verify unread count is 0
        unread_count = await repository.fetch_unread_count(user_id, conn=asyncpg_conn)
        assert unread_count == 0

        # Step 4: Dismiss one event
        await repository.dismiss_event(event_ids[0], conn=asyncpg_conn)

        # Step 5: Verify 4 events remain in tray
        events = await repository.fetch_user_events(
            user_id=user_id,
            unread_only=False,
            limit=10,
            offset=0,
            conn=asyncpg_conn,
        )
        assert len(events) == 4

    @pytest.mark.asyncio
    async def test_delivery_tracking_workflow(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_notification_event,
    ) -> None:
        """Test delivery tracking workflow: insert event, record delivery attempts."""
        # Arrange
        event_id = await create_test_notification_event()

        # Step 1: Record discord delivery (success)
        await repository.record_delivery_result(
            event_id=event_id,
            channel="discord",
            status="delivered",
            error_message=None,
            conn=asyncpg_conn,
        )

        # Step 2: Record email delivery (failed)
        await repository.record_delivery_result(
            event_id=event_id,
            channel="email",
            status="failed",
            error_message="SMTP timeout",
            conn=asyncpg_conn,
        )

        # Step 3: Record push delivery (skipped)
        await repository.record_delivery_result(
            event_id=event_id,
            channel="push",
            status="skipped",
            error_message="No device registered",
            conn=asyncpg_conn,
        )

        # Step 4: Verify all delivery attempts recorded
        rows = await asyncpg_conn.fetch(
            "SELECT channel, status, error_message, delivered_at FROM notifications.delivery_log WHERE event_id = $1 ORDER BY channel",
            event_id,
        )
        assert len(rows) == 3

        # Discord - delivered
        assert rows[0]["channel"] == "discord"
        assert rows[0]["status"] == "delivered"
        assert rows[0]["delivered_at"] is not None
        assert rows[0]["error_message"] is None

        # Email - failed
        assert rows[1]["channel"] == "email"
        assert rows[1]["status"] == "failed"
        assert rows[1]["delivered_at"] is None
        assert rows[1]["error_message"] == "SMTP timeout"

        # Push - skipped
        assert rows[2]["channel"] == "push"
        assert rows[2]["status"] == "skipped"
        assert rows[2]["delivered_at"] is None
        assert rows[2]["error_message"] == "No device registered"

    @pytest.mark.asyncio
    async def test_preference_management_workflow(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
    ) -> None:
        """Test preference management workflow: set, update, fetch."""
        # Arrange
        user_id = await create_test_user()

        # Step 1: Set initial preferences
        await repository.upsert_preference(
            user_id=user_id,
            event_type="completion_submitted",
            channel="discord",
            enabled=True,
            conn=asyncpg_conn,
        )
        await repository.upsert_preference(
            user_id=user_id,
            event_type="completion_submitted",
            channel="email",
            enabled=False,
            conn=asyncpg_conn,
        )

        # Step 2: Fetch preferences
        prefs = await repository.fetch_preferences(user_id, conn=asyncpg_conn)
        assert len(prefs) == 2

        # Step 3: Update one preference
        await repository.upsert_preference(
            user_id=user_id,
            event_type="completion_submitted",
            channel="email",
            enabled=True,
            conn=asyncpg_conn,
        )

        # Step 4: Verify update
        prefs = await repository.fetch_preferences(user_id, conn=asyncpg_conn)
        assert len(prefs) == 2
        email_pref = next(p for p in prefs if p["channel"] == "email")
        assert email_pref["enabled"] is True


# ==============================================================================
# TRANSACTION EDGE CASES
# ==============================================================================


class TestTransactionEdgeCases:
    """Test complex transaction scenarios."""

    @pytest.mark.asyncio
    async def test_multiple_operations_in_transaction_commit(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
    ) -> None:
        """Test multiple operations in single transaction commit together."""
        # Arrange
        user_id = await create_test_user()

        # Act
        async with asyncpg_conn.transaction():
            # Insert event
            event_id = await repository.insert_event(
                user_id=user_id,
                event_type="test",
                title="Test",
                body="Test",
                metadata=None,
                conn=asyncpg_conn,
            )

            # Mark as read
            await repository.mark_event_read(event_id, conn=asyncpg_conn)

            # Record delivery
            await repository.record_delivery_result(
                event_id=event_id,
                channel="discord",
                status="delivered",
                error_message=None,
                conn=asyncpg_conn,
            )

        # Assert - all operations persisted
        event = await repository.fetch_event_by_id(event_id, conn=asyncpg_conn)
        assert event is not None
        assert event["read_at"] is not None

        delivery = await asyncpg_conn.fetchrow(
            "SELECT * FROM notifications.delivery_log WHERE event_id = $1",
            event_id,
        )
        assert delivery is not None

    @pytest.mark.asyncio
    async def test_multiple_operations_in_transaction_rollback(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
    ) -> None:
        """Test multiple operations in single transaction rollback together."""
        # Arrange
        user_id = await create_test_user()
        event_id = None

        # Act
        try:
            async with asyncpg_conn.transaction():
                # Insert event
                event_id = await repository.insert_event(
                    user_id=user_id,
                    event_type="test",
                    title="Test",
                    body="Test",
                    metadata=None,
                    conn=asyncpg_conn,
                )

                # Mark as read
                await repository.mark_event_read(event_id, conn=asyncpg_conn)

                # Force rollback
                raise Exception("Force rollback")
        except Exception:
            pass

        # Assert - no operations persisted
        event = await repository.fetch_event_by_id(event_id, conn=asyncpg_conn)
        assert event is None


# ==============================================================================
# BOUNDARY VALUE TESTS
# ==============================================================================


class TestBoundaryValues:
    """Test boundary value scenarios."""

    @pytest.mark.asyncio
    async def test_very_large_metadata_object(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
    ) -> None:
        """Test inserting event with very large metadata object."""
        # Arrange
        user_id = await create_test_user()
        large_metadata = {
            f"key_{i}": f"value_{i}" * 100
            for i in range(100)
        }

        # Act
        event_id = await repository.insert_event(
            user_id=user_id,
            event_type="test",
            title="Test",
            body="Test",
            metadata=large_metadata,
            conn=asyncpg_conn,
        )

        # Assert
        event = await repository.fetch_event_by_id(event_id, conn=asyncpg_conn)
        assert event["metadata"] == large_metadata

    @pytest.mark.asyncio
    async def test_fetch_user_events_very_large_limit(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
        create_test_notification_event,
    ) -> None:
        """Test fetching user events with very large limit."""
        # Arrange
        user_id = await create_test_user()
        await create_test_notification_event(user_id=user_id)

        # Act
        events = await repository.fetch_user_events(
            user_id=user_id,
            unread_only=False,
            limit=2147483647,  # Max int32
            offset=0,
            conn=asyncpg_conn,
        )

        # Assert
        assert len(events) >= 1

    @pytest.mark.asyncio
    async def test_mark_all_events_read_with_many_events(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
        create_test_notification_event,
    ) -> None:
        """Test marking all events read with many events."""
        # Arrange
        user_id = await create_test_user()
        for _ in range(20):
            await create_test_notification_event(user_id=user_id)

        # Act
        count = await repository.mark_all_events_read(user_id, conn=asyncpg_conn)

        # Assert
        assert count == 20


# ==============================================================================
# SPECIAL CHARACTER AND UNICODE TESTS
# ==============================================================================


class TestSpecialCharactersAndUnicode:
    """Test special character and unicode handling."""

    @pytest.mark.asyncio
    async def test_event_with_unicode_emoji(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
    ) -> None:
        """Test inserting event with unicode emoji characters."""
        # Arrange
        user_id = await create_test_user()
        title = "🎮 New Achievement Unlocked! 🏆"
        body = "You earned the 'Speedrunner' badge 🏃‍♂️💨"

        # Act
        event_id = await repository.insert_event(
            user_id=user_id,
            event_type="achievement",
            title=title,
            body=body,
            metadata={"emoji": "🎉"},
            conn=asyncpg_conn,
        )

        # Assert
        event = await repository.fetch_event_by_id(event_id, conn=asyncpg_conn)
        assert event["title"] == title
        assert event["body"] == body
        assert event["metadata"]["emoji"] == "🎉"

    @pytest.mark.asyncio
    async def test_event_with_japanese_characters(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
    ) -> None:
        """Test inserting event with Japanese characters."""
        # Arrange
        user_id = await create_test_user()
        title = "新しいマップが承認されました"
        body = "あなたのマップ「花村」が公式マップとして承認されました！"

        # Act
        event_id = await repository.insert_event(
            user_id=user_id,
            event_type="map_approved",
            title=title,
            body=body,
            metadata=None,
            conn=asyncpg_conn,
        )

        # Assert
        event = await repository.fetch_event_by_id(event_id, conn=asyncpg_conn)
        assert event["title"] == title
        assert event["body"] == body

    @pytest.mark.asyncio
    async def test_preference_with_special_characters(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
    ) -> None:
        """Test upserting preference with special characters."""
        # Arrange
        user_id = await create_test_user()
        event_type = "test-event_type.v2"
        channel = "webhook::https://example.com"

        # Act
        await repository.upsert_preference(
            user_id=user_id,
            event_type=event_type,
            channel=channel,
            enabled=True,
            conn=asyncpg_conn,
        )

        # Assert
        prefs = await repository.fetch_preferences(user_id, conn=asyncpg_conn)
        assert len(prefs) == 1
        assert prefs[0]["event_type"] == event_type
        assert prefs[0]["channel"] == channel


# ==============================================================================
# NULL AND EMPTY VALUE TESTS
# ==============================================================================


class TestNullAndEmptyValues:
    """Test null and empty value handling."""

    @pytest.mark.asyncio
    async def test_event_with_empty_metadata(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
    ) -> None:
        """Test inserting event with empty dict metadata."""
        # Arrange
        user_id = await create_test_user()
        metadata = {}

        # Act
        event_id = await repository.insert_event(
            user_id=user_id,
            event_type="test",
            title="Test",
            body="Test",
            metadata=metadata,
            conn=asyncpg_conn,
        )

        # Assert
        event = await repository.fetch_event_by_id(event_id, conn=asyncpg_conn)
        assert event["metadata"] == {}

    @pytest.mark.asyncio
    async def test_delivery_result_with_null_error_message(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_notification_event,
    ) -> None:
        """Test recording delivery result with null error message."""
        # Arrange
        event_id = await create_test_notification_event()

        # Act
        await repository.record_delivery_result(
            event_id=event_id,
            channel="discord",
            status="delivered",
            error_message=None,
            conn=asyncpg_conn,
        )

        # Assert
        row = await asyncpg_conn.fetchrow(
            "SELECT error_message FROM notifications.delivery_log WHERE event_id = $1",
            event_id,
        )
        assert row["error_message"] is None

    @pytest.mark.asyncio
    async def test_delivery_result_with_empty_error_message(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_notification_event,
    ) -> None:
        """Test recording delivery result with empty string error message."""
        # Arrange
        event_id = await create_test_notification_event()

        # Act
        await repository.record_delivery_result(
            event_id=event_id,
            channel="email",
            status="failed",
            error_message="",
            conn=asyncpg_conn,
        )

        # Assert
        row = await asyncpg_conn.fetchrow(
            "SELECT error_message FROM notifications.delivery_log WHERE event_id = $1",
            event_id,
        )
        assert row["error_message"] == ""
