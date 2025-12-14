import datetime as dt
from typing import Annotated, Literal

from msgspec import UNSET, Meta, Struct, UnsetType

from .difficulties import DifficultyAll, DifficultyTop
from .internal import JobStatusResponse
from .maps import GuideURL, MedalType, OverwatchCode, OverwatchMap

__all__ = (
    "CompletionCreateRequest",
    "CompletionCreatedEvent",
    "CompletionPatchRequest",
    "CompletionResponse",
    "CompletionSubmissionJobResponse",
    "CompletionSubmissionResponse",
    "CompletionVerificationUpdateRequest",
    "ExtractedResultResponse",
    "ExtractedTextsResponse",
    "FailedAutoverifyEvent",
    "MapRecordProgressionResponse",
    "OcrResponse",
    "PendingVerificationResponse",
    "QualityUpdateRequest",
    "SuspiciousCompletionCreateRequest",
    "SuspiciousCompletionResponse",
    "SuspiciousFlag",
    "TimePlayedPerRankResponse",
    "UpvoteCreateRequest",
    "UpvoteSubmissionJobResponse",
    "UpvoteUpdateEvent",
    "VerificationChangedEvent",
    "WorldRecordXPCheckResponse",
)


class CompletionSubmissionJobResponse(Struct):
    """Job response for completion submissions.

    Attributes:
        job_status: Asynchronous processing status for the submission.
        completion_id: Identifier of the submitted completion.
    """

    job_status: JobStatusResponse | None
    completion_id: int


class UpvoteSubmissionJobResponse(Struct):
    """Job response for upvote submissions.

    Attributes:
        job_status: Asynchronous processing status for the upvote.
        upvotes: Updated upvote total after processing.
    """

    job_status: JobStatusResponse | None
    upvotes: int | None


class CompletionCreateRequest(Struct):
    """Request payload for submitting a completion.

    Attributes:
        code: Workshop code for the map.
        user_id: Identifier for the submitting user.
        time: Completion time in seconds.
        screenshot: Proof screenshot URL.
        video: Optional video proof URL.
    """

    code: OverwatchCode
    user_id: int
    time: float
    screenshot: GuideURL
    video: GuideURL | None


class CompletionResponse(Struct):
    """Represents a completion entry with verification metadata.

    Attributes:
        code: Workshop code for the map.
        user_id: Identifier for the completing user.
        name: Display name of the runner.
        also_known_as: Alternate display name if available.
        time: Completion time in seconds.
        screenshot: Screenshot URL for proof.
        video: Optional video URL for proof.
        completion: Whether the run qualifies as a completion.
        verified: Whether the completion has been staff verified.
        rank: Leaderboard rank if available.
        medal: Awarded medal tier for the run.
        map_name: Name of the Overwatch map.
        difficulty: Difficulty rating for the map.
        message_id: Discord message ID tied to the submission.
        legacy: Whether the record predates current validation rules.
        legacy_medal: Medal tier used for legacy records.
        suspicious: Whether the run has raised suspicion flags.
        total_results: Total number of records in the query, when paginated.
        upvotes: Current upvote total for the submission.
    """

    code: OverwatchCode
    user_id: int
    name: str
    also_known_as: str | None
    time: float
    screenshot: str
    video: GuideURL | None
    completion: bool
    verified: bool
    rank: int | None
    medal: MedalType | None
    map_name: OverwatchMap
    difficulty: DifficultyAll
    message_id: int
    legacy: bool
    legacy_medal: MedalType | None
    suspicious: bool
    total_results: int | None = None
    upvotes: int = 0


