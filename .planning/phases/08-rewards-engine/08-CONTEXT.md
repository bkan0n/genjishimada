# Phase 8: Rewards Engine — CONTEXT

**Created:** 2026-05-30
**Mode:** `--auto` (decisions auto-selected; recommended option chosen per gray area)
**Requirements:** RWD-01, RWD-02, RWD-04, RWD-05

## Domain

This phase delivers the **rewards layer** of the tournament system: it grants XP for
participation and placement, and tracks weekly participation streaks that unlock bonus XP
at admin-configured thresholds. It is pure backend business logic on the existing
Litestar API — no new bot work (that is Phase 9), no new frameworks. All XP is delivered
through the **existing `api.xp.grant` RabbitMQ pipeline**; the bot remains a consumer.

**What "done" looks like (from ROADMAP success criteria):**
1. A player receives a flat participation XP bonus on their **first submission in a cycle**
   (once per cycle, not per submission).
2. At cycle end, **placement-based XP** is calculated from admin-configured tier/amount
   pairs and published to `api.xp.grant`.
3. A player's **participation streak** increments when they submit in ≥1 category per
   cycle, and **resets to zero** if they miss a cycle.
4. **Streak-based XP bonuses** are granted when a streak reaches an admin-configured
   threshold.

## Carrying Forward from Earlier Phases

- **Phase 7 already built** the cycle-transition machinery: a SQL transition function
  (`tournaments.process_cycle_transitions`, pg_cron) that finalizes a cycle, **snapshots
  placements as JSON in the `tournaments.pending_transitions` outbox payload** (the
  `cycle_completed` row), and an **API outbox poller** (`apps/api/services/tournament_outbox_service.py`)
  that publishes `TournamentCycleStartedEvent` / `TournamentCycleCompletedEvent` from
  unpublished outbox rows via `FOR UPDATE SKIP LOCKED` + at-least-once. Placement XP and
  streak updates are cycle-end concerns and must hook into THIS finalization/outbox flow —
  not a second scheduler. The `cycle_completed` payload already carries final placements,
  so reward computation can read placements from the event rather than recomputing.
- **Phase 6 already built** the submission flow (`TournamentService` submit path +
  `cross_write_to_core`). Participation XP is a submission-time concern and hooks into
  THIS submit path.
- **Phase 1 schema** already provisioned reward state + config (confirmed in
  `0020_tournaments.sql`):
  - `tournaments.streaks` — `user_id` (unique), `current_streak`, `max_streak`,
    `last_cycle_id`. Reward STATE lives here.
  - **Reward CONFIG is per-category jsonb on `tournaments.categories`:**
    `placement_xp` = `[{place, xp}]`, `streak_xp` = `[{threshold, xp}]`. There is **no**
    separate `xp_config` table — admins already edit these via the Phase-4 category
    CRUD endpoints. This phase reads them; it does not invent a config surface.
- **SDK already anticipates tournament rewards** (`libs/sdk/.../tournaments.py`):
  `TournamentXpGrantEvent` (first-class reward event), `PlacementXpTier`, `StreakXpTier`,
  `TournamentStreakResponse`. Phase 2 pre-defined these — reuse them, don't redefine.
- **Architecture invariants (locked, do not revisit):** no ORM (raw asyncpg);
  single-writer (only the API writes Postgres; bot never writes); all async XP via
  `api.xp.grant`; `BaseService.publish_message()` is the only publish path.

## Decisions (auto-selected)

### A. Participation XP — trigger point & once-per-cycle guarantee
- `[auto] Participation XP — Q: "Where is participation XP awarded?" → Selected: "Inside the existing submission service path (TournamentService submit), detecting the player's first submission for the cycle" (recommended)`
- `[auto] Participation XP — Q: "How is once-per-cycle enforced?" → Selected: "DB-state guard: award only when no prior completion exists for (user, cycle)" (recommended)`
- **Decision:** Participation XP is granted within the submit flow, gated on "this is the
  player's first completion in this cycle." The DB state (existing `tournaments.completions`
  for the cycle) is the source of truth for the once-per-cycle guarantee — not queue
  idempotency. Amount comes from tournament config (participation XP — confirm whether it
  lives on `tournaments.config` singleton or `tournaments.categories`; see open questions).

