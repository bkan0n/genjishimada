from __future__ import annotations

import datetime as dt
import re
from typing import Annotated, Literal

from msgspec import UNSET, Meta, Struct, UnsetType, ValidationError

from .difficulties import DifficultyAll, DifficultyTop
from .helpers import sanitize_string
from .internal import JobStatusResponse
from .users import Creator, CreatorFull

__all__ = (
    "MAX_CREATORS",
    "PLAYTEST_VOTE_THRESHOLD",
    "URL_PATTERN",
    "URL_REGEX",
    "ArchivalStatusPatchRequest",
    "GuideFullResponse",
    "GuideResponse",
    "GuideURL",
    "LinkMapsCreateRequest",
    "MapCategory",
    "MapCompletionStatisticsResponse",
    "MapCountsResponse",
    "MapCreateRequest",
    "MapCreationJobResponse",
    "MapMasteryCreateRequest",
    "MapMasteryCreateResponse",
    "MapMasteryResponse",
    "MapPartialResponse",
    "MapPatchRequest",
    "MapPerDifficultyStatisticsResponse",
    "MapPlaytestResponse",
    "MapResponse",
    "Mechanics",
    "MedalType",
    "MedalsResponse",
    "OverwatchCode",
    "OverwatchMap",
    "PlaytestApproveRequest",
    "PlaytestApprovedEvent",
    "PlaytestCreatePartialRequest",
    "PlaytestCreateRequest",
    "PlaytestCreatedEvent",
    "PlaytestForceAcceptRequest",
    "PlaytestForceAcceptedEvent",
    "PlaytestForceDeniedEvent",
    "PlaytestForceDenyRequest",
    "PlaytestPatchRequest",
    "PlaytestResetEvent",
    "PlaytestResetRequest",
    "PlaytestResponse",
    "PlaytestStatus",
    "PlaytestThreadAssociateRequest",
    "PlaytestVote",
    "PlaytestVoteCastEvent",
    "PlaytestVoteCastRequest",
    "PlaytestVoteRemovedEvent",
    "PlaytestVoteRemovedRequest",
    "PlaytestVoteWithUser",
    "PlaytestVotesResponse",
    "PopularMapsStatisticsResponse",
    "QualityValueRequest",
    "Restrictions",
    "SendToPlaytestRequest",
    "TopCreatorsResponse",
    "TrendingMapResponse",
    "UnlinkMapsCreateRequest",
    "XPMultiplierRequest",
    "get_map_banner",
)

MAX_CREATORS = 3

URL_PATTERN = r"(https?:\/\/)([\w\-])+\.{1}([a-zA-Z]{2,63})([\/\w-]*)*\/?\??([^#\n\r]*)?#?([^\n\r]*)"
URL_REGEX = re.compile(URL_PATTERN)

OverwatchCode = Annotated[str, Meta(min_length=4, max_length=6, pattern="^[A-Z0-9]*$")]
GuideURL = Annotated[
    str,
    Meta(
        pattern=URL_PATTERN,
        description="Must be a valid URL starting with http:// or https://.",
    ),
]

MapCategory = Literal[
    "Classic",
    "Increasing Difficulty",
    "Other",
]

