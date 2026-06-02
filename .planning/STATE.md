---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: — Phases
status: unknown
last_updated: "2026-06-01T22:40:10.726Z"
last_activity: 2026-06-01
progress:
  total_phases: 2
  completed_phases: 2
  total_plans: 10
  completed_plans: 10
  percent: 100
---

# Tournament System — State

Last activity: 2026-06-02 - Completed quick task 260601-ui4: fix tournament verify hang on finalizing cycles

## Current Status

Milestone v1.0 (recurring tournament cycles) is **shipped** — phases 01–11
complete and committed on `feat/tournaments-pr` (`52b066e feat(tournaments):
tournament verification system (GSD v1.0, phases 01-11)`).

## What's Built

Tournament domain within the Genji Shimada monorepo, following the existing
Controller → Service → Repository pattern:

- **Migrations:** `apps/api/migrations/0020_tournaments.sql`, `0021_tournament_cycle_transitions.sql`, `0022_tournament_xp_grants.sql` (`tournaments` schema; `core.completions.tournament_completion_id` FK).
- **SDK:** `libs/sdk/src/genjishimada_sdk/tournaments.py` (msgspec structs + events).
- **Repository:** `apps/api/repository/tournaments_repository.py`.
- **Services:** `apps/api/services/tournament_service.py`, `tournament_outbox_service.py`, `tournament_reward_service.py`; exceptions in `apps/api/services/exceptions/tournaments.py`.
- **Routes:** `apps/api/routes/v3/tournaments.py`.
- **Bot:** `apps/bot/extensions/tournaments.py` (queue consumers, announcements, admin slash commands).
- **Cycle transitions:** automatic rollover via pg_cron + outbox/poller (Phase 07).

## Key Decisions (carried forward)

- Separate `tournaments.completions` table; cross-write to `core.completions` only when strictly faster (preserves "latest = fastest").
- Tier-then-time ranking (verified > unverified, then fastest).
- Automatic cycle transitions via pg_cron + outbox poller.
- XP via existing `api.xp.grant` queue with deterministic keys for double-grant prevention.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260601-bhy | Tournament cycle lifecycle control: bootstrap first cycle, pause/resume, debug cycle-length override | 2026-06-01 | 0df17d6 | [260601-bhy-tournament-cycle-lifecycle-control-boots](./quick/260601-bhy-tournament-cycle-lifecycle-control-boots/) |
| 260601-ui4 | Fix tournament verify hang: PB propagation resolved cycle via active-only lookup, so verifying during a `finalizing` cycle never drained the gate (edition stuck in awaiting_results, no results announcement) | 2026-06-02 | 527a7ad | [260601-ui4-tournament-verification-needs-to-be-bake](./quick/260601-ui4-tournament-verification-needs-to-be-bake/) |

## Blockers/Concerns

- `ROADMAP.md`/`STATE.md` were missing locally (gitignored, never persisted); reconstructed 2026-06-01 to unblock GSD tooling.
- PROJECT.md originally listed manual cycle transitions as Out of Scope; quick-task work intentionally amends that for bootstrap + test tooling only.

## Accumulated Context

### Phase 12.1 Progress

