---
phase: quick-260612-pyo
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - apps/api/migrations/0028_skill_tier_config.sql
  - libs/sdk/src/genjishimada_sdk/skill.py
  - libs/sdk/src/genjishimada_sdk/users.py
  - apps/api/repository/skill_repository.py
  - apps/api/services/skill_service.py
  - apps/api/routes/v3/skill.py
  - apps/api/repository/community_repository.py
  - apps/api/tests/integration/test_skill.py
autonomous: true
requirements:
  - PYO-TIER-01  # migration 0028: skill.tier_config (boundaries, percentiles, computed_at)
  - PYO-TIER-02  # recompute_all computes boundaries via percentile_cont over skill_score>0
  - PYO-TIER-03  # tier+percentile on SkillSummaryResponse via width_bucket
  - PYO-TIER-04  # tier+percentile on CommunityLeaderboardResponse + leaderboard query
  - PYO-TIER-05  # GET /api/v3/skill/tiers (boundaries+percentiles+computed_at)
  - PYO-TIER-06  # population-floor guard (<20 non-zero -> everyone Unranked)
user_setup: []

must_haves:
  truths:
    - "Migration 0028 applies cleanly on a fresh test DB and seeds the default percentile array."
    - "After a recompute on a populated snapshot, skill.tier_config holds 6 strictly increasing boundary scores computed from skill_score > 0 rows."
    - "GET /api/v3/skill/users/{id} returns tier (1..7) and percentile for a scored player, and tier 0 / Unranked for a player with no eligible completions."
    - "Each community leaderboard row carries a tier consistent with its skill_score and the current boundaries; skill_rank and skill_score are unchanged."
    - "GET /api/v3/skill/tiers returns the current boundaries + percentiles + computed_at."
    - "Population-floor guard: fewer than 20 non-zero players -> boundaries empty -> everyone Unranked (tier 0), no crash."
  artifacts:
    - path: "apps/api/migrations/0028_skill_tier_config.sql"
      provides: "skill.tier_config single-row table + seeded default percentiles"
      contains: "CREATE TABLE IF NOT EXISTS skill.tier_config"
    - path: "apps/api/repository/skill_repository.py"
      provides: "compute_tier_boundaries, fetch_tier_config, fetch_snapshot_with_tier"
      contains: "percentile_cont"
    - path: "apps/api/services/skill_service.py"
      provides: "boundary recompute inside _do_recompute + get_tier_config + tier/percentile reads"
      contains: "compute_tier_boundaries"
    - path: "apps/api/routes/v3/skill.py"
      provides: "GET /skill/tiers endpoint"
      exports: ["get_tiers"]
    - path: "apps/api/repository/community_repository.py"
      provides: "tier + percentile columns on the leaderboard query"
      contains: "width_bucket"
  key_links:
    - from: "apps/api/services/skill_service.py::_do_recompute"
      to: "skill.tier_config"
      via: "SkillRepository.compute_tier_boundaries after replace_snapshot"
      pattern: "compute_tier_boundaries"
    - from: "apps/api/repository/community_repository.py"
      to: "skill.tier_config"
      via: "LEFT JOIN skill.tier_config + width_bucket(ss.skill_score, tc.boundaries)"
      pattern: "width_bucket"
---

<objective>
Add a percentile-based skill TIER system (integer icon ranks 1..7, 0 = Unranked) layered
on top of the existing numeric `skill_score` from Phase 13. Tiers are assigned by where a
player's `skill_score` falls in the CURRENT population distribution, so they stay correct
automatically as scores drift. Boundaries are derived from the live distribution (no
hardcoded score cutoffs) via Postgres `percentile_cont`; a player's tier is `width_bucket`
over those cached boundaries.

This is a NEW concept, fully SEPARATE from the existing Ninja..God `skill_rank` label and
from the scoring algorithm/weights — all of which are left completely untouched.

