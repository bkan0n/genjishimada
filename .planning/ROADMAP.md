# Tournament System — Roadmap

**Project:** Tournament System (see PROJECT.md)
**Current milestone:** v1.0 — Recurring tournament cycles (SHIPPED)

> Reconstructed 2026-06-01 from PROJECT.md, committed phase directories, and git
> history (`feat(tournaments): tournament verification system (GSD v1.0, phases
> 01-11)`). `.planning/` is gitignored; this file is local-only orchestration
> state for the GSD tooling.

## Milestone v1.0 — Phases

| Phase | Name | Status |
|-------|------|--------|
| 01 | Database schema & migrations | ✅ Complete |
| 02 | SDK types & domain exceptions | ✅ Complete |
| 03 | Repository layer | ✅ Complete |
| 06 | Submission flow & leaderboard | ✅ Complete |
| 07 | Automatic cycle transitions | ✅ Complete |
| 08 | Rewards engine | ✅ Complete |
| 09 | Bot queue consumers & announcements | ✅ Complete |
| 10 | Bot slash commands | ✅ Complete |
| 11 | Tournament verification flow | ✅ Complete |

(Phase numbers 04–05 were folded into adjacent phases during execution; the
shipped milestone is the 9 phases above.)

### Phase Goals

- **01 — Database schema & migrations:** Create the `tournaments` PostgreSQL schema (tables, constraints, indexes) plus the `core.completions` ALTER for `tournament_completion_id`.
- **02 — SDK types & domain exceptions:** msgspec structs for tournament requests/responses/events and the tournament domain exception hierarchy.
- **03 — Repository layer:** Raw asyncpg data access for categories, cycles, completions, blacklist, eligible-map selection.
- **06 — Submission flow & leaderboard:** Tournament completion submission with tier-then-time ranking and cross-write to `core.completions` (faster-only).
- **07 — Automatic cycle transitions:** Scheduled cycle rollover (pg_cron) with an outbox/poller that emits cycle-transition events.
- **08 — Rewards engine:** Participation, placement, and streak XP via the existing `api.xp.grant` queue with double-grant prevention.
- **09 — Bot queue consumers & announcements:** Bot-side consumers for tournament events; Discord announcements for new maps, results, champion transfers.
- **10 — Bot slash commands:** Admin slash commands for tournament actions.
- **11 — Tournament verification flow:** Tournament completion verification reusing the existing verification pipeline.

## Post-v1.0 — Quick Tasks

Operational gaps surfaced after v1.0 shipped are handled as quick tasks (see
`.planning/quick/` and STATE.md "Quick Tasks Completed"). These intentionally
amend the original PROJECT.md "Out of Scope" note on manual cycle transitions,
limited to bootstrap + test tooling:

- Cycle lifecycle control: manual bootstrap of the first cycle, pause/resume, and a debug cycle-length override for testing.

### Phase 12: Overhaul of tournaments

**Goal:** Replace the per-category, `now()`-stamped cycle-timing model with a single shared-epoch tournament — one explicit `tournaments.editions` entity holding grid-anchored start/end shared by every category (the drift fix: the cron job records exact grid timestamps, never `now()`), a single global cadence/anchor/pause/debug config, one combined rollover announcement (results of N + start of N+1), and a fresh-restart migration that wipes cycles/completions while preserving non-tournament PBs in `core.completions`.
**Requirements:** Tracked via locked decisions D-01..D-15 (incl. D-13a) in `12-CONTEXT.md` — no REQ-IDs in roadmap. NOTE: the prior "configurable **per-category** cycle frequency" requirement (PROJECT.md) is **amended/superseded** by D-01/D-02 (single global cadence).
**Depends on:** Phase 11
**Plans:** 5/5 plans complete

Plans:
**Wave 1**

- [x] 12-01-PLAN.md — Migration 0024: edition schema + global config + grid fn + transition rewrite (drift fix) + fresh-restart wipe + cron; Wave 0 test scaffolds (wave 1) — ✅ Complete (3/3 tasks, commits ebf4509/6d036e8/be742dc/f25c15f)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 12-02-PLAN.md — SDK structs (TournamentRolloverEvent, edition + global config) + repository edition CRUD & global config setters (wave 2)

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 12-03-PLAN.md — Service bootstrap_edition (grid-snap) + global pause/debug + outbox single combined event keyed by edition_id (wave 3)

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 12-04-PLAN.md — Routes: config-level pause/debug/cadence/anchor (scope-guarded) + GET /editions/active (wave 4)
- [x] 12-05-PLAN.md — Bot: single _on_edition_rollover handler with conditional results/starting sections (wave 4)

### Phase 12.1: Verification-aware tournament results (INSERTED)

**Goal:** Fix the correctness bug in Phase 12's combined rollover: results are
snapshotted at the grid boundary, so runs still pending verification are excluded
from standings, placement XP, and the champion-role transfer — permanently, once
announced. Decouple edition N's **results** from the on-time **start** of N+1.
When in-flight verifications remain at rollover, announce the start plus a
"results pending verification" placeholder, hold the champion role, and publish a
separate results announcement once the verification queue **drains** (no time cap).
Move results computation + reward grants out of the pg_cron function into the
existing outbox poller (cron becomes timing-only), preserving the single combined
message in the common no-pending case. Add an admin force-publish escape hatch and
a tri-state verification model so "drained" is detectable (reject currently leaves
`verified=FALSE`, indistinguishable from un-reviewed).
**Requirements:** Tracked via locked decisions D-01..D-09 in `12.1-CONTEXT.md`.
Amends Phase 12's D-09/D-10/D-11 (combined-announcement) decisions.
**Depends on:** Phase 12, Phase 11 (verification flow)
**Plans:** 5/5 plans complete

