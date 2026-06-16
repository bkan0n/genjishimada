"""Unit tests for SkillService methods (recompute, reads, weight update).

Pure-logic tests with a mocked SkillRepository — no DB. They cover the D-04/D-05
rebuild routine + in-flight collapse guard, the D-07 empty-player read rule, the D-06
breakdown decode, and the gamma>=0.5 guard.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from genjishimada_sdk.skill import (
    SKILL_TIER_NAMES,
    SkillBreakdownRow,
    SkillConfigUpdateRequest,
    SkillSummaryResponse,
    SkillTiersUpdateRequest,
    Weights,
    skill_tier_name,
)

from services import skill_service as svc
from services.exceptions.skill import InvalidGammaError, InvalidPercentilesError
from services.skill_service import SkillService, TriggerDescriptor

pytestmark = [pytest.mark.domain_skill]

_WEIGHTS = {
    "diff_base": 1.44,
    "gamma": 0.68,
    "time_bonus": 0.55,
    "shrink_k": 10.0,
    "wr_bonus": 0.10,
    "partial_factor": 0.60,
    "medal_gold": 1.12,
    "medal_silver": 1.07,
    "medal_bronze": 1.03,
}


class _FakeAcquire:
    """Async-context-manager stand-in for ``pool.acquire()`` yielding a fake connection."""

    def __init__(self, conn) -> None:
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *_exc) -> None:
        return None


class _FakeTransaction:
    """Async-context-manager stand-in for ``conn.transaction()`` (a no-op)."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc) -> None:
        return None


def _make_service(mocker) -> tuple[SkillService, AsyncMock]:
    repo = mocker.AsyncMock()
    state = mocker.Mock()
    # _do_recompute runs inside `async with self._pool.acquire() as conn, conn.transaction():`
    # (Pitfall 6 atomic capture), so the mocked pool/conn must support those async CMs.
    conn = mocker.Mock()
    conn.transaction = lambda: _FakeTransaction()
    pool = mocker.Mock()
    pool.acquire = lambda: _FakeAcquire(conn)
    state.db_pool = pool
    # Default: no previous snapshot (first recompute). Tests that exercise prev-before-truncate
    # override this with a populated {user_id: {"skill_score", "breakdown"}} dict.
    repo.fetch_all_snapshots.return_value = {}
    service = SkillService(pool, state, repo)
    return service, repo


@pytest.fixture(autouse=True)
def _reset_guard():
    """Reset the process-wide recompute guard between tests.

    Clears the descriptor accumulator (D-10) in BOTH halves so a test's burst descriptors
    never leak into the next test's cause-policy resolution.
    """
    svc._GUARD._lock = None
    svc._GUARD.rerun_requested = False
    svc._GUARD.pending.clear()
    yield
    svc._GUARD._lock = None
    svc._GUARD.rerun_requested = False
    svc._GUARD.pending.clear()


def _input_row(user_id: int, raw: float, *, video: bool) -> dict:
    return {
        "user_id": user_id,
        "map_name": f"map-{raw}",
        "code": "ABCDE",
        "map_id": 1,
        "difficulty": "Hell",
        "raw_difficulty": raw,
        "fully_verified": video,
        "field_size": 20,
        "time_pct": 0.5,
        "medal": None,
        "video_rank": None,
    }


async def test_recompute_all_groups_and_replaces_snapshot(mocker):
    """recompute_all reads weights, scores per user, and replaces the lean snapshot (D-04/D-07)."""
    service, repo = _make_service(mocker)
    repo.fetch_weights.return_value = dict(_WEIGHTS)
    repo.fetch_skill_inputs.return_value = [
        _input_row(1, 9.6, video=True),
        _input_row(1, 7.0, video=False),
        _input_row(2, 5.0, video=True),
    ]

    await service.recompute_all()

    repo.replace_snapshot.assert_awaited_once()
    snapshot_rows = repo.replace_snapshot.await_args.args[0]
    assert {r["user_id"] for r in snapshot_rows} == {1, 2}
    user1 = next(r for r in snapshot_rows if r["user_id"] == 1)
    assert user1["maps_cleared"] == 2
    assert user1["video_clears"] == 1
    assert user1["hardest_raw"] == 9.6
    # breakdown contributions sum to the player's total within float tolerance (SPEC AC)
    total = sum(b["contribution"] for b in user1["breakdown"])
    assert abs(total - user1["skill_score"]) <= 1e-9


async def test_recompute_all_collapses_concurrent_bursts(mocker):
    """A burst of recompute_all calls does not launch overlapping rebuilds (D-05)."""
    service, repo = _make_service(mocker)
    repo.fetch_weights.return_value = dict(_WEIGHTS)
    repo.fetch_skill_inputs.return_value = [_input_row(1, 5.0, video=True)]

    started = 0
    release = asyncio.Event()

    async def slow_replace(_rows, *, conn=None):
        nonlocal started
        started += 1
        await release.wait()

    repo.replace_snapshot.side_effect = slow_replace

    # Fire 5 concurrent calls; the first acquires the lock, the rest set rerun_requested.
    tasks = [asyncio.create_task(service.recompute_all()) for _ in range(5)]
    await asyncio.sleep(0)  # let the first task acquire the lock and enter slow_replace
    release.set()
    await asyncio.gather(*tasks)

    # No overlap: at most one in-flight rebuild + one coalesced rerun (never 5).
    assert started <= 2


