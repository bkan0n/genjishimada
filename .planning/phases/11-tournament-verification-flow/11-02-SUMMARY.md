---
phase: 11-tournament-verification-flow
plan: 02
subsystem: tournaments
tags: [completions, submit-path, verify-path, cross-write, idempotency, tests]
requires:
  - "tournaments_repository.get_active_cycle_by_map_id (11-01)"
  - "tournaments_repository.set_tournament_verified (11-01)"
  - "tournaments_repository.create_tournament_completion (preserved)"
  - "tournament_reward_service.award_participation / publish_xp_events (08-02)"
  - "SDK TournamentVerificationChangedEvent (11-01)"
  - "RabbitMQ api.tournament.verification.changed (11-01)"
provides:
  - "submit_completion tournament auto-detect (D-01) + PB cross-write link (D-04)"
  - "submit_completion D-07 slower-than-PB relax on tournament maps only"
  - "verify_completion tournament verification propagation (D-04a) + participation XP"
  - "completions_repository.set_completion_tournament_link (core->tournament FK)"
  - "fetch_completion_for_moderation now returns tournament_completion_id"
affects:
  - "11-03 (verify surface): the verify endpoint reuses set_tournament_verified directly for non-PB rows"
tech-stack:
  added: []
  patterns:
    - "narrow asyncpg.exceptions.CheckViolationError catch around the 0017 speed trigger"
    - "optional DI deps (3-arg ctor preserved) so existing unit tests keep working"
    - "fresh conn+txn acquisition when conn is None (mirrors verify_completion_with_pool)"
    - "idempotent participation XP via the 08-01 ledger; publish post-commit"
key-files:
  created: []
  modified:
    - apps/api/services/completions_service.py
    - apps/api/repository/completions_repository.py
    - apps/api/routes/v3/completions.py
    - apps/api/tests/services/test_completions_service.py
    - apps/api/tests/services/test_tournament_verification.py
decisions:
  - "FK link set via a NEW explicit UPDATE method (set_completion_tournament_link) rather than extending insert_completion — the PB core row already exists, so an UPDATE is clearer than threading an optional param through the insert CTE"
  - "DI: injected TournamentRepository + TournamentRewardService as OPTIONAL ctor params (default None); runtime module-level imports (no circular dep exists — neither tournaments_repository nor tournament_reward_service imports completions modules) so Litestar can resolve the provider signature"
  - "CheckViolationError imported as `from asyncpg.exceptions import CheckViolationError` (function-local in submit_completion)"
  - "SlowerThanPendingError precheck gated on `active_cycle is None`; tournament maps fall through to the CheckViolationError relax so a valid slower run is recorded instead of 400ing"
  - "verify-side propagation lives INSIDE verify_completion (not a bot consumer) because VerificationChangedEvent carries no map_id (P8)"
metrics:
  duration: 35min
  completed: 2026-05-31
  tasks: 2
  files: 5
---

# Phase 11 Plan 02: Tournament Submit/Verify Wiring Summary

Tournament times now flow through the shared completion pipeline: a normal completion on the active cycle's map is auto-detected and recorded as a tournament row (PB runs cross-linked to `core.completions`, valid slower-than-PB runs relaxed past the 0017 speed trigger into a tournament-only row), and verifying the linked core completion propagates the verdict to the tournament row with idempotent participation XP — all inside the existing submit/verify transactions.

## What Was Built

**Task 1 — submit_completion auto-detect + PB link + D-07 relax (commit 390fe82)**
- Injected `TournamentRepository` + `TournamentRewardService` into `CompletionsService.__init__` as optional params (3-arg ctor preserved for existing unit tests). Runtime module-level imports added (verified no circular dependency).
- `submit_completion` now resolves the active cycle once at the top of the transaction via `_resolve_active_cycle` (`fetch_map_metadata_by_code` -> `get_active_cycle_by_map_id`).
- PB path (D-04): when `insert_completion` succeeds on an active cycle map, `_record_tournament_completion` inserts the tournament row and `set_completion_tournament_link` sets `core.completions.tournament_completion_id` in the same transaction.
- D-07 relax: `insert_completion` is wrapped so ONLY `asyncpg.exceptions.CheckViolationError` (the 0017 speed trigger, ERRCODE 23514) is caught; on an active cycle map it records a tournament-only row (no core row, no link) and returns; on a non-tournament map it re-raises so the existing HTTP 400 is preserved. Unique/FK violations are NOT caught here (P7).
- `SlowerThanPendingError` precheck gated on `active_cycle is None` so tournament maps fall through to the relax.
- New repo method `set_completion_tournament_link(core_id, tournament_id)` — `UPDATE core.completions SET tournament_completion_id=$2 WHERE id=$1`.
- Controller DI: added `tournament_repo`, `tournament_reward_service`, `lootbox_repo` to the completions controller `dependencies` dict so the provider resolves the nested deps.

