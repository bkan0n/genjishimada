---
phase: quick-260629-btl
plan: 01
type: tdd
wave: 1
depends_on: []
files_modified:
  - apps/api/tests/utilities/test_map_search_builder.py
  - apps/api/utilities/map_search.py
  - apps/api/routes/v3/maps.py
  - apps/bot/extensions/api_service.py
autonomous: true
requirements: [QUICK-MAPID-FILTER]

must_haves:
  truths:
    - "MapSearchFilters accepts a map_id integer and produces an m.id equality WHERE clause"
    - "When map_id is set (and force_filters is false), CTE-based filters are skipped exactly like code-search"
    - "GET /api/v3/maps accepts a map_id query parameter that locks results to one map"
    - "Bot APIService.get_maps forwards a map_id param to the API"
  artifacts:
    - path: "apps/api/utilities/map_search.py"
      provides: "map_id filter field, CTE bypass guard, m.id WHERE clause"
      contains: "map_id"
    - path: "apps/api/routes/v3/maps.py"
      provides: "map_id endpoint parameter wired into MapSearchFilters"
      contains: "map_id"
    - path: "apps/bot/extensions/api_service.py"
      provides: "map_id param in get_maps and params dict"
      contains: "map_id"
    - path: "apps/api/tests/utilities/test_map_search_builder.py"
      provides: "failing-first test asserting m.id equality and CTE skip"
      contains: "map_id"
  key_links:
    - from: "apps/api/routes/v3/maps.py"
      to: "MapSearchFilters"
      via: "map_id=map_id kwarg"
      pattern: "map_id=map_id"
    - from: "apps/api/utilities/map_search.py _build_ctes"
      to: "CTE bypass"
      via: "code or map_id guard"
      pattern: "self\\._filters\\.map_id"
---

<objective>
Add a `map_id` filter to the maps search endpoint that locks results to a single map by its integer primary key (`m.id`), mirroring the existing `code` filter exactly: it produces an `m.id` equality WHERE clause and bypasses CTE-based filters (mechanics/restrictions/tags/creators/quality/medals/completions) when `force_filters` is false.

Purpose: There is currently no code path to filter maps by their integer primary key — only by `code`. The `code` filter is the exact working analog; this change mirrors it in 5 places plus the bot client.

Output: `map_id` support across the search builder, the API route, and the bot's APIService, plus a failing-first unit test that pins the behavior.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md

<interfaces>
<!-- All locations verified against current source. Edit against these directly. -->

apps/api/utilities/map_search.py — MapSearchFilters struct (line ~47-76),
the `code` field is at line 55:
  code: OverwatchCode | None = None

apps/api/utilities/map_search.py — _build_ctes guard (line 190):
  if self._filters.code and not self._filters.force_filters:
      return []

apps/api/utilities/map_search.py — _apply_where_clauses code block (line 444-445):
  if self._filters.code:
      query.where_eq("m.code", self._filters.code)

  `query.where_eq("m.id", self._filters.map_id)` is the correct mirror —
  where_eq emits the column name and binds the value as a positional arg,
  so a built query for map_id=123 contains "m.id" and 123 in args.

apps/api/routes/v3/maps.py — get_maps_endpoint (line 100, already `# noqa: PLR0913`).
  `code` parameter is declared at line 103:
    code: Annotated[OverwatchCode | None, Parameter(description="Filter by map code")] = None
  MapSearchFilters(...) is constructed at line 152, `code=code` at line 153.

apps/bot/extensions/api_service.py — get_maps (line 407, already `# noqa: PLR0913`).
  `code` param at line 414, its docstring line at line 442, and the
  `"code": code,` params-dict entry at line 472.
</interfaces>
</context>

<tasks>

