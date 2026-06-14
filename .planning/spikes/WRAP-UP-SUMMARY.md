# Spike Wrap-Up Summary

**Date:** 2026-06-12
**Spikes processed:** 3
**Feature areas:** Skill input query (data layer), Scoring algorithm, Leaderboard UI
**Skill output:** `./.claude/skills/spike-findings-genjishimada/`

## Processed Spikes

| # | Name | Type | Verdict | Feature Area |
|---|------|------|---------|--------------|
| 001 | skill-input-query | standard | VALIDATED | Skill input query (data layer) |
| 002 | scoring-farming-resistance | standard | VALIDATED | Scoring algorithm |
| 003 | leaderboard-feel | standard | VALIDATED | Leaderboard UI |

## Key Findings

- **Skill is separate from XP** and computed from verified, non-legacy, non-archived completions only.
  One AsyncPG query produces one best row per `(user, map)` carrying every candidate signal.
- **The `completion` flag means verification depth, not practice-vs-real.** `TRUE` = partial
  (screenshot-only), `FALSE` = fully-verified (video). This reshaped the whole design into a hybrid
  model and is the load-bearing schema fact — confirmed against the migration COMMENT, the repo SQL,
  and the user.
- **Signal density drives the formula.** Difficulty (100%) and time-percentile-vs-field (99.6%) are
  the dense backbone; leaderboard rank (236 runs) and medals (90 maps) are sparse bonus layers only.
  Never compare raw `time` across maps — units differ; use percentile vs the map's field.
- **Hybrid scorer survives the kill-risk.** Floor (any verified clear) + video-gated proof multipliers,
  aggregated with diminishing returns `Σ s_i / i**gamma`. Farming resistance holds at every credible
  weight; `gamma` is the anti-farm dial (gamma=0 is farmable — don't ship; default 0.68).
- **The proof layer is bimodal, not inert** — 0% median uplift (most players have no video) but up to
  +238.6% for the ~41 who video their runs, reshuffling the elite tier. That is the hybrid model
  working as intended.
- **Felt validation by a domain expert** produced the adopted default weights
  (`diff_base=1.44 gamma=0.68 time_bonus=0.55 shrink_k=10.0 wr_bonus=0.10 partial_factor=0.60`). The
  real `SkillService` keeps them config-tunable.
- **Stack proven for spiking:** stdlib + `asyncpg` only, one DB read cached to JSON and reused, scorer
  as a single shared module, standalone dependency-free bundle for tester handoff. See CONVENTIONS.md.

## Next

The validated knowledge is packaged into `spike-findings-genjishimada`, which auto-loads during the
real build. Recommended next step: `/gsd:plan-phase` for the `SkillService` + `/api/v3/skill/*`
implementation, or `/gsd:spike` (frontier mode) to find remaining unknowns (e.g. snapshot table
schema, recompute cadence, Discord surface).
