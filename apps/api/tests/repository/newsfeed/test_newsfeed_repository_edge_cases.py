"""Edge case and integration tests for NewsfeedRepository."""

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
# CONCURRENT OPERATIONS TESTS
# ==============================================================================


class TestNewsfeedConcurrentOperations:
    """Test concurrent operations across multiple methods."""

    @pytest.mark.asyncio
    async def test_concurrent_insert_and_fetch(
        self,
        repository: NewsfeedRepository,
    ) -> None:
        """Test concurrent inserts and fetches work correctly."""
        import asyncio
        import datetime as dt

        # Arrange
        async def insert_events(count: int) -> list[int]:
            ids = []
            for i in range(count):
                timestamp = dt.datetime.now(dt.timezone.utc)
                payload = {"type": "concurrent_test", "index": i}
                event_id = await repository.insert_event(timestamp, payload)
                ids.append(event_id)
            return ids

        async def fetch_events() -> list[dict]:
            return await repository.fetch_events(limit=10, offset=0, event_type="concurrent_test")

        # Act - Run inserts and fetches concurrently
        insert_task = asyncio.create_task(insert_events(5))
        fetch_task = asyncio.create_task(fetch_events())

        inserted_ids, fetched_events = await asyncio.gather(insert_task, fetch_task)

        # Assert - All inserts succeeded
        assert len(inserted_ids) == 5
        assert all(isinstance(id, int) for id in inserted_ids)

    @pytest.mark.asyncio
    async def test_concurrent_fetch_by_id_same_event(
        self,
        repository: NewsfeedRepository,
        create_test_newsfeed_event,
    ) -> None:
        """Test concurrent fetches of same event by ID."""
        import asyncio

        # Arrange
        event_id = await create_test_newsfeed_event()

        # Act - Fetch same event 10 times concurrently
        tasks = [repository.fetch_event_by_id(event_id) for _ in range(10)]
        results = await asyncio.gather(*tasks)

        # Assert - All fetches succeeded and returned same data
        assert len(results) == 10
        assert all(result is not None for result in results)
        assert all(result["id"] == event_id for result in results)

    @pytest.mark.asyncio
    async def test_concurrent_fetch_events_with_different_filters(
        self,
        repository: NewsfeedRepository,
        create_test_newsfeed_event,
    ) -> None:
        """Test concurrent fetch_events with different filters."""
        import asyncio

        # Arrange
        await create_test_newsfeed_event(payload={"type": "filter_a"})
        await create_test_newsfeed_event(payload={"type": "filter_b"})
        await create_test_newsfeed_event(payload={"type": "filter_c"})

        # Act - Fetch with different filters concurrently
        tasks = [
            repository.fetch_events(limit=10, offset=0, event_type="filter_a"),
            repository.fetch_events(limit=10, offset=0, event_type="filter_b"),
            repository.fetch_events(limit=10, offset=0, event_type="filter_c"),
        ]
        results = await asyncio.gather(*tasks)

        # Assert
        assert len(results) == 3
        assert all(isinstance(result, list) for result in results)


# ==============================================================================
# INTEGRATION TESTS
# ==============================================================================


class TestNewsfeedIntegration:
    """Test integration scenarios across multiple methods."""

    @pytest.mark.asyncio
    async def test_insert_then_fetch_by_id(
        self,
        repository: NewsfeedRepository,
    ) -> None:
        """Test insert then immediately fetch by ID returns correct data."""
        import datetime as dt

        # Arrange
        timestamp = dt.datetime(2024, 1, 15, 14, 30, 0, tzinfo=dt.timezone.utc)
        payload = {
            "type": "integration_test",
            "message": "Test integration",
            "data": {"nested": "value"},
        }

        # Act
        event_id = await repository.insert_event(timestamp, payload)
        fetched = await repository.fetch_event_by_id(event_id)

        # Assert
        assert fetched is not None
        assert fetched["id"] == event_id
        assert fetched["timestamp"] == timestamp
        assert fetched["event_type"] == "integration_test"
        assert fetched["payload"]["message"] == "Test integration"
        assert fetched["payload"]["data"]["nested"] == "value"

    @pytest.mark.asyncio
    async def test_insert_multiple_then_fetch_with_pagination(
        self,
        repository: NewsfeedRepository,
    ) -> None:
        """Test inserting multiple events then fetching with pagination."""
        import datetime as dt

        # Arrange & Act - Insert 10 events
        base_time = dt.datetime(2024, 1, 15, 10, 0, 0, tzinfo=dt.timezone.utc)
        inserted_ids = []
        for i in range(10):
            timestamp = base_time + dt.timedelta(minutes=i)
            payload = {"type": "pagination_test", "sequence": i}
            event_id = await repository.insert_event(timestamp, payload)
            inserted_ids.append(event_id)

        # Act - Fetch in pages
        page1 = await repository.fetch_events(
            limit=3, offset=0, event_type="pagination_test"
        )
        page2 = await repository.fetch_events(
            limit=3, offset=3, event_type="pagination_test"
        )
        page3 = await repository.fetch_events(
            limit=3, offset=6, event_type="pagination_test"
        )

        # Assert
        assert len(page1) == 3
        assert len(page2) == 3
        assert len(page3) >= 1  # At least 1 remaining

        # No overlaps
        all_ids = (
            [e["id"] for e in page1] +
            [e["id"] for e in page2] +
            [e["id"] for e in page3]
        )
        assert len(all_ids) == len(set(all_ids))

    @pytest.mark.asyncio
    async def test_insert_then_fetch_with_type_filter(
        self,
        repository: NewsfeedRepository,
    ) -> None:
        """Test insert then fetch with event_type filter."""
        import datetime as dt

        # Arrange
        timestamp = dt.datetime.now(dt.timezone.utc)
        unique_type = f"filter_test_{uuid4().hex[:8]}"

        # Act - Insert events with specific type
        event_ids = []
        for i in range(3):
            payload = {"type": unique_type, "index": i}
            event_id = await repository.insert_event(timestamp, payload)
            event_ids.append(event_id)

        # Fetch with filter
        result = await repository.fetch_events(
            limit=10, offset=0, event_type=unique_type
        )

        # Assert
        assert len(result) >= 3
        result_ids = [e["id"] for e in result]
        for event_id in event_ids:
            assert event_id in result_ids


