"""Tests for PlaytestService."""

from unittest.mock import AsyncMock, Mock

import pytest


@pytest.fixture
def mock_playtest_repo():
    """Create mock repository."""
    repo = Mock()
    repo.fetch_playtest_meta = AsyncMock(return_value=None)
    repo.fetch_votes = AsyncMock(return_value=[])
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
def playtest_service(mock_pool, mock_state, mock_playtest_repo):
    """Create service with mocked repository."""
    from services.playtest_service import PlaytestService

    return PlaytestService(mock_pool, mock_state, mock_playtest_repo)


class TestPlaytestServiceBasic:
    """Test basic service functionality."""

    def test_service_instantiates(self, playtest_service):
        """Test that service can be instantiated."""
        assert playtest_service is not None
