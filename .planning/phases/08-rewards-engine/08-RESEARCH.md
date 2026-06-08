# Phase 8: Rewards Engine - Research

**Researched:** 2026-05-30
**Domain:** Brownfield backend business logic — XP rewards (participation/placement/streak) on the existing Litestar + asyncpg + RabbitMQ tournament machinery (Phases 1-7)
**Confidence:** HIGH (all 5 open questions resolved by direct codebase inspection; no external libraries involved)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **A. Participation XP** — granted within the submit flow (`TournamentService.submit_completion`), gated on "this is the player's first completion in this cycle." DB state in `tournaments.completions` is the source of truth for once-per-cycle, NOT queue idempotency. Amount comes from tournament config.
- **B. Placement XP** — computed at cycle finalization, in the API service that processes the Phase-7 `cycle_completed` outbox event, mapping snapshotted placements to `tournaments.categories.placement_xp` tiers in **Python** (read placements from the `cycle_completed` payload — do not recompute).
- **C. Streak tracking** — updated at cycle-end finalization, per player. Increment `current_streak` (+bump `max_streak`) for every player who submitted in ≥1 category that cycle; reset to 0 for every tracked player who did not. Set `last_cycle_id`. Computed from `tournaments.completions`, written to `tournaments.streaks`.
- **D. Streak bonus** — thresholds + amounts come from `categories.streak_xp`. When an incremented streak reaches a configured threshold, publish a streak-bonus grant in the same finalization step.
- **E. Double-grant prevention** — `api.xp.grant` is in `IGNORE_IDEMPOTENCY`, so reward grants must be made safe by **DB-recorded award state**: participation tied to first-completion existence; placement/streak grants guarded per `(cycle, user)` so a finalization re-run or outbox replay cannot double-pay. Use deterministic keys of form `tournament:{reason}:{cycle_id}:{user_id}` as a second line of defense.
- **F. Reward payload shape** — reuse the SDK reward event already defined. Confirm fields and whether the bot XP consumer accepts the tournament event or the generic `xp.XpGrantEvent`. (RESOLVED below — see Open Question 1: the generic path is the only consumable one.)
- **Architecture invariants (locked, do not revisit):** no ORM (raw asyncpg); single-writer (only API writes Postgres; bot never writes); all async XP via `api.xp.grant`; `BaseService.publish_message()` is the only publish path.

### Claude's Discretion
- Exact shape of the double-grant marker (new column vs. new ledger table) — see Open Question 4; this research recommends a grants-ledger table (migration `0022`).
- Whether to add a tournament-specific `XP_TYPES` literal member vs. reuse `"Other"` — see Open Question 1/6.
- Internal structure of the new reward service / reward repository methods.

### Deferred Ideas (OUT OF SCOPE)
- Discord champion role transfer (RWD-03) → Phase 9.
- Cycle results / XP-awarded announcements → Phase 9.
- "Set during Tournament X" badge metadata (ENG-01) → v2.
- Personal streak/stats slash command → Phase 10.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| RWD-01 | Flat participation XP on first submission per cycle (once per cycle) | Hook in `TournamentService.submit_completion` `existing is None` branch (line 506); amount from `categories.participation_xp` (Q2); grant via existing XP mechanism (Q1) |
| RWD-02 | Placement XP at cycle end from admin-configured tier/amount pairs | Read placements from `TournamentCycleCompletedEvent.standings` in the outbox flow (Q5); map `rank → categories.placement_xp[].place` in Python (Decision B) |
| RWD-04 | Participation streak increments per cycle; resets to 0 on a missed cycle | Cycle-end recompute from `tournaments.completions`; global per-user streak (Q3); needs a NEW reset-capable repo method (existing `upsert_streak` only increments) |
| RWD-05 | Streak bonus XP at admin-configured thresholds | `categories.streak_xp` thresholds; granted in same finalization step (Decision D); per-category bonus amount source resolved in Q3 |

*RWD-03 (champion role) is Phase 9 — OUT of scope.*
</phase_requirements>

## Summary

Every open question is answered by direct inspection of the existing codebase — **no external research or new libraries are required** (the phase is pure brownfield business logic, consistent with the "no new frameworks" constraint).

The single most important finding (**Open Question 1**) overturns the CONTEXT's tentative Decision F. The `api.xp.grant` queue is **already owned and consumed** by `apps/bot/extensions/xp.py:106`, whose handler `_process_xp_grant` decodes the **generic `genjishimada_sdk.xp.XpGrantEvent`** and *requires* the fields `type`, `previous_amount`, and `new_amount`. The SDK's `TournamentXpGrantEvent` has **none** of those fields. Critically, `previous_amount`/`new_amount` are produced by the **API-side DB mutation** (`lootbox.xp` upsert via `LootboxRepository.upsert_user_xp`) inside `LootboxService.grant_user_xp` — the event is a *post-write notification*, not a *request to grant*. Therefore tournament rewards must **route through the existing XP grant mechanism** (which performs the `lootbox.xp` write and emits a correctly-shaped `XpGrantEvent`), **not** publish `TournamentXpGrantEvent`. The `TournamentXpGrantEvent` struct currently has **zero producers and zero consumers** and should be treated as a not-yet-wired stub, not a contract.

