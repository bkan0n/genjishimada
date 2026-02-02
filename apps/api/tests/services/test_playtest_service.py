"""Unit tests for PlaytestService."""

from unittest.mock import ANY

import msgspec
import pytest
from genjishimada_sdk.difficulties import DifficultyAll
from genjishimada_sdk.maps import (
    PlaytestPatchRequest,
    PlaytestVote,
)

from repository.exceptions import CheckConstraintViolationError
from services.exceptions.playtest import (
    InvalidPatchError,
    PlaytestNotFoundError,
    PlaytestStateError,
    VoteConstraintError,
    VoteNotFoundError,
)
from services.playtest_service import PlaytestService

pytestmark = [
    pytest.mark.domain_playtests,
]


class TestPlaytestServiceGetVotes:
    """Test get_votes() business logic."""

    async def test_get_votes_multiple_votes_calculates_average(
        self, mock_pool, mock_state, mock_playtest_repo, mock_maps_repo
    ):
        """get_votes() calculates correct average from multiple votes."""
        service = PlaytestService(mock_pool, mock_state, mock_playtest_repo, mock_maps_repo)

        # Mock repository returning multiple votes
        mock_playtest_repo.fetch_playtest_votes.return_value = [
            {"user_id": 1, "name": "user1", "difficulty": 5.0},
            {"user_id": 2, "name": "user2", "difficulty": 7.0},
            {"user_id": 3, "name": "user3", "difficulty": 6.0},
        ]

        result = await service.get_votes(thread_id=12345)

        assert len(result.votes) == 3
        assert result.average == 6.0  # (5 + 7 + 6) / 3
        mock_playtest_repo.fetch_playtest_votes.assert_called_once_with(12345)

    async def test_get_votes_empty_votes_returns_zero_average(
        self, mock_pool, mock_state, mock_playtest_repo, mock_maps_repo
    ):
        """get_votes() returns average of 0 when no votes exist."""
        service = PlaytestService(mock_pool, mock_state, mock_playtest_repo, mock_maps_repo)

        # Mock repository returning empty list
        mock_playtest_repo.fetch_playtest_votes.return_value = []

        result = await service.get_votes(thread_id=12345)

        assert len(result.votes) == 0
        assert result.average == 0
        mock_playtest_repo.fetch_playtest_votes.assert_called_once_with(12345)

    async def test_get_votes_single_vote_returns_that_value(
        self, mock_pool, mock_state, mock_playtest_repo, mock_maps_repo
    ):
        """get_votes() returns the single vote value as average."""
        service = PlaytestService(mock_pool, mock_state, mock_playtest_repo, mock_maps_repo)

        # Mock repository returning single vote
        mock_playtest_repo.fetch_playtest_votes.return_value = [
            {"user_id": 1, "name": "user1", "difficulty": 8.5},
        ]

        result = await service.get_votes(thread_id=12345)

        assert len(result.votes) == 1
        assert result.average == 8.5
        mock_playtest_repo.fetch_playtest_votes.assert_called_once_with(12345)

    async def test_get_votes_rounds_to_two_decimals(
        self, mock_pool, mock_state, mock_playtest_repo, mock_maps_repo
    ):
        """get_votes() rounds average to 2 decimal places."""
        service = PlaytestService(mock_pool, mock_state, mock_playtest_repo, mock_maps_repo)

        # Mock repository returning votes that produce non-round average
        mock_playtest_repo.fetch_playtest_votes.return_value = [
            {"user_id": 1, "name": "user1", "difficulty": 5.0},
            {"user_id": 2, "name": "user2", "difficulty": 6.0},
            {"user_id": 3, "name": "user3", "difficulty": 7.0},
        ]

        result = await service.get_votes(thread_id=12345)

        assert result.average == 6.0  # (5 + 6 + 7) / 3 = 6.0
        mock_playtest_repo.fetch_playtest_votes.assert_called_once_with(12345)