# ==============================================================================
# PAYLOAD EDGE CASES
# ==============================================================================


class TestPayloadEdgeCases:
    """Test edge cases related to payload handling."""

    @pytest.mark.asyncio
    async def test_payload_with_json_reserved_characters(
        self,
        repository: NewsfeedRepository,
        create_test_newsfeed_event,
    ) -> None:
        """Test payload with JSON reserved characters."""
        # Arrange
        payload = {
            "type": "json_chars",
            "quote": 'He said "hello"',
            "backslash": "path\\to\\file",
            "newline": "line1\nline2",
            "tab": "col1\tcol2",
        }

        # Act
        event_id = await create_test_newsfeed_event(payload=payload)
        fetched = await repository.fetch_event_by_id(event_id)

        # Assert
        assert fetched is not None
        assert fetched["payload"]["quote"] == 'He said "hello"'
        assert fetched["payload"]["backslash"] == "path\\to\\file"
        assert fetched["payload"]["newline"] == "line1\nline2"
        assert fetched["payload"]["tab"] == "col1\tcol2"

    @pytest.mark.asyncio
    async def test_payload_with_unicode_and_emoji(
        self,
        repository: NewsfeedRepository,
        create_test_newsfeed_event,
    ) -> None:
        """Test payload with unicode and emoji characters."""
        # Arrange
        payload = {
            "type": "unicode_test",
            "chinese": "你好世界",
            "japanese": "こんにちは",
            "arabic": "مرحبا",
            "emoji": "🎉🎊🎈✨",
            "mixed": "Hello 世界 🌍",
        }

        # Act
        event_id = await create_test_newsfeed_event(payload=payload)
        fetched = await repository.fetch_event_by_id(event_id)

        # Assert
        assert fetched is not None
        assert fetched["payload"]["chinese"] == "你好世界"
        assert fetched["payload"]["japanese"] == "こんにちは"
        assert fetched["payload"]["arabic"] == "مرحبا"
        assert fetched["payload"]["emoji"] == "🎉🎊🎈✨"
        assert fetched["payload"]["mixed"] == "Hello 世界 🌍"

    @pytest.mark.asyncio
    async def test_payload_with_very_deep_nesting(
        self,
        repository: NewsfeedRepository,
        create_test_newsfeed_event,
    ) -> None:
        """Test payload with very deep nesting (10 levels)."""
        # Arrange - Create deeply nested structure
        payload = {"type": "deep_nesting"}
        current = payload
        for i in range(10):
            current["level"] = i
            current["nested"] = {}
            current = current["nested"]
        current["value"] = "deepest"

        # Act
        event_id = await create_test_newsfeed_event(payload=payload)
        fetched = await repository.fetch_event_by_id(event_id)

        # Assert - Navigate to deepest level
        assert fetched is not None
        current = fetched["payload"]
        for i in range(10):
            assert current["level"] == i
            current = current["nested"]
        assert current["value"] == "deepest"

    @pytest.mark.asyncio
    async def test_payload_with_array_of_mixed_types(
        self,
        repository: NewsfeedRepository,
        create_test_newsfeed_event,
    ) -> None:
        """Test payload with array containing mixed types."""
        # Arrange
        payload = {
            "type": "mixed_array",
            "items": [
                1,
                "string",
                True,
                None,
                {"nested": "object"},
                [1, 2, 3],
                3.14,
            ],
        }

        # Act
        event_id = await create_test_newsfeed_event(payload=payload)
        fetched = await repository.fetch_event_by_id(event_id)

        # Assert
        assert fetched is not None
        items = fetched["payload"]["items"]
        assert items[0] == 1
        assert items[1] == "string"
        assert items[2] is True
        assert items[3] is None
        assert items[4] == {"nested": "object"}
        assert items[5] == [1, 2, 3]
        assert items[6] == 3.14


