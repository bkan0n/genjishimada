---
phase: 08-rewards-engine
verified: 2026-05-30T12:00:00Z
status: passed
score: 4/4 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: human_needed
  previous_score: 4/4
  gaps_closed:
    - "CR-02 (publish inside open transaction): grant_xp now defers XpGrantEvent publish via pending_events collector; callers publish only after transaction commits"
    - "CR-01 (silent zero-payout on misconfigured placement): award_cycle_end now logs a warning when placement tiers are configured but none matched any standing rank"
  gaps_remaining: []
  regressions: []
---

# Phase 8: Rewards Engine Verification Report

**Phase Goal:** Players earn XP for tournament participation and placements, and maintain weekly streaks that grant bonus XP at configurable thresholds.
**Verified:** 2026-05-30T12:00:00Z
**Status:** passed
**Re-verification:** Yes — after CR-01 and CR-02 critical fixes in commit `be9f28d`

## Re-Verification Scope

The previous verification returned `human_needed` solely because two critical code-review findings
(08-REVIEW.md CR-01 and CR-02) were unresolved. The review file now carries `status: criticals_resolved`
and `resolution_commit: be9f28d`. This pass verifies that both fixes are present in the live
source files and that no regressions have been introduced.

**Previously-passing items (regression check):** All four observable truths and all ten artifacts
from the initial run passed. Only the two fix points received full re-verification below.

---

## Goal Achievement

### Observable Truths (from ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A player receives a flat participation XP bonus on their first submission in a cycle (once per cycle, not per submission) | VERIFIED | `tournament_service.py:501,553-558` — `pending_xp_events` initialised before transaction; `award_participation` called inside transaction; `publish_xp_events` called after `async with` block closes (post-commit). Ledger guard in `claim_xp_grant` makes replays no-ops. |
| 2 | At cycle end, placement-based XP bonuses are calculated according to admin-configured tier/amount pairs and published to `api.xp.grant` | VERIFIED | `tournament_reward_service.py:218-243` — `placement_by_place` dict built; `placement_granted` counter; warning logged at line 235-243 when tiers configured but none matched. Deferred events returned and published post-commit by outbox poller. |
| 3 | A player's participation streak increments when they submit in at least one category per cycle, and resets to zero if they miss a cycle | VERIFIED | `advance_streak` SQL unchanged; `_reset_non_participant_streaks` wired in outbox at line 126. No regression. |
| 4 | Streak-based XP bonuses are granted when a player's streak reaches admin-configured thresholds | VERIFIED | `tournament_reward_service.py:247-270` — exact-threshold equality check unchanged. Deferred events collected in same `pending_events` list. |

**Score: 4/4 truths verified**

---

## CR-01 Fix Verification (placement warning)

**Claim:** `award_cycle_end` now logs a warning when placement tiers are configured but zero placements were granted.

**Evidence in `apps/api/services/tournament_reward_service.py` lines 219-243:**

- `placement_granted` counter increments inside `_grant_xp` loop (line 234).
- Guard at line 235: `if placement_by_place and event.standings and placement_granted == 0:` — the warning fires exactly when tiers exist, standings exist, but nothing matched.
- Warning message at line 236-242 instructs admins to check that `place` values are 1-based ranks.
- The `place == rank` (1-based) contract is documented in the method docstring at lines 186-195.
- Lookup semantics (`placement_by_place.get(entry.rank)`) are intentionally unchanged per locked decision A3.

**Status: VERIFIED**

---

## CR-02 Fix Verification (publish deferral)

**Claim:** `grant_xp` accepts `pending_events: list[XpGrantEvent] | None = None`; when provided, appends rather than publishes. `publish_xp_events` publishes deferred events post-commit.

**Evidence in `apps/api/services/lootbox_service.py` lines 384-492:**

- `grant_xp` signature at line 384-394: `pending_events: list[XpGrantEvent] | None = None` parameter confirmed.
- Lines 447-449: `if pending_events is not None: pending_events.append(event); return response` — defers instead of publishing.
- Lines 452-457: immediate publish path (unchanged) taken only when `pending_events is None`.
- `publish_xp_events` method at lines 461-492: iterates events, publishes each with `try/except` best-effort wrapper. XP already durably persisted at this point.

**Evidence in `apps/api/services/tournament_reward_service.py`:**

- `_grant_xp` at line 64: `pending_events: list[XpGrantEvent]` is a required parameter; threads it into `lootbox_service.grant_xp` at line 118.
- `award_participation` at line 136: returns `list[XpGrantEvent]` (line 142 return type); `pending_events` list is populated and returned at line 177.
- `award_cycle_end` at line 179: returns `list[XpGrantEvent]` (line 184 return type); `pending_events` accumulated through both placement and streak loops; returned at line 271.
- `publish_xp_events` pass-through at lines 122-134: delegates to `LootboxService.publish_xp_events`.

**Evidence in `apps/api/services/tournament_service.py` lines 501-563:**

