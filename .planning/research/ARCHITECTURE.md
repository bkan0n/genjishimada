# Architecture Patterns

**Domain:** Recurring tournament system for a gaming community platform
**Researched:** 2026-05-29
**Confidence:** HIGH (patterns derived from existing codebase, no external dependencies)

## Recommended Architecture

The tournament system introduces seven new components that slot into the existing Controller-Service-Repository API and Discord bot consumer architecture. The system follows two primary flows: (1) a request-driven flow for submissions, configuration, and queries, and (2) a scheduled flow for automatic cycle transitions that originates in PostgreSQL via pg_cron and propagates through the API into RabbitMQ for Discord-side effects.

```text
                         ┌──────────────────────────────────────────┐
                         │          Scheduled Trigger               │
                         │   pg_cron -> SQL function hourly check   │
                         │   "Does any category need transition?"   │
                         └─────────────┬────────────────────────────┘
                                       │ transition_needed = true
                                       ▼
┌────────────────────────────────────────────────────────────────────────────────┐
│                              Litestar REST API                                │
│                                                                               │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │                    TournamentsController                                │  │
│  │    /api/v3/tournaments/*                                                │  │
│  │                                                                         │  │
│  │  Public:                         Admin:                                 │  │
│  │    GET /active                     POST /admin/config                   │  │
│  │    GET /leaderboard/{cycle_id}     PATCH /admin/categories/{id}         │  │
│  │    POST /submit                    POST /admin/reroll/{category_id}     │  │
│  │    GET /history                    GET  /admin/preview-next             │  │
│  │    GET /streak/{user_id}           POST /admin/transition (manual)      │  │
│  │                                                                         │  │
│  └────────────┬────────────────────────────────────────────────────────────┘  │
│               │                                                               │
│  ┌────────────▼────────────────────────────────────────────────────────────┐  │
│  │                    TournamentService                                    │  │
│  │                                                                         │  │
│  │  submit_completion()     ──── Cross-write to core.completions           │  │
│  │  transition_cycle()      ──── Finalize results, select next maps        │  │
│  │  configure_tournament()  ──── Validate + persist config changes         │  │
│  │  get_leaderboard()       ──── Ranked query with tier-then-time          │  │
│  │  get_active_cycles()     ──── Current maps per category                 │  │
│  │  get_streak()            ──── User participation streak                 │  │
│  │                                                                         │  │
│  │  publish_message():                                                     │  │
│  │    -> api.tournament.cycle.started     (new maps announced)             │  │
│  │    -> api.tournament.cycle.completed   (results + champion transfer)    │  │
│  │    -> api.tournament.submission        (completion submitted)           │  │
│  │    -> api.xp.grant                     (reuse existing XP queue)        │  │
│  └────────────┬────────────────────────────────────────────────────────────┘  │
│               │                                                               │
│  ┌────────────▼────────────────────────────────────────────────────────────┐  │
│  │                    TournamentRepository                                 │  │
│  │                                                                         │  │
│  │  insert_completion()           fetch_cycle_leaderboard()                │  │
│  │  fetch_active_cycles()         fetch_user_streak()                      │  │
│  │  insert_cycle()                update_cycle_status()                    │  │
│  │  select_random_maps()          insert_blacklist_entries()               │  │
│  │  fetch_tournament_config()     update_tournament_config()               │  │
│  │  fetch_next_cycle_maps()       reroll_next_map()                        │  │
│  │  cross_write_to_core()         fetch_placement_results()                │  │
│  └─────────────────────────────────────────────────────────────────────────┘  │
│                                                                               │
│               │ RabbitMQ publish                                              │
└───────────────┼───────────────────────────────────────────────────────────────┘
                │
                ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                              RabbitMQ                                         │
│                                                                               │
│   api.tournament.cycle.started     (idempotent)                              │
│   api.tournament.cycle.completed   (idempotent)                              │
│   api.tournament.submission        (idempotent)                              │
│   api.xp.grant                     (existing, non-idempotent)                │
│                                                                               │
└───────────────┬───────────────────────────────────────────────────────────────┘
                │
                ▼
┌───────────────────────────────────────────────────────────────────────────────┐
│                            Discord.py Bot                                     │
│                                                                               │
│  ┌─────────────────────────────────────────────────────────────────────────┐  │
│  │                    TournamentHandler (BaseHandler)                      │  │
│  │                                                                         │  │
│  │  @queue_consumer("api.tournament.cycle.started")                        │  │
│  │    -> Post announcement embed with new maps per category                │  │
│  │    -> Pin announcement message                                          │  │
│  │                                                                         │  │
│  │  @queue_consumer("api.tournament.cycle.completed")                      │  │
│  │    -> Post results embed with placements                                │  │
│  │    -> Transfer champion role (remove from old, add to new)              │  │
│  │    -> Trigger XP grants for placements via bot.api                      │  │
│  │                                                                         │  │
│  │  @queue_consumer("api.tournament.submission")                           │  │
│  │    -> Post submission to tournament channel (optional)                   │  │
│  │                                                                         │  │
│  │  Slash commands (TournamentCog):                                        │  │
│  │    /tournament leaderboard [category]                                   │  │
│  │    /tournament info                                                     │  │
│  │    /tournament streak [user]                                            │  │
│  │    /tournament admin reroll <category>                                  │  │
│  │    /tournament admin preview                                            │  │
│  └─────────────────────────────────────────────────────────────────────────┘  │
│                                                                               │
└───────────────────────────────────────────────────────────────────────────────┘
```