OverwatchMap = Literal[
    "Circuit Royal",
    "Runasapi",
    "Practice Range",
    "Route 66",
    "Midtown",
    "Junkertown",
    "Colosseo",
    "Lijiang Tower (Lunar New Year)",
    "Dorado",
    "Throne of Anubis",
    "Castillo",
    "Blizzard World (Winter)",
    "Hollywood (Halloween)",
    "King's Row",
    "Black Forest (Winter)",
    "Petra",
    "Framework",
    "Eichenwalde",
    "Workshop Island",
    "Chateau Guillard (Halloween)",
    "New Junk City",
    "Necropolis",
    "Kanezaka",
    "Havana",
    "Oasis",
    "Ayutthaya",
    "Volskaya Industries",
    "Hanamura",
    "Workshop Expanse",
    "Hanaoka",
    "Lijiang Tower",
    "Busan (Lunar New Year)",
    "Suravasa",
    "King's Row (Winter)",
    "Ecopoint: Antarctica",
    "Hanamura (Winter)",
    "Blizzard World",
    "Chateau Guillard",
    "Paraiso",
    "Workshop Green Screen",
    "Watchpoint: Gibraltar",
    "Shambali",
    "Eichenwalde (Halloween)",
    "Tools",
    "Nepal",
    "Samoa",
    "Horizon Lunar Colony",
    "Paris",
    "Esperanca",
    "Black Forest",
    "Antarctic Peninsula",
    "Workshop Chamber",
    "Hollywood",
    "New Queen Street",
    "Rialto",
    "Busan",
    "Malevento",
    "Temple of Anubis",
    "Ilios",
    "Ecopoint: Antarctica (Winter)",
    "Numbani",
    "Adlersbrunn",
    "Aatlis",
]

Mechanics = Literal[
    "Edge Climb",
    "Bhop",
    "Save Climb",
    "High Edge",
    "Distance Edge",
    "Quick Climb",
    "Slide",
    "Stall",
    "Dash",
    "Ultimate",
    "Emote Save Bhop",
    "Death Bhop",
    "Triple Jump",
    "Multi Climb",
    "Vertical Multi Climb",
    "Standing Create Bhop",
    "Crouch Edge",
    "Bhop First",
    "Create Bhop",
    "Save Double",
]

Restrictions = Literal[
    "Wall Climb",
    "Create Bhop",
    "Dash Start",
    "Death Bhop",
    "Triple Jump",
    "Multi Climb",
    "Standing Create Bhop",
    "Emote Save Bhop",
    "Double Jump",
    "Bhop",
]

PlaytestStatus = Literal["Approved", "In Progress", "Rejected"]

MedalType = Literal["Gold", "Silver", "Bronze"]


class MapCreationJobResponse(Struct):
    """Job response for map creation requests.

    Attributes:
        job_status: Status of the asynchronous map creation job.
        data: Map details produced by the creation process.
    """

    job_status: JobStatusResponse | None
    data: MapResponse


class MedalsResponse(Struct):
    gold: float
    silver: float
    bronze: float

    def __post_init__(self) -> None:
        """Validate medals.

        All medals must be present and be in order.
        """
        if not (self.bronze > self.silver > self.gold):
            raise ValidationError("Bronze medal must be larger than silver, and silver larger than gold.")


class GuideResponse(Struct):
    """Represents a guide entry for a map.

    Attributes:
        url: URL of the guide content.
        user_id: Identifier of the guide author.
    """

    url: GuideURL
    user_id: int


class GuideFullResponse(GuideResponse):
    """Guide response including author usernames."""

    usernames: list[str] = []


class MapCreateRequest(Struct):
    """Payload for creating a new map entry.

    Attributes:
        code: Workshop code for the map.
        map_name: Overwatch map name.
        category: Category describing the map type.
        creators: List of map creators.
        checkpoints: Number of checkpoints in the map.
        difficulty: Difficulty rating for the map.
        official: Whether the map is official.
        hidden: Whether the map should be hidden from listings.
        playtesting: Current playtest status.
        archived: Whether the map is archived.
        mechanics: Mechanics required for the map.
        restrictions: Restrictions applied to the map.
        description: Optional map description.
        medals: Medal thresholds for the map.
        guide_url: URL to a primary guide.
        title: Optional display title for the map.
        custom_banner: Custom banner asset name.
    """

    code: OverwatchCode
    map_name: OverwatchMap
    category: MapCategory
    creators: Annotated[list[Creator], Meta(max_length=3)]
    checkpoints: Annotated[int, Meta(gt=0)]
    difficulty: DifficultyAll
    official: bool = True
    hidden: bool = True
    playtesting: PlaytestStatus = "In Progress"
    archived: bool = False
    mechanics: list[Mechanics] = []
    restrictions: list[Restrictions] = []
    description: str | None = None
    medals: MedalsResponse | None = None
    guide_url: GuideURL | None = None
    title: str | None = None
    custom_banner: str | None = None

    @property
    def primary_creator_id(self) -> int:
        """Get the primary creator."""
        res = next((element for element in self.creators if element.is_primary), None)
        if not res:
            raise ValueError("No primary creator found.")
        return res.id


