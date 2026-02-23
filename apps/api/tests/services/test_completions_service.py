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
                        "target_time": 42.0,
                    },
                }
            ]
        )
        mocker.patch("services.completions_service.StoreService", return_value=mock_store_service)

        mock_users_repo_instance = mocker.AsyncMock()
        mock_users_repo_instance.fetch_user.return_value = {"coalesced_name": "RivalPlayer"}
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