class CompletionSubmissionResponse(Struct):
    """Submission response returned immediately after creating a run.

    Attributes:
        id: Identifier of the new submission.
        user_id: Identifier for the submitting user.
        time: Completion time in seconds.
        screenshot: Screenshot URL for proof.
        video: Optional video URL for proof.
        verified: Whether the submission has been verified.
        completion: Whether the run qualifies as a completion.
        inserted_at: Timestamp when the submission was recorded.
        code: Workshop code for the map.
        difficulty: Difficulty rating for the map.
        map_name: Name of the Overwatch map.
        hypothetical_rank: Expected leaderboard rank if verified.
        hypothetical_medal: Expected medal tier if verified.
        name: Display name of the runner.
        also_known_as: Alternate display name if available.
        verified_by: Identifier of the verifier, if verified.
        verification_id: Verification entry ID, if applicable.
        message_id: Discord message ID tied to the submission.
        suspicious: Whether the run has raised suspicion flags.
    """

    id: int
    user_id: int
    time: float
    screenshot: str
    video: GuideURL | None
    verified: bool
    completion: bool
    inserted_at: dt.datetime
    code: OverwatchCode
    difficulty: DifficultyAll
    map_name: OverwatchMap
    hypothetical_rank: int | None
    hypothetical_medal: MedalType | None
    name: str
    also_known_as: str
    verified_by: int | None
    verification_id: int | None
    message_id: int | None
    suspicious: bool


class CompletionPatchRequest(Struct):
    """Partial update payload for completion records.

    Attributes:
        message_id: Discord message identifier for the submission.
        completion: Flag indicating completion status.
        verification_id: Identifier linking to verification metadata.
        legacy: Whether the record predates current validation rules.
        legacy_medal: Medal tier used for legacy records.
        wr_xp_check: Whether to perform world-record XP validation.
    """

    message_id: int | UnsetType = UNSET
    completion: bool | UnsetType = UNSET
    verification_id: int | UnsetType = UNSET
    legacy: bool | UnsetType = UNSET
    legacy_medal: str | None | UnsetType = UNSET
    wr_xp_check: bool | UnsetType = UNSET


class WorldRecordXPCheckResponse(Struct):
    """Result of checking whether a completion grants world-record XP.

    Attributes:
        code: Workshop code for the map.
        user_id: Identifier of the runner.
    """

    code: OverwatchCode
    user_id: int


class CompletionVerificationUpdateRequest(Struct):
    """Update verification metadata for a completion.

    Attributes:
        verified_by: Identifier of the staff member performing the verification.
        verified: Whether the completion has been verified.
        reason: Optional reasoning for verification changes.
    """

    verified_by: int
    verified: bool
    reason: str | None


class PendingVerificationResponse(Struct):
    """Represents a completion waiting for verification.

    Attributes:
        id: Identifier of the completion submission.
        verification_id: Identifier of the verification entry.
    """

    id: int
    verification_id: int


class CompletionCreatedEvent(Struct):
    """Event emitted when a completion is created.

    Attributes:
        completion_id: Identifier of the new completion.
    """

    completion_id: int


class VerificationChangedEvent(Struct):
    """Event emitted when a completion's verification changes.

    Attributes:
        completion_id: Identifier of the affected completion.
        verified: New verification state.
        verified_by: Identifier of the verifier.
        reason: Optional reason for the change.
    """

    completion_id: int
    verified: bool
    verified_by: int
    reason: str | None


SuspiciousFlag = Literal["Cheating", "Scripting"]


class SuspiciousCompletionCreateRequest(Struct):
    """Request payload for flagging a completion as suspicious.

    Attributes:
        context: Explanation of why the run is suspicious.
        flag_type: Category for the suspicion (e.g., cheating).
        flagged_by: Identifier of the moderator setting the flag.
        message_id: Discord message ID associated with the run.
        verification_id: Verification record ID, if applicable.
    """

    context: str
    flag_type: SuspiciousFlag
    flagged_by: int
    message_id: int | None = None
    verification_id: int | None = None


