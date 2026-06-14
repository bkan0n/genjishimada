---
spike: 002
name: scoring-farming-resistance
type: standard
validates: "Given a player who grinds many easy maps vs one who clears few hard maps well, when the diminishing-returns scorer runs, then the hard-map player ranks higher — farming cannot win"
verdict: VALIDATED
related: [001, 003]
tags: [algorithm, farming]
---

# Spike 002: Scoring & Farming Resistance

## What This Validates

Given the kill-risk — *can grinding easy maps out-score genuine hard-map performance?* — when the
hybrid-verification scorer with diminishing returns runs over both adversarial synthetic profiles
and the 261 real players, then hard-map performers rank above grinders at every credible weight
setting, and farming is provably suppressed.

## The Model

```
per-map FLOOR        diff_weight(raw) = diff_base ** (raw - 1.5)        # Easy~1 .. Hell~16
  (any verified clear, partial or full)

per-map PROOF LAYER  (fully-verified / video runs only)
  time_mult  = 1 + time_bonus * shrink * time_pct      shrink = field/(field+k)   # tames small fields
  medal_mult = {Gold:1.5, Silver:1.3, Bronze:1.15}
  wr_mult    = 1 + wr_bonus  if video_rank == 1

per-map score  = floor                              (partial clear)
               = floor * time_mult * medal * wr      (fully-verified clear)

PLAYER TOTAL   = Σ  s_i / i**gamma     over the player's per-map scores sorted descending
                 ^^^ diminishing returns: 1st map counts fully, 50th barely. gamma = anti-farm knob.
```

No external research needed — pure logic over Spike 001's exported `skill_inputs.json` (no DB read).

## How to Run

```bash
python3 .planning/spikes/002-scoring-farming-resistance/score.py
```

Exits 0 if all farming-resistance checks pass, 1 otherwise.

## What to Expect

All five farming checks PASS. Synthetic ranking (default weights):

```
hell-wr-3            154.75   (3 maps)     <- 3 video Hell WRs
hell-specialist-10   138.69   (10 maps)
all-rounder-40       101.93   (40 maps)
one-hit-wonder        68.48   (1 map)      <- single perfect Hell WR
medium-grinder-200    48.17   (200 maps)   <- farm
easy-grinder-200      26.86   (200 maps)   <- farm
```

## Investigation Trail

1. **Built the scorer** off the Spike 001 requirements and ran the adversarial profiles. All five
   checks passed first time — hard-map players beat both the 200-easy and 200-medium grinders.
2. **Quantified the gamma knob** with a break-even search: *how many Easy maps to match a 10-Hell
   video specialist?* This makes the anti-farm dial tangible (table below). gamma=0 is farmable
   (306 maps); gamma≥0.5 makes it absurd (5.5k+); gamma=1.0 is unfarmable.
3. **Sanity-checked the real leaderboard.** Top-10 avg `hardest_raw = 9.66` vs global `6.12` — the
   formula surfaces genuine Hell-clearers, not volume grinders. Good.
4. **Noticed the top players have `video=0`** (Dosa: 634 maps, 0 video, rank #2) and suspected the
   proof-multiplier layer was inert on real data. **Measured it** instead of assuming — and the
   result was more interesting than "inert" (see Results).

## Results

**VALIDATED — farming resistance holds at every credible weight.** Plus two findings that shape the
real build:

### gamma is the anti-farm dial (break-even to match a 10-Hell-video specialist)

| gamma | Easy maps needed | Reading |
|------:|------------------|---------|
| 0.0 | 306 | pure sum — **farmable**, do not ship |
| 0.3 | 1,141 | weak |
| 0.5 | 5,518 | solid default |
| 0.7 | 128,606 | aggressive |
| 1.0 | unfarmable (>1M) | peak-performance-only |

### The proof layer is bimodal, not inert — and that's the hybrid model working

Comparing full scoring vs difficulty-floor-only over the 261 real players:

- **Median score uplift from the proof layer: 0.00%** — most players submit no video, so time/medal/
  WR multipliers never fire for them. Their skill is pure diminishing-returns difficulty breadth.
- **But: max uplift +238.6%, 26 players boosted >1%, and 15 of the top 20 positions move.** For the
  41 players who actually prove their speed on video, the proof layer is decisive and reshuffles the
  elite tier heavily (e.g. Arrow, 45 video maps, climbs).

This is the hybrid decision behaving exactly as intended: **clearing hard maps gets you a floor;
proving speed on video is what lets you climb the top of the ladder.** It is a *feature* that video
submission is the differentiator at the top, not a bug.

### Surprise / open tension for the build

With current data, **breadth of hard *partial* clears can still top the board** (Dosa #2: 634 maps,
0 video). Whether that's desirable is a product call, not a math bug — and it's exactly what the
`gamma` and `partial_factor` knobs control. Spike 003 makes this *felt*: slide `partial_factor` down
and watch pure-volume partial players demote beneath the video-proven players. The math is sound at
every setting; the remaining question is taste, which is why 003 is an interactive tuner.
