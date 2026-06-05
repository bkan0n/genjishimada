---
phase: quick-260605-gjy
plan: 01
subsystem: bot/tournaments
tags: [tournaments, bot, announcement, bugfix]
requires:
  - apps/bot/extensions/tournaments.py:_on_edition_rollover
provides:
  - "Start-only rollover card title that does not announce a non-existent ending"
affects:
  - apps/bot/extensions/tournaments.py
  - apps/api/tests/bot/test_tournaments_handler.py
tech-stack:
  added: []
  patterns: ["conditional title selection in _on_edition_rollover"]
key-files:
  created:
    - .planning/quick/260605-gjy-start-only-rollover-title/260605-gjy-SUMMARY.md
    - .planning/quick/260605-gjy-start-only-rollover-title/deferred-items.md
  modified:
    - apps/bot/extensions/tournaments.py
    - apps/api/tests/bot/test_tournaments_handler.py
decisions:
  - "Used '# 🏆 New Tournament!\\nA new rotation has arrived!' as the start-only title (per plan), keeping existing emoji/line-break style."
metrics:
  duration: "~25m (most of it rebuilding a stale, relocated .venv)"
  completed: 2026-06-05
  tasks: 2
  files: 2
requirements: [QUICK-260605-GJY]
---

# Phase quick-260605-gjy Plan 01: Start-Only Rollover Title Summary

One-line: the start-only tournament rollover card no longer says "Tournament Ended!" — it now
leads with "🏆 New Tournament!", while the two genuinely-ended branches keep their ending copy.

## What Changed

- `apps/bot/extensions/tournaments.py` — `_on_edition_rollover`, the `elif event.started:`
  branch: title literal changed from
  `"# 🏆 Tournament Ended!\nA new rotation has arrived!"` to
  `"# 🏆 New Tournament!\nA new rotation has arrived!"`. This is the start-only case
  (out-of-hiatus or never-started; `has_ended` is False), where nothing actually ended.
  The `if event.started and has_ended:` (normal) and `else:` (into-hiatus) branches were
  left untouched and still announce "Tournament Ended!".
- `apps/api/tests/bot/test_tournaments_handler.py` — five assertions added across the three
  existing rollover tests (no new test functions, no fixture changes):
  - `test_rollover_out_of_hiatus_started_only_no_transfer`:
    `assert "Tournament Ended" not in rendered` and `assert "New Tournament" in rendered`.
  - `test_rollover_normal_renders_both_sections_and_transfers_champion`:
    `assert "Tournament Ended" in rendered`.
  - `test_rollover_into_hiatus_results_only_no_starting_section`:
    `assert "Tournament Ended" in rendered`.

## Verification

- Targeted module: `apps/api/tests/bot/test_tournaments_handler.py` — 21/21 passed.
- Tournament module run serially (`-p no:xdist`): 41/41 passed (handler + outbox poller).
- `just lint-bot`: ruff format (44 files unchanged), ruff check (all passed),
  basedpyright (0 errors, 0 warnings, 0 notes).
- `grep` confirms exactly one title branch changed: line 382 is now `🏆 New Tournament!`;
  lines 380 and 384 still contain `Tournament Ended!`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Rebuilt a stale/relocated project virtualenv**
- **Found during:** Task 2 (running `just test-api`).
- **Issue:** `uv run pytest` failed with `No such file or directory`. The `.venv` had been
  created when the repo lived at `/Users/nebula/coding/coding/parkour/...` (doubled path);
  every console-script shebang pointed at a non-existent interpreter, so pytest could not spawn.
  Test deps (`pytest`, `pytest_databases`) were also not present in the default sync.
- **Fix:** `rm -rf .venv` then `uv sync --all-groups --all-packages` (the project's documented
  `just sync` invocation), which rebuilds the venv with correct shebangs and installs the
  `dev-api` test group.
- **Files modified:** none (environment only).
- **Commit:** n/a (not a source change).

### Out-of-scope (NOT fixed — logged to deferred-items.md)

Pre-existing parallel-test (xdist) flakiness, unrelated to this title change. Each failure
passed in isolation, passed on the unmodified baseline, and the full tournament module passes
deterministically when run serially:
- `test_outbox_poller.py::TestRolloverHiatusSections::test_out_of_hiatus_started_only`
  (`award_cycle_end` call leaks across parallel workers).
- `test_maps_repository_update_core_map.py::test_update_timestamps_are_automatic`
  (`updated_at > created_at` flakes on same-microsecond updates).
See `deferred-items.md` for detail and suggested follow-up.

## Known Stubs

None.

## Self-Check: PASSED

- FOUND: apps/bot/extensions/tournaments.py (line 382 = `🏆 New Tournament!`)
- FOUND: apps/api/tests/bot/test_tournaments_handler.py (3 tests extended)
- FOUND: commit 07f4745