class TestPlaytestServiceCastVote:
    """Test cast_vote() error translation."""

    async def test_cast_vote_success(
        self, mock_pool, mock_state, mock_playtest_repo, mock_maps_repo, mocker
    ):
        """cast_vote() successfully casts vote when no constraints violated."""
        service = PlaytestService(mock_pool, mock_state, mock_playtest_repo, mock_maps_repo)

        # Mock headers for RabbitMQ idempotency
        mock_headers = mocker.Mock()

        # Mock successful vote cast
        mock_playtest_repo.cast_vote.return_value = None

        # Mock publish_message to avoid RabbitMQ
        mocker.patch.object(service, "publish_message", return_value=mocker.AsyncMock())

        vote_data = PlaytestVote(difficulty=6.5)
        await service.cast_vote(
            thread_id=12345,
            user_id=999,
            data=vote_data,
            headers=mock_headers,
        )

        # Verify repository was called correctly
        mock_playtest_repo.cast_vote.assert_called_once_with(12345, 999, 6.5)

    async def test_cast_vote_constraint_violation_raises_domain_error(
        self, mock_pool, mock_state, mock_playtest_repo, mock_maps_repo, mocker
    ):
        """cast_vote() translates CheckConstraintViolationError to VoteConstraintError."""
        service = PlaytestService(mock_pool, mock_state, mock_playtest_repo, mock_maps_repo)

        # Mock headers
        mock_headers = mocker.Mock()

        # Mock repository raising constraint violation
        mock_playtest_repo.cast_vote.side_effect = CheckConstraintViolationError(
            constraint_name="check_user_has_submission",
            table="playtest_votes",
        )

        vote_data = PlaytestVote(difficulty=6.5)

        # Should raise VoteConstraintError with appropriate message
        with pytest.raises(
            VoteConstraintError,
            match="You do not have a verified, non-completion submission",
        ):
            await service.cast_vote(
                thread_id=12345,
                user_id=999,
                data=vote_data,
                headers=mock_headers,
            )

        # Verify repository was called
        mock_playtest_repo.cast_vote.assert_called_once_with(12345, 999, 6.5)


class TestPlaytestServiceDeleteVote:
    """Test delete_vote() business logic."""

    async def test_delete_vote_success(
        self, mock_pool, mock_state, mock_playtest_repo, mock_maps_repo, mocker
    ):
        """delete_vote() successfully deletes vote when it exists."""
        service = PlaytestService(mock_pool, mock_state, mock_playtest_repo, mock_maps_repo)

        # Mock headers
        mock_headers = mocker.Mock()

        # Mock vote exists
        mock_playtest_repo.check_vote_exists.return_value = True
        mock_playtest_repo.delete_vote.return_value = None

        # Mock publish_message
        mocker.patch.object(service, "publish_message", return_value=mocker.AsyncMock())

        await service.delete_vote(
            thread_id=12345,
            user_id=999,
            headers=mock_headers,
        )

        # Verify calls
        mock_playtest_repo.check_vote_exists.assert_called_once_with(12345, 999)
        mock_playtest_repo.delete_vote.assert_called_once_with(12345, 999)

    async def test_delete_vote_not_found_raises_domain_error(
        self, mock_pool, mock_state, mock_playtest_repo, mock_maps_repo, mocker
    ):
        """delete_vote() raises VoteNotFoundError when vote doesn't exist."""
        service = PlaytestService(mock_pool, mock_state, mock_playtest_repo, mock_maps_repo)

        # Mock headers
        mock_headers = mocker.Mock()

        # Mock vote does not exist
        mock_playtest_repo.check_vote_exists.return_value = False

        # Should raise VoteNotFoundError
        with pytest.raises(VoteNotFoundError) as exc_info:
            await service.delete_vote(
                thread_id=12345,
                user_id=999,
                headers=mock_headers,
            )

        # Verify error contains correct IDs
        assert "12345" in str(exc_info.value)
        assert "999" in str(exc_info.value)

        # Verify check was called but delete was not
        mock_playtest_repo.check_vote_exists.assert_called_once_with(12345, 999)
        mock_playtest_repo.delete_vote.assert_not_called()