Plans:
**Wave 1** *(parallel — disjoint files)*

- [x] 12.1-01-PLAN.md — Migration 0025: tri-state status (D-08) + awaiting_results/start_announced + timing-only cron rewrite (D-06) + Wave 0 schema scaffolds
- [x] 12.1-02-PLAN.md — SDK: TournamentEditionResultsEvent + results_pending flag + EditionStatus awaiting_results (D-09); msgspec old-payload compat

**Wave 2** *(blocked on Wave 1)*

- [x] 12.1-03-PLAN.md — Repo + service tri-state writes (verify/reject) + count_inflight_verifications drain query (D-08)

**Wave 3** *(blocked on Wave 2)*

- [x] 12.1-04-PLAN.md — Poller drain state machine, 3 emit paths + deferred-results outbox row (D-01/D-02/D-05/D-07) + force-publish route/service (D-03)

**Wave 4** *(blocked on Waves 1 + 3)*

- [x] 12.1-05-PLAN.md — Bot _on_edition_results handler + results-pending placeholder (D-01/D-04/D-05) + /tournament publish-results command (D-03)

### Phase 13: Skill score

**Goal:** Add a performance-based **skill score** (separate from XP and from the
existing Ninja→God completion-rank label), computed from verified non-legacy
completions using the spike-validated hybrid algorithm (difficulty floor +
video-gated proof multipliers + diminishing returns), persisted to a lightweight
snapshot so the existing community leaderboard can sort/paginate by it, and served
via new `/api/v3/skill/*` endpoints. API-only vertical; bot + website surfaces are
later phases.
**Requirements:** See `13-SPEC.md` (spec-phase). Grounded in
`Skill("spike-findings-genjishimada")` (spikes 001/002/003).
**Depends on:** Phase 11 (verification flow)
**Plans:** 6/6 plans complete

Plans:
**Wave 1**

- [x] 13-01-PLAN.md — Migration 0027: skill schema + lean snapshot table + seeded weight config (req 1, 5) [wave 1]
- [x] 13-02-PLAN.md — SDK skill structs + CommunityLeaderboardResponse.skill_score field (req 5, 6, 7) [wave 1]

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 13-03-PLAN.md — skill_repository: 4-CTE input-query port + snapshot/weights CRUD (req 2, 3, 5) [wave 2]

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 13-04-PLAN.md — SkillService: spike scorer port + recompute_all + reads + in-flight guard (req 4, 5) [wave 3]

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 13-05-PLAN.md — /skill/* endpoints + in-process recompute listener + app-side nightly backstop (req 4, 5, 7, 8) [wave 4]

**Wave 5** *(blocked on Wave 4 completion)*

- [x] 13-06-PLAN.md — Emit recompute from all 4 verify paths + leaderboard skill_score column + integration test (req 6, 8, 9) [wave 5]

### Phase 14: Skill Score Dashboard

**Goal:** Provide a per-user skill score dashboard, building on the Phase 13 skill-score engine. Surface a user's skill score over time and the events that move it: timestamped per-user score-history capture + per-change attribution (cause + delta + before/after breakdown diff) riding the single Phase 13 `recompute_all` routine, plus three public GET endpoints under `/api/v3/skill/users/{id}/...` — windowed history (7d/30d/90d/1y/all) + summary, a newest-first paginated changes feed, and a per-change drill-down (top-N map impacts + other_factors). API-only vertical; website/bot surfaces are later phases.

**Requirements:** See `14-SPEC.md` (spec-phase) — 7 requirements locked (ambiguity 0.12). API-only vertical; website/bot surfaces are later phases.
**Depends on:** Phase 13
**Plans:** 3/5 plans executed

Plans:
**Wave 1** *(parallel — disjoint files)*

- [x] 14-01-PLAN.md — Migration 0031: skill.score_history + skill.score_change tables (cause CHECK, feed index, forward-only) [wave 1]
- [x] 14-02-PLAN.md — SDK dashboard response structs + CauseCategory Literal; enrich SkillRecomputeRequestedEvent (cause_category + actor_user_id, D-10) [wave 1]

**Wave 2** *(blocked on Wave 1)*

- [x] 14-03-PLAN.md — skill_repository: prev-snapshot bulk read + append-only bulk inserts + windowed history/paginated feed/IDOR-checked change lookup + completion-owner lookup (A4) [wave 2]

**Wave 3** *(blocked on Wave 2)*

- [ ] 14-04-PLAN.md — SkillService capture wiring in _do_recompute (D-05) + _RecomputeGuard descriptor accumulator + cause policy (D-08/D-09) + read methods; thread cause+owner through listener + 5 emit sites; extend service tests [wave 3]

**Wave 4** *(blocked on Wave 3)*

- [ ] 14-05-PLAN.md — Three public GET dashboard routes (history/changes/drill-down) + SYSTEM-tag PATCH /config recompute + integration test (Req 1,3,4,5,6,7) [wave 4]
