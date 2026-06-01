import datetime as dt
import warnings
from typing import Literal

from msgspec import UNSET, Struct, UnsetType

from .difficulties import DifficultyTop

__all__ = (
    "Cadence",
    "CycleFrequency",
    "CycleStatus",
    "EditionStatus",
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
    "TournamentEditionResponse",
    "TournamentEditionResultsEvent",
    "TournamentLeaderboardEntryResponse",
    "TournamentLifecycleResponse",
    "TournamentNextCycleResponse",
    "TournamentPauseRequest",
    "TournamentRolloverEvent",
    "TournamentStreakResponse",
    "TournamentVerificationChangedEvent",
    "TournamentXpGrantEvent",
)

CycleFrequency = Literal["weekly", "biweekly"]
CycleStatus = Literal["pending", "active", "finalizing", "completed"]
Cadence = Literal["weekly", "biweekly"]
EditionStatus = Literal["active", "awaiting_results", "completed"]


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

    Carries the global cadence/anchor/pause/debug levers that migration 0024
    moved off ``tournaments.categories`` onto the ``tournaments.config`` singleton
    (D-02/D-03/D-07). There is no per-category ``id`` framing — these are global.

    Attributes:
        blacklist_weeks: Number of weeks a map is excluded after use.
        cadence: Global cycle cadence ('weekly' | 'biweekly') (D-02).
        anchor_weekday: Grid anchor weekday using EXTRACT(DOW): 0=Sun..6=Sat (D-07).
        anchor_time: Grid anchor time-of-day in anchor_tz wall-clock (D-07).
        anchor_tz: IANA timezone name for the grid anchor (D-07).
        transitions_paused: Global hiatus lever; when True the next edition is
            suppressed at the boundary (D-03).
        debug_cycle_seconds: Debug/test edition-length override in seconds, or
            None for the normal weekly/biweekly cadence (D-03).
        created_at: When the config was created.
        updated_at: When the config was last updated.
    """

    blacklist_weeks: int
    cadence: Cadence
    anchor_weekday: int
    anchor_time: dt.time
    anchor_tz: str
    transitions_paused: bool
    debug_cycle_seconds: int | None
    created_at: dt.datetime
    updated_at: dt.datetime


class TournamentConfigPatchRequest(Struct, kw_only=True):
    """Partial update for tournament global configuration.

    Attributes:
        blacklist_weeks: Number of weeks for map cooldown.
        cadence: Global cycle cadence ('weekly' | 'biweekly').
        anchor_weekday: Grid anchor weekday (0=Sun..6=Sat).
        anchor_time: Grid anchor time-of-day in anchor_tz wall-clock.
        anchor_tz: IANA timezone name for the grid anchor.
    """

    blacklist_weeks: int | UnsetType = UNSET
    cadence: Cadence | UnsetType = UNSET
    anchor_weekday: int | UnsetType = UNSET
    anchor_time: dt.time | UnsetType = UNSET
    anchor_tz: str | UnsetType = UNSET


# ---------------------------------------------------------------------------
# Category types
# ---------------------------------------------------------------------------


class TournamentCategoryResponse(Struct):
    """Full tournament category with XP configuration.

    Migration 0024 moved cadence OFF the category onto the global config singleton
    (``tournaments.config.cadence``, D-02); categories no longer carry their own
    ``cycle_frequency``.

    Attributes:
        id: Category identifier.
        name: Category display name.
        difficulties: Difficulty groupings this category includes.
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
    participation_xp: int
    placement_xp: list[PlacementXpTier]
    streak_xp: list[StreakXpTier]
    champion_role_id: int | None
    is_active: bool
    created_at: dt.datetime
    updated_at: dt.datetime


class TournamentCategoryCreateRequest(Struct):
    """Request payload for creating a tournament category.

    Cadence is GLOBAL (``tournaments.config.cadence``, D-02) since migration 0024 —
    a category create no longer accepts a per-category ``cycle_frequency``.

    Attributes:
        name: Category display name.
        difficulties: Difficulty groupings this category includes.
        participation_xp: Flat XP bonus for first submission per cycle.
        placement_xp: Placement-based XP tiers.
        streak_xp: Streak-based XP thresholds.
        champion_role_id: Discord role ID for category champion.
    """

    name: str
    difficulties: list[DifficultyTop]
    participation_xp: int = 0
    placement_xp: list[PlacementXpTier] = []
    streak_xp: list[StreakXpTier] = []
    champion_role_id: int | None = None


