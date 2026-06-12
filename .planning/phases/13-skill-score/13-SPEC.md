# Phase 13: Skill Score — Specification

**Created:** 2026-06-12
**Ambiguity score:** 0.134 (gate: ≤ 0.20)
**Requirements:** 9 locked

## Goal

Genji Parkour gains a numeric **skill score** — a per-player measure of in-game
*performance* (clearing hard maps, fast relative to the field) computed from
verified non-legacy completions — that is fully separate from XP and from the
existing Ninja→God completion-rank label, persisted to a snapshot table, surfaced
as a sortable column on the existing community leaderboard, and served via new
`/api/v3/skill/*` endpoints, using the spike-validated algorithm and community-tuned
default weights.

## Background

No skill code exists today: no `skill` schema, no `SkillService`, no
`skill_repository.py`, no `routes/v3/skill.py`, no SDK `skill.py` module, no skill
snapshot table. Latest migration is `0026`, so this phase introduces `0027`.

The community leaderboard (`GET /api/v3/community/leaderboard`,
`community_repository.py`, `CommunityLeaderboardResponse` in
`libs/sdk/.../users.py:214`) already has a `skill_rank` field — but that is a
**derived difficulty-tier label** (Ninja → God, from the hardest official map a
player has cleared). It is *not* the new numeric skill score and must remain
untouched. XP (`lootbox.xp`) and the completion-count rank tiers also remain
untouched.

Spikes 001/002/003 (see `Skill("spike-findings-genjishimada")`) validated the
end-to-end design against real imported data (17,508 verified non-legacy
completions, 1,341 maps, 272 players → ~14,788 best-rows / 261 players / 786 maps):
the single input query (per-(user,map) best run carrying every signal), the hybrid
scoring algorithm, farming-resistance break-even math, and the adopted weights
(domain-expert tuned). This phase ports those proven spike artifacts
(`sources/001-skill-input-query/query.py`, `sources/002-scoring-farming-resistance/score.py`)
into Genji's Litestar + AsyncPG + msgspec architecture.

## Requirements

1. **Skill schema & snapshot table (migration 0027)**: A new `skill` PostgreSQL schema with a snapshot table storing each player's computed skill score plus the summary fields the leaderboard/profile need.
   - Current: No `skill` schema or snapshot table exists; latest migration is `0026`
   - Target: Migration `0027` creates the `skill` schema and a snapshot table (per-user: skill score, maps-cleared count, video-clear count, hardest raw difficulty, computed-at timestamp) that the community leaderboard can JOIN and sort/paginate by in SQL
   - Acceptance: `0027` applies cleanly on a fresh test DB; the snapshot table exists in the `skill` schema; a player row can be written and read back with its score

2. **Skill input query (repository)**: A repository method returns one row per `(user, map)` — the player's fastest verified non-legacy completion — carrying every scoring signal.
   - Current: No skill repository; the per-(user,map) best-run query exists only as the spike script `sources/001-skill-input-query/query.py`
   - Target: `skill_repository` method ports the 4-CTE query (`best` → `field` → `video_ranked` → `fully`) over `core.completions ⋈ core.maps ⋈ core.users ⋈ users.overwatch_usernames ⋈ maps.medals`, emitting `raw_difficulty::float8`, `time::float8`, `fully_verified` (`completion = FALSE`), `field_size`, `field_rank`, `video_rank`, `time_pct`, computed `medal`, `has_medal_thresholds`, and `suspicious`
   - Acceptance: For a player who follows the spike's known fixtures, the query returns exactly the fastest eligible run per map; rows with `c.verified = FALSE`, `c.legacy = TRUE`, `m.archived = TRUE`, `m.code IS NULL`, or suspicious-flagged users are absent; `time_pct = 1.0` for the fastest run in each field

