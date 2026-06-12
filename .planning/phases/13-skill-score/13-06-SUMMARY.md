---
phase: 13-skill-score
plan: 06
subsystem: api
tags: [skill-score, in-process-event, recompute, leaderboard, integration-test, symmetric-removal]

# Dependency graph
requires:
  - phase: 13-01
    provides: "skill.snapshot table (user_id PK, skill_score) the leaderboard LEFT JOINs"
  - phase: 13-04
    provides: "SkillService.recompute_all / get_user_skill / get_user_breakdown, provide_skill_service"
  - phase: 13-05
    provides: "SkillRecomputeRequestedEvent struct + handle_skill_recompute listener (skill_service DI arg)"
provides:
  - "skill.recompute.requested emitted from all four D-02 verification state-change paths (verify, un-verify, set_suspicious_flags, remove_suspicious_flags)"
  - "Community leaderboard skill_score column: LEFT JOIN skill.snapshot + COALESCE(0) + skill_score sort option (repo/service/route)"
  - "Integration test proving the symmetric add/remove freshness contract, field relativity, sortable column, empty-player rule, PATCH authz, breakdown-sums-to-total"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Post-commit fire-and-forget in-process emit threaded from the route via a DI-injected service kwarg matching the listener arg name (skill_service)"
    - "Optional-request guard on the emit helper (_emit_skill_recompute) so event-driven service calls without a request skip the emit (nightly backstop self-heals)"
    - "Surgical leaderboard extension: one LEFT JOIN + one COALESCE column + one Literal member duplicated across repository/service/route, skill_rank untouched"
    - "Integration test drives the deterministic snapshot via the shared recompute_all on a dedicated test pool (last-writer) after a settle yield, sidestepping the background-listener pool-teardown race"

key-files:
  created:
    - apps/api/tests/integration/test_skill.py
  modified:
    - apps/api/services/completions_service.py
    - apps/api/routes/v3/completions.py
    - apps/api/repository/community_repository.py
    - apps/api/services/community_service.py
    - apps/api/routes/v3/community.py

key-decisions:
  - "verify_completion handles both verify (data.verified=True) and un-verify/reject (False) in one method, so the two emits live in that method's post-commit tail as distinct branches — together with set/remove suspicious flags this yields the four D-02 paths (5 emit-site string occurrences)."
  - "The suspicious-flag service methods + their route handlers were threaded with request + skill_service (they previously took neither) so the emit can fire; the emit helper guards request is None for event-driven callers."
  - "skill_score sorts as a plain numeric column via the existing else: sort_values = sort_column branch — no CASE was added (only skill_rank needs the ordinal CASE)."
  - "The integration test invokes the SAME recompute_all routine deterministically on its own pool as the authoritative rebuild, after a 0.1s settle yield; the HTTP verify/reject/flag calls still fire the real background emit (proving the wiring), but the test does not depend on the background task's timing or its app-pool lifecycle."

requirements-completed: [6, 8, 9]

# Metrics
duration: ~12min
completed: 2026-06-12
---

# Phase 13 Plan 06: Skill Freshness + Leaderboard Column Summary

**Closed the symmetric add/remove freshness contract by emitting `skill.recompute.requested` from all four D-02 verification state-change paths (verify, un-verify/reject, set_suspicious_flags, remove_suspicious_flags), surfaced the `skill_score` column as a sortable COALESCE(0) LEFT JOIN on the existing community leaderboard (skill_rank untouched), and proved the full SPEC acceptance matrix — verify-raises / reject-restores / flag-to-0 / field-relativity / sortable-paginated column / zero-eligible-last / PATCH authz / breakdown-sums-to-total — with an integration test.**

## Performance

- **Duration:** ~12 min
- **Completed:** 2026-06-12
- **Tasks:** 3
- **Files modified:** 6 (1 created, 5 modified)

## Accomplishments

- **Task 1 — emit from all four D-02 paths (`completions_service.py` + `routes/v3/completions.py`):**
  - Added a `_emit_skill_recompute` static helper (post-commit, fire-and-forget, guarded for `request is None`/`skill_service is None`) emitting `request.app.emit("skill.recompute.requested", SkillRecomputeRequestedEvent(reason=...), skill_service=skill_service)` — copying the `:754` emit shape; the kwarg name `skill_service` matches the listener's DI arg.
  - `verify_completion` emits in both the `data.verified` (verify) and `else` (un-verify/reject) branches after `update_verification` commits — symmetric add/remove (req 8/9). Threaded an optional `skill_service` param through `verify_completion` + `verify_completion_with_pool`.
  - `set_suspicious_flags` (flag → contribution drops → score 0) and `remove_suspicious_flags` (un-flag → contribution restored) were threaded with `request` + `skill_service` (they previously took neither) and emit post-commit.
  - Route: added `provide_skill_service` + `provide_skill_repository` to `CompletionsController.dependencies`; the verify + POST/DELETE suspicious handlers now inject `request: Request` + `skill_service: SkillService` and pass them through. (5 `skill.recompute.requested` string occurrences; verify ≥4.)
- **Task 2 — sortable `skill_score` leaderboard column (`community_repository.py` + `community_service.py` + `routes/v3/community.py`):**
  - `fetch_community_leaderboard`: added `LEFT JOIN skill.snapshot ss ON u.id = ss.user_id` and `coalesce(ss.skill_score, 0) AS skill_score` (D-07 zero-eligible ranked last), and `"skill_score"` to the `sort_column` Literal + docstring. No CASE added — it sorts via the existing plain-column branch.
  - Mirrored `"skill_score"` into the duplicated `sort_column` Literal in the service and route, plus the route handler docstring/description. `skill_rank` label + its CASE ordering left UNTOUCHED (SPEC req 6).
