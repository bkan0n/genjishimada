# Phase 7: Automatic Cycle Transitions - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.
>
> **Mode:** `--auto` — no interactive prompts. Every option below was auto-selected
> using the recommended (codebase-aligned) choice. Listed so a human can audit the defaults.

**Date:** 2026-05-30
**Phase:** 7-Automatic Cycle Transitions
**Areas discussed:** Transition mechanism, End-time detection, Next-cycle start & map source, Placement computation & outbox payload, Outbox publishing bridge, Cadence

---

## Transition Mechanism & Concurrency

| Option | Description | Selected |
|--------|-------------|----------|
| PL/pgSQL function via pg_cron + advisory lock | DB owns scheduled work; mirrors `store.check_and_rotate()` (0013) | ✓ |
| API lifespan task drives transitions in Python | API polls for due cycles and mutates via repo | |
| External scheduler / cron container | New infra; rejected (no new frameworks constraint) | |

**Auto choice:** PL/pgSQL function via pg_cron + global advisory lock.
**Notes:** Closest proven analog is `0013_coin_store.sql`. Advisory lock + EXCEPTION cleanup + idempotent `cron.schedule` guarded by `pg_extension` check. → D-01, D-02, D-03.

---

## End-Time Detection

| Option | Description | Selected |
|--------|-------------|----------|
| Compute inline from `started_at + cycle_frequency` | No schema change; frequency is single source of truth | ✓ |
| Add stored `scheduled_end_at` column | Explicit, admin-overridable; requires a new migration | |

**Auto choice:** Compute inline (`weekly` → 7d, `biweekly` → 14d).
**Notes:** `tournaments.cycles` has only `started_at`/`ended_at`. Avoids a migration; stored column deferred. → D-04.

---

## Next-Cycle Start & Map Source

| Option | Description | Selected |
|--------|-------------|----------|
| Promote pre-rolled pending cycle → active, then pre-roll next via SQL helper | Reuses Phase 5 pre-roll; always keeps a pre-roll ready | ✓ |
| Select a fresh map at transition time (no pre-roll consumed) | Ignores Phase 5 pre-roll design | |
| API pre-rolls the next cycle on receipt of `cycle_started` event | Avoids SQL/Python selection duplication | (noted as research alternative) |

**Auto choice:** Promote pending → active; pre-roll next via a SQL selection helper mirroring `fetch_eligible_maps`.
**Notes:** SQL/Python duplication is the key risk STATE.md flagged — research must validate or adopt the API-pre-roll alternative. → D-05, D-06, D-07.

---

## Placement Computation & Outbox Payload

| Option | Description | Selected |
|--------|-------------|----------|
| Compute at finalization, embed standings in `cycle_completed` payload | No new table; downstream reads payload | ✓ |
| Materialize placements into a new table/column | Queryable later; adds schema | |
| Compute on-the-fly at read time only | No snapshot; risky once submissions stop | |

**Auto choice:** Compute at finalization (same tier-then-time RANK() as leaderboard), embed in outbox payload.
**Notes:** Two outbox rows per transition: `cycle_completed` + `cycle_started`, matching the schema CHECK. → D-08, D-09.

---

## Outbox → RabbitMQ Bridge

| Option | Description | Selected |
|--------|-------------|----------|
| API lifespan background asyncio poller, SKIP LOCKED, publish + mark | Matches "API polls the outbox" success criterion | ✓ |
| LISTEN/NOTIFY trigger pushes to API | Lower latency; more moving parts | |
| Second pg_cron job publishes directly | DB can't easily reach RabbitMQ; rejected | |

**Auto choice:** Lifespan poller using `FOR UPDATE SKIP LOCKED`, publish via `BaseService.publish_message()`, then mark `published = TRUE`.
**Notes:** Added alongside `rabbitmq_connection` in `app.py`. At-least-once; duplicates handled by Phase 9 idempotency. → D-10, D-11.

---

## Cadence

| Option | Description | Selected |
|--------|-------------|----------|
| pg_cron every minute; poll every ~10s | Fires close to schedule; responsive announcements | ✓ |
| pg_cron hourly (coin_store default) | Coarser; up to 1h late | |

**Auto choice:** pg_cron `* * * * *`; outbox poll ~10s. Both tunable. → D-12.

---

## Claude's Discretion

- SQL function/helper names; whether selection is a new helper or reuses Phase 5 query text.
- Session-level vs transaction-level advisory lock.
- Exact poll interval / cron expression within the cadence intent.
- Migration file number and whether cron registration is in the same or a dedicated migration.
- How the poller acquires a pooled DB connection inside the lifespan task.
- Exact JSON shape of `cycle_started` / `cycle_completed` payloads (align with Phase 2 SDK structs).

## Deferred Ideas

- Reward/XP grants & streaks on transition → Phase 8 (consumes `cycle_completed`).
- Discord announcements & champion role transfer → Phase 9 (consumes both events).
- Admin/manual transition trigger → out of scope (automatic only).
- Stored `scheduled_end_at` / admin-adjustable end times → deferred unless a future requirement needs per-cycle overrides.
