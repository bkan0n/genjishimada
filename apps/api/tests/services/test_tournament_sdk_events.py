"""SDK wire-contract tests for the verification-aware tournament results events (Phase 12.1, D-09).

These assert the msgspec round-trip + backward-compatibility guarantees the poller (Plan 04)
and bot (Plan 05) build against:

- ``TournamentEditionResultsEvent`` exists, is importable + exported, and round-trips.
- ``TournamentRolloverEvent`` gained an additive ``results_pending: bool = False`` flag so an
  OLD-shape outbox payload (no ``results_pending`` key) still ``msgspec.convert``s cleanly
  (Pitfall 2 — a hard backward-compat constraint for in-flight rows at deploy).
- ``EditionStatus`` Literal includes ``awaiting_results``.
"""

import typing

import msgspec

import genjishimada_sdk.tournaments as sdk_tournaments
from genjishimada_sdk.tournaments import (
    EditionStatus,
    TournamentEditionResultsEvent,
    TournamentRolloverEvent,
)


def test_rollover_old_shape_payload_converts_with_default_false() -> None:
    """An OLD-shape payload (no results_pending key) converts and defaults results_pending to False."""
    event = msgspec.convert(
        {"edition_id": 1, "results": [], "started": []},
        TournamentRolloverEvent,
    )
    assert event.results_pending is False


def test_rollover_payload_with_results_pending_true() -> None:
    """A payload carrying results_pending=True yields results_pending == True."""
    event = msgspec.convert(
        {"edition_id": 1, "results": [], "started": [], "results_pending": True},
        TournamentRolloverEvent,
    )
    assert event.results_pending is True


def test_edition_results_event_construction() -> None:
    """TournamentEditionResultsEvent carries edition_id + results."""
    event = TournamentEditionResultsEvent(edition_id=1, results=[])
    assert event.edition_id == 1
    assert event.results == []


def test_edition_results_event_round_trips() -> None:
    """TournamentEditionResultsEvent survives a msgspec JSON encode/decode round-trip."""
    event = TournamentEditionResultsEvent(edition_id=42, results=[])
    decoded = msgspec.json.decode(msgspec.json.encode(event), type=TournamentEditionResultsEvent)
    assert decoded.edition_id == 42
    assert decoded.results == []


def test_edition_results_event_exported_in_all() -> None:
    """TournamentEditionResultsEvent is importable and present in __all__."""
    assert "TournamentEditionResultsEvent" in sdk_tournaments.__all__


def test_edition_status_includes_awaiting_results() -> None:
    """The EditionStatus Literal contains awaiting_results."""
    assert "awaiting_results" in typing.get_args(EditionStatus)
