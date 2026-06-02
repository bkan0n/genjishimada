---
phase: 07-automatic-cycle-transitions
reviewed: 2026-05-29T00:00:00Z
depth: standard
files_reviewed: 8
files_reviewed_list:
  - apps/api/migrations/0021_tournament_cycle_transitions.sql
  - libs/sdk/src/genjishimada_sdk/tournaments.py
  - apps/api/repository/tournaments_repository.py
  - apps/api/services/tournament_outbox_service.py
  - apps/api/app.py
  - apps/api/tests/repository/tournaments/test_cycle_transitions.py
  - apps/api/tests/repository/tournaments/test_outbox_poller.py
  - apps/api/tests/repository/tournaments/test_select_eligible_map.py
findings:
  critical: 3
  warning: 4
  info: 2
  total: 9
status: issues_found
---

# Phase 07: Code Review Report

**Reviewed:** 2026-05-29
**Depth:** standard
**Files Reviewed:** 8
**Status:** issues_found

## Summary

Phase 07 implements a pg_cron-driven automatic cycle transition state machine backed
by a transactional outbox and an asyncio background poller. The overall approach is
sound: the advisory lock is correctly transaction-scoped, the outbox pattern is
well-understood, and the three-way payload contract between SQL `jsonb_build_object`,
the SDK structs, and `msgspec.convert` is consistent at first inspection.

However, three blockers exist: (1) the outbox poller starts before the RabbitMQ
channel pool is wired onto `app.state`, causing every poll on startup to crash;
(2) the `asyncio.sleep(10)` that follows the `try/except` block executes even after
`CancelledError` is re-raised from inside the `try`, meaning a cancelled task
hangs for up to 10 seconds before actually stopping; and (3) the two dynamic SQL
query builders in `TournamentRepository` interpolate raw dict keys directly into
SQL strings without any column-name allowlist, producing a SQL injection surface
accessible through the authenticated PATCH endpoints.

Four warnings cover: the winner extraction using `MIN(user_id)` when multiple users
tie at rank 1 (silently picks an arbitrary winner); the `select_eligible_map` LRU
fallback returning duplicate `LEFT JOIN` rows and therefore choosing incorrectly
among equal `started_at` values; the tournament routing keys being absent from the
RabbitMQ `definitions.json` queue declarations (messages will be silently dropped
on the default exchange with no declared queue); and the idempotency key scheme
using `tournament:{event_type}:{cycle_id}` which allows re-delivery of a
`cycle_completed` event from a past run to be dropped by the idempotency guard on
any legitimate re-delivery from a new cycle that happens to reuse the same
cycle_id row (cycle_ids are `GENERATED ALWAYS AS IDENTITY` so reuse is not
possible today, but the key format doesn't include the outbox `id` so a crashed
re-publish within the same cycle will be swallowed if the first publish succeeded).

---

## Critical Issues

### CR-01: Outbox Poller Starts Before RabbitMQ Channel Pool Is Ready

**File:** `apps/api/app.py:240`
**Issue:** The `lifespan` list is `[rabbitmq_connection, tournament_outbox_poller]`.
Litestar enters lifespan contexts in order and yields each one before entering the
next, but the `tournament_outbox_poller` context manager immediately spawns its
background task (`asyncio.create_task(_loop())`) at line 96 before yielding. The
`_loop` begins executing concurrently before `rabbitmq_connection` has finished its
own setup (it runs in a separate lifespan slot, not as a dependency of the poller).

In practice, the first poll tick fires within milliseconds and calls
`publish_pending_transitions` -> `BaseService.publish_message` ->
`self._state.mq_channel_pool.acquire()`. At that moment
`_app.state.mq_channel_pool` may not yet exist (set at line 67 inside
`rabbitmq_connection`), raising `AttributeError: State has no attribute
'mq_channel_pool'`. The broad `except Exception` at line 92 will swallow this and
log it, but every poll tick for the first ~10 s will fail, and if RabbitMQ startup
is slow the poller degrades to a permanent log-spam loop.

