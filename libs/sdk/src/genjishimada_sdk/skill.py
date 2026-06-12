from __future__ import annotations

from datetime import datetime

from msgspec import UNSET, Struct, UnsetType

__all__ = (
    "SkillBreakdownRow",
    "SkillConfigUpdateRequest",
    "SkillSummaryResponse",
    "SkillTiersResponse",
    "Weights",
)


class Weights(Struct):
    """Skill-score tuning weights, loaded 1:1 from the ``skill.weight_config`` row.

    Every field is required and has no default: the adopted defaults live in the
    migration seed (`0027`), never in code (SPEC req 5 — no hardcoded weights).

    Attributes:
        diff_base: Base of the difficulty floor `diff_base ** (raw - 1.5)`.
        gamma: Diminishing-returns exponent across maps (>= 0.5; the anti-farm dial).
        time_bonus: Maximum time-quality multiplier applied to fully-verified runs.
        shrink_k: Field-size shrink constant `field_size / (field_size + shrink_k)`.
        wr_bonus: Bonus multiplier for a video world record (video_rank == 1).
        partial_factor: Multiplier for partially-verified (screenshot-only) clears.
        medal_gold: Multiplier for a Gold medal.
        medal_silver: Multiplier for a Silver medal.
        medal_bronze: Multiplier for a Bronze medal.
    """

    diff_base: float
    gamma: float
    time_bonus: float
    shrink_k: float
    wr_bonus: float
    partial_factor: float
    medal_gold: float
    medal_silver: float
    medal_bronze: float


class SkillConfigUpdateRequest(Struct):
    """Partial-update body for `PATCH /skill/config` (superuser only).

    Every field is optional with PATCH semantics: an omitted field decodes to
    `UNSET` and is left unchanged. msgspec strict typing rejects non-float weight
    inputs at decode (T-13-03); semantic range validation lives in the DB/service.

    Attributes:
        diff_base: New difficulty-floor base, or UNSET to leave unchanged.
        gamma: New diminishing-returns exponent, or UNSET to leave unchanged.
        time_bonus: New max time-quality multiplier, or UNSET to leave unchanged.
        shrink_k: New field-size shrink constant, or UNSET to leave unchanged.
        wr_bonus: New world-record bonus, or UNSET to leave unchanged.
        partial_factor: New partial-clear multiplier, or UNSET to leave unchanged.
        medal_gold: New Gold-medal multiplier, or UNSET to leave unchanged.
        medal_silver: New Silver-medal multiplier, or UNSET to leave unchanged.
        medal_bronze: New Bronze-medal multiplier, or UNSET to leave unchanged.
    """

    diff_base: float | UnsetType = UNSET
    gamma: float | UnsetType = UNSET
    time_bonus: float | UnsetType = UNSET
    shrink_k: float | UnsetType = UNSET
    wr_bonus: float | UnsetType = UNSET
    partial_factor: float | UnsetType = UNSET
    medal_gold: float | UnsetType = UNSET
    medal_silver: float | UnsetType = UNSET
    medal_bronze: float | UnsetType = UNSET


class SkillSummaryResponse(Struct):
    """Per-player skill summary for `GET /skill/users/{id}`.

    Attributes:
        user_id: Identifier of the user.
        skill_score: Aggregate numeric skill score (0 when no eligible runs).
        maps_cleared: Number of distinct eligible maps cleared.
        video_clears: Number of fully-verified (video-proof) clears.
        hardest_raw: Highest `raw_difficulty` cleared (0 when no eligible runs).
        tier: Percentile tier 1..7, 0 = Unranked (no eligible runs / population floor not met).
        percentile: 0..1 population percentile of skill_score (0 when no eligible runs).
    """

    user_id: int
    skill_score: float
    maps_cleared: int
    video_clears: int
    hardest_raw: float
    tier: int
    percentile: float


class SkillTiersResponse(Struct):
    """Current tier legend for `GET /skill/tiers`.

    Exposes the cached percentile-based tier boundaries so the website can render a
    tier legend. Boundaries are DERIVED from the live distribution by recompute_all;
    an empty `boundaries` array means the population floor is not met (everyone
    Unranked). The `percentiles` array is the only tunable (seeded in migration 0028).

    Attributes:
        boundaries: The 6 computed cut-point scores (empty until a qualifying recompute).
        percentiles: The 6 configured percentiles that produce the boundaries.
        computed_at: When the boundaries were last computed.
    """

    boundaries: list[float]
    percentiles: list[float]
    computed_at: datetime


class SkillBreakdownRow(Struct):
    """One per-map breakdown entry for `GET /skill/users/{id}/breakdown`.

    Decodes straight from a `skill.snapshot.breakdown` JSONB array element via the
    app's jsonb<->msgspec codec (D-06). Field names mirror the scorer's
    `player_breakdown` dict keys exactly.

    Attributes:
        map_name: Display name (or code) of the map.
        difficulty: Difficulty-tier label of the map.
        raw: Raw difficulty (0-10 numeric) of the map.
        fully_verified: Whether the clear is fully verified (video proof).
        medal: Medal earned (Gold/Silver/Bronze), or None.
        wr: Whether the run is a video world record (video_rank == 1).
        raw_score: Per-map score before diminishing-returns decay.
        contribution: Per-map score after diminishing-returns decay.
        rank: 1-based position of this map within the player's sorted scores.
    """

    map_name: str
    difficulty: str
    raw: float
    fully_verified: bool
    medal: str | None
    wr: bool
    raw_score: float
    contribution: float
    rank: int
