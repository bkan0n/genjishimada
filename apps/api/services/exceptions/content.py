"""Domain exceptions for the content domain.

These exceptions represent business rule violations.
They are raised by services and caught by controllers.
"""

from __future__ import annotations

from utilities.errors import DomainError


class ContentError(DomainError):
    """Base exception for the content domain."""


class CategoryNotFoundError(ContentError):
    """Category with the given ID does not exist."""


class DifficultyNotFoundError(ContentError):
    """Difficulty with the given ID does not exist."""


class DuplicateNameError(ContentError):
    """A category or difficulty with the given name already exists."""


class TechniqueNotFoundError(ContentError):
    """Technique with the given ID does not exist."""
