# Phase 7: Automatic Cycle Transitions - Pattern Map

**Mapped:** 2026-05-30
**Files analyzed:** 6
**Analogs found:** 6 / 6 (all have strong in-codebase analogs; 1 has no analog for the *loop* mechanism specifically)

This is a pure-backend, pure-pattern-reuse phase. Every file maps to an existing, proven analog. The only genuinely new *composition* is the long-running outbox poller loop (see file 2).

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `apps/api/migrations/0021_tournament_cycle_transitions.sql` (new) | migration | batch / event-driven (scheduled) | `apps/api/migrations/0013_coin_store.sql` §225-300 | exact |
| `apps/api/app.py` (modify — add `tournament_outbox_poller` lifespan) | config / provider | pub-sub (poll→publish) | `apps/api/app.py` §48-66, 204 (`rabbitmq_connection`) | role-match (no analog for the *loop* itself) |
| `apps/api/repository/tournaments_repository.py` (modify — harden `fetch_unpublished_transitions`) | repository | CRUD | same file §947-1032 (existing outbox methods) | exact |
| `apps/api/services/tournament_outbox_service.py` (new, recommended) or extend `tournament_service.py` | service | pub-sub (publish primitive) | `apps/api/services/base.py` §56-114 (`BaseService.publish_message`) | role-match |
| `libs/sdk/src/genjishimada_sdk/tournaments.py` (modify — extend 2 event structs) | model | event payload | same file §282-299 (`TournamentLeaderboardEntryResponse`), §403-427 (existing lean events) | exact (extend in place) |
| `apps/api/tests/integration/test_tournament_transitions.py` + `test_tournament_outbox.py` (new) | test | integration | `apps/api/tests/integration/test_quest_lifecycle.py` §905-946 (direct `SELECT fn()`), `tests/repository/tournaments/conftest.py` (fixtures) | role-match |

## Pattern Assignments

### `apps/api/migrations/0021_tournament_cycle_transitions.sql` (migration, scheduled batch)

**Analog:** `apps/api/migrations/0013_coin_store.sql` §225-300 (`store.check_and_rotate`)

This is the canonical template. The new file contains: (1) the `tournaments.process_cycle_transitions()` PL/pgSQL function, (2) the optional `tournaments.select_eligible_map(category_id)` helper, (3) the idempotent pg_cron registration `DO` block.

**Advisory-lock + EXCEPTION-cleanup pattern** (lines 234-262) — session-level variant. RESEARCH recommends switching to transaction-level `pg_try_advisory_xact_lock(<CONST>)` (auto-release, no EXCEPTION boilerplate); D-02 permits either. If session-level is kept, copy this cleanup verbatim:
```sql
v_lock_acquired := pg_try_advisory_lock(1234567890);  -- store uses 1234567890; tournaments MUST pick a non-colliding constant (RESEARCH suggests 2025070100)
IF NOT v_lock_acquired THEN
    RAISE NOTICE 'Store rotation already in progress, skipping';
    RETURN;
END IF;
BEGIN
    -- ... work ...
    PERFORM pg_advisory_unlock(1234567890);
EXCEPTION
    WHEN OTHERS THEN
        PERFORM pg_advisory_unlock(1234567890);  -- release even on error
        RAISE;
END;
```

**Idempotent pg_cron registration block** (lines 280-300) — copy verbatim, swap names/schedule. This is the `0013` form (guards on `pg_extension`, includes `cron.unschedule` before `cron.schedule`); use it per D-01 (NOT the `0014` `pg_namespace`/`$cron$` form):
```sql
DO $body$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
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

**Map-selection helper (D-06)** — mirror `fetch_eligible_maps` (`tournaments_repository.py` §548-571) + `fetch_least_recently_used_map` (§593-604) in PL/pgSQL. Both are already pure SQL; the Python is just orchestration. Reproduce in `tournaments.select_eligible_map(p_category_id int) RETURNS int`. Eligible query core to copy:
```sql
SELECT m.id FROM core.maps m
WHERE m.official = TRUE AND m.archived = FALSE AND m.code IS NOT NULL
  AND regexp_replace(m.difficulty, '\s*[-+]\s*$', '', '') = ANY($1)   -- category.difficulties
  AND m.id NOT IN (SELECT cy.map_id FROM tournaments.cycles cy
                   WHERE cy.started_at > now() - make_interval(weeks => $2))  -- blacklist window
  AND m.id NOT IN (SELECT cy.map_id FROM tournaments.cycles cy WHERE cy.status = 'pending')
