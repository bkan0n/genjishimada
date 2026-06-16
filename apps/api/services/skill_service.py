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

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from itertools import pairwise
from typing import Literal

import msgspec
from asyncpg import Pool
from genjishimada_sdk.skill import (
    SkillBreakdownRow,
    SkillConfigUpdateRequest,
    SkillSummaryResponse,
    SkillTiersResponse,
    Weights,
    skill_tier_name,
)
from litestar.datastructures import State

from repository.skill_repository import SkillRepository
from services.exceptions.skill import InvalidGammaError, InvalidPercentilesError

from .base import BaseService

# The safe diminishing-returns floor (SPEC Constraint / T-13-09): below this the score
# approaches a pure sum and becomes farmable. The DB CHECK (gamma >= 0.5) is the backstop.
_GAMMA_FLOOR = 0.5

# The percentile tier system mints exactly this many cut-points (PYO-TIER-02), so a tier
# update MUST supply exactly this many percentiles — one per boundary. 7 boundaries mint
# integer tiers 1..8 via width_bucket; tier 0 is Unranked.
_TIER_PERCENTILE_COUNT = 7

# Read-time top-N cut for the change drill-down (D-06/D-07): the largest-|impact| per-map
# contributors are listed individually as `main_causes`; the remaining tail is rolled into a
# single `other_factors` scalar. N is a TUNABLE CODE CONSTANT, never stored — so the cutoff can
# change forever with no migration (forward-only history cannot be re-cut). Per-user map counts
# are small (<~50), so storing ALL impacts and cutting at read time is cheap.
_TOP_N = 5

# Window -> lookback duration for the history/changes reads. `all` has no bound (a far-past
# sentinel is used). Mirrors the SDK/route Literal; the route's msgspec-decoded `window` is the
# only validated source.
_WINDOW_DELTAS: dict[str, timedelta] = {
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
    "1y": timedelta(days=365),
}

# Far-past sentinel for the `all` window (timezone-aware so it compares against captured_at).
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

SkillWindow = Literal["7d", "30d", "90d", "1y", "all"]

# Per-recompute cause policy categories (D-08/D-09). PLAYER_ACTION resolves the actor; every
# other user-with-data is MAP_ENVIRONMENT. SYSTEM tags everyone "global recalculation".
_PLAYER_ACTION = "PLAYER_ACTION"
_MAP_ENVIRONMENT = "MAP_ENVIRONMENT"
_SYSTEM = "SYSTEM"

# Short human-readable reason strings stored on each change row (D-08/D-09). The per-recompute
# reason is shared by all of that recompute's change rows; the per-user cause_category is what
# distinguishes actor / bystander.
_SYSTEM_REASON = "global recalculation"
_PLAYER_ACTION_REASON = "verified completion"


@dataclass
class TriggerDescriptor:
    """A single recompute trigger's cause + actor (D-10).

    Accumulated on the module-scope ``_RecomputeGuard.pending`` so a burst's descriptors are
    evaluated together: exactly one clean completion descriptor (an actor set, cause
    PLAYER_ACTION) yields the actor/bystander split (D-08); two-or-more descriptors OR any
    SYSTEM descriptor promotes the whole recompute to SYSTEM "global recalculation" (D-09).

    Attributes:
        cause_category: The trigger's cause (``PLAYER_ACTION`` / ``MAP_ENVIRONMENT`` / ``SYSTEM``).
        actor_user_id: The completion owner for a PLAYER_ACTION trigger; ``None`` for SYSTEM.
    """

    cause_category: str = _SYSTEM
    actor_user_id: int | None = None


class _RecomputeGuard:
    """Process-wide in-flight collapse guard for recompute_all (D-05).

    Litestar constructs a fresh SkillService per request via DI, so a per-instance lock would
    never coalesce a burst across requests — the guard MUST live at module scope to be
    one-per-process. The lock is created lazily on first use so it binds to the running loop.

    The ``pending`` descriptor accumulator (D-10) ALSO lives here (module scope) for the same
    reason: a coalesced burst arriving across separate requests must aggregate its descriptors
    into one place so the cause policy can promote it to SYSTEM.
    """

    def __init__(self) -> None:
        self._lock: asyncio.Lock | None = None
        self.rerun_requested = False
        self.pending: list[TriggerDescriptor] = []

    @property
    def lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock


# Single process-wide guard instance shared by every SkillService.
_GUARD = _RecomputeGuard()


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


