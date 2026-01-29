"""Tests for RankCardService."""

from unittest.mock import AsyncMock, Mock

import pytest

from services.rank_card_service import RankCardService


@pytest.fixture
def mock_repo():
    """Create mock repository."""
    repo = Mock()
    repo.fetch_background = AsyncMock(return_value={"name": "placeholder"})
    return repo


@pytest.fixture
def mock_state(test_client):
    """Create mock state."""
    return test_client.app.state


@pytest.fixture
def mock_pool():
    """Create mock pool."""
    return Mock()


@pytest.fixture
def rank_card_service(mock_repo, mock_state, mock_pool):
    """Create service with mocked repository."""
    return RankCardService(mock_pool, mock_state, mock_repo)


class TestServiceLayer:
    """Test service business logic."""

    async def test_get_background_calls_repo(self, rank_card_service, mock_repo):
        """Test that service calls repository."""
        await rank_card_service.get_background(user_id=1)
        mock_repo.fetch_background.assert_called_once_with(user_id=1)