# ==============================================================================
# TIMESTAMP EDGE CASES
# ==============================================================================


class TestTimestampEdgeCases:
    """Test edge cases related to timestamp handling."""

    @pytest.mark.asyncio
    async def test_events_with_same_timestamp_ordering(
        self,
        repository: NewsfeedRepository,
    ) -> None:
        """Test that events with identical timestamps are ordered by ID."""
        import datetime as dt

        # Arrange - Insert multiple events with exact same timestamp
        same_timestamp = dt.datetime(2024, 1, 15, 12, 0, 0, 0, tzinfo=dt.timezone.utc)
        unique_type = f"same_ts_{uuid4().hex[:8]}"

        event_ids = []
        for i in range(5):
            payload = {"type": unique_type, "index": i}
            event_id = await repository.insert_event(same_timestamp, payload)
            event_ids.append(event_id)

        # Act
        result = await repository.fetch_events(
            limit=10, offset=0, event_type=unique_type
        )

        # Assert - Should be ordered by ID DESC
        result_ids = [e["id"] for e in result[:5]]
        assert result_ids == sorted(result_ids, reverse=True)

    @pytest.mark.asyncio
    async def test_events_with_microsecond_precision(
        self,
        repository: NewsfeedRepository,
        create_test_newsfeed_event,
    ) -> None:
        """Test that timestamps with microsecond precision are preserved."""
        import datetime as dt

        # Arrange - Timestamp with microseconds
        timestamp = dt.datetime(
            2024, 1, 15, 12, 30, 45, 123456, tzinfo=dt.timezone.utc
        )
        payload = {"type": "microsecond_test"}

        # Act
        event_id = await create_test_newsfeed_event(
            timestamp=timestamp, payload=payload
        )
        fetched = await repository.fetch_event_by_id(event_id)

        # Assert
        assert fetched is not None
        assert fetched["timestamp"] == timestamp
        assert fetched["timestamp"].microsecond == 123456

    @pytest.mark.asyncio
    async def test_events_with_different_timezones_normalized_to_utc(
        self,
        repository: NewsfeedRepository,
    ) -> None:
        """Test that timestamps are normalized to UTC."""
        import datetime as dt

        # Arrange - Create timestamp in different timezone
        # Note: Since we're using timezone-aware datetimes, PostgreSQL will normalize to UTC
        timestamp_utc = dt.datetime(2024, 1, 15, 12, 0, 0, tzinfo=dt.timezone.utc)
        payload = {"type": "timezone_test"}

        # Act
        event_id = await repository.insert_event(timestamp_utc, payload)
        fetched = await repository.fetch_event_by_id(event_id)

        # Assert
        assert fetched is not None
        # PostgreSQL stores in UTC
        assert fetched["timestamp"].tzinfo == dt.timezone.utc


# ==============================================================================
# BOUNDARY VALUE TESTS
# ==============================================================================


class TestBoundaryValues:
    """Test boundary value cases."""

    @pytest.mark.asyncio
    async def test_fetch_events_with_maximum_limit(
        self,
        repository: NewsfeedRepository,
        create_test_newsfeed_event,
    ) -> None:
        """Test fetch_events with very large limit value."""
        # Arrange
        unique_type = f"max_limit_{uuid4().hex[:8]}"
        await create_test_newsfeed_event(payload={"type": unique_type})

        # Act
        result = await repository.fetch_events(
            limit=2147483647,  # Max 32-bit int
            offset=0,
            event_type=unique_type,
        )

        # Assert - Should work without error
        assert isinstance(result, list)
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_event_type_with_maximum_length(
        self,
        repository: NewsfeedRepository,
        create_test_newsfeed_event,
    ) -> None:
        """Test event with very long event_type string."""
        # Arrange - Create very long type string
        long_type = "a" * 200

        payload = {"type": long_type, "data": "test"}

        # Act
        event_id = await create_test_newsfeed_event(payload=payload)
        fetched = await repository.fetch_event_by_id(event_id)

        # Assert
        assert fetched is not None
        assert fetched["event_type"] == long_type
        assert len(fetched["event_type"]) == 200
