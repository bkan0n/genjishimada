# Technology Stack: Tournament System

**Project:** Recurring Tournament System for Genji Parkour
**Researched:** 2026-05-29
**Overall confidence:** HIGH

## Executive Summary

The tournament system requires **zero new Python dependencies**. Every capability needed -- scheduled cycle transitions, random map selection with exclusion windows, leaderboard ranking, state management, and async notifications -- is achievable with tools already in the stack: pg_cron, PL/pgSQL functions, PostgreSQL window functions, RabbitMQ queues, and discord.ext.tasks. The project already has two production systems (store rotations, quest rotations) that implement the exact same "recurring timed cycle with random selection and config singleton" pattern the tournament needs. The tournament system should follow these proven patterns, not introduce new abstractions.

---

## Recommended Stack

### No New Dependencies Required

The tournament system is a new **domain** within the existing architecture, not a new **technology problem**. Every building block exists.

| Capability | Existing Tool | Already Used For | Confidence |
|------------|--------------|-----------------|------------|
| Scheduled cycle transitions | pg_cron + PL/pgSQL | Store rotation (0013), quest rotation (0014) | HIGH |
| Random map selection with exclusion | `ORDER BY random() LIMIT N` in PL/pgSQL | Store item selection, quest selection | HIGH |
| Leaderboard ranking | `RANK() OVER (ORDER BY time, inserted_at)` | Completions leaderboard (`completions_repository.py`) | HIGH |
| Bot notifications | RabbitMQ queue consumers | All bot-side reactions to API events | HIGH |
| Periodic bot-side polling | `discord.ext.tasks.loop` | Ninja role check (1m), change request cleanup (1h) | HIGH |
| Cycle state management | Config singleton table + enum columns | `store.config`, `store.quest_config` | HIGH |
| XP rewards | `api.xp.grant` RabbitMQ queue | Lootbox XP grants | HIGH |
| Admin API endpoints | Litestar Controller-Service-Repository | Every existing domain | HIGH |
| Shared types | msgspec Struct in SDK | All API-bot communication | HIGH |

---

## Scheduling: pg_cron (Not APScheduler)

**Decision:** Use pg_cron with PL/pgSQL functions for tournament cycle transitions.

**Why pg_cron, not APScheduler or application-level scheduling:**

| Criterion | pg_cron | APScheduler 3.x | asyncio tasks.loop |
|-----------|---------|-----------------|-------------------|
| Already in stack | Yes (Docker image, 2 production jobs) | No | Yes (bot only) |
| Survives API restart | Yes (database-level) | No (in-process) | No (in-process) |
| Single-instance guarantee | Yes (pg advisory locks, proven pattern) | Requires external lock | No |
| Handles cycle transition atomicity | Yes (runs SQL directly, can use transactions) | Requires DB call from Python | Requires DB call from Python |
| Precision needed | Hourly check sufficient (same as store/quests) | Sub-minute capable | Sub-minute capable |
| Complexity | Low (follows existing migration pattern) | Medium (new dependency, config, data store) | Low but wrong layer |

**The existing pattern (from migration 0013):**

1. **Config singleton table** (`CHECK (id = 1)`) stores `next_rotation_at`, cycle parameters
2. **PL/pgSQL function** performs the transition atomically: finalize old cycle, select new maps, update config timestamps
3. **pg_cron job** runs hourly, calls the checker function
4. **Advisory lock** (`pg_try_advisory_lock(N)`) prevents concurrent execution
5. **Graceful degradation** in tests: `IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron')` guard

**For tournaments, the same pattern applies:** A `tournaments.config` singleton, a `tournaments.transition_cycle()` PL/pgSQL function, and a pg_cron job running every 15-30 minutes that checks `now() >= next_cycle_at`.

