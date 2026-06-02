---
phase: 08-rewards-engine
plan: 03
subsystem: services
tags: [tournaments, xp, rewards, outbox, streaks, idempotency, asyncpg, tdd]

requires:
  - phase: 08-rewards-engine
    plan: 01
    provides: tournaments.xp_grants ledger + claim_xp_grant/advance_streak/fetch_cycle_participants/fetch_all_streak_user_ids
  - phase: 08-rewards-engine
    plan: 02
    provides: TournamentRewardService (award_participation/award_cycle_end) + LootboxService.grant_xp conn-accepting helper
  - phase: 07-cycle-transitions
    provides: tournaments.pending_transitions outbox + publish_pending_transitions ~10s poller + cycle_completed events
provides:
  - Participation XP hook in TournamentService.submit_completion (existing-is-None branch, inside the submit transaction)
  - Cycle-end placement + streak rewards hooked into publish_pending_transitions for cycle_completed rows (inside the outbox transaction)
  - Non-participant streak reset sweep (_reset_non_participant_streaks) using fetch_all_streak_user_ids minus fetch_cycle_participants
  - Controller DI wiring of provide_tournament_reward_service into TournamentsController
  - Real-DB integration tests proving RWD-01/02/04/05 + ledger double-grant safety end-to-end
affects: []

tech-stack:
  added: []
  patterns:
    - "Reward hooks ride existing transactions (submit txn + outbox txn) — every grant atomic with the work that triggers it, replay-safe via the 08-01 ledger, no new scheduler"
    - "Reset sweep computed in Python: full streak roster (fetch_all_streak_user_ids) minus cycle participants (fetch_cycle_participants), advance_streak(participated=False) on the complement"
    - "Optional reward_service param on TournamentService keeps existing unit-test constructors working while the DI provider always supplies one"

key-files:
  created: []
  modified:
    - apps/api/services/tournament_service.py
    - apps/api/routes/v3/tournaments.py
    - apps/api/services/tournament_outbox_service.py
    - apps/api/tests/integration/test_tournament_rewards.py
    - apps/api/tests/services/test_tournament_service.py
    - apps/api/tests/repository/tournaments/test_outbox_poller.py

key-decisions:
  - "reward_service is an OPTIONAL TournamentService.__init__ param (default None) so the 26 existing mock-based unit tests keep their 3-arg constructor; submit_completion guards the call with `is not None`"
  - "The non-participant reset sweep lives in a module-level helper (_reset_non_participant_streaks) in the outbox service, not in TournamentRewardService — it needs the full tracked-user set which is broader than one event's category scope (per 08-02 boundary)"
  - "Integration + outbox reward-hook tests DELETE orphaned unpublished pending_transitions rows for other cycles before polling, because the session/xdist-shared DB can carry an unpublishable poison row from TestPublishFailure that would make the poll raise before reaching the test's own cycle_completed row"
  - "Controller deps add lootbox_repo + tournament_reward_service so provide_tournament_reward_service (which needs both repos) resolves and provide_tournament_service receives the reward service"

requirements-completed: [RWD-01, RWD-02, RWD-04, RWD-05]

duration: 14min
completed: 2026-05-30
---

# Phase 08 Plan 03: Rewards Engine — Hook Wiring Summary

**Wired the 08-02 reward service into the two existing transaction boundaries — participation XP on `submit_completion`'s first-completion branch and placement + streak rewards on the outbox poller's `cycle_completed` rows — added the non-participant streak reset sweep (the piece the per-event reward service could not own), and proved RWD-01/02/04/05 plus end-to-end ledger double-grant safety with real-DB integration tests. No new scheduler, no API-side broker consumer.**

## Performance

- **Duration:** ~14 min
- **Started:** 2026-05-30T15:15:00Z (approx)
- **Completed:** 2026-05-30
- **Tasks:** 3
- **Files modified:** 6

## Accomplishments

- **Task 1 — Participation hook (RWD-01):** `submit_completion` now captures `is_first_completion = existing is None` and, inside the open submit transaction (after `create_tournament_completion`/`cross_write_to_core`), calls `self._reward_service.award_participation(cycle=cycle, user_id=..., conn=conn)`. The ledger claim + lootbox.xp upsert + completion insert commit (or roll back) together. `reward_service` is injected via an updated `provide_tournament_service`, and `provide_tournament_reward_service` + `lootbox_repo` are wired into the `TournamentsController.dependencies` dict.
- **Task 2 — Cycle-end hook + reset sweep (RWD-02/04/05):** `publish_pending_transitions` constructs a `TournamentRewardService` alongside the existing outbox service and, for `cycle_completed` rows only, calls `await reward_service.award_cycle_end(event, conn=conn)` then `_reset_non_participant_streaks(...)` inside the SAME outbox transaction before publish/mark. The reset sweep reads `fetch_all_streak_user_ids` minus `fetch_cycle_participants(event.cycle_id)` and calls `advance_streak(participated=False)` on the complement, resetting non-participant streaks to 0 while the `last_cycle_id IS DISTINCT FROM` guard keeps multi-category dedupe intact. Rides the existing ~10s lifespan poller — no second scheduler.
- **Task 3 — Integration tests:** Replaced the 08-01 scaffold with 5 real-DB tests driving the submit endpoint and `publish_pending_transitions` directly (07-03 pattern, `publish_message` monkeypatched). Coverage: participation granted once on first submit / not on repeat; participant streak increments; non-participant streak resets to 0; multi-category/replay dedupe leaves `current_streak == 1`; double-grant replay adds no `xp_grants` rows and no extra `lootbox.xp`.

## Task Commits