The remaining questions resolve cleanly: participation XP amount lives **per-category** on `tournaments.categories.participation_xp` (Q2, `int NOT NULL DEFAULT 0`, line 38 of `0020`); streaks are **global per user** with the per-category `streak_xp` bonus read from the just-completed cycle's category (Q3); a thin additive migration **`0022`** introducing a **grants-ledger table** is the cleanest double-grant marker (Q4); and placement edge cases (RANK() ties, places beyond configured tiers, zero-participant cycles) are all handled in the Python mapping reading `standings` from the `cycle_completed` payload (Q5).

**Primary recommendation:** Build a new `TournamentRewardService` (extending `BaseService`) plus a small set of reward repository methods and a `0022` grants-ledger migration. Participation XP hooks into `submit_completion`'s first-completion branch; placement + streak rewards hook into the outbox flow driven by `cycle_completed`. All XP is delivered by reusing the existing `lootbox.xp` upsert + `XpGrantEvent` publish pattern (extract a shared helper or call `LootboxService.grant_user_xp`), guarded by the grants ledger for at-least-once safety.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Detect first completion in cycle | API service (`TournamentService.submit_completion`) | API repo (`fetch_user_completion`) | Submission-time concern; transaction already open here (line 491) |
| Award participation XP | API service (new `TournamentRewardService`) | XP delivery mechanism (`lootbox.xp` write + `XpGrantEvent`) | XP mutation is single-writer API-side; bot only consumes the resulting event |
| Compute placements | Already done (Phase-7 SQL) | — | `process_cycle_transitions` snapshots `standings` JSON into the `cycle_completed` outbox payload (`0021` lines 137-190). Phase 8 READS, never recomputes |
| Map placement → XP amount | API service (Python) | `categories.placement_xp` jsonb | Decision B; reading the event payload, not the DB ranking |
| Update streaks (increment/reset) | API service (cycle-end) | API repo (NEW reset-capable method) | Decision C; existing `upsert_streak` only increments — insufficient for reset semantics |
| Grant streak bonus XP | API service | `categories.streak_xp` jsonb | Decision D |
| Double-grant prevention | API DB state (NEW grants ledger) | deterministic idempotency keys | `api.xp.grant` is non-idempotent (Decision E) |
| Deliver XP to user / Discord roles | Bot consumer (EXISTS) | — | `apps/bot/extensions/xp.py` — Phase 9 owns no new work here; the existing consumer already does notifications + rank-up |

## Standard Stack

No new packages. The phase uses only what is already in the monorepo.

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| asyncpg (via litestar-asyncpg) | `>=0.4.0` | Raw SQL data access | Project mandates raw SQL, no ORM `[CITED: CLAUDE.md]` |
| msgspec | `>=0.19.0` | Event/struct serialization | Shared SDK contract `[CITED: CLAUDE.md]` |
| aio-pika (via `BaseService.publish_message`) | `>=9.5.5` | RabbitMQ publishing | Only sanctioned publish path `[VERIFIED: apps/api/services/base.py:56]` |

**Installation:** None required.

## Package Legitimacy Audit

Not applicable — this phase installs **no external packages**. All work uses existing in-repo modules and the already-pinned dependency set. (Slopcheck/registry verification skipped: zero new dependencies.)

---

## OPEN QUESTION RESOLUTIONS (the core of this research)

### Q1 — XP event contract (HIGHEST PRIORITY) — RESOLVED

**Finding: Tournament rewards MUST route through the existing XP grant mechanism that writes `lootbox.xp` and emits the generic `genjishimada_sdk.xp.XpGrantEvent`. They must NOT publish `TournamentXpGrantEvent`.** `[VERIFIED: apps/bot/extensions/xp.py:106-131, apps/api/services/lootbox_service.py:373-417]`

Field-by-field comparison:

| Field | `xp.XpGrantEvent` (the live contract) | `tournaments.TournamentXpGrantEvent` (unused stub) |
|-------|---------------------------------------|----------------------------------------------------|
| `user_id` | ✅ int | ✅ int |
| `amount` | ✅ int | ✅ int |
| `type` | ✅ `XP_TYPES` Literal (**consumer reads `event.type`**) | ❌ absent |
| `previous_amount` | ✅ int (**consumer passes to `get_xp_tier_change` for rank-up**) | ❌ absent |
| `new_amount` | ✅ int (**consumer passes to `get_xp_tier_change`**) | ❌ absent |
| `reason` | ✅ `str \| None` | — (`grant_reason: str` instead) |
| `cycle_id` | ❌ absent | ✅ int |
| `category_id` | ❌ absent | ✅ int |
| `grant_reason` | — | ✅ str |

