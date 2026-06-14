# Spike Manifest

## Idea

Add a **skill score** to Genji Parkour that is fully **separate from XP**. XP rewards general
activity (completions, records, guides, playtests, map submissions). Skill should instead measure
actual in-game *performance*: clearing hard maps, and clearing them fast relative to other players.
The score is computed from verified completion data, resists farming (grinding easy maps can't beat
genuine hard-map skill), and feeds a skill leaderboard + per-map breakdown. Eventually exposed via
`/api/v3/skill/*` endpoints and a stored snapshot table, computed by a new `SkillService`.

## Requirements

Design decisions that emerged while spiking. Non-negotiable for the real build.

- **Skill stays separate from XP** — new computation, not derived from `lootbox.xp` or the existing
  completion-count rank tiers (Ninja…God). Those remain untouched.
- **Verified, non-legacy completions only** — `verified = TRUE AND legacy = FALSE`. Unverified,
  legacy, archived-map, and suspicious-flagged completions score 0 / are excluded.
- **Difficulty uses `raw_difficulty` (0–10 numeric), not the text tier** — continuous weighting is
  finer-grained and avoids cliff effects at tier boundaries.
- **Backbone signal is difficulty × time-quality-vs-field, NOT leaderboard rank.** Discovered in
  Spike 001: only **236** runs are ranked records (`completion = FALSE`) and only **90/1341** maps
  have medal thresholds — far too sparse to anchor a score. Time-percentile-vs-field is computable
  on **99.5%** of best-completions and is the dense signal.
- **Hybrid verification model (`completion` flag = verification depth).** `completion=TRUE` is a
  *partially-verified* clear (no video, screenshot-only); `completion=FALSE` is a *fully-verified*
  run (video proof). Skill uses both, differently:
  - **Floor:** any verified clear (partial or full) earns base `difficulty` credit — the whole
    community participates (272 players / 913 maps).
  - **Proof multiplier:** time-quality multipliers, medals, and WR/rank bonuses apply **only to
    fully-verified (video) runs** (42 players / 121 maps). You can't claim a fast time without
    video proof. This is the anti-cheat backbone — speed must be proven on video to multiply score.
- **Medals/leaderboard-rank/WR are sparse *bonus* layers**, not the base. They sharpen the top of
  the table but must not be required for a player to score.
- **Diminishing returns across maps** — farming many easy maps must not outweigh a few strong hard
  clears. (Validated in Spike 002.)
- **One best completion per (user, map)** — fastest verified non-legacy time; no double-counting.
- **Community-tuned default weights (tester round 1, adopted)** — starting point for the real build,
  validated by a domain-expert tester feeling the live leaderboard (Spike 003):
  ```
  diff_base=1.44  gamma=0.68  time_bonus=0.55  shrink_k=10.0
  wr_bonus=0.10   partial_factor=0.60   medals={Gold:1.12, Silver:1.07, Bronze:1.03}
  ```
  Philosophy: **skill = difficulty × breadth of clears; video-vs-screenshot is the main
  differentiator; time/medal/WR are light garnish.** These are *defaults*, not hardcoded — the real
  `SkillService` must keep them config-tunable. Known trade-off the tester accepted: flat proof
  bonuses mean the most prolific *video* player (Arrow, 45 video maps, Extreme+) ranks below
  Hell-breadth grinders.

## Spikes

| # | Name | Type | Validates | Verdict | Tags |
|---|------|------|-----------|---------|------|
| 001 | skill-input-query | standard | One query yields per-(user,map) `(raw_difficulty, time, time_pct_vs_field, medal, rank, is_wr, suspicious)` over real data, excluding legacy/unverified/archived/suspicious | ✓ VALIDATED | data, sql, asyncpg |
| 002 | scoring-farming-resistance | standard | Easy-map grinder ranks below genuine hard-map performer under diminishing returns | ✓ VALIDATED | algorithm, farming |
| 003 | leaderboard-feel | standard | Interactive leaderboard + live weight sliders + per-player breakdown; ranking matches intuition | ✓ VALIDATED | ui, leaderboard |
