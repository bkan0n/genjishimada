---
phase: quick-260612-oqg
plan: 01
subsystem: api
tags: [skill-score, leaderboard, asyncpg, litestar, lifespan, cold-start]

requires:
  - phase: 13-skill-score
    provides: "skill.snapshot cache, SkillRepository, SkillService.recompute_all, skill_nightly_rebuild_poller, community leaderboard skill_score column"
provides:
  - "SkillRepository.snapshot_is_empty() — NOT EXISTS emptiness probe"
  - "One-time cold-start population in skill_nightly_rebuild_poller (recompute_all once on boot when snapshot empty)"
affects: [skill-score, leaderboard, deploy]

tech-stack:
  added: []
  patterns:
    - "Initial-population-before-loop in a Litestar lifespan poller, gated on an emptiness probe, reusing the existing recompute path (no forked rebuild logic)"

key-files:
  created: []
  modified:
    - apps/api/repository/skill_repository.py
    - apps/api/app.py
    - apps/api/tests/integration/test_skill.py

key-decisions:
  - "Reuse the existing provide_skill_repository/provide_skill_service/recompute_all path (D-04, no forked rebuild logic)"
  - "Guard the initial population on snapshot_is_empty() so a normal restart with a populated snapshot skips the redundant full rebuild"
  - "Keep the existing 5s warmup-sleep-before-run to dodge the cold-start db_pool race; it is also the cancellation point shutdown relies on"
  - "NOT EXISTS probe over COUNT(*)=0 so the query short-circuits on the first row"

patterns-established:
  - "Cold-start population: run the one-time rebuild ONCE on boot inside the same lifespan task that owns the nightly backstop, guarded by an emptiness check, with the same broad-except + log.exception shape"

requirements-completed: [QUICK-260612-oqg]

duration: ~18min
completed: 2026-06-12
---

# Phase quick-260612-oqg: Fix skill-score leaderboard cold-start Summary

**On a fresh deploy the API now auto-populates `skill.snapshot` once on boot (when empty) via the existing nightly poller, so the leaderboard ranks by real non-zero skill scores within seconds instead of returning `coalesce(skill_score,0)=0` until the next verification event, config PATCH, or the 04:00 UTC rebuild.**

## Performance

- **Duration:** ~18 min
- **Tasks:** 2 completed
- **Files modified:** 3

## Accomplishments

- **Task 1 (TDD):** Added `SkillRepository.snapshot_is_empty(*, conn=None) -> bool` — a cheap `SELECT NOT EXISTS (SELECT 1 FROM skill.snapshot)` probe placed alongside `fetch_snapshot`, following the surrounding `_get_connection(conn)` / keyword-only-`conn` / Google-docstring conventions. Drove it RED→GREEN with a focused integration test (`TestSnapshotIsEmpty`) that truncates the snapshot, asserts empty is `True`, seeds an eligible completion + runs the shared `recompute_all` helper, then asserts empty is `False`. Reused the existing `seed` fixture and `_recompute` helper; no new fixtures.
- **Task 2:** Added a one-time initial-population block to `skill_nightly_rebuild_poller._loop` in `app.py`, BEFORE the unchanged `while True:` nightly loop. After a 5s db_pool-warmup sleep it builds the service via the SAME `provide_skill_repository`/`provide_skill_service` DI the nightly run uses and, only when `snapshot_is_empty()` is `True`, runs `recompute_all()` once. Same `except asyncio.CancelledError: raise` + broad `except Exception: log.exception(...)` shape as the nightly body. Updated the function docstring. Did not touch the lifespan registration, task create/cancel/await teardown, the nightly schedule math, the scoring math, the `/skill/*` endpoints, the leaderboard query, or the event listener.

## Key Implementation Details

- `snapshot_is_empty` returns the bool directly from `fetchval` (asyncpg returns a Python `bool` for the SQL boolean).
- The initial population reuses the exact existing recompute path (D-04); the plan-13-04 in-flight collapse guard makes overlap with any concurrent event-driven recompute safe.
- A failed initial population is logged via `log.exception("[!] skill initial population failed")` and never crashes the lifespan loop; `CancelledError` is re-raised so shutdown stays clean.

## Verification Results

Both automated verification steps were run in the worktree and observed to pass.

**1. `just lint-api`** — PASS (run after each task and again at the end):
```
uv run ruff format apps/api
96 files left unchanged
uv run ruff check apps/api
All checks passed!
uv run basedpyright apps/api/repository apps/api/services apps/api/routes apps/api/middleware apps/api/utilities
0 errors, 0 warnings, 0 notes
```

**2. Skill integration suite** (`uv run pytest apps/api/tests/integration/test_skill.py -o addopts="" -p no:cacheprovider -q`) — PASS:
```
............                                                             [100%]
12 passed in 6.05s
```
(11 pre-existing tests + the new `TestSnapshotIsEmpty::test_empty_before_recompute_false_after_population`.) The DB-backed integration tests ran against a real Postgres provisioned by `pytest-databases` (Docker daemon was available); `.env.local` was not present in the worktree and was not needed — `pytest-databases` spins up its own ephemeral container.

**TDD gate trace:** the new test was confirmed RED first (`AttributeError: 'SkillRepository' object has no attribute 'snapshot_is_empty'`) before the repository method was added, then GREEN after.

**3-5. Manual runtime checks (cold-start boot, leaderboard HTTP ordering, restart-skip)** — NOT run as live HTTP/boot checks in the worktree (no seeded local DB + running API). They are covered structurally:
- Step 3 (cold boot populates snapshot): exercised by the new integration test (empty → populated via the same `recompute_all` path) plus `import app` succeeding (the poller wiring is valid).
- Step 5 (restart with populated snapshot skips rebuild): enforced by the `if await skill_repo.snapshot_is_empty():` guard, directly tested by `snapshot_is_empty()` returning `False` after population.
- Step 4 (leaderboard `sort_column=skill_score&sort_direction=desc` descending, `skill_rank` unchanged): covered by the pre-existing `TestLeaderboardSkillScore` tests, all passing; this plan did not touch the leaderboard query.

## Deviations from Plan

None — plan executed as written. One harmless note on the plan's verify command:

- The plan's Task 1 `<verify>` used `-k snapshot_is_empty`, but the new test lives in class `TestSnapshotIsEmpty` / method `test_empty_before_recompute_false_after_population`, neither of which contains the substring `snapshot_is_empty`. That `-k` filter deselects all tests (0 run). The test was instead run with `-k SnapshotIsEmpty` (and via the full-file run), and passed. No code change was needed for this; it is purely a keyword-filter mismatch in the plan command.

## Environment Notes

- Ran `uv sync --all-groups --all-packages` once at the start so the API dev/test dependency group (`pytest-databases[postgres]`, `pytest-asyncio`, `pytest-xdist`, etc.) was installed in the worktree venv. This regenerated `uv.lock` with some dev-tooling churn (toml/typer/etc.); `uv.lock` was intentionally NOT staged or committed — it is incidental tooling churn unrelated to the task.

## Commits

- `1837f82` feat(260612-oqg): add SkillRepository.snapshot_is_empty cold-start guard
- `95d0efa` feat(260612-oqg): populate skill snapshot on cold start in poller

## Self-Check: PASSED

- Files exist: `apps/api/repository/skill_repository.py`, `apps/api/app.py`, `apps/api/tests/integration/test_skill.py`, `260612-oqg-SUMMARY.md`.
- Commits exist: `1837f82`, `95d0efa`.
- `snapshot_is_empty` present in repository; initial-population block present in `app.py`.
