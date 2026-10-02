"""Atomically drain tournament source rows, rewards, and PostgreSQL delivery jobs."""

from __future__ import annotations

from logging import getLogger
from typing import TYPE_CHECKING

import msgspec
from asyncpg import Pool
from genjishimada_sdk.tournaments import (
    TournamentCycleCompletedEvent,
    TournamentCycleStartedEvent,
    TournamentEditionResultsEvent,
    TournamentLeaderboardEntryResponse,
    TournamentRolloverEvent,
)
from litestar.datastructures import Headers, State

from repository.lootbox_repository import LootboxRepository
from repository.tournaments_repository import TournamentRepository
from services.base import BaseService
from services.lootbox_service import LootboxService
from services.tournament_reward_service import TournamentRewardService
from utilities.transactions import transaction

if TYPE_CHECKING:
    from asyncpg import Connection

log = getLogger(__name__)

# Routing for outbox rows. The combined edition_rollover event collapses the
# former cycle_started/cycle_completed pair; the edition_results event (Phase
# 12.1, D-09) carries the deferred results-only payload written when an
# awaiting_results edition's verification queue drains. The row's payload is
# converted directly into the mapped struct; drift between the jsonb payload keys
# and the struct surfaces as an immediate msgspec.convert error rather than a
# silently shipped bad event (Pitfall 5).
_EVENT_ROUTING: dict[str, tuple[str, type[msgspec.Struct]]] = {
    "edition_rollover": ("api.tournament.rollover", TournamentRolloverEvent),
    "edition_results": ("api.tournament.results", TournamentEditionResultsEvent),
}


class TournamentOutboxService(BaseService):
    """Service that bridges tournament outbox rows to PostgreSQL queue.

    Extends :class:`BaseService` purely to inherit ``enqueue`` (and its
    ``public.jobs`` record + idempotency handling). The poll loop lives in the
    module-level :func:`publish_pending_transitions` so it can be driven by the
    ``tournament_outbox_poller`` lifespan task in ``app.py``.
    """


def _build_event(row: dict) -> tuple[str, TournamentRolloverEvent | TournamentEditionResultsEvent]:
    """Convert an outbox row into its routing key and decoded event.

    Dispatches on ``event_type`` via :data:`_EVENT_ROUTING`: an
    ``edition_rollover`` row decodes to a :class:`TournamentRolloverEvent` on
    ``api.tournament.rollover``; an ``edition_results`` row (Phase 12.1, D-09)
    decodes to a :class:`TournamentEditionResultsEvent` on
    ``api.tournament.results``. One row == one event. Both event structs carry
    ``edition_id`` and ``results``, the only fields the publish loop reads.

    Args:
        row: A ``tournaments.pending_transitions`` row dict. ``event_type`` is the
            CHECK-constrained discriminator; ``payload`` is already a Python dict
            via the jsonb<->msgspec codec registered in ``app.py``.

    Returns:
        A ``(routing_key, event)`` tuple.

    Raises:
        KeyError: If ``event_type`` is not a known transition type.
        msgspec.ValidationError: If the payload does not match the struct shape
            (Pitfall 5 — keeps a malformed payload row unpublished).
    """
    routing_key, struct_type = _EVENT_ROUTING[row["event_type"]]
    event = msgspec.convert(row["payload"], struct_type)
    return routing_key, event  # type: ignore[return-value]


