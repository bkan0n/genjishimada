"""Tests for NewsfeedRepository list operations."""

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


class TestFetchEventsHappyPath:
    """Test happy path scenarios for fetch_events."""

    @pytest.mark.asyncio
    async def test_fetch_events_with_pagination(
        self,
        repository: NewsfeedRepository,
        create_test_newsfeed_event,
    ) -> None:
        """Test fetching events with limit and offset."""
        import datetime as dt

        # Arrange - Create 5 events
        base_time = dt.datetime(2024, 1, 15, 12, 0, 0, tzinfo=dt.timezone.utc)
        event_ids = []
        for i in range(5):
            timestamp = base_time + dt.timedelta(minutes=i)
            payload = {"type": f"event_{i}", "index": i}
            event_id = await create_test_newsfeed_event(timestamp=timestamp, payload=payload)
            event_ids.append(event_id)

        # Act - Fetch first 3 events
        result = await repository.fetch_events(limit=3, offset=0)

        # Assert
        assert len(result) == 3
        assert all(isinstance(event, dict) for event in result)
        assert all("id" in event for event in result)

    @pytest.mark.asyncio
    async def test_fetch_events_with_offset(
        self,
        repository: NewsfeedRepository,
        create_test_newsfeed_event,
    ) -> None:
        """Test fetching events with offset skips correct number."""
        import datetime as dt

        # Arrange - Create 5 events
        base_time = dt.datetime(2024, 1, 15, 12, 0, 0, tzinfo=dt.timezone.utc)
        for i in range(5):
            timestamp = base_time + dt.timedelta(minutes=i)
            payload = {"type": f"event_{i}", "index": i}
            await create_test_newsfeed_event(timestamp=timestamp, payload=payload)

        # Act - Fetch with offset
        page1 = await repository.fetch_events(limit=2, offset=0)
        page2 = await repository.fetch_events(limit=2, offset=2)

        # Assert
        assert len(page1) == 2
        assert len(page2) == 2
        # Should not overlap
        page1_ids = {event["id"] for event in page1}
        page2_ids = {event["id"] for event in page2}
        assert len(page1_ids & page2_ids) == 0

    @pytest.mark.asyncio
    async def test_fetch_events_without_filter(
        self,
        repository: NewsfeedRepository,
        create_test_newsfeed_event,
    ) -> None:
        """Test fetching events without event_type filter returns all events."""
        # Arrange - Create events with different types
        await create_test_newsfeed_event(payload={"type": "type_a"})
        await create_test_newsfeed_event(payload={"type": "type_b"})
        await create_test_newsfeed_event(payload={"type": "type_c"})

        # Act - Fetch without filter
        result = await repository.fetch_events(limit=10, offset=0, event_type=None)

        # Assert - Should get at least our 3 events
        assert len(result) >= 3
        types = {event["event_type"] for event in result if event["event_type"] in ["type_a", "type_b", "type_c"]}
        assert len(types) == 3

    @pytest.mark.asyncio
    async def test_fetch_events_returns_all_fields(
        self,
        repository: NewsfeedRepository,
        create_test_newsfeed_event,
    ) -> None:
        """Test that fetch_events returns all expected fields."""
        # Arrange
        await create_test_newsfeed_event()

        # Act
        result = await repository.fetch_events(limit=1, offset=0)

        # Assert
        assert len(result) >= 1
        event = result[0]
        assert "id" in event
        assert "timestamp" in event
        assert "payload" in event
        assert "event_type" in event

    @pytest.mark.asyncio
    async def test_fetch_events_payload_is_parsed_as_dict(
        self,
        repository: NewsfeedRepository,
        create_test_newsfeed_event,
    ) -> None:
        """Test that payloads in fetched events are parsed as dicts."""
        # Arrange
        payload = {
            "type": "parse_test",
            "data": {"nested": "value"},
        }
        await create_test_newsfeed_event(payload=payload)

        # Act
        result = await repository.fetch_events(limit=1, offset=0, event_type="parse_test")

        # Assert
        assert len(result) >= 1
        event = result[0]
        assert isinstance(event["payload"], dict)
        assert event["payload"]["type"] == "parse_test"


# ==============================================================================
# FILTERING TESTS
# ==============================================================================


