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
    SkillBreakdownRow,
    SkillConfigUpdateRequest,
    SkillSummaryResponse,
    Weights,
)

from services import skill_service as svc
from services.exceptions.skill import InvalidGammaError
from services.skill_service import SkillService

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


def _make_service(mocker) -> tuple[SkillService, AsyncMock]:
    repo = mocker.AsyncMock()
    state = mocker.Mock()
    state.db_pool = mocker.Mock()
    service = SkillService(state.db_pool, state, repo)
    return service, repo


@pytest.fixture(autouse=True)
def _reset_guard():
    """Reset the process-wide recompute guard between tests."""
    svc._GUARD._lock = None
    svc._GUARD.rerun_requested = False
    yield
    svc._GUARD._lock = None
    svc._GUARD.rerun_requested = False


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

    async def slow_replace(_rows):
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


async def test_get_user_skill_empty_player_returns_zero(mocker):
    """get_user_skill returns an all-zero summary when no snapshot row exists (D-07)."""
    service, repo = _make_service(mocker)
    repo.fetch_snapshot.return_value = None

    result = await service.get_user_skill(999)

    assert result == SkillSummaryResponse(
        user_id=999, skill_score=0.0, maps_cleared=0, video_clears=0, hardest_raw=0.0
    )


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
