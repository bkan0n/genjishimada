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

import msgspec
from asyncpg import Pool
from genjishimada_sdk.tournaments import (
    TournamentCycleCompletedEvent,
    TournamentCycleStartedEvent,
)
from litestar.datastructures import Headers, State

from repository.tournaments_repository import TournamentRepository
from services.base import BaseService

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
    async with pool.acquire() as conn, conn.transaction():
        rows = await repository.fetch_unpublished_transitions(conn=conn)  # type: ignore[arg-type]
        for row in rows:
            routing_key, event = _build_event(row)
            await service.publish_message(
                routing_key=routing_key,
                data=event,
                headers=Headers({}),
                idempotency_key=f"tournament:{row['event_type']}:{row['cycle_id']}",
            )
            await repository.mark_transition_published(row["id"], conn=conn)  # type: ignore[arg-type]
            log.info("[→] published %s for cycle %s", row["event_type"], row["cycle_id"])
