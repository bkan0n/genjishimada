"""Unit tests for TournamentService map selection logic."""

import pytest

from genjishimada_sdk.tournaments import TournamentChooseMapRequest, TournamentCompletionCreateRequest
from services.exceptions.tournaments import (
    CategoryNotFoundError,
    CycleNotActiveError,
    CycleNotFoundError,
    MapNotEligibleError,
    NoEligibleMapsError,
    PendingCycleAlreadyExistsError,
    PendingCycleNotFoundError,
    SlowerTimeError,
)
from services.tournament_service import TournamentService

pytestmark = [pytest.mark.domain_tournaments]


# ---------------------------------------------------------------------------
# Helpers -- dict factories for mock return values
# ---------------------------------------------------------------------------

_config = lambda **kw: {"blacklist_weeks": 4, **kw}
_category = lambda **kw: {"id": 1, "name": "Test", "difficulties": ["Easy"], **kw}
_map = lambda **kw: {"id": 10, "code": "ABC12", "map_name": "TestMap", "difficulty": "Easy", **kw}
_completion = lambda **kw: {
    "id": 1,
    "cycle_id": 1,
    "user_id": 100,
    "map_id": 10,
    "time": 42.5,
    "screenshot": "https://example.com/s.png",
    "video": None,
    "verified": False,
    "completion": False,
    "inserted_at": "2026-01-01T00:00:00",
    **kw,
}
_cycle = lambda **kw: {
    "id": 1,
    "category_id": 1,
    "map_id": 10,
    "status": "active",
    "started_at": "2026-01-01T00:00:00",
    "ended_at": None,
    "created_at": "2026-01-01T00:00:00",
    **kw,
}
_leaderboard_entry = lambda **kw: {
    "rank": 1,
    "user_id": 100,
    "name": "TestUser",
    "time": 42.5,
    "verified": False,
    "completion": False,
    **kw,
}
_pending = lambda **kw: {
    "id": 100,
    "category_id": 1,
    "map_id": 10,
    "map_code": "ABC12",
    "map_name": "TestMap",
    "map_difficulty": "Easy",
    "status": "pending",
    "started_at": None,
    "ended_at": None,
    "created_at": "2026-01-01T00:00:00",
    **kw,
}


