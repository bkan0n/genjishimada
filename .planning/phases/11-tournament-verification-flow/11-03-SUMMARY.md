---
phase: 11-tournament-verification-flow
plan: 03
subsystem: tournaments
tags: [verification, ocr, endpoints, idempotency, participation-xp, tests]
requires:
  - "tournaments_repository.set_tournament_verified (11-01)"
  - "tournaments_repository.create_tournament_completion (preserved)"
  - "tournament_reward_service.award_participation / publish_xp_events (08-02)"
  - "SDK TournamentVerificationChangedEvent + extended TournamentCompletionCreatedEvent (11-01)"
  - "RabbitMQ api.tournament.verification.changed + api.tournament.completion.created (+ DLQs, 11-01)"
  - "events.schemas.TournamentOcrVerificationRequestedEvent (11-01)"
  - "completions_service.submit_completion D-07 relax branch (11-02)"
provides:
  - "TournamentService.verify_tournament_completion / reject_tournament_completion"
  - "PATCH /tournaments/completions/{id}/verify|reject (scope tournaments:verify)"
  - "tournaments_repository.fetch_tournament_completion lookup"
  - "TournamentCompletionNotFoundError (404)"
  - "completions_service.attempt_tournament_auto_verify_async OCR variant + verify_tournament_completion seam"
  - "events/completions.py tournament.ocr.requested listener (auto-discovered)"
  - "submit_completion D-07 non-PB dispatch (no-video -> OCR, video -> mod queue)"
affects:
  - "11-05 (bot mod review): consumes api.tournament.completion.created; calls back PATCH verify|reject"
tech-stack:
  added: []
  patterns:
    - "shared verify/reject body (_set_verified) param-flagged for verified value + award_xp + idempotency key"
    - "fresh conn+txn when conn is None (flip + XP atomic; XP notification flushed post-commit, CR-02)"
    - "OCR variant copies the proven core OCR HTTP block verbatim; only the terminal differs (P4)"
    - "request headers forwarded into the service so X-PYTEST-ENABLED skips the broker in integration"
    - "idempotent participation XP via the 08-01 ledger; award_participation called unconditionally"
key-files:
  created: []
  modified:
    - apps/api/services/tournament_service.py
    - apps/api/services/completions_service.py
    - apps/api/services/exceptions/tournaments.py
    - apps/api/routes/v3/tournaments.py
    - apps/api/events/completions.py
    - apps/api/repository/tournaments_repository.py
    - apps/api/tests/services/test_tournament_verification.py
    - apps/api/tests/integration/test_tournaments_integration.py
decisions:
  - "fetch_tournament_completion WAS added (it was absent) — returns id, cycle_id, user_id, time, verified"
  - "verify and reject share one _set_verified body parameterized by verified/award_xp/idempotency_key; reject sets verified=FALSE (Open-Q1 simplest reject) and grants no XP"
  - "OCR variant on-match terminal calls completions_service.verify_tournament_completion, a thin seam that builds a TournamentService on the pool and delegates — so OCR auto-verify and the bot callback share one verify implementation"
  - "verify/reject service methods accept an optional headers param; the routes forward request.headers so the api.tournament.verification.changed publish honors X-PYTEST-ENABLED in tests (the publish targets a non-IGNORE_IDEMPOTENCY queue, so it would otherwise hit the broker and 500)"
  - "TournamentService/provide imported at module top of completions_service (no circular dep: tournament_service imports nothing from completions)"
metrics:
  duration: 22min
  completed: 2026-05-31
  tasks: 2
  files: 8
---

# Phase 11 Plan 03: Non-PB Tournament Verification Surface Summary