### B. Placement XP — computation locus & timing
- `[auto] Placement XP — Q: "Where/when is placement XP computed?" → Selected: "At cycle finalization, in the API service that processes the Phase-7 cycle_completed outbox event, mapping the snapshotted placements to tournaments.categories.placement_xp tiers" (recommended)`
- `[auto] Placement XP — Q: "SQL or Python for tier→amount mapping?" → Selected: "Python (API service) reading placements from the cycle_completed payload" (recommended)`
- **Decision:** Phase-7 already snapshots placements into the `cycle_completed` outbox
  payload. **Phase 8 maps each placement to a `categories.placement_xp` tier in Python**
  and publishes one `TournamentXpGrantEvent` (→ `api.xp.grant`) per placed player. Hook
  into the cycle-end / outbox flow rather than adding a new trigger.

### C. Streak tracking — update timing & data source
- `[auto] Streaks — Q: "When are streaks updated?" → Selected: "At cycle-end finalization, per player" (recommended)`
- `[auto] Streaks — Q: "What counts as participation for the streak?" → Selected: "Submitting in ≥1 category during the just-ended cycle (RWD-04)" (recommended)`
- **Decision:** At finalization, for the just-ended cycle: **increment** `current_streak`
  (and bump `max_streak`) for every player who submitted in ≥1 category that cycle;
  **reset to 0** every tracked player who did not. Set `last_cycle_id`. Computed from
  `tournaments.completions`, written to `tournaments.streaks`.

### D. Streak bonus — threshold config & grant
- `[auto] Streak bonus — Q: "Where are streak thresholds/amounts configured?" → Selected: "tournaments.categories.streak_xp jsonb ([{threshold, xp}])" (recommended)`
- `[auto] Streak bonus — Q: "When is the bonus granted?" → Selected: "In the same finalization step, immediately after the streak increments and crosses a configured threshold" (recommended)`
- **Decision:** Streak thresholds + amounts come from `categories.streak_xp`. When an
  incremented streak reaches a configured threshold, publish a streak-bonus
  `TournamentXpGrantEvent` in the same finalization step. (Confirm whether streaks are
  global-per-user or per-category — the streaks table is keyed by `user_id` only, but
  `streak_xp` config is per-category; see open questions.)

### E. Double-grant prevention (at-least-once delivery)
- `[auto] Idempotency — Q: "How do we avoid double-granting XP on retry?" → Selected: "Dedupe at the source via DB-recorded award state / deterministic cycle-scoped keys, consistent with Phase-7 outbox at-least-once semantics — NOT queue idempotency (api.xp.grant is non-idempotent / in IGNORE_IDEMPOTENCY)" (recommended)`
- **Decision:** `api.xp.grant` is in `IGNORE_IDEMPOTENCY` (confirmed `base.py:34`), so
  reward grants must be made safe by **DB-recorded award state**: participation tied to
  first-completion existence; placement/streak grants guarded per (cycle, user) so a
  re-run of finalization or an outbox replay cannot double-pay. Use deterministic
  `idempotency_key`s of the form `tournament:{reason}:{cycle_id}:{user_id}` as a second
  line of defense. **Research must determine where the "already-granted" marker lives** —
  likely a new `granted` boolean/timestamp column or a small grants-ledger table (thin
  additive migration `0022`).

### F. Reward payload shape
- `[auto] Payload — Q: "New event struct or reuse?" → Selected: "Reuse the existing TournamentXpGrantEvent struct already defined in the SDK" (recommended)`
- **Decision:** Publish the existing `TournamentXpGrantEvent` (already in
  `libs/sdk/.../tournaments.py`) to `api.xp.grant`. Confirm its fields cover
  user id, amount, reason/source (participation | placement | streak), and `cycle_id`;
  extend minimally only if a field is missing. (Note: existing non-tournament XP grants
  use `genjishimada_sdk.xp.XpGrantEvent`/`XpGrantRequest` — research must confirm the bot
  XP consumer accepts the tournament event struct on `api.xp.grant`, or whether the
  tournament service should emit the generic `xp.XpGrantEvent` instead. This is the single
  most important contract question for the phase.)

## Canonical Refs (MUST read before planning)

- `.planning/ROADMAP.md` — Phase 8 goal + 4 success criteria (authoritative scope).
- `.planning/REQUIREMENTS.md` — RWD-01, RWD-02, RWD-04, RWD-05 (RWD-03 champion role is
  Phase 9, OUT of scope here).
- `apps/api/migrations/0020_tournaments.sql` — `tournaments.streaks`
  (`current_streak`/`max_streak`/`last_cycle_id`, unique on `user_id`), and
  `tournaments.categories.placement_xp` / `streak_xp` jsonb config. Confirm columns; scope
  thin additive migration `0022` only if a grant-ledger / `granted` marker is needed (E).
