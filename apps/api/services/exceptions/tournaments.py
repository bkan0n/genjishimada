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


class CycleAlreadyLiveError(TournamentsError):
    """A live or pending cycle already exists; the category cannot be bootstrapped.

    Raised when bootstrap is attempted but the category already has a cycle in
    active, finalizing, or pending status. Bootstrap only activates the FIRST
    cycle and must never double-start an already-running rotation.
    """

    def __init__(self, category_id: int, cycle_id: int) -> None:
        super().__init__(
            "Category already has a live or pending cycle; cannot bootstrap.",
            category_id=category_id,
            cycle_id=cycle_id,
        )


class DebugRouteDisabledError(TournamentsError):
    """The debug cycle-length override route is disabled in production."""

    def __init__(self) -> None:
        super().__init__("Debug cycle-length override is disabled in production.")


class NoActiveEditionError(TournamentsError):
    """No tournament edition is currently active (D-05).

    Raised when ``GET /editions/active`` is requested but no edition has status
    'active'. The shared grid-anchored timing (started_at/ends_at) only exists
    while an edition is running; controllers map this to HTTP 404.
    """

    def __init__(self) -> None:
        super().__init__("No active tournament edition exists.")


class NoAwaitingResultsEditionError(TournamentsError):
    """No edition is currently awaiting results (D-03).

    Raised by ``force_publish_results`` when the admin force-publish escape hatch
    is invoked but no edition has status ``'awaiting_results'`` — there is nothing
    to publish. Controllers map this to HTTP 409 (the same conflict shape as
    bootstrap's ``CycleAlreadyLiveError``).
    """

    def __init__(self) -> None:
        super().__init__("No edition is currently awaiting results.")


class InvalidTimezoneError(TournamentsError):
    """The supplied anchor timezone is not a known IANA timezone name (T-12-04).

    Validated against ``pg_timezone_names`` before persisting so an invalid value
    cannot reach the grid-boundary PL/pgSQL function (where ``AT TIME ZONE`` would
    raise on every cron tick and stall edition transitions).
    """

    def __init__(self, anchor_tz: str) -> None:
        super().__init__(f"Unknown timezone '{anchor_tz}'.", anchor_tz=anchor_tz)


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


class MapMismatchError(TournamentsError):
    """Map submitted does not match the cycle's assigned map."""

    def __init__(self, cycle_id: int, expected_map_id: int, submitted_map_id: int) -> None:
        super().__init__(
            f"Map mismatch: cycle {cycle_id} uses map {expected_map_id}, not {submitted_map_id}.",
            cycle_id=cycle_id,
            expected_map_id=expected_map_id,
            submitted_map_id=submitted_map_id,
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


class NoEligibleMapsError(TournamentsError):
    """No eligible maps found for the category's difficulty grouping."""

    def __init__(self, category_id: int) -> None:
        super().__init__(
            "No eligible maps found. Consider reducing blacklist_weeks or adding more maps "
            "matching the category's difficulties.",
            category_id=category_id,
        )


class PendingCycleAlreadyExistsError(TournamentsError):
    """A pending cycle already exists for this category."""

    def __init__(self, category_id: int) -> None:
        super().__init__(
            "A pending cycle already exists for this category. Use reroll to replace it.",
            category_id=category_id,
        )


class PendingCycleNotFoundError(TournamentsError):
    """No pending cycle exists for this category."""

    def __init__(self, category_id: int) -> None:
        super().__init__("No pending cycle exists for this category.", category_id=category_id)


class StreakNotFoundError(TournamentsError):
    """User tournament streak record does not exist."""

    def __init__(self, user_id: int) -> None:
        super().__init__("Tournament streak record not found.", user_id=user_id)


class TournamentCompletionNotFoundError(TournamentsError):
    """Tournament completion row does not exist."""

    def __init__(self, tournament_completion_id: int) -> None:
        super().__init__(
            "Tournament completion not found.",
            tournament_completion_id=tournament_completion_id,
        )


class AlreadyVerifiedError(TournamentsError):
    """A verified tournament completion cannot be rejected after the fact.

    A run that has already been verified (participation XP granted) cannot be
    silently reverted to unverified, because the XP grant is not reversed. The
    verdict is terminal once verified; controllers map this to HTTP 409 (CR-01).
    """

    def __init__(self, tournament_completion_id: int) -> None:
        super().__init__(
            "Tournament completion is already verified and cannot be rejected.",
            tournament_completion_id=tournament_completion_id,
        )
