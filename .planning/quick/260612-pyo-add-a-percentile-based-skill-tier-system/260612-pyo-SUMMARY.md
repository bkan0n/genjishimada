---
phase: quick-260612-pyo
plan: 01
subsystem: skill
tags: [skill, tiers, percentile, leaderboard, migration]
requires:
  - skill.snapshot (migration 0027)
  - skill.weight_config (migration 0027)
  - SkillService.recompute_all / _do_recompute (Phase 13)
provides:
  - skill.tier_config (boundaries, percentiles, computed_at)
  - SkillRepository.compute_tier_boundaries / fetch_tier_config / fetch_snapshot_with_tier
  - SkillService.get_tier_config + tier/percentile on get_user_skill
  - GET /api/v3/skill/tiers
  - tier + percentile columns on the community leaderboard
affects:
  - GET /api/v3/skill/users/{id}
  - GET /api/v3/community/leaderboard
tech-stack:
  added: []
  patterns: [percentile_cont, width_bucket, single-row config table, percentile floor guard]
key-files:
  created:
    - apps/api/migrations/0028_skill_tier_config.sql
  modified:
    - libs/sdk/src/genjishimada_sdk/skill.py
    - libs/sdk/src/genjishimada_sdk/users.py
    - apps/api/repository/skill_repository.py
    - apps/api/services/skill_service.py
    - apps/api/routes/v3/skill.py
    - apps/api/repository/community_repository.py
    - apps/api/tests/integration/test_skill.py
    - apps/api/tests/services/test_skill_service.py
decisions:
  - "Flicker: recompute tier boundaries on EVERY snapshot rebuild (inside _do_recompute), reusing the single D-04 path."
  - "Population floor 20: below 20 non-zero players -> empty boundaries -> everyone Unranked."
  - "Tier tests seed skill.snapshot directly + call the real compute_tier_boundaries (recompute_all rebuilds from the shared core.completions, so it cannot isolate the non-zero population)."
metrics:
  duration: ~30m
  completed: 2026-06-12
  tasks: 3
  files: 9
requirements: [PYO-TIER-01, PYO-TIER-02, PYO-TIER-03, PYO-TIER-04, PYO-TIER-05, PYO-TIER-06]
---

# Quick Task 260612-pyo: Percentile-based Skill Tier System Summary

Percentile-derived skill TIER icons (1..7, 0 = Unranked) layered on top of the existing
numeric `skill_score` without touching the scorer math, weights, or the Ninja..God
`skill_rank` label. Boundaries are 6 `percentile_cont` cut-points over `skill_score > 0`
snapshot rows (the seeded percentile array is the only tunable — no hardcoded score
cutoffs); a player's tier is `width_bucket` over those cached boundaries.

## What was built

- **Task 1 (`056bb38`)** — Migration `0028_skill_tier_config.sql`: single-row
  `skill.tier_config` (`boundaries float8[]` default empty, `percentiles float8[]` seeded
  `ARRAY[0.50, 0.75, 0.90, 0.97, 0.99, 0.995]`, `computed_at`), idempotent seed. SDK:
  `tier`/`percentile` on `SkillSummaryResponse`, new `SkillTiersResponse`, and
  `tier`/`percentile` on `CommunityLeaderboardResponse`.
- **Task 2 (`d0e1d73`)** — `SkillRepository`: `_TIER_POPULATION_FLOOR = 20`,
  `compute_tier_boundaries` (percentile_cont over non-zero rows; empty boundaries below the
  floor; always refreshes `computed_at`), `fetch_tier_config`, `fetch_snapshot_with_tier`
  (`width_bucket(skill_score, boundaries) + 1`, Unranked when score <= 0 or boundaries
  empty, plus population percentile). `_do_recompute` calls `compute_tier_boundaries` after
  `replace_snapshot` (single D-04 path, no fork). `get_user_skill` returns tier/percentile;
  `get_tier_config` added. `GET /skill/tiers` wired (public, no new scope).
- **Task 3 (`c09f0ea`)** — Leaderboard query: `LEFT JOIN skill.tier_config tc ON TRUE` +
  `tier`/`percentile` columns adjacent to `skill_score` (`skill_rank` CASE, `sort_column`
  Literal, and ORDER BY untouched). New `TestSkillTiers` integration tests + an updated
  service unit test.

## Flicker decision (and churn tradeoff)

**Decision taken: boundaries recompute on EVERY snapshot rebuild.** The boundary
computation runs inside `_do_recompute`, immediately after `replace_snapshot`, so it rides
the single D-04 `recompute_all` routine (verify / reject / suspicious-flag events + the
nightly backstop + PATCH config) without forking the rebuild path. This guarantees
`skill.tier_config` is always consistent with the snapshot that produced it.