- `apps/api/migrations/0021_tournament_cycle_transitions.sql` — Phase-7 transition +
  `pending_transitions` outbox; `cycle_completed` payload carries the placement snapshot
  Phase 8 reads.
- `libs/sdk/src/genjishimada_sdk/tournaments.py` — `TournamentXpGrantEvent`,
  `PlacementXpTier`, `StreakXpTier`, `TournamentStreakResponse`,
  `TournamentCycleCompletedEvent` (reuse these; extend minimally if needed).
- `libs/sdk/src/genjishimada_sdk/xp.py` — generic `XpGrantEvent` / `XpGrantRequest` used
  by existing XP grants (maps/store/lootbox). Determines whether tournament rewards reuse
  this or the tournament-specific event.
- `apps/api/services/base.py` — `BaseService.publish_message()`; `IGNORE_IDEMPOTENCY` set
  (line 34 includes `api.xp.grant`) → drives Decision E.
- `apps/api/services/lootbox_service.py:377-412` — **reference implementation** of building
  an `XpGrantEvent` and publishing to `api.xp.grant`. Closest analog for the reward publish.
- `apps/api/services/tournament_service.py` — `TournamentService`; submit path is the
  participation-XP hook.
- `apps/api/services/tournament_outbox_service.py` — Phase-7 outbox poller; the
  placement/streak finalization rewards integrate here (or in a sibling reward step driven
  by `cycle_completed`).
- `apps/api/repository/tournaments_repository.py` — `TournamentRepository`; add
  streak read/update + per-cycle participation queries + any grant-ledger access.
- `apps/api/services/exceptions/tournaments.py` — domain exceptions; add reward-specific
  errors here if needed.
- `.planning/codebase/INTEGRATIONS.md`, `.planning/codebase/CONVENTIONS.md` — DI/service
  patterns, queue conventions (`api.xp.grant` non-idempotent), logging/error conventions.
- Prior context: `.planning/phases/07-automatic-cycle-transitions/07-CONTEXT.md`,
  `.planning/phases/06-submission-flow-leaderboard/06-CONTEXT.md`.

## Code Context (reusable assets & patterns)

- **XP delivery:** existing `api.xp.grant` queue + `BaseService.publish_message()`; copy
  the `lootbox_service.py` build-event-and-publish pattern.
- **Finalization hook:** Phase-7 transition (SQL) + `pending_transitions` outbox +
  `tournament_outbox_service.py` poller — placement/streak rewards attach here; placements
  are already in the `cycle_completed` payload.
- **Submission hook:** Phase-6 `TournamentService` submit — participation XP attaches here.
- **Config surface:** `tournaments.categories.placement_xp` / `streak_xp` (per-category
  jsonb), already admin-editable via Phase-4 category endpoints. Reward amounts are config,
  not constants.
- **Reward state:** `tournaments.streaks` (one row per user).
- **Patterns to follow:** repository `self._get_connection(conn)` + positional `$N`;
  service raises domain exceptions; CTE-based atomic multi-table writes; `%s`-style logging
  with `[→]/[✓]/[x]/[!]` markers; msgspec structs for events.

## Open Questions for Research (verify before/while planning)

1. **XP event contract (highest priority):** does the bot XP consumer on `api.xp.grant`
   accept `TournamentXpGrantEvent`, or must tournament rewards emit the generic
   `xp.XpGrantEvent`/`XpGrantRequest`? Confirm the consumer side (Phase 9 bot is not built,
   but the `api.xp.grant` contract is owned by the existing XP system).
2. **Participation XP amount source:** is the flat participation amount on the
   `tournaments.config` singleton or on `tournaments.categories`? (placement/streak configs
   are per-category; participation may be global.)
3. **Streak scope:** `tournaments.streaks` is keyed by `user_id` only (global per user), but
   `streak_xp` config is per-category. Resolve: is the streak global (any-category
   participation) with per-category bonus amounts, or should streaks be per-category?
   RWD-04 says "submitting in any category" → global streak; confirm bonus-amount source.
4. **Double-grant marker (E):** where does the "already granted" state live — a new column
   on `streaks`/`completions`, or a new grants-ledger table? Scope migration `0022` if so.
5. **Placement→amount edge cases:** ties in placement, places beyond the configured tiers
   (no XP), and zero-participant cycles.

## Deferred Ideas (not this phase)

- Discord champion role transfer (RWD-03) → Phase 9.
- Cycle results / XP-awarded announcements → Phase 9.
- "Set during Tournament X" badge metadata (ENG-01) → v2.
- Personal streak/stats slash command (ADM/DSC) → Phase 10.