**What APScheduler would add (and why it's wrong):**
- APScheduler 4.x is still in alpha (4.0.0a6 as of April 2025) -- **not production-ready**
- APScheduler 3.x (stable at 3.11.2) would require adding SQLAlchemy as a dependency for persistent job storage, which conflicts with the project's raw-asyncpg philosophy
- Application-level schedulers create a SPOF: if the API process restarts during a cycle transition, the job is lost. pg_cron runs independently of the application
- The project has never used application-level task scheduling in the API; introducing it creates architectural inconsistency

**Confidence:** HIGH -- Two existing production systems use this exact pattern.

---

## Bot Notification for Cycle Transitions

**Decision:** Hybrid approach -- pg_cron handles the data transition, then notifies the bot via one of two mechanisms.

### Option A: pg_cron writes a "pending notification" row, bot polls via `tasks.loop` (Recommended)

The simplest approach that follows existing patterns:

1. pg_cron transition function writes a row to `tournaments.pending_notifications` (type: `cycle_completed`, with cycle_id, results)
2. Bot runs a `@tasks.loop(minutes=1)` that polls `GET /api/v3/tournaments/pending-notifications`
3. Bot processes notification (announces results, transfers champion roles, announces new maps)
4. Bot calls `DELETE /api/v3/tournaments/pending-notifications/{id}` to acknowledge

**Why this over RabbitMQ:** pg_cron runs raw SQL, not Python. It cannot publish to RabbitMQ directly. The bot already uses `tasks.loop` for periodic checks. A 1-minute polling delay for weekly/biweekly transitions is negligible.

### Option B: pg_cron calls API via pg_net/pgsql-http extension, API publishes to RabbitMQ

More complex but lower latency:

1. Install `pg_net` or `pgsql-http` PostgreSQL extension
2. pg_cron transition function calls `SELECT net.http_post(...)` to hit an internal API endpoint
3. API endpoint publishes to RabbitMQ queue `api.tournament.cycle.completed`
4. Bot consumes the queue like any other event

**Why not recommended:** Adds a new PostgreSQL extension not currently in the stack, creates a dependency between PostgreSQL and the API's HTTP availability, and adds complexity for zero practical benefit (weekly events don't need sub-second notification).

**Confidence:** HIGH for Option A; MEDIUM for Option B.

---

## Random Map Selection with Exclusion Windows

**Decision:** Use `ORDER BY random() LIMIT N` with `NOT EXISTS` subquery for blacklist exclusion, inside PL/pgSQL.

**Pattern (directly from existing store rotation code):**

```sql
-- Select random maps for a category, excluding recently used
INSERT INTO tournaments.cycle_maps (cycle_id, category_id, map_code, ...)
SELECT
    p_cycle_id,
    p_category_id,
    m.code,
    ...
FROM maps.maps m
WHERE m.difficulty = ANY(p_difficulties)
  AND m.archived = FALSE
  AND NOT EXISTS (
      SELECT 1 FROM tournaments.cycle_maps cm
      JOIN tournaments.cycles c ON c.id = cm.cycle_id
      WHERE cm.map_code = m.code
        AND c.ended_at > now() - (p_blacklist_weeks || ' weeks')::interval
  )
ORDER BY random()
LIMIT 1;
```

**Why `ORDER BY random()` is fine here:**
- The eligible map pool is small (hundreds, not millions)
- Selection happens once per cycle (weekly/biweekly), not on every request
- TABLESAMPLE is inappropriate: it samples by table blocks, not by query result rows with WHERE filters
- This is the exact same approach used in store rotation (migration 0013) and quest rotation (migration 0014) for the same reason

**Confidence:** HIGH -- Three existing systems use this pattern on similar-sized datasets.

---

## Leaderboard Ranking

**Decision:** Use PostgreSQL `RANK() OVER (ORDER BY ...)` window functions, following the existing completions leaderboard pattern.

**For "tier-then-time" tournament ranking:**

```sql
RANK() OVER (
    PARTITION BY cycle_id, category_id
    ORDER BY
        CASE WHEN completion = FALSE THEN 0 ELSE 1 END,  -- full completion first
        time ASC,
        inserted_at ASC
) AS rank
```

**Why `RANK()` not `DENSE_RANK()` or `ROW_NUMBER()`:**
- `RANK()` is already used throughout `completions_repository.py` for leaderboards
- Ties get the same rank (correct for leaderboard semantics)
- Consistent with existing display logic

**Confidence:** HIGH -- Existing leaderboard queries use this exact function.

---

## Cycle State Management

**Decision:** Use a config singleton table pattern with enum-like status columns, following `store.config` and `store.quest_config`.

**Proven pattern elements:**
- `tournaments.config` singleton table (`CHECK (id = 1)`)
- Status tracked via `timestamptz` columns (`last_cycle_at`, `next_cycle_at`) rather than string enums
- Per-category configuration stored in a related table (`tournaments.categories`) with cycle frequency
- No formal state machine library needed -- the state is implicit in the timestamps and the transition function's logic

**Why no state machine library:**
- The existing store/quest systems use no state machine library
- Tournament cycles have exactly 2 states: active and transitioning (momentary)
- The transition is a single atomic PL/pgSQL function, not a multi-step process with rollback
- Adding `python-statemachine` (v3.1.2, latest, does support async) would be over-engineering for a 2-state system
- If future complexity demands it (seasons, multi-phase tournaments), a state machine can be added then

**Confidence:** HIGH -- Config singleton pattern used in 2 existing systems.

---

## Tournament Completions and Cross-Write

**Decision:** Use raw asyncpg SQL in the repository layer (same as `completions_repository.py`), with a CTE-based atomic cross-write.

**The cross-write pattern:**