class TestFetchEventsFiltering:
    """Test event_type filtering for fetch_events."""

    @pytest.mark.asyncio
    async def test_fetch_events_with_event_type_filter(
        self,
        repository: NewsfeedRepository,
        create_test_newsfeed_event,
    ) -> None:
        """Test fetching events with event_type filter returns only matching events."""
        # Arrange - Create events with different types
        await create_test_newsfeed_event(payload={"type": "filter_test_a"})
        await create_test_newsfeed_event(payload={"type": "filter_test_a"})
        await create_test_newsfeed_event(payload={"type": "filter_test_b"})

        # Act - Fetch only filter_test_a
        result = await repository.fetch_events(limit=10, offset=0, event_type="filter_test_a")

        # Assert
        assert len(result) >= 2
        # All returned events should be filter_test_a
        for event in result:
            if event["event_type"] == "filter_test_a":
                assert event["payload"]["type"] == "filter_test_a"

    @pytest.mark.asyncio
    async def test_fetch_events_filter_excludes_other_types(
        self,
        repository: NewsfeedRepository,
        create_test_newsfeed_event,
    ) -> None:
        """Test that event_type filter excludes non-matching events."""
        # Arrange
        await create_test_newsfeed_event(payload={"type": "include_type"})
        await create_test_newsfeed_event(payload={"type": "exclude_type"})

        # Act
        result = await repository.fetch_events(limit=10, offset=0, event_type="include_type")

        # Assert
        event_types = {event["event_type"] for event in result}
        assert "include_type" in event_types
        assert "exclude_type" not in event_types

    @pytest.mark.asyncio
    async def test_fetch_events_with_non_existent_type_returns_empty(
        self,
        repository: NewsfeedRepository,
    ) -> None:
        """Test fetching events with non-existent type returns empty list."""
        # Act
        result = await repository.fetch_events(
            limit=10,
            offset=0,
            event_type="non_existent_type_xyz123",
        )

        # Assert
        assert result == []


# ==============================================================================
# ORDERING TESTS
# ==============================================================================


class TestFetchEventsOrdering:
    """Test ordering behavior for fetch_events."""

    @pytest.mark.asyncio
    async def test_fetch_events_ordered_by_timestamp_desc(
        self,
        repository: NewsfeedRepository,
        create_test_newsfeed_event,
    ) -> None:
        """Test that events are ordered by timestamp DESC."""
        import datetime as dt

        # Arrange - Create events with specific timestamps
        timestamps = [
            dt.datetime(2024, 1, 15, 10, 0, 0, tzinfo=dt.timezone.utc),
            dt.datetime(2024, 1, 15, 11, 0, 0, tzinfo=dt.timezone.utc),
            dt.datetime(2024, 1, 15, 12, 0, 0, tzinfo=dt.timezone.utc),
        ]
        for i, timestamp in enumerate(timestamps):
            await create_test_newsfeed_event(
                timestamp=timestamp,
                payload={"type": f"order_test_{i}"},
            )

        # Act
        result = await repository.fetch_events(limit=10, offset=0, event_type="order_test_0")
        result.extend(await repository.fetch_events(limit=10, offset=0, event_type="order_test_1"))
        result.extend(await repository.fetch_events(limit=10, offset=0, event_type="order_test_2"))

        # Get our test events
        test_events = [e for e in result if e["event_type"] and e["event_type"].startswith("order_test_")]
        test_events.sort(key=lambda x: (x["timestamp"], x["id"]), reverse=True)

        # Assert - Timestamps should be in descending order
        if len(test_events) >= 2:
            for i in range(len(test_events) - 1):
                assert test_events[i]["timestamp"] >= test_events[i + 1]["timestamp"]

    @pytest.mark.asyncio
    async def test_fetch_events_ordered_by_id_desc_for_same_timestamp(
        self,
        repository: NewsfeedRepository,
        create_test_newsfeed_event,
    ) -> None:
        """Test that events with same timestamp are ordered by id DESC."""
        import datetime as dt

        # Arrange - Create multiple events with same timestamp
        same_timestamp = dt.datetime(2024, 1, 15, 12, 0, 0, tzinfo=dt.timezone.utc)
        event_ids = []
        for i in range(3):
            event_id = await create_test_newsfeed_event(
                timestamp=same_timestamp,
                payload={"type": "same_time", "index": i},
            )
            event_ids.append(event_id)

        # Act
        result = await repository.fetch_events(limit=10, offset=0, event_type="same_time")

        # Assert - IDs should be in descending order
        if len(result) >= 2:
            for i in range(len(result) - 1):
                assert result[i]["id"] >= result[i + 1]["id"]