### Component Boundaries

| Component | Responsibility | Communicates With |
|-----------|---------------|-------------------|
| `tournaments` PostgreSQL schema | All tournament state: config, cycles, categories, completions, blacklist, streaks | Read/written by TournamentRepository only |
| `TournamentRepository` | Raw SQL queries against `tournaments.*` tables; cross-write queries to `core.completions` | TournamentService (called by) |
| `TournamentService` | Business logic: submission validation, cycle transition orchestration, map selection, streak tracking, XP calculation | TournamentRepository (calls), BaseService.publish_message (publishes to RabbitMQ), CompletionsRepository (cross-write reads) |
| `TournamentsController` | HTTP endpoint layer at `/api/v3/tournaments/*`; auth scopes, param extraction, exception-to-HTTP translation | TournamentService (delegates to) |
| `tournaments.py` SDK module | Shared msgspec Structs for requests, responses, and events | Imported by API controller/service and bot extension |
| `TournamentHandler` (bot) | Consumes RabbitMQ events; posts Discord embeds, manages champion role, triggers XP grants | RabbitMQ (consumes), bot.api (HTTP calls to API) |
| `TournamentCog` (bot) | Slash commands for tournament info, leaderboard, admin actions | bot.api (HTTP calls to API) |
| pg_cron job | Hourly check: calls `tournaments.check_and_transition()` SQL function | PostgreSQL only (pure SQL) |

### Data Flow

**Flow 1: Tournament Completion Submission**

```text
User/Bot -> POST /api/v3/tournaments/submit
         -> TournamentsController.submit_completion()
         -> TournamentService.submit_completion()
            1. Validate: active cycle exists for this map
            2. Validate: time is faster than user's existing tournament entry (or first entry)
            3. INSERT into tournaments.completions (within transaction)
            4. Cross-write: check if time < user's core.completions best for this map
               YES -> INSERT/UPDATE core.completions with tournament_completion_id FK
               NO  -> skip (preserve "latest = fastest" invariant)
            5. Publish "api.tournament.submission" to RabbitMQ
         <- Return TournamentSubmissionResponse
```

**Flow 2: Automatic Cycle Transition (the critical path)**

