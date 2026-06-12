---
phase: 13-skill-score
verified: 2026-06-12T00:00:00Z
status: human_needed
score: 9/9 must-haves verified
overrides_applied: 0
re_verification: null
gaps: []
human_verification:
  - test: "Run the full integration test suite with testmon disabled and confirm all 11 tests pass"
    expected: "pytest apps/api/tests/integration/test_skill.py -x -q -o addopts='' passes all 11 tests"
    why_human: "Cannot start the test DB (Docker + PostgreSQL) in this verification environment; skill.* schema exists only in the migrated integration DB"
  - test: "Confirm migration 0027 applies cleanly on the live dev DB (or a fresh test DB)"
    expected: "psql migration runs without error, skill.snapshot and skill.weight_config tables exist, seeded row with diff_base=1.44 gamma=0.68 etc. is present"
    why_human: "Cannot run SQL migrations against a live DB in this static verification pass"
  - test: "GET /api/v3/community/leaderboard?sort_column=skill_score&sort_direction=desc returns players in descending skill_score order with skill_rank column intact"
    expected: "HTTP 200, JSON array sorted by skill_score desc, every row has skill_rank (string) and skill_score (number)"
    why_human: "Live endpoint requires a running API + populated DB"
---

# Phase 13: Skill Score Verification Report

