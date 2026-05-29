# Roadmap: Tournament System

## Overview

Build a recurring tournament system for Genji Parkour as a new domain within the existing monorepo. The system delivers automatic weekly/biweekly competitive cycles where players compete on randomly selected maps, earn XP rewards, and vie for champion recognition on Discord. The build progresses from database foundation through API layers to bot integration, with each phase adding a verifiable technical layer that the next phase builds upon.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Database Schema & Migrations** - Create the tournaments PostgreSQL schema with all tables, constraints, and indexes (completed 2026-05-29)
- [ ] **Phase 2: SDK Types & Domain Exceptions** - Define shared msgspec Structs and domain exception hierarchy for the tournament system
- [ ] **Phase 3: Repository Layer** - Implement raw SQL data access for all tournament operations
- [ ] **Phase 4: Config & Category Management** - Service and controller layer for tournament configuration and category CRUD
- [ ] **Phase 5: Map Selection & Blacklist** - Random map selection engine with cooldown window, pre-roll, and admin reroll
- [ ] **Phase 6: Submission Flow & Leaderboard** - Tournament completion submissions with tier-then-time ranking, cross-write, and leaderboard
- [ ] **Phase 7: Automatic Cycle Transitions** - pg_cron scheduled transitions with outbox bridge pattern and placement computation
- [ ] **Phase 8: Rewards Engine** - Participation XP, placement XP, streak tracking, and streak bonuses
- [ ] **Phase 9: Bot Queue Consumers & Announcements** - RabbitMQ consumers for tournament events, Discord announcements, and champion role transfers
- [ ] **Phase 10: Bot Slash Commands** - Discord slash commands for tournament info, leaderboard, and admin actions

## Phase Details

### Phase 1: Database Schema & Migrations
**Goal**: The tournaments PostgreSQL schema exists with all tables, constraints, indexes, and the foundation for every downstream layer
**Depends on**: Nothing (first phase)
**Requirements**: (foundation -- no direct requirement mapping; enables all requirements)
**Success Criteria** (what must be TRUE):
  1. A new `tournaments` schema exists in PostgreSQL with tables for config, categories, cycles, completions, streaks, blacklist, pending_transitions, xp_config, and completion_links
  2. The migration file runs cleanly against the existing database without conflicts with other schemas
  3. Foreign key relationships correctly reference existing tables (core.users, maps.maps) and internal tournament tables
  4. A CHECK(id = 1) singleton constraint exists on the config table following the store.config pattern
  5. The `core.completions` table has a nullable `tournament_completion_id` FK column added via ALTER TABLE
**Plans:** 1/1 plans complete

Plans:
- [x] 01-01-PLAN.md -- Tournament schema migration and integration tests

### Phase 2: SDK Types & Domain Exceptions
**Goal**: All shared data types and error types are defined so the API and bot have a common contract for tournament data
**Depends on**: Phase 1
**Requirements**: (foundation -- no direct requirement mapping; enables all requirements)
**Success Criteria** (what must be TRUE):
  1. A `tournaments.py` module exists in the SDK with msgspec Structs for all request, response, and event types
  2. Domain exception classes exist in `services/exceptions/tournaments.py` covering tournament-specific error conditions
  3. Repository exception mappings cover tournament-specific constraint violations
  4. SDK types pass lint and type-check (`just lint-sdk`)
**Plans:** 1/2 plans executed

Plans:
- [x] 02-01-PLAN.md -- SDK tournaments.py module with all msgspec Structs and type aliases
- [ ] 02-02-PLAN.md -- Domain exception hierarchy and barrel __init__.py updates

### Phase 3: Repository Layer
**Goal**: Raw SQL data access exists for every tournament database operation so the service layer can be built without touching SQL directly
**Depends on**: Phase 2
**Requirements**: (foundation -- no direct requirement mapping; enables all requirements)
**Success Criteria** (what must be TRUE):
  1. A `TournamentRepository` class exists with methods for all CRUD operations across tournament tables
  2. Repository methods follow the existing pattern (optional `conn` parameter, `self._get_connection(conn)`, positional `$N` parameters)
  3. Cross-write query uses a CTE that checks current best time before inserting into `core.completions`, avoiding the speed enforcement trigger
  4. Leaderboard query uses `RANK() OVER (ORDER BY verification_tier DESC, time ASC)` for tier-then-time ranking
**Plans**: TBD

### Phase 4: Config & Category Management
**Goal**: Admins can create, read, update, and manage tournament configuration and difficulty-based categories through the API
**Depends on**: Phase 3
**Requirements**: CYCLE-02, CYCLE-03, CYCLE-08, ADM-01, ADM-02
**Success Criteria** (what must be TRUE):
  1. Admin can GET/PATCH the tournament config singleton (cycle frequencies, XP amounts, blacklist window)
  2. Admin can create, list, update, and delete tournament categories with difficulty groupings
  3. Category modifications are rejected with a clear error when a cycle is currently active for that category
  4. Non-admin API requests to config/category endpoints are rejected by scope guard
**Plans**: TBD

