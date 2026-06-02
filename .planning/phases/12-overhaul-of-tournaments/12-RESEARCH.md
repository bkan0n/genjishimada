# Phase 12: Overhaul of tournaments - Research

**Researched:** 2026-06-01
**Domain:** PostgreSQL 17 + pg_cron PL/pgSQL grid-time scheduling, transactional outbox, msgspec SDK, Litestar Controller→Service→Repository, discord.py CV2 announcements, fresh-restart data migration
**Confidence:** HIGH (everything verifiable against the existing codebase; grid-time PL/pgSQL is standard PostgreSQL date arithmetic)

## Summary

This is a backend refactor of an already-shipped tournament system (phases 01–11). The
existing model gives every category its own independently-timed `tournaments.cycles` row, and
the pg_cron transition function (`migrations/0023` `process_cycle_transitions()`) re-stamps
`started_at = now()` on every promote. Because the cron tick fires up to ~60s late and the new
start is anchored to *execution time*, categories drift apart and never re-converge. **That
`started_at = now()` write at lines 153 and 183 of 0023 is the single root-cause bug.**

The fix is structural, not a patch: introduce an explicit top-level **edition** entity
(`tournaments.editions`) holding the one shared, grid-anchored `started_at`/`ends_at`, with each
category's `tournaments.cycles` row as a child of the edition (FK `edition_id`). The cron job
becomes a **status-only flip** — it computes "is the configured grid boundary reached?" but
writes the *exact grid timestamps* (anchor + N×period) into the edition, never `now()`. The
separate `cycle_started`/`cycle_completed` events collapse into one `edition_rollover` outbox
row → one `TournamentRolloverEvent` → one bot card with conditional results/start sections.
Global pause and debug-length levers move off `tournaments.categories` (added in 0023) onto the
shared config. A fresh-restart migration wipes all cycles + tournament completions, NULLs the
`core.completions.tournament_completion_id` FK on cross-written rows (keeping the PB times), and
bootstraps the first edition snapped to the next grid boundary.

**Primary recommendation:** Add `tournaments.editions` as the timing-owning parent; rewrite
`process_cycle_transitions()` to be a grid-boundary detector + status flipper that stores
`anchor + N×period` (never `now()`); collapse the outbox to one combined `edition_rollover` row
per rollover keyed by `edition_id`; reshape SDK/API so timing reads off the edition; use the
existing `core.completions` FK's `ON DELETE SET NULL` (already defined) plus an explicit
`UPDATE ... SET tournament_completion_id = NULL` before wiping, so PB times survive. Reuse the
0013 advisory-lock + idempotent cron-reschedule pattern verbatim. No new external packages.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Grid-boundary detection + status flip | Database (PL/pgSQL + pg_cron) | — | DB owns scheduled timing; API does not drive it (established pattern, `_async_pg_init`/cron). Must run atomically inside one txn under advisory lock. |
| Storing exact grid timestamps (`started_at`/`ends_at`) | Database (edition row) | — | The drift fix *is* "DB records grid values, not execution time" (D-08). |
| Edition + child-cycle modeling | Database (schema) | SDK (response shapes) | Single source of truth in Postgres; SDK mirrors. |
| Global cadence/anchor/pause/debug config | Database (`tournaments.config` singleton) | API service (admin mutations) | Config already lives here (`blacklist_weeks`); D-02/D-03/D-07 add columns. |
| Outbox → RabbitMQ publishing (one combined event) | API (`tournament_outbox_service` + `app.py` poller) | — | Bot never reads Postgres; API is the producer (CLAUDE.md). |
| Combined rollover announcement rendering | Bot (discord.py CV2 consumer) | API (category/map lookups on receipt) | Bot is consumer-only; missing data fetched via API. |
| Champion-role transfer | Bot | — | Discord-side action; folds into the single rollover handler. |
| Leaderboards / XP / streaks | API service/repo (per child cycle) | — | Stay keyed on `cycle_id` (preserve current behavior — see §Architecture). |
| Fresh-restart wipe + FK null | Database (migration) | — | One-time DDL/DML; ordering matters (null then wipe). |

## Standard Stack

No new packages. This phase is built entirely on the existing, already-installed stack. Every
"library" below is already a project dependency (verified in `pyproject.toml` / CLAUDE.md tech
stack), so no registry/slopcheck verification applies (see Package Legitimacy Audit).

### Core
| Library / Tool | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| PostgreSQL | 17 `[VERIFIED: infra/postgres/Dockerfile FROM postgres:17]` | Schema, PL/pgSQL transition fn, grid-time arithmetic | Single source of truth; already the project DB |
| pg_cron | postgresql-17-cron `[VERIFIED: infra/postgres/Dockerfile]` | Drives `process_cycle_transitions()` every minute | Established scheduler (0013, 0021); `cron.database_name=genjishimada` |
| msgspec | `>=0.19.0` `[CITED: CLAUDE.md]` | SDK structs + jsonb outbox payload round-trip | All cross-service models; codecs in `app.py _async_pg_init` |
| asyncpg | `>=0.30.0` (via litestar-asyncpg `>=0.4.0`) `[CITED: CLAUDE.md]` | Raw SQL repo layer | No ORM (CLAUDE.md constraint) |
| Litestar | `>=2.16.0` `[CITED: CLAUDE.md]` | Controller routes + DI | Three-layer pattern |
| aio-pika | `>=9.5.5` `[CITED: CLAUDE.md]` | Outbox→RabbitMQ publish (`BaseService.publish_message`) | Producer side |
| discord.py | master (git) `[CITED: CLAUDE.md]` | CV2 LayoutView rollover card | Bot consumer |

### Supporting (existing test stack)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest + pytest-asyncio | `>=8.3.5` / `>=1.2.0` | Service/repo/integration tests | All tests (asyncio mode auto) |
| pytest-databases[postgres] | `>=0.14.0` | Per-test Postgres fixture | Repo + migration + transition-fn tests |
| pytest-xdist | `>=3.8.0` | Parallel | `just test-api` (8 workers); use `-p no:xdist` for targeted |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Storing `started_at`/`ends_at` in the edition row | Recompute grid on every read | D-08 explicitly says RECORD grid times; stored values are the contract the frontend/SDK read and what proves drift-immunity. Reject recompute-on-read. |
| New `tournaments.editions` table | Reuse `tournaments.config` with a "current edition" pointer | An edition is a per-rotation entity with history (id, started_at, ends_at, status); config is a singleton. Editions need their own rows. D-05 names the entity explicitly. |
| Singleton settings row for cadence/anchor | New columns on existing `tournaments.config` (id=1 singleton) | Config IS already a singleton (`CHECK (id = 1)`) with `blacklist_weeks`. Adding columns there is the lowest-friction home (Discretion item resolved → recommend `tournaments.config`). |
| `make_interval(weeks => N)` period math | `date_trunc('week', ...)` only | `date_trunc` snaps to ISO Monday but cannot express arbitrary weekday/biweekly/time-of-day anchors. Use anchor-relative arithmetic (see Pattern 1). |

