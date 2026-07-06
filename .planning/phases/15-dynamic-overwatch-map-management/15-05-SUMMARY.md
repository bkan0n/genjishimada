---
phase: 15-dynamic-overwatch-map-management
plan: 05
subsystem: bot
tags: [discord.py, api-client, pagination, msgspec, map-names, ui-select]

# Dependency graph
requires:
  - phase: 15-04
    provides: "GET /api/v3/utilities/map-names -> list[str] (full, sorted, no search/limit)"
  - phase: 15-01
    provides: "OverwatchMap = str (Literal dropped), so get_args(OverwatchMap) returns () at runtime"
provides:
  - "api_service.get_all_map_names() bot client calling GET /utilities/map-names"
  - "DB-fed MapNameSelect (options sourced from the live list, not the compiled-in Literal) at both wizard construction sites"
  - "Newly-added maps appear in the moderator/edit-request map-name dropdown with no bot restart"
affects: [bot, overwatch-map-management]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Bot test harness bootstrap: self-contained tests under apps/bot/tests/ with an in-file sys.path insert of the bot root (no conftest), run via explicit `uv run pytest apps/bot/tests/<file>.py`"
    - "Sync-def-returns-coroutine client method shape (mirrors get_autocomplete_map_names); call sites await"

key-files:
  created:
    - apps/bot/tests/test_api_service.py
    - apps/bot/tests/test_map_name_select.py
  modified:
    - apps/bot/extensions/api_service.py
    - apps/bot/extensions/moderator.py
    - apps/bot/extensions/map_editor.py

key-decisions:
  - "get_all_map_names is a plain def returning self._request(...) (NOT async def), matching get_autocomplete_map_names; the two call sites await it."
  - "MapNameSelect takes all_maps: list[str]; the full list is fetched ONCE in the async command callback and threaded view.__init__ -> rebuild -> MapNameSelect (never awaited inside the sync ui.Select __init__)."
  - "Pagination slice / total_pages / SelectOption math kept byte-for-byte (Spike 008)."
  - "get_args(MapCategory)/Mechanics/Restrictions/Tags left untouched (still real Literals)."
  - "Bot tests are self-contained (no conftest/harness) and are NOT run by `just test-api`; verify with explicit `uv run pytest apps/bot/tests/...`."

patterns-established:
  - "DB-fed Discord ui.Select: fetch the source list once in the async build context, pass it down into the sync Select constructor as a param."

requirements-completed: [REQ-09, REQ-10, D-02]

# Metrics
duration: ~12min
completed: 2026-06-25
---

# Phase 15 Plan 05: Bot DB-fed MapNameSelect Summary

**The moderator map-edit map-name dropdown now sources its options from the live DB via `api_service.get_all_map_names()` (`GET /utilities/map-names`) at both construction sites, so a map added through the API appears in the dropdown with no bot restart; pagination math is verbatim Spike-008.**

## Performance

- **Duration:** ~12 min (autonomous code/test tasks)
- **Started:** 2026-06-26T02:54Z
- **Completed:** 2026-06-26T02:59Z (autonomous tasks; Task 4 is a pending human-verify checkpoint)
- **Tasks:** 3 of 4 (Task 4 is the human-verify checkpoint, surfaced not auto-passed)
- **Files modified:** 5 (3 source, 2 new tests)

## Accomplishments
- Added `api_service.get_all_map_names() -> Response[list[str]]` — a plain `def` returning `self._request(Route("GET", "/utilities/map-names"), response_model=list[str])`, mirroring the sync-def-returns-coroutine shape of `get_autocomplete_map_names` (callers `await`). (REQ-09)
- DB-fed `MapNameSelect`: replaced `list(get_args(OverwatchMap))` (now `()` post-15-01) with an injected `all_maps: list[str]`; threaded the list `MapEditWizardView.__init__` -> `self._all_maps` -> `rebuild()` -> `MapNameSelect(all_maps=...)`. (REQ-10)
- Both async construction sites fetch the list once and pass it in: `moderator.py` `/map edit` (`is_mod=True`) and `map_editor.py` `/map edit-request` (`is_mod=False`), each `await itx.client.api.get_all_map_names()`.
- Pagination slice / `total_pages` / `SelectOption` math kept byte-for-byte (Spike 008); `get_args(MapCategory)`/`Mechanics`/`Restrictions`/`Tags` untouched.
- Two self-contained bot unit tests (no conftest/harness): the REQ-09 client-shape test and the REQ-10 pagination test.

## Task Commits

Each autonomous task was committed atomically on `feat/better-ow-map-management`:

1. **Task 1: add `get_all_map_names()` client + REQ-09 unit test** — `63092a9` (feat)
2. **Task 2: DB-feed `MapNameSelect` at both wizard sites** — `7790327` (feat)
3. **Task 3: MapNameSelect pagination unit test (REQ-10)** — `8371bdd` (test)

**Task 4 (checkpoint:human-verify):** NOT executed/auto-passed — surfaced as a checkpoint (steps below).

**Plan metadata:** committed separately with this SUMMARY + STATE/ROADMAP updates.

