"""Tests for NotificationsService."""

from unittest.mock import AsyncMock, Mock

import pytest
from genjishimada_sdk.notifications import NotificationCreateRequest
from litestar import Litestar
from litestar.datastructures import Headers, State
from litestar.testing import AsyncTestClient
from services.notifications_service import NotificationsService


@pytest.fixture
def mock_repo() -> Mock:
    """Create mock repository."""
    repo = Mock()
    repo.insert_event = AsyncMock(return_value=42)
    repo.fetch_user_events = AsyncMock(return_value=[])
    repo.fetch_unread_count = AsyncMock(return_value=0)
    repo.mark_event_read = AsyncMock()
    repo.mark_all_events_read = AsyncMock(return_value=2)
    repo.dismiss_event = AsyncMock()
    repo.record_delivery_result = AsyncMock()
    repo.fetch_preferences = AsyncMock(return_value=[])
    repo.upsert_preference = AsyncMock()
    return repo


@pytest.fixture
def mock_state(test_client: AsyncTestClient[Litestar]) -> State:
    """Create mock state."""
    return test_client.app.state


@pytest.fixture
def mock_pool() -> Mock:
    """Create mock pool."""
    return Mock()


@pytest.fixture
def notifications_service(mock_repo: Mock, mock_state: State, mock_pool: Mock) -> NotificationsService:
    """Create service with mocked repository."""
    return NotificationsService(mock_pool, mock_state, mock_repo)


class TestServiceLayer:
    """Test service business logic."""

    async def test_create_and_dispatch_calls_repo(
        self, notifications_service: NotificationsService, mock_repo: Mock
    ) -> None:
        """Test that create_and_dispatch calls repository."""
        request = NotificationCreateRequest(
            user_id=300,
            event_type="xp_gain",
            title="XP Gained",
            body="You gained 100 XP",
            discord_message="🎉 +100 XP",
            metadata={"xp_amount": 100},
        )
        headers = Headers({})

        result = await notifications_service.create_and_dispatch(request, headers)

        mock_repo.insert_event.assert_called_once()
        assert result.id == 42  # noqa: PLR2004

    async def test_get_user_events_calls_repo(
        self, notifications_service: NotificationsService, mock_repo: Mock
    ) -> None:
        """Test that get_user_events calls repository."""
        await notifications_service.get_user_events(300, unread_only=False, limit=50, offset=0)
        mock_repo.fetch_user_events.assert_called_once_with(
            user_id=300,
            unread_only=False,
            limit=50,
            offset=0,
        )

    async def test_get_unread_count_calls_repo(
        self, notifications_service: NotificationsService, mock_repo: Mock
    ) -> None:
        """Test that get_unread_count calls repository."""
        await notifications_service.get_unread_count(300)
        mock_repo.fetch_unread_count.assert_called_once_with(300)

    async def test_mark_read_calls_repo(self, notifications_service: NotificationsService, mock_repo: Mock) -> None:
        """Test that mark_read calls repository."""
        await notifications_service.mark_read(42)
        mock_repo.mark_event_read.assert_called_once_with(42)
