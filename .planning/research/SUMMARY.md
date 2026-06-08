# Project Research Summary

**Project:** Recurring Tournament System for Genji Parkour
**Domain:** Competitive gaming tournament with automated cycle management
**Researched:** 2026-05-29
**Confidence:** HIGH

## Executive Summary

The tournament system is a recurring time-trial competition where players compete on randomly selected maps within difficulty categories, with automatic weekly or biweekly cycle transitions, leaderboard ranking, XP rewards, and Discord integration. This is not a new technology problem -- it is a new domain built entirely on existing infrastructure. The codebase already has two production systems (store rotations, quest rotations) that implement the exact "pg_cron + config singleton + random selection with exclusion" pattern the tournament needs. Zero new Python dependencies are required; every capability (scheduling, random selection, leaderboard ranking, notifications, XP grants) maps directly to tools already in the stack: pg_cron, PL/pgSQL, PostgreSQL window functions, RabbitMQ, and discord.ext.tasks.

The recommended approach is a six-phase build following the Controller-Service-Repository pattern, starting with the database schema and SDK types, then layering in CRUD, submissions, automated transitions, bot integration, and engagement features. The architecture centers on a two-phase cycle transition: pg_cron handles time-critical database mutations atomically in SQL, then writes to a `pending_transitions` outbox table that the API polls to trigger RabbitMQ events for Discord-side effects. This cleanly separates "what happened" (database) from "who needs to know" (bot), matching the existing producer-consumer boundary.

The most dangerous risks are: (1) the `core.completions` speed enforcement trigger rejecting tournament cross-writes when a faster unverified submission exists, (2) race conditions during the brief cycle transition window allowing late submissions to alter finalized placements, and (3) Discord rate limiting when champion role transfers and batch XP grants fire simultaneously. All three have concrete prevention strategies documented in the research -- separate transactions with graceful CheckViolationError handling, a `finalizing` status gate on submissions, and staggered role operations with batched member.edit calls.

## Key Findings

### Recommended Stack

No new dependencies. The tournament system reuses asyncpg (database), aio-pika (RabbitMQ), msgspec (serialization), Litestar (API), discord.py (bot), and pg_cron (scheduling). The project's existing pg_cron infrastructure (installed in the PostgreSQL Docker image, used by migrations 0013 and 0014) handles cycle transition scheduling. APScheduler, Celery, Redis, SQLAlchemy, and state machine libraries were all evaluated and rejected -- each either adds unnecessary complexity, conflicts with the raw-asyncpg architecture, or solves a problem that does not exist (2-state transitions do not need a state machine library).

**Core technologies (all existing):**
- **pg_cron + PL/pgSQL:** Scheduled cycle transitions -- survives API restarts, uses advisory locks, follows store/quest rotation pattern
- **PostgreSQL window functions:** `RANK() OVER (ORDER BY verification_tier DESC, time ASC)` for tier-then-time leaderboards -- same pattern as existing completions leaderboard
- **RabbitMQ queues:** Three new queues (`api.tournament.cycle.started`, `api.tournament.cycle.completed`, `api.tournament.submission`) plus reuse of existing `api.xp.grant`
- **`discord.ext.tasks.loop`:** Bot-side polling for pending transitions at 1-minute intervals -- negligible latency for weekly events
- **Config singleton pattern:** `tournaments.config` with `CHECK (id = 1)` -- follows `store.config` and `store.quest_config`

### Expected Features

**Must have (table stakes):**
- Automatic cycle transitions via pg_cron (manual resets defeat the purpose)
- Random map selection per category with blacklist/cooldown window
- Per-cycle leaderboard with tier-then-time ranking
- Tournament completion submission with cross-write to core completions
- Participation XP and placement-based XP bonuses (via existing `api.xp.grant`)
- Discord champion role per category (transferred at cycle end)
- Discord announcements for new cycles and results
- Admin configuration endpoints (categories, cycle frequency, XP amounts)
- Pre-rolled next-cycle maps with admin reroll capability
- Category-based difficulty grouping with per-category cycle frequency
- Tournament history/archive

**Should have (differentiators):**
- Weekly participation streak tracking with streak XP bonuses (+34% retention per Duolingo data)
- "Set during Tournament X" metadata on core completions (via link table)
- Tournament-specific Discord threads per cycle
- Countdown to cycle end
- Configurable announcement channel per category