Evidence chain:
1. The bot consumer is **already built and registered**: `@queue_consumer("api.xp.grant", struct_type=XpGrantEvent, idempotent=True)` `[VERIFIED: apps/bot/extensions/xp.py:106]`. It msgspec-decodes `XpGrantEvent`. A `TournamentXpGrantEvent` payload would **fail to decode** (missing required `type`/`previous_amount`/`new_amount`) or, worse, decode into a struct missing the fields the handler then dereferences (`event.previous_amount`, `event.new_amount`, `event.type` at lines 114-131).
2. The event is a **post-write notification, not a grant request**. `LootboxService.grant_user_xp` (`lootbox_service.py:373-417`) does the actual mutation first: `fetch_xp_multiplier()` → `upsert_user_xp()` (writes `lootbox.xp`, returns `previous_amount`/`new_amount`) → then builds `XpGrantEvent(... previous_amount=..., new_amount=...)` and publishes. The `previous_amount`/`new_amount` exist *because* the DB write already happened.
3. `TournamentXpGrantEvent` has **zero producers and zero consumers** anywhere in `apps/` (the only `api.xp.grant` references are `base.py:34`, `lootbox_service.py:412`, and `bot/extensions/xp.py:106` — none use the tournament struct). It is a Phase-2 stub that was never wired.
4. `_EVENT_ROUTING` in the outbox service maps tournament events to `api.tournament.cycle_started` / `api.tournament.cycle_completed` routing keys — **not** `api.xp.grant` `[VERIFIED: tournament_outbox_service.py:34-37]`. XP is a separate queue with a separate, existing owner.

**Recommended approach for the planner:**
- Tournament reward grants call the existing XP grant logic. Two concrete options:
  - **(Preferred) Extract a shared internal helper** from `LootboxService.grant_user_xp` (e.g., a `grant_xp(user_id, amount, type, reason, headers, *, conn=None)` on a shared base or a small `XpGrantService`) that does `upsert_user_xp` + publish `XpGrantEvent`, and call it from `TournamentRewardService`. This keeps the single-writer + correct-event-shape invariants and avoids duplicating the multiplier/upsert logic.
  - **(Acceptable) Call `LootboxService.grant_user_xp` directly** from the reward service via DI. Note its current signature is `grant_user_xp(headers, user_id, data: XpGrantRequest) -> XpGrantResponse` and it does **not** accept a `conn` — see the atomicity caveat in Q4.
- **`XP_TYPES` does NOT include a tournament member** (`Literal["Map Submission","Playtest","Guide","Completion","Record","World Record","Quest","Other"]`, `xp.py:17`). The `type` field is a constrained Literal, so a tournament grant must either use `type="Other"` with a descriptive `reason` (e.g., `"Tournament Participation"`, `"Tournament Placement #1"`, `"Tournament Streak x5"`), or the planner adds a new `XP_TYPES` member (e.g., `"Tournament"`) in the SDK. **Recommendation:** add a `"Tournament"` member to `XP_TYPES` (and a `XP_AMOUNTS` entry is NOT needed — tournament amounts are config-driven, not from the `XP_AMOUNTS` table) so XP-source analytics can distinguish tournament XP. This is a one-line SDK change; flag it for the planner. `[VERIFIED: libs/sdk/src/genjishimada_sdk/xp.py:17]`

**Disposition of `TournamentXpGrantEvent`:** leave it in the SDK (harmless), but **do not publish it** this phase. It can be removed or repurposed in a later cleanup; planning should not depend on a consumer existing for it. `[ASSUMED — recommendation, not a hard requirement]`

### Q2 — Participation XP amount source — RESOLVED

**Finding: Participation XP is PER-CATEGORY on `tournaments.categories.participation_xp`. It is NOT on the `tournaments.config` singleton.** `[VERIFIED: apps/api/migrations/0020_tournaments.sql:38]`

- `tournaments.categories.participation_xp int NOT NULL DEFAULT 0` (line 38). Comment: "Flat XP bonus for first submission per cycle" (line 50).
- `tournaments.config` (singleton, lines 16-22) has **only** `blacklist_weeks` + timestamps — **no XP fields at all**. Confirmed against `TournamentConfigResponse` (`tournaments.py:67-79`) which exposes only `blacklist_weeks`.
- The amount is admin-editable via the Phase-4 category CRUD (`participation_xp` is in both `TournamentCategoryCreateRequest` and `TournamentCategoryPatchRequest`, and `TournamentService.update_category` handles it at `tournament_service.py:176-177`).

**Implication for the participation hook:** in `submit_completion`, the cycle row is already fetched (`cycle["category_id"]`). The reward service fetches the category (`fetch_category(category_id)`) to read `participation_xp`. If `participation_xp == 0`, skip the grant (no-op).

