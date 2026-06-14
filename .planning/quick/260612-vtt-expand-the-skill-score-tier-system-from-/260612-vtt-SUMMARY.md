---
phase: quick-260612-vtt
plan: 01
subsystem: skill-score
tags: [skill, tiers, leaderboard, sdk, migration]
requires:
  - skill-score feature (feat/skill-score branch: migration 0028, SkillService, percentile tier derivation, PATCH /skill/tiers)
provides:
  - 7-percentile tier seed minting integer tiers 1-8 (tier 0 = Unranked)
  - SKILL_TIER_NAMES single-source int->name map (0=Unranked..8=Champion) + skill_tier_name helper
  - skill_tier_name on SkillSummaryResponse and CommunityLeaderboardResponse
  - renamed leaderboard columns skill_tier / skill_percentile (was tier / percentile)
affects:
  - GET /skill/users/{id} response shape (adds skill_tier_name)
  - GET /community/leaderboard row shape (renames tier/percentile, adds skill_tier_name)
  - PATCH /skill/tiers validation (now exactly 7 percentiles)
tech-stack:
  added: []
  patterns:
    - "Single source-of-truth int->name map in the SDK, imported by both the leaderboard service and the skill summary path"
key-files:
  created: []
  modified:
    - apps/api/migrations/0028_skill_tier_config.sql
    - libs/sdk/src/genjishimada_sdk/skill.py
    - libs/sdk/src/genjishimada_sdk/users.py
    - apps/api/services/skill_service.py
    - apps/api/services/exceptions/skill.py
    - apps/api/repository/community_repository.py
    - apps/api/services/community_service.py
    - apps/api/tests/services/test_skill_service.py
    - apps/api/tests/integration/test_skill.py
decisions:
  - "Inserted the new cut-point in the lower half of the percentile array (0.50, 0.70, 0.85, 0.93, 0.97, 0.99, 0.995) rather than appending, keeping the existing high-end tail (0.97/0.99/0.995) intact so the top tiers stay rare."
  - "skill_tier_name is injected into the row dict before msgspec.convert on both the summary and leaderboard paths, so the SDK map is the only place names are defined."
metrics:
  duration_min: 7
  completed: 2026-06-12
  tasks: 3
  files: 9
---

# Phase quick-260612-vtt Plan 01: Skill-Score Tier Expansion (7 -> 8 Named Tiers) Summary

Expanded the percentile-based skill-tier system from 7 to 8 named tiers plus Unranked by seeding 7 percentiles (was 6) so `width_bucket` mints integer tiers 1-8, adding a single source-of-truth `SKILL_TIER_NAMES` map (0=Unranked..8=Champion) reused by both the community leaderboard rows and the per-user skill summary, and renaming the leaderboard `tier`/`percentile` columns to `skill_tier`/`skill_percentile` — all without touching the scorer or the percentile-based boundary derivation.

## What Was Built

**Task 1 — Seed 7 percentiles, name map, validation bump (`c4e8c7c`)**
- Migration 0028 edited in place: seed array `ARRAY[0.50, 0.70, 0.85, 0.93, 0.97, 0.99, 0.995]` (7 strictly-increasing values); narrative comments updated to "7 boundaries / tiers 1..8, 0 = Unranked". Boundaries default stays empty `'{}'`.
- SDK `skill.py`: added `SKILL_TIER_NAMES: dict[int, str]` (single source of truth) and the `skill_tier_name(tier) -> str` helper (falls back to "Unranked" out of range); both exported in `__all__`. Added `skill_tier_name: str` to `SkillSummaryResponse`. Docstrings bumped 6 -> 7 / 1..7 -> 1..8.
- `skill_service.py`: `_TIER_PERCENTILE_COUNT` 6 -> 7; `get_user_skill` populates `skill_tier_name` on BOTH return paths (no-row -> "Unranked"; row -> `skill_tier_name(int(row["tier"]))` injected before convert).
- `exceptions/skill.py`: `InvalidPercentilesError` docstring 6 -> 7.

