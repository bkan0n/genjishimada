"""Tests for NotificationsRepository create operations."""

import json
from uuid import uuid4

import pytest
from faker import Faker

from repository.exceptions import ForeignKeyViolationError
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
# insert_event TESTS
# ==============================================================================


class TestInsertEventHappyPath:
    """Test happy path scenarios for insert_event."""

    @pytest.mark.asyncio
    async def test_insert_event_with_valid_data_returns_id(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
    ) -> None:
        """Test inserting event with valid data returns event ID."""
        # Arrange
        user_id = await create_test_user()
        event_type = fake.word()
        title = fake.sentence(nb_words=5)
        body = fake.sentence(nb_words=15)

        # Act
        event_id = await repository.insert_event(
            user_id=user_id,
            event_type=event_type,
            title=title,
            body=body,
            metadata=None,
            conn=asyncpg_conn,
        )

        # Assert
        assert isinstance(event_id, int)
        assert event_id > 0

        # Verify in database
        row = await asyncpg_conn.fetchrow(
            "SELECT * FROM notifications.events WHERE id = $1",
            event_id,
        )
        assert row is not None
        assert row["user_id"] == user_id
        assert row["event_type"] == event_type
        assert row["title"] == title
        assert row["body"] == body
        assert row["metadata"] is None

    @pytest.mark.asyncio
    async def test_insert_event_with_metadata_stores_json(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
    ) -> None:
        """Test inserting event with metadata stores JSON correctly."""
        # Arrange
        user_id = await create_test_user()
        metadata = {
            "map_code": "TEST123",
            "rank": 1,
            "nested": {"key": "value"},
        }

        # Act
        event_id = await repository.insert_event(
            user_id=user_id,
            event_type="completion_submitted",
            title=fake.sentence(),
            body=fake.sentence(),
            metadata=metadata,
            conn=asyncpg_conn,
        )

        # Assert
        row = await asyncpg_conn.fetchrow(
            "SELECT metadata FROM notifications.events WHERE id = $1",
            event_id,
        )
        assert row is not None
        # Metadata is stored as JSONB and returned as JSON string
        import json
        assert json.loads(row["metadata"]) == metadata

    @pytest.mark.asyncio
    async def test_insert_event_sets_created_at_timestamp(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
    ) -> None:
        """Test inserting event sets created_at timestamp."""
        # Arrange
        user_id = await create_test_user()

        # Act
        event_id = await repository.insert_event(
            user_id=user_id,
            event_type=fake.word(),
            title=fake.sentence(),
            body=fake.sentence(),
            metadata=None,
            conn=asyncpg_conn,
        )

        # Assert
        row = await asyncpg_conn.fetchrow(
            "SELECT created_at, read_at, dismissed_at FROM notifications.events WHERE id = $1",
            event_id,
        )
        assert row is not None
        assert row["created_at"] is not None
        assert row["read_at"] is None
        assert row["dismissed_at"] is None


