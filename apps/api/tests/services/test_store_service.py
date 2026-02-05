"""Unit tests for StoreService quest reversion behavior."""

import pytest

from services.store_service import StoreService


pytestmark = [
    pytest.mark.domain_store,
]


class TestStoreServiceRevertQuestProgress:
    """Test quest progress reversion logic."""

    async def test_revert_skips_completed_quests(
        self, mock_pool, mock_state, mock_store_repo, mock_lootbox_repo, mocker
    ):
        """Completed quests should not be reverted when a completion is unverified."""
        service = StoreService(mock_pool, mock_state, mock_store_repo, mock_lootbox_repo)
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
