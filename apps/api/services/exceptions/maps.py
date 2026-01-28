"""Domain exceptions for maps.

These exceptions represent business rule violations.
They are raised by services and caught by controllers.
"""

from __future__ import annotations

from utilities.errors import DomainError


class MapsError(DomainError):
    """Base exception for maps domain."""


# Validation errors


class MapValidationError(MapsError):
    """Map validation failed."""

    def __init__(self, message: str, field: str = "unknown") -> None:
        super().__init__(message, field=field)


class MapCodeExistsError(MapsError):
    """Map code already exists."""

    def __init__(self, code: str) -> None:
        super().__init__(
            f"Provided code already exists: {code}",
            code=code,
        )


class MapNotFoundError(MapsError):
    """Map not found."""

    def __init__(self, code: str) -> None:
        super().__init__(
            f"No map found with code: {code}",
            code=code,
        )


class DuplicateMechanicError(MapsError):
    """Duplicate mechanic in request."""

    def __init__(self) -> None:
        super().__init__("You have a duplicate mechanic.")


class DuplicateRestrictionError(MapsError):
    """Duplicate restriction in request."""

    def __init__(self) -> None:
        super().__init__("You have a duplicate restriction.")


class DuplicateCreatorError(MapsError):
    """Duplicate creator ID in request."""

    def __init__(self) -> None:
        super().__init__("You have a duplicate creator ID.")


class CreatorNotFoundError(MapsError):
    """Creator user not found."""

    def __init__(self) -> None:
        super().__init__("There is no user associated with supplied ID.")


class GuideNotFoundError(MapsError):
    """Guide not found for user."""

    def __init__(self, code: str, user_id: int) -> None:
        super().__init__(
            f"No guide found for map {code} by user {user_id}",
            code=code,
            user_id=user_id,
        )


class DuplicateGuideError(MapsError):
    """User already has a guide for this map."""

    def __init__(self, code: str, user_id: int) -> None:
        super().__init__(
            f"User {user_id} already has a guide for map {code}",
            code=code,
            user_id=user_id,
        )


class AlreadyInPlaytestError(MapsError):
    """Map is already in playtest."""

    def __init__(self, code: str) -> None:
        super().__init__(
            f"Map {code} is already in playtest",
            code=code,
        )


class LinkedMapError(MapsError):
    """Error with linked map operation."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class MasteryUpdateFailedError(MapsError):
    """Mastery update failed."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"Mastery update failed: {reason}")


# Edit request errors


class PendingEditRequestExistsError(MapsError):
    """Map already has a pending edit request."""

    def __init__(self, code: str, existing_edit_id: int) -> None:
        super().__init__(
            f"There is already a pending edit request for map {code}",
            code=code,
            existing_edit_id=existing_edit_id,
        )


class EditRequestNotFoundError(MapsError):
    """Edit request not found."""

    def __init__(self, edit_id: int) -> None:
        super().__init__(
            f"Edit request {edit_id} not found",
            edit_id=edit_id,
        )


class InvalidEditResolutionError(MapsError):
    """Invalid edit request resolution."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