The genuinely new construct of the phase: a slower-than-PB tournament run (recorded by 11-02's D-07 relax with NO core row) now gets its OWN verification. No-video runs OCR-auto-verify against the tournament row; video runs publish to the bot mod-review queue; the bot calls back the new scoped `PATCH /tournaments/completions/{id}/verify|reject` endpoints (the bot never writes the DB). Verifying flips `tournaments.completions.verified` TRUE and auto-enrolls the player with idempotent participation XP (D-02/D-06); rejecting leaves the row unverified with no XP.

## What Was Built

**Task 1 — verify/reject service + scoped endpoints + non-PB dispatch (RED c520d5e, GREEN 49a7d9e)**
- `TournamentRepository.fetch_tournament_completion(id)` — `SELECT id, cycle_id, user_id, time, verified FROM tournaments.completions WHERE id = $1` (it was absent; added).
- `TournamentService.verify_tournament_completion` / `reject_tournament_completion` delegate to a shared `_set_verified(verified, idempotency_key, award_xp)`: fetch the row (404 via `TournamentCompletionNotFoundError` if missing), `set_tournament_verified`, on verify resolve the cycle via `fetch_cycle` and call `award_participation` (idempotent — never branches on already-granted, P5), publish `TournamentVerificationChangedEvent`, flush deferred XP post-commit. When `conn` is None a fresh conn+txn is acquired so the flip + XP are atomic (mirrors `verify_completion_with_pool`).
- `PATCH /tournaments/completions/{tournament_completion_id:int}/verify` and `/reject`, `opt={"required_scopes": {"tournaments:verify"}}`, thin delegation, `TournamentCompletionNotFoundError -> CustomHTTPException 404`. Both forward `request.headers`.
- Non-PB dispatch (`completions_service.submit_completion` D-07 branch): the relax branch now records the tournament row, captures `(tc_id, cycle)`, and after the transaction commits routes via `_dispatch_non_pb_tournament` — no-video emits `tournament.ocr.requested`, video publishes `TournamentCompletionCreatedEvent` on `api.tournament.completion.created` (`idempotency_key=f"tournament:submission:{user_id}:{tc_id}"`).

**Task 2 — OCR variant + listener (GREEN 49a7d9e)**
- `completions_service.attempt_tournament_auto_verify_async` copies the core OCR HTTP block verbatim (hostname switch, `POST /extract`, `msgspec.json.decode(OcrResponse)`, three-way code/time/name match). Terminal differs (P4): on match `verify_tournament_completion(tc_id)` (NOT `verify_completion_with_pool`); on mismatch (and on any exception) `_publish_tournament_mod_review` publishes `TournamentCompletionCreatedEvent` on `api.tournament.completion.created` (NOT `CompletionCreatedEvent`). Idempotency key `f"tournament:submission:{user_id}:{tc_id}"`.
- `completions_service.verify_tournament_completion` is a thin seam that builds a `TournamentService` on the pool (reusing the injected reward service when present) and delegates — so OCR auto-verify and the bot callback share one verify implementation.
- `events/completions.py` `@listener("tournament.ocr.requested") handle_tournament_ocr_verification` dispatches to the OCR variant; auto-discovered by `events/__init__.py` (no manual registration).

## Endpoint Paths + Scope
- `PATCH /api/v3/tournaments/completions/{tournament_completion_id:int}/verify` — scope `tournaments:verify`
- `PATCH /api/v3/tournaments/completions/{tournament_completion_id:int}/reject` — scope `tournaments:verify`

## OCR-Variant On-Match Terminal
`verify_tournament_completion(tournament_completion_id)` (the tournament row's own verification) — NOT `verify_completion_with_pool`. No core completion path is touched (there is no core row for a non-PB run).

## Idempotency Key Shapes
- verify publish: `tournament:verify:{tc_id}` on `api.tournament.verification.changed`
- reject publish: `tournament:reject:{tc_id}` on `api.tournament.verification.changed`
- non-PB video submit + OCR mismatch escalation: `tournament:submission:{user_id}:{tc_id}` on `api.tournament.completion.created`

## fetch_tournament_completion
Added (it was absent). Returns `id, cycle_id, user_id, time, verified`.

## Deviations from Plan

**[Rule 1 - Bug] Fixed a pre-existing test-mock bug in test_tournament_verification.py.** The 11-02 submission tests set `completions_repo.get_suspicious_flags.return_value = []`, but `submit_completion` calls `self._completions_repo.fetch_suspicious_flags` — so the mock never took effect and `test_pb_path_submission_creates_linked_tournament_and_core_rows` failed with a msgspec ValidationError (AsyncMock instead of a list). Corrected both occurrences to `fetch_suspicious_flags`. Found during Task 1 GREEN. Commit 49a7d9e.

## Threat Mitigations Verified

| Threat ID | Mitigation | Test |
|-----------|-----------|------|
| T-11-09 | tournaments:verify scope guard; player cannot self-verify | `test_verify_without_scope_rejected` (401) |
| T-11-10 | award_participation ledger UNIQUE; called unconditionally; verify key `tournament:verify:{tc_id}` | `test_verify_twice_grants_participation_once`, `test_verify_tournament_completion_twice_awards_xp_once` |
| T-11-11 | three-way OCR match reused verbatim; mismatch escalates to mod review | `test_tournament_ocr_mismatch_publishes_tournament_created` |

## Deferred Issues

- `tests/services/test_completions_service.py::TestVerifyCompletionTournamentSideEffect` (`test_verify_propagates_to_linked_tournament_row`, `test_verify_on_non_cycle_map_no_side_effect`) fail on the RED tree BEFORE any 11-03 edit — a `store_repository.py:520` TypeError in the quest-progress mock path, unrelated to the verify surface. Logged in `deferred-items.md`; out of scope for 11-03.
- Pre-existing RUF100 unused-`noqa` on `claim_xp_grant` (tournaments_repository.py:869), carried from 11-01.

## Verification Evidence
- `uv run --directory apps/api pytest tests/services/test_tournament_verification.py tests/integration/test_tournaments_integration.py --no-testmon -p no:xdist -q` -> 59 passed.
- `uv run --directory apps/api pytest tests/services/test_tournament_service.py tests/integration/test_tournament_rewards.py tests/integration/test_completions_integration.py --no-testmon -p no:xdist -q` -> 99 passed (no regression).
- `cd apps/api && uv run ruff check services/completions_service.py services/tournament_service.py routes/v3/tournaments.py events/completions.py` -> All checks passed.
- `cd apps/api && uv run basedpyright services/tournament_service.py services/completions_service.py routes/v3/tournaments.py events/completions.py repository/tournaments_repository.py` -> 0 errors, 0 warnings.
- `from app import create_app; create_app()` -> APP_OK (no circular import; DI resolves).
- Acceptance greps: verify/reject methods present; `tournaments:verify` on both PATCH routes; `attempt_tournament_auto_verify_async` x1; `tournament.ocr.requested` listener present; `fetch_tournament_completion` added.

## Self-Check: PASSED
- All 8 modified files exist on disk.
- Commits found in git log: c520d5e (RED tests), 49a7d9e (GREEN impl).
