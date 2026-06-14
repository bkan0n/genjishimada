---
spike: 001
name: skill-input-query
type: standard
validates: "Given the completions+maps+medals schema, when one query runs, then it yields per-(user,map) best completion with difficulty, time, time-percentile-vs-field, medal, leaderboard rank, WR, and suspicious flag — excluding legacy/unverified/archived/suspicious"
verdict: VALIDATED
related: [002, 003]
tags: [data, sql, asyncpg]
---

# Spike 001: Skill Input Query

## What This Validates

Given `core.completions` + `core.maps` + `maps.medals` + `users.suspicious_flags`, when a single
AsyncPG query runs against the real local DB, then it returns one row per (user, map) — the player's
fastest verified non-legacy completion — carrying every signal a skill score could use, with
ineligible completions excluded.

## Research

No external libraries — pure SQL against the existing schema. Grounded in the real DB (local Docker,
imported from VPS): 17,508 verified non-legacy completions / 1,341 maps / 272 players. Validated the
authoritative ranking logic by reading `apps/api/repository/completions_repository.py:60-189`
(the `latest_per_user_all → split → rankable` CTE chain) rather than trusting a summary.

### Critical schema finding — the `completion` flag is inverted from intuition

`core.completions.completion` (COMMENT, `migrations/0001_init.sql:482`) means *"whether the
submission counts as a completion (submissions while in playtest are completions, as well as
submissions that lack a video)."* Confirmed by the user:

| Flag | Meaning | Count (verified, non-legacy) |
|------|---------|------------------------------|
| `completion = TRUE`  | **partially verified** — screenshot-only / playtest, no video | 17,272 (272 players, 913 maps) |
| `completion = FALSE` | **fully verified** — has video proof, ranked, medal-eligible | 236 (42 players, 121 maps) |

The repo's leaderboard/medal logic ranks `completion = FALSE` only — so **leaderboard rank and
medals exist on a tiny slice of the data**. This killed the user's original design assumption that
"leaderboard_multiplier" could anchor the score. See `## Results`.

### Signal density (the finding that drives the whole formula)

| Signal | Source | Coverage | Verdict for scoring |
|--------|--------|----------|---------------------|
| Difficulty (`raw_difficulty` 0–10) | `core.maps` | 100% | **backbone** |
| Time-percentile vs field | `percent_rank()` per map | 99.6% (field ≥ 3) | **backbone** |
| Fully-verified (video) | `completion = FALSE` | 219 rows / 41 players | proof gate for multipliers |
| Medal (absolute thresholds) | `maps.medals`, 90/1341 maps | 416 rows | sparse bonus |
| Leaderboard / WR rank | rank over video runs | 109 WR rows | sparse bonus |
| Suspicious flag | `users.suspicious_flags` | 2 flags total | cheap exclusion |

## How to Run

```bash
uv run --env-file .env.local --with asyncpg python .planning/spikes/001-skill-input-query/query.py
```

Reads DB creds from `.env.local` (project convention). Writes `skill_inputs.json` next to the
script — the dataset spikes 002 and 003 consume (one DB read, reused downstream).

## What to Expect

```
rows (best per user/map) ........ 14788  (0 suspicious dropped)
distinct players ................ 261
distinct maps ................... 786
fully-verified (video) rows ..... 219  (41 players)
time-pct computable (field>=3) .. 14725  (99.6%)
medal-earning rows .............. 416
world-record rows (video_rank=1)  109
```

Each row: `user_id, name, map_id, code, map_name, difficulty, raw_difficulty, time, completion,
fully_verified, field_size, field_rank, video_rank, time_pct, medal, has_medal_thresholds,
suspicious`.

## Investigation Trail

1. **Started** assuming the exploration summary's claim that `completion=FALSE` = "rankable record"
   and `completion=TRUE` = "practice." A quick count broke that immediately: only 236 rows are
   `completion=FALSE` — far too few to be the leaderboard.
2. **Read the migration COMMENT and the repo SQL directly.** The flag means *verification depth*,
   not practice-vs-real. `completion=TRUE` is a partial (no-video) completion. Confirmed by the user.
3. **Pivoted the signal model.** Counted coverage of each candidate signal. Leaderboard rank (236)
   and medals (90 maps) are far too sparse to anchor a score. Time-percentile-vs-field is dense
   (99.6%) — re-centered the design on `difficulty × time_pct` with sparse bonus layers.
4. **`FILTER` on a window function** (`rank() OVER (...) FILTER (...)`) threw a syntax error —
   Postgres only allows `FILTER` on aggregates. Fixed by ranking the video-only set in its own CTE
   and left-joining it back (`video_ranked`).
5. **Applied real-world exclusions** the summary missed: `m.archived = FALSE` and `m.code IS NOT
   NULL`. These trimmed 16,599 → 14,788 best-rows (261 players / 786 maps) — the legitimately
   scoreable universe.

## Results

**VALIDATED.** A single query produces a complete, clean skill-input dataset over real data. Key
discoveries that reshaped the build:

- **The `completion` flag is verification depth, not practice-vs-real.** Decided (with user) on a
  **hybrid model**: partial clears earn a difficulty *floor*; time-quality/medal/WR multipliers
  require *full (video) verification*. This is the anti-cheat backbone.
- **Leaderboard rank cannot be the skill backbone** (236 ranked runs). Time-percentile-vs-field is
  the dense substitute (99.6%). This is the single most important finding for Spike 002.
- **Surprise — noisy times in the data:** some rows show times like `6094.92` and `28.54` within the
  same difficulty tier (units differ per map / long maps). The scorer must use *relative* time
  (percentile vs field), never absolute time across maps. Spike 001 already does this; flagged so
  002 doesn't regress to comparing raw seconds.
- **Small fields make percentile noisy** (field=5 → percentiles snap to 0/.25/.5/.75/1). 002 must
  shrink the time multiplier toward neutral for small fields rather than trust a 1-of-3 "win."