```text
pg_cron (hourly) -> SELECT tournaments.check_and_transition()
  SQL function:
    1. Advisory lock (prevent concurrent transitions)
    2. For each category where now() >= next_transition_at:
       a. Mark current cycle as 'completed'
       b. Calculate placements (rank by verification_tier DESC, time ASC)
       c. Store placement results in tournaments.cycle_results
       d. Add current map to blacklist with expiry
       e. Activate pre-rolled next cycle (set status = 'active')
       f. Pre-roll the cycle AFTER next (random map selection from eligible pool)
       g. Update next_transition_at based on category frequency
       h. INSERT a transition event record into tournaments.pending_transitions
    3. Release advisory lock

API (polling or LISTEN/NOTIFY) -> detects pending transitions
  -> TournamentService.process_pending_transitions()
     For each pending transition:
       1. Compute XP awards (participation + placement)
       2. Publish "api.tournament.cycle.completed" with results
       3. Publish "api.xp.grant" for each XP award
       4. Publish "api.tournament.cycle.started" with new map info
       5. Mark transition as processed

Bot consumes events:
  "api.tournament.cycle.completed":
    -> Post results embed to tournament channel
    -> Transfer champion role
  "api.tournament.cycle.started":
    -> Post new cycle announcement embed
    -> Pin announcement
  "api.xp.grant":
    -> Existing XP handler processes grants
```

**Flow 3: Admin Configuration**

```text
Admin -> PATCH /api/v3/tournaments/admin/categories/{id}
      -> TournamentService.update_category()
         1. Validate: no active cycle (config locked during active cycles)
         2. Update category config
         3. Re-roll next maps if difficulty filter changed
      <- Return updated config

Admin -> POST /api/v3/tournaments/admin/reroll/{category_id}
      -> TournamentService.reroll_next_map()
         1. Select new random map from eligible pool
         2. Replace pre-rolled map for next cycle
      <- Return new map selection
```

## Database Schema Design

### New `tournaments` PostgreSQL Schema

```sql
CREATE SCHEMA IF NOT EXISTS tournaments;

-- Tournament-level configuration (singleton-ish, one row per tournament instance)
-- In V1 there is only one tournament, but the schema supports future expansion
CREATE TABLE tournaments.config (
    id              int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name            text NOT NULL DEFAULT 'Weekly Tournament',
    active          boolean NOT NULL DEFAULT true,
    created_at      timestamptz DEFAULT now(),
    updated_at      timestamptz DEFAULT now()
);

-- Categories define difficulty groupings with independent cycle frequencies
CREATE TABLE tournaments.categories (
    id              int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tournament_id   int NOT NULL REFERENCES tournaments.config(id),
    name            text NOT NULL,                          -- e.g., "Easy/Medium", "Hard/Very Hard"
    difficulties    text[] NOT NULL,                        -- e.g., {'Easy', 'Medium'}
    cycle_days      int NOT NULL DEFAULT 7,                 -- 7 = weekly, 14 = biweekly
    champion_role_id bigint,                                -- Discord role ID for this category's champion
    active          boolean NOT NULL DEFAULT true,
    created_at      timestamptz DEFAULT now(),
    updated_at      timestamptz DEFAULT now()
);

-- Each cycle is one "round" for a category
CREATE TABLE tournaments.cycles (
    id              int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    category_id     int NOT NULL REFERENCES tournaments.categories(id),
    map_code        text NOT NULL REFERENCES core.maps(code),
    cycle_number    int NOT NULL,                           -- sequential per category
    status          text NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'active', 'completed')),
    starts_at       timestamptz NOT NULL,
    ends_at         timestamptz NOT NULL,
    created_at      timestamptz DEFAULT now(),
    UNIQUE (category_id, cycle_number)
);

-- Tournament completions (separate from core.completions)
CREATE TABLE tournaments.completions (
    id              int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cycle_id        int NOT NULL REFERENCES tournaments.cycles(id),
    user_id         bigint NOT NULL REFERENCES core.users(id),
    map_code        text NOT NULL REFERENCES core.maps(code),
    time            numeric(10, 4) NOT NULL,
    screenshot      text NOT NULL,
    video           text,
    verified        boolean DEFAULT false,
    verification_tier int NOT NULL DEFAULT 0,               -- 0 = unverified, 1 = partial, 2 = full
    submitted_at    timestamptz DEFAULT now(),
    UNIQUE (cycle_id, user_id)                              -- one entry per user per cycle
);

-- Placement results computed at cycle end
CREATE TABLE tournaments.cycle_results (
    id              int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cycle_id        int NOT NULL REFERENCES tournaments.cycles(id),
    user_id         bigint NOT NULL REFERENCES core.users(id),
    placement       int NOT NULL,
    time            numeric(10, 4) NOT NULL,
    verification_tier int NOT NULL,
    xp_awarded      int NOT NULL DEFAULT 0,
    UNIQUE (cycle_id, user_id)
);

-- Map blacklist to prevent recent maps from reappearing
CREATE TABLE tournaments.map_blacklist (
    id              int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    category_id     int NOT NULL REFERENCES tournaments.categories(id),
    map_code        text NOT NULL REFERENCES core.maps(code),
    blacklisted_at  timestamptz DEFAULT now(),
    expires_at      timestamptz NOT NULL
);

-- Participation streaks
CREATE TABLE tournaments.streaks (
    user_id         bigint NOT NULL REFERENCES core.users(id),
    current_streak  int NOT NULL DEFAULT 0,
    longest_streak  int NOT NULL DEFAULT 0,
    last_cycle_id   int REFERENCES tournaments.cycles(id),
    updated_at      timestamptz DEFAULT now(),
    PRIMARY KEY (user_id)
);

-- XP configuration for placements
CREATE TABLE tournaments.xp_config (
    id              int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tournament_id   int NOT NULL REFERENCES tournaments.config(id),
    placement       int NOT NULL,                           -- 1 = first, 2 = second, etc.
    xp_amount       int NOT NULL,
    UNIQUE (tournament_id, placement)
);

-- Participation XP config
ALTER TABLE tournaments.config ADD COLUMN participation_xp int NOT NULL DEFAULT 10;
ALTER TABLE tournaments.config ADD COLUMN streak_bonus_xp int NOT NULL DEFAULT 5;
ALTER TABLE tournaments.config ADD COLUMN blacklist_weeks int NOT NULL DEFAULT 4;

-- Pending transitions (bridge between pg_cron and API)
CREATE TABLE tournaments.pending_transitions (
    id              int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    category_id     int NOT NULL REFERENCES tournaments.categories(id),
    completed_cycle_id int NOT NULL REFERENCES tournaments.cycles(id),
    new_cycle_id    int NOT NULL REFERENCES tournaments.cycles(id),
    processed       boolean NOT NULL DEFAULT false,
    created_at      timestamptz DEFAULT now()
);

-- Add tournament FK to core.completions for metadata linking
ALTER TABLE core.completions
    ADD COLUMN tournament_completion_id int
    REFERENCES tournaments.completions(id) ON DELETE SET NULL;
```