Purpose: Give the website a browsable tier legend + per-player tier badge without altering
the proven scoring math.
Output: Migration 0028, SDK fields, repository tier computation, service wiring inside the
single `recompute_all` path, `GET /skill/tiers`, leaderboard `tier`/`percentile`, and a new
integration test.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.planning/quick/260612-pyo-add-a-percentile-based-skill-tier-system/260612-pyo-TASK.md
@./CLAUDE.md

Skill: invoke/read `Skill("spike-findings-genjishimada")` for the scoring formula, input
query, and gotchas. The tier system does NOT change any of that math — it only buckets the
already-computed `skill_score`.

<key_decision name="flicker">
**Recompute boundaries on EVERY snapshot rebuild** (inside `_do_recompute`, after
`replace_snapshot`). Rationale: `recompute_all` is the single D-04 rebuild path (verify /
reject / suspicious-flag events + nightly backstop + PATCH config), and we MUST reuse it
without forking (TASK constraint, D-04). Computing boundaries in the same routine guarantees
`skill.tier_config` is always consistent with the snapshot that produced it. Tradeoff (note
in the SUMMARY): a player's tier can shift when the field around them moves even though their
own score is unchanged — acceptable for a display-only badge; if churn becomes a concern
later it can be gated to the nightly slot without a schema change.
</key_decision>

<key_decision name="tier_mapping">
6 boundary cut-points -> `width_bucket(score, boundaries)` returns 0..6 -> map to tier 1..7
by adding 1. A player with `skill_score = 0` or no snapshot row is tier 0 / Unranked
regardless of boundaries. When boundaries is empty (population floor not met), EVERYONE is
tier 0.
</key_decision>

<key_decision name="population_floor">
If fewer than 20 players have `skill_score > 0`, skip tiering: persist an EMPTY boundaries
array (`'{}'::float8[]`) so `width_bucket` is never called on a degenerate sample. Reads
treat empty boundaries (`cardinality(boundaries) = 0`) as "everyone Unranked".
</key_decision>

<interfaces>
<!-- Real symbols extracted from the codebase. Use these directly; no exploration needed. -->

Migration latest is `apps/api/migrations/0027_skill_score.sql` -> this is `0028`.
Migrations are auto-applied in sorted order by `apps/api/tests/conftest.py::_apply_sql_dir`
(MIGRATIONS_DIR), so 0028 is picked up automatically by the test DB. No conftest edits.

skill.snapshot columns (from 0027): user_id bigint PK, skill_score double precision,
maps_cleared int, video_clears int, hardest_raw double precision, breakdown jsonb,
computed_at timestamptz.

libs/sdk/src/genjishimada_sdk/skill.py:
  class SkillSummaryResponse(Struct): user_id:int, skill_score:float, maps_cleared:int,
    video_clears:int, hardest_raw:float    # ADD tier:int, percentile:float
  __all__ tuple — ADD "SkillTiersResponse".

libs/sdk/src/genjishimada_sdk/users.py:
  class CommunityLeaderboardResponse(Struct): ... skill_rank:str, skill_score:float,
    total_results:int    # ADD tier:int, percentile:float (place adjacent to skill_score)

apps/api/repository/skill_repository.py:
  SkillRepository(BaseRepository): fetch_skill_inputs, snapshot_is_empty, fetch_snapshot
    (SELECT * FROM skill.snapshot WHERE user_id=$1), replace_snapshot (TRUNCATE + executemany
    in a txn; Pool-vs-Connection acquire pattern), fetch_weights, update_weights.
    `self._get_connection(conn)`, `isinstance(_conn, Pool)`.

apps/api/services/skill_service.py:
  SkillService(BaseService).__init__(pool, state, skill_repo); `self._skill_repo`.
  recompute_all() -> guards -> while rerun: await self._do_recompute().
  _do_recompute(): fetch_weights -> fetch_skill_inputs -> group -> replace_snapshot(...).
  get_user_skill(user_id) -> SkillSummaryResponse (None row -> all-zero summary).
  provide_skill_service(state, skill_repo).

