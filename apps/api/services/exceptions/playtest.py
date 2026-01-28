"""Domain exceptions for playtest operations.

These exceptions represent business rule violations in the playtest system.
They are raised by services and caught by controllers.
"""

from __future__ import annotations

from utilities.errors import DomainError


class PlaytestError(DomainError):
    """Base exception for playtest domain."""


class PlaytestNotFoundError(PlaytestError):
    """Playtest not found."""

    def __init__(self, thread_id: int) -> None:
        super().__init__(
            f"Playtest with thread ID {thread_id} not found",
            thread_id=thread_id,
        )


class VoteNotFoundError(PlaytestError):
    """User has no vote to remove."""

    def __init__(self, thread_id: int, user_id: int) -> None:
        super().__init__(
            f"User {user_id} has no vote for playtest {thread_id}",
            thread_id=thread_id,
            user_id=user_id,
        )


class VoteConstraintError(PlaytestError):
    """Vote failed constraint check."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class InvalidPatchError(PlaytestError):
    """Invalid playtest patch request."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class PlaytestStateError(PlaytestError):
    """Invalid playtest state transition."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
