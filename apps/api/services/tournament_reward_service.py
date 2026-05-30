"""Service for tournament reward business logic (participation, placement, streak)."""

from __future__ import annotations

from logging import getLogger
from typing import TYPE_CHECKING

import msgspec
from asyncpg import Pool
from genjishimada_sdk.tournaments import PlacementXpTier, StreakXpTier
from litestar.datastructures import State
from litestar.datastructures.headers import Headers

from repository.lootbox_repository import LootboxRepository
from repository.tournaments_repository import TournamentRepository
from services.base import BaseService
from services.lootbox_service import LootboxService

if TYPE_CHECKING:
    from asyncpg import Connection
    from genjishimada_sdk.tournaments import TournamentCycleCompletedEvent
    from genjishimada_sdk.xp import XpGrantEvent

log = getLogger(__name__)


class TournamentRewardService(BaseService):
    """Tournament reward grants: participation, placement, and streak bonuses.

    Every grant is guarded by the 08-01 idempotency ledger (claim_xp_grant) and
    routed through LootboxService.grant_xp, which writes lootbox.xp and publishes
    the generic XpGrantEvent (type="Tournament") to ``api.xp.grant``. The
    tournament-specific grant event variant has zero consumers and is never
    published — only the generic XpGrantEvent the bot already decodes is emitted.

    Scope boundary: award_cycle_end advances streaks only for the finalizing
    cycle's participants. The non-participant streak RESET sweep (which needs the
    full tracked-user set via fetch_all_streak_user_ids, broader than one event's
    category scope) is owned by 08-03's outbox hook, not this service.
    """

    def __init__(
        self,
        pool: Pool,
        state: State,
        tournament_repo: TournamentRepository,
        lootbox_repo: LootboxRepository,
        lootbox_service: LootboxService,
    ) -> None:
        """Initialize service.

        Args:
            pool: AsyncPG connection pool.
            state: Application state.
            tournament_repo: Tournament repository (ledger, streaks, participants).
            lootbox_repo: Lootbox repository (XP multiplier + upsert).
            lootbox_service: Lootbox service supplying the conn-accepting grant_xp helper.
        """
        super().__init__(pool, state)
        self._tournament_repo = tournament_repo
        self._lootbox_repo = lootbox_repo
        self._lootbox_service = lootbox_service

    async def _grant_xp(  # noqa: PLR0913
        self,
        user_id: int,
        amount: int,
        reason: str,
        cycle_id: int,
        grant_reason_key: str,
        pending_events: list[XpGrantEvent],
        *,
        conn: Connection,
    ) -> None:
        """Ledger-guarded XP grant inside the caller's transaction.

        Claims the (cycle_id, user_id, grant_reason_key) ledger row first; a
        replay (claim returns False) is a no-op. On a fresh claim, delegates to
        LootboxService.grant_xp so the lootbox.xp write joins ``conn``'s
        transaction. The generic XpGrantEvent (type="Tournament") is NOT published
        here — it is appended to ``pending_events`` so the caller publishes it only
        after the transaction commits (CR-02: never notify the bot about XP a
        rollback would erase).

        Args:
            user_id: User receiving XP.
            amount: XP amount.
            reason: Human-readable grant reason (carried on the event).
            cycle_id: Cycle the grant belongs to.
            grant_reason_key: Ledger reason category (participation/placement/streak).
            pending_events: Collector for the deferred XpGrantEvent (published
                post-commit by the caller via publish_xp_events).
            conn: Active connection for transactional participation.
        """
        claimed = await self._tournament_repo.claim_xp_grant(
            cycle_id,
            user_id,
            grant_reason_key,
            amount,
            conn=conn,
        )
        if not claimed:
            log.debug(
                "[!] XP grant already claimed (cycle=%s, user=%s, reason=%s) — skipping",
                cycle_id,
                user_id,
                grant_reason_key,
            )
            return

        await self._lootbox_service.grant_xp(
            headers=Headers({}),
            user_id=user_id,
            amount=amount,
            type="Tournament",
            reason=reason,
            conn=conn,
            pending_events=pending_events,
        )
        log.debug("[✓] Granted %s XP to user %s (%s)", amount, user_id, grant_reason_key)

    async def publish_xp_events(self, events: list[XpGrantEvent]) -> None:
        """Publish deferred tournament XP grant events after the caller commits.

        Thin pass-through to :meth:`LootboxService.publish_xp_events`. Callers
        invoke this only AFTER the transaction that produced ``events`` has
        committed, so a notification is never sent for XP a rollback erased.

        Args:
            events: Deferred XpGrantEvents returned by award_participation /
                award_cycle_end.
        """
        if events:
            await self._lootbox_service.publish_xp_events(events)

    async def award_participation(
        self,
        cycle: dict,
        user_id: int,
        *,
        conn: Connection,
    ) -> list[XpGrantEvent]:
        """Grant the category's participation_xp once per (cycle, user).

        A participation_xp of 0 is a no-op (no ledger claim, no grant). A second
        call for the same (cycle, user) grants nothing because the ledger claim
        returns False.

        Args:
            cycle: Cycle row dict (must contain ``id`` and ``category_id``).
            user_id: Participating user ID.
            conn: Active connection for transactional participation.

        Returns:
            Deferred XpGrantEvents to publish AFTER the caller commits (empty when
            nothing was granted). Publish via :meth:`publish_xp_events`.
        """
        pending_events: list[XpGrantEvent] = []
        category = await self._tournament_repo.fetch_category(cycle["category_id"], conn=conn)
        if not category:
            log.debug("[!] No category %s for participation grant — skipping", cycle["category_id"])
            return pending_events

        participation_xp = category["participation_xp"]
        if not participation_xp:
            return pending_events

        await self._grant_xp(
            user_id=user_id,
            amount=participation_xp,
            reason="Tournament Participation",
            cycle_id=cycle["id"],
            grant_reason_key="participation",
            pending_events=pending_events,
            conn=conn,
        )
        return pending_events

    async def award_cycle_end(
        self,
        event: TournamentCycleCompletedEvent,
        *,
        conn: Connection,
    ) -> list[XpGrantEvent]:
        """Grant placement rewards and advance/bonus streaks at cycle finalization.

        Placement: builds ``{place: xp}`` from the category's placement_xp tiers
        and grants ``map.get(rank)`` to each standing. The admin-configured
        ``PlacementXpTier.place`` is matched against the leaderboard ``rank``
        (``RANK() OVER (ORDER BY time)``): both are 1-based positions, so ``place``
        is the canonical name for the same value the standings call ``rank`` (per
        decision A3). Ties (same rank) are each paid their rank's XP, ranks beyond
        the configured tiers are skipped, and empty standings grant nothing. If
        tiers are configured but match no standing (likely a misconfigured
        ``place`` set), a warning is logged rather than silently paying nothing.

        Streak: every distinct cycle participant gets advance_streak(participated=
        True); a bonus is granted only when the returned current_streak exactly
        matches a configured streak threshold. The non-participant reset sweep is
        owned by 08-03 (it needs the full tracked-user set).

        Args:
            event: Cycle-completed event with snapshotted standings.
            conn: Active connection for transactional participation.

        Returns:
            Deferred XpGrantEvents to publish AFTER the caller commits (empty when
            nothing was granted). Publish via :meth:`publish_xp_events`.
        """
        pending_events: list[XpGrantEvent] = []
        category = await self._tournament_repo.fetch_category(event.category_id, conn=conn)
        if not category:
            log.debug("[!] No category %s for cycle-end rewards — skipping", event.category_id)
            return pending_events

        # PLACEMENT: dict[place -> xp] from configured tiers. place == leaderboard
        # rank (both 1-based; decision A3).
        placement_tiers = msgspec.convert(category["placement_xp"], list[PlacementXpTier])
        placement_by_place = {tier.place: tier.xp for tier in placement_tiers}
        placement_granted = 0
        for entry in event.standings:
            xp = placement_by_place.get(entry.rank)
            if not xp:
                continue
            await self._grant_xp(
                user_id=entry.user_id,
                amount=xp,
                reason=f"Tournament Placement #{entry.rank}",
                cycle_id=event.cycle_id,
                grant_reason_key="placement",
                pending_events=pending_events,
                conn=conn,
            )
            placement_granted += 1
        if placement_by_place and event.standings and placement_granted == 0:
            log.warning(
                "[!] cycle %s: %d placement tier(s) configured but none matched any of "
                "%d standing rank(s) — check categories.placement_xp 'place' values "
                "are 1-based ranks",
                event.cycle_id,
                len(placement_by_place),
                len(event.standings),
            )

        # STREAK: advance every participant; bonus only at an exact threshold.
        streak_tiers = msgspec.convert(category["streak_xp"], list[StreakXpTier])
        streak_by_threshold = {tier.threshold: tier.xp for tier in streak_tiers}
        participants = set(await self._tournament_repo.fetch_cycle_participants(event.cycle_id, conn=conn))
        for participant_id in participants:
            streak = await self._tournament_repo.advance_streak(
                participant_id,
                event.cycle_id,
                True,
                conn=conn,
            )
            current_streak = streak.get("current_streak")
            if current_streak is None:
                continue
            bonus = streak_by_threshold.get(current_streak)
            if not bonus:
                continue
            await self._grant_xp(
                user_id=participant_id,
                amount=bonus,
                reason=f"Tournament Streak x{current_streak}",
                cycle_id=event.cycle_id,
                grant_reason_key="streak",
                pending_events=pending_events,
                conn=conn,
            )
        return pending_events


async def provide_tournament_reward_service(
    state: State,
    tournament_repo: TournamentRepository,
    lootbox_repo: LootboxRepository,
) -> TournamentRewardService:
    """Litestar DI provider for the tournament reward service.

    Args:
        state: Application state containing the database pool.
        tournament_repo: Tournament repository instance.
        lootbox_repo: Lootbox repository instance.

    Returns:
        TournamentRewardService instance.
    """
    lootbox_service = LootboxService(pool=state.db_pool, state=state, lootbox_repo=lootbox_repo)
    return TournamentRewardService(
        pool=state.db_pool,
        state=state,
        tournament_repo=tournament_repo,
        lootbox_repo=lootbox_repo,
        lootbox_service=lootbox_service,
    )
