"""Rank Card domain exceptions.

These exceptions represent business rule violations in the rank_card domain.
They are raised by RankCardService and caught by controllers.
"""

from utilities.errors import DomainError


class RankCardError(DomainError):
    """Base for rank_card domain errors."""
