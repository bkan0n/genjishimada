"""Tests for LootboxService."""

from unittest.mock import AsyncMock, Mock
import pytest

from genjishimada_sdk.lootbox import LootboxKeyType
from genjishimada_sdk.xp import XpGrantRequest

from services.lootbox_service import LootboxService
from services.exceptions.lootbox import InsufficientKeysError, LootboxError


@pytest.fixture
def mock_repo():
    """Create mock repository."""
    repo = Mock()
    repo.fetch_all_rewards = AsyncMock(return_value=[])
    repo.fetch_all_key_types = AsyncMock(return_value=[])
    repo.fetch_user_keys = AsyncMock(return_value=[])
    repo.fetch_user_key_count = AsyncMock(return_value=0)
    repo.fetch_xp_multiplier = AsyncMock(return_value=1.0)
    repo.upsert_user_xp = AsyncMock(return_value={"previous_amount": 0, "new_amount": 0})
    repo.insert_user_key = AsyncMock()
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


class TestExceptions:
    """Test domain exceptions."""

    def test_lootbox_error_base(self) -> None:
        """Test base LootboxError."""
        error = LootboxError("test message")
        assert "test message" in str(error)

    def test_insufficient_keys_error(self) -> None:
        """Test InsufficientKeysError."""
        error = InsufficientKeysError("Classic")
        assert "Classic" in error.message
        assert "enough keys" in error.message.lower()
        assert error.context["key_type"] == "Classic"


class TestReadMethods:
    """Test read service methods."""

    async def test_view_all_rewards(self, lootbox_service, mock_repo):
        """Test view_all_rewards."""
        mock_repo.fetch_all_rewards.return_value = [
            {"name": "test", "key_type": "Classic", "rarity": "common", "type": "spray"}
        ]
        result = await lootbox_service.view_all_rewards()
        assert len(result) == 1
        mock_repo.fetch_all_rewards.assert_called_once()

    async def test_view_user_keys(self, lootbox_service, mock_repo):
        """Test view_user_keys."""
        mock_repo.fetch_user_keys.return_value = [{"key_type": "Classic", "amount": 5}]
        result = await lootbox_service.view_user_keys(user_id=1)
        assert len(result) == 1
        mock_repo.fetch_user_keys.assert_called_once()


class TestWriteMethods:
    """Test write service methods."""

    async def test_grant_key_calls_repo(self, lootbox_service, mock_repo):
        """Test grant_key_to_user."""
        mock_repo.insert_user_key = AsyncMock()
        await lootbox_service.grant_key_to_user(user_id=1, key_type="Classic")
        mock_repo.insert_user_key.assert_called_once_with(1, "Classic", conn=None)

    async def test_grant_xp_calls_repo_and_publishes_event(self, lootbox_service, mock_repo, mock_state):
        """Test grant_user_xp publishes event to RabbitMQ."""
        from litestar.datastructures.headers import Headers

        mock_repo.fetch_xp_multiplier.return_value = 1.0
        mock_repo.upsert_user_xp.return_value = {"previous_amount": 0, "new_amount": 50}

        # Mock publish_message
        lootbox_service.publish_message = AsyncMock()

        headers = Headers({})
        request = XpGrantRequest(amount=50, type="Completion")
        resp = await lootbox_service.grant_user_xp(headers, user_id=1, data=request)

        assert resp.new_amount == 50
        assert resp.previous_amount == 0

        # Verify RabbitMQ publishing was called
        lootbox_service.publish_message.assert_called_once()
        call_args = lootbox_service.publish_message.call_args
        assert call_args.kwargs["routing_key"] == "api.xp.grant"
        assert call_args.kwargs["data"].user_id == 1
        assert call_args.kwargs["data"].amount == 50


class TestValidation:
    """Test validation logic."""

    async def test_insufficient_keys_raises_error(self, lootbox_service, mock_repo):
        """Test that insufficient keys raises InsufficientKeysError."""
        mock_repo.fetch_user_key_count.return_value = 0

        with pytest.raises(InsufficientKeysError):
            await lootbox_service.get_random_items(
                user_id=1,
                key_type="Classic",
                amount=3,
                test_mode=False
            )