### Q3 — Streak scope — RESOLVED

**Finding: Streaks are GLOBAL per user (one row per `user_id`). The per-category `streak_xp` bonus amount is read from the category of the cycle being finalized.** `[VERIFIED: 0020_tournaments.sql:118-128; RWD-04 wording]`

- `tournaments.streaks` has a `UNIQUE INDEX ON (user_id)` (line 128) — one streak per user, **no `category_id` column**. Schema comment: "Per-user weekly participation streak tracking" (line 130). It physically cannot be per-category without a migration, and CONTEXT Decision C/E and RWD-04 ("submitting in any category") both point to global.
- **Bonus-amount source:** `streak_xp` is per-category jsonb (`categories.streak_xp`, line 40). The resolution: streak *count* is global, but the bonus *amount* for a threshold crossing is read from the `streak_xp` config of **the category whose cycle is currently finalizing**. Because finalization runs per due cycle (the outbox emits one `cycle_completed` per category-cycle), each finalization naturally has a single `category_id` in scope (`TournamentCycleCompletedEvent.category_id`). Read that category's `streak_xp` tiers and check whether the user's new global streak value matches a configured `threshold`.

**Edge case the planner must decide (flag as a design choice):** with a global streak and per-category thresholds, if a user participates in 2 categories in the same cycle, do we increment the streak **once per cycle-window** or once per category finalization? The streak is "consecutive cycles with ≥1 submission" (RWD-04 / Decision C). **Recommendation:** increment the global streak **once per cycle window**, keyed on a distinct cycle-window concept — but since each category has independent cycles, the simplest correct model is: at each `cycle_completed` finalization, for that category's just-ended cycle, recompute streaks for that cycle's participants. To avoid double-incrementing a user who plays multiple simultaneous categories, the **grants ledger / `last_cycle_id` guard** must dedupe the streak update per `(user, cycle_window)`. The cleanest dedupe is the existing `tournaments.streaks.last_cycle_id` column combined with the grants ledger (Q4): only increment if this finalization's cycle is "newer" than `last_cycle_id`. **This is the trickiest correctness point in the phase — call it out explicitly in the plan and cover it with a test.** `[ASSUMED — model recommendation; needs a locked decision before/while planning]`

### Q4 — Double-grant marker — RESOLVED (recommend new ledger table, migration 0022)

**Finding: Add a thin additive migration `0022` introducing a tournament grants-ledger table. This is cleaner than per-grant boolean columns and naturally extends to participation, placement, and streak grants.** `[VERIFIED: no existing ledger — migrations 0001-0021 contain none; grep found nothing]`

Why a ledger over columns:
- There are **three** distinct grant reasons (participation, placement, streak), each scoped to `(cycle_id, user_id)` (and the reason). A single boolean column cannot represent "participation granted but placement not yet." A ledger row per `(cycle_id, user_id, reason)` with a `UNIQUE` constraint is the natural at-least-once guard.
- The outbox is at-least-once (`tournament_outbox_service.py` publishes-before-marks; a crash re-publishes — docstring lines 79-84). Finalization rewards driven by `cycle_completed` can therefore run **more than once** for the same cycle. The ledger's unique constraint makes the second run a no-op (`INSERT ... ON CONFLICT DO NOTHING` returning whether a row was inserted gates the grant).
- It also doubles as the data source for Phase 9 "XP awarded" announcements and a future audit trail.

**Recommended `0022` shape (additive, follows existing conventions):**
```sql
-- Migration 0022: Tournament reward grants ledger (double-grant prevention)
BEGIN;
CREATE TABLE IF NOT EXISTS tournaments.xp_grants (
    id          int         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cycle_id    int         NOT NULL REFERENCES tournaments.cycles(id) ON DELETE CASCADE,
    user_id     bigint      NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    reason      text        NOT NULL CHECK (reason IN ('participation', 'placement', 'streak')),
    amount      int         NOT NULL,
    granted_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (cycle_id, user_id, reason)   -- the at-least-once guard
);
CREATE INDEX IF NOT EXISTS idx_xp_grants_cycle ON tournaments.xp_grants (cycle_id);
CREATE INDEX IF NOT EXISTS idx_xp_grants_user ON tournaments.xp_grants (user_id);
COMMIT;
```
Note `user_id bigint` — `core.users.id` is a Discord snowflake; `0021` explicitly widened `v_winner` to `bigint` to avoid overflow (line 104). Match that.

**Grant pattern (planner reference):** before any XP grant, `INSERT INTO tournaments.xp_grants (cycle_id, user_id, reason, amount) VALUES (...) ON CONFLICT (cycle_id, user_id, reason) DO NOTHING RETURNING id`. Only if a row was returned (i.e., not previously granted) proceed to actually grant the XP. This makes the grant idempotent against outbox replay.