### pg_cron Transition Function

```sql
-- Called hourly by pg_cron
CREATE OR REPLACE FUNCTION tournaments.check_and_transition()
RETURNS void LANGUAGE plpgsql AS $$
DECLARE
    v_lock_acquired boolean;
    v_category record;
    v_current_cycle record;
    v_next_cycle record;
    v_new_next_cycle_id int;
    v_random_map text;
BEGIN
    v_lock_acquired := pg_try_advisory_lock(9876543210);
    IF NOT v_lock_acquired THEN RETURN; END IF;

    BEGIN
        FOR v_category IN
            SELECT c.* FROM tournaments.categories c
            JOIN tournaments.config t ON t.id = c.tournament_id
            WHERE c.active AND t.active
        LOOP
            -- Find active cycle that has ended
            SELECT * INTO v_current_cycle
            FROM tournaments.cycles
            WHERE category_id = v_category.id
              AND status = 'active'
              AND ends_at <= now();

            IF v_current_cycle IS NULL THEN CONTINUE; END IF;

            -- Mark current cycle as completed
            UPDATE tournaments.cycles SET status = 'completed'
            WHERE id = v_current_cycle.id;

            -- Activate the pre-rolled next cycle
            SELECT * INTO v_next_cycle
            FROM tournaments.cycles
            WHERE category_id = v_category.id
              AND status = 'pending'
              AND cycle_number = v_current_cycle.cycle_number + 1;

            IF v_next_cycle IS NOT NULL THEN
                UPDATE tournaments.cycles
                SET status = 'active'
                WHERE id = v_next_cycle.id;
            END IF;

            -- Blacklist the completed map
            INSERT INTO tournaments.map_blacklist (category_id, map_code, expires_at)
            VALUES (v_category.id, v_current_cycle.map_code,
                    now() + (SELECT blacklist_weeks FROM tournaments.config
                             WHERE id = v_category.tournament_id) * interval '1 week');

            -- Pre-roll the NEXT next cycle
            SELECT code INTO v_random_map
            FROM core.maps m
            WHERE m.difficulty = ANY(v_category.difficulties)
              AND m.archived = false
              AND m.hidden = false
              AND m.code NOT IN (
                  SELECT map_code FROM tournaments.map_blacklist
                  WHERE category_id = v_category.id AND expires_at > now()
              )
              AND m.code NOT IN (
                  SELECT map_code FROM tournaments.cycles
                  WHERE category_id = v_category.id AND status IN ('active', 'pending')
              )
            ORDER BY random() LIMIT 1;

            IF v_random_map IS NOT NULL AND v_next_cycle IS NOT NULL THEN
                INSERT INTO tournaments.cycles (category_id, map_code, cycle_number, status, starts_at, ends_at)
                VALUES (
                    v_category.id, v_random_map,
                    v_next_cycle.cycle_number + 1, 'pending',
                    v_next_cycle.ends_at,
                    v_next_cycle.ends_at + (v_category.cycle_days * interval '1 day')
                )
                RETURNING id INTO v_new_next_cycle_id;
            END IF;

            -- Record pending transition for API to process
            INSERT INTO tournaments.pending_transitions
                (category_id, completed_cycle_id, new_cycle_id)
            VALUES (v_category.id, v_current_cycle.id,
                    COALESCE(v_next_cycle.id, v_current_cycle.id));
        END LOOP;

        PERFORM pg_advisory_unlock(9876543210);
    EXCEPTION WHEN OTHERS THEN
        PERFORM pg_advisory_unlock(9876543210);
        RAISE;
    END;
END;
$$;
```