class SuspiciousCompletionResponse(Struct):
    """Represents a stored suspicious completion entry.

    Attributes:
        id: Identifier of the suspicious record.
        user_id: Identifier of the flagged user.
        context: Explanation of why the run is suspicious.
        flag_type: Category for the suspicion (e.g., cheating).
        message_id: Discord message ID associated with the run.
        verification_id: Verification record ID, if applicable.
        flagged_by: Identifier of the moderator setting the flag.
    """

    id: int
    user_id: int
    context: str
    flag_type: SuspiciousFlag
    message_id: int | None
    verification_id: int | None
    flagged_by: int


class UpvoteCreateRequest(Struct):
    """Request payload for adding an upvote to a completion.

    Attributes:
        user_id: Identifier of the user casting the upvote.
        message_id: Discord message identifier for the completion message.
    """

    user_id: int
    message_id: int


class MapRecordProgressionResponse(Struct):
    """Represents a historical record progression for a map.

    Attributes:
        time: Completion time in seconds.
        inserted_at: Timestamp when the record was recorded.
    """

    time: float
    inserted_at: dt.datetime


class TimePlayedPerRankResponse(Struct):
    """Aggregated time played per rank bucket.

    Attributes:
        total_seconds: Total time played in seconds.
        difficulty: Rank or difficulty bucket represented.
    """

    total_seconds: float
    difficulty: DifficultyTop


class UpvoteUpdateEvent(Struct):
    """Event emitted when a completion's upvotes change.

    Attributes:
        user_id: Identifier of the user that triggered the change.
        message_id: Discord message identifier for the completion.
    """

    user_id: int
    message_id: int


class QualityUpdateRequest(Struct):
    """Request payload for submitting a quality rating.

    Attributes:
        user_id: Identifier of the user submitting the rating.
        quality: Numeric quality score between 1 and 6 inclusive.
    """

    user_id: int
    quality: Annotated[int, Meta(ge=1, le=6)]


def to_camel(name: str) -> str:
    """Convert a snake_case field name to camelCase."""
    parts = name.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


class CamelConfig(Struct, rename=to_camel):
    """Base struct that renames fields to camelCase during encoding/decoding."""


class ExtractedTextsResponse(CamelConfig):
    """OCR text snippets extracted from a screenshot.

    Attributes:
        top_left: Raw text detected in the top-left area.
        top_left_white: White-colored text detected in the top-left area.
        top_left_cyan: Cyan-colored text detected in the top-left area.
        banner: Text detected in the banner region.
        top_right: Raw text detected in the top-right area.
        bottom_left: Raw text detected in the bottom-left area.
    """

    top_left: str | None
    top_left_white: str | None
    top_left_cyan: str | None
    banner: str | None
    top_right: str | None
    bottom_left: str | None


class ExtractedResultResponse(CamelConfig):
    """OCR output summarizing detected result details.

    Attributes:
        name: Detected player name, if any.
        time: Detected completion time in seconds.
        code: Detected workshop code.
        texts: Raw extracted text blocks from the image.
    """

    name: str | None
    time: float | None
    code: str | None
    texts: ExtractedTextsResponse


class OcrResponse(CamelConfig):
    """Top-level OCR response payload."""

    extracted: ExtractedResultResponse


class FailedAutoverifyEvent(Struct):
    """Event fired when automatic verification fails after OCR.

    Attributes:
        submitted_code: Workshop code submitted by the user.
        submitted_time: Completion time submitted by the user.
        user_id: Identifier of the submitting user.
        extracted: OCR results extracted from the proof.
        code_match: Whether the extracted code matched the submission.
        time_match: Whether the extracted time matched the submission.
        user_match: Whether the extracted user matched the submission.
        extracted_code_cleaned: Normalized code detected via OCR.
        extracted_time: Time detected via OCR.
        extracted_user_id: User identifier detected via OCR.
    """

    submitted_code: OverwatchCode
    submitted_time: float
    user_id: int
    extracted: ExtractedResultResponse
    code_match: bool
    time_match: bool
    user_match: bool
    extracted_code_cleaned: str | None
    extracted_time: float | None
    extracted_user_id: int | None
