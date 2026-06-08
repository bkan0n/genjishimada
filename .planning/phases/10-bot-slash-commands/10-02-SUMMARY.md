---
phase: 10-bot-slash-commands
plan: 02
subsystem: bot
tags: [tournaments, discord, app_commands, transformer, autocomplete, api_service]

requires:
  - phase: 10-01-streak-read-endpoint
    provides: "GET /api/v3/tournaments/streaks/{user_id} that get_tournament_streak calls"
provides:
  - "APIService.get_tournament_streak / list_tournament_categories / list_tournament_cycles / get_tournament_leaderboard / reroll_next_cycle / choose_next_cycle"
  - "CategoryTransformer (transform category name/id -> int + live autocomplete from list_tournament_categories)"
affects: [10-bot-slash-commands-03]

tech-stack:
  added: []
  patterns:
    - "Sync def APIService wrappers returning self._request(...) — path ids as Route(...) kwargs, query filters via params= (auto-skips None)"
    - "app_commands.Transformer with digit fast-path transform + live API-backed autocomplete capped at 25 (mirrors UserTransformer)"

key-files:
  created: []
  modified:
    - apps/bot/extensions/api_service.py
    - apps/bot/utilities/transformers.py

key-decisions:
  - "choose_next_cycle uses PATCH /tournaments/categories/{category_id}/next-cycle (controller verb is PATCH, overriding CONTEXT D-15's POST mention; interfaces block + live controller both confirm PATCH)"
  - "CategoryTransformer makes per-keystroke API calls with no cache, consistent with UserTransformer (A4) — no caching added"

patterns-established:
  - "Tournament APIService wrappers: typed sync def, Route placeholders as kwargs, filters via params=, response_model= for shape"
  - "CategoryTransformer: digit fast-path -> int; name miss -> UserFacingError; autocomplete case-fold substring filter sliced [:25]"

requirements-completed: [ADM-03]

duration: 4min
completed: 2026-05-30
---

# Phase 10 Plan 02: Tournament APIService Wrappers + CategoryTransformer Summary

**Six typed bot-side APIService tournament wrappers (streak + five reused endpoints, POST reroll / PATCH next-cycle) plus a CategoryTransformer that resolves a typed category_id and powers live D-09 autocomplete from the API category list.**

## Performance

- **Duration:** ~4 min
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Added six thin sync `APIService` wrappers next to the existing `get_tournament_category` (~api_service.py:1667), each returning `self._request(...)`: `get_tournament_streak`, `list_tournament_categories`, `list_tournament_cycles`, `get_tournament_leaderboard`, `reroll_next_cycle` (POST), `choose_next_cycle` (PATCH).
- Imported the six tournament SDK structs (`TournamentStreakResponse`, `TournamentCategoryResponse`, `TournamentCycleListResponse`, `TournamentLeaderboardEntryResponse`, `TournamentNextCycleResponse`, `TournamentChooseMapRequest`).
- Added `CategoryTransformer` mirroring `UserTransformer`: digit fast-path transform, case-fold name resolution against the live category list (raising `UserFacingError` on a miss), and live autocomplete capped at 25 choices (Discord hard limit, Pitfall 3).

## Task Commits

1. **Task 1: Add six APIService tournament wrappers** - `ad81fcb` (feat)
2. **Task 2: Add CategoryTransformer (autocomplete + transform)** - `cb4e1af` (feat)

## Files Created/Modified

- `apps/bot/extensions/api_service.py` - Six tournament wrappers + expanded tournaments SDK import
- `apps/bot/utilities/transformers.py` - New `CategoryTransformer` (transform + autocomplete)

## Decisions Made

- **choose_next_cycle verb is PATCH, not POST.** CONTEXT D-15 mentioned `POST .../next-cycle`, but the plan's `<interfaces>` block and the live controller (`apps/api/routes/v3/tournaments.py:420` `@litestar.patch`) both specify PATCH. Followed the authoritative controller — PATCH.
- **No caching in CategoryTransformer.** Per-keystroke API calls match `UserTransformer` (A4); caching deliberately not added.

## Deviations from Plan

None - plan executed exactly as written (the PATCH verb choice was the plan's `<interfaces>`-confirmed verb, not a deviation).

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- The six wrappers and `CategoryTransformer` are inert glue, ready for the Plan 10-03 command Cog to compose into `/tournament info|leaderboard|streak` and `/tournament-reroll`.
- Manual-only validation noted in the plan: live category autocomplete in `/tournament info` can only be confirmed in the dev guild (no Discord interaction test harness exists).

## Self-Check

- `apps/bot/extensions/api_service.py` - FOUND (six wrappers present)
- `apps/bot/utilities/transformers.py` - FOUND (CategoryTransformer present)
- Commit `ad81fcb` - present in git log
- Commit `cb4e1af` - present in git log

## Self-Check: PASSED

---
*Phase: 10-bot-slash-commands*
*Completed: 2026-05-30*
