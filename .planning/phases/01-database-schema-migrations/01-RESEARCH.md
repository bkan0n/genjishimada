# Phase 1: Database Schema & Migrations - Research

**Researched:** 2026-05-29
**Domain:** PostgreSQL schema design, migration authoring
**Confidence:** HIGH

## Summary

Phase 1 creates the `tournaments` PostgreSQL schema as a single migration file (`0020_tournaments.sql`). The schema follows every established pattern from the existing codebase: identity columns, `timestamptz` timestamps, `core.users(id)` and `core.maps(id)` FK references, named indexes, and table/column comments. The migration also ALTER TABLEs `core.completions` to add a nullable `tournament_completion_id` FK.

All 10 locked decisions from CONTEXT.md have been validated against the existing schema and present no conflicts. The most important structural findings are: (1) maps live in `core.maps`, not `maps.maps` -- all FK references must target `core.maps(id)`, (2) the singleton config pattern from `store.config` uses `CHECK(id = 1)` with `GENERATED ALWAYS AS IDENTITY`, and (3) the speed enforcement trigger on `core.completions` fires on INSERT/UPDATE but only matters for Phase 6 cross-writes, not for the ALTER TABLE in this phase.

**Primary recommendation:** Write a single `0020_tournaments.sql` migration file wrapped in `BEGIN;`/`COMMIT;` that creates the schema, all tables, indexes, comments, and the ALTER TABLE on `core.completions`. No pg_cron jobs, no PL/pgSQL functions, no seed data -- those belong in later phases.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Tournament completions use the same boolean column pattern as `core.completions` -- `verified boolean`, `video text`, `completion boolean`. No new tier column type.
- **D-02:** Tier-then-time ranking is two tiers only: verified > unverified. Derived at query time via `ORDER BY verified DESC, time ASC`. The `video` column exists for data but does not affect ranking.
- **D-03:** Map cooldown is global -- a map used in ANY category goes on cooldown for ALL categories.
- **D-04:** No separate blacklist table. Cooldown is derived from cycle history: exclude maps where `started_at > now() - interval N weeks` from the `tournaments.cycles` table. The `blacklist_weeks` config value controls the window.
- **D-05:** All XP configuration is per-category, NOT global. The `tournaments.categories` table holds: `participation_xp int`, `placement_xp jsonb`, `streak_xp jsonb`.
- **D-06:** The `tournaments.config` singleton holds global settings only (e.g., `blacklist_weeks`). No XP values on the global config.
- **D-07:** New `tournaments` schema following existing multi-schema pattern (core, maps, store, etc.)
- **D-08:** Singleton config table with `CHECK(id = 1)` following `store.config` pattern
- **D-09:** Nullable `tournament_completion_id` FK added to `core.completions` via ALTER TABLE
- **D-10:** Migration file numbered `0020_tournaments.sql`

### Claude's Discretion
No specific requirements -- open to standard approaches following existing codebase patterns.

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

This is a foundation phase with no direct requirement mapping. It enables all 25 v1 requirements by providing the database schema that every downstream phase builds upon.

| Success Criterion | Research Support |
|----|------------------|
| SC-1: `tournaments` schema with tables for config, categories, cycles, completions, streaks, pending_transitions, and completion_links | Table designs documented in Architecture Patterns; D-04 eliminated blacklist table; D-05/D-06 clarified XP config placement |
| SC-2: Migration runs cleanly without conflicts | No naming collisions with existing schemas (core, maps, completions, playtests, users, lootbox, rank_card, store, content, public); BEGIN/COMMIT wrapping pattern from migration 0018 |
| SC-3: FK relationships to core.users, core.maps, and internal tables | Verified FK targets: `core.users(id)` is `bigint`, `core.maps(id)` is `int GENERATED ALWAYS AS IDENTITY`; no `maps.maps` table exists |
| SC-4: CHECK(id = 1) singleton on config | Exact pattern verified from `store.config`: `int GENERATED ALWAYS AS IDENTITY PRIMARY KEY CHECK (id = 1)` |
| SC-5: `core.completions` ALTER TABLE with nullable `tournament_completion_id` FK | Table structure verified; column is safe to add (nullable, no default, no rewrite); FK references `tournaments.completions(id)` |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Schema creation | Database / Storage | -- | Pure DDL, no application code |
| Table constraints & indexes | Database / Storage | -- | Enforced at DB level per project pattern |
| FK relationships to existing tables | Database / Storage | -- | Cross-schema references, DB-level integrity |
| ALTER TABLE on core.completions | Database / Storage | -- | Modifying existing table structure |
| Migration file authoring | Database / Storage | -- | SQL file in `apps/api/migrations/` |

