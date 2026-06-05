# Deferred Items — quick-260605-gjy

Out-of-scope discoveries found during execution. NOT fixed (per executor SCOPE BOUNDARY rule —
unrelated to this task's title-string change). Logged for future attention.

## Pre-existing parallel-test (xdist) flakiness

The full `just test-api` suite (`pytest -n 4 ... -x`) exhibits non-deterministic failures
that are unrelated to this task. Each failure passed in isolation, passed on the un-modified
baseline (this task's change stashed), and the whole tournament module passes deterministically
when run serially (`-p no:xdist`: 41/41 passed).

1. `apps/api/tests/repository/tournaments/test_outbox_poller.py::TestRolloverHiatusSections::test_out_of_hiatus_started_only`
   - Symptom: `assert captured == []` fails as `assert [9] == []` — a sibling edition's
     `award_cycle_end` call leaks across tests under parallel workers (DB/test isolation).
   - Passes in isolation and on baseline. Not caused by this task.

2. `apps/api/tests/repository/maps/test_maps_repository_update_core_map.py::test_update_timestamps_are_automatic`
   - Symptom: `assert updated_at > created_at` fails when both equal to the microsecond — a
     timing-sensitive assertion that flakes when an update lands in the same microsecond.
   - Entirely unrelated to tournaments.

Suggested follow-up: stabilize these tests (per-worker DB isolation / use `>=` or a forced
clock tick for the timestamp test). Tracked separately from this title fix.
