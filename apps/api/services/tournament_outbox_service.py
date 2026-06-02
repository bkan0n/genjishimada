"""Outbox->RabbitMQ bridge for the combined tournament edition-rollover event.

The pg_cron transition function writes ONE ``tournaments.pending_transitions``
row per rollover (the transactional outbox) with ``event_type='edition_rollover'``
and a combined payload ``{results, started, edition_id}`` (D-09). This module's
:func:`publish_pending_transitions` poll-publish-mark loop reads unpublished rows
under ``FOR UPDATE SKIP LOCKED``, converts each into one
:class:`TournamentRolloverEvent`, publishes it to ``api.tournament.rollover`` via
:meth:`BaseService.publish_message` with the edition-scoped idempotency key
``tournament:rollover:{edition_id}`` (D-11), and marks the row published in the
SAME transaction. Publish happens BEFORE mark so a crash between the two
re-publishes on the next poll (at-least-once, D-11); the stable idempotency key
makes the duplicates harmless downstream.

The reward/streak side effects (``award_cycle_end`` +
``_reset_non_participant_streaks``) run once PER CHILD CYCLE — i.e. once per
``event.results`` entry, keyed on ``entry.cycle_id`` (Pattern 4) — NOT once per
edition. The XP grant ledger (``UNIQUE(cycle_id, user_id, reason)``) is the real
double-grant guard, so a re-delivered rollover grants no duplicate XP.

WHY THE GRANTS STAY INSIDE THE OUTBOX TRANSACTION (deliberate, not an oversight):
the XP grant, the ``publish_message``, and ``mark_transition_published`` are
coupled in ONE transaction on purpose. Decoupling the grants to a post-commit
step would break the per-cycle grant-once guarantee: if the row were marked
published (so it never re-polls) but the process died before a post-commit grant
ran, the XP would be permanently lost with no replay. Keeping them transactional
means a ``mark_transition_published`` rollback also rolls back the grant, and the
next poll re-attempts the whole unit. The grant itself is idempotent via the
ledger, so the at-least-once re-poll is harmless. Only the NON-idempotent
``xp.grant`` notifications are deferred to after commit (``pending_xp_events``):
a notification cannot be un-sent, so it must never fire for XP that rolled back.
The transaction does hold the ``FOR UPDATE SKIP LOCKED`` locks for the duration
of the grants (O(N categories x M participants) round-trips); this is bounded in
practice by the small per-edition category/participant counts and is the accepted
cost of the correctness coupling above. If participant counts ever grow large
enough to threaten the poller's transaction window, the right fix is batching the
grant queries (set-based INSERT ... SELECT into the ledger) — NOT moving them out
of the transaction.
"""

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

if TYPE_CHECKING:
    from asyncpg import Connection
    from genjishimada_sdk.xp import XpGrantEvent

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
    """Service that bridges tournament outbox rows to RabbitMQ.

    Extends :class:`BaseService` purely to inherit ``publish_message`` (and its
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

    ``edition_rollover`` -> ``tournament:rollover:{edition_id}`` (D-11);
    ``edition_results`` -> ``tournament:results:{edition_id}`` (Phase 12.1, D-09).
    Both keys are edition-scoped so a re-delivered message cannot double-grant XP
    or double-transfer the champion role.

    Args:
        event_type: The outbox row's ``event_type`` discriminator.
        edition_id: The edition the event belongs to.

    Returns:
        The idempotency key string.
    """
    prefix = "results" if event_type == "edition_results" else "rollover"
    return f"tournament:{prefix}:{edition_id}"


