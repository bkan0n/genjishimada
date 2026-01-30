"""Tests for NewsfeedRepository create operations."""

from uuid import uuid4

import pytest
from faker import Faker

from repository.newsfeed_repository import NewsfeedRepository

fake = Faker()

pytestmark = [
    pytest.mark.domain_newsfeed,
]


@pytest.fixture
async def repository(asyncpg_conn):
    """Provide newsfeed repository instance."""
    return NewsfeedRepository(asyncpg_conn)


# ==============================================================================
# HAPPY PATH TESTS
# ==============================================================================


class TestInsertEventHappyPath:
    """Test happy path scenarios for insert_event."""

    @pytest.mark.asyncio
    async def test_insert_event_with_simple_payload_returns_id(
        self,
        repository: NewsfeedRepository,
    ) -> None:
        """Test inserting event with simple payload returns event ID."""
        import datetime as dt

        # Arrange
        timestamp = dt.datetime.now(dt.timezone.utc)
        payload = {
            "type": "test_event",
            "message": "Test message",
        }

        # Act
        event_id = await repository.insert_event(timestamp, payload)

        # Assert
        assert isinstance(event_id, int)
        assert event_id > 0

    @pytest.mark.asyncio
    async def test_insert_event_with_complex_nested_payload(
        self,
        repository: NewsfeedRepository,
    ) -> None:
        """Test inserting event with complex nested payload structure."""
        import datetime as dt

        # Arrange
        timestamp = dt.datetime.now(dt.timezone.utc)
        payload = {
            "type": "complex_event",
            "user": {
                "id": fake.random_int(min=1000, max=9999),
                "name": fake.name(),
            },
            "data": {
                "items": [
                    {"id": 1, "value": fake.word()},
                    {"id": 2, "value": fake.word()},
                ],
                "metadata": {
                    "source": "test",
                    "version": "1.0",
                },
            },
        }

        # Act
        event_id = await repository.insert_event(timestamp, payload)

        # Assert
        assert isinstance(event_id, int)
        assert event_id > 0

    @pytest.mark.asyncio
    async def test_insert_event_stores_data_correctly(
        self,
        repository: NewsfeedRepository,
        asyncpg_conn,
    ) -> None:
        """Test that insert_event stores data correctly in database."""
        import datetime as dt
        import json

        # Arrange
        timestamp = dt.datetime(2024, 1, 15, 10, 30, 0, tzinfo=dt.timezone.utc)
        payload = {
            "type": "verification_event",
            "data": fake.sentence(),
        }

        # Act
        event_id = await repository.insert_event(timestamp, payload)

        # Assert - Verify data in database
        row = await asyncpg_conn.fetchrow(
            "SELECT id, timestamp, payload, event_type FROM public.newsfeed WHERE id = $1",
            event_id,
        )

        assert row is not None
        assert row["id"] == event_id
        # Timestamps should match (both are timezone-aware UTC)
        assert row["timestamp"].replace(microsecond=0) == timestamp.replace(microsecond=0)
        assert row["event_type"] == "verification_event"
        # Payload might be string or dict depending on asyncpg version
        payload_data = row["payload"] if isinstance(row["payload"], dict) else json.loads(row["payload"])
        assert isinstance(payload_data, dict)
        assert payload_data["type"] == "verification_event"
        assert payload_data["data"] == payload["data"]

    @pytest.mark.asyncio
    async def test_insert_multiple_events_sequentially(
        self,
        repository: NewsfeedRepository,
    ) -> None:
        """Test inserting multiple events sequentially returns unique IDs."""
        import datetime as dt

        # Arrange
        timestamp = dt.datetime.now(dt.timezone.utc)
        event_ids = []

        # Act - Insert 5 events
        for i in range(5):
            payload = {
                "type": f"event_{i}",
                "sequence": i,
            }
            event_id = await repository.insert_event(timestamp, payload)
            event_ids.append(event_id)

        # Assert
        assert len(event_ids) == 5
        assert len(set(event_ids)) == 5  # All IDs unique
        # IDs should be sequential (auto-increment)
        assert event_ids == sorted(event_ids)


# ==============================================================================
# EDGE CASE TESTS
# ==============================================================================


