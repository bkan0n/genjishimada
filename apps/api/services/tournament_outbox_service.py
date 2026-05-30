"""Outbox->RabbitMQ bridge for tournament cycle transition events.

The pg_cron transition function writes ``tournaments.pending_transitions`` rows
(the transactional outbox). This module's :func:`publish_pending_transitions`
poll-publish-mark loop body reads unpublished rows under
``FOR UPDATE SKIP LOCKED``, publishes each to its ``api.tournament.*`` routing
key via :meth:`BaseService.publish_message`, and marks it published in the same
transaction. Publish happens BEFORE mark so a crash between the two re-publishes
on the next poll (at-least-once, D-11); cycle-scoped idempotency keys make the
duplicates harmless downstream.
"""

from __future__ import annotations

from logging import getLogger
from typing import TYPE_CHECKING

import msgspec
from asyncpg import Pool
from genjishimada_sdk.tournaments import (
    TournamentCycleCompletedEvent,
    TournamentCycleStartedEvent,
)
from litestar.datastructures import Headers, State

from repository.lootbox_repository import LootboxRepository
from repository.tournaments_repository import TournamentRepository
from services.base import BaseService
from services.lootbox_service import LootboxService
from services.tournament_reward_service import TournamentRewardService

if TYPE_CHECKING:
    from genjishimada_sdk.xp import XpGrantEvent

log = getLogger(__name__)

# Maps the pending_transitions.event_type CHECK values to their routing key and
# SDK event struct. The struct field names are the canonical contract that the
# SQL jsonb_build_object payload keys must match (Pitfall 5 — drift surfaces as
# an immediate msgspec.convert error rather than a silently shipped bad event).
_EVENT_ROUTING: dict[str, tuple[str, type[msgspec.Struct]]] = {
    "cycle_started": ("api.tournament.cycle_started", TournamentCycleStartedEvent),
    "cycle_completed": ("api.tournament.cycle_completed", TournamentCycleCompletedEvent),
}


class TournamentOutboxService(BaseService):
    """Service that bridges tournament outbox rows to RabbitMQ.

    Extends :class:`BaseService` purely to inherit ``publish_message`` (and its
    ``public.jobs`` record + idempotency handling). The poll loop lives in the
    module-level :func:`publish_pending_transitions` so it can be driven by the
    ``tournament_outbox_poller`` lifespan task in ``app.py``.
    """


def _build_event(row: dict) -> tuple[str, msgspec.Struct]:
    """Convert an outbox row's payload into its routing key and SDK event struct.

    Args:
        row: A ``tournaments.pending_transitions`` row dict. ``event_type`` is the
            CHECK-constrained discriminator; ``payload`` is already a Python dict
            via the jsonb<->msgspec codec registered in ``app.py``.

    Returns:
        A ``(routing_key, event)`` tuple ready for ``publish_message``.

    Raises:
        KeyError: If ``event_type`` is not a known transition type.
        msgspec.ValidationError: If the payload does not match the struct shape
            (Pitfall 5 — keeps a malformed payload row unpublished).
    """
    routing_key, struct_type = _EVENT_ROUTING[row["event_type"]]
    event = msgspec.convert(row["payload"], struct_type)
    return routing_key, event


async def publish_pending_transitions(state: State) -> None:
    """Publish all unpublished outbox transitions, marking each published.

    Selects unpublished rows under ``FOR UPDATE SKIP LOCKED`` inside one
    transaction (D-11, no multi-instance double-publish), then for each row:
    builds its SDK event struct, publishes to the matching ``api.tournament.*``
    routing key with a cycle-scoped idempotency key, and marks the row published
    in the SAME transaction. Publish precedes mark so a crash between them
    re-publishes on the next poll (at-least-once).

    Each ``publish_message`` writes a ``public.jobs`` row; a re-publish creates a
    new one (acceptable for an outbox/at-least-once design). Per-row failures
    propagate: the ``tournament_outbox_poller`` lifespan loop logs and retries
    the whole batch on the next tick, and the unmarked row is re-attempted.

    Args:
        state: Application state holding ``db_pool`` (acquires its own connection,
            never a request-scoped one) and ``mq_channel_pool``.
    """
    pool: Pool = state.db_pool
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

            # RWD-02/04/05: on a finalizing cycle, grant placement + streak rewards
            # and reset non-participant streaks INSIDE this outbox transaction
            # (Option A) before the publish/mark. award_cycle_end is replay-safe via
            # the 08-01 ledger, so a re-delivered cycle_completed row grants no
            # duplicate XP. No second scheduler — this rides the ~10s poller.
            # The non-idempotent xp.grant NOTIFICATIONS are collected and published
            # only AFTER this transaction commits (CR-02): a rollback (e.g. a
            # mark_transition_published failure) must not notify the bot about XP
            # that rolled back and will be re-granted on the next poll.
            if row["event_type"] == "cycle_completed" and isinstance(event, TournamentCycleCompletedEvent):
                pending_xp_events += await reward_service.award_cycle_end(event, conn=conn)  # type: ignore[arg-type]
                await _reset_non_participant_streaks(repository, event, conn=conn)  # type: ignore[arg-type]
                log.info("[✓] cycle-end rewards processed for cycle %s", event.cycle_id)

            # The api.tournament.* event is idempotent (cycle-scoped key) and rides
            # the existing at-least-once outbox contract, so it stays inside the
            # transaction (publish-before-mark). Only the xp.grant events defer.
            await service.publish_message(
                routing_key=routing_key,
                data=event,
                headers=Headers({}),
                idempotency_key=f"tournament:{row['event_type']}:{row['cycle_id']}",
            )
            await repository.mark_transition_published(row["id"], conn=conn)  # type: ignore[arg-type]
            log.info("[→] published %s for cycle %s", row["event_type"], row["cycle_id"])

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