ORDER BY random()
```
LRU fallback (when empty): `LEFT JOIN tournaments.cycles cy ON cy.map_id = m.id ... ORDER BY cy.started_at ASC NULLS FIRST LIMIT 1`. On NULL result, `RAISE NOTICE` and skip pre-roll (D-07) — do NOT abort the run.

**Placement snapshot (D-08)** — mirror `fetch_leaderboard` (`tournaments_repository.py` §889-911) ranking exactly, wrapped in `jsonb_agg`. The ranking CTE to copy:
```sql
WITH best_per_user AS (
    SELECT DISTINCT ON (tc.user_id) tc.user_id, tc.time, tc.verified, tc.completion
    FROM tournaments.completions tc
    WHERE tc.cycle_id = $1
    ORDER BY tc.user_id, tc.verified DESC, tc.time ASC
)
SELECT RANK() OVER (ORDER BY bpu.verified DESC, bpu.time ASC)::int AS rank,
       bpu.user_id, COALESCE(u.global_name, u.nickname, 'Unknown') AS name,
       bpu.time::float AS time, bpu.verified, bpu.completion
FROM best_per_user bpu JOIN core.users u ON u.id = bpu.user_id
ORDER BY bpu.verified DESC, bpu.time ASC
```
Use `COALESCE(jsonb_agg(...), '[]'::jsonb)` to handle zero-submission cycles. Tables touched (`tournaments.cycles`, `categories`, `completions`, `pending_transitions`) are defined in `0020_tournaments.sql`.

**End-time detection (D-04)** — no stored column; compute inline via `make_interval` (same primitive `fetch_eligible_maps` uses at line 558): `now() >= cy.started_at + make_interval(days => CASE cat.cycle_frequency WHEN 'biweekly' THEN 14 ELSE 7 END)`.

**Submissions auto-rejected:** `submit_completion` already raises `CycleNotActiveError` when `status != 'active'` (`tournament_service.py` §498-499). Setting `finalizing`/`completed` rejects new submissions with ZERO new code. Just set `finalizing` *before* computing the snapshot.

---

### `apps/api/app.py` (config/provider — add `tournament_outbox_poller` lifespan) (pub-sub)

**Analog (shape):** `rabbitmq_connection` §48-66 — an `@asynccontextmanager` added to `lifespan=[...]`. **No analog for the loop** — the existing lifespan only *sets up* the channel pool, it does not run a loop. This is the one new mechanism.

**Lifespan wiring** (line 204) — extend the list:
```python
lifespan=[rabbitmq_connection],   # becomes: lifespan=[rabbitmq_connection, tournament_outbox_poller]
```

**Existing lifespan shape to copy** (§48-66):
```python
@asynccontextmanager
async def rabbitmq_connection(_app: Litestar) -> AsyncGenerator[None, None]:
    """Connect to RabbitMQ."""
    # ... sets _app.state.mq_channel_pool ...
    yield
```

**New loop (RESEARCH-recommended scaffolding)** — wrap an `asyncio.Task` with cancel-on-shutdown. `asyncio.sleep(10)` (D-12) is the cancellation point; broad `except` keeps the loop alive (one bad row must not kill it); `log.exception` is captured by Sentry:
```python
@asynccontextmanager
async def tournament_outbox_poller(_app: Litestar) -> AsyncGenerator[None, None]:
    async def _loop() -> None:
        from services.tournament_outbox_service import publish_pending_transitions  # local import avoids cycles
        while True:
            try:
                await publish_pending_transitions(_app.state)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("[!] tournament outbox poll failed")
            await asyncio.sleep(10)
    task = asyncio.create_task(_loop())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
