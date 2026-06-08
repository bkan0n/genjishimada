---
phase: quick-260601-ui4
plan: 01
subsystem: tournaments
tags: [tournaments, verification, edition-rollover, drain-gate]
requires:
  - tournaments.completions.status (tri-state, migration 0025)
  - TournamentRepository.fetch_tournament_completion + fetch_cycle
  - TournamentRepository.count_inflight_verifications
provides:
  - "_propagate_tournament_verification resolves cycle from the completion's own cycle_id (status-agnostic)"
affects:
  - apps/api/services/completions_service.py
tech-stack:
  added: []
  patterns:
    - "Row-driven cycle resolution (mirror of TournamentService._set_verified) for the verify/propagation path"
key-files:
  created: []
  modified:
    - apps/api/services/completions_service.py
    - apps/api/tests/services/test_tournament_verification.py
    - apps/api/tests/services/test_completions_service.py
    - apps/api/tests/integration/test_tournaments_integration.py
decisions:
  - "Resolve the propagation cycle via fetch_tournament_completion -> fetch_cycle(row['cycle_id']) instead of the active-only get_active_cycle_by_map_id, so a finalizing cycle still propagates."
  - "Left the submit-path _resolve_active_cycle / get_active_cycle_by_map_id untouched: new runs must not join a finalizing cycle."
  - "Regression test drives _propagate_tournament_verification directly against the real pool with tournament_reward_service omitted, isolating the row-flip + drain-gate assertion."
metrics:
  duration: ~25m
  completed: 2026-06-01
requirements: [UI4-FINALIZING-PROPAGATION]
---

# Phase quick-260601-ui4 Plan 01: Tournament Finalizing-Cycle Verification Propagation Summary

Fixed the edition-rollover hang: verifying a PB tournament completion whose cycle is
`finalizing` now flips `tournaments.completions.status` to `verified`, so
`count_inflight_verifications` drains to 0 and the edition leaves `awaiting_results`.

## What Changed

**Root cause.** `CompletionsService._propagate_tournament_verification` gated on
`_resolve_active_cycle` → `get_active_cycle_by_map_id`, which filters `status='active'`
and therefore excludes `finalizing`. During edition rollover the child cycle is
`finalizing`, so the lookup returned `None`, propagation no-op'd, and the
`tournaments.completions` row stayed `pending`. The drain gate
(`count_inflight_verifications`) counts `pending` rows on cycles
`IN ('active','finalizing')`, so it never reached 0 and the edition hung forever.

**Fix (Task 1, `apps/api/services/completions_service.py`).** Inside the `_do(active_conn)`
closure, replaced the active-only cycle gate with a row-driven resolution that mirrors
`TournamentService._set_verified`:

1. `row = await self._tournament_repo.fetch_tournament_completion(tournament_completion_id, conn=active_conn)` — `None` → safe no-op `(None, [], None)`.
2. `cycle = await self._tournament_repo.fetch_cycle(row["cycle_id"], conn=active_conn)` — `None` → safe no-op.
3. `set_tournament_verified`, `award_participation`, and `return cycle, events, row` unchanged.

The submit-path resolver (`completions_service.py:665` → `_resolve_active_cycle` →
`get_active_cycle_by_map_id`) is **untouched** — a new run still cannot join a finalizing
cycle. `_resolve_active_cycle` is left in place (still the documented submit-path helper).

**Tests (Task 2).**
- `test_tournaments_integration.py`: new `TestFinalizingCyclePropagation` real-DB
  regression. Reuses `_seed_awaiting_edition_for_service(with_pending=True)` to seed an
  `awaiting_results` edition + `finalizing` cycle + a `pending` PB completion, asserts the
  drain gate is `>= 1` before, drives `_propagate_tournament_verification` against the real
  pool, then asserts the row is `status='verified'` AND
  `count_inflight_verifications(edition_id) == 0`.
- `test_tournament_verification.py`: updated `test_pb_path_verify_propagates_to_both_rows`
  and `test_pb_path_verify_idempotent_award_via_ledger` to stub
  `fetch_tournament_completion` + `fetch_cycle` (`status='finalizing'`) instead of
  `get_active_cycle_by_map_id`; added `get_active_cycle_by_map_id.assert_not_awaited()`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Aligned `test_completions_service.py` verify side-effect tests with the new resolution path**
- **Found during:** Task 2 (true full-suite check, `-n 4 --no-testmon`).
- **Issue:** `TestVerifyCompletionTournamentSideEffect::test_verify_on_non_cycle_map_no_side_effect`
  failed (`set_tournament_verified` awaited once, expected zero) — it drove the no-op via
  `get_active_cycle_by_map_id.return_value = None`, which propagation no longer calls.
  `test_verify_propagates_to_linked_tournament_row` passed by luck (unprogrammed AsyncMocks
  returned truthy) but had stale stubs.
- **Fix:** no-op test now stubs `fetch_tournament_completion.return_value = None`; the
  propagation test stubs `fetch_tournament_completion` + `fetch_cycle` (`finalizing`); both
  assert `get_active_cycle_by_map_id.assert_not_awaited()`. Test-only change, directly
  caused by the Task 1 contract move (plan files_modified did not list this file, but the
  breakage is a direct consequence of the in-scope fix).
- **Files modified:** `apps/api/tests/services/test_completions_service.py`
- **Commit:** `424241f`

This file was not in the plan's `files_modified`, but the change is strictly a test-stub
alignment with the new propagation contract — no production behavior beyond the Task 1 fix.

## Verification

**Regression test command + result (the load-bearing proof):**

```
cd apps/api && uv run pytest tests/integration/test_tournaments_integration.py \
  -k "Finalizing or Propagation or inflight" -p no:xdist -q
# -> 1 passed, 51 deselected
```

`TestFinalizingCyclePropagation::test_finalizing_pb_verify_flips_row_and_drains_gate`
asserts the row flips to `status='verified'` AND
`count_inflight_verifications(edition_id) == 0` after the verify.

**Other checks:**
- `uv run pytest tests/services/test_tournament_verification.py --no-testmon -p no:xdist -q` → 16 passed.
- `grep -c "get_active_cycle_by_map_id" apps/api/services/completions_service.py` → 2 (submit-path call site preserved).
- `grep -n 'fetch_cycle(row\["cycle_id"\]' apps/api/services/completions_service.py` → line 1126 (key_link satisfied).
- `just lint-api` → ruff format/check + basedpyright all clean.
- **True full suite** (`cd apps/api && uv run pytest -n 4 --no-testmon -q`) → **1840 passed / 2 skipped / 2 xfailed / 0 failures** (up from 1839; +1 new regression test). No new regressions; known flakes did not surface.

## Commits

- `e3f8731` — test (RED): pin propagation to completion's own cycle_id (unit tests).
- `527a7ad` — fix (GREEN): propagate tournament verify via completion's cycle_id.
- `4841078` — test: real-DB regression for finalizing-cycle drain gate.
- `424241f` — test: align verify side-effect tests with cycle_id propagation.

## Known Stubs

None.

## TDD Gate Compliance

Task 1 followed RED → GREEN: `e3f8731` (`test(...)`, failing unit tests) precedes
`527a7ad` (`fix(...)`, implementation). No REFACTOR commit needed.

## Self-Check: PASSED

All created/modified files exist on disk; all four task commits
(`e3f8731`, `527a7ad`, `4841078`, `424241f`) are present in git history.