**Atomicity caveat (critical — flag for planner):** the ideal is to do the ledger insert + the `lootbox.xp` upsert in the **same transaction**, so a crash never leaves "ledger says granted but XP not written" (or vice versa). However:
- The participation hook runs inside `submit_completion`'s open transaction (`tournament_service.py:491`), but `LootboxService.grant_user_xp` does **not** accept a `conn` and acquires its own pool connection independently (`lootbox_service.py:389-395`) — so calling it from inside the submit transaction would NOT participate, breaking atomicity.
- **Recommendation:** the shared XP-grant helper extracted in Q1 should accept an optional `conn` (like every other repo/service method per `_get_connection` convention) so the ledger insert + `upsert_user_xp` run in one transaction. The RabbitMQ publish itself is best-effort/after-commit (publish failures already degrade gracefully in `publish_message`, returning a `failed` JobStatus rather than raising — `base.py:111-113`). For the finalization path, the outbox poller already runs inside a transaction (`tournament_outbox_service.py:93`), so reward grants there can share that connection too.
- The `idempotency_key` form `tournament:{reason}:{cycle_id}:{user_id}` is still set as the message `message_id` (second line of defense), but since `api.xp.grant` is in `IGNORE_IDEMPOTENCY` the **DB ledger is the real guard** — the key only helps any future idempotent consumer. `[VERIFIED: base.py:28-36, 101]`

### Q5 — Placement → amount edge cases — RESOLVED

**Finding: Placements arrive as a JSON `standings` array on `TournamentCycleCompletedEvent`, already ranked via SQL `RANK()` (ties produce equal ranks). All edge cases are handled in the Python mapping.** `[VERIFIED: 0021 lines 137-190; tournaments.py:425-438]`

Payload shape — `TournamentCycleCompletedEvent` (`tournaments.py:425-438`):
- `cycle_id: int`, `category_id: int`, `winner_user_id: int | None`, and `standings: list[TournamentLeaderboardEntryResponse]`.
- Each `TournamentLeaderboardEntryResponse` (`tournaments.py:282-299`): `rank, user_id, name, time, verified, completion`. The SQL builds these as `jsonb_build_object('rank', ..., 'user_id', ..., ...)` ordered by rank (`0021` lines 157-166).

Edge cases and required mapping behavior:
1. **Ties in placement.** The snapshot uses `RANK() OVER (ORDER BY verified DESC, time ASC)` (`0021` line 146). Ties (identical `verified` + `time`) produce the **same rank** and SKIP the next (1,1,3). The placement-XP mapping must therefore:
   - Match each standing's `rank` against `placement_xp[].place`. Two users with `rank=1` **both** receive the `place=1` reward. **Decide and document:** does rank 2 then go unfilled (gap), and does the second user get nothing if only `place=1,2,3` are configured but ranks are `1,1,3,...`? **Recommendation:** award strictly by matching `rank == place`; a tie means both tied users get that place's XP, and the skipped rank number simply has no recipient. This is the least surprising rule and falls naturally out of "map `rank` to the tier with the same `place`." Flag for confirmation.
2. **Places beyond configured tiers → no XP.** `placement_xp` is a sparse list of `{place, xp}` (e.g., only top 3). Any standing whose `rank` has no matching `place` entry receives **no placement XP** (skip). Build a `dict[place → xp]` from `placement_xp` and `.get(rank)`; `None` → skip. `[VERIFIED: PlacementXpTier struct tournaments.py:38-47]`
3. **Zero-participant cycles.** `standings` is `'[]'::jsonb` when no submissions (`COALESCE(..., '[]'::jsonb)`, `0021` line 167) and `winner_user_id` is `NULL` (`MIN(...) FILTER (WHERE rank = 1)` over an empty set, line 169). The mapping iterates an empty list → grants nothing. No special-casing needed beyond "iterate standings." Streak handling for an empty cycle: no participants to increment; the **reset** sweep (Decision C) still applies to previously-tracked users who didn't participate.
4. **Winner determination for role transfer is Phase 9** — `winner_user_id` is present in the payload but RWD-03 is out of scope here.

---

## Architecture Patterns

### System Architecture Diagram

