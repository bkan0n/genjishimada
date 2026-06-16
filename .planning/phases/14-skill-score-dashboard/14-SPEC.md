# Phase 14: Skill Score Dashboard — Specification

**Created:** 2026-06-16
**Ambiguity score:** 0.12 (gate: ≤ 0.20)
**Requirements:** 7 locked

## Goal

Expose REST endpoints under `/api/v3/skill/users/{id}/...` that serve a per-user skill-score dashboard: a timestamped score history filterable by 7d/30d/90d/1y/all, window summary stats (best, lowest, average, first-vs-last point change and percentage), a recent-changes feed of every recompute that touched the user (tagged PLAYER_ACTION / MAP_ENVIRONMENT / SYSTEM), and a per-change drill-down attributing the delta to individual maps plus an "other factors" aggregate.

## Background

Phase 13 shipped the skill-score engine. The current state, grounded in code:

- **No history exists.** `skill.snapshot` (migration `0027`) is a **lean, single-row-per-user cache** that `SkillRepository.replace_snapshot` **TRUNCATEs and rebuilds** on every `recompute_all`. The `computed_at` column reflects only the most recent global rebuild — there is exactly one row per user, holding the *current* score. Past scores are unrecoverable.
- **Recompute is a full GLOBAL rebuild**, never incremental (`SkillService._do_recompute`). It is triggered by: the in-process `skill.recompute.requested` listener (fired from all four verify/reject/flag completion paths), `PATCH /skill/config` and `PATCH /skill/tiers`, the nightly 04:00 UTC backstop, and cold-start auto-fill. A `_RecomputeGuard` **coalesces** a burst of triggers into a single rebuild.
- **No per-change attribution.** The `SkillRecomputeRequestedEvent` carries an optional `reason` string that is currently logged only — unused for any persisted attribution. There is no notion of "what changed a user's score" and no per-user delta.
- **Per-map breakdown exists for the current state only.** `skill.snapshot.breakdown` (JSONB, D-06) holds each user's current per-map contributions, but nothing captures a before/after diff across a change.
- **Endpoints today:** `GET /skill/users/{id}`, `/users/{id}/breakdown`, `/tiers`, `/config`; `PATCH /tiers`, `/config`. No time-series, summary, or change-feed endpoint exists.

This phase adds a **forward-only history + per-change capture layer** that rides the existing `recompute_all` routine, plus three read endpoints. It is an **API-only vertical** — the website that renders this dashboard is a separate later phase, consistent with Phase 13.

## Requirements

1. **Timestamped history capture**: Every `recompute_all` records a timestamped score point for every user with data.
   - Current: `skill.snapshot` is overwritten (TRUNCATE + rebuild) on every recompute; no history is retained and `computed_at` reflects only the latest rebuild.
   - Target: a new timestamped history store gains one point per user-with-data on every recompute (all such users, even those whose score did not move), forward-only from this phase, retained unbounded. No backfill of pre-phase scores.
   - Acceptance: after two recomputes, a user with data has ≥2 history rows with distinct `captured_at`; no rows exist with a timestamp before the phase rollout.

2. **Per-change record with cause + delta + breakdown diff**: Each recompute persists, per user, the data needed to explain the score move.
   - Current: recompute carries an unused optional `reason`; no per-user previous/new score, delta, cause, or breakdown diff is stored.
   - Target: each recompute writes, per user-with-data, a change record carrying `previous_score`, `new_score`, `delta`, a `cause_category` ∈ {`PLAYER_ACTION`, `MAP_ENVIRONMENT`, `SYSTEM`}, a human-readable reason, and the before/after per-map breakdown needed for drill-down. A single clean trigger keeps its specific PLAYER/MAP cause; coalesced bursts and the nightly backstop are `SYSTEM` "global recalculation".
   - Acceptance: a verified completion by user X yields a `PLAYER_ACTION` change for X with `delta = new_score − previous_score`; a `PATCH /config` or nightly recompute yields `SYSTEM`-tagged changes; a coalesced multi-trigger recompute is tagged `SYSTEM` "global recalculation".

3. **History + summary endpoint**: `GET /api/v3/skill/users/{id}/history?window=7d|30d|90d|1y|all`.
   - Current: no time-series or summary endpoint exists.
   - Target: returns the ordered list of `(captured_at, skill_score)` points within the window plus a summary block: `point_change`, `percent_change`, `best {score, date}`, `lowest {score, date}`, `average`. Anchoring: `point_change = latest_in_window − earliest_in_window`; `percent_change = point_change / earliest_in_window × 100`; if the window begins before the user's first record, anchor on the earliest available record. `best`/`lowest` are the max/min points in the window with their dates; `average` is the mean of in-window points.
   - Acceptance: a known fixture series over 30d returns the correct best/lowest/average and first-vs-last `point_change`/`percent_change`; an invalid `window` value returns 4xx; a user with no history returns 200 with an empty points list and an all-zero summary.