class TestSelectMap:
    """Tests for TournamentService.select_map."""

    async def test_select_map_happy_path(self, mock_pool, mock_state, mock_tournament_repo):
        """Happy path: selects a random eligible map and creates pending cycle."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_pending_cycle.side_effect = [None, _pending()]
        mock_tournament_repo.fetch_config.return_value = _config()
        mock_tournament_repo.fetch_category.return_value = _category()
        mock_tournament_repo.fetch_eligible_maps.return_value = [_map()]
        mock_tournament_repo.create_cycle.return_value = {"id": 100, "category_id": 1, "map_id": 10, "status": "pending"}

        result = await service.select_map(1)

        assert result.map_code == "ABC12"
        mock_tournament_repo.fetch_eligible_maps.assert_called_once()
        call_args = mock_tournament_repo.fetch_eligible_maps.call_args
        assert call_args.args[0] == ["Easy"]
        assert call_args.args[1] == 4

    async def test_select_map_pending_already_exists(self, mock_pool, mock_state, mock_tournament_repo):
        """Raises PendingCycleAlreadyExistsError when a pending cycle exists."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_pending_cycle.return_value = _pending()

        with pytest.raises(PendingCycleAlreadyExistsError):
            await service.select_map(1)

    async def test_select_map_category_not_found(self, mock_pool, mock_state, mock_tournament_repo):
        """Raises CategoryNotFoundError when category does not exist."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_pending_cycle.return_value = None
        mock_tournament_repo.fetch_config.return_value = _config()
        mock_tournament_repo.fetch_category.return_value = None

        with pytest.raises(CategoryNotFoundError):
            await service.select_map(1)

    async def test_select_map_pool_exhausted_lru_fallback(self, mock_pool, mock_state, mock_tournament_repo):
        """Falls back to LRU map when eligible pool is exhausted."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_pending_cycle.side_effect = [None, _pending()]
        mock_tournament_repo.fetch_config.return_value = _config()
        mock_tournament_repo.fetch_category.return_value = _category()
        mock_tournament_repo.fetch_eligible_maps.return_value = []
        mock_tournament_repo.fetch_least_recently_used_map.return_value = _map()
        mock_tournament_repo.create_cycle.return_value = {"id": 100, "category_id": 1, "map_id": 10, "status": "pending"}

        result = await service.select_map(1)

        assert result.map_code == "ABC12"
        mock_tournament_repo.fetch_least_recently_used_map.assert_called_once()

    async def test_select_map_no_eligible_maps(self, mock_pool, mock_state, mock_tournament_repo):
        """Raises NoEligibleMapsError when both pool and LRU fallback fail."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_pending_cycle.return_value = None
        mock_tournament_repo.fetch_config.return_value = _config()
        mock_tournament_repo.fetch_category.return_value = _category()
        mock_tournament_repo.fetch_eligible_maps.return_value = []
        mock_tournament_repo.fetch_least_recently_used_map.return_value = None

        with pytest.raises(NoEligibleMapsError):
            await service.select_map(1)


class TestRerollMap:
    """Tests for TournamentService.reroll_map."""

    async def test_reroll_happy_path(self, mock_pool, mock_state, mock_tournament_repo):
        """Deletes existing pending cycle and creates new one excluding old map."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        old_pending = _pending(id=100, map_id=10)
        new_pending = _pending(id=101, map_id=20, map_code="DEF34")

        mock_tournament_repo.fetch_category.return_value = _category()
        mock_tournament_repo.fetch_pending_cycle.side_effect = [old_pending, new_pending]
        mock_tournament_repo.delete_cycle.return_value = True
        mock_tournament_repo.fetch_config.return_value = _config()
        mock_tournament_repo.fetch_eligible_maps.return_value = [_map(id=20, code="DEF34")]
        mock_tournament_repo.create_cycle.return_value = {"id": 101, "category_id": 1, "map_id": 20, "status": "pending"}

        result = await service.reroll_map(1)

        assert result.map_code == "DEF34"
        mock_tournament_repo.delete_cycle.assert_called_once_with(100, conn=mock_tournament_repo.delete_cycle.call_args.kwargs["conn"])
        call_kwargs = mock_tournament_repo.fetch_eligible_maps.call_args.kwargs
        assert call_kwargs["exclude_map_ids"] == [10]

    async def test_reroll_no_pending_raises(self, mock_pool, mock_state, mock_tournament_repo):
        """Raises PendingCycleNotFoundError when no pending cycle exists."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_category.return_value = _category()
        mock_tournament_repo.fetch_pending_cycle.return_value = None

        with pytest.raises(PendingCycleNotFoundError):
            await service.reroll_map(1)


class TestChooseMap:
    """Tests for TournamentService.choose_map."""

    async def test_choose_map_happy_path(self, mock_pool, mock_state, mock_tournament_repo):
        """Creates pending cycle with the explicitly chosen map."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_category.return_value = _category(difficulties=["Easy"])
        mock_tournament_repo.fetch_map_by_code.return_value = _map(difficulty="Easy")
        mock_tournament_repo.fetch_pending_cycle.side_effect = [None, _pending()]
        mock_tournament_repo.create_cycle.return_value = {"id": 100, "category_id": 1, "map_id": 10, "status": "pending"}

        result = await service.choose_map(1, TournamentChooseMapRequest(map_code="ABC12"))

        assert result.map_code == "ABC12"

    async def test_choose_map_not_found(self, mock_pool, mock_state, mock_tournament_repo):
        """Raises MapNotEligibleError when map code does not exist."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_category.return_value = _category()
        mock_tournament_repo.fetch_map_by_code.return_value = None

        with pytest.raises(MapNotEligibleError):
            await service.choose_map(1, TournamentChooseMapRequest(map_code="ZZZZZ"))

    async def test_choose_map_difficulty_mismatch(self, mock_pool, mock_state, mock_tournament_repo):
        """Raises MapNotEligibleError when map difficulty does not match category."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_category.return_value = _category(difficulties=["Hard"])
        mock_tournament_repo.fetch_map_by_code.return_value = _map(difficulty="Easy")

        with pytest.raises(MapNotEligibleError):
            await service.choose_map(1, TournamentChooseMapRequest(map_code="ABC12"))

    async def test_choose_map_replaces_existing_pending(self, mock_pool, mock_state, mock_tournament_repo):
        """Deletes existing pending cycle before creating new one."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        existing_pending = _pending(id=100)
        new_pending = _pending(id=101, map_id=20, map_code="DEF34")

        mock_tournament_repo.fetch_category.return_value = _category(difficulties=["Easy"])
        mock_tournament_repo.fetch_map_by_code.return_value = _map(id=20, code="DEF34", difficulty="Easy")
        mock_tournament_repo.fetch_pending_cycle.side_effect = [existing_pending, new_pending]
        mock_tournament_repo.delete_cycle.return_value = True
        mock_tournament_repo.create_cycle.return_value = {"id": 101, "category_id": 1, "map_id": 20, "status": "pending"}

        result = await service.choose_map(1, TournamentChooseMapRequest(map_code="DEF34"))

        assert result.map_code == "DEF34"
        mock_tournament_repo.delete_cycle.assert_called_once_with(100, conn=mock_tournament_repo.delete_cycle.call_args.kwargs["conn"])


class TestGetNextCycle:
    """Tests for TournamentService.get_next_cycle."""

    async def test_get_next_cycle_happy_path(self, mock_pool, mock_state, mock_tournament_repo):
        """Returns pending cycle with map details."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_category.return_value = _category()
        mock_tournament_repo.fetch_pending_cycle.return_value = _pending()

        result = await service.get_next_cycle(1)

        assert result.map_code == "ABC12"
        assert result.status == "pending"
        assert result.category_id == 1

    async def test_get_next_cycle_category_not_found(self, mock_pool, mock_state, mock_tournament_repo):
        """Raises CategoryNotFoundError when category does not exist."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_category.return_value = None

        with pytest.raises(CategoryNotFoundError):
            await service.get_next_cycle(1)

    async def test_get_next_cycle_no_pending(self, mock_pool, mock_state, mock_tournament_repo):
        """Raises PendingCycleNotFoundError when no pending cycle exists."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_category.return_value = _category()
        mock_tournament_repo.fetch_pending_cycle.return_value = None

        with pytest.raises(PendingCycleNotFoundError):
            await service.get_next_cycle(1)


