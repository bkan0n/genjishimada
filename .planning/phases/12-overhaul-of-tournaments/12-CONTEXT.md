# Phase 12: Overhaul of tournaments - Context

**Gathered:** 2026-06-01
**Status:** Ready for planning

<domain>
## Phase Boundary

Replace the per-category cycle-timing model with a **single shared-epoch tournament**. Today each
`tournaments.cycles` row gets `started_at = now()` independently — at bootstrap (per category) and on
every pg_cron promote (`migrations/0021` `process_cycle_transitions()` sets `started_at = now()`,
computes end inline). Because `now()` is re-stamped on each transition and the cron tick fires up to
~60s late, categories drift apart and never re-converge.

This phase makes all categories run as **one tournament**: a single grid-anchored start/end shared by
every category (an explicit top-level tournament entity per rotation, with per-category cycles as its
children), and collapses the separate start + end announcements into **one combined rollover message**.

**In scope:**
1. Single global cadence — all categories transition together on one shared grid (D-01, D-02).
2. Explicit top-level tournament entity per rotation holding the shared timing (D-05).
3. Fixed, admin-configurable wall-clock grid anchor; edition times recorded as exact grid values, not
   execution time (D-06, D-07, D-08).
4. Global pause (suppress next start = hiatus) + global debug-cycle-length levers (D-03, D-12).
5. One combined rollover announcement (results of N + start of N+1) via a single combined event (D-09,
   D-10, D-11).
6. Fresh-restart migration onto the new model (D-13, D-14, D-15).
7. SDK structs/events, API service+repo+route changes, migration(s), bot handler changes, tests.

**Out of scope (not this phase):**
- Changing map selection / blacklist / pre-roll logic (Phases 5/7 own that mechanism — reused as-is).
- Changing the leaderboard *ranking* formula (tier-then-time, Phase 6) or the verification flow
  (Phase 11).
- New tournament *capabilities* (seasons, multiple simultaneous tournaments, etc. — Out of Scope in
  PROJECT.md).
- Bot writing to Postgres (architecturally forbidden — bot calls the API / consumes events).

**Requirement amendment (flag for roadmap/PROJECT.md):** PROJECT.md lists "Configurable **per-category**
cycle frequency (weekly or biweekly)" as an Active requirement. This overhaul **replaces it with a
single global cadence** (D-01/D-02). The planner and `/gsd-transition` should move that requirement to
amended/superseded.

</domain>

<decisions>
## Implementation Decisions (locked this discussion — do not revisit)

### Cadence & data model
- **D-01:** **Single global cadence.** All categories start AND end together every period — one
  tournament spanning every category, not per-category independent cycles. Makes "one shared start/end
  event" literally true every rotation.
- **D-02:** The period is **one admin-configurable global frequency** (weekly/biweekly), e.g. on the
  existing `tournaments.config` table alongside `blacklist_weeks`. Replaces per-category
  `tournaments.categories.cycle_frequency` with a single global knob.
- **D-03:** The **pause/resume and debug-cycle-length levers become global** (one `transitions_paused`
  + one `debug_cycle_seconds` for the whole tournament, e.g. on `tournaments.config`). Migrate/drop the
  per-category columns added in migration 0023. (Pause semantics refined in D-12.)
- **D-05:** Model "one tournament" as an **explicit top-level entity per rotation** (e.g.
  `tournaments.editions`) holding the shared `started_at`/`ends_at`; each category's run is a **child
  cycle linked to it**. This changes API/SDK response shapes (the shared timing moves up a level off
  individual cycles) and the frontend spec — planner must account for downstream shape changes.

### Grid anchor & boundary
- **D-06:** **Fixed wall-clock anchor.** Each edition rolls over on a configured weekday + time slot
  (e.g. every Monday 00:00 UTC) — edition N ends and N+1 starts on that exact slot. Predictable for
  players ("new maps every Monday").
- **D-07:** The anchor is **admin-configurable** (weekday + time-of-day + timezone, stored in
  `tournaments.config`). Changes take effect **next edition**, locked mid-edition.
- **D-08:** **Record grid times, not execution time** (the core drift fix). An edition's
  `started_at`/`ends_at` are ALWAYS the exact grid boundary (anchor + N×period), regardless of when the
  cron job actually fires. The pg_cron job only **flips status** — it must never write `now()` into the
  timestamps. Late execution can no longer shift the grid.
- **D-13a (first edition):** On bootstrap (and on resume from hiatus), the first/next edition **snaps to
  the next grid boundary** — perfectly grid-aligned from day one. A startup gap (no active tournament
  until the boundary) is acceptable. This keeps D-08's "record grid times" rule with **no exceptions**.

### Combined announcement
- **D-09:** **One combined message per rollover** — a single announcement carrying both the results of
  edition N and the start of edition N+1 (per category). A **new combined event** (e.g.
  `TournamentRolloverEvent`) replaces the separate `cycle_started`/`cycle_completed` pair, consumed by a
  single bot handler (replacing `_on_cycle_started` / `_on_cycle_completed`).