async def test_recompute_player_action_splits_actor_and_bystander(mocker):
    """One PLAYER_ACTION descriptor → actor row PLAYER_ACTION, bystander row MAP_ENVIRONMENT (D-08)."""
    service, repo = _make_service(mocker)
    repo.fetch_weights.return_value = dict(_WEIGHTS)
    # Two users with eligible runs: user 1 is the actor, user 2 a bystander.
    repo.fetch_skill_inputs.return_value = [
        _input_row(1, 9.6, video=True),
        _input_row(2, 5.0, video=True),
    ]

    await service.recompute_all(TriggerDescriptor(cause_category="PLAYER_ACTION", actor_user_id=1))

    repo.bulk_insert_changes.assert_awaited_once()
    change_rows = repo.bulk_insert_changes.await_args.args[0]
    by_uid = {r["user_id"]: r for r in change_rows}
    assert by_uid[1]["cause_category"] == "PLAYER_ACTION"
    assert by_uid[2]["cause_category"] == "MAP_ENVIRONMENT"
    assert by_uid[1]["reason"] == "verified completion"


async def test_recompute_coalesced_burst_promotes_to_system(mocker):
    """Two-or-more drained descriptors → every change row SYSTEM 'global recalculation' (D-09)."""
    service, repo = _make_service(mocker)
    repo.fetch_weights.return_value = dict(_WEIGHTS)
    repo.fetch_skill_inputs.return_value = [
        _input_row(1, 9.6, video=True),
        _input_row(2, 5.0, video=True),
    ]

    # Pre-load a second descriptor so the single recompute drains >=2 → SYSTEM promotion.
    svc._GUARD.pending.append(TriggerDescriptor(cause_category="PLAYER_ACTION", actor_user_id=99))
    await service.recompute_all(TriggerDescriptor(cause_category="PLAYER_ACTION", actor_user_id=1))

    change_rows = repo.bulk_insert_changes.await_args.args[0]
    assert all(r["cause_category"] == "SYSTEM" for r in change_rows)
    assert all(r["reason"] == "global recalculation" for r in change_rows)


async def test_recompute_reads_prev_snapshot_before_truncate(mocker):
    """The 2nd recompute's change rows carry previous_score from the prior snapshot (Pitfall 1)."""
    service, repo = _make_service(mocker)
    repo.fetch_weights.return_value = dict(_WEIGHTS)
    repo.fetch_skill_inputs.return_value = [_input_row(1, 9.6, video=True)]
    # Non-empty prev snapshot read BEFORE replace_snapshot — a populated prior score + breakdown.
    repo.fetch_all_snapshots.return_value = {
        1: {"skill_score": 3.0, "breakdown": [{"map_name": "old-map", "contribution": 3.0}]}
    }

    await service.recompute_all(TriggerDescriptor(cause_category="SYSTEM"))

    change_rows = repo.bulk_insert_changes.await_args.args[0]
    row = next(r for r in change_rows if r["user_id"] == 1)
    assert row["previous_score"] == 3.0
    assert abs(row["delta"] - (row["new_score"] - 3.0)) <= 1e-9


async def test_recompute_change_diff_conserves(mocker):
    """Σ diff.maps[*].impact ≈ delta within 1e-6 — conservation by construction (D-04)."""
    service, repo = _make_service(mocker)
    repo.fetch_weights.return_value = dict(_WEIGHTS)
    repo.fetch_skill_inputs.return_value = [
        _input_row(1, 9.6, video=True),
        _input_row(1, 7.0, video=False),
    ]
    # A prev≠new breakdown so the diff has non-trivial per-map impacts on both sides.
    repo.fetch_all_snapshots.return_value = {
        1: {"skill_score": 2.0, "breakdown": [{"map_name": "stale-map", "contribution": 2.0}]}
    }

    await service.recompute_all(TriggerDescriptor(cause_category="SYSTEM"))

    change_rows = repo.bulk_insert_changes.await_args.args[0]
    row = next(r for r in change_rows if r["user_id"] == 1)
    impact_sum = sum(m["impact"] for m in row["diff"]["maps"])
    assert abs(impact_sum - row["delta"]) <= 1e-6


async def test_get_user_skill_empty_player_returns_zero(mocker):
    """get_user_skill returns an all-zero / Unranked summary when no snapshot row exists (D-07)."""
    service, repo = _make_service(mocker)
    # get_user_skill now reads via fetch_snapshot_with_tier (tier/percentile join, PYO-TIER-03).
    repo.fetch_snapshot_with_tier.return_value = None

    result = await service.get_user_skill(999)

    assert result == SkillSummaryResponse(
        user_id=999,
        skill_score=0.0,
        maps_cleared=0,
        video_clears=0,
        hardest_raw=0.0,
        tier=0,
        percentile=0.0,
        skill_tier_name="Unranked",
    )