class TestSubmitCompletion:
    """Tests for TournamentService.submit_completion."""

    async def test_submit_happy_path(self, mock_pool, mock_state, mock_tournament_repo):
        """First submission for cycle succeeds and triggers cross-write."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_cycle.return_value = _cycle()
        mock_tournament_repo.fetch_user_completion.return_value = None
        mock_tournament_repo.create_tournament_completion.return_value = _completion()
        mock_tournament_repo.cross_write_to_core.return_value = 999

        result = await service.submit_completion(
            1, TournamentCompletionCreateRequest(user_id=100, time=42.5, screenshot="https://example.com/s.png")
        )

        assert result.id == 1
        mock_tournament_repo.create_tournament_completion.assert_called_once()
        mock_tournament_repo.cross_write_to_core.assert_called_once()

    async def test_submit_faster_replaces(self, mock_pool, mock_state, mock_tournament_repo):
        """Faster time than existing submission succeeds."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_cycle.return_value = _cycle()
        mock_tournament_repo.fetch_user_completion.return_value = _completion(time=50.0)
        mock_tournament_repo.create_tournament_completion.return_value = _completion(time=42.5)
        mock_tournament_repo.cross_write_to_core.return_value = 999

        result = await service.submit_completion(
            1, TournamentCompletionCreateRequest(user_id=100, time=42.5, screenshot="https://example.com/s.png")
        )

        assert result.time == 42.5
        mock_tournament_repo.create_tournament_completion.assert_called_once()

    async def test_rejects_slower_time(self, mock_pool, mock_state, mock_tournament_repo):
        """Slower time than current best raises SlowerTimeError."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_cycle.return_value = _cycle()
        mock_tournament_repo.fetch_user_completion.return_value = _completion(time=30.0)

        with pytest.raises(SlowerTimeError):
            await service.submit_completion(
                1, TournamentCompletionCreateRequest(user_id=100, time=35.0, screenshot="https://example.com/s.png")
            )

    async def test_rejects_equal_time(self, mock_pool, mock_state, mock_tournament_repo):
        """Equal time to current best raises SlowerTimeError (not faster)."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_cycle.return_value = _cycle()
        mock_tournament_repo.fetch_user_completion.return_value = _completion(time=42.5)

        with pytest.raises(SlowerTimeError):
            await service.submit_completion(
                1, TournamentCompletionCreateRequest(user_id=100, time=42.5, screenshot="https://example.com/s.png")
            )

    async def test_cycle_not_active(self, mock_pool, mock_state, mock_tournament_repo):
        """Submission to non-active cycle raises CycleNotActiveError."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_cycle.return_value = _cycle(status="completed")

        with pytest.raises(CycleNotActiveError):
            await service.submit_completion(
                1, TournamentCompletionCreateRequest(user_id=100, time=42.5, screenshot="https://example.com/s.png")
            )

    async def test_cycle_not_found(self, mock_pool, mock_state, mock_tournament_repo):
        """Submission to nonexistent cycle raises CycleNotFoundError."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_cycle.return_value = None

        with pytest.raises(CycleNotFoundError):
            await service.submit_completion(
                1, TournamentCompletionCreateRequest(user_id=100, time=42.5, screenshot="https://example.com/s.png")
            )