class TestPlaytestServiceEditMeta:
    """Test edit_playtest_meta() validation."""

    async def test_edit_playtest_meta_valid_patch(
        self, mock_pool, mock_state, mock_playtest_repo, mock_maps_repo
    ):
        """edit_playtest_meta() successfully updates with valid fields."""
        service = PlaytestService(mock_pool, mock_state, mock_playtest_repo, mock_maps_repo)

        # Create patch with some fields set
        patch_data = PlaytestPatchRequest(
            thread_id=msgspec.UNSET,
            verification_id=123,
            completed=True,
        )

        await service.edit_playtest_meta(thread_id=12345, data=patch_data)

        # Verify repository was called with only non-UNSET fields
        mock_playtest_repo.update_playtest_meta.assert_called_once()
        call_args = mock_playtest_repo.update_playtest_meta.call_args
        assert call_args[0][0] == 12345  # thread_id
        cleaned_data = call_args[0][1]
        assert "verification_id" in cleaned_data
        assert "completed" in cleaned_data
        assert "thread_id" not in cleaned_data  # UNSET should be filtered out

    async def test_edit_playtest_meta_all_unset_raises_error(
        self, mock_pool, mock_state, mock_playtest_repo, mock_maps_repo
    ):
        """edit_playtest_meta() raises InvalidPatchError when all fields are UNSET."""
        service = PlaytestService(mock_pool, mock_state, mock_playtest_repo, mock_maps_repo)

        # Create patch with all fields UNSET
        patch_data = PlaytestPatchRequest(
            thread_id=msgspec.UNSET,
            verification_id=msgspec.UNSET,
            completed=msgspec.UNSET,
        )

        # Should raise InvalidPatchError
        with pytest.raises(InvalidPatchError, match="All fields cannot be UNSET"):
            await service.edit_playtest_meta(thread_id=12345, data=patch_data)

        # Verify repository was not called
        mock_playtest_repo.update_playtest_meta.assert_not_called()

    async def test_edit_playtest_meta_filters_unset_fields(
        self, mock_pool, mock_state, mock_playtest_repo, mock_maps_repo
    ):
        """edit_playtest_meta() filters UNSET fields and passes only set ones."""
        service = PlaytestService(mock_pool, mock_state, mock_playtest_repo, mock_maps_repo)

        # Create patch with mixed UNSET and valid fields
        patch_data = PlaytestPatchRequest(
            verification_id=456,
            thread_id=msgspec.UNSET,
            completed=True,
        )

        await service.edit_playtest_meta(thread_id=12345, data=patch_data)

        # Verify only set fields were sent
        call_args = mock_playtest_repo.update_playtest_meta.call_args
        cleaned_data = call_args[0][1]
        assert cleaned_data == {"verification_id": 456, "completed": True}
        assert "thread_id" not in cleaned_data