**Task 2 — Rename leaderboard columns + expose name (`043a271`)**
- `community_repository.py`: SELECT aliases `... AS tier` -> `AS skill_tier`, `... AS percentile` -> `AS skill_percentile` (the `width_bucket` expression and `skill_score` alias unchanged); method docstring updated to the renamed columns / 1..8.
- SDK `users.py` `CommunityLeaderboardResponse`: `tier` -> `skill_tier`, `percentile` -> `skill_percentile`, added `skill_tier_name: str`; Attributes docstring updated.
- `community_service.py`: imports `skill_tier_name`, maps `row["skill_tier_name"] = skill_tier_name(int(row["skill_tier"]))` onto every row before `msgspec.convert`. No sort/filter/allow-list changes (`skill_score` remains a valid sort column).

**Task 3 — Tests (`ce153f8`)**
- `test_skill_service.py`: reject tests use 6- and 8-element (wrong length) and 7-element (range / non-increasing) arrays; round-trip uses a 7-element array; no-row summary asserts `skill_tier_name="Unranked"`; new `test_skill_tier_name_map` asserts 0->Unranked, 8->Champion, out-of-range->Unranked, len 9.
- `test_skill.py`: legend asserts 7 percentiles + 7 boundaries; per-user tier 1..8; per-user and every leaderboard row assert `skill_tier_name` equals `SKILL_TIER_NAMES[skill_tier]`; reads renamed `skill_tier`/`skill_percentile`; explicit Unranked-at-0 assertions; `_VALID`/`_SEEDED_DEFAULT` are 7-element arrays with `_SEEDED_DEFAULT` matching the new migration seed.

## Verification Results

- `just lint-sdk`: clean (ruff format, ruff check, basedpyright 0/0/0).
- `just lint-api`: clean (ruff format, ruff check, basedpyright 0/0/0).
- `just test-api` (full suite, `-n 4`): **1272 passed, 2 xfailed, 0 failures** in ~111s.
- Targeted: `tests/services/test_skill_service.py` 12 passed; `tests/integration/test_skill.py` 19 passed.
- Single-source-of-truth invariant: exactly one `SKILL_TIER_NAMES` map literal (in the SDK); no inline int->name duplicates in app/lib code.
- Scorer (`_map_score`/`_player_score`/`_player_breakdown`) and the `compute_tier_boundaries` / `width_bucket` derivation are unchanged except for the two documented alias renames.

## Deviations from Plan

**Worktree base correction (setup, not a code deviation):** The orchestrator instructed a reset to base `5518c5e` (a `main`-rooted commit carrying only the vtt PLAN.md). That commit is a *sibling* of `feat/skill-score` (tip `c51a224`) and does NOT contain any of the prerequisite skill-score files the plan edits (migration 0028, `skill.py`, `skill_service.py`, `community_*`, the skill tests). After the mandated reset to `5518c5e`, the worktree was re-based onto `feat/skill-score` (`c51a224`) — which holds all prerequisite code — and the vtt PLAN.md was restored via `git checkout 5518c5e -- <plan>`. This was required for the plan's "edit in place" / "scorer untouched" instructions to be executable at all; the alternative (recreating the entire skill-score feature on the `main`-rooted base) was out of scope and contradicted by the plan. No application code was added beyond the three planned tasks.

No Rule 1-4 code deviations: the plan executed exactly as written.

## Known Stubs

None. All new fields are wired to real data (`skill_tier_name` is computed from the integer tier via the SDK map on every code path).

## Self-Check: PASSED

All 9 modified files exist on disk. All three task commits are present:
- `c4e8c7c` feat(quick-260612-vtt): seed 7 percentiles, add tier-name map, bump validation to 7
- `043a271` feat(quick-260612-vtt): rename leaderboard tier/percentile to skill_tier/skill_percentile, add skill_tier_name
- `ce153f8` test(quick-260612-vtt): cover 8 tiers, Unranked-at-0, renamed columns, tier-name map