- **12.1-05 complete (2026-06-01):** Bot deferred-results handler + force-publish
  command (D-01/D-03/D-04/D-05) — the bot-side completion of the verification-aware
  flow. New `_on_edition_results` consumer (`@queue_consumer("api.tournament.results",
  struct_type=TournamentEditionResultsEvent, idempotent=True)`) posts the deferred
  results as a NEW separate Components-V2 card (D-04 — no edit-in-place, no stored
  message ids) and performs the HELD champion-role transfer (D-05) per result entry by
  reusing `_transfer_champion_role` verbatim (strip-all-then-grant, staggered,
  guild-leave-safe, vacant-on-None-winner); an empty/all-rejected edition posts a
  no-winner card and transfers nothing. `_on_edition_rollover` renders a `## 🏅 Results
  / Results pending verification…` placeholder when `results_pending=True` (empty
  `results` → transfer loop skips → previous champion KEEPS the role, D-01/D-05); the
  empty-event early-return guard was widened with `and not results_pending` so a
  hiatus+pending placeholder-only event still posts. New mod-gated
  `/tournament-publish-results` command (in `TournamentRerollCog`, copying
  `/tournament-reroll`): defer ephemeral → AUTHORITATIVE bot-side `is_mod` (mod or
  sensei) gate raising `UserFacingError` before any API call (T-12.1-14;
  `default_permissions(manage_guild=True)` is a UI hint) → `ConfirmationView` gate
  (abandon is irreversible) → `api_service.force_publish_tournament_results()`. New
  `api_service.force_publish_tournament_results` = PATCH `/tournaments/publish-results`
  → `JobStatusResponse` (the bot's ONLY DB path — bot never writes Postgres).
  Mention-injection mitigation reused verbatim (numeric `<@id>` only + AllowedMentions
  allow-list, ping in a TextDisplay, T-12.1-15). 8 new bot tests (5 handler + 3
  command); `just lint-bot` clean; TRUE full suite (`-n 4 --no-testmon`) **1839 passed
  / 2 skipped / 2 xfailed / 0 failures** (up from 1831). No deviations. Commits
  `c834ba5` (Task 1) / `8d43bfb` (Task 2). **Phase 12.1 complete (5/5 plans).**

- **12.1-04 complete (2026-06-01):** Poller drain state machine + force-publish
  (D-01/D-02/D-03/D-05/D-07) — the heart of the phase. `process_awaiting_results_editions`
  now runs INSIDE the existing publish-before-mark outbox transaction and implements
  the D-07 three-branch drain state machine per `awaiting_results` edition (locked
  `FOR UPDATE SKIP LOCKED`, `ends_at ASC`): first-tick-no-pending → combined
  `TournamentRolloverEvent(results_pending=False)` + grant + complete; first-tick-pending
  → start-only `TournamentRolloverEvent(results_pending=True)` (empty results → champion
  role held, D-05) + `start_announced`, no grants; later-tick-drained → write an
  `edition_results` outbox row (the SAME loop drains+publishes+grants it next tick at
  `tournament:results:{edition_id}`, Pitfall 3 at-least-once) + complete. The grant loop
  (`award_cycle_end` + `_reset_non_participant_streaks`) is reused VERBATIM inside the
  transaction (docstring 21-38 invariant intact); the deferred grant runs exactly once
  when the row drains (no double-grant). Force-publish (D-03): `force_publish_results`
  reuses the shared `_write_drained_results_row` IGNORING `count_inflight_verifications`,
  leaves abandoned pending runs `pending` (Open Q2); PATCH `/api/v3/tournaments/publish-results`
  (`tournaments:write`) → 409 on `NoAwaitingResultsEditionError`. New repo methods:
  `fetch_awaiting_results_editions`, `fetch_edition_child_cycles`,
  `mark_edition_start_announced`, `complete_edition`. `_EVENT_ROUTING`/`_build_event`
  dispatch `edition_results` → `api.tournament.results`; `_idempotency_key` derives the
  edition-scoped key per event type. TDD RED→GREEN per task (`f9496ed`/`1bfd53b` poller,
  `b471203`/`4a90a73` force-publish); `just lint-api` clean.

  - **Cleared the last 3 inherited failures.** Rewrote `test_edition_transitions.py`
    (`TestDrift`/`TestSingleEdition`/`TestHiatus`) to the poller-owns-results model
    (cron stops at `awaiting_results`/`finalizing`, writes no outbox row). TRUE full
    suite (`-n 4 --no-testmon`): **1831 passed / 2 skipped / 2 xfailed / 0 failures** —
    the prior `-n 4` flake also passed this run. Phase test debt fully retired.

  - **Deviations (both Rule 3 blocking):** (1) extended the `pending_transitions`
    event_type CHECK with `edition_results` in migration 0025 (the row write is core to
    this plan, was rejected by the 0024-era CHECK); (2) relocated the real-DB
    force-publish SERVICE tests from `tests/services/` to the integration suite
    (`services/conftest.py` makes `setup_test_db` a no-op, so `tournaments.*` only exists
    in the migrated integration DB).

- **12.1-03 complete (2026-06-01):** Repository + service verify/reject tri-state
  writes (D-08). `set_tournament_verified` now writes `SET status = $2`
  ('verified'/'rejected'; mapped from the kept bool signature) instead of the
  now-generated read-only `verified` column — preserving the `IS DISTINCT FROM`
  no-op idempotency guard (CR-01/WR-06), now keyed on `status`. Added
  `count_inflight_verifications(edition_id)` — `COUNT(*) ... JOIN cycles ON
  edition_id WHERE status='pending'` — the poller's drain signal (Plan 04).
  `fetch_tournament_completion` now returns `status`. Service `_set_verified`
  terminal guard (`status=='verified'` -> AlreadyVerifiedError, T-12.1-06) and
  no-op short-circuit (re-verify, T-12.1-07) rewritten to read `existing['status']`;
  the no-op verdict event derives `verified` from `status`. The atomic
  `_do(active_conn)` flip+participation-XP transaction wrapper is unchanged.
  TDD RED->GREEN per task (`e9a3622`/`30a8513` repo, `b272419`/`ec2018a` service);
  `just lint-api` clean.

  - **Cleared the 11 Wave-1-inherited failures.** Reject is now drain-detectable
    (writes `status='rejected'`, closing the D-08 indistinguishability bug). Fixed
    the shared `create_test_tournament_completion` fixture + two
    `test_tournaments_integration.py` seeds to write `status` (the `verified`
    column is generated). Full suite: **4 failed / 1814 passed** (down from the
    15-failure baseline) — the 4 remaining are the 3 Plan-04-owned
    `test_edition_transitions.py` (`awaiting_results` vs `completed`) + 1
    pre-existing `-n 4` flake. No new regressions.

- **12.1-02 complete (2026-06-01):** SDK wire contracts (D-09), interface-first.
  Added `TournamentEditionResultsEvent` (`edition_id`, `results:
  list[TournamentCycleCompletedEvent]`) on `api.tournament.results` (idempotency
  `tournament:results:{edition_id}`), exported in `__all__`. Added
  `results_pending: bool = False` as the LAST field on `TournamentRolloverEvent`
  — the default is a HARD backward-compat constraint (Pitfall 2): an OLD-shape
  `edition_rollover` outbox payload with no `results_pending` key still
  `msgspec.convert`s, so in-flight rows at deploy never get stuck unpublished.
  Extended `EditionStatus` Literal → `["active", "awaiting_results", "completed"]`.
  TDD RED (`ce2afc3`, ImportError confirmed) → GREEN (`bca32ed`); 6 SDK
  round-trip/compat tests pass; `just fix` reinstalled the editable workspace SDK;
  `just lint-sdk` clean. No deviations.

  - **Full-suite gate:** 15 failed / 1795 passed — identical to the 12.1-01
    baseline (11 owned by 12.1-03 `set_tournament_verified` generated-column write,
    3 owned by 12.1-04 timing-only-cron edition_transitions assertions, 1
    pre-existing `-n 4` flake). No new regressions from this SDK-only plan.

- **12.1-01 complete (2026-06-01):** Migration 0025 — verification-aware DB
  bedrock (D-06/D-08). Added tri-state `tournaments.completions.status`
  (`pending`/`verified`/`rejected`, CHECK-constrained) so "verification queue
  drained" is detectable (`COUNT(*) WHERE status='pending'`) and the illegal
  "verified AND rejected" state is unrepresentable. Re-added `verified` as a
  STORED generated column (`GENERATED ALWAYS AS (status = 'verified') STORED`)
  via the ordered swap (add status → backfill → drop ranking index → drop
  verified → re-add generated → recreate index, Pitfall 1) — every `verified DESC`
  ranking read + SDK `verified` field keeps working unchanged; only WRITES move
  to `status`. Extended the editions status CHECK with `awaiting_results` + added
  a `start_announced` marker. Rewrote `process_edition_transitions()` TIMING-ONLY:
  flips edition `active → awaiting_results`, child cycles → `finalizing`, creates
  N+1 grid-anchored, writes NO outbox row + NO snapshot (D-06). 7 Wave 0 schema
  tests authored RED then GREEN (22 passed in the file). `just lint-api` clean.

  - **Deviation (Rule 1, plan-owned):** fixed the pre-existing fresh-restart-wipe
    test seed to use `status='verified'` (the boolean is now generated).

  - **Carried-forward / deferred-by-design (see `deferred-items.md`):** the TRUE
    full suite (`-n 4 --no-testmon`) shows 15 failures — 11 owned by **12.1-03**
    (`set_tournament_verified` still does `SET verified = $2`, hits the generated
    column; verify/reject/leaderboard/cross-write), 3 owned by **12.1-04**
    (`test_edition_transitions.py` asserts the OLD cron-finalizes behavior; the
    timing-only cron correctly stops at `awaiting_results`), and 1 pre-existing
    `-n 4` flake (`test_filter_by_single_category`). None are 12.1-01 regressions;
    all resolved by downstream plans whose `files_modified` own the app code.

### Phase 12 Progress

- **12-05 complete (2026-06-01):** Bot combined-rollover consumer. Fused the
  `_on_cycle_started` + `_on_cycle_completed` pair into ONE `_on_edition_rollover`
  handler on `api.tournament.rollover` (`@queue_consumer(...,
  struct_type=TournamentRolloverEvent, idempotent=True)`, D-09), completing the DB →
  outbox → bot event path. Renders ONE CV2 LayoutView card with CONDITIONAL sections
  (D-10): a `## 🏅 Results` block iff `event.results`, a `## 🏁 New Cycle` block iff
  `event.started` — covering normal / into-hiatus / out-of-hiatus; a both-empty event
  posts nothing. Champion transfer iterates `event.results` FIRST (only when results
  present), reusing `_transfer_champion_role` verbatim (strip-all-then-grant, A6).
  Winners mentioned by numeric `<@id>` only, `AllowedMentions(users=allow-list,
  everyone=False, roles=False)`, ping inside a `ui.TextDisplay` (T-12-11); category/map
  fetched via the API on receipt (bot never reads Postgres, T-12-13). Dropped the
  deprecated `TournamentCyclesStarted/CompletedEvent` bot imports. Handler tests
  extended with the three conditional cases (`-k rollover` → 5 passed); full handler
  file 16 passed; `just lint-bot` clean. Wave-merge full suite: 7 failed (all
  deferred-by-design `test_cycle_transitions.py` 5 + `test_lifecycle_control.py` 2 —
  exactly as 12-04 predicted; no regressions) / 1801 passed.

- **12-04 complete (2026-06-01):** Routes + edition read. Moved pause/debug off
  per-category routes to config-level `PATCH /tournaments/pause` +
  `PATCH /tournaments/debug-cycle-length` (global, `tournaments:write`); cadence/anchor
  via `PATCH /tournaments/config`; bootstrap → `POST /tournaments/bootstrap`. Added
  `GET /tournaments/editions/active` (`tournaments:read`) surfacing the STORED
  `started_at`/`ends_at` (D-05/D-08, closes frontend-spec §8); 404 = `NoActiveEditionError`.
  `InvalidTimezoneError` → 422 on config PATCH (T-12-10); production debug guard → 403
  preserved (T-12-07). Per-cycle endpoints kept cycle-scoped (A5). NEW
  `tests/integration/test_config_tournament.py` (16 tests) proves scope guards
  (401/403 via a seeded non-superuser read-only token), the production debug-guard,
  and the stored-timing edition read.

  - **Deviation (plan-owned cleanup):** completed the `cycle_frequency` removal
    (cadence is global since 0024) the deferred-items doc assigned to 12-04 — dropped
    it from the category SDK structs + repo `create_category` + service create/update,
    resolving the 26-test `POST /categories` 500 cascade and un-xfailing repo
    `TestCreateCategory`. Fixed the downstream bot `/tournament info` to read the stored
    edition `ends_at` via a new `api.get_active_edition` (was deriving from cadence).
    Net full-suite: 35 → 7 failing (the 7 remaining = deferred-by-design
    `test_cycle_transitions.py` 5 + `test_lifecycle_control.py` 2; no regressions).
    `just lint-api`/`lint-sdk`/`lint-bot` all clean.

- **12-03 complete (2026-06-01):** Service + outbox edition re-wiring.
  `bootstrap_edition` grid-snaps the first edition via repo `next_grid_boundary()`
  (now() consulted only to pick the boundary, NEVER stored — D-08/D-13a), creating
  ONE edition + one child cycle per active category + ONE start-only
  `edition_rollover` outbox row (D-09). Global `set_transitions_paused` /
  `set_debug_cycle_length` config setters (pause = hiatus, D-12; production guard
  preserved, T-12-07). Added `fetch_active_edition` service wrapper for Plan 04's
  `GET /editions/active`. Outbox collapsed to ONE `TournamentRolloverEvent` per
  rollover keyed by `tournament:rollover:{edition_id}` (D-11); reward/streak
  side-effects iterate `event.results` once per child cycle keyed on `cycle_id`
  (D-10/Pattern 4); FOR UPDATE SKIP LOCKED publish-before-mark + deferred XP
  publish preserved. TDD RED→GREEN both tasks. Targeted suite 46 passed; reward
  integration 5 passed; `just lint-api` clean.

  - **Deviations:** added repo `next_grid_boundary`/`is_valid_timezone` helpers
    (three-layer) + `InvalidTimezoneError` (anchor_tz validation, T-12-04); thin
    route updates + deprecated `bootstrap_cycle` shim to keep lint clean until 12-04
    re-paths; adapted `test_tournament_rewards.py` to the `edition_rollover` seed
    (its outbox path was directly impacted).

  - **Carried-forward for 12-04:** the `create_category`/`cycle_frequency` cascade
    (27 `test_tournaments_integration.py` failures) + `test_cycle_transitions.py`
    (5) + `test_lifecycle_control.py` (2) remain deferred-by-design (see
    `deferred-items.md`); none are 12-03 regressions.

- **12-02 complete (2026-06-01):** SDK + repository edition contracts.
  `TournamentRolloverEvent` (edition_id/results/started — byte-identical to the
  0024 `edition_rollover` payload), `TournamentEditionResponse`, global
  cadence/anchor/pause/debug config structs; repo `create_edition` (param-bound
  grid timestamps, never `now()`), `create_cycle_for_edition`,
  `fetch_active_edition`, injection-safe global config setters, and
  `create_pending_transition` with nullable cycle_id + edition_id. Targeted repo
  suite 52 passed / 2 xfailed; lint-sdk + lint-api clean.

  - **Carried-forward for 12-03 (service wave):** `TournamentCategoryLifecycleResponse`
    kept as an importable alias to `TournamentLifecycleResponse`; per-category
    `set_category_paused`/`set_category_debug_cycle_seconds` kept as deprecated
    shims delegating to the global setters; `create_category` + its
    `TournamentCategoryCreateRequest` service call still bind dropped
    `cycle_frequency` (TestCreateCategory xfail-by-design). The old
    `test_cycle_transitions.py` / `test_lifecycle_control.py` failures remain
    deferred (outside this plan's files_modified).

- **12-01 complete (2026-06-01):** Migration 0024 edition overhaul. Adds
  `tournaments.editions` + child FK, global cadence/anchor/pause/debug config,
  `next_grid_boundary()` (DST-correct), `process_edition_transitions()`
  (status-only flip, `next.started_at = prev.ends_at`, never `now()` — the drift
  fix), one `edition_rollover` outbox row `{results, started, edition_id}`, and a
  PB-preserving fresh-restart wipe. Wave 0 scaffolds (grid/edition/schema) GREEN.

  - **Wipe bug caught & fixed:** `TRUNCATE ... CASCADE` would structurally truncate
    `core.completions` (FK into `tournaments.completions`), destroying PBs — replaced
    with ordered row-level DELETEs that honor `ON DELETE SET NULL` (D-15).

  - **Carried-forward for 12-02/12-03:** 11 pre-existing tournament tests
    (`test_cycle_transitions.py`, `test_lifecycle_control.py` pause/debug,
    `test_tournaments_repository.py::TestCreateCategory`) are stale-by-design
    against the dropped per-category columns / old function. See
    `deferred-items.md`; downstream plans rewrite the SDK/repo/service.

### Roadmap Evolution

- 2026-06-01: Reconstructed roadmap after v1.0 ship; added post-v1.0 quick-task track for cycle lifecycle control.
- Phase 12 added: Overhaul of tournaments
- Phase 12.1 inserted after Phase 12: Verification-aware tournament results: defer edition results until pending verifications drain (URGENT)
