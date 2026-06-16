"""Skill-recompute event listener (in-process, D-01/D-04)."""

from __future__ import annotations

import logging

import sentry_sdk
from litestar.events import listener

from events.schemas import SkillRecomputeRequestedEvent
from services.skill_service import SkillService, TriggerDescriptor

log = logging.getLogger(__name__)


@listener("skill.recompute.requested")
async def handle_skill_recompute(event: SkillRecomputeRequestedEvent, skill_service: SkillService) -> None:
    """Recompute the whole skill snapshot in the background (D-04).

    Fired in-process after a verification-state change commits (D-01/D-02). Runs the
    single full-rebuild routine shared with the nightly poller and the PATCH path
    (D-04). This is NOT a RabbitMQ publish, so ``X-PYTEST-ENABLED=1`` does not gate
    it — tests can emit and assert a recompute deterministically.

    The ``recompute_all`` call is wrapped so a failed recompute (e.g. a transient
    DB error or the app pool drained at shutdown) is logged rather than silently
    dropped — the snapshot would otherwise stay stale until the next event or the
    04:00 UTC nightly backstop self-heals it. We log and continue (no re-raise) so
    a dropped recompute never crashes the event loop (WR-03).

    The typed cause descriptor (D-10) is carried on the event (``cause_category`` +
    ``actor_user_id``) and threaded into ``recompute_all`` so the service resolves the
    per-user cause policy (PLAYER_ACTION actor / MAP_ENVIRONMENT bystanders / SYSTEM
    coalesced) from the typed accumulator — never by parsing the ``reason`` string.

    Args:
        event: The recompute-requested event (log reason + typed cause descriptor).
        skill_service: DI-injected skill service.
    """
    log.debug(
        "[skill] recompute requested (reason=%s, cause=%s, actor=%s)",
        event.reason,
        event.cause_category,
        event.actor_user_id,
    )
    descriptor = TriggerDescriptor(cause_category=event.cause_category, actor_user_id=event.actor_user_id)
    try:
        await skill_service.recompute_all(descriptor)
    except Exception as e:
        # Log and continue: the nightly backstop + the next event self-heal the
        # snapshot, so a single dropped recompute must not crash the event loop.
        # Still report to Sentry (WR-02): a persistently failing recompute (missing
        # weight row, schema drift) would otherwise leave the snapshot stale with no
        # monitoring signal until the nightly backstop runs.
        log.exception("[!] skill recompute (reason=%s) failed", event.reason)
        sentry_sdk.capture_exception(e)
