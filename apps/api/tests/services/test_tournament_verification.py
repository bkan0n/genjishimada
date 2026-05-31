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

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from genjishimada_sdk.completions import (
    CompletionCreateRequest,
    CompletionVerificationUpdateRequest,
)
from genjishimada_sdk.tournaments import (
    TournamentCompletionCreatedEvent,
    TournamentVerificationChangedEvent,
)

from services.completions_service import CompletionsService

pytestmark = [pytest.mark.domain_tournaments]


def _make_service() -> tuple[CompletionsService, Any, Any, Any]:
    """Build a CompletionsService with mocked deps for 11-02 branch tests.

    Returns the service plus the completions repo, tournament repo, and reward
    service mocks so callers can program return values and assert calls. The pool
    yields a single shared connection whose transaction() is a no-op async CM.
    """
    pool = MagicMock()
    conn = AsyncMock()

    acquire_cm = MagicMock()
    acquire_cm.__aenter__ = AsyncMock(return_value=conn)
    acquire_cm.__aexit__ = AsyncMock(return_value=None)
    pool.acquire.return_value = acquire_cm

    txn_cm = MagicMock()
    txn_cm.__aenter__ = AsyncMock(return_value=None)
    txn_cm.__aexit__ = AsyncMock(return_value=None)
    # conn.transaction() must return the CM synchronously (not a coroutine), so
    # override the AsyncMock attribute with a plain MagicMock.
    conn.transaction = MagicMock(return_value=txn_cm)

    completions_repo = AsyncMock()
    tournament_repo = AsyncMock()
    tournament_repo.get_active_cycle_by_map_id.return_value = None
    reward_service = AsyncMock()
    reward_service.award_participation.return_value = []

    service = CompletionsService(
        pool,
        MagicMock(),
        completions_repo,
        tournament_repo=tournament_repo,
        tournament_reward_service=reward_service,
    )
    service.publish_message = AsyncMock(return_value={"job_id": "j"})  # type: ignore[method-assign]
    return service, completions_repo, tournament_repo, reward_service


def _request() -> Any:
    request = MagicMock()
    request.headers = {}
    request.app.emit = MagicMock()
    return request


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


async def test_pb_path_submission_creates_linked_tournament_and_core_rows() -> None:
    """A PB run on a cycle map writes a core row linked to a tournament row (D-04).

    The submit hook resolves map -> active cycle and inserts the tournament row +
    core.completions.tournament_completion_id link inside one transaction.
    """
    service, completions_repo, tournament_repo, _ = _make_service()
    completions_repo.get_pending_verification.return_value = None
    completions_repo.fetch_map_metadata_by_code.return_value = {"map_id": 777}
    completions_repo.insert_completion.return_value = 5001
    completions_repo.get_suspicious_flags.return_value = []
    tournament_repo.get_active_cycle_by_map_id.return_value = {
        "id": 42,
        "category_id": 3,
        "map_id": 777,
        "status": "active",
    }
    tournament_repo.create_tournament_completion.return_value = {"id": 9001}

    await service.submit_completion(
        data=CompletionCreateRequest(
            user_id=123,
            code="ABC123",
            time=8.0,
            screenshot="https://example.com/s.png",
            video="https://example.com/v.mp4",
        ),
        request=_request(),
        notifications=AsyncMock(),
        users=AsyncMock(),
    )

    tournament_repo.create_tournament_completion.assert_awaited_once()
    completions_repo.set_completion_tournament_link.assert_awaited_once()
    args = completions_repo.set_completion_tournament_link.await_args
    assert args.args[0] == 5001
    assert args.args[1] == 9001


async def test_pb_path_verify_propagates_to_both_rows() -> None:
    """Verifying the PB completion flips the tournament row + awards XP (D-04a/SC-3).

    ``set_tournament_verified`` side-effect inside the completion verify path
    marks ``tournaments.completions.verified`` TRUE and grants participation XP.
    """
    service, completions_repo, tournament_repo, reward_service = _make_service()
    conn = AsyncMock()
    completions_repo.check_completion_exists.return_value = True
    completions_repo.fetch_completion_for_moderation.return_value = {
        "user_id": 123,
        "code": "ABC123",
        "old_time": 8.0,
        # old_verified True so the (verified AND not old_verified) quest-progress
        # branch is skipped — this test isolates the tournament side-effect.
        "old_verified": True,
        "tournament_completion_id": 9001,
    }
    completions_repo.fetch_map_metadata_by_code.return_value = {"map_id": 777}
    tournament_repo.get_active_cycle_by_map_id.return_value = {
        "id": 42,
        "category_id": 3,
        "map_id": 777,
        "status": "active",
    }
    tournament_repo.set_tournament_verified.return_value = {
        "id": 9001,
        "cycle_id": 42,
        "user_id": 123,
        "time": 8.0,
    }
    reward_service.award_participation.return_value = ["xp"]

    await service.verify_completion(
        request=_request(),
        record_id=5001,
        data=CompletionVerificationUpdateRequest(verified=True, verified_by=456, reason=None),
        conn=conn,
    )

    tournament_repo.set_tournament_verified.assert_awaited_once_with(9001, conn=conn)
    reward_service.award_participation.assert_awaited_once()


