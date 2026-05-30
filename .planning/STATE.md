---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: verifying
stopped_at: Completed 07-04-PLAN.md (gap closure)
last_updated: "2026-05-30T22:30:00Z"
last_activity: 2026-05-30
progress:
  total_phases: 10
  completed_phases: 10
  total_plans: 23
  completed_plans: 23
  percent: 100
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-29)

**Core value:** Give the Genji Parkour community a persistent, competitive cycle that keeps players engaged week-over-week through fresh map challenges, leaderboard competition, and visible champion recognition.
**Current focus:** Phase 10 — bot-slash-commands

## Current Position

Phase: 10 (bot-slash-commands) — EXECUTING
Plan: 3 of 3
Status: Phase complete — ready for verification
Last activity: 2026-05-30 - Completed quick task 260530-mu5: add just recipes for local infrastructure

Progress: [██████████] 100%

## Performance Metrics

**Velocity:**

- Total plans completed: 9
- Average duration: -
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 1 | - | - |
| 06 | 2 | - | - |
| 7 | 3 | - | - |
| 08 | 3 | - | - |

**Recent Trend:**

- Last 5 plans: -
- Trend: -

*Updated after each plan completion*
| Phase 02 P01 | 2min | 2 tasks | 2 files |
| Phase 02 P02 | 3min | 2 tasks | 2 files |
| Phase 05 P01 | 3min | 2 tasks | 4 files |
| Phase 05 P02 | 2min | 2 tasks | 2 files |
| Phase 05 P03 | 5min | 2 tasks | 3 files |
| Phase 07 P01 | 15m | 2 tasks | 2 files |
| Phase 07 P02 | 12m | 3 tasks | 3 files |
| Phase 07 P03 | 40m | 3 tasks | 4 files |
| Phase 08 P01 | 3min | 3 tasks | 5 files |
| Phase Phase 08 P02 P02 | 6min | 3 tasks | 3 files |
| Phase 08 P03 | 14min | 3 tasks | 6 files |
| Phase 09 P01 | 9min | 3 tasks | 8 files |
| Phase 09 P02 | 18min | 3 tasks | 3 files |
| Phase 10 P01 | 13min | 2 tasks | 5 files |
| Phase 10 P02 | 4min | 2 tasks | 2 files |
| Phase 10 P03 | 7min | 3 tasks | 3 files |
| Phase 07 P04 | 8min | 2 tasks | 3 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Roadmap]: 10 phases derived from 25 requirements with fine granularity, horizontal layer approach splitting schema/SDK/repository into separate foundational phases
- [Roadmap]: Phases 1-3 are foundational (no direct requirement mapping), Phases 4-10 map all 25 v1 requirements
- [Phase ?]: All 4 tournament RabbitMQ event types defined upfront in SDK to prevent churn across phases 3-10
- [Phase ?]: JSONB columns modeled as typed sub-structs (PlacementXpTier, StreakXpTier) for compile-time validation
- [Phase ?]: Used aliased barrel import (TournamentsCategoryNotFoundError) matching existing CompletionsMapNotFoundError convention
- [Phase 05]: Conditional SQL query building pattern for optional exclude_map_ids in fetch_eligible_maps
- [Phase 05]: Used re.sub difficulty normalization for choose_map validation, matching SQL regexp_replace pattern
- [Phase 05]: choose_map silently replaces existing pending cycle rather than requiring explicit reroll first
- [Phase ?]: D-02: cycle transitions use pg_try_advisory_xact_lock(2025070100) (transaction-level, auto-release, non-blocking no-op)
- [Phase ?]: D-06: select_eligible_map SQL helper mirrors Phase 5 Python selection to keep the transition atomic
- [Phase ?]: D-10/D-11/D-12: outbox poller is a Litestar lifespan asyncio task (10s cadence) selecting FOR UPDATE SKIP LOCKED and marking published in the same transaction; publish-before-mark gives at-least-once
- [Phase ?]: 07-03: widened migration 0021 v_winner to bigint to fix Discord-snowflake overflow in the placement-snapshot winner
- [Phase ?]: 07-03: tournament integration tests use property/membership assertions for the session- and xdist-shared DB; poller tested via a monkeypatched publish_message seam (equivalent to X-PYTEST-ENABLED skip)
- [Phase ?]: [Phase 08]: 08-01 tournament XP grants reuse the generic XpGrantEvent (type='Tournament'), overriding CONTEXT Decision F
- [Phase ?]: [Phase 08]: 08-01 xp_grants UNIQUE(cycle_id, user_id, reason) is the only double-grant guard since api.xp.grant is in IGNORE_IDEMPOTENCY
- [Phase ?]: [Phase 08]: 08-01 advance_streak is a new reset-capable method (dedupe via last_cycle_id IS DISTINCT FROM); upsert_streak is increment-only
- [Phase ?]: [Phase 08]: 08-02 grant_xp is conn-accepting (ledger claim + lootbox.xp upsert atomic); grant_user_xp delegates with no conn
- [Phase ?]: [Phase 08]: 08-02 TournamentRewardService injects LootboxService for a mockable grant seam; placement dict[place->xp].get(rank) ties paid/beyond-tier skipped; streak bonus on exact threshold only
- [Phase ?]: [Phase 08]: 08-02 only the generic XpGrantEvent (type=Tournament) is published (no TournamentXpGrantEvent); non-participant streak reset deferred to 08-03
- [Phase ?]: [Phase 08]: 08-03 reward hooks ride existing transactions (submit txn + outbox txn), replay-safe via the 08-01 ledger, no new scheduler
- [Phase ?]: [Phase 08]: 08-03 non-participant streak reset sweep lives in the outbox service (fetch_all_streak_user_ids minus fetch_cycle_participants), not the per-event reward service
- [Phase ?]: [Phase 08]: 08-03 reward_service is an optional TournamentService ctor param so existing 3-arg mock unit tests keep working; submit_completion guards the call
- [Phase 09]: 09-01 D-01 channels.tournament.announcements is a dedicated repointable key initialized to the existing per-env announcements channel id; struct + both TOML blocks land in one task (forbid_unknown_fields)
- [Phase 09]: 09-01 bot unit tests live under apps/api/tests/bot/; bot Config is loaded by file path and registered in sys.modules so msgspec resolves forward-ref annotations (avoids utilities package collision with apps/api)
- [Phase 09]: 09-01 Wave 0 handler stubs are xfail and -k-selectable (cycle_started/results_embed/champion_role/champion_vacant/stagger/idempotency) for Plan 09-02
- [Phase 09]: 09-02 TournamentHandler is attached as PUBLIC bot.tournaments (RabbitHandler skips _-prefixed attrs); both consumers @queue_consumer(idempotent=True) — outbox message_id is the only dedupe key, no hand-rolled key
- [Phase 09]: 09-02 champion transfer is strip-all-then-grant (self-healing, D-04/D-05), role-first/send-last (Pitfall 5), _ROLE_OP_DELAY=1.0s stagger; winner-left-guild logged + skipped not crashed (Pitfall 3)
- [Phase 09]: 09-02 results embed deliberately omits XP line (D-03); numeric <@id> mentions + AllowedMentions(everyone/roles False) for mention-injection mitigation; champion line folded into the one results embed (D-06)
- [Phase ?]: [Phase 10]: 10-01 get_streak mirrors get_category three-tier hierarchy — service raises StreakNotFoundError(TournamentsError), route converts to 404; endpoint 404s on absent (D-04 zero-mapping is bot-side, Plan 10-03)
- [Phase ?]: [Phase 10]: 10-02 six tournament APIService wrappers are sync def returning self._request; choose_next_cycle uses PATCH /next-cycle (controller verb, overriding CONTEXT D-15 POST mention)
- [Phase ?]: [Phase 10]: 10-02 CategoryTransformer mirrors UserTransformer (digit fast-path + live autocomplete capped at 25, no cache); name miss raises UserFacingError
- [Phase ?]: [Phase 10]: 10-03 /tournament is a GroupCog (info/leaderboard/streak); /tournament-reroll is a SEPARATE flat command (default_member_permissions applies at top-level, can't mix open+locked subcommands)
- [Phase ?]: [Phase 10]: 10-03 authoritative reroll gate is bot-side itx.user.get_role(mod/sensei) raising UserFacingError; default_member_permissions is a UI hint only (bot key is full-scope)
- [Phase ?]: [Phase 10]: 10-03 bot owns streak 404->zero-state (except APIHTTPError + e.status==NOT_FOUND -> 0/0); empty leaderboard short-circuits before paginator (zero-page modulo guard)
- [Phase ?]: [Phase 10]: 10-03 TournamentLeaderboardPaginator is StaticPaginatorView[Any]; both bot test files share a real-utilities loader with sys.modules snapshot/restore
- [Phase 07]: 07-04 fixed cold-start db_pool race: poller _loop sleeps before its first poll (asyncpg lifespan is plugin-appended after the poller's) + publish_pending_transitions guards state.get('db_pool') with a clean no-op; cadence/cancellation/semantics unchanged

### Pending Todos

None yet.

### Blockers/Concerns

- Research flag: Phase 6 (Submission + Cross-Write) needs careful study of the `enforce_speed_rules_nonlegacy_only()` trigger behavior
- Research flag: Phase 7 (Cycle Transitions) outbox bridge pattern is architecturally novel for this codebase -- needs validation during planning
- Verification tier mapping: existing completions use boolean `verified` + `video` presence, tournament needs integer tiers -- resolve during Phase 1 schema design

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260530-mu5 | add just recipes for local infrastructure (infra-up, infra-down, infra-logs) | 2026-05-30 | d178334 | [260530-mu5-add-just-recipes-for-local-infrastructur](./quick/260530-mu5-add-just-recipes-for-local-infrastructur/) |

## Deferred Items

Items acknowledged and carried forward from previous milestone close:

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Test bug | `TestCheckActiveCycleForCategory` asserts `is True`/`is False` but method returns `int \| None` (phase 03-02, commit 99623a3) | open | Phase 05 P03 |

## Session Continuity

Last session: 2026-05-30T20:13:34.581Z
Stopped at: Completed 07-04-PLAN.md (gap closure)
Resume file: None
