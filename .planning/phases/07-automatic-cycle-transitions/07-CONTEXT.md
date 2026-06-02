# Phase 7: Automatic Cycle Transitions - Context

**Gathered:** 2026-05-30
**Status:** Ready for planning

> **Auto mode:** All gray areas were auto-resolved using the recommended (codebase-aligned) option. Each decision below was selected without interactive prompts. Review and adjust before planning if any default is wrong. STATE.md flagged this phase as architecturally novel ("outbox bridge pattern needs validation during planning") — research should confirm the bridge design before locking plans.

<domain>
## Phase Boundary

Build the automatic cycle transition machinery. A pg_cron job periodically detects tournament cycles that have passed their scheduled end time and runs an atomic transition: mark the cycle `finalizing` (stop accepting submissions), compute final placements, mark it `completed`, and promote the pre-rolled pending cycle for that category to `active`. Each completed transition writes a row to the `tournaments.pending_transitions` outbox table. An API-side background poller reads unpublished outbox rows and publishes the corresponding RabbitMQ events. Concurrent transition runs are prevented with PostgreSQL advisory locks.

**In scope:** transition detection + atomic state machine in SQL, placement computation, outbox writes, API outbox→RabbitMQ bridge, concurrency control.
**Out of scope (later phases):** XP/reward grants and streaks (Phase 8), bot consumers / Discord announcements / champion role transfer (Phase 9), slash commands (Phase 10). This phase only *produces* the events; it does not consume them.

</domain>

<decisions>
## Implementation Decisions

### Transition Mechanism & Concurrency (CYCLE-01, success criteria 1, 2, 5)
- **D-01:** The transition logic lives in a PL/pgSQL function (e.g. `tournaments.process_cycle_transitions()`) invoked by a pg_cron job. This mirrors the established codebase pattern in `0013_coin_store.sql` (`store.check_and_rotate()`) and `0014_quests_system.sql` — the DB owns the scheduled work; the API does not drive cycle timing. The pg_cron registration uses the same defensive `DO $body$ ... IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') ... cron.unschedule(...) ... cron.schedule(...)` block so the migration is idempotent and safe where pg_cron is absent (local/test).
- **D-02:** Concurrency is prevented with a **global session-level advisory lock** at the top of the transition function (`pg_try_advisory_lock(<constant>)`), skipping the run if not acquired and releasing in an `EXCEPTION WHEN OTHERS` handler — exactly the coin_store pattern. One transition run processes all due cycles; overlapping cron ticks no-op. (Planner may prefer `pg_advisory_xact_lock` for auto-release — acceptable equivalent.)
- **D-03:** The function loops over all cycles whose status is `active` and whose computed end time has passed, transitioning each. The per-cycle state changes (`active`→`finalizing`→`completed` + promote next) run inside the function's transaction so the whole run is atomic — a failure rolls back cleanly and the next cron tick retries.

### End-Time Detection (success criteria 1)
- **D-04:** There is **no stored `scheduled_end_at` column** on `tournaments.cycles` (schema has only `started_at` and `ended_at`). The end time is **computed inline** as `started_at + interval` derived from the category's `cycle_frequency` (`weekly` → 7 days, `biweekly` → 14 days). A cycle is "due" when `status = 'active' AND now() >= started_at + frequency_interval`. This avoids a schema migration and keeps the frequency as the single source of truth on the category.

