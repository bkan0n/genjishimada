---
phase: quick-260612-vtt
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - apps/api/migrations/0028_skill_tier_config.sql
  - libs/sdk/src/genjishimada_sdk/skill.py
  - libs/sdk/src/genjishimada_sdk/users.py
  - apps/api/services/skill_service.py
  - apps/api/services/exceptions/skill.py
  - apps/api/repository/community_repository.py
  - apps/api/services/community_service.py
  - apps/api/tests/services/test_skill_service.py
  - apps/api/tests/integration/test_skill.py
autonomous: true
requirements: [VTT-TIER-8]

must_haves:
  truths:
    - "skill.tier_config seeds 7 percentiles, so width_bucket yields integer tiers 1-8 (tier 0 = Unranked)."
    - "A single int->name map (0=Unranked .. 8=Champion) is the only source of truth, reused by both the leaderboard rows and SkillSummaryResponse."
    - "GET /skill/users/{id} returns skill_tier_name alongside the integer tier."
    - "The community leaderboard rows expose skill_tier, skill_percentile, skill_score, and skill_tier_name (renamed from tier/percentile)."
    - "SkillService.update_tier_config validates exactly 7 percentiles; InvalidPercentilesError message and SDK docstrings say 7."
    - "The percentile-based derivation and the existing scorer are untouched."
  artifacts:
    - path: "apps/api/migrations/0028_skill_tier_config.sql"
      provides: "7-percentile seed array, comments referencing 7 boundaries / tiers 1-8"
      contains: "ARRAY[0.50"
    - path: "libs/sdk/src/genjishimada_sdk/skill.py"
      provides: "SKILL_TIER_NAMES map + skill_tier_name helper; SkillSummaryResponse.skill_tier_name; 'exactly 7' docstrings"
      contains: "SKILL_TIER_NAMES"
    - path: "libs/sdk/src/genjishimada_sdk/users.py"
      provides: "CommunityLeaderboardResponse with skill_tier, skill_percentile, skill_tier_name"
      contains: "skill_tier_name"
    - path: "apps/api/services/skill_service.py"
      provides: "_TIER_PERCENTILE_COUNT = 7 + skill_tier_name population on summary"
      contains: "_TIER_PERCENTILE_COUNT = 7"
  key_links:
    - from: "apps/api/services/skill_service.py"
      to: "genjishimada_sdk.skill.skill_tier_name"
      via: "import + call when building SkillSummaryResponse"
      pattern: "skill_tier_name"
    - from: "apps/api/services/community_service.py"
      to: "genjishimada_sdk.skill.skill_tier_name"
      via: "map int skill_tier -> name onto each leaderboard row before convert"
      pattern: "skill_tier_name"
    - from: "apps/api/repository/community_repository.py"
      to: "CommunityLeaderboardResponse"
      via: "SQL aliases skill_tier / skill_percentile"
      pattern: "AS skill_tier"
---

<objective>
Expand the skill-score tier system from 7 to 8 named tiers plus Unranked. Seed
7 percentiles (was 6) so `width_bucket` mints integer tiers 1-8 with tier 0
reserved for Unranked; add a single source-of-truth int->name map and expose
the mapped string name on both the community leaderboard rows and the per-user
skill summary; and rename the new leaderboard `tier`/`percentile` columns to
`skill_tier`/`skill_percentile` (keeping `skill_score`).

Purpose: Give the website a browsable, named tier ladder (Bronze..Champion)
without touching the scoring formula or the percentile-based derivation.

Output: Edited migration 0028, updated SDK structs + name map, service
validation bumped to "exactly 7", renamed leaderboard columns + name exposure,
and updated tests covering 8 tiers, Unranked-at-0, the new field names, and the
name mapping.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@CLAUDE.md

Invoke `Skill("spike-findings-genjishimada")` before editing — it carries the
scoring formula, tier-config patterns, constraints, and gotchas. The existing
scorer (`SkillService._map_score` / `_player_score` / `_player_breakdown`) and
the percentile-based boundary derivation (`SkillRepository.compute_tier_boundaries`,
`width_bucket(skill_score, boundaries) + 1`) MUST remain UNTOUCHED.

<interfaces>
<!-- Current contracts the executor must edit. Extracted from the codebase. -->

Migration seed (apps/api/migrations/0028_skill_tier_config.sql:30-32) — currently 6:
  INSERT INTO skill.tier_config (boundaries, percentiles)
  SELECT '{}'::float8[], ARRAY[0.50, 0.75, 0.90, 0.97, 0.99, 0.995]::float8[]
  WHERE NOT EXISTS (SELECT 1 FROM skill.tier_config);
  Comments at lines 3-4, 17-18, 22-23 reference "icon ranks 1..7", "6 computed cut-points",
  "6 configurable percentiles" — update narrative to 7 boundaries / tiers 1..8.

