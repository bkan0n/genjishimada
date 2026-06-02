---
phase: 08-rewards-engine
plan: 02
subsystem: services
tags: [tournaments, xp, rewards, idempotency, asyncpg, msgspec, rabbitmq, tdd]

requires:
  - phase: 08-rewards-engine
    plan: 01
    provides: tournaments.xp_grants ledger + claim_xp_grant/advance_streak/fetch_cycle_participants repo methods + "Tournament" XP_TYPES
provides:
  - LootboxService.grant_xp — conn-accepting, transaction-aware XP grant helper (lootbox.xp write + XpGrantEvent publish in caller's transaction)
  - TournamentRewardService with award_participation + award_cycle_end + _grant_xp + provide_tournament_reward_service DI provider
  - Full unit coverage (RWD-01/02/05) against a mocked grant seam
affects: [08-03-hook-wiring]

tech-stack:
  added: []
  patterns:
    - "Transaction-aware grant helper: grant_xp(..., conn) threads conn into fetch_xp_multiplier + upsert_user_xp so ledger claim + xp write commit atomically"
    - "Ledger-guarded grant: claim_xp_grant precedes every grant; False claim is a no-op (double-grant guard since api.xp.grant is in IGNORE_IDEMPOTENCY)"
    - "Placement mapping via dict[place->xp].get(rank): ties both paid, beyond-tier ranks skipped, empty standings grant nothing"
    - "Streak bonus on exact-threshold match only (dict[threshold->xp].get(current_streak))"

key-files:
  created:
    - apps/api/services/tournament_reward_service.py
  modified:
    - apps/api/services/lootbox_service.py
    - apps/api/tests/services/test_lootbox_service.py
    - apps/api/tests/services/test_tournament_reward_service.py

key-decisions:
  - "Inject LootboxService into TournamentRewardService (not instantiated internally per call) for testability — the grant_xp seam is mocked in unit tests"
  - "grant_user_xp delegates to grant_xp with no conn, preserving its self-acquiring behavior and all existing lootbox tests"
  - "Removed every textual reference to the tournament-specific grant event from the reward service so the plan's `! grep -q TournamentXpGrantEvent` negative assertion stays true even against docstrings"
  - "Streak bonus fires only on exact threshold equality (not >=), matching the per-tier dict.get(current_streak) contract"

requirements-completed: [RWD-01, RWD-02, RWD-05]

duration: 6min
completed: 2026-05-30
---

# Phase 08 Plan 02: Rewards Engine — Reward Service Summary

**A transaction-aware `LootboxService.grant_xp` helper plus `TournamentRewardService` (participation, placement with tie/beyond-tier/empty handling, and exact-threshold streak bonuses) — every grant ledger-guarded by 08-01's `claim_xp_grant` and delivered as the generic `XpGrantEvent` (type="Tournament") the bot already consumes**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-05-30T15:06:52Z
- **Completed:** 2026-05-30T15:13:01Z
- **Tasks:** 3
- **Files modified:** 3 (1 created, 2 modified) + 2 test files

## Accomplishments
- Extracted `LootboxService.grant_xp(headers, user_id, amount, type, reason, *, conn=None)` — threads `conn` into `fetch_xp_multiplier` and `upsert_user_xp` so the `lootbox.xp` upsert joins the caller's transaction; publishes the generic `XpGrantEvent` to `api.xp.grant` as a post-write notification. `grant_user_xp` now delegates to it (no behavior change; all 23 existing lootbox tests green).
- Implemented `TournamentRewardService(BaseService)` with `award_participation`, `award_cycle_end`, a private ledger-guarded `_grant_xp`, and the `provide_tournament_reward_service` DI provider.
  - **Participation (RWD-01):** grants `categories.participation_xp` once per (cycle, user) via the ledger; `participation_xp == 0` is a no-op (no claim, no grant).
  - **Placement (RWD-02):** `{place: xp}` map applied via `.get(rank)` — ties both paid, ranks beyond configured tiers skipped, empty standings grant nothing.
  - **Streak (RWD-05):** every distinct participant gets `advance_streak(participated=True)`; bonus granted only when the returned `current_streak` exactly matches a configured threshold. Non-participant reset is explicitly deferred to 08-03 (documented in the class docstring).
- Replaced the 08-01 reward test scaffold with 11 real unit tests (participation once / zero-noop, placement map / tie / beyond-tier / empty, streak at / below / above threshold, all-participants-advanced) against a mocked `grant_xp` seam — no broker or DB.

## Task Commits

1. **Task 1: Extract conn-accepting grant_xp helper** (TDD) — `bd98622` (test/RED), `b6c8789` (feat/GREEN)
2. **Task 2 + Task 3: TournamentRewardService + unit tests** (TDD) — `2a4eba7` (test/RED), `c4a1a0b` (feat/GREEN)

## Files Created/Modified
- `apps/api/services/tournament_reward_service.py` — new `TournamentRewardService` + `_grant_xp` + DI provider
- `apps/api/services/lootbox_service.py` — extracted `grant_xp` helper; `grant_user_xp` delegates
- `apps/api/tests/services/test_lootbox_service.py` — `TestGrantXpConnHelper` (conn threading, event shape, delegation)
- `apps/api/tests/services/test_tournament_reward_service.py` — replaced scaffold with RWD-01/02/05 coverage

## Decisions Made
- Inject `LootboxService` into the reward service for a clean, mockable grant seam (vs. constructing one per grant).
- `grant_user_xp` delegates to `grant_xp` with no `conn`, preserving its self-acquiring path and existing test behavior.
- Stripped the tournament-specific grant-event name from the reward service entirely (even docstrings) so the negative assertion holds.
- Streak bonus is exact-threshold-equality, matching the `dict[threshold->xp].get(current_streak)` contract.

## Deviations from Plan
None - plan executed exactly as written. (The only structural choice — LootboxService injection vs. internal instantiation — was offered by the plan itself; injection was chosen for testability as the plan recommended.)

## Issues Encountered
- `--testmon` (in `apps/api/pyproject.toml` `addopts`) deselected all tests when both test files were passed together, masking results. Resolved by appending `--no-testmon` for combined verification runs; per-file runs were unaffected. No code change required.

## TDD Gate Compliance
Both tasks were `tdd="true"` and followed RED→GREEN:
- Task 1: `bd98622` (RED — `grant_xp` AttributeError) → `b6c8789` (GREEN).
- Task 2/3: `2a4eba7` (RED — `ModuleNotFoundError: services.tournament_reward_service`) → `c4a1a0b` (GREEN).
No REFACTOR commits were needed (implementations were clean on first GREEN).

## Threat Model Compliance
- **T-08-04 (double XP on replay):** every grant gated by `claim_xp_grant` before `grant_xp`; a False claim short-circuits (`_grant_xp` early return). Covered by `test_participation_second_call_no_grant`.
- **T-08-05 (partial grant on crash):** `grant_xp` accepts `conn`, so the ledger claim + `upsert_user_xp` share the caller's transaction; publish is a best-effort after-write notification. Covered by `test_grant_xp_threads_conn_into_repo_calls`.
- **T-08-06 (undecodable event crashes bot):** only the generic `XpGrantEvent` (type="Tournament") is published; `grep -c TournamentXpGrantEvent` in the reward service returns 0.

## Verification
- `pytest tests/services/test_tournament_reward_service.py tests/services/test_lootbox_service.py --no-testmon -p no:xdist` → 34 passed.
- `basedpyright services/tournament_reward_service.py services/lootbox_service.py` → 0 errors.
- `ruff check` + `ruff format --check` on both service files → clean.
- `! grep -q TournamentXpGrantEvent services/tournament_reward_service.py` → true.

## Known Stubs
None — all reward paths are wired to live repo methods and the real grant helper. (The non-participant streak reset is an intentional out-of-scope boundary owned by 08-03, documented in the service docstring, not a stub.)

## Next Phase Readiness
- 08-03 can wire `award_participation` into the submission path and `award_cycle_end` into the cycle-completed outbox hook, supplying the active `conn` for atomicity.
- 08-03 owns the non-participant streak reset sweep using `fetch_all_streak_user_ids` (already present from 08-01) minus `fetch_cycle_participants`.

## Self-Check: PASSED
- FOUND: apps/api/services/tournament_reward_service.py
- FOUND: apps/api/services/lootbox_service.py (grant_xp)
- FOUND: apps/api/tests/services/test_tournament_reward_service.py (11 tests)
- FOUND commits: bd98622, b6c8789, 2a4eba7, c4a1a0b

---
*Phase: 08-rewards-engine*
*Completed: 2026-05-30*
