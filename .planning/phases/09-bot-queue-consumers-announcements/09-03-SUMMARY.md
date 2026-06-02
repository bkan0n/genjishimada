---
phase: 09-bot-queue-consumers-announcements
plan: 03
subsystem: infra
tags: [rabbitmq, aio_pika, dlq, definitions.json, tournament-queues, bot, resilience]

# Dependency graph
requires:
  - phase: 09-bot-queue-consumers-announcements (09-02)
    provides: "TournamentHandler consuming api.tournament.cycle_started / .cycle_completed via @queue_consumer"
  - phase: 07-cycle-transitions
    provides: "tournament_outbox_service routing keys api.tournament.cycle_started / .cycle_completed"
provides:
  - "api.tournament.cycle_started / .cycle_completed (+ .dlq) declared in infra/rabbitmq/definitions.json (canonical broker-load-time topology)"
  - "Per-base-queue channel isolation in the bot DLQ sweep so one missing/failing DLQ cannot cascade ChannelInvalidStateError into the rest"
  - "ChannelNotFoundEntity guard in _process_one_dlq that logs + skips a missing .dlq"
  - "Unit test (apps/api/tests/bot/test_rabbit_dlq_sweep.py) proving sweep isolation"
affects: [verify-work-9, bot-rabbit, future-queue-additions]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Every queue + its .dlq companion declared as a pair in definitions.json, mirroring the api.xp.grant model (x-dead-letter-* + classic type), so broker-boot topology matches the bot's runtime _set_up_queues declare (no PRECONDITION_FAILED)"
    - "DLQ sweep acquires a fresh channel per base queue inside the loop; a channel-level error on one queue cannot poison the next"

key-files:
  created:
    - apps/api/tests/bot/test_rabbit_dlq_sweep.py
    - .planning/phases/09-bot-queue-consumers-announcements/deferred-items.md
  modified:
    - infra/rabbitmq/definitions.json
    - apps/bot/extensions/rabbit.py

key-decisions:
  - "Per-base-queue channel acquisition (preferred plan approach) is the true isolation fix; the ChannelNotFoundEntity guard in _process_one_dlq is an additive defensive layer (a passive-declare failure still closes the channel at the broker, so the per-queue channel is what actually breaks the cascade)"
  - "New test path-loads rabbit.py via importlib with the utilities/extensions sys.modules snapshot/evict/restore guard; FakeChannelPool yields a fresh channel per acquire() so per-queue isolation is directly observable"

patterns-established:
  - "Bot test modules that path-load a bot source file must remove their apps/bot sys.path insertion in finally, or apps/api's utilities package shadows the bot's when a sibling bot test path-loads later in the same pytest session"

requirements-completed: [DSC-01, DSC-02, DSC-03, RWD-03]

# Metrics
duration: 4min
completed: 2026-05-31
---

# Phase 9 Plan 03: Tournament Queue Declarations + DLQ Sweep Isolation Summary

**Declared the two tournament queues + their .dlq companions in rabbitmq definitions.json and hardened the bot's periodic DLQ sweep to acquire a fresh channel per base queue, so a NOT_FOUND on a missing tournament .dlq no longer cascades ChannelInvalidStateError into api.xp.grant and the other tournament queue.**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-05-31T02:42:52Z
- **Completed:** 2026-05-31T02:47:04Z
- **Tasks:** 2
- **Files modified:** 3 (1 infra JSON, 1 bot source, 1 new test) + 1 deferred-items log

## Accomplishments
- Added four queue objects to `infra/rabbitmq/definitions.json` (`api.tournament.cycle_started`, `api.tournament.cycle_started.dlq`, `api.tournament.cycle_completed`, `api.tournament.cycle_completed.dlq`) mirroring the `api.xp.grant` + `.dlq` canonical pair exactly — the primary broker-load-time fix that matches every other queue+DLQ pair.
- Moved channel acquisition INSIDE the per-base-queue loop in `_process_all_dlqs_once`, so a channel-level failure on one queue cannot close the channel used by the next (Part B resilience fix; mitigates T-09-10).
- Added a `ChannelNotFoundEntity` guard in `_process_one_dlq` that logs `[!]` and returns 0 for a missing `.dlq` (additive defensive layer).
- New `apps/api/tests/bot/test_rabbit_dlq_sweep.py` (4 tests) proving: B's NOT_FOUND does not block A and C; total excludes B; a missing DLQ skips cleanly without raising; a fresh channel is acquired per base queue.

## Task Commits

Each task was committed atomically:

1. **Task 1: Declare tournament queues + DLQs in definitions.json** - `4c31fa4` (fix)
2. **Task 2: Harden the DLQ sweep (TDD)**
   - RED: `fd2ebe1` (test) — failing per-queue-channel isolation test
   - GREEN: `33059e7` (fix) — per-base-queue channel + ChannelNotFoundEntity guard
   - Follow-up test isolation fix: `07e8b0d` (test) — remove apps/bot from sys.path in finally