## Patterns to Follow

### Pattern 1: pg_cron + Pending Transitions Table (Bridge Pattern)

**What:** pg_cron performs the time-critical database mutations (cycle status changes, map selection) entirely in SQL. It writes a record to `tournaments.pending_transitions` for each transition. The API polls or is triggered to process these records, computing XP and publishing RabbitMQ events.

**When:** Any scheduled operation that needs both database mutations AND side effects (Discord announcements, XP grants).

**Why this pattern:** The existing codebase uses pg_cron for store rotations, but those are purely DB operations with no RabbitMQ messages needed. Tournament transitions require Discord-side effects, so we need a bridge. The "pending transitions" table acts as an outbox -- pg_cron writes, the API reads and processes.

**Implementation options for the API side:**
1. **Hourly API-side polling** -- A background task in the API lifespan that checks `pending_transitions` every minute. Simplest, aligns with how store rotation works (pg_cron checks hourly, transitions happen within minutes).
2. **pg_cron calls API endpoint** -- pg_cron could call `net_http_get()` but this requires `pg_net` extension which is not currently installed. Avoid adding infrastructure.
3. **LISTEN/NOTIFY** -- PostgreSQL pushes a notification that the API receives via asyncpg. More reactive but adds complexity not present elsewhere in the codebase.

**Recommendation:** Option 1 (API-side polling). Use a Litestar lifespan background task that runs every 60 seconds, checking for unprocessed pending transitions. This matches the existing DLQ processor pattern on the bot side and the hourly pg_cron pattern for store rotations.

```python
# In TournamentService
async def process_pending_transitions(self) -> None:
    """Process any pending cycle transitions."""
    pending = await self._tournament_repo.fetch_pending_transitions()
    for transition in pending:
        async with self._pool.acquire() as conn, conn.transaction():
            # Compute placements
            results = await self._tournament_repo.compute_placements(
                transition["completed_cycle_id"], conn=conn
            )
            # Store results
            await self._tournament_repo.insert_cycle_results(results, conn=conn)
            # Mark processed
            await self._tournament_repo.mark_transition_processed(
                transition["id"], conn=conn
            )

        # Publish events (outside transaction)
        await self._publish_cycle_completed(transition, results)
        await self._publish_cycle_started(transition)
        await self._grant_placement_xp(results)
```

