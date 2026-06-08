# Phase 1: Database Schema & Migrations - Pattern Map

**Mapped:** 2026-05-29
**Files analyzed:** 1 (new migration file)
**Analogs found:** 4 / 1

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `apps/api/migrations/0020_tournaments.sql` | migration | DDL (schema creation + ALTER TABLE) | `apps/api/migrations/0013_coin_store.sql` | exact |

**Secondary analogs (supplementary patterns):**

| Analog File | What It Provides | Match Quality |
|-------------|-----------------|---------------|
| `apps/api/migrations/0018_movement_techniques.sql` | Recent BEGIN/COMMIT wrapping, CREATE SCHEMA, multi-table migration structure | exact |
| `apps/api/migrations/0019_release_map_code.sql` | ALTER TABLE on existing core table, ADD COLUMN pattern | exact |
| `apps/api/migrations/0001_init.sql` (lines 447-487) | `core.completions` table definition, FK patterns, index naming, COMMENT ON usage | exact |

## Pattern Assignments

### `apps/api/migrations/0020_tournaments.sql` (migration, DDL)

**Primary Analog:** `apps/api/migrations/0013_coin_store.sql`
**Structure Analog:** `apps/api/migrations/0018_movement_techniques.sql`
**ALTER TABLE Analog:** `apps/api/migrations/0019_release_map_code.sql`

---

**File header pattern** (`0018_movement_techniques.sql`, lines 1-8):
```sql
-- Migration: Add content schema and movement technique tables
-- Description: Creates the content schema with movement_tech_categories,
--              movement_tech_difficulties, movement_techniques,
--              movement_tech_tips, and movement_tech_videos tables for the
--              Movement Techniques feature.
-- Date: 2026-03-29

BEGIN;
```

---

**CREATE SCHEMA pattern** (`0018_movement_techniques.sql`, line 10):
```sql
CREATE SCHEMA IF NOT EXISTS content;
```

---

**Singleton config table with CHECK(id=1)** (`0013_coin_store.sql`, lines 19-32):
```sql
CREATE TABLE store.config (
    id                    int GENERATED ALWAYS AS IDENTITY PRIMARY KEY CHECK (id = 1),
    rotation_period_days  int NOT NULL DEFAULT 7 CHECK (rotation_period_days > 0),
    last_rotation_at      timestamptz NOT NULL DEFAULT now(),
    next_rotation_at      timestamptz NOT NULL DEFAULT now() + interval '7 days',
    active_key_type       text NOT NULL DEFAULT 'Classic',

    CONSTRAINT fk_active_key_type FOREIGN KEY (active_key_type)
        REFERENCES lootbox.key_types(name) ON DELETE RESTRICT
);

COMMENT ON TABLE store.config IS 'Store configuration (singleton)';
COMMENT ON COLUMN store.config.rotation_period_days IS 'How often the store rotates (days)';
COMMENT ON COLUMN store.config.active_key_type IS 'Current active key type (cheaper pricing)';
```

---

**Singleton config INSERT with OVERRIDING SYSTEM VALUE** (`0013_coin_store.sql`, lines 266-273):
```sql
INSERT INTO store.config (
    id, rotation_period_days, last_rotation_at, next_rotation_at, active_key_type
)
OVERRIDING SYSTEM VALUE
VALUES (
    1, 7, now(), now() + interval '7 days', 'Classic'
)
ON CONFLICT (id) DO NOTHING;
```

---

**Identity column primary key pattern** (`0018_movement_techniques.sql`, lines 12-18):
```sql
CREATE TABLE IF NOT EXISTS content.movement_tech_categories
(
    id         int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name       text NOT NULL UNIQUE,
    sort_order int  NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
```

---

**TEXT CHECK constraint for status values (instead of ENUM)** (`0014_quests_system.sql`, lines 14-15):
```sql
    quest_type      text NOT NULL CHECK (quest_type IN ('global', 'bounty')),
    difficulty      text NOT NULL CHECK (difficulty IN ('easy', 'medium', 'hard')),
```

---

**FK to core.users and core.maps with ON DELETE CASCADE** (`0001_init.sql`, lines 447-451):
```sql
CREATE TABLE IF NOT EXISTS core.completions
(
    id              int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    map_id          int            NOT NULL REFERENCES core.maps (id) ON DELETE CASCADE,
    user_id         bigint         NOT NULL REFERENCES core.users (id) ON DELETE CASCADE,
```

---

**core.completions column pattern (verified, video, completion, time, screenshot)** (`0001_init.sql`, lines 452-459):
```sql
    time            numeric(10, 2) NOT NULL,
    screenshot      text           NOT NULL,
    video           text,
    verified        boolean        NOT NULL DEFAULT FALSE,
    verification_id bigint,
    message_id      bigint,
    completion      boolean        NOT NULL DEFAULT FALSE,
    inserted_at     timestamptz    NOT NULL DEFAULT now(),
```

---

**UNIQUE constraint pattern** (`0001_init.sql`, lines 465-466):
```sql
    UNIQUE (map_id, user_id, inserted_at),
    UNIQUE (message_id)
```

---

