---
phase: 07-automatic-cycle-transitions
verified: 2026-05-30T00:00:00Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 0
re_verification: true
human_verification_approved: 2026-05-30 (user approved deploy/runtime checks; see 07-HUMAN-UAT.md)
human_verification:
  - test: "Start the API process and wait ~10 seconds; confirm the tournament_outbox_poller background task starts without error and logs nothing unexpected on startup."
    expected: "Litestar app boots; tournament_outbox_poller lifespan task is created; no exception is raised; sending SIGTERM causes the task to cancel and the process exits cleanly."
    why_human: "The lifespan task lifecycle (startup/shutdown sequencing, clean cancellation under real signal handling) cannot be verified without running the full Litestar process. asyncio.create_task + contextlib.suppress(CancelledError) are present in code but runtime behaviour requires an actual process."
  - test: "On a VPS with pg_cron installed and migration 0021 applied, verify that the cron job 'tournament-cycle-transitions' appears in cron.job and runs on the 1-minute schedule."
    expected: "SELECT jobname, schedule FROM cron.job WHERE jobname = 'tournament-cycle-transitions' returns one row with schedule '* * * * *'. Waiting one minute and querying tournaments.pending_transitions shows outbox rows written if any cycle was due."
    why_human: "pg_cron is absent in the test DB; the idempotent registration block fires its RAISE NOTICE skip branch. Actual cron execution requires the production/dev VPS where pg_cron is loaded into shared_preload_libraries."
re_verification_07_04:
  previous_status: passed (with UAT-sourced cold-start gap pending)
  gap_closed: "Cold-start lifespan ordering race — publish_pending_transitions raised KeyError/AttributeError on first tick before asyncpg lifespan populated state.db_pool"
  method: "sleep-first loop + state.get() readiness guard + regression test (TestPoolNotReady)"
  test_result: "7/7 passed (uv run pytest tests/repository/tournaments/test_outbox_poller.py -v -p no:xdist --no-testmon)"
  lint_result: "basedpyright 0 errors; ruff check clean on edited files (1 unrelated noqa warning in tournaments_repository.py pre-existing)"
---

# Phase 7: Automatic Cycle Transitions — Verification Report

**Phase Goal:** Tournament cycles automatically transition at their scheduled end times -- finalizing the current cycle, computing placements, and starting the next cycle with pre-selected maps
**Verified:** 2026-05-30
**Status:** passed
**Re-verification (07-04 gap-closure):** Yes — cold-start race gap closed by 07-04; all 5 roadmap truths remain verified; no regressions introduced

---

## 07-04 Gap-Closure Re-Verification

### Scope

07-04 targeted the single gap identified in 07-UAT.md (Test 1): on a cold start, the `tournament_outbox_poller._loop` ran its first `publish_pending_transitions(_app.state)` before the litestar-asyncpg plugin's lifespan populated `state.db_pool`, producing `KeyError: 'db_pool'` → `AttributeError` and the log line `[!] tournament outbox poll failed`.

The objective for this re-verification described three different gaps (retry ceiling, dead-letter path, structured health logging) that are **not present in this VERIFICATION.md and were not the gaps 07-04 was planned to close**. Those items do not appear in 07-UAT.md, 07-VERIFICATION.md (prior version), or 07-04-PLAN.md. They are not addressed by the code delivered. Verification scope is therefore the actual gap documented in 07-UAT.md and targeted by 07-04-PLAN.md.

### Gap: Cold-Start db_pool Race

**Truth being closed:** "On a fresh/cold start the tournament_outbox_poller runs without error and can publish pending transitions"

| Check | Finding | Status |
|-------|---------|--------|
| `asyncio.sleep(10)` moved to TOP of `while True` body in `app.py _loop` | Line 93 of app.py: `await asyncio.sleep(10)` precedes the `try/await publish_pending_transitions` block; comment on lines 88-92 documents the cold-start ordering rationale | VERIFIED |
| `publish_pending_transitions` reads `state.get("db_pool")` with early-return guard | Lines 97-103 of tournament_outbox_service.py: `pool: Pool | None = state.get("db_pool")` then `if pool is None: log.debug(...); return` | VERIFIED |
| Delivery semantics unchanged | Publish-before-mark at lines 138-144; `FOR UPDATE SKIP LOCKED` in repository query; cycle-scoped idempotency key `tournament:{event_type}:{cycle_id}`; `lifespan=[rabbitmq_connection, tournament_outbox_poller]` list at app.py line 240 untouched | VERIFIED |
| `asyncio.CancelledError` re-raise preserved | Lines 96-97: `except asyncio.CancelledError: raise` inside `_loop` | VERIFIED |
| Regression test `TestPoolNotReady.test_publish_noops_when_db_pool_absent` | Lines 317-334 of test_outbox_poller.py: calls `publish_pending_transitions(State({}))`, asserts no exception and `calls == []` | VERIFIED |

### Test Results (Live Run)

