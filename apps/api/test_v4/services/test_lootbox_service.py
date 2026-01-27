"""Tests for LootboxService."""

from unittest.mock import AsyncMock, Mock
import pytest

from services.lootbox_service import LootboxService


@pytest.fixture
def mock_repo():
    """Create mock repository."""
    repo = Mock()
    repo.fetch_all_rewards = AsyncMock(return_value=[])
    repo.fetch_all_key_types = AsyncMock(return_value=[])
    repo.fetch_user_keys = AsyncMock(return_value=[])
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
def lootbox_service(mock_repo, mock_state, mock_pool):
    """Create service with mocked repository."""
    return LootboxService(mock_pool, mock_state, mock_repo)


class TestServiceLayer:
    """Test service business logic."""

    async def test_view_all_rewards_calls_repo(self, lootbox_service, mock_repo):
        """Test that service calls repository."""
        await lootbox_service.view_all_rewards()
        mock_repo.fetch_all_rewards.assert_called_once()

    async def test_view_all_keys_calls_repo(self, lootbox_service, mock_repo):
        """Test that service calls repository."""
        await lootbox_service.view_all_keys()
        mock_repo.fetch_all_key_types.assert_called_once()