class TestGetLeaderboard:
    """Tests for TournamentService.get_leaderboard."""

    async def test_returns_ranked_entries(self, mock_pool, mock_state, mock_tournament_repo):
        """Returns ranked leaderboard entries in order."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_leaderboard.return_value = [
            _leaderboard_entry(rank=1, time=30.0),
            _leaderboard_entry(rank=2, user_id=200, name="User2", time=45.0),
        ]

        result = await service.get_leaderboard(1)

        assert len(result) == 2
        assert result[0].rank == 1
        assert result[1].rank == 2

    async def test_empty_leaderboard(self, mock_pool, mock_state, mock_tournament_repo):
        """Empty leaderboard returns empty list."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_leaderboard.return_value = []

        result = await service.get_leaderboard(1)

        assert result == []


class TestListCycles:
    """Tests for TournamentService.list_cycles."""

    async def test_returns_paginated_cycles(self, mock_pool, mock_state, mock_tournament_repo):
        """Returns paginated cycle list with winner info."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_cycles.return_value = (
            1,
            [
                {
                    "id": 1,
                    "category_id": 1,
                    "map_id": 10,
                    "map_code": "ABC12",
                    "map_name": "TestMap",
                    "map_difficulty": "Easy",
                    "status": "completed",
                    "started_at": "2026-01-01T00:00:00",
                    "ended_at": "2026-01-08T00:00:00",
                    "created_at": "2026-01-01T00:00:00",
                    "winner_name": "Champion",
                    "winner_user_id": 100,
                },
            ],
        )

        result = await service.list_cycles(status="completed")

        assert result.total == 1
        assert len(result.cycles) == 1
        assert result.cycles[0].winner_name == "Champion"

    async def test_passes_filters_to_repo(self, mock_pool, mock_state, mock_tournament_repo):
        """Passes filter parameters through to repository."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_cycles.return_value = (0, [])

        await service.list_cycles(status="active", category_id=3, limit=10, offset=5)

        mock_tournament_repo.fetch_cycles.assert_called_once_with(
            status="active",
            category_id=3,
            limit=10,
            offset=5,
        )
