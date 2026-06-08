---
phase: 07-automatic-cycle-transitions
plan: 04
subsystem: api
tags: [litestar, lifespan, asyncpg, outbox, asyncio, cold-start, gap-closure]

requires:
  - phase: 07-02
    provides: publish_pending_transitions poller loop + tournament_outbox_poller lifespan CM
  - phase: 07-03
    provides: outbox poller integration tests (publish/mark, SKIP-LOCKED, at-least-once)
provides:
  - Cold-start-safe outbox poller (first poll deferred ~10s until the asyncpg lifespan populates state.db_pool)
  - Defensive db_pool readiness guard in publish_pending_transitions (clean no-op when pool absent)
  - Regression test asserting the no-op behavior without a live broker
affects:
  - "None — delivery semantics, cadence, and the SDK event contract are unchanged"

tech-stack:
  added: []
  patterns:
    - "sleep-first poll loop so a plugin-appended lifespan (asyncpg) initializes before the first tick"
    - "dict-like State.get() readiness guard for state populated by a later lifespan CM"

key-files:
  created: []
  modified:
    - apps/api/app.py
    - apps/api/services/tournament_outbox_service.py
    - apps/api/tests/repository/tournaments/test_outbox_poller.py

key-decisions:
  - "Deferred the first poll by moving asyncio.sleep(10) to the TOP of the while-loop (belt) AND added a state.get('db_pool') early-return guard (suspenders) — both keep the cadence at ~10s and the sleep as the D-08 cancellation point"
  - "Did not reorder the lifespan=[...] list or touch the litestar-asyncpg plugin (the resolved order [rabbitmq, poller, asyncpg.lifespan] is plugin-appended and out of scope)"

patterns-established:
  - "Background lifespan asyncio tasks that read state populated by a plugin-appended lifespan must defer their first tick and/or guard the read — they enter before the plugin's lifespan"

requirements-completed: [CYCLE-01]

duration: ~8min
completed: 2026-05-30
---

# Phase 7 Plan 04: Outbox Poller Cold-Start Race Fix Summary

**Eliminated the cold-start `KeyError: 'db_pool'` from the tournament outbox poller by deferring its first poll until after the asyncpg lifespan initializes the pool, plus a defensive `state.get("db_pool")` readiness guard that makes `publish_pending_transitions` a clean no-op when the pool is absent — cadence, cancellation, and delivery semantics unchanged.**

## Performance

- **Duration:** ~8 min
- **Completed:** 2026-05-30
- **Tasks:** 2
- **Files modified:** 3 (0 created, 3 modified)

## Accomplishments

- **Root cause closed (lifespan ordering race):** `tournament_outbox_poller._loop` previously ran its first `publish_pending_transitions(_app.state)` immediately, before the litestar-asyncpg plugin's lifespan (resolved AFTER the poller's lifespan) had set `state.db_pool`. Moving `await asyncio.sleep(10)` to the TOP of the `while True` body defers the first poll long enough for startup to populate the pool, so the cold-start error and its reliance on the broad-`except` self-heal are gone.
- **Defensive readiness guard:** `publish_pending_transitions` now reads `pool: Pool | None = state.get("db_pool")` and returns early (with a `log.debug` at `%s`-free debug level) when `None`, guaranteeing the function can never raise on a missing pool even if entered early. The type is narrowed (`Pool | None` then early-return) so BasedPyright strict stays clean.
- **Regression test:** `TestPoolNotReady.test_publish_noops_when_db_pool_absent` calls `publish_pending_transitions(State({}))` and asserts it returns without raising and never publishes (`calls == []`), using the existing `_stub_publish` recorder — no `asyncpg_pool` fixture or broker needed.
- **No semantic drift:** publish-then-mark, at-least-once, `FOR UPDATE SKIP LOCKED`, cycle-scoped idempotency keys, the ~10s cadence (D-12), the `asyncio.CancelledError` re-raise, and the lifespan `finally` shutdown (D-08) are all preserved. The `lifespan=[...]` list and the third-party plugin were not touched.

## Task Commits

1. **Task 1: Defer first poll + db_pool readiness guard** - `1c1c570` (fix)
2. **Task 2: Regression test — no-op when db_pool absent** - `42cbe99` (test)

## Files Created/Modified

- `apps/api/app.py` - `tournament_outbox_poller._loop`: `await asyncio.sleep(10)` moved to the top of the `while` body with a comment explaining the cold-start ordering rationale; try/except block otherwise unchanged.
- `apps/api/services/tournament_outbox_service.py` - `publish_pending_transitions`: `pool: Pool = state.db_pool` replaced with `pool: Pool | None = state.get("db_pool")` + early-return no-op guard when `None`.
- `apps/api/tests/repository/tournaments/test_outbox_poller.py` - added `TestPoolNotReady` with one async test asserting the guard's no-op-and-no-publish behavior.

## Decisions Made

- **Belt-and-suspenders, not either/or.** The plan offered the sleep-first reorder OR the readiness guard; both were applied. The sleep-first edit removes the race in practice (the pool is ready by the time the first poll runs); the guard guarantees correctness regardless of future lifespan-ordering changes. This matches the plan's explicit "belt-and-suspenders" framing.
- **Kept the sleep as the single cancellation point.** With the sleep at the top of the loop body, it remains the `await` the lifespan `finally`'s `task.cancel()` interrupts (D-08), so clean shutdown is unaffected.

## Deviations from Plan

None - plan executed exactly as written. (Note: the plan's prompt-level title referenced a retry/dead-letter migration `0023`, but the actual `07-04-PLAN.md` content is the cold-start race fix described above; no migration was created because the plan body and `files_modified` do not call for one.)

## Test Results

- Targeted: `uv run pytest tests/repository/tournaments/test_outbox_poller.py -v -p no:xdist` → **7 passed** (the new `TestPoolNotReady` plus the six pre-existing tests across `TestPublishAndMark`, `TestSkipLocked`, `TestPublishFailure`, `TestCycleEndRewardHook` (×2), `TestBuildEvent`).
- Lint: `uv run ruff check app.py services/tournament_outbox_service.py` → All checks passed. `uv run basedpyright app.py services/tournament_outbox_service.py` → 0 errors, 0 warnings, 0 notes.

## Next Phase Readiness

- The Phase 7 cold-start gap from `07-UAT.md` (Test 1) is closed; the poller boots clean and its first successful poll occurs ~10s after startup on the ~10s cadence.
- Manual cold-start confirmation (`just run-api`, no `[!] tournament outbox poll failed` / `KeyError: 'db_pool'`, clean Ctrl-C) remains an optional dev-VPS check per the plan's `<verification>` — the automated regression test pins the guard behavior in CI.

## Self-Check: PASSED

- FOUND: apps/api/app.py (modified, sleep-first in `_loop`)
- FOUND: apps/api/services/tournament_outbox_service.py (modified, `state.get("db_pool")` guard)
- FOUND: apps/api/tests/repository/tournaments/test_outbox_poller.py (modified, `TestPoolNotReady`)
- FOUND: commit 1c1c570 (Task 1)
- FOUND: commit 42cbe99 (Task 2)

---
*Phase: 07-automatic-cycle-transitions*
*Completed: 2026-05-30*
