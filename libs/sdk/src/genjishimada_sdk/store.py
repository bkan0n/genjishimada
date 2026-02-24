"""Store domain data models."""

from __future__ import annotations

import datetime as dt
from typing import Literal
from uuid import UUID

from msgspec import Struct

from .utilities import get_reward_url

__all__ = (
    "ClaimQuestRequest",
    "ClaimQuestResponse",
    "GenerateQuestRotationResponse",
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
    "QuestConfigResponse",
    "QuestData",
    "QuestHistoryItem",
    "QuestHistoryResponse",
    "QuestProgress",
    "QuestRequirements",
    "QuestResponse",
    "QuestSummary",
    "RotationItemResponse",
    "RotationResponse",
    "StoreConfigResponse",
    "UpdateConfigRequest",
    "UpdateQuestConfigRequest",
    "UpdateQuestConfigResponse",
    "UpdateQuestRequest",
    "UpdateQuestResponse",
    "UserQuestsResponse",
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

    url: str | None = None

    def __post_init__(self) -> None:
        """Compute the asset URL for the reward."""
        self.url = get_reward_url(self.item_type, self.item_name)


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


class ClaimQuestRequest(Struct):
    """Request to claim a completed quest.

    Attributes:
        user_id: User claiming the reward.
    """

    user_id: int


class UpdateQuestConfigRequest(Struct):
    """Request to update quest configuration.

    Attributes:
        rotation_day: Day of week (1-7, Monday=1).
        rotation_hour: Hour of day (0-23 UTC).
        easy_quest_count: Number of easy quests per rotation.
        medium_quest_count: Number of medium quests per rotation.
        hard_quest_count: Number of hard quests per rotation.
    """

    rotation_day: int | None = None
    rotation_hour: int | None = None
    easy_quest_count: int | None = None
    medium_quest_count: int | None = None
    hard_quest_count: int | None = None


class UpdateQuestRequest(Struct):
    """Request to update a quest in the pool.

    Attributes:
        name: Quest name.
        description: Quest description.
        difficulty: Quest difficulty.
        coin_reward: Coin reward amount.
        xp_reward: XP reward amount.
        requirements: Quest requirements JSONB.
        is_active: Whether quest is active.
    """

    name: str | None = None
    description: str | None = None
    difficulty: str | None = None
    coin_reward: int | None = None
    xp_reward: int | None = None
    requirements: dict | None = None
    is_active: bool | None = None


class QuestSummary(Struct):
    """Summary of user's quest progress for the rotation.

    Attributes:
        total_quests: Total number of quests.
        completed: Number of completed quests.
        claimed: Number of claimed quests.
        potential_coins: Total potential coin rewards.
        potential_xp: Total potential XP rewards.
        earned_coins: Coins already earned.
        earned_xp: XP already earned.
    """

    total_quests: int
    completed: int
    claimed: int
    potential_coins: int
    potential_xp: int
    earned_coins: int
    earned_xp: int


class UserQuestsResponse(Struct):
    """User's active quests with progress.

    Attributes:
        rotation_id: Current rotation UUID.
        available_until: When this rotation expires.
        quests: List of quests with progress.
        summary: Aggregate summary of progress.
    """

    rotation_id: UUID
    available_until: dt.datetime | None
    quests: list[QuestResponse]
    summary: QuestSummary


class ClaimQuestResponse(Struct):
    """Response from claiming a quest reward.

    Attributes:
        success: Whether claim succeeded.
        quest_name: Name of the claimed quest.
        coins_earned: Coins awarded.
        xp_earned: XP awarded.
        new_coin_balance: Updated coin balance.
        new_xp: Updated XP total.
    """

    success: bool
    quest_name: str | None
    coins_earned: int
    xp_earned: int
    new_coin_balance: int
    new_xp: int


class QuestHistoryItem(Struct):
    """Single completed quest in history.

    Attributes:
        progress_id: Progress record ID.
        quest_id: Quest template ID (None for bounties).
        name: Quest name.
        description: Quest description.
        difficulty: Quest difficulty.
        coin_reward: Configured coin reward.
        xp_reward: Configured XP reward.
        completed_at: When quest was completed.
        claimed_at: When rewards were claimed.
        coins_rewarded: Actual coins rewarded.
        xp_rewarded: Actual XP rewarded.
        rotation_id: Rotation this quest belonged to.
        bounty_type: Bounty type if personalized quest.
    """

    progress_id: int
    quest_id: int | None = None
    name: str | None = None
    description: str | None = None
    difficulty: str | None = None
    coin_reward: int = 0
    xp_reward: int = 0
    completed_at: dt.datetime | None = None
    claimed_at: dt.datetime | None = None
    coins_rewarded: int = 0
    xp_rewarded: int = 0
    rotation_id: UUID | None = None
    bounty_type: str | None = None


class QuestHistoryResponse(Struct):
    """User's completed quest history.

    Attributes:
        total: Total number of completed quests.
        quests: List of completed quests.
    """

    total: int
    quests: list[QuestHistoryItem]


class QuestConfigResponse(Struct):
    """Quest system configuration.

    Attributes:
        rotation_day: Day of week (1=Monday, 7=Sunday).
        rotation_hour: Hour of day (0-23 UTC).
        easy_quest_count: Easy quests per rotation.
        medium_quest_count: Medium quests per rotation.
        hard_quest_count: Hard quests per rotation.
        current_rotation_id: Active rotation UUID.
        last_rotation_at: When last rotation occurred.
        next_rotation_at: When next rotation will occur.
    """

    rotation_day: int
    rotation_hour: int
    easy_quest_count: int
    medium_quest_count: int
    hard_quest_count: int
    current_rotation_id: UUID | None
    last_rotation_at: dt.datetime
    next_rotation_at: dt.datetime


class UpdateQuestConfigResponse(Struct):
    """Response from updating quest configuration.

    Attributes:
        success: Whether update succeeded.
        updated_fields: List of field names that were updated.
        next_rotation_at: Updated next rotation time.
    """

    success: bool
    updated_fields: list[str]
    next_rotation_at: dt.datetime | None


class GenerateQuestRotationResponse(Struct):
    """Response from manually generating quest rotation.

    Attributes:
        rotation_id: UUID of the rotation.
        generated: Whether a new rotation was generated.
        auto_claimed_quests: Number of auto-claimed quests.
        global_quests_generated: Number of global quests created.
    """

    rotation_id: UUID
    generated: bool
    auto_claimed_quests: int
    global_quests_generated: int


class UpdateQuestResponse(Struct):
    """Response from updating a quest in the pool.

    Attributes:
        success: Whether update succeeded.
        updated_fields: List of field names that were updated.
    """

    success: bool
    updated_fields: list[str]


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
    medal_type: str | None = None
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