**Defer indefinitely:**
- Seasons/time-boxed tournaments (add only if perpetual cycle proves insufficient)
- Live leaderboard updates in Discord (high complexity, marginal engagement lift)
- Personal tournament stats/trends (reporting layer, not core)
- Bracket/elimination format, ELO, multiple simultaneous tournaments, user-created tournaments, map voting (all anti-features)

### Architecture Approach

The system follows the existing three-layer API (Controller -> Service -> Repository) with a new `tournaments` PostgreSQL schema, a `TournamentRepository` for raw SQL, a `TournamentService` for business logic and RabbitMQ publishing, and a `TournamentsController` at `/api/v3/tournaments/*`. The critical architectural decision is the "outbox bridge" pattern: pg_cron performs atomic cycle transitions in SQL and writes to `tournaments.pending_transitions`, then the API polls this table and publishes RabbitMQ events that the bot consumes for Discord-side effects. This avoids adding new PostgreSQL extensions (pg_net) and keeps the producer-consumer boundary clean.

**Major components:**
1. **`tournaments` PostgreSQL schema** -- Config, categories, cycles, completions, streaks, blacklist, pending_transitions, xp_config (9 tables)
2. **`TournamentRepository`** -- Raw SQL against tournament tables plus cross-write queries to `core.completions`
3. **`TournamentService`** -- Submission validation, cycle transition orchestration, map selection, streak tracking, XP calculation, RabbitMQ publishing
4. **`TournamentsController`** -- HTTP endpoints (public: active cycle, leaderboard, history, submit; admin: config, categories, reroll, preview)
5. **`tournaments.py` SDK module** -- Shared msgspec Structs for requests, responses, and RabbitMQ events
6. **`TournamentHandler` (bot)** -- Queue consumers for cycle.started, cycle.completed, submission events; champion role management
7. **`TournamentCog` (bot)** -- Slash commands: `/tournament leaderboard`, `/tournament info`, `/tournament streak`, `/tournament admin reroll`
8. **pg_cron job** -- Hourly `tournaments.check_and_transition()` SQL function with advisory lock

### Critical Pitfalls

1. **Cross-write vs. speed enforcement trigger** -- The `core.completions` trigger rejects inserts where the time is not strictly faster than existing best (including unverified submissions). Prevention: use a CTE that checks current best before inserting, catch `CheckViolationError` gracefully, and execute cross-write in a separate transaction from the tournament completion insert.

2. **pg_cron cannot trigger Discord announcements** -- pg_cron runs SQL only, cannot publish to RabbitMQ or call HTTP. Prevention: use the outbox pattern (`pending_transitions` table) with API-side polling every 60 seconds to detect transitions and publish events.

3. **Race condition during transition window** -- Submissions during the brief transition window can alter already-finalized placements. Prevention: add a `finalizing` status to cycles, reject submissions when status is not `active`, and compute placements with a `WHERE submitted_at < transition_timestamp` filter.

4. **Discord role rate limiting on champion transfer** -- Multiple category champion transfers + batch XP grants can exceed Discord's 10 role-ops/10s limit. Prevention: serialize role operations, batch all role changes per member into single `member.edit()` calls, stagger XP grants over 1-2 minutes.

5. **Map pool exhaustion from aggressive blacklist** -- A large blacklist window relative to the eligible map pool leaves zero maps to select. Prevention: validate pool health at selection time, fall back to least-recently-used map, add admin-facing pool metrics endpoint.

## Implications for Roadmap

Based on research, suggested phase structure:

### Phase 1: Database Schema + SDK Types + Repository

**Rationale:** Every other component depends on the database schema and shared types. The schema design decision (link table vs. FK on `core.completions`) must be settled first because it affects all cross-write logic downstream.
**Delivers:** `tournaments` schema migration, SDK structs in `tournaments.py`, `TournamentRepository` with raw SQL queries, domain exceptions.
**Addresses:** Category configuration, cycle data model, completion storage, blacklist tables, streak tables, XP config tables.
**Avoids:** Pitfall 6 (FK coupling) -- use a `tournaments.completion_links` table instead of adding a FK column to `core.completions`.

### Phase 2: Service + Controller (Config, Categories, Read Endpoints)

**Rationale:** Admin CRUD for tournament configuration must exist before submissions or transitions can work. Categories define difficulty groupings that drive map selection.
**Delivers:** `TournamentService` (config, categories, active cycles, leaderboard queries), `TournamentsController` (GET endpoints + admin config PATCH/POST), dependency injection setup.
**Addresses:** Admin configuration endpoints, category management, tournament history/archive, per-cycle leaderboard display.
**Avoids:** Pitfall 8 (pre-roll fairness) -- implement audit logging for map preview access from the start.

