"""Tests for UtilitiesService."""

from unittest.mock import AsyncMock, Mock

import pytest

from services.utilities_service import UtilitiesService


@pytest.fixture
def mock_repo():
    """Create mock repository."""
    repo = Mock()
    repo.log_analytics = AsyncMock()
    repo.log_map_click = AsyncMock()
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
def utilities_service(mock_repo, mock_state, mock_pool):
    """Create service with mocked repository."""
    return UtilitiesService(mock_pool, mock_state, mock_repo)


class TestServiceLayer:
    """Test service business logic."""

    async def test_log_analytics_calls_repo(self, utilities_service, mock_repo):
        """Test that service calls repository."""
        import datetime as dt
        from genjishimada_sdk.logs import LogCreateRequest

        request = LogCreateRequest(
            command_name="test",
            user_id=123,
            created_at=dt.datetime.now(dt.timezone.utc),
            namespace={},
        )
        await utilities_service.log_analytics(request)
        mock_repo.log_analytics.assert_called_once()

    async def test_log_map_click_hashes_ip(self, utilities_service, mock_repo):
        """Test that service hashes IP address."""
        from genjishimada_sdk.logs import MapClickCreateRequest

        request = MapClickCreateRequest(
            code="TEST123",
            ip_address="192.168.1.1",
            user_id=None,
            source="web",
        )

        await utilities_service.log_map_click(request)

        # Verify repository was called with hashed IP
        mock_repo.log_map_click.assert_called_once()
        call_args = mock_repo.log_map_click.call_args
        assert "ip_hash" in call_args.kwargs
        assert call_args.kwargs["ip_hash"] != "192.168.1.1"  # Should be hashed