## Standard Stack

No external packages are installed in this phase. This is a pure SQL migration.

### Core
| Tool | Version | Purpose | Why Standard |
|------|---------|---------|--------------|
| PostgreSQL | 17 | Database engine | Project standard, custom Docker image at `infra/postgres/Dockerfile` [VERIFIED: Dockerfile] |
| pg_cron | (bundled) | Extension available for later phases | Preloaded in Dockerfile, not used in this phase [VERIFIED: Dockerfile] |

### Supporting
N/A -- no application dependencies for a DDL migration.

## Package Legitimacy Audit

No packages are installed in this phase. This section is intentionally empty.

## Architecture Patterns

### System Architecture Diagram

```
0020_tournaments.sql
        |
        v
  +-----------+
  | BEGIN;    |
  +-----------+
        |
        v
  +----------------------------+
  | CREATE SCHEMA tournaments  |
  +----------------------------+
        |
        v
  +----------------------------+      +-----------------------+
  | tournaments.config         |      | tournaments.categories|
  | (singleton, CHECK id=1)    |<-----| (per-category config) |
  +----------------------------+      +-----------------------+
                                              |
                                              v
                                    +---------------------+
                                    | tournaments.cycles  |
                                    | (FK -> categories)  |
                                    +---------------------+
                                              |
                                              v
                              +-------------------------------+
                              | tournaments.completions       |
                              | (FK -> cycles, core.users,    |
                              |  core.maps)                   |
                              +-------------------------------+
                                              |
                                              v
                              +-------------------------------+
                              | ALTER TABLE core.completions  |
                              | ADD tournament_completion_id  |
                              | FK -> tournaments.completions |
                              +-------------------------------+
                                              |
        +-------------------------------------+
        |                                     |
        v                                     v
+-------------------------+     +------------------------------+
| tournaments.streaks     |     | tournaments.pending_         |
| (FK -> core.users)      |     | transitions                  |
+-------------------------+     | (FK -> cycles, outbox table) |
                                +------------------------------+
        |
        v
  +-----------+
  | COMMIT;   |
  +-----------+
```

### Recommended File Structure
```
apps/api/migrations/
    0020_tournaments.sql    # Single migration file for this phase
```

### Pattern 1: Singleton Config Table
**What:** A table constrained to exactly one row via `CHECK(id = 1)`, used for global configuration.
**When to use:** When a domain needs exactly one configuration record.
**Example:**
```sql
-- Source: apps/api/migrations/0013_coin_store.sql (store.config)
CREATE TABLE tournaments.config (
    id                int GENERATED ALWAYS AS IDENTITY PRIMARY KEY CHECK (id = 1),
    blacklist_weeks   int NOT NULL DEFAULT 4 CHECK (blacklist_weeks > 0),
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);
```
[VERIFIED: migration 0013 lines 19-28]

### Pattern 2: Identity Column Primary Keys
**What:** All tables use `int GENERATED ALWAYS AS IDENTITY PRIMARY KEY` for auto-incrementing IDs, except user-facing tables that use Discord snowflake bigints.
**When to use:** Every tournament-internal table.
**Example:**
```sql
-- Source: apps/api/migrations/0001_init.sql pattern
id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY
```
[VERIFIED: migrations 0001, 0013, 0014, 0018]

### Pattern 3: Foreign Keys to Core Tables
**What:** Tournament tables reference `core.users(id)` as `bigint` and `core.maps(id)` as `int`.
**When to use:** Any table that links to a user or map.
**Critical finding:** There is NO `maps.maps` table. All map references go to `core.maps(id)`. The ROADMAP.md mentions `maps.maps(id)` but this is incorrect.
```sql
-- Source: apps/api/migrations/0001_init.sql (every FK to maps)
user_id  bigint NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
map_id   int    NOT NULL REFERENCES core.maps(id) ON DELETE CASCADE,
```
[VERIFIED: migration 0001 lines 450-451]

### Pattern 4: Transaction-Wrapped Migrations
**What:** Migrations that modify multiple objects are wrapped in `BEGIN;` / `COMMIT;`.
**When to use:** Any migration creating multiple tables or modifying existing tables.
**Example:**
```sql
-- Source: apps/api/migrations/0018_movement_techniques.sql
BEGIN;
-- ... DDL statements ...
COMMIT;
```
[VERIFIED: migrations 0018, 0019]

