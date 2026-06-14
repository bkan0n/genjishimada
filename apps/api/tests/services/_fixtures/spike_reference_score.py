"""Frozen reference scorer (vendored test fixture).

This is a verbatim, frozen copy of the spike-002 reference scorer, duplicated into
the test tree so the equivalence test (`test_skill_scorer.py`) is fully self-contained
and runs in CI. It is the independent reference the ported `SkillService` is proven
against — do not edit it to track app behavior. Reference-only material is never read
from the planning or agent-config directories at test time.

Spike 002 — skill scorer + farming-resistance proof.

The kill-risk spike: if grinding many easy maps can out-score genuine hard-map performance, the
whole idea is dead. This implements the hybrid-verification scorer (Spike 001 requirements) and
pits adversarial synthetic profiles against each other to prove diminishing returns works.

Model (per the MANIFEST requirements):
  - FLOOR: every verified clear (partial or full) earns a difficulty weight from raw_difficulty.
  - PROOF MULTIPLIER: time-quality / medal / WR multipliers apply ONLY to fully-verified (video)
    runs. You can't multiply your score with an unproven (no-video) time.
  - DIMINISHING RETURNS: a player's per-map scores are sorted desc and summed as s_i / i**gamma,
    so the 1st map counts fully, the 50th barely. gamma is the anti-farm knob.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DATA = Path(__file__).parent.parent / "001-skill-input-query" / "skill_inputs.json"


@dataclass
class Weights:
    # Community-tuned defaults (tester round 1, adopted). Philosophy: skill = difficulty x breadth,
    # video-vs-screenshot is the main differentiator, time/medal/WR are light garnish.
    # Original exploratory defaults in comments for reference.
    diff_base: float = 1.44          # (was 1.41) diff_weight(raw) = diff_base ** (raw - 1.5) -> Easy~1, Hell~17
    gamma: float = 0.68              # (was 0.5)  diminishing-returns exponent; the anti-farm dial
    time_bonus: float = 0.55         # (was 1.0)  max additional multiplier for a field-topping time (video only)
    shrink_k: float = 10.0           # (was 4.0)  field-size shrinkage so small fields don't mint fake "wins"
    wr_bonus: float = 0.10           # (was 0.5)  extra multiplier when video_rank == 1 (world record)
    partial_factor: float = 0.60     # (was 1.0)  multiplier on the difficulty floor for partial (no-video) clears
    medal_mult: dict[str, float] = field(
        default_factory=lambda: {"Gold": 1.12, "Silver": 1.07, "Bronze": 1.03}  # (was 1.5/1.3/1.15)
    )


def diff_weight(raw: float, w: Weights) -> float:
    return w.diff_base ** (raw - 1.5)


def map_score(row: dict, w: Weights) -> float:
    """Score for one (user, map) row under the hybrid model."""
    floor = diff_weight(row["raw_difficulty"], w)
    if not row["fully_verified"]:
        return floor * w.partial_factor  # partial clear: difficulty floor only, no proof multipliers

    # fully verified (video proof) -> time / medal / WR multipliers unlock
    field_size = row["field_size"] or 1
    shrink = field_size / (field_size + w.shrink_k)          # 0..1, ~0 for tiny fields
    time_pct = row["time_pct"] or 0.0                         # 1.0 = fastest in field
    time_mult = 1 + w.time_bonus * shrink * time_pct
    medal_mult = w.medal_mult.get(row["medal"], 1.0) if row["medal"] else 1.0
    wr_mult = 1 + w.wr_bonus if row["video_rank"] == 1 else 1.0
    return floor * time_mult * medal_mult * wr_mult


def player_score(rows: list[dict], w: Weights) -> float:
    """Aggregate one player's per-map scores with diminishing returns."""
    scores = sorted((map_score(r, w) for r in rows), reverse=True)
    return sum(s / (i ** w.gamma) for i, s in enumerate(scores, start=1))


def player_breakdown(rows: list[dict], w: Weights) -> list[dict]:
    """Per-map contributions for one player, after diminishing-returns decay. Sorted by contribution."""
    scored = sorted(
        ((map_score(r, w), r) for r in rows), key=lambda t: t[0], reverse=True
    )
    out = []
    for i, (s, r) in enumerate(scored, start=1):
        decay = i ** w.gamma
        out.append({
            "map_name": r.get("map_name") or r.get("code") or f"map {r.get('map_id')}",
            "difficulty": r.get("difficulty", ""),
            "raw": r["raw_difficulty"],
            "fully_verified": r["fully_verified"],
            "medal": r.get("medal"),
            "wr": r.get("video_rank") == 1,
            "raw_score": s,
            "contribution": s / decay,
            "rank": i,
        })
    return out


def score_all(rows: list[dict], w: Weights) -> dict[int, dict]:
    by_user: dict[int, list[dict]] = {}
    for r in rows:
        by_user.setdefault(r["user_id"], []).append(r)
    out = {}
    for uid, urows in by_user.items():
        out[uid] = {
            "user_id": uid,
            "name": urows[0]["name"],
            "skill": player_score(urows, w),
            "maps": len(urows),
            "video_maps": sum(1 for r in urows if r["fully_verified"]),
            "hardest": max(r["raw_difficulty"] for r in urows),
        }
    return out


