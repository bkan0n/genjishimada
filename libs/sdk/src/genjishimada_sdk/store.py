"""Store domain data models."""

from __future__ import annotations

import datetime as dt
from typing import Literal
from uuid import UUID

from msgspec import Struct

__all__ = (
    "GenerateRotationRequest",
    "GenerateRotationResponse",
    "ItemPurchaseRequest",
    "ItemPurchaseResponse",
    "KeyPriceInfo",
    "KeyPricingListResponse",
    "KeyPricingResponse",
    "KeyPurchaseRequest",
    "KeyPurchaseResponse",
    "PurchaseHistoryItem",
    "PurchaseHistoryResponse",
    "QuestData",
    "QuestProgress",
    "QuestRequirements",
    "QuestResponse",
    "RotationItemResponse",
    "RotationResponse",
    "StoreConfigResponse",
    "UpdateConfigRequest",
)


class StoreConfigResponse(Struct):
    """Store configuration response.

    Attributes:
        rotation_period_days: How often the store rotates.
        active_key_type: Current active key type.
        last_rotation_at: When the last rotation occurred.
        next_rotation_at: When the next rotation will occur.
    """

    rotation_period_days: int
    active_key_type: str
    last_rotation_at: dt.datetime
    next_rotation_at: dt.datetime


class RotationItemResponse(Struct):
    """Item in current store rotation.

    Attributes:
        item_name: Name of the item.
        item_type: Type of item (spray, skin, etc.).
        key_type: Associated key type.
        rarity: Item rarity.
        price: Coin cost.
        owned: Whether user owns this item.
    """

    item_name: str
    item_type: str
    key_type: str
    rarity: str
    price: int
    owned: bool = False


class RotationResponse(Struct):
    """Current store rotation response.

    Attributes:
        rotation_id: UUID identifying this rotation.
        available_until: When this rotation expires.
        items: List of items in rotation.
    """

    rotation_id: UUID
    available_until: dt.datetime
    items: list[RotationItemResponse]


class KeyPriceInfo(Struct):
    """Price information for a quantity of keys.

    Attributes:
        quantity: Number of keys.
        price: Total coin cost.
        discount_percent: Discount percentage applied.
    """

    quantity: int
    price: int
    discount_percent: int


class KeyPricingResponse(Struct):
    """Key pricing for a specific key type.

    Attributes:
        key_type: Name of key type.
        is_active: Whether this is the active key type.
        prices: List of pricing tiers.
    """

    key_type: str
    is_active: bool
    prices: list[KeyPriceInfo]


class KeyPricingListResponse(Struct):
    """Response containing key pricing for all key types.

    Attributes:
        active_key_type: Currently active key type.
        keys: List of pricing information for each key type.
    """

    active_key_type: str
    keys: list[KeyPricingResponse]


class KeyPurchaseRequest(Struct):
    """Request to purchase keys.

    Attributes:
        user_id: User making purchase.
        key_type: Type of key to purchase.
        quantity: Number of keys (must be 1, 3, or 5).
    """

    user_id: int
    key_type: str
    quantity: Literal[1, 3, 5]


class KeyPurchaseResponse(Struct):
    """Response from key purchase.

    Attributes:
        success: Whether purchase succeeded.
        keys_purchased: Number of keys purchased.
        price_paid: Coins spent.
        remaining_coins: User's remaining coin balance.
    """

    success: bool
    keys_purchased: int
    price_paid: int
    remaining_coins: int


class ItemPurchaseRequest(Struct):
    """Request to purchase store item.

    Attributes:
        user_id: User making purchase.
        item_name: Name of item to purchase.
        item_type: Type of item.
        key_type: Associated key type.
    """

    user_id: int
    item_name: str
    item_type: str
    key_type: str


class ItemPurchaseResponse(Struct):
    """Response from item purchase.

    Attributes:
        success: Whether purchase succeeded.
        item_name: Name of purchased item.
        item_type: Type of item.
        price_paid: Coins spent.
        remaining_coins: User's remaining coin balance.
    """

    success: bool
    item_name: str
    item_type: str
    price_paid: int
    remaining_coins: int


class PurchaseHistoryItem(Struct):
    """Single purchase in user's history.

    Attributes:
        id: Purchase ID.
        purchase_type: Type of purchase (must be 'key' or 'item').
        item_name: Name of item (if item purchase).
        item_type: Type of item (if item purchase).
        key_type: Key type.
        quantity: Quantity purchased.
        price_paid: Coins spent.
        purchased_at: When purchase occurred.
    """

    id: int
    purchase_type: Literal["key", "item"]
    item_name: str | None
    item_type: str | None
    key_type: str
    quantity: int
    price_paid: int
    purchased_at: dt.datetime


class PurchaseHistoryResponse(Struct):
    """User's purchase history.

    Attributes:
        total: Total number of purchases.
        purchases: List of purchases.
    """

    total: int
    purchases: list[PurchaseHistoryItem]


class GenerateRotationRequest(Struct):
    """Request to generate new rotation.

    Attributes:
        item_count: Number of items to include (default 5).
    """

    item_count: int = 5


class GenerateRotationResponse(Struct):
    """Response from rotation generation.

    Attributes:
        rotation_id: UUID of the newly generated rotation.
        items_generated: Number of items included in rotation.
        available_until: When this rotation expires.
    """

    rotation_id: UUID
    items_generated: int
    available_until: dt.datetime


class UpdateConfigRequest(Struct):
    """Request to update store config.

    Attributes:
        rotation_period_days: How often to rotate (optional).
        active_key_type: Active key type (optional).
    """

    rotation_period_days: int | None = None
    active_key_type: str | None = None


class QuestRequirements(Struct):
    """Quest requirement specification."""

    type: str
    count: int | None = None
    difficulty: str | None = None
    category: str | None = None
    medal_type: str | None = None
    map_id: int | None = None
    target_time: float | None = None
    target_type: str | None = None
    rival_user_id: int | None = None
    rival_time: float | None = None
    target: str | None = None
    min_count: int | None = None


class QuestData(Struct):
    """Quest metadata and configuration."""

    name: str
    description: str
    difficulty: str
    coin_reward: int
    xp_reward: int
    requirements: dict
    bounty_type: str | None = None


class QuestProgress(Struct):
    """User progress on a quest."""

    current: int | None = None
    target: int | None = None
    percentage: int | None = None
    details: dict | None = None
    completed_map_ids: list[int] | None = None
    counted_map_ids: list[int] | None = None
    medals: list[dict] | None = None
    map_id: int | None = None
    target_time: float | None = None
    target_type: str | None = None
    best_attempt: float | None = None
    last_attempt: float | None = None
    rival_user_id: int | None = None
    rival_time: float | None = None
    completed: bool | None = None
    medal_earned: str | None = None


class QuestResponse(Struct):
    """Quest with progress for API responses."""

    progress_id: int
    quest_id: int | None
    name: str
    description: str
    difficulty: str
    coin_reward: int
    xp_reward: int
    progress: QuestProgress
    completed: bool
    claimed: bool
    bounty_type: str | None = None