**Phase Goal:** Add a performance-based skill score (separate from XP and the existing Ninja->God completion-rank label), computed from verified non-legacy completions using the spike-validated hybrid algorithm (difficulty floor + video-gated proof multipliers + diminishing returns), persisted to a lightweight snapshot so the existing community leaderboard can sort/paginate by it, and served via new /api/v3/skill/* endpoints. API-only vertical; bot + website surfaces are later phases.
**Verified:** 2026-06-12
**Status:** human_needed — all 9 SPEC requirements verified in source; 3 live-environment checks deferred to human
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths (mapped to SPEC requirements 1–9 and 11 Acceptance Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Migration 0027 creates `skill` schema, `skill.snapshot` table (lean, JSONB breakdown), `skill.weight_config` with `CHECK (gamma >= 0.5)` seeded with adopted defaults | VERIFIED | `apps/api/migrations/0027_skill_score.sql`: schema + snapshot + weight_config + CHECK constraint + idempotent seed with exact values (1.44, 0.68, 0.55, 10.0, 0.10, 0.60, 1.12, 1.07, 1.03). No pg_cron block present (matches D-03 app-side poller). |
| 2 | 4-CTE input query (`best -> field -> video_ranked -> fully`) ports the spike faithfully with eligibility filters, `time_pct`, FILTER-aggregate workaround | VERIFIED | `apps/api/repository/skill_repository.py` lines 28–96: exact 4-CTE structure `best AS / field AS / video_ranked AS / fully AS`; eligibility WHERE `c.verified=TRUE AND c.legacy=FALSE AND m.archived=FALSE AND m.code IS NOT NULL`; `DISTINCT ON (c.user_id, c.map_id) ORDER BY … time ASC`; `percent_rank() OVER (PARTITION BY map_id ORDER BY time DESC)` gives 1.0 for fastest; video_ranked is a separate CTE (no FILTER on window), then LEFT JOINed back. Suspicious rows excluded at Python level post-query (`[dict(row) for row in rows if not row["suspicious"]]`). |
| 3 | SkillService scorer reproduces the spike algorithm; NO hardcoded weight literals (all read from DB config) | VERIFIED | `apps/api/services/skill_service.py`: `_diff_weight`, `_map_score`, `_player_score`, `_player_breakdown` port the spike exactly. `recompute_all` calls `self._skill_repo.fetch_weights()` then `msgspec.convert(…, Weights)` — no weight literals in service or repository; the only constants are structural (`_FLOOR_OFFSET=1.5`, `_NEUTRAL=1.0`, `_GAMMA_FLOOR=0.5`). Partial clears receive `floor * partial_factor` only; fully-verified clears receive `floor * time_mult * medal_mult * wr_mult * shrink`. |
| 4 | `skill.recompute.requested` fires from ALL FIVE eligibility-changing paths including `moderate_completion` (the CR-01 fix) | VERIFIED | `completions_service.py` has 5 `self._emit_skill_recompute(…)` call sites: verify (:1092), un-verify (:1094), set_suspicious_flags (:1291), remove_suspicious_flags (:1320), and `moderate_completion` (:1561, the CR-01 fix). `moderate_completion` receives `request` and `skill_service` params threaded from the route handler (`routes/v3/completions.py:365-385`). A dedicated integration test (`test_moderate_verify_change_refreshes_score`) proves the fix. |
| 5 | Community leaderboard LEFT JOINs `skill.snapshot`, COALESCE(skill_score, 0), `skill_score` in sort_column Literal; `skill_rank` untouched | VERIFIED | `community_repository.py` line 228: `LEFT JOIN skill.snapshot ss ON u.id = ss.user_id`; line 221: `coalesce(ss.skill_score, 0) AS skill_score`; line 31: `"skill_score"` in sort_column Literal. `skill_rank` label CASE ordering at line 220 is untouched. Mirrored in `community_service.py` (line 55) and `routes/v3/community.py` (line 60). |
| 6 | Four /skill/* endpoints exist, PATCH /skill/config is superuser-only (no new scope minted) | VERIFIED | `apps/api/routes/v3/skill.py`: GET `/users/{id}`, GET `/users/{id}/breakdown`, GET `/config`, PATCH `/config`. PATCH uses `opt={"required_scopes": {"skill:admin"}}` — a sentinel no real token holds; `scope_guard` bypasses for superusers (`is_superuser` check at line 25 of guards.py). No new scope is minted (SPEC out-of-scope constraint honored). |
| 7 | D-07 empty-player rule: zero-eligible player -> score 0 ranked last; GET /skill/users/{id} returns 0 with empty breakdown | VERIFIED | `skill_service.py` `get_user_skill` returns `SkillSummaryResponse(skill_score=0.0, …)` when no snapshot row (line 228-235); `get_user_breakdown` returns `[]` (line 248-249). SQL COALESCE in leaderboard ranks them last. Integration test `test_zero_eligible_player_ranked_last` and `test_empty_player_zero_and_empty_breakdown` both cover this. |
| 8 | App-side nightly rebuild poller in `app.py` (D-03), NOT pg_cron; migration has no cron block | VERIFIED | `app.py` `skill_nightly_rebuild_poller` async context manager (lines 111-156): sleeps until next 04:00 UTC, calls `skill_service.recompute_all()`, registered in `lifespan` list (line 294). Migration 0027 explicitly notes "No pg_cron block". |
| 9 | Breakdown contributions (gamma-decayed) sum to the user's score total after recompute | VERIFIED | `_player_breakdown` stores `contribution = s / decay` (line 149); `_player_score` sums `s / i**gamma` (line 119) — both use the same decay formula over the same sorted scores, so sum(contribution) == skill_score. Integration test `test_breakdown_contributions_sum_to_total` asserts `math.isclose(contribution_sum, total, rel_tol=1e-6)`. |

**Score:** 9/9 truths verified in source code

---

### Decisions (D-01 through D-10) honored

| Decision | Contract | Status |
|----------|----------|--------|
| D-01 | In-process Litestar event, not RabbitMQ | VERIFIED — `events/skill.py` `@listener("skill.recompute.requested")` |
| D-02 | ALL state-change paths emit (verify/un-verify/reject/flag/unflag + moderate) | VERIFIED — 5 call sites, moderate added as 5th path (CR-01 fix) |
| D-03 | Nightly rebuild = app-side lifespan task, not pg_cron | VERIFIED — `skill_nightly_rebuild_poller` in `app.py` lifespan |
| D-04 | Single full-global recompute routine shared by event, cron, PATCH | VERIFIED — `recompute_all()` called in all three paths |
| D-05 | In-flight collapse guard | VERIFIED — `_RecomputeGuard` module-level singleton with asyncio.Lock |
| D-06 | Breakdown stored as JSONB on snapshot row | VERIFIED — `breakdown jsonb NOT NULL DEFAULT '[]'::jsonb` in migration; `_player_breakdown` stored in snapshot |
| D-07 | Lean snapshot (players with >=1 eligible run only); zero-score at read time | VERIFIED — `replace_snapshot` writes only players with eligible rows; COALESCE(0) in leaderboard |
| D-08 | Column named `skill_score` (not `score_skill`) | VERIFIED — consistent in migration, repository, service, route, SDK, tests |
| D-09 | Single typed-column config row, not key/value | VERIFIED — `skill.weight_config` with 9 typed columns; `Weights` struct with no defaults |
| D-10 | PATCH /config triggers immediate recompute | VERIFIED — `skill.py` route calls `await skill_service.recompute_all()` after `update_weights` |

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `apps/api/migrations/0027_skill_score.sql` | skill schema + snapshot + weight_config | VERIFIED | Exists, substantive (54 lines), creates schema/tables/CHECK/seed |
| `apps/api/repository/skill_repository.py` | 4-CTE input query + snapshot CRUD + weight CRUD | VERIFIED | 264 lines, all methods implemented with real SQL; `_WEIGHT_COLUMNS` allow-list for safe UPDATE |
| `apps/api/services/skill_service.py` | Hybrid scorer + recompute_all + reads | VERIFIED | 281 lines, full implementation; `_GUARD` module-level singleton; all 4 public read/write methods present |
| `apps/api/routes/v3/skill.py` | 4 endpoints + superuser guard | VERIFIED | 124 lines, all 4 endpoints implemented with proper DI and guard |
| `apps/api/events/skill.py` | In-process listener for `skill.recompute.requested` | VERIFIED | Auto-discovered by `events/__init__.py`; try/except wraps recompute (WR-03 advisory addressed) |
| `apps/api/events/schemas.py` | `SkillRecomputeRequestedEvent` struct | VERIFIED | Defined as msgspec.Struct with optional `reason` field |
| `libs/sdk/src/genjishimada_sdk/skill.py` | `Weights`, `SkillConfigUpdateRequest`, `SkillSummaryResponse`, `SkillBreakdownRow` | VERIFIED | 118 lines, all 4 structs with correct field types; `Weights` has no defaults (migration provides values) |
| `libs/sdk/src/genjishimada_sdk/users.py` | `CommunityLeaderboardResponse` gains `skill_score: float` | VERIFIED | Lines 245-246: `skill_rank: str` and `skill_score: float` both present |
| `apps/api/tests/integration/test_skill.py` | 11 integration tests covering full SPEC AC matrix | VERIFIED | 532 lines, 11 tests covering symmetric add/remove, CR-01 moderate path, field relativity, leaderboard sort, empty-player, PATCH authz, breakdown-sum |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `verify_completion` | `handle_skill_recompute` listener | `request.app.emit("skill.recompute.requested", …, skill_service=skill_service)` | VERIFIED | Line 1092/1094 in completions_service.py |
| `set_suspicious_flags` | listener | same emit helper | VERIFIED | Line 1291; method now accepts `request` + `skill_service` |
| `remove_suspicious_flags` | listener | same emit helper | VERIFIED | Line 1320; same threading |
| `moderate_completion` | listener | same emit helper (CR-01 fix) | VERIFIED | Line 1561; `skill_dirty` flag gates the emit |
| `fetch_community_leaderboard` | `skill.snapshot` | `LEFT JOIN skill.snapshot ss ON u.id = ss.user_id` | VERIFIED | community_repository.py line 228 |
| `handle_skill_recompute` | `SkillService.recompute_all` | DI-injected `skill_service` kwarg matching listener arg name | VERIFIED | events/skill.py line 36 |
| `PATCH /skill/config` | `recompute_all` | `await skill_service.recompute_all()` post-update (D-10) | VERIFIED | skill.py route lines 122 |
| `skill_nightly_rebuild_poller` | `recompute_all` | `provide_skill_service` + `await service.recompute_all()` | VERIFIED | app.py lines 142-144 |
| `CompletionsController` | `skill_service` DI | `provide_skill_service` in dependencies dict | VERIFIED | completions.py line 78 |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `SkillService.recompute_all` | `w` (weights) | `skill_repo.fetch_weights()` -> `SELECT … FROM skill.weight_config` | DB query confirmed | FLOWING |
| `SkillService.recompute_all` | `rows` (skill inputs) | `skill_repo.fetch_skill_inputs()` -> 4-CTE SQL against `core.completions ⋈ core.maps ⋈ core.users ⋈ maps.medals` | DB query confirmed | FLOWING |
| `SkillService.recompute_all` | snapshot rows | `replace_snapshot(snapshot_rows)` -> TRUNCATE + executemany INSERT | DB write confirmed | FLOWING |
| `SkillService.get_user_skill` | `row` | `skill_repo.fetch_snapshot(user_id)` -> `SELECT * FROM skill.snapshot WHERE user_id=$1` | DB query confirmed | FLOWING |
| `SkillController.update_config` | `weights` | `skill_service.update_weights(data)` -> `UPDATE skill.weight_config SET … RETURNING …` | DB write + return confirmed | FLOWING |
| `CommunityRepository.fetch_community_leaderboard` | `skill_score` | `LEFT JOIN skill.snapshot ss ON u.id = ss.user_id` -> `coalesce(ss.skill_score, 0)` | DB query confirmed | FLOWING |

---

### Behavioral Spot-Checks

Step 7b: SKIPPED for live endpoint tests (no running server). Unit + integration test coverage exists.

---

### Probe Execution

No probe scripts declared in PLAN files or found in `scripts/*/tests/probe-*.sh`.

---

### Requirements Coverage (SPEC requirements 1–9 + 11 ACs)

| Requirement | Status | Evidence |
|-------------|--------|----------|
| Req 1: Migration 0027 — skill schema + snapshot + weight config seeded | SATISFIED | Migration file exists with all stated elements |
| Req 2: Input query — 4-CTE spike port, one row per (user, map) | SATISFIED | `SKILL_INPUT_QUERY` in skill_repository.py mirrors spike exactly |
| Req 3: Eligibility filtering — verified/non-legacy/non-archived/coded/non-suspicious | SATISFIED | WHERE clause lines 35-38; Python-level suspicious filter line 144 |
| Req 4: Scoring algorithm — floor + video-gated proof multipliers + diminishing returns | SATISFIED | `_diff_weight`, `_map_score`, `_player_score` in skill_service.py |
| Req 5: DB-configurable weights — no hardcoded literals in service/repository | SATISFIED | `fetch_weights()` call in `_do_recompute`; no weight literals in service/repo (verified by grep) |
| Req 6: Community leaderboard skill_score sortable column | SATISFIED | LEFT JOIN + COALESCE(0) + Literal member in repo/service/route |
| Req 7: Four /skill/* endpoints + superuser PATCH guard | SATISFIED | All 4 endpoints in skill.py; `skill:admin` sentinel + superuser bypass |
| Req 8: Freshness on verification change — recompute fires from all paths | SATISFIED | 5 emit paths including moderate_completion (CR-01 fix) |
| Req 9: Symmetric removal — rejection/unflag/unsuspicious drops contribution | SATISFIED | All 5 paths emit; input query re-filters ineligible rows; integration test asserts symmetric add/remove |
| AC: 0027 applies cleanly on fresh test DB | NEEDS HUMAN | Cannot run migration in this environment |
| AC: Input query returns one fastest eligible run per (user, map) with time_pct=1.0 for field fastest | SATISFIED (code) | DISTINCT ON + ORDER BY time ASC; percent_rank() ORDER BY time DESC gives 1.0 for min time |
| AC: SkillService reproduces spike scorer totals | SATISFIED (code) | Identical formula structure to spike scorer; unit tests in test_skill_scorer.py |
| AC: Partial clears = floor only; video clears = multipliers; lowering gamma reduces farming | SATISFIED | `not row["fully_verified"]` branch returns `floor * partial_factor`; gamma in `_player_score` |
| AC: No hardcoded weight literals | SATISFIED | grep found no weight literals; `_WEIGHT_COLUMNS` allow-list in repo |
| AC: GET /community/leaderboard?sort=skill_score returns descending order + unchanged skill_rank | NEEDS HUMAN | Live endpoint test required |
| AC: GET /skill/users/{id}, /breakdown, /config return 200 with msgspec bodies; breakdown sums to total | SATISFIED (code + test) | Unit test `test_breakdown_contributions_sum_to_total` asserts this |
| AC: PATCH /skill/config — 401/403 non-superuser, 200 superuser | SATISFIED (code + test) | Integration test `TestConfigPatchAuthz` covers all three cases |
| AC: Verifying a run updates submitter AND second player on same map | SATISFIED (code + test) | `test_field_relativity_second_player_updates` |
| AC: Rejecting returns score to pre-verify value; suspicious-flag drops to 0 | SATISFIED (code + test) | `test_verify_raises_and_reject_restores`, `test_suspicious_flag_drops_score_to_zero` |
| AC: Zero-eligible player shows score 0 ranked last; /skill/users/{id} returns 0 + empty breakdown | SATISFIED (code + test) | `test_zero_eligible_player_ranked_last`, `test_empty_player_zero_and_empty_breakdown` |

---

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| `community_repository.py:232` | `sort_values` and `sort_direction` f-string-interpolated into SQL without a SQL-boundary allow-list (WR-01 from code review) | Warning | Correctness today relies solely on the `Literal[...]` type annotation; a future loosening or internal caller bypassing the Literal could introduce SQL injection. The weight-update code in the same phase uses `_WEIGHT_COLUMNS` as a defense-in-depth pattern, but the leaderboard sort does not. Not an exploit with current callers. |
| `community_repository.py:232` | `ORDER BY nickname` is ambiguous when `sort_column="nickname"` — `nickname` appears in two CTE scopes (WR-02) | Warning | Relies on Postgres resolving the unqualified `nickname` in ORDER BY to the outer output column; if the projection shifts the sort silently changes. Pre-skill behavior was already this way; the phase did not worsen it but also did not fix it. |
| `skill_service.py:254` / `skill_repository.py:227` | `fetch_weights()` returns `{}` when config row is missing; `msgspec.convert({}, Weights)` raises an opaque 500 (WR-06) | Warning | Only reachable if migration was not applied or the row was deleted. No guard in service. |

No `TBD`, `FIXME`, or `XXX` debt markers were found in any phase-13-modified files.

---

### Code Review Critical Finding (CR-01) — Verification

The code review identified that `moderate_completion` never emitted `skill.recompute.requested`, leaving the snapshot stale after moderation. This was classified CRITICAL (SPEC req 8/9 violation).

**Verified fixed:**
- `moderate_completion` method now accepts `request: Request | None` and `skill_service: SkillService | None` (completions_service.py:1417-1419)
- `skill_dirty = False` flag tracks any eligibility-changing field change (line 1459)
- Flag is set to `True` on verified flip (line 1486), new suspicious flag insert (line 1527), and suspicious flag delete (line 1537)
- `_emit_skill_recompute` fires post-commit when `skill_dirty` (line 1560-1561)
- Route handler `moderate_completion` in `routes/v3/completions.py:365-385` injects `skill_service: SkillService` and `request: Request` and passes them through
- Integration test `test_moderate_verify_change_refreshes_score` (line 212) proves the fix by driving the moderation endpoint and asserting the snapshot refreshes

---

### Advisory Warnings (WR-01, WR-02, WR-06) — Status

These three code-review warnings remain open (not fixed in this phase):

- **WR-01** (sort_column SQL interpolation without allow-list): OPEN warning. Mitigated in practice by the closed `Literal[...]` type on all three call sites. Not a blocker for phase goal.
- **WR-02** (nickname ORDER BY ambiguity): OPEN warning. Pre-existing pattern, not introduced by this phase. Not a blocker.
- **WR-06** (empty `{}` from `fetch_weights` produces opaque 500): OPEN warning. Requires the seeded migration row to be absent (unlikely in practice). Not a blocker.

These are observable risks but do not prevent the phase goal from being achieved.

---

### Human Verification Required

#### 1. Run Integration Test Suite

**Test:** `cd /Users/nebula/coding/parkour/genji/genjishimada && uv run --project apps/api pytest apps/api/tests/integration/test_skill.py -x -q -o addopts=""`
**Expected:** 11 tests pass (10 original + 1 added for CR-01 moderate path)
**Why human:** Requires live PostgreSQL container via `docker compose -f docker-compose.local.yml up -d`

#### 2. Migration 0027 Clean Apply

**Test:** Apply migration 0027 to a fresh test DB and verify `skill.snapshot`, `skill.weight_config`, seeded row, and `CHECK (gamma >= 0.5)` constraint exist
**Expected:** Migration applies without error; `SELECT * FROM skill.weight_config` returns one row with `diff_base=1.44, gamma=0.68, time_bonus=0.55, shrink_k=10.0, wr_bonus=0.10, partial_factor=0.60, medal_gold=1.12, medal_silver=1.07, medal_bronze=1.03`
**Why human:** Requires live PostgreSQL and migration tooling

#### 3. Live Leaderboard Sort Endpoint

**Test:** `GET /api/v3/community/leaderboard?sort_column=skill_score&sort_direction=desc&page_size=20` against a running API with populated skill snapshot
**Expected:** HTTP 200, rows sorted by `skill_score` descending, every row includes `skill_rank` (string label, untouched), zero-eligible players have `skill_score=0` at end of list
**Why human:** Requires running API + live DB with computed snapshot

---

### Gaps Summary

No gaps. All 9 SPEC requirements are satisfied in the source code. The CR-01 critical code review finding is confirmed fixed (5th emit path in `moderate_completion` exists and is wired through route). The 3 advisory warnings (WR-01/02/06) remain open and are noted above but do not block the phase goal.

Status is `human_needed` because 3 items (integration test run, migration apply, live endpoint) require a running environment and cannot be verified from static code inspection alone.

---

_Verified: 2026-06-12_
_Verifier: Claude (gsd-verifier)_
