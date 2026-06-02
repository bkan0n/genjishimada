---
phase: 08-rewards-engine
plan: 01
subsystem: database
tags: [postgres, asyncpg, msgspec, tournaments, xp, idempotency, outbox]

requires:
  - phase: 07-cycle-transitions
    provides: tournaments.pending_transitions outbox + cycle_completed events (at-least-once re-delivery this ledger guards against)
  - phase: 01-foundation
    provides: tournaments schema (categories, cycles, completions, streaks) from migration 0020/0021
provides:
  - tournaments.xp_grants double-grant ledger (migration 0022) with UNIQUE(cycle_id, user_id, reason)
  - "Tournament" XP_TYPES member reusing the generic XpGrantEvent
  - claim_xp_grant (ON CONFLICT DO NOTHING ledger claim)
  - advance_streak (reset-capable, dedupe-guarded streak update)
  - fetch_cycle_participants (distinct submitters per cycle)
  - fetch_all_streak_user_ids (full tracked-user set for the 08-03 reset sweep)
  - Wave-0 reward test scaffolds (filled in 08-02/08-03)
affects: [08-02-reward-service, 08-03-hook-wiring]

tech-stack:
  added: []
  patterns:
    - "Idempotency ledger: UNIQUE(scope) + INSERT ON CONFLICT DO NOTHING RETURNING id, claim returns True only on first insert"
    - "Reset-capable streak update with last_cycle_id IS DISTINCT FROM dedupe guard for multi-category windows"

key-files:
  created:
    - apps/api/migrations/0022_tournament_xp_grants.sql
    - apps/api/tests/services/test_tournament_reward_service.py
    - apps/api/tests/integration/test_tournament_rewards.py
  modified:
    - libs/sdk/src/genjishimada_sdk/xp.py
    - apps/api/repository/tournaments_repository.py

key-decisions:
  - "Tournament XP reuses the generic XpGrantEvent (type='Tournament') per RESEARCH.md, overriding CONTEXT Decision F's TournamentXpGrantEvent"
  - "No XP_AMOUNTS entry for 'Tournament' — amounts are config-driven from tournaments.categories, not table-driven"
  - "advance_streak is a new method (not a change to upsert_streak) because upsert_streak has no reset path and no dedupe guard"
  - "xp_grants.user_id is bigint (Discord snowflake), matching 0021 v_winner widening, not int"

patterns-established:
  - "Ledger-guarded grant: claim_xp_grant returns False on replay so the api.xp.grant publish (in IGNORE_IDEMPOTENCY) is the single source of double-grant protection"
  - "fetch_all_streak_user_ids has no WHERE clause by design — the sweep subtracts cycle participants in Python"

requirements-completed: [RWD-01, RWD-02, RWD-04, RWD-05]

duration: 3min
completed: 2026-05-30
---

# Phase 08 Plan 01: Rewards Engine Foundation Summary

**tournaments.xp_grants double-grant ledger (migration 0022), the 'Tournament' XP_TYPES member, and four reward repository methods (idempotent claim, reset-capable streak, per-cycle participants, all tracked users) that the reward service and hook wiring build on**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-05-30T15:01:32Z
- **Completed:** 2026-05-30T15:04:31Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments
- Migration 0022 creates `tournaments.xp_grants` with `UNIQUE(cycle_id, user_id, reason)` — the only real double-grant guard since `api.xp.grant` is in IGNORE_IDEMPOTENCY.
- Added `"Tournament"` to `XP_TYPES` and reinstalled the workspace SDK (`just fix`) so API/bot resolve the new literal; tournament grants reuse the generic `XpGrantEvent`.
- Added four `TournamentRepository` methods: `claim_xp_grant`, `advance_streak` (reset-capable + dedupe-guarded), `fetch_cycle_participants`, `fetch_all_streak_user_ids`.
- Created two Wave-0 test scaffolds so downstream `<verify>` commands have collectible targets.

## Task Commits

1. **Task 1: Write migration 0022 — tournaments.xp_grants ledger** — `3ef6fdb` (feat)
2. **Task 2: Add 'Tournament' to XP_TYPES and run just fix** — `f5cc23a` (feat)
3. **Task 3: Add reward repository methods + Wave-0 test scaffolds** (TDD) — `5df3be1` (test, scaffolds/RED), `5345407` (feat, repository methods/GREEN)

## Files Created/Modified
- `apps/api/migrations/0022_tournament_xp_grants.sql` — xp_grants ledger table, indexes, comments
- `libs/sdk/src/genjishimada_sdk/xp.py` — added "Tournament" to XP_TYPES literal
- `apps/api/repository/tournaments_repository.py` — claim_xp_grant, advance_streak, fetch_cycle_participants, fetch_all_streak_user_ids
- `apps/api/tests/services/test_tournament_reward_service.py` — unit scaffold (domain_tournaments)
- `apps/api/tests/integration/test_tournament_rewards.py` — integration scaffold (integration, domain_tournaments)

## Decisions Made
- Tournament XP grants reuse the generic `XpGrantEvent` with `type="Tournament"` (RESEARCH.md authoritative contract, overriding CONTEXT Decision F).
- No `XP_AMOUNTS` entry for `"Tournament"` — amounts come from `tournaments.categories` config.
- `advance_streak` is a brand-new method rather than a modification of `upsert_streak`, which is increment-only with no dedupe guard.
- `xp_grants.user_id` is `bigint` (Discord snowflake), matching the 0021 v_winner widening.

## Deviations from Plan
None - plan executed exactly as written.

## Issues Encountered
None.

## TDD Gate Compliance
Task 3 was `tdd="true"`. The "tests" here are intentional placeholder scaffolds (filled in 08-02/08-03 per the plan), so they pass rather than fail in RED. Gate sequence in git log: `test(...)` scaffold commit (`5df3be1`) precedes the `feat(...)` implementation commit (`5345407`). No behavioral RED→GREEN failure cycle applies because the plan explicitly defines these as scaffolds, not behavior tests.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Foundation is in place for 08-02 (reward service) and 08-03 (hook wiring + non-participant reset sweep).
- `claim_xp_grant`, `advance_streak`, `fetch_cycle_participants`, and `fetch_all_streak_user_ids` type-check clean (basedpyright: 0 errors) and the migration applies under the conftest glob (38 tournament integration tests pass).

## Self-Check: PASSED
- FOUND: apps/api/migrations/0022_tournament_xp_grants.sql
- FOUND: apps/api/repository/tournaments_repository.py (4 methods)
- FOUND: apps/api/tests/services/test_tournament_reward_service.py
- FOUND: apps/api/tests/integration/test_tournament_rewards.py
- FOUND: libs/sdk/src/genjishimada_sdk/xp.py ("Tournament")
- FOUND commits: 3ef6fdb, f5cc23a, 5df3be1, 5345407

---
*Phase: 08-rewards-engine*
*Completed: 2026-05-30*