class TestInsertEventEdgeCases:
    """Test edge cases for insert_event."""

    @pytest.mark.asyncio
    async def test_insert_event_with_empty_payload(
        self,
        repository: NewsfeedRepository,
    ) -> None:
        """Test inserting event with empty payload succeeds."""
        import datetime as dt

        # Arrange
        timestamp = dt.datetime.now(dt.timezone.utc)
        payload = {}

        # Act
        event_id = await repository.insert_event(timestamp, payload)

        # Assert
        assert isinstance(event_id, int)
        assert event_id > 0

    @pytest.mark.asyncio
    async def test_insert_event_with_special_characters_in_payload(
        self,
        repository: NewsfeedRepository,
    ) -> None:
        """Test inserting event with special characters in payload."""
        import datetime as dt

        # Arrange
        timestamp = dt.datetime.now(dt.timezone.utc)
        payload = {
            "type": "special_chars",
            "message": "Test with special chars: <>&\"'@#$%^&*()",
            "unicode": "Unicode: 你好世界 🎉",
            "newlines": "Line 1\nLine 2\nLine 3",
        }

        # Act
        event_id = await repository.insert_event(timestamp, payload)

        # Assert
        assert isinstance(event_id, int)
        assert event_id > 0

    @pytest.mark.asyncio
    async def test_insert_event_with_null_values_in_payload(
        self,
        repository: NewsfeedRepository,
    ) -> None:
        """Test inserting event with null values in payload."""
        import datetime as dt

        # Arrange
        timestamp = dt.datetime.now(dt.timezone.utc)
        payload = {
            "type": "null_test",
            "nullable_field": None,
            "data": {
                "nested_null": None,
            },
        }

        # Act
        event_id = await repository.insert_event(timestamp, payload)

        # Assert
        assert isinstance(event_id, int)
        assert event_id > 0

    @pytest.mark.asyncio
    async def test_insert_event_with_large_payload(
        self,
        repository: NewsfeedRepository,
    ) -> None:
        """Test inserting event with large payload."""
        import datetime as dt

        # Arrange
        timestamp = dt.datetime.now(dt.timezone.utc)
        # Create a large payload with 100 items
        payload = {
            "type": "large_event",
            "items": [
                {
                    "id": i,
                    "data": fake.text(max_nb_chars=100),
                }
                for i in range(100)
            ],
        }

        # Act
        event_id = await repository.insert_event(timestamp, payload)

        # Assert
        assert isinstance(event_id, int)
        assert event_id > 0

    @pytest.mark.asyncio
    async def test_insert_event_preserves_payload_structure(
        self,
        repository: NewsfeedRepository,
        asyncpg_conn,
    ) -> None:
        """Test that complex payload structure is preserved after insert."""
        import datetime as dt
        import json

        # Arrange
        timestamp = dt.datetime.now(dt.timezone.utc)
        payload = {
            "type": "structure_test",
            "array": [1, 2, 3],
            "nested": {
                "level1": {
                    "level2": {
                        "value": "deep",
                    },
                },
            },
            "mixed": [
                {"id": 1, "name": "first"},
                {"id": 2, "name": "second"},
            ],
        }

        # Act
        event_id = await repository.insert_event(timestamp, payload)

        # Assert - Verify structure is preserved
        row = await asyncpg_conn.fetchrow(
            "SELECT payload FROM public.newsfeed WHERE id = $1",
            event_id,
        )

        # Parse payload if it's a string
        payload_data = row["payload"] if isinstance(row["payload"], dict) else json.loads(row["payload"])

        assert payload_data["array"] == [1, 2, 3]
        assert payload_data["nested"]["level1"]["level2"]["value"] == "deep"
        assert len(payload_data["mixed"]) == 2
        assert payload_data["mixed"][0]["name"] == "first"


# ==============================================================================
# TRANSACTION TESTS
# ==============================================================================


class TestInsertEventTransactions:
    """Test transaction behavior for insert_event."""

    @pytest.mark.asyncio
    async def test_insert_event_transaction_commit(
        self,
        repository: NewsfeedRepository,
        asyncpg_conn,
    ) -> None:
        """Test that committed transaction persists event."""
        import datetime as dt

        # Arrange
        timestamp = dt.datetime.now(dt.timezone.utc)
        payload = {
            "type": "commit_test",
            "data": fake.word(),
        }

        # Act - Insert within transaction and commit
        async with asyncpg_conn.transaction():
            event_id = await repository.insert_event(timestamp, payload, conn=asyncpg_conn)

        # Assert - Verify data persists after transaction
        row = await asyncpg_conn.fetchrow(
            "SELECT id FROM public.newsfeed WHERE id = $1",
            event_id,
        )

        assert row is not None
        assert row["id"] == event_id

    @pytest.mark.asyncio
    async def test_insert_event_transaction_rollback(
        self,
        repository: NewsfeedRepository,
        asyncpg_conn,
    ) -> None:
        """Test that rolled back transaction doesn't persist event."""
        import datetime as dt

        # Arrange
        timestamp = dt.datetime.now(dt.timezone.utc)
        payload = {
            "type": "rollback_test",
            "data": fake.word(),
        }

        # Act - Insert within transaction and rollback
        event_id = None
        try:
            async with asyncpg_conn.transaction():
                event_id = await repository.insert_event(timestamp, payload, conn=asyncpg_conn)
                # Force rollback
                raise Exception("Intentional rollback")
        except Exception:
            pass

        # Assert - Verify data doesn't exist after rollback
        row = await asyncpg_conn.fetchrow(
            "SELECT id FROM public.newsfeed WHERE id = $1",
            event_id,
        )

        assert row is None


# ==============================================================================
# CONCURRENCY TESTS
# ==============================================================================


class TestInsertEventConcurrency:
    """Test concurrent insert behavior."""

    @pytest.mark.asyncio
    async def test_concurrent_inserts_no_collisions(
        self,
        postgres_service,
    ) -> None:
        """Test concurrent inserts with auto-increment IDs don't collide."""
        import asyncio
        import datetime as dt
        import asyncpg

        # Create a pool for concurrent operations
        pool = await asyncpg.create_pool(
            user=postgres_service.user,
            password=postgres_service.password,
            host=postgres_service.host,
            port=postgres_service.port,
            database=postgres_service.database,
        )

        try:
            repository = NewsfeedRepository(pool)

            # Arrange
            timestamp = dt.datetime.now(dt.timezone.utc)
            num_events = 10

            async def insert_event(index: int) -> int:
                payload = {
                    "type": f"concurrent_{index}",
                    "index": index,
                }
                return await repository.insert_event(timestamp, payload)

            # Act - Insert multiple events concurrently
            tasks = [insert_event(i) for i in range(num_events)]
            event_ids = await asyncio.gather(*tasks)

            # Assert
            assert len(event_ids) == num_events
            assert len(set(event_ids)) == num_events  # All IDs unique
            assert all(isinstance(event_id, int) for event_id in event_ids)
            assert all(event_id > 0 for event_id in event_ids)
        finally:
            await pool.close()