### Phase 5: Map Selection & Blacklist
**Goal**: The system can randomly select eligible maps for each category while respecting the blacklist cooldown window, and admins can preview and override selections
**Depends on**: Phase 4
**Requirements**: CYCLE-04, CYCLE-05, CYCLE-06, CYCLE-07
**Success Criteria** (what must be TRUE):
  1. Maps used within the configured N-week window are excluded from the eligible selection pool
  2. A random map is selected from the eligible pool filtered by the category's difficulty grouping
  3. Next-cycle maps are pre-generated and stored so admins can preview them before the cycle starts
  4. Admin can reroll a specific category's next map or explicitly choose a map via the API
  5. When the eligible pool is exhausted, the system falls back to the least-recently-used map and logs a warning
**Plans**: TBD

### Phase 6: Submission Flow & Leaderboard
**Goal**: Players can submit tournament completions and view per-cycle leaderboards, with tournament times that beat personal bests automatically written to core completions
**Depends on**: Phase 5
**Requirements**: SUB-01, SUB-02, SUB-03, SUB-04, SUB-05, SUB-06
**Success Criteria** (what must be TRUE):
  1. A player can submit a tournament completion for an active cycle's map, stored in `tournaments.completions` with per-cycle speed enforcement
  2. Submissions are ranked by tier-then-time: fully verified completions always outrank partial, and within the same tier fastest time wins
  3. When a tournament submission is strictly faster than the player's existing best in `core.completions`, a cross-write occurs with a `tournament_completion_id` link
  4. A per-cycle leaderboard endpoint returns ranked standings for a given cycle
  5. A tournament history/archive endpoint returns past cycles with their results and standings
**Plans**: TBD

### Phase 7: Automatic Cycle Transitions
**Goal**: Tournament cycles automatically transition at their scheduled end times -- finalizing the current cycle, computing placements, and starting the next cycle with pre-selected maps
**Depends on**: Phase 6
**Requirements**: CYCLE-01
**Success Criteria** (what must be TRUE):
  1. A pg_cron job runs periodically and detects cycles that have passed their end time
  2. The transition function atomically sets the cycle to `finalizing` (rejecting new submissions), computes final placements, closes the cycle as `completed`, and opens the next cycle
  3. Completed transitions write to the `pending_transitions` outbox table for downstream consumption
  4. The API polls the outbox and publishes RabbitMQ events for each pending transition
  5. Concurrent transition attempts are prevented by PostgreSQL advisory locks
**Plans**: TBD

### Phase 8: Rewards Engine
**Goal**: Players earn XP for tournament participation and placements, and maintain weekly streaks that grant bonus XP at configurable thresholds
**Depends on**: Phase 7
**Requirements**: RWD-01, RWD-02, RWD-04, RWD-05
**Success Criteria** (what must be TRUE):
  1. A player receives a flat participation XP bonus on their first submission in a cycle (once per cycle, not per submission)
  2. At cycle end, placement-based XP bonuses are calculated according to admin-configured tier/amount pairs and published to the `api.xp.grant` queue
  3. A player's participation streak increments when they submit in at least one category per cycle, and resets to zero if they miss a cycle
  4. Streak-based XP bonuses are granted when a player's streak reaches admin-configured thresholds
**Plans**: TBD

### Phase 9: Bot Queue Consumers & Announcements
**Goal**: The Discord bot reacts to tournament events -- announcing new cycles, posting results, and transferring champion roles
**Depends on**: Phase 8
**Requirements**: DSC-01, DSC-02, DSC-03, RWD-03
**Success Criteria** (what must be TRUE):
  1. When a new cycle starts, the bot posts an announcement embed in the configured channel with the map name, difficulty, and category
  2. When a cycle completes, the bot posts a results embed with final standings, placements, and XP awarded
  3. The champion Discord role for each category is removed from the previous holder and granted to the new cycle's winner
  4. Role operations are staggered to avoid Discord rate limiting when multiple categories transition simultaneously
  5. Queue consumers use cycle-scoped idempotency keys to prevent duplicate announcements on retry
**Plans**: TBD

### Phase 10: Bot Slash Commands
**Goal**: Players and admins can interact with the tournament system through Discord slash commands
**Depends on**: Phase 9
**Requirements**: ADM-03
**Success Criteria** (what must be TRUE):
  1. Players can view the current active cycle info (map, time remaining, category) via a slash command
  2. Players can view the current cycle leaderboard via a slash command
  3. Players can check their participation streak via a slash command
  4. Admins can trigger a map reroll for a category's next cycle via a slash command
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 -> 5 -> 6 -> 7 -> 8 -> 9 -> 10

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Database Schema & Migrations | 1/1 | Complete   | 2026-05-29 |
| 2. SDK Types & Domain Exceptions | 1/2 | In Progress|  |
| 3. Repository Layer | 0/0 | Not started | - |
| 4. Config & Category Management | 0/0 | Not started | - |
| 5. Map Selection & Blacklist | 0/0 | Not started | - |
| 6. Submission Flow & Leaderboard | 0/0 | Not started | - |
| 7. Automatic Cycle Transitions | 0/0 | Not started | - |
| 8. Rewards Engine | 0/0 | Not started | - |
| 9. Bot Queue Consumers & Announcements | 0/0 | Not started | - |
| 10. Bot Slash Commands | 0/0 | Not started | - |
