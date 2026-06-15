"""Unit tests for CompletionsService."""

import msgspec
import pytest
from genjishimada_sdk.notifications import NotificationEventType
from genjishimada_sdk.completions import (
    CompletionCreateRequest,
    CompletionModerateRequest,
    CompletionPatchRequest,
    CompletionVerificationUpdateRequest,
    SuspiciousCompletionCreateRequest,
    UpvoteCreateRequest,
)
from genjishimada_sdk.maps import OverwatchCode

from repository.exceptions import (
    ForeignKeyViolationError,
    UniqueConstraintViolationError,
)
from services.completions_service import CompletionsService
from services.exceptions.completions import (
    CompletionNotFoundError,
    DuplicateCompletionError,
    DuplicateFlagError,
    DuplicateQualityVoteError,
    DuplicateUpvoteError,
    DuplicateVerificationError,
    MapNotFoundError,
    SlowerThanPendingError,
)

pytestmark = [
    pytest.mark.domain_completions,
]


class TestCompletionsServiceBuildPatchDict:
    """Test _build_patch_dict helper method."""

    def test_build_patch_dict_all_unset(self, mock_pool, mock_state, mock_completions_repo):
        """All UNSET fields are excluded from patch dict."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        patch = CompletionPatchRequest()
        result = service._build_patch_dict(patch)

        assert result == {}

    def test_build_patch_dict_some_set(self, mock_pool, mock_state, mock_completions_repo):
        """Only set fields are included in patch dict."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        patch = CompletionPatchRequest(message_id=12345, completion=True)
        result = service._build_patch_dict(patch)

        assert result == {"message_id": 12345, "completion": True}
        assert "verification_id" not in result

    def test_build_patch_dict_all_set(self, mock_pool, mock_state, mock_completions_repo):
        """All set fields are included in patch dict."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        patch = CompletionPatchRequest(
            message_id=12345,
            completion=True,
            verification_id=100,
            legacy=False,
            legacy_medal="gold",
            wr_xp_check=True,
        )
        result = service._build_patch_dict(patch)

        assert result == {
            "message_id": 12345,
            "completion": True,
            "verification_id": 100,
            "legacy": False,
            "legacy_medal": "gold",
            "wr_xp_check": True,
        }

    def test_build_patch_dict_preserves_none_value(
        self, mock_pool, mock_state, mock_completions_repo
    ):
        """None values that are explicitly set are included."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        patch = CompletionPatchRequest(legacy_medal=None)
        result = service._build_patch_dict(patch)

        assert result == {"legacy_medal": None}
        assert "message_id" not in result
        assert "completion" not in result


