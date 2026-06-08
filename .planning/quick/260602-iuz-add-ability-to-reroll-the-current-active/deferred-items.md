# Deferred Items — quick-260602-iuz

Out-of-scope discoveries logged during execution (SCOPE BOUNDARY rule).

## Pre-existing bot-handler test failures — RESOLVED 2026-06-02 (follow-up to this task)

The TRUE no-testmon full suite (`pytest -n 4 --no-testmon`) surfaced 4 failing tests
during execution. All 4 were **proven to fail identically at the base commit `5d4e850`**
with zero IUZ changes present — they were NOT regressions from active-cycle reroll. They
belonged to the `feat/tournaments-pr` branch's deliberate removal of the per-run verdict
message and its card/announcement copy changes (commit `d2554d6` "feat(tournaments): drop
per-run verification verdict message + retitle new-cycle section"), where the matching
bot-handler tests were left stale.

These were fixed in a follow-up after the reroll task (commits `89dfa60` + the docs commit
referencing this file). Each was confirmed a **stale test from an intentional behavior
change**, not a code bug:

| Test | Was failing because | Fix |
|------|---------------------|-----|
| `test_tournaments_handler.py::test_rollover_normal_renders_both_sections_and_transfers_champion` | asserted the map link host `workshop.codes`; the card link host moved to `genji.pk/search` (`_WORKSHOP_URL`, tournaments.py:73) | assert `genji.pk/search` |
| `test_tournament_commands.py::test_info_renders_card_for_active_cycle` | same `workshop.codes` host drift in the `/tournament info` card | assert `genji.pk/search` |
| `test_tournaments_handler.py::test_verification_changed_surfaces_verdict` | expected a channel post; `_on_verification_changed` was reduced to a log-only no-op when the per-run verdict message was dropped (d2554d6) | renamed to `test_verification_changed_posts_no_per_run_message`, asserts `channel.send_calls == []`; also corrected the now-misleading handler docstring |
| `test_tournaments_handler.py::test_on_edition_results_empty_standings_posts_no_winner_card_no_transfer` | asserted bare `"Congratulations" not in rendered`; the results card now has an unconditional `"...Congratulations to this rotation's champions!"` header (tournaments.py:397/545) distinct from the gated winner ping `"Congratulations <@id>!"` (:454/569) | assert the ping form `"Congratulations <@"` is absent instead of the bare word |

All four now pass (`tests/bot/test_tournaments_handler.py` + `tests/bot/test_tournament_commands.py`: 39 passed, no-testmon); `just lint-bot` clean.
