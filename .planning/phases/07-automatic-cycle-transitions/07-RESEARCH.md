# Phase 7: Automatic Cycle Transitions - Research

**Researched:** 2026-05-29
**Domain:** PostgreSQL PL/pgSQL scheduled jobs (pg_cron), transactional outbox pattern, Litestar async lifespan background tasks, RabbitMQ publishing
**Confidence:** HIGH (all findings verified against the actual codebase; no external library uncertainty — this is a pure "follow existing patterns" phase)

## Summary

Phase 7 is almost entirely a "compose existing, proven patterns" phase, not a greenfield design. Every primitive it needs already exists in the codebase:

- The pg_cron + advisory-lock + idempotent-scheduling pattern is fully demonstrated in `store.check_and_rotate()` (`0013_coin_store.sql`). The new `tournaments.process_cycle_transitions()` function is a near-copy with tournament-specific body.
- The outbox table (`tournaments.pending_transitions`) and its three repository methods (`create_pending_transition`, `fetch_unpublished_transitions`, `mark_transition_published`) **already exist** in `tournaments_repository.py` — written ahead during prior phases. The bridge mostly needs to *wire them into a poller*, plus harden `fetch_unpublished_transitions` with `FOR UPDATE SKIP LOCKED` (D-11 requires this and the current query lacks it).
- The SDK event structs (`TournamentCycleStartedEvent`, `TournamentCycleCompletedEvent`) **already exist** but are minimal (`cycle_id`, `category_id`, `map_id` / `cycle_id`, `category_id`). The placement-snapshot and map-detail payloads described in D-08/D-09 do **not** fit these structs — this is the single most important struct decision the planner must make (see "SDK Event Structs" below).
- The Litestar lifespan pattern is shown by `rabbitmq_connection` in `app.py`; the outbox poller is a second `@asynccontextmanager` lifespan that spawns an `asyncio.Task` and cancels it on shutdown.

The "architecturally novel" flag from STATE.md refers to the **outbox→RabbitMQ bridge being the first long-running background poller in this codebase** (the existing rabbitmq lifespan only sets up a pool; it does not run a loop). That is the one genuinely new mechanism and the main thing to validate.

**Primary recommendation:** Implement the transition entirely in SQL following the `check_and_rotate` template (transaction-level advisory lock, `make_interval` for end-time math), write both outbox rows inside the same function transaction, and add a standalone `tournament_outbox_poller` lifespan task that uses `FOR UPDATE SKIP LOCKED` publish-then-mark. For the D-06 map pre-roll duplication risk, **recommend the SQL helper `tournaments.select_eligible_map()`** (keeps the transition atomic and self-contained) but flag the duplication explicitly; the API-pre-roll alternative is viable and lower-duplication but introduces an ordering dependency the planner should weigh.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Detect due cycles + run transition | Database (pg_cron + PL/pgSQL) | — | D-01: DB owns scheduled work; matches `store.check_and_rotate`. API must not drive cycle timing. |
| Concurrency control for transition | Database (advisory lock) | — | D-02: lock lives inside the SQL function; only the DB sees concurrent cron ticks. |
| Compute final placements | Database (PL/pgSQL embedding leaderboard SQL) | — | D-08: snapshot computed at finalization, embedded as JSON; reuses `fetch_leaderboard` ranking logic. |
| Pre-roll next map | Database (SQL helper) *recommended* | API (on event receipt) *alternative* | D-06: keeps transition atomic; alternative reuses Phase 5 Python but breaks atomicity. |
| Write outbox rows | Database (inside transition txn) | — | D-03/D-09: outbox write is part of the atomic transition. |
| Poll outbox + publish to RabbitMQ | API (Litestar lifespan asyncio task) | — | D-10: bot never writes DB; only the API holds the RabbitMQ channel pool and publishes. |
| Mark rows published | API (same txn as the select, `FOR UPDATE SKIP LOCKED`) | — | D-11: prevents double-publish across API instances. |
| Consume events (announcements, rewards) | OUT OF SCOPE | — | Phases 8/9. This phase only *produces* events. |

## Standard Stack

No new libraries. Everything is already in the dependency tree (verified in `apps/api/pyproject.toml` and CLAUDE.md tech stack).

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pg_cron | (DB extension, loaded via `infra/postgres/Dockerfile`) | Periodic invocation of the transition function | `[VERIFIED: codebase]` Already the scheduler for `store.check_and_rotate` and quest rotation. `shared_preload_libraries=pg_cron`, `cron.database_name=genjishimada`. |
| asyncpg | `>=0.30.0` | Pool + connection for the outbox poller | `[VERIFIED: codebase]` `state.db_pool` is the litestar-asyncpg pool. |
| aio-pika | `>=9.5.5` | Publishing via `mq_channel_pool` | `[VERIFIED: codebase]` Used by `BaseService.publish_message`. |
| msgspec | `>=0.19.0` | Encode event payloads; jsonb codec round-trips | `[VERIFIED: codebase]` `_async_pg_init` registers jsonb↔msgspec codec. |
| Litestar | `>=2.16.0` | `lifespan=[...]` async context managers for background task | `[VERIFIED: codebase]` `rabbitmq_connection` is the template. |

**Installation:** None required.

## Package Legitimacy Audit

Not applicable — this phase installs **zero** external packages. All primitives are already present in the project. No slopcheck/registry verification needed.

## Architecture Patterns

### System Architecture Diagram

