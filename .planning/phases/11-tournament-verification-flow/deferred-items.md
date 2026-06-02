# Deferred Items — Phase 11

- [11-01 Task 1] Pre-existing RUF100 unused-noqa on `claim_xp_grant` (tournaments_repository.py:869, PLR0913) — present in HEAD, out of scope, not fixed.
- [11-03] Pre-existing failures in `tests/services/test_completions_service.py::TestVerifyCompletionTournamentSideEffect` (`test_verify_propagates_to_linked_tournament_row`, `test_verify_on_non_cycle_map_no_side_effect`) — fail on the RED tree before any 11-03 edit; cause is a `store_repository.py:520` TypeError in the quest-progress mock path (a non-awaited AsyncMock), unrelated to the verify surface. Out of scope for 11-03.
