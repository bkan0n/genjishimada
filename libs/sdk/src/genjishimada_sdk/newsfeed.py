from __future__ import annotations

import datetime as dt
from typing import Literal

from msgspec import Struct

from .difficulties import DifficultyAll
from .internal import JobStatusResponse
from .maps import GuideURL, MedalType, OverwatchCode, OverwatchMap, get_map_banner

__all__ = (
    "NewsfeedAnnouncement",
    "NewsfeedArchive",
    "NewsfeedBulkArchive",
    "NewsfeedBulkUnarchive",
    "NewsfeedDispatchEvent",
    "NewsfeedEvent",
    "NewsfeedEventType",
    "NewsfeedFieldChange",
    "NewsfeedGuide",
    "NewsfeedLegacyRecord",
    "NewsfeedLinkedMap",
    "NewsfeedMapEdit",
    "NewsfeedNewMap",
    "NewsfeedPayload",
    "NewsfeedRecord",
    "NewsfeedRole",
    "NewsfeedScalar",
    "NewsfeedUnarchive",
    "NewsfeedUnlinkedMap",
    "PublishNewsfeedJobResponse",
)


NewsfeedEventType = Literal[
    "new_map",
    "record",
    "archive",
    "unarchive",
    "bulk_archive",
    "bulk_unarchive",
    "guide",
    "legacy_record",
    "map_edit",
    "role",
    "announcement",
    "linked_map",
    "unlinked_map",
]


# Scalars for map_edit diffs, etc.
NewsfeedScalar = str | int | float | bool | None


# ---- Tagged base for all payload variants ----
class _TaggedPayload(Struct, tag_field="type"):
    """All payloads inherit this so they're tagged with field 'type'."""


# ---- Payload variants (NOTE: no normal 'type' attributes!) ----


class NewsfeedRecord(_TaggedPayload, tag="record", kw_only=True):
    """Newsfeed entry for a new completion record.

    Attributes:
        code: Workshop code for the map.
        map_name: Name of the Overwatch map.
        time: Completion time achieved.
        video: Video URL showcasing the run.
        rank_num: Leaderboard rank number.
        name: Player name for the run.
        medal: Medal tier assigned.
        difficulty: Difficulty rating for the map.
    """

    code: OverwatchCode
    map_name: OverwatchMap
    time: float
    video: GuideURL
    rank_num: int
    name: str
    medal: MedalType | None
    difficulty: DifficultyAll


class NewsfeedNewMap(_TaggedPayload, tag="new_map", kw_only=True):
    """Newsfeed entry for publishing a new map.

    Attributes:
        code: Workshop code for the new map.
        map_name: Name of the Overwatch map.
        difficulty: Difficulty rating for the map.
        creators: List of creator names.
        title: Optional display title for the map.
        banner_url: URL for the map banner.
        official: Whether the map is official.
    """

    code: OverwatchCode
    map_name: OverwatchMap
    difficulty: DifficultyAll
    creators: list[str]
    title: str | None = None
    banner_url: str | None = None
    official: bool = True

    def __post_init__(self) -> None:
        """Set the map banner dynamically."""
        if not self.banner_url:
            self.banner_url = get_map_banner(self.map_name)


class NewsfeedArchive(_TaggedPayload, tag="archive", kw_only=True):
    """Newsfeed entry for archiving a map.

    Attributes:
        code: Workshop code for the map.
        map_name: Name of the Overwatch map.
        creators: List of creator names.
        difficulty: Difficulty rating for the map.
        reason: Explanation for the archive action.
    """

    code: OverwatchCode
    map_name: OverwatchMap
    creators: list[str]
    difficulty: DifficultyAll
    reason: str


class NewsfeedUnarchive(_TaggedPayload, tag="unarchive", kw_only=True):
    """Newsfeed entry for unarchiving a map.

    Attributes:
        code: Workshop code for the map.
        map_name: Name of the Overwatch map.
        creators: List of creator names.
        difficulty: Difficulty rating for the map.
        reason: Explanation for restoring the map.
    """

    code: OverwatchCode
    map_name: OverwatchMap
    creators: list[str]
    difficulty: DifficultyAll
    reason: str


class NewsfeedBulkArchive(_TaggedPayload, tag="bulk_archive", kw_only=True):
    """Newsfeed entry for bulk archiving multiple maps.

    Attributes:
        codes: Workshop codes for the affected maps.
        reason: Explanation for the bulk archive action.
    """

    codes: list[OverwatchCode]
    reason: str


class NewsfeedBulkUnarchive(_TaggedPayload, tag="bulk_unarchive", kw_only=True):
    """Newsfeed entry for restoring multiple maps.

    Attributes:
        codes: Workshop codes for the affected maps.
        reason: Explanation for the bulk unarchive action.
    """

    codes: list[OverwatchCode]
    reason: str


