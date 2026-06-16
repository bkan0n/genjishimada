"""Skill-score domain exceptions.

These exceptions represent business rule violations in the skill-score domain.
They are raised by SkillService and caught by controllers (plan 13-05).
"""

from utilities.errors import DomainError


class SkillError(DomainError):
    """Base for skill-score domain errors."""


class InvalidGammaError(SkillError):
    """The diminishing-returns exponent gamma is below the safe floor.

    gamma < 0.5 makes the aggregation farmable (it approaches a pure sum), so the
    service rejects it before the write; the DB ``CHECK (gamma >= 0.5)`` in migration
    0027 is the backstop (T-13-09, SPEC Constraint).
    """

    def __init__(self, gamma: float) -> None:
        super().__init__(
            "gamma must be >= 0.5 (lower values make the score farmable).",
            gamma=gamma,
        )


class SkillConfigNotSeededError(SkillError):
    """The skill ``weight_config`` / ``tier_config`` singleton row is missing.

    Migration 0027/0028 seed these single-row config tables. A partial/failed migration, a
    manual ``TRUNCATE``, or an environment that skipped the seed leaves the table empty, and
    every recompute/read then fails. Without this guard the failure surfaces as an opaque
    msgspec ``ValidationError`` 500 (``msgspec.convert({}, Weights)`` — all fields required);
    raising this at the repository boundary fails loudly with a descriptive message instead
    (WR-03).
    """

    def __init__(self, config_name: str) -> None:
        super().__init__(
            f"skill {config_name} is not seeded — the single config row is missing "
            f"(run/repair migration 0027/0028).",
            config_name=config_name,
        )


class InvalidPercentilesError(SkillError):
    """The tier ``percentiles`` array fails a server-side validation rule.

    Raised by ``SkillService.update_tier_config`` BEFORE any write when the supplied
    percentiles are not exactly 7 values, not all strictly within ``(0, 1)``, or not
    strictly increasing. The controller maps it to HTTP 400; nothing is persisted on a
    rejected update (T-u82-02).
    """

    def __init__(self, message: str) -> None:
        super().__init__(message)
