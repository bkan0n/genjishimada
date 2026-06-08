---
phase: 11-tournament-verification-flow
verified: 2026-05-31T23:55:00Z
status: passed
score: 6/6 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 5/6
  gaps_closed:
    - "TestVerifyCompletionTournamentSideEffect::test_verify_propagates_to_linked_tournament_row and test_verify_on_non_cycle_map_no_side_effect now PASS — mocker.patch.object(service, '_update_quest_progress_for_completion') stubs the quest-progress branch, letting both tests reach their tournament-propagation assertions"
    - "CR-01: _record_tournament_completion now wraps create_tournament_completion in try/except translating UniqueConstraintViolationError -> DuplicateCompletionError and ForeignKeyViolationError -> CompletionNotFoundError/MapNotFoundError; both call sites (non-PB line 687 and PB line 704) are protected; two new regression tests pass"
  gaps_remaining: []
  regressions: []
---

# Phase 11: Tournament Verification Flow — Verification Report

**Phase Goal:** Tournament times are earned through the same verification pipeline as normal completions — the verification-skipping bypass is removed — and verified tournament-relevant runs (including valid runs slower than a player's all-time PB) reach the tournament leaderboard via auto-detection on normal submission.
**Verified:** 2026-05-31T23:55:00Z
**Status:** passed
**Re-verification:** Yes — after gap closure (commit 9b36dbe + 749ccc6 + c0bc4cf + 3727a7f)

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A normal verified completion on an active cycle's map appears on that cycle's leaderboard with no separate tournament submission step (SC-1) | VERIFIED | `submit_completion` calls `_resolve_active_cycle` -> `get_active_cycle_by_map_id` -> `_record_tournament_completion` in the same transaction; `GET /cycles/{id}/leaderboard` wired to `fetch_leaderboard`; integration test `test_normal_completion_on_cycle_map_writes_unverified_tournament_row` passes |
| 2 | A valid tournament run slower than the player's all-time PB still gets verified (OCR or mod review) and is recorded as their tournament time, kept only if fastest (SC-2) | VERIFIED | `CheckViolationError` from 0017 speed trigger caught only on active cycle maps; tournament row created with no core row; dispatch routes no-video -> `tournament.ocr.requested` and video -> `api.tournament.completion.created`; `fetch_leaderboard` uses `DISTINCT ON (user_id) ORDER BY verified DESC, time ASC`; unit tests `test_non_pb_path_submission_creates_tournament_row_without_core_row`, `test_tournament_ocr_match_calls_tournament_verify`, `test_verify_tournament_completion_flips_row_and_awards_xp` all pass |
| 3 | A PB run on the active tournament map is verified exactly once and marks both core and tournament records verified (SC-3) | VERIFIED | `verify_completion` calls `_propagate_tournament_verification` which calls `set_tournament_verified` + `award_participation`; `test_pb_path_verify_propagates_to_both_rows` PASSES; `TestVerifyCompletionTournamentSideEffect::test_verify_propagates_to_linked_tournament_row` and `test_verify_on_non_cycle_map_no_side_effect` now PASS after stubbing `_update_quest_progress_for_completion` (3 of 3 tests in the class pass) |
| 4 | The bypass endpoint POST /api/v3/tournaments/cycles/{cycle_id}/submit no longer exists and no code path writes a tournament completion without verification (SC-4) | VERIFIED | `grep -rn "cycles/.*/submit" apps/api/routes/` returns nothing; `TournamentService.submit_completion` deleted; `TournamentCompletionCreateRequest` removed from SDK; `TestSubmitBypassRemoved` 4 tests pass; seed script repointed to `POST /api/v3/completions/` |
| 5 | Participation XP and a verified leaderboard standing are granted only on verification; unverified runs rank below verified ones (SC-5) | VERIFIED | `award_participation` only called in `_propagate_tournament_verification` and `_set_verified`, never in submit path; leaderboard SQL `ORDER BY bpu.verified DESC, bpu.time ASC`; `test_submit_then_verify_grants_participation_once` passes |
| 6 | The core.completions "latest = fastest" invariant is preserved — no slower-than-PB tournament rows are inserted into core.completions (SC-6) | VERIFIED | 0017 speed trigger raises `CheckViolationError` caught ONLY on active cycle maps; tournament-only row recorded with no core row; non-tournament maps re-raise; `test_slower_on_cycle_map_records_tournament_row_no_core` and `test_slower_on_non_cycle_map_propagates_check_violation` both pass |

**Score:** 6/6 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `apps/api/repository/tournaments_repository.py` | `get_active_cycle_by_map_id`, `set_tournament_verified`, `fetch_tournament_completion` | VERIFIED | All three methods exist; `create_tournament_completion` (L917) and `cross_write_to_core` (L962) preserved |
| `libs/sdk/src/genjishimada_sdk/tournaments.py` | `TournamentVerificationChangedEvent` + extended `TournamentCompletionCreatedEvent` | VERIFIED | Both classes present; `TournamentVerificationChangedEvent` in `__all__`; structs construct correctly |
| `infra/rabbitmq/definitions.json` | `api.tournament.completion.created` + `api.tournament.verification.changed` + their DLQs | VERIFIED | All four queue names present; per-queue DLQ isolation |
| `apps/api/events/completions.py` | `tournament.ocr.requested` listener | VERIFIED | `@listener("tournament.ocr.requested") handle_tournament_ocr_verification` at line 43 |
| `apps/api/services/completions_service.py` | auto-detect + D-07 relax + D-04a propagation + OCR variant + CR-01 guard | VERIFIED | `_resolve_active_cycle`, `_record_tournament_completion` (with CR-01 try/except at lines 815-830), `_dispatch_non_pb_tournament`, `_propagate_tournament_verification`, `attempt_tournament_auto_verify_async` all present and correct |
| `apps/api/services/tournament_service.py` | `verify_tournament_completion` + `reject_tournament_completion` | VERIFIED | Both methods at lines 496, 536; bypass `submit_completion` removed |
| `apps/api/routes/v3/tournaments.py` | PATCH `/tournaments/completions/{id}/verify\|reject` scoped `tournaments:verify`; NO submit route | VERIFIED | Both PATCH handlers at lines 461-519; `grep -rn "cycles/.*/submit" apps/api/routes/` returns nothing |
| `apps/bot/extensions/tournaments.py` | `api.tournament.completion.created` consumer + Accept/Reject view | VERIFIED | `TournamentVerificationAcceptButton`, `TournamentVerificationRejectButton`, two `@queue_consumer` calls |
| `apps/bot/extensions/api_service.py` | `verify_tournament_completion` + `reject_tournament_completion` | VERIFIED | Both methods at lines 1092, 1109; build `PATCH` routes |
| `scripts/seed-tournament-local.sh` | No bypass submit reference; uses `POST /api/v3/completions/` | VERIFIED | Uses verified completion flow; `grep cycles/.*/submit` returns nothing |
| `apps/api/tests/services/test_completions_service.py` | 3 tests in TestVerifyCompletionTournamentSideEffect | VERIFIED | All 3 tests PASS after Gap 1 fix (mocker.patch.object stubs quest-progress branch) |
| `apps/api/tests/services/test_tournament_verification.py` | CR-01 regression tests | VERIFIED | `test_non_pb_duplicate_tournament_row_raises_duplicate_not_500` and `test_pb_duplicate_tournament_row_raises_duplicate_not_500` both PASS |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `completions_service.py::submit_completion` | `TournamentRepository.get_active_cycle_by_map_id` | `_resolve_active_cycle` at lines 653, 785 | WIRED | Confirmed in code |
| `completions_service.py::verify_completion` | `TournamentRepository.set_tournament_verified` | `_propagate_tournament_verification` at line 1094 | WIRED | Confirmed in code |
| `completions_service.py::verify_completion` | `award_participation` | `_propagate_tournament_verification` at line 1099 | WIRED | Confirmed in code |
| `routes/v3/tournaments.py PATCH verify` | `TournamentService.verify_tournament_completion` | thin delegation at line 483 | WIRED | Confirmed in code |
| `attempt_tournament_auto_verify_async` | `TournamentService.verify_tournament_completion` | seam at line 501/620 | WIRED | OCR on-match calls `self.verify_tournament_completion(tournament_completion_id)` |
| `bot Accept button` | `bot.api.verify_tournament_completion` | callback at line 124 | WIRED | Confirmed; bot never writes DB |
| `_record_tournament_completion` | `UniqueConstraintViolationError` handler | `try/except` inside `_record_tournament_completion` body (lines 815-830) | WIRED | CR-01 fixed: both call sites (non-PB line 687 and PB line 704) delegate to the method which now translates constraint errors into domain exceptions |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `routes/v3/tournaments.py::get_leaderboard` | leaderboard rows | `fetch_leaderboard` SQL `DISTINCT ON (user_id) ORDER BY verified DESC, time ASC` | Yes — real `tournaments.completions` query | FLOWING |
| `bot/extensions/tournaments.py TournamentVerificationView` | `TournamentCompletionCreatedEvent` fields | `api.tournament.completion.created` RabbitMQ message | Yes — event carries `completion_id, cycle_id, user_id, time, video, screenshot` | FLOWING |
| `completions_service.py::_propagate_tournament_verification` | `verified_row` | `set_tournament_verified` returns `id, cycle_id, user_id, time` | Yes | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| SC-3: PB verify propagates to tournament row | `pytest test_tournament_verification.py::test_pb_path_verify_propagates_to_both_rows` | PASS | PASS |
| SC-3 (first-verify, old_verified=False): propagation to linked row | `pytest test_completions_service.py::TestVerifyCompletionTournamentSideEffect::test_verify_propagates_to_linked_tournament_row` | PASS (was FAIL) | PASS |
| SC-3 (first-verify, non-cycle map): no side-effect | `pytest test_completions_service.py::TestVerifyCompletionTournamentSideEffect::test_verify_on_non_cycle_map_no_side_effect` | PASS (was FAIL) | PASS |
| SC-2: non-PB tournament row verifiable | `pytest test_tournament_verification.py::test_verify_tournament_completion_flips_row_and_awards_xp` | PASS | PASS |
| SC-4: bypass endpoint absent | `pytest tests/services/test_tournament_service.py::TestSubmitBypassRemoved` | 4 PASS | PASS |
| SC-5: XP only on verify, not submit | `pytest tests/integration/test_tournament_rewards.py` | 5 PASS | PASS |
| SC-6: no slower-than-PB to core | `pytest tests/services/test_completions_service.py::TestSubmitTournamentAutoDetect` | 2 PASS | PASS |
| CR-01: non-PB duplicate tournament row raises DuplicateCompletionError | `pytest test_tournament_verification.py::test_non_pb_duplicate_tournament_row_raises_duplicate_not_500` | PASS (new) | PASS |
| CR-01: PB duplicate tournament row raises DuplicateCompletionError | `pytest test_tournament_verification.py::test_pb_duplicate_tournament_row_raises_duplicate_not_500` | PASS (new) | PASS |
| Bot mod-review: Accept/Reject route through API | `pytest tests/bot/test_tournaments_handler.py` | 15 PASS | PASS |

### Probe Execution

Step 7c: SKIPPED (no `scripts/*/tests/probe-*.sh` files; phase does not declare probes in PLAN.md).

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| SUB-01 | 11-01 through 11-05 | Tournament completion submission with tier-then-time ranking (fully verified > partial) | SATISFIED | Leaderboard SQL `ORDER BY verified DESC, time ASC`; verification pipeline routes all tournament completions through OCR or mod review before marking verified; bypass removed |

Note: REQUIREMENTS.md traceability table lists SUB-01 as "Phase 6 / Complete" (the original submission feature). Phase 11 references SUB-01 because it extends the same requirement with the verified pipeline.

### Anti-Patterns Found

The following non-blocking warnings were identified in the initial verification and remain present. They are noted for future maintenance but do NOT block goal achievement.

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `apps/api/services/tournament_service.py` | 605-645 | `_set_verified` publishes `TournamentVerificationChangedEvent` even when `updated is None` (WR-01) | Warning | Bot may post "verified" confirmation for a phantom flip when the row was deleted between precheck and update |
| `apps/bot/extensions/tournaments.py` | 160-179 | Reject button reports success without polling job (WR-02) | Warning | If broker publish fails, moderator sees "Successfully rejected" when the rejection did not take effect |
| `apps/api/services/completions_service.py` | 954-1027, 1104-1106 | Core verify and tournament propagation are on separate connections/transactions (WR-04) | Warning | Process crash between core commit and tournament commit leaves split state (core verified, tournament unverified) |
| `apps/api/repository/tournaments_repository.py` | 962-1041 | `cross_write_to_core` has zero production callers (dead code, WR-03) | Warning | Future maintainer may rewire it, silently bypassing the live submit path speed trigger |
| `apps/api/services/completions_service.py` | 470 | `_ = cycle_id  # reserved` — dead parameter in `attempt_tournament_auto_verify_async` (IN-01) | Info | Harmless today; misleading annotation |
| `apps/api/services/tournament_service.py` | 512-513, 628-630 | Dangling `(CR-02)` cross-reference in docstring (IN-02) | Info | No CR-02 artifact exists in this diff |
| `infra/rabbitmq/definitions.json` | 295-434 | Inconsistent 2-space vs 4-space indentation (IN-03) | Info | Valid JSON; cosmetic only |

### Human Verification Required

None required — all behaviors are verifiable programmatically.

### Gaps Summary

All gaps from the initial verification are closed. No new gaps identified.

**Gap 1 (closed):** `TestVerifyCompletionTournamentSideEffect` — Both previously failing tests now use `mocker.patch.object(service, "_update_quest_progress_for_completion", mocker.AsyncMock())` to isolate the tournament-propagation branch from the quest-progress branch. All 3 tests in the class pass.

**Gap 2 (closed):** CR-01 — `_record_tournament_completion` now wraps `create_tournament_completion` in a try/except block (lines 815-830) that translates `UniqueConstraintViolationError` -> `DuplicateCompletionError` and `ForeignKeyViolationError` -> `CompletionNotFoundError`/`MapNotFoundError`. Both call sites (non-PB at line 687 and PB at line 704) delegate to this method, so constraint races now surface as 409 not 500. Two new regression tests confirm the behavior.

---

_Verified: 2026-05-31T23:55:00Z_
_Verifier: Claude (gsd-verifier)_
