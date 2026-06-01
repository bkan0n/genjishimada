"""Unit tests for TournamentService edition lifecycle-control methods.

Covers bootstrap_edition (grid-snapped, D-13a/D-08), the global pause/debug
config setters (D-03/D-12), and the fetch_active_edition wrapper (Plan 04
GET /editions/active depends on it). Mirrors the mock-based construction in
test_tournament_service.py (mock_pool / mock_state / mock_tournament_repo).
"""

import datetime as dt

import msgspec
import pytest

from genjishimada_sdk.tournaments import (
    TournamentCycleStartedEvent,
    TournamentRolloverEvent,
)
from services.exceptions.tournaments import (
    CycleAlreadyLiveError,
    DebugRouteDisabledError,
    NoEligibleMapsError,
)
from services.tournament_service import TournamentService

pytestmark = [pytest.mark.domain_tournaments]


# Monday 2026-01-05 00:00:00 UTC is the next-Monday grid boundary the repo
# next_grid_boundary() would return for an anchor of Monday 00:00 UTC when now()
# falls on the preceding Saturday. The service stores exactly what the repo
# returns; it never reads now() itself (D-08).
_NEXT_MONDAY = dt.datetime(2026, 1, 5, 0, 0, 0, tzinfo=dt.UTC)

_config = lambda **kw: {
    "blacklist_weeks": 4,
    "cadence": "weekly",
    "anchor_weekday": 1,
    "anchor_time": dt.time(0, 0),
    "anchor_tz": "UTC",
    "transitions_paused": False,
    "debug_cycle_seconds": None,
    **kw,
}
_lifecycle = lambda **kw: {
    "transitions_paused": False,
    "debug_cycle_seconds": None,
    **kw,
}
_category = lambda **kw: {
    "id": 1,
    "name": "Test",
    "difficulties": ["Easy"],
    "is_active": True,
    **kw,
}
_map = lambda **kw: {"id": 10, "code": "ABC12", "map_name": "TestMap", "difficulty": "Easy", **kw}
_edition = lambda **kw: {
    "id": 500,
    "started_at": _NEXT_MONDAY,
    "ends_at": _NEXT_MONDAY + dt.timedelta(days=7),
    "status": "active",
    "created_at": _NEXT_MONDAY,
    **kw,
}
_child_cycle = lambda **kw: {
    "id": 100,
    "edition_id": 500,
    "category_id": 1,
    "map_id": 10,
    "status": "active",
    "started_at": _NEXT_MONDAY,
    "ended_at": None,
    "created_at": _NEXT_MONDAY,
    **kw,
}