class TournamentCategoryPatchRequest(Struct, kw_only=True):
    """Partial update for a tournament category.

    Cadence is GLOBAL (``tournaments.config.cadence``, D-02) since migration 0024 —
    a category PATCH no longer accepts a per-category ``cycle_frequency``.

    Attributes:
        name: Category display name.
        difficulties: Difficulty groupings this category includes.
        participation_xp: Flat XP bonus for first submission per cycle.
        placement_xp: Placement-based XP tiers.
        streak_xp: Streak-based XP thresholds.
        champion_role_id: Discord role ID for category champion.
        is_active: Whether the category is currently active.
    """

    name: str | UnsetType = UNSET
    difficulties: list[DifficultyTop] | UnsetType = UNSET
    participation_xp: int | UnsetType = UNSET
    placement_xp: list[PlacementXpTier] | UnsetType = UNSET
    streak_xp: list[StreakXpTier] | UnsetType = UNSET
    champion_role_id: int | None | UnsetType = UNSET
    is_active: bool | UnsetType = UNSET


class TournamentLifecycleResponse(Struct):
    """Global lifecycle-control state for automatic edition transitions.

    Returned by the global pause/resume and debug-cycle-length admin routes.
    Migration 0024 moved these levers off individual categories onto the
    ``tournaments.config`` singleton, so there is no per-category ``id`` framing
    (D-03).

    Attributes:
        transitions_paused: When True, automatic edition transitions are paused
            (global hiatus lever).
        debug_cycle_seconds: Debug/test edition-length override in seconds, or
            None for the normal weekly/biweekly cadence.
    """

    transitions_paused: bool
    debug_cycle_seconds: int | None


# DEPRECATED backward-compat alias: the lifecycle structs moved to global
# (config-level) semantics in migration 0024 (D-03). The old per-category name is
# retained as an importable alias so the still-category-scoped service/route
# handlers keep importing until Plan 03/05 rewrite them to the global surface.
# New code MUST use ``TournamentLifecycleResponse``. (Cannot attach a runtime
# DeprecationWarning here without also warning on the live type it aliases, so the
# warning is documentation-only for this name.)
TournamentCategoryLifecycleResponse = TournamentLifecycleResponse


class TournamentPauseRequest(Struct):
    """Request payload for pausing or resuming automatic edition transitions (global).

    Attributes:
        paused: True pauses automatic transitions globally; False resumes the
            normal weekly/biweekly cadence.
    """

    paused: bool


class TournamentDebugCycleLengthRequest(Struct):
    """Request payload for overriding the global edition length (DEBUG/TEST ONLY).

    Attributes:
        seconds: Edition length override in seconds, or None to clear the override
            and restore the normal weekly/biweekly cadence.
    """

    seconds: int | None


# ---------------------------------------------------------------------------
# Edition types
# ---------------------------------------------------------------------------


