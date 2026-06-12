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

    Args:
        event: The recompute-requested event (carries an optional log reason only).
        skill_service: DI-injected skill service.
    """
    log.debug("[skill] recompute requested (reason=%s)", event.reason)
    await skill_service.recompute_all()
