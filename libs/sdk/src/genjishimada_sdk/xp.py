from typing import Literal

from msgspec import Struct

__all__ = (
    "XP_AMOUNTS",
    "XP_TYPES",
    "PlayersPerSkillTierResponse",
    "PlayersPerXPTierResponse",
    "TierChangeResponse",
    "XpGrantEvent",
    "XpGrantRequest",
    "XpGrantResponse",
)

XP_TYPES = Literal["Map Submission", "Playtest", "Guide", "Completion", "Record", "World Record", "Other"]

XP_AMOUNTS: dict[XP_TYPES, int] = {
    "Map Submission": 30,
    "Playtest": 35,
    "Guide": 35,
    "Completion": 5,
    "Record": 15,
    "World Record": 50,
}


class XpGrantResponse(Struct):
    """Return payload when XP is granted.

    Attributes:
        previous_amount: XP amount before the grant.
        new_amount: XP amount after the grant.
    """

    previous_amount: int
    new_amount: int


class XpGrantRequest(Struct):
    """Request payload for granting XP.

    Attributes:
        amount: Amount of XP to grant.
        type: Category describing why XP is granted.
    """

    amount: int
    type: XP_TYPES


class TierChangeResponse(Struct):
    """Computed tier deltas between old and new XP.

    Attributes:
        old_xp: XP before the change.
        new_xp: XP after the change.
        old_main_tier_name: Main tier label before the change.
        new_main_tier_name: Main tier label after the change.
        old_sub_tier_name: Sub-tier label before the change.
        new_sub_tier_name: Sub-tier label after the change.
        old_prestige_level: Prestige level before the change.
        new_prestige_level: Prestige level after the change.
        rank_change_type: Description of the rank movement, if any.
        prestige_change: Whether the prestige level changed.
    """

    old_xp: int
    new_xp: int
    old_main_tier_name: str
    new_main_tier_name: str
    old_sub_tier_name: str
    new_sub_tier_name: str
    old_prestige_level: int
    new_prestige_level: int
    # "Main Tier Rank Up" | "Sub-Tier Rank Up" | None
    rank_change_type: str | None
    prestige_change: bool


class PlayersPerXPTierResponse(Struct):
    """Number of players per XP tier.

    Attributes:
        tier: Name of the XP tier.
        amount: Count of players in the tier.
    """

    tier: str
    amount: int


class PlayersPerSkillTierResponse(Struct):
    """Number of players per skill tier.

    Attributes:
        tier: Name of the skill tier.
        amount: Count of players in the tier.
    """

    tier: str
    amount: int


class XpGrantEvent(Struct):
    """Event emitted when XP is granted to a user.

    Attributes:
        user_id: Identifier of the user receiving XP.
        amount: Amount of XP granted.
        type: Category describing why XP is granted.
        previous_amount: XP total before the grant.
        new_amount: XP total after the grant.
    """

    user_id: int
    amount: int
    type: XP_TYPES
    previous_amount: int
    new_amount: int