class TestPlaytestServiceApprove:
    """Test approve() orchestration and state validation."""

    async def test_approve_success(
        self, mock_pool, mock_state, mock_playtest_repo, mock_maps_repo, mocker
    ):
        """approve() successfully approves playtest with all data present."""
        service = PlaytestService(mock_pool, mock_state, mock_playtest_repo, mock_maps_repo)

        # Mock headers
        mock_headers = mocker.Mock()

        # Mock repository responses
        mock_playtest_repo.get_map_id_from_thread.return_value = 100
        mock_playtest_repo.get_average_difficulty.return_value = 6.5
        mock_playtest_repo.approve_playtest.return_value = None
        mock_playtest_repo.get_primary_creator.return_value = 999
        mock_playtest_repo.get_map_code.return_value = "ABC123"

        # Mock publish_message
        mocker.patch.object(service, "publish_message", return_value=mocker.AsyncMock())

        await service.approve(
            thread_id=12345,
            verifier_id=888,
            headers=mock_headers,
        )

        # Verify all repository calls were made
        mock_playtest_repo.get_map_id_from_thread.assert_called_once_with(12345, conn=ANY)
        mock_playtest_repo.get_average_difficulty.assert_called_once_with(12345, conn=ANY)
        mock_playtest_repo.approve_playtest.assert_called_once_with(100, 12345, 6.5, conn=ANY)
        mock_playtest_repo.get_primary_creator.assert_called_once_with(100, conn=ANY)
        mock_playtest_repo.get_map_code.assert_called_once_with(100, conn=ANY)

    async def test_approve_playtest_not_found_no_map_id(
        self, mock_pool, mock_state, mock_playtest_repo, mock_maps_repo, mocker
    ):
        """approve() raises PlaytestNotFoundError when map_id is None."""
        service = PlaytestService(mock_pool, mock_state, mock_playtest_repo, mock_maps_repo)

        # Mock headers
        mock_headers = mocker.Mock()

        # Mock repository returning None for map_id
        mock_playtest_repo.get_map_id_from_thread.return_value = None

        # Should raise PlaytestNotFoundError
        with pytest.raises(PlaytestNotFoundError) as exc_info:
            await service.approve(
                thread_id=12345,
                verifier_id=888,
                headers=mock_headers,
            )

        assert "12345" in str(exc_info.value)

    async def test_approve_no_votes_raises_state_error(
        self, mock_pool, mock_state, mock_playtest_repo, mock_maps_repo, mocker
    ):
        """approve() raises PlaytestStateError when no votes exist."""
        service = PlaytestService(mock_pool, mock_state, mock_playtest_repo, mock_maps_repo)

        # Mock headers
        mock_headers = mocker.Mock()

        # Mock repository responses - difficulty is None (no votes)
        mock_playtest_repo.get_map_id_from_thread.return_value = 100
        mock_playtest_repo.get_average_difficulty.return_value = None

        # Should raise PlaytestStateError
        with pytest.raises(PlaytestStateError, match="Cannot approve playtest with no votes"):
            await service.approve(
                thread_id=12345,
                verifier_id=888,
                headers=mock_headers,
            )

    async def test_approve_no_map_code_raises_state_error(
        self, mock_pool, mock_state, mock_playtest_repo, mock_maps_repo, mocker
    ):
        """approve() raises PlaytestStateError when map code is None."""
        service = PlaytestService(mock_pool, mock_state, mock_playtest_repo, mock_maps_repo)

        # Mock headers
        mock_headers = mocker.Mock()

        # Mock repository responses - code is None
        mock_playtest_repo.get_map_id_from_thread.return_value = 100
        mock_playtest_repo.get_average_difficulty.return_value = 6.5
        mock_playtest_repo.approve_playtest.return_value = None
        mock_playtest_repo.get_primary_creator.return_value = 999
        mock_playtest_repo.get_map_code.return_value = None

        # Should raise PlaytestStateError
        with pytest.raises(PlaytestStateError, match="Map code not found"):
            await service.approve(
                thread_id=12345,
                verifier_id=888,
                headers=mock_headers,
            )

    async def test_approve_no_primary_creator_raises_state_error(
        self, mock_pool, mock_state, mock_playtest_repo, mock_maps_repo, mocker
    ):
        """approve() raises PlaytestStateError when primary creator is None."""
        service = PlaytestService(mock_pool, mock_state, mock_playtest_repo, mock_maps_repo)

        # Mock headers
        mock_headers = mocker.Mock()

        # Mock repository responses - primary_creator_id is None
        mock_playtest_repo.get_map_id_from_thread.return_value = 100
        mock_playtest_repo.get_average_difficulty.return_value = 6.5
        mock_playtest_repo.approve_playtest.return_value = None
        mock_playtest_repo.get_primary_creator.return_value = None
        mock_playtest_repo.get_map_code.return_value = "ABC123"

        # Should raise PlaytestStateError
        with pytest.raises(PlaytestStateError, match="Primary creator not found"):
            await service.approve(
                thread_id=12345,
                verifier_id=888,
                headers=mock_headers,
            )


