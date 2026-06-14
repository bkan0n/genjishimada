---
phase: quick-260613-rh2
plan: 01
subsystem: rank-card
tags: [rank-card, skill-score, leaderboard-parity, msgspec, asyncpg]
requires:
  - skill.snapshot / skill.tier_config (migrations 0027/0028)
  - genjishimada_sdk.skill.skill_tier_name (single source of truth)
  - CommunityLeaderboardResponse skill projection (the contract mirrored)
provides:
  - RankCardResponse.skill_score / skill_tier / skill_percentile / skill_tier_name
  - RankCardRepository.fetch_skill_summary (single-user skill projection)
affects:
  - GET /api/v3/users/{user_id}/rank-card/
tech-stack:
  added: []
  patterns:
    - Mirror leaderboard SQL byte-for-byte for a single user (anchored on core.users)
    - Map integer tier -> name via SDK skill_tier_name (no duplicated name map)
key-files:
  created: []
  modified:
    - libs/sdk/src/genjishimada_sdk/rank_card.py
    - apps/api/repository/rank_card_repository.py
    - apps/api/services/rank_card_service.py
    - apps/api/tests/integration/test_rank_card_integration.py
decisions:
  - Anchor the single-user skill query on core.users so a snapshot-less user gets 0/0/0.0 (never None), mirroring the leaderboard's COALESCE/CASE.
  - Four new RankCardResponse fields are non-defaulted (placed before the computed URL fields) because the service always supplies them and the SQL COALESCEs guarantee non-null — matching the leaderboard contract.
metrics:
  duration: ~2m
  completed: 2026-06-14
  tasks: 3
  files: 4
---

# Phase quick-260613-rh2 Plan 01: Add skill-score column to get-rank-card-data Summary

Mirror the community leaderboard's four skill fields (`skill_score`, `skill_tier`, `skill_percentile`, `skill_tier_name`) onto the single-user rank-card endpoint, sourced from the same `skill.snapshot` + `skill.tier_config` join and name-mapped through the SDK single source of truth.

## What Was Built

`GET /api/v3/users/{user_id}/rank-card/` now returns the same four skill fields the community leaderboard exposes per row, so the frontend can reuse its leaderboard rendering for the rank card:

- **SDK (`rank_card.py`):** `RankCardResponse` gains `skill_score: float`, `skill_tier: int`, `skill_percentile: float`, `skill_tier_name: str` — non-defaulted, placed before the computed `*_url` fields (msgspec ordering), names/types mirroring `CommunityLeaderboardResponse` exactly. `__post_init__` untouched (no URL derived from skill).
- **Repository (`rank_card_repository.py`):** new `fetch_skill_summary(user_id, *, conn=None)` ports the leaderboard's skill projection into a single-user query anchored on `core.users` with `LEFT JOIN skill.snapshot` + `LEFT JOIN skill.tier_config tc ON TRUE`. Returns the same three computed columns (`coalesce(skill_score,0)`; the `width_bucket+1` CASE tier; the correlated-subquery percentile ratio). Pure read, positional `$1` binding. Snapshot-less user → `0.0/0/0.0` (the COALESCE/CASE zero path), with a defensive `None`-row fallback returning the same zeros.
- **Service (`rank_card_service.py`):** imports `skill_tier_name` from `genjishimada_sdk.skill`, calls `fetch_skill_summary` inside the existing `async with self._pool.acquire()` block, maps the integer tier to its name (exactly as `community_service` does), and passes all four fields into `RankCardResponse(...)`.
- **Tests (`test_rank_card_integration.py`):** `test_happy_path` extended to assert the four keys are present and correctly typed; new `test_skill_fields_default_unranked` proves a fresh (snapshot-less) user returns `skill_score==0`, `skill_tier==0`, `skill_percentile==0`, `skill_tier_name=="Unranked"`.

## Tasks

| Task | Name | Commit | Files |
| ---- | ---- | ------ | ----- |
| 1 | Add four skill fields to RankCardResponse SDK struct | 3bf58b1 | libs/sdk/src/genjishimada_sdk/rank_card.py |
| 2 | Single-user skill query in repository + wire through service | d3275a7 | apps/api/repository/rank_card_repository.py, apps/api/services/rank_card_service.py |
| 3 | Integration tests — skill fields present + zero-eligible Unranked | b8dc288 | apps/api/tests/integration/test_rank_card_integration.py |

## Verification

- `just lint-sdk` clean (ruff format + check + basedpyright: 0 errors).
- `just lint-api` clean (ruff format + check + basedpyright: 0 errors).
- Task 1/2 grep gates pass: `skill_tier_name` in SDK struct (×3); `fetch_skill_summary` + `skill.snapshot` in repo; `skill_tier_name` in service.
- `pytest test_rank_card_integration.py -k GetRankCard`: **4 passed** (happy-path with the four typed skill fields + the new zero-eligible Unranked case), 24 deselected.
- Field names/types match `CommunityLeaderboardResponse` exactly (frontend reuse), and the SQL projection is byte-for-byte equivalent to the leaderboard's.

## Deviations from Plan

None - plan executed exactly as written.

(One environment-setup step, not a code deviation: the fresh worktree venv lacked the dev/test deps — `just sync` was run before the Task 3 integration test. No source or plan change resulted.)

## Threat Surface

No new security-relevant surface beyond the plan's `<threat_model>`. `fetch_skill_summary` is a pure read with positional `$1` binding mirroring the already-reviewed leaderboard SQL; skill score/tier/percentile is public leaderboard data already exposed for every user; the two correlated counts run once per single-user request (strictly cheaper than the existing leaderboard usage). No packages installed.

## Self-Check: PASSED

- libs/sdk/src/genjishimada_sdk/rank_card.py — FOUND (modified)
- apps/api/repository/rank_card_repository.py — FOUND (modified)
- apps/api/services/rank_card_service.py — FOUND (modified)
- apps/api/tests/integration/test_rank_card_integration.py — FOUND (modified)
- Commit 3bf58b1 — FOUND
- Commit d3275a7 — FOUND
- Commit b8dc288 — FOUND
