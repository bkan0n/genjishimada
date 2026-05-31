"""Wave-0 scaffold for SC-2 (non-PB verify) and SC-3 (PB propagation).

These tests pin the Phase 11 verification contracts established in plan 11-01
(repo lookups + SDK events) and stake out the SC-2/SC-3 behaviors that the
hot-path edits in 11-02/11-03 will fill in.

Behaviors that are not yet implemented are marked ``xfail(strict=False)`` so
the suite is green today and flips to real coverage as the surface lands.

Conventions (CLAUDE.md / project MEMORY):
- pytest-asyncio is in ``auto`` mode.
- ``X-PYTEST-ENABLED=1`` makes ``BaseService.publish_message`` skip RabbitMQ,
  so integration assertions target DB/job state, not the broker.
- Do NOT assert ``is True``/``is False`` against ``check_active_cycle_for_category``;
  it returns ``int | None`` (a cycle id), not a bool (Phase-4 contract).

Fixtures (described, wired in 11-02/11-03):
- ``seeded_faster_core_completion``: a pre-seeded core completion that is
  strictly faster than the tournament submission, so the 0017 speed trigger
  (``enforce_speed_rules_nonlegacy_only``) rejects the slower run and NO core
  row is written -- this is what routes the run onto the non-PB tournament
  verification surface.
- ``tournament_completion_factory``: creates a ``tournaments.completions`` row
  keyed to an active cycle's map, returning its id for verify/leaderboard
  assertions.
"""

import pytest

from genjishimada_sdk.tournaments import (
    TournamentCompletionCreatedEvent,
    TournamentVerificationChangedEvent,
)

pytestmark = [pytest.mark.domain_tournaments]


# ---------------------------------------------------------------------------
# Contract pins (real assertions -- these pass today on the 11-01 contracts)
# ---------------------------------------------------------------------------


def test_verification_changed_event_contract() -> None:
    """TournamentVerificationChangedEvent carries the verify-propagation fields."""
    event = TournamentVerificationChangedEvent(
        tournament_completion_id=1,
        cycle_id=2,
        user_id=3,
        verified=True,
        time=42.5,
    )
    assert event.tournament_completion_id == 1
    assert event.cycle_id == 2
    assert event.user_id == 3
    assert event.verified is True
    assert event.time == 42.5


def test_completion_created_event_carries_submission_details() -> None:
    """Extended TournamentCompletionCreatedEvent lets the bot embed skip a fetch."""
    event = TournamentCompletionCreatedEvent(
        completion_id=10,
        cycle_id=2,
        user_id=3,
        time=42.5,
        video=None,
        screenshot="https://example.com/s.png",
    )
    assert event.completion_id == 10
    assert event.user_id == 3
    assert event.video is None
    assert event.screenshot == "https://example.com/s.png"


# ---------------------------------------------------------------------------
# SC-3: PB path -- a personal-best on the cycle map verified once propagates
# verification to BOTH core.completions AND the tournament row.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="implemented in 11-02/11-03", strict=False)
def test_pb_path_submission_creates_linked_tournament_and_core_rows() -> None:
    """A PB run on a cycle map writes a core row linked to a tournament row.

    Asserted once the submit hook (11-02) resolves map -> active cycle and
    inserts the tournament row + core.completions.tournament_completion_id link
    inside one transaction.
    """
    raise AssertionError("PB submit cross-write link not implemented yet (11-02)")


@pytest.mark.xfail(reason="implemented in 11-02/11-03", strict=False)
def test_pb_path_verify_propagates_to_both_rows() -> None:
    """Verifying the PB completion flips both core.completions and the tournament row.

    SC-3: ``set_tournament_verified`` side-effect inside the completion verify
    path marks ``tournaments.completions.verified`` TRUE alongside the core row.
    """
    raise AssertionError("PB verify propagation not implemented yet (11-03)")


# ---------------------------------------------------------------------------
# SC-2: non-PB path -- a slower-than-PB run on the cycle map writes NO core row
# (0017 speed trigger), creates a tournament row, and is verifiable via the new
# tournament verify endpoint.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="implemented in 11-02/11-03", strict=False)
def test_non_pb_path_submission_creates_tournament_row_without_core_row() -> None:
    """A slower run trips the 0017 trigger: no core row, tournament row created.

    SC-2: with a pre-seeded faster core completion, the slower submission is
    rejected by ``enforce_speed_rules_nonlegacy_only`` so no core row exists,
    while the tournament-native row is still created for the cycle.
    """
    raise AssertionError("non-PB submit branch not implemented yet (11-02)")


@pytest.mark.xfail(reason="implemented in 11-02/11-03", strict=False)
def test_non_pb_path_verify_endpoint_marks_tournament_row_verified() -> None:
    """The new verify endpoint flips a non-PB tournament row to verified.

    SC-2: PATCH /tournaments/completions/{id}/verify calls
    ``set_tournament_verified`` and publishes TournamentVerificationChangedEvent;
    no core row is touched.
    """
    raise AssertionError("tournament verify endpoint not implemented yet (11-03)")