### Pattern 2: Cross-Write with Invariant Preservation

**What:** Tournament completions live in `tournaments.completions` but conditionally propagate to `core.completions` when the tournament time is strictly faster than the user's existing best.

**When:** At submission time, within a single transaction.

**Why:** The existing `core.completions` table enforces "latest = fastest" -- the most recent record is always the fastest. Inserting a slower time would violate this invariant and break existing leaderboard queries.

```python
async def submit_completion(self, data: TournamentSubmissionRequest, ...) -> ...:
    async with self._pool.acquire() as conn, conn.transaction():
        # 1. Insert tournament completion
        tournament_completion_id = await self._tournament_repo.insert_completion(
            cycle_id=..., user_id=data.user_id,
            map_code=data.code, time=data.time, ..., conn=conn
        )

        # 2. Cross-write only if faster
        current_best = await self._completions_repo.fetch_user_best_time(
            data.user_id, data.code, conn=conn
        )
        if current_best is None or data.time < current_best:
            await self._tournament_repo.cross_write_to_core(
                user_id=data.user_id, map_code=data.code,
                time=data.time, tournament_completion_id=tournament_completion_id,
                conn=conn
            )
```

### Pattern 3: Tier-Then-Time Ranking

**What:** Tournament leaderboards rank by verification tier descending (fully verified > partially verified > unverified), then by time ascending within the same tier.

**When:** All tournament leaderboard queries and placement calculations.

```sql
SELECT user_id, time, verification_tier
FROM tournaments.completions
WHERE cycle_id = $1
ORDER BY verification_tier DESC, time ASC;
```

### Pattern 4: Pre-Rolled Map Selection

**What:** When a cycle starts, the next cycle's map is already selected ("pre-rolled"). Admins can view and reroll at any time. This avoids last-minute selection failures.

**When:** At initial tournament setup and at each cycle transition.

**Lifecycle:**
```text
Cycle N (active) + Cycle N+1 (pending, map pre-selected)
    |
    | cycle N ends (pg_cron transition)
    ▼
Cycle N (completed) + Cycle N+1 (active) + Cycle N+2 (pending, map pre-selected)
```

## Anti-Patterns to Avoid

### Anti-Pattern 1: Bot-Side Scheduling

**What:** Using `discord.ext.tasks` or asyncio loops in the bot to trigger cycle transitions.

**Why bad:** The bot is a consumer. If it crashes or restarts, transitions are missed. The API is the single source of truth -- scheduling belongs in the database (pg_cron) with the API orchestrating side effects.

**Instead:** pg_cron handles timing, API handles business logic and RabbitMQ publishing, bot handles Discord presentation only.

### Anti-Pattern 2: Batched Cross-Writes at Cycle End

**What:** Waiting until the cycle ends to cross-write all tournament completions to `core.completions`.

**Why bad:** If a user sets a tournament time that is their all-time best, the core leaderboard would be stale until the cycle ends. Players would see inconsistent data between tournament and core leaderboards. Also, a batch failure could lose cross-writes.

**Instead:** Cross-write at submission time (Flow 1 above). Each submission is atomic -- either both tournament and core records exist, or neither does.

### Anti-Pattern 3: Storing Champion State Only in Discord

**What:** Relying on Discord role membership to know who the current champion is.

**Why bad:** Discord is eventually consistent. Role operations can fail silently. The API needs to know champions for API responses.

**Instead:** Store `champion_user_id` on `tournaments.categories` (or in cycle results). The bot reads from the API and syncs the Discord role as a presentation concern.

### Anti-Pattern 4: Shared Completion Pipeline

**What:** Routing tournament submissions through the existing `POST /api/v3/completions` endpoint and adding tournament logic there.

**Why bad:** Tournament completions have different validation rules (per-cycle uniqueness, tier-then-time ranking, no existing speed enforcement from core). Mixing them pollutes the existing completions service with tournament-specific branching.

**Instead:** Separate `POST /api/v3/tournaments/submit` endpoint with its own service logic that explicitly calls the cross-write when appropriate.

## Component Build Order

