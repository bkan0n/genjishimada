from __future__ import annotations

from datetime import datetime
from typing import Literal

from msgspec import UNSET, Struct, UnsetType

__all__ = (
    "SKILL_TIER_NAMES",
    "CauseCategory",
    "SkillBreakdownRow",
    "SkillChangeCause",
    "SkillChangeDetailResponse",
    "SkillChangeFeedItem",
    "SkillConfigUpdateRequest",
    "SkillHistoryExtremum",
    "SkillHistoryPoint",
    "SkillHistoryResponse",
    "SkillHistorySummary",
    "SkillSummaryResponse",
    "SkillTiersResponse",
    "SkillTiersUpdateRequest",
    "Weights",
    "skill_tier_name",
)

# The single SDK source of truth for the closed set of skill-change cause categories.
# `PLAYER_ACTION` — the actor (completion owner) whose own verify/reject/flag triggered
# the recompute; `MAP_ENVIRONMENT` — a bystander whose score moved because the
# competitive field around them changed; `SYSTEM` — a global recalculation
# (config/tier PATCH, nightly backstop, cold-start, or any coalesced burst). msgspec
# strict decode rejects any value outside this set (T-14-04); the DB CHECK in migration
# 0031 is the persistence-side backstop.
#
# KNOWN LIMITATION (WR-04 / D-09): cause attribution is best-effort, not authoritative. When
# two recompute triggers coalesce (concurrent verifies, or a verify overlapping a nightly/PATCH
# rebuild) the whole batch is promoted to `SYSTEM`, so a genuine player-triggered change can be
# recorded as `SYSTEM` rather than `PLAYER_ACTION`. Consumers MUST treat `PLAYER_ACTION` as a
# hint only — never as proof a specific user personally caused the change — and must not assume a
# `SYSTEM` row had no player trigger.
CauseCategory = Literal["PLAYER_ACTION", "MAP_ENVIRONMENT", "SYSTEM"]


# The SINGLE source of truth mapping an integer percentile tier (0..8) to its display
# name. 7 seeded percentiles mint integer tiers 1..8 via ``width_bucket``; tier 0 is
# reserved for Unranked (no eligible runs / population floor not met). Reused by both the
# community leaderboard rows and the per-user skill summary so the names never drift.
SKILL_TIER_NAMES: dict[int, str] = {
    0: "Unranked",
    1: "Bronze",
    2: "Silver",
    3: "Gold",
    4: "Emerald",
    5: "Diamond",
    6: "Ascendant",
    7: "Elite",
    8: "Champion",
}


def skill_tier_name(tier: int) -> str:
    """Map an integer percentile tier to its display name.

    Args:
        tier: Integer tier (0..8). 0 is Unranked; 1..8 are Bronze..Champion.

    Returns:
        The tier's display name, falling back to ``"Unranked"`` for any out-of-range
        tier so callers never raise on an unexpected value.
    """
    return SKILL_TIER_NAMES.get(tier, "Unranked")


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


class SkillTiersUpdateRequest(Struct):
    """Update body for `PATCH /skill/tiers` (superuser only).

    Carries the full replacement ``percentiles`` array for the percentile-based tier
    system. msgspec strict typing rejects non-float inputs at decode; the semantic
    rules — exactly 7 values, each strictly in ``(0, 1)``, strictly increasing — are
    enforced server-side in ``SkillService.update_tier_config`` (raising a 400), NOT
    by msgspec. On any violation nothing is persisted.

    Attributes:
        percentiles: The 7 replacement percentiles (strictly increasing, all in ``(0, 1)``)
            that the existing boundary routine re-derives the tier cut-points from.
    """

    percentiles: list[float]


class SkillSummaryResponse(Struct):
    """Per-player skill summary for `GET /skill/users/{id}`.

    Attributes:
        user_id: Identifier of the user.
        skill_score: Aggregate numeric skill score (0 when no eligible runs).
        maps_cleared: Number of distinct eligible maps cleared.
        video_clears: Number of fully-verified (video-proof) clears.
        hardest_raw: Highest `raw_difficulty` cleared (0 when no eligible runs).
        tier: Percentile tier 1..8, 0 = Unranked (no eligible runs / population floor not met).
        percentile: 0..1 population percentile of skill_score (0 when no eligible runs).
        skill_tier_name: Mapped tier name (Unranked..Champion) for the integer ``tier``.
    """

    user_id: int
    skill_score: float
    maps_cleared: int
    video_clears: int
    hardest_raw: float
    tier: int
    percentile: float
    skill_tier_name: str