Note: Migration 0001 uses `BEGIN;` at the top but its `COMMIT;` is at the very end (line 1639). Migration 0013 does NOT use explicit BEGIN/COMMIT (relies on auto-commit per statement). The more recent pattern (0018, 0019) uses explicit `BEGIN;`/`COMMIT;`.

### Pattern 5: Named Indexes
**What:** All indexes follow the naming convention `idx_{table}_{columns}`.
**When to use:** Every index.
```sql
-- Source: apps/api/migrations/0001_init.sql
CREATE INDEX IF NOT EXISTS idx_records_map_user_date ON core.completions (map_id, user_id, inserted_at DESC);
```
[VERIFIED: migration 0001 lines 469-474]

### Pattern 6: Table and Column Comments
**What:** Every table and significant column gets a `COMMENT ON` statement.
**When to use:** All new tables and non-obvious columns.
```sql
-- Source: apps/api/migrations/0013_coin_store.sql
COMMENT ON TABLE store.config IS 'Store configuration (singleton)';
COMMENT ON COLUMN store.config.rotation_period_days IS 'How often the store rotates (days)';
```
[VERIFIED: migration 0013 lines 30-32]

### Anti-Patterns to Avoid
- **Using `maps.maps` as FK target:** There is no `maps.maps` table. Maps live in `core.maps`. [VERIFIED: grep of all migrations -- zero references to `maps.maps`]
- **Adding NOT NULL column with volatile default to existing table:** Adding a NOT NULL column with `DEFAULT now()` to `core.completions` would rewrite the entire table. The `tournament_completion_id` column must be nullable with no default. [CITED: postgresql-table-design skill]
- **Forgetting FK column indexes:** PostgreSQL does NOT auto-index FK columns. Every FK column needs an explicit index. [CITED: postgresql-table-design skill]
- **Using `serial` instead of `GENERATED ALWAYS AS IDENTITY`:** Project uses identity columns exclusively. [VERIFIED: all migrations]
- **Using `varchar(n)` or `char(n)`:** Project uses `text` for all string columns. [VERIFIED: all migrations]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Auto-incrementing IDs | Custom sequence management | `GENERATED ALWAYS AS IDENTITY` | Project standard, prevents accidental value override |
| Singleton constraint | Application-level enforcement | `CHECK(id = 1)` DB constraint | Cannot be bypassed, proven pattern from store.config |
| Map cooldown/blacklist | Separate blacklist table | Query-time derivation from `tournaments.cycles` | D-04 locked decision, simpler, no sync issues |
| Difficulty filtering | Custom difficulty logic in SQL | Store `text[]` of difficulty names, match against `core.maps.difficulty` | Leverages existing difficulty column |

## Common Pitfalls

### Pitfall 1: FK to Non-Existent `maps.maps` Table
**What goes wrong:** Migration fails with `relation "maps.maps" does not exist`.
**Why it happens:** The ROADMAP.md mentions `maps.maps(id)` as an FK target, but this table does not exist. Maps are stored in `core.maps`.
**How to avoid:** All map FK references must use `REFERENCES core.maps(id)`.
**Warning signs:** Any `REFERENCES maps.maps` in the migration SQL.

### Pitfall 2: Missing FK Column Indexes
**What goes wrong:** Queries joining on FK columns perform full table scans; parent table deletes/updates cause lock escalation.
**Why it happens:** PostgreSQL does not automatically create indexes on FK columns (unlike some ORMs that do).
**How to avoid:** Add explicit `CREATE INDEX` for every FK column: `user_id`, `map_id`, `category_id`, `cycle_id`, `tournament_completion_id`.
**Warning signs:** Any FK column without a corresponding `CREATE INDEX` statement.

### Pitfall 3: Table Rewrite on ALTER TABLE core.completions
**What goes wrong:** Adding a `NOT NULL` column or a column with a volatile `DEFAULT` to `core.completions` rewrites the entire table, causing extended lock time.
**Why it happens:** PostgreSQL must fill in values for every existing row.
**How to avoid:** The `tournament_completion_id` column MUST be nullable with no default. This is a metadata-only operation in PostgreSQL -- near-instant regardless of table size.
**Warning signs:** `NOT NULL` or `DEFAULT` clause on the ALTER TABLE ADD COLUMN statement.