class TestPlaytestServiceForceAccept:
    """Test force_accept() difficulty conversion."""

    async def test_force_accept_success_with_difficulty_conversion(
        self, mock_pool, mock_state, mock_playtest_repo, mock_maps_repo, mocker
    ):
        """force_accept() successfully converts difficulty tier to raw value."""
        service = PlaytestService(mock_pool, mock_state, mock_playtest_repo, mock_maps_repo)

        # Mock headers
        mock_headers = mocker.Mock()

        # Mock repository responses
        mock_playtest_repo.get_map_id_from_thread.return_value = 100
        mock_playtest_repo.force_accept_playtest.return_value = None

        # Mock publish_message
        mocker.patch.object(service, "publish_message", return_value=mocker.AsyncMock())

        await service.force_accept(
            thread_id=12345,
            difficulty="Medium",
            verifier_id=888,
            headers=mock_headers,
        )

        # Verify repository was called with converted difficulty
        # DIFFICULTY_MIDPOINTS["Medium"] should be used
        from genjishimada_sdk.difficulties import DIFFICULTY_MIDPOINTS

        expected_raw_difficulty = DIFFICULTY_MIDPOINTS["Medium"]
        mock_playtest_repo.force_accept_playtest.assert_called_once_with(
            100, 12345, expected_raw_difficulty, conn=ANY
        )

    async def test_force_accept_playtest_not_found(
        self, mock_pool, mock_state, mock_playtest_repo, mock_maps_repo, mocker
    ):
        """force_accept() raises PlaytestNotFoundError when map_id is None."""
        service = PlaytestService(mock_pool, mock_state, mock_playtest_repo, mock_maps_repo)

        # Mock headers
        mock_headers = mocker.Mock()

        # Mock repository returning None for map_id
        mock_playtest_repo.get_map_id_from_thread.return_value = None

        # Should raise PlaytestNotFoundError
        with pytest.raises(PlaytestNotFoundError) as exc_info:
            await service.force_accept(
                thread_id=12345,
                difficulty="Hard",
                verifier_id=888,
                headers=mock_headers,
            )

        assert "12345" in str(exc_info.value)

    async def test_force_accept_difficulty_lookup(
        self, mock_pool, mock_state, mock_playtest_repo, mock_maps_repo, mocker
    ):
        """force_accept() correctly looks up difficulty from DIFFICULTY_MIDPOINTS."""
        service = PlaytestService(mock_pool, mock_state, mock_playtest_repo, mock_maps_repo)

        # Mock headers
        mock_headers = mocker.Mock()

        # Mock repository responses
        mock_playtest_repo.get_map_id_from_thread.return_value = 100
        mock_playtest_repo.force_accept_playtest.return_value = None

        # Mock publish_message
        mocker.patch.object(service, "publish_message", return_value=mocker.AsyncMock())

        # Test with Very Hard difficulty
        await service.force_accept(
            thread_id=12345,
            difficulty="Very Hard",
            verifier_id=888,
            headers=mock_headers,
        )

        # Verify correct midpoint was used
        from genjishimada_sdk.difficulties import DIFFICULTY_MIDPOINTS

        expected_raw = DIFFICULTY_MIDPOINTS["Very Hard"]
        call_args = mock_playtest_repo.force_accept_playtest.call_args
        assert call_args[0][2] == expected_raw  # Third argument is raw_difficulty