3. **Eligibility filtering**: Only verified, non-legacy, non-archived, coded, non-suspicious completions contribute; one best (fastest) completion per `(user, map)`.
   - Current: No eligibility logic exists for skill
   - Target: Filter is `c.verified = TRUE AND c.legacy = FALSE AND m.archived = FALSE AND m.code IS NOT NULL` and excludes users with `users.suspicious_flags`; `DISTINCT ON (user_id, map_id) ORDER BY time ASC` enforces one best run
   - Acceptance: A user with two verified runs on the same map contributes only the faster; flipping a contributing run to `verified = FALSE` removes it from that player's inputs on next recompute

4. **Scoring algorithm (SkillService)**: The hybrid floor + video-gated proof multipliers + diminishing-returns scorer, ported faithfully from the spike.
   - Current: No `SkillService`; scorer exists only as `sources/002-scoring-farming-resistance/score.py`
   - Target: `SkillService` computes per-map FLOOR `diff_base ** (raw_difficulty - 1.5)`; partial (screenshot) clears score `floor * partial_factor`; fully-verified (video) clears score `floor * time_mult * medal_mult * wr_mult` with field-size shrink `field/(field+shrink_k)`; player total = `Σ s_i / i**gamma` over per-map scores sorted descending
   - Acceptance: Given the spike's cached `skill_inputs.json`, `SkillService` reproduces the spike scorer's player totals (same ordering and values within float tolerance); a partial clear receives no time/medal/WR multiplier; `gamma` lowered toward 0 measurably reduces farming resistance (break-even map count drops), confirming the dial is wired

5. **DB-configurable weights**: All scoring weights live in a DB config row seeded with the adopted defaults; nothing is hardcoded.
   - Current: Weights exist only as literals in the spike scorer
   - Target: A `skill` config table holds `diff_base=1.44, gamma=0.68, time_bonus=0.55, shrink_k=10.0, wr_bonus=0.10, partial_factor=0.60, medal_gold=1.12, medal_silver=1.07, medal_bronze=1.03`, read by `SkillService` at compute time
   - Acceptance: Editing a weight in the config table and recomputing changes scores accordingly; no scoring weight is a hardcoded literal in service/repository code (defaults live as seed data / migration values)

6. **Community leaderboard skill column**: The existing community leaderboard gains the numeric skill score as a sortable, paginated column.
   - Current: `GET /api/v3/community/leaderboard` exposes `skill_rank` (Ninja→God label) but no numeric skill score
   - Target: `CommunityLeaderboardResponse` gains a `skill_score` field; the leaderboard query JOINs the snapshot table; `sort_column='skill_score'` orders the board by skill, paginated like existing sorts; the `skill_rank` label and all other columns are unchanged
   - Acceptance: `GET /community/leaderboard?sort=skill_score` returns players ordered by descending skill score with working pagination; the same call without skill sort still returns the existing columns including the untouched `skill_rank` label

7. **Skill endpoints**: New `/api/v3/skill/*` routes expose per-user score, per-user breakdown, and weight config.
   - Current: No `routes/v3/skill.py`
   - Target: `GET /api/v3/skill/users/{id}` (total score + summary), `GET /api/v3/skill/users/{id}/breakdown` (per-map `raw_score`, gamma-decayed `contribution`, badges: video / Gold|Silver|Bronze / WR), `GET /api/v3/skill/config` (current weights), `PATCH /api/v3/skill/config` (update weights, superuser-only)
   - Acceptance: All four endpoints return 200 with msgspec-typed bodies for a known player; `breakdown` rows sum (after gamma decay) to the player's total from the score endpoint; `PATCH /skill/config` returns 401/403 for a non-superuser and succeeds for a superuser