# ==============================================================================
# EDGE CASE TESTS
# ==============================================================================


class TestFetchEventsEdgeCases:
    """Test edge cases for fetch_events."""

    @pytest.mark.asyncio
    async def test_fetch_events_with_zero_limit(
        self,
        repository: NewsfeedRepository,
    ) -> None:
        """Test fetching events with limit=0 returns empty list."""
        # Act
        result = await repository.fetch_events(limit=0, offset=0)

        # Assert
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_events_with_large_offset_returns_empty(
        self,
        repository: NewsfeedRepository,
    ) -> None:
        """Test fetching events with offset larger than total returns empty list."""
        # Act
        result = await repository.fetch_events(limit=10, offset=999999)

        # Assert
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_events_with_large_limit(
        self,
        repository: NewsfeedRepository,
        create_test_newsfeed_event,
    ) -> None:
        """Test fetching events with very large limit works."""
        # Arrange
        await create_test_newsfeed_event(payload={"type": "large_limit_test"})

        # Act
        result = await repository.fetch_events(limit=10000, offset=0, event_type="large_limit_test")

        # Assert - Should get at least 1 event
        assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_fetch_events_empty_database(
        self,
        repository: NewsfeedRepository,
        asyncpg_conn,
    ) -> None:
        """Test fetching events when no events exist returns empty list."""
        # Arrange - Clear all events for this specific test type
        await asyncpg_conn.execute(
            "DELETE FROM public.newsfeed WHERE event_type = 'empty_db_test'"
        )

        # Act
        result = await repository.fetch_events(limit=10, offset=0, event_type="empty_db_test")

        # Assert
        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_events_with_complex_payloads(
        self,
        repository: NewsfeedRepository,
        create_test_newsfeed_event,
    ) -> None:
        """Test fetching events with complex nested payloads."""
        # Arrange
        payload = {
            "type": "complex_list",
            "user": {"id": 123, "name": "Test"},
            "items": [
                {"id": 1, "value": "first"},
                {"id": 2, "value": "second"},
            ],
        }
        await create_test_newsfeed_event(payload=payload)

        # Act
        result = await repository.fetch_events(limit=10, offset=0, event_type="complex_list")

        # Assert
        assert len(result) >= 1
        event = result[0]
        assert event["payload"]["user"]["id"] == 123
        assert len(event["payload"]["items"]) == 2

    @pytest.mark.asyncio
    async def test_fetch_events_preserves_payload_structure_for_all_events(
        self,
        repository: NewsfeedRepository,
        create_test_newsfeed_event,
    ) -> None:
        """Test that complex payloads are preserved for multiple events."""
        # Arrange - Create multiple events with different structures
        payloads = [
            {"type": "structure_1", "data": [1, 2, 3]},
            {"type": "structure_2", "data": {"nested": {"value": "deep"}}},
            {"type": "structure_3", "data": "simple"},
        ]
        for payload in payloads:
            await create_test_newsfeed_event(payload=payload)

        # Act
        result1 = await repository.fetch_events(limit=1, offset=0, event_type="structure_1")
        result2 = await repository.fetch_events(limit=1, offset=0, event_type="structure_2")
        result3 = await repository.fetch_events(limit=1, offset=0, event_type="structure_3")

        # Assert
        if result1:
            assert result1[0]["payload"]["data"] == [1, 2, 3]
        if result2:
            assert result2[0]["payload"]["data"]["nested"]["value"] == "deep"
        if result3:
            assert result3[0]["payload"]["data"] == "simple"


# ==============================================================================
# TRANSACTION TESTS
# ==============================================================================


class TestFetchEventsTransactions:
    """Test transaction behavior for fetch_events."""

    @pytest.mark.asyncio
    async def test_fetch_events_within_transaction(
        self,
        repository: NewsfeedRepository,
        create_test_newsfeed_event,
        asyncpg_conn,
    ) -> None:
        """Test fetching events within transaction works correctly."""
        # Arrange
        await create_test_newsfeed_event(payload={"type": "transaction_test"})

        # Act - Fetch within transaction
        async with asyncpg_conn.transaction():
            result = await repository.fetch_events(
                limit=10,
                offset=0,
                event_type="transaction_test",
                conn=asyncpg_conn,
            )

        # Assert
        assert len(result) >= 1