## Files Created/Modified
- `apps/bot/extensions/api_service.py` — added `get_all_map_names()` (plain def returning the coroutine; Google docstring).
- `apps/bot/extensions/moderator.py` — `MapNameSelect.__init__(current, all_maps, page=0)`; `MapEditWizardView.__init__(map_data, is_mod, all_maps)` stores `self._all_maps`; `rebuild()` passes `all_maps=self._all_maps`; `/map edit` fetches the list and threads it in. Verbatim pagination math; `get_args(MapCategory)`/etc. untouched.
- `apps/bot/extensions/map_editor.py` — `/map edit-request` fetches the list and threads it into `MapEditWizardView(..., all_maps=all_maps)`.
- `apps/bot/tests/test_api_service.py` (new) — self-contained: asserts `_request` called once with a `GET /utilities/map-names` `Route` and `response_model=list[str]`, no `search/limit/params/data`; asserts the method is NOT a coroutine function.
- `apps/bot/tests/test_map_name_select.py` (new) — self-contained: page-0 first 25 sorted, last-page remainder (13), `total_pages == ceil(n/25)`, `current`-default on the matching option (and none when off-page), empty-list -> 0 options / `total_pages == 0` (no crash).

## Bot test harness note

The bot has **no** `apps/bot/tests/` harness, conftest, or pytest config in `apps/bot/pyproject.toml`, and `just test-all` runs only `just test-api`. Both bot tests here are therefore **self-contained** (mocks/synthetic data only) and bootstrap the bot root onto `sys.path` in-file (the bot normally imports `extensions.*` as top-level because it runs as `python main.py` from `apps/bot`). Verify them explicitly:

```
cd apps/bot && uv run pytest tests/test_api_service.py tests/test_map_name_select.py -x
```

## Verification Results
- `cd apps/bot && uv run pytest tests/test_api_service.py -k get_all_map_names -x` -> 2 passed.
- `cd apps/bot && uv run pytest tests/test_map_name_select.py -k map_name_select -x` -> 6 passed.
- Combined: **8 passed**.
- `just lint-bot` -> clean (ruff format: 44 files unchanged; ruff check: all passed; basedpyright: 0 errors, 0 warnings, 0 notes).
- AST/grep gates: `extensions/moderator.py` parses, contains `all_maps` + `await ... get_all_map_names` + `get_args(MapCategory)`, and no longer references `get_args(OverwatchMap)`; `extensions/map_editor.py` parses and awaits `get_all_map_names`.

## Decisions Made
None beyond the plan — followed it as specified (sync-def coroutine shape, fetch-once-in-async-callback, verbatim pagination, untouched `MapCategory`).

## Deviations from Plan

None — plan executed exactly as written.

Note (not a behavioural deviation): the in-source docstring for `all_maps` was worded to avoid the literal token `get_args(OverwatchMap)` so the plan's backstop grep/AST gate (`'get_args(OverwatchMap)' not in moderator.py`) passes on file text — same approach 15-01 used. No code semantics changed. The `OverwatchMap` import is intentionally KEPT (still used as the `current: OverwatchMap | None` annotation and `cast(OverwatchMap | None, ...)`, where `OverwatchMap = str` post-15-01).

## Issues Encountered
- Initial test run failed with `ModuleNotFoundError: No module named 'extensions'` — pytest does not add the bot root to `sys.path` (no conftest/harness). Resolved by an in-file `sys.path.insert(0, <bot root>)` at the top of each self-contained test (kept conftest-free per the plan's harness note). Resolved before Task 1's commit.

## Known Stubs
None — the dropdown is fully wired to the live endpoint; no placeholder/empty data sources introduced.

## Pending Human Verification (Task 4 — checkpoint:human-verify, NOT auto-passed)

The autonomous code/test tasks are complete and committed. The live discord.py UI has no bot test harness, so the end-to-end "new map appears in the dropdown with no restart" claim must be verified manually:

1. Run the API (`just run-api`) and bot (`just run-bot`) locally against the local DB/MinIO.
2. Add a brand-new map via the API: `POST /api/v3/content/maps` (multipart `name` + a small PNG `banner`) — or have an admin add one. (Requires the `content:admin` scope.)
3. In Discord, open the moderator map-edit wizard (`/map edit <code>`), advance to the **Map Name** field.
4. Confirm the dropdown lists DB rows, includes the newly-added map, and paginates with the prev/next buttons (25/page). Confirm the banner for the new map resolves on the website/map read surface (`assets/map_banners/{stripped}.png`).

**Resume signal:** reply "approved" if the new map appears and paginates correctly, or describe what is wrong.

## Next Phase Readiness
- The phase goal ("a one-call add appears on all three surfaces") closes on the bot surface once the human-verify checkpoint is approved.
- Phase 15: this is the final plan (Wave 4); after approval, 5/5 plans complete.

## Self-Check: PASSED

- Files: `apps/bot/tests/test_api_service.py`, `apps/bot/tests/test_map_name_select.py`, `15-05-SUMMARY.md` — all present.
- Commits: `63092a9`, `7790327`, `8371bdd` — all present in git log.

---
*Phase: 15-dynamic-overwatch-map-management*
*Completed (autonomous tasks): 2026-06-25*