class TestInsertEventEdgeCases:
    """Test edge cases for insert_event."""

    @pytest.mark.asyncio
    async def test_insert_event_with_empty_strings_succeeds(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
    ) -> None:
        """Test inserting event with empty strings succeeds."""
        # Arrange
        user_id = await create_test_user()

        # Act
        event_id = await repository.insert_event(
            user_id=user_id,
            event_type="",
            title="",
            body="",
            metadata=None,
            conn=asyncpg_conn,
        )

        # Assert
        assert isinstance(event_id, int)
        row = await asyncpg_conn.fetchrow(
            "SELECT event_type, title, body FROM notifications.events WHERE id = $1",
            event_id,
        )
        assert row["event_type"] == ""
        assert row["title"] == ""
        assert row["body"] == ""

    @pytest.mark.asyncio
    async def test_insert_event_with_special_characters_succeeds(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
    ) -> None:
        """Test inserting event with special characters succeeds."""
        # Arrange
        user_id = await create_test_user()
        title = "Test <script>alert('XSS')</script> & \"quotes\" 'single'"
        body = "Special chars: €™®©¶§¢£¥ 日本語 emoji: 🎮🏆"

        # Act
        event_id = await repository.insert_event(
            user_id=user_id,
            event_type=fake.word(),
            title=title,
            body=body,
            metadata=None,
            conn=asyncpg_conn,
        )

        # Assert
        row = await asyncpg_conn.fetchrow(
            "SELECT title, body FROM notifications.events WHERE id = $1",
            event_id,
        )
        assert row["title"] == title
        assert row["body"] == body

    @pytest.mark.asyncio
    async def test_insert_event_with_very_long_strings_succeeds(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
    ) -> None:
        """Test inserting event with very long strings succeeds."""
        # Arrange
        user_id = await create_test_user()
        long_title = "A" * 500
        long_body = "B" * 5000
        long_event_type = "C" * 200

        # Act
        event_id = await repository.insert_event(
            user_id=user_id,
            event_type=long_event_type,
            title=long_title,
            body=long_body,
            metadata=None,
            conn=asyncpg_conn,
        )

        # Assert
        assert isinstance(event_id, int)

    @pytest.mark.asyncio
    async def test_insert_event_with_complex_metadata_succeeds(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
    ) -> None:
        """Test inserting event with complex nested metadata succeeds."""
        # Arrange
        user_id = await create_test_user()
        metadata = {
            "level1": {
                "level2": {
                    "level3": {
                        "array": [1, 2, 3],
                        "bool": True,
                        "null": None,
                        "string": "test",
                    }
                }
            },
            "special_chars": "🎮 日本語",
        }

        # Act
        event_id = await repository.insert_event(
            user_id=user_id,
            event_type=fake.word(),
            title=fake.sentence(),
            body=fake.sentence(),
            metadata=metadata,
            conn=asyncpg_conn,
        )

        # Assert
        row = await asyncpg_conn.fetchrow(
            "SELECT metadata FROM notifications.events WHERE id = $1",
            event_id,
        )
        import json
        assert json.loads(row["metadata"]) == metadata


class TestInsertEventErrorCases:
    """Test error handling for insert_event."""

    @pytest.mark.asyncio
    async def test_insert_event_invalid_user_id_raises_foreign_key_error(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
    ) -> None:
        """Test inserting event with non-existent user_id raises ForeignKeyViolationError."""
        # Arrange
        fake_user_id = 999999999999999999

        # Act & Assert
        with pytest.raises(ForeignKeyViolationError) as exc_info:
            await repository.insert_event(
                user_id=fake_user_id,
                event_type=fake.word(),
                title=fake.sentence(),
                body=fake.sentence(),
                metadata=None,
                conn=asyncpg_conn,
            )

        assert "user_id" in exc_info.value.constraint_name or "events_user_id_fkey" in exc_info.value.constraint_name


class TestInsertEventTransactions:
    """Test transaction behavior for insert_event."""

    @pytest.mark.asyncio
    async def test_insert_event_transaction_commit_persists_data(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
    ) -> None:
        """Test inserting event in committed transaction persists data."""
        # Arrange
        user_id = await create_test_user()

        # Act
        async with asyncpg_conn.transaction():
            event_id = await repository.insert_event(
                user_id=user_id,
                event_type=fake.word(),
                title=fake.sentence(),
                body=fake.sentence(),
                metadata=None,
                conn=asyncpg_conn,
            )

        # Assert - data should persist after commit
        row = await asyncpg_conn.fetchrow(
            "SELECT * FROM notifications.events WHERE id = $1",
            event_id,
        )
        assert row is not None

    @pytest.mark.asyncio
    async def test_insert_event_transaction_rollback_discards_data(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
    ) -> None:
        """Test inserting event in rolled back transaction discards data."""
        # Arrange
        user_id = await create_test_user()
        event_id = None

        # Act
        try:
            async with asyncpg_conn.transaction():
                event_id = await repository.insert_event(
                    user_id=user_id,
                    event_type=fake.word(),
                    title=fake.sentence(),
                    body=fake.sentence(),
                    metadata=None,
                    conn=asyncpg_conn,
                )
                # Force rollback
                raise Exception("Force rollback")
        except Exception:
            pass

        # Assert - data should not persist after rollback
        row = await asyncpg_conn.fetchrow(
            "SELECT * FROM notifications.events WHERE id = $1",
            event_id,
        )
        assert row is None


