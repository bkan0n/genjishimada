import datetime as dt
from typing import Literal

from msgspec import UNSET, Struct, UnsetType

from .difficulties import DifficultyTop

__all__ = (
    "CycleFrequency",
    "CycleStatus",
    "PlacementXpTier",
    "StreakXpTier",
    "TournamentCategoryCreateRequest",
    "TournamentCategoryPatchRequest",
    "TournamentCategoryResponse",
    "TournamentChooseMapRequest",
    "TournamentCompletionCreateRequest",
    "TournamentCompletionCreatedEvent",
    "TournamentCompletionResponse",
    "TournamentConfigPatchRequest",
    "TournamentConfigResponse",
    "TournamentCycleCompletedEvent",
    "TournamentCycleResponse",
    "TournamentCycleResultsResponse",
    "TournamentCycleStartedEvent",
    "TournamentLeaderboardEntryResponse",
    "TournamentNextCycleResponse",
    "TournamentStreakResponse",
    "TournamentXpGrantEvent",
)

CycleFrequency = Literal["weekly", "biweekly"]
CycleStatus = Literal["pending", "active", "finalizing", "completed"]


class PlacementXpTier(Struct):
    """Single placement-based XP reward tier.

    Attributes:
        place: Placement position (1st, 2nd, etc.).
        xp: XP amount awarded for this placement.
    """

    place: int
    xp: int


class StreakXpTier(Struct):
    """Single streak-based XP reward threshold.

    Attributes:
        threshold: Number of consecutive cycles required.
        xp: XP amount awarded at this threshold.
    """

    threshold: int
    xp: int


# ---------------------------------------------------------------------------
# Config types
# ---------------------------------------------------------------------------


class TournamentConfigResponse(Struct):
    """Tournament global configuration.

    Attributes:
        blacklist_weeks: Number of weeks a map is excluded after use.
        created_at: When the config was created.
        updated_at: When the config was last updated.
    """

    blacklist_weeks: int
    created_at: dt.datetime
    updated_at: dt.datetime


class TournamentConfigPatchRequest(Struct, kw_only=True):
    """Partial update for tournament global configuration.

    Attributes:
        blacklist_weeks: Number of weeks for map cooldown.
    """

    blacklist_weeks: int | UnsetType = UNSET


# ---------------------------------------------------------------------------
# Category types
# ---------------------------------------------------------------------------


class TournamentCategoryResponse(Struct):
    """Full tournament category with XP configuration.

    Attributes:
        id: Category identifier.
        name: Category display name.
        difficulties: Difficulty groupings this category includes.
        cycle_frequency: How often cycles rotate.
        participation_xp: Flat XP bonus for first submission per cycle.
        placement_xp: Placement-based XP tiers.
        streak_xp: Streak-based XP thresholds.
        champion_role_id: Discord role ID for category champion.
        is_active: Whether the category is currently active.
        created_at: When the category was created.
        updated_at: When the category was last updated.
    """

    id: int
    name: str
    difficulties: list[DifficultyTop]
    cycle_frequency: CycleFrequency
    participation_xp: int
    placement_xp: list[PlacementXpTier]
    streak_xp: list[StreakXpTier]
    champion_role_id: int | None
    is_active: bool
    created_at: dt.datetime
    updated_at: dt.datetime


class TournamentCategoryCreateRequest(Struct):
    """Request payload for creating a tournament category.

    Attributes:
        name: Category display name.
        difficulties: Difficulty groupings this category includes.
        cycle_frequency: How often cycles rotate.
        participation_xp: Flat XP bonus for first submission per cycle.
        placement_xp: Placement-based XP tiers.
        streak_xp: Streak-based XP thresholds.
        champion_role_id: Discord role ID for category champion.
    """

    name: str
    difficulties: list[DifficultyTop]
    cycle_frequency: CycleFrequency = "weekly"
    participation_xp: int = 0
    placement_xp: list[PlacementXpTier] = []
    streak_xp: list[StreakXpTier] = []
    champion_role_id: int | None = None


class TournamentCategoryPatchRequest(Struct, kw_only=True):
    """Partial update for a tournament category.

    Attributes:
        name: Category display name.
        difficulties: Difficulty groupings this category includes.
        cycle_frequency: How often cycles rotate.
        participation_xp: Flat XP bonus for first submission per cycle.
        placement_xp: Placement-based XP tiers.
        streak_xp: Streak-based XP thresholds.
        champion_role_id: Discord role ID for category champion.
        is_active: Whether the category is currently active.
    """

    name: str | UnsetType = UNSET
    difficulties: list[DifficultyTop] | UnsetType = UNSET
    cycle_frequency: CycleFrequency | UnsetType = UNSET
    participation_xp: int | UnsetType = UNSET
    placement_xp: list[PlacementXpTier] | UnsetType = UNSET
    streak_xp: list[StreakXpTier] | UnsetType = UNSET
    champion_role_id: int | None | UnsetType = UNSET
    is_active: bool | UnsetType = UNSET


# ---------------------------------------------------------------------------
# Cycle types
# ---------------------------------------------------------------------------


class TournamentCycleResponse(Struct):
    """Tournament cycle with status and timing.

    Attributes:
        id: Cycle identifier.
        category_id: Category this cycle belongs to.
        map_id: Map selected for this cycle.
        status: Current lifecycle status.
        started_at: When the cycle became active.
        ended_at: When the cycle was finalized.
        created_at: When the cycle record was created.
    """

    id: int
    category_id: int
    map_id: int
    status: CycleStatus
    started_at: dt.datetime | None
    ended_at: dt.datetime | None
    created_at: dt.datetime


