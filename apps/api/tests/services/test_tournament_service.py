"""Unit tests for TournamentService map selection logic."""

import pytest

from genjishimada_sdk.tournaments import TournamentChooseMapRequest
from services.exceptions.tournaments import (
    CategoryNotFoundError,
    MapNotEligibleError,
    NoEligibleMapsError,
    PendingCycleAlreadyExistsError,
    PendingCycleNotFoundError,
)
from services.tournament_service import TournamentService

pytestmark = [pytest.mark.domain_tournaments]


# ---------------------------------------------------------------------------
# Helpers -- dict factories for mock return values
# ---------------------------------------------------------------------------

_config = lambda **kw: {"blacklist_weeks": 4, **kw}
_category = lambda **kw: {"id": 1, "name": "Test", "difficulties": ["Easy"], **kw}
_map = lambda **kw: {"id": 10, "code": "ABC12", "map_name": "TestMap", "difficulty": "Easy", **kw}
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