```
                          PARTICIPATION XP (submission-time)
  HTTP POST submit ──> TournamentService.submit_completion (txn open, line 491)
                          │  fetch_cycle / fetch_user_completion
                          ▼
                    existing is None?  ──NO──> (not first completion this cycle) ─> skip reward
                          │ YES (first completion in cycle)
                          ▼
                    TournamentRewardService.award_participation(conn, cycle, user)
                          │  read categories.participation_xp (Q2)
                          │  ledger INSERT (cycle,user,'participation') ON CONFLICT DO NOTHING (Q4)
                          │  if newly inserted -> XP grant helper:
                          │       upsert lootbox.xp  +  publish XpGrantEvent -> api.xp.grant (Q1)
                          ▼
                    bot/extensions/xp.py _process_xp_grant (EXISTS) -> notify + rank-up

                          PLACEMENT + STREAK XP (cycle-end)
  pg_cron ─> tournaments.process_cycle_transitions() (0021)
                          │ snapshots standings JSON -> pending_transitions(cycle_completed)
                          ▼
  10s poller ─> publish_pending_transitions (outbox txn, FOR UPDATE SKIP LOCKED)
                          │ _build_event -> TournamentCycleCompletedEvent
                          │ publish -> api.tournament.cycle_completed
                          ▼  (NEW: same flow, sibling reward step driven by cycle_completed)
                    TournamentRewardService.award_cycle_end(conn, event)
                          │  PLACEMENT: for each standing, dict[place->xp].get(rank) (Q5)
                          │  STREAK:    recompute participants from completions;
                          │             increment global streak (reset-capable repo, Q3);
                          │             bonus if new streak == categories.streak_xp[].threshold
                          │  each guarded by ledger INSERT ON CONFLICT (Q4)
                          ▼
                    XP grant helper -> api.xp.grant (one event per grant) -> bot consumer
```

### Where to attach the cycle-end reward step (decision for planner)

The CONTEXT offers three loci; the inspection narrows it to two viable ones:

| Option | How | Tradeoff |
|--------|-----|----------|
| **(A) Inside the outbox publish step** — `publish_pending_transitions`, when `event_type == 'cycle_completed'`, also call `award_cycle_end(event, conn)` in the same transaction | Reuses the outbox txn + at-least-once; ledger dedupe makes replay safe | Couples reward logic to the publish loop; the loop currently publishes-then-marks, so reward grants must be inside the same txn and idempotent (they are, via ledger) |
| **(B) Sibling consumer of `api.tournament.cycle_completed`** — a separate API-side handler reacts to the published event | Cleaner separation | The API has **no RabbitMQ consumer infrastructure** — consumers live bot-side (`_queue_registry.py`). Building API-side consumption is net-new and contradicts "no new frameworks/patterns." **NOT recommended.** |

**Recommendation: Option A.** The placement/streak rewards run inside `publish_pending_transitions` (or a function it calls) when processing a `cycle_completed` row, sharing the existing outbox transaction and connection. This keeps everything API-side, single-writer, and replay-safe via the `0022` ledger. The reward grants' own `api.xp.grant` publishes are separate messages emitted within the same poll. `[VERIFIED: tournament_outbox_service.py:71-105; app.py:71-103]`

### Recommended new/changed files
```
apps/api/migrations/0022_tournament_xp_grants.sql   # NEW: grants ledger (Q4)
apps/api/services/tournament_reward_service.py       # NEW: TournamentRewardService(BaseService)
apps/api/repository/tournaments_repository.py        # EDIT: add reset-capable streak update,
                                                     #       participation-count query, ledger insert,
                                                     #       fetch cycle participants, fetch all streak user ids
apps/api/services/tournament_service.py              # EDIT: call reward service in submit first-completion branch
apps/api/routes/v3/tournaments.py                    # EDIT: wire reward service provider into DI dependencies
apps/api/services/tournament_outbox_service.py       # EDIT: invoke award_cycle_end on cycle_completed rows
apps/api/services/lootbox_service.py (or new xp svc) # EDIT: extract conn-accepting grant helper (Q1/Q4)
libs/sdk/src/genjishimada_sdk/xp.py                  # EDIT (optional): add "Tournament" to XP_TYPES (Q1)
apps/api/services/exceptions/tournaments.py          # EDIT: add reward errors if needed
tests/services/test_tournament_reward_service.py     # NEW
tests/integration/test_tournament_rewards.py         # NEW
```

### Pattern: reuse the existing XP grant publish (do NOT hand-roll a new XP event)
```python
# Source: apps/api/services/lootbox_service.py:389-415 (the canonical, consumed pattern)
multiplier = await self._lootbox_repo.fetch_xp_multiplier(conn=conn)
result = await self._lootbox_repo.upsert_user_xp(user_id, xp_amount, float(multiplier), conn=conn)
event = XpGrantEvent(
    user_id=user_id,
    amount=xp_amount,
    type="Other",            # or new "Tournament" XP_TYPES member
    previous_amount=result["previous_amount"],
    new_amount=result["new_amount"],
    reason="Tournament Participation",
)
await self.publish_message(routing_key="api.xp.grant", data=event, headers=headers,
                           idempotency_key=f"tournament:participation:{cycle_id}:{user_id}")
```