```
Pool access: `_app.state.db_pool` (litestar-asyncpg pool). The poller must acquire its OWN connection (not a request-scoped `conn`). jsonb payloads round-trip to dicts automatically via `_async_pg_init` codec (§84-98).

---

### `apps/api/repository/tournaments_repository.py` (repository, CRUD)

**Analog:** the three outbox methods already in this file (§947-1032). They EXIST — `create_pending_transition` (§947), `fetch_unpublished_transitions` (§986), `mark_transition_published` (§1008). The only change is hardening `fetch_unpublished_transitions` with `FOR UPDATE SKIP LOCKED` (D-11).

**Current method (lacks row locking)** — §999-1005:
```python
query = """
    SELECT * FROM tournaments.pending_transitions
    WHERE published = FALSE
    ORDER BY created_at ASC
"""   # ADD: FOR UPDATE SKIP LOCKED  (D-11 — prevents double-publish across instances)
```

**`_get_connection` injection pattern** (used by every method here, e.g. §999, §1023): `_conn = self._get_connection(conn)` from `BaseRepository`. The poller must call this WITHIN an open `conn.transaction()` so the `FOR UPDATE` lock and the `mark_transition_published` UPDATE share one transaction (D-11). Either harden the repo method or use inline SQL in the poller — RESEARCH accepts both.

**`mark_transition_published`** (§1008-1032) — already correct: `UPDATE ... SET published = TRUE WHERE id = $1 AND published = FALSE`, returns `result == "UPDATE 1"`.

---

### `apps/api/services/tournament_outbox_service.py` (new) — publish primitive (pub-sub)

**Analog:** `apps/api/services/base.py` §56-114 (`BaseService.publish_message`). New service extends `BaseService` to get `publish_message`; a module-level `publish_pending_transitions(state)` function orchestrates the poll-publish-mark loop.

**`publish_message` signature + idempotency requirement** (§56-76):
```python
async def publish_message(
    self, *, routing_key: str, data: msgspec.Struct | list[msgspec.Struct],
    headers: Headers, idempotency_key: str | None = None,
) -> JobStatusResponse:
    if routing_key not in IGNORE_IDEMPOTENCY and not idempotency_key:
        raise ValueError(f"idempotency_key required for routing_key='{routing_key}'")
```
- Routing keys (RESEARCH): `api.tournament.cycle_started`, `api.tournament.cycle_completed`. NOT in `IGNORE_IDEMPOTENCY` (§28-36), so a cycle-scoped `idempotency_key=f"tournament:{event_type}:{cycle_id}"` is REQUIRED.
- Test-mode skip (§80-82): `if headers.get("X-PYTEST-ENABLED") == "1": return JobStatusResponse(uuid4(), "succeeded")` — publishing is skipped in tests. The poller must pass a `Headers` object; tests assert publish/mark behavior using this skip.
- Each publish inserts a `public.jobs` row (§92-97). At-least-once re-publish creates a new job row — acceptable for outbox.

**Payload→struct conversion (D-09, Pitfall 5):** RESEARCH recommends `msgspec.convert(row["payload"], TournamentCycleStartedEvent)` in the poller so SQL/struct field drift fails fast. Keep three things in sync: SQL `jsonb_build_object` keys, SDK struct fields, poller `_build_event` mapping. Publish-then-mark ordering (D-11): publish first, then `UPDATE published=TRUE` in the same `FOR UPDATE SKIP LOCKED` transaction.

---

### `libs/sdk/src/genjishimada_sdk/tournaments.py` (model, event payload)

**Analog:** existing structs in the same file. **IMPORTANT GAP (verified):** the two event structs are too lean for D-08/D-09 payloads.

**Current structs** (§403-427) — must be extended:
```python
class TournamentCycleStartedEvent(Struct):
    cycle_id: int
    category_id: int
    map_id: int          # needs: map_code, map_name, started_at, ends_at (D-09)

class TournamentCycleCompletedEvent(Struct):
    cycle_id: int
    category_id: int     # needs: standings, winner_user_id (D-08)
```

**Reuse `TournamentLeaderboardEntryResponse`** (§282-299) as the standings element type — its fields exactly match the placement snapshot SQL emits (`rank, user_id, name, time, verified, completion`):
```python
class TournamentLeaderboardEntryResponse(Struct):
    rank: int
    user_id: int
    name: str
    time: float
    verified: bool
    completion: bool
