---
phase: 07-automatic-cycle-transitions
plan: 02
subsystem: tournaments
tags: [outbox, rabbitmq, asyncio, lifespan, msgspec, skip-locked, at-least-once]
requires:
  - tournaments.pending_transitions outbox (0020_tournaments.sql)
  - tournaments.process_cycle_transitions() writing outbox rows (07-01)
  - extended TournamentCycleStartedEvent / TournamentCycleCompletedEvent SDK structs (07-01)
  - BaseService.publish_message + state.mq_channel_pool / state.db_pool
provides:
  - hardened fetch_unpublished_transitions (FOR UPDATE SKIP LOCKED)
  - TournamentOutboxService + publish_pending_transitions(state) poll-publish-mark loop body
  - tournament_outbox_poller Litestar lifespan background task
  - api.tournament.cycle_started / api.tournament.cycle_completed publishing
affects:
  - Phase 8 rewards / Phase 9 announcements (consume the emitted RabbitMQ events)
  - Wave 3 integration tests (assert publish+mark / SKIP-LOCKED / at-least-once via X-PYTEST-ENABLED skip)
tech-stack:
  added: []
  patterns:
    - transactional outbox poller as a Litestar lifespan asyncio task (first long-running loop in the codebase)
    - FOR UPDATE SKIP LOCKED for multi-instance-safe outbox polling
    - publish-then-mark in one transaction for at-least-once delivery
    - msgspec.convert(payload_dict, EventStruct) to fail fast on SQL/struct field drift
    - cancel + suppress(CancelledError) lifespan shutdown
key-files:
  created:
    - apps/api/services/tournament_outbox_service.py
  modified:
    - apps/api/repository/tournaments_repository.py
    - apps/api/app.py
decisions:
  - "D-10/D-11/D-12: poller is a lifespan asyncio task on a 10s cadence; selects FOR UPDATE SKIP LOCKED and marks published in the same transaction; publish-before-mark = at-least-once"
  - "Pitfall 5: poller deserializes via msgspec.convert(row['payload'], Struct) so SQL/struct drift fails fast"
  - "Followed existing tournament_service.py convention of `# type: ignore[arg-type]` for pool-acquired conn passed to repo methods typed as Connection"
metrics:
  duration: ~12m
  completed: 2026-05-30
  tasks: 3
  files: 3
---

# Phase 7 Plan 02: Outbox to RabbitMQ Bridge Summary

The outbox->RabbitMQ bridge: a multi-instance-safe row lock on the unpublished-transitions query, a publish-then-mark service loop that serializes each outbox payload into its SDK event struct and publishes it to `api.tournament.*`, and the first long-running background lifespan task in the codebase that drives the loop on a ~10s cadence and cancels cleanly on shutdown.

## What Was Built