def _build_diff(prev_breakdown: list[dict], new_breakdown: list[dict]) -> dict:
    """Build the all-maps impact array for a change row (D-04).

    Joins the previous and new per-map breakdowns on ``map_name`` (A2 — the breakdown's stable
    display key; the breakdown carries no ``map_id``) and emits one entry per map in the union:
    ``{"map", "prev", "new", "impact"}`` where ``prev``/``new`` are the decayed ``contribution``
    on each side (0.0 when the map is absent on that side) and ``impact = new - prev``. Because
    ``skill_score == Σ contribution`` (the scorer's own decomposition), ``Σ impact == delta``
    EXACTLY at write time — conservation is by construction, never read-time rebalancing.

    Args:
        prev_breakdown: The user's per-map breakdown from the PREVIOUS snapshot (may be empty).
        new_breakdown: The user's per-map breakdown from the NEW snapshot (may be empty).

    Returns:
        ``{"maps": [{"map": str, "prev": float, "new": float, "impact": float}, ...]}``.
    """
    prev_by_map = {row["map_name"]: float(row.get("contribution") or 0.0) for row in prev_breakdown}
    new_by_map = {row["map_name"]: float(row.get("contribution") or 0.0) for row in new_breakdown}
    maps: list[dict] = []
    for map_name in {*prev_by_map, *new_by_map}:
        prev_c = prev_by_map.get(map_name, 0.0)
        new_c = new_by_map.get(map_name, 0.0)
        maps.append({"map": map_name, "prev": prev_c, "new": new_c, "impact": new_c - prev_c})
    return {"maps": maps}


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

    async def recompute_all(self, descriptor: TriggerDescriptor | None = None) -> None:
        """Rebuild the entire skill snapshot from scratch — THE single rebuild routine (D-04).

        Called by the in-process verification-change event (13-05), the nightly backstop
        (13-05), and PATCH config (13-05). Reads the weights from the DB config (req 5 — never
        literals), re-runs the input query, scores every player, captures the per-map
        breakdown (D-06), and atomically replaces the lean snapshot (only players with >=1
        eligible run get a row, D-07). On every recompute it ALSO captures one history point +
        one change record per user-with-data (D-02), riding this single routine (no forked
        compute path).

        A per-process in-flight collapse guard (D-05) ensures a burst of triggers does not
        launch N overlapping full rebuilds: while one rebuild runs, additional calls set a
        "rerun requested" flag instead of starting their own; the holder loops once more so
        the final snapshot is consistent with the latest inputs.

        Each trigger's cause descriptor (D-10) is appended to the module-scope accumulator
        BEFORE the in-flight early return — so a coalesced trigger still records its descriptor
        — and the accumulator is DRAINED inside the rerun loop (Pitfall 2): descriptors that
        arrived mid-rebuild belong to the rerun, so the cause policy is resolved per
        ``_do_recompute`` call.

        Args:
            descriptor: The trigger's cause + actor. ``None`` defaults to a SYSTEM descriptor
                (nightly backstop / cold-start / PATCH callers that pass nothing).
        """
        _GUARD.pending.append(descriptor if descriptor is not None else TriggerDescriptor())
        _GUARD.rerun_requested = True
        if _GUARD.lock.locked():
            # A rebuild is already running; it will pick up the rerun_requested flag and drain
            # the descriptor we just appended on its next loop iteration.
            return
        async with _GUARD.lock:
            while _GUARD.rerun_requested:
                _GUARD.rerun_requested = False
                # Drain INSIDE the loop (Pitfall 2): descriptors that arrived during the prior
                # _do_recompute belong to THIS rerun, so resolve the policy per iteration.
                drained = _GUARD.pending[:]
                _GUARD.pending.clear()
                policy = self._resolve_cause_policy(drained)
                await self._do_recompute(policy)

    @staticmethod
    def _resolve_cause_policy(drained: list[TriggerDescriptor]) -> tuple[str, int | None]:
        """Resolve the per-recompute cause policy from the drained descriptors (D-08/D-09).

        A single clean completion descriptor (cause PLAYER_ACTION with an actor) yields the
        actor/bystander split: ``(PLAYER_ACTION, actor_id)``. Anything else — two or more
        descriptors, any SYSTEM descriptor, or a lone descriptor with no actor — promotes the
        whole recompute to ``(SYSTEM, None)`` "global recalculation".

        Args:
            drained: The descriptors accumulated for this recompute.

        Returns:
            A ``(cause_category, actor_user_id)`` tuple. ``PLAYER_ACTION`` carries the actor;
            ``SYSTEM`` carries ``None``.
        """
        if len(drained) == 1 and drained[0].cause_category == _PLAYER_ACTION and drained[0].actor_user_id is not None:
            return (_PLAYER_ACTION, drained[0].actor_user_id)
        return (_SYSTEM, None)

    async def _do_recompute(self, policy: tuple[str, int | None]) -> None:
        """Run one full snapshot rebuild + capture (no locking; callers hold the guard).

        Reads the previous snapshot BEFORE ``replace_snapshot`` TRUNCATEs (Pitfall 1 / D-05),
        scores every player, then — for each user-with-data — builds one ``score_history`` row
        and one ``score_change`` row whose per-map ``diff`` conserves exactly (``Σ impact ==
        delta`` by construction, D-04). Snapshot replace, both bulk inserts, and the tier
        recompute run in ONE transaction (Pitfall 6) mirroring ``update_tier_config``.

        Args:
            policy: The resolved ``(cause_category, actor_user_id)`` cause policy (D-08/D-09).
        """
        cause_category, actor_id = policy
        reason = _SYSTEM_REASON if cause_category == _SYSTEM else _PLAYER_ACTION_REASON

        w = msgspec.convert(await self._skill_repo.fetch_weights(), Weights)
        rows = await self._skill_repo.fetch_skill_inputs()

        by_user: dict[int, list[dict]] = defaultdict(list)
        for r in rows:
            by_user[r["user_id"]].append(r)

        # The SINGLE captured_at reused for every history + change row of this recompute (D-02);
        # do NOT mint a second timestamp.
        computed_at = datetime.now(timezone.utc)

        async with self._pool.acquire() as conn, conn.transaction():
            # Read prev snapshot BEFORE replace_snapshot truncates (Pitfall 1 / D-05).
            prev = await self._skill_repo.fetch_all_snapshots(conn=conn)  # type: ignore[arg-type]

            snapshot_rows: list[dict] = []
            history_rows: list[dict] = []
            change_rows: list[dict] = []
            for user_id, urows in by_user.items():
                breakdown = _player_breakdown(urows, w)
                new_score = _player_score(urows, w)
                snapshot_rows.append(
                    {
                        "user_id": user_id,
                        "skill_score": new_score,
                        "maps_cleared": len(urows),
                        "video_clears": sum(1 for r in urows if r["fully_verified"]),
                        "hardest_raw": max(r["raw_difficulty"] for r in urows),
                        "breakdown": breakdown,
                        "computed_at": computed_at,
                    }
                )

                previous_score = float(prev.get(user_id, {}).get("skill_score") or 0.0)
                delta = new_score - previous_score
                diff = _build_diff(prev.get(user_id, {}).get("breakdown") or [], breakdown)

                if cause_category == _SYSTEM:
                    user_cause = _SYSTEM
                elif user_id == actor_id:
                    user_cause = _PLAYER_ACTION
                else:
                    user_cause = _MAP_ENVIRONMENT

                history_rows.append({"user_id": user_id, "captured_at": computed_at, "skill_score": new_score})
                change_rows.append(
                    {
                        "user_id": user_id,
                        "captured_at": computed_at,
                        "previous_score": previous_score,
                        "new_score": new_score,
                        "delta": delta,
                        "cause_category": user_cause,
                        "reason": reason,
                        "diff": diff,
                    }
                )

            await self._skill_repo.replace_snapshot(snapshot_rows, conn=conn)  # type: ignore[arg-type]
            await self._skill_repo.bulk_insert_history(history_rows, conn=conn)  # type: ignore[arg-type]
            await self._skill_repo.bulk_insert_changes(change_rows, conn=conn)  # type: ignore[arg-type]
            # Flicker decision: recompute the tier boundaries on EVERY snapshot rebuild, riding
            # the single D-04 routine (no fork) so verify/reject/flag events, the nightly
            # backstop, and PATCH config all keep skill.tier_config consistent with the snapshot
            # that produced it. Tradeoff: a player's tier can shift when the field around them
            # moves even if their own score is unchanged — acceptable for a display-only badge.
            await self._skill_repo.compute_tier_boundaries(conn=conn)  # type: ignore[arg-type]

    async def get_user_skill(self, user_id: int) -> SkillSummaryResponse:
        """Fetch a player's skill summary, honoring the D-07 empty-player rule.

        Args:
            user_id: Discord user ID.

        Returns:
            The player's summary (incl. tier + percentile), or an all-zero / Unranked
            summary when no snapshot row exists.
        """
        row = await self._skill_repo.fetch_snapshot_with_tier(user_id)
        if row is None:
            return SkillSummaryResponse(
                user_id=user_id,
                skill_score=0.0,
                maps_cleared=0,
                video_clears=0,
                hardest_raw=0.0,
                tier=0,
                percentile=0.0,
                skill_tier_name=skill_tier_name(0),
            )
        # Map the integer tier to its display name via the SDK single source of truth; the
        # snapshot/tier row carries `tier` but not `skill_tier_name`, so inject it before convert.
        row = {**dict(row), "skill_tier_name": skill_tier_name(int(row["tier"]))}
        return msgspec.convert(row, SkillSummaryResponse)

    async def get_user_breakdown(self, user_id: int) -> list[SkillBreakdownRow]:
        """Fetch a player's per-map breakdown (D-06), or [] when no snapshot row exists (D-07).

        Args:
            user_id: Discord user ID.

        Returns:
            The decoded per-map breakdown rows, or an empty list for zero-eligible players.
        """
        row = await self._skill_repo.fetch_snapshot(user_id)
        if row is None:
            return []
        return msgspec.convert(row["breakdown"], list[SkillBreakdownRow])

    async def get_tier_config(self) -> SkillTiersResponse:
        """Read the current tier legend: boundaries, percentiles, and computed_at (PYO-TIER-05).

        Returns:
            The current tier configuration. An empty ``boundaries`` array means the
            population floor is not met (everyone Unranked).
        """
        return msgspec.convert(await self._skill_repo.fetch_tier_config(), SkillTiersResponse)

    async def get_weights(self) -> Weights:
        """Read the current tuning weights from the DB config (req 5)."""
        return msgspec.convert(await self._skill_repo.fetch_weights(), Weights)

    async def update_weights(self, data: SkillConfigUpdateRequest) -> Weights:
        """Partial-update the weight config (pure write; PATCH triggers recompute in the route).

        Only the set (non-UNSET) fields are written. A gamma below the safe floor is rejected
        before the write (SPEC Constraint / T-13-09); the DB CHECK is the backstop.

        Args:
            data: The partial PATCH body.

        Returns:
            The full updated weight config.

        Raises:
            InvalidGammaError: If gamma is being set below 0.5.
        """
        updates = {field: value for field, value in msgspec.structs.asdict(data).items() if value is not msgspec.UNSET}
        gamma = updates.get("gamma")
        if gamma is not None and gamma < _GAMMA_FLOOR:
            raise InvalidGammaError(gamma)
        return msgspec.convert(await self._skill_repo.update_weights(updates), Weights)

    async def update_tier_config(self, percentiles: list[float]) -> SkillTiersResponse:
        """Replace the tier percentiles, then re-derive the boundaries (U82-TIER-PATCH-01).

        Validates the supplied percentiles BEFORE any write (nothing is persisted on a
        rejected update, T-u82-02): exactly ``_TIER_PERCENTILE_COUNT`` values, every value
        strictly within ``(0, 1)``, and strictly increasing. On valid input it persists the
        percentiles and re-derives the boundaries from the CURRENT snapshot on a SINGLE
        connection (one transaction) by reusing the existing ``compute_tier_boundaries`` — it
        does NOT re-run the full ``recompute_all`` (scores are unchanged; only the percentile
        config and its derived boundaries move).

        Args:
            percentiles: The full replacement percentile array.

        Returns:
            The updated tier configuration (boundaries re-derived, computed_at refreshed).

        Raises:
            InvalidPercentilesError: If the array is not exactly 7 values, any value is not
                strictly within (0, 1), or the values are not strictly increasing.
        """
        if len(percentiles) != _TIER_PERCENTILE_COUNT:
            raise InvalidPercentilesError(f"percentiles must contain exactly {_TIER_PERCENTILE_COUNT} values.")
        if any(not (0.0 < p < 1.0) for p in percentiles):
            raise InvalidPercentilesError("every percentile must be strictly between 0 and 1.")
        if any(b <= a for a, b in pairwise(percentiles)):
            raise InvalidPercentilesError("percentiles must be strictly increasing.")

        async with self._pool.acquire() as conn, conn.transaction():
            await self._skill_repo.update_percentiles(percentiles, conn=conn)  # type: ignore[arg-type]
            await self._skill_repo.compute_tier_boundaries(conn=conn)  # type: ignore[arg-type]
            row = await self._skill_repo.fetch_tier_config(conn=conn)  # type: ignore[arg-type]
        return msgspec.convert(row, SkillTiersResponse)


async def provide_skill_service(state: State, skill_repo: SkillRepository) -> SkillService:
    """Litestar DI provider for SkillService."""
    return SkillService(state.db_pool, state, skill_repo)
