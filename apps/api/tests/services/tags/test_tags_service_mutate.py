"""Tests for TagsService.mutate_tags dispatch logic."""

from __future__ import annotations

import pytest
from genjishimada_sdk.tags import (
    OpCreate,
    OpEdit,
    OpIncrementUsage,
    OpRemove,
)

from repository.tags_repository import TagsRepository
from services.tags_service import TagsService

pytestmark = [pytest.mark.domain_tags]

GUILD_ID = 100000000000000001
OWNER_ID = 200000000000000001


@pytest.fixture
def mock_tags_repo(mocker):
    """Mock TagsRepository."""
    return mocker.AsyncMock(spec=TagsRepository)


@pytest.fixture
def service(mock_pool, mock_state, mock_tags_repo):
    """Provide tags service instance with mocked dependencies."""
    return TagsService(mock_pool, mock_state, mock_tags_repo)


class TestMutateDispatch:
    async def test_create_op(self, service: TagsService, mock_tags_repo) -> None:
        """Create op dispatches to repository and returns tag_id."""
        mock_tags_repo.create_tag.return_value = 42
        ops = [OpCreate(guild_id=GUILD_ID, name="svc-create", content="hello", owner_id=OWNER_ID)]
        result = await service.mutate_tags(ops)
        assert len(result.results) == 1
        assert result.results[0].ok is True
        assert result.results[0].tag_id == 42
        mock_tags_repo.create_tag.assert_awaited_once_with(GUILD_ID, "svc-create", "hello", OWNER_ID)

    async def test_edit_nonexistent_returns_zero_affected(self, service: TagsService, mock_tags_repo) -> None:
        """Edit op on nonexistent tag returns ok with zero affected rows."""
        mock_tags_repo.edit_tag.return_value = 0
        ops = [OpEdit(guild_id=GUILD_ID, name="no-such-tag", new_content="x", owner_id=OWNER_ID)]
        result = await service.mutate_tags(ops)
        assert len(result.results) == 1
        assert result.results[0].ok is True
        assert result.results[0].affected == 0

    async def test_remove_nonexistent_returns_not_found(self, service: TagsService, mock_tags_repo) -> None:
        """Remove op on nonexistent tag returns ok=False."""
        mock_tags_repo.remove_tag_by_name.return_value = False
        ops = [OpRemove(guild_id=GUILD_ID, name="ghost", requester_id=OWNER_ID)]
        result = await service.mutate_tags(ops)
        assert len(result.results) == 1
        assert result.results[0].ok is False

    async def test_multiple_ops_in_batch(self, service: TagsService, mock_tags_repo) -> None:
        """Multiple ops execute sequentially and all return results."""
        mock_tags_repo.create_tag.return_value = 99
        ops = [
            OpCreate(guild_id=GUILD_ID, name="batch-tag", content="x", owner_id=OWNER_ID),
            OpIncrementUsage(guild_id=GUILD_ID, name="batch-tag"),
        ]
        result = await service.mutate_tags(ops)
        assert len(result.results) == 2
        assert all(r.ok for r in result.results)

    async def test_failed_op_does_not_block_later_ops(self, service: TagsService, mock_tags_repo) -> None:
        """A failed op does not prevent subsequent ops from executing."""
        mock_tags_repo.remove_tag_by_name.return_value = False
        mock_tags_repo.create_tag.return_value = 77
        ops = [
            OpRemove(guild_id=GUILD_ID, name="nonexistent", requester_id=OWNER_ID),
            OpCreate(guild_id=GUILD_ID, name="after-fail", content="x", owner_id=OWNER_ID),
        ]
        result = await service.mutate_tags(ops)
        assert len(result.results) == 2
        assert result.results[0].ok is False
        assert result.results[1].ok is True
