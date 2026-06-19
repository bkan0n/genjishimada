"""Unit tests for the tournament reward service (08-02).

Covers RWD-01 (participation), RWD-02 (placement), RWD-05 (streak bonus)
against TournamentRewardService with a mocked grant seam — no real broker or DB.
The injected LootboxService.grant_xp is an AsyncMock, so we assert grant
call counts/args rather than hitting RabbitMQ or PostgreSQL.
"""

from unittest.mock import AsyncMock

import pytest
from genjishimada_sdk.tournaments import TournamentCycleCompletedEvent, TournamentLeaderboardEntryResponse

from services.tournament_reward_service import TournamentRewardService

pytestmark = [pytest.mark.domain_tournaments]


# ---------------------------------------------------------------------------
# Dict / struct factories
# ---------------------------------------------------------------------------


def _category(
    category_id: int = 1,
    participation_xp: int = 10,
    placement_xp: list[dict] | None = None,
    streak_xp: list[dict] | None = None,
) -> dict:
    """Build a tournaments.categories row dict (jsonb tiers as list[dict])."""
    return {
        "id": category_id,
        "name": "Test Category",
        "participation_xp": participation_xp,
        "placement_xp": placement_xp if placement_xp is not None else [{"place": 1, "xp": 100}],
        "streak_xp": streak_xp if streak_xp is not None else [{"threshold": 3, "xp": 50}],
    }


def _cycle(cycle_id: int = 7, category_id: int = 1) -> dict:
    """Build a minimal cycle row dict."""
    return {"id": cycle_id, "category_id": category_id}


def _leaderboard_entry(rank: int, user_id: int) -> TournamentLeaderboardEntryResponse:
    """Build a leaderboard standing entry."""
    return TournamentLeaderboardEntryResponse(
        rank=rank,
        user_id=user_id,
        name=f"user{user_id}",
        time=10.0 + rank,
        verified=True,
        completion=True,
    )


def _completed_event(
    cycle_id: int = 7,
    category_id: int = 1,
    standings: list[TournamentLeaderboardEntryResponse] | None = None,
) -> TournamentCycleCompletedEvent:
    """Build a cycle-completed event."""
    return TournamentCycleCompletedEvent(
        cycle_id=cycle_id,
        category_id=category_id,
        standings=standings if standings is not None else [],
        winner_user_id=standings[0].user_id if standings else None,
    )


@pytest.fixture
def reward_service(mock_pool, mock_state, mock_tournament_repo, mock_lootbox_repo, mock_lootbox_service):
    """Construct TournamentRewardService with an AsyncMock grant seam.

    grant_xp on the injected LootboxService is the publish seam; assert on it.
    claim_xp_grant defaults to True (claim granted) unless a test overrides it.
    """
    mock_tournament_repo.claim_xp_grant.return_value = True
    mock_lootbox_service.grant_xp = AsyncMock()
    return TournamentRewardService(
        pool=mock_pool,
        state=mock_state,
        tournament_repo=mock_tournament_repo,
        lootbox_repo=mock_lootbox_repo,
        lootbox_service=mock_lootbox_service,
    )


# ---------------------------------------------------------------------------
# RWD-01: participation
# ---------------------------------------------------------------------------


class TestAwardParticipation:
    """RWD-01: participation_xp once per (cycle, user); 0 is a no-op."""

    async def test_participation_grants_once(self, reward_service, mock_tournament_repo, mock_lootbox_service):
        """First participation call grants participation_xp via grant_xp."""
        mock_tournament_repo.fetch_category.return_value = _category(participation_xp=15)

        await reward_service.award_participation(_cycle(), user_id=42, conn=object())

        mock_lootbox_service.grant_xp.assert_awaited_once()
        kwargs = mock_lootbox_service.grant_xp.call_args.kwargs
        assert kwargs["user_id"] == 42
        assert kwargs["amount"] == 15
        assert kwargs["type"] == "Tournament"

    async def test_participation_second_call_no_grant(
        self, reward_service, mock_tournament_repo, mock_lootbox_service
    ):
        """When the ledger claim returns False, no grant is issued."""
        mock_tournament_repo.fetch_category.return_value = _category(participation_xp=15)
        mock_tournament_repo.claim_xp_grant.side_effect = [True, False]

        await reward_service.award_participation(_cycle(), user_id=42, conn=object())
        await reward_service.award_participation(_cycle(), user_id=42, conn=object())

        assert mock_lootbox_service.grant_xp.await_count == 1

    async def test_participation_zero_is_noop(self, reward_service, mock_tournament_repo, mock_lootbox_service):
        """participation_xp == 0 grants nothing and claims nothing."""
        mock_tournament_repo.fetch_category.return_value = _category(participation_xp=0)

        await reward_service.award_participation(_cycle(), user_id=42, conn=object())

        mock_lootbox_service.grant_xp.assert_not_awaited()
        mock_tournament_repo.claim_xp_grant.assert_not_awaited()


