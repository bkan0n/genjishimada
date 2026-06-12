---
phase: 13-skill-score
plan: 05
subsystem: api
tags: [skill-score, litestar, controller, in-process-event, lifespan-poller, superuser-guard]

# Dependency graph
requires:
  - phase: 13-02
    provides: "Weights / SkillConfigUpdateRequest / SkillSummaryResponse / SkillBreakdownRow SDK structs"
  - phase: 13-03
    provides: "provide_skill_repository / SkillRepository"
  - phase: 13-04
    provides: "SkillService.recompute_all / get_user_skill / get_user_breakdown / get_weights / update_weights, provide_skill_service, InvalidGammaError"
provides:
  - "SkillController: GET /skill/users/{id}, GET /skill/users/{id}/breakdown, GET /skill/config, PATCH /skill/config (superuser-only + immediate recompute)"
  - "skill.recompute.requested in-process event + SkillRecomputeRequestedEvent struct + handle_skill_recompute listener (auto-registered, D-01/D-04)"
  - "skill_nightly_rebuild_poller app-side lifespan task (D-03 durability backstop) calling the same recompute_all"
affects: [13-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Litestar Controller with @get/@patch handlers calling a DI-injected service (community.py / content.py shape)"
    - "Superuser-only write via opt={'required_scopes': {sentinel}} reusing scope_guard — no new scope minted"
    - "In-process @listener auto-registered by events/__init__.py discovery (no __init__.py edit)"
    - "App-side @asynccontextmanager lifespan poller mirroring tournament_outbox_poller (sleep-before-run, CancelledError-safe, cancel+await on shutdown)"

key-files:
  created:
    - apps/api/routes/v3/skill.py
    - apps/api/events/skill.py
  modified:
    - apps/api/events/schemas.py
    - apps/api/app.py

key-decisions:
  - "PATCH /skill/config maps InvalidGammaError (from update_weights, plan 13-04) to HTTP 422 before the recompute runs, so a bad gamma never triggers a rebuild."
  - "Nightly poller constructs the service via the existing provide_skill_repository/provide_skill_service DI providers from _app.state (not a hand-rolled construction), so it stays in lockstep with the request-path wiring."
  - "Nightly slot is 04:00 UTC (matching the '0 4 * * *' the dropped pg_cron block referenced); next-run computed each loop, sleep-before-run dodges the cold-start db_pool race."

requirements-completed: [4, 5, 7, 8]

# Metrics
duration: ~2min
completed: 2026-06-12
---

# Phase 13 Plan 05: Skill HTTP Surface + Recompute Machinery Summary

**Wired the skill domain into a reachable API: the four `/api/v3/skill/*` endpoints (3 typed GET reads + a superuser-only PATCH that updates weights then recomputes), the in-process `skill.recompute.requested` listener that runs the single `recompute_all` rebuild routine (D-04), and the app-side nightly lifespan poller that is the D-03 durability backstop — both recompute paths share the one routine, no pg_cron added.**

## Performance

- **Duration:** ~2 min
- **Completed:** 2026-06-12
- **Tasks:** 3
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments

- **`apps/api/routes/v3/skill.py` (new) — `SkillController`** (`path="/skill"`, auto-registered by `routes/v3/__init__.py`):
  - `GET /skill/users/{user_id:int}` → `SkillSummaryResponse` (score 0 + zero summary for a zero-eligible player, D-07).
  - `GET /skill/users/{user_id:int}/breakdown` → `list[SkillBreakdownRow]` (the D-06 per-map JSONB breakdown; `[]` for a zero-eligible player, D-07).
  - `GET /skill/config` → `Weights`.
  - `PATCH /skill/config` (`opt={"required_scopes": {"skill:admin"}}` sentinel → superuser bypasses the guard, everyone else 401/403; no new scope minted) → `update_weights(data)` then `recompute_all()` (D-10 immediate full recompute). `InvalidGammaError` → 422 before any recompute.
- **`apps/api/events/skill.py` (new) + `events/schemas.py` (mod) — the D-01 in-process trigger:** `SkillRecomputeRequestedEvent` (optional `reason` only, no required fields → emitter-friendly) + `@listener("skill.recompute.requested") handle_skill_recompute(event, skill_service)` running the single `recompute_all` (D-04). Auto-registered by `events/__init__.py` discovery — `from events import listeners` now reports 6 listeners (was 5), no `__init__.py` edit. In-process (not RabbitMQ), so `X-PYTEST-ENABLED=1` does not gate it.
- **`apps/api/app.py` (mod) — `skill_nightly_rebuild_poller` lifespan (D-03 backstop):** modeled on `tournament_outbox_poller` — sleeps until the next 04:00 UTC slot, builds the service via the existing `provide_skill_repository`/`provide_skill_service` DI providers from `_app.state` (local import avoids a circular import), and runs the SAME `recompute_all` as the event (D-04). CancelledError-safe with a broad `except` keeping the loop alive; cancelled+awaited on shutdown. Registered in `lifespan=[...]` after `tournament_outbox_poller`. **No pg_cron added to 0027** (the scorer is Python — app-side scheduler is the chosen mechanism; PATTERNS flag resolved).

## Task Commits

1. **Task 1: SkillController — 4 endpoints** — `e6e47af` (feat)
2. **Task 2: skill.recompute.requested event struct + listener** — `7e8ca94` (feat)
3. **Task 3: app-side nightly rebuild lifespan task** — `d712a42` (feat)

## Files Created/Modified

- `apps/api/routes/v3/skill.py` (created) — `SkillController` with the four endpoints.
- `apps/api/events/skill.py` (created) — `handle_skill_recompute` listener on `skill.recompute.requested`.
- `apps/api/events/schemas.py` (modified) — added `SkillRecomputeRequestedEvent` (no required fields).
- `apps/api/app.py` (modified) — `skill_nightly_rebuild_poller` lifespan task + registration.

## Verification Performed

- **Task 1 `<automated>`:** source assertions (`class SkillController`, `/users/{user_id:int}/breakdown`, `required_scopes`, `recompute_all`) pass; `just lint-api` clean (ruff format/check + basedpyright 0 errors).
- **Task 2 `<automated>`:** run from `apps/api` (the package's import root — the plan's repo-root invocation cannot resolve `events`), `from events import listeners` includes the new listener (6 listeners), `SkillRecomputeRequestedEvent()` constructs with no args; `just lint-api` clean.
- **Task 3 `<automated>`:** `app.py` mentions `skill_nightly_rebuild_poller` ≥2× and `recompute_all`; `import app` succeeds (lifespan wired); no pg_cron schedule in 0027 (only two doc comments noting its deliberate absence); `just lint-api` clean.

## Deviations from Plan

None - plan executed exactly as written.

Note (not a deviation): Task 2's `<automated>` verify snippet is written to run from the repo root, where the `events` package is not importable (the api app's import root is `apps/api/`). Re-running the identical assertions from `apps/api/` passes (6 listeners). No code change was required.