class TestBootstrapEdition:
    """Tests for TournamentService.bootstrap_edition (grid-snap, D-13a/D-08)."""

    async def test_bootstrap_grid_snaps_start_no_now(self, mock_pool, mock_state, mock_tournament_repo):
        """The edition started_at is the grid boundary the repo returned, not now()."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_active_edition.return_value = None
        mock_tournament_repo.fetch_config.return_value = _config()
        mock_tournament_repo.next_grid_boundary.return_value = _NEXT_MONDAY
        mock_tournament_repo.fetch_categories.return_value = [_category()]
        mock_tournament_repo.fetch_eligible_maps.return_value = [_map()]
        mock_tournament_repo.create_edition.return_value = _edition()
        mock_tournament_repo.create_cycle_for_edition.return_value = _child_cycle()
        mock_tournament_repo.create_pending_transition.return_value = {"id": 1}

        result = await service.bootstrap_edition()

        assert result.started_at == _NEXT_MONDAY
        # create_edition was called with the grid boundary as started_at and
        # started_at + period as ends_at -- NEVER now().
        call = mock_tournament_repo.create_edition.call_args
        started_arg = call.args[0] if call.args else call.kwargs["started_at"]
        ends_arg = call.args[1] if len(call.args) > 1 else call.kwargs["ends_at"]
        assert started_arg == _NEXT_MONDAY
        assert ends_arg == _NEXT_MONDAY + dt.timedelta(days=7)

    async def test_bootstrap_one_edition_one_cycle_per_active_category(
        self, mock_pool, mock_state, mock_tournament_repo
    ):
        """One edition + one child cycle per active category; child start == edition start."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        cat_a = _category(id=1, difficulties=["Easy"])
        cat_b = _category(id=2, difficulties=["Hard"])
        mock_tournament_repo.fetch_active_edition.return_value = None
        mock_tournament_repo.fetch_config.return_value = _config()
        mock_tournament_repo.next_grid_boundary.return_value = _NEXT_MONDAY
        mock_tournament_repo.fetch_categories.return_value = [cat_a, cat_b]
        mock_tournament_repo.fetch_eligible_maps.return_value = [_map()]
        mock_tournament_repo.create_edition.return_value = _edition()
        mock_tournament_repo.create_cycle_for_edition.side_effect = [
            _child_cycle(id=100, category_id=1),
            _child_cycle(id=101, category_id=2),
        ]
        mock_tournament_repo.create_pending_transition.return_value = {"id": 1}

        await service.bootstrap_edition()

        # Exactly one edition.
        mock_tournament_repo.create_edition.assert_called_once()
        # One child cycle per active category.
        assert mock_tournament_repo.create_cycle_for_edition.call_count == 2
        for c in mock_tournament_repo.create_cycle_for_edition.call_args_list:
            # started_at inherited from the edition (grid boundary), keyword or positional.
            started = c.kwargs.get("started_at", c.args[3] if len(c.args) > 3 else None)
            assert started == _NEXT_MONDAY

    async def test_bootstrap_ends_at_uses_debug_period(self, mock_pool, mock_state, mock_tournament_repo):
        """When debug_cycle_seconds is set, the period is that many seconds (debug wins)."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_active_edition.return_value = None
        mock_tournament_repo.fetch_config.return_value = _config(debug_cycle_seconds=30)
        mock_tournament_repo.next_grid_boundary.return_value = _NEXT_MONDAY
        mock_tournament_repo.fetch_categories.return_value = [_category()]
        mock_tournament_repo.fetch_eligible_maps.return_value = [_map()]
        mock_tournament_repo.create_edition.return_value = _edition(
            ends_at=_NEXT_MONDAY + dt.timedelta(seconds=30)
        )
        mock_tournament_repo.create_cycle_for_edition.return_value = _child_cycle()
        mock_tournament_repo.create_pending_transition.return_value = {"id": 1}

        await service.bootstrap_edition()

        call = mock_tournament_repo.create_edition.call_args
        ends_arg = call.args[1] if len(call.args) > 1 else call.kwargs["ends_at"]
        assert ends_arg == _NEXT_MONDAY + dt.timedelta(seconds=30)
        # next_grid_boundary received the debug period.
        gb_call = mock_tournament_repo.next_grid_boundary.call_args
        period = gb_call.kwargs.get("period", gb_call.args[-1] if gb_call.args else None)
        assert period == dt.timedelta(seconds=30)

    async def test_bootstrap_biweekly_period(self, mock_pool, mock_state, mock_tournament_repo):
        """Biweekly cadence yields a 14-day period."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_active_edition.return_value = None
        mock_tournament_repo.fetch_config.return_value = _config(cadence="biweekly")
        mock_tournament_repo.next_grid_boundary.return_value = _NEXT_MONDAY
        mock_tournament_repo.fetch_categories.return_value = [_category()]
        mock_tournament_repo.fetch_eligible_maps.return_value = [_map()]
        mock_tournament_repo.create_edition.return_value = _edition(
            ends_at=_NEXT_MONDAY + dt.timedelta(days=14)
        )
        mock_tournament_repo.create_cycle_for_edition.return_value = _child_cycle()
        mock_tournament_repo.create_pending_transition.return_value = {"id": 1}

        await service.bootstrap_edition()

        call = mock_tournament_repo.create_edition.call_args
        ends_arg = call.args[1] if len(call.args) > 1 else call.kwargs["ends_at"]
        assert ends_arg == _NEXT_MONDAY + dt.timedelta(days=14)

    async def test_bootstrap_writes_single_rollover_outbox_row(self, mock_pool, mock_state, mock_tournament_repo):
        """Bootstrap writes ONE edition_rollover row (start-only: results empty, started populated)."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_active_edition.return_value = None
        mock_tournament_repo.fetch_config.return_value = _config()
        mock_tournament_repo.next_grid_boundary.return_value = _NEXT_MONDAY
        mock_tournament_repo.fetch_categories.return_value = [_category()]
        mock_tournament_repo.fetch_eligible_maps.return_value = [_map()]
        mock_tournament_repo.create_edition.return_value = _edition()
        mock_tournament_repo.create_cycle_for_edition.return_value = _child_cycle()
        mock_tournament_repo.create_pending_transition.return_value = {"id": 1}

        await service.bootstrap_edition()

        mock_tournament_repo.create_pending_transition.assert_called_once()
        call = mock_tournament_repo.create_pending_transition.call_args
        # cycle_id is None for an edition_rollover row; event_type is edition_rollover.
        assert call.args[0] is None
        assert call.args[1] == "edition_rollover"
        assert call.kwargs.get("edition_id") == 500
        payload = msgspec.json.decode(call.args[2].encode())
        event = msgspec.convert(payload, TournamentRolloverEvent)
        assert event.edition_id == 500
        assert event.results == []  # start-only (bootstrap)
        assert len(event.started) == 1
        started = event.started[0]
        assert isinstance(started, TournamentCycleStartedEvent)
        assert started.cycle_id == 100
        assert started.started_at == _NEXT_MONDAY

    async def test_bootstrap_already_active_edition_raises(self, mock_pool, mock_state, mock_tournament_repo):
        """Raises CycleAlreadyLiveError when an active edition already exists (idempotency)."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_active_edition.return_value = _edition()

        with pytest.raises(CycleAlreadyLiveError):
            await service.bootstrap_edition()

    async def test_bootstrap_lru_fallback(self, mock_pool, mock_state, mock_tournament_repo):
        """Falls back to LRU map when the eligible pool is exhausted."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_active_edition.return_value = None
        mock_tournament_repo.fetch_config.return_value = _config()
        mock_tournament_repo.next_grid_boundary.return_value = _NEXT_MONDAY
        mock_tournament_repo.fetch_categories.return_value = [_category()]
        mock_tournament_repo.fetch_eligible_maps.return_value = []
        mock_tournament_repo.fetch_least_recently_used_map.return_value = _map()
        mock_tournament_repo.create_edition.return_value = _edition()
        mock_tournament_repo.create_cycle_for_edition.return_value = _child_cycle()
        mock_tournament_repo.create_pending_transition.return_value = {"id": 1}

        await service.bootstrap_edition()

        mock_tournament_repo.fetch_least_recently_used_map.assert_called_once()

    async def test_bootstrap_no_eligible_maps_raises(self, mock_pool, mock_state, mock_tournament_repo):
        """Raises NoEligibleMapsError when both pool and LRU fallback fail for a category."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_active_edition.return_value = None
        mock_tournament_repo.fetch_config.return_value = _config()
        mock_tournament_repo.next_grid_boundary.return_value = _NEXT_MONDAY
        mock_tournament_repo.fetch_categories.return_value = [_category()]
        mock_tournament_repo.fetch_eligible_maps.return_value = []
        mock_tournament_repo.fetch_least_recently_used_map.return_value = None

        with pytest.raises(NoEligibleMapsError):
            await service.bootstrap_edition()