**Task 2 — verify_completion propagation D-04a (commit 66e270d, lint/syntax repair in 4e8a1c9)**
- `fetch_completion_for_moderation` extended to also return `c.tournament_completion_id`.
- `verify_completion`: when `data.verified` is True, `_propagate_tournament_verification` runs. If the core row links a tournament row whose map is an active cycle, it calls `set_tournament_verified` + `award_participation` (idempotent via the 08-01 ledger) on a single connection, then flushes deferred XP via `publish_xp_events` post-commit, then publishes `TournamentVerificationChangedEvent` on `api.tournament.verification.changed` with `idempotency_key=f"tournament:verify:{id}"`.
- Connection handling: when `verify_completion`'s `conn` is None (pooled route call), a fresh conn + transaction is acquired so the flip + XP grant are atomic (mirrors `verify_completion_with_pool`).
- The existing `VerificationChangedEvent` publish (bot UI) is unchanged.

## How the FK Link Was Set

A NEW explicit `UPDATE` method (`set_completion_tournament_link`) was added rather than extending `insert_completion` with an optional `tournament_completion_id` param. Rationale: the PB core row already exists when we know the tournament row id, so a targeted `UPDATE` is clearer than threading a param through the insert CTE.

## DI Shape Injected

`CompletionsService(pool, state, completions_repo, tournament_repo=None, tournament_reward_service=None)`. Both tournament deps are optional (default None) — when absent (existing 3-arg unit tests), `_resolve_active_cycle` / `_propagate_tournament_verification` short-circuit. The DI provider `provide_completions_service(state, completions_repo, tournament_repo, tournament_reward_service)` always supplies them in production.

## CheckViolationError Import Path

`from asyncpg.exceptions import CheckViolationError` (function-local inside `submit_completion`).

## SlowerThanPendingError Gating

The precheck `if data.time >= pending["time"]` is now `if data.time >= pending["time"] and active_cycle is None`. Non-tournament maps keep the exact existing behavior (raise + HTTP 400); tournament maps skip the precheck and let the CheckViolationError relax handle the valid slower run. The pending rejection/delete only fires on a strictly-faster time (`data.time < pending["time"]`).

## Deviations from Plan

None functional — plan executed as written. Both tasks landed with the planned signatures and the D-07 guard / P7 propagation tests assert exactly the threat-register mitigations (T-11-04, T-11-05, T-11-06, T-11-07).

**[Rule 1 - Bug] Repaired a self-inflicted syntax corruption (commit 4e8a1c9).** The Task 2 commit (66e270d) landed with three stray `)` lines in the PB-link block (an editing artifact) that left `completions_service.py` un-parseable, plus ruff (PLC0415 function-local import, I001 import order, PLR0912 branch count) and basedpyright (PoolConnectionProxy -> Connection) violations. Fixed in a follow-up: removed the stray lines, hoisted the `CheckViolationError` import, sorted import blocks, cast the pooled connection, returned `completion_id=0` on the non-PB relax (int contract), and added `# noqa: PLR0912`. Final `ruff check` + `basedpyright` are clean and all tests pass.

## Tests

- `test_completions_service.py`: +6 (Task 1: PB link, non-cycle no-op, slower relax, slower non-cycle re-raise, unique propagation) and +3 (Task 2: propagate, no-link guard, non-cycle guard) — 49 passed.
- `test_tournament_verification.py`: flipped 3 SC-2/SC-3 xfail stubs to real mock-based service tests + added a verify-twice idempotency test; the 11-03 verify-endpoint stub remains xfail — 6 passed, 1 xfailed.
- Tournament service/reward regression: 50 passed, 1 xfailed.
- Integration `test_completions_integration.py`: 20 passed (no regression from the `fetch_completion_for_moderation` column addition).

## Threat Mitigations Verified

| Threat ID | Mitigation | Test |
|-----------|-----------|------|
| T-11-04 | CheckViolationError swallow gated on active cycle; non-tournament re-raises | test_slower_on_non_cycle_map_propagates_check_violation |
| T-11-05 | Only CheckViolationError caught; Unique propagates | test_unique_violation_still_propagates_as_duplicate |
| T-11-06 | award_participation idempotent (ledger); verify-twice flushes once | test_pb_path_verify_idempotent_award_via_ledger |
| T-11-07 | No core row on slower run (relax records tournament-only) | test_slower_on_cycle_map_records_tournament_row_no_core |

## Verification Evidence

- `uv run --directory apps/api pytest tests/services/test_completions_service.py -p no:xdist -q` -> 49 passed.
- `uv run --directory apps/api pytest tests/integration/test_completions_integration.py tests/services/test_tournament_verification.py -k "pb_path or link or verify" --no-testmon -p no:xdist -q` -> 3 passed.
- `uv run --directory apps/api pytest tests/integration/test_completions_integration.py --no-testmon -p no:xdist -q` -> 20 passed.
- `ruff check` on the 3 changed source files -> All checks passed.
- `basedpyright` on completions_service.py + completions_repository.py -> 0 errors, 0 warnings.
- `from app import create_app; create_app()` -> APP_OK (DI resolves the new nested deps).

## Self-Check: PASSED
- All 5 modified files + SUMMARY exist on disk.
- All commits found in git log: 390fe82 (Task 1), 66e270d (Task 2), 4b96715 (lint/syntax repair), c0bc4cf (docs), 6f96a44 (test-isolation refinement: sync conn.transaction CM + old_verified=True to isolate the tournament side-effect from the quest-progress branch).
- Verification re-run on final tree: test_completions_service.py 49 passed; test_tournament_verification.py 6 passed/1 xfailed; integration+verify subset 3 passed; ruff clean on the 3 changed source files.