```
                          pg_cron tick (every minute, '* * * * *')
                                      │
                                      ▼
              ┌──────────────────────────────────────────────┐
              │  tournaments.process_cycle_transitions()       │
              │                                                │
              │  1. pg_advisory_xact_lock(<LOCK_CONST>)        │  ◄── concurrency gate (D-02)
              │       (or pg_try_advisory_lock + EXCEPTION)    │
              │  2. FOR each cycle WHERE status='active'       │  ◄── due detection (D-04)
              │         AND now() >= started_at +              │
              │         make_interval(days=>freq_days):        │
              │       a. UPDATE cycle -> 'finalizing'          │  ◄── stops submissions (D-01)
              │       b. compute placements (RANK() snapshot)  │  ◄── D-08
              │       c. UPDATE cycle -> 'completed', ended_at │
              │       d. INSERT pending_transitions            │
              │            (cycle_completed, payload=standings)│  ◄── outbox write (D-09)
              │       e. promote category's pending cycle      │  ◄── D-05
              │            -> 'active', started_at=now()        │
              │       f. INSERT pending_transitions            │
              │            (cycle_started, payload=map+timing) │  ◄── outbox write (D-09)
              │       g. pre-roll NEXT pending cycle via        │  ◄── D-06 (select_eligible_map)
              │            select_eligible_map(category_id)     │
              │  3. (xact lock auto-releases on COMMIT)        │
              └──────────────────────────────────────────────┘
                                      │
                       writes rows to │
                                      ▼
              ┌──────────────────────────────────────────────┐
              │  tournaments.pending_transitions (outbox)      │
              │  (published=FALSE rows accumulate)             │
              └──────────────────────────────────────────────┘
                                      │
              poll every ~10s (D-12)  │  (separate connection from API pool)
                                      ▼
              ┌──────────────────────────────────────────────┐
              │  tournament_outbox_poller (Litestar lifespan)  │
              │                                                │
              │  BEGIN;                                        │
              │  SELECT * FROM pending_transitions             │
              │    WHERE published=FALSE                       │
              │    ORDER BY created_at                         │
              │    FOR UPDATE SKIP LOCKED;                     │  ◄── D-11 multi-instance safe
              │  for each row:                                 │
              │    publish_message(routing_key=                │  ◄── D-10
              │      'api.tournament.cycle_started'|completed,  │
              │      data=event_struct, idempotency_key=...)   │  ◄── cycle-scoped key
              │    UPDATE ... SET published=TRUE WHERE id=$1;   │  ◄── publish-then-mark (at-least-once)
              │  COMMIT;                                        │
              └──────────────────────────────────────────────┘
                                      │
                            api.tournament.* queues
                                      ▼
                       (Phase 9 bot consumers — out of scope)
```

### Pattern 1: pg_cron-driven PL/pgSQL function (the canonical template)

**What:** A `LANGUAGE plpgsql` function does the work; a `DO` block at the bottom of the migration registers it with pg_cron, guarded so it no-ops where pg_cron is absent (local/tests).
**When to use:** D-01 — the transition function.
**Exact idempotent registration block the new migration MUST follow** (verbatim pattern from `0013_coin_store.sql` §280-300):

```sql
-- Source: apps/api/migrations/0013_coin_store.sql §280-300 [VERIFIED: codebase]
DO $body$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        -- Unschedule existing job first so migration re-runs are idempotent
        PERFORM cron.unschedule('tournament-cycle-transitions') WHERE EXISTS (
            SELECT 1 FROM cron.job WHERE jobname = 'tournament-cycle-transitions'
        );
        PERFORM cron.schedule(
            'tournament-cycle-transitions',
            '* * * * *',                                   -- D-12: every minute
            'SELECT tournaments.process_cycle_transitions()'
        );
        RAISE NOTICE 'Scheduled pg_cron job: tournament-cycle-transitions';
    ELSE
        RAISE NOTICE 'pg_cron extension not available, skipping cron scheduling';
    END IF;
END $body$;
```

> NOTE on two variants in the codebase: `0013` guards on `pg_extension WHERE extname='pg_cron'`; `0014` guards on `pg_namespace WHERE nspname='cron'` and uses `$cron$...$cron$` dollar-quoting. Both work. **Use the `0013` form** — it is the canonical reference per CONTEXT D-01 and includes the `cron.unschedule` idempotency guard that `0014` omits.

Also include the extension-creation guard at the top (from `0013` §7-13):

```sql
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS pg_cron;
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'pg_cron extension not available, skipping cron scheduling';
END $$;
```