**Churn tradeoff:** because the cut-points move whenever the field around a player moves, a
player's displayed tier can shift even when their own `skill_score` is unchanged (e.g. the
field's scores drift up and a P90 boundary rises past them). This is acceptable for a
display-only badge. If rank churn ever becomes a concern, the boundary update can be gated
to the nightly slot only — scores stay fresh on every event, cut-points move once a day —
**without a schema change** (the `percentiles`/`boundaries`/`computed_at` shape already
supports a less-frequent update cadence).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking env] Worktree missing `.env.local` and unsynced dev test group**
- **Found during:** Task 1 verify (`No environment file found at .env.local`) and Task 3
  gate (`ModuleNotFoundError: No module named 'pytest_databases'`).
- **Fix:** Symlinked the main repo's `.env.local` into the worktree (gitignored, not
  committed) and ran `uv sync --all-groups --all-packages` to install the `dev-api` test
  deps (pytest-databases etc.), matching `just setup`. Restored `uv.lock` after each `uv`
  invocation (the older worktree base re-resolved it to lock revision 2; not part of this
  task).
- **Files modified:** none committed (environment-only).

**2. [Rule 1 - Bug] Pre-existing service unit test broke after the read refactor**
- **Found during:** Task 3 gate. `test_get_user_skill_empty_player_returns_zero` mocked
  `repo.fetch_snapshot`, but `get_user_skill` now reads via `fetch_snapshot_with_tier`
  (tier/percentile join). With an `AsyncMock` repo the old mock no longer returned `None`,
  so the empty-player branch was skipped and `msgspec.convert` got AsyncMock fields.
- **Fix:** Updated the test to mock `fetch_snapshot_with_tier` and assert the new
  `tier=0, percentile=0.0` fields. (Test file — excluded from lint.)
- **Commit:** `c09f0ea`.

**3. [Rule 1 - Bug] Tier tests could not isolate the non-zero population via `recompute_all`**
- **Found during:** Task 3 first test run. `recompute_all` rebuilds the WHOLE snapshot from
  every row in the shared `core.completions`, so TRUNCATE + a few seeded completions did not
  produce a sub-floor population (it repopulated from all sibling-test completions), and the
  full population had score ties that broke strict boundary monotonicity.
- **Fix:** The tier tests now seed `skill.snapshot` DIRECTLY (a clean, distinct,
  strictly-increasing score spread) and invoke the REAL `SkillRepository.compute_tier_boundaries`
  — the same routine `_do_recompute` calls — then exercise the real `/skill/tiers`,
  `/skill/users/{id}`, and `/community/leaderboard` read endpoints over the result. This
  gives a deterministic, isolated population while still testing the production boundary SQL
  and read paths. A `zip(..., strict=True)` idiom bug in the monotonicity assert was also
  fixed (`boundaries[:-1]` vs `boundaries[1:]`).
- **Files modified:** `apps/api/tests/integration/test_skill.py`.
- **Commit:** `c09f0ea`.

## Hard Gates

### Gate 1 — `just lint-api` (ruff + basedpyright strict)

```
uv run ruff format apps/api
96 files left unchanged
uv run ruff check apps/api
All checks passed!
uv run basedpyright apps/api/repository apps/api/services apps/api/routes apps/api/middleware apps/api/utilities
0 errors, 0 warnings, 0 notes
```

### Gate 2 — skill tests with testmon disabled

```
uv run --env-file .env.local pytest apps/api/tests/integration/test_skill.py apps/api/tests/services/test_skill_service.py -o addopts="" -p no:cacheprovider -q
......................                                                   [100%]
22 passed in 9.55s
```

Both gates PASS.

## Verification against constraints

- Single `recompute_all` / `_do_recompute` reused for boundary computation — rebuild path
  NOT forked.
- No hardcoded score cutoffs in service/repository code (`grep` confirmed); the seeded
  `percentiles` array in migration 0028 is the only tunable.
- No new auth scope; `GET /skill/tiers` is a public read like the other skill GETs.
- Scorer math (`_diff_weight`/`_map_score`/`_player_score`/`_player_breakdown`), the
  Ninja..God `skill_rank` CASE, the leaderboard `sort_column` Literal, and
  `skill.weight_config` are all byte-for-byte unchanged (`git diff` confirmed).
- Migration is `0028` (sequential after `0027`).

## Known Stubs

None.

## Self-Check: PASSED

- FOUND: apps/api/migrations/0028_skill_tier_config.sql
- FOUND: commits 056bb38, d0e1d73, c09f0ea
- Both hard gates green (lint-api 0 errors; 22 skill tests passed).
