"""Domain exceptions for change requests.

These exceptions represent business rule violations.
They are raised by services and caught by controllers.
"""

from __future__ import annotations

from utilities.errors import DomainError


class ChangeRequestsError(DomainError):
    """Base exception for change requests domain."""


class ChangeRequestAlreadyExistsError(ChangeRequestsError):
    """Change request already exists for this thread."""

    def __init__(self, thread_id: int) -> None:
        super().__init__(
            f"Change request already exists for thread {thread_id}",
            thread_id=thread_id,
        )


class MapNotFoundError(ChangeRequestsError):
    """Map not found."""

    def __init__(self, code: str) -> None:
        super().__init__(
            f"No map found with code: {code}",
            code=code,
        )
