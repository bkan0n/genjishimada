"""Tests for CompletionsService."""

from unittest.mock import Mock

import pytest

from services.completions_service import CompletionsService


@pytest.fixture
def mock_repo() -> Mock:
    """Create mock completions repository."""
    return Mock()


@pytest.fixture
def mock_state(test_client) -> Mock:  # type: ignore[no-untyped-def]
    """Create mock state."""
    return test_client.app.state


@pytest.fixture
def mock_pool() -> Mock:
    """Create mock pool."""
    return Mock()


@pytest.fixture
def completions_service(mock_repo: Mock, mock_state: Mock, mock_pool: Mock) -> CompletionsService:
    """Create completions service with mocked repository."""
    return CompletionsService(mock_pool, mock_state, mock_repo)


class TestServiceSmoke:
    """Basic service wiring tests."""

    def test_service_instantiates(self, completions_service: CompletionsService) -> None:
        """Ensure service can be instantiated."""
        assert completions_service is not None