### Next-Cycle Start & Map Source (success criteria 2)
- **D-05:** Starting the next cycle = **promote the pre-rolled `pending` cycle** for that category to `active` (set `status = 'active'`, `started_at = now()`). Phase 5 already creates exactly one `pending` cycle per category (pre-roll). The transition consumes that pending cycle rather than selecting a fresh map at transition time.
- **D-06:** After promoting, the transition **pre-rolls the *next* pending cycle** so a category always has a pre-roll ready for the following rotation. Because map selection currently lives in the Python service (Phase 5) but the transition runs in SQL, the recommended approach is a **SQL selection helper** (e.g. `tournaments.select_eligible_map(category_id)`) that mirrors `fetch_eligible_maps` (random eligible map filtered by category difficulties, excluding maps within the blacklist window), with LRU fallback. **This SQL/Python duplication is the key risk** STATE.md flagged — research must validate it (or propose an alternative, e.g. the API pre-rolls on receipt of the `cycle_started` event instead of the SQL function doing it).
- **D-07:** Edge case — if no `pending` cycle exists for a category at transition time, the transition selects one inline via the same SQL helper and logs a warning (mirrors Phase 5's pool-exhaustion handling). If no eligible map exists at all, the transition completes the old cycle but leaves the category without an active cycle (logs warning) rather than failing the whole run.

### Placement Computation & Outbox Payload (success criteria 2, 3)
- **D-08:** Final placements are **computed at finalization** (tier-then-time ranking, same `RANK() OVER (ORDER BY verified DESC, time ASC)` logic as the existing leaderboard) and **embedded as JSON in the `pending_transitions.payload`** of the `cycle_completed` row. No new placements table — the outbox payload is the snapshot. Downstream (Phase 8 rewards, Phase 9 announcements) read placements straight from the event payload.
- **D-09:** Two outbox event types are written per transition, matching the schema CHECK constraint: a `cycle_completed` row for the finished cycle (payload includes final standings/placements + winner) and a `cycle_started` row for the newly activated cycle (payload includes category, map id/code/name, started_at, computed end time). Payload shapes should align with the SDK tournament event structs defined in Phase 2.

### Outbox → RabbitMQ Bridge (success criteria 3, 4)
- **D-10:** The API publishes outbox rows via a **background asyncio task started in a Litestar lifespan context manager** (new `tournament_outbox_poller` alongside the existing `rabbitmq_connection` lifespan in `apps/api/app.py`). The loop polls `tournaments.pending_transitions WHERE published = FALSE` on an interval, publishes each via `BaseService.publish_message()` to the tournament RabbitMQ queues, and sets `published = TRUE`.
- **D-11:** Polling selects unpublished rows with `FOR UPDATE SKIP LOCKED` and marks them published in the same transaction, so multiple API instances never double-publish. Publish-then-mark ordering favors at-least-once delivery (a crash between publish and mark re-publishes; downstream idempotency in Phase 9 handles duplicates — cycle-scoped idempotency keys are already planned there).
- **D-12:** Cadence defaults: pg_cron runs **every minute** (`* * * * *`) — fine-grained enough that weekly/biweekly transitions fire close to schedule; the outbox poller loops every **~10 seconds**. Both are tunable; these are starting values, not hard requirements.

### Claude's Discretion
- Exact SQL function/helper names (`process_cycle_transitions`, `select_eligible_map`, etc.) and whether selection is one helper or reuses Phase 5 query text.
- Whether the advisory lock is session-level (`pg_try_advisory_lock` + manual unlock) or transaction-level (`pg_advisory_xact_lock`) — both satisfy success criteria 5.
- Exact poll interval and cron expression (within the cadence intent in D-12).
- The migration file number (next sequential after 0020) and whether the cron registration is in the same file or a dedicated migration.
- Whether the outbox poller reuses an existing service or is a small standalone task; how it acquires a DB connection from the pool inside the lifespan task.
- Exact JSON shape of `cycle_started` / `cycle_completed` payloads (align with Phase 2 SDK event structs).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### pg_cron / Scheduled-Work Patterns (closest analogs — read first)
- `apps/api/migrations/0013_coin_store.sql` §225-300 — `store.check_and_rotate()`: the canonical pattern for a pg_cron-driven PL/pgSQL function with advisory locking, `EXCEPTION` cleanup, idempotent `cron.unschedule`/`cron.schedule` registration guarded by `pg_extension` existence check.
- `apps/api/migrations/0014_quests_system.sql` §449+ — second example of `cron.schedule(...)` usage in this codebase.
- `infra/postgres/Dockerfile` — confirms pg_cron is loaded (`shared_preload_libraries=pg_cron`, `cron.database_name=genjishimada`).

### Tournament Schema (tables this phase mutates)
- `apps/api/migrations/0020_tournaments.sql` — `tournaments.cycles` (status lifecycle `pending→active→finalizing→completed`, `started_at`/`ended_at`, no stored end column), `tournaments.categories` (`cycle_frequency` weekly/biweekly drives end-time math, `champion_role_id`, `placement_xp`/`streak_xp`), `tournaments.completions` (ranking index `(cycle_id, verified DESC, time ASC)`), `tournaments.pending_transitions` (outbox: `event_type` CHECK `cycle_started`/`cycle_completed`, `payload jsonb`, `published`, partial index on unpublished rows).

### Existing Tournament Code (extend / reuse)
- `apps/api/repository/tournaments_repository.py` — `fetch_eligible_maps()` + `fetch_least_recently_used_map()` (the selection logic the SQL helper must mirror for D-06/D-07), `fetch_leaderboard()` (placement/ranking SQL to mirror for D-08), `create_cycle()`, `fetch_active_cycle()`, `fetch_pending_cycle()`.
- `apps/api/services/tournament_service.py` — existing `TournamentService` (map-selection methods that the SQL helper duplicates — note for the duplication-risk discussion).
- `apps/api/services/base.py` — `BaseService.publish_message()` for the outbox bridge (D-10); note `IGNORE_IDEMPOTENCY` set and job-record behavior.
- `libs/sdk/src/genjishimada_sdk/tournaments.py` — tournament event structs (defined upfront in Phase 2) that the outbox payloads must match.

### API Lifespan / Background-Task Pattern
- `apps/api/app.py` §48-66 — `rabbitmq_connection` `@asynccontextmanager` lifespan and `lifespan=[...]` wiring (line ~204); the outbox poller is added here as a second lifespan task. Also `_async_pg_init` (jsonb/numeric codecs) and channel-pool setup relevant to publishing.

### Advisory Lock Examples
- `apps/api/migrations/0013_coin_store.sql` §235-261 — `pg_try_advisory_lock`/`pg_advisory_unlock` with EXCEPTION cleanup.
- `apps/api/services/store_service.py` §578 — `pg_advisory_xact_lock(hashtext($1))` (transaction-level alternative).

### Prior Phase Context
- `.planning/phases/05-map-selection-blacklist/05-CONTEXT.md` — D-01/D-02 (pending cycles are the pre-roll storage; one pending per category), D-03 (selection flow + LRU fallback), D-04 (global blacklist cooldown). Directly informs D-05/D-06/D-07.
- `.planning/phases/06-submission-flow-leaderboard/06-CONTEXT.md` — D-08 (RabbitMQ event publishing deferred to a later phase; this phase introduces the outbox bridge), leaderboard/ranking refs informing D-08.

### Project Planning
- `.planning/PROJECT.md` — Constraints (no ORM, bot never writes to DB, pg_cron is the scheduler, existing patterns only).
- `.planning/REQUIREMENTS.md` — CYCLE-01 (the sole requirement this phase covers).
- `.planning/ROADMAP.md` §157-170 — Phase 7 goal + 5 success criteria.
- `.planning/STATE.md` — Blockers/Concerns: "outbox bridge pattern is architecturally novel for this codebase — needs validation during planning."

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `store.check_and_rotate()` (migration 0013) — copy-paste-adapt template for the pg_cron-driven transition function (advisory lock + EXCEPTION cleanup + idempotent scheduling).
- `TournamentRepository.fetch_eligible_maps()` / `fetch_least_recently_used_map()` — selection logic to mirror in the SQL pre-roll helper (D-06).
- `TournamentRepository.fetch_leaderboard()` — `RANK() OVER (ORDER BY verified DESC, time ASC)` placement query to mirror for the finalization snapshot (D-08).
- `rabbitmq_connection` lifespan in `app.py` — template for adding the `tournament_outbox_poller` lifespan task.
- `BaseService.publish_message()` — the publish primitive for the outbox bridge.

### Established Patterns
- pg_cron jobs are registered inside migrations behind a `pg_extension` existence guard with `cron.unschedule` before `cron.schedule` (idempotent re-runs).
- Advisory locks gate scheduled mutations against concurrent runs (coin_store).
- Litestar lifespans are async context managers passed in a `lifespan=[...]` list; app state holds shared pools (`mq_channel_pool`, `db_pool`).
- Cycle status is a constrained text enum with CHECK; transitions move strictly forward.
- jsonb columns round-trip through msgspec via `_async_pg_init` codecs — outbox payloads decode to Python objects automatically.

### Integration Points
- New migration (next after `0020_tournaments.sql`) — adds the transition function, optional SQL selection helper, and the pg_cron registration.
- `apps/api/app.py` — add the outbox poller lifespan task to the `lifespan=[...]` list.
- `apps/api/repository/tournaments_repository.py` — likely add `fetch_unpublished_transitions()` (FOR UPDATE SKIP LOCKED) and `mark_transition_published()` for the bridge.
- `apps/api/services/tournament_service.py` (or a small dedicated poller) — the publish loop calling `BaseService.publish_message()`.
- `libs/sdk/src/genjishimada_sdk/tournaments.py` — outbox payloads must serialize to the existing tournament event structs.

</code_context>

<specifics>
## Specific Ideas

No specific user requirements — auto mode selected codebase-aligned defaults throughout. The strongest steer is "follow the `0013_coin_store.sql` pattern" for the pg_cron + advisory-lock machinery, since it is the closest existing analog and already proven in production.

</specifics>

<deferred>
## Deferred Ideas

- **Reward/XP grants on transition** — participation XP, placement XP, streak updates are Phase 8. This phase only emits `cycle_completed` with placements in the payload; Phase 8 consumes it.
- **Discord announcements & champion role transfer** — Phase 9 consumes the `cycle_started`/`cycle_completed` events this phase produces.
- **Admin/manual cycle transition trigger** — explicitly out of scope per REQUIREMENTS.md (automatic only).
- **Stored `scheduled_end_at` column / admin-adjustable end times** — not added now (D-04 computes inline). Revisit only if a future requirement needs per-cycle end-time overrides.

None of these block Phase 7 — discussion stayed within the transition machinery.

</deferred>

---

*Phase: 7-Automatic Cycle Transitions*
*Context gathered: 2026-05-30*