def test_skill_tier_name_map():
    """The int->name map covers 0..8 and falls back to Unranked for out-of-range tiers."""
    assert SKILL_TIER_NAMES[0] == "Unranked"
    assert SKILL_TIER_NAMES[8] == "Champion"
    assert len(SKILL_TIER_NAMES) == 9
    assert skill_tier_name(0) == "Unranked"
    assert skill_tier_name(8) == "Champion"
    assert skill_tier_name(99) == "Unranked"


async def test_get_user_breakdown_empty_player_returns_empty(mocker):
    """get_user_breakdown returns [] when no snapshot row exists (D-07)."""
    service, repo = _make_service(mocker)
    repo.fetch_snapshot.return_value = None

    assert await service.get_user_breakdown(999) == []


async def test_get_user_breakdown_decodes_jsonb_rows(mocker):
    """get_user_breakdown decodes the stored breakdown array into SkillBreakdownRow (D-06)."""
    service, repo = _make_service(mocker)
    repo.fetch_snapshot.return_value = {
        "breakdown": [
            {
                "map_name": "Lijiang",
                "difficulty": "Hell",
                "raw": 9.6,
                "fully_verified": True,
                "medal": None,
                "wr": False,
                "raw_score": 17.0,
                "contribution": 17.0,
                "rank": 1,
            }
        ]
    }

    rows = await service.get_user_breakdown(1)
    assert len(rows) == 1
    assert isinstance(rows[0], SkillBreakdownRow)
    assert rows[0].map_name == "Lijiang"


async def test_update_weights_rejects_low_gamma(mocker):
    """update_weights rejects gamma < 0.5 before writing (SPEC Constraint / T-13-09)."""
    service, repo = _make_service(mocker)

    with pytest.raises(InvalidGammaError):
        await service.update_weights(SkillConfigUpdateRequest(gamma=0.3))

    repo.update_weights.assert_not_awaited()


async def test_update_weights_writes_only_set_fields(mocker):
    """update_weights builds a dict of only the non-UNSET fields and returns the full row."""
    service, repo = _make_service(mocker)
    repo.update_weights.return_value = dict(_WEIGHTS, gamma=0.9)

    result = await service.update_weights(SkillConfigUpdateRequest(gamma=0.9))

    repo.update_weights.assert_awaited_once_with({"gamma": 0.9})
    assert isinstance(result, Weights)
    assert result.gamma == 0.9


async def test_update_tier_config_rejects_wrong_length(mocker):
    """update_tier_config rejects an array that is not exactly 7 values, before any write (T-u82-02)."""
    service, repo = _make_service(mocker)

    for bad in (
        [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],  # 6 values
        [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8],  # 8 values
    ):
        with pytest.raises(InvalidPercentilesError):
            await service.update_tier_config(bad)

    repo.update_percentiles.assert_not_awaited()
    repo.compute_tier_boundaries.assert_not_awaited()


async def test_update_tier_config_rejects_out_of_range(mocker):
    """A 7-element array containing a value at/outside (0, 1) is rejected; nothing persisted."""
    service, repo = _make_service(mocker)

    for bad in (
        [0.0, 0.2, 0.4, 0.6, 0.8, 0.9, 0.95],  # 0.0 not strictly > 0
        [0.2, 0.4, 0.6, 0.7, 0.8, 0.9, 1.0],  # 1.0 not strictly < 1
        [0.2, 0.4, 0.6, 0.7, 0.8, 0.9, 1.5],  # > 1
    ):
        with pytest.raises(InvalidPercentilesError):
            await service.update_tier_config(bad)

    repo.update_percentiles.assert_not_awaited()
    repo.compute_tier_boundaries.assert_not_awaited()


async def test_update_tier_config_rejects_non_increasing(mocker):
    """A 7-element in-range but non-strictly-increasing array is rejected; nothing persisted."""
    service, repo = _make_service(mocker)

    for bad in (
        [0.1, 0.2, 0.2, 0.4, 0.5, 0.6, 0.7],  # equal neighbours
        [0.1, 0.3, 0.2, 0.4, 0.5, 0.6, 0.7],  # decreasing step
    ):
        with pytest.raises(InvalidPercentilesError):
            await service.update_tier_config(bad)

    repo.update_percentiles.assert_not_awaited()
    repo.compute_tier_boundaries.assert_not_awaited()


def test_tier_update_request_round_trips():
    """SkillTiersUpdateRequest decodes a JSON percentiles array unchanged (SDK shape sanity)."""
    import msgspec

    decoded = msgspec.json.decode(
        b'{"percentiles":[0.1,0.2,0.3,0.4,0.5,0.6,0.7]}', type=SkillTiersUpdateRequest
    )
    assert decoded.percentiles == [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]
