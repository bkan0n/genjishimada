"""Completion-related event listeners."""

from __future__ import annotations

import logging

from litestar.events import listener

from events.schemas import OcrVerificationRequestedEvent
from services.completions_service import CompletionsService
from services.notifications_service import NotificationsService
from services.users_service import UsersService

log = logging.getLogger(__name__)


@listener("completion.ocr.requested")
async def handle_ocr_verification(
    event: OcrVerificationRequestedEvent,
    svc: CompletionsService,
    users: UsersService,
    notifications: NotificationsService,
) -> None:
    """Handle OCR auto-verification in background.

    Args:
        event: OCR verification request event.
        svc: Completions service.
        users: Users service.
        notifications: Notifications service.
    """
    await svc.attempt_auto_verify_async(
        completion_id=event.completion_id,
        user_id=event.user_id,
        code=event.code,
        time=event.time,
        screenshot=event.screenshot,
        users=users,
        notifications=notifications,
    )