**Task 1 - Harden `fetch_unpublished_transitions` (`apps/api/repository/tournaments_repository.py`, commit c2e3153):**
- Appended `FOR UPDATE SKIP LOCKED` after the existing `ORDER BY created_at ASC` (D-11). Two API instances polling concurrently now skip each other's locked rows instead of double-selecting.
- Rewrote the docstring to require callers to invoke the method inside an open `conn.transaction()` so the row lock is held until the matching `mark_transition_published` UPDATE runs in the same transaction.
- Left `create_pending_transition` and `mark_transition_published` untouched (the latter's `WHERE id=$1 AND published=FALSE` guard is already correct).

**Task 2 - `TournamentOutboxService` + `publish_pending_transitions` (`apps/api/services/tournament_outbox_service.py`, commit 70f29d0):**
- `class TournamentOutboxService(BaseService)` exists purely to inherit `publish_message` (with its `public.jobs` record + idempotency handling).
- Module-level `_EVENT_ROUTING` dict maps `event_type` -> `(routing_key, struct_type)`: `cycle_started` -> `api.tournament.cycle_started` + `TournamentCycleStartedEvent`; `cycle_completed` -> `api.tournament.cycle_completed` + `TournamentCycleCompletedEvent`.
- `_build_event(row)` does `msgspec.convert(row["payload"], struct_type)` (payload is already a dict via the jsonb codec) so any SQL/struct field drift raises immediately (Pitfall 5) and leaves the row unpublished.
- `publish_pending_transitions(state)` acquires its own connection from `state.db_pool`, opens `async with pool.acquire() as conn, conn.transaction():`, calls the hardened `fetch_unpublished_transitions(conn=conn)` (lock held), and per row: publishes with `idempotency_key=f"tournament:{row['event_type']}:{row['cycle_id']}"` (REQUIRED -- these keys are not in `IGNORE_IDEMPOTENCY`), THEN `mark_transition_published(row["id"], conn=conn)` in the same transaction. Publish-before-mark gives at-least-once: a crash between the two re-publishes on the next poll (D-11). `%s`-style logging; per-row failures propagate to the lifespan loop.

**Task 3 - `tournament_outbox_poller` lifespan (`apps/api/app.py`, commit 3e3dfdc):**
- New `@asynccontextmanager async def tournament_outbox_poller(_app)` next to `rabbitmq_connection`. Inner `_loop()` does a local import of `publish_pending_transitions` (avoids circular import), `while True:` -> `try await publish_pending_transitions(_app.state)` / `except asyncio.CancelledError: raise` / `except Exception: log.exception(...)` / `await asyncio.sleep(10)` (D-12 cadence + cancellation point).
- `task = asyncio.create_task(_loop())`; `try: yield finally: task.cancel()` + `contextlib.suppress(asyncio.CancelledError): await task` for clean shutdown (D-08 / T-07-08).
- Added `import asyncio` and `import contextlib` at top; changed `lifespan=[rabbitmq_connection]` to `lifespan=[rabbitmq_connection, tournament_outbox_poller]`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking lint] basedpyright `reportArgumentType` on pool-acquired conn**
- **Found during:** Task 2 (`just lint-api`)
- **Issue:** `pool.acquire()` yields a `PoolConnectionProxy`, but the repo methods type `conn` as `Connection | None`, so passing it tripped two `reportArgumentType` errors.
- **Fix:** Added `# type: ignore[arg-type]` to the two `conn=conn` repo calls -- the exact convention already used throughout `tournament_service.py` (lines 190-295).
- **Files modified:** apps/api/services/tournament_outbox_service.py
- **Commit:** 70f29d0

**2. [Rule 3 - Blocking lint] ruff `PLC0415` on the required local import**
- **Found during:** Task 3 (`just lint-api`)
- **Issue:** The plan mandates a function-local import of `publish_pending_transitions` to avoid a circular import; ruff flags `PLC0415 import should be at the top-level`.
- **Fix:** Added a targeted `# noqa: PLC0415  # local import avoids circular import` (the import is deliberate per the plan/RESEARCH scaffolding, not an accident).
- **Files modified:** apps/api/app.py
- **Commit:** 3e3dfdc

## Verification

- **Task 1:** `uv run --directory apps/api pytest tests/repository/tournaments/test_tournaments_repository.py -p no:xdist -q --co` -> `38/39 tests collected` (exit 0), no import/syntax regression.
- **Task 2:** `just lint-api` -> ruff format + check + basedpyright all clean (0 errors).
- **Task 3:** `just lint-api` -> ruff format + check + basedpyright all clean (0 errors).
- Single-writer constraint honored: the poller acquires its own connection from `state.db_pool` and only the API publishes; it never writes outside the API process.
- Behavioral guarantees (publish+mark, SKIP-LOCKED no-double-publish, at-least-once) are asserted by Wave 3 integration tests using the `X-PYTEST-ENABLED=1` publish skip; this plan provides the artifacts those tests invoke.

## Threat Model Coverage

- **T-07-05** (double-publish across instances): mitigated -- `FOR UPDATE SKIP LOCKED` + mark-published in the same transaction + cycle-scoped idempotency key `tournament:{event_type}:{cycle_id}`.
- **T-07-06** (poisoned payload): mitigated -- `msgspec.convert(payload, Struct)` validates before publish; a malformed payload raises and the row stays unpublished.
- **T-07-07** (poison row re-failing / unbounded growth): accepted -- per-tick broad `except` + `log.exception` keeps the loop alive; retry cap / DLQ deferred (RESEARCH Open Question 3).
- **T-07-08** (orphaned background task on shutdown): mitigated -- lifespan `finally` cancels + awaits with `suppress(CancelledError)`; `CancelledError` re-raised inside the loop.
- **T-07-SC** (package installs): n/a -- no package installs in this plan.

## Known Stubs

None. All three artifacts are fully wired: the query locks rows, the service publishes-then-marks, and the poller is registered in the lifespan list.

## Self-Check: PASSED

- FOUND: apps/api/services/tournament_outbox_service.py
- FOUND: apps/api/repository/tournaments_repository.py (modified)
- FOUND: apps/api/app.py (modified)
- FOUND: commit c2e3153 (Task 1)
- FOUND: commit 70f29d0 (Task 2)
- FOUND: commit 3e3dfdc (Task 3)