**Named index pattern** (`0001_init.sql`, lines 469-474):
```sql
CREATE INDEX IF NOT EXISTS idx_records_map_user_date ON core.completions (map_id, user_id, inserted_at DESC);
CREATE INDEX IF NOT EXISTS idx_records_inserted_at ON core.completions (inserted_at);
CREATE INDEX IF NOT EXISTS idx_records_user_date ON core.completions (user_id, inserted_at);
CREATE INDEX IF NOT EXISTS idx_records_map_id ON core.completions (map_id);
CREATE INDEX IF NOT EXISTS idx_completions_verified_nonlegacy_pair ON core.completions (user_id, map_id) WHERE verified = TRUE AND legacy = FALSE;
CREATE INDEX IF NOT EXISTS idx_completions_nonlegacy_best ON core.completions (user_id, map_id, time) WHERE legacy = FALSE;
```

---

**Partial index pattern** (`0014_quests_system.sql`, lines 77-78):
```sql
CREATE INDEX idx_user_quest_progress_unclaimed ON store.user_quest_progress (user_id, completed_at)
    WHERE completed_at IS NOT NULL AND claimed_at IS NULL;
```

---

**FK index pattern** (`0018_movement_techniques.sql`, lines 57-60):
```sql
CREATE INDEX IF NOT EXISTS idx_movement_techniques_category_id ON content.movement_techniques (category_id);
CREATE INDEX IF NOT EXISTS idx_movement_techniques_difficulty_id ON content.movement_techniques (difficulty_id);
CREATE INDEX IF NOT EXISTS idx_movement_tech_tips_technique_id ON content.movement_tech_tips (technique_id);
CREATE INDEX IF NOT EXISTS idx_movement_tech_videos_technique_id ON content.movement_tech_videos (technique_id);
```

---

**COMMENT ON table and column pattern** (`0001_init.sql`, lines 476-486):
```sql
COMMENT ON COLUMN core.completions.time IS 'How long it took the user to complete a the map';
COMMENT ON COLUMN core.completions.screenshot IS 'The URL to the uploaded screenshot';
COMMENT ON COLUMN core.completions.video IS 'The URL to the uploaded video (Usually YouTube)';
COMMENT ON COLUMN core.completions.verified IS 'If the record has been verified';
COMMENT ON COLUMN core.completions.verification_id IS 'The verification queue message ID snowflake in Discord';
COMMENT ON COLUMN core.completions.message_id IS 'The completions channel message ID snowflake in Discord';
COMMENT ON COLUMN core.completions.completion IS 'Whether the submission counts as a completion (submissions while in playtest are completions as well as submissions that lack a video)';
```

---

**ALTER TABLE ADD COLUMN on existing core table** (`0019_release_map_code.sql`, lines 12-13):
```sql
ALTER TABLE core.maps ADD COLUMN original_code text;
COMMENT ON COLUMN core.maps.original_code IS 'Preserves the map code after a release-code operation. NULL for active maps.';
```

---

**Transaction COMMIT** (`0018_movement_techniques.sql`, line 62):
```sql
COMMIT;
```

## Shared Patterns

### Schema Naming Convention
**Source:** All migrations
**Apply to:** `0020_tournaments.sql`
- Schema names are lowercase single words: `core`, `maps`, `store`, `content`, `tournaments`
- Table references use dot notation: `schema.table_name`
- All constraint references cross-schema use full path: `core.maps(id)`, `core.users(id)`

### Identity Column Convention
**Source:** Every migration (`0001`, `0013`, `0014`, `0018`)
**Apply to:** All tournament tables
```sql
id int GENERATED ALWAYS AS IDENTITY PRIMARY KEY
```
- Never use `serial` or `bigserial`
- Use `bigint` only for tables that may exceed int range (user-facing tables with Discord snowflake IDs)

### Timestamp Convention
**Source:** `0001_init.sql`, `0013_coin_store.sql`, `0018_movement_techniques.sql`
**Apply to:** All tournament tables with timestamps
```sql
created_at timestamptz NOT NULL DEFAULT now()
```
- Always use `timestamptz`, never `timestamp`
- Always include `NOT NULL DEFAULT now()` on creation timestamps
- Nullable timestamps (like `started_at`, `ended_at`) omit the DEFAULT

### IF NOT EXISTS vs. Bare CREATE
**Source:** `0018_movement_techniques.sql` uses `IF NOT EXISTS` on all tables and indexes; `0013_coin_store.sql` does NOT use `IF NOT EXISTS`
**Apply to:** `0020_tournaments.sql`
- Newer migrations (0018) prefer `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS`
- This is safe for re-runnable migrations within a BEGIN/COMMIT block
- Follow the 0018 pattern (more recent, more defensive)

### FK Data Types
**Source:** `0001_init.sql` lines 450-451
**Apply to:** All tournament tables referencing core tables
- `core.users(id)` is `bigint` -- FK columns must be `bigint`
- `core.maps(id)` is `int GENERATED ALWAYS AS IDENTITY` -- FK columns must be `int`
- Internal tournament table FKs match the referenced column type (`int` for tournament identity columns)

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| -- | -- | -- | All patterns for this phase have exact analogs in existing migrations |

No files lack analogs. The `0020_tournaments.sql` migration is fully covered by combining patterns from `0013_coin_store.sql` (singleton config), `0018_movement_techniques.sql` (multi-table schema creation with BEGIN/COMMIT), `0019_release_map_code.sql` (ALTER TABLE on existing table), and `0001_init.sql` (core.completions structure, FK patterns, indexes, comments).

## Metadata

**Analog search scope:** `apps/api/migrations/`
**Files scanned:** 19 migration files
**Pattern extraction date:** 2026-05-29
