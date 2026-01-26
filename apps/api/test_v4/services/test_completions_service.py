"""Tests for CompletionsService."""

from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from genjishimada_sdk.completions import CompletionPatchRequest, UpvoteCreateRequest
from genjishimada_sdk.internal import JobStatusResponse
from litestar.datastructures import Headers

from services.completions_service import CompletionsService
from utilities.errors import CustomHTTPException


@pytest.fixture
def mock_repo() -> Mock:
    """Create mock completions repository."""
    repo = Mock()
    repo.fetch_user_completions = AsyncMock(return_value=[])
    repo.submit_completion = AsyncMock(return_value=(1, None))
    repo.edit_completion = AsyncMock(return_value=None)
    repo.insert_upvote = AsyncMock(return_value=1)
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
def completions_service(mock_repo: Mock, mock_state: Mock, mock_pool: Mock) -> CompletionsService:
    """Create completions service with mocked repository."""
    return CompletionsService(mock_pool, mock_state, mock_repo)


class TestServiceSmoke:
    """Basic service wiring tests."""

    def test_service_instantiates(self, completions_service: CompletionsService) -> None:
        """Ensure service can be instantiated."""
        assert completions_service is not None


class TestServiceBehavior:
    """Service behavior tests."""

    @pytest.mark.asyncio
    async def test_upvote_submission_raises_on_duplicate(
        self, completions_service: CompletionsService, mock_repo: Mock
    ) -> None:
        """Upvote should raise when user already upvoted."""
        mock_repo.insert_upvote.return_value = None
        with pytest.raises(CustomHTTPException):
            await completions_service.upvote_submission(
                request=Mock(headers=Headers()),
                data=UpvoteCreateRequest(user_id=1, message_id=2),
            )

    @pytest.mark.asyncio
    async def test_upvote_submission_publishes_on_milestone(
        self, completions_service: CompletionsService, mock_repo: Mock
    ) -> None:
        """Upvote should publish when milestone reached."""
        mock_repo.insert_upvote.return_value = 10
        completions_service.publish_message = AsyncMock(return_value=JobStatusResponse(uuid4(), "queued"))
        result = await completions_service.upvote_submission(
            request=Mock(headers=Headers()),
            data=UpvoteCreateRequest(user_id=1, message_id=2),
        )
        assert result.upvotes == 10
        completions_service.publish_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_edit_completion_filters_unset_fields(
        self, completions_service: CompletionsService, mock_repo: Mock
    ) -> None:
        """Edit completion should only pass set fields."""
        patch = CompletionPatchRequest(message_id=123)
        await completions_service.edit_completion(Mock(), 10, patch)
        mock_repo.edit_completion.assert_called_once_with(10, {"message_id": 123})
