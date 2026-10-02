"""Transport-neutral queue contracts shared by the API and bot."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import msgspec

from genjishimada_sdk.completions import (
    CompletionCreatedEvent,
    FailedAutoverifyEvent,
    UpvoteUpdateEvent,
    VerificationChangedEvent,
    VerificationMessageDeleteEvent,
)
from genjishimada_sdk.maps import (
    MapEditCreatedEvent,
    MapEditResolvedEvent,
    PlaytestApprovedEvent,
    PlaytestCreatedEvent,
    PlaytestForceAcceptedEvent,
    PlaytestForceDeniedEvent,
    PlaytestResetEvent,
    PlaytestVoteCastEvent,
    PlaytestVoteRemovedEvent,
)
from genjishimada_sdk.newsfeed import NewsfeedDispatchEvent
from genjishimada_sdk.notifications import NotificationDeliveryEvent
from genjishimada_sdk.tournaments import (
    TournamentCompletionCreatedEvent,
    TournamentEditionResultsEvent,
    TournamentRolloverEvent,
    TournamentVerificationChangedEvent,
)
from genjishimada_sdk.xp import XpGrantEvent


class JobEnvelope(msgspec.Struct):
    """Versioned durable payload; contains no HTTP credentials."""

    job_id: UUID
    event_name: str
    event_key: str
    payload: bytes
    schema_version: int = 1
    entity_key: str | None = None


@dataclass(frozen=True)
class JobContext:
    """Application identity and fenced execution ownership."""

    job_id: UUID
    event_name: str
    event_key: str
    queue_job_id: int
    manager_id: UUID
    claimed_at: datetime
    payload: bytes
    schema_version: int = 1


class HoldJobError(Exception):
    """The operation needs operator intervention, without automatic retry."""


class UncertainEffectError(HoldJobError):
    """An external operation may have completed; reconcile before resending."""


class DependencyFailed(HoldJobError):  # noqa: N818 - semantic outcome shared by API and worker
    """A prerequisite is held; its eventual success releases this job."""


class DependencyUnavailable(Exception):  # noqa: N818 - semantic outcome shared by API and worker
    """A recoverable dependency outage does not consume the handler budget."""


class LostOwnershipError(DependencyUnavailable):
    """The worker's claim no longer authorizes effects."""


current_job: ContextVar[JobContext | None] = ContextVar("current_queue_job", default=None)

EVENT_PAYLOAD_TYPES: dict[str, type] = {
    "api.completion.autoverification.failed": FailedAutoverifyEvent,
    "api.completion.submission": CompletionCreatedEvent,
    "api.completion.upvote": UpvoteUpdateEvent,
    "api.completion.verification": VerificationChangedEvent,
    "api.completion.verification.delete": VerificationMessageDeleteEvent,
    "api.map_edit.created": MapEditCreatedEvent,
    "api.map_edit.resolved": MapEditResolvedEvent,
    "api.newsfeed.create": NewsfeedDispatchEvent,
    "api.notification.delivery": NotificationDeliveryEvent,
    "api.playtest.approve": PlaytestApprovedEvent,
    "api.playtest.create": PlaytestCreatedEvent,
    "api.playtest.force_accept": PlaytestForceAcceptedEvent,
    "api.playtest.force_deny": PlaytestForceDeniedEvent,
    "api.playtest.reset": PlaytestResetEvent,
    "api.playtest.vote.cast": PlaytestVoteCastEvent,
    "api.playtest.vote.remove": PlaytestVoteRemovedEvent,
    "api.tournament.completion.created": TournamentCompletionCreatedEvent,
    "api.tournament.results": TournamentEditionResultsEvent,
    "api.tournament.rollover": TournamentRolloverEvent,
    "api.tournament.verification.changed": TournamentVerificationChangedEvent,
    "api.xp.grant": XpGrantEvent,
}
BOT_ENTRYPOINTS = frozenset(EVENT_PAYLOAD_TYPES)
API_ENTRYPOINTS = frozenset({"completion.ocr.requested", "tournament.ocr.requested", "map.linked.newsfeed.requested"})
EVENT_PAYLOAD_TYPES.update(dict.fromkeys(API_ENTRYPOINTS, dict))
ALL_ENTRYPOINTS = BOT_ENTRYPOINTS | API_ENTRYPOINTS