1. **Task 1: Hook participation XP into submit_completion** (TDD) — `9d7e393` (test/RED), `52c81b5` (feat/GREEN)
2. **Task 2: Hook cycle-end rewards + reset sweep into outbox loop** (TDD) — `aed1471` (test/RED), `6a86dcf` (feat/GREEN)
3. **Task 3: Real-DB integration tests** — `e2032b5` (test)

## Files Created/Modified

- `apps/api/services/tournament_service.py` — optional `reward_service` ctor param; `award_participation` call in the existing-is-None branch; `provide_tournament_service` injects the reward service
- `apps/api/routes/v3/tournaments.py` — controller deps add `lootbox_repo` + `tournament_reward_service`
- `apps/api/services/tournament_outbox_service.py` — `award_cycle_end` + `_reset_non_participant_streaks` for `cycle_completed` rows in the outbox transaction
- `apps/api/tests/integration/test_tournament_rewards.py` — scaffold replaced with 5 RWD-01/02/04/05 + double-grant integration tests
- `apps/api/tests/services/test_tournament_service.py` — participation-hook unit tests (called once on first completion, not on repeat)
- `apps/api/tests/repository/tournaments/test_outbox_poller.py` — cycle-end reward hook tests (invoked for cycle_completed, never for cycle_started)

## Decisions Made

- `reward_service` is an optional `TournamentService.__init__` param (default `None`) to preserve the existing 3-arg mock constructors; `submit_completion` guards with `is not None`.
- The non-participant reset sweep is a module-level helper in the outbox service (not in `TournamentRewardService`), honoring the 08-02 scope boundary that the per-event service cannot see the full tracked-user set.
- Reward-hook tests clear orphaned unpublished `pending_transitions` rows for other cycles before polling, to be resilient to the `TestPublishFailure` poison row in the shared DB.

## Deviations from Plan

None - plan executed exactly as written. (The optional-param choice and the orphan-row cleanup are test-isolation tactics within the plan's intent, not scope changes.)

## Issues Encountered

- `--testmon` in `apps/api/pyproject.toml` `addopts` deselects tests when multiple files are passed together; used `--no-testmon` for combined verification runs (carried forward from 08-02).
- The session/xdist-shared DB carries an unpublishable poison `cycle_completed` row left by `TestPublishFailure`; without cleanup, any later test calling `publish_pending_transitions` raises `msgspec.ValidationError` before reaching its own row. Resolved by deleting other cycles' unpublished rows at test setup (no production code change).

## TDD Gate Compliance

- Task 1: `9d7e393` (RED — `TournamentService.__init__()` takes 4 args but 5 given) → `52c81b5` (GREEN).
- Task 2: `aed1471` (RED — `award_cycle_end` not invoked, `assert 1 in []`) → `6a86dcf` (GREEN).
- Task 3: tests authored after the Task 1/2 implementations existed (the plan defines Task 3 as the end-to-end proof of already-wired hooks); all 5 pass on a real DB. No behavioral RED cycle applies since the wiring was already GREEN.
- No REFACTOR commits were needed.

## Threat Model Compliance

- **T-08-08 (outbox replay double-pays):** `award_cycle_end` runs inside the outbox txn; every grant ledger-guarded. `TestDoubleGrantReplaySafe::test_replay_grants_no_duplicate_xp` asserts identical `xp_grants` count and `lootbox.xp` amount after a second poll.
- **T-08-09 (repeated submissions farm participation):** participation gated on the existing-is-None branch AND the `participation` ledger row. `test_first_submission_grants_participation_once` asserts a repeat submit adds no grant.
- **T-08-10 (streak inflation via concurrent categories):** `advance_streak` `last_cycle_id IS DISTINCT FROM` guard; `TestMultiCategoryDedupe` asserts `current_streak == 1` after re-processing the same cycle.
- **T-08-11 (partial state mid-finalization):** `award_cycle_end` + reset sweep share the outbox `conn.transaction()`; grants roll back together; publish is best-effort after-write.
- **T-08-SC (package installs):** none — zero new dependencies this plan.

## Verification

- `pytest tests/integration/test_tournament_rewards.py -p no:xdist -q` → 5 passed.
- `pytest tests/integration/test_tournament_rewards.py tests/integration/test_tournaments_integration.py tests/services/test_tournament_service.py tests/services/test_tournament_reward_service.py tests/repository/tournaments/test_outbox_poller.py -p no:xdist --no-testmon` → 87 passed.
- `pytest tests/services/test_lootbox_service.py` → 23 passed (no grant_xp regression).
- `basedpyright services/tournament_service.py services/tournament_outbox_service.py services/tournament_reward_service.py routes/v3/tournaments.py` → 0 errors.
- `ruff check` + `ruff format --check` on modified service/route files → clean.
- `python -c "from app import app"` → exits 0 (DI wiring resolves).

## Known Stubs

None — both hooks call live reward-service methods with the active connection; the reset sweep uses the real 08-01 repo methods.

## Next Phase Readiness

- The rewards engine is fully wired end-to-end: participation on submit, placement + streak + reset on cycle finalization, all replay-safe. Downstream phases (champion role assignment, leaderboards) can rely on `tournaments.xp_grants`, `tournaments.streaks`, and the `XpGrantEvent` stream being populated by the live hooks.

## Self-Check: PASSED

- FOUND: apps/api/services/tournament_service.py (award_participation)
- FOUND: apps/api/routes/v3/tournaments.py (tournament_reward_service)
- FOUND: apps/api/services/tournament_outbox_service.py (award_cycle_end, fetch_all_streak_user_ids)
- FOUND: apps/api/tests/integration/test_tournament_rewards.py (5 tests)
- FOUND commits: 9d7e393, 52c81b5, aed1471, 6a86dcf, e2032b5

---
*Phase: 08-rewards-engine*
*Completed: 2026-05-30*
