---
phase: 06-submission-flow-leaderboard
verified: 2026-05-30T01:59:50Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Register `domain_tournaments` pytest marker in apps/api/pyproject.toml and confirm `just test-api` collects and passes all tournament tests"
    expected: "All 63 tournament tests run (not deselected) in the default `just test-api` run. The marker `domain_tournaments: Tournament domain tests` should appear alongside the other domain markers."
    why_human: "testmon deselects all tests whose coverage DB has no data yet. With no source file changes, testmon marks 0 changed files and 63 tournament tests are skipped. The tests pass when forced with `-m domain_tournaments`, but the unregistered marker means `just test-api` silently skips them. Requires a human to add the marker to pyproject.toml and re-run the full suite to confirm it integrates cleanly."
---

# Phase 6: Submission Flow & Leaderboard Verification Report

**Phase Goal:** Players can submit tournament completions and view per-cycle leaderboards, with tournament times that beat personal bests automatically written to core completions
**Verified:** 2026-05-30T01:59:50Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A player can submit a tournament completion for an active cycle's map, stored in `tournaments.completions` with per-cycle speed enforcement | VERIFIED | `submit_completion` in `tournament_service.py:468` runs in a single transaction: fetches cycle, validates active status, checks existing best via `fetch_user_completion`, inserts via `create_tournament_completion`. Integration test `test_submit_returns_201` PASSES. |
| 2 | Submissions are ranked by tier-then-time: fully verified completions always outrank partial, and within the same tier fastest time wins | VERIFIED | `fetch_leaderboard` SQL (Phase 3) uses `RANK() OVER (ORDER BY tc.verified DESC, tc.time ASC)` — tier-then-time ordering. `get_leaderboard` service method (`tournament_service.py:533`) converts rows to `TournamentLeaderboardEntryResponse`. Integration test `test_leaderboard_returns_200` confirms ranked entries are returned. |
| 3 | When a tournament submission is strictly faster than the player's existing best in `core.completions`, a cross-write occurs with a `tournament_completion_id` link | VERIFIED | `submit_completion` calls `cross_write_to_core` (`tournament_service.py:519`) within the same transaction. Integration test `test_cross_write_sets_fk` PASSES: queries `core.completions` directly and asserts `tournament_completion_id IS NOT NULL` and equals the returned tournament completion ID. |
| 4 | A per-cycle leaderboard endpoint returns ranked standings for a given cycle | VERIFIED | `GET /tournaments/cycles/{cycle_id}/leaderboard` exists in `routes/v3/tournaments.py:465` with `tournaments:read` scope. Integration tests `TestLeaderboardEndpoint` (2 tests) PASS. |
| 5 | A tournament history/archive endpoint returns past cycles with their results and standings | VERIFIED | `GET /tournaments/cycles` exists at `routes/v3/tournaments.py:486` with optional `status`, `category_id`, `limit`, `offset` parameters. Returns `TournamentCycleListResponse` with `total` count and `cycles` list including winner info. Integration tests `TestCycleListingEndpoint` (3 tests) PASS. |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `apps/api/services/exceptions/tournaments.py` | SlowerTimeError and MapMismatchError domain exceptions | VERIFIED | `SlowerTimeError(current_best, submitted_time)` at line 132; `MapMismatchError(cycle_id, expected_map_id, submitted_map_id)` at line 75. Both extend `TournamentsError`. |
| `libs/sdk/src/genjishimada_sdk/tournaments.py` | TournamentCycleWithWinnerResponse and TournamentCycleListResponse structs | VERIFIED | `TournamentCycleWithWinnerResponse` at line 233 with all 12 fields; `TournamentCycleListResponse` at line 265 with `total: int` and `cycles: list[TournamentCycleWithWinnerResponse]`. Both in `__all__`. |
| `apps/api/repository/tournaments_repository.py` | fetch_cycles method with optional filters and winner JOIN | VERIFIED | `fetch_cycles` at line 442 with `status: str | None`, `category_id: int | None`, `limit: int`, `offset: int`. Dynamic WHERE clause with conditions list. LEFT JOIN LATERAL with DISTINCT ON for winner info. Returns `tuple[int, list[dict]]`. |
| `apps/api/services/tournament_service.py` | submit_completion, get_leaderboard, list_cycles methods | VERIFIED | `submit_completion` at line 468; `get_leaderboard` at line 533; `list_cycles` at line 545. All three methods fully implemented. |
| `apps/api/routes/v3/tournaments.py` | 3 new endpoint handlers | VERIFIED | POST `/cycles/{cycle_id:int}/submit` at line 422; GET `/cycles/{cycle_id:int}/leaderboard` at line 465; GET `/cycles` at line 486. |
| `apps/api/tests/services/test_tournament_service.py` | Unit tests for submit_completion, get_leaderboard, list_cycles | VERIFIED | TestSubmitCompletion (6 tests), TestGetLeaderboard (2 tests), TestListCycles (2 tests). All 24 tests PASS. |
| `apps/api/tests/integration/test_tournaments_integration.py` | Integration tests for submission, leaderboard, and cycle listing | VERIFIED | TestSubmitCompletionEndpoint (5 tests including test_cross_write_sets_fk), TestLeaderboardEndpoint (2 tests), TestCycleListingEndpoint (3 tests). All 39 integration tests PASS. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `tournament_service.py` | `tournaments_repository.py` | `self._tournament_repo.(fetch_cycle|fetch_user_completion|create_tournament_completion|cross_write_to_core|fetch_leaderboard|fetch_cycles)` | VERIFIED | All 6 repo calls present in service methods. Transaction wraps all submission calls at lines 491–527. |
| `tournament_service.py` | `services/exceptions/tournaments.py` | `raise CycleNotFoundError / CycleNotActiveError / SlowerTimeError` | VERIFIED | Lines 497, 499, 507 in submit_completion. All three imports confirmed in service file import block lines 29–40. |
| `tournament_service.py` | `genjishimada_sdk/tournaments.py` | `msgspec.convert(...)` | VERIFIED | `msgspec.convert(row, TournamentCompletionResponse)` at line 531; list comprehension with `TournamentLeaderboardEntryResponse` at line 543; `TournamentCycleListResponse(...)` wrapper at lines 570–573. |
| `routes/v3/tournaments.py` | `tournament_service.py` | `tournament_service.(submit_completion|get_leaderboard|list_cycles)` | VERIFIED | All three delegations present at lines 448, 484, 511–516. |
| `routes/v3/tournaments.py` | `services/exceptions/tournaments.py` | `except (CycleNotFoundError|CycleNotActiveError|SlowerTimeError)` | VERIFIED | Lines 449, 454, 459 in submit_completion endpoint. All three imported at lines 38–44. |
| `tests/integration/test_tournaments_integration.py` | `routes/v3/tournaments.py` | `test_client.(post|get).*cycles` | VERIFIED | All 10 new integration test methods use test_client.post/get to `/api/v3/tournaments/cycles/...`. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|-------------------|--------|
| `tournament_service.py:submit_completion` | `row` (tournament completion dict) | `create_tournament_completion` SQL INSERT RETURNING in repository | Yes — real asyncpg INSERT with RETURNING id | FLOWING |
| `tournament_service.py:get_leaderboard` | `rows` (list of ranked dicts) | `fetch_leaderboard` SQL with RANK() OVER window function | Yes — real DB query with DISTINCT ON + RANK() | FLOWING |
| `tournament_service.py:list_cycles` | `total, rows` | `fetch_cycles` SQL with COUNT(*) + SELECT with JOINs | Yes — real DB queries with dynamic WHERE + LEFT JOIN LATERAL | FLOWING |
| `routes/v3/tournaments.py:submit_completion` | return value | `tournament_service.submit_completion(cycle_id, data)` | Yes — service returns msgspec-converted TournamentCompletionResponse | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Service unit tests (all 24 including 10 Phase 6 tests) | `uv run --directory apps/api pytest tests/services/test_tournament_service.py -v -m "domain_tournaments"` | 24 passed in 0.18s | PASS |
| Integration tests (all 39 including 10 Phase 6 tests) | `uv run --directory apps/api pytest tests/integration/test_tournaments_integration.py -v -m "domain_tournaments and integration"` | 39 passed in 16.90s | PASS |
| SUB-04 cross-write FK test | `test_cross_write_sets_fk` within integration run | PASSED — asserts `tournament_completion_id IS NOT NULL` and equals response `id` | PASS |