### Anti-Patterns to Avoid
- **Publishing `TournamentXpGrantEvent` to `api.xp.grant`.** No consumer decodes it; it would crash or silently drop the existing handler's rank-up path (Q1).
- **Reusing the existing `upsert_streak` repo method for cycle-end streaks.** It only *increments* (`current_streak + 1`, `ON CONFLICT`, lines 723-732) and has **no reset path**. Decision C requires reset-to-0 for non-participants. A new repo method (or a CTE that handles both increment and reset) is required.
- **Relying on queue idempotency for double-grant prevention.** `api.xp.grant ∈ IGNORE_IDEMPOTENCY` (`base.py:34`) — the message_id is ignored. The DB ledger is the only real guard (Q4).
- **Calling `LootboxService.grant_user_xp` from inside the submit transaction expecting atomicity.** It acquires its own connection and won't enlist in the caller's transaction (Q4 caveat).
- **Recomputing placements from `tournaments.completions` at reward time.** The snapshot in the payload is authoritative; recomputing risks divergence if late data changed (Decision B).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| XP delivery to users / Discord rank-up | A new XP event + bot consumer | Existing `XpGrantEvent` + `bot/extensions/xp.py` consumer + `lootbox.xp` upsert | Already built, tested, and owns the contract (Q1) |
| Placement computation | A new ranking query | Read `standings` from `cycle_completed` payload | Phase-7 SQL already snapshots it (Q5) |
| At-least-once outbox publishing | A second scheduler/poller | Hook into `publish_pending_transitions` | Phase-7 outbox already provides FOR UPDATE SKIP LOCKED + at-least-once |
| Idempotent reward guard | Ad-hoc flags | `0022` ledger with `UNIQUE(cycle_id,user_id,reason)` + `ON CONFLICT DO NOTHING` | Standard transactional-outbox dedupe |
| Reward amount config surface | New config table/endpoints | `categories.participation_xp / placement_xp / streak_xp` | Admin-editable via Phase-4 CRUD already |

**Key insight:** Phase 8 is almost entirely *wiring existing parts together*. The only genuinely new persistent state is the grants ledger; the only new logic is the Python tier-mapping and the reset-capable streak recompute.

## Runtime State Inventory

This is a brownfield phase but it adds new state rather than renaming existing state. Relevant pre-existing runtime state that the rewards engine touches or depends on:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `tournaments.streaks` (existing, one row/user); `tournaments.completions` (per-cycle participation source); `lootbox.xp` (the XP balance the grant mutates); `categories.{participation_xp,placement_xp,streak_xp}` (config) | Read all; write `streaks` (increment/reset) and `lootbox.xp` (grant). NEW: `tournaments.xp_grants` ledger (migration 0022) |
| Live service config | pg_cron job `tournament-cycle-transitions` (every minute, `0021`); outbox poller lifespan task (~10s, `app.py:240`). The cycle-end reward step rides on these — **no new scheduler** | None — attach to existing flow |
| OS-registered state | None — verified: no Task Scheduler/systemd/pm2 involvement; scheduling is pg_cron inside Postgres | None |
| Secrets/env vars | None new — uses existing RabbitMQ/DB connection state on `state.db_pool` / `state.mq_channel_pool` | None |
| Build artifacts | None — no package rename; SDK edit (optional `XP_TYPES` member) requires `just sync`/`just fix` to reinstall workspace SDK so API/bot see the new literal | If `XP_TYPES` is edited, run `just fix` (per MEMORY.md) before tests |

## Common Pitfalls

### Pitfall 1: Streak double-increment for multi-category participants
**What goes wrong:** A user submits in two categories whose cycles finalize in the same poll; each `cycle_completed` finalization increments the global streak, inflating it.
**Why it happens:** Streak is global (Q3) but finalization is per-category-cycle.
**How to avoid:** Guard the streak update with `tournaments.streaks.last_cycle_id` and/or a `('streak')` ledger row per `(cycle_id,user)`; only increment when this cycle hasn't already advanced the user's streak for the current window. **Lock this model before coding** (see Q3).
**Warning signs:** Streak grows by >1 per cycle window in tests with concurrent categories.

### Pitfall 2: Lost atomicity between ledger and XP write
**What goes wrong:** Ledger marks granted but `lootbox.xp` write fails (or vice versa), causing missed or double XP on retry.
**Why it happens:** `LootboxService.grant_user_xp` doesn't accept `conn` and won't join the caller's transaction (Q4).
**How to avoid:** Extract a `conn`-accepting grant helper; do ledger insert + `upsert_user_xp` in one transaction; treat the RabbitMQ publish as after-the-fact notification (publish failure already degrades gracefully — `base.py:111-113`).
**Warning signs:** Integration test that injects a failure between ledger and upsert shows divergent state.

### Pitfall 3: Participation XP fires on every submission
**What goes wrong:** XP granted per submission instead of once per cycle.
**Why it happens:** Hooking after `create_tournament_completion` without checking prior-existence.
**How to avoid:** Gate strictly on the `existing is None` branch (`submit_completion` line 506) AND the ledger `('participation')` unique guard. Note `fetch_user_completion` returns the *best* prior completion — `existing is None` is the correct "first ever this cycle" signal because the new row is inserted *after* this check.
**Warning signs:** Second (slower-rejected or faster-accepted) submission grants XP again.

