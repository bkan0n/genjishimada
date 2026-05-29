"""Tournaments domain exceptions.

These exceptions represent business rule violations in the tournaments domain.
They are raised by TournamentsService and caught by controllers.
"""

from utilities.errors import DomainError


class TournamentsError(DomainError):
    """Base for tournaments domain errors."""


class CategoryLockedError(TournamentsError):
    """Category cannot be modified while a cycle is active."""

    def __init__(self, category_id: int, cycle_id: int) -> None:
        super().__init__(
            "Category cannot be modified while a cycle is active.",
            category_id=category_id,
            cycle_id=cycle_id,
        )


class CategoryNameExistsError(TournamentsError):
    """A tournament category with this name already exists."""

    def __init__(self, name: str) -> None:
        super().__init__(f"A tournament category named '{name}' already exists.", name=name)


class CategoryNotFoundError(TournamentsError):
    """Tournament category does not exist."""

    def __init__(self, category_id: int) -> None:
        super().__init__("Tournament category not found.", category_id=category_id)


class CycleAlreadyActiveError(TournamentsError):
    """A cycle is already active for this category."""

    def __init__(self, category_id: int) -> None:
        super().__init__("A cycle is already active for this category.", category_id=category_id)


class CycleNotActiveError(TournamentsError):
    """Submission attempted on a non-active cycle."""

    def __init__(self, cycle_id: int, status: str) -> None:
        super().__init__(
            f"Cycle is not active (current status: {status}).",
            cycle_id=cycle_id,
            status=status,
        )


class CycleNotFoundError(TournamentsError):
    """Cycle does not exist."""

    def __init__(self, cycle_id: int) -> None:
        super().__init__("Cycle not found.", cycle_id=cycle_id)


class DuplicateTournamentCompletionError(TournamentsError):
    """User has already submitted a completion for this cycle."""

    def __init__(self, user_id: int, cycle_id: int) -> None:
        super().__init__(
            "User has already submitted a completion for this cycle.",
            user_id=user_id,
            cycle_id=cycle_id,
        )


class MapNotEligibleError(TournamentsError):
    """Map is not eligible for tournament selection."""

    def __init__(self, map_id: int, reason: str = "") -> None:
        message = "Map is not eligible for tournament selection."
        if reason:
            message = f"{message} {reason}"
        super().__init__(message, map_id=map_id, reason=reason)


class NoCycleActiveError(TournamentsError):
    """No active cycle exists for this category."""

    def __init__(self, category_id: int) -> None:
        super().__init__("No active cycle exists for this category.", category_id=category_id)