### Pitfall 4: Forgetting BEGIN/COMMIT Transaction Wrapper
**What goes wrong:** A failure partway through the migration leaves the database in a partially-migrated state.
**Why it happens:** Without explicit transaction wrapping, each statement auto-commits.
**How to avoid:** Wrap the entire migration in `BEGIN;` / `COMMIT;`.
**Warning signs:** Missing `BEGIN;` at the top of the migration file.

### Pitfall 5: XP Config on Wrong Table
**What goes wrong:** XP values placed on `tournaments.config` instead of `tournaments.categories` contradicts D-05/D-06 and makes per-category XP configuration impossible.
**Why it happens:** Natural instinct to centralize config.
**How to avoid:** `tournaments.config` holds ONLY global settings (`blacklist_weeks`). XP columns (`participation_xp`, `placement_xp`, `streak_xp`) go on `tournaments.categories`.
**Warning signs:** Any `xp` column on the config table.

### Pitfall 6: Cycle Status as Enum Type
**What goes wrong:** Using `CREATE TYPE ... AS ENUM` for cycle status makes future status additions require a migration with `ALTER TYPE ... ADD VALUE` which cannot run inside a transaction.
**Why it happens:** Enum feels like the right choice for a small set of values.
**How to avoid:** Use `text NOT NULL CHECK(status IN ('pending', 'active', 'finalizing', 'completed'))` instead. This is the pattern used throughout the codebase (e.g., `store.purchases.purchase_type`).
**Warning signs:** Any `CREATE TYPE` statement for tournament status values.

## Code Examples

### Complete Table: tournaments.config (Singleton)
```sql
-- Source: Derived from store.config pattern (migration 0013)
CREATE TABLE tournaments.config (
    id              int GENERATED ALWAYS AS IDENTITY PRIMARY KEY CHECK (id = 1),
    blacklist_weeks int         NOT NULL DEFAULT 4 CHECK (blacklist_weeks > 0),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE tournaments.config IS 'Tournament global configuration (singleton)';
COMMENT ON COLUMN tournaments.config.blacklist_weeks IS 'Number of weeks a map is excluded after being used in any category';
```

### Complete Table: tournaments.categories
```sql
-- Source: Derived from D-05, D-06 decisions and existing patterns
CREATE TABLE tournaments.categories (
    id               int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name             text        NOT NULL UNIQUE,
    difficulties     text[]      NOT NULL,
    cycle_frequency  text        NOT NULL DEFAULT 'weekly'
                     CHECK (cycle_frequency IN ('weekly', 'biweekly')),
    participation_xp int         NOT NULL DEFAULT 0,
    placement_xp     jsonb       NOT NULL DEFAULT '[]'::jsonb,
    streak_xp        jsonb       NOT NULL DEFAULT '[]'::jsonb,
    champion_role_id bigint,
    is_active        boolean     NOT NULL DEFAULT TRUE,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE tournaments.categories IS 'Tournament difficulty categories with per-category XP config';
COMMENT ON COLUMN tournaments.categories.difficulties IS 'Array of DifficultyTop values this category includes';
COMMENT ON COLUMN tournaments.categories.cycle_frequency IS 'How often cycles rotate: weekly or biweekly';
COMMENT ON COLUMN tournaments.categories.participation_xp IS 'Flat XP bonus for first submission per cycle';
COMMENT ON COLUMN tournaments.categories.placement_xp IS 'JSON array of {place: N, xp: N} placement bonuses';
COMMENT ON COLUMN tournaments.categories.streak_xp IS 'JSON array of {threshold: N, xp: N} streak bonuses';
COMMENT ON COLUMN tournaments.categories.champion_role_id IS 'Discord role ID for category champion';
```