**Installation:** None. `just sync` after branch switch; no `uv add`.

## Package Legitimacy Audit

**Not applicable.** This phase installs zero external packages — it operates entirely on the
existing project dependency set (PostgreSQL 17, pg_cron, msgspec, asyncpg, Litestar, aio-pika,
discord.py, pytest), all already present in `uv.lock` and documented in CLAUDE.md. No
`uv add` / `pip install` / registry resolution occurs, so slopcheck and registry verification
have nothing to check. `[VERIFIED: uv.lock + CLAUDE.md tech stack]`

If the planner discovers a genuinely new dependency need during planning, run the Package
Legitimacy Gate before adding it.

## Architecture Patterns

### System Architecture Diagram (target model)

```
                        ┌──────────────────────────────────────────────┐
                        │  tournaments.config (singleton id=1)           │
   admin PATCH /config  │  blacklist_weeks                               │
   ───────────────────► │  cadence ('weekly'|'biweekly')      [D-02]     │
                        │  anchor_weekday + anchor_time + anchor_tz [D-07]│
                        │  transitions_paused (global)        [D-03/D-12]│
                        │  debug_cycle_seconds (global)       [D-03]     │
                        └───────────────────┬──────────────────────────┘
                                            │ read by
                                            ▼
   pg_cron (* * * * *)        ┌─────────────────────────────────────────┐
   ──────────────────────────►│ tournaments.process_edition_transitions()│
                              │  advisory xact lock 2025070100           │
                              │  1. find active edition where             │
                              │     now() >= edition.ends_at  (boundary?) │  ← detection only
                              │  2. finalize: status active→completed,    │
                              │     snapshot per-category standings       │
                              │  3. IF NOT paused: create NEXT edition with│
                              │     started_at = OLD.ends_at               │  ← EXACT grid value
                              │     ends_at   = OLD.ends_at + period       │  ← NOT now()
                              │     + child cycles (one per active cat),   │
                              │       pre-roll maps via select_eligible_map│
                              │  4. write ONE edition_rollover outbox row  │
                              │     payload = {results[], started[]}       │
                              └───────────────────┬──────────────────────┘
                                                  │ writes
                                                  ▼
                              ┌─────────────────────────────────────────┐
   API poller (~10s, app.py) │ tournaments.pending_transitions (outbox)  │
   ──────────────────────────►│  event_type='edition_rollover'           │
   publish_pending_transitions│  payload jsonb {results, started, edition_id}│
                              └───────────────────┬──────────────────────┘
                                                  │ ONE publish per rollover
                                                  │ idempotency_key=tournament:rollover:{edition_id}
                                                  ▼
                              api.tournament.rollover  ──► RabbitMQ ──► Bot consumer
                                                                         _on_edition_rollover
                                                                         ├─ transfer champion roles (if results)
                                                                         └─ ONE CV2 card:
                                                                            [results section?] + [start section?]
```

Trace the primary use case (normal rollover) by following the arrows: cron detects
`now() >= ends_at`, flips the old edition to `completed` (snapshotting standings), creates the
next edition with `started_at = old.ends_at` and `ends_at = old.ends_at + period`, writes one
outbox row, the poller publishes one event keyed by `edition_id`, and the bot renders one card.

### Recommended Project Structure (files touched — no new top-level dirs)

```
apps/api/migrations/
└── 0024_tournament_editions_overhaul.sql   # edition table + config cols + fn rewrite
                                            # + fresh-restart wipe + FK null + cron reschedule
                                            # (Discretion: may split into 0024..0026; see below)
libs/sdk/src/genjishimada_sdk/
└── tournaments.py                          # + Edition structs, TournamentRolloverEvent;
                                            #   revise/retire Cycle*Event structs
apps/api/repository/
└── tournaments_repository.py               # + edition CRUD, edition-aware cycle reads
apps/api/services/
├── tournament_service.py                   # bootstrap → bootstrap_edition (grid-snapped)
│                                           # pause/debug setters → global (config, not category)
└── tournament_outbox_service.py            # group by edition_id, ONE rollover event
apps/api/routes/v3/tournaments.py           # config-level pause/debug; edition reads
apps/bot/extensions/tournaments.py          # _on_cycle_started + _on_cycle_completed
                                            #   → _on_edition_rollover (conditional sections)
```

### Pattern 1: Grid-boundary computation in PL/pgSQL (the core fix)

**What:** Compute the exact next grid boundary from `anchor_weekday + anchor_time + anchor_tz`
and the global cadence, and store `started_at`/`ends_at` as those exact grid values.

