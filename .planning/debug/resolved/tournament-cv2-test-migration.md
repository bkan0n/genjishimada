---
status: resolved
trigger: "13 test failures surfaced by full no-testmon run on feat/tournaments; testmon cache was hiding them"
created: 2026-05-31
updated: 2026-06-01
---

# Debug: tournament CV2 test migration

## Current Focus
- hypothesis: bot handler + command cogs were migrated to CV2 LayoutView batch cards
  (commits 6a944a4, 9800eab) but their tests still assert the old `embed=`/`content=`
  shape and pass singular events to handlers that now expect batch events.
- next_action: rewrite 12 stale bot-test assertions to the CV2 `view=` shape; investigate
  the 13th (schema seed `blacklist_weeks` 4 vs 5) separately.

## Root Cause (confirmed by reading source)
- `apps/bot/extensions/tournaments.py`:
  - `_on_cycle_started` now takes `TournamentCyclesStartedEvent` (batch, has `.cycles`),
    sends ONE `ui.LayoutView` (Container + TextDisplay sections + static hero MediaGallery).
    No map-banner thumbnail anymore.
  - `_on_cycle_completed` now takes `TournamentCyclesCompletedEvent`, sends ONE combined
    CV2 results card; winner ping is a TextDisplay INSIDE the card (no `content=` kwarg);
    `allowed_mentions` still restricts to numeric winner ids.
  - `streak` / `info` slash commands now render `view=ui.LayoutView(Container(TextDisplay))`
    instead of `embed=`.
- Stale tests (under apps/api/tests/bot/, run by the API suite):
  - test_tournaments_handler.py: 9 tests pass singular events + assert `embed`/`content`.
  - test_tournament_commands.py: 3 tests (streak x2, info) assert `embed`/thumbnail.

## Separate issue (13th failure)
- tests/integration/test_tournaments_schema.py::test_config_singleton_seeded expects
  `blacklist_weeks == 4` but DB seed yields `5`. Schema-seed vs test-expectation mismatch,
  unrelated to CV2. Investigate after the 12 are green.

## Evidence
- timestamp 2026-05-31: full `pytest -n4 --no-testmon` → 13 failed, 1724 passed.
- AttributeError 'TournamentCycleCompletedEvent' object has no attribute 'cycles' at
  tournaments.py:364 — handler reads `event.cycles` (batch) but test passed singular event.

## Files to change
- apps/api/tests/bot/test_tournaments_handler.py
- apps/api/tests/bot/test_tournament_commands.py
- (TBD) tests/integration/test_tournaments_schema.py OR the seed migration