```sql
-- Atomic: insert tournament completion + conditionally cross-write to core.completions
WITH tournament_insert AS (
    INSERT INTO tournaments.completions (cycle_id, user_id, map_code, time, ...)
    VALUES ($1, $2, $3, $4, ...)
    RETURNING id, user_id, map_code, time
),
existing_best AS (
    SELECT time FROM completions.completions
    WHERE user_id = $2 AND map_id = (SELECT id FROM maps.maps WHERE code = $3)
    ORDER BY inserted_at DESC LIMIT 1
)
INSERT INTO completions.completions (user_id, map_id, time, tournament_completion_id, ...)
SELECT ti.user_id, m.id, ti.time, ti.id, ...
FROM tournament_insert ti
JOIN maps.maps m ON m.code = ti.map_code
WHERE NOT EXISTS (SELECT 1 FROM existing_best WHERE time <= ti.time)
   OR NOT EXISTS (SELECT 1 FROM existing_best);
```

**Why CTEs:**
- Atomic: both inserts succeed or fail together within the transaction
- The existing codebase uses CTEs extensively for multi-table operations (noted in CLAUDE.md memory)
- No need for application-level two-phase logic

**Confidence:** HIGH -- CTE pattern well-established in the codebase.

---

## XP Rewards

**Decision:** Use the existing `api.xp.grant` RabbitMQ queue for all tournament XP (participation + placement + streak).

**The XP grant pipeline already exists:**
- API publishes `XpGrantEvent` to `api.xp.grant` queue (see `services/base.py`, `lootbox_service.py`)
- Bot consumes via `@queue_consumer("api.xp.grant", struct_type=XpGrantEvent, idempotent=True)` (see `extensions/xp.py`)
- Tournament service just needs to publish the same event type with tournament-specific metadata

**No new queue needed** -- the existing `api.xp.grant` queue handles arbitrary XP grants from any source.

**Confidence:** HIGH -- Direct reuse of existing infrastructure.

---

## New RabbitMQ Queues

The tournament system needs these new queues for bot-side actions:

| Queue | Event | Purpose |
|-------|-------|---------|
| `api.tournament.cycle.started` | `TournamentCycleStartedEvent` | Bot announces new maps, posts leaderboard embeds |
| `api.tournament.cycle.ended` | `TournamentCycleEndedEvent` | Bot announces results, transfers champion roles |
| `api.tournament.completion.submitted` | `TournamentCompletionSubmittedEvent` | Bot updates live leaderboard embed (optional) |

**Note:** These follow the existing naming convention (`api.<domain>.<action>`). The `cycle.started` and `cycle.ended` events would be published by the API when the bot polls for pending notifications and triggers the announcement flow, or directly by the API endpoint that processes the pg_cron transition results.

**Confidence:** HIGH -- Standard queue pattern.

---

## SDK Structs

New msgspec Struct definitions in `libs/sdk/src/genjishimada_sdk/tournaments.py`:

- `TournamentConfigResponse` -- admin config view
- `TournamentCycleResponse` -- current/historical cycle data
- `TournamentCategoryResponse` -- category configuration
- `TournamentLeaderboardResponse` -- ranked entries per category
- `TournamentCompletionRequest` -- submission payload
- `TournamentCompletionResponse` -- submission result
- `TournamentCycleStartedEvent` -- RabbitMQ event
- `TournamentCycleEndedEvent` -- RabbitMQ event
- `TournamentCycleMapResponse` -- map selection per category
- `TournamentStreakResponse` -- user streak data

**Confidence:** HIGH -- Standard SDK pattern.

---

## Database Schema

**New schema:** `tournaments` (following convention: `core`, `maps`, `completions`, `playtests`, `users`, `lootbox`, `store`, `content`, `tournaments`)

**New migration:** `0020_tournament_system.sql`

**Key tables:**
- `tournaments.config` -- singleton, global tournament settings
- `tournaments.categories` -- difficulty groupings with per-category cycle frequency
- `tournaments.cycles` -- historical cycle records
- `tournaments.cycle_maps` -- maps selected for each cycle/category
- `tournaments.completions` -- tournament-specific completion records
- `tournaments.streaks` -- per-user participation streak tracking
- `tournaments.xp_config` -- configurable XP amounts per placement tier
- `tournaments.pending_notifications` -- pg_cron to bot notification bridge
- `tournaments.map_blacklist_config` -- exclusion window configuration

**Confidence:** HIGH -- Standard schema pattern.

---

## API Route Structure