```
uv run pytest tests/repository/tournaments/test_outbox_poller.py -v -p no:xdist --no-testmon
```

```
tests/repository/tournaments/test_outbox_poller.py::TestPublishAndMark::test_poller_publishes_and_marks PASSED
tests/repository/tournaments/test_outbox_poller.py::TestSkipLocked::test_skip_locked_no_double_publish PASSED
tests/repository/tournaments/test_outbox_poller.py::TestPublishFailure::test_publish_failure_leaves_unpublished PASSED
tests/repository/tournaments/test_outbox_poller.py::TestCycleEndRewardHook::test_cycle_completed_invokes_award_cycle_end PASSED
tests/repository/tournaments/test_outbox_poller.py::TestCycleEndRewardHook::test_cycle_started_does_not_invoke_award_cycle_end PASSED
tests/repository/tournaments/test_outbox_poller.py::TestPoolNotReady::test_publish_noops_when_db_pool_absent PASSED
tests/repository/tournaments/test_outbox_poller.py::TestBuildEvent::test_invalid_event_type_rejected PASSED

7 passed in 8.86s
```

No regressions in pre-existing tests.

### Lint Results (Live Run)

```
just lint-api
```

- `ruff format apps/api`: 91 files left unchanged
- `ruff check apps/api`: 1 pre-existing fixable warning (`RUF100` unused `noqa: PLR0913` in `tournaments_repository.py:837`) — not introduced by 07-04
- `basedpyright apps/api/...`: 0 errors, 0 warnings, 0 notes

The ruff warning is pre-existing and unrelated to 07-04 changes. Both edited files (`app.py`, `tournament_outbox_service.py`) are clean.

---

## Goal Achievement (Original 5/5 Truths — Regression Check)

All five roadmap truths verified in the original report remain satisfied. 07-04 touched only `app.py` (sleep ordering), `tournament_outbox_service.py` (readiness guard), and `test_outbox_poller.py` (new test class). No changes to migration 0021, SDK structs, repository layer, or other services. The 7/7 test pass above confirms Truth 4 (poller publishes and marks, SKIP LOCKED, at-least-once) is not regressed.

| # | Truth | Status |
|---|-------|--------|
| 1 | pg_cron job runs periodically and detects due cycles | VERIFIED (migration 0021 unchanged) |
| 2 | `process_cycle_transitions()` atomically finalizes+snapshots+completes+promotes | VERIFIED (migration 0021 unchanged) |
| 3 | Completed transitions write to `pending_transitions` outbox | VERIFIED (migration 0021 unchanged) |
| 4 | API polls outbox, publishes RabbitMQ events, marks published | VERIFIED (7/7 tests pass, cold-start gap closed) |
| 5 | Concurrent transition attempts prevented by advisory locks + SKIP LOCKED | VERIFIED (TestSkipLocked passes, no changes to query) |

**Score:** 5/5 truths verified

---

## Objective Mismatch Note

The re-verification objective described three gaps that were not present in this phase's VERIFICATION.md:

1. "Unbounded outbox-poller failure mode — retry ceiling" — no such gap exists in 07-VERIFICATION.md or 07-UAT.md
2. "Missing dead-letter path for poison events" — no such gap exists; the existing design lets malformed rows remain unpublished (at-least-once retry on next tick), proven by `TestPublishFailure`
3. "No operational visibility into poller health — structured health logging" — no such gap exists; the poller logs `[!] tournament outbox poll failed` on error via `log.exception` and `[→] published {event_type} for cycle {cycle_id}` per row

These are absent from the gap lists in 07-UAT.md, 07-VERIFICATION.md, and 07-04-PLAN.md. They were not part of 07-04's gap-closure scope. No migration `0026_outbox_retry_dead_letter.sql` was created or was expected to be created — the highest migration is `0022_tournament_xp_grants.sql`. These items may describe future enhancements but are not unresolved gaps for Phase 7.

---

## Original Gaps Summary

No gaps. All 5 roadmap success criteria remain VERIFIED with codebase evidence:

1. pg_cron job registered idempotently in 0021 (guarded on pg_extension); due-detection logic proven by `TestDueDetection`.
2. `process_cycle_transitions()` atomically finalizes+snapshots+completes+promotes; full state machine proven by `TestStateMachine` and `TestCompletedPayload`.
3. Two `INSERT INTO tournaments.pending_transitions` per transition; third INSERT for D-07 missing-pending edge.
4. `publish_pending_transitions` polls outbox, publishes to `api.tournament.*`, marks published in same transaction; wired as Litestar lifespan task; cold-start race closed by 07-04.
5. `pg_try_advisory_xact_lock(2025070100)` + `FOR UPDATE SKIP LOCKED`; both proven by `TestAdvisoryLock` and `TestSkipLocked`.

The RabbitMQ queue declarations for `api.tournament.cycle_started`/`cycle_completed` are deferred to Phase 9 as documented in `deferred-items.md`.

---

_Verified: 2026-05-30_
_Verifier: Claude (gsd-verifier)_