class TestCompletionsServiceSubmitCompletion:
    """Test submit_completion business logic."""

    async def test_submit_completion_map_not_found(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """Raises MapNotFoundError if map code doesn't exist."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.check_map_exists.return_value = False

        data = CompletionCreateRequest(
            code="NOTFOUND",
            user_id=123456789,
            time=45.5,
            screenshot="https://example.com/screenshot.png",
            video=None,
        )
        mock_request = mocker.Mock()
        mock_autocomplete = mocker.AsyncMock()
        mock_users = mocker.AsyncMock()

        with pytest.raises(MapNotFoundError):
            await service.submit_completion(data, mock_request, mock_autocomplete, mock_users)

        mock_completions_repo.check_map_exists.assert_called_once_with("NOTFOUND")

    async def test_submit_completion_slower_than_pending(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """Raises SlowerThanPendingError if new time >= pending time."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.check_map_exists.return_value = True
        mock_completions_repo.get_pending_verification.return_value = {
            "id": 1,
            "time": 40.0,
            "verification_id": 100,
        }

        data = CompletionCreateRequest(
            code="ABC123",
            user_id=123456789,
            time=45.5,  # Slower than pending 40.0
            screenshot="https://example.com/screenshot.png",
            video=None,
        )
        mock_request = mocker.Mock()
        mock_autocomplete = mocker.AsyncMock()
        mock_users = mocker.AsyncMock()

        with pytest.raises(SlowerThanPendingError):
            await service.submit_completion(data, mock_request, mock_autocomplete, mock_users)

    async def test_submit_completion_supersedes_pending_with_faster_time(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """Successfully supersedes pending verification with faster time."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.check_map_exists.return_value = True
        mock_completions_repo.get_pending_verification.return_value = {
            "id": 1,
            "time": 45.0,
            "verification_id": 100,
        }
        mock_completions_repo.insert_completion.return_value = 2
        mock_completions_repo.fetch_suspicious_flags.return_value = []

        data = CompletionCreateRequest(
            code="ABC123",
            user_id=123456789,
            time=40.0,  # Faster than pending 45.0
            screenshot="https://example.com/screenshot.png",
            video="https://example.com/video.mp4",  # Has video, skips auto-verify
        )
        mock_request = mocker.Mock()
        mock_request.headers = {}
        mock_autocomplete = mocker.AsyncMock()
        mock_users = mocker.AsyncMock()

        # Mock publish_message to skip RabbitMQ
        service.publish_message = mocker.AsyncMock(return_value={"job_id": "job123"})

        result = await service.submit_completion(data, mock_request, mock_autocomplete, mock_users)

        # Verify pending was rejected
        mock_completions_repo.reject_completion.assert_called_once_with(1, 969632729643753482, conn=mocker.ANY)

        # Verify new completion was inserted
        mock_completions_repo.insert_completion.assert_called_once_with(
            code="ABC123",
            user_id=123456789,
            time=40.0,
            screenshot="https://example.com/screenshot.png",
            video="https://example.com/video.mp4",
            conn=mocker.ANY,
        )

        # Verify deletion message was published
        delete_calls = [call for call in service.publish_message.call_args_list if "delete" in call[1]["routing_key"]]
        assert len(delete_calls) == 1

        # Verify submission message was published
        submission_calls = [call for call in service.publish_message.call_args_list if "submission" in call[1]["routing_key"]]
        assert len(submission_calls) == 1

        assert result.completion_id == 2

    async def test_submit_completion_does_not_update_quest_progress(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """Quest progress should not update on submission (only on verification)."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.check_map_exists.return_value = True
        mock_completions_repo.get_pending_verification.return_value = None
        mock_completions_repo.insert_completion.return_value = 2
        mock_completions_repo.fetch_suspicious_flags.return_value = []
        mock_completions_repo.fetch_map_metadata_by_code.return_value = {
            "map_id": 10,
            "difficulty": "Hard",
            "category": "Speedrun",
        }

        mock_store_repo = mocker.AsyncMock()
        mock_store_repo.get_medal_thresholds.return_value = {
            "gold": 30,
            "silver": 40,
            "bronze": 50,
        }
        mocker.patch("services.completions_service.StoreRepository", return_value=mock_store_repo)
        mocker.patch("services.completions_service.LootboxRepository", return_value=mocker.AsyncMock())

        mock_store_service = mocker.Mock()
        mock_store_service.update_quest_progress = mocker.AsyncMock(return_value=[])
        mocker.patch("services.completions_service.StoreService", return_value=mock_store_service)

        data = CompletionCreateRequest(
            code="ABC123",
            user_id=123456789,
            time=40.0,
            screenshot="https://example.com/screenshot.png",
            video="https://example.com/video.mp4",
        )
        mock_request = mocker.Mock()
        mock_request.headers = {}
        mock_notifications = mocker.AsyncMock()
        mock_users = mocker.AsyncMock()

        service.publish_message = mocker.AsyncMock(return_value={"job_id": "job123"})

        await service.submit_completion(data, mock_request, mock_notifications, mock_users)

        mock_store_service.update_quest_progress.assert_not_called()

    async def test_submit_completion_success_no_pending(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """Successfully submits completion with no pending verification."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.check_map_exists.return_value = True
        mock_completions_repo.get_pending_verification.return_value = None
        mock_completions_repo.insert_completion.return_value = 2

        data = CompletionCreateRequest(
            code="ABC123",
            user_id=123456789,
            time=40.0,
            screenshot="https://example.com/screenshot.png",
            video="https://example.com/video.mp4",  # Has video, skips auto-verify
        )
        mock_request = mocker.Mock()
        mock_request.headers = {}
        mock_autocomplete = mocker.AsyncMock()
        mock_users = mocker.AsyncMock()

        # Mock publish_message and get_suspicious_flags
        service.publish_message = mocker.AsyncMock(return_value={"job_id": "job123"})
        service.get_suspicious_flags = mocker.AsyncMock(return_value=[])

        result = await service.submit_completion(data, mock_request, mock_autocomplete, mock_users)

        # Verify no rejection occurred
        mock_completions_repo.reject_completion.assert_not_called()

        # Verify new completion was inserted
        mock_completions_repo.insert_completion.assert_called_once()

        # Verify no deletion message was published
        delete_calls = [call for call in service.publish_message.call_args_list if "delete" in call[1]["routing_key"]]
        assert len(delete_calls) == 0

        # Verify submission message was published
        submission_calls = [call for call in service.publish_message.call_args_list if "submission" in call[1]["routing_key"]]
        assert len(submission_calls) == 1

        assert result.completion_id == 2


class TestCompletionsServiceVerifyCompletion:
    """Test verify_completion business logic."""

    async def test_verify_completion_updates_quest_progress_on_verified(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """Quest progress should update when a completion is verified."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.check_completion_exists.return_value = True
        mock_completions_repo.fetch_completion_for_moderation.return_value = {
            "user_id": 123456789,
            "code": "ABC123",
            "old_time": 40.0,
            "old_verified": False,
        }
        mock_completions_repo.fetch_map_metadata_by_code.return_value = {
            "map_id": 10,
            "difficulty": "Hard",
            "category": "Speedrun",
        }

        mock_store_repo = mocker.AsyncMock()
        mock_store_repo.get_medal_thresholds.return_value = {
            "gold": 30,
            "silver": 40,
            "bronze": 50,
        }
        mocker.patch("services.completions_service.StoreRepository", return_value=mock_store_repo)
        mocker.patch("services.completions_service.LootboxRepository", return_value=mocker.AsyncMock())

        mock_store_service = mocker.Mock()
        mock_store_service.update_quest_progress = mocker.AsyncMock(
            return_value=[{"name": "Quest One", "quest_id": 1, "progress_id": 99}]
        )
        mocker.patch("services.completions_service.StoreService", return_value=mock_store_service)

        mock_users_repo = mocker.AsyncMock()
        mock_users_repo.fetch_user.return_value = {"coalesced_name": "TestPlayer"}
        mocker.patch("services.completions_service.UsersRepository", return_value=mock_users_repo)

        service.publish_message = mocker.AsyncMock(return_value={"job_id": "job123"})

        data = CompletionVerificationUpdateRequest(
            verified_by=123456789,
            verified=True,
            reason="Looks good",
        )
        mock_request = mocker.Mock()
        mock_request.headers = {}
        mock_notifications = mocker.AsyncMock()

        await service.verify_completion(mock_request, 1, data, notifications=mock_notifications)

        mock_store_service.update_quest_progress.assert_called_once_with(
            user_id=123456789,
            event_type="completion",
            event_data={
                "map_id": 10,
                "difficulty": "Hard",
                "category": "Speedrun",
                "time": 40.0,
                "medal": "Silver",
            },
        )
        mock_notifications.create_and_dispatch.assert_called_once()

    async def test_verify_completion_unverified_reverts_quest_progress(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """Quest progress should revert when a completion is unverified."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.check_completion_exists.return_value = True
        mock_completions_repo.fetch_completion_for_moderation.return_value = {
            "user_id": 123456789,
            "code": "ABC123",
            "old_time": 40.0,
            "old_verified": True,
        }
        mock_completions_repo.fetch_map_metadata_by_code.return_value = {
            "map_id": 10,
            "difficulty": "Hard",
            "category": "Speedrun",
        }
        mock_completions_repo.fetch_verified_times_for_user_map.return_value = []

        mock_store_repo = mocker.AsyncMock()
        mock_store_repo.get_medal_thresholds.return_value = {
            "gold": 30,
            "silver": 40,
            "bronze": 50,
        }
        mocker.patch("services.completions_service.StoreRepository", return_value=mock_store_repo)
        mocker.patch("services.completions_service.LootboxRepository", return_value=mocker.AsyncMock())

        mock_store_service = mocker.Mock()
        mock_store_service.revert_quest_progress = mocker.AsyncMock()
        mocker.patch("services.completions_service.StoreService", return_value=mock_store_service)

        service.publish_message = mocker.AsyncMock(return_value={"job_id": "job123"})

        data = CompletionVerificationUpdateRequest(
            verified_by=123456789,
            verified=False,
            reason="Invalid proof",
        )
        mock_request = mocker.Mock()
        mock_request.headers = {}

        await service.verify_completion(mock_request, 1, data)

        mock_store_service.revert_quest_progress.assert_called_once_with(
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


class TestUpdateQuestProgressNotifications:
    """Verify quest completion notification metadata enrichment."""

    async def test_quest_complete_notification_includes_metadata(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """QUEST_COMPLETE notification includes quest_name, difficulty, rewards in metadata."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.fetch_map_metadata_by_code.return_value = {
            "map_id": 101,
            "difficulty": "Hard",
            "category": "Classic",
        }

        mock_store_repo = mocker.AsyncMock()
        mock_store_repo.get_medal_thresholds.return_value = None
        mocker.patch("services.completions_service.StoreRepository", return_value=mock_store_repo)
        mocker.patch("services.completions_service.LootboxRepository", return_value=mocker.AsyncMock())

        mock_store_service = mocker.Mock()
        mock_store_service.update_quest_progress = mocker.AsyncMock(
            return_value=[
                {
                    "name": "Complete 3 Maps",
                    "difficulty": "easy",
                    "quest_id": 5,
                    "progress_id": 42,
                    "coin_reward": 100,
                    "xp_reward": 15,
                    "requirements": {"type": "complete_maps", "count": 3},
                }
            ]
        )
        mocker.patch("services.completions_service.StoreService", return_value=mock_store_service)

        mock_users_repo = mocker.AsyncMock()
        mock_users_repo.fetch_user.return_value = {"coalesced_name": "TestPlayer"}
        mocker.patch("services.completions_service.UsersRepository", return_value=mock_users_repo)

        mock_notifications = mocker.AsyncMock()

        await service._update_quest_progress_for_completion(
            user_id=123,
            map_code="ABC123",
            time=42.0,
            notifications=mock_notifications,
            headers={},
        )

        mock_notifications.create_and_dispatch.assert_called_once()
        call_kwargs = mock_notifications.create_and_dispatch.call_args.kwargs
        call_data = call_kwargs.get("data") or mock_notifications.create_and_dispatch.call_args[0][0]
        assert call_data.event_type == NotificationEventType.QUEST_COMPLETE.value
        assert call_data.metadata["quest_name"] == "Complete 3 Maps"
        assert call_data.metadata["quest_difficulty"] == "easy"
        assert call_data.metadata["coin_reward"] == 100
        assert call_data.metadata["xp_reward"] == 15

    async def test_rival_quest_dispatches_second_notification(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """Rival challenge quest dispatches QUEST_RIVAL_MENTION to rival user."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.fetch_map_metadata_by_code.return_value = {
            "map_id": 101,
            "difficulty": "Hard",
            "category": "Classic",
        }

        rival_user_id = 456789
        mock_store_repo = mocker.AsyncMock()
        mock_store_repo.get_medal_thresholds.return_value = None
        mocker.patch("services.completions_service.StoreRepository", return_value=mock_store_repo)
        mocker.patch("services.completions_service.LootboxRepository", return_value=mocker.AsyncMock())

        mock_store_service = mocker.Mock()
        mock_store_service.update_quest_progress = mocker.AsyncMock(
            return_value=[
                {
                    "name": "Rival Challenge",
                    "difficulty": "bounty",
                    "quest_id": None,
                    "progress_id": 99,
                    "coin_reward": 300,
                    "xp_reward": 50,
                    "requirements": {
                        "type": "beat_rival",
                        "map_id": 101,
                        "rival_user_id": rival_user_id,
                        "rival_time": 42.0,
                        "target_time": 42.0,
                    },
                }
            ]
        )
        mocker.patch("services.completions_service.StoreService", return_value=mock_store_service)

        mock_users_repo_instance = mocker.AsyncMock()
        mock_users_repo_instance.fetch_user.side_effect = [
            {"coalesced_name": "Completer"},     # completer lookup (fetched first)
            {"coalesced_name": "RivalPlayer"},   # rival lookup (fetched second)
        ]
        mocker.patch("services.completions_service.UsersRepository", return_value=mock_users_repo_instance)

        mock_notifications = mocker.AsyncMock()

        await service._update_quest_progress_for_completion(
            user_id=123,
            map_code="ABC123",
            time=40.0,
            notifications=mock_notifications,
            headers={},
        )

        # Should have 2 calls: QUEST_COMPLETE for completer + QUEST_RIVAL_MENTION for rival
        assert mock_notifications.create_and_dispatch.call_count == 2
        calls = mock_notifications.create_and_dispatch.call_args_list

        first_kwargs = calls[0].kwargs
        first_data = first_kwargs.get("data") or calls[0][0][0]
        assert first_data.event_type == NotificationEventType.QUEST_COMPLETE.value
        assert first_data.user_id == 123
        assert first_data.metadata["rival_user_id"] == rival_user_id

        second_kwargs = calls[1].kwargs
        second_data = second_kwargs.get("data") or calls[1][0][0]
        assert second_data.event_type == NotificationEventType.QUEST_RIVAL_MENTION.value
        assert second_data.user_id == rival_user_id

    async def test_non_rival_quest_fetches_completer_display_name(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """completer_display_name is fetched even for non-rival quests."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.fetch_map_metadata_by_code.return_value = {
            "map_id": 101,
            "difficulty": "Hard",
            "category": "Classic",
        }

        mock_store_repo = mocker.AsyncMock()
        mock_store_repo.get_medal_thresholds.return_value = None
        mocker.patch("services.completions_service.StoreRepository", return_value=mock_store_repo)
        mocker.patch("services.completions_service.LootboxRepository", return_value=mocker.AsyncMock())

        mock_store_service = mocker.Mock()
        mock_store_service.update_quest_progress = mocker.AsyncMock(
            return_value=[
                {
                    "name": "Complete 3 Maps",
                    "difficulty": "easy",
                    "progress_id": 42,
                    "coin_reward": 100,
                    "xp_reward": 15,
                    "requirements": {"type": "complete_maps", "count": 3},
                }
            ]
        )
        mocker.patch("services.completions_service.StoreService", return_value=mock_store_service)

        mock_users_repo = mocker.AsyncMock()
        mock_users_repo.fetch_user.return_value = {"coalesced_name": "TestPlayer"}
        mocker.patch("services.completions_service.UsersRepository", return_value=mock_users_repo)

        mock_notifications = mocker.AsyncMock()

        await service._update_quest_progress_for_completion(
            user_id=123,
            map_code="ABC123",
            time=42.0,
            notifications=mock_notifications,
            headers={},
        )

        # completer_display_name should be in metadata
        call_kwargs = mock_notifications.create_and_dispatch.call_args.kwargs
        call_data = call_kwargs.get("data") or mock_notifications.create_and_dispatch.call_args[0][0]
        assert call_data.metadata["completer_display_name"] == "TestPlayer"

    async def test_metadata_includes_bounty_type_and_map_code(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """Metadata includes bounty_type, map_code, and completion_time for bounty quests."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.fetch_map_metadata_by_code.return_value = {
            "map_id": 101,
            "difficulty": "Hard",
            "category": "Classic",
        }

        mock_store_repo = mocker.AsyncMock()
        mock_store_repo.get_medal_thresholds.return_value = None
        mocker.patch("services.completions_service.StoreRepository", return_value=mock_store_repo)
        mocker.patch("services.completions_service.LootboxRepository", return_value=mocker.AsyncMock())

        mock_store_service = mocker.Mock()
        mock_store_service.update_quest_progress = mocker.AsyncMock(
            return_value=[
                {
                    "name": "Explore New Territory",
                    "description": "Complete ABC123",
                    "difficulty": "bounty",
                    "progress_id": 42,
                    "coin_reward": 300,
                    "xp_reward": 50,
                    "bounty_type": "gap_filling",
                    "requirements": {"type": "complete_map", "map_id": 101},
                }
            ]
        )
        mocker.patch("services.completions_service.StoreService", return_value=mock_store_service)

        mock_users_repo = mocker.AsyncMock()
        mock_users_repo.fetch_user.return_value = {"coalesced_name": "TestPlayer"}
        mocker.patch("services.completions_service.UsersRepository", return_value=mock_users_repo)

        mock_notifications = mocker.AsyncMock()

        await service._update_quest_progress_for_completion(
            user_id=123,
            map_code="ABC123",
            time=83.45,
            notifications=mock_notifications,
            headers={},
        )

        call_kwargs = mock_notifications.create_and_dispatch.call_args.kwargs
        call_data = call_kwargs.get("data") or mock_notifications.create_and_dispatch.call_args[0][0]
        assert call_data.metadata["bounty_type"] == "gap_filling"
        assert call_data.metadata["map_code"] == "ABC123"

    async def test_rival_challenge_body_includes_times(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """Rival challenge body includes rival_time -> completion_time format."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.fetch_map_metadata_by_code.return_value = {
            "map_id": 101,
            "difficulty": "Hard",
            "category": "Classic",
        }

        mock_store_repo = mocker.AsyncMock()
        mock_store_repo.get_medal_thresholds.return_value = None
        mocker.patch("services.completions_service.StoreRepository", return_value=mock_store_repo)
        mocker.patch("services.completions_service.LootboxRepository", return_value=mocker.AsyncMock())

        rival_user_id = 456789
        mock_store_service = mocker.Mock()
        mock_store_service.update_quest_progress = mocker.AsyncMock(
            return_value=[
                {
                    "name": "Rival Challenge",
                    "description": "Beat RivalPlayer's time on ABC123",
                    "difficulty": "bounty",
                    "progress_id": 99,
                    "coin_reward": 300,
                    "xp_reward": 50,
                    "bounty_type": "rival_challenge",
                    "requirements": {
                        "type": "beat_rival",
                        "map_id": 101,
                        "rival_user_id": rival_user_id,
                        "rival_time": 45.0,
                        "target_time": 45.0,
                    },
                }
            ]
        )
        mocker.patch("services.completions_service.StoreService", return_value=mock_store_service)

        mock_users_repo = mocker.AsyncMock()
        mock_users_repo.fetch_user.side_effect = [
            {"coalesced_name": "Completer"},     # completer lookup (fetched first)
            {"coalesced_name": "RivalPlayer"},   # rival lookup (fetched second)
        ]
        mocker.patch("services.completions_service.UsersRepository", return_value=mock_users_repo)

        mock_notifications = mocker.AsyncMock()

        await service._update_quest_progress_for_completion(
            user_id=123,
            map_code="ABC123",
            time=40.50,
            notifications=mock_notifications,
            headers={},
        )

        calls = mock_notifications.create_and_dispatch.call_args_list
        first_data = calls[0].kwargs.get("data") or calls[0][0][0]
        assert "beat RivalPlayer's time on ABC123" in first_data.body
        assert "45.00s" in first_data.body
        assert "40.50s" in first_data.body
        assert first_data.metadata["completion_time"] == 40.50
        assert first_data.metadata["rival_time"] == 45.0

    async def test_personal_improvement_body_includes_times(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """Personal improvement body includes target_time -> completion_time format."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.fetch_map_metadata_by_code.return_value = {
            "map_id": 101,
            "difficulty": "Hard",
            "category": "Classic",
        }

        mock_store_repo = mocker.AsyncMock()
        mock_store_repo.get_medal_thresholds.return_value = None
        mocker.patch("services.completions_service.StoreRepository", return_value=mock_store_repo)
        mocker.patch("services.completions_service.LootboxRepository", return_value=mocker.AsyncMock())

        mock_store_service = mocker.Mock()
        mock_store_service.update_quest_progress = mocker.AsyncMock(
            return_value=[
                {
                    "name": "Beat Your Best",
                    "description": "Improve your time on ABC123",
                    "difficulty": "bounty",
                    "progress_id": 77,
                    "coin_reward": 300,
                    "xp_reward": 50,
                    "bounty_type": "personal_improvement",
                    "requirements": {
                        "type": "beat_time",
                        "map_id": 101,
                        "target_time": 90.0,
                    },
                }
            ]
        )
        mocker.patch("services.completions_service.StoreService", return_value=mock_store_service)

        mock_users_repo = mocker.AsyncMock()
        mock_users_repo.fetch_user.return_value = {"coalesced_name": "TestPlayer"}
        mocker.patch("services.completions_service.UsersRepository", return_value=mock_users_repo)

        mock_notifications = mocker.AsyncMock()

        await service._update_quest_progress_for_completion(
            user_id=123,
            map_code="ABC123",
            time=83.45,
            notifications=mock_notifications,
            headers={},
        )

        call_kwargs = mock_notifications.create_and_dispatch.call_args.kwargs
        call_data = call_kwargs.get("data") or mock_notifications.create_and_dispatch.call_args[0][0]
        assert "improved their time on ABC123" in call_data.body
        assert "90.00s" in call_data.body
        assert "83.45s" in call_data.body
        assert call_data.metadata["completion_time"] == 83.45
        assert call_data.metadata["target_time"] == 90.0

    async def test_gap_filling_body_includes_map_code(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """Gap filling body uses map_code."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.fetch_map_metadata_by_code.return_value = {
            "map_id": 101,
            "difficulty": "Hard",
            "category": "Classic",
        }

        mock_store_repo = mocker.AsyncMock()
        mock_store_repo.get_medal_thresholds.return_value = None
        mocker.patch("services.completions_service.StoreRepository", return_value=mock_store_repo)
        mocker.patch("services.completions_service.LootboxRepository", return_value=mocker.AsyncMock())

        mock_store_service = mocker.Mock()
        mock_store_service.update_quest_progress = mocker.AsyncMock(
            return_value=[
                {
                    "name": "Explore New Territory",
                    "description": "Complete ABC123",
                    "difficulty": "bounty",
                    "progress_id": 42,
                    "coin_reward": 300,
                    "xp_reward": 50,
                    "bounty_type": "gap_filling",
                    "requirements": {"type": "complete_map", "map_id": 101},
                }
            ]
        )
        mocker.patch("services.completions_service.StoreService", return_value=mock_store_service)

        mock_users_repo = mocker.AsyncMock()
        mock_users_repo.fetch_user.return_value = {"coalesced_name": "TestPlayer"}
        mocker.patch("services.completions_service.UsersRepository", return_value=mock_users_repo)

        mock_notifications = mocker.AsyncMock()

        await service._update_quest_progress_for_completion(
            user_id=123,
            map_code="ABC123",
            time=42.0,
            notifications=mock_notifications,
            headers={},
        )

        call_kwargs = mock_notifications.create_and_dispatch.call_args.kwargs
        call_data = call_kwargs.get("data") or mock_notifications.create_and_dispatch.call_args[0][0]
        assert "completed ABC123" in call_data.body
        assert "300 coins" in call_data.body

    async def test_global_quest_body_includes_description(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """Global quest (no bounty_type) body includes quest description."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.fetch_map_metadata_by_code.return_value = {
            "map_id": 101,
            "difficulty": "Hard",
            "category": "Classic",
        }

        mock_store_repo = mocker.AsyncMock()
        mock_store_repo.get_medal_thresholds.return_value = None
        mocker.patch("services.completions_service.StoreRepository", return_value=mock_store_repo)
        mocker.patch("services.completions_service.LootboxRepository", return_value=mocker.AsyncMock())

        mock_store_service = mocker.Mock()
        mock_store_service.update_quest_progress = mocker.AsyncMock(
            return_value=[
                {
                    "name": "Complete 5 Hard Maps",
                    "description": "Complete 5 maps rated Hard or above",
                    "difficulty": "medium",
                    "progress_id": 10,
                    "coin_reward": 200,
                    "xp_reward": 30,
                    "requirements": {"type": "complete_maps", "count": 5, "min_difficulty": "Hard"},
                }
            ]
        )
        mocker.patch("services.completions_service.StoreService", return_value=mock_store_service)

        mock_users_repo = mocker.AsyncMock()
        mock_users_repo.fetch_user.return_value = {"coalesced_name": "TestPlayer"}
        mocker.patch("services.completions_service.UsersRepository", return_value=mock_users_repo)

        mock_notifications = mocker.AsyncMock()

        await service._update_quest_progress_for_completion(
            user_id=123,
            map_code="ABC123",
            time=42.0,
            notifications=mock_notifications,
            headers={},
        )

        call_kwargs = mock_notifications.create_and_dispatch.call_args.kwargs
        call_data = call_kwargs.get("data") or mock_notifications.create_and_dispatch.call_args[0][0]
        assert "completed 'Complete 5 Hard Maps'" in call_data.body
        assert "Complete 5 maps rated Hard or above" in call_data.body


class TestCompletionsServiceModerateCompletion:
    """Test moderate_completion orchestration."""

    async def test_moderate_completion_not_found(
        self, mock_pool, mock_state, mock_completions_repo
    ):
        """Raises CompletionNotFoundError if completion doesn't exist."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.fetch_completion_for_moderation.return_value = None

        data = CompletionModerateRequest(moderated_by=123456789)

        with pytest.raises(CompletionNotFoundError):
            await service.moderate_completion(1, data)

    async def test_moderate_completion_time_change_with_notification(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """Time change triggers notification."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.fetch_completion_for_moderation.return_value = {
            "user_id": 123456789,
            "code": "ABC123",
            "old_time": 45.0,
            "old_verified": True,
        }

        mock_notification_service = mocker.AsyncMock()
        mock_headers = mocker.Mock()

        data = CompletionModerateRequest(
            moderated_by=999999999,
            time=40.0,
            time_change_reason="Timer was incorrectly read",
        )

        await service.moderate_completion(
            1, data, notification_service=mock_notification_service, headers=mock_headers
        )

        # Verify time was updated
        mock_completions_repo.update_completion_time.assert_called_once_with(1, 40.0)

        # Verify notification was sent
        mock_notification_service.create_and_dispatch.assert_called_once()
        call_args = mock_notification_service.create_and_dispatch.call_args
        notification_data = call_args[0][0]
        assert "45.0s" in notification_data.body
        assert "40.0s" in notification_data.body
        assert "Timer was incorrectly read" in notification_data.body

    async def test_moderate_completion_verified_change_to_verified(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """Verification change to verified triggers notification."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        service._update_quest_progress_for_completion = mocker.AsyncMock()

        mock_completions_repo.fetch_completion_for_moderation.return_value = {
            "user_id": 123456789,
            "code": "ABC123",
            "old_time": 45.0,
            "old_verified": False,
        }

        mock_notification_service = mocker.AsyncMock()
        mock_headers = mocker.Mock()

        data = CompletionModerateRequest(
            moderated_by=999999999,
            verified=True,
        )

        await service.moderate_completion(
            1, data, notification_service=mock_notification_service, headers=mock_headers
        )

        # Verify verification was updated
        mock_completions_repo.update_completion_verified.assert_called_once_with(1, True)

        # Verify notification was sent
        mock_notification_service.create_and_dispatch.assert_called_once()
        call_args = mock_notification_service.create_and_dispatch.call_args
        notification_data = call_args[0][0]
        assert "verified by a moderator" in notification_data.body

    async def test_moderate_completion_verified_change_to_unverified(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """Verification change to unverified triggers notification with reason."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        service._revert_quest_progress_for_completion = mocker.AsyncMock()

        mock_completions_repo.fetch_completion_for_moderation.return_value = {
            "user_id": 123456789,
            "code": "ABC123",
            "old_time": 45.0,
            "old_verified": True,
        }

        mock_notification_service = mocker.AsyncMock()
        mock_headers = mocker.Mock()

        data = CompletionModerateRequest(
            moderated_by=999999999,
            verified=False,
            verification_reason="Screenshot appears edited",
        )

        await service.moderate_completion(
            1, data, notification_service=mock_notification_service, headers=mock_headers
        )

        # Verify verification was updated
        mock_completions_repo.update_completion_verified.assert_called_once_with(1, False)

        # Verify notification includes reason
        mock_notification_service.create_and_dispatch.assert_called_once()
        call_args = mock_notification_service.create_and_dispatch.call_args
        notification_data = call_args[0][0]
        assert "unverified by a moderator" in notification_data.body
        assert "Screenshot appears edited" in notification_data.body

    async def test_moderate_completion_unverified_reverts_quest_progress(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """Unverifying via moderation should revert quest progress."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.fetch_completion_for_moderation.return_value = {
            "user_id": 123456789,
            "code": "ABC123",
            "old_time": 45.0,
            "old_verified": True,
        }
        mock_completions_repo.fetch_map_metadata_by_code.return_value = {
            "map_id": 10,
            "difficulty": "Hard",
            "category": "Speedrun",
        }
        mock_completions_repo.fetch_verified_times_for_user_map.return_value = []

        mock_store_repo = mocker.AsyncMock()
        mock_store_repo.get_medal_thresholds.return_value = {
            "gold": 30,
            "silver": 40,
            "bronze": 50,
        }
        mocker.patch("services.completions_service.StoreRepository", return_value=mock_store_repo)
        mocker.patch("services.completions_service.LootboxRepository", return_value=mocker.AsyncMock())

        mock_store_service = mocker.Mock()
        mock_store_service.revert_quest_progress = mocker.AsyncMock()
        mocker.patch("services.completions_service.StoreService", return_value=mock_store_service)

        data = CompletionModerateRequest(
            moderated_by=999999999,
            verified=False,
            verification_reason="Invalid proof",
        )

        await service.moderate_completion(1, data)

        mock_store_service.revert_quest_progress.assert_called_once_with(
            user_id=123456789,
            event_type="completion",
            event_data={
                "map_id": 10,
                "difficulty": "Hard",
                "category": "Speedrun",
                "time": 45.0,
            },
            remaining_times=[],
            remaining_medals=[],
        )

    async def test_moderate_completion_mark_suspicious(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """Marking as suspicious creates flag and sends notification."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.fetch_completion_for_moderation.return_value = {
            "user_id": 123456789,
            "code": "ABC123",
            "old_time": 45.0,
            "old_verified": False,
        }
        mock_completions_repo.check_suspicious_flag_exists.return_value = False

        mock_notification_service = mocker.AsyncMock()
        mock_headers = mocker.Mock()

        data = CompletionModerateRequest(
            moderated_by=999999999,
            mark_suspicious=True,
            suspicious_context="Multiple fast completions",
            suspicious_flag_type="cheating",
        )

        await service.moderate_completion(
            1, data, notification_service=mock_notification_service, headers=mock_headers
        )

        # Verify flag was created
        mock_completions_repo.insert_suspicious_flag_by_completion_id.assert_called_once()

        # Verify notification includes flag info
        mock_notification_service.create_and_dispatch.assert_called_once()
        call_args = mock_notification_service.create_and_dispatch.call_args
        notification_data = call_args[0][0]
        assert "flagged as suspicious" in notification_data.body
        assert "cheating" in notification_data.body
        assert "Multiple fast completions" in notification_data.body

    async def test_moderate_completion_unmark_suspicious(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """Unmarking suspicious removes flag and sends notification."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.fetch_completion_for_moderation.return_value = {
            "user_id": 123456789,
            "code": "ABC123",
            "old_time": 45.0,
            "old_verified": False,
        }
        mock_completions_repo.delete_suspicious_flag.return_value = 1  # 1 row deleted

        mock_notification_service = mocker.AsyncMock()
        mock_headers = mocker.Mock()

        data = CompletionModerateRequest(
            moderated_by=999999999,
            unmark_suspicious=True,
        )

        await service.moderate_completion(
            1, data, notification_service=mock_notification_service, headers=mock_headers
        )

        # Verify flag was deleted
        mock_completions_repo.delete_suspicious_flag.assert_called_once_with(1)

        # Verify notification
        mock_notification_service.create_and_dispatch.assert_called_once()
        call_args = mock_notification_service.create_and_dispatch.call_args
        notification_data = call_args[0][0]
        assert "suspicious flag" in notification_data.body
        assert "removed" in notification_data.body

    async def test_moderate_completion_multiple_changes(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """Multiple changes in one moderation action combine notifications."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.fetch_completion_for_moderation.return_value = {
            "user_id": 123456789,
            "code": "ABC123",
            "old_time": 45.0,
            "old_verified": False,
        }

        mock_notification_service = mocker.AsyncMock()
        mock_headers = mocker.Mock()

        data = CompletionModerateRequest(
            moderated_by=999999999,
            time=40.0,
            time_change_reason="Corrected",
            verified=True,
        )

        await service.moderate_completion(
            1, data, notification_service=mock_notification_service, headers=mock_headers
        )

        # Verify both updates occurred
        mock_completions_repo.update_completion_time.assert_called_once_with(1, 40.0)
        mock_completions_repo.update_completion_verified.assert_called_once_with(1, True)

        # Verify single notification with both messages
        mock_notification_service.create_and_dispatch.assert_called_once()
        call_args = mock_notification_service.create_and_dispatch.call_args
        notification_data = call_args[0][0]
        # Both messages should be in the body
        assert "45.0s" in notification_data.body
        assert "40.0s" in notification_data.body
        assert "verified by a moderator" in notification_data.body

    async def test_moderate_completion_no_notification_service(
        self, mock_pool, mock_state, mock_completions_repo
    ):
        """Moderation without notification service doesn't crash."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.fetch_completion_for_moderation.return_value = {
            "user_id": 123456789,
            "code": "ABC123",
            "old_time": 45.0,
            "old_verified": False,
        }

        data = CompletionModerateRequest(
            moderated_by=999999999,
            verified=True,
        )

        # Should not crash even without notification_service
        await service.moderate_completion(1, data, notification_service=None, headers=None)

        # Verify update still occurred
        mock_completions_repo.update_completion_verified.assert_called_once_with(1, True)


class TestCompletionsServiceSuspiciousFlags:
    """Test suspicious flag management."""

    pass


class TestCompletionsServiceUpvotes:
    """Test upvote submission logic."""

    pass


class TestCompletionsServiceQualityVotes:
    """Test quality vote logic."""

    pass


class TestCompletionsServiceErrorTranslation:
    """Test repository exception translation to domain exceptions."""

    async def test_submit_completion_unique_constraint_duplicate(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """UniqueConstraintViolationError during insert raises DuplicateCompletionError."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.check_map_exists.return_value = True
        mock_completions_repo.get_pending_verification.return_value = None
        mock_completions_repo.insert_completion.side_effect = UniqueConstraintViolationError(
            constraint_name="completions_user_id_code_key",
            table="completions.records",
        )

        data = CompletionCreateRequest(
            code="ABC123",
            user_id=123456789,
            time=40.0,
            screenshot="https://example.com/screenshot.png",
            video=None,
        )
        mock_request = mocker.Mock()
        mock_autocomplete = mocker.AsyncMock()
        mock_users = mocker.AsyncMock()

        with pytest.raises(DuplicateCompletionError):
            await service.submit_completion(data, mock_request, mock_autocomplete, mock_users)

    async def test_submit_completion_fk_violation_user_not_found(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """ForeignKeyViolationError on user_id raises CompletionNotFoundError."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.check_map_exists.return_value = True
        mock_completions_repo.get_pending_verification.return_value = None
        mock_completions_repo.insert_completion.side_effect = ForeignKeyViolationError(
            constraint_name="completions_user_id_fkey",
            table="completions.records",
        )

        data = CompletionCreateRequest(
            code="ABC123",
            user_id=999999999,
            time=40.0,
            screenshot="https://example.com/screenshot.png",
            video=None,
        )
        mock_request = mocker.Mock()
        mock_autocomplete = mocker.AsyncMock()
        mock_users = mocker.AsyncMock()

        with pytest.raises(CompletionNotFoundError):
            await service.submit_completion(data, mock_request, mock_autocomplete, mock_users)

    async def test_submit_completion_fk_violation_map_not_found(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """ForeignKeyViolationError on code raises MapNotFoundError."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.check_map_exists.return_value = True
        mock_completions_repo.get_pending_verification.return_value = None
        mock_completions_repo.insert_completion.side_effect = ForeignKeyViolationError(
            constraint_name="completions_code_fkey",
            table="completions.records",
        )

        data = CompletionCreateRequest(
            code="ABC123",
            user_id=123456789,
            time=40.0,
            screenshot="https://example.com/screenshot.png",
            video=None,
        )
        mock_request = mocker.Mock()
        mock_autocomplete = mocker.AsyncMock()
        mock_users = mocker.AsyncMock()

        with pytest.raises(MapNotFoundError):
            await service.submit_completion(data, mock_request, mock_autocomplete, mock_users)

    async def test_verify_completion_unique_constraint_duplicate(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """UniqueConstraintViolationError during verification raises DuplicateVerificationError."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.update_verification.side_effect = UniqueConstraintViolationError(
            constraint_name="verification_completion_id_key",
            table="completions.verification",
        )

        data = CompletionVerificationUpdateRequest(
            verified_by=123456789,
            verified=True,
            reason="Looks good",
        )
        mock_request = mocker.Mock()
        mock_request.headers = {}

        with pytest.raises(DuplicateVerificationError):
            await service.verify_completion(mock_request, 1, data)

    async def test_verify_completion_fk_violation_completion_not_found(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """ForeignKeyViolationError during verification raises CompletionNotFoundError."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.update_verification.side_effect = ForeignKeyViolationError(
            constraint_name="verification_completion_id_fkey",
            table="completions.verification",
        )

        data = CompletionVerificationUpdateRequest(
            verified_by=123456789,
            verified=True,
            reason="Looks good",
        )
        mock_request = mocker.Mock()
        mock_request.headers = {}

        with pytest.raises(CompletionNotFoundError):
            await service.verify_completion(mock_request, 999, data)

    async def test_set_suspicious_flags_unique_constraint_duplicate(
        self, mock_pool, mock_state, mock_completions_repo
    ):
        """UniqueConstraintViolationError during flag insert raises DuplicateFlagError."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.insert_suspicious_flag.side_effect = UniqueConstraintViolationError(
            constraint_name="suspicious_verification_id_key",
            table="completions.suspicious",
        )

        data = SuspiciousCompletionCreateRequest(
            message_id=12345,
            verification_id=100,
            context="Suspicious activity",
            flag_type="cheating",
            flagged_by=123456789,
        )

        with pytest.raises(DuplicateFlagError):
            await service.set_suspicious_flags(data)

    async def test_set_suspicious_flags_fk_violation_completion_not_found(
        self, mock_pool, mock_state, mock_completions_repo
    ):
        """ForeignKeyViolationError during flag insert raises CompletionNotFoundError."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.insert_suspicious_flag.side_effect = ForeignKeyViolationError(
            constraint_name="suspicious_verification_id_fkey",
            table="completions.suspicious",
        )

        data = SuspiciousCompletionCreateRequest(
            message_id=12345,
            verification_id=999,
            context="Suspicious activity",
            flag_type="cheating",
            flagged_by=123456789,
        )

        with pytest.raises(CompletionNotFoundError):
            await service.set_suspicious_flags(data)

    async def test_upvote_submission_unique_constraint_duplicate(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """UniqueConstraintViolationError during upvote raises DuplicateUpvoteError."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.insert_upvote.side_effect = UniqueConstraintViolationError(
            constraint_name="upvotes_user_id_message_id_key",
            table="completions.upvotes",
        )

        data = UpvoteCreateRequest(user_id=123456789, message_id=12345)
        mock_request = mocker.Mock()

        with pytest.raises(DuplicateUpvoteError):
            await service.upvote_submission(mock_request, data)

    async def test_upvote_submission_fk_violation_completion_not_found(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """ForeignKeyViolationError during upvote raises CompletionNotFoundError."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.insert_upvote.side_effect = ForeignKeyViolationError(
            constraint_name="upvotes_message_id_fkey",
            table="completions.upvotes",
        )

        data = UpvoteCreateRequest(user_id=123456789, message_id=99999)
        mock_request = mocker.Mock()

        with pytest.raises(CompletionNotFoundError):
            await service.upvote_submission(mock_request, data)

    async def test_quality_vote_fk_violation_map_not_found(
        self, mock_pool, mock_state, mock_completions_repo
    ):
        """ForeignKeyViolationError on map raises MapNotFoundError."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.upsert_quality_vote.side_effect = ForeignKeyViolationError(
            constraint_name="quality_votes_map_code_fkey",
            table="maps.quality_votes",
        )

        with pytest.raises(MapNotFoundError):
            await service.set_quality_vote_for_map_code("NOTFOUND", 123456789, 5)

    async def test_quality_vote_fk_violation_user_not_found(
        self, mock_pool, mock_state, mock_completions_repo
    ):
        """ForeignKeyViolationError on user raises CompletionNotFoundError."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.upsert_quality_vote.side_effect = ForeignKeyViolationError(
            constraint_name="quality_votes_user_id_fkey",
            table="maps.quality_votes",
        )

        with pytest.raises(CompletionNotFoundError):
            await service.set_quality_vote_for_map_code("ABC123", 999999999, 5)

    async def test_edit_completion_unique_constraint_duplicate(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """UniqueConstraintViolationError during edit raises DuplicateCompletionError."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.edit_completion.side_effect = UniqueConstraintViolationError(
            constraint_name="completions_user_id_code_key",
            table="completions.records",
        )

        data = CompletionPatchRequest(completion=True)
        mock_state_obj = mocker.Mock()

        with pytest.raises(DuplicateCompletionError):
            await service.edit_completion(mock_state_obj, 1, data)

    async def test_edit_completion_fk_violation_completion_not_found(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """ForeignKeyViolationError during edit raises CompletionNotFoundError."""
        service = CompletionsService(mock_pool, mock_state, mock_completions_repo)

        mock_completions_repo.edit_completion.side_effect = ForeignKeyViolationError(
            constraint_name="completions_id_fkey",
            table="completions.records",
        )

        data = CompletionPatchRequest(completion=True)
        mock_state_obj = mocker.Mock()

        with pytest.raises(CompletionNotFoundError):
            await service.edit_completion(mock_state_obj, 999, data)


# ---------------------------------------------------------------------------
# Phase 11-02: tournament auto-detect (D-01) + PB cross-write link (D-04) +
# D-07 slower-than-PB relax on tournament maps only.
# ---------------------------------------------------------------------------


def _tournament_service(mocker, mock_pool, mock_state, mock_completions_repo):
    """Build a CompletionsService wired with tournament dep mocks for 11-02."""
    tournament_repo = mocker.AsyncMock()
    tournament_repo.get_active_cycle_by_map_id.return_value = None
    reward_service = mocker.AsyncMock()
    reward_service.award_participation.return_value = []
    service = CompletionsService(
        mock_pool,
        mock_state,
        mock_completions_repo,
        tournament_repo=tournament_repo,
        tournament_reward_service=reward_service,
    )
    return service, tournament_repo, reward_service


class TestSubmitTournamentAutoDetect:
    """D-01/D-04: PB submit on an active cycle map links a tournament row."""

    async def test_pb_on_cycle_map_creates_linked_tournament_row(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """PB on the active cycle map inserts core + tournament rows and links them."""
        service, tournament_repo, _ = _tournament_service(
            mocker, mock_pool, mock_state, mock_completions_repo
        )
        mock_completions_repo.get_pending_verification.return_value = None
        mock_completions_repo.fetch_map_metadata_by_code.return_value = {"map_id": 777}
        mock_completions_repo.insert_completion.return_value = 5001
        service.get_suspicious_flags = mocker.AsyncMock(return_value=[])
        service.publish_message = mocker.AsyncMock(return_value={"job_id": "j"})
        tournament_repo.get_active_cycle_by_map_id.return_value = {
            "id": 42,
            "category_id": 3,
            "map_id": 777,
            "status": "active",
        }
        tournament_repo.create_tournament_completion.return_value = {"id": 9001}

        data = CompletionCreateRequest(
            user_id=123,
            code="ABC123",
            time=8.0,
            screenshot="https://example.com/s.png",
            video="https://example.com/v.mp4",
        )
        mock_request = mocker.Mock()
        mock_request.headers = {}

        await service.submit_completion(data, mock_request, mocker.AsyncMock(), mocker.AsyncMock())

        tournament_repo.get_active_cycle_by_map_id.assert_awaited()
        tournament_repo.create_tournament_completion.assert_awaited_once()
        mock_completions_repo.set_completion_tournament_link.assert_awaited_once()
        args = mock_completions_repo.set_completion_tournament_link.await_args
        assert args.args[0] == 5001
        assert args.args[1] == 9001

    async def test_pb_on_non_cycle_map_creates_no_tournament_row(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """PB on a non-cycle map behaves exactly as before (no tournament row)."""
        service, tournament_repo, _ = _tournament_service(
            mocker, mock_pool, mock_state, mock_completions_repo
        )
        mock_completions_repo.get_pending_verification.return_value = None
        mock_completions_repo.fetch_map_metadata_by_code.return_value = {"map_id": 777}
        mock_completions_repo.insert_completion.return_value = 5001
        service.get_suspicious_flags = mocker.AsyncMock(return_value=[])
        service.publish_message = mocker.AsyncMock(return_value={"job_id": "j"})
        tournament_repo.get_active_cycle_by_map_id.return_value = None

        data = CompletionCreateRequest(
            user_id=123,
            code="ABC123",
            time=8.0,
            screenshot="https://example.com/s.png",
            video="https://example.com/v.mp4",
        )
        mock_request = mocker.Mock()
        mock_request.headers = {}

        await service.submit_completion(data, mock_request, mocker.AsyncMock(), mocker.AsyncMock())

        tournament_repo.create_tournament_completion.assert_not_awaited()
        mock_completions_repo.set_completion_tournament_link.assert_not_awaited()


class TestSubmitTournamentSlowerRelax:
    """D-07: slower-than-PB run relaxed ONLY on tournament maps."""

    async def test_slower_on_cycle_map_records_tournament_row_no_core(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """A slower run on the cycle map: 0017 trigger fires, no core row, tournament row made."""
        from asyncpg.exceptions import CheckViolationError

        service, tournament_repo, _ = _tournament_service(
            mocker, mock_pool, mock_state, mock_completions_repo
        )
        mock_completions_repo.get_pending_verification.return_value = None
        mock_completions_repo.fetch_map_metadata_by_code.return_value = {"map_id": 777}
        mock_completions_repo.insert_completion.side_effect = CheckViolationError("speed trigger")
        service.get_suspicious_flags = mocker.AsyncMock(return_value=[])
        tournament_repo.get_active_cycle_by_map_id.return_value = {
            "id": 42,
            "category_id": 3,
            "map_id": 777,
            "status": "active",
        }
        tournament_repo.create_tournament_completion.return_value = {"id": 9002}

        data = CompletionCreateRequest(
            user_id=123,
            code="ABC123",
            time=99.0,
            screenshot="https://example.com/s.png",
            video=None,
        )
        mock_request = mocker.Mock()
        mock_request.headers = {}

        # Must NOT raise (D-07).
        await service.submit_completion(data, mock_request, mocker.AsyncMock(), mocker.AsyncMock())

        tournament_repo.create_tournament_completion.assert_awaited_once()
        mock_completions_repo.set_completion_tournament_link.assert_not_awaited()

    async def test_slower_on_non_cycle_map_propagates_check_violation(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """D-07 guard: slower run on a non-tournament map re-raises (preserves HTTP 400)."""
        from asyncpg.exceptions import CheckViolationError

        service, tournament_repo, _ = _tournament_service(
            mocker, mock_pool, mock_state, mock_completions_repo
        )
        mock_completions_repo.get_pending_verification.return_value = None
        mock_completions_repo.fetch_map_metadata_by_code.return_value = {"map_id": 777}
        mock_completions_repo.insert_completion.side_effect = CheckViolationError("speed trigger")
        tournament_repo.get_active_cycle_by_map_id.return_value = None

        data = CompletionCreateRequest(
            user_id=123,
            code="ABC123",
            time=99.0,
            screenshot="https://example.com/s.png",
            video=None,
        )
        mock_request = mocker.Mock()
        mock_request.headers = {}

        with pytest.raises(CheckViolationError):
            await service.submit_completion(data, mock_request, mocker.AsyncMock(), mocker.AsyncMock())
        tournament_repo.create_tournament_completion.assert_not_awaited()

    async def test_unique_violation_still_propagates_as_duplicate(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """P7: a genuine UniqueViolation from insert_completion is NOT swallowed by the relax."""
        service, tournament_repo, _ = _tournament_service(
            mocker, mock_pool, mock_state, mock_completions_repo
        )
        mock_completions_repo.get_pending_verification.return_value = None
        mock_completions_repo.fetch_map_metadata_by_code.return_value = {"map_id": 777}
        mock_completions_repo.insert_completion.side_effect = UniqueConstraintViolationError(
            "uq", "core.completions", "dup"
        )
        tournament_repo.get_active_cycle_by_map_id.return_value = {
            "id": 42,
            "category_id": 3,
            "map_id": 777,
            "status": "active",
        }

        data = CompletionCreateRequest(
            user_id=123,
            code="ABC123",
            time=8.0,
            screenshot="https://example.com/s.png",
            video=None,
        )
        mock_request = mocker.Mock()
        mock_request.headers = {}

        with pytest.raises(DuplicateCompletionError):
            await service.submit_completion(data, mock_request, mocker.AsyncMock(), mocker.AsyncMock())


# ---------------------------------------------------------------------------
# Phase 11-02 Task 2: verify_completion tournament side-effect (D-04a).
# ---------------------------------------------------------------------------


class TestVerifyCompletionTournamentSideEffect:
    """D-04a: verifying a linked PB completion flips the tournament row + XP."""

    async def test_verify_propagates_to_linked_tournament_row(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """Verify on a PB-linked cycle completion sets tournament verified + awards XP."""
        service, tournament_repo, reward_service = _tournament_service(
            mocker, mock_pool, mock_state, mock_completions_repo
        )
        # old_verified=False flips this run False->True, which also runs the
        # quest-progress branch; stub that helper so the test isolates tournament
        # propagation rather than the unrelated quest/medal/lootbox chain.
        mocker.patch.object(service, "_update_quest_progress_for_completion", mocker.AsyncMock())
        conn = mocker.AsyncMock()
        mock_completions_repo.check_completion_exists.return_value = True
        mock_completions_repo.fetch_completion_for_moderation.return_value = {
            "user_id": 123,
            "code": "ABC123",
            "old_time": 8.0,
            "old_verified": False,
            "tournament_completion_id": 9001,
        }
        mock_completions_repo.fetch_map_metadata_by_code.return_value = {"map_id": 777}
        # Propagation resolves the cycle from the completion's own cycle_id
        # (UI4-FINALIZING-PROPAGATION); finalizing locks in that a non-active cycle
        # still propagates.
        tournament_repo.fetch_tournament_completion.return_value = {
            "id": 9001,
            "cycle_id": 42,
            "user_id": 123,
            "time": 8.0,
            "status": "pending",
        }
        tournament_repo.fetch_cycle.return_value = {
            "id": 42,
            "category_id": 3,
            "map_id": 777,
            "status": "finalizing",
        }
        tournament_repo.set_tournament_verified.return_value = {
            "id": 9001,
            "cycle_id": 42,
            "user_id": 123,
            "time": 8.0,
        }
        reward_service.award_participation.return_value = ["xp-event"]
        service.publish_message = mocker.AsyncMock(return_value={"job_id": "j"})

        data = CompletionVerificationUpdateRequest(verified=True, verified_by=456, reason=None)
        mock_request = mocker.Mock()
        mock_request.headers = {}

        await service.verify_completion(mock_request, 5001, data, conn=conn)

        tournament_repo.set_tournament_verified.assert_awaited_once_with(9001, verified=True, conn=conn)
        reward_service.award_participation.assert_awaited_once()
        reward_service.publish_xp_events.assert_awaited_once_with(["xp-event"])
        tournament_repo.get_active_cycle_by_map_id.assert_not_awaited()
        tournament_publishes = [
            c
            for c in service.publish_message.call_args_list
            if c.kwargs.get("routing_key") == "api.tournament.verification.changed"
        ]
        assert len(tournament_publishes) == 1
        assert tournament_publishes[0].kwargs["idempotency_key"] == "tournament:verify:9001"

    async def test_verify_no_tournament_link_no_side_effect(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """A core completion with no tournament link triggers no side-effect."""
        service, tournament_repo, reward_service = _tournament_service(
            mocker, mock_pool, mock_state, mock_completions_repo
        )
        conn = mocker.AsyncMock()
        mock_completions_repo.check_completion_exists.return_value = True
        mock_completions_repo.fetch_completion_for_moderation.return_value = {
            "user_id": 123,
            "code": "ABC123",
            "old_time": 8.0,
            "old_verified": False,
            "tournament_completion_id": None,
        }
        service.publish_message = mocker.AsyncMock(return_value={"job_id": "j"})

        data = CompletionVerificationUpdateRequest(verified=True, verified_by=456, reason=None)
        mock_request = mocker.Mock()
        mock_request.headers = {}

        await service.verify_completion(mock_request, 5001, data, conn=conn)

        tournament_repo.set_tournament_verified.assert_not_awaited()
        reward_service.award_participation.assert_not_awaited()

    async def test_verify_on_non_cycle_map_no_side_effect(
        self, mock_pool, mock_state, mock_completions_repo, mocker
    ):
        """A linked row that no longer resolves to a cycle triggers no side-effect.

        Propagation now resolves the cycle from the completion's own cycle_id
        (fetch_tournament_completion -> fetch_cycle, UI4-FINALIZING-PROPAGATION).
        When fetch_tournament_completion returns None (row gone), the closure
        no-ops: no set_tournament_verified, no award_participation.
        """
        service, tournament_repo, reward_service = _tournament_service(
            mocker, mock_pool, mock_state, mock_completions_repo
        )
        # old_verified=False flips this run False->True, which also runs the
        # quest-progress branch; stub that helper so the test isolates the
        # no-side-effect assertion rather than the unrelated quest chain.
        mocker.patch.object(service, "_update_quest_progress_for_completion", mocker.AsyncMock())
        conn = mocker.AsyncMock()
        mock_completions_repo.check_completion_exists.return_value = True
        mock_completions_repo.fetch_completion_for_moderation.return_value = {
            "user_id": 123,
            "code": "ABC123",
            "old_time": 8.0,
            "old_verified": False,
            "tournament_completion_id": 9001,
        }
        mock_completions_repo.fetch_map_metadata_by_code.return_value = {"map_id": 777}
        # The linked tournament row no longer resolves -> propagation no-ops.
        tournament_repo.fetch_tournament_completion.return_value = None
        service.publish_message = mocker.AsyncMock(return_value={"job_id": "j"})

        data = CompletionVerificationUpdateRequest(verified=True, verified_by=456, reason=None)
        mock_request = mocker.Mock()
        mock_request.headers = {}

        await service.verify_completion(mock_request, 5001, data, conn=conn)

        tournament_repo.set_tournament_verified.assert_not_awaited()
        reward_service.award_participation.assert_not_awaited()
        # Propagation no longer consults the active-only map lookup.
        tournament_repo.get_active_cycle_by_map_id.assert_not_awaited()
