# Phase 1: Database Schema & Migrations - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-29
**Phase:** 1-Database Schema & Migrations
**Areas discussed:** Verification tiers, Blacklist scope, XP config modeling

---

## Verification Tiers

| Option | Description | Selected |
|--------|-------------|----------|
| Integer tier column | A smallint verification_tier column (0=unverified, 1=video, 2=verified). Simple, extensible. | |
| Match existing booleans | Keep same verified + video + completion columns from core.completions. Derive tier at query time. | ✓ |
| PostgreSQL enum type | CREATE TYPE tournaments.verification_tier AS ENUM. Readable but harder to extend. | |

**User's choice:** Match existing booleans
**Notes:** None

### Follow-up: Tier Mapping

| Option | Description | Selected |
|--------|-------------|----------|
| Three tiers (verified > video > screenshot) | Rewards video proof even before mod verification. | |
| Two tiers (verified > unverified) | Simpler: mod-verified always ranks above unverified regardless of video. | ✓ |

**User's choice:** Two tiers (verified > unverified)
**Notes:** Ranking is simply `ORDER BY verified DESC, time ASC`

---

## Blacklist Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Global blacklist | Map used in ANY category goes on cooldown for ALL categories. Simpler schema. | ✓ |
| Per-category blacklist | Map used in one category can still appear in others. Requires category_id FK. | |

**User's choice:** Global blacklist
**Notes:** None

### Follow-up: Blacklist Storage

| Option | Description | Selected |
|--------|-------------|----------|
| Derive from cycles | No separate table. Query cycles table for recently used maps. | ✓ |
| Dedicated blacklist table | Separate table with map_id, used_at, expires_at. Allows manual entries. | |

**User's choice:** Derive from cycles
**Notes:** Cooldown window controlled by `blacklist_weeks` on config singleton

---

## XP Config Modeling

| Option | Description | Selected |
|--------|-------------|----------|
| JSONB on config singleton | placement_xp and streak_xp as JSONB columns on tournaments.config. | |
| Normalized rows | Separate tables for each tier type. | |
| You decide | Let researcher/planner pick. | |

**User's choice:** Other — "What about a table with a single row that gets updated"
**Notes:** User clarified they want config on the singleton row, which maps to JSONB columns approach

### Follow-up: Participation XP Scope

| Option | Description | Selected |
|--------|-------------|----------|
| All on config row | participation_xp, placement_xp, streak_xp all on global config. | |
| Participation XP per-category | Participation XP amount on category row, allowing different bonuses per difficulty. | ✓ |

**User's choice:** Participation XP per-category
**Notes:** None

### Follow-up: Placement & Streak XP Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Global (on config) | Placement tiers and streak thresholds same across all categories. | |
| Per-category | Each category has own placement XP tiers and streak thresholds. | ✓ |

**User's choice:** Per-category
**Notes:** All XP config (participation, placement, streak) lives on tournaments.categories

---

## Claude's Discretion

None — user made all decisions.

## Deferred Ideas

None — discussion stayed within phase scope.
