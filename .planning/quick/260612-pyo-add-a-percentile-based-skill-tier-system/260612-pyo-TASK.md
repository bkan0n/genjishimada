# Quick Task 260612-pyo — Full Specification

Add a percentile-based skill TIER system (icon ranks) on top of the existing numeric skill_score from Phase 13. This is a NEW concept, separate from the existing Ninja->God skill_rank difficulty label — do not touch skill_rank, the scoring math, the weights, or the existing behavior of the four /skill/* endpoints.

**Goal:** every player gets a tier — an integer 1..7, plus 0 = Unranked for players with no eligible completions (skill_score = 0) — assigned by where their skill_score falls in the CURRENT population distribution, so tiers stay correct automatically as scores drift (new maps, field improvements, weight retunes). 7 tiers, pyramid-shaped (most players low, few at top). No fixed or hardcoded absolute score cutoffs — boundaries are derived from the live distribution, mirroring the Phase 13 "no hardcoded weights" rule.

## How to compute

- Boundaries are 6 cut-point scores (tiers - 1) computed over the non-zero snapshot scores using Postgres `percentile_cont(...) WITHIN GROUP (ORDER BY skill_score)`, at configurable percentiles. Default percentiles `ARRAY[0.50, 0.75, 0.90, 0.97, 0.99, 0.995]`. Store the percentile array in config so it can be tuned without code changes.
- Compute and persist the 6 boundary scores as part of the existing single recompute routine (`SkillService.recompute_all` / `_do_recompute`) so boundaries are always consistent with the snapshot that produced them. Reuse the one rebuild path (D-04) — do not fork it.
- Assign a user's tier with Postgres `width_bucket(skill_score, boundaries_array)` -> 0..6 mapped to tier 1..7; skill_score = 0 or no snapshot row -> tier 0 / Unranked.
- Population-floor guard: if fewer than 20 players have skill_score > 0, skip tiering (everyone Unranked / provisional) rather than minting meaningless boundaries from a tiny sample.

## Schema (migration 0028)

A single-row `skill.tier_config` table holding `boundaries float8[]` (the 6 computed cut-points), `percentiles float8[]` seeded with the default percentile array, and `computed_at timestamptz`, updated by recompute_all. Must apply cleanly on a fresh test DB and seed the percentiles row.

## API surface

- Add a `tier` field (int 1..7, 0 = Unranked) and the player's `percentile` (0..1) to `SkillSummaryResponse` (GET /api/v3/skill/users/{id}) and to `CommunityLeaderboardResponse` + its leaderboard query, computed via `width_bucket` over the cached boundaries. The frontend maps the integer tier to an icon, so the backend returns the integer (and percentile), not icon assets.
- Add `GET /api/v3/skill/tiers` returning the current boundaries + percentiles + computed_at so the website can render a tier legend. No new auth scope; public read like the other skill GETs.
- Do NOT add tier to the leaderboard `sort_column` Literal — sorting by skill_score already orders tiers; tier is display-only.

## Flicker decision

Boundaries recompute on every snapshot rebuild by default, which keeps them fresh but means a user's tier can shift when the field around them moves even if their own score is unchanged. If rank churn is a concern, gate the boundary update to the nightly rebuild only (scores stay fresh on every event; cutoffs move once a day). Choose one, implement it, and note it in the summary.

## Acceptance criteria

- Migration 0028 applies cleanly on a fresh test DB and seeds the percentiles config.
- After a recompute on a populated snapshot, `skill.tier_config` holds 6 strictly increasing boundary scores computed from skill_score > 0 rows.
- GET /api/v3/skill/users/{id} returns tier (1..7) and percentile for a scored player, and tier 0 / Unranked with an empty breakdown for a player with no eligible completions.
- Each community leaderboard row carries a tier consistent with its skill_score and the current boundaries; skill_rank (Ninja->God) and skill_score are unchanged.
- GET /api/v3/skill/tiers returns the current boundaries + percentiles + computed_at.
- No hardcoded score cutoffs in service/repository code (boundaries are data); the percentile array is the only tunable and lives in config.
- Population-floor guard verified (tiny sample -> everyone Unranked, no crash).
- `just lint-api` passes (ruff + basedpyright strict, 0 errors); skill tests pass with testmon disabled:
  `uv run --env-file .env.local pytest apps/api/tests/integration/test_skill.py apps/api/tests/services/test_skill_service.py -o addopts="" -p no:cacheprovider -q`
  including a new test asserting tier assignment, the Unranked/0 case, boundary monotonicity, and the population-floor fallback.

## Constraints

Litestar + AsyncPG + msgspec, raw SQL (no ORM), three-layer Controller->Service->Repository, sequential migration (latest is 0027 -> this is 0028), reuse the single recompute_all routine, no new auth scope, and leave the existing Ninja->God skill_rank label and the scoring algorithm/weights untouched. Verify against genjishimada-db-local (database genjishimada, schema skill); note the snapshot may need a recompute (PATCH /api/v3/skill/config, or the cold-start auto-population fix) before the tier boundaries are non-trivial.

## Skill Routing note

A project skill `spike-findings-genjishimada` (and `Skill("spike-findings-genjishimada")`) documents skill-score implementation patterns, scoring formula, input query, constraints, gotchas. Consult it for context on the existing skill-score feature.