**Next sequential migration number:** Current highest is `0020_tournaments.sql` `[VERIFIED: codebase — ls migrations/]`. The new file is **`0021_tournament_cycle_transitions.sql`**. Put the transition function, the optional `select_eligible_map` helper, and the cron registration in this single file (Claude's discretion per D-47; one file keeps the feature cohesive).

### Pattern 2: Advisory lock — RECOMMENDATION: transaction-level

**What:** Gate concurrent cron ticks.
**Two options observed:**
- `store.check_and_rotate` (§237-261): session-level `pg_try_advisory_lock(1234567890)` + manual `pg_advisory_unlock` + `EXCEPTION WHEN OTHERS` re-unlock. `[VERIFIED: codebase]`
- `store_service.py:578`: transaction-level `pg_advisory_xact_lock(hashtext($1))` — auto-releases on COMMIT/ROLLBACK. `[VERIFIED: codebase]`

**RECOMMENDATION: use transaction-level `pg_advisory_xact_lock(<LOCK_CONST>)`.** Rationale:
- The entire transition runs inside the function's implicit transaction (a plpgsql function called via `SELECT` runs in one transaction). `pg_advisory_xact_lock` auto-releases on commit/rollback — no `EXCEPTION` cleanup boilerplate, no risk of a leaked lock if an unexpected error path skips the unlock.
- D-02 explicitly permits this: "Planner may prefer `pg_advisory_xact_lock` for auto-release — acceptable equivalent."
- Use the **non-blocking** variant if you want overlapping ticks to no-op cleanly: `pg_try_advisory_xact_lock(<CONST>)` returning boolean; `IF NOT acquired THEN RETURN; END IF;`. (Blocking `pg_advisory_xact_lock` would queue ticks, which is also acceptable but less clean for a "skip if busy" semantic.)

**Lock constant — pick a value that does NOT collide.** Existing advisory lock IDs `[VERIFIED: codebase — grep]`:
- `1234567890` — store rotation (`0013_coin_store.sql:237`)
- `hashtext('quest_provision:{user_id}:{rotation_id}')` — quest provisioning (`store_service.py:578`), per-user dynamic
- A commented-out `pg_advisory_xact_lock((NEW.user_id << 32) | NEW.map_id)` in `0001_init.sql:501` (disabled)

**Recommend a fixed, documented constant such as `2025070100` (or any unique bigint) for tournament transitions**, with a SQL comment noting it must not collide with `1234567890`. A single global lock is correct per D-02 ("One transition run processes all due cycles; overlapping cron ticks no-op").

### Pattern 3: End-time computation (D-04) — inline, no schema change

**Confirmed `[VERIFIED: codebase — 0020_tournaments.sql §59-69]`:** `tournaments.cycles` has only `started_at timestamptz` and `ended_at timestamptz`; there is **no `scheduled_end_at` column**. `tournaments.categories.cycle_frequency` is `text CHECK (cycle_frequency IN ('weekly','biweekly'))` `[VERIFIED: §36-37]`.

**Exact "due" predicate** (frequency lives on the category, so join):

```sql
-- weekly -> 7 days, biweekly -> 14 days
SELECT cy.id, cy.category_id, cy.map_id, cat.cycle_frequency
FROM tournaments.cycles cy
JOIN tournaments.categories cat ON cat.id = cy.category_id
WHERE cy.status = 'active'
  AND now() >= cy.started_at + make_interval(
        days => CASE cat.cycle_frequency WHEN 'biweekly' THEN 14 ELSE 7 END
      );
```

`make_interval(days => ...)` is the same primitive Phase 5 already uses (`fetch_eligible_maps`: `make_interval(weeks => $2)`) `[VERIFIED: codebase — tournaments_repository.py:558]`, so it is consistent and known-good.

### Pattern 4: Placement snapshot embedded as JSON (D-08)

Reuse the exact ranking expression from `fetch_leaderboard` `[VERIFIED: codebase — tournaments_repository.py:889-911]`: `DISTINCT ON (user_id)` best-per-user, then `RANK() OVER (ORDER BY verified DESC, time ASC)`. In PL/pgSQL, aggregate the ranked rows into a JSON array with `jsonb_agg` / `json_build_object` and store it in `pending_transitions.payload`:

```sql
-- inside process_cycle_transitions, for the finishing cycle v_cycle_id:
SELECT jsonb_agg(
         jsonb_build_object(
           'rank', ranked.rank,
           'user_id', ranked.user_id,
           'name', ranked.name,
           'time', ranked.time,
           'verified', ranked.verified,
           'completion', ranked.completion
         ) ORDER BY ranked.rank
       )
INTO v_standings
FROM (
    WITH best_per_user AS (
        SELECT DISTINCT ON (tc.user_id)
            tc.user_id, tc.time, tc.verified, tc.completion
        FROM tournaments.completions tc
        WHERE tc.cycle_id = v_cycle_id
        ORDER BY tc.user_id, tc.verified DESC, tc.time ASC
    )
    SELECT
        RANK() OVER (ORDER BY bpu.verified DESC, bpu.time ASC)::int AS rank,
        bpu.user_id,
        COALESCE(u.global_name, u.nickname, 'Unknown') AS name,
        bpu.time::float AS time,
        bpu.verified, bpu.completion
    FROM best_per_user bpu
    JOIN core.users u ON u.id = bpu.user_id
) ranked;
```

`v_standings` (jsonb) becomes part of the `cycle_completed` payload. `COALESCE(v_standings, '[]'::jsonb)` to handle zero-submission cycles.

### Pattern 5: Outbox poller as a Litestar lifespan task (D-10/D-11) — the genuinely new mechanism

**Template:** `rabbitmq_connection` in `app.py` §48-66 `[VERIFIED: codebase]` is an `@asynccontextmanager` added to `lifespan=[...]` (§204). It currently only *sets up* the channel pool; it does not run a loop. The poller adds the first long-running background loop.

```python
# apps/api/app.py — new lifespan, added to lifespan=[rabbitmq_connection, tournament_outbox_poller]
import asyncio
import contextlib

@asynccontextmanager
async def tournament_outbox_poller(_app: Litestar) -> AsyncGenerator[None, None]:
    """Poll the tournaments outbox and publish pending transition events."""
    async def _loop() -> None:
        from services.tournament_outbox_service import publish_pending_transitions  # local import avoids cycles
        while True:
            try:
                await publish_pending_transitions(_app.state)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("[!] tournament outbox poll failed")
            await asyncio.sleep(10)  # D-12 cadence

    task = asyncio.create_task(_loop())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
```

**The publish function** (recommend a small dedicated service or module function rather than overloading `TournamentService`, per D-48 discretion):

```python
async def publish_pending_transitions(state: State) -> None:
    pool = state.db_pool
    service = TournamentOutboxService(pool, state)  # extends BaseService for publish_message
    async with pool.acquire() as conn, conn.transaction():
        rows = await conn.fetch(
            """
            SELECT id, cycle_id, event_type, payload
            FROM tournaments.pending_transitions
            WHERE published = FALSE
            ORDER BY created_at ASC
            FOR UPDATE SKIP LOCKED
            """
        )
        for row in rows:
            event, routing_key = _build_event(row)        # map event_type -> struct + queue
            headers = Headers({})                          # NOT pytest -> real publish
            await service.publish_message(
                routing_key=routing_key,
                data=event,
                headers=headers,
                idempotency_key=f"tournament:{row['event_type']}:{row['cycle_id']}",
            )
            await conn.execute(
                "UPDATE tournaments.pending_transitions SET published = TRUE WHERE id = $1",
                row["id"],
            )
```

Key points:
- **`FOR UPDATE SKIP LOCKED`** — D-11. The existing `fetch_unpublished_transitions` repo method (line 986-1006) lacks this clause; either harden it or use inline SQL in the poller. Locking + mark-in-same-transaction means a second API instance polling concurrently skips already-locked rows.
- **Publish-then-mark ordering** — D-11 favors at-least-once. A crash between `publish_message` and `UPDATE published=TRUE` re-publishes on the next poll. Downstream idempotency (Phase 9) dedupes. Cycle-scoped idempotency keys (`tournament:cycle_started:<cycle_id>`) make duplicates harmless.
- **Pool acquisition** — the poller gets the asyncpg pool from `_app.state.db_pool` (the litestar-asyncpg-managed pool). It must acquire its *own* connection (not a request-scoped `conn`), because it runs outside any HTTP request.
- **Graceful shutdown** — `task.cancel()` + `suppress(CancelledError)` in the `finally` of the context manager. The `asyncio.sleep(10)` is the cancellation point.

### Anti-Patterns to Avoid

- **Don't use the deprecated `handle_db_exceptions` decorator** (CLAUDE.md anti-pattern). The transition is pure SQL; the poller catches its own errors.
- **Don't have the bot or any consumer write to the DB** — the poller is API-side only; events flow API→RabbitMQ→bot (CLAUDE.md single-writer constraint).
- **Don't poll without `SKIP LOCKED`** — multiple API instances (dev + prod, or future horizontal scaling) would double-publish and double-insert `public.jobs` rows.
- **Don't `SELECT` the outbox and mark-published in separate transactions** — the window between them is the double-publish race D-11 closes.
- **Don't add a `scheduled_end_at` column** — D-04 / Deferred. Compute inline.
- **Don't select a fresh map at promotion time** — D-05: promote the pre-existing `pending` cycle; only *pre-roll the next one* afterward.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Periodic scheduling | A Python `asyncio` timer that triggers transitions | pg_cron calling `process_cycle_transitions()` | D-01: DB owns timing; survives API restarts; matches store/quest pattern. |
| Concurrency control | A Redis lock / app-level mutex | `pg_advisory_xact_lock` | Same connection as the work; auto-release; zero new infra. |
| Leaderboard ranking | New ranking SQL | The `fetch_leaderboard` `RANK() OVER (...)` expression | D-08: identical tie-break semantics already tested in Phase 6. |
| Outbox row CRUD | New repo methods | `create_pending_transition`, `fetch_unpublished_transitions`, `mark_transition_published` (already exist) | `[VERIFIED: codebase]` written ahead in tournaments_repository.py:947-1032. |
| RabbitMQ publish + job tracking | Direct `aio_pika` calls | `BaseService.publish_message` | Handles `public.jobs` record, idempotency, test-mode skip, persistent delivery. |
| End-time interval math | String concatenation of intervals | `make_interval(days => ...)` | Phase 5 already uses it; type-safe; no injection. |

**Key insight:** This phase has essentially nothing to invent. The one new *composition* (a long-running lifespan poller) is built from `rabbitmq_connection` (lifespan shape) + `publish_message` (publish) + standard `asyncio.Task` cancel-on-shutdown. Validate that composition; don't redesign it.

## THE KEY RISK: SQL map-selection helper duplication (D-06/D-07)

**The conflict:** Phase 5 implemented map selection in **Python** (`TournamentService.select_map`/`reroll_map` orchestrating `fetch_eligible_maps` + LRU fallback). The transition runs in **SQL** (pg_cron), so to pre-roll the next cycle inside the atomic transition it must re-express that selection logic in PL/pgSQL.

**The Phase 5 selection logic to mirror** `[VERIFIED: codebase — tournaments_repository.py:524-605]`:
1. `fetch_eligible_maps`: official + not archived + code not null + base-difficulty (regexp-stripped of trailing `-`/`+`) `= ANY(category.difficulties)` + NOT used in any cycle within `make_interval(weeks => blacklist_weeks)` + NOT in any `pending` cycle; `ORDER BY random()`.
2. If empty → `fetch_least_recently_used_map`: same difficulty filter, `LEFT JOIN cycles ... ORDER BY started_at ASC NULLS FIRST LIMIT 1`.

A PL/pgSQL `tournaments.select_eligible_map(p_category_id int) RETURNS int` can faithfully reproduce both queries (they are already pure SQL — the Python is just orchestration). The regexp (`regexp_replace(m.difficulty, '\s*[-+]\s*$', '', '')`), `make_interval`, and `random()` are all native SQL. **So yes, it can be faithfully reimplemented** — the duplication is real but mechanical and low-ambiguity.

### Recommendation (planner decides; both satisfy D-06):

**OPTION A — SQL helper `tournaments.select_eligible_map(category_id)` (RECOMMENDED).**
- *Pros:* Transition stays fully atomic and self-contained; no cross-process ordering; pre-roll happens in the same transaction as promotion, so a category always has a pending cycle the instant the cron tick commits. Matches D-01's "DB owns the work."
- *Cons:* Duplicates the Phase 5 selection SQL in PL/pgSQL. Future changes to selection rules must be made in two places. Mitigate by (a) copying the SQL verbatim with a comment cross-referencing `fetch_eligible_maps`, and (b) adding a test that asserts the SQL helper and the Python repo method return equivalent eligibility for the same inputs.

**OPTION B — API pre-rolls on receipt of the `cycle_started` event (the CONTEXT-flagged alternative).**
- *Pros:* Zero SQL duplication — reuses the exact Phase 5 `select_map` Python path. Single source of truth for selection rules.
- *Cons:* Breaks atomicity — between the transition committing and the bot/API processing `cycle_started`, the category has an active cycle but **no pending pre-roll**. If the next transition fires before the pre-roll completes, D-07's "no pending cycle exists" edge path triggers (inline selection or warning). Introduces a dependency on the poller→consumer→API round trip succeeding. More moving parts for the same outcome.

**Verdict:** Recommend **Option A**. The duplication is bounded and testable; atomicity and self-containment are worth more than DRY here, and D-01 already commits to "the DB owns the work." Document the duplication as a known maintenance cost. Implement D-07 edge handling inside the SQL function: if `select_eligible_map` returns NULL (no eligible map *and* LRU empty), `RAISE NOTICE` and skip pre-roll for that category (leave it without a pending cycle) rather than aborting the whole run — mirrors Phase 5's `NoEligibleMapsError` handling but downgraded to a warning since cron can't surface an exception to a user.

## SDK Event Structs (D-09) — IMPORTANT MISMATCH

**Existing structs** `[VERIFIED: codebase — libs/sdk/src/genjishimada_sdk/tournaments.py:403-427]`:

```python
class TournamentCycleStartedEvent(Struct):
    cycle_id: int
    category_id: int
    map_id: int

class TournamentCycleCompletedEvent(Struct):
    cycle_id: int
    category_id: int
```

**D-08/D-09 require richer payloads:** `cycle_completed` must carry final standings/placements + winner; `cycle_started` must carry category, map id/code/name, started_at, computed end time. **The current structs do NOT hold these fields.** This is a real gap the planner must resolve. Options:

1. **Extend the existing structs** (recommended — minimal churn, Phase 2 decision was "define all 4 upfront"): add fields to `TournamentCycleCompletedEvent` (e.g., `standings: list[TournamentLeaderboardEntryResponse]`, `winner_user_id: int | None`) and `TournamentCycleStartedEvent` (e.g., `map_code: str`, `map_name: str`, `started_at: datetime`, `ends_at: datetime`). Downstream phases consume these.
2. Keep the structs lean (just IDs) and have downstream re-query — but D-08 explicitly says "downstream read placements straight from the event payload," so the payload must be self-sufficient. **Do not** choose this; it contradicts D-08.

**Critical alignment requirement:** The JSON the SQL function writes into `pending_transitions.payload` must deserialize cleanly into whatever the final struct shape is. Because `msgspec.json.decode` (via the jsonb codec) and `publish_message`'s `msgspec.json.encode(data)` are symmetric, the planner must keep three things in sync:
- the `jsonb_build_object` field names the SQL function emits,
- the SDK struct field names,
- the `_build_event` mapping in the poller that `msgspec.convert`s the payload dict into the struct.

**Recommend:** the poller does `msgspec.convert(row["payload"], TournamentCycleStartedEvent)` (payload already a dict via jsonb codec) and publishes the struct. This forces the SQL payload shape and the struct to match, surfacing mismatches as test failures immediately. Add the SDK struct edits to the SDK barrel `__init__.py` if any new sub-struct is introduced (CLAUDE.md SDK convention).

## RabbitMQ Queue Names & Idempotency

**Convention** `[VERIFIED: CLAUDE.md + base.py IGNORE_IDEMPOTENCY]`: `api.<domain>.<action>`. Existing tournament event structs exist but **no tournament queue is wired yet** (no `api.tournament.*` entry in `IGNORE_IDEMPOTENCY`, no consumer — this phase introduces publishing). Recommended routing keys:
- `api.tournament.cycle_started`
- `api.tournament.cycle_completed`

**Idempotency decision:** `publish_message` raises `ValueError` if `routing_key not in IGNORE_IDEMPOTENCY and not idempotency_key` `[VERIFIED: base.py:75-76]`. Two valid paths:
- **(Recommended)** Pass a cycle-scoped `idempotency_key=f"tournament:{event_type}:{cycle_id}"` and do **not** add these queues to `IGNORE_IDEMPOTENCY`. This gives at-least-once + downstream dedup (D-11) and the message's `message_id` header becomes the idempotency key, which Phase 9 consumers can claim against `public.idempotency_claims`.
- (Alternative) Add `api.tournament.cycle_started`/`cycle_completed` to `IGNORE_IDEMPOTENCY` if Phase 9 will dedupe by cycle_id at the application level instead. Less safe; not recommended given D-11 explicitly plans cycle-scoped idempotency keys.

**Note:** `publish_message` inserts a `public.jobs` row per publish. On re-publish after a crash, a new job row is created (the old one stays). That is acceptable for an outbox/at-least-once design but worth a one-line note in the plan.

## Runtime State Inventory

This is a backend feature-addition phase, not a rename/refactor. Section included for completeness; most categories are empty.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | New rows in `tournaments.pending_transitions` (outbox); cycle status mutations in `tournaments.cycles`. No data migration of existing rows. | Code/SQL only. |
| Live service config | **pg_cron job `tournament-cycle-transitions` registered inside the migration** via `cron.schedule`. This is OS/DB-registered state created by the migration, not separate manual config. Idempotent `cron.unschedule`-before-`cron.schedule` guard handles re-runs. | Handled by migration `DO` block; verify in dev after deploy with `SELECT * FROM cron.job`. |
| OS-registered state | None — no Task Scheduler / systemd / pm2 changes. | None. |
| Secrets/env vars | None new. Poller uses existing `state.db_pool` and `mq_channel_pool` (already configured via existing env vars). | None. |
| Build artifacts | SDK struct changes (if structs extended) require `just sync`/`just fix` so API + bot pick up the updated `genjishimada-sdk`. | Run `just fix` after SDK edits (MEMORY.md note: SDK import failures fixed by `just fix`). |

## Common Pitfalls

### Pitfall 1: pg_cron not present in tests → function-creation must not depend on cron
**What goes wrong:** Writing the function so it can only be exercised via cron, or letting the migration fail when pg_cron is absent.
**Why it happens:** Test postgres image does not load pg_cron `[VERIFIED: codebase — conftest applies all migrations via `_apply_sql_dir`; `0013`/`0014` guards prove cron is absent in tests, the `RAISE NOTICE` branch fires]`.
**How to avoid:** The function is created unconditionally (plain `CREATE OR REPLACE FUNCTION`); only the `cron.schedule` call is guarded by the `pg_extension` check. Tests invoke the function directly: `SELECT tournaments.process_cycle_transitions();` — exactly how store/quest cron functions are tested (`SELECT store.check_and_generate_quest_rotation()` appears in 7 test files) `[VERIFIED: codebase — grep]`.
**Warning signs:** Migration errors in test DB; function only reachable via cron.

### Pitfall 2: Forgetting `FOR UPDATE SKIP LOCKED` → double-publish
**What goes wrong:** Two API instances (dev API + a second worker, or future scaling) both select the same unpublished rows and publish twice, also inserting two `public.jobs` rows.
**Why it happens:** The existing `fetch_unpublished_transitions` repo method (line 986) is a plain `SELECT ... WHERE published=FALSE` with no row locking.
**How to avoid:** D-11 — add `FOR UPDATE SKIP LOCKED` and mark-published in the same transaction. Either harden the repo method or use inline SQL in the poller.
**Warning signs:** Duplicate `cycle_started`/`cycle_completed` in RabbitMQ; duplicate job rows.

### Pitfall 3: Advisory lock leak (session-level variant)
**What goes wrong:** If you choose session-level `pg_try_advisory_lock` and an error path skips the `pg_advisory_unlock`, the lock persists for the session, blocking all future ticks until the connection closes.
**Why it happens:** Missing `EXCEPTION WHEN OTHERS` re-unlock (the `0013` pattern includes it precisely for this reason).
**How to avoid:** Prefer `pg_advisory_xact_lock` (auto-release on commit/rollback) per the recommendation above. If session-level is used, replicate the `0013` EXCEPTION cleanup exactly.
**Warning signs:** Transitions silently stop firing; `pg_locks` shows a stuck advisory lock.

### Pitfall 4: `finalizing` already rejects submissions — don't add redundant logic
**What goes wrong:** Planner adds new submission-rejection code, duplicating existing behavior.
**Why it happens:** Not checking the Phase 6 submission flow.
**How to avoid / Confirmed:** `submit_completion` already does `if cycle["status"] != "active": raise CycleNotActiveError(...)` `[VERIFIED: codebase — tournament_service.py:498-499]`. Setting status to `finalizing` (or `completed`) **automatically rejects new submissions** — success criterion 2's "rejecting new submissions" is satisfied with zero new submission code. The only requirement is that the transition sets `finalizing` *before* computing placements (so no submission lands mid-snapshot). Because the whole transition is one transaction with the advisory lock held, in-flight submissions either commit before the lock/status change or fail the `status='active'` check afterward.
**Warning signs:** Duplicate rejection logic; a test asserting submissions during `finalizing` fail (already true).

### Pitfall 5: jsonb payload field-name drift between SQL and SDK struct
**What goes wrong:** `msgspec.convert(payload, EventStruct)` raises at publish time because the SQL `jsonb_build_object` keys don't match struct fields.
**Why it happens:** Three places must agree (SQL emit, SDK struct, poller convert) and they're edited separately.
**How to avoid:** Decode-to-struct in the poller (`msgspec.convert(row["payload"], Struct)`) so any drift fails fast in tests; add an integration test that runs the transition then asserts the published payload deserializes.
**Warning signs:** `msgspec.ValidationError` in the poller; events silently failing to publish (caught by the poller's broad `except`).

### Pitfall 6: Poller broad `except` swallowing the bug
**What goes wrong:** The poller's `except Exception: log.exception(...)` hides a persistent failure (e.g., struct mismatch) — rows never get marked published and re-fail every 10s forever.
**How to avoid:** Keep the broad catch (so one bad row doesn't kill the loop) but ensure per-row failures don't block other rows, and surface via Sentry (`log.exception` is captured by the API Sentry integration). Consider a failure counter / dead-letter for rows that fail repeatedly (can be deferred — note it).
**Warning signs:** Outbox table grows unbounded with `published=FALSE`; repeated identical exceptions in logs.

## Code Examples

### Transition function skeleton (assembles Patterns 1-4)
```sql
-- Source: synthesized from 0013_coin_store.sql + tournaments_repository.py ranking/selection SQL
CREATE OR REPLACE FUNCTION tournaments.process_cycle_transitions()
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_due       record;
    v_pending   record;
    v_standings jsonb;
    v_next_map  int;
BEGIN
    -- Non-blocking transaction-level lock; auto-released on commit (D-02)
    IF NOT pg_try_advisory_xact_lock(2025070100) THEN
        RAISE NOTICE 'Cycle transition already in progress, skipping';
        RETURN;
    END IF;

    FOR v_due IN
        SELECT cy.id, cy.category_id, cy.map_id, cat.cycle_frequency
        FROM tournaments.cycles cy
        JOIN tournaments.categories cat ON cat.id = cy.category_id
        WHERE cy.status = 'active'
          AND now() >= cy.started_at + make_interval(
                days => CASE cat.cycle_frequency WHEN 'biweekly' THEN 14 ELSE 7 END)
    LOOP
        -- a. stop submissions
        UPDATE tournaments.cycles SET status = 'finalizing' WHERE id = v_due.id;

        -- b. snapshot placements (Pattern 4) into v_standings ...

        -- c. complete
        UPDATE tournaments.cycles
        SET status = 'completed', ended_at = now()
        WHERE id = v_due.id;

        -- d. outbox: cycle_completed
        INSERT INTO tournaments.pending_transitions (cycle_id, event_type, payload)
        VALUES (v_due.id, 'cycle_completed',
                jsonb_build_object('cycle_id', v_due.id,
                                   'category_id', v_due.category_id,
                                   'standings', COALESCE(v_standings, '[]'::jsonb)));

        -- e. promote pending cycle (D-05)
        SELECT * INTO v_pending
        FROM tournaments.cycles
        WHERE category_id = v_due.category_id AND status = 'pending'
        LIMIT 1;

        IF v_pending.id IS NOT NULL THEN
            UPDATE tournaments.cycles
            SET status = 'active', started_at = now()
            WHERE id = v_pending.id;

            -- f. outbox: cycle_started (payload joins core.maps for code/name + computed end)
            INSERT INTO tournaments.pending_transitions (cycle_id, event_type, payload)
            SELECT v_pending.id, 'cycle_started',
                   jsonb_build_object('cycle_id', v_pending.id,
                                      'category_id', v_due.category_id,
                                      'map_id', v_pending.map_id,
                                      'map_code', m.code,
                                      'map_name', m.map_name,
                                      'started_at', now(),
                                      'ends_at', now() + make_interval(
                                          days => CASE v_due.cycle_frequency WHEN 'biweekly' THEN 14 ELSE 7 END))
            FROM core.maps m WHERE m.id = v_pending.map_id;
        ELSE
            RAISE NOTICE 'No pending cycle for category %, pre-rolling inline (D-07)', v_due.category_id;
            -- inline select + create active cycle ...
        END IF;

        -- g. pre-roll NEXT pending cycle (D-06) via helper
        v_next_map := tournaments.select_eligible_map(v_due.category_id);
        IF v_next_map IS NOT NULL THEN
            INSERT INTO tournaments.cycles (category_id, map_id) VALUES (v_due.category_id, v_next_map);
        ELSE
            RAISE NOTICE 'No eligible map to pre-roll for category % (D-07)', v_due.category_id;
        END IF;
    END LOOP;
END;
$$;
```

### Test invocation (no cron needed)
```python
# Source: pattern from test_store_integration.py / test_quest_lifecycle.py [VERIFIED: codebase]
async with asyncpg_pool.acquire() as conn:
    await conn.execute("SELECT tournaments.process_cycle_transitions()")
    # then assert cycle status + pending_transitions rows
```

## State of the Art

No external "state of the art" shift applies — this is internal-pattern reuse. The transactional outbox pattern (write event to a DB table in the same transaction as the state change, separate process publishes) is a well-established microservices pattern; the codebase is adopting it for the first time here, which is exactly STATE.md's "architecturally novel for this codebase" flag.

**Deprecated/outdated in this codebase (avoid):**
- `handle_db_exceptions` decorator — superseded by domain-exception hierarchy (CLAUDE.md). Not relevant to pure-SQL transition but don't introduce it in the poller.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `0014`-style `pg_namespace` guard and `0013`-style `pg_extension` guard are functionally equivalent; recommend `0013` form | Pattern 1 | Low — both verified present and working in the codebase; choice is stylistic. |
| A2 | Recommended advisory lock constant `2025070100` does not collide | Pattern 2 | Low — verified only `1234567890` and dynamic `hashtext(...)` keys exist; any unique bigint works. Planner picks final value. |
| A3 | Extending the existing SDK event structs (rather than adding new ones) is the lower-churn path | SDK Event Structs | Medium — if Phase 9 already assumed lean structs, extension is still backward-additive, but planner should confirm Phase 9/8 expectations. |
| A4 | `api.tournament.cycle_started` / `api.tournament.cycle_completed` are the right routing keys | RabbitMQ section | Low — follows documented `api.<domain>.<action>` convention; no existing tournament queue to conflict. |
| A5 | The test Postgres image lacks pg_cron (so direct `SELECT fn()` is the test path) | Pitfall 1 / Testing | Low — strongly implied by the guards firing the `RAISE NOTICE` branch and store/quest functions being tested via direct `SELECT`. Not 100% confirmed by inspecting the image, but the defensive guards make this safe regardless. |

## Open Questions

1. **Do Phases 8/9 dictate the exact event payload field names?**
   - What we know: D-08/D-09 say standings + map details go in the payload; existing structs are lean.
   - What's unclear: whether downstream phases have pre-committed to specific field names.
   - Recommendation: Planner extends the SDK structs and treats the SQL `jsonb_build_object` keys as the contract; align Phase 8/9 consumers to these. Add a round-trip test.

2. **Single API instance or multiple in dev/prod?**
   - What we know: `FOR UPDATE SKIP LOCKED` makes the poller safe for N instances regardless.
   - What's unclear: current deployment runs one API container per env.
   - Recommendation: Implement `SKIP LOCKED` unconditionally (cheap insurance); no need to confirm instance count.

3. **Repeated-failure handling for stuck outbox rows (Pitfall 6).**
   - Recommendation: Out of scope for v1 of this phase; note as a follow-up. The broad `except` + Sentry surfaces it operationally.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| pg_cron | Scheduling `process_cycle_transitions` (prod/dev) | ✓ (prod/dev image) / ✗ (test image) | loaded via `infra/postgres/Dockerfile` | Tests invoke function directly via `SELECT` — no cron needed; migration guards skip scheduling when absent. |
| asyncpg pool (`state.db_pool`) | Outbox poller DB access | ✓ | `>=0.30.0` | — |
| RabbitMQ channel pool (`state.mq_channel_pool`) | Outbox poller publish | ✓ | aio-pika `>=9.5.5` | `X-PYTEST-ENABLED=1` skips real publish in tests. |
| pytest-databases[postgres] | Integration tests | ✓ | `>=0.14.0` | — |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** pg_cron absent in test DB — direct `SELECT tournaments.process_cycle_transitions()` is the established test invocation path.

## Validation Architecture

Nyquist validation is **enabled** (`.planning/config.json` → `workflow.nyquist_validation: true`).

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.3.5+ with pytest-asyncio (mode `auto`), pytest-databases[postgres], pytest-xdist |
| Config file | `apps/api/pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `uv run --directory apps/api pytest tests/integration/test_tournament_transitions.py -v -p no:xdist` (new file) |
| Full suite command | `just test-api` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CYCLE-01 | Due-cycle detection by computed end time (weekly=7d, biweekly=14d) | integration | `pytest tests/integration/test_tournament_transitions.py::test_detects_due_cycle -x` | ❌ Wave 0 |
| CYCLE-01 | Transition atomically sets finalizing→completed + promotes pending→active | integration | `...::test_transition_state_machine -x` | ❌ Wave 0 |
| CYCLE-01 | Submissions rejected once status is `finalizing`/`completed` | integration | `...::test_submission_rejected_during_finalizing -x` (verifies existing `CycleNotActiveError`) | ❌ Wave 0 |
| CYCLE-01 | Placement snapshot embedded in `cycle_completed` payload matches leaderboard ranking | integration | `...::test_completed_payload_standings -x` | ❌ Wave 0 |
| CYCLE-01 | Pre-roll: a new `pending` cycle exists after transition (D-06) | integration | `...::test_next_cycle_prerolled -x` | ❌ Wave 0 |
| CYCLE-01 | Edge: no pending cycle → inline select + warning (D-07) | integration | `...::test_missing_pending_cycle_edge -x` | ❌ Wave 0 |
| CYCLE-01 | Concurrent runs no-op via advisory lock (call function twice concurrently) | integration | `...::test_advisory_lock_concurrency -x` | ❌ Wave 0 |
| CYCLE-01 | Outbox poller publishes unpublished rows and marks them published | integration | `tests/integration/test_tournament_outbox.py::test_poller_publishes_and_marks -x` | ❌ Wave 0 |
| CYCLE-01 | Poller `FOR UPDATE SKIP LOCKED` prevents double-publish | integration | `...::test_skip_locked_no_double_publish -x` | ❌ Wave 0 |
| CYCLE-01 | At-least-once: row stays unpublished if publish fails (publish-then-mark) | integration | `...::test_publish_failure_leaves_unpublished -x` | ❌ Wave 0 |
| CYCLE-01 | `select_eligible_map` SQL helper matches Python `fetch_eligible_maps` eligibility | integration/repository | `tests/repository/tournaments/test_select_eligible_map.py -x` | ❌ Wave 0 |

### Critical behaviors that MUST be validated (Nyquist focus)
1. **Transition atomicity** — a failure mid-transition rolls back cleanly; no cycle left in `finalizing`; next tick retries.
2. **Advisory-lock concurrency safety** — overlapping invocations do not double-process a cycle.
3. **End-time detection accuracy** — weekly vs biweekly interval math; cycle exactly at boundary `now() >= started_at + interval`.
4. **Outbox at-least-once delivery** — publish-then-mark; crash window re-publishes; no lost events.
5. **Submission rejection during finalizing** — confirms existing `status != 'active'` guard rejects (no new code, but assert it).
6. **Payload↔struct round-trip** — `cycle_completed`/`cycle_started` payloads deserialize into SDK structs without `ValidationError`.

### Sampling Rate
- **Per task commit:** quick run of the relevant new test file (`-p no:xdist`).
- **Per wave merge:** `just test-api` (full suite, 8 workers).
- **Phase gate:** Full suite green before `/gsd:verify-work`.

### Wave 0 Gaps
- [ ] `tests/integration/test_tournament_transitions.py` — covers CYCLE-01 transition machinery (direct `SELECT tournaments.process_cycle_transitions()` invocation, no cron).
- [ ] `tests/integration/test_tournament_outbox.py` — covers CYCLE-01 outbox poller (publish, skip-locked, at-least-once).
- [ ] `tests/repository/tournaments/test_select_eligible_map.py` — covers SQL helper parity with Phase 5 Python selection.
- [ ] Existing fixtures (`create_test_category`, `create_test_cycle`, `create_test_tournament_completion` in `tests/repository/tournaments/conftest.py`) are reusable; may need a fixture to set `started_at` in the past to make a cycle "due" — the existing `create_test_cycle` already accepts `status` and `started_at` overrides, so `await create_test_cycle(cat, map, status="active", started_at=<past>)` works directly.
- [ ] No framework install needed (all present).

## Security Domain

`security_enforcement` is not set to `false` in config, so this section is included. This is an internal scheduled/background mechanism with no user-facing input surface in this phase.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No new auth surface; poller is internal, no endpoint added. |
| V3 Session Management | no | — |
| V4 Access Control | no | No new endpoints; transition is DB-internal, poller is API-internal. |
| V5 Input Validation | partial | Outbox payload is DB-generated (not user input); still `msgspec.convert` validates payload→struct before publish. |
| V6 Cryptography | no | No crypto; never hand-roll. |

### Known Threat Patterns for PL/pgSQL + asyncpg + RabbitMQ
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection in dynamic interval/selection SQL | Tampering | All SQL is static or uses `$N` positional params / `make_interval(days => int)`; never string-interpolate frequency. (Frequency is a CHECK-constrained enum, but still mapped via `CASE`, not concatenation.) |
| Double-publish / event duplication | (Repudiation / integrity) | `FOR UPDATE SKIP LOCKED` + cycle-scoped idempotency keys + downstream dedup (Phase 9). |
| Advisory lock leak (DoS on scheduler) | Denial of Service | Transaction-level lock auto-releases; if session-level, EXCEPTION cleanup. |
| Unbounded outbox growth from a poison row | Denial of Service | Per-row error isolation in poller; Sentry alerting; (follow-up) retry cap / DLQ. |

## Sources

### Primary (HIGH confidence — all codebase, VERIFIED)
- `apps/api/migrations/0013_coin_store.sql` — `store.check_and_rotate`, advisory lock, idempotent cron registration (§7-13, §225-300).
- `apps/api/migrations/0014_quests_system.sql` §449+ — second `cron.schedule` example.
- `apps/api/migrations/0020_tournaments.sql` — `cycles`, `categories`, `pending_transitions`, `completions` schema (§16-180).
- `apps/api/repository/tournaments_repository.py` — `fetch_eligible_maps` (524), `fetch_least_recently_used_map` (574), `fetch_leaderboard` (870), `create/fetch_unpublished/mark_transition_published` (947-1032).
- `apps/api/services/tournament_service.py` — `select_map` (239), `submit_completion` status check (498-499).
- `apps/api/services/base.py` — `publish_message`, `IGNORE_IDEMPOTENCY`, idempotency requirement (28-114).
- `apps/api/app.py` — `rabbitmq_connection` lifespan, `lifespan=[...]`, `_async_pg_init` jsonb codec (48-66, 84-98, 204).
- `apps/api/services/store_service.py:578` — `pg_advisory_xact_lock` example.
- `libs/sdk/src/genjishimada_sdk/tournaments.py` — event structs (403-457).
- `apps/api/tests/conftest.py` + `tests/repository/tournaments/conftest.py` — migration application, fixtures.
- `apps/api/tests/integration/test_quest_lifecycle.py`, `test_store_integration.py` — direct `SELECT store.fn()` cron-function test pattern.
- `.planning/config.json` — nyquist_validation enabled.

### Secondary / Tertiary
- None. No external sources needed; phase is internal-pattern composition.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new packages; every primitive verified in-repo.
- Architecture: HIGH — direct templates exist (`check_and_rotate`, `rabbitmq_connection`, leaderboard SQL). Only genuinely new piece is the lifespan poller loop, which is a small, well-understood composition.
- Pitfalls: HIGH — derived from reading the actual submission/lock/outbox code, not speculation.
- SDK struct mismatch (A3): MEDIUM — the gap is verified, but the resolution choice depends on Phase 8/9 expectations the planner should confirm.

**Research date:** 2026-05-29
**Valid until:** 2026-06-28 (stable — internal codebase patterns, no fast-moving external deps)
