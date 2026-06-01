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
    "TournamentCategoryLifecycleResponse",
    "TournamentCategoryPatchRequest",
    "TournamentCategoryResponse",
    "TournamentChooseMapRequest",
    "TournamentCompletionCreatedEvent",
    "TournamentCompletionResponse",
    "TournamentConfigPatchRequest",
    "TournamentConfigResponse",
    "TournamentCycleCompletedEvent",
    "TournamentCycleListResponse",
    "TournamentCycleResponse",
    "TournamentCycleResultsResponse",
    "TournamentCycleStartedEvent",
    "TournamentCycleWithWinnerResponse",
    "TournamentCyclesCompletedEvent",
    "TournamentCyclesStartedEvent",
    "TournamentDebugCycleLengthRequest",
    "TournamentLeaderboardEntryResponse",
    "TournamentNextCycleResponse",
    "TournamentPauseRequest",
    "TournamentStreakResponse",
    "TournamentVerificationChangedEvent",
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


class TournamentCategoryLifecycleResponse(Struct):
    """Lifecycle-control state for a tournament category.

    Returned by the pause/resume and debug-cycle-length admin routes.

    Attributes:
        id: Category identifier.
        transitions_paused: When True, automatic cycle transitions are paused.
        debug_cycle_seconds: Debug/test cycle-length override in seconds, or None
            for the normal weekly/biweekly cadence.
    """

    id: int
    transitions_paused: bool
    debug_cycle_seconds: int | None


class TournamentPauseRequest(Struct):
    """Request payload for pausing or resuming automatic cycle transitions.

    Attributes:
        paused: True pauses automatic transitions for the category; False resumes
            the normal weekly/biweekly cadence.
    """

    paused: bool


class TournamentDebugCycleLengthRequest(Struct):
    """Request payload for overriding a category's cycle length (DEBUG/TEST ONLY).

    Attributes:
        seconds: Cycle length override in seconds, or None to clear the override
            and restore the normal weekly/biweekly cadence.
    """

    seconds: int | None


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


class TournamentCycleWithWinnerResponse(Struct):
    """Tournament cycle with joined map details and rank-1 winner info.

    Attributes:
        id: Cycle identifier.
        category_id: Category this cycle belongs to.
        map_id: Map selected for this cycle.
        map_code: Workshop code of the selected map.
        map_name: Display name of the selected map.
        map_difficulty: Difficulty rating of the selected map.
        status: Current lifecycle status.
        started_at: When the cycle became active.
        ended_at: When the cycle was finalized.
        created_at: When the cycle record was created.
        winner_name: Display name of the rank-1 winner, or None if no submissions.
        winner_user_id: User ID of the rank-1 winner, or None if no submissions.
    """

    id: int
    category_id: int
    map_id: int
    map_code: str
    map_name: str
    map_difficulty: str
    status: CycleStatus
    started_at: dt.datetime | None
    ended_at: dt.datetime | None
    created_at: dt.datetime
    winner_name: str | None
    winner_user_id: int | None


class TournamentCycleListResponse(Struct):
    """Paginated list of tournament cycles with winner info.

    Attributes:
        total: Total number of cycles matching the query.
        cycles: List of cycles for the current page.
    """

    total: int
    cycles: list[TournamentCycleWithWinnerResponse]


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
        map_code: Workshop code of the selected map.
        map_name: Display name of the selected map.
        started_at: When the cycle became active.
        ends_at: Computed end time for the cycle based on its frequency.
    """

    cycle_id: int
    category_id: int
    map_id: int
    map_code: str
    map_name: str
    started_at: dt.datetime
    ends_at: dt.datetime


class TournamentCycleCompletedEvent(Struct):
    """Event emitted when a tournament cycle is finalized.

    Attributes:
        cycle_id: Identifier of the completed cycle.
        category_id: Category the cycle belongs to.
        standings: Final ranked leaderboard entries snapshotted at finalization.
        winner_user_id: User ID of the rank-1 winner, or None if no submissions.
    """

    cycle_id: int
    category_id: int
    standings: list[TournamentLeaderboardEntryResponse]
    winner_user_id: int | None


class TournamentCyclesStartedEvent(Struct):
    """Combined event for every cycle started in a single rotation.

    A single pg_cron rotation can start multiple categories' cycles in one
    transaction. The outbox poller groups those rows by their shared
    ``created_at`` and publishes ONE of these batch events so the bot renders a
    single combined announcement instead of one per category.

    Attributes:
        cycles: Per-category started events that share one rotation transaction.
    """

    cycles: list[TournamentCycleStartedEvent]


class TournamentCyclesCompletedEvent(Struct):
    """Combined event for every cycle completed in a single rotation.

    A single pg_cron rotation can finalize multiple categories' cycles in one
    transaction. The outbox poller groups those rows by their shared
    ``created_at`` and publishes ONE of these batch events so the bot renders a
    single combined results announcement instead of one per category.

    Attributes:
        cycles: Per-category completed events that share one rotation transaction.
    """

    cycles: list[TournamentCycleCompletedEvent]


class TournamentCompletionCreatedEvent(Struct):
    """Event emitted when a tournament completion is created.

    Rides ``api.tournament.completion.created`` (non-PB video path). Carries
    the submission details so the bot embed needs no extra fetch.

    Attributes:
        completion_id: Identifier of the tournament completion.
        cycle_id: Identifier of the tournament cycle.
        user_id: Identifier of the submitting user.
        time: Completion time in seconds.
        video: Optional video proof URL.
        screenshot: Screenshot proof URL.
    """

    completion_id: int
    cycle_id: int
    user_id: int
    time: float
    video: str | None
    screenshot: str


class TournamentVerificationChangedEvent(Struct):
    """Event emitted when a tournament completion's verification changes.

    Rides ``api.tournament.verification.changed``. The table has no
    ``verified_by`` column, so the event does not carry one.

    Attributes:
        tournament_completion_id: Identifier of the tournament completion.
        cycle_id: Identifier of the tournament cycle.
        user_id: Identifier of the submitting user.
        verified: New verified state of the completion.
        time: Completion time in seconds.
    """

    tournament_completion_id: int
    cycle_id: int
    user_id: int
    verified: bool
    time: float


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