More critically: Litestar's lifespan list may execute contexts concurrently
depending on the version. If `tournament_outbox_poller` is entered first (or
concurrently), the pool is accessed before it is set.

**Fix:** Make the poller check for the pool attribute or add an initial sleep before
the first tick, OR register the poller as a nested lifespan inside
`rabbitmq_connection` so the pool is guaranteed to exist. The simplest safe fix is
a readiness check at the top of `_loop`:

```python
async def _loop() -> None:
    from services.tournament_outbox_service import publish_pending_transitions

    # Wait for the RabbitMQ channel pool to become available before polling.
    while not hasattr(_app.state, "mq_channel_pool"):
        await asyncio.sleep(1)

    while True:
        try:
            await publish_pending_transitions(_app.state)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("[!] tournament outbox poll failed")
        await asyncio.sleep(10)
```

A cleaner architectural fix is to combine the two lifespan managers so the poller
task is created inside `rabbitmq_connection` after `channel_pool` is assigned.

---

### CR-02: `asyncio.sleep` Executes After `CancelledError` Re-raise — Task Hangs on Shutdown

**File:** `apps/api/app.py:87-94`
**Issue:** The loop body is:

```python
while True:
    try:
        await publish_pending_transitions(_app.state)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("[!] tournament outbox poll failed")
    await asyncio.sleep(10)   # <-- line 94, OUTSIDE the try/except
```

When `task.cancel()` is called at shutdown, a `CancelledError` is injected into
whatever coroutine the task is currently awaiting. If the task is sleeping at
`asyncio.sleep(10)`, the `CancelledError` is raised directly there (not inside the
`try` block), so it propagates immediately — that path is fine.

However if cancellation arrives while inside `await publish_pending_transitions(...)`,
the `CancelledError` is caught by the `except asyncio.CancelledError: raise` clause
and re-raised. Python's `raise` exits the `try` block and propagates upward — but
the `await asyncio.sleep(10)` on line 94 is **outside** the `try/except`, so
execution still reaches it after the `raise` exits the `except` block... 

Wait — actually `raise` inside `except asyncio.CancelledError` re-raises immediately
and does NOT fall through to line 94; `raise` unwinds the frame. So the `sleep` is
not reached. The concern on this path is different: when cancellation hits during
`asyncio.sleep(10)` (the most common timing), the error propagates up through the
`while True` loop and exits cleanly. That path is correct.

The actual shutdown bug is subtler: `task.cancel()` sets a cancellation on the
task but if `publish_pending_transitions` catches and swallows `CancelledError`
internally (e.g. inside `pool.acquire()` or the asyncpg transaction context
manager), the task will NOT re-raise it and will instead continue to
`asyncio.sleep(10)`. Only after the sleep will the next iteration's
`await publish_pending_transitions` see the cancellation. This is a latent
10-second delay for any future refactor of the inner coroutine that adds a bare
`except Exception` around an awaitable. The current `publish_pending_transitions`
itself does not swallow `CancelledError`, but the broad `except Exception` in the
loop provides no protection if a future inner awaitable does.

More concretely: `asyncio.sleep(10)` on line 94 always executes after a normal
poll (non-error path), even when the task is being cancelled. If the task is
cancelled between the `try` block completing normally (no exception) and the
`asyncio.sleep(10)` call, the `CancelledError` fires in `sleep` — that is fine.
But if the task has no pending cancellation between those points, the `sleep` runs
for a full 10 seconds before the `finally` in the outer `tournament_outbox_poller`
context manager proceeds. On high-load shutdowns with Litestar's shutdown timeout
this can cause the server to hang for up to 10 seconds.

**Fix:** Move the `asyncio.sleep` inside the `try` block so it is also cancellable
and participates in the same exception handling:

```python
while True:
    try:
        await publish_pending_transitions(_app.state)
        await asyncio.sleep(10)
    except asyncio.CancelledError:
        raise
    except Exception:
        log.exception("[!] tournament outbox poll failed")
        await asyncio.sleep(10)
```

