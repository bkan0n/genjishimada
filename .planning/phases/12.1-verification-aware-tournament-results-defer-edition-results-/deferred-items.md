# Phase 12.1 — Deferred Items

Items discovered during execution that are **out of scope** for the plan that
found them (per the executor SCOPE BOUNDARY rule) and are owned by a downstream
plan in this phase. These are deferred-by-design transitional breakages caused
by the foundational migration 0025 (Plan 12.1-01), which intentionally makes
`tournaments.completions.verified` a generated column and makes
`process_edition_transitions()` timing-only — BEFORE the downstream app-code
rewrites that follow.

## Discovered in Plan 12.1-01 (migration 0025)

Migration 0025 (tri-state `status` + generated `verified` + timing-only cron) is
the bedrock the rest of the phase stands on. By design it breaks existing
app code/tests that (a) write the now-generated `verified` column directly, or
(b) assert the OLD cron behavior (snapshot leaderboard, write outbox row, flip
edition → `completed`). Plan 12.1-01's `files_modified` is intentionally limited
to the migration + `test_tournaments_schema.py`; the app-code rewrites are
separate downstream plans.

### Owned by Plan 12.1-03 (repository + service: verify/reject write the tri-state)

`set_tournament_verified` (`tournaments_repository.py:1517`) still does
`SET verified = $2`, which now raises
`asyncpg.exceptions.GeneratedAlwaysError: cannot insert a non-DEFAULT value into
column "verified"`. It must be rewritten to `SET status = $2` (Pitfall 4). Until
then these tests fail (transitional, not regressions):

- `tests/integration/test_tournament_rewards.py::TestParticipationGrant::test_submit_then_verify_grants_participation_once`
- `tests/integration/test_tournaments_integration.py::TestLeaderboardEndpoint::test_leaderboard_returns_200`
- `tests/integration/test_tournaments_integration.py::TestVerifyTournamentCompletion::test_verify_flips_row_and_grants_participation`
- `tests/integration/test_tournaments_integration.py::TestVerifyTournamentCompletion::test_verify_twice_grants_participation_once`
- `tests/repository/tournaments/test_tournaments_repository.py::TestCrossWriteToCore::test_cross_write_inserts_when_faster`
- `tests/repository/tournaments/test_tournaments_repository.py::TestCrossWriteToCore::test_cross_write_skips_when_slower`
- `tests/repository/tournaments/test_tournaments_repository.py::TestCrossWriteToCore::test_cross_write_skips_when_equal`
- `tests/repository/tournaments/test_tournaments_repository.py::TestFetchLeaderboard::test_leaderboard_ranking_by_time`
- `tests/repository/tournaments/test_tournaments_repository.py::TestFetchLeaderboard::test_leaderboard_verified_beats_unverified`
- `tests/repository/tournaments/test_tournaments_repository.py::TestFetchLeaderboard::test_leaderboard_includes_display_name`
- `tests/repository/tournaments/test_tournaments_repository.py::TestFetchUserCompletion::test_fetch_user_completion_found`

(All of these insert/seed completions with the boolean `verified` column or
exercise the verify path; they pass once writes move to `status` in 12.1-03.)

### Owned by Plan 12.1-04 (outbox poller: results computation on drain)

The cron is now timing-only (edition → `awaiting_results`, never `completed`; no
snapshot; no outbox row, D-06). These tests assert the OLD cron-finalizes
behavior and are stale-by-design until the poller owns results computation and
the tests are rewritten to drive the poller:

- `tests/repository/tournaments/test_edition_transitions.py::TestSingleEdition::test_one_rollover_one_edition_per_category`
- `tests/repository/tournaments/test_edition_transitions.py::TestHiatus::test_pause_completes_without_next_edition`
- `tests/repository/tournaments/test_edition_transitions.py::TestDrift::test_drift_immune_under_late_cron`

(Symptom: `assert 'awaiting_results' == 'completed'` — the cron correctly stops
at `awaiting_results`; the poller will perform the flip to `completed`.)

## Pre-existing flaky (NOT a 12.1-01 regression)

- `tests/repository/maps/test_maps_repository_fetch_maps.py::TestFetchMapsFilterCategory::test_filter_by_single_category`
  — documented in MEMORY as a `-n 4` parallel cross-worker test-DB contamination
  flake; passes in isolation. Unrelated to tournaments.
