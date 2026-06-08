---
status: diagnosed
trigger: "On startup the tournament outbox poll fails with KeyError: 'db_pool' -> AttributeError (07-UAT Test 1 Cold Start Smoke Test)"
created: 2026-05-30T00:00:00Z
updated: 2026-05-30T00:00:00Z
goal: find_root_cause_only
---

## Current Focus

hypothesis: CONFIRMED — lifespan ordering race. The `tournament_outbox_poller` lifespan
  context manager is entered BEFORE the litestar-asyncpg plugin's lifespan (which sets
  `state.db_pool`). The poller's first `_loop()` tick reads `state.db_pool` before it exists.
test: Traced lifespan registration + entry order in litestar app.py and litestar_asyncpg config/plugin.
expecting: First tick fails with KeyError 'db_pool'; subsequent ticks (after 10s) succeed.
next_action: Diagnosis complete — return ROOT CAUSE FOUND.

## Symptoms

expected: On fresh cold start (`just run-api`), the poller starts and its polls succeed (or no-op cleanly when there are no rows).
actual: On startup the first tournament outbox poll fails with `KeyError: 'db_pool'` -> `AttributeError`, logged as `[!] tournament outbox poll failed`. Application startup still completes.
errors: |
  KeyError: 'db_pool' (litestar/datastructures/state.py:123 __getattr__)
  -> AttributeError (state.py:125)
  raised from tournament_outbox_service.py:97 `pool: Pool = state.db_pool`
  called from app.py:89 `_loop` -> publish_pending_transitions(_app.state)
reproduction: 07-UAT.md Test 1 (Cold Start Smoke Test) — start API fresh, watch startup logs.
started: Introduced in plan 07-02 (commits 70f29d0, 3e3dfdc) — poller lifespan + publish_pending_transitions.

## Eliminated

- hypothesis: Wrong state key name (poller reads `db_pool` but plugin stores under a different key)
  evidence: litestar_asyncpg config.py:132 `pool_app_state_key: str = "db_pool"`. The key is correct.
    Every DI provider in the codebase reads `state.db_pool` (grep across repository/ and services/). Not a key-name bug.
  timestamp: 2026-05-30T00:00:00Z

- hypothesis: Persistent failure — db_pool never set, events never publish
  evidence: asyncpg lifespan (config.py:246-248) DOES set `app.state.update({"db_pool": db_pool})` after
    create_pool() completes. It is set, just slightly later than the poller's first tick. Loop catches Exception,
    sleeps 10s, retries. By the next tick db_pool exists. Self-heals.
  timestamp: 2026-05-30T00:00:00Z

## Evidence

- timestamp: 2026-05-30T00:00:00Z
  checked: apps/api/app.py:71-102 (tournament_outbox_poller) and :221-244 (Litestar construction)
  found: Poller lifespan does `task = asyncio.create_task(_loop())` then `yield` immediately. `_loop()` first
    line of work is `await publish_pending_transitions(_app.state)` with no readiness guard. lifespan list passed
    explicitly is `lifespan=[rabbitmq_connection, tournament_outbox_poller]` — asyncpg NOT in this list.
  implication: The asyncpg pool lifespan must be appended by the plugin, AFTER these two.

- timestamp: 2026-05-30T00:00:00Z
  checked: apps/api/services/tournament_outbox_service.py:97
  found: `pool: Pool = state.db_pool` — direct attribute access at the very top of publish_pending_transitions,
    executed on the first poll tick during startup.
  implication: If db_pool is not yet on state, this raises KeyError->AttributeError exactly as the traceback shows.

- timestamp: 2026-05-30T00:00:00Z
  checked: litestar_asyncpg plugin.py:39-58 (on_app_init) + config.py:245-253 (lifespan) + config.py:132 (pool_app_state_key)
  found: Plugin sets the pool via its OWN lifespan CM: `db_pool = await self.create_pool(); app.state.update({"db_pool": db_pool})`.
    on_app_init does `app_config.lifespan.append(self._config.lifespan)` — APPENDS to the lifespan list.
  implication: db_pool is set only when the asyncpg lifespan CM is entered, which happens AFTER the user-supplied
    lifespan managers because the plugin appends.

- timestamp: 2026-05-30T00:00:00Z
  checked: litestar/app.py:359 (config.lifespan = list(lifespan or [])), :397-402 (plugin on_app_init runs, appending),
    :411 (self._lifespan_managers = config.lifespan), :637-659 (lifespan() enters managers in list order)
  found: Final lifespan order = [rabbitmq_connection, tournament_outbox_poller, asyncpg.lifespan].
    `lifespan()` enters each manager sequentially via AsyncExitStack in that order. tournament_outbox_poller is
    entered (spawning _loop task) BEFORE asyncpg.lifespan runs create_pool() and sets db_pool.
  implication: Definitive ordering race. The poller's _loop is scheduled and runs its first tick during the
    await inside asyncpg.create_pool(), before app.state["db_pool"] is populated.

- timestamp: 2026-05-30T00:00:00Z
  checked: apps/api/app.py:87-94 (loop body) — try/except Exception + asyncio.sleep(10)
  found: First-tick exception is caught, logged `[!] tournament outbox poll failed`, then the loop sleeps 10s and
    retries. By the second tick the asyncpg lifespan has set db_pool, so the poll succeeds.
  implication: SELF-HEALS after the first tick. Impact is one bogus startup error + up to ~10s delay before the
    first successful poll. Events are NOT permanently dropped — pg_cron keeps writing outbox rows and the next
    tick publishes any pending ones.

## Resolution

root_cause: |
  Lifespan initialization ordering race. In apps/api/app.py the app is built with
  `lifespan=[rabbitmq_connection, tournament_outbox_poller]`. The litestar-asyncpg plugin populates
  `state.db_pool` from inside its OWN lifespan context manager (litestar_asyncpg/config.py:246-248), and registers
  that CM by APPENDING it to app_config.lifespan during on_app_init (plugin.py:53). Litestar enters lifespan
  managers in list order (litestar/app.py:651-654), so the resolved order is
  [rabbitmq_connection, tournament_outbox_poller, asyncpg.lifespan]. tournament_outbox_poller does
  `asyncio.create_task(_loop())` then yields immediately (app.py:96-98); _loop's first action is
  `await publish_pending_transitions(_app.state)` (app.py:89) which reads `state.db_pool`
  (tournament_outbox_service.py:97). That first tick runs during the `await` inside asyncpg.create_pool(),
  BEFORE app.state["db_pool"] is set — producing KeyError 'db_pool' -> AttributeError.
fix: ""  # find_root_cause_only — not applied
verification: |
  Self-heals: the loop catches Exception, sleeps 10s, and the next tick succeeds once db_pool exists. So this is a
  transient first-tick-only startup error, not a persistent failure. No permanent event loss.
files_changed: []
