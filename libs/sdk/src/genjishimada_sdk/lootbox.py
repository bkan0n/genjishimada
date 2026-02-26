from __future__ import annotations

import datetime as dt
from typing import Literal

from msgspec import Struct

from .helpers import sanitize_string

__all__ = (
    "LootboxKeyType",
    "LootboxKeyTypeResponse",
    "RewardTypeResponse",
    "UserLootboxKeyAmountResponse",
    "UserRewardResponse",
)

from .utilities import get_reward_url

LootboxKeyType = Literal["Classic", "Winter", "Summer", "Halloween", "Spring", "Autumn"]


class RewardTypeResponse(Struct):
    """Reward definition returned from lootbox operations.

    Attributes:
        name: Display name of the reward.
        key_type: Lootbox key type associated with the reward.
        rarity: Rarity tier of the reward.
        type: Reward category (e.g., spray, skin).
        duplicate: Whether the reward is a duplicate.
        coin_amount: Coin payout when receiving a duplicate reward.
        url: Asset URL associated with the reward.
    """

    name: str
    key_type: LootboxKeyType
    rarity: str
    type: str
    duplicate: bool = False
    coin_amount: int = 0

    url: str | None = None

    def __post_init__(self) -> None:
        """Compute the asset URL for the reward."""
        self.url = get_reward_url(self.type, self.name)


class LootboxKeyTypeResponse(Struct):
    """Represents a lootbox key type.

    Attributes:
        name: Name of the key type.
    """

    name: str


class UserRewardResponse(Struct):
    """Represents a reward granted to a user.

    Attributes:
        user_id: Identifier of the rewarded user.
        earned_at: Timestamp when the reward was earned.
        name: Name of the reward item.
        type: Reward category (e.g., mastery, spray).
        rarity: Rarity tier of the reward.
        medal: Medal tier when the reward relates to mastery.
        url: Asset URL associated with the reward.
    """

    user_id: int
    earned_at: dt.datetime
    name: str
    type: str
    rarity: str
    medal: str | None

    url: str | None = None

    def __post_init__(self) -> None:
        """Compute the asset URL for the reward."""
        if self.type == "mastery":
            name = sanitize_string(self.name)
            medal = sanitize_string(self.medal)
            self.url = f"https://cdn.genji.pk/assets/mastery/{name}_{medal}.webp"
        else:
            self.url = get_reward_url(self.type, self.name)


class UserLootboxKeyAmountResponse(Struct):
    """Amount of lootbox keys a user currently holds.

    Attributes:
        key_type: Type of key counted.
        amount: Number of keys available.
    """

    key_type: LootboxKeyType
    amount: int