async def test_pb_path_verify_idempotent_award_via_ledger() -> None:
    """Verifying twice grants participation once (SC-7 — ledger is the guard).

    ``award_participation`` is called unconditionally each verify; the 08-01
    ledger returns no events on replay so ``publish_xp_events`` flushes nothing.
    """
    service, completions_repo, tournament_repo, reward_service = _make_service()
    conn = AsyncMock()
    completions_repo.check_completion_exists.return_value = True
    completions_repo.fetch_completion_for_moderation.return_value = {
        "user_id": 123,
        "code": "ABC123",
        "old_time": 8.0,
        # old_verified True so the quest-progress branch is skipped (isolation).
        "old_verified": True,
        "tournament_completion_id": 9001,
    }
    completions_repo.fetch_map_metadata_by_code.return_value = {"map_id": 777}
    tournament_repo.get_active_cycle_by_map_id.return_value = {
        "id": 42,
        "category_id": 3,
        "map_id": 777,
        "status": "active",
    }
    tournament_repo.set_tournament_verified.return_value = {
        "id": 9001,
        "cycle_id": 42,
        "user_id": 123,
        "time": 8.0,
    }
    # Replay: ledger already claimed -> no events to publish.
    reward_service.award_participation.return_value = []

    await service.verify_completion(
        request=_request(),
        record_id=5001,
        data=CompletionVerificationUpdateRequest(verified=True, verified_by=456, reason=None),
        conn=conn,
    )

    reward_service.award_participation.assert_awaited_once()
    reward_service.publish_xp_events.assert_not_awaited()


# ---------------------------------------------------------------------------
# SC-2: non-PB path -- a slower-than-PB run on the cycle map writes NO core row
# (0017 speed trigger), creates a tournament row, and is verifiable via the new
# tournament verify endpoint.
# ---------------------------------------------------------------------------


async def test_non_pb_path_submission_creates_tournament_row_without_core_row() -> None:
    """A slower run trips the 0017 trigger: no core row, tournament row created (SC-2/D-07).

    The slower submission is rejected by ``enforce_speed_rules_nonlegacy_only``
    (surfaced as CheckViolationError) so no core row exists; on an active cycle
    map the tournament-native row is still created and no 400 is raised.
    """
    from asyncpg.exceptions import CheckViolationError

    service, completions_repo, tournament_repo, _ = _make_service()
    completions_repo.get_pending_verification.return_value = None
    completions_repo.fetch_map_metadata_by_code.return_value = {"map_id": 777}
    completions_repo.insert_completion.side_effect = CheckViolationError("speed trigger")
    completions_repo.get_suspicious_flags.return_value = []
    tournament_repo.get_active_cycle_by_map_id.return_value = {
        "id": 42,
        "category_id": 3,
        "map_id": 777,
        "status": "active",
    }
    tournament_repo.create_tournament_completion.return_value = {"id": 9002}

    await service.submit_completion(
        data=CompletionCreateRequest(
            user_id=123,
            code="ABC123",
            time=99.0,
            screenshot="https://example.com/s.png",
            video=None,
        ),
        request=_request(),
        notifications=AsyncMock(),
        users=AsyncMock(),
    )

    tournament_repo.create_tournament_completion.assert_awaited_once()
    completions_repo.set_completion_tournament_link.assert_not_awaited()


@pytest.mark.xfail(reason="tournament verify endpoint lands in 11-03", strict=False)
def test_non_pb_path_verify_endpoint_marks_tournament_row_verified() -> None:
    """The new verify endpoint flips a non-PB tournament row to verified.

    SC-2: PATCH /tournaments/completions/{id}/verify calls
    ``set_tournament_verified`` and publishes TournamentVerificationChangedEvent;
    no core row is touched. The endpoint itself is delivered in plan 11-03.
    """
    raise AssertionError("tournament verify endpoint not implemented yet (11-03)")
