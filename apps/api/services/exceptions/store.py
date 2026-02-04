"""Store domain exceptions.

These exceptions represent business rule violations in the store domain.
They are raised by StoreService and caught by controllers.
"""

from utilities.errors import DomainError


class StoreError(DomainError):
    """Base exception for store domain."""


class InvalidQuantityError(StoreError):
    """Raised when key purchase quantity is invalid."""

    def __init__(self, quantity: int) -> None:
        """Initialize exception.

        Args:
            quantity: Invalid quantity value.
        """
        super().__init__(f"Invalid quantity: {quantity}. Must be 1, 3, or 5.", quantity=quantity)


class InsufficientCoinsError(StoreError):
    """Raised when user doesn't have enough coins."""

    def __init__(self, user_coins: int, required: int) -> None:
        """Initialize exception.

        Args:
            user_coins: User's current coin balance.
            required: Coins required for purchase.
        """
        super().__init__(
            f"Insufficient coins: have {user_coins}, need {required}", user_coins=user_coins, required=required
        )


class ItemNotInRotationError(StoreError):
    """Raised when item is not in current rotation."""

    def __init__(self, item_name: str) -> None:
        """Initialize exception.

        Args:
            item_name: Name of item not in rotation.
        """
        super().__init__(f"Item not in current rotation: {item_name}", item_name=item_name)


class RotationExpiredError(StoreError):
    """Raised when trying to purchase from expired rotation."""

    def __init__(self) -> None:
        """Initialize exception."""
        super().__init__("Rotation has expired")


class AlreadyOwnedError(StoreError):
    """Raised when user already owns the item."""

    def __init__(self, item_name: str) -> None:
        """Initialize exception.

        Args:
            item_name: Name of already-owned item.
        """
        super().__init__(f"User already owns this item: {item_name}", item_name=item_name)