class MapPatchRequest(Struct, kw_only=True):
    """Partial update payload for map entries.

    Attributes mirror :class:`MapCreateRequest` but are optional for patching.
    """

    code: OverwatchCode | UnsetType = UNSET
    map_name: OverwatchMap | UnsetType = UNSET
    category: MapCategory | UnsetType = UNSET
    creators: list[Creator] | UnsetType = UNSET
    checkpoints: Annotated[int, Meta(gt=0)] | UnsetType = UNSET
    difficulty: DifficultyAll | UnsetType = UNSET
    hidden: bool | UnsetType = UNSET
    official: bool | UnsetType = UNSET
    playtesting: PlaytestStatus | UnsetType = UNSET
    archived: bool | UnsetType = UNSET
    mechanics: list[Mechanics] | UnsetType | None = UNSET
    restrictions: list[Restrictions] | UnsetType | None = UNSET
    description: str | UnsetType | None = UNSET
    medals: MedalsResponse | UnsetType | None = UNSET
    title: str | UnsetType | None = UNSET
    custom_banner: str | UnsetType | None = UNSET


class MapEditCreateRequest(Struct, kw_only=True):
    """Partial update payload for map edit request entries."""

    reason: str
    created_by: int
    code: OverwatchCode | UnsetType = UNSET
    map_name: OverwatchMap | UnsetType = UNSET
    category: MapCategory | UnsetType = UNSET
    creators: list[Creator] | UnsetType = UNSET
    checkpoints: Annotated[int, Meta(gt=0)] | UnsetType = UNSET
    difficulty: DifficultyAll | UnsetType = UNSET
    hidden: bool | UnsetType = UNSET
    archived: bool | UnsetType = UNSET
    mechanics: list[Mechanics] | UnsetType | None = UNSET
    restrictions: list[Restrictions] | UnsetType | None = UNSET
    description: str | UnsetType | None = UNSET
    medals: MedalsResponse | UnsetType | None = UNSET
    title: str | UnsetType | None = UNSET
    custom_banner: str | UnsetType | None = UNSET


class MapEditCreateResponse(Struct, kw_only=True):
    edit_request_id: int
    current_map_data: MapResponse


class MapEditChangesResponse(Struct, kw_only=True):
    code: OverwatchCode | None = None
    map_name: OverwatchMap | None = None
    category: MapCategory | None = None
    creators: list[Creator] | None = None
    checkpoints: Annotated[int, Meta(gt=0)] | None = None
    difficulty: DifficultyAll | None = None
    hidden: bool | None = None
    archived: bool | None = None
    mechanics: list[Mechanics] | None = None
    restrictions: list[Restrictions] | None = None
    description: str | None = None
    medals: MedalsResponse | None = None
    title: str | None = None
    custom_banner: str | None = None


class MapEditResponse(Struct, kw_only=True):
    id: int
    map_id: int
    code: OverwatchCode
    fields: MapEditChangesResponse
    reason: str
    created_at: dt.datetime
    completed_at: dt.datetime
    accepted_by: int
    accepted: bool | None
    message_id: int
    created_by: int
    rejection_reason: str | None


class MapEditSetMessageIdRequest(Struct, kw_only=True):
    message_id: int


class MapEditResolveRequest(Struct, kw_only=True):
    accepted: bool
    accepted_by: int
    rejection_reason: str | None = None


class ArchivalStatusPatchRequest(Struct):
    """Bulk update for map archival status.

    Attributes:
        codes: Workshop codes to update.
        status: Desired archival status.
    """

    codes: list[OverwatchCode]
    status: Literal["Archive", "Unarchived"]