class SkillTiersResponse(Struct):
    """Current tier legend for `GET /skill/tiers`.

    Exposes the cached percentile-based tier boundaries so the website can render a
    tier legend. Boundaries are DERIVED from the live distribution by recompute_all;
    an empty `boundaries` array means the population floor is not met (everyone
    Unranked). The `percentiles` array is the only tunable (seeded in migration 0028).

    Attributes:
        boundaries: The 7 computed cut-point scores (empty until a qualifying recompute).
        percentiles: The 7 configured percentiles that produce the boundaries.
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


class SkillHistoryPoint(Struct):
    """One timestamped skill-score sample for `GET /skill/users/{id}/history`.

    Attributes:
        captured_at: When this score was recorded (the recompute's `captured_at`).
        skill_score: The user's aggregate skill score at that instant.
    """

    captured_at: datetime
    skill_score: float


class SkillHistoryExtremum(Struct):
    """A best- or lowest-score extremum within a history window.

    Attributes:
        score: The extremum score value (0 when the window has no points).
        date: When the extremum occurred, or None when there are no points
            (the empty / zero-summary shape, SPEC req 7).
    """

    score: float
    date: datetime | None


class SkillHistorySummary(Struct):
    """Window summary stats for `GET /skill/users/{id}/history`.

    Anchored on the earliest available record when the window predates it
    (SPEC req 3).

    Attributes:
        point_change: First-to-last absolute score change over the window.
        percent_change: First-to-last percent change over the window.
        best: Highest score point in the window (and when it occurred).
        lowest: Lowest score point in the window (and when it occurred).
        average: Mean score across the window's points.
    """

    point_change: float
    percent_change: float
    best: SkillHistoryExtremum
    lowest: SkillHistoryExtremum
    average: float


class SkillHistoryResponse(Struct):
    """Time-windowed score history for `GET /skill/users/{id}/history`.

    Attributes:
        user_id: Identifier of the user.
        points: Ordered score samples within the requested window (empty when none).
        summary: Window summary stats (zeroed when there are no points).
    """

    user_id: int
    points: list[SkillHistoryPoint]
    summary: SkillHistorySummary


class SkillChangeFeedItem(Struct):
    """One newest-first change-feed entry for `GET /skill/users/{id}/changes`.

    Attributes:
        change_id: Identifier of the change record (drill-down lookup key).
        captured_at: When the change was recorded.
        delta: Signed score change for this recompute (`new - previous`).
        cause_category: The closed-set cause of this change.
        description: Human-readable summary of the change cause.
    """

    change_id: int
    captured_at: datetime
    delta: float
    cause_category: CauseCategory
    description: str


class SkillChangeCause(Struct):
    """One per-map contributor in a change drill-down's `main_causes`.

    Attributes:
        map: Display name (or code) of the map whose contribution shifted.
        reason: Human-readable reason for this map's impact.
        impact: Signed decayed-contribution change for this map (`new - prev`).
    """

    map: str
    reason: str
    impact: float


class SkillChangeDetailResponse(Struct):
    """Change drill-down for `GET /skill/users/{id}/changes/{change_id}`.

    The top-N (code-tunable, N=5) per-map contributors are listed individually in
    `main_causes`; the remaining tail is rolled into `other_factors` so
    `sum(main_causes.impact) + other_factors == delta` within 1e-6 (D-07).

    Attributes:
        change_id: Identifier of the change record.
        captured_at: When the change was recorded.
        previous_score: The user's score before this recompute.
        new_score: The user's score after this recompute.
        delta: Signed score change (`new_score - previous_score`).
        percent_change: Percent change from `previous_score` to `new_score`.
        cause_category: The closed-set cause of this change.
        main_causes: Top-N per-map contributors by absolute impact.
        other_factors: Summed impact of the remaining (untruncated) tail of maps.
    """

    change_id: int
    captured_at: datetime
    previous_score: float
    new_score: float
    delta: float
    percent_change: float
    cause_category: CauseCategory
    main_causes: list[SkillChangeCause]
    other_factors: float