- **D-10:** The combined message uses **conditional sections** — an optional "results" part (previous
  edition) and an optional "starting" part (new edition); the card renders whichever are present.
- **D-11:** **Produced via a single `edition_rollover` outbox row** per rollover (one
  `tournaments.pending_transitions` row whose payload holds results for all categories + next maps for
  all categories). Poller publishes one event with **one idempotency key per rollover**. Replaces the
  current `(event_type, created_at)` grouping that can fragment a rotation into multiple messages.
- **D-12 (pause semantics — clarified by user):** **Pause = suppress the NEXT edition from starting (a
  hiatus), NOT freeze the current edition.** The active edition always runs its full term and announces
  results on schedule. Resume (unpause) → next edition starts at the next grid boundary (per D-13a).
  Therefore the three announcement cases are:
  - **Normal rollover:** results (N) + start (N+1) — both sections.
  - **Going into hiatus** (paused when N ends): **results-only**.
  - **Coming out of hiatus** (resume): **start-only** — same shape as the very first edition.
  **Debug-cycle-length** just shrinks the grid period for testing; the current edition still ends on its
  computed boundary.

### Live migration (fresh restart)
- **D-13:** **Fresh restart.** Finalize/discard the currently-running in-flight cycles and bootstrap the
  first edition fresh (snapping to the next boundary per D-13a). No real production standings to protect
  at cutover.
- **D-14:** **Wipe everything** — drop all cycles + tournament completions and start clean under the new
  edition model. No archive/back-fill of completed cycles (no meaningful history to preserve).
- **D-15:** Wiping `tournaments.completions` orphans the `core.completions.tournament_completion_id` FK
  on cross-written rows. **Null the FK but KEEP the core times** — they are legitimate PBs on the MAIN
  (non-tournament) leaderboard; players only lose the "set during Tournament X" badge link.
  **Do NOT cascade-delete `core.completions` rows.**

### Claude's Discretion (defer to research/planning)
- Exact new table/column names (`tournaments.editions` vs other naming; where global cadence/anchor/
  pause/debug config lives — new columns on `tournaments.config` vs a singleton settings row).
- Exact migration file number(s) (next sequential after 0023) and whether the wipe + schema change +
  pg_cron re-registration live in one migration or several.
- Exact name/shape of the combined `TournamentRolloverEvent` SDK struct, its routing key, and the new
  outbox `event_type` value (`edition_rollover` is illustrative).
- How the transition function computes "is the boundary reached" against the grid anchor + timezone
  (DST handling, `make_interval` vs date arithmetic) and how it derives the exact `started_at`/`ends_at`
  grid values to store.
- Whether per-category leaderboards, champion-role transfers, XP/reward grants, and streaks attach to
  the edition or stay per child cycle (they are downstream of the edition entity — preserve current
  behavior, re-wire to the new parent).
- Fate of existing per-cycle API endpoints (`GET /cycles`, `/cycles/{id}/leaderboard`,
  `/cycles/{id}/submit`, `next-cycle`, etc.) under the edition model — keep, alias, or reshape; and
  corresponding frontend-spec updates.
- Handling of existing Discord champion-role holders at the fresh-restart cutover (likely retained until
  the first new rollover strips/grants — planner to confirm).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Specs (untracked — frontend/leaderboard contracts that the edition reshape affects)
- `docs/specs/tournament-frontend-spec.md` — API/response shapes the frontend consumes; §3 (cycle
  shapes with `started_at`/`ended_at`), §6 (polling for transitions), §8 (notes the missing `ends_at`
  field — relevant since timing moves to the edition).
- `docs/specs/tournament-leaderboard.md` — leaderboard + cross-write model; the
  `core.completions.tournament_completion_id` FK relationship (relevant to D-15).

### The machinery being overhauled (read first)
- `apps/api/migrations/0020_tournaments.sql` — `tournaments.cycles` (cols: `category_id`, `map_id`,
  `status` CHECK pending/active/finalizing/completed, `started_at`, `ended_at`, `created_at`),
  `tournaments.categories` (`cycle_frequency`, reward config, `champion_role_id`),
  `tournaments.pending_transitions` (outbox; `event_type` CHECK `cycle_started`/`cycle_completed`).
- `apps/api/migrations/0021_tournament_cycle_transitions.sql` — `process_cycle_transitions()` (~96-264):
  due-cycle detection `now() >= started_at + interval`; sets new `started_at = now()` (~201) — **the
  drift source**; cron registered `* * * * *` (~281).
- `apps/api/migrations/0023` (cycle pause + debug-length) — adds per-category `transitions_paused` +
  `debug_cycle_seconds`; updates the transition function to honor them. These columns go **global** (D-03).

