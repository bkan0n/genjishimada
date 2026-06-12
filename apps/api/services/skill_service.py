"""Skill-score service: the hybrid scorer + the single rebuild routine + read methods.

The scoring math is a faithful port of the spike's farming-resistance scorer
(`sources/002-scoring-farming-resistance/score.py:44-106`): a per-map difficulty
FLOOR, video-gated PROOF multipliers, field-size shrink, and a diminishing-returns
aggregation `Σ sᵢ / iᵞ`. Every weight is read from the DB config at compute time
(`skill.weight_config` via `SkillRepository.fetch_weights`) — there are NO weight
literals in this module (SPEC req 5). Only the structural identities of the spike
formula (the `1.5` floor offset and the neutral `1`/`1.0`/`0.0` multiplier defaults)
appear as constants.
"""

from __future__ import annotations

from asyncpg import Pool
from genjishimada_sdk.skill import Weights
from litestar.datastructures import State

from repository.skill_repository import SkillRepository

from .base import BaseService

# Structural constants of the spike scorer formula (NOT tunable weights):
#   _FLOOR_OFFSET — the `raw - 1.5` recentre so Easy(~1.5) -> ~1.
#   _NEUTRAL      — the identity multiplier for an absent medal / non-WR / partial field.
_FLOOR_OFFSET = 1.5
_NEUTRAL = 1.0


def _diff_weight(raw: float, w: Weights) -> float:
    """Exponential difficulty floor: ``diff_base ** (raw - 1.5)`` (port of score.py:44-45)."""
    return w.diff_base ** (raw - _FLOOR_OFFSET)


def _map_score(row: dict, w: Weights) -> float:
    """Score one (user, map) row under the hybrid model (port of score.py:48-61).

    Partial (screenshot) clears earn the difficulty floor only. Fully-verified (video)
    clears additionally unlock the time-quality, medal, and world-record multipliers,
    tempered by a field-size shrink so tiny fields cannot mint fake top-time bonuses.

    Args:
        row: One eligible (user, map) input row.
        w: The tuning weights loaded from the DB config.

    Returns:
        The per-map score before diminishing-returns decay.
    """
    floor = _diff_weight(row["raw_difficulty"], w)
    if not row["fully_verified"]:
        return floor * w.partial_factor  # partial clear: difficulty floor only, no proof multipliers

    field_size = row["field_size"] or 1
    shrink = field_size / (field_size + w.shrink_k)  # 0..1, ~0 for tiny fields -> tames noise
    time_pct = row["time_pct"] or 0.0  # 1.0 = fastest in field
    time_mult = _NEUTRAL + w.time_bonus * shrink * time_pct
    medal_mult = (
        {"Gold": w.medal_gold, "Silver": w.medal_silver, "Bronze": w.medal_bronze}.get(row["medal"], _NEUTRAL)
        if row["medal"]
        else _NEUTRAL
    )
    wr_mult = _NEUTRAL + w.wr_bonus if row["video_rank"] == 1 else _NEUTRAL
    return floor * time_mult * medal_mult * wr_mult


def _player_score(rows: list[dict], w: Weights) -> float:
    """Aggregate one player's per-map scores with diminishing returns (port of score.py:64-67).

    Per-map scores are sorted descending and summed as ``sᵢ / iᵞ`` (1-based ``i``), so the
    best map counts fully and each subsequent map contributes less — the anti-farm dial.

    Args:
        rows: All of one player's eligible (user, map) rows.
        w: The tuning weights loaded from the DB config.

    Returns:
        The player's aggregate skill score.
    """
    scores = sorted((_map_score(r, w) for r in rows), reverse=True)
    return sum(s / (i**w.gamma) for i, s in enumerate(scores, start=1))


def _player_breakdown(rows: list[dict], w: Weights) -> list[dict]:
    """Per-map contributions for one player after decay (port of score.py:70-89).

    The returned dict keys mirror ``SkillBreakdownRow`` exactly so the stored JSONB array
    decodes straight into ``list[SkillBreakdownRow]`` via the app's jsonb<->msgspec codec
    (D-06).

    Args:
        rows: All of one player's eligible (user, map) rows.
        w: The tuning weights loaded from the DB config.

    Returns:
        A list of per-map breakdown dicts, sorted by raw score descending.
    """
    scored = sorted(((_map_score(r, w), r) for r in rows), key=lambda t: t[0], reverse=True)
    out: list[dict] = []
    for i, (s, r) in enumerate(scored, start=1):
        decay = i**w.gamma
        out.append(
            {
                "map_name": r.get("map_name") or r.get("code") or f"map {r.get('map_id')}",
                "difficulty": r.get("difficulty", ""),
                "raw": r["raw_difficulty"],
                "fully_verified": r["fully_verified"],
                "medal": r.get("medal"),
                "wr": r.get("video_rank") == 1,
                "raw_score": s,
                "contribution": s / decay,
                "rank": i,
            }
        )
    return out


class SkillService(BaseService):
    """Service for the skill-score domain: scorer, rebuild routine, and read methods."""

    def __init__(self, pool: Pool, state: State, skill_repo: SkillRepository) -> None:
        """Initialize skill service.

        Args:
            pool: AsyncPG connection pool.
            state: Application state.
            skill_repo: Skill repository.
        """
        super().__init__(pool, state)
        self._skill_repo = skill_repo


async def provide_skill_service(state: State, skill_repo: SkillRepository) -> SkillService:
    """Litestar DI provider for SkillService."""
    return SkillService(state.db_pool, state, skill_repo)