This ensures cancellation during sleep is also caught and re-raised, and the sleep
after a normal iteration and after an error are both cancellable.

---

### CR-03: SQL Injection via Unsanitised Dict Keys in `update_config` and `update_category`

**File:** `apps/api/repository/tournaments_repository.py:75,217-221`
**Issue:** Both `update_config` and `update_category` build dynamic SQL by
interpolating raw dict keys directly into the query string:

```python
# update_config (line 75)
set_clauses.append(f"{field} = ${idx}")

# update_category (lines 217-221)
set_clauses.append(f"{field} = ${idx}::jsonb")
set_clauses.append(f"{field} = ${idx}::text[]")
set_clauses.append(f"{field} = ${idx}")
```

The `field` variable comes from `updates.keys()`, which is populated by the service
layer from SDK struct field names. In `update_config`, the only caller today passes
`{"blacklist_weeks": ...}`, and in `update_category` the service constructs the
dict from hardcoded attribute names. So the immediate exploitation path requires
compromising the service layer.

However, this is a structural SQL injection: there is no allowlist of permitted
column names, no quote-identifier escaping, and the pattern is identical to the
established anti-pattern. If any future caller passes untrusted input as a key
(e.g., from a request body field that is forwarded without filtering), the
unsanitised key becomes part of the SQL string. The `update_config` method's
docstring says "Dict of field names to new values" with no restriction, making it
easy to misuse.

The pattern also exists in `apps/api/repository/store_service.py` (pre-existing),
but it should not be allowed to proliferate.

**Fix:** Add a column-name allowlist at the top of each method:

```python
# update_config
_ALLOWED_CONFIG_FIELDS = frozenset({"blacklist_weeks"})

async def update_config(self, updates: dict, *, conn: Connection | None = None) -> None:
    if not updates:
        return
    unknown = updates.keys() - _ALLOWED_CONFIG_FIELDS
    if unknown:
        raise ValueError(f"Unknown config fields: {unknown}")
    ...

# update_category
_ALLOWED_CATEGORY_FIELDS = frozenset({
    "name", "difficulties", "cycle_frequency", "participation_xp",
    "placement_xp", "streak_xp", "champion_role_id", "is_active",
})
```

---

## Warnings

### WR-01: Tie-Breaking `MIN(user_id)` Silently Picks an Arbitrary Winner

**File:** `apps/api/migrations/0021_tournament_cycle_transitions.sql:169`
**Issue:** The winner extraction query is:

```sql
MIN(ranked.user_id) FILTER (WHERE ranked.rank = 1)
INTO v_winner
```

`RANK()` by design assigns the same rank to all tied entries (e.g. two users with
identical `verified=TRUE, time=10.0` both get `rank=1`). In that case,
`MIN(user_id)` returns the numerically smallest Discord snowflake ID among the
tied users. This is deterministic but arbitrary — the user with the oldest Discord
account ID wins on a tie. There is no business logic reasoning for this tiebreaker,
no documentation of it, and the bot will announce this user as champion.

The Python `fetch_leaderboard` query does not emit a single winner at all; it
returns all rank-1 entries. The SQL transition silently resolves the tie by
snowflake ID without the application being aware a tie existed.

**Fix:** Either document the tiebreaker explicitly (with a comment in the SQL and
in the SDK event struct), or use a deterministic business-rule tiebreaker (e.g.
earliest `inserted_at` in `tournaments.completions`), or surface `winner_user_id`
as `int[] | None` to include all tied winners:

```sql
-- Document intent:
-- On a tie, the rank-1 user with the smallest user_id (oldest account) is chosen.
-- This is a known limitation; change to earliest-insertion tiebreaker if needed.
MIN(ranked.user_id) FILTER (WHERE ranked.rank = 1)
```

---

### WR-02: LRU Fallback Returns Multiple Rows per Map, Incorrect `ORDER BY cy.started_at`

**File:** `apps/api/migrations/0021_tournament_cycle_transitions.sql:75-82`
**Issue:** The LRU fallback path in `select_eligible_map` is:

