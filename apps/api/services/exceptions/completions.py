"""Completions domain exceptions.

These exceptions represent business rule violations in the completions domain.
They are raised by CompletionsService and caught by controllers.
"""

from utilities.errors import DomainError


class CompletionsError(DomainError):
    """Base for completions domain errors."""


class MapNotFoundError(CompletionsError):
    """Map code does not exist or has been archived."""

    def __init__(self, code: str) -> None:
        super().__init__("This map code does not exist or has been archived.", code=code)


class DuplicateCompletionError(CompletionsError):
    """User already has a completion for this map."""

    def __init__(self, user_id: int, map_code: str) -> None:
        super().__init__("You already have a completion for this map.", user_id=user_id, map_code=map_code)


class SlowerThanPendingError(CompletionsError):
    """New submission is slower than pending verification."""

    def __init__(self, new_time: float, pending_time: float) -> None:
        super().__init__(
            f"You already have a pending verification for this map with time {pending_time}s. "
            f"Your new submission ({new_time}s) must be faster. "
            f"Please wait for verification or submit a faster time.",
            new_time=new_time,
            pending_time=pending_time,
        )


class CompletionNotFoundError(CompletionsError):
    """Completion record does not exist."""

    def __init__(self, completion_id: int) -> None:
        super().__init__("Completion not found.", completion_id=completion_id)


class DuplicateVerificationError(CompletionsError):
    """Verification record already exists."""

    def __init__(self, completion_id: int) -> None:
        super().__init__("Verification record already exists.", completion_id=completion_id)


class DuplicateFlagError(CompletionsError):
    """Suspicious flag already exists."""

    def __init__(self, completion_id: int) -> None:
        super().__init__("This flag already exists.", completion_id=completion_id)


class DuplicateUpvoteError(CompletionsError):
    """User already upvoted this completion."""

    def __init__(self, user_id: int, message_id: int) -> None:
        super().__init__("User has already upvoted this completion.", user_id=user_id, message_id=message_id)


class DuplicateQualityVoteError(CompletionsError):
    """Quality vote already exists."""

    def __init__(self, user_id: int, map_id: int) -> None:
        super().__init__("Quality vote already exists.", user_id=user_id, map_id=map_id)