**When to use:** (a) bootstrap/resume — snap the first/next edition to the next grid boundary
(D-13a); (b) rollover — the next edition's `started_at = old edition's ends_at` exactly, and its
`ends_at = started_at + period`. The cron job NEVER writes `now()` into these columns.

**Two distinct calculations — keep them separate:**

1. **Rollover chaining (no `now()` at all):** the new edition simply inherits the boundary.
   ```sql
   -- inside process_edition_transitions(), creating the next edition:
   v_period := CASE
       WHEN v_cfg.debug_cycle_seconds IS NOT NULL
            THEN make_interval(secs => v_cfg.debug_cycle_seconds)
       WHEN v_cfg.cadence = 'biweekly' THEN make_interval(weeks => 2)
       ELSE make_interval(weeks => 1)
   END;
   INSERT INTO tournaments.editions (started_at, ends_at, status)
   VALUES (v_old.ends_at,                 -- EXACT grid value, inherited
           v_old.ends_at + v_period,      -- next boundary
           'active');
   ```
   This is drift-immune by construction: late cron execution cannot shift `v_old.ends_at`.

2. **Bootstrap / resume snap-to-next-boundary (the only place `now()` is consulted, and only to
   pick which boundary — never to store it):**
   ```sql
   -- next_grid_boundary(p_from timestamptz, weekday int, tod time, tz text, period interval)
   -- weekday: 0=Sun..6=Sat (PostgreSQL EXTRACT(DOW))
   CREATE OR REPLACE FUNCTION tournaments.next_grid_boundary(
       p_from      timestamptz,
       p_weekday   int,
       p_tod       time,
       p_tz        text,
       p_period    interval
   ) RETURNS timestamptz LANGUAGE plpgsql AS $$
   DECLARE
       v_local       timestamp;     -- wall-clock in the anchor tz
       v_anchor_day  date;
       v_candidate   timestamptz;
       v_dow_diff    int;
   BEGIN
       -- Interpret "now" as wall-clock in the configured anchor timezone.
       v_local := p_from AT TIME ZONE p_tz;                  -- timestamptz -> local timestamp
       -- Days until the next occurrence of the target weekday (0..6).
       v_dow_diff := (p_weekday - EXTRACT(DOW FROM v_local)::int + 7) % 7;
       v_anchor_day := (v_local::date) + v_dow_diff;
       -- Compose local wall-clock boundary, convert back to timestamptz in the anchor tz
       -- (this is the DST-correct step: AT TIME ZONE resolves the offset for THAT date).
       v_candidate := (v_anchor_day + p_tod) AT TIME ZONE p_tz;
       -- If that instant is already past (same-day but time elapsed), step one period.
       IF v_candidate <= p_from THEN
           v_candidate := v_candidate + p_period;
       END IF;
       RETURN v_candidate;
   END;
   $$;
   ```

**Example (bootstrap):**
```sql
-- Source: existing 0013 store.config precedent (stores next_rotation_at as a real ts column)
v_start := tournaments.next_grid_boundary(now(), v_cfg.anchor_weekday,
                                          v_cfg.anchor_time, v_cfg.anchor_tz, v_period);
