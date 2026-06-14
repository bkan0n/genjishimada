"""Equivalence tests for the ported skill scorer.

These are pure-Python unit tests (no DB): they load the cached real-data inputs
(`skill_inputs.json`) and the spike's reference scorer
(`spike_reference_score.py`) via importlib, then assert that
`SkillService`'s ported helpers reproduce the spike's totals within float
tolerance for every user. They also prove the two headline behaviors:
partial-vs-video gating and the gamma anti-farm dial.

Both fixtures are frozen copies vendored into `_fixtures/` (duplicated from the
spike reference material). Tests never reach into the planning or agent-config
directories — that material is reference-only and absent from CI checkouts.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path

import pytest
from genjishimada_sdk.skill import Weights

from services import skill_service as svc

pytestmark = [pytest.mark.domain_skill]

_FIXTURES = Path(__file__).resolve().parent / "_fixtures"
_SKILL_INPUTS = _FIXTURES / "skill_inputs.json"
_SPIKE_SCORE = _FIXTURES / "spike_reference_score.py"

# The adopted community-tuned defaults (D-09). The real weights live in the DB seed;
# the test supplies them explicitly to build a Weights struct for the equivalence proof.
_ADOPTED = {
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

_TOL = 1e-6


def _load_spike_module():
    """Import the spike reference scorer (score.py) by file path."""
    spec = importlib.util.spec_from_file_location("spike_score", _SPIKE_SCORE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec: the spike's @dataclass resolves field annotations against
    # sys.modules[cls.__module__] during class creation.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _adopted_weights() -> Weights:
    return Weights(**_ADOPTED)


def _load_inputs() -> list[dict]:
    return json.loads(_SKILL_INPUTS.read_text())


def _group_by_user(rows: list[dict]) -> dict[int, list[dict]]:
    by_user: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        by_user[r["user_id"]].append(r)
    return by_user


def test_player_totals_match_spike_within_tolerance():
    """SkillService player totals equal the spike's player_score for every user (SPEC AC)."""
    spike = _load_spike_module()
    rows = _load_inputs()
    w = _adopted_weights()
    spike_w = spike.Weights()  # adopted defaults are the spike dataclass defaults

    by_user = _group_by_user(rows)
    assert by_user, "expected at least one user in the cached inputs"

    for uid, urows in by_user.items():
        ours = svc._player_score(urows, w)
        theirs = spike.player_score(urows, spike_w)
        assert abs(ours - theirs) <= _TOL, f"user {uid}: ours={ours} theirs={theirs}"


def test_partial_clear_scores_floor_only_and_below_video():
    """A partial (screenshot) clear scores exactly floor*partial_factor; the same row as
    video scores strictly higher (SPEC AC: partial = floor only)."""
    w = _adopted_weights()
    base = {
        "raw_difficulty": 7.0,
        "time_pct": 0.9,
        "field_size": 30,
        "medal": "Gold",
        "video_rank": 1,
    }
    partial = {**base, "fully_verified": False}
    video = {**base, "fully_verified": True}

    floor = svc._diff_weight(base["raw_difficulty"], w)
    partial_score = svc._map_score(partial, w)
    video_score = svc._map_score(video, w)

    assert abs(partial_score - floor * w.partial_factor) <= _TOL
    assert video_score > partial_score


def _easy_map(w: Weights) -> dict:
    return {
        "raw_difficulty": 1.5,
        "fully_verified": False,
        "time_pct": 0.0,
        "field_size": 20,
        "medal": None,
        "video_rank": None,
    }


def _hell_specialist(n: int) -> list[dict]:
    return [
        {
            "raw_difficulty": 9.6,
            "fully_verified": True,
            "time_pct": 0.85,
            "field_size": 20,
            "medal": None,
            "video_rank": None,
        }
        for _ in range(n)
    ]


def _break_even_easy_count(gamma: float) -> int:
    """Number of easy partial maps needed to match a 10-Hell video specialist."""
    w = Weights(**{**_ADOPTED, "gamma": gamma})
    target = svc._player_score(_hell_specialist(10), w)
    easy = _easy_map(w)
    n = 1
    while svc._player_score([easy for _ in range(n)], w) < target and n < 1_000_000:
        n = int(n * 1.3) + 1
    return n


def test_gamma_dial_lowers_break_even_count():
    """Lowering gamma toward 0 lowers the easy-map break-even count (SPEC AC: the gamma
    dial measurably changes farming resistance)."""
    high_gamma = _break_even_easy_count(0.68)
    low_gamma = _break_even_easy_count(0.3)
    assert low_gamma < high_gamma, f"gamma=0.3 break-even {low_gamma} not below gamma=0.68 {high_gamma}"