# ==============================================================================
# record_delivery_result TESTS
# ==============================================================================


class TestRecordDeliveryResultHappyPath:
    """Test happy path scenarios for record_delivery_result."""

    @pytest.mark.asyncio
    async def test_record_delivery_result_delivered_sets_delivered_at(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_notification_event,
    ) -> None:
        """Test recording delivered status sets delivered_at timestamp."""
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
            "SELECT * FROM notifications.delivery_log WHERE event_id = $1 AND channel = $2",
            event_id,
            "discord",
        )
        assert row is not None
        assert row["status"] == "delivered"
        assert row["delivered_at"] is not None
        assert row["attempted_at"] is not None
        assert row["error_message"] is None

    @pytest.mark.asyncio
    async def test_record_delivery_result_failed_stores_error_message(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_notification_event,
    ) -> None:
        """Test recording failed status stores error message."""
        # Arrange
        event_id = await create_test_notification_event()
        error_msg = "Connection timeout"

        # Act
        await repository.record_delivery_result(
            event_id=event_id,
            channel="email",
            status="failed",
            error_message=error_msg,
            conn=asyncpg_conn,
        )

        # Assert
        row = await asyncpg_conn.fetchrow(
            "SELECT * FROM notifications.delivery_log WHERE event_id = $1 AND channel = $2",
            event_id,
            "email",
        )
        assert row is not None
        assert row["status"] == "failed"
        assert row["delivered_at"] is None
        assert row["error_message"] == error_msg

    @pytest.mark.asyncio
    async def test_record_delivery_result_skipped_no_delivered_at(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_notification_event,
    ) -> None:
        """Test recording skipped status does not set delivered_at."""
        # Arrange
        event_id = await create_test_notification_event()

        # Act
        await repository.record_delivery_result(
            event_id=event_id,
            channel="push",
            status="skipped",
            error_message="User has no device",
            conn=asyncpg_conn,
        )

        # Assert
        row = await asyncpg_conn.fetchrow(
            "SELECT * FROM notifications.delivery_log WHERE event_id = $1 AND channel = $2",
            event_id,
            "push",
        )
        assert row is not None
        assert row["status"] == "skipped"
        assert row["delivered_at"] is None


class TestRecordDeliveryResultUpsert:
    """Test upsert behavior for record_delivery_result."""

    @pytest.mark.asyncio
    async def test_record_delivery_result_updates_existing_record(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_notification_event,
    ) -> None:
        """Test recording delivery result updates existing record on conflict."""
        # Arrange
        event_id = await create_test_notification_event()

        # First insert
        await repository.record_delivery_result(
            event_id=event_id,
            channel="discord",
            status="failed",
            error_message="First attempt failed",
            conn=asyncpg_conn,
        )

        # Act - second insert with same event_id and channel
        await repository.record_delivery_result(
            event_id=event_id,
            channel="discord",
            status="delivered",
            error_message=None,
            conn=asyncpg_conn,
        )

        # Assert - should have updated, not created new record
        count = await asyncpg_conn.fetchval(
            "SELECT COUNT(*) FROM notifications.delivery_log WHERE event_id = $1 AND channel = $2",
            event_id,
            "discord",
        )
        assert count == 1

        row = await asyncpg_conn.fetchrow(
            "SELECT * FROM notifications.delivery_log WHERE event_id = $1 AND channel = $2",
            event_id,
            "discord",
        )
        assert row["status"] == "delivered"
        assert row["delivered_at"] is not None
        assert row["error_message"] is None

    @pytest.mark.asyncio
    async def test_record_delivery_result_multiple_channels_separate_records(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_notification_event,
    ) -> None:
        """Test recording delivery results for multiple channels creates separate records."""
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
        await repository.record_delivery_result(
            event_id=event_id,
            channel="email",
            status="failed",
            error_message="SMTP error",
            conn=asyncpg_conn,
        )

        # Assert
        count = await asyncpg_conn.fetchval(
            "SELECT COUNT(*) FROM notifications.delivery_log WHERE event_id = $1",
            event_id,
        )
        assert count == 2