# ---------- adversarial synthetic profiles ----------

def fake_map(raw: float, *, video: bool, time_pct: float = 0.5, field: int = 20,
             medal: str | None = None, wr: bool = False) -> dict:
    return {
        "user_id": -1, "name": "synthetic", "raw_difficulty": raw, "time_pct": time_pct,
        "field_size": field, "fully_verified": video, "medal": medal,
        "video_rank": 1 if wr else None,
    }


def profiles() -> dict[str, list[dict]]:
    return {
        # grinds 200 Easy maps, screenshot-only (the farm we must defeat)
        "easy-grinder-200": [fake_map(1.5, video=False) for _ in range(200)],
        # grinds 200 Medium maps, screenshot-only (a harder farm)
        "medium-grinder-200": [fake_map(3.2, video=False) for _ in range(200)],
        # 10 Hell maps, video, strong times
        "hell-specialist-10": [fake_map(9.6, video=True, time_pct=0.85, field=20) for _ in range(10)],
        # 3 Hell world records on video (elite, low volume)
        "hell-wr-3": [fake_map(9.6, video=True, time_pct=1.0, field=25, medal="Gold", wr=True) for _ in range(3)],
        # broad strong player: 40 maps Medium->Extreme, video, decent times
        "all-rounder-40": [fake_map(3.5 + 0.12 * i, video=True, time_pct=0.6, field=15) for i in range(40)],
        # one perfect Hell WR and nothing else
        "one-hit-wonder": [fake_map(9.6, video=True, time_pct=1.0, field=30, medal="Gold", wr=True)],
    }


def main() -> None:
    rows = json.loads(DATA.read_text())
    w = Weights()

    print(f"Loaded {len(rows)} real rows. Weights: diff_base={w.diff_base} gamma={w.gamma} "
          f"time_bonus={w.time_bonus} wr_bonus={w.wr_bonus}\n")

    # --- 1. farming-resistance assertions on synthetic profiles ---
    print("=== Synthetic profiles (default weights) ===")
    ps = {name: player_score(maps, w) for name, maps in profiles().items()}
    for name, s in sorted(ps.items(), key=lambda kv: -kv[1]):
        n = len(profiles()[name])
        print(f"  {name:<22} skill={s:8.2f}   ({n} maps)")

    checks = [
        ("hell-specialist beats easy-grinder-200", ps["hell-specialist-10"] > ps["easy-grinder-200"]),
        ("hell-specialist beats medium-grinder-200", ps["hell-specialist-10"] > ps["medium-grinder-200"]),
        ("all-rounder-40 beats easy-grinder-200", ps["all-rounder-40"] > ps["easy-grinder-200"]),
        ("hell-wr-3 beats easy-grinder-200", ps["hell-wr-3"] > ps["easy-grinder-200"]),
        ("hell-specialist (10 video Hell) beats all-rounder (40 mid)", ps["hell-specialist-10"] > ps["all-rounder-40"]),
    ]
    print("\n=== Farming-resistance checks ===")
    all_pass = True
    for label, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        all_pass &= ok

    # --- 2. how much volume to break even? the gamma knob ---
    print("\n=== Break-even: how many Easy maps to match the Hell specialist? ===")
    target = ps["hell-specialist-10"]
    for gamma in (0.0, 0.3, 0.5, 0.7, 1.0):
        wg = Weights(gamma=gamma)
        t = player_score(profiles()["hell-specialist-10"], wg)
        n = 1
        while player_score([fake_map(1.5, video=False) for _ in range(n)], wg) < t and n < 1_000_000:
            n = int(n * 1.3) + 1
        verdict = "UNFARMABLE within 1M maps" if n >= 1_000_000 else f"{n:,} easy maps needed"
        print(f"  gamma={gamma:<4} hell-specialist={t:7.2f}  ->  {verdict}")

    # --- 3. real-data leaderboard sanity check ---
    print("\n=== Real-data skill leaderboard (top 15) ===")
    scored = sorted(score_all(rows, w).values(), key=lambda r: -r["skill"])
    for i, r in enumerate(scored[:15], 1):
        print(f"  {i:>2}. {r['name'][:24]:<24} skill={r['skill']:8.2f}  "
              f"maps={r['maps']:<4} video={r['video_maps']:<3} hardest_raw={r['hardest']:.2f}")

    # are top players actually hard-map players, or volume grinders?
    top10 = scored[:10]
    median_maps = sorted(r["maps"] for r in scored)[len(scored) // 2]
    print(f"\n  median maps/player = {median_maps}")
    print(f"  top-10 avg hardest_raw = {sum(r['hardest'] for r in top10) / 10:.2f} "
          f"(vs global avg {sum(r['hardest'] for r in scored) / len(scored):.2f})")

    print(f"\nVERDICT: {'farming resistance HOLDS' if all_pass else 'FARMING RESISTANCE FAILED'}")
    raise SystemExit(0 if all_pass else 1)


if __name__ == "__main__":
    main()
