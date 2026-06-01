"""Outbox->RabbitMQ bridge for tournament cycle transition events.

The pg_cron transition function writes ``tournaments.pending_transitions`` rows
(the transactional outbox). A single rotation can write one ``cycle_started`` +
one ``cycle_completed`` row per due category, all sharing the SAME transaction
``created_at``. This module's :func:`publish_pending_transitions`
poll-publish-mark loop reads unpublished rows under ``FOR UPDATE SKIP LOCKED``,
GROUPS them by ``(event_type, created_at)``, publishes ONE combined batch event
per group to its plural ``api.tournament.cycles_*`` routing key via
:meth:`BaseService.publish_message`, and marks every row in the group published
in the same transaction. Publish happens BEFORE mark so a crash between the two
re-publishes on the next poll (at-least-once, D-11); the rotation-scoped
idempotency key (``tournament:{event_type}:{created_at_iso}``) makes the
duplicates harmless downstream.

The per-cycle XP/streak side effects (``award_cycle_end`` +
``_reset_non_participant_streaks``) still run once PER ROW (per cycle), not per
group — the grouping is purely a publish/render concern.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from logging import getLogger
from typing import TYPE_CHECKING

import msgspec
from asyncpg import Pool
from genjishimada_sdk.tournaments import (
    TournamentCycleCompletedEvent,
    TournamentCyclesCompletedEvent,
    TournamentCyclesStartedEvent,
    TournamentCycleStartedEvent,
)
from litestar.datastructures import Headers, State

from repository.lootbox_repository import LootboxRepository
from repository.tournaments_repository import TournamentRepository
from services.base import BaseService
from services.lootbox_service import LootboxService
from services.tournament_reward_service import TournamentRewardService

if TYPE_CHECKING:
    import datetime as dt

    from genjishimada_sdk.xp import XpGrantEvent

log = getLogger(__name__)

# Maps the pending_transitions.event_type CHECK values to the PLURAL (batch)
# routing key and the batch SDK event struct that wraps a list of per-cycle
# events. The per-cycle struct (used to convert each row's payload) is resolved
# via _SINGLE_EVENT_STRUCT. Drift between SQL jsonb_build_object payload keys and
# the per-cycle struct surfaces as an immediate msgspec.convert error rather than
# a silently shipped bad event (Pitfall 5).
_EVENT_ROUTING: dict[str, tuple[str, type[msgspec.Struct]]] = {
    "cycle_started": ("api.tournament.cycles_started", TournamentCyclesStartedEvent),
    "cycle_completed": ("api.tournament.cycles_completed", TournamentCyclesCompletedEvent),
}

# Maps each event_type to the SINGLE-cycle struct used to convert one row's
# payload before it is appended to a batch group's ``cycles`` list.
_SINGLE_EVENT_STRUCT: dict[str, type[msgspec.Struct]] = {
    "cycle_started": TournamentCycleStartedEvent,
    "cycle_completed": TournamentCycleCompletedEvent,
}


@dataclass
class _TransitionGroup:
    """Accumulator for one ``(event_type, created_at)`` rotation group.

    Attributes:
        events: Per-cycle SDK events that share one rotation transaction.
        row_ids: Outbox row ids backing ``events`` (all marked published together).
    """

    events: list[msgspec.Struct] = field(default_factory=list)
    row_ids: list[int] = field(default_factory=list)


class TournamentOutboxService(BaseService):
    """Service that bridges tournament outbox rows to RabbitMQ.

    Extends :class:`BaseService` purely to inherit ``publish_message`` (and its
    ``public.jobs`` record + idempotency handling). The poll loop lives in the
    module-level :func:`publish_pending_transitions` so it can be driven by the
    ``tournament_outbox_poller`` lifespan task in ``app.py``.
    """


def _build_event(row: dict) -> tuple[str, msgspec.Struct]:
    """Convert an outbox row's payload into its routing key and per-cycle event.

    The returned ``routing_key`` is the PLURAL (batch) routing key for the row's
    ``event_type``; the returned ``event`` is the SINGLE-cycle struct decoded from
    this row's payload (one batch event later wraps a list of these). Grouping and
    batch-event construction happen in :func:`publish_pending_transitions`.

    Args:
        row: A ``tournaments.pending_transitions`` row dict. ``event_type`` is the
            CHECK-constrained discriminator; ``payload`` is already a Python dict
            via the jsonb<->msgspec codec registered in ``app.py``.

    Returns:
        A ``(routing_key, per_cycle_event)`` tuple. ``routing_key`` is the plural
        batch key; ``per_cycle_event`` is a single-cycle SDK struct.

    Raises:
        KeyError: If ``event_type`` is not a known transition type.
        msgspec.ValidationError: If the payload does not match the struct shape
            (Pitfall 5 — keeps a malformed payload row unpublished).
    """
    routing_key, _batch_struct = _EVENT_ROUTING[row["event_type"]]
    struct_type = _SINGLE_EVENT_STRUCT[row["event_type"]]
    event = msgspec.convert(row["payload"], struct_type)
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

    The per-cycle reward side effects (``award_cycle_end`` + the non-participant
    streak reset) still run ONCE PER ROW (per cycle), independent of grouping.

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
    # Group key -> accumulated per-cycle events + the row ids backing them. One
    # group == one (event_type, created_at) rotation, published as ONE batch event.
    groups: dict[tuple[str, dt.datetime], _TransitionGroup] = {}
    async with pool.acquire() as conn, conn.transaction():
        rows = await repository.fetch_unpublished_transitions(conn=conn)  # type: ignore[arg-type]
        for row in rows:
            _routing_key, event = _build_event(row)

            # RWD-02/04/05: on a finalizing cycle, grant placement + streak rewards
            # and reset non-participant streaks INSIDE this outbox transaction
            # (Option A) before the publish/mark. These run ONCE PER CYCLE (per row),
            # NOT per group. award_cycle_end is replay-safe via the 08-01 ledger, so a
            # re-delivered cycle_completed row grants no duplicate XP. No second
            # scheduler — this rides the ~10s poller. The non-idempotent xp.grant
            # NOTIFICATIONS are collected and published only AFTER this transaction
            # commits (CR-02): a rollback (e.g. a mark_transition_published failure)
            # must not notify the bot about XP that rolled back and will be re-granted
            # on the next poll.
            if row["event_type"] == "cycle_completed" and isinstance(event, TournamentCycleCompletedEvent):
                pending_xp_events += await reward_service.award_cycle_end(event, conn=conn)  # type: ignore[arg-type]
                await _reset_non_participant_streaks(repository, event, conn=conn)  # type: ignore[arg-type]
                log.info("[✓] cycle-end rewards processed for cycle %s", event.cycle_id)

            # Accumulate this row's per-cycle event into its (event_type, created_at)
            # group so all categories that rotated together ship as ONE batch event.
            key = (row["event_type"], row["created_at"])
            group = groups.setdefault(key, _TransitionGroup(events=[], row_ids=[]))
            group.events.append(event)
            group.row_ids.append(row["id"])

        # One combined publish per group, then mark EVERY row in the group published
        # — all inside this transaction (publish-before-mark = at-least-once). The
        # rotation-scoped idempotency key dedupes re-publishes downstream.
        for (event_type, created_at), group in groups.items():
            routing_key, batch_struct = _EVENT_ROUTING[event_type]
            batch_event = batch_struct(cycles=group.events)  # type: ignore[call-arg]
            await service.publish_message(
                routing_key=routing_key,
                data=batch_event,
                headers=Headers({}),
                idempotency_key=f"tournament:{event_type}:{created_at.isoformat()}",
            )
            for row_id in group.row_ids:
                await repository.mark_transition_published(row_id, conn=conn)  # type: ignore[arg-type]
            log.info(
                "[→] published %s batch (%d cycles) for rotation %s",
                event_type,
                len(group.events),
                created_at.isoformat(),
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