INSERT INTO tournaments.editions (started_at, ends_at, status)
VALUES (v_start, v_start + v_period, 'active');
```

**DST handling (HIGH confidence — verified against PostgreSQL docs):** Do the weekday/time
arithmetic on the *local wall-clock* (`AT TIME ZONE p_tz` to get a `timestamp`, compose the
boundary, then `AT TIME ZONE p_tz` again to get back a `timestamptz`). Composing the local
wall-clock and converting back is what makes "every Monday 00:00 America/Los_Angeles" land on
the correct instant across a DST transition. Adding `interval '1 week'` to a `timestamptz` is
*calendar* arithmetic in PostgreSQL and is the right tool for "one week later, same wall-clock
slot"; do NOT use `interval '168 hours'` (that's exact-duration and will be one hour off across
DST). `[CITED: postgresql.org/docs/current/functions-datetime.html — "adding interval '1 day'
does not necessarily equal '24 hours' across DST"; "date_trunc/AT TIME ZONE performed with
respect to a particular time zone"]`

**Precedent in this codebase:** `migrations/0013_coin_store.sql` `store.config` already stores a
real `next_rotation_at timestamptz` column and `check_and_rotate()` only acts when
`now() >= next_rotation_at`. The edition model is the same shape, generalized to an explicit
per-rotation entity with a configurable grid anchor. `[VERIFIED: 0013_coin_store.sql:22-23,
247]`

### Pattern 2: Status-only cron flip under advisory lock (reuse 0021/0023 skeleton)

**What:** Keep the exact concurrency/atomicity skeleton from `process_cycle_transitions()` —
`pg_try_advisory_xact_lock(2025070100)`, one transaction, snapshot standings with the
identical tier-then-time `RANK()` CTE — but change the loop to operate on the **edition** and
NEVER write `now()` into timestamps.

**Anchor of the rewrite (what changes vs 0023):**
- Detection: `WHERE edition.status='active' AND now() >= edition.ends_at` (single row, not a
  per-category loop). `[replaces 0023:69-78]`
- Promote: create the *next edition* with inherited grid timestamps (Pattern 1 calc #1), NOT
  `UPDATE ... started_at = now()`. `[replaces 0023:151-153, 182-183 — the bug]`
- Pause (D-12): if `transitions_paused` is true at the boundary, finalize the current edition
  (results-only) and **do not create the next edition** — go into hiatus. `[new]`
- Outbox: ONE `edition_rollover` row with a combined payload (results[] + started[]), not N
  `cycle_started`/`cycle_completed` rows. `[replaces 0023:131-141, 159-203]`
- Champion role / XP / streaks: still keyed per child `cycle_id` inside the payload
  (preserve current reward path — see Pattern 4).

**Snapshot CTE:** copy `tournaments.fetch_leaderboard`'s `best_per_user → RANK() OVER
(ORDER BY verified DESC, time ASC)` block verbatim per child cycle (it already appears inline at
0023:88-122 and in `repository.fetch_leaderboard` 1259-1279 — identical ranking, do not
re-derive). `[VERIFIED: tournaments_repository.py:1259-1279, 0023:88-122]`

### Pattern 3: One combined outbox row → one event (D-09/D-10/D-11)

**What:** The transition fn writes ONE `pending_transitions` row per rollover with
`event_type='edition_rollover'` and a payload carrying both the finalized edition's
per-category results AND the new edition's per-category starts. The poller publishes ONE
`TournamentRolloverEvent` keyed by `edition_id`.

**Why this replaces the current grouping:** Today the poller groups rows by
`(event_type, created_at)` (`tournament_outbox_service.py:188`) — fragile because it depends on
two separate `INSERT`s sharing a transaction `created_at`, and it produces *two* messages
(started + completed) per rotation. With one row per rollover, grouping disappears: the
`edition_id` is the natural, stable idempotency key. `[VERIFIED: tournament_outbox_service.py:
56-59, 188, 196-204]`

**Idempotency key:** `tournament:rollover:{edition_id}` (one per rollover, replacing
`tournament:{event_type}:{created_at_iso}`). The poller's publish-before-mark + at-least-once
re-publish semantics stay identical. `[VERIFIED: tournament_outbox_service.py:203]`

**Outbox FK caveat:** `tournaments.pending_transitions.cycle_id` is `NOT NULL REFERENCES
tournaments.cycles(id)` `[VERIFIED: 0020_tournaments.sql:142-143]`. A per-edition row has no
single cycle. The migration must either (a) add a nullable `edition_id` column + relax/extend
the `event_type` CHECK to include `edition_rollover` and make `cycle_id` nullable, or (b) point
`cycle_id` at a representative child. Recommend (a): add `edition_id int REFERENCES
tournaments.editions(id) ON DELETE CASCADE`, make `cycle_id` nullable, extend the CHECK. The
poller groups by `edition_id`. `[ASSUMED — exact column strategy is the planner's call; flag]`

### Pattern 4: Reward/leaderboard/streak/champion wiring stays per child cycle

**What:** Do NOT re-key XP/streaks/leaderboards to the edition. The reward service
(`award_cycle_end`, `award_participation`), the `tournaments.xp_grants` ledger
(`UNIQUE(cycle_id, user_id, reason)`), `tournaments.streaks.last_cycle_id`, and
`tournaments.completions.cycle_id` are ALL keyed on `cycle_id`. The edition is a timing parent;
each category still has its own child cycle with its own leaderboard/winner/champion. Preserve
this exactly (CONTEXT Discretion: "preserve current behavior, re-wire to the new parent").

**Concretely:** the `edition_rollover` payload's `results[]` is a list of per-category objects,
each carrying its `cycle_id`, `category_id`, `standings`, `winner_user_id` — i.e. the existing
`TournamentCycleCompletedEvent` shape, one per category. The outbox service still calls
`award_cycle_end(event, conn)` and `_reset_non_participant_streaks(...)` **once per child cycle**
(per results entry), exactly as it does today per row. `[VERIFIED: tournament_outbox_service.py:
181-184, 219-246; tournament_reward_service.py:179-266; 0022_tournament_xp_grants.sql:19-24]`

### Anti-Patterns to Avoid
- **Writing `now()` into edition `started_at`/`ends_at`** — this *is* the bug. The cron job only
  flips status and stores inherited/grid-computed timestamps.
- **`interval '7 days'` literal vs `make_interval(weeks => ...)` for DST** — across a DST
  boundary use *calendar* interval (`make_interval(weeks=>1)` / `+ interval '1 week'`), never an
  exact-hours interval.
- **Recomputing the boundary on every cron tick from `now()`** — drift returns. Compute once at
  bootstrap/resume; thereafter chain `next.started_at = prev.ends_at`.
- **Cascade-deleting `core.completions` when wiping `tournaments.completions`** — D-15: NULL the
  FK first, keep the PB rows. The FK is `ON DELETE SET NULL` so even a raw delete won't cascade,
  but do the explicit `UPDATE ... = NULL` to be intention-revealing and order-safe.
- **Two messages per rollover** — one `edition_rollover` event only (D-09/D-11).
- **Re-deriving the ranking SQL** — copy the existing tier-then-time CTE verbatim.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Next-weekday-at-time-in-tz | Manual day-counting in Python then store | PL/pgSQL `AT TIME ZONE` + `EXTRACT(DOW)` (Pattern 1) | DST correctness; DB owns timing; keeps `now()` out of stored columns |
| Concurrent cron de-dup | Status flags / SELECT FOR UPDATE on config | `pg_try_advisory_xact_lock(2025070100)` (existing) | Auto-releases on COMMIT/ROLLBACK; already proven (0021/0023) |
| Idempotent cron (re)registration | Conditional DROP/CREATE guesswork | `cron.unschedule(...) WHERE EXISTS; cron.schedule(...)` (0013/0021 pattern) | Safe on migration re-run and where pg_cron is absent (test DBs) |
| Outbox at-least-once + dedupe | Bespoke publish tracking | Existing `fetch_unpublished_transitions` (FOR UPDATE SKIP LOCKED) + `publish_message(idempotency_key=...)` | Crash-safe publish-before-mark already implemented |
| Tier-then-time ranking | New window-function query | Copy `fetch_leaderboard` CTE | Identical semantics already snapshotted in the transition fn |
| XP double-grant guard | New check | `tournaments.xp_grants` ledger `claim_xp_grant` | `api.xp.grant` is in IGNORE_IDEMPOTENCY; ledger is the only real guard |
| jsonb ↔ struct round-trip | Manual dict building | `_async_pg_init` codecs + `msgspec.convert` | Drift between payload keys and struct surfaces as a loud `ValidationError` (Pitfall 5 of prior phase) |

**Key insight:** Almost everything needed already exists — the work is *restructuring* (edition
parent, one event) and *deleting the `now()` writes*, not building new machinery.

## Runtime State Inventory

> Rename/refactor/migration phase — required. This is a fresh-restart data migration (D-13/14/15).

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| **Stored data** | `tournaments.cycles` (all rows wiped), `tournaments.completions` (all rows wiped), `tournaments.xp_grants` (FK `ON DELETE CASCADE` to cycles → auto-deleted on cycle wipe), `tournaments.streaks.last_cycle_id` (FK `ON DELETE SET NULL` → auto-NULLed), `core.completions.tournament_completion_id` (FK `ON DELETE SET NULL` to `tournaments.completions` — **must NULL these but KEEP the core.completions rows**, D-15) | Data migration: `UPDATE core.completions SET tournament_completion_id = NULL WHERE tournament_completion_id IS NOT NULL;` THEN wipe `tournaments.completions`/`cycles`. Order matters but FK is SET NULL so safe either way; explicit NULL is intention-revealing. `[VERIFIED: 0020:170-172 ON DELETE SET NULL; 0022:19 CASCADE; 0020:124 SET NULL]` |
| **Live service config** | `tournaments.config` singleton (id=1) — `blacklist_weeks` persists; NEW columns added (cadence, anchor_weekday/time/tz, transitions_paused, debug_cycle_seconds) | Migration `ALTER TABLE ... ADD COLUMN` with sane defaults (e.g. cadence='weekly', anchor Monday 00:00 UTC). Migrate the per-category `transitions_paused`/`debug_cycle_seconds` (0023) values to global, then DROP those category columns (D-03). |
| **OS-registered state** | pg_cron job `tournament-cycle-transitions` (registered in 0021, runs `SELECT tournaments.process_cycle_transitions()`) | Re-register: `cron.unschedule('tournament-cycle-transitions')` then `cron.schedule(...,'SELECT tournaments.process_edition_transitions()')` (or keep the same fn name with new body via CREATE OR REPLACE — simpler; cron calls by name). Recommend keeping the job name; either rename the fn and reschedule, or `CREATE OR REPLACE` the same-named fn. `[VERIFIED: 0021:277-285]` |
| **Secrets/env vars** | None — `APP_ENVIRONMENT` gates the debug route (production rejects it) but no secret/key name changes. | None. The global debug route should keep the `APP_ENVIRONMENT == 'production'` guard from `set_debug_cycle_length` (`tournament_service.py:480-481`). |
| **Build artifacts / installed packages** | None — pure schema + Python source changes; SDK is workspace-local (`libs/sdk`), reinstalled by `just sync`. If SDK structs change, run `just fix` (per MEMORY.md) so `genjishimada_sdk` re-installs. | After SDK struct changes: `just sync` / `just fix` (MEMORY note: `ModuleNotFoundError: genjishimada_sdk` → `just fix`). |

**The canonical question (after every repo file is updated, what runtime state still holds the
old model?):** A running dev/prod DB still has the old per-category cycles + drifted timestamps
and the old pg_cron job pointing at the old function. The migration must wipe rows, replace the
function (CREATE OR REPLACE keeps the cron job valid), add config columns, and bootstrap the
first grid-aligned edition. There is no Discord/Datadog/Task-Scheduler state involved (the bot
is consumer-only; champion roles are live Discord roles addressed below).

**Champion-role holders at cutover (Discretion):** Recommend **retain current holders until the
first new rollover strips/grants** (CONTEXT's stated likely default). The wipe removes cycles but
does NOT touch Discord roles (bot never writes DB; roles are Discord-side). The existing
`_transfer_champion_role` strips ALL holders then grants the winner on each completion — so the
first real `edition_rollover` with a results section self-heals role state. No migration-time
Discord action needed. `[VERIFIED: tournaments.py:475-547 strips all `role.members` first]`

## Common Pitfalls

### Pitfall 1: Re-introducing drift by storing `now()`
**What goes wrong:** A well-meaning "set started_at when the edition activates" writes `now()`,
re-creating the exact bug being fixed.
**Why it happens:** The old code did this at three sites (0023:153, 183, and the bootstrap
`create_active_cycle` uses `started_at = now()` at repo:469).
**How to avoid:** Edition `started_at`/`ends_at` come ONLY from `next_grid_boundary()` (bootstrap/
resume) or from `prev.ends_at` (rollover). Grep the new migration + repo for `now()` near
edition timestamp writes — there should be none. The bootstrap path must use the grid calc, not
`create_active_cycle`'s `now()`.
**Warning signs:** Test "two consecutive rollovers under a late (delayed) cron tick land on the
same grid instants" fails.

### Pitfall 2: DST off-by-one from exact-hours intervals
**What goes wrong:** Using `now() + interval '168 hours'` (or `make_interval(hours=>168)`) crosses
a DST boundary and lands an hour off the wall-clock slot.
**How to avoid:** Use calendar intervals (`make_interval(weeks=>1)` / `+ interval '1 week'`) and
do weekday/time composition via `AT TIME ZONE` (Pattern 1).
**Warning signs:** A test pinned across a spring-forward/fall-back date shows `ends_at` at 01:00
or 23:00 instead of 00:00 local.

### Pitfall 3: Pause freezing the current edition instead of suppressing the next (D-12)
**What goes wrong:** Treating pause like 0023 (skip the category in detection) would freeze the
running edition forever — wrong semantics now.
**Why it happens:** 0023's pause skipped the *detection* loop (`transitions_paused = FALSE` in
WHERE), so a paused row never finalizes.
**How to avoid:** The active edition ALWAYS finalizes on its boundary (results announced). Pause
only gates **creating the next edition**. On resume, the next edition snaps to the next grid
boundary (D-13a). Three announcement cases: normal (results+start), into-hiatus (results-only),
out-of-hiatus (start-only).
**Warning signs:** Test "pause then cross boundary → edition completes AND no next edition is
created AND a results-only rollover event is published."

### Pitfall 4: FK wipe cascading away PB times (D-15)
**What goes wrong:** Deleting `tournaments.completions` while believing core rows are protected,
or worse, an accidental cascade removing legitimate `core.completions` PBs.
**Why it happens:** Misreading the FK direction. `core.completions.tournament_completion_id`
references `tournaments.completions(id)` with `ON DELETE SET NULL` — deleting the tournament row
NULLs the link, it does NOT delete the core row. Safe.
**How to avoid:** Explicit `UPDATE core.completions SET tournament_completion_id = NULL` before
the wipe (intention-revealing), then `DELETE`/`TRUNCATE` the tournament tables. Never add a
`CASCADE` to that FK.
**Warning signs:** Test "wipe migration preserves `core.completions` row count for cross-written
PBs while NULLing their `tournament_completion_id`."

### Pitfall 5: Outbox payload key drift vs struct
**What goes wrong:** The PL/pgSQL `jsonb_build_object` keys diverge from `TournamentRolloverEvent`
field names; the publish silently ships a bad event — except the existing design makes
`msgspec.convert` raise a `ValidationError` and leaves the row unpublished.
**How to avoid:** Keep payload keys byte-identical to the struct fields; add a test that
round-trips a hand-written payload jsonb through `msgspec.convert(payload,
TournamentRolloverEvent)`.
**Warning signs:** `_build_event`/poller raises `msgspec.ValidationError`; rows stay unpublished.

### Pitfall 6: SDK change without reinstall
**What goes wrong:** `ModuleNotFoundError: genjishimada_sdk` or stale struct after editing
`libs/sdk`.
**How to avoid:** `just fix` / `just sync` after SDK edits (MEMORY.md).

## Code Examples

### Edition table (recommended shape)
```sql
-- Source: derived from 0013 store.config (stored next_rotation_at) + 0020 cycle status enum
CREATE TABLE IF NOT EXISTS tournaments.editions (
    id         int         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    started_at timestamptz NOT NULL,          -- EXACT grid value; never now()
    ends_at    timestamptz NOT NULL,          -- started_at + period
    status     text        NOT NULL DEFAULT 'active'
               CHECK (status IN ('active', 'completed')),  -- editions need no pending/finalizing
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_editions_status ON tournaments.editions (status);
CREATE INDEX IF NOT EXISTS idx_editions_ends_at ON tournaments.editions (ends_at);

-- child link
ALTER TABLE tournaments.cycles
    ADD COLUMN IF NOT EXISTS edition_id int REFERENCES tournaments.editions(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS idx_cycles_edition_id ON tournaments.cycles (edition_id);
```

### Global config columns (on existing singleton)
```sql
-- Source: extends 0020 tournaments.config (id=1 singleton)
ALTER TABLE tournaments.config
    ADD COLUMN IF NOT EXISTS cadence text NOT NULL DEFAULT 'weekly'
        CHECK (cadence IN ('weekly', 'biweekly')),
    ADD COLUMN IF NOT EXISTS anchor_weekday int NOT NULL DEFAULT 1   -- 0=Sun..6=Sat; 1=Mon
        CHECK (anchor_weekday BETWEEN 0 AND 6),
    ADD COLUMN IF NOT EXISTS anchor_time time NOT NULL DEFAULT '00:00',
    ADD COLUMN IF NOT EXISTS anchor_tz text NOT NULL DEFAULT 'UTC',
    ADD COLUMN IF NOT EXISTS transitions_paused boolean NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS debug_cycle_seconds int
        CHECK (debug_cycle_seconds IS NULL OR debug_cycle_seconds > 0);

-- Migrate per-category levers (0023) to global, then drop them (D-03):
UPDATE tournaments.config SET transitions_paused = (
    SELECT bool_or(transitions_paused) FROM tournaments.categories
) WHERE id = 1;
ALTER TABLE tournaments.categories DROP COLUMN IF EXISTS transitions_paused;
ALTER TABLE tournaments.categories DROP COLUMN IF EXISTS debug_cycle_seconds;
ALTER TABLE tournaments.categories DROP COLUMN IF EXISTS cycle_frequency;  -- replaced by global cadence (D-02)
```

### Fresh-restart wipe preserving PBs (D-13/14/15)
```sql
-- Source: D-15 + verified FK ON DELETE SET NULL (0020:170-172)
-- 1) NULL the link on cross-written core rows (KEEP the core.completions PB rows).
UPDATE core.completions SET tournament_completion_id = NULL
WHERE tournament_completion_id IS NOT NULL;
-- 2) Wipe tournament state (xp_grants cascade from cycles; streaks.last_cycle_id SET NULL).
TRUNCATE tournaments.completions, tournaments.cycles, tournaments.editions RESTART IDENTITY CASCADE;
DELETE FROM tournaments.pending_transitions;   -- drop any stale outbox rows
-- 3) Bootstrap first edition snapped to next grid boundary (Pattern 1) -- in the same migration
--    OR via the bootstrap endpoint; planner's call.
```

### TournamentRolloverEvent (SDK) — combined, conditional sections
```python
# Source: collapses TournamentCyclesStartedEvent + TournamentCyclesCompletedEvent (sdk:469-496)
class TournamentRolloverEvent(Struct):
    """One combined rollover: results of edition N (optional) + start of N+1 (optional)."""
    edition_id: int
    results: list[TournamentCycleCompletedEvent]   # empty on out-of-hiatus (start-only)
    started: list[TournamentCycleStartedEvent]      # empty on into-hiatus (results-only)
# routing key: "api.tournament.rollover"; idempotency_key: f"tournament:rollover:{edition_id}"
```

### Bot handler (conditional rendering)
```python
# Source: fuses _on_cycle_started (tournaments.py:303) + _on_cycle_completed (339)
@queue_consumer("api.tournament.rollover", struct_type=TournamentRolloverEvent, idempotent=True)
async def _on_edition_rollover(self, event, _):
    # 1) champion transfers FIRST (only if there are results) — Pitfall 5 ordering preserved
    for entry in event.results:
        category = await self.bot.api.get_tournament_category(entry.category_id)
        await self._transfer_champion_role(entry, category)
    # 2) ONE CV2 card: append a results Container section iff event.results,
    #    then a "new cycle" section iff event.started, then send once.
```

## State of the Art

| Old Approach (phases 01–11) | New Approach (Phase 12) | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Per-category independent cycle timing, `started_at = now()` on promote | Single grid-anchored edition; stored exact grid timestamps | Phase 12 (D-01/05/08) | Drift eliminated; "new maps every Monday" predictable |
| Per-category `cycle_frequency` | Single global `cadence` on config | D-02 | One knob; PROJECT.md per-category requirement superseded |
| Per-category `transitions_paused`/`debug_cycle_seconds` (0023) | Global on config; pause = hiatus (suppress next) not freeze | D-03/D-12 | Whole-tournament levers; correct hiatus semantics |
| Two events (`cycle_started`+`cycle_completed`), grouped by `(event_type, created_at)` | One `edition_rollover` event keyed by `edition_id` | D-09/10/11 | One combined card; stable idempotency key |
| End time computed inline from frequency, no stored `ends_at` (frontend-spec §8 gap) | `ends_at` stored on the edition | D-08 | Frontend-spec §8 gap closed; bot/frontend stop computing it |

**Deprecated/outdated by this phase:**
- `TournamentCyclesStartedEvent` / `TournamentCyclesCompletedEvent` (sdk:469-496) — superseded by
  `TournamentRolloverEvent`. The per-category `TournamentCycleStartedEvent`/`...CompletedEvent`
  structs are RETAINED as payload elements inside the combined event (reuse, don't delete).
- `bootstrap_cycle` per-category `started_at = now()` path → edition bootstrap with grid snap.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Global config lives as new columns on `tournaments.config` (vs a new settings table) | Standard Stack / Code Examples | Low — config is already a singleton; trivial to relocate. Discretion item; planner confirms. |
| A2 | `tournaments.editions` is the entity name; status enum is just `active`/`completed` | Code Examples | Low — naming is explicit Discretion; editions don't need pending/finalizing (cycles keep theirs). |
| A3 | Outbox carries `edition_rollover` via a new nullable `edition_id` column + relaxed CHECK + nullable `cycle_id` | Pattern 3 | Medium — exact outbox schema strategy is the planner's call; alternative is a representative cycle_id. |
| A4 | Migration may be one file (0024) or split (0024–0026); single file is acceptable | Project Structure | Low — Discretion explicitly allows either. |
| A5 | Per-cycle endpoints (`/cycles`, `/cycles/{id}/leaderboard`, `/cycles/{id}/submit`) are KEPT and remain cycle-scoped; only timing reads gain edition awareness | Open Questions | Medium — frontend-spec contract; see OQ. Submit/leaderboard stay per cycle (rewards keyed on cycle_id). |
| A6 | Champion holders retained at cutover; first rollover self-heals via existing strip-all logic | Runtime State Inventory | Low — verified the bot strips all holders before granting. |
| A7 | Keep the pg_cron job NAME `tournament-cycle-transitions`; CREATE OR REPLACE the function (renamed body) | Runtime State Inventory | Low — cron calls by name; rescheduling is idempotent either way. |
| A8 | anchor_weekday uses PostgreSQL `EXTRACT(DOW)` convention (0=Sun..6=Sat) | Pattern 1 | Low — internal convention; document it in the column comment. |
| A9 | Default anchor = Monday 00:00 UTC, default cadence = weekly | Code Examples | Low — admin-configurable; defaults are illustrative, confirm with user. |

## Open Questions (RESOLVED)

1. **Fate of per-cycle API endpoints under the edition model (CONTEXT Discretion).**
   - What we know: `/cycles` (list), `/cycles/{id}/leaderboard`, `/cycles/{id}/submit` (frontend-spec §4), and `/categories/{id}/next-cycle` exist; submit/leaderboard/rewards are all keyed on `cycle_id`.
   - What's unclear: whether to add an `/editions` read surface and whether `/cycles` rows should expose `edition_id` + edition timing.
   - Recommendation: **Keep all per-cycle endpoints cycle-scoped** (submit/leaderboard/rewards must stay per cycle). Add `edition_id` to cycle responses and either add `GET /editions/active` (returns the shared `started_at`/`ends_at`) or surface edition timing on the active cycle response so the frontend stops deriving `ends_at` (closes frontend-spec §8). Flag the frontend-spec update to `/gsd-transition`.
   - RESOLVED: Keep per-cycle endpoints cycle-scoped; add GET /editions/active (Plan 12-04).

2. **Single migration vs several (CONTEXT Discretion).**
   - Recommendation: one file `0024_tournament_editions_overhaul.sql` is acceptable and keeps the wipe+schema+function+cron atomic; split only if review prefers. Wrap DDL in `BEGIN/COMMIT` like 0020/0023 (note: `CREATE EXTENSION`/`cron.schedule` guards follow the 0021 unwrapped-DO pattern).
   - RESOLVED: Single migration file 0024 (Plan 12-01).

3. **PROJECT.md requirement amendment.** The "configurable per-category cycle frequency"
   Active requirement is superseded by D-01/D-02. Flag to roadmap/PROJECT.md as
   amended/superseded (CONTEXT domain note). Not a code question — a doc-state action for the
   planner/`/gsd-transition`.
   - RESOLVED: Doc-state action for /gsd-transition (PROJECT.md per-category-frequency superseded by D-01/D-02), not a code blocker.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| PostgreSQL | Schema + PL/pgSQL fn | ✓ | 17 | — |
| pg_cron | Scheduled transition | ✓ (prod/dev image) / ✗ (test) | postgresql-17-cron | Migration guards on `pg_extension` so test DBs no-op the cron registration (existing 0021 pattern); transition fn is tested by calling it directly |
| RabbitMQ | Outbox publish | ✓ | aio-pika `>=9.5.5` | `X-PYTEST-ENABLED=1` header skips publish in tests |
| MinIO/R2 | (not used this phase) | — | — | — |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** pg_cron in the test environment — the established
guard (`IF EXISTS (SELECT 1 FROM pg_extension WHERE extname='pg_cron')`) makes the migration's
cron block a no-op there; transition-function logic is exercised by invoking
`tournaments.process_edition_transitions()` directly in repo/integration tests (as
`test_cycle_transitions.py` already does for the current fn). `[VERIFIED: 0021:276-290;
tests/repository/tournaments/test_cycle_transitions.py exists]`

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest `>=8.3.5` + pytest-asyncio (mode auto) + pytest-databases[postgres] |
| Config file | `apps/api/pyproject.toml` (`addopts = "--testmon"`) |
| Quick run command | `uv run --directory apps/api pytest tests/<file>.py -p no:xdist` (single file; testmon ok) |
| Full suite command | `uv run --directory apps/api pytest -n 4 --no-testmon` (TRUE full run — testmon hides unaffected failures, per MEMORY.md) |

### Phase Requirements → Test Map
Requirements derived from locked decisions (no REQ-IDs in roadmap). Each row is a proposed test seam.

| Decision | Behavior to prove | Test Type | Automated Command (proposed) | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| D-08 (drift fix) | Two consecutive rollovers under a *late* cron tick land on exact grid instants (`next.started_at == prev.ends_at`, no `now()` leakage) | integration (DB fn) | `pytest tests/repository/tournaments/test_edition_transitions.py -k drift -p no:xdist` | ❌ Wave 0 |
| D-06/D-07 (grid anchor) | `next_grid_boundary()` returns correct next weekday@time for a given tz, including a DST-crossing date | unit (SQL) | `pytest tests/repository/tournaments/test_grid_boundary.py -p no:xdist` | ❌ Wave 0 |
| D-01/D-05 (single edition) | One rollover creates ONE edition + one child cycle per active category, all sharing edition timing | integration | `pytest tests/repository/tournaments/test_edition_transitions.py -k single_edition -p no:xdist` | ❌ Wave 0 |
| D-12 (pause=hiatus) | Paused at boundary → current edition completes (results-only) AND no next edition created; resume snaps next to grid | integration | `... -k hiatus` | ❌ Wave 0 |
| D-09/D-10/D-11 (one event) | One `edition_rollover` row → ONE published event, one idempotency key `tournament:rollover:{edition_id}`; re-poll re-publishes idempotently | service | `pytest tests/services/test_tournament_outbox.py -k rollover -p no:xdist` | ❌ Wave 0 (extend existing outbox tests) |
| D-10 (3 cases) | Payload shapes: normal (results+started), into-hiatus (results only, started empty), out-of-hiatus (started only, results empty) render the right card sections | bot | `pytest tests/bot/test_tournaments_handler.py -k rollover -p no:xdist` | ⚠️ extend existing |
| D-13/D-14/D-15 (wipe) | Migration NULLs `tournament_completion_id` on cross-written rows, KEEPS `core.completions` rows, wipes tournament tables, bootstraps one grid-aligned edition | integration (migration) | `pytest tests/integration/test_tournaments_schema.py -k overhaul -p no:xdist` | ⚠️ extend existing |
| D-15 (FK safety) | `core.completions` row count for cross-written PBs unchanged; their `tournament_completion_id` is NULL | integration | `... -k preserve_pbs` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** the single relevant test file (`pytest tests/.../<file>.py -p no:xdist`).
- **Per wave merge:** `uv run --directory apps/api pytest -n 4 --no-testmon` (TRUE full suite — do NOT trust a green testmon run; MEMORY.md documents 13 hidden failures slipping through CI).
- **Phase gate:** full suite green before `/gsd:verify-work`. Run `just lint-all` (Ruff + BasedPyright strict) too — test files are lint-exempt but source is not.

### Wave 0 Gaps
- [ ] `tests/repository/tournaments/test_grid_boundary.py` — `next_grid_boundary()` correctness incl. DST (D-06/07)
- [ ] `tests/repository/tournaments/test_edition_transitions.py` — drift-immunity, single-edition, hiatus (D-01/05/08/12)
- [ ] Extend `tests/services/test_tournament_outbox.py` — one combined `edition_rollover` event + idempotency (D-09/11) *(verify exact existing filename; current outbox tests live alongside `test_tournament_*`)*
- [ ] Extend `tests/bot/test_tournaments_handler.py` — three conditional rendering cases (D-10)
- [ ] Extend `tests/integration/test_tournaments_schema.py` — wipe/FK-null/bootstrap migration (D-13/14/15)
- [ ] Shared fixtures: an "advance the clock past `ends_at`" helper (set edition `ends_at` in the past) and a "simulate late cron" helper to invoke the transition fn at an arbitrary delay — both prove D-08 without real time passing
- [ ] Framework install: none — existing infra covers it

## Security Domain

> `security_enforcement` not found in `.planning/config.json` (file absent). Treated as enabled; section included.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | Existing `X-API-KEY` middleware; routes keep `opt={"required_scopes": {...}}` (`tournaments:read`/`write`) |
| V3 Session Management | no | No sessions added |
| V4 Access Control | yes | Scope guards unchanged; global pause/debug routes require `tournaments:write`; debug route keeps the `APP_ENVIRONMENT == 'production'` reject (`tournament_service.py:480`) |
| V5 Input Validation | yes | msgspec struct typing on all requests; `anchor_tz` text is consumed by `AT TIME ZONE` — validate it is a known tz name (a bad tz raises in PL/pgSQL → keep it admin-only and consider a CHECK against `pg_timezone_names`) |
| V6 Cryptography | no | None |
| V12/V5 (injection) | yes | Raw SQL uses `$1..$n` positional params only (asyncpg) — no string interpolation of user input; `anchor_tz`/cadence are CHECK-constrained or validated |

### Known Threat Patterns for {PostgreSQL/PL-pgSQL + Litestar + discord.py}

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via dynamic `SET field = ...` in repo update builders | Tampering | Field names come from a fixed allow-list (existing `update_config`/`update_category` build `SET` from known keys, values via `$n`) — keep that pattern; never interpolate values |
| Invalid `anchor_tz` crashing the cron fn (DoS of transitions) | Denial of Service | CHECK `anchor_tz IN (SELECT name FROM pg_timezone_names)` at write time, or validate in the service before persisting |
| Mention-injection in the rollover card (free-text winner names) | Tampering/Spoofing | Preserve existing rule: mention winners by numeric `<@id>` ONLY, `AllowedMentions(users=allow-list, everyone=False, roles=False)` (`tournaments.py:380-408`) |
| Debug-length lever abused in production to shrink cycles | Tampering | Keep the `APP_ENVIRONMENT == 'production'` guard; require `tournaments:write` |
| Concurrent/duplicate rollover publish | Tampering | Advisory lock in the fn + `edition_id` idempotency key + outbox FOR UPDATE SKIP LOCKED (all existing) |

## Project Constraints (from CLAUDE.md)

- **No ORM** — raw asyncpg SQL with `$1..$n` positional params; repo methods accept `conn: Connection | None = None` and use `self._get_connection(conn)`.
- **Bot NEVER writes Postgres** — bot is consumer-only; the rollover handler reads missing data via the API and performs only Discord-side actions (role transfer, card post).
- **Three-layer** Controller → Service → Repository; DI via `provide_*` functions.
- **msgspec structs in SDK** (`libs/sdk/src/genjishimada_sdk/tournaments.py`); `*Request`/`*Response`/`*Event` suffixes; `UNSET`/`UnsetType` for PATCH fields.
- **pg_cron + advisory-lock migration pattern** — guard `CREATE EXTENSION`/`cron.schedule` on `pg_extension`; idempotent `unschedule`-then-`schedule`; `pg_try_advisory_xact_lock(2025070100)` (do NOT collide with store lock `1234567890`).
- **`idempotency_key` on `publish_message`** unless the routing key is in `IGNORE_IDEMPOTENCY`. The new `api.tournament.rollover` key needs an idempotency key (`tournament:rollover:{edition_id}`).
- **Sequential migration numbering** — next file is `0024_*`.
- **Logging** — `log` var, `%s` formatting, `log.exception()` for caught errors, emoji prefixes for RabbitMQ ops.
- **DB exception handling** — catch specific repo exceptions only where a user-friendly transform is needed; otherwise let them propagate.
- **GSD workflow** — all edits go through a GSD command (this is `/gsd:plan-phase` research).
- **Line length 120, Ruff + BasedPyright strict, Google docstrings** (tests lint-exempt).

## Sources

### Primary (HIGH confidence)
- Codebase (read directly): `apps/api/migrations/{0013,0020,0021,0022,0023}.sql`, `apps/api/services/{tournament_service,tournament_outbox_service,tournament_reward_service}.py`, `apps/api/repository/tournaments_repository.py`, `apps/api/routes/v3/tournaments.py`, `apps/api/app.py` (poller), `apps/bot/extensions/tournaments.py`, `libs/sdk/src/genjishimada_sdk/tournaments.py`, `infra/postgres/Dockerfile`.
- `.planning/phases/12-overhaul-of-tournaments/12-CONTEXT.md` — locked decisions D-01..D-15.
- `docs/specs/tournament-frontend-spec.md` (§3/§6/§8 contract), `docs/specs/tournament-leaderboard.md` (cross-write + FK model).
- CLAUDE.md (constraints, tech stack), MEMORY.md (test-running gotchas: testmon hides failures, `just fix` for SDK reinstall).

### Secondary (MEDIUM confidence)
- [PostgreSQL Date/Time Functions docs](https://www.postgresql.org/docs/current/functions-datetime.html) — `date_trunc`/`AT TIME ZONE`/calendar-vs-exact interval DST behavior (corroborates Pattern 1/Pitfall 2).

### Tertiary (LOW confidence)
- None — all load-bearing claims are verified against the codebase or PostgreSQL docs.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; all verified in CLAUDE.md/uv.lock and used by existing tournament code.
- Architecture (edition model, status-only flip, one event): HIGH — direct extension of existing 0013/0021/0023 patterns; bug root cause located at specific lines.
- Grid-time PL/pgSQL: HIGH — standard PostgreSQL 17 date arithmetic; DST approach confirmed by docs.
- Pitfalls: HIGH — derived from the actual code being changed and prior-phase pitfalls.
- Exact table/column/outbox-schema names: MEDIUM — Claude's Discretion; recommendations given, planner confirms (see Assumptions Log).

**Research date:** 2026-06-01
**Valid until:** 2026-07-01 (stable — internal codebase + mature PostgreSQL features; re-verify only if the tournament code changes before planning)
