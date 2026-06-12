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
