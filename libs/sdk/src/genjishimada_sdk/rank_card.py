from __future__ import annotations

from msgspec import Struct

from .difficulties import DifficultyTop
from .helpers import sanitize_string

__all__ = (
    "AvatarResponse",
    "BackgroundResponse",
    "RankCardBadgeSettings",
    "RankCardDifficultiesData",
    "RankCardResponse",
)


class BackgroundResponse(Struct):
    name: str | None
    url: str = ""

    def __post_init__(self) -> None:
        """Normalize fields and build the background asset URL.

        - Ensures ``name`` is set (defaults to ``"placeholder"`` if falsy).
        - Sanitizes ``name`` via :func:`sanitize_string`.
        - Populates ``url`` as ``assets/rank_card/background/{sanitized}.webp``.
        """
        if not self.name:
            self.name = "placeholder"
        self.url = f"assets/rank_card/background/{sanitize_string(self.name)}.webp"


class AvatarResponse(Struct):
    skin: str | None = "Overwatch 1"
    pose: str | None = "Heroic"

    url: str = ""

    def __post_init__(self) -> None:
        """Normalize fields and build the avatar asset URL.

        - Sets default ``skin`` (``"Overwatch 1"``) and ``pose`` (``"Heroic"``)
          when falsy.
        - Sanitizes ``skin`` and ``pose`` via :func:`sanitize_string`.
        - Populates ``url`` as
          ``assets/rank_card/avatar/{skin}/{pose}.webp``.
        """
        if not self.skin:
            self.skin = "Overwatch 1"
        if not self.pose:
            self.pose = "Heroic"
        self.url = f"assets/rank_card/avatar/{sanitize_string(self.skin)}/{sanitize_string(self.pose)}.webp"


class RankCardBadgeSettings(Struct):
    badge_name1: str | None = None
    badge_type1: str | None = None
    badge_name2: str | None = None
    badge_type2: str | None = None
    badge_name3: str | None = None
    badge_type3: str | None = None
    badge_name4: str | None = None
    badge_type4: str | None = None
    badge_name5: str | None = None
    badge_type5: str | None = None
    badge_name6: str | None = None
    badge_type6: str | None = None

    badge_url1: str | None = None
    badge_url2: str | None = None
    badge_url3: str | None = None
    badge_url4: str | None = None
    badge_url5: str | None = None
    badge_url6: str | None = None


class RankCardDifficultiesData(Struct):
    completed: int
    gold: int
    silver: int
    bronze: int
    total: int


class RankCardResponse(Struct):
    rank_name: str
    nickname: str
    background: str
    total_maps_created: int
    total_playtests: int
    world_records: int
    difficulties: dict[DifficultyTop, RankCardDifficultiesData]
    avatar_skin: str
    avatar_pose: str
    badges: RankCardBadgeSettings

    xp: int
    community_rank: str
    prestige_level: int

    background_url: str = ""
    rank_url: str = ""
    avatar_url: str = ""

    def __post_init__(self) -> None:
        """Compute and populate asset URLs for background, rank, and avatar.

        Uses :func:`sanitize_string` to normalize:
        - ``background`` → ``background_url`` as
          ``assets/rank_card/background/{sanitized}.webp``
        - ``rank_name`` → ``rank_url`` as
          ``assets/ranks/{sanitized}.webp``
        - ``avatar_skin`` and ``avatar_pose`` → ``avatar_url`` as
          ``assets/rank_card/avatar/{skin}/{pose}.webp``
        """
        self.background_url = f"assets/rank_card/background/{sanitize_string(self.background)}.webp"
        self.rank_url = f"assets/ranks/{sanitize_string(self.rank_name)}.webp"
        self.avatar_url = (
            f"assets/rank_card/avatar/{sanitize_string(self.avatar_skin)}/{sanitize_string(self.avatar_pose)}.webp"
        )
