"""Tests for ChangeRequestsService."""

from unittest.mock import AsyncMock, Mock

import pytest

from services.change_requests_service import ChangeRequestsService


@pytest.fixture
def mock_repo() -> Mock:
    """Create mock change requests repository."""
    repo = Mock()
    repo.fetch_creator_mentions = AsyncMock(return_value="100000000000000001")
    repo.fetch_unresolved_requests = AsyncMock(return_value=[])
    repo.create_request = AsyncMock(return_value=None)
    repo.mark_resolved = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_state(test_client) -> Mock:  # type: ignore[no-untyped-def]
    """Create mock state."""
    return test_client.app.state


@pytest.fixture
def mock_pool() -> Mock:
    """Create mock pool."""
    return Mock()


@pytest.fixture
def change_requests_service(mock_repo: Mock, mock_state: Mock, mock_pool: Mock) -> ChangeRequestsService:
    """Create service with mocked repository."""
    return ChangeRequestsService(mock_pool, mock_state, mock_repo)


class TestPermissionLogic:
    """Test permission check business logic."""

    async def test_check_permission_returns_true_when_user_in_mentions(
        self, change_requests_service: ChangeRequestsService, mock_repo: Mock
    ) -> None:
        """Test permission returns True when user ID in creator_mentions."""
        mock_repo.fetch_creator_mentions.return_value = "100000000000000001, 100000000000000002"
        result = await change_requests_service.check_permission(1, 100000000000000001, "TEST")
        assert result is True

    async def test_check_permission_returns_false_when_user_not_in_mentions(
        self, change_requests_service: ChangeRequestsService, mock_repo: Mock
    ) -> None:
        """Test permission returns False when user ID not in creator_mentions."""
        mock_repo.fetch_creator_mentions.return_value = "100000000000000001"
        result = await change_requests_service.check_permission(1, 999999, "TEST")
        assert result is False

    async def test_check_permission_returns_false_when_no_mentions(
        self, change_requests_service: ChangeRequestsService, mock_repo: Mock
    ) -> None:
        """Test permission returns False when no creator_mentions found."""
        mock_repo.fetch_creator_mentions.return_value = None
        result = await change_requests_service.check_permission(1, 100000000000000001, "TEST")
        assert result is False
