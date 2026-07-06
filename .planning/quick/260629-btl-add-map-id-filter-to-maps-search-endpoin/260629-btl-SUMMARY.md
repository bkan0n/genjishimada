---
phase: quick-260629-btl
plan: 01
subsystem: api
tags: [maps, search, sqlspec, asyncpg, msgspec, discord-bot]

requires: []
provides:
  - "map_id integer filter on the maps search builder (m.id equality + CTE bypass)"
  - "map_id query parameter on GET /api/v3/maps"
  - "map_id param forwarded by the bot APIService.get_maps client"
affects: [maps-search, bot-api-client]

tech-stack:
  added: []
  patterns:
    - "map_id filter mirrors the existing code filter (WHERE-clause + force_filters CTE bypass)"

key-files:
  created: []
  modified:
    - apps/api/utilities/map_search.py
    - apps/api/routes/v3/maps.py
    - apps/bot/extensions/api_service.py
    - apps/api/tests/utilities/test_map_search_builder.py

key-decisions:
  - "map_id mirrors code exactly: m.id equality clause + CTE bypass when force_filters is false"
  - "Asserted on the tag_match_0 CTE-filter marker (not tag_links, which is an always-present base JOIN)"

patterns-established:
  - "Single-map lookups use the integer PK via map_id; code remains the human-facing share-code filter"

requirements-completed: [QUICK-MAPID-FILTER]

duration: 16min
completed: 2026-06-29
---

# Quick 260629-btl: map_id Filter on Maps Search Summary

**Added a `map_id` integer-PK filter to the maps search builder, the `GET /api/v3/maps` route, and the bot's `APIService.get_maps` — mirroring the existing `code` filter (m.id equality WHERE clause + CTE bypass when `force_filters` is false).**

## Performance

- **Duration:** ~16 min
- **Started:** 2026-06-29T08:26Z (approx)
- **Completed:** 2026-06-29T13:42Z (UTC commit time)
- **Tasks:** 3 (TDD: RED → GREEN → wire)
- **Files modified:** 4

## Accomplishments
- `MapSearchFilters` now accepts `map_id: int | None`, producing an `m.id` equality WHERE clause via `query.where_eq("m.id", ...)`.
- The `_build_ctes` bypass guard extended to `(code or map_id) and not force_filters`, so a `map_id` search skips mechanics/restrictions/tags/creators/quality/medals/completions CTEs exactly like a `code` search; `force_filters=True` still applies them.
- `GET /api/v3/maps` accepts a `map_id` query parameter threaded into `MapSearchFilters`.
- Bot `APIService.get_maps` gained a `map_id` parameter, a docstring arg line, and a `"map_id": map_id` params-dict entry.
- A failing-first unit test (`test_build_query_with_map_id`) pins the m.id equality clause, the args binding, the CTE bypass, and the `force_filters` override.

## Task Commits

Each task was committed atomically:

1. **Task 1: Write failing test for map_id filter** - `7e52ff5` (test) — RED confirmed (`TypeError: Unexpected keyword argument 'map_id'`)
2. **Task 2: Implement map_id in the search builder** - `8b84cfe` (feat) — GREEN
3. **Task 3: Wire map_id through API route and bot client** - `da3e7c2` (feat)

_Plan metadata commit (SUMMARY/STATE) is handled by the orchestrator._

## Files Created/Modified
- `apps/api/utilities/map_search.py` - Added `map_id` field to `MapSearchFilters`; extended CTE bypass guard; added `m.id` equality WHERE clause.
- `apps/api/routes/v3/maps.py` - Added `map_id` query parameter to `get_maps_endpoint`; passed `map_id=map_id` into `MapSearchFilters`.
- `apps/bot/extensions/api_service.py` - Added `map_id` param + docstring line + params-dict entry to `get_maps`.
- `apps/api/tests/utilities/test_map_search_builder.py` - New `test_build_query_with_map_id` (m.id clause, args, CTE bypass, force_filters override).

## Decisions Made
- Mirrored the `code` filter precisely (field placement, bypass guard, WHERE clause) per the plan's interface notes — no other filter logic touched.
- The bot's `get_map` (singular) method was intentionally left unchanged: the plan scoped Task 3 to `get_maps` only.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected test assertions to the builder's actual emitted SQL**
- **Found during:** Task 2 (GREEN)
- **Issue:** The Task 1 RED test asserted `"m.id" in query` and `"tag_links" not in query`. Both were wrong against the live builder output: (a) SQLSpec quotes identifiers as `"m"."id"`, not `m.id`; (b) `tag_links` (`maps.tag_links`) is an always-present base-table JOIN for the `tags` column projection, NOT a tag-FILTER CTE marker — it appears even when CTE filters are bypassed. The implementation was correct (`WHERE ... "m"."id" = $1`, args `[123]`; tag CTE absent when bypassed); only the assertions were inaccurate.
- **Fix:** Assert `"m.id" in query or '"m"."id"' in query` (matching the existing `test_build_query_with_sorting` quoting-tolerant style) and assert on `tag_match_0` — the verified discriminating CTE-filter marker (absent when bypassed, present when `force_filters=True`). Confirmed via direct builder introspection: `tag_match_0` bypassed=False / forced=True; `tag_links` always True.
- **Files modified:** apps/api/tests/utilities/test_map_search_builder.py
- **Verification:** `test_build_query_with_map_id` passes; the RED→GREEN transition is preserved (Task 1's committed test still failed with `TypeError` because the field did not exist yet).
- **Committed in:** `8b84cfe` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug — test-assertion accuracy)
**Impact on plan:** The implementation matched the plan exactly; the only correction was to the test's assertion strings, which were based on the plan's interface notes that mislabeled `tag_links` as a CTE marker and assumed unquoted identifiers. No scope creep; no production-code deviation.

## Issues Encountered
- The worktree's `uv` venv lacked the dev/test dependency groups initially (`ModuleNotFoundError: pytest_databases`); resolved with `uv sync --all-groups --all-packages` (the `just setup`/`sync` recipe), matching how `just test-api` expects the workspace.

## Verification Gate Results
- `test_build_query_with_map_id`: PASS (isolated builder test, no DB).
- `just lint-api` (ruff format + ruff check + basedpyright over repository/services/routes/middleware/utilities): clean — `All checks passed!`, `0 errors, 0 warnings, 0 notes`.
- `just lint-bot` (ruff format + ruff check + basedpyright over core/extensions/utilities/main.py): clean — `All checks passed!`, `0 errors, 0 warnings, 0 notes`.
- `just test-api` (testmon-selected, post-Task-3): `98 passed`.
- Full no-testmon API suite (`uv run pytest -n 4 apps/api --no-testmon`): **1951 passed, 2 skipped, 2 xfailed, 0 failures** (103.61s).
- Final grep: `map_id` present in all four target files.

## Known Stubs
None.

## Next Phase Readiness
- The maps search endpoint now supports single-map lookup by integer PK; callers (website/bot) can pass `map_id`. No follow-up work required.

## Self-Check: PASSED

- SUMMARY.md exists at the expected path.
- All three task commits exist: `7e52ff5` (test/RED), `8b84cfe` (feat/GREEN), `da3e7c2` (feat/wire).
- All four target files exist and contain `map_id`.

---
*Phase: quick-260629-btl*
*Completed: 2026-06-29*
