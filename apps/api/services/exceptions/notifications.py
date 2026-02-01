"""Notifications domain exceptions.

These exceptions represent business rule violations in the notifications domain.
They are raised by NotificationsService and caught by controllers.
"""

from utilities.errors import DomainError


class NotificationsError(DomainError):
    """Base for notifications domain errors."""


class NotificationEventNotFoundError(NotificationsError):
    """Notification event does not exist."""

    def __init__(self, event_id: int) -> None:
        super().__init__("Notification event not found.", event_id=event_id)
