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

    The ``cause_category`` + ``actor_user_id`` fields (D-10) thread the trigger's cause
    into the recompute so the capture layer can attribute per-user score changes: a
    single clean completion trigger marks the actor ``PLAYER_ACTION`` and bystanders
    ``MAP_ENVIRONMENT``, while SYSTEM triggers (config/tier PATCH, nightly backstop,
    cold-start, or any coalesced burst) mark everyone ``SYSTEM``. ``cause_category`` is a
    plain ``str`` (not the SDK ``CauseCategory`` Literal) to keep this API-side event
    module dependency-light; the service normalizes any unrecognized category to
    ``SYSTEM`` (it is not rejected) so only the three closed-set constants are ever
    persisted.

    Attributes:
        reason: Optional human-readable trigger reason for logs (verify/reject/flag).
        cause_category: The trigger's cause; defaults to ``"SYSTEM"`` so config/tier/
            nightly/cold-start emitters construct cleanly with no per-user actor.
        actor_user_id: The completion owner for a single PLAYER_ACTION trigger; ``None``
            for SYSTEM triggers.
    """

    reason: str | None = None
    cause_category: str = "SYSTEM"
    actor_user_id: int | None = None