class MapPlaytestResponse(Struct):
    """Playtest metadata associated with a map.

    Attributes:
        thread_id: Discord thread for the playtest discussion.
        vote_average: Average difficulty vote.
        vote_count: Number of votes cast.
        voters: Identifiers of voters.
        verification_id: Verification entry for the playtest.
        initial_difficulty: Initial difficulty estimate.
        completed: Whether the playtest is complete.
    """

    thread_id: int
    vote_average: float | None
    vote_count: int | None
    voters: list[int] | None
    verification_id: int | None
    initial_difficulty: float
    completed: bool


class MapResponse(Struct):
    """Full map representation returned by API endpoints.

    Attributes:
        id: Database identifier for the map.
        code: Workshop code for the map.
        map_name: Overwatch map name.
        category: Category describing the map type.
        creators: Full creator details.
        checkpoints: Number of checkpoints in the map.
        difficulty: Difficulty rating for the map.
        official: Whether the map is official.
        playtesting: Current playtest status.
        archived: Whether the map is archived.
        hidden: Whether the map is hidden from listings.
        created_at: Timestamp when the map was created.
        updated_at: Timestamp when the map was last updated.
        ratings: Average community rating.
        playtest: Playtest metadata for the map.
        guides: List of guide URLs.
        raw_difficulty: Raw numerical difficulty score.
        mechanics: Mechanics required for the map.
        restrictions: Restrictions applied to the map.
        description: Optional map description.
        medals: Medal thresholds for the map.
        title: Optional display title for the map.
        map_banner: Banner asset URL.
        time: Best recorded time for the map.
        total_results: Total results when returned in paginated queries.
        linked_code: Workshop code linked to this map.
    """

    id: int
    code: OverwatchCode
    map_name: OverwatchMap
    category: MapCategory
    creators: list[CreatorFull]
    checkpoints: Annotated[int, Meta(gt=0)]
    difficulty: DifficultyAll
    official: bool
    playtesting: PlaytestStatus
    archived: bool
    hidden: bool
    created_at: dt.datetime
    updated_at: dt.datetime
    ratings: float | None
    playtest: MapPlaytestResponse | None
    guides: list[GuideURL] | None = None
    raw_difficulty: Annotated[float, Meta(ge=0, le=10)] | None = None
    mechanics: list[Mechanics] = []
    restrictions: list[Restrictions] = []
    description: str | None = None
    medals: MedalsResponse | None = None
    title: str | None = None
    map_banner: str | None = ""
    time: float | None = None
    total_results: int | None = None
    linked_code: OverwatchCode | None = None

    def __post_init__(self) -> None:
        """Post init."""
        self.creators.sort(key=lambda c: not c.is_primary)
        if not self.map_banner:
            self.map_banner = get_map_banner(self.map_name)

    @property
    def primary_creator_id(self) -> int:
        """Get the primary creator."""
        res = next((element for element in self.creators if element.is_primary), None)
        if not res:
            raise ValueError("No primary creator found.")
        return res.id

    @property
    def primary_creator_name(self) -> str:
        """Get the primary creator."""
        res = next((element for element in self.creators if element.is_primary), None)
        if not res:
            raise ValueError("No primary creator found.")
        return res.name


class SendToPlaytestRequest(Struct):
    """Request payload for initiating a playtest.

    Attributes:
        initial_difficulty: Initial difficulty estimate for the playtest.
    """

    initial_difficulty: DifficultyAll


class PlaytestCreatePartialRequest(Struct):
    """Partial playtest creation payload when creating alongside a map.

    Attributes:
        code: Workshop code for the map.
        initial_difficulty: Initial difficulty estimate.
    """

    code: OverwatchCode
    initial_difficulty: DifficultyAll


class PlaytestThreadAssociateRequest(Struct):
    """Associates an existing playtest with a Discord thread.

    Attributes:
        playtest_id: Identifier of the playtest.
        thread_id: Discord thread identifier.
    """

    playtest_id: int
    thread_id: int


class PlaytestCreateRequest(Struct):
    """Request payload for creating a playtest entry.

    Attributes:
        code: Workshop code for the map.
        thread_id: Discord thread identifier.
        initial_difficulty: Initial difficulty estimate.
    """

    code: OverwatchCode
    thread_id: int
    initial_difficulty: DifficultyAll


