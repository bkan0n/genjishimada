---
spike: 003
name: leaderboard-feel
type: standard
validates: "Given computed skill scores, when shown as an interactive leaderboard with live weight sliders and per-player breakdowns over real data, then the ranking matches community intuition and the knobs behave predictably"
verdict: VALIDATED
related: [001, 002]
tags: [ui, leaderboard]
---

# Spike 003: Leaderboard Feel

## What This Validates

Given the scorer from Spike 002, when the real 261-player community is rendered as a live-tunable
leaderboard, then a human can *feel* whether the ranking is right — and watch farming resistance
hold (or break at gamma=0) by dragging a slider, rather than trusting an assertion.

## Architecture (real spike-to-spike integration)

- `server.py` — stdlib `http.server`, **no dependencies**. Imports Spike 002's `score.py` directly
  (the scorer is the single source of truth) and reads Spike 001's `skill_inputs.json`. This is a
  genuine integration: 001 (data) → 002 (scorer) → 003 (UI), each spike consuming the last.
- `index.html` — vanilla JS, no build step. Sliders POST weights to `/api/score`; clicking a player
  POSTs to `/api/player` for the gamma-decayed per-map breakdown.

## How to Run

```bash
python3 .planning/spikes/003-leaderboard-feel/server.py
# open http://localhost:8077
```

## What to Expect

- A dark leaderboard of 261 real players, skill bars, maps / video / hardest-raw columns.
- **Sliders** (left): `diff_base`, `gamma`, `time_bonus`, `wr_bonus`, `partial_factor`, `shrink_k`,
  `medal_gold`. The board re-ranks ~90ms after any drag.
- **"Make farmable" (gamma=0) + "inject ★ farm profiles"**: `medium-grinder-200` jumps to ~#42 and
  `easy-grinder-200` to ~#62 — farming visibly succeeds. Raise gamma and they sink back. This is the
  felt version of Spike 002's break-even table.
- **Click a player** → per-map breakdown with `raw_score` and gamma-decayed `+contribution`, plus
  `video` / `floor` / `Gold|Silver|Bronze` / `WR` badges.

## Investigation Trail

1. Built server importing 002's scorer (no logic duplication) and a vanilla-JS frontend.
2. **Shell gotcha:** smoke-testing with `UID=$(...)` failed — `UID` is a read-only shell variable.
   Renamed to `PUID`; endpoints all returned correctly. (No server bug.)
3. **Verified the synthetic injection lands meaningfully:** at gamma=0 the farm profiles infiltrate
   the top half; at gamma≥0.5 they fall to the bottom — the UI reproduces Spike 002's math live.
4. **Breakdown confirmed the hybrid model visually:** the #1 player (뽈롱뽈롱뽀로로, only 7 video maps
   of 204) tops the board because those 7 are video Extreme/Hell runs with Gold medals scoring ~41
   each — vastly more than a 16.8 partial-Hell floor. Proof-multiplier made tangible.

## Results

**VALIDATED — confirmed by a domain-expert tester.** All endpoints work over real data; the sliders
re-rank live; farming resistance is visibly demonstrable by dragging gamma; per-player breakdowns
correctly attribute score to floor vs proof layers.

The decisive validation: the demo was zipped into a **standalone, dependency-free bundle** (see
`dist/genji-skill-leaderboard.zip` — Python-3-only, no DB, data baked in) and sent to a community
tester. They tuned the weights to their own intuition and sent them back:

```
diff_base=1.44  gamma=0.68  time_bonus=0.55  shrink_k=10.0
wr_bonus=0.10   partial_factor=0.60   medals={Gold:1.12, Silver:1.07, Bronze:1.03}
```

Running these against the real board confirmed the model behaves the way a domain expert *expects*:
- **Farming resistance strengthened** (hell-specialist 102 vs medium-grinder 16 — gap widened).
- Their `partial_factor=0.60` + `gamma=0.68` did exactly the intended thing: **Dosa #2→#6**
  (634 maps, 0 video) demoted; **Fidget →#2** (175 maps, 10 video) promoted. Video-proven hard
  clears beat raw screenshot volume.
- **Surfaced trade-off:** flattening all proof bonuses means the most prolific *video* player
  (Arrow, 45 video maps, Extreme+) ranks *below* Hell-breadth grinders. The tester's stance: skill
  is difficulty + breadth + did-you-video-it, not how flashy the video is. Accepted.

These weights were **adopted as the recommended defaults** (`score.py`, MANIFEST requirements). The
real `SkillService` keeps them config-tunable. A human feeling the leaderboard and having clear
opinions about the knobs *is* the validation this spike existed to get.