4. **Recent-changes feed endpoint**: `GET /api/v3/skill/users/{id}/changes?window=...&limit=...` (paginated).
   - Current: no change-feed endpoint exists.
   - Target: returns change records newest-first, each with `change_id`, `captured_at`, `delta`, `cause_category`, and a short description; supports the same window filter and pagination (limit + cursor/offset).
   - Acceptance: records return in descending `captured_at` order; pagination bounds the page size; the window filter is respected; a user with no history returns an empty feed.

5. **Change drill-down endpoint**: `GET /api/v3/skill/users/{id}/changes/{change_id}`.
   - Current: no drill-down endpoint exists; nothing stores a before/after per-map diff.
   - Target: returns `previous_score`, `new_score`, `delta`, `percent_change`, `cause_category`, a `main_causes` list of `{map, reason, impact}` derived from the stored per-map breakdown diff (`impact = new_contribution − old_contribution`), and an `other_factors` aggregate. The largest-magnitude maps are listed individually (top-N); the remaining long tail is rolled into `other_factors`. The listed impacts plus `other_factors` sum to the total `delta`.
   - Acceptance: for a known before/after breakdown, `sum(main_causes.impact) + other_factors == delta` within 1e-6; an unknown or foreign `change_id` (not belonging to the user) returns 404.

6. **Time-window filtering**: The 7d/30d/90d/1y/all windows constrain both history and changes.
   - Current: no windowing exists.
   - Target: each window returns only points/changes whose `captured_at` falls within the range relative to "now"; `all` returns the full retained history.
   - Acceptance: each of the five window values returns only in-range data; `all` returns every retained record; an unrecognized window value is rejected with a 4xx.

7. **Empty / zero-eligible handling**: New users and zero-eligible players never error.
   - Current: Phase 13 returns a zero summary / empty breakdown for zero-eligible players (D-07); the new endpoints must continue this.
   - Target: a user with no eligible runs / no history returns 200 with an empty series + zero summary (`/history`), an empty feed (`/changes`), and 404 for any `change_id` (`/changes/{id}`). Never 500, never a synthetic row.
   - Acceptance: all three endpoints return the empty/zero shapes above (and the documented 404) for a user with no snapshot/history; none return 500.

## Boundaries

**In scope:**
- A new migration adding timestamped per-user history + per-change capture (cause, prev/new/delta, before/after breakdown) in the `skill` schema.
- Wiring that capture into the existing single `recompute_all` routine (D-04 — no forked compute path).
- Threading a 3-category cause (`PLAYER_ACTION` / `MAP_ENVIRONMENT` / `SYSTEM`) through each recompute trigger, reusing the existing recompute `reason` channel.
- Three GET endpoints: `/skill/users/{id}/history` (+summary), `/skill/users/{id}/changes` (feed), `/skill/users/{id}/changes/{change_id}` (drill-down).
- Time-window filtering (7d/30d/90d/1y/all) on history and changes.
- New SDK msgspec structs for the responses; integration + service tests.

**Out of scope:**
- The website/frontend dashboard UI in the screenshot — separate later phase; this repo has no frontend codebase.
- A Discord bot surface for the dashboard — later phase.
- Backfill or reconstruction of pre-phase scores — past scores were never recorded and are unrecoverable; map difficulties/field sizes have also drifted.
- Retention pruning, capping, or downsampling — retention is unbounded forward-only for now; pruning is a later concern.
- Push notifications / alerts when a user's score changes — not a dashboard read concern.
- Leaderboard-wide or multi-user history aggregation beyond the per-user endpoints.
- Any change to the Phase 13 scoring formula, `skill.weight_config`, or the tier/percentile system — unchanged this phase.

## Constraints

- **Scorer immutability:** the Phase 13 scorer math (`SkillService._map_score`/`_player_score`/`_player_breakdown`), `skill.weight_config`, and the tier/percentile system must remain byte-for-byte unchanged; existing skill tests must still pass.
- **Single recompute path:** history/change capture must ride the one shared `recompute_all` routine (D-04), the same routine used by the event listener, the nightly backstop, and the PATCH paths — no second compute path.
- **Capture volume:** one history point + one change record per user-with-data per recompute (~261 active users × recompute frequency). The `_RecomputeGuard` coalescing bounds burst volume. Retention is unbounded forward-only; this is acceptable at current scale.
- **Cause threading:** the cause category is supplied by each recompute trigger via the existing `reason` channel — verify/reject/flag carry PLAYER/MAP causes; config/tier/nightly/coalesced default to `SYSTEM` "global recalculation".
- **Drill-down conservation:** `sum(main_causes.impact) + other_factors` must equal the recorded `delta` within 1e-6.
- **Project conventions:** Litestar + AsyncPG + msgspec; raw SQL; three-layer Controller → Service → Repository; new migration under `apps/api/migrations/` with sequential numbering; `just lint-api`/`lint-sdk` clean.