class PlaytestResponse(Struct):
    """Playtest entry with status metadata.

    Attributes:
        id: Identifier of the playtest.
        thread_id: Discord thread identifier for discussion.
        code: Workshop code for the map.
        verification_id: Verification entry related to the playtest.
        initial_difficulty: Initial difficulty estimate.
        created_at: When the playtest was created.
        updated_at: When the playtest was last updated.
        completed: Whether the playtest is complete.
        thread_creation_status: Status of thread creation automation.
        thread_creation_failure_reason: Reason thread creation failed, if any.
        thread_creation_last_attempt_at: Timestamp of the last thread creation attempt.
    """

    id: int
    thread_id: int | None
    code: OverwatchCode
    verification_id: int | None
    initial_difficulty: float
    created_at: dt.datetime
    updated_at: dt.datetime
    completed: bool
    thread_creation_status: Literal["pending", "processing", "success", "failed"] | None = None
    thread_creation_failure_reason: str | None = None
    thread_creation_last_attempt_at: dt.datetime | None = None


class PlaytestPatchRequest(Struct):
    """Partial update payload for playtests."""

    thread_id: int | UnsetType = UNSET
    verification_id: int | UnsetType = UNSET
    completed: bool | UnsetType = UNSET
    thread_creation_status: Literal["pending", "processing", "success", "failed"] | UnsetType = UNSET
    thread_creation_failure_reason: str | None | UnsetType = UNSET
    thread_creation_last_attempt_at: dt.datetime | UnsetType = UNSET


class MapPartialResponse(Struct):
    """Lightweight map response used for playtest listings.

    Attributes:
        map_id: Identifier of the map.
        code: Workshop code for the map.
        difficulty: Difficulty rating for the map.
        creator_name: Primary creator name.
        map_name: Overwatch map name.
        checkpoints: Number of checkpoints in the map.
    """

    map_id: int
    code: OverwatchCode
    difficulty: DifficultyAll
    creator_name: str
    map_name: OverwatchMap
    checkpoints: int

    @property
    def thread_name(self) -> str:
        """Return the thread name."""
        return f"{self.code} | {self.difficulty} {self.map_name} by {self.creator_name}"[:100]


class PlaytestCreatedEvent(Struct):
    """Event emitted when a playtest is created.

    Attributes:
        code: Workshop code for the map.
        playtest_id: Identifier of the playtest.
    """

    code: OverwatchCode
    playtest_id: int


class PlaytestVote(Struct):
    """Difficulty vote value for a playtest."""

    difficulty: float


class PlaytestVoteWithUser(Struct):
    """Difficulty vote paired with user information.

    Attributes:
        user_id: Identifier of the voter.
        name: Display name of the voter.
        difficulty: Difficulty value submitted.
    """

    user_id: int
    name: str
    difficulty: float


class PlaytestVotesResponse(Struct):
    """Collection of playtest votes with aggregates.

    Attributes:
        votes: Individual votes with user context.
        average: Average difficulty vote.
    """

    votes: list[PlaytestVoteWithUser]
    average: float | None


class MapMasteryCreateRequest(Struct):
    """Request payload for recording map mastery progress.

    Attributes:
        user_id: Identifier of the user earning mastery.
        map_name: Name of the Overwatch map.
        level: Mastery level achieved.
    """

    user_id: int
    map_name: OverwatchMap
    level: str


class MapMasteryCreateResponse(Struct):
    """Response returned after creating or updating mastery progress.

    Attributes:
        map_name: Name of the Overwatch map.
        medal: Medal earned for the mastery level.
        operation_status: Whether the record was inserted or updated.
    """

    map_name: OverwatchMap
    medal: str
    operation_status: Literal["inserted", "updated"]