### Complete Table: tournaments.cycles
```sql
-- Source: Derived from requirements CYCLE-01 through CYCLE-08
CREATE TABLE tournaments.cycles (
    id          int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    category_id int         NOT NULL REFERENCES tournaments.categories(id) ON DELETE CASCADE,
    map_id      int         NOT NULL REFERENCES core.maps(id) ON DELETE RESTRICT,
    status      text        NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'active', 'finalizing', 'completed')),
    started_at  timestamptz,
    ended_at    timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_cycles_category_id ON tournaments.cycles (category_id);
CREATE INDEX idx_cycles_map_id ON tournaments.cycles (map_id);
CREATE INDEX idx_cycles_status ON tournaments.cycles (status);
CREATE INDEX idx_cycles_category_status ON tournaments.cycles (category_id, status);
CREATE INDEX idx_cycles_started_at ON tournaments.cycles (started_at);

COMMENT ON TABLE tournaments.cycles IS 'Tournament cycles -- one per category per rotation period';
COMMENT ON COLUMN tournaments.cycles.status IS 'Lifecycle: pending -> active -> finalizing -> completed';
COMMENT ON COLUMN tournaments.cycles.started_at IS 'When cycle became active (NULL while pending)';
COMMENT ON COLUMN tournaments.cycles.ended_at IS 'When cycle was finalized (NULL while active)';
```

### Complete Table: tournaments.completions
```sql
-- Source: Mirrors core.completions boolean pattern per D-01, D-02
CREATE TABLE tournaments.completions (
    id          int            GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cycle_id    int            NOT NULL REFERENCES tournaments.cycles(id) ON DELETE CASCADE,
    user_id     bigint         NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    map_id      int            NOT NULL REFERENCES core.maps(id) ON DELETE CASCADE,
    time        numeric(10, 2) NOT NULL,
    screenshot  text           NOT NULL,
    video       text,
    verified    boolean        NOT NULL DEFAULT FALSE,
    completion  boolean        NOT NULL DEFAULT FALSE,
    inserted_at timestamptz    NOT NULL DEFAULT now(),
    UNIQUE (cycle_id, user_id, inserted_at)
);

CREATE INDEX idx_tournament_completions_cycle_id ON tournaments.completions (cycle_id);
CREATE INDEX idx_tournament_completions_user_id ON tournaments.completions (user_id);
CREATE INDEX idx_tournament_completions_map_id ON tournaments.completions (map_id);
CREATE INDEX idx_tournament_completions_cycle_user ON tournaments.completions (cycle_id, user_id);
-- Leaderboard query index: tier-then-time ranking per D-02
CREATE INDEX idx_tournament_completions_ranking
    ON tournaments.completions (cycle_id, verified DESC, time ASC);

COMMENT ON TABLE tournaments.completions IS 'Tournament-specific completion records, separate from core.completions';
COMMENT ON COLUMN tournaments.completions.verified IS 'Whether the completion has been verified (affects ranking tier)';
COMMENT ON COLUMN tournaments.completions.video IS 'URL to uploaded video (does not affect ranking per D-02)';
COMMENT ON COLUMN tournaments.completions.completion IS 'Whether submission counts as a full completion';
```

### ALTER TABLE core.completions
```sql
-- Source: D-09 decision
ALTER TABLE core.completions
    ADD COLUMN tournament_completion_id int REFERENCES tournaments.completions(id) ON DELETE SET NULL;

CREATE INDEX idx_completions_tournament_completion_id
    ON core.completions (tournament_completion_id)
    WHERE tournament_completion_id IS NOT NULL;

COMMENT ON COLUMN core.completions.tournament_completion_id IS 'Link to tournament completion that produced this record (NULL for non-tournament submissions)';
```

### Complete Table: tournaments.streaks
```sql
-- Source: RWD-04 requirement
CREATE TABLE tournaments.streaks (
    id              int         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id         bigint      NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    current_streak  int         NOT NULL DEFAULT 0,
    max_streak      int         NOT NULL DEFAULT 0,
    last_cycle_id   int         REFERENCES tournaments.cycles(id) ON DELETE SET NULL,
    updated_at      timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX idx_streaks_user_id ON tournaments.streaks (user_id);

COMMENT ON TABLE tournaments.streaks IS 'Per-user weekly participation streak tracking';
COMMENT ON COLUMN tournaments.streaks.current_streak IS 'Consecutive cycles with at least one submission';
COMMENT ON COLUMN tournaments.streaks.max_streak IS 'Highest streak ever achieved';
COMMENT ON COLUMN tournaments.streaks.last_cycle_id IS 'Last cycle the user participated in';
```