**Route prefix:** `/api/v3/tournaments`

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/current` | GET | Public | Current cycle, maps, leaderboards |
| `/cycles` | GET | Public | Historical cycles |
| `/cycles/{id}` | GET | Public | Specific cycle details |
| `/cycles/{id}/leaderboard` | GET | Public | Cycle leaderboard |
| `/completions` | POST | User | Submit tournament completion |
| `/streaks/{user_id}` | GET | Public | User streak info |
| `/config` | GET/PATCH | Admin | Tournament configuration |
| `/categories` | GET/POST/PATCH/DELETE | Admin | Category management |
| `/cycles/next/maps` | GET | Admin | Pre-rolled next maps |
| `/cycles/next/maps/reroll` | POST | Admin | Reroll next cycle maps |
| `/pending-notifications` | GET/DELETE | Bot | Notification polling |

**Confidence:** HIGH -- Standard route pattern.

---

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Scheduling | pg_cron (existing) | APScheduler 3.x | New dependency, in-process (dies with API), no advisory lock pattern, inconsistent with existing architecture |
| Scheduling | pg_cron (existing) | APScheduler 4.x | Alpha quality (4.0.0a6), requires SQLAlchemy, not production-ready |
| Scheduling | pg_cron (existing) | Celery + Redis/RabbitMQ beat | Massive overkill, adds Redis or Celery infra, wrong tool for periodic DB operations |
| Scheduling | pg_cron (existing) | OS-level crontab | Not containerized, no advisory locks, external to the system |
| Random selection | `ORDER BY random()` | TABLESAMPLE | TABLESAMPLE samples table blocks, not filtered query results -- wrong tool |
| Random selection | `ORDER BY random()` | Application-level Python `random` | Requires fetching all eligible maps to Python, slower, less atomic |
| State machine | Implicit in PL/pgSQL timestamps | python-statemachine 3.x | Over-engineering for 2 states (active/transitioning), no existing precedent |
| State machine | Implicit in PL/pgSQL timestamps | transitions library | Same over-engineering concern, plus transitions doesn't have great async support for this use case |
| Bot notification | Poll via `tasks.loop` | pg_net HTTP extension | New PG extension not in stack, HTTP dependency between PG and API, unnecessary for weekly events |
| Bot notification | Poll via `tasks.loop` | PostgreSQL LISTEN/NOTIFY + asyncpg | Bypasses the API layer (bot shouldn't read DB events directly per architecture), adds complexity |
| Leaderboard | `RANK() OVER` | Application-level sorting | Slower, inconsistent with existing leaderboard code, loses DB-level pagination |

---

## What NOT to Use

| Technology | Why Not |
|------------|---------|
| **APScheduler** (any version) | Existing pg_cron pattern is superior for this use case. APScheduler 4.x is alpha. 3.x adds unnecessary application-level complexity. |
| **Celery** | Massive infrastructure overhead for a single periodic job. The project uses RabbitMQ but not as a Celery broker. |
| **Redis** | Not in the stack, not needed. PostgreSQL handles all persistence. |
| **SQLAlchemy** | The project uses raw asyncpg by design. Adding an ORM for one feature violates architectural consistency. |
| **python-statemachine / transitions** | Over-engineering. Tournament state is 2 values, not a complex graph. |
| **pg_net / pgsql-http** | New PostgreSQL extension for marginal notification latency improvement on weekly events. |
| **Temporal / Prefect / Airflow** | Workflow orchestrators for a single cron job. Absurdly overscoped. |

---

## Installation

```bash
# No new packages to install.
# The tournament system uses only existing dependencies:
#   - asyncpg (database)
#   - aio-pika (RabbitMQ)
#   - msgspec (serialization)
#   - litestar (API framework)
#   - discord.py (bot framework)
#
# Infrastructure already has pg_cron enabled in the PostgreSQL Docker image.
```

---

## Sources

- [pg_cron GitHub repository](https://github.com/citusdata/pg_cron) -- Extension documentation and usage patterns
- [APScheduler PyPI](https://pypi.org/project/APScheduler/) -- Version 3.11.2 stable, 4.0.0a6 alpha (verified 2026-05-29)
- [APScheduler documentation](https://apscheduler.readthedocs.io/en/master/userguide.html) -- AsyncScheduler API and data store options
- [python-statemachine PyPI](https://pypi.org/project/python-statemachine/) -- Version 3.1.2 (2026-05-19), supports async
- [PostgreSQL window functions documentation](https://www.postgresql.org/docs/current/functions-window.html) -- RANK, DENSE_RANK, ROW_NUMBER
- [Supabase pg_cron guide](https://supabase.com/docs/guides/database/extensions/pg_cron) -- pg_cron scheduling patterns
- [pg_net extension](https://supabase.com/docs/guides/database/extensions/pg_net) -- Async HTTP from PostgreSQL (considered, not recommended)
- Existing codebase migrations: `0013_coin_store.sql`, `0014_quests_system.sql` -- Proven rotation patterns
- Existing codebase: `apps/api/repository/completions_repository.py` -- RANK() leaderboard patterns
- Existing codebase: `apps/bot/extensions/events.py`, `apps/bot/extensions/xp.py` -- tasks.loop and queue consumer patterns

---

*Stack analysis: 2026-05-29*