### Probe Execution

No probes declared or applicable for this phase.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|---------|
| SUB-01 | 06-01, 06-02 | Tournament completion submission with tier-then-time ranking | SATISFIED | `submit_completion` inserts to `tournaments.completions`; leaderboard SQL uses `RANK() OVER (ORDER BY tc.verified DESC, tc.time ASC)` |
| SUB-02 | 06-01, 06-02 | Separate tournaments.completions table with per-cycle speed enforcement | SATISFIED | Service checks `fetch_user_completion` and raises `SlowerTimeError` when `data.time >= existing["time"]`. Equal time rejected. |
| SUB-03 | 06-01, 06-02 | Cross-write to core.completions only when tournament time is strictly faster | SATISFIED | `cross_write_to_core` CTE in repository uses `$4 < cb.best_time` guard. Called unconditionally from service within same transaction — CTE handles the strictly-faster check. |
| SUB-04 | 06-01, 06-02 | tournament_completion_id FK on core.completions for metadata linking | SATISFIED | `test_cross_write_sets_fk` PASSES: queries `core.completions` and asserts `tournament_completion_id` IS NOT NULL and equals the returned tournament completion ID. |
| SUB-05 | 06-01, 06-02 | Per-cycle tournament leaderboard endpoint | SATISFIED | `GET /tournaments/cycles/{cycle_id}/leaderboard` returns `list[TournamentLeaderboardEntryResponse]` with `tournaments:read` scope. Verified by 2 integration tests. |
| SUB-06 | 06-01, 06-02 | Tournament history/archive endpoint with past cycles and results | SATISFIED | `GET /tournaments/cycles` returns `TournamentCycleListResponse` with pagination and optional `status`/`category_id` filters. Each cycle entry includes rank-1 winner info. Verified by 3 integration tests including status filter test. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `apps/api/pyproject.toml` | (markers section) | `domain_tournaments` marker used in test files but NOT registered in pyproject.toml | WARNING | testmon deselects all 63 tournament tests in standard `just test-api` run because testmon has no coverage data for new tests. Tests pass when forced with `-m "domain_tournaments"`. The marker is pre-existing from Phase 5 (same pattern for `test_tournament_service.py`). |