apps/api/routes/v3/skill.py:
  SkillController (path="/skill", tags=["Skill"]); dependencies skill_repo/skill_service.
  Existing GETs: /users/{user_id:int}, /users/{user_id:int}/breakdown, /config; PATCH /config.

apps/api/repository/community_repository.py::fetch_community_leaderboard (final SELECT ~208-233):
    coalesce(ss.skill_score, 0) AS skill_score,
    count(*) OVER () AS total_results
    FROM xp_tiers u ... LEFT JOIN skill.snapshot ss ON u.id = ss.user_id
    ORDER BY {sort_values} {sort_direction} LIMIT $1 OFFSET $2
  -- ADD a LEFT JOIN skill.tier_config tc ON TRUE and tier/percentile expressions.
  `sort_column` Literal in repo/service/route already includes "skill_score" — do NOT add
  "tier" to it (TASK: tier is display-only; skill_score sort already orders tiers).

app jsonb<->msgspec codec: apps/api/app.py::_async_pg_init. float8[] arrays decode to Python
list[float] natively; no codec needed for the boundaries/percentiles arrays.

DO NOT TOUCH: the `skill_rank` (Ninja..God) CASE; `community_repository.fetch_players_per_skill_tier`
(the rank-string tier in xp.py::PlayersPerSkillTierResponse — unrelated); the scorer math
(`_diff_weight`/`_map_score`/`_player_score`/`_player_breakdown`); `skill.weight_config`.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Migration 0028 + SDK tier fields</name>
  <files>apps/api/migrations/0028_skill_tier_config.sql, libs/sdk/src/genjishimada_sdk/skill.py, libs/sdk/src/genjishimada_sdk/users.py</files>
  <action>
Create apps/api/migrations/0028_skill_tier_config.sql (PYO-TIER-01) wrapped in BEGIN/COMMIT,
mirroring 0027's header-comment style. `CREATE SCHEMA IF NOT EXISTS skill;` (idempotent,
already created by 0027). `CREATE TABLE IF NOT EXISTS skill.tier_config` with columns:
  - id integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY
  - boundaries  float8[] NOT NULL DEFAULT '{}'::float8[]   -- 6 computed cut-points; empty until first qualifying recompute
  - percentiles float8[] NOT NULL                          -- 6 configurable percentiles; the ONLY tunable
  - computed_at timestamptz NOT NULL DEFAULT now()