def _idempotency_key(event_type: str, edition_id: int) -> str:
    """Return the edition-scoped idempotency key for an outbox event type.

    ``edition_rollover`` -> ``tournament:rollover:{edition_id}:start``;
    ``edition_results`` -> ``tournament:results:{edition_id}`` (Phase 12.1, D-09).
    Both keys are edition-scoped so a re-delivered message cannot double-grant XP
    or double-transfer the champion role.

    The ``:start`` qualifier on the rollover key is load-bearing: every
    ``edition_rollover`` OUTBOX row is a bootstrap START announcement
    (:meth:`TournamentService.bootstrap_edition` is the sole writer — migration 0025
    stopped the pg_cron transition from writing rollover rows). The edition END
    rollover is published DIRECTLY by :func:`process_awaiting_results_editions` under
    the un-suffixed ``tournament:rollover:{edition_id}``. Without the ``:start``
    suffix the two share one key, so the bot's idempotency claim on the bootstrap
    START silently drops the same edition's END card (the ``results_pending=True``
    "rotation has ended" announcement) whenever that edition later drains.

    Args:
        event_type: The outbox row's ``event_type`` discriminator.
        edition_id: The edition the event belongs to.

    Returns:
        The idempotency key string.
    """
    if event_type == "edition_results":
        return f"tournament:results:{edition_id}"
    return f"tournament:rollover:{edition_id}:start"


async def publish_pending_transitions(state: State) -> None:
    """Atomically grant rewards, enqueue deliveries, and acknowledge source rows."""
    pool: Pool | None = state.get("db_pool")
    if pool is None:
        # Defensive readiness guard: on a fresh cold start the asyncpg lifespan
        # (entered after the poller's lifespan) may not have populated db_pool yet.
        # No-op cleanly rather than raising -- the next ~10s tick retries.
        log.debug("[!] outbox poll skipped: db_pool not ready")
        return
    service = TournamentOutboxService(pool, state)
    repository = TournamentRepository(pool)
    lootbox_repo = LootboxRepository(pool)
    lootbox_service = LootboxService(pool=pool, state=state, lootbox_repo=lootbox_repo)
    reward_service = TournamentRewardService(
        pool=pool,
        state=state,
        tournament_repo=repository,
        lootbox_repo=lootbox_repo,
        lootbox_service=lootbox_service,
    )
    async with transaction(pool) as conn:
        # (1) Drain-aware results computation for awaiting_results editions (D-07).
        # This runs INSIDE the same transaction as the outbox drain below so the
        # edition flip + the edition_results outbox-row write (the deferred path)
        # + any grants are one atomic unit (Pitfall 3 — at-least-once preserved).
        await process_awaiting_results_editions(
            conn,  # type: ignore[arg-type]
            repository,
            service,
            reward_service,
        )

        # (2) Drain the outbox: publish every unpublished row (edition_rollover
        # AND the edition_results rows written above on a PRIOR tick).
        rows = await repository.fetch_unpublished_transitions(conn=conn)  # type: ignore[arg-type]
        for row in rows:
            routing_key, event = _build_event(row)
            edition_id = event.edition_id

            # RWD-02/04/05: grant placement (per child cycle) + advance/reset
            # streaks (ONCE per edition over the union of child-cycle participants)
            # INSIDE this outbox transaction (Option A) before the publish/mark.
            # Placement is keyed on entry.cycle_id; streaks on the edition's marker
            # cycle. Both are replay-safe via the 08-01 ledger / advance_streak guard,
            # so a re-delivered edition_rollover grants no duplicate XP and never
            # double-advances. XP notifications enqueue on this same transaction,
            # so acknowledgement failures also roll back grants and delivery work.
            for entry in event.results:
                await reward_service.award_cycle_placements(entry, conn=conn)  # type: ignore[arg-type]
                log.info("[✓] cycle-end rewards processed for cycle %s (edition %s)", entry.cycle_id, edition_id)
            await reward_service.award_edition_streaks(list(event.results), conn=conn)  # type: ignore[arg-type]

            # ONE combined publish per row, then mark it published — all inside this
            # transaction (publish-before-mark = at-least-once). The edition-scoped
            # idempotency key (rollover OR results) dedupes re-publishes downstream.
            await service.enqueue(
                conn=conn,
                routing_key=routing_key,
                data=event,
                headers=Headers({}),
                idempotency_key=_idempotency_key(row["event_type"], edition_id),
                entity_key="tournament:announcements",
            )
            await repository.mark_transition_published(row["id"], conn=conn)  # type: ignore[arg-type]
            log.info(
                "[→] published %s (edition %s: %d results)",
                row["event_type"],
                edition_id,
                len(event.results),
            )