Service (apps/api/services/skill_service.py):
  _TIER_PERCENTILE_COUNT = 6                  # -> 7
  update_tier_config(): `if len(percentiles) != _TIER_PERCENTILE_COUNT: raise InvalidPercentilesError(...)`
  get_user_skill(): builds SkillSummaryResponse(... tier=..., percentile=...) for both the
    no-row (tier=0) path and the msgspec.convert(row, SkillSummaryResponse) path.
  Docstring on update_tier_config currently says "exactly 6 values".

Exception (apps/api/services/exceptions/skill.py):
  InvalidPercentilesError docstring says "not exactly 6 values".

SDK (libs/sdk/src/genjishimada_sdk/skill.py):
  SkillTiersUpdateRequest docstring: "exactly 6 values", "The 6 replacement percentiles".
  SkillSummaryResponse fields: user_id, skill_score, maps_cleared, video_clears,
    hardest_raw, tier:int, percentile:float  (docstring: "tier 1..7", needs skill_tier_name).
  SkillTiersResponse docstring: "6 computed cut-point scores", "6 configured percentiles".

Repository SQL (apps/api/repository/community_repository.py:222-229) — leaderboard SELECT:
  coalesce(ss.skill_score, 0) AS skill_score,
  CASE WHEN ... THEN 0 ELSE width_bucket(ss.skill_score, tc.boundaries) + 1 END AS tier,   # -> AS skill_tier
  coalesce(... ) AS percentile,                                                              # -> AS skill_percentile
  (skill_repository.py fetch_snapshot_with_tier returns `tier`/`percentile` keys consumed by
   msgspec.convert -> SkillSummaryResponse; those struct field names stay `tier`/`percentile`.)

SDK (libs/sdk/src/genjishimada_sdk/users.py:214-251) — CommunityLeaderboardResponse:
  ... tier: int  percentile: float ...   # -> skill_tier: int, skill_percentile: float, + skill_tier_name: str

Community service (apps/api/services/community_service.py:62-71):
  rows = await self._community_repo.fetch_community_leaderboard(...)
  return msgspec.convert(rows, list[CommunityLeaderboardResponse])
  (rows are list[dict]; mutate each dict to add skill_tier_name before convert.)

Service test (apps/api/tests/services/test_skill_service.py:193-241):
  6-element arrays in reject tests; round-trip decodes a 6-element percentiles array;
  no-row expected summary asserts tier=0/percentile=0.0 (will need skill_tier_name="Unranked").

