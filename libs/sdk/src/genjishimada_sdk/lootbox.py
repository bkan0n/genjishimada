from __future__ import annotations

import datetime as dt
from typing import Literal

from msgspec import Struct

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

LootboxKeyType = Literal["Classic", "Winter"]


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
        self.url = _reward_url(self.type, self.name)


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
            self.url = f"assets/mastery/{name}_{medal}.webp"
        else:
            self.url = _reward_url(self.type, self.name)


def _reward_url(type_: str, name: str) -> str:
    sanitized_name = sanitize_string(name)
    if type_ == "spray":
        url = f"assets/rank_card/spray/{sanitized_name}.webp"
    elif type_ == "skin":
        url = f"assets/rank_card/avatar/{sanitized_name}/heroic.webp"
    elif type_ == "pose":
        url = f"assets/rank_card/avatar/overwatch_1/{sanitized_name}.webp"
    elif type_ == "background":
        url = f"assets/rank_card/background/{sanitized_name}.webp"
    elif type_ == "coins":
        url = f"assets/rank_card/coins/{sanitized_name}.webp"
    else:
        url = ""
    return url


class UserLootboxKeyAmountResponse(Struct):
    """Amount of lootbox keys a user currently holds.

    Attributes:
        key_type: Type of key counted.
        amount: Number of keys available.
    """

    key_type: LootboxKeyType
    amount: int