class MapMasteryResponse(Struct):
    """Aggregated mastery progress for a map.

    Attributes:
        map_name: Name of the Overwatch map.
        amount: Number of mastery completions.
        level: Computed mastery level name.
        icon_url: Asset URL for the mastery icon.
    """

    map_name: OverwatchMap
    amount: int
    level: str | None = None
    icon_url: str | None = None

    def __post_init__(self) -> None:
        """Post init."""
        self.level = self._level()
        self.icon_url = self._icon_url()

    def _level(self) -> str:
        thresholds = [
            (0, "Placeholder"),
            (5, "Rookie"),
            (10, "Explorer"),
            (15, "Trailblazer"),
            (20, "Pathfinder"),
            (25, "Specialist"),
            (30, "Prodigy"),
        ]

        icon_name = "Placeholder"
        for threshold, name in thresholds:
            if self.amount >= threshold:
                icon_name = name
        return icon_name

    def _icon_url(self) -> str:
        _sanitized_map_name = sanitize_string(self.map_name)
        assert self.level
        _lowered_level = self.level.lower()
        return f"assets/mastery/{_sanitized_map_name}_{_lowered_level}.webp"


class PlaytestApproveRequest(Struct):
    """Request payload for approving a playtest.

    Attributes:
        verifier_id: Identifier of the verifier approving the playtest.
    """

    verifier_id: int


class PlaytestApprovedEvent(Struct):
    """Event emitted when a playtest is approved.

    Attributes:
        verifier_id: Identifier of the verifier approving the playtest.
        difficulty: Final difficulty rating.
        thread_id: Discord thread identifier for the playtest.
        primary_creator_id: Identifier of the primary creator for the map.
        code: Workshop code for the map.
    """

    verifier_id: int
    difficulty: DifficultyAll
    thread_id: int
    primary_creator_id: int
    code: OverwatchCode


class PlaytestForceAcceptRequest(Struct):
    """Request to force-accept a playtest with a given difficulty.

    Attributes:
        difficulty: Difficulty rating to assign.
    """

    difficulty: DifficultyAll
    verifier_id: int


class PlaytestForceAcceptedEvent(Struct):
    difficulty: DifficultyAll
    verifier_id: int
    thread_id: int


class PlaytestForceDenyRequest(Struct):
    """Request to force-deny a playtest.

    Attributes:
        verifier_id: Identifier of the verifier denying the playtest.
        reason: Explanation for the denial.
    """

    verifier_id: int
    reason: str


class PlaytestForceDeniedEvent(Struct):
    """Event emitted when a playtest is force-denied.

    Attributes:
        verifier_id: Identifier of the verifier denying the playtest.
        reason: Explanation for the denial.
        thread_id: Discord thread identifier for the playtest.
    """

    verifier_id: int
    reason: str
    thread_id: int


class PlaytestResetRequest(Struct):
    """Request payload for resetting a playtest.

    Attributes:
        verifier_id: Identifier of the verifier performing the reset.
        reason: Explanation for the reset.
        remove_votes: Whether to delete existing votes.
        remove_completions: Whether to delete associated completions.
    """

    verifier_id: int
    reason: str
    remove_votes: bool
    remove_completions: bool


class PlaytestResetEvent(Struct):
    """Event emitted when a playtest is reset.

    Attributes:
        verifier_id: Identifier of the verifier performing the reset.
        reason: Explanation for the reset.
        remove_votes: Whether votes were removed.
        remove_completions: Whether completions were removed.
        thread_id: Discord thread identifier for the playtest.
    """

    verifier_id: int
    reason: str
    remove_votes: bool
    remove_completions: bool
    thread_id: int


class PlaytestVoteCastRequest(Struct):
    """Payload for casting a playtest difficulty vote.

    Attributes:
        voter_id: Identifier of the voter.
        difficulty_value: Difficulty vote value.
    """

    voter_id: int
    difficulty_value: float


class PlaytestVoteCastEvent(Struct):
    """Event emitted when a playtest vote is cast.

    Attributes:
        voter_id: Identifier of the voter.
        difficulty_value: Difficulty vote value.
        thread_id: Discord thread identifier for the playtest.
    """

    voter_id: int
    difficulty_value: float
    thread_id: int