<task type="tdd">
  <name>Task 1: Write failing test for map_id filter</name>
  <files>apps/api/tests/utilities/test_map_search_builder.py</files>
  <behavior>
    - MapSearchFilters(map_id=123) builds a query whose `.query` contains "m.id" and whose `.args` contains 123 (the m.id equality clause).
    - With map_id set plus a CTE-triggering filter (e.g. tags=["Other Heroes"]) and force_filters left false, the built query does NOT contain the tag CTE markers ("tag_match_0", "tag_links") — proving CTE-based filters are skipped, exactly like code-search.
    - Optionally: with map_id set AND force_filters=True, the tag CTE markers DO appear (force_filters overrides the bypass).
  </behavior>
  <action>Add a new test method (e.g. `test_build_query_with_map_id`) to the existing `TestMapSearchSQLSpecBuilder` class, matching the style of `test_build_query_with_tags` (build the filters, call `builder.build()`, assert on `query_result.query` / `query_result.args`). Construct `MapSearchFilters(map_id=123)` — this will fail to even import/construct until Task 2 adds the field, which is the expected RED state. Add an assertion that "m.id" is in the built query and 123 is in `query_result.args`. Add a second filters object combining `map_id=123` with `tags=["Other Heroes"]` and assert the tag CTE markers are absent from the query. Test files are exempt from lint rules per CLAUDE.md, so no annotations/docstring lint concerns. Do NOT add the `map_id` field to the struct in this task — the test must fail first.</action>
  <verify>
    <automated>cd /Users/nebula/coding/parkour/genji/genjishimada && just test-api 2>&1 | grep -i "test_build_query_with_map_id" ; echo "RED expected: test errors/fails because MapSearchFilters has no map_id field yet"</automated>
  </verify>
  <done>New test method exists referencing MapSearchFilters(map_id=...) and FAILS (TypeError/attribute error) because the field does not yet exist — RED confirmed.</done>
</task>

<task type="tdd">
  <name>Task 2: Implement map_id in the search builder (GREEN)</name>
  <files>apps/api/utilities/map_search.py</files>
  <action>Mirror the `code` filter in three places. (1) In the `MapSearchFilters` struct, add `map_id: int | None = None` immediately after the `code: OverwatchCode | None = None` field (line ~55). (2) In `_build_ctes` (line 190), change the guard from `if self._filters.code and not self._filters.force_filters:` to `if (self._filters.code or self._filters.map_id) and not self._filters.force_filters:` so map_id-search bypasses CTE-based filters exactly like code-search. (3) In `_apply_where_clauses`, immediately after the `if self._filters.code: query.where_eq("m.code", self._filters.code)` block (lines 444-445), add `if self._filters.map_id: query.where_eq("m.id", self._filters.map_id)`. Do not touch any other filter logic.</action>
  <verify>
    <automated>cd /Users/nebula/coding/parkour/genji/genjishimada && just test-api 2>&1 | tail -20 && just lint-api 2>&1 | tail -10</automated>
  </verify>
  <done>The Task 1 test passes (GREEN); `just test-api` shows no new failures and `just lint-api` is clean.</done>
</task>

<task type="auto">
  <name>Task 3: Wire map_id through the API route and bot client</name>
  <files>apps/api/routes/v3/maps.py, apps/bot/extensions/api_service.py</files>
  <action>In `apps/api/routes/v3/maps.py` `get_maps_endpoint` (line 100, already has `# noqa: PLR0913`), add a new parameter `map_id: Annotated[int | None, Parameter(description="Filter by map ID")] = None` (place it near the `code` parameter at line 103 for readability) and pass `map_id=map_id` into the `MapSearchFilters(...)` construction (alongside `code=code` at line 153). In `apps/bot/extensions/api_service.py` `get_maps` (line 407, already `# noqa: PLR0913`), add a `map_id: int | None = None` parameter (place it near `code` at line 414), add a Google-style docstring arg line for it (mirroring `code (OverwatchCode | None): Filter by map code.` at line 442), and add a `"map_id": map_id,` entry to the `params` dict (near `"code": code,` at line 472). Make no other behavioral changes.</action>
  <verify>
    <automated>cd /Users/nebula/coding/parkour/genji/genjishimada && just lint-api 2>&1 | tail -10 && just lint-bot 2>&1 | tail -10 && just test-api 2>&1 | tail -15</automated>
  </verify>
  <done>`just lint-api`, `just lint-bot`, and `just test-api` all pass; the route accepts `map_id` and forwards it into MapSearchFilters; the bot client sends a `map_id` query param.</done>
</task>

</tasks>

<verification>
- `just test-api` passes, including the new `test_build_query_with_map_id` test.
- `just lint-api` and `just lint-bot` are clean.
- Grep confirms `map_id` appears in all four files:
  `grep -rl "map_id" apps/api/utilities/map_search.py apps/api/routes/v3/maps.py apps/bot/extensions/api_service.py apps/api/tests/utilities/test_map_search_builder.py`
</verification>

<success_criteria>
- A search with `map_id=N` returns only the single map with `m.id = N`, bypassing CTE-based filters when `force_filters` is false (mirroring `code`).
- `force_filters=True` still applies CTE-based filters even when `map_id` is set.
- All lint and test gates green.
</success_criteria>

<output>
Create `.planning/quick/260629-btl-add-map-id-filter-to-maps-search-endpoin/260629-btl-SUMMARY.md` when done.
</output>