### Phase 3: Submission Flow + Cross-Write

**Rationale:** Submissions are the core user action and the most dangerous integration point. The cross-write to `core.completions` must be implemented carefully to avoid the speed enforcement trigger. This phase should be fully tested before adding automated transitions.
**Delivers:** `POST /api/v3/tournaments/submit` endpoint, cross-write logic with trigger-safe CTE, `api.tournament.submission` RabbitMQ event, tier-then-time ranking.
**Addresses:** Completion submission, cross-write to core completions, per-cycle leaderboard updates.
**Avoids:** Pitfall 1 (speed trigger) -- separate transactions, CTE-based conditional insert, CheckViolationError handling. Pitfall 3 (race condition) -- cycle status validation on submission.

### Phase 4: Automatic Cycle Transitions

**Rationale:** The automated loop is the system's backbone, but it depends on having submission data to rank and categories to transition. This phase wires up pg_cron, the outbox bridge, and the API-side polling that makes transitions trigger RabbitMQ events.
**Delivers:** pg_cron job, `tournaments.check_and_transition()` PL/pgSQL function, `pending_transitions` outbox, API background task polling, placement computation, XP grant publishing via existing `api.xp.grant` queue, pre-rolled map selection.
**Addresses:** Automatic cycle transitions, map selection with blacklist, placement XP, participation XP, pre-rolled maps with admin reroll.
**Avoids:** Pitfall 2 (pg_cron gap) -- outbox pattern bridges SQL-only transitions to RabbitMQ. Pitfall 3 (race window) -- `finalizing` status gate. Pitfall 5 (pool exhaustion) -- pool health validation at selection time. Pitfall 9 (map archival) -- guard in archive endpoint.

### Phase 5: Bot Integration

**Rationale:** Bot consumers depend on the RabbitMQ events that only Phase 4 produces. Champion role transfer and Discord announcements are presentation concerns that layer on top of the working data pipeline.
**Delivers:** `TournamentHandler` (queue consumers for cycle.started, cycle.completed, submission), announcement embeds, champion role transfer, `TournamentCog` (slash commands), bot config additions.
**Addresses:** Discord announcements (new cycle + results), champion role per category, Discord slash commands for leaderboard/info/streak.
**Avoids:** Pitfall 4 (rate limiting) -- staggered role operations, batched member.edit. Pitfall 12 (bot offline) -- staleness checks on transition timestamps, query DB for current champion instead of trusting message payload. Pitfall 10 (idempotency) -- cycle-scoped idempotency keys.

### Phase 6: Streaks + Engagement Polish

**Rationale:** Streaks and engagement features are independent of the core cycle loop. They enhance retention but do not block the tournament from functioning. Deferring them reduces the blast radius of early phases.
**Delivers:** Streak tracking, streak XP bonuses, tournament-completion link metadata ("Set during Tournament X" badges), countdown display, admin pool health endpoint.
**Addresses:** Weekly participation streak, streak-based XP bonuses, tournament badge metadata, countdown to cycle end.
**Avoids:** Pitfall 7 (ambiguous streaks) -- define streak as "submitted in at least one category that had an active cycle," or simplify to single global frequency in v1.

### Phase Ordering Rationale

- **Schema first (Phase 1)** because every layer depends on table definitions and SDK types. Getting the link table vs. FK decision right here avoids a corrective migration later.
- **CRUD before submissions (Phase 2 before 3)** because submissions require active cycles to exist, which requires category and config setup.
- **Submissions before transitions (Phase 3 before 4)** because transitions are meaningless without completion data to rank, and the cross-write is the hardest integration point that needs isolation for testing.
- **Transitions before bot (Phase 4 before 5)** because the bot consumes events that only the transition pipeline produces.
- **Streaks last (Phase 6)** because they are additive engagement features with no dependency on them from core phases, and the streak definition across mixed-frequency categories needs careful thought that benefits from seeing the system run first.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 3 (Submission + Cross-Write):** The `core.completions` speed enforcement trigger interaction is the single most dangerous integration point. Needs careful study of the trigger source (`enforce_speed_rules_nonlegacy_only()`) and testing against edge cases (unverified submissions, legacy rows).
- **Phase 4 (Cycle Transitions):** The outbox bridge pattern (pg_cron -> pending_transitions -> API poll -> RabbitMQ) is architecturally novel for this codebase. While each piece is proven individually, the composition needs validation. The transition PL/pgSQL function is complex and should be developed test-first.