8. **Freshness on verification change**: The snapshot reflects verification status changes before the next leaderboard read, recomputing the affected map's full field (field-relativity).
   - Current: No snapshot, no refresh path
   - Target: When a completion's verification status changes (verify / reject / suspicious-flag), the snapshot is recomputed such that the next leaderboard/score read reflects it; because `time_pct` is relative to a map's field, the recompute re-evaluates every player who has a run on the affected map. Exact mechanism (event consumer vs lazy-on-read vs poller) is a discuss-phase decision; the *contract* is locked here. A full recompute (~90ms / 261 players at current scale) is an acceptable implementation
   - Acceptance: After a pending run on map X is verified, a leaderboard/score read reflects the new contribution without a manual rebuild; a second player on map X whose percentile shifts also shows an updated score after the same event

9. **Symmetric score removal**: Rejection, un-verification, and suspicious-flagging actively remove the contribution on recompute.
   - Current: No removal path
   - Target: A previously-verified run that is later rejected/un-verified, or a user that becomes suspicious-flagged, drops the corresponding contribution from the player's score (and updates the affected map's field for others) on the next recompute — symmetric with addition, same recompute path
   - Acceptance: Verifying a run raises a player's score; subsequently rejecting that run returns the score to (within float tolerance of) its pre-verification value; suspicious-flagging a user drops their skill score to 0

## Boundaries

**In scope:**
- Migration `0027`: `skill` schema, snapshot table, weight config table seeded with adopted defaults
- `skill_repository` — input query (port of spike 001) and snapshot read/write
- `SkillService` — scoring algorithm (port of spike 002), reading weights from DB config
- SDK skill structs (request/response/summary/breakdown) in `libs/sdk/.../skill.py`
- `routes/v3/skill.py` — `GET /skill/users/{id}`, `GET /skill/users/{id}/breakdown`, `GET /skill/config`, `PATCH /skill/config`
- Community leaderboard integration — `skill_score` sortable column added to existing endpoint + `CommunityLeaderboardResponse`
- Snapshot freshness on verification change + symmetric removal (contract; mechanism chosen in discuss-phase)

**Out of scope:**
- Discord bot slash commands for skill (e.g. `/skill`) — later phase; this is API-only
- Website skill leaderboard UI and admin weight-tuning dashboard — later phase; the spike slider tool (`003-leaderboard-feel`) stays a spike artifact for re-tuning
- The existing XP system (`lootbox.xp`) and Ninja→God completion-rank tiers — untouched by design
- The existing `skill_rank` label on the community leaderboard — kept as-is alongside the new numeric column
- Medal-threshold backfill — uses existing `maps.medals` data as-is (only 90/1341 maps have thresholds; they are bonus-only)
- A new auth scope for config — superuser/admin guard is reused, no new scope minted

## Constraints