class NewsfeedGuide(_TaggedPayload, tag="guide", kw_only=True):
    """Newsfeed entry announcing a new guide for a map.

    Attributes:
        code: Workshop code for the map.
        guide_url: URL of the newly published guide.
        name: Name of the guide creator.
    """

    code: OverwatchCode
    guide_url: GuideURL
    name: str


class NewsfeedLegacyRecord(_TaggedPayload, tag="legacy_record", kw_only=True):
    """Newsfeed entry for legacy record adjustments.

    Attributes:
        code: Workshop code for the map.
        affected_count: Number of records affected.
        reason: Explanation for the legacy record change.
    """

    code: OverwatchCode
    affected_count: int
    reason: str


class NewsfeedFieldChange(Struct, kw_only=True):
    """Represents a field difference for map edit newsfeed items.

    Attributes:
        field: Name of the field that changed.
        old: Previous value.
        new: Updated value.
    """

    field: str
    old: NewsfeedScalar
    new: NewsfeedScalar


class NewsfeedMapEdit(_TaggedPayload, tag="map_edit", kw_only=True):
    """Newsfeed entry describing edits made to a map.

    Attributes:
        code: Workshop code for the map.
        changes: List of field-level changes.
        reason: Explanation for the edits.
    """

    code: OverwatchCode
    changes: list[NewsfeedFieldChange]
    reason: str


class NewsfeedRole(_TaggedPayload, tag="role", kw_only=True):
    """Newsfeed entry for a role assignment change.

    Attributes:
        user_id: Identifier of the user receiving the role change.
        name: Name of the role.
        added: List of permissions or scopes added.
    """

    user_id: int
    name: str
    added: list[str]


class NewsfeedAnnouncement(_TaggedPayload, tag="announcement", kw_only=True):
    """Newsfeed entry for general announcements.

    Attributes:
        title: Announcement title.
        content: Body content of the announcement.
        url: Optional link for more details.
        banner_url: Optional banner image URL.
        thumbnail_url: Optional thumbnail image URL.
        from_discord: Whether the announcement originated from Discord.
    """

    title: str
    content: str
    url: str | None
    banner_url: GuideURL | None
    thumbnail_url: GuideURL | None
    from_discord: bool


class NewsfeedLinkedMap(_TaggedPayload, tag="linked_map", kw_only=True):
    """Newsfeed entry for linking an unofficial map to an official one.

    Attributes:
        official_code: Code for the official map.
        unofficial_code: Code for the unofficial map.
        playtest_id: Optional playtest identifier related to the link.
    """

    official_code: OverwatchCode
    unofficial_code: OverwatchCode
    playtest_id: int | None = None


class NewsfeedUnlinkedMap(_TaggedPayload, tag="unlinked_map", kw_only=True):
    """Newsfeed entry for unlinking maps.

    Attributes:
        official_code: Code for the official map.
        unofficial_code: Code for the unofficial map.
        reason: Explanation for unlinking.
    """

    official_code: OverwatchCode
    unofficial_code: OverwatchCode
    reason: str


NewsfeedPayload = (
    NewsfeedRecord
    | NewsfeedNewMap
    | NewsfeedArchive
    | NewsfeedUnarchive
    | NewsfeedBulkArchive
    | NewsfeedBulkUnarchive
    | NewsfeedGuide
    | NewsfeedLegacyRecord
    | NewsfeedMapEdit
    | NewsfeedRole
    | NewsfeedAnnouncement
    | NewsfeedLinkedMap
    | NewsfeedUnlinkedMap
)


class NewsfeedEvent(Struct, kw_only=True):
    """Top-level newsfeed event record.

    Attributes:
        id: Identifier of the newsfeed entry.
        timestamp: When the event occurred.
        payload: Typed payload for the event.
        event_type: Optional explicit event type override.
        total_results: Total items for paginated feeds.
    """

    id: int | None
    timestamp: dt.datetime
    payload: NewsfeedPayload
    event_type: NewsfeedEventType | None = None
    total_results: int | None = None


class NewsfeedDispatchEvent(Struct, kw_only=True):
    """Event dispatched when a newsfeed entry should be delivered.

    Attributes:
        newsfeed_id: Identifier of the newsfeed entry to dispatch.
    """

    newsfeed_id: int


class PublishNewsfeedJobResponse(Struct):
    """Job response after requesting newsfeed publication.

    Attributes:
        job_status: Status of the publishing job.
        newsfeed_id: Identifier of the newsfeed entry being published.
    """

    job_status: JobStatusResponse
    newsfeed_id: int