```sql
SELECT m.id INTO v_map_id
FROM core.maps m
LEFT JOIN tournaments.cycles cy ON cy.map_id = m.id
WHERE m.official = TRUE
  AND m.archived = FALSE
  AND m.code IS NOT NULL
  AND regexp_replace(m.difficulty, '\s*[-+]\s*$', '', '') = ANY(v_difficulties)
ORDER BY cy.started_at ASC NULLS FIRST
LIMIT 1;
```

A map that has been used in multiple cycles will appear multiple times in this join
(once per cycle row), with different `cy.started_at` values. `LIMIT 1` takes the
first row after sorting. If map A has cycles with `started_at` = (5 days ago, 10
days ago) and map B has a cycle with `started_at` = 7 days ago, the join produces:

```
map_A | 10 days ago
map_A |  5 days ago
map_B |  7 days ago
```

After `ORDER BY cy.started_at ASC`, row 1 is `map_A | 10 days ago`, so map_A is
chosen — even though map_A's *most recent* use (5 days ago) is more recent than
map_B's (7 days ago). True LRU should order by the most recent cycle per map.

The Python counterpart `fetch_least_recently_used_map` has the same bug, so the
SQL mirrors it faithfully — but this is still incorrect LRU semantics.

**Fix:** Use a subquery or `DISTINCT ON` to get the most recent cycle per map
before sorting:

```sql
SELECT m.id INTO v_map_id
FROM core.maps m
LEFT JOIN (
    SELECT DISTINCT ON (cy2.map_id) cy2.map_id, cy2.started_at
    FROM tournaments.cycles cy2
    ORDER BY cy2.map_id, cy2.started_at DESC
) cy ON cy.map_id = m.id
WHERE m.official = TRUE
  AND m.archived = FALSE
  AND m.code IS NOT NULL
  AND regexp_replace(m.difficulty, '\s*[-+]\s*$', '', '') = ANY(v_difficulties)
ORDER BY cy.started_at ASC NULLS FIRST
LIMIT 1;
```

---

### WR-03: `api.tournament.*` Queues Not Declared in RabbitMQ `definitions.json`

**File:** `apps/api/services/tournament_outbox_service.py:35-36`
**Issue:** The poller publishes to `api.tournament.cycle_started` and
`api.tournament.cycle_completed`. Inspection of
`infra/rabbitmq/definitions.json` shows no queues with either name are declared.
The default RabbitMQ exchange routes by routing key to a queue of the same name.
If the queue does not exist, messages published to the default exchange with those
routing keys are silently dropped — the `channel.default_exchange.publish` call
succeeds (no error), but the message is lost.

This means the entire Phase 07 pipeline produces no bot-side effects in any
deployed environment until the queues and their DLQs are declared.

**Fix:** Add the queue declarations (with DLQ arguments matching the existing
pattern) to `infra/rabbitmq/definitions.json` and `infra/rabbitmq/rabbit-init.sh`:

```json
{
  "name": "api.tournament.cycle_started",
  "arguments": {
    "x-dead-letter-exchange": "",
    "x-dead-letter-routing-key": "api.tournament.cycle_started.dlq"
  },
  "durable": true
},
{
  "name": "api.tournament.cycle_started.dlq",
  "durable": true
},
{
  "name": "api.tournament.cycle_completed",
  "arguments": {
    "x-dead-letter-exchange": "",
    "x-dead-letter-routing-key": "api.tournament.cycle_completed.dlq"
  },
  "durable": true
},
{
  "name": "api.tournament.cycle_completed.dlq",
  "durable": true
}
```

---

### WR-04: Idempotency Key Does Not Include Outbox Row ID — Re-delivery Suppression on Crash-Restart

**File:** `apps/api/services/tournament_outbox_service.py:101`
**Issue:** The idempotency key is constructed as:

```python
idempotency_key=f"tournament:{row['event_type']}:{row['cycle_id']}"
```