async def _build_cycle_completed_event(
    repository: TournamentRepository,
    cycle_id: int,
    category_id: int,
    *,
    conn: Connection,
) -> TournamentCycleCompletedEvent:
    """Build a per-cycle completed event from the LIVE leaderboard (D-07, Pattern 4).

    Reuses :meth:`TournamentRepository.fetch_leaderboard` verbatim — the same
    ranking the cron used to snapshot, now computed at drain time when every
    completion is ``verified`` or ``rejected`` (no ``pending`` rows remain). The
    winner is the rank-1 standing (``standings[0]`` is already the lowest
    ``inserted_at``/``user_id`` at rank 1); an empty leaderboard yields empty
    standings and ``winner_user_id=None`` (Pitfall 6, no champion transfer).

    Args:
        repository: Tournament repository (leaderboard read).
        cycle_id: Child cycle to compute.
        category_id: Category the cycle belongs to.
        conn: Active outbox connection for transactional participation.

    Returns:
        The per-cycle :class:`TournamentCycleCompletedEvent`.
    """
    rows = await repository.fetch_leaderboard(cycle_id, conn=conn)  # type: ignore[arg-type]
    standings = [msgspec.convert(r, TournamentLeaderboardEntryResponse) for r in rows]
    winner = standings[0].user_id if standings and standings[0].rank == 1 else None
    return TournamentCycleCompletedEvent(
        cycle_id=cycle_id,
        category_id=category_id,
        standings=standings,
        winner_user_id=winner,
    )


async def _write_drained_results_row(
    repository: TournamentRepository,
    edition_id: int,
    *,
    conn: Connection,
) -> None:
    """Shared drained-path: compute results from the live leaderboard, write the row, complete.

    The single source of truth for the "results actually publish, deferred" branch,
    called by BOTH the poller's drain detection
    (:func:`process_awaiting_results_editions`) and the admin force-publish service
    method (D-03) so the two cannot diverge. For each child cycle it builds a
    :class:`TournamentCycleCompletedEvent` from the live leaderboard, writes ONE
    ``edition_results`` outbox row (Pitfall 3 — the existing publish-before-mark
    machinery drains it next tick), and flips the edition + its cycles to
    ``completed``.

    The XP grants are NOT run here: the deferred results ride an outbox row, and
    the SAME poll loop runs the grant loop (``award_cycle_placements`` per cycle +
    ``award_edition_streaks`` once per edition) when it drains that row (exactly like
    an ``edition_rollover`` row). Granting here too would double-grant within one
    tick. Keeping the grant on the row-drain path preserves the load-bearing
    invariant (module docstring 21-38): grant + publish + mark are one transaction
    and re-poll re-attempts the whole unit, ledger-idempotent.

    Args:
        repository: Tournament repository.
        edition_id: The edition whose results are publishing.
        conn: Active connection inside an open transaction.
    """
    children = await repository.fetch_edition_child_cycles(edition_id, conn=conn)  # type: ignore[arg-type]
    results: list[TournamentCycleCompletedEvent] = [
        await _build_cycle_completed_event(repository, child["id"], child["category_id"], conn=conn)
        for child in children
    ]
    # Deferred results go through an outbox row (Pitfall 3): the same poll loop
    # drains+publishes it next tick at tournament:results:{edition_id} AND runs the
    # grant loop then, preserving at-least-once. No now() / message-id churn here.
    results_event = TournamentEditionResultsEvent(edition_id=edition_id, results=results)
    await repository.create_pending_transition(
        None,
        "edition_results",
        msgspec.json.encode(results_event).decode(),
        edition_id=edition_id,
        conn=conn,  # type: ignore[arg-type]
    )
    await repository.complete_edition(edition_id, conn=conn)  # type: ignore[arg-type]
    log.info("[✓] drained results row written for edition %s (%d cycles)", edition_id, len(results))