Seed exactly ONE row idempotently (INSERT ... SELECT ... WHERE NOT EXISTS, like 0027's seed)
with `percentiles = ARRAY[0.50, 0.75, 0.90, 0.97, 0.99, 0.995]::float8[]` and empty
boundaries. NO hardcoded SCORE cutoffs — boundaries start empty and are filled by recompute.

In libs/sdk/.../skill.py: add `tier: int` and `percentile: float` to SkillSummaryResponse
(after `hardest_raw`) with docstring lines ("tier: percentile tier 1..7, 0 = Unranked";
"percentile: 0..1 population percentile of skill_score"). Add `SkillTiersResponse(Struct)`
with `boundaries: list[float]`, `percentiles: list[float]`, `computed_at: datetime` (import
`from datetime import datetime`), a full Google docstring, and add "SkillTiersResponse" to
`__all__` keeping the tuple alphabetically sorted (ruff RUF022).

In libs/sdk/.../users.py: add `tier: int` and `percentile: float` to
CommunityLeaderboardResponse adjacent to `skill_score` (before `total_results`) with
docstring lines. Both non-optional — the leaderboard SQL COALESCEs them (Task 3), so a value
is always present. Do NOT rename/reorder existing fields; leave `skill_rank` untouched.
  </action>
  <verify>
    <automated>uv run --env-file .env.local python -c "import pathlib; t=pathlib.Path('apps/api/migrations/0028_skill_tier_config.sql').read_text(); assert 'skill.tier_config' in t and 'percentiles' in t and '0.995' in t and 'boundaries' in t; from genjishimada_sdk.skill import SkillSummaryResponse, SkillTiersResponse; from genjishimada_sdk.users import CommunityLeaderboardResponse; r=SkillSummaryResponse(user_id=1, skill_score=0.0, maps_cleared=0, video_clears=0, hardest_raw=0.0, tier=0, percentile=0.0); assert r.tier==0; assert {'boundaries','percentiles','computed_at'} <= set(SkillTiersResponse.__struct_fields__); assert {'tier','percentile'} <= set(CommunityLeaderboardResponse.__struct_fields__); print('ok')"</automated>
  </verify>
  <done>0028 exists with skill.tier_config (boundaries float8[] default '{}', percentiles seeded with the default array, computed_at) and is idempotent; SDK exposes SkillSummaryResponse.tier/.percentile, SkillTiersResponse, and CommunityLeaderboardResponse.tier/.percentile; `just lint-sdk` clean.</done>
</task>

<task type="auto">
  <name>Task 2: Repository boundary computation + tier reads + service/route wiring (reuse recompute_all)</name>
  <files>apps/api/repository/skill_repository.py, apps/api/services/skill_service.py, apps/api/routes/v3/skill.py</files>
  <action>
Repository (skill_repository.py):
  - Add module constant `_TIER_POPULATION_FLOOR = 20` (PYO-TIER-06) with a comment that below
    this non-zero count tiers are skipped (sample too small to mint meaningful boundaries).
  - `async def compute_tier_boundaries(self, *, conn: Connection | None = None) -> None`
    (PYO-TIER-02): one UPDATE that reads the configured `percentiles` from the existing
    skill.tier_config row, and when the count of `skill_score > 0` snapshot rows is
    `>= _TIER_POPULATION_FLOOR` sets `boundaries` to the array of
    `percentile_cont(p) WITHIN GROUP (ORDER BY skill_score)` over `skill.snapshot WHERE
    skill_score > 0` for each percentile p (ascending), else sets `boundaries = '{}'::float8[]`;
    always sets `computed_at = now()`. Suggested shape (validate it yields a strictly
    increasing array — the Task 3 test asserts monotonicity; adjust grouping/ordering if not):
      WITH cfg AS (SELECT percentiles FROM skill.tier_config LIMIT 1),
           pop AS (SELECT count(*) AS n FROM skill.snapshot WHERE skill_score > 0),
           b AS (
             SELECT array(
               SELECT percentile_cont(p) WITHIN GROUP (ORDER BY ss.skill_score)
               FROM unnest((SELECT percentiles FROM cfg)) WITH ORDINALITY AS u(p, ord)
               CROSS JOIN skill.snapshot ss
               WHERE ss.skill_score > 0
               GROUP BY p, ord
               ORDER BY ord
             ) AS boundaries
           )
      UPDATE skill.tier_config SET
        boundaries = CASE WHEN (SELECT n FROM pop) >= $1
                          THEN (SELECT boundaries FROM b)
                          ELSE '{}'::float8[] END,
        computed_at = now();
    Bind `$1 = _TIER_POPULATION_FLOOR`.
  - `async def fetch_tier_config(self, *, conn=None) -> dict` (PYO-TIER-05):
    `SELECT boundaries, percentiles, computed_at FROM skill.tier_config LIMIT 1`;
    return `dict(row)` (float8[] -> list[float] natively).
  - `async def fetch_snapshot_with_tier(self, user_id: int, *, conn=None) -> dict | None`:
    select the snapshot row plus tier+percentile vs the cached boundaries, e.g.
      SELECT ss.*,
        CASE WHEN ss.skill_score <= 0 OR cardinality(tc.boundaries) = 0 THEN 0
             ELSE width_bucket(ss.skill_score, tc.boundaries) + 1 END AS tier,   -- PYO-TIER-03
        coalesce(
          (SELECT count(*) FROM skill.snapshot s2
             WHERE s2.skill_score > 0 AND s2.skill_score <= ss.skill_score)::float8
          / NULLIF((SELECT count(*) FROM skill.snapshot s3 WHERE s3.skill_score > 0), 0),
          0.0) AS percentile
      FROM skill.snapshot ss CROSS JOIN skill.tier_config tc
      WHERE ss.user_id = $1
    Return `dict(row)` or None. Keep the existing `fetch_snapshot` (used by the breakdown
    read path) UNCHANGED.

Service (skill_service.py):
  - In `_do_recompute`, AFTER `await self._skill_repo.replace_snapshot(snapshot_rows)`, call
    `await self._skill_repo.compute_tier_boundaries()` (PYO-TIER-02). This is the ONLY place
    boundaries are recomputed — it rides the single D-04 routine so verify/reject/flag events,
    the nightly backstop, and PATCH config all refresh boundaries. Do NOT fork the path. Add
    one comment noting the flicker decision (boundaries recompute every rebuild, by design).
  - `get_user_skill`: call `fetch_snapshot_with_tier`. None -> all-zero SkillSummaryResponse
    with `tier=0, percentile=0.0` (Unranked). Present -> `msgspec.convert(row,
    SkillSummaryResponse)` (the row now carries tier/percentile).
  - Add `async def get_tier_config(self) -> SkillTiersResponse` (PYO-TIER-05): import
    `SkillTiersResponse`; `return msgspec.convert(await self._skill_repo.fetch_tier_config(),
    SkillTiersResponse)`. Full Google docstring. No weight literals; no scorer changes.

Route (skill.py):
  - Import `SkillTiersResponse`. Add `@get(path="/tiers", summary="Get Skill Tier Config",
    description="Return the current tier boundaries, configured percentiles, and computed_at
    for rendering a tier legend. Public read; no new scope.")` handler `async def
    get_tiers(self, skill_service: SkillService) -> SkillTiersResponse: return await
    skill_service.get_tier_config()` with a Google docstring (PYO-TIER-05). NO
    `opt={"required_scopes": ...}` — public like the other skill GETs.

Full type annotations + Google docstrings on every new public method (basedpyright strict +
ruff ANN/D). `%s`-style logging only if any is added (none required).
  </action>
  <verify>
    <automated>uv run --env-file .env.local python -c "import inspect; import app; from repository.skill_repository import SkillRepository; from services.skill_service import SkillService; from routes.v3.skill import SkillController; assert all(hasattr(SkillRepository, m) for m in ('compute_tier_boundaries','fetch_tier_config','fetch_snapshot_with_tier')); assert hasattr(SkillService, 'get_tier_config'); assert 'compute_tier_boundaries' in inspect.getsource(SkillService._do_recompute); assert 'get_tiers' in dir(SkillController); print('ok')" && just lint-api
</automated>
  </verify>
  <done>`recompute_all` (the single D-04 path) recomputes boundaries every rebuild; `compute_tier_boundaries`/`fetch_tier_config`/`fetch_snapshot_with_tier` exist; `get_user_skill` returns tier+percentile (0/Unranked when no row); `GET /skill/tiers` is wired and public; no scorer/weight/skill_rank code changed; `just lint-api` clean (ruff + basedpyright strict, 0 errors).</done>
</task>

<task type="auto">
  <name>Task 3: Leaderboard tier/percentile column + tier integration tests</name>
  <files>apps/api/repository/community_repository.py, apps/api/tests/integration/test_skill.py</files>
  <action>
Leaderboard (community_repository.py::fetch_community_leaderboard) — PYO-TIER-04:
  - In the final SELECT (the one with `coalesce(ss.skill_score, 0) AS skill_score` and
    `count(*) OVER () AS total_results`), add two projected columns adjacent to skill_score:
      CASE WHEN coalesce(ss.skill_score, 0) <= 0 OR cardinality(tc.boundaries) = 0 THEN 0
           ELSE width_bucket(ss.skill_score, tc.boundaries) + 1 END AS tier,
      coalesce(
        (SELECT count(*) FROM skill.snapshot s2
           WHERE s2.skill_score > 0 AND s2.skill_score <= ss.skill_score)::float8
        / NULLIF((SELECT count(*) FROM skill.snapshot s3 WHERE s3.skill_score > 0), 0),
        0.0) AS percentile,
  - Add `LEFT JOIN skill.tier_config tc ON TRUE` to the final query's JOIN list (next to the
    existing `LEFT JOIN skill.snapshot ss ON u.id = ss.user_id`). tier_config is a single row,
    so the cross-join is at most 1:1.
  - Do NOT touch the `skill_rank` CASE, the `sort_column` Literal (no "tier"), the
    `skill_rank_data`/`highest_ranks` CTEs, or the `{sort_values} {sort_direction}` ORDER BY.
    `msgspec.convert(rows, list[CommunityLeaderboardResponse])` in community_service picks up
    the new fields automatically (added in Task 1).