# ---------------------------------------------------------------------------
# RWD-02: placement
# ---------------------------------------------------------------------------


class TestAwardCycleEndPlacement:
    """RWD-02: dict[place->xp].get(rank); ties paid; beyond-tier skipped; empty -> none."""

    async def test_placement_maps_rank_to_xp(self, reward_service, mock_tournament_repo, mock_lootbox_service):
        """Each standing's rank maps to its place's xp."""
        mock_tournament_repo.fetch_category.return_value = _category(
            placement_xp=[{"place": 1, "xp": 100}, {"place": 2, "xp": 50}]
        )
        mock_tournament_repo.fetch_cycle_participants.return_value = []
        event = _completed_event(standings=[_leaderboard_entry(1, 11), _leaderboard_entry(2, 22)])

        await reward_service.award_cycle_placements(event, conn=object())

        amounts = {c.kwargs["user_id"]: c.kwargs["amount"] for c in mock_lootbox_service.grant_xp.call_args_list}
        assert amounts == {11: 100, 22: 50}

    async def test_placement_tie_both_paid(self, reward_service, mock_tournament_repo, mock_lootbox_service):
        """Two rank-1 standings (tie) both receive place-1 xp -> two grant calls."""
        mock_tournament_repo.fetch_category.return_value = _category(placement_xp=[{"place": 1, "xp": 100}])
        mock_tournament_repo.fetch_cycle_participants.return_value = []
        event = _completed_event(standings=[_leaderboard_entry(1, 11), _leaderboard_entry(1, 22)])

        await reward_service.award_cycle_placements(event, conn=object())

        assert mock_lootbox_service.grant_xp.await_count == 2
        for call in mock_lootbox_service.grant_xp.call_args_list:
            assert call.kwargs["amount"] == 100

    async def test_placement_beyond_tier_skipped(self, reward_service, mock_tournament_repo, mock_lootbox_service):
        """A rank with no matching place (rank 5 vs top-3 config) is skipped."""
        mock_tournament_repo.fetch_category.return_value = _category(
            placement_xp=[{"place": 1, "xp": 100}, {"place": 2, "xp": 50}, {"place": 3, "xp": 25}]
        )
        mock_tournament_repo.fetch_cycle_participants.return_value = []
        event = _completed_event(standings=[_leaderboard_entry(1, 11), _leaderboard_entry(5, 55)])

        await reward_service.award_cycle_placements(event, conn=object())

        granted_users = [c.kwargs["user_id"] for c in mock_lootbox_service.grant_xp.call_args_list]
        assert granted_users == [11]

    async def test_placement_empty_standings_no_grants(
        self, reward_service, mock_tournament_repo, mock_lootbox_service
    ):
        """Empty standings produce zero placement grants."""
        mock_tournament_repo.fetch_category.return_value = _category()
        mock_tournament_repo.fetch_cycle_participants.return_value = []
        event = _completed_event(standings=[])

        await reward_service.award_cycle_placements(event, conn=object())

        mock_lootbox_service.grant_xp.assert_not_awaited()


# ---------------------------------------------------------------------------
# RWD-05: streak bonus
# ---------------------------------------------------------------------------


