"""Domain exceptions for tags.

These exceptions represent business rule violations.
They are raised by services and caught by controllers.
"""

from __future__ import annotations

from utilities.errors import DomainError


class TagsError(DomainError):
    """Base exception for tags domain."""


class TagNotFoundError(TagsError):
    """Tag does not exist."""

    def __init__(self, name: str) -> None:
        super().__init__(f"Tag not found: {name}", name=name)


class TagPermissionError(TagsError):
    """User does not have permission for this tag operation."""

    def __init__(self, name: str) -> None:
        super().__init__(f"No permission for tag: {name}", name=name)