class TestFetchActiveEdition:
    """Tests for TournamentService.fetch_active_edition (Plan 04 GET /editions/active)."""

    async def test_returns_edition_when_active(self, mock_pool, mock_state, mock_tournament_repo):
        """Returns a TournamentEditionResponse when an active edition exists."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_active_edition.return_value = _edition()

        result = await service.fetch_active_edition()

        assert result is not None
        assert result.id == 500
        assert result.started_at == _NEXT_MONDAY
        assert result.status == "active"

    async def test_returns_none_when_no_active_edition(self, mock_pool, mock_state, mock_tournament_repo):
        """Returns None when no active edition exists (route surfaces 404)."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.fetch_active_edition.return_value = None

        result = await service.fetch_active_edition()

        assert result is None


class TestSetTransitionsPaused:
    """Tests for TournamentService.set_transitions_paused (global, D-03/D-12)."""

    async def test_pause_then_resume_round_trip(self, mock_pool, mock_state, mock_tournament_repo):
        """Pausing mutates the GLOBAL config; resume does not itself create an edition (hiatus)."""
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.set_transitions_paused.return_value = _lifecycle(transitions_paused=True)
        paused = await service.set_transitions_paused(True)
        assert paused.transitions_paused is True
        mock_tournament_repo.set_transitions_paused.assert_called_with(True)
        # No per-category mutation occurred.
        mock_tournament_repo.set_category_paused.assert_not_called()

        mock_tournament_repo.set_transitions_paused.return_value = _lifecycle(transitions_paused=False)
        resumed = await service.set_transitions_paused(False)
        assert resumed.transitions_paused is False
        # Resume does NOT create an edition (D-12 hiatus: the grid cron/bootstrap does).
        mock_tournament_repo.create_edition.assert_not_called()


class TestSetDebugCycleLength:
    """Tests for TournamentService.set_debug_cycle_length (global, D-03)."""

    async def test_set_and_clear(self, mock_pool, mock_state, mock_tournament_repo, monkeypatch):
        """Sets then clears the global debug override in a non-production environment."""
        monkeypatch.setenv("APP_ENVIRONMENT", "local")
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        mock_tournament_repo.set_debug_cycle_seconds.return_value = _lifecycle(debug_cycle_seconds=30)
        set_result = await service.set_debug_cycle_length(30)
        assert set_result.debug_cycle_seconds == 30

        mock_tournament_repo.set_debug_cycle_seconds.return_value = _lifecycle(debug_cycle_seconds=None)
        cleared = await service.set_debug_cycle_length(None)
        assert cleared.debug_cycle_seconds is None

    async def test_production_disabled(self, mock_pool, mock_state, mock_tournament_repo, monkeypatch):
        """Raises DebugRouteDisabledError when APP_ENVIRONMENT is production (T-12-07)."""
        monkeypatch.setenv("APP_ENVIRONMENT", "production")
        service = TournamentService(mock_pool, mock_state, mock_tournament_repo)

        with pytest.raises(DebugRouteDisabledError):
            await service.set_debug_cycle_length(30)
        # The repo setter must never run in production.
        mock_tournament_repo.set_debug_cycle_seconds.assert_not_called()
