# Deferred Items — quick-260602-iuz

Out-of-scope discoveries logged during execution (SCOPE BOUNDARY rule). NOT fixed by this task.

## Pre-existing bot-handler test failures (NOT regressions)

The TRUE no-testmon full suite (`pytest -n 4 --no-testmon`) surfaced 4 failing tests.
All 4 were **proven to fail identically at the base commit `5d4e850`** with zero IUZ
changes present (verified by checking out base versions of the source/test files and
re-running). They predate this task and belong to the `feat/tournaments-pr` branch's
deliberate removal of the per-run verdict / announcement messages (commit `d2554d6`
"feat(tournaments): drop per-run verification verdict message") where the corresponding
bot-handler tests were not updated.

| Test | Failure | Root cause |
|------|---------|------------|
| `tests/bot/test_tournaments_handler.py::test_verification_changed_surfaces_verdict` | `len(channel.send_calls) == 0`, expected 1 | `_on_verification_changed` no longer posts a verdict message (removed in d2554d6); test still asserts a send. |
| `tests/bot/test_tournaments_handler.py::test_rollover_normal_renders_both_sections_and_transfers_champion` | render/section assertion | rollover card content drift vs the updated tournaments.py card copy. |
| `tests/bot/test_tournaments_handler.py::test_on_edition_results_empty_standings_posts_no_winner_card_no_transfer` | card/transfer assertion | same edition-results card-copy drift. |
| `tests/bot/test_tournament_commands.py::test_info_renders_card_for_active_cycle` | info card assertion | `/tournament info` card copy drift. |

These are unrelated to active-cycle reroll. Recommend a follow-up to reconcile the
tournament bot-handler tests with the current (post-d2554d6) card/announcement copy.