**Plan metadata:** committed separately (docs: complete plan).

_TDD task produced test → feat commits as expected._

## Files Created/Modified
- `infra/rabbitmq/definitions.json` - Added the four tournament queue/DLQ declarations before the closing `]` of the `queues` array (comma added after the previous last element). Valid JSON; main queues carry `x-dead-letter-exchange: ""` + own-name `.dlq` routing key; `.dlq` objects carry only `x-queue-type: classic`.
- `apps/bot/extensions/rabbit.py` - `_process_all_dlqs_once` now acquires a fresh channel per base queue inside the loop (shared-channel reuse removed); imported `ChannelNotFoundEntity` and guarded the passive `.dlq` declare in `_process_one_dlq`.
- `apps/api/tests/bot/test_rabbit_dlq_sweep.py` (new) - Path-loads `rabbit.py`, builds `RabbitHandler` via `object.__new__`, drives `_process_one_dlq` via AsyncMock side_effect, asserts isolation + totals + clean skip; FakeChannelPool yields a fresh channel per acquire().
- `.planning/phases/09-bot-queue-consumers-announcements/deferred-items.md` (new) - Logs the two pre-existing out-of-scope `ruff format` drifts in Phase-10 files.

## Decisions Made
- Per-base-queue channel acquisition is the load-bearing fix; the `ChannelNotFoundEntity` guard is additive (a passive-declare failure still closes the channel at the broker, so the guard alone is insufficient — the per-queue channel is required for true isolation, per the plan's PART B note).
- Test follows the `test_tournaments_handler.py` path-load precedent but additionally removes its `apps/bot` `sys.path` insertion in `finally` (see Deviations) to keep the whole `tests/bot/` directory collectable.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] New test broke whole-directory bot-test collection; removed apps/bot from sys.path in finally**
- **Found during:** Task 2 (after GREEN, running the full `tests/bot/` suite)
- **Issue:** The new test's `_load_rabbit_module` left `apps/bot` permanently on `sys.path`. When `test_tournaments_handler.py` path-loaded `tournaments.py` later in the same pytest session, `from utilities import transformers` resolved against apps/api's `utilities` package (shadowing the bot's), raising `ImportError` and aborting collection of the whole `tests/bot/` directory. Each file still passed in isolation.
- **Fix:** Track whether the `apps/bot` path entry was inserted and remove it in `finally` so sibling bot tests re-resolve `utilities` against the bot tree cleanly.
- **Files modified:** apps/api/tests/bot/test_rabbit_dlq_sweep.py
- **Verification:** `uv run --directory apps/api pytest tests/bot/ --no-testmon -p no:xdist` → 28 passed.
- **Committed in:** `07e8b0d`

---

**Total deviations:** 1 auto-fixed (1 bug — test isolation). 
**Impact on plan:** Necessary for the new test to coexist with the existing bot tests; no scope creep. The two `ruff format` drifts the bot linter wants to apply to `apps/bot/extensions/tournaments.py` and `apps/bot/utilities/transformers.py` are pre-existing (Phase-10 files, not touched by this plan) and were reverted + logged to `deferred-items.md` per the scope-boundary rule.

## Issues Encountered
- `just lint-bot` reformats two unrelated Phase-10 files on every run (pre-existing drift). Reverted both (out of scope) and logged them in `deferred-items.md`. `rabbit.py` itself is lint- and type-clean (`ruff check` passes, basedpyright 0 errors).

## User Setup Required
None - no external service configuration required. NOTE (operator action for full verification, not setup): rebuild + restart the RabbitMQ broker so it reloads the new `definitions.json` (`docker compose -f docker-compose.local.yml up -d --build rabbitmq`, or dev/prod equivalent) and restart the bot, then observe one full DLQ sweep interval with no `ChannelNotFoundEntity` / `Channel closed by RPC timeout` lines for the tournament queues or `api.xp.grant`. Then re-run `/gsd:verify-work 9` Tests 1-6.

## Next Phase Readiness
- UAT Test 1 defect closed at the source: tournament `.dlq` queues now exist at broker boot, and the sweep tolerates a missing/failing DLQ. Phase-9 UAT Tests 1-6 are unblocked for re-verification.
- No blockers.

## Self-Check: PASSED

- FOUND: `.planning/phases/09-bot-queue-consumers-announcements/09-03-SUMMARY.md`
- FOUND: `apps/api/tests/bot/test_rabbit_dlq_sweep.py`
- FOUND: `infra/rabbitmq/definitions.json` (4 tournament queue objects present, valid JSON)
- FOUND commits: `4c31fa4` (Task 1), `fd2ebe1` (RED), `33059e7` (GREEN), `07e8b0d` (test isolation fix)

_Note: `.planning/` is gitignored (`commit_docs: false`); SUMMARY + deferred-items live on disk, not in git, by project config._

---
*Phase: 09-bot-queue-consumers-announcements*
*Completed: 2026-05-31*
