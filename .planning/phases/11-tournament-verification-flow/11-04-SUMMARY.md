---
phase: 11-tournament-verification-flow
plan: 04
subsystem: tournaments
tags: [submit-bypass, cleanup, sdk, seed-script, tests, sc-4]
requires:
  - "11-02 submit_completion auto-detect + PB cross-write (the verified PB path that replaces the bypass)"
  - "11-03 verify/reject endpoints + non-PB OCR surface (the verified write path)"
  - "tournaments_repository.cross_write_to_core / create_tournament_completion (preserved, PB-path reuse)"
  - "tournament_reward_service.award_participation / publish_xp_events (preserved, verify-path use)"
  - "tournaments_repository.get_active_cycle_by_map_id (active-only auto-detect lookup)"
provides:
  - "D-05: no code path writes a tournament completion without verification (bypass route + service method removed)"
  - "SC-4 regression coverage: old POST /cycles/{id}/submit 404s; TournamentCompletionCreateRequest not importable"
  - "seed-tournament-local.sh repointed to the verified normal-completion POST"
affects:
  - "11-05 (bot mod review): the bot already calls the verified PATCH verify|reject endpoints; no submit endpoint to consume"
tech-stack:
  added: []
  patterns:
    - "removed-symbol regression tests (hasattr false + ImportError) prove the bypass cannot be re-imported"
    - "auto-detect lookup is status='active' ONLY — finalizing/completed cycles are never recorded as tournament rows"
key-files:
  created: []
  modified:
    - apps/api/routes/v3/tournaments.py
    - apps/api/services/tournament_service.py
    - apps/api/services/exceptions/tournaments.py
    - libs/sdk/src/genjishimada_sdk/tournaments.py
    - scripts/seed-tournament-local.sh
    - apps/api/tests/services/test_tournament_service.py
    - apps/api/tests/integration/test_tournaments_integration.py
    - apps/api/tests/integration/test_tournament_rewards.py
    - apps/api/tests/repository/tournaments/test_cycle_transitions.py
decisions:
  - "TournamentCompletionCreateRequest REMOVED from the SDK (+ __all__ entry): after deleting the bypass route + service method, the only remaining references were tests (which now assert it is NOT importable)"
  - "SlowerTimeError exception REMOVED: zero references remained anywhere in apps/ or libs/ after the bypass deletion (no barrel re-export); the keep-fastest gate it served lived only in the deleted bypass"
  - "Seed script repointed to POST /api/v3/completions/ on the active cycle's map (auto-detect verified pipeline); the script now fetches the cycle's map code from the DB for the usage hint"
  - "Participation-XP regression moved from submit to verify: the rewards integration test now submits a normal completion (unverified, NO xp) then verifies (grants participation once via the ledger)"
  - "TestSubmissionRejection rewritten at the repository tier: instead of asserting the deleted bypass raised CycleNotActiveError, it asserts get_active_cycle_by_map_id returns None for a finalizing cycle (so the auto-detect path writes nothing) and matches an active cycle"
metrics:
  duration: 18min
  completed: 2026-05-31
  tasks: 2
  files: 9
---

# Phase 11 Plan 04: Remove Tournament Submit Bypass Summary

The verification-skipping bypass is gone (D-05): the `POST /api/v3/tournaments/cycles/{cycle_id}/submit` route, the bypass `TournamentService.submit_completion` method (with its XP-on-submit), the now-unused `TournamentCompletionCreateRequest` SDK struct, and the orphaned `SlowerTimeError` exception are all deleted. The only remaining tournament write is the verified pipeline (11-02 auto-detect + 11-03 verify/reject). The PB-path repo helpers (`cross_write_to_core`, `create_tournament_completion`) and the verify-path reward helpers (`award_participation`, `publish_xp_events`) plus the 11-03 `verify_tournament_completion`/`reject_tournament_completion` methods are all preserved. The local seed script and every submit-asserting test now exercise the verified path, with an explicit SC-4 regression proving the old endpoint 404s and the removed symbols are not importable.

## What Was Built

**Task 1 — delete the bypass route + service method; preserve helpers (commit 877a150)**
- Removed the `POST /cycles/{cycle_id:int}/submit` handler (decorator + body + try/except for `CycleNotFoundError`/`CycleNotActiveError`/`SlowerTimeError`) from `routes/v3/tournaments.py`.
- Removed the bypass `submit_completion` method from `tournament_service.py` (fetch_cycle, keep-fastest `SlowerTimeError` gate, `create_tournament_completion` + `cross_write_to_core` + award-participation-on-submit + post-commit `publish_xp_events`).
- Dropped the now-unused imports surfaced by the deletion: route (`TournamentCompletionCreateRequest`, `TournamentCompletionResponse`, `CycleNotActiveError`, `CycleNotFoundError`, `SlowerTimeError`) and service (same set minus the still-used `XpGrantEvent`).
- Verified preserved: repo `cross_write_to_core` + `create_tournament_completion` (grep count 2), reward `award_participation` + `publish_xp_events`, service `verify_tournament_completion` + `reject_tournament_completion`.

**Task 2 — remove unused SDK struct + SlowerTimeError, repoint seed, rewrite tests (commit 5cfcaa8)**
- SDK: removed `TournamentCompletionCreateRequest` (struct + `__all__` entry); kept `TournamentCompletionResponse`, `TournamentCompletionCreatedEvent`, `TournamentVerificationChangedEvent`. Ran `just fix` to re-sync the workspace package.
- Exceptions: removed `SlowerTimeError` (zero references remained anywhere after the bypass deletion).
- Seed script: repointed the usage hint + header comment from the bypass submit to `POST /api/v3/completions/` on the active cycle's map (the auto-detect verified pipeline); the script now reads the cycle's map code from the DB for an accurate hint. `bash -n` clean.
- Tests rewritten across four files (see Test Changes).