### Pitfall 4: RANK() tie handling in placement mapping
**What goes wrong:** Ties (equal rank) either crash a 1:1 mapping or silently overpay.
**Why it happens:** `RANK()` yields duplicate rank values (1,1,3).
**How to avoid:** Map by `dict[place→xp].get(rank)`; both tied users at rank 1 get `place=1` XP; rank 2 simply has no recipient. Confirm this business rule (Q5).
**Warning signs:** Test with two identical times shows wrong number of grants.

### Pitfall 5: payload/struct drift
**What goes wrong:** Reward code reads a key not present in `standings` entries.
**Why it happens:** The SQL `jsonb_build_object` keys (`0021` lines 157-166) must match `TournamentLeaderboardEntryResponse` field names exactly.
**How to avoid:** Decode via `msgspec.convert(payload, TournamentCycleCompletedEvent)` (the outbox already does this in `_build_event`) and read typed fields, not raw dict keys.

## Code Examples

### Ledger-guarded grant (reference for the reward repo + service)
```python
# Reward repo: idempotent ledger claim. Returns True only on first insert.
async def claim_xp_grant(self, cycle_id: int, user_id: int, reason: str, amount: int,
                         *, conn: Connection | None = None) -> bool:
    _conn = self._get_connection(conn)
    row = await _conn.fetchval(
        """
        INSERT INTO tournaments.xp_grants (cycle_id, user_id, reason, amount)
        VALUES ($1, $2, $3, $4)
        ON CONFLICT (cycle_id, user_id, reason) DO NOTHING
        RETURNING id
        """,
        cycle_id, user_id, reason, amount,
    )
    return row is not None
```

### Placement mapping (Python, reading the event)
```python
# Source pattern derived from tournaments.py:282-299 + 425-438 (verified structs)
placement_by_place = {tier.place: tier.xp for tier in category.placement_xp}
for entry in event.standings:                       # TournamentLeaderboardEntryResponse
    xp = placement_by_place.get(entry.rank)         # None -> beyond configured tiers, skip
    if not xp:
        continue
    if await repo.claim_xp_grant(event.cycle_id, entry.user_id, "placement", xp, conn=conn):
        await self._grant_xp(entry.user_id, xp, reason=f"Tournament Placement #{entry.rank}", conn=conn)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `TournamentXpGrantEvent` envisioned as the reward event (CONTEXT Decision F tentative) | Reuse generic `XpGrantEvent` via existing grant mechanism | This research (Q1) | Avoids a dead-letter storm; reuses tested bot consumer |
| Per-grant boolean columns mooted for dedupe | `0022` grants-ledger table | This research (Q4) | One mechanism for 3 grant reasons + audit trail |

**Deprecated/outdated:** none. The `handle_db_exceptions` decorator is project-deprecated (CLAUDE.md) — use the domain-exception hierarchy in any new reward errors.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Add a `"Tournament"` member to `XP_TYPES` (vs. reuse `"Other"`) | Q1 | Low — cosmetic/analytics only; `"Other"`+reason works regardless |
| A2 | Streak increments once per cycle window; multi-category dedupe via `last_cycle_id`+ledger | Q3 | **Medium** — wrong model inflates streaks; lock before coding |
| A3 | Ties: each tied user gets that place's XP; skipped rank numbers have no recipient | Q5 | Medium — alternative (dense rank / no-tie-payout) would change payouts |
| A4 | Cycle-end rewards attach inside `publish_pending_transitions` (Option A) | Architecture | Low — Option B exists but contradicts "no new patterns" |
| A5 | Leave `TournamentXpGrantEvent` in SDK unused | Q1 | Low |

## Open Questions (RESOLVED)

1. **Streak window model (A2)** — RESOLVED: increment the global streak once per cycle window; dedupe multi-category participation via `tournaments.streaks.last_cycle_id IS DISTINCT FROM $cycle_id` in `advance_streak` (combined with the `('streak')` ledger row). A user who plays two simultaneous categories' cycles increments once, not twice. Locked into 08-01 Task 3 (advance_streak) and proven by 08-03 Task 3's multi-category dedupe integration test.
2. **Tie payout rule (A3)** — RESOLVED: each tied user is paid their own rank's XP (map `dict[place->xp].get(rank)`; two users at `rank=1` both receive `place=1` XP; the skipped rank number simply has no recipient). Locked into 08-02 Task 2 placement mapping and 08-02 Task 3 placement-tie unit test.
3. **`XP_TYPES` extension (A1)** — RESOLVED: add a `"Tournament"` member to the SDK `XP_TYPES` literal (no `XP_AMOUNTS` entry — amounts are config-driven), and run `just fix` to reinstall the workspace SDK before tests. Locked into 08-01 Task 2.
</content>