No TBD/FIXME/XXX debt markers found in any phase-modified files. No stub returns (empty list/null) in production code paths. No placeholder implementations. No RabbitMQ publishing (correct per D-08 decision).

### Human Verification Required

### 1. Register `domain_tournaments` pytest marker

**Test:** Add `"domain_tournaments: Tournament domain tests"` to the `markers` list in `apps/api/pyproject.toml`, then run `just test-api` and confirm tournament tests are collected and pass.

**Expected:** `just test-api` collects and runs all tournament tests (no deselection). The test suite remains green.

**Why human:** testmon's coverage tracking deselects new tests until they have been run against the coverage database. The `domain_tournaments` marker is also unregistered in pyproject.toml — while this produces only a warning (not an error), the combination means the standard CI run silently skips all 63 tournament tests. A human needs to add the marker registration and run `just test-api` to confirm the full suite stays green.

---

## Gaps Summary

No functional gaps were found. All 5 ROADMAP success criteria are verified. All 6 SUB requirements are satisfied. All declared must-have truths, artifacts, and key links are verified and substantive.

The single human verification item is a pytest marker registration that does not affect the correctness of the implementation but prevents tournament tests from running in the standard CI workflow without explicit marker selection.

---

_Verified: 2026-05-30T01:59:50Z_
_Verifier: Claude (gsd-verifier)_