### Complete Table: tournaments.pending_transitions
```sql
-- Source: Phase 7 outbox pattern requirement
CREATE TABLE tournaments.pending_transitions (
    id          int         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cycle_id    int         NOT NULL REFERENCES tournaments.cycles(id) ON DELETE CASCADE,
    event_type  text        NOT NULL CHECK (event_type IN ('cycle_started', 'cycle_completed')),
    payload     jsonb       NOT NULL DEFAULT '{}'::jsonb,
    published   boolean     NOT NULL DEFAULT FALSE,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_pending_transitions_unpublished
    ON tournaments.pending_transitions (published, created_at)
    WHERE published = FALSE;
CREATE INDEX idx_pending_transitions_cycle_id ON tournaments.pending_transitions (cycle_id);

COMMENT ON TABLE tournaments.pending_transitions IS 'Outbox table for cycle transition events to be published to RabbitMQ';
COMMENT ON COLUMN tournaments.pending_transitions.published IS 'Whether this event has been picked up and published to RabbitMQ';
```

### Config Initialization
```sql
-- Source: Pattern from store.config (migration 0013 lines 266-273)
INSERT INTO tournaments.config (blacklist_weeks)
OVERRIDING SYSTEM VALUE
VALUES (4)
ON CONFLICT (id) DO NOTHING;
```
Note: The `OVERRIDING SYSTEM VALUE` is NOT needed here since we are not specifying `id` -- the identity column generates it automatically. However, looking at the store.config pattern more carefully, it explicitly sets `id = 1`. For the singleton pattern to work correctly on first insert, we can either:
- Let the identity generate `id = 1` naturally (first insert always gets 1), OR
- Explicitly set `id = 1` with `OVERRIDING SYSTEM VALUE`

The safer approach (matching `store.config` exactly) is to explicitly set `id = 1`:
```sql
INSERT INTO tournaments.config (id, blacklist_weeks)
OVERRIDING SYSTEM VALUE
VALUES (1, 4)
ON CONFLICT (id) DO NOTHING;
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `serial` columns | `GENERATED ALWAYS AS IDENTITY` | PG10+ | Project already uses identity exclusively |
| `varchar(n)` | `text` with CHECK constraints | Project convention | No length-limited varchar in codebase |
| `CREATE TYPE AS ENUM` for statuses | `text CHECK(... IN (...))` | Project convention | Avoids ALTER TYPE issues in transactions |
| Separate blacklist table | Query-time derivation from cycle history | D-04 decision | Simpler, no sync issues |

**Deprecated/outdated:**
- `serial` type: Not used anywhere in codebase, do not introduce.
- `varchar(n)`: Not used for general strings, only `text` or `text` with CHECK.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `difficulties text[]` on categories stores DifficultyTop values (e.g., `{'Easy', 'Medium'}`) | Code Examples (categories) | Low -- column type is flexible; service layer maps values |
| A2 | `placement_xp jsonb DEFAULT '[]'` stores array of `{place, xp}` objects | Code Examples (categories) | Low -- JSONB is schemaless; service layer validates |
| A3 | `streak_xp jsonb DEFAULT '[]'` stores array of `{threshold, xp}` objects | Code Examples (categories) | Low -- same as A2 |
| A4 | Cycle status values are `pending`, `active`, `finalizing`, `completed` | Code Examples (cycles) | Medium -- Phase 7 may need additional statuses; CHECK constraint is easy to ALTER |
| A5 | `ON DELETE RESTRICT` on `cycles.map_id` FK (prevent map deletion while used in tournament) | Code Examples (cycles) | Low -- could be CASCADE but RESTRICT is safer for data integrity |
| A6 | Config table only needs `blacklist_weeks` initially | Code Examples (config) | Low -- additional columns can be added in later phases via ALTER TABLE |
| A7 | `pending_transitions.event_type` values are `cycle_started` and `cycle_completed` | Code Examples (pending_transitions) | Medium -- Phase 7 may define additional event types |

## Open Questions

1. **Should `tournaments.completions` allow multiple submissions per user per cycle?**
   - What we know: `core.completions` has `UNIQUE (map_id, user_id, inserted_at)` allowing multiple submissions if timestamps differ. The speed enforcement trigger allows only faster times.
   - What's unclear: Whether tournament completions should follow the same pattern or only keep the latest/best per cycle.
   - Recommendation: Allow multiple submissions per user per cycle (matching core pattern) with `UNIQUE (cycle_id, user_id, inserted_at)`. The leaderboard query selects the best per user. This preserves submission history and matches existing behavior.

2. **Should the config table have `updated_at` with a trigger?**
   - What we know: `core.users` and `core.maps` have `set_updated_at()` triggers. `store.config` does NOT have one.
   - What's unclear: Whether tournament config needs change tracking.
   - Recommendation: Add `updated_at` column but skip the trigger for now (matches `store.config` pattern). Can be added later if needed.

3. **What ON DELETE behavior for `core.completions.tournament_completion_id` FK?**
   - What we know: If a tournament completion is deleted, the core completion should remain but lose its tournament link.
   - What's unclear: Whether tournament completions would ever be deleted.
   - Recommendation: Use `ON DELETE SET NULL` -- safest option, preserves core data.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.3.5+ with pytest-databases[postgres] |
| Config file | `apps/api/pyproject.toml` (pytest section) |
| Quick run command | `uv run --directory apps/api pytest tests/test_conftest.py -v -p no:xdist` |
| Full suite command | `just test-api` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SC-1 | tournaments schema and tables exist | integration | `uv run --directory apps/api pytest tests/integration/test_tournaments_schema.py -v -p no:xdist` | No -- Wave 0 |
| SC-2 | Migration runs without conflicts | integration | Same test file -- migration applied by conftest `setup_test_db` fixture | No -- Wave 0 |
| SC-3 | FK relationships valid | integration | Query `information_schema.table_constraints` | No -- Wave 0 |
| SC-4 | Singleton CHECK constraint | integration | Attempt to insert id=2, verify failure | No -- Wave 0 |
| SC-5 | `core.completions.tournament_completion_id` column exists | integration | Query `information_schema.columns` | No -- Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run --directory apps/api pytest tests/test_conftest.py -v -p no:xdist`
- **Per wave merge:** `just test-api`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `apps/api/tests/integration/test_tournaments_schema.py` -- covers SC-1 through SC-5
- [ ] No new fixtures needed -- existing `asyncpg_conn` fixture sufficient for schema introspection queries

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | N/A -- no auth in DDL phase |
| V3 Session Management | No | N/A |
| V4 Access Control | No | N/A -- access control added in Phase 4 |
| V5 Input Validation | Yes | DB-level CHECK constraints, FK constraints |
| V6 Cryptography | No | N/A |