- **Task 3 — integration test (`tests/integration/test_skill.py`, new, 10 tests):** the full SPEC acceptance matrix against the migrated integration DB (see Acceptance Criteria).

## Task Commits

1. **Task 1: emit skill.recompute.requested from all four D-02 verification paths** — `8222496` (feat)
2. **Task 2: add sortable skill_score column to community leaderboard** — `affd0ad` (feat)
3. **Task 3: integration test for freshness + sortable column + authz** — `58df609` (test)

## Files Created/Modified

- `apps/api/services/completions_service.py` (mod) — `_emit_skill_recompute` helper; emits from verify/un-verify + set/remove suspicious flags; threaded `skill_service` through `verify_completion`/`verify_completion_with_pool` and `request`+`skill_service` through the suspicious-flag methods.
- `apps/api/routes/v3/completions.py` (mod) — `provide_skill_service`/`provide_skill_repository` deps; verify + suspicious handlers inject `request` + `skill_service`.
- `apps/api/repository/community_repository.py` (mod) — LEFT JOIN skill.snapshot + COALESCE(0) skill_score column + Literal member.
- `apps/api/services/community_service.py` (mod) — `skill_score` in the duplicated sort_column Literal.
- `apps/api/routes/v3/community.py` (mod) — `skill_score` in the duplicated sort_column Literal + docstring/description.
- `apps/api/tests/integration/test_skill.py` (new) — 10 integration tests covering the SPEC acceptance matrix.

## Verification Performed

- **Task 1 `<automated>`:** `skill.recompute.requested` occurs 5× (≥4) in `completions_service.py`; `provide_skill_service` present in the route; `just lint-api` clean (ruff format/check + basedpyright 0 errors).
- **Task 2 `<automated>`:** `LEFT JOIN skill.snapshot` + `skill_score` present in repository; `skill_score` present in service + route Literals; `skill_rank` still present in repository; `just lint-api` clean.
- **Task 3 `<automated>`:** `pytest apps/api/tests/integration/test_skill.py` → **10 passed** (run with testmon disabled via `-o addopts=""`, the authoritative result); `just lint-api` clean.

## Decisions Made

- **Two emits in `verify_completion`, not a delete-branch emit.** The plan's `read_first` pointed at the `api.completion.verification.delete` branch (lines 723-730), but that branch lives in `submit_completion` (a slower-than-PB verification cleanup), not the verification flow. In this codebase, `verify_completion` itself handles BOTH verify (`data.verified=True`) and un-verify/reject (`False`) — so the symmetric add/remove emits belong in that method's post-commit tail, one per branch. Together with the two suspicious-flag methods this gives the four D-02 paths (req 8/9 symmetry). This is a documentation/locator nuance, not a behavior change.
- **Deterministic test recompute over background-task assertion.** The HTTP verify/reject/flag calls fire the real `request.app.emit` background listener (proving the wiring), but that listener runs on the app's own pool, which `AsyncTestClient` may release between calls — producing a *logged, non-fatal* listener error. Rather than race the background task, the test yields the loop (0.1s) then runs the SAME `recompute_all` routine on its dedicated test pool as the authoritative last writer. This keeps assertions deterministic while still exercising the real endpoints (the plan explicitly permits "calling recompute_all directly — in-process, not RabbitMQ-gated").

## Deviations from Plan

None — plan executed exactly as written. (The "delete-branch" locator nuance under Decisions Made is a documentation clarification, not a deviation: all four D-02 state-change paths emit as required, verified by the ≥4 emit-site check and the symmetric add/remove integration assertions.)

## Acceptance Criteria

- [x] `skill.recompute.requested` emitted from verify (True), un-verify (False), set_suspicious_flags, remove_suspicious_flags; suspicious-flag methods + routes threaded with `request`+`skill_service` (≥4 emit sites — 5 occurrences).
- [x] `provide_skill_service` in `CompletionsController.dependencies`; emit kwarg name is `skill_service` (matches the listener arg); every emit is post-commit and optional-request-guarded.
- [x] Leaderboard `sort_column` Literal includes `"skill_score"` in repository, service, and route; `LEFT JOIN skill.snapshot` + `coalesce(ss.skill_score, 0) AS skill_score`; no CASE added; `skill_rank` + its CASE unchanged.
- [x] Integration test (10 tests, all passing): verify→raises, reject→restores within 1e-6, flag→0, unflag→restores; field relativity (second player on the same map shifts); `sort=skill_score` descending + paginated with `skill_rank` intact; zero-eligible player score 0 ranked last + `GET /skill/users/{id}` returns 0 / empty breakdown; PATCH 401 unauth / 401-403 non-superuser / 200 superuser with scores changing; breakdown contributions sum to total.
- [x] `just lint-api` clean.

## Known Stubs

None — every change wires live behavior (real emits, a real SQL column, real endpoint-driven test assertions).

## Threat Flags

None — no security surface beyond the planned `<threat_model>` was introduced. The emit is fire-and-forget post-commit bounded by the 13-04 in-flight collapse guard (T-13-15); the leaderboard `sort` param is a closed Literal allow-list with no raw interpolation (T-13-16); all four state-change paths emit so symmetric removal is CI-proven (T-13-17/T-13-18); no new package installs (T-13-SC).

## Self-Check: PASSED

- FOUND: apps/api/tests/integration/test_skill.py
- FOUND commit: 8222496
- FOUND commit: affd0ad
- FOUND commit: 58df609

---
*Phase: 13-skill-score*
*Completed: 2026-06-12*