Note (not a deviation): `just lint-api`'s basedpyright scope does not include `apps/api/events`, but the ruff format pass covers it and the full app import chain (which imports `events`) type-checks clean via `app.py`.

## Acceptance Criteria

- [x] `SkillController` defines all four endpoints with the exact paths (`/skill/users/{id}`, `/breakdown`, `/config` GET + PATCH).
- [x] PATCH handler calls `update_weights` then `recompute_all` (D-10); guarded by `opt={"required_scopes": {...}}` (superuser-only).
- [x] `events/skill.py` defines `@listener("skill.recompute.requested")` calling `recompute_all` with a `skill_service: SkillService` DI arg; auto-registers.
- [x] `SkillRecomputeRequestedEvent` constructs with no required args.
- [x] `skill_nightly_rebuild_poller` defined + registered in `lifespan=[...]`; calls `recompute_all`; CancelledError-safe.
- [x] No pg_cron added to 0027; `just lint-api` clean; API boots without error (`import app` succeeds).

## Known Stubs

None — all four handlers and both recompute paths call live `SkillService` methods.

## Threat Flags

None — no security surface beyond the planned `<threat_model>` was introduced. The PATCH write reuses the existing superuser guard (T-13-11), `InvalidGammaError`→422 keeps a tampered gamma from triggering a recompute (T-13-12), and the in-flight collapse guard from 13-04 bounds the recompute paths (T-13-13).

## Next Phase Readiness

- The four endpoints, the in-process listener, and the nightly backstop are wired. Plan 13-06 emits `skill.recompute.requested` from the four D-02 verification-state-change paths in `completions_service.py` (threading `skill_service` into the listener kwargs, matching the listener arg name) and adds the integration tests (PATCH 401/403-vs-superuser, the three GET reads, event-triggered recompute) plus the community-leaderboard `skill_score` column wiring.
- Human-check (boot the API; exercise the four endpoints + a superuser/non-superuser PATCH) is best run alongside 13-06's integration suite once the emitters and the seeded snapshot exist.

## Self-Check: PASSED

- FOUND: apps/api/routes/v3/skill.py
- FOUND: apps/api/events/skill.py
- FOUND commit: e6e47af
- FOUND commit: 7e8ca94
- FOUND commit: d712a42

---
*Phase: 13-skill-score*
*Completed: 2026-06-12*
