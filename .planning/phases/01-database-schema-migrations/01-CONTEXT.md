# Phase 1: Database Schema & Migrations - Context

**Gathered:** 2026-05-29
**Status:** Ready for planning

<domain>
## Phase Boundary

Create the `tournaments` PostgreSQL schema with all tables, constraints, indexes, and the `core.completions` ALTER TABLE — the foundation for every downstream layer. No API code, no SDK types, no service logic.

</domain>

<decisions>
## Implementation Decisions

### Verification Tiers
- **D-01:** Tournament completions use the same boolean column pattern as `core.completions` — `verified boolean`, `video text`, `completion boolean`. No new tier column type.
- **D-02:** Tier-then-time ranking is two tiers only: verified > unverified. Derived at query time via `ORDER BY verified DESC, time ASC`. The `video` column exists for data but does not affect ranking.

### Blacklist / Map Cooldown
- **D-03:** Map cooldown is global — a map used in ANY category goes on cooldown for ALL categories.
- **D-04:** No separate blacklist table. Cooldown is derived from cycle history: exclude maps where `started_at > now() - interval N weeks` from the `tournaments.cycles` table. The `blacklist_weeks` config value controls the window.

### XP Configuration
- **D-05:** All XP configuration is per-category, NOT global. The `tournaments.categories` table holds: `participation_xp int`, `placement_xp jsonb`, `streak_xp jsonb`.
- **D-06:** The `tournaments.config` singleton holds global settings only (e.g., `blacklist_weeks`). No XP values on the global config.

### Schema Structure (from prior decisions)
- **D-07:** New `tournaments` schema following existing multi-schema pattern (core, maps, store, etc.)
- **D-08:** Singleton config table with `CHECK(id = 1)` following `store.config` pattern
- **D-09:** Nullable `tournament_completion_id` FK added to `core.completions` via ALTER TABLE
- **D-10:** Migration file numbered `0020_tournaments.sql`

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Schema Patterns
- `apps/api/migrations/0001_init.sql` — Core tables, `core.completions` definition (lines 447-541), speed enforcement trigger `enforce_speed_rules_nonlegacy_only()`
- `apps/api/migrations/0013_coin_store.sql` — Singleton config pattern (`store.config` with `CHECK(id=1)`), pg_cron extension setup
- `apps/api/migrations/0017_fix_speed_trigger_check_verified.sql` — Latest version of speed enforcement trigger

### Project Planning
- `.planning/PROJECT.md` — Constraints section (tech stack, data integrity, bot pattern, schema, cycle timing)
- `.planning/REQUIREMENTS.md` — Full v1 requirement list with IDs (CYCLE-*, SUB-*, RWD-*, ADM-*, DSC-*)
- `.planning/ROADMAP.md` — Phase 1 success criteria (5 items)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `store.config` singleton pattern: `int GENERATED ALWAYS AS IDENTITY PRIMARY KEY CHECK (id = 1)` — reuse exactly for `tournaments.config`
- pg_cron extension setup with graceful fallback for test environments (migration 0013 pattern)

### Established Patterns
- Schema naming: lowercase, dot-separated (`schema.table_name`)
- Identity columns: `int GENERATED ALWAYS AS IDENTITY PRIMARY KEY`
- Timestamps: `timestamptz NOT NULL DEFAULT now()` for `created_at`/`inserted_at`
- Foreign keys to core tables: `bigint REFERENCES core.users(id)`, `int REFERENCES core.maps(id)`
- Indexes named: `idx_{table}_{columns}`
- Comments on tables and columns for documentation
- Sequential migration files (`0001` through `0019`)

### Integration Points
- `core.completions` table needs ALTER TABLE to add nullable `tournament_completion_id` FK
- Speed enforcement trigger `core.enforce_speed_rules_nonlegacy_only()` fires on INSERT/UPDATE — cross-write CTE must account for this in Phase 3/6
- `core.users(id)` and `core.maps(id)` / `maps.maps(id)` are the FK targets for tournament tables

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches following existing codebase patterns.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 1-Database Schema & Migrations*
*Context gathered: 2026-05-29*