## What TournamentCompletionCreateRequest + SlowerTimeError Did (caller evidence)

- **`TournamentCompletionCreateRequest`** — after deleting the bypass route + service method, `grep -rn TournamentCompletionCreateRequest apps/ libs/ scripts/` returned only test references. Those tests were rewritten; the SC-4 regression now asserts the symbol is gone (`not hasattr` + `ImportError`). REMOVED.
- **`SlowerTimeError`** — `grep -rn SlowerTimeError apps/ libs/` (excluding its own `class` line) returned nothing after the bypass deletion. No barrel `__init__` re-export. The keep-fastest gate it served existed only inside the deleted bypass. REMOVED.

## New Seed-Script Flow

`scripts/seed-tournament-local.sh` still creates two categories, rolls + activates a first cycle, then prints a submission hint. The hint changed from:

```
POST /api/v3/tournaments/cycles/{id}/submit  {"user_id":...,"time":...,"screenshot":...}
```

to a NORMAL completion on the cycle's map (auto-detected as a tournament submission by the verified pipeline — there is no submit endpoint):

```
POST /api/v3/completions/  {"code":"<cycle map code>","user_id":...,"time":...,"screenshot":...,"video":null}
```

The script resolves `<cycle map code>` from `tournaments.cycles JOIN core.maps` for the Easy/Medium active cycle.

## Test Changes

- `test_tournament_service.py`: deleted `TestSubmitCompletion` (6 bypass cases) + `TestSubmitParticipationHook` (2 cases); added `TestSubmitBypassRemoved` (4 cases: service has no `submit_completion`, CreateRequest non-importable, PB-path helpers preserved, verify-path methods preserved).
- `test_tournaments_integration.py`: replaced `TestSubmitCompletionEndpoint` (bypass) with `TestSubmitBypassRemoved` (old endpoint 404; normal completion POST on the cycle map records an UNVERIFIED tournament row; cross-write sets the core FK). The leaderboard test seeds a tournament row directly instead of POSTing the bypass.
- `test_tournament_rewards.py`: rewrote `TestParticipationGrant` — submit a normal completion (unverified, asserts 0 grants / 0 XP), then `PATCH .../verify` grants participation exactly once (verify-twice stays at 1 grant / 25 XP via the ledger).
- `test_cycle_transitions.py`: rewrote `TestSubmissionRejection` from a bypass-`submit_completion`-raises-`CycleNotActiveError` assertion to two repository-tier guards: a finalizing cycle yields `get_active_cycle_by_map_id is None` (no auto-detect write) and an active cycle is matched. Dropped the now-unused `TournamentCompletionCreateRequest`/`State`/`CycleNotActiveError`/`TournamentService` imports.

## Threat Mitigations Verified

| Threat ID | Mitigation | Test |
|-----------|-----------|------|
| T-11-14 | Bypass route + service method deleted | `TestSubmitBypassRemoved::test_old_submit_endpoint_returns_404`, `test_service_has_no_submit_completion`, `test_create_request_not_importable` |
| T-11-15 | PB-path helpers + verify methods preserved | `test_pb_path_helpers_preserved`, `test_verify_path_methods_preserved`; acceptance grep count == 2 |
| T-11-16 | Seed script repointed to the verified completion POST | `grep cycles/.*/submit scripts/seed-tournament-local.sh` returns nothing |
| T-11-SC | No package installs in this plan | n/a — no install task |

## Deviations from Plan

None functional — plan executed as written. Both `TournamentCompletionCreateRequest` and `SlowerTimeError` were REMOVED (caller evidence above); the seed script flow is the verified `POST /api/v3/completions/` auto-detect path.

## Deferred Issues

- `tests/services/test_completions_service.py::TestVerifyCompletionTournamentSideEffect` (`test_verify_propagates_to_linked_tournament_row`, `test_verify_on_non_cycle_map_no_side_effect`) fail on a `store_repository.py:520` TypeError in the quest-progress mock path — pre-existing, documented in `deferred-items.md` since 11-03, fails on the tree before this plan's edits, and lives in a test file this plan did not touch. Out of scope.

## Verification Evidence

- `! grep -rn "cycles/.*/submit" apps/api/routes/ scripts/` -> CLEAN.
- `grep -c "async def cross_write_to_core\|async def create_tournament_completion" apps/api/repository/tournaments_repository.py` -> 2.
- `uv run --directory apps/api pytest tests/services/test_tournament_service.py tests/integration/test_tournaments_integration.py tests/integration/test_tournament_rewards.py tests/repository/tournaments/test_cycle_transitions.py --no-testmon -p no:xdist -q` -> 81 passed.
- `uv run --directory apps/api pytest tests/services/test_tournament_verification.py tests/services/test_completions_service.py tests/integration/test_completions_integration.py --no-testmon -p no:xdist -q` -> 125 passed, 2 failed (the documented pre-existing quest-progress failures, untouched files).
- `cd apps/api && uv run ruff check routes/v3/tournaments.py services/tournament_service.py services/exceptions/tournaments.py` -> All checks passed.
- `cd libs/sdk && uv run ruff check src/genjishimada_sdk/tournaments.py` -> All checks passed.
- `cd apps/api && uv run basedpyright routes/v3/tournaments.py services/tournament_service.py services/exceptions/tournaments.py` -> 0 errors, 0 warnings.
- `from app import create_app; create_app()` -> APP_OK.
- `bash -n scripts/seed-tournament-local.sh` -> SYNTAX OK.

## Self-Check: PASSED
- All 9 modified files exist on disk.
- Commits found in git log: 877a150 (Task 1), 5cfcaa8 (Task 2).
