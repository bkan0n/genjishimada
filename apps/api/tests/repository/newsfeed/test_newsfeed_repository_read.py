"""Tests for NewsfeedRepository read operations."""

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


class TestFetchEventByIdHappyPath:
    """Test happy path scenarios for fetch_event_by_id."""

    @pytest.mark.asyncio
    async def test_fetch_event_by_id_returns_correct_event(
        self,
        repository: NewsfeedRepository,
        create_test_newsfeed_event,
    ) -> None:
        """Test fetching event by ID returns correct event data."""
        import datetime as dt

        # Arrange
        timestamp = dt.datetime(2024, 1, 15, 12, 0, 0, tzinfo=dt.timezone.utc)
        payload = {
            "type": "test_event",
            "message": "Test message",
        }
        event_id = await create_test_newsfeed_event(timestamp=timestamp, payload=payload)

        # Act
        result = await repository.fetch_event_by_id(event_id)

        # Assert
        assert result is not None
        assert result["id"] == event_id
        assert result["timestamp"] == timestamp
        assert result["event_type"] == "test_event"
        assert result["payload"]["type"] == "test_event"
        assert result["payload"]["message"] == "Test message"

    @pytest.mark.asyncio
    async def test_fetch_event_returns_all_fields(
        self,
        repository: NewsfeedRepository,
        create_test_newsfeed_event,
    ) -> None:
        """Test that fetch_event_by_id returns all expected fields."""
        # Arrange
        event_id = await create_test_newsfeed_event()

        # Act
        result = await repository.fetch_event_by_id(event_id)

        # Assert
        assert result is not None
        assert "id" in result
        assert "timestamp" in result
        assert "payload" in result
        assert "event_type" in result

    @pytest.mark.asyncio
    async def test_fetch_event_payload_is_dict(
        self,
        repository: NewsfeedRepository,
        create_test_newsfeed_event,
    ) -> None:
        """Test that fetched event payload is parsed as dict."""
        # Arrange
        payload = {
            "type": "dict_test",
            "data": {
                "nested": "value",
            },
        }
        event_id = await create_test_newsfeed_event(payload=payload)

        # Act
        result = await repository.fetch_event_by_id(event_id)

        # Assert
        assert result is not None
        assert isinstance(result["payload"], dict)
        assert result["payload"]["type"] == "dict_test"
        assert result["payload"]["data"]["nested"] == "value"

    @pytest.mark.asyncio
    async def test_fetch_event_with_complex_payload_structure(
        self,
        repository: NewsfeedRepository,
        create_test_newsfeed_event,
    ) -> None:
        """Test fetching event with complex nested payload structure."""
        # Arrange
        payload = {
            "type": "complex",
            "user": {
                "id": 12345,
                "name": "Test User",
            },
            "items": [
                {"id": 1, "value": "first"},
                {"id": 2, "value": "second"},
            ],
            "metadata": {
                "source": "api",
                "version": "2.0",
            },
        }
        event_id = await create_test_newsfeed_event(payload=payload)

        # Act
        result = await repository.fetch_event_by_id(event_id)

        # Assert
        assert result is not None
        assert result["payload"]["user"]["id"] == 12345
        assert result["payload"]["user"]["name"] == "Test User"
        assert len(result["payload"]["items"]) == 2
        assert result["payload"]["items"][0]["value"] == "first"
        assert result["payload"]["metadata"]["version"] == "2.0"


# ==============================================================================
# NOT FOUND TESTS
# ==============================================================================


class TestFetchEventByIdNotFound:
    """Test fetch_event_by_id when event doesn't exist."""

    @pytest.mark.asyncio
    async def test_fetch_non_existent_event_returns_none(
        self,
        repository: NewsfeedRepository,
    ) -> None:
        """Test fetching non-existent event returns None."""
        # Arrange - Use a very large ID that shouldn't exist
        non_existent_id = 999999999

        # Act
        result = await repository.fetch_event_by_id(non_existent_id)

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_negative_id_returns_none(
        self,
        repository: NewsfeedRepository,
    ) -> None:
        """Test fetching with negative ID returns None."""
        # Act
        result = await repository.fetch_event_by_id(-1)

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_fetch_zero_id_returns_none(
        self,
        repository: NewsfeedRepository,
    ) -> None:
        """Test fetching with zero ID returns None."""
        # Act
        result = await repository.fetch_event_by_id(0)

        # Assert
        assert result is None


