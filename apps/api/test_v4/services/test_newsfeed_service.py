"""Tests for NewsfeedService."""

import datetime as dt
from unittest.mock import AsyncMock, Mock

import pytest

from services.newsfeed_service import NewsfeedService


@pytest.fixture
def mock_repo():
    """Create mock repository."""
    repo = Mock()
    repo.insert_event = AsyncMock(return_value=42)
    repo.fetch_event_by_id = AsyncMock(
        return_value={
            "id": 1,
            "timestamp": dt.datetime.now(dt.timezone.utc),
            "payload": {"type": "guide", "code": "TEST1", "guide_url": "https://example.com", "name": "Tester"},
            "event_type": "guide",
        }
    )
    repo.fetch_events = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_state():
    """Create mock state."""
    return Mock()


@pytest.fixture
def mock_pool():
    """Create mock pool."""
    return Mock()


@pytest.fixture
def newsfeed_service(mock_repo, mock_state, mock_pool):
    """Create service with mocked repository."""
    return NewsfeedService(mock_pool, mock_state, mock_repo)


class TestServiceLayer:
    """Test service business logic."""

    async def test_create_and_publish_calls_repo(self, newsfeed_service, mock_repo):
        """Test that create_and_publish calls repository."""
        from genjishimada_sdk.newsfeed import NewsfeedEvent, NewsfeedGuide
        from litestar.datastructures import Headers

        event = NewsfeedEvent(
            id=None,
            timestamp=dt.datetime.now(dt.timezone.utc),
            payload=NewsfeedGuide(code="TEST1", guide_url="https://example.com", name="Tester"),
            event_type="guide",
        )
        headers = Headers({"X-PYTEST-ENABLED": "1"})

        result = await newsfeed_service.create_and_publish(event=event, headers=headers)

        mock_repo.insert_event.assert_called_once()
        assert result.newsfeed_id == 42

    async def test_get_event_calls_repo(self, newsfeed_service, mock_repo):
        """Test that get_event calls repository."""
        await newsfeed_service.get_event(1)
        mock_repo.fetch_event_by_id.assert_called_once_with(1)

    async def test_list_events_calls_repo(self, newsfeed_service, mock_repo):
        """Test that list_events calls repository."""
        await newsfeed_service.list_events(limit=10, page_number=1, type_=None)
        mock_repo.fetch_events.assert_called_once_with(limit=10, offset=0, event_type=None)