### Code to extend / re-wire
- `apps/api/services/tournament_service.py` — `bootstrap_cycle()` (~341-432, sets `started_at = now()`),
  `set_transitions_paused()` (~434-457), `set_debug_cycle_length()` (~459-485).
- `apps/api/repository/tournaments_repository.py` — `create_active_cycle()` (~443-478),
  pause/debug setters (~312-372), eligible-map selection, `fetch_leaderboard()`.
- `apps/api/services/tournament_outbox_service.py` — `publish_pending_transitions()` (~120-216), groups
  by `(event_type, created_at)` (~188), routing keys (~56-59), reward side-effects (~181-184). This is
  where the single combined `edition_rollover` event is produced (D-11).
- `apps/api/app.py` — `tournament_outbox_poller()` (~72-107, ~10s cadence).
- `apps/bot/extensions/tournaments.py` — `_on_cycle_started` (~298-337) + `_on_cycle_completed`
  (~339-410) + `_transfer_champion_role` (~475-547). The two handlers collapse into one combined-message
  handler (D-09/D-10).
- `libs/sdk/src/genjishimada_sdk/tournaments.py` — cycle structs + events
  (`TournamentCycleStartedEvent` ~431, `TournamentCycleCompletedEvent` ~453,
  `TournamentCyclesStartedEvent` ~469, `TournamentCyclesCompletedEvent` ~484, lifecycle structs ~177-213).
  New `TournamentRolloverEvent` + edition structs go here.

### Prior phase context (decisions this phase changes / depends on)
- `.planning/phases/07-automatic-cycle-transitions/07-CONTEXT.md` — D-04 (no stored end column; computed
  inline) and D-05 (`started_at = now()` on promote) are exactly what D-08 reverses; outbox/bridge/
  advisory-lock patterns to preserve.
- `.planning/phases/11-tournament-verification-flow/11-CONTEXT.md` — verification flow + cross-write
  invariants (D-15 must not break "latest = fastest" in `core.completions`).

### Project planning
- `.planning/PROJECT.md` — Constraints (no ORM, bot never writes DB, pg_cron scheduler, existing stack
  only) + the per-category-frequency requirement being amended.
- `CLAUDE.md` — Tournament System constraints + DB exception-handling / pg_cron migration patterns.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `migrations/0013_coin_store.sql` `store.check_and_rotate()` — the canonical pg_cron + advisory-lock +
  idempotent `cron.unschedule`/`cron.schedule` pattern the transition function already follows; reused.
- Outbox → RabbitMQ bridge (`tournament_outbox_service.publish_pending_transitions` + the `app.py`
  poller lifespan) — keep the mechanism; change what rows it produces/publishes (one combined event).
- Bot already builds **one combined LayoutView card per event-type** from a per-category list
  (`TournamentCyclesStarted/CompletedEvent`) — the combined-rollover card extends this, just fusing
  results + start into one card with conditional sections.

### Established Patterns
- Cycle status is a forward-only CHECK enum (`pending → active → finalizing → completed`).
- jsonb outbox payloads round-trip through msgspec via `_async_pg_init` codecs.
- Transition work lives in PL/pgSQL invoked by pg_cron (DB owns scheduled timing; API doesn't drive it).
- Tournament config (blacklist_weeks) already lives in a `tournaments.config` table — natural home for
  global cadence/anchor/pause/debug.

### Integration Points
- New migration (next after 0023): edition entity + global config columns + transition-function rewrite
  (grid-anchored, status-only flip) + combined-event outbox + fresh-restart wipe + null the core FK +
  pg_cron re-registration.
- SDK: new edition structs + `TournamentRolloverEvent`; revise cycle event structs.
- API routes/service/repo: edition-aware reads; reshaped cycle endpoints (planner's call per Discretion).
- Bot: one combined-rollover handler replacing the started/completed pair; champion-role transfer folds
  into it.

</code_context>

<specifics>
## Specific Ideas

- "Treat all tournament categories as one unit (a single tournament spanning every category)" — the
  guiding mental model for D-01/D-05.
- "Tournament start and end become one shared event with a single grid-anchored time for all
  categories" — D-06/D-08/D-09.
- "Pause should pause the next cycle from starting, not ending — so we can have a hiatus of tournaments
  if necessary" — D-12 (direct user quote, drove the pause-semantics correction).

</specifics>

<deferred>
## Deferred Ideas

- **Preserve historical completed cycles / past-champions archive across the migration** — explicitly
  declined now (D-14, fresh restart wipes). Revisit if/when a real production tournament with standings
  exists before a future schema change.
- **Per-edition vs per-category leaderboard surfacing / reshaped public API + frontend-spec rewrite** —
  acknowledged as downstream of the edition entity; left to planner discretion, may warrant its own
  follow-up if the frontend contract changes substantially.

None of these block Phase 12 — discussion stayed within the timing-overhaul scope.

</deferred>

---

*Phase: 12-overhaul-of-tournaments*
*Context gathered: 2026-06-01*
