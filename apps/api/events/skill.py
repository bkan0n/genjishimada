"""Skill-recompute event listener (in-process, D-01/D-04)."""

from __future__ import annotations

import logging

from litestar.events import listener

from events.schemas import SkillRecomputeRequestedEvent
from services.skill_service import SkillService

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

    Args:
        event: The recompute-requested event (carries an optional log reason only).
        skill_service: DI-injected skill service.
    """
    log.debug("[skill] recompute requested (reason=%s)", event.reason)
    try:
        await skill_service.recompute_all()
    except Exception:
        # Log and continue: the nightly backstop + the next event self-heal the
        # snapshot, so a single dropped recompute must not crash the event loop.
        log.exception("[!] skill recompute (reason=%s) failed", event.reason)