Phases with standard patterns (skip research-phase):
- **Phase 1 (Schema + SDK + Repository):** Well-documented -- follows existing schema creation, SDK struct, and repository patterns exactly.
- **Phase 2 (Service + Controller CRUD):** Standard Controller-Service-Repository CRUD -- done many times in this codebase.
- **Phase 5 (Bot Integration):** Standard queue consumer and cog patterns -- follows existing `CompletionHandler`, `XPHandler`, and `NotificationHandler` exactly.
- **Phase 6 (Streaks + Polish):** Simple data tracking with standard queries.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Zero new dependencies. Every tool is already in production use for analogous features (store rotation, quest rotation, completions leaderboard, XP grants). |
| Features | HIGH | Strong PROJECT.md spec, clear table-stakes vs. differentiators distinction, feature dependencies mapped. Anti-features explicitly defined (no seasons, no brackets, no ELO). |
| Architecture | HIGH | All patterns derive from existing codebase (Controller-Service-Repository, pg_cron + advisory locks, RabbitMQ producer-consumer, config singleton). The outbox bridge is the only novel composition. |
| Pitfalls | HIGH | Pitfalls identified through direct codebase analysis (trigger source code, rate limit patterns, idempotency enforcement). Prevention strategies are concrete and testable. |

**Overall confidence:** HIGH

### Gaps to Address

- **Speed enforcement trigger details:** The exact behavior of `core.enforce_speed_rules_nonlegacy_only()` with respect to unverified/pending completions needs to be verified by reading the trigger source during Phase 3 planning. The research identifies the risk but the trigger's edge case behavior around verification status is not fully characterized.
- **Verification tier definition:** The tier-then-time ranking assumes a `verification_tier` integer (0=unverified, 1=partial, 2=full), but the existing completions system uses a boolean `verified` column plus a `video` presence check. The exact mapping from existing verification state to tournament tiers needs to be defined during Phase 1.
- **Per-category vs. global cycle frequency:** FEATURES.md recommends per-category frequency (weekly vs. biweekly), but PITFALLS.md warns this creates ambiguous streak semantics. The decision to support per-category frequency in v1 or defer it needs to be made during Phase 1 schema design. Recommendation: support it in the schema but use a single frequency for v1 launch.
- **API-side polling mechanism:** The outbox bridge uses an API background task polling every 60 seconds. The exact Litestar mechanism for this (lifespan context manager, startup hook, or `on_startup` callback) should be confirmed during Phase 4 planning. The bot-side DLQ processor pattern in `rabbit.py` provides a reference implementation.
- **Champion role IDs:** Categories need `champion_role_id` configured. These Discord roles must be created manually in the server before the system can transfer them. This is an operational prerequisite, not a code gap, but should be documented in the setup guide.

## Sources

### Primary (HIGH confidence)
- Existing codebase migrations: `0013_coin_store.sql`, `0014_quests_system.sql` -- proven pg_cron + advisory lock + random selection patterns
- Existing codebase: `apps/api/repository/completions_repository.py` -- RANK() leaderboard pattern
- Existing codebase: `apps/api/services/base.py` -- BaseService, publish_message, IGNORE_IDEMPOTENCY
- Existing codebase: `apps/bot/extensions/xp.py`, `completions.py`, `notifications.py` -- queue consumer patterns
- Existing codebase: `apps/bot/extensions/_queue_registry.py` -- @queue_consumer decorator
- Existing codebase: `apps/api/migrations/0001_init.sql`, `0010`, `0012`, `0017` -- speed enforcement trigger evolution
- `infra/postgres/Dockerfile` -- pg_cron extension availability

### Secondary (MEDIUM confidence)
- [pg_cron GitHub repository](https://github.com/citusdata/pg_cron) -- Extension documentation
- [PostgreSQL window functions documentation](https://www.postgresql.org/docs/current/functions-window.html) -- RANK, DENSE_RANK
- [Discord Rate Limit Documentation](https://discord.com/developers/docs/topics/rate-limits)
- [APScheduler PyPI](https://pypi.org/project/APScheduler/) -- Version verification (3.11.2 stable, 4.0.0a6 alpha)

### Tertiary (LOW confidence)
- Duolingo gamification case study -- streak retention data (34% overall retention increase claim)
- Epochtal (epochtal.p2r3.com) -- Weekly Portal 2 speedrun competition pattern
- Valorant/CS2/PUBG map rotation cooldown systems -- conceptual validation

---
*Research completed: 2026-05-29*
*Ready for roadmap: yes*