class TestAwardEditionStreak:
    """RWD-05: per-edition streak — +1 per tournament; bonus at exact threshold."""

    async def test_streak_bonus_at_threshold(self, reward_service, mock_tournament_repo, mock_lootbox_service):
        """Bonus granted when advance_streak returns current_streak == threshold."""
        mock_tournament_repo.fetch_category.return_value = _category(
            placement_xp=[], streak_xp=[{"threshold": 3, "xp": 50}]
        )
        mock_tournament_repo.fetch_cycle_participants.return_value = [77]
        mock_tournament_repo.fetch_all_streak_user_ids.return_value = [77]
        mock_tournament_repo.advance_streak.return_value = {"current_streak": 3}
        event = _completed_event(standings=[])

        await reward_service.award_edition_streaks([event], conn=object())

        mock_lootbox_service.grant_xp.assert_awaited_once()
        kwargs = mock_lootbox_service.grant_xp.call_args.kwargs
        assert kwargs["user_id"] == 77
        assert kwargs["amount"] == 50

    async def test_streak_no_bonus_below_threshold(
        self, reward_service, mock_tournament_repo, mock_lootbox_service
    ):
        """No bonus when current_streak is below every configured threshold."""
        mock_tournament_repo.fetch_category.return_value = _category(
            placement_xp=[], streak_xp=[{"threshold": 3, "xp": 50}]
        )
        mock_tournament_repo.fetch_cycle_participants.return_value = [77]
        mock_tournament_repo.fetch_all_streak_user_ids.return_value = [77]
        mock_tournament_repo.advance_streak.return_value = {"current_streak": 2}
        event = _completed_event(standings=[])

        await reward_service.award_edition_streaks([event], conn=object())

        mock_lootbox_service.grant_xp.assert_not_awaited()

    async def test_streak_no_bonus_above_threshold(
        self, reward_service, mock_tournament_repo, mock_lootbox_service
    ):
        """No bonus when current_streak overshoots the threshold (exact match only)."""
        mock_tournament_repo.fetch_category.return_value = _category(
            placement_xp=[], streak_xp=[{"threshold": 3, "xp": 50}]
        )
        mock_tournament_repo.fetch_cycle_participants.return_value = [77]
        mock_tournament_repo.fetch_all_streak_user_ids.return_value = [77]
        mock_tournament_repo.advance_streak.return_value = {"current_streak": 4}
        event = _completed_event(standings=[])

        await reward_service.award_edition_streaks([event], conn=object())

        mock_lootbox_service.grant_xp.assert_not_awaited()

    async def test_streak_advances_union_once_per_user(
        self, reward_service, mock_tournament_repo, mock_lootbox_service
    ):
        """Each distinct edition participant advances exactly once (participated=True)."""
        mock_tournament_repo.fetch_category.return_value = _category(placement_xp=[], streak_xp=[])
        mock_tournament_repo.fetch_cycle_participants.return_value = [1, 2, 3]
        mock_tournament_repo.fetch_all_streak_user_ids.return_value = [1, 2, 3]
        mock_tournament_repo.advance_streak.return_value = {"current_streak": 1}
        event = _completed_event(standings=[])

        await reward_service.award_edition_streaks([event], conn=object())

        assert mock_tournament_repo.advance_streak.await_count == 3
        for call in mock_tournament_repo.advance_streak.call_args_list:
            # participated flag is True for every participant
            assert call.args[2] is True or call.kwargs.get("participated") is True

    async def test_streak_union_dedupes_across_categories(
        self, reward_service, mock_tournament_repo, mock_lootbox_service
    ):
        """A user who plays two categories of one edition advances ONCE, not per cycle."""
        mock_tournament_repo.fetch_category.return_value = _category(placement_xp=[], streak_xp=[])
        # Cycle 7 participants {1, 2}; cycle 8 participants {2, 3}. Union = {1, 2, 3}.
        mock_tournament_repo.fetch_cycle_participants.side_effect = [[1, 2], [2, 3]]
        mock_tournament_repo.fetch_all_streak_user_ids.return_value = [1, 2, 3]
        mock_tournament_repo.advance_streak.return_value = {"current_streak": 1}
        results = [_completed_event(cycle_id=7, category_id=1), _completed_event(cycle_id=8, category_id=2)]

        await reward_service.award_edition_streaks(results, conn=object())

        advanced = [c for c in mock_tournament_repo.advance_streak.call_args_list if c.args[2] is True]
        assert len(advanced) == 3  # one advance per distinct user, not 4
        # All advances key on the marker cycle (max child cycle id), never per-cycle.
        assert {c.args[1] for c in advanced} == {8}

    async def test_streak_resets_edition_non_participants_only(
        self, reward_service, mock_tournament_repo, mock_lootbox_service
    ):
        """Tracked users who played NO child cycle reset to 0; sibling-category players do not."""
        mock_tournament_repo.fetch_category.return_value = _category(placement_xp=[], streak_xp=[])
        # Edition participants are {1, 2}; user 9 is tracked but didn't play -> reset.
        mock_tournament_repo.fetch_cycle_participants.side_effect = [[1], [2]]
        mock_tournament_repo.fetch_all_streak_user_ids.return_value = [1, 2, 9]
        mock_tournament_repo.advance_streak.return_value = {"current_streak": 1}
        results = [_completed_event(cycle_id=7, category_id=1), _completed_event(cycle_id=8, category_id=2)]

        await reward_service.award_edition_streaks(results, conn=object())

        resets = [c for c in mock_tournament_repo.advance_streak.call_args_list if c.args[2] is False]
        assert [c.args[0] for c in resets] == [9]  # only the true non-participant
        assert resets[0].args[1] == 8  # reset keyed on the marker cycle too
