from typing import Literal
from uuid import UUID

from msgspec import Struct

__all__ = (
    "ClaimCreateRequest",
    "ClaimResponse",
    "JobStatusResponse",
    "JobStatusUpdateRequest",
)


class JobStatusResponse(Struct):
    """Status information for asynchronous jobs.

    Attributes:
        id: Unique job identifier.
        status: Current processing state.
        error_code: Optional machine-readable error code.
        error_msg: Optional human-readable error message.
    """

    id: UUID
    status: Literal["processing", "succeeded", "failed", "timeout", "queued"]
    error_code: str | None = None
    error_msg: str | None = None


class JobStatusUpdateRequest(Struct):
    """Payload for updating the status of an asynchronous job.

    Attributes:
        status: New processing state to apply.
        error_code: Optional machine-readable error code.
        error_msg: Optional human-readable error message.
    """

    status: Literal["processing", "succeeded", "failed", "timeout", "queued"]
    error_code: str | None = None
    error_msg: str | None = None


class ClaimCreateRequest(Struct):
    """Request payload for claiming an invite or reward key.

    Attributes:
        key: Claim token provided to the user.
    """

    key: str


class ClaimResponse(Struct):
    """Result of processing a claim request.

    Attributes:
        claimed: Whether the key was successfully claimed.
    """

    claimed: bool