Tests (apps/api/tests/integration/test_skill.py) — extend, do NOT rewrite. Reuse the existing
`seed` factory (`make_user`/`make_map`/`make_completion`) and the `_recompute(asyncpg_pool)`
helper. Add one class `TestSkillTiers` (marked by the file's module-level
`pytestmark = [integration, domain_skill]`) covering:
  1. test_tier_assignment_and_legend (PYO-TIER-02/03/05): seed >= 20 users each with one
     verified video completion across a spread of map difficulties/times so non-zero scores
     vary; `await _recompute`. Assert `GET /skill/tiers` returns 6 `percentiles` and 6
     `boundaries`, and boundaries are strictly increasing (monotonicity). Assert the
     top-scoring user's `GET /skill/users/{id}` has `tier >= 1` (1..7) and `0 <= percentile
     <= 1`. Assert the per-user `tier` from `GET /skill/users/{id}` matches that row's `tier`
     in `GET /community/leaderboard?sort_column=skill_score&sort_direction=desc` (consistency
     PYO-TIER-04). Confirm `skill_rank` and `skill_score` are still present/unchanged on
     leaderboard rows.
  2. test_unranked_zero_eligible (PYO-TIER-03, Unranked/0 case): a user with no completions
     -> `GET /skill/users/{id}` returns `tier == 0` and `skill_score == 0`; its leaderboard
     row (if present) has `tier == 0`.
  3. test_population_floor_fallback (PYO-TIER-06): TRUNCATE skill.snapshot, seed only a few
     (< 20) scored users, `await _recompute`. Assert `GET /skill/tiers` `boundaries == []`
     (empty) and every scored user's `GET /skill/users/{id}` returns `tier == 0` (everyone
     Unranked, no crash).
  Use `int(uuid4().int % 9_000_000_000)` message ids like the existing tests. For the >=20
  case, loop a range and vary `raw`/`time` to produce a non-degenerate distribution. Keep
  assertions tolerant of float rounding (no exact-equality on percentile).
  </action>
  <verify>
    <automated>uv run --env-file .env.local pytest apps/api/tests/integration/test_skill.py apps/api/tests/services/test_skill_service.py -o addopts="" -p no:cacheprovider -q</automated>
  </verify>
  <done>Leaderboard rows carry `tier`+`percentile` consistent with skill_score and current boundaries; `skill_rank`/`skill_score` unchanged. New `TestSkillTiers` asserts tier assignment, the Unranked/0 case, boundary monotonicity, and the population-floor fallback. The full skill test command (integration + service) passes with testmon disabled; `just lint-api` clean.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| client -> GET /skill/tiers, /skill/users/{id} | Public reads (no auth, like other skill GETs); only return cached, non-sensitive tier/boundary data. |
| client -> GET /community/leaderboard | Existing public read; new tier/percentile columns are derived from already-public skill_score. |
| service -> Postgres (raw SQL) | tier boundary/percentile SQL must use bound params, never string interpolation of user input. |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-pyo-01 | Tampering | `compute_tier_boundaries` / leaderboard SQL | mitigate | All values bound positionally ($1 = population floor); `percentiles` come from the DB config row, never the request. No f-string interpolation of caller data into the tier SQL (the only interpolated tokens in the leaderboard query are the pre-existing allow-listed `{sort_values}`/`{sort_direction}`, untouched). |
| T-pyo-02 | Information Disclosure | GET /skill/tiers | accept | Boundaries + percentiles are non-sensitive aggregate display data (a public tier legend); intentionally unauthenticated per the TASK (no new scope). |
| T-pyo-03 | Denial of Service | `percentile_cont` over snapshot on every rebuild | accept | Snapshot is small (~hundreds of rows, lean per-player cache); one extra aggregate UPDATE per rebuild is negligible vs the existing full recompute. Population floor avoids degenerate work on tiny samples. |
| T-pyo-SC | Tampering | npm/pip/cargo installs | mitigate | No new packages added (pure SQL + existing msgspec/asyncpg/Litestar); no install step, so no package legitimacy gate required. |
</threat_model>

<verification>
- Migration: 0028 applies cleanly on the fresh test DB (auto-applied by conftest in sorted
  order); `skill.tier_config` exists with one seeded row whose `percentiles` is the 6-element
  default array and `boundaries` starts empty.
- Recompute: after a populated recompute (>=20 non-zero), `skill.tier_config.boundaries` holds
  6 strictly increasing float8 cut-points derived from `skill_score > 0` rows.
- Reads: `GET /skill/users/{id}` returns tier 1..7 + percentile for a scored player; tier 0 /
  Unranked for a zero-eligible player. `GET /skill/tiers` returns boundaries + percentiles +
  computed_at.
- Leaderboard: each row's `tier` is consistent with its `skill_score` and the current
  boundaries; `skill_rank` (Ninja..God) and `skill_score` are byte-for-byte unchanged.
- Floor: < 20 non-zero players -> boundaries empty -> everyone Unranked, no crash.
- Gates: `just lint-api` (ruff + basedpyright strict, 0 errors) AND the full skill test
  command pass:
  `uv run --env-file .env.local pytest apps/api/tests/integration/test_skill.py apps/api/tests/services/test_skill_service.py -o addopts="" -p no:cacheprovider -q`
- Untouched: no edits to the scorer math, `skill.weight_config`, the `skill_rank` CASE, or
  `fetch_players_per_skill_tier`. No hardcoded score cutoffs anywhere (grep: the only tunable
  is the seeded `percentiles` array in 0028).
</verification>

<success_criteria>
- All three tasks' `<done>` conditions met.
- Every acceptance criterion in `260612-pyo-TASK.md` satisfied (migration, boundary compute,
  user tier/percentile, leaderboard tier/percentile, /skill/tiers, no hardcoded cutoffs,
  population floor).
- The single `recompute_all` / `_do_recompute` routine is reused for boundary computation —
  the rebuild path is NOT forked (D-04).
- Flicker decision (recompute boundaries every rebuild) is implemented and documented in the
  SUMMARY with its churn tradeoff.
- `just lint-api` and the full skill test command both pass.
</success_criteria>

<output>
Create `.planning/quick/260612-pyo-add-a-percentile-based-skill-tier-system/260612-pyo-SUMMARY.md` when done.
In the SUMMARY, explicitly state the flicker decision taken (boundaries recompute on every
snapshot rebuild) and its churn tradeoff.
</output>