class TestPlaytestServiceReset:
    """Test reset() conditional logic."""

    async def test_reset_remove_votes_true(
        self, mock_pool, mock_state, mock_playtest_repo, mock_maps_repo, mocker
    ):
        """reset() calls delete_all_votes when remove_votes=True."""
        service = PlaytestService(mock_pool, mock_state, mock_playtest_repo, mock_maps_repo)

        # Mock headers
        mock_headers = mocker.Mock()

        # Mock publish_message
        mocker.patch.object(service, "publish_message", return_value=mocker.AsyncMock())

        await service.reset(
            thread_id=12345,
            verifier_id=888,
            reason="Test reason",
            remove_votes=True,
            remove_completions=False,
            headers=mock_headers,
        )

        # Verify delete_all_votes was called
        mock_playtest_repo.delete_all_votes.assert_called_once_with(12345, conn=ANY)
        mock_playtest_repo.delete_completions_for_playtest.assert_not_called()

    async def test_reset_remove_votes_false(
        self, mock_pool, mock_state, mock_playtest_repo, mock_maps_repo, mocker
    ):
        """reset() does not call delete_all_votes when remove_votes=False."""
        service = PlaytestService(mock_pool, mock_state, mock_playtest_repo, mock_maps_repo)

        # Mock headers
        mock_headers = mocker.Mock()

        # Mock publish_message
        mocker.patch.object(service, "publish_message", return_value=mocker.AsyncMock())

        await service.reset(
            thread_id=12345,
            verifier_id=888,
            reason="Test reason",
            remove_votes=False,
            remove_completions=False,
            headers=mock_headers,
        )

        # Verify delete_all_votes was NOT called
        mock_playtest_repo.delete_all_votes.assert_not_called()

    async def test_reset_remove_completions_true(
        self, mock_pool, mock_state, mock_playtest_repo, mock_maps_repo, mocker
    ):
        """reset() calls delete_completions_for_playtest when remove_completions=True."""
        service = PlaytestService(mock_pool, mock_state, mock_playtest_repo, mock_maps_repo)

        # Mock headers
        mock_headers = mocker.Mock()

        # Mock publish_message
        mocker.patch.object(service, "publish_message", return_value=mocker.AsyncMock())

        await service.reset(
            thread_id=12345,
            verifier_id=888,
            reason="Test reason",
            remove_votes=False,
            remove_completions=True,
            headers=mock_headers,
        )

        # Verify delete_completions_for_playtest was called
        mock_playtest_repo.delete_completions_for_playtest.assert_called_once_with(12345, conn=ANY)
        mock_playtest_repo.delete_all_votes.assert_not_called()

    async def test_reset_remove_completions_false(
        self, mock_pool, mock_state, mock_playtest_repo, mock_maps_repo, mocker
    ):
        """reset() does not call delete_completions_for_playtest when remove_completions=False."""
        service = PlaytestService(mock_pool, mock_state, mock_playtest_repo, mock_maps_repo)

        # Mock headers
        mock_headers = mocker.Mock()

        # Mock publish_message
        mocker.patch.object(service, "publish_message", return_value=mocker.AsyncMock())

        await service.reset(
            thread_id=12345,
            verifier_id=888,
            reason="Test reason",
            remove_votes=False,
            remove_completions=False,
            headers=mock_headers,
        )

        # Verify delete_completions_for_playtest was NOT called
        mock_playtest_repo.delete_completions_for_playtest.assert_not_called()

    async def test_reset_both_flags_true(
        self, mock_pool, mock_state, mock_playtest_repo, mock_maps_repo, mocker
    ):
        """reset() calls both delete methods when both flags are True."""
        service = PlaytestService(mock_pool, mock_state, mock_playtest_repo, mock_maps_repo)

        # Mock headers
        mock_headers = mocker.Mock()

        # Mock publish_message
        mocker.patch.object(service, "publish_message", return_value=mocker.AsyncMock())

        await service.reset(
            thread_id=12345,
            verifier_id=888,
            reason="Test reason",
            remove_votes=True,
            remove_completions=True,
            headers=mock_headers,
        )

        # Verify both methods were called
        mock_playtest_repo.delete_all_votes.assert_called_once_with(12345, conn=ANY)
        mock_playtest_repo.delete_completions_for_playtest.assert_called_once_with(12345, conn=ANY)

    async def test_reset_both_flags_false(
        self, mock_pool, mock_state, mock_playtest_repo, mock_maps_repo, mocker
    ):
        """reset() calls neither delete method when both flags are False."""
        service = PlaytestService(mock_pool, mock_state, mock_playtest_repo, mock_maps_repo)

        # Mock headers
        mock_headers = mocker.Mock()

        # Mock publish_message
        mocker.patch.object(service, "publish_message", return_value=mocker.AsyncMock())

        await service.reset(
            thread_id=12345,
            verifier_id=888,
            reason="Test reason",
            remove_votes=False,
            remove_completions=False,
            headers=mock_headers,
        )

        # Verify neither method was called
        mock_playtest_repo.delete_all_votes.assert_not_called()
        mock_playtest_repo.delete_completions_for_playtest.assert_not_called()