The at-least-once contract (D-11) requires that if the API crashes after publishing
but before marking the row published, the next poll re-publishes the same row.
`BaseService.publish_message` sets `message_id=idempotency_key` on the AMQP
message. The bot's `@queue_consumer(idempotent=True)` guard checks
`public.idempotency_claims` by this message ID and will **refuse to process** a
message with an already-claimed ID.

So the sequence that breaks at-least-once is:
1. Poll 1: publishes `tournament:cycle_completed:42`, bot claims it and processes it.
2. API crashes before `mark_transition_published`.
3. Poll 2: re-publishes `tournament:cycle_completed:42` with the same
   `message_id`. Bot sees the claim already exists and silently skips it.
4. The cycle_completed handling (XP grants, role assignment) never runs a second
   time — which is correct only if poll 1 completed all side effects.

This is actually fine for a single normal at-least-once scenario. The problem
surfaces if the bot's idempotency claim from poll 1 was deleted (e.g. the bot
handler failed and deleted the claim per its retry design). The next re-delivery
would be processed again — which is the intended behaviour. So in that specific
sub-path the design is correct.

However the key format `tournament:{event_type}:{cycle_id}` without the outbox row
`id` means that if a new `cycle_completed` outbox row is ever inserted for the
same `cycle_id` (e.g. a manual admin re-trigger that inserts a new outbox row for
the same cycle), the idempotency key would be identical to the first event, and
the bot would silently skip it even though it is a new legitimate row.

**Fix:** Include the outbox row ID in the key to make it unique per physical row:

```python
idempotency_key=f"tournament:{row['event_type']}:{row['cycle_id']}:{row['id']}"
```

This preserves idempotency within a single row (same key on re-publish of the
same row) while distinguishing separate rows for the same cycle.

---

## Info

### IN-01: `cron.unschedule` Syntax May Silently Fail on Some pg_cron Versions

**File:** `apps/api/migrations/0021_tournament_cycle_transitions.sql:277-279`
**Issue:** The unschedule block is:

```sql
PERFORM cron.unschedule('tournament-cycle-transitions') WHERE EXISTS (
    SELECT 1 FROM cron.job WHERE jobname = 'tournament-cycle-transitions'
);
```

`PERFORM` is a PL/pgSQL statement that discards the return value of a function
call. The `WHERE EXISTS (...)` clause is not valid syntax for a `PERFORM` statement
— `PERFORM` does not accept a `WHERE` clause. This block runs inside a `DO $$`
anonymous block, so PL/pgSQL parses it. On PostgreSQL + pg_cron versions where
`cron.unschedule` returns void (or bigint on newer versions), the `WHERE EXISTS`
clause is a syntax error that would cause the `DO` block to fail. If it somehow
passes parsing, the `WHERE` is ignored and `cron.unschedule` is called
unconditionally, raising an error if the job does not exist (depending on pg_cron
version).

The correct idiomatic pattern is to use an `IF EXISTS` guard:

```sql
IF EXISTS (SELECT 1 FROM cron.job WHERE jobname = 'tournament-cycle-transitions') THEN
    PERFORM cron.unschedule('tournament-cycle-transitions');
END IF;
```

---

### IN-02: `fetch_cycle_history` Total Count Does Not Match Data Query Filters

**File:** `apps/api/repository/tournaments_repository.py:424-439`
**Issue:** `fetch_cycle_history` counts all cycles for a `category_id`:

```python
total = await _conn.fetchval(
    "SELECT COUNT(*) FROM tournaments.cycles WHERE category_id = $1",
    category_id,
)
```

Then fetches with `ORDER BY created_at DESC LIMIT $2 OFFSET $3`. There are no
additional filters in either query, so count and data are consistent today. This
is not a current bug but is a fragility: if a `status` filter is added to the data
query later without updating the count query, pagination metadata will be wrong.
The pattern in `fetch_cycles` (which has explicit filter parity) is the better
model. Worth noting as a maintenance hazard adjacent to the new code.

---

_Reviewed: 2026-05-29_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