class PlaytestVoteRemovedRequest(Struct):
    """Request payload for removing a playtest vote.

    Attributes:
        voter_id: Identifier of the voter whose vote is removed.
    """

    voter_id: int


class PlaytestVoteRemovedEvent(Struct):
    """Event emitted when a playtest vote is removed.

    Attributes:
        voter_id: Identifier of the voter whose vote is removed.
        thread_id: Discord thread identifier for the playtest.
    """

    voter_id: int
    thread_id: int


class MapCompletionStatisticsResponse(Struct):
    """Aggregate statistics for map completion times.

    Attributes:
        min: Minimum completion time.
        max: Maximum completion time.
        avg: Average completion time.
    """

    min: float | None = None
    max: float | None = None
    avg: float | None = None


class MapPerDifficultyStatisticsResponse(Struct):
    """Statistics grouped by difficulty level.

    Attributes:
        difficulty: Difficulty tier represented.
        amount: Number of maps in the tier.
    """

    difficulty: DifficultyTop
    amount: int


class PopularMapsStatisticsResponse(Struct):
    """Metrics summarizing popular maps.

    Attributes:
        code: Workshop code for the map.
        completions: Number of completions recorded.
        quality: Average quality score.
        difficulty: Difficulty rating for the map.
        ranking: Popularity ranking position.
    """

    code: OverwatchCode
    completions: int
    quality: float
    difficulty: DifficultyTop
    ranking: int


class TopCreatorsResponse(Struct):
    """Summary of top-performing creators.

    Attributes:
        map_count: Number of maps created.
        name: Creator name.
        average_quality: Average quality score across maps.
    """

    map_count: int
    name: str
    average_quality: float


class MapCountsResponse(Struct):
    """Count of maps grouped by map name.

    Attributes:
        map_name: Overwatch map name.
        amount: Number of maps recorded.
    """

    map_name: OverwatchMap
    amount: int


class QualityValueRequest(Struct):
    """Request payload for submitting a quality value.

    Attributes:
        value: Quality score between 1 and 6.
    """

    value: Annotated[int, Meta(ge=1, le=6)]


class XPMultiplierRequest(Struct):
    """Request payload for setting an XP multiplier.

    Attributes:
        value: Multiplier value between 1 and 10.
    """

    value: Annotated[float, Meta(ge=1, le=10)]


class TrendingMapResponse(Struct):
    """Trending map metrics used for surfacing content.

    Attributes:
        code: Workshop code for the map.
        map_name: Overwatch map name.
        clicks: Number of clicks on the map.
        completions: Number of completions recorded.
        upvotes: Number of upvotes received.
        momentum: Momentum score for the map.
        trend_score: Aggregate trend score.
    """

    code: OverwatchCode
    map_name: OverwatchMap
    clicks: int
    completions: int
    upvotes: int
    momentum: float
    trend_score: float


class LinkMapsCreateRequest(Struct):
    """Request payload for linking an unofficial map to an official one.

    Attributes:
        official_code: Workshop code of the official map.
        unofficial_code: Workshop code of the unofficial map.
    """

    official_code: OverwatchCode
    unofficial_code: OverwatchCode


class UnlinkMapsCreateRequest(Struct):
    """Request payload for unlinking a map pair.

    Attributes:
        official_code: Workshop code of the official map.
        unofficial_code: Workshop code of the unofficial map.
        reason: Explanation for unlinking the maps.
    """

    official_code: OverwatchCode
    unofficial_code: OverwatchCode
    reason: str


PLAYTEST_VOTE_THRESHOLD: dict[DifficultyTop, int] = {
    "Easy": 5,
    "Medium": 5,
    "Hard": 5,
    "Very Hard": 3,
    "Extreme": 2,
    "Hell": 1,
}


def get_map_banner(map_name: str) -> str:
    """Get the applicable map banner."""
    _map = re.sub(r"[^a-zA-Z0-9]", "", map_name)
    sanitized_name = _map.lower().strip().replace(" ", "")
    return f"https://bkan0n.com/assets/images/map_banners/{sanitized_name}.png"
