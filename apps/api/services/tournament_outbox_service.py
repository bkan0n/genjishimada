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
from genjishimada_sdk.tournaments import TournamentRolloverEvent
from litestar.datastructures import Headers, State

from repository.lootbox_repository import LootboxRepository
from repository.tournaments_repository import TournamentRepository
from services.base import BaseService
from services.lootbox_service import LootboxService
from services.tournament_reward_service import TournamentRewardService

if TYPE_CHECKING:
    from genjishimada_sdk.tournaments import TournamentCycleCompletedEvent
    from genjishimada_sdk.xp import XpGrantEvent

log = getLogger(__name__)

# Single routing entry: the combined edition_rollover event collapses the former
# cycle_started/cycle_completed pair. The row's payload is converted directly into
# TournamentRolloverEvent; drift between the SQL jsonb_build_object payload keys
# and the struct surfaces as an immediate msgspec.convert error rather than a
# silently shipped bad event (Pitfall 5).
_EVENT_ROUTING: dict[str, tuple[str, type[msgspec.Struct]]] = {
    "edition_rollover": ("api.tournament.rollover", TournamentRolloverEvent),
}


class TournamentOutboxService(BaseService):
    """Service that bridges tournament outbox rows to RabbitMQ.

    Extends :class:`BaseService` purely to inherit ``publish_message`` (and its
    ``public.jobs`` record + idempotency handling). The poll loop lives in the
    module-level :func:`publish_pending_transitions` so it can be driven by the
    ``tournament_outbox_poller`` lifespan task in ``app.py``.
    """


def _build_event(row: dict) -> tuple[str, TournamentRolloverEvent]:
    """Convert an edition_rollover outbox row into its routing key and event.

    The returned ``routing_key`` is ``api.tournament.rollover``; the returned
    ``event`` is the combined :class:`TournamentRolloverEvent` decoded from this
    row's payload (one row == one combined event, D-09).

    Args:
        row: A ``tournaments.pending_transitions`` row dict. ``event_type`` is the
            CHECK-constrained discriminator; ``payload`` is already a Python dict
            via the jsonb<->msgspec codec registered in ``app.py``.

    Returns:
        A ``(routing_key, rollover_event)`` tuple.

    Raises:
        KeyError: If ``event_type`` is not a known transition type.
        msgspec.ValidationError: If the payload does not match the struct shape
            (Pitfall 5 — keeps a malformed payload row unpublished).
    """
    routing_key = _EVENT_ROUTING[row["event_type"]][0]
    event = msgspec.convert(row["payload"], TournamentRolloverEvent)
    return routing_key, event


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

            # ONE combined publish per edition_rollover row, then mark it published
            # — all inside this transaction (publish-before-mark = at-least-once).
            # The edition-scoped idempotency key dedupes re-publishes downstream.
            await service.publish_message(
                routing_key=routing_key,
                data=event,
                headers=Headers({}),
                idempotency_key=f"tournament:rollover:{edition_id}",
            )
            await repository.mark_transition_published(row["id"], conn=conn)  # type: ignore[arg-type]
            log.info(
                "[→] published edition_rollover (edition %s: %d results, %d started)",
                edition_id,
                len(event.results),
                len(event.started),
            )

    # Transaction committed: publish the deferred, non-idempotent XP grant
    # notifications. Best-effort (the XP is already durably persisted).
    await reward_service.publish_xp_events(pending_xp_events)


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