- **Separate from XP and rank tiers**: skill score is a new computation, never derived from `lootbox.xp` or completion-count rank tiers; those tables/values are not modified.
- **`raw_difficulty` (0–10 numeric), never the text tier** — continuous weighting avoids cliff effects.
- **Never compare raw `time` across maps** — always use `time_pct` (percentile vs the map's own field); raw times are per-map units (e.g. `6094.92` and `28.54` coexist).
- **`completion` flag = verification depth** (load-bearing schema fact, confirmed against `migrations/0001_init.sql:482` and `completions_repository.py:60-189`): `completion = TRUE` → partial (screenshot-only), `completion = FALSE` → full (video, ranked + medal-eligible). Proof multipliers apply **only** to `completion = FALSE` rows.
- **`gamma ≥ 0.5` always (default 0.68)** — `gamma = 0` reduces to a farmable pure sum; must never be the shipped default.
- **Field-size shrink required** — `shrink = field/(field+shrink_k)`, `shrink_k = 10` keeps tiny-field "wins" near-neutral; do not drop it.
- **Postgres `FILTER` is aggregate-only** — rank the video (`completion = FALSE`) set in its own CTE and `LEFT JOIN` it back; `rank() OVER (...) FILTER (...)` is invalid.
- **Scale / performance**: at current scale a full recompute is ~261 players in ~90ms; acceptable. The community leaderboard endpoint itself remains paginated.
- **Tech stack**: Litestar + AsyncPG + msgspec, raw SQL (no ORM), three-layer Controller→Service→Repository, `/api/v3/*` prefix — follow existing Genji conventions.

## Acceptance Criteria

- [ ] Migration `0027` applies cleanly on a fresh test DB and creates the `skill` schema, snapshot table, and seeded weight config table
- [ ] Input query returns one fastest verified-non-legacy run per `(user, map)`, excluding unverified/legacy/archived/codeless/suspicious rows, with `time_pct = 1.0` for each field's fastest run
- [ ] `SkillService` reproduces the spike scorer's totals (ordering + values within float tolerance) on the spike's `skill_inputs.json`
- [ ] Partial (screenshot) clears receive floor-only score; video clears receive time/medal/WR multipliers; lowering `gamma` measurably lowers farming resistance
- [ ] All scoring weights are read from the DB config; no weight is a hardcoded literal in service/repository code
- [ ] `GET /community/leaderboard?sort=skill_score` returns players ordered by descending skill score with working pagination; the `skill_rank` label column is unchanged
- [ ] `GET /skill/users/{id}`, `GET /skill/users/{id}/breakdown`, `GET /skill/config` return 200 with msgspec-typed bodies; breakdown contributions sum to the user's total after gamma decay
- [ ] `PATCH /skill/config` succeeds for a superuser and is rejected (401/403) for a non-superuser
- [ ] Verifying a pending run updates the submitter's score AND other players' scores on the same map on the next read, with no manual rebuild
- [ ] Rejecting a previously-verified run returns the player's score to its pre-verification value; suspicious-flagging a user drops their skill score to 0
- [ ] A player with zero eligible completions appears on the skill-sorted board with an explicit score of 0 (ranked last), and `GET /skill/users/{id}` returns 0 with an empty breakdown

## Ambiguity Report

| Dimension          | Score | Min  | Status | Notes                                                        |
|--------------------|-------|------|--------|--------------------------------------------------------------|
| Goal Clarity       | 0.92  | 0.75 | ✓      | Algorithm, weights, data filters locked by spikes 001/002/003 |
| Boundary Clarity   | 0.88  | 0.70 | ✓      | API-only; bot/frontend deferred; XP + Ninja→God label untouched |
| Constraint Clarity | 0.80  | 0.65 | ✓      | Freshness contract + field-relativity + gamma floor locked    |
| Acceptance Criteria| 0.82  | 0.70 | ✓      | 11 pass/fail criteria; endpoints + removal + empty-player pinned |
| **Ambiguity**      | 0.134 | ≤0.20| ✓      |                                                              |

Status: ✓ = met minimum, ⚠ = below minimum (planner treats as assumption)

## Interview Log

| Round | Perspective      | Question summary                          | Decision locked                                                                 |
|-------|------------------|-------------------------------------------|---------------------------------------------------------------------------------|
| 0     | Researcher       | What's phase 13 and what exists?          | Skill score from spikes 001/002/003; no skill code exists; migration → 0027     |
| 1     | Boundary/Simplifier | Scope? compute model? weight storage?  | API-only vertical; (initially) on-demand; weights in DB config table             |
| 2     | Boundary Keeper  | Which `/skill/*` endpoints?               | User redirected: surface skill on the **existing community leaderboard**, not a standalone one |
| 3     | Boundary Keeper  | Sortable LB column? standalone endpoints? | Sortable → **snapshot/cache back in scope**; ship per-user score + breakdown + config; superuser-guarded config |
| 4     | Failure Analyst  | Snapshot freshness? score removal? empties? | Fresh on **verification** change (not submission), recompute affected map's field; removal in scope; empty players = score 0, present |

---

*Phase: 13-skill-score*
*Spec created: 2026-06-12*
*Next step: /gsd:discuss-phase 13 — implementation decisions (refresh mechanism: event consumer vs lazy-on-read vs poller; snapshot table shape; breakdown struct; SQL vs app-layer scoring for the leaderboard join)*