class TournamentEditionResponse(Struct):
    """Top-level tournament edition: the shared grid-anchored timing entity (D-05).

    Migration 0024 moved the one shared ``started_at``/``ends_at`` up off the
    individual cycles onto the edition; child cycles link via ``edition_id``.
    ``ends_at`` is a STORED field, not derived from cadence — closing
    frontend-spec §8 (D-08).

    Attributes:
        id: Edition identifier.
        started_at: EXACT grid value (anchor + N x period); never now().
        ends_at: started_at + period; the next edition inherits this as its
            started_at (the drift fix).
        status: Current edition status ('active' | 'completed').
        created_at: When the edition record was created.
    """

    id: int
    started_at: dt.datetime
    ends_at: dt.datetime
    status: EditionStatus
    created_at: dt.datetime


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

    .. deprecated::
        Superseded by :class:`TournamentRolloverEvent`, which collapses the
        started/completed pair into one ``edition_rollover`` event. Retained as
        importable until Plan 03/05 remove the remaining references; do not use
        for new code.

    Attributes:
        cycles: Per-category started events that share one rotation transaction.
    """

    cycles: list[TournamentCycleStartedEvent]

    def __post_init__(self) -> None:
        """Emit a DeprecationWarning whenever this superseded event is constructed."""
        warnings.warn(
            "TournamentCyclesStartedEvent is deprecated; use TournamentRolloverEvent "
            "(the combined edition_rollover event).",
            DeprecationWarning,
            stacklevel=2,
        )


class TournamentCyclesCompletedEvent(Struct):
    """Combined event for every cycle completed in a single rotation.

    .. deprecated::
        Superseded by :class:`TournamentRolloverEvent`, which collapses the
        started/completed pair into one ``edition_rollover`` event. Retained as
        importable until Plan 03/05 remove the remaining references; do not use
        for new code.

    Attributes:
        cycles: Per-category completed events that share one rotation transaction.
    """

    cycles: list[TournamentCycleCompletedEvent]

    def __post_init__(self) -> None:
        """Emit a DeprecationWarning whenever this superseded event is constructed."""
        warnings.warn(
            "TournamentCyclesCompletedEvent is deprecated; use TournamentRolloverEvent "
            "(the combined edition_rollover event).",
            DeprecationWarning,
            stacklevel=2,
        )


class TournamentRolloverEvent(Struct):
    """One combined edition rollover event (collapses the started/completed pair).

    Carried on ``api.tournament.rollover``. Migration 0024 writes ONE
    ``edition_rollover`` outbox row per boundary with a jsonb payload whose keys
    are byte-identical to these field names (``edition_id``, ``results``,
    ``started``) — a mismatch raises ``msgspec.ValidationError`` and (safely)
    leaves the row unpublished (D-09/D-10/D-11, Pitfall 5).

    The two sections are conditional (D-10):
    - ``results`` is empty when the boundary only starts the next edition.
    - ``started`` is empty when the boundary only finalizes the edition (into a
      hiatus, ``transitions_paused``).

    When verification is still in flight at the boundary (Phase 12.1, D-09),
    ``results_pending=True`` marks a start-only deferred rollover: ``results`` is
    empty and the finalized edition's standings arrive later as a separate
    :class:`TournamentEditionResultsEvent`. ``results_pending`` defaults to
    ``False`` so an OLD-shape outbox payload (written before this field existed,
    no ``results_pending`` key) still ``msgspec.convert``s cleanly — in-flight
    rows at deploy MUST keep converting or they stay unpublished forever
    (Pitfall 2, hard backward-compatibility constraint).

    Attributes:
        edition_id: Identifier of the edition that rolled over (idempotency key
            source: ``tournament:rollover:{edition_id}``).
        results: Per-category completed results of the finalized edition; empty
            on a start-only (out-of-hiatus) rollover OR when ``results_pending``.
        started: Per-category started cycles of the next edition; empty on a
            results-only (into-hiatus) rollover.
        results_pending: ``True`` when the finalized edition's results are
            deferred pending verification drain; ``results`` is then empty and a
            separate :class:`TournamentEditionResultsEvent` follows. Defaults to
            ``False`` to keep old-shape payloads convertible.
    """

    edition_id: int
    results: list[TournamentCycleCompletedEvent]
    started: list[TournamentCycleStartedEvent]
    results_pending: bool = False


class TournamentEditionResultsEvent(Struct):
    """Results-only event for a deferred (verification-gated) edition rollover.

    Carried on ``api.tournament.results`` (idempotency key
    ``tournament:results:{edition_id}``). Emitted when a finalized edition's
    pending verifications have drained AFTER a start-only
    :class:`TournamentRolloverEvent` (``results_pending=True``) already announced
    the next edition's start (Phase 12.1, D-09). The bot's ``_on_edition_results``
    handler posts the deferred standings as a NEW announcement and performs the
    held champion-role transfer.

    Attributes:
        edition_id: Identifier of the finalized edition whose results settled
            (idempotency key source: ``tournament:results:{edition_id}``).
        results: Per-category completed results of the finalized edition; empty
            when every run was rejected / no submissions (a no-winner card).
    """

    edition_id: int
    results: list[TournamentCycleCompletedEvent]


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