```
RESEARCH recommends extending `TournamentCycleCompletedEvent` with `standings: list[TournamentLeaderboardEntryResponse]` + `winner_user_id: int | None`, and `TournamentCycleStartedEvent` with `map_code: str`, `map_name: str`, `started_at: datetime`, `ends_at: datetime`. Note `TournamentCycleResultsResponse` (§302-323) already pairs cycle metadata with `standings` — a close structural precedent for the completed-event shape. Update `__all__` (§8) if any new sub-struct is added (it already lists both event structs). Run `just fix` after SDK edits (MEMORY.md: SDK import failures fixed by `just fix`).

---

### Integration tests (test, integration)

**Analog (cron-function invocation):** `apps/api/tests/integration/test_quest_lifecycle.py` §909-910 — direct `SELECT fn()`, no cron needed (test DB lacks pg_cron):
```python
async with asyncpg_pool.acquire() as conn:
    await conn.execute("SELECT store.check_and_generate_quest_rotation()")
```
Transition tests: `await conn.execute("SELECT tournaments.process_cycle_transitions()")`, then assert cycle status + `pending_transitions` rows.

**Analog (fixtures):** `apps/api/tests/repository/tournaments/conftest.py` — `create_test_category` (§19-63), `create_test_cycle` (§67-100), `create_test_tournament_completion` (§104-144). All reusable. `create_test_cycle` already accepts `status` and `started_at` overrides, so a "due" cycle is `await create_test_cycle(cat, map, status="active", started_at=<past datetime>)` — no new fixture needed.

**Analog (poller test):** use the `X-PYTEST-ENABLED=1` header (`base.py` §80) to skip real RabbitMQ publish; assert rows flip to `published=TRUE` and `msgspec.convert(payload, Struct)` succeeds. Place new files at `tests/integration/test_tournament_transitions.py` and `tests/integration/test_tournament_outbox.py`; helper-parity test at `tests/repository/tournaments/test_select_eligible_map.py`.

## Shared Patterns

### pg_cron registration (idempotent, guarded)
**Source:** `apps/api/migrations/0013_coin_store.sql` §280-300
**Apply to:** the new migration's `DO` block. Always `cron.unschedule` before `cron.schedule`; always guard on `pg_extension WHERE extname='pg_cron'` so test/local migrations no-op.

### Advisory lock (concurrency gate for scheduled mutations)
**Source:** `0013_coin_store.sql` §234-262 (session-level) OR `apps/api/services/store_service.py:578` (`pg_advisory_xact_lock`, transaction-level)
**Apply to:** top of `process_cycle_transitions()`. Pick a non-colliding bigint constant (existing: `1234567890` for store). RESEARCH recommends transaction-level for auto-release.

### Repository connection injection
**Source:** `BaseRepository._get_connection` (used throughout `tournaments_repository.py`, e.g. §547, §999)
**Apply to:** every repo method touched. Poller wraps the SELECT-FOR-UPDATE + UPDATE in one `conn.transaction()`.

### RabbitMQ publish + idempotency + test-skip
**Source:** `apps/api/services/base.py` §56-114
**Apply to:** the outbox poller's publish call. Routing keys not in `IGNORE_IDEMPOTENCY` require `idempotency_key`; `X-PYTEST-ENABLED=1` skips publishing in tests; each publish writes a `public.jobs` row.

### jsonb ↔ msgspec round-trip
**Source:** `apps/api/app.py` §84-98 (`_async_pg_init`, `_jsonb_encoder`/`_jsonb_decoder`)
**Apply to:** outbox `payload` reads — already decode to Python dict; `msgspec.convert(payload, Struct)` validates before publish.

## No Analog Found

| File / Mechanism | Role | Data Flow | Reason |
|------------------|------|-----------|--------|
| The long-running poll loop inside `tournament_outbox_poller` | provider | pub-sub | No existing long-running background asyncio loop in the codebase. The lifespan *shape* (`rabbitmq_connection`) and the publish *primitive* (`publish_message`) exist, but the `while True: ... asyncio.sleep` loop with cancel-on-shutdown is a new composition. This is STATE.md's "architecturally novel" flag. Use the RESEARCH §231-298 scaffolding; validate, don't redesign. |

## Metadata

**Analog search scope:** `apps/api/migrations/`, `apps/api/services/`, `apps/api/repository/`, `apps/api/tests/integration/`, `apps/api/tests/repository/tournaments/`, `apps/api/app.py`, `libs/sdk/src/genjishimada_sdk/`
**Files scanned:** ~9 (all targeted via RESEARCH/CONTEXT line refs — verified, not speculative)
**Pattern extraction date:** 2026-05-30
