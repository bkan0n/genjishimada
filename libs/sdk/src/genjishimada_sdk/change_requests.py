from typing import Literal

from msgspec import Struct

__all__ = (
    "ChangeRequestCreateRequest",
    "ChangeRequestResponse",
    "ChangeRequestType",
    "StaleChangeRequestResponse",
)

ChangeRequestType = Literal[
    "Difficulty Change",
    "Map Geometry",
    "Map Edit Required",
    "Framework/Workshop",
    "Other",
]


class ChangeRequestCreateRequest(Struct):
    """Payload for creating a change request.

    Attributes:
        thread_id: Discord thread identifier where the request is tracked.
        user_id: Identifier of the user submitting the request.
        code: Overwatch workshop code for the associated map.
        content: Freeform description of the requested change.
        change_request_type: Category describing the request type.
        creator_mentions: Mention string for notifying map creators.
    """

    thread_id: int
    user_id: int
    code: str
    content: str
    change_request_type: ChangeRequestType
    creator_mentions: str


class ChangeRequestResponse(Struct):
    """Represents a persisted change request entry.

    Attributes:
        thread_id: Discord thread identifier where the request is tracked.
        user_id: Identifier of the user that opened the request.
        code: Overwatch workshop code for the associated map.
        content: Description of the requested change.
        change_request_type: Category describing the request type.
        creator_mentions: Mention string for notifying map creators, if any.
        alerted: Whether the request has been surfaced to moderators or staff.
        resolved: Whether the change request has been completed.
    """

    thread_id: int
    user_id: int
    code: str
    content: str
    change_request_type: ChangeRequestType
    creator_mentions: str | None = None
    alerted: bool = False
    resolved: bool = False


class StaleChangeRequestResponse(Struct):
    """Old change request that needs follow-up.

    Attributes:
        thread_id: Discord thread identifier for the stale request.
        user_id: Identifier of the user who created the request.
        creator_mentions: Mention string for notifying map creators.
    """

    thread_id: int
    user_id: int
    creator_mentions: str
