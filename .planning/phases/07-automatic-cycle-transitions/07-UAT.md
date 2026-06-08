---
status: diagnosed
phase: 07-automatic-cycle-transitions
source: [07-01-SUMMARY.md, 07-02-SUMMARY.md, 07-03-SUMMARY.md]
started: 2026-05-30T21:58:32Z
updated: 2026-05-30T22:08:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Cold Start Smoke Test
expected: Kill any running API process. Apply migration 0021 against a fresh/clean DB and clear ephemeral state. Start the API from scratch (`just run-api`). Server boots without errors, all migrations (including 0021) apply cleanly, the `tournament_outbox_poller` task starts (visible in logs), and a primary query (healthcheck or a tournament read) returns live data.
result: issue
reported: "On startup the tournament outbox poll fails with `KeyError: 'db_pool'` -> `AttributeError` (state.db_pool not initialized). Logged: '[!] tournament outbox poll failed' with traceback in publish_pending_transitions -> `pool: Pool = state.db_pool` at tournament_outbox_service.py:97, called from app.py:89 _loop. Application startup still completes."
severity: major

### 2. Due Cycle Transitions Automatically
expected: With an active cycle whose `started_at` is past its due window (7d weekly / 14d biweekly) and a pending cycle queued for the same category, invoking `SELECT tournaments.process_cycle_transitions();` flips the due cycle to `completed` (with `ended_at` set) and promotes the category's pending cycle to `active`. A not-yet-due cycle is left untouched (stays `active`).
result: skipped
reason: Behavior implied from migration 0021 (process_cycle_transitions state machine) and pinned by test_cycle_transitions.py due-detection + finalizing→completed→promote tests. Skipped per user directive (implied from migrations).

### 3. New Active Cycle Gets a Fresh Eligible Map
expected: After a transition, the newly-activated cycle has a map assigned that is official, not archived, has a non-null code, matches the category's difficulty band, and is not blacklisted/recently-used (ideally not the map from the cycle that just completed). When no eligible map exists, selection falls back to the least-recently-used matching map rather than crashing.
result: skipped
reason: Behavior implied from migration 0021 (select_eligible_map) and pinned by test_select_eligible_map.py parity/LRU/NULL tests. Skipped per user directive (implied from migrations).

### 4. Completed Cycle Records Standings + Winner
expected: The completed cycle captures a final placement snapshot — a ranked standings list (RANK() over verified times) and a single winner user id (the rank-1 user, a large Discord snowflake handled without integer overflow). With no submissions, the winner is null and standings are empty rather than erroring.
result: skipped
reason: Behavior implied from migration 0021 (jsonb standings snapshot + v_winner bigint fix) and pinned by test_cycle_transitions.py msgspec round-trip. Skipped per user directive (implied from migrations).

### 5. Cycle Events Reach RabbitMQ
expected: After a transition, the outbox poller (running every ~10s) publishes the queued `pending_transitions` rows to `api.tournament.cycle_completed` and `api.tournament.cycle_started`, then marks them published so they aren't re-sent. Events carry the full payload (map code/name, started/ends timestamps, standings, winner) that downstream bot announcements consume.
result: skipped
reason: Requires a running API + RabbitMQ broker (lifespan poller). Skipped per user directive (requires API up). NOTE: this path is exactly what Test 1's db_pool startup bug breaks — see Gaps.

## Summary

total: 5
passed: 0
issues: 1
pending: 0
skipped: 4
blocked: 0

## Gaps

- truth: "On a fresh/cold start the tournament_outbox_poller runs without error and can publish pending transitions"
  status: failed
  reason: "User reported: On startup the tournament outbox poll fails with KeyError: 'db_pool' -> AttributeError (state.db_pool not initialized). Logged '[!] tournament outbox poll failed' with traceback in publish_pending_transitions -> pool: Pool = state.db_pool at tournament_outbox_service.py:97, called from app.py:89 _loop. Application startup still completes."
  severity: major
  test: 1
  root_cause: "Lifespan initialization ordering race. app.py:240 builds the app with explicit lifespan=[rabbitmq_connection, tournament_outbox_poller]; the litestar-asyncpg plugin sets state.db_pool from inside its OWN lifespan CM which it appends during on_app_init, so the resolved order is [rabbitmq_connection, tournament_outbox_poller, asyncpg.lifespan]. tournament_outbox_poller (app.py:96-98) does asyncio.create_task(_loop()) then yields; _loop's first action (app.py:89) calls publish_pending_transitions which reads state.db_pool (tournament_outbox_service.py:97) with no readiness guard and zero startup delay -- so the first tick runs before the asyncpg lifespan sets db_pool. State key name is correct (pool_app_state_key='db_pool'); this is purely an ordering bug. Self-heals on the next ~10s tick (broad except + sleep(10) retry); no permanent event loss since pg_cron keeps writing outbox rows. Impact = one bogus startup error + up to ~10s delay before first successful poll."
  artifacts:
    - path: "apps/api/app.py"
      issue: "Lines 71-102 + 240: tournament_outbox_poller spawns _loop that polls immediately on first tick; explicit lifespan list places the poller ahead of the plugin-appended asyncpg pool-init lifespan."
    - path: "apps/api/services/tournament_outbox_service.py"
      issue: "Line 97: unguarded `pool: Pool = state.db_pool` access on the first tick, before the pool exists."
  missing:
    - "Defer/guard the poller's first poll until state.db_pool exists -- e.g. move the asyncio.sleep(10) to the top of the loop, or `while getattr(_app.state, 'db_pool', None) is None: await asyncio.sleep(0.1)` before the first poll."
    - "Alternatively guard publish_pending_transitions to no-op cleanly when db_pool is absent (state.get('db_pool'); return early if None)."
    - "Alternatively control lifespan ordering so the asyncpg pool is initialized before the poller lifespan is entered."
  debug_session: ".planning/debug/outbox-poller-db-pool-startup.md"