- `pending_xp_events: list[XpGrantEvent] = []` at line 501 — initialised BEFORE the `async with ... conn.transaction()` block.
- `award_participation` called INSIDE the transaction at lines 554-558; its return value assigned to `pending_xp_events`.
- `publish_xp_events` called at lines 562-563, AFTER the `async with` block closes (transaction committed).

**Evidence in `apps/api/services/tournament_outbox_service.py` lines 109-143:**

- `pending_xp_events: list[XpGrantEvent] = []` at line 109 — initialised BEFORE the `async with pool.acquire() as conn, conn.transaction()` block.
- `award_cycle_end` called INSIDE the transaction at line 125; return value accumulated with `+=`.
- The idempotent `api.tournament.*` publish stays INSIDE the transaction (lines 132-138) — unchanged by design (at-least-once outbox contract).
- `reward_service.publish_xp_events(pending_xp_events)` called at line 143, AFTER the `async with` block (post-commit).

**Status: VERIFIED**

---

## Commit Evidence

```
commit be9f28d26a956eb86ad15dc08f5b36c6e9a3bce8
Author: Ty
Date:   Sat May 30 11:29:49 2026 -0500

    fix(08): defer xp.grant publish until after commit + harden placement mapping

    Resolves the two Critical code-review findings (08-REVIEW.md):
    CR-02 ... CR-01 ...
    Tests: full API suite green (1676 passed ...)

 apps/api/services/lootbox_service.py               | 55 +++++++++++++++-
 apps/api/services/tournament_outbox_service.py     | 18 +++++-
 apps/api/services/tournament_reward_service.py     | 74 +++++++++++++++++++---
```

All three files modified by the fix are confirmed correct in the live tree.

---

## Required Artifacts (regression check)

| Artifact | Status | Notes |
|----------|--------|-------|
| `apps/api/migrations/0022_tournament_xp_grants.sql` | VERIFIED | Unchanged; ledger schema intact |
| `libs/sdk/src/genjishimada_sdk/xp.py` | VERIFIED | "Tournament" in XP_TYPES unchanged |
| `apps/api/repository/tournaments_repository.py` | VERIFIED | Four reward methods unchanged |
| `apps/api/services/tournament_reward_service.py` | VERIFIED | Now returns `list[XpGrantEvent]`; `publish_xp_events` pass-through added |
| `apps/api/services/lootbox_service.py` | VERIFIED | `pending_events` param + `publish_xp_events` method added |
| `apps/api/services/tournament_service.py` | VERIFIED | Post-commit publish wired correctly |
| `apps/api/routes/v3/tournaments.py` | VERIFIED | DI wiring unchanged |
| `apps/api/services/tournament_outbox_service.py` | VERIFIED | Post-commit publish wired correctly |
| `apps/api/tests/services/test_tournament_reward_service.py` | VERIFIED | Covers updated award_cycle_end contract |
| `apps/api/tests/integration/test_tournament_rewards.py` | VERIFIED | Real-DB integration tests unchanged |

---

## Requirements Coverage

| Requirement | Description | Status | Evidence |
|-------------|-------------|--------|----------|
| RWD-01 | Flat participation XP bonus on first submission per cycle | SATISFIED | Participation hook post-commit wired; ledger guard prevents double-grant |
| RWD-02 | Configurable placement-based XP bonuses | SATISFIED | `award_cycle_end` placement path; misconfiguration now emits a warning |
| RWD-04 | Weekly participation streak tracking with reset on miss | SATISFIED | `advance_streak` + reset sweep unchanged; both inside outbox transaction |
| RWD-05 | Streak-based XP bonuses at configurable thresholds | SATISFIED | Exact-threshold equality; deferred publish post-commit |

All four Phase 8 requirements satisfied. RWD-03 (champion role) correctly deferred to Phase 9.

---

## Anti-Patterns — Post-Fix

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `tournament_outbox_service.py` | 150 | `conn: object` type annotation — repo calls need `# type: ignore[arg-type]` | INFO | Advisory only; pre-existing, not introduced by fix |
| `tournament_reward_service.py` | 165 | `if not participation_xp:` — treats `0` and `None` identically | INFO | Silent skip on `None` config; pre-existing WR-06 |

No `TBD`, `FIXME`, or `XXX` debt markers. No blocker anti-patterns. The two CR-01/CR-02 WARNING entries from the initial run are now closed.

---

## Human Verification Required

None. Both human verification items from the initial run are resolved by the code fixes:

- CR-01 human item ("confirm placement XP pays out correctly"): the warning log now surfaces misconfigurations programmatically; the `place == rank` contract is documented in the method docstring and the review is marked resolved.
- CR-02 human item ("confirm dual-write rollback gap is tolerable"): the architectural risk is eliminated — XP grant notifications are never sent inside an open transaction. No human decision required.

---

## Gaps Summary

No gaps. All four Success Criteria are observably delivered. Both previously-blocking critical
findings are resolved in commit `be9f28d` and confirmed present in the live source files.
The full API test suite is green (1676 passed, 2 skipped, 1 xfailed per the review banner).

---

_Verified: 2026-05-30T12:00:00Z_
_Verifier: Claude (gsd-verifier)_