async def process_awaiting_results_editions(
    conn: Connection,
    repository: TournamentRepository,
    service: TournamentOutboxService,
    reward_service: TournamentRewardService,
) -> None:
    """Publish the start or drained results together with edition state and rewards."""
    editions = await repository.fetch_awaiting_results_editions(conn=conn)  # type: ignore[arg-type]
    for edition in editions:
        edition_id = edition["id"]
        inflight = await repository.count_inflight_verifications(edition_id, conn=conn)  # type: ignore[arg-type]
        start_announced = edition["start_announced"]

        # The boundary cron created the NEXT edition (status='active') with its child
        # cycles; ride that new tournament's cycle info on the rollover card so the bot
        # can render the "new cycle" section (Bug #1). Empty when paused/hiatus -> the
        # card reads ended-only without crashing.
        started_rows = await repository.fetch_active_edition_started_cycles(conn=conn)  # type: ignore[arg-type]
        started = [
            TournamentCycleStartedEvent(
                cycle_id=row["cycle_id"],
                category_id=row["category_id"],
                map_id=row["map_id"],
                map_code=row["map_code"],
                map_name=row["map_name"],
                started_at=row["started_at"],
                ends_at=row["ends_at"],
            )
            for row in started_rows
        ]

        if not start_announced and inflight > 0:
            # First tick with pending verifications: start-only, hold the champion
            # role (empty results -> bot skips transfer, D-05), NO grants.
            rollover = TournamentRolloverEvent(
                edition_id=edition_id,
                results=[],
                started=started,
                results_pending=True,
            )
            # State and durable delivery either commit together or both roll back.
            await repository.mark_edition_start_announced(edition_id, conn=conn)  # type: ignore[arg-type]
            await service.enqueue(
                conn=conn,
                routing_key="api.tournament.rollover",
                data=rollover,
                headers=Headers({}),
                idempotency_key=f"tournament:rollover:{edition_id}",
                entity_key="tournament:announcements",
            )
            log.info("[→] start-only rollover (edition %s, results pending)", edition_id)
            continue

        if not start_announced and inflight == 0:
            # First tick, no pending: combined results + completion (the common
            # case). Compute + grant + publish ONE combined rollover, then complete.
            children = await repository.fetch_edition_child_cycles(edition_id, conn=conn)  # type: ignore[arg-type]
            results: list[TournamentCycleCompletedEvent] = []
            for child in children:
                entry = await _build_cycle_completed_event(repository, child["id"], child["category_id"], conn=conn)
                results.append(entry)
                await reward_service.award_cycle_placements(entry, conn=conn)  # type: ignore[arg-type]
            await reward_service.award_edition_streaks(results, conn=conn)
            rollover = TournamentRolloverEvent(
                edition_id=edition_id,
                results=results,
                started=started,
                results_pending=False,
            )
            await service.enqueue(
                conn=conn,
                routing_key="api.tournament.rollover",
                data=rollover,
                headers=Headers({}),
                idempotency_key=f"tournament:rollover:{edition_id}",
                entity_key="tournament:announcements",
            )
            await repository.complete_edition(edition_id, conn=conn)  # type: ignore[arg-type]
            log.info("[→] combined rollover (edition %s, %d results)", edition_id, len(results))
            continue

        if inflight == 0:
            # Later tick, results still owed, queue now drained: write the deferred
            # edition_results outbox row (drained+published+granted next tick) and
            # complete. The grant loop runs when the SAME poll loop drains the row.
            await _write_drained_results_row(repository, edition_id, conn=conn)
            continue

        # start_announced AND pending > 0: still draining, nothing to do this tick.
        log.debug("[!] edition %s still draining (%d pending)", edition_id, inflight)