Integration test (apps/api/tests/integration/test_skill.py):
  ~604-690 (TestSkillTiers): asserts len(percentiles)==6, len(boundaries)==6, 1<=tier<=7,
    leaderboard rows carry "tier"/"skill_rank"/"skill_score".
  ~698-759 (TestTiersPatch): _VALID and _SEEDED_DEFAULT are 6-element arrays;
    asserts len(boundaries_before/after)==6.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Seed 7 percentiles, add the int->name map, bump validation to "exactly 7", add skill_tier_name to the summary</name>
  <files>apps/api/migrations/0028_skill_tier_config.sql, libs/sdk/src/genjishimada_sdk/skill.py, apps/api/services/skill_service.py, apps/api/services/exceptions/skill.py</files>
  <behavior>
    - SKILL_TIER_NAMES maps exactly {0:Unranked, 1:Bronze, 2:Silver, 3:Gold, 4:Emerald, 5:Diamond, 6:Ascendant, 7:Elite, 8:Champion}; skill_tier_name(0)=="Unranked", skill_tier_name(8)=="Champion".
    - update_tier_config raises InvalidPercentilesError for a 6-element array and for an 8-element array; accepts a 7-element strictly-increasing in-(0,1) array.
    - get_user_skill on a no-row user returns skill_tier_name=="Unranked" with tier==0.
  </behavior>
  <action>
    Edit migration 0028 IN PLACE (local-only, unpushed — do NOT create a new migration). Change the seed array at lines 30-32 from the 6-value `ARRAY[0.50, 0.75, 0.90, 0.97, 0.99, 0.995]` to a 7-value strictly-increasing array in (0,1): insert one additional cut-point so width_bucket yields tiers 1-8 (e.g. `ARRAY[0.50, 0.70, 0.85, 0.93, 0.97, 0.99, 0.995]` — 7 ascending values, keep the existing tail). Update the file's narrative comments (lines 3-4, 17-18, 22-23) from "icon ranks 1..7" / "6 computed cut-points" / "6 configurable percentiles" to 7 boundaries producing tiers 1..8, 0 = Unranked. Do NOT change the boundaries default (stays empty `'{}'`).

    In libs/sdk skill.py, add the SINGLE source-of-truth map `SKILL_TIER_NAMES: dict[int, str]` with exactly 0=Unranked,1=Bronze,2=Silver,3=Gold,4=Emerald,5=Diamond,6=Ascendant,7=Elite,8=Champion, plus a helper `def skill_tier_name(tier: int) -> str` returning `SKILL_TIER_NAMES.get(tier, "Unranked")` (Google docstring). Export both `SKILL_TIER_NAMES` and `skill_tier_name` in `__all__`. Add a `skill_tier_name: str` field to `SkillSummaryResponse` and document it. Update the SkillSummaryResponse `tier` docstring to "1..8", and update SkillTiersUpdateRequest / SkillTiersResponse docstrings from "6" to "7" (exactly 7 values / 7 cut-points / 7 configured percentiles).

    In skill_service.py: change `_TIER_PERCENTILE_COUNT = 6` to `7`; update the `update_tier_config` docstring "exactly 6 values" -> "exactly 7 values" (the validation already uses the constant). Import `skill_tier_name` from genjishimada_sdk.skill. In `get_user_skill`, set `skill_tier_name` on BOTH return paths: the no-row path passes `skill_tier_name="Unranked"` (tier 0); the row path computes the name from the row's integer tier — convert the row to SkillSummaryResponse, then either pass the name into the construction or build the struct with `skill_tier_name=skill_tier_name(int(row["tier"]))`. Do not touch fetch_snapshot_with_tier or any scoring code.

    In services/exceptions/skill.py: update the InvalidPercentilesError docstring "not exactly 6 values" -> "not exactly 7 values".
  </action>
  <verify>
    <automated>cd apps/api && uv run python -c "from genjishimada_sdk.skill import SKILL_TIER_NAMES, skill_tier_name; assert SKILL_TIER_NAMES[0]=='Unranked' and SKILL_TIER_NAMES[8]=='Champion' and len(SKILL_TIER_NAMES)==9 and skill_tier_name(99)=='Unranked'; from services.skill_service import _TIER_PERCENTILE_COUNT; assert _TIER_PERCENTILE_COUNT==7; print('ok')"</automated>
  </verify>
  <done>Migration seeds 7 percentiles with updated comments; SKILL_TIER_NAMES + skill_tier_name exist and are exported; SkillSummaryResponse has skill_tier_name; _TIER_PERCENTILE_COUNT==7; InvalidPercentilesError + SDK docstrings say "7".</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Rename leaderboard columns to skill_tier/skill_percentile and expose skill_tier_name</name>
  <files>apps/api/repository/community_repository.py, libs/sdk/src/genjishimada_sdk/users.py, apps/api/services/community_service.py</files>
  <behavior>
    - A leaderboard row dict from fetch_community_leaderboard carries keys skill_tier and skill_percentile (no longer tier / percentile), and skill_score unchanged.
    - get_community_leaderboard returns CommunityLeaderboardResponse rows whose skill_tier_name matches skill_tier_name(skill_tier) for every row (Unranked at skill_tier 0).
  </behavior>
  <action>
    In community_repository.py (the fetch_community_leaderboard SELECT, ~lines 222-229): rename the two output aliases only — `... END AS tier` -> `... END AS skill_tier`, and `coalesce(...) AS percentile` -> `coalesce(...) AS skill_percentile`. Keep `coalesce(ss.skill_score, 0) AS skill_score` exactly as-is. Do NOT touch the width_bucket expression, the boundaries logic, or any other CTE. Update the method docstring's "percentile tier (1..7, 0 = Unranked)" wording to 1..8 and to the renamed columns.

    In libs/sdk users.py, CommunityLeaderboardResponse: rename `tier: int` -> `skill_tier: int`, `percentile: float` -> `skill_percentile: float`, and add `skill_tier_name: str`. Update the docstring Attributes accordingly (skill_tier "1..8, 0 = Unranked"; skill_tier_name "Mapped tier name, Unranked..Champion"). Keep `skill_score` and `skill_rank` unchanged.

    In community_service.py `get_community_leaderboard`: import `skill_tier_name` from genjishimada_sdk.skill; after fetching `rows` (list[dict]) and BEFORE `msgspec.convert`, set `row["skill_tier_name"] = skill_tier_name(int(row["skill_tier"]))` for each row. Then convert to list[CommunityLeaderboardResponse] as before. Do not change any sort/filter logic or the allow-list of sortable columns (skill_score stays a valid sort column).
  </action>
  <verify>
    <automated>cd apps/api && uv run python -c "from genjishimada_sdk.users import CommunityLeaderboardResponse as C; f={x for x in C.__struct_fields__}; assert {'skill_tier','skill_percentile','skill_tier_name','skill_score'} <= f and 'tier' not in f and 'percentile' not in f, f; print('ok')"</automated>
  </verify>
  <done>Repository aliases emit skill_tier/skill_percentile; CommunityLeaderboardResponse has skill_tier/skill_percentile/skill_tier_name and no longer has tier/percentile; community service maps the name onto every row.</done>
