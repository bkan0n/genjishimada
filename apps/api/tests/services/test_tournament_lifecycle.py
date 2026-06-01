"""Unit tests for TournamentService cycle lifecycle-control methods.

Covers bootstrap_cycle, set_transitions_paused, and set_debug_cycle_length
added in quick-task 260601-bhy. Mirrors the mock-based construction in
test_tournament_service.py (mock_pool / mock_state / mock_tournament_repo).
"""

import msgspec
import pytest

from genjishimada_sdk.tournaments import TournamentCycleStartedEvent
from services.exceptions.tournaments import (
    CategoryNotFoundError,
    CycleAlreadyLiveError,
    DebugRouteDisabledError,
    NoEligibleMapsError,
)
from services.tournament_service import TournamentService

pytestmark = [pytest.mark.domain_tournaments]


_config = lambda **kw: {"blacklist_weeks": 4, **kw}
_category = lambda **kw: {
    "id": 1,
    "name": "Test",
    "difficulties": ["Easy"],
    "cycle_frequency": "weekly",
    "debug_cycle_seconds": None,
    **kw,
}
_map = lambda **kw: {"id": 10, "code": "ABC12", "map_name": "TestMap", "difficulty": "Easy", **kw}
_active_cycle = lambda **kw: {
    "id": 100,
    "category_id": 1,
    "map_id": 10,
    "status": "active",
    "started_at": "2026-01-01T00:00:00+00:00",
    "ended_at": None,
    "created_at": "2026-01-01T00:00:00+00:00",
    **kw,
}


class TestBootstrapCycle:
    """Tests for TournamentService.bootstrap_cycle."""

    async def test_bootstrap_happy_path(self, mock_pool, mock_state, mock_tournament_repo):
        """Creates an active cycle and writes a cycle_started outbox row."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_category.return_value = _category()
        mock_tournament_repo.check_any_live_cycle.return_value = None
        mock_tournament_repo.fetch_config.return_value = _config()
        mock_tournament_repo.fetch_eligible_maps.return_value = [_map()]
        mock_tournament_repo.create_active_cycle.return_value = _active_cycle()
        mock_tournament_repo.create_pending_transition.return_value = {"id": 1}

        result = await service.bootstrap_cycle(1)

        assert result.status == "active"
        assert result.id == 100
        mock_tournament_repo.create_active_cycle.assert_called_once()

        # a cycle_started outbox row was written with a payload that round-trips
        mock_tournament_repo.create_pending_transition.assert_called_once()
        call = mock_tournament_repo.create_pending_transition.call_args
        assert call.args[1] == "cycle_started"
        payload = msgspec.json.decode(call.args[2].encode())
        event = msgspec.convert(payload, TournamentCycleStartedEvent)
        assert event.cycle_id == 100
        assert event.map_code == "ABC12"
        assert event.map_name == "TestMap"

    async def test_bootstrap_category_not_found(self, mock_pool, mock_state, mock_tournament_repo):
        """Raises CategoryNotFoundError when the category does not exist."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_category.return_value = None

        with pytest.raises(CategoryNotFoundError):
            await service.bootstrap_cycle(1)

    async def test_bootstrap_already_live(self, mock_pool, mock_state, mock_tournament_repo):
        """Raises CycleAlreadyLiveError when a live/pending cycle exists."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_category.return_value = _category()
        mock_tournament_repo.check_any_live_cycle.return_value = 55

        with pytest.raises(CycleAlreadyLiveError):
            await service.bootstrap_cycle(1)

    async def test_bootstrap_no_eligible_maps(self, mock_pool, mock_state, mock_tournament_repo):
        """Raises NoEligibleMapsError when no maps match and LRU fallback fails."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_category.return_value = _category()
        mock_tournament_repo.check_any_live_cycle.return_value = None
        mock_tournament_repo.fetch_config.return_value = _config()
        mock_tournament_repo.fetch_eligible_maps.return_value = []
        mock_tournament_repo.fetch_least_recently_used_map.return_value = None

        with pytest.raises(NoEligibleMapsError):
            await service.bootstrap_cycle(1)

    async def test_bootstrap_lru_fallback(self, mock_pool, mock_state, mock_tournament_repo):
        """Falls back to LRU map when the eligible pool is exhausted."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_category.return_value = _category()
        mock_tournament_repo.check_any_live_cycle.return_value = None
        mock_tournament_repo.fetch_config.return_value = _config()
        mock_tournament_repo.fetch_eligible_maps.return_value = []
        mock_tournament_repo.fetch_least_recently_used_map.return_value = _map()
        mock_tournament_repo.create_active_cycle.return_value = _active_cycle()
        mock_tournament_repo.create_pending_transition.return_value = {"id": 1}

        result = await service.bootstrap_cycle(1)

        assert result.status == "active"
        mock_tournament_repo.fetch_least_recently_used_map.assert_called_once()


class TestSetTransitionsPaused:
    """Tests for TournamentService.set_transitions_paused."""

    async def test_pause_then_resume_round_trip(self, mock_pool, mock_state, mock_tournament_repo):
        """Pausing then resuming returns the lifecycle state each time."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.set_category_paused.return_value = {
            "id": 1,
            "transitions_paused": True,
            "debug_cycle_seconds": None,
        }
        paused = await service.set_transitions_paused(1, True)
        assert paused.transitions_paused is True

        mock_tournament_repo.set_category_paused.return_value = {
            "id": 1,
            "transitions_paused": False,
            "debug_cycle_seconds": None,
        }
        resumed = await service.set_transitions_paused(1, False)
        assert resumed.transitions_paused is False

    async def test_missing_category_raises(self, mock_pool, mock_state, mock_tournament_repo):
        """Raises CategoryNotFoundError when the repo returns None."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.set_category_paused.return_value = None

        with pytest.raises(CategoryNotFoundError):
            await service.set_transitions_paused(999, True)


class TestSetDebugCycleLength:
    """Tests for TournamentService.set_debug_cycle_length."""

    async def test_set_and_clear(self, mock_pool, mock_state, mock_tournament_repo, monkeypatch):
        """Sets then clears the debug override in a non-production environment."""
        monkeypatch.setenv("APP_ENVIRONMENT", "local")
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.set_category_debug_cycle_seconds.return_value = {
            "id": 1,
            "transitions_paused": False,
            "debug_cycle_seconds": 30,
        }
        set_result = await service.set_debug_cycle_length(1, 30)
        assert set_result.debug_cycle_seconds == 30

        mock_tournament_repo.set_category_debug_cycle_seconds.return_value = {
            "id": 1,
            "transitions_paused": False,
            "debug_cycle_seconds": None,
        }
        cleared = await service.set_debug_cycle_length(1, None)
        assert cleared.debug_cycle_seconds is None

    async def test_missing_category_raises(self, mock_pool, mock_state, mock_tournament_repo, monkeypatch):
        """Raises CategoryNotFoundError when the repo returns None."""
        monkeypatch.setenv("APP_ENVIRONMENT", "local")
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.set_category_debug_cycle_seconds.return_value = None

        with pytest.raises(CategoryNotFoundError):
            await service.set_debug_cycle_length(999, 30)

    async def test_production_disabled(self, mock_pool, mock_state, mock_tournament_repo, monkeypatch):
        """Raises DebugRouteDisabledError when APP_ENVIRONMENT is production."""
        monkeypatch.setenv("APP_ENVIRONMENT", "production")
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        with pytest.raises(DebugRouteDisabledError):
            await service.set_debug_cycle_length(1, 30)
