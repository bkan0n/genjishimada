"""Tests for MapsService."""

from unittest.mock import AsyncMock, Mock

import pytest


@pytest.fixture
def mock_maps_repo():
    """Create mock repository."""
    repo = Mock()
    repo.fetch_maps = AsyncMock(return_value=[])
    repo.lookup_map_id = AsyncMock(return_value=None)
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
def maps_service(mock_pool, mock_state, mock_maps_repo):
    """Create service with mocked repository."""
    from services.maps_service import MapsService

    return MapsService(mock_pool, mock_state, mock_maps_repo)


class TestMapsServiceBasic:
    """Test basic service functionality."""

    def test_service_instantiates(self, maps_service):
        """Test that service can be instantiated."""
        assert maps_service is not None
        assert hasattr(maps_service, "_maps_repo")
