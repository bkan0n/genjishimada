"""Tests for CommunityService."""

from unittest.mock import AsyncMock, Mock

import pytest

from services.community_service import CommunityService


@pytest.fixture
def mock_repo() -> Mock:
    """Create mock community repository."""
    repo = Mock()
    repo.fetch_community_leaderboard = AsyncMock(return_value=[])
    repo.fetch_players_per_xp_tier = AsyncMock(return_value=[])
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
def community_service(mock_repo: Mock, mock_state: Mock, mock_pool: Mock) -> CommunityService:
    """Create community service with mocked repository."""
    return CommunityService(mock_pool, mock_state, mock_repo)


class TestServicePassThrough:
    """Test service layer passes through to repository."""

    async def test_get_community_leaderboard_calls_repo(
        self, community_service: CommunityService, mock_repo: Mock
    ) -> None:
        """Test that service calls repository method."""
        await community_service.get_community_leaderboard()
        mock_repo.fetch_community_leaderboard.assert_called_once()