## Acceptance Criteria

- [ ] A new sequential migration adds timestamped history + per-change capture tables in the `skill` schema and applies cleanly on a fresh test DB.
- [ ] `recompute_all` writes one history point + one change record per user-with-data on every recompute (forward-only; no pre-phase rows).
- [ ] `GET /skill/users/{id}/history?window=…` returns ordered points + summary (best/lowest/average + first-vs-last `point_change` & `percent_change`) for all five windows.
- [ ] `GET /skill/users/{id}/changes` returns a newest-first paginated feed, each record carrying `delta` + `cause_category`.
- [ ] `GET /skill/users/{id}/changes/{change_id}` returns prev/new/delta + per-map `main_causes` (top-N) + `other_factors` that sum to `delta` within 1e-6.
- [ ] Each change is tagged `PLAYER_ACTION` / `MAP_ENVIRONMENT` / `SYSTEM`; coalesced bursts and the nightly backstop are `SYSTEM` "global recalculation".
- [ ] Invalid `window` value → 4xx; unknown/foreign `change_id` → 404; user with no history → 200 empty series + zero summary + empty feed (never 500).
- [ ] Phase 13 scorer math, `weight_config`, and tier system are unchanged (grep clean; existing skill tests still pass).
- [ ] New SDK structs added for the responses; `just lint-api`/`lint-sdk` clean; new integration tests pass.

## Ambiguity Report

| Dimension          | Score | Min  | Status | Notes                                              |
|--------------------|-------|------|--------|----------------------------------------------------|
| Goal Clarity       | 0.92  | 0.75 | ✓      | API-only dashboard endpoints, surface confirmed    |
| Boundary Clarity   | 0.88  | 0.70 | ✓      | Explicit out-of-scope; forward-only; 3 endpoints   |
| Constraint Clarity | 0.78  | 0.65 | ✓      | Capture cadence, retention, coalesce/nightly fixed |
| Acceptance Criteria| 0.90  | 0.70 | ✓      | 9 pass/fail criteria, 1e-6 conservation check      |
| **Ambiguity**      | 0.12  | ≤0.20| ✓      |                                                    |

Status: ✓ = met minimum, ⚠ = below minimum (planner treats as assumption)

## Interview Log

| Round | Perspective     | Question summary                          | Decision locked                                                        |
|-------|-----------------|-------------------------------------------|------------------------------------------------------------------------|
| 1     | Researcher/Boundary | What surface does Phase 14 ship?      | API-only (`/skill/*` endpoints); website/bot are later phases          |
| 1     | Researcher      | How is the time-series populated?         | Forward-only accrual; no backfill (past scores unrecoverable)          |
| 1     | Boundary Keeper | How granular is change attribution?       | Per-recompute, with cause + per-map breakdown diff for drill-down      |
| 2     | Constraint      | When is a history/change record written?  | Per recompute, for ALL users with data (even unchanged)                |
| 2     | Constraint      | Retention policy?                         | Unbounded, forward-only (pruning deferred)                             |
| 2     | Boundary Keeper | Cause taxonomy?                           | 3 categories: PLAYER_ACTION / MAP_ENVIRONMENT / SYSTEM                  |
| 3     | Boundary Keeper | Endpoint structure?                       | Three endpoints: history(+summary), changes feed, change detail        |
| 3     | Failure Analyst | Coalesced bursts & nightly attribution?   | Coalesced + nightly = SYSTEM "global recalculation"                    |
| 4     | Failure Analyst | Summary gain/loss anchoring?              | First vs last point in window; anchor on earliest record if needed     |
| 4     | Failure Analyst | Empty/new-user behavior?                  | Empty series + zero summary + empty feed; 404 on bad change id; no 500 |
| 4     | Seed Closer     | Drill-down "main causes" derivation?      | Per-map contribution delta, top-N individually + "Other factors" rollup|

---

*Phase: 14-skill-score-dashboard*
*Spec created: 2026-06-16*
*Next step: /gsd:discuss-phase 14 — implementation decisions (history table schema, capture wiring into recompute_all, pagination scheme, top-N cutoff)*