</task>

<task type="auto">
  <name>Task 3: Update tests for 8 tiers, Unranked-at-0, new field names, and tier-name mapping</name>
  <files>apps/api/tests/services/test_skill_service.py, apps/api/tests/integration/test_skill.py</files>
  <action>
    In test_skill_service.py: update the reject tests so the "wrong length" case uses arrays that are NOT 7 (e.g. a 6-element and an 8-element array), and the out-of-range / non-increasing cases use 7-element arrays. Update the round-trip test (`test_tier_update_request_round_trips`) to a 7-element percentiles array. Update the no-row expected `SkillSummaryResponse` (~line 134) to include `skill_tier_name="Unranked"`. Add at least one assertion exercising the name map: import `skill_tier_name` / `SKILL_TIER_NAMES` and assert 0->"Unranked", 8->"Champion", and out-of-range->"Unranked".

    In test_skill.py TestSkillTiers (~604-690): change `len(legend["percentiles"]) == 6` and `len(legend["boundaries"]) == 6` to `== 7`; change `assert 1 <= int(user_json["tier"]) <= 7` to `<= 8`; assert the per-user read now carries `skill_tier_name` (a non-empty str consistent with the integer tier — e.g. for tier 0 it equals "Unranked"). Update the leaderboard-row assertions to the renamed columns: read `r["skill_tier"]` / `r["skill_percentile"]` (not `tier`/`percentile`), assert `skill_tier_name` is present and equals the SDK map for that row's skill_tier, and add an explicit Unranked assertion (a tier-0 row -> skill_tier_name == "Unranked"). In `test_unranked_zero_eligible`, assert the empty user's leaderboard row (if present) has `skill_tier == 0` and `skill_tier_name == "Unranked"`.

    In test_skill.py TestTiersPatch (~698-759): change `_VALID` and `_SEEDED_DEFAULT` to 7-element strictly-increasing arrays in (0,1). `_SEEDED_DEFAULT` MUST exactly match the new migration seed array. Update the `len(boundaries_before) == 6` / `len(boundaries_after) == 6` assertions to `== 7`.

    Do NOT modify the scorer-math tests (test_skill_service.py:~96) or any test asserting the percentile-based derivation formula — only the tier-count, field-name, and tier-name surface.
  </action>
  <verify>
    <automated>cd /Users/nebula/coding/parkour/genji/genjishimada && just test-api 2>&1 | tail -25</automated>
  </verify>
  <done>test_skill_service.py and test_skill.py assert 7 percentiles / 7 boundaries, tiers 1..8, Unranked-at-0, the renamed skill_tier/skill_percentile columns, and skill_tier_name mapping; `just test-api` passes.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| client -> PATCH /skill/tiers | Untrusted percentiles array crosses here (already gated superuser-only). |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-vtt-01 | Tampering | update_tier_config percentile count | mitigate | Bump validation to exactly 7; reject any other length before any write (nothing persisted on rejection — existing T-u82-02 behavior preserved). |
| T-vtt-02 | Information disclosure | skill_tier_name surface | accept | Tier names are display-only public ladder labels; no PII, low-value. |
| T-vtt-03 | Tampering | migration 0028 edit-in-place | accept | Migration is local-only/unpushed per task spec; boundaries stay empty, no hardcoded score cutoffs introduced. |
</threat_model>

<verification>
- `just lint-sdk && just lint-api` pass (type hints, Google docstrings, 120 line length).
- `just test-api` passes, including the updated skill + leaderboard tests.
- Migration 0028 seeds 7 percentiles; boundaries default stays empty.
- `SKILL_TIER_NAMES` is the only int->name definition (grep finds exactly one map literal), reused by both the leaderboard service and the skill summary path.
- The scorer (`_map_score`/`_player_score`/`_player_breakdown`) and `compute_tier_boundaries` / `width_bucket` derivation are byte-for-byte unchanged except for the documented alias renames.
</verification>

<success_criteria>
- skill.tier_config seeds 7 percentiles -> width_bucket yields tiers 1-8, tier 0 = Unranked.
- A single source-of-truth int->name map (0=Unranked..8=Champion) is reused by the leaderboard rows and SkillSummaryResponse via `skill_tier_name`.
- Community leaderboard columns renamed: tier -> skill_tier, percentile -> skill_percentile; skill_score unchanged; skill_tier_name added.
- Service validation, InvalidPercentilesError message, and SDK docstrings say "exactly 7".
- Tests cover 8 tiers, Unranked-at-0, the new field names, and the tier-name mapping.
- The percentile-based derivation and the existing scorer remain untouched.
</success_criteria>

<output>
Create `.planning/quick/260612-vtt-expand-the-skill-score-tier-system-from-/260612-vtt-SUMMARY.md` when done.
</output>
