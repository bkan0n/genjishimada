"""Unit tests for StoreService quest behavior."""

import pytest
from genjishimada_sdk.store import (
    AdminUpdateUserQuestRequest,
    PatchQuestProgress,
)

from services.exceptions.store import InvalidQuestPatchError, QuestNotFoundError
from services.store_service import StoreService


pytestmark = [
    pytest.mark.domain_store,
]


class TestStoreServiceRevertQuestProgress:
    """Test quest progress reversion logic."""

    async def test_revert_skips_completed_quests(
        self, mock_pool, mock_state, mock_store_repo, mock_lootbox_repo, mock_lootbox_service, mocker
    ):
        """Completed quests should not be reverted when a completion is unverified."""
        service = StoreService(mock_pool, mock_state, mock_store_repo, mock_lootbox_repo, mock_lootbox_service)
        service.ensure_user_quests_for_rotation = mocker.AsyncMock()

        mock_store_repo.get_active_user_quests.return_value = [
            {
                "progress_id": 1,
                "quest_data": {"requirements": {"type": "complete_maps", "count": 15, "difficulty": "any"}},
                "progress": {"current": 15, "completed_map_ids": [10]},
                "completed_at": "2025-01-01T00:00:00Z",
            }
        ]

        await service.revert_quest_progress(
            user_id=123456789,
            event_type="completion",
            event_data={
                "map_id": 10,
                "difficulty": "Hard",
                "category": "Speedrun",
                "time": 40.0,
            },
            remaining_times=[],
            remaining_medals=[],
        )

        mock_store_repo.update_quest_progress.assert_not_called()
        mock_store_repo.unmark_quest_complete.assert_not_called()


class TestAdminUpdateUserQuest:
    """Tests for admin_update_user_quest service method."""

    async def test_all_unset_raises_error(self, mock_pool, mock_state, mock_store_repo, mock_lootbox_repo, mock_lootbox_service):
        """All-UNSET request raises InvalidQuestPatchError."""
        service = StoreService(mock_pool, mock_state, mock_store_repo, mock_lootbox_repo, mock_lootbox_service)
        data = AdminUpdateUserQuestRequest()

        with pytest.raises(InvalidQuestPatchError):
            await service.admin_update_user_quest(1, 1, data)

    async def test_quest_not_found_raises_error(self, mock_pool, mock_state, mock_store_repo, mock_lootbox_repo, mock_lootbox_service):
        """Nonexistent progress_id raises QuestNotFoundError."""
        service = StoreService(mock_pool, mock_state, mock_store_repo, mock_lootbox_repo, mock_lootbox_service)
        mock_store_repo.get_user_quest_progress.return_value = None
        data = AdminUpdateUserQuestRequest(completed=True)

        with pytest.raises(QuestNotFoundError):
            await service.admin_update_user_quest(1, 999, data)

    async def test_complete_auto_patches_count_based(self, mock_pool, mock_state, mock_store_repo, mock_lootbox_repo, mock_lootbox_service):
        """completed=True on complete_maps quest sets current=target."""
        service = StoreService(mock_pool, mock_state, mock_store_repo, mock_lootbox_repo, mock_lootbox_service)
        mock_store_repo.get_user_quest_progress.return_value = {
            "quest_data": {"requirements": {"type": "complete_maps", "count": 10}},
            "progress": {"current": 3, "completed_map_ids": [1, 2, 3]},
            "completed_at": None,
        }
        data = AdminUpdateUserQuestRequest(completed=True)

        await service.admin_update_user_quest(1, 1, data)

        call_kwargs = mock_store_repo.admin_update_user_quest.call_args.kwargs
        assert call_kwargs["progress"]["current"] == 10
        assert call_kwargs["completed_at"] is not None

    async def test_complete_auto_patches_time_based(self, mock_pool, mock_state, mock_store_repo, mock_lootbox_repo, mock_lootbox_service):
        """completed=True on beat_time quest sets best_attempt < target_time."""
        service = StoreService(mock_pool, mock_state, mock_store_repo, mock_lootbox_repo, mock_lootbox_service)
        mock_store_repo.get_user_quest_progress.return_value = {
            "quest_data": {"requirements": {"type": "beat_time", "target_time": 60.0}},
            "progress": {},
            "completed_at": None,
        }
        data = AdminUpdateUserQuestRequest(completed=True)

        await service.admin_update_user_quest(1, 1, data)

        call_kwargs = mock_store_repo.admin_update_user_quest.call_args.kwargs
        assert call_kwargs["progress"]["best_attempt"] == 59.99
        assert call_kwargs["completed_at"] is not None

    async def test_complete_auto_patches_complete_map(self, mock_pool, mock_state, mock_store_repo, mock_lootbox_repo, mock_lootbox_service):
        """completed=True on complete_map quest sets completed=True in progress."""
        service = StoreService(mock_pool, mock_state, mock_store_repo, mock_lootbox_repo, mock_lootbox_service)
        mock_store_repo.get_user_quest_progress.return_value = {
            "quest_data": {"requirements": {"type": "complete_map", "map_id": 42}},
            "progress": {"completed": False},
            "completed_at": None,
        }
        data = AdminUpdateUserQuestRequest(completed=True)

        await service.admin_update_user_quest(1, 1, data)

        call_kwargs = mock_store_repo.admin_update_user_quest.call_args.kwargs
        assert call_kwargs["progress"]["completed"] is True

    async def test_explicit_progress_overrides_auto_patch(
        self, mock_pool, mock_state, mock_store_repo, mock_lootbox_repo, mock_lootbox_service
    ):
        """Sending both completed=True and explicit progress uses explicit values."""
        service = StoreService(mock_pool, mock_state, mock_store_repo, mock_lootbox_repo, mock_lootbox_service)
        mock_store_repo.get_user_quest_progress.return_value = {
            "quest_data": {"requirements": {"type": "complete_maps", "count": 10}},
            "progress": {"current": 3},
            "completed_at": None,
        }
        data = AdminUpdateUserQuestRequest(completed=True, progress=PatchQuestProgress(current=7))

        await service.admin_update_user_quest(1, 1, data)

        call_kwargs = mock_store_repo.admin_update_user_quest.call_args.kwargs
        assert call_kwargs["progress"]["current"] == 7

    async def test_uncomplete_clears_completed_at(self, mock_pool, mock_state, mock_store_repo, mock_lootbox_repo, mock_lootbox_service):
        """completed=False clears completed_at."""
        service = StoreService(mock_pool, mock_state, mock_store_repo, mock_lootbox_repo, mock_lootbox_service)
        mock_store_repo.get_user_quest_progress.return_value = {
            "quest_data": {"requirements": {"type": "complete_maps", "count": 10}},
            "progress": {"current": 10},
            "completed_at": "2025-01-01T00:00:00Z",
        }
        data = AdminUpdateUserQuestRequest(completed=False)

        await service.admin_update_user_quest(1, 1, data)

        call_kwargs = mock_store_repo.admin_update_user_quest.call_args.kwargs
        assert call_kwargs["completed_at"] is None
