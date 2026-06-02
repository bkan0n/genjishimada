# Tournament System

## What This Is

A recurring tournament system for Genji Parkour where random maps are selected from the map pool on a configurable cycle (weekly or biweekly per category). Players compete for the fastest verified completion times across difficulty-based categories, earning bonus XP, placement rewards, and a transferable Discord Champion role. Built as a new domain within the existing Genji Shimada monorepo (Litestar API + Discord.py bot + shared SDK).

## Core Value

Give the Genji Parkour community a persistent, competitive cycle that keeps players engaged week-over-week through fresh map challenges, leaderboard competition, and visible champion recognition.

## Requirements

### Validated

- Existing completion submission pipeline (core.completions, verification, XP)
- Existing map pool with difficulty metadata (Easy, Medium, Hard, Very Hard)
- Existing leaderboard system ("latest = fastest" invariant)
- Existing XP and ranking system
- Existing Discord bot announcement infrastructure (RabbitMQ events)
- Existing API + bot architecture (Controller-Service-Repository pattern)
- Existing admin scope system for API key authorization

### Active

- [ ] Configurable tournament categories (e.g., Easy/Medium and Hard/Very Hard) with admin control over category count and difficulty groupings
- [ ] Random map selection from eligible pool per category each cycle
- [ ] Configurable per-category cycle frequency (weekly or biweekly)
- [ ] Map blacklist with configurable exclusion window (N weeks) to prevent recent maps from reappearing
- [ ] Pre-rolled next-cycle maps visible to admins, with ability to reroll or explicitly choose
- [ ] Tournament completion submissions with "tier then time" ranking (fully verified > partial; within same tier, fastest wins)
- [ ] Separate `tournaments.completions` table with own speed enforcement (fresh slate per tournament)
- [ ] Cross-write to `core.completions` only when tournament time is strictly faster than existing best, preserving "latest = fastest" invariant
- [ ] `tournament_completion_id` FK on `core.completions` for metadata linking ("Set during Tournament X" badges)
- [ ] Tournament-specific leaderboard per cycle
- [ ] Flat participation XP bonus for submitting any run
- [ ] Configurable placement-based XP bonuses (admin sets N placement tiers and amounts)
- [ ] Weekly participation streak (maintained by submitting in at least one category per cycle)
- [ ] Streak-based XP bonuses
- [ ] One Discord Champion role per category, transferred each cycle to the winner
- [ ] Automatic cycle transitions at scheduled times
- [ ] Full Discord announcement automation (new maps, cycle results, champion transfers)
- [ ] Admin API endpoints for tournament configuration and management
- [ ] Discord bot slash commands for admin tournament actions
- [ ] Category configuration locked during active cycles, changeable between cycles

### Out of Scope

- Seasons/time-boxed tournaments with season leaderboards -- perpetual cycle only for now
- Manual/admin-triggered cycle transitions -- automatic only
- Mid-cycle category changes -- locked during active cycle
- Mobile or web UI for tournament management -- API + Discord bot only
- Tournament-specific verification pipeline -- uses existing verification flow
- Multiple simultaneous tournaments -- single tournament system

## Context

**Existing architecture:** Litestar REST API (Controller-Service-Repository, raw asyncpg SQL), Discord.py bot consuming RabbitMQ events, shared msgspec SDK. The tournament system follows the same patterns.

**Completions system insight:** The existing `core.completions` table enforces "latest = fastest" -- the most recent record for a (user, map) pair is always the fastest time. Tournament cross-writes must respect this invariant by only inserting when the tournament time beats the user's current best.

**Data model decision (from spec):** Tournament completions live in `tournaments.completions` (separate schema). Cross-write to `core.completions` happens at submission time (not batched) with a nullable `tournament_completion_id` FK for metadata linking. This means no changes to existing leaderboard queries.

**Map pool:** Maps have difficulty ratings that can be grouped into tournament categories. The random selection draws from maps matching the category's difficulty filter, excluding blacklisted (recently used) maps.

**XP system:** Existing XP grant pipeline via `api.xp.grant` RabbitMQ queue. Tournament XP (participation + placement) will use the same infrastructure.

## Constraints

- **Tech stack**: Must use existing Litestar + asyncpg + msgspec + RabbitMQ patterns -- no new frameworks
- **Data integrity**: Cross-write must preserve "latest = fastest" invariant in `core.completions`
- **Bot pattern**: Bot never writes directly to DB -- all mutations go through the API
- **Schema**: New `tournaments` PostgreSQL schema for tournament-specific tables
- **Cycle timing**: Automatic transitions need a scheduler (pg_cron already available in infrastructure)

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Separate tournaments.completions table | Fresh slate per tournament, no pollution of core completions speed enforcement | -- Pending |
| Cross-write only when faster | Preserves "latest = fastest" invariant, no leaderboard query changes needed | -- Pending |
| tournament_completion_id FK on core.completions | Enables "Set during Tournament X" badges without changing leaderboard queries | -- Pending |
| Pre-rolled next-cycle maps | Admins can review/reroll anytime, simpler than on-demand generation | -- Pending |
| Per-category cycle frequency | Flexibility for different difficulty groups to run on different schedules | -- Pending |
| Tier-then-time ranking | Fully verified beats partial regardless of speed, incentivizes full verification | -- Pending |
| Automatic cycle transitions | Consistency and reliability, no admin action required to keep tournament running | -- Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? -> Move to Out of Scope with reason
2. Requirements validated? -> Move to Validated with phase reference
3. New requirements emerged? -> Add to Active
4. Decisions to log? -> Add to Key Decisions
5. "What This Is" still accurate? -> Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check -- still the right priority?
3. Audit Out of Scope -- reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-29 after initialization*
