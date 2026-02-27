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


class TestClaimQuestXpGrant:
    """Test that claim_quest delegates XP granting to LootboxService."""

    @staticmethod
    def _make_conn(mocker, mock_pool, fetchrow_return, fetchval_return):
        """Set up an async mock connection on mock_pool for claim_quest tests."""
        conn = mocker.AsyncMock()
        conn.fetchrow.return_value = fetchrow_return
        conn.fetchval.return_value = fetchval_return

        # transaction() must return a sync context manager (not a coroutine)
        tx_cm = mocker.MagicMock()
        tx_cm.__aenter__ = mocker.AsyncMock(return_value=None)
        tx_cm.__aexit__ = mocker.AsyncMock(return_value=None)
        conn.transaction = mocker.MagicMock(return_value=tx_cm)

        mock_pool.acquire.return_value.__aenter__ = mocker.AsyncMock(return_value=conn)
        return conn

    async def test_claim_quest_calls_grant_user_xp(
        self, mock_pool, mock_state, mock_store_repo, mock_lootbox_repo, mock_lootbox_service, mocker
    ):
        """Claiming a quest delegates XP to LootboxService.grant_user_xp."""
        from genjishimada_sdk.xp import XpGrantRequest, XpGrantResponse

        service = StoreService(mock_pool, mock_state, mock_store_repo, mock_lootbox_repo, mock_lootbox_service)

        self._make_conn(
            mocker,
            mock_pool,
            fetchrow_return={
                "quest_data": {"name": "Test Quest", "coin_reward": 100, "xp_reward": 25},
                "coins_rewarded": 100,
                "xp_rewarded": 25,
            },
            fetchval_return=200,
        )

        # Mock grant_user_xp response
        mock_lootbox_service.grant_user_xp.return_value = XpGrantResponse(
            previous_amount=50,
            new_amount=75,
        )

        headers = mocker.MagicMock()
        result = await service.claim_quest(user_id=123, progress_id=1, headers=headers)

        # Verify grant_user_xp was called with correct args
        mock_lootbox_service.grant_user_xp.assert_called_once_with(
            headers,
            123,
            XpGrantRequest(amount=25, type="Quest"),
        )

        assert result.success is True
        assert result.xp_earned == 25  # 75 - 50
        assert result.new_xp == 75
        assert result.coins_earned == 100
        assert result.new_coin_balance == 200

    async def test_claim_quest_skips_xp_grant_when_zero(
        self, mock_pool, mock_state, mock_store_repo, mock_lootbox_repo, mock_lootbox_service, mocker
    ):
        """Claiming a quest with zero XP reward skips grant_user_xp."""
        service = StoreService(mock_pool, mock_state, mock_store_repo, mock_lootbox_repo, mock_lootbox_service)

        self._make_conn(
            mocker,
            mock_pool,
            fetchrow_return={
                "quest_data": {"name": "Coin Only Quest", "coin_reward": 50, "xp_reward": 0},
                "coins_rewarded": 50,
                "xp_rewarded": 0,
            },
            fetchval_return=150,
        )

        headers = mocker.MagicMock()
        result = await service.claim_quest(user_id=123, progress_id=1, headers=headers)

        mock_lootbox_service.grant_user_xp.assert_not_called()
        assert result.xp_earned == 0
        assert result.new_xp == 0