The following build order respects component dependencies. Each layer depends only on layers built before it.

```text
Phase 1: Database + SDK + Repository
    tournaments schema migration
    tournaments.py SDK structs
    TournamentRepository
    (No service, no controller, no bot -- pure data layer)

Phase 2: Service + Controller (Core CRUD)
    TournamentService (config, categories, active cycles, leaderboard)
    TournamentsController (read endpoints + admin config)
    Domain exceptions (tournaments.py in services/exceptions/)
    (Tournament is queryable and configurable, but no submissions or transitions)

Phase 3: Submission Flow
    TournamentService.submit_completion() with cross-write logic
    POST /api/v3/tournaments/submit endpoint
    "api.tournament.submission" RabbitMQ event
    SDK event structs for submission
    (Players can submit, core leaderboard reflects faster times)

Phase 4: Cycle Transition (Scheduled)
    pg_cron job + SQL transition function
    tournaments.pending_transitions table
    API background task polling pending transitions
    TournamentService.process_pending_transitions()
    "api.tournament.cycle.completed" + "api.tournament.cycle.started" events
    Placement computation + XP grant publishing
    (Cycles auto-rotate, results computed, XP awarded)

Phase 5: Bot Integration
    TournamentHandler (BaseHandler subclass)
    Queue consumers for all three tournament events
    Announcement embeds (new cycle, results)
    Champion role transfer logic
    TournamentCog (slash commands)
    Bot config additions (tournament channel, champion role IDs)
    (Full Discord integration, announcements, role management)

Phase 6: Streaks + Polish
    Streak tracking in TournamentService
    Streak XP bonuses
    GET /api/v3/tournaments/streak/{user_id}
    /tournament streak slash command
    Admin preview/reroll refinements
```

**Build order rationale:**
- Phase 1 must come first because all other layers depend on the database schema and SDK types.
- Phase 2 before Phase 3 because submissions need active cycles to exist, which requires the config and category CRUD.
- Phase 3 before Phase 4 because transitions are meaningless without completion data to rank.
- Phase 4 before Phase 5 because the bot consumes events that only Phase 4 produces.
- Phase 6 is independent of the core flow and can be deferred without blocking the main system.

## Scalability Considerations

| Concern | At 100 users | At 10K users | At 1M users |
|---------|--------------|--------------|-------------|
| Leaderboard queries | Simple query, sub-ms | Index on (cycle_id, verification_tier DESC, time ASC) sufficient | Materialized view or cached results per cycle |
| Cycle transitions | Single pg_cron call, instant | Same -- transitions are per-category, not per-user | Same |
| Cross-writes | Inline with submission, negligible | Consider async cross-write if submission latency matters | Outbox pattern for cross-writes |
| Streak computation | Single row lookup per user | Same -- streaks is a user-keyed table | Same |
| Map blacklist checks | Subquery in random selection | Same -- blacklist is small (weeks, not months) | Same |

The tournament system is inherently bounded: there are few categories (2-4), few cycles active at once (1 per category), and the map pool is finite. The per-user data (completions, streaks) scales linearly but with small constants per cycle. This is not a system that needs to worry about scale -- the existing asyncpg connection pool handles the load.

## Sources

- Existing codebase patterns: `apps/api/services/base.py` (BaseService, publish_message), `apps/api/services/completions_service.py` (cross-service orchestration), `apps/api/services/store_service.py` (rotation patterns)
- pg_cron usage: `apps/api/migrations/0013_coin_store.sql` (store rotation scheduling), `apps/api/migrations/0014_quests_system.sql` (quest rotation scheduling)
- Bot consumer patterns: `apps/bot/extensions/xp.py` (XPHandler), `apps/bot/extensions/completions.py` (CompletionHandler), `apps/bot/extensions/notifications.py` (NotificationHandler)
- Queue registry: `apps/bot/extensions/_queue_registry.py` (queue_consumer decorator)
- Bot config: `apps/bot/utilities/config.py` (Config struct, role/channel IDs)
- PostgreSQL infrastructure: `infra/postgres/Dockerfile` (pg_cron extension)

---

*Architecture analysis: 2026-05-29*