# ==============================================================================
# EDGE CASE TESTS
# ==============================================================================


class TestFetchEventByIdEdgeCases:
    """Test edge cases for fetch_event_by_id."""

    @pytest.mark.asyncio
    async def test_fetch_event_with_empty_payload(
        self,
        repository: NewsfeedRepository,
        create_test_newsfeed_event,
    ) -> None:
        """Test fetching event with empty payload."""
        # Arrange
        payload = {}
        event_id = await create_test_newsfeed_event(payload=payload)

        # Act
        result = await repository.fetch_event_by_id(event_id)

        # Assert
        assert result is not None
        assert result["payload"] == {}
        assert result["event_type"] is None  # No 'type' field in payload

    @pytest.mark.asyncio
    async def test_fetch_event_with_null_values_in_payload(
        self,
        repository: NewsfeedRepository,
        create_test_newsfeed_event,
    ) -> None:
        """Test fetching event with null values in payload."""
        # Arrange
        payload = {
            "type": "null_test",
            "nullable_field": None,
            "data": {
                "nested_null": None,
            },
        }
        event_id = await create_test_newsfeed_event(payload=payload)

        # Act
        result = await repository.fetch_event_by_id(event_id)

        # Assert
        assert result is not None
        assert result["payload"]["nullable_field"] is None
        assert result["payload"]["data"]["nested_null"] is None

    @pytest.mark.asyncio
    async def test_fetch_event_with_special_characters(
        self,
        repository: NewsfeedRepository,
        create_test_newsfeed_event,
    ) -> None:
        """Test fetching event with special characters in payload."""
        # Arrange
        payload = {
            "type": "special_chars",
            "message": "Special: <>&\"'@#$%",
            "unicode": "你好世界 🎉",
        }
        event_id = await create_test_newsfeed_event(payload=payload)

        # Act
        result = await repository.fetch_event_by_id(event_id)

        # Assert
        assert result is not None
        assert result["payload"]["message"] == "Special: <>&\"'@#$%"
        assert result["payload"]["unicode"] == "你好世界 🎉"

    @pytest.mark.asyncio
    async def test_fetch_event_type_computed_correctly(
        self,
        repository: NewsfeedRepository,
        create_test_newsfeed_event,
    ) -> None:
        """Test that event_type is computed from payload type field."""
        # Arrange
        payload = {
            "type": "computed_type_test",
            "data": "value",
        }
        event_id = await create_test_newsfeed_event(payload=payload)

        # Act
        result = await repository.fetch_event_by_id(event_id)

        # Assert
        assert result is not None
        assert result["event_type"] == "computed_type_test"
        assert result["payload"]["type"] == "computed_type_test"

    @pytest.mark.asyncio
    async def test_fetch_event_without_type_field_has_null_event_type(
        self,
        repository: NewsfeedRepository,
        create_test_newsfeed_event,
    ) -> None:
        """Test that event without 'type' field has null event_type."""
        # Arrange
        payload = {
            "data": "no type field",
            "message": "test",
        }
        event_id = await create_test_newsfeed_event(payload=payload)

        # Act
        result = await repository.fetch_event_by_id(event_id)

        # Assert
        assert result is not None
        assert result["event_type"] is None
        assert "type" not in result["payload"]


# ==============================================================================
# TRANSACTION TESTS
# ==============================================================================


class TestFetchEventByIdTransactions:
    """Test transaction behavior for fetch_event_by_id."""

    @pytest.mark.asyncio
    async def test_fetch_event_within_transaction(
        self,
        repository: NewsfeedRepository,
        create_test_newsfeed_event,
        asyncpg_conn,
    ) -> None:
        """Test fetching event within transaction works correctly."""
        # Arrange
        event_id = await create_test_newsfeed_event()

        # Act - Fetch within transaction
        async with asyncpg_conn.transaction():
            result = await repository.fetch_event_by_id(event_id, conn=asyncpg_conn)

        # Assert
        assert result is not None
        assert result["id"] == event_id
