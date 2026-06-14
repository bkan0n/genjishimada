"""Event payload schemas for internal API events."""

import msgspec


class OcrVerificationRequestedEvent(msgspec.Struct):
    """Event emitted when OCR auto-verification should be attempted."""

    completion_id: int
    user_id: int
    code: str
    time: float
    screenshot: str


class TournamentOcrVerificationRequestedEvent(msgspec.Struct):
    """Event emitted when tournament OCR auto-verification should be attempted.

    In-process schema dispatched on ``tournament.ocr.requested`` (consumed in
    11-03). Mirrors OcrVerificationRequestedEvent with the tournament-completion
    id added so the verify side-effect targets the tournament row.
    """

    tournament_completion_id: int
    cycle_id: int
    user_id: int
    code: str
    time: float
    screenshot: str


class SkillRecomputeRequestedEvent(msgspec.Struct):
    """Event emitted after a verification-state change commits (D-01/D-02).

    A full skill recompute (D-04) re-runs the whole input query + scorer for every
    player, so the event carries no map_id. The optional ``reason`` is for logs only;
    the struct constructs with no required args so any emitter can fire it.

    Attributes:
        reason: Optional human-readable trigger reason for logs (verify/reject/flag).
    """

    reason: str | None = None
