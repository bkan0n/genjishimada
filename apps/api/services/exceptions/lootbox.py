"""Domain exceptions for lootbox.

These exceptions represent business rule violations.
They are raised by services and caught by controllers.
"""

from __future__ import annotations

from utilities.errors import DomainError


class LootboxError(DomainError):
    """Base exception for lootbox domain."""


class InsufficientKeysError(LootboxError):
    """User has insufficient keys for the requested operation."""

    def __init__(self, key_type: str) -> None:
        """Initialize error.

        Args:
            key_type: The key type that was insufficient.

        """
        super().__init__(
            f"User does not have enough keys of type '{key_type}' for this action.",
            key_type=key_type,
        )