# ==============================================================================
# upsert_preference TESTS
# ==============================================================================


class TestUpsertPreferenceHappyPath:
    """Test happy path scenarios for upsert_preference."""

    @pytest.mark.asyncio
    async def test_upsert_preference_insert_new_preference(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
    ) -> None:
        """Test upserting new preference inserts record."""
        # Arrange
        user_id = await create_test_user()

        # Act
        await repository.upsert_preference(
            user_id=user_id,
            event_type="completion_submitted",
            channel="discord",
            enabled=True,
            conn=asyncpg_conn,
        )

        # Assert
        row = await asyncpg_conn.fetchrow(
            "SELECT * FROM notifications.preferences WHERE user_id = $1 AND event_type = $2 AND channel = $3",
            user_id,
            "completion_submitted",
            "discord",
        )
        assert row is not None
        assert row["enabled"] is True

    @pytest.mark.asyncio
    async def test_upsert_preference_update_existing_preference(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
    ) -> None:
        """Test upserting existing preference updates enabled flag."""
        # Arrange
        user_id = await create_test_user()
        event_type = "map_approved"
        channel = "email"

        # First insert
        await repository.upsert_preference(
            user_id=user_id,
            event_type=event_type,
            channel=channel,
            enabled=True,
            conn=asyncpg_conn,
        )

        # Act - update to disabled
        await repository.upsert_preference(
            user_id=user_id,
            event_type=event_type,
            channel=channel,
            enabled=False,
            conn=asyncpg_conn,
        )

        # Assert - should have updated, not created new record
        count = await asyncpg_conn.fetchval(
            "SELECT COUNT(*) FROM notifications.preferences WHERE user_id = $1 AND event_type = $2 AND channel = $3",
            user_id,
            event_type,
            channel,
        )
        assert count == 1

        row = await asyncpg_conn.fetchrow(
            "SELECT enabled FROM notifications.preferences WHERE user_id = $1 AND event_type = $2 AND channel = $3",
            user_id,
            event_type,
            channel,
        )
        assert row["enabled"] is False

    @pytest.mark.asyncio
    async def test_upsert_preference_enabled_false(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
        create_test_user,
    ) -> None:
        """Test upserting preference with enabled=False."""
        # Arrange
        user_id = await create_test_user()

        # Act
        await repository.upsert_preference(
            user_id=user_id,
            event_type="rank_beaten",
            channel="push",
            enabled=False,
            conn=asyncpg_conn,
        )

        # Assert
        row = await asyncpg_conn.fetchrow(
            "SELECT enabled FROM notifications.preferences WHERE user_id = $1",
            user_id,
        )
        assert row["enabled"] is False


class TestUpsertPreferenceErrorCases:
    """Test error handling for upsert_preference."""

    @pytest.mark.asyncio
    async def test_upsert_preference_invalid_user_id_raises_foreign_key_error(
        self,
        repository: NotificationsRepository,
        asyncpg_conn,
    ) -> None:
        """Test upserting preference with non-existent user_id raises ForeignKeyViolationError."""
        # Arrange
        fake_user_id = 999999999999999999

        # Act & Assert
        with pytest.raises(ForeignKeyViolationError) as exc_info:
            await repository.upsert_preference(
                user_id=fake_user_id,
                event_type=fake.word(),
                channel=fake.word(),
                enabled=True,
                conn=asyncpg_conn,
            )

        assert "user_id" in exc_info.value.constraint_name or "preferences_user_id_fkey" in exc_info.value.constraint_name