class TournamentNextCycleResponse(Struct):
    """Preview of a pending next-cycle map for admin review.

    Attributes:
        id: Cycle identifier.
        category_id: Category this cycle belongs to.
        map_id: Map selected for this cycle.
        map_code: Workshop code of the selected map.
        map_name: Display name of the selected map.
        map_difficulty: Difficulty rating of the selected map.
        status: Current lifecycle status (always 'pending' for next-cycle previews).
        created_at: When the cycle record was created.
    """

    id: int
    category_id: int
    map_id: int
    map_code: str
    map_name: str
    map_difficulty: str
    status: CycleStatus
    created_at: dt.datetime


class TournamentChooseMapRequest(Struct):
    """Request payload for explicitly choosing a map for next cycle.

    Attributes:
        map_code: Workshop code of the map to select.
    """

    map_code: str


# ---------------------------------------------------------------------------
# Leaderboard types
# ---------------------------------------------------------------------------


class TournamentLeaderboardEntryResponse(Struct):
    """Single ranked entry on a tournament cycle leaderboard.

    Attributes:
        rank: Position on the leaderboard.
        user_id: Identifier of the competing user.
        name: Display name of the user.
        time: Best completion time in seconds.
        verified: Whether the submission has been verified.
        completion: Whether the submission counts as a full completion.
    """

    rank: int
    user_id: int
    name: str
    time: float
    verified: bool
    completion: bool


class TournamentCycleResultsResponse(Struct):
    """Archived cycle results with standings.

    Attributes:
        id: Cycle identifier.
        category_id: Category this cycle belongs to.
        map_id: Map selected for this cycle.
        status: Current lifecycle status.
        started_at: When the cycle became active.
        ended_at: When the cycle was finalized.
        created_at: When the cycle record was created.
        standings: Ranked leaderboard entries for the cycle.
    """

    id: int
    category_id: int
    map_id: int
    status: CycleStatus
    started_at: dt.datetime | None
    ended_at: dt.datetime | None
    created_at: dt.datetime
    standings: list[TournamentLeaderboardEntryResponse]


# ---------------------------------------------------------------------------
# Completion types
# ---------------------------------------------------------------------------


class TournamentCompletionCreateRequest(Struct):
    """Request payload for submitting a tournament completion.

    Attributes:
        user_id: Identifier of the submitting user.
        time: Completion time in seconds.
        screenshot: Proof screenshot URL.
        video: Optional video proof URL.
    """

    user_id: int
    time: float
    screenshot: str
    video: str | None = None


class TournamentCompletionResponse(Struct):
    """Full tournament completion record.

    Attributes:
        id: Completion record identifier.
        cycle_id: Cycle the completion belongs to.
        user_id: Identifier of the completing user.
        map_id: Map that was completed.
        time: Completion time in seconds.
        screenshot: Proof screenshot URL.
        video: Optional video proof URL.
        verified: Whether the completion has been verified.
        completion: Whether the submission counts as a full completion.
        inserted_at: When the completion was recorded.
    """

    id: int
    cycle_id: int
    user_id: int
    map_id: int
    time: float
    screenshot: str
    video: str | None
    verified: bool
    completion: bool
    inserted_at: dt.datetime


# ---------------------------------------------------------------------------
# Streak types
# ---------------------------------------------------------------------------


class TournamentStreakResponse(Struct):
    """User participation streak data.

    Attributes:
        user_id: Identifier of the user.
        current_streak: Consecutive cycles with at least one submission.
        max_streak: Highest streak ever achieved.
        last_cycle_id: Last cycle the user participated in.
        updated_at: When the streak was last updated.
    """

    user_id: int
    current_streak: int
    max_streak: int
    last_cycle_id: int | None
    updated_at: dt.datetime


# ---------------------------------------------------------------------------
# Event types (RabbitMQ)
# ---------------------------------------------------------------------------


class TournamentCycleStartedEvent(Struct):
    """Event emitted when a new tournament cycle is activated.

    Attributes:
        cycle_id: Identifier of the started cycle.
        category_id: Category the cycle belongs to.
        map_id: Map selected for the cycle.
    """

    cycle_id: int
    category_id: int
    map_id: int


class TournamentCycleCompletedEvent(Struct):
    """Event emitted when a tournament cycle is finalized.

    Attributes:
        cycle_id: Identifier of the completed cycle.
        category_id: Category the cycle belongs to.
    """

    cycle_id: int
    category_id: int


class TournamentCompletionCreatedEvent(Struct):
    """Event emitted when a tournament completion is created.

    Attributes:
        completion_id: Identifier of the tournament completion.
        cycle_id: Identifier of the tournament cycle.
    """

    completion_id: int
    cycle_id: int


class TournamentXpGrantEvent(Struct):
    """Event emitted to grant tournament XP to a user.

    Attributes:
        user_id: Identifier of the user receiving XP.
        amount: Amount of XP to grant.
        cycle_id: Cycle that triggered the grant.
        category_id: Category the cycle belongs to.
        grant_reason: Human-readable reason for the grant.
    """

    user_id: int
    amount: int
    cycle_id: int
    category_id: int
    grant_reason: str