### Known Threat Patterns for PostgreSQL DDL

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Schema injection via migration | Tampering | Migration file is code-reviewed, not user-supplied |
| Constraint bypass | Elevation of Privilege | CHECK and FK constraints enforced at DB level |
| Data loss from overly-aggressive CASCADE | Denial of Service | Use RESTRICT where deletion should be prevented (tournament cycle maps) |

## Sources

### Primary (HIGH confidence)
- `apps/api/migrations/0001_init.sql` -- core.completions structure, core.maps structure, core.users structure, FK patterns, index naming, timestamp patterns
- `apps/api/migrations/0013_coin_store.sql` -- singleton config pattern (CHECK(id=1), GENERATED ALWAYS AS IDENTITY, pg_cron setup, OVERRIDING SYSTEM VALUE insert)
- `apps/api/migrations/0014_quests_system.sql` -- quest_config singleton (CHECK(id=1)), JSONB config patterns, pg_cron scheduling
- `apps/api/migrations/0017_fix_speed_trigger_check_verified.sql` -- current speed enforcement trigger (relevant for Phase 6 cross-write awareness)
- `apps/api/migrations/0018_movement_techniques.sql` -- recent migration pattern (BEGIN/COMMIT wrapping, IF NOT EXISTS, FK patterns)
- `apps/api/migrations/0019_release_map_code.sql` -- ALTER TABLE pattern on core.maps
- `apps/api/conftest.py` -- migration execution mechanism (sorted glob of *.sql files)
- `infra/postgres/Dockerfile` -- PostgreSQL 17, pg_cron extension
- `libs/sdk/src/genjishimada_sdk/difficulties.py` -- DifficultyTop and DifficultyAll type definitions
- `libs/sdk/src/genjishimada_sdk/maps.py` -- MapCategory definition

### Secondary (MEDIUM confidence)
- `.agents/skills/postgresql-table-design/SKILL.md` -- best practices for identity columns, FK indexing, data types, ALTER TABLE behavior

### Tertiary (LOW confidence)
- None -- all findings verified against codebase

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- pure SQL, no external dependencies, all patterns verified in existing migrations
- Architecture: HIGH -- table designs follow established codebase patterns and locked decisions
- Pitfalls: HIGH -- every pitfall identified from real codebase patterns or verified PostgreSQL behavior

**Research date:** 2026-05-29
**Valid until:** 2026-06-28 (stable -- PostgreSQL schema patterns do not change frequently)