async def publish_pending_transitions(state: State) -> None:
    """Publish all unpublished outbox transitions, marking each published.

    Selects unpublished rows under ``FOR UPDATE SKIP LOCKED`` inside one
    transaction (D-11, no multi-instance double-publish), GROUPS them by
    ``(event_type, created_at)`` (one rotation), then for each group: builds ONE
    combined batch event wrapping every per-cycle event, publishes it to the
    plural ``api.tournament.cycles_*`` routing key with a rotation-scoped
    idempotency key, and marks EVERY row in the group published in the SAME
    transaction. Publish precedes mark so a crash between them re-publishes on the
    next poll (at-least-once).

    The reward side effects (``award_cycle_end`` + the non-participant streak
    reset) run ONCE PER CHILD CYCLE — once per ``event.results`` entry, keyed on
    ``entry.cycle_id`` (Pattern 4) — NOT once per edition.

    Each ``publish_message`` writes a ``public.jobs`` row; a re-publish creates a
    new one (acceptable for an outbox/at-least-once design). Failures propagate:
    the ``tournament_outbox_poller`` lifespan loop logs and retries the whole
    batch on the next tick, and the unmarked rows are re-attempted.

    Args:
        state: Application state holding ``db_pool`` (acquires its own connection,
            never a request-scoped one) and ``mq_channel_pool``.
    """
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
    pending_xp_events: list[XpGrantEvent] = []
    async with pool.acquire() as conn, conn.transaction():
        # (1) Drain-aware results computation for awaiting_results editions (D-07).
        # This runs INSIDE the same transaction as the outbox drain below so the
        # edition flip + the edition_results outbox-row write (the deferred path)
        # + any grants are one atomic unit (Pitfall 3 — at-least-once preserved).
        pending_xp_events += await process_awaiting_results_editions(
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

            # RWD-02/04/05: grant placement + streak rewards and reset
            # non-participant streaks INSIDE this outbox transaction (Option A)
            # before the publish/mark. These run ONCE PER CHILD CYCLE — once per
            # results entry, keyed on entry.cycle_id (Pattern 4 — NOT re-keyed to
            # the edition). award_cycle_end is replay-safe via the 08-01 ledger, so
            # a re-delivered edition_rollover grants no duplicate XP. The
            # non-idempotent xp.grant NOTIFICATIONS are collected and published only
            # AFTER this transaction commits (CR-02): a rollback (e.g. a
            # mark_transition_published failure) must not notify the bot about XP
            # that rolled back and will be re-granted on the next poll.
            for entry in event.results:
                pending_xp_events += await reward_service.award_cycle_end(entry, conn=conn)  # type: ignore[arg-type]
                await _reset_non_participant_streaks(repository, entry, conn=conn)  # type: ignore[arg-type]
                log.info("[✓] cycle-end rewards processed for cycle %s (edition %s)", entry.cycle_id, edition_id)

            # ONE combined publish per row, then mark it published — all inside this
            # transaction (publish-before-mark = at-least-once). The edition-scoped
            # idempotency key (rollover OR results) dedupes re-publishes downstream.
            await service.publish_message(
                routing_key=routing_key,
                data=event,
                headers=Headers({}),
                idempotency_key=_idempotency_key(row["event_type"], edition_id),
            )
            await repository.mark_transition_published(row["id"], conn=conn)  # type: ignore[arg-type]
            log.info(
                "[→] published %s (edition %s: %d results)",
                row["event_type"],
                edition_id,
                len(event.results),
            )

    # Transaction committed: publish the deferred, non-idempotent XP grant
    # notifications. Best-effort (the XP is already durably persisted).
    await reward_service.publish_xp_events(pending_xp_events)


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
    the SAME poll loop runs the grant loop (``award_cycle_end`` +
    ``_reset_non_participant_streaks``) when it drains that row (exactly like an
    ``edition_rollover`` row). Granting here too would double-grant within one
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
) -> list[XpGrantEvent]:
    """Run the D-07 three-branch drain state machine for awaiting_results editions.

    Called INSIDE :func:`publish_pending_transitions`' open transaction. For each
    ``awaiting_results`` edition (locked ``FOR UPDATE SKIP LOCKED``, oldest first)
    it counts in-flight verifications and branches:

    * **first tick, pending == 0** (``start_announced`` is FALSE) — compute results
      from the live leaderboard, grant XP, publish ONE combined
      :class:`TournamentRolloverEvent` (``results_pending=False``) inline with the
      edition-scoped idempotency key, and flip the edition + cycles to
      ``completed``.
    * **first tick, pending > 0** — publish a start-only
      :class:`TournamentRolloverEvent` (``results_pending=True``, empty
      ``results`` so the bot holds the champion role, D-05), set
      ``start_announced``, and leave the edition ``awaiting_results`` (NO grants).
    * **later tick, drained** (``start_announced`` is TRUE, pending == 0) — defer
      to :func:`_publish_drained_results`: write an ``edition_results`` outbox row
      (drained+published by the same loop on the next tick) and flip to
      ``completed``.

    A re-poll after completion finds no ``awaiting_results`` edition, so nothing
    re-grants; ``award_cycle_end`` is itself ledger-idempotent as a second guard.

    Args:
        conn: Active outbox connection inside an open transaction.
        repository: Tournament repository.
        service: The outbox service (for the inline start/combined publish).
        reward_service: Reward service (grant loop).

    Returns:
        Deferred Xp grant notifications to publish AFTER the caller commits.
    """
    pending_xp_events: list[XpGrantEvent] = []
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
            # Mark FIRST (inside the transaction), then publish (CR-01/CR-02). publish_message
            # opens its own channel and does NOT join this conn's transaction, so if it
            # succeeded BEFORE the mark and the mark then raised, the transaction would roll
            # back start_announced and the next tick would re-publish the start-only rollover
            # with a fresh public.jobs UUID (new message_id), defeating the bot's idempotency
            # claim and double-announcing the start. Marking first guarantees that once the
            # transaction commits, start_announced is set; a publish failure after the mark
            # simply rolls back the mark too, so the pair stays atomic.
            await repository.mark_edition_start_announced(edition_id, conn=conn)  # type: ignore[arg-type]
            await service.publish_message(
                routing_key="api.tournament.rollover",
                data=rollover,
                headers=Headers({}),
                idempotency_key=f"tournament:rollover:{edition_id}",
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
                pending_xp_events += await reward_service.award_cycle_end(entry, conn=conn)  # type: ignore[arg-type]
                await _reset_non_participant_streaks(repository, entry, conn=conn)  # type: ignore[arg-type]
            rollover = TournamentRolloverEvent(
                edition_id=edition_id,
                results=results,
                started=started,
                results_pending=False,
            )
            await service.publish_message(
                routing_key="api.tournament.rollover",
                data=rollover,
                headers=Headers({}),
                idempotency_key=f"tournament:rollover:{edition_id}",
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

    return pending_xp_events


async def _reset_non_participant_streaks(
    repository: TournamentRepository,
    event: TournamentCycleCompletedEvent,
    *,
    conn: object,
) -> None:
    """Reset streaks to 0 for every tracked user who did not participate this cycle.

    award_cycle_end advances streaks only for the finalizing cycle's participants
    (it cannot see the full tracked-user set). This sweep — owned by 08-03 — closes
    that gap: it reads the full streak roster via fetch_all_streak_user_ids (08-01)
    and calls advance_streak(participated=False) for every tracked user NOT in
    fetch_cycle_participants, resetting current_streak to 0 and stamping
    last_cycle_id. The advance_streak ``last_cycle_id IS DISTINCT FROM`` guard keeps
    the multi-category dedupe intact (a participant already stamped with this cycle
    is never reset here because they are excluded as a participant).

    Args:
        repository: Tournament repository (streak roster + participants + advance).
        event: Cycle-completed event carrying the finalizing cycle_id.
        conn: Active outbox connection for transactional participation.
    """
    all_tracked = set(await repository.fetch_all_streak_user_ids(conn=conn))  # type: ignore[arg-type]
    participants = set(await repository.fetch_cycle_participants(event.cycle_id, conn=conn))  # type: ignore[arg-type]
    non_participants = all_tracked - participants
    for user_id in non_participants:
        await repository.advance_streak(user_id, event.cycle_id, False, conn=conn)  # type: ignore[arg-type]
        log.debug("[!] streak reset to 0 for non-participant %s (cycle %s)", user_id, event.cycle_id)
