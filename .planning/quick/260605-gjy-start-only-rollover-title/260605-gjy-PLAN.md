---
phase: quick-260605-gjy
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - apps/bot/extensions/tournaments.py
  - apps/api/tests/bot/test_tournaments_handler.py
autonomous: true
requirements: [QUICK-260605-GJY]
must_haves:
  truths:
    - "A start-only rollover (started non-empty, nothing ended) posts a card whose title does NOT contain 'Tournament Ended'."
    - "A start-only rollover title leads with a START framing (e.g. 'New Tournament')."
    - "The normal case (results + started) still announces 'Tournament Ended!'."
    - "The into-hiatus case (results only, no started) still announces 'Tournament Ended!'."
  artifacts:
    - path: "apps/bot/extensions/tournaments.py"
      provides: "Corrected start-only rollover title in _on_edition_rollover"
      contains: "elif event.started:"
    - path: "apps/api/tests/bot/test_tournaments_handler.py"
      provides: "Assertions locking the start-only fix and guarding the two ended branches"
  key_links:
    - from: "apps/bot/extensions/tournaments.py:_on_edition_rollover"
      to: "title selection branch `elif event.started:`"
      via: "string literal change only"
      pattern: "elif event.started"
---

<objective>
Fix the tournament rollover announcement so a start-only rollover (a cycle that
has never started, or one returning from a paused/hiatus cycle) does NOT announce
a non-existent "Tournament Ended!" — its title must reference ONLY the start of
the new cycle.

Purpose: From the bot's perspective "never started" and "returning from a paused
cycle" are the SAME case (`event.started` non-empty, `has_ended` False). The
current `elif event.started:` branch hardcodes a "Tournament Ended!" title,
announcing a tournament that never existed. The two genuinely-ended cases (normal
and into-hiatus) MUST keep their "ended" messaging per explicit user instruction.

Output: One-line title string change in `_on_edition_rollover` plus test
assertions that lock the fix and guard against over-correction.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@./CLAUDE.md

<interfaces>
<!-- Title-selection block in apps/bot/extensions/tournaments.py, _on_edition_rollover.
     Current code at lines 378-384 — verified. Only line 382 changes. -->

```python
has_ended = bool(event.results) or event.results_pending
if event.started and has_ended:
    title = "# 🏆 Tournament Ended!\nThe previous rotation has ended and a new one has begun!"
elif event.started:
    title = "# 🏆 Tournament Ended!\nA new rotation has arrived!"   # <-- BUG: nothing ended here
else:
    title = "# 🏆 Tournament Ended!\nThe rotation has ended."
```

Branch semantics:
- `event.started and has_ended` → NORMAL: real previous tournament ended AND new one begins. KEEP "Tournament Ended!".
- `elif event.started:` → START-ONLY: out-of-hiatus OR never-started. `has_ended` is False. THIS IS THE BUG.
- `else:` → INTO-HIATUS / results-only: a real tournament ended, no new start. KEEP "Tournament Ended!".

Relevant tests in apps/api/tests/bot/test_tournaments_handler.py (line numbers verified):
- `test_rollover_normal_renders_both_sections_and_transfers_champion` (~line 232) — normal branch.
- `test_rollover_into_hiatus_results_only_no_starting_section` (~line 266) — into-hiatus branch.
- `test_rollover_out_of_hiatus_started_only_no_transfer` (~line 287) — the buggy start-only branch; builds `TournamentRolloverEvent(edition_id=7, results=[], started=[started])` and inspects `rendered = _view_text(...)`.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Fix the start-only rollover title</name>
  <files>apps/bot/extensions/tournaments.py</files>
  <action>In `_on_edition_rollover`, change ONLY the `elif event.started:` title
  string (currently line 382). Replace the "# 🏆 Tournament Ended!\nA new rotation
  has arrived!" literal with a START-framed title that contains NO "Tournament
  Ended" / "previous rotation ended" / "ended" wording. Use:
  "# 🏆 New Tournament!\nA new rotation has arrived!". Do NOT touch the
  `if event.started and has_ended:` branch (line 380) or the `else:` branch
  (line 384) — both intentionally keep "Tournament Ended!" per user instruction.
  Do not change `has_ended` logic, the container build, or any section rendering.
  Keep the existing emoji and line-break (`\n`) formatting style.</action>
  <verify>
    <automated>grep -n "New Tournament" apps/bot/extensions/tournaments.py</automated>
  </verify>
  <done>The `elif event.started:` branch sets a title leading with "🏆 New Tournament!" and containing no "Tournament Ended" text; the other two branches are unchanged (still contain "Tournament Ended!").</done>
</task>

<task type="auto">
  <name>Task 2: Lock the fix and guard the ended branches with test assertions</name>
  <files>apps/api/tests/bot/test_tournaments_handler.py</files>
  <action>Add assertions to three existing tests (no new test functions, no fixture
  changes):
  1. In `test_rollover_out_of_hiatus_started_only_no_transfer` (~line 287), after
     `rendered = _view_text(...)`, assert the start-only card does NOT announce an
     ending and DOES use the new start framing: add
     `assert "Tournament Ended" not in rendered` and
     `assert "New Tournament" in rendered`.
  2. In `test_rollover_normal_renders_both_sections_and_transfers_champion`
     (~line 232), add a positive guard `assert "Tournament Ended" in rendered`
     so the normal branch keeps its ended messaging.
  3. In `test_rollover_into_hiatus_results_only_no_starting_section` (~line 266),
     add `assert "Tournament Ended" in rendered` so the into-hiatus branch keeps
     its ended messaging.
  Do not modify any other assertions or test setup.</action>
  <verify>
    <automated>just test-api 2>&1 | tail -20</automated>
  </verify>
  <done>The three tests pass: start-only asserts no "Tournament Ended" + presence of "New Tournament"; normal and into-hiatus assert "Tournament Ended" is present.</done>
</task>

</tasks>

<verification>
- `just test-api` passes (or the targeted module `apps/api/tests/bot/test_tournaments_handler.py`).
- `just lint-bot` passes.
- Manual grep confirms exactly one title branch changed: `elif event.started:` no longer references "Tournament Ended".
</verification>

<success_criteria>
- Start-only rollover card title contains no "Tournament Ended" wording and leads with a START framing.
- Normal and into-hiatus rollover titles still announce "Tournament Ended!".
- No migration, SDK, or API change; bot + test files only.
- `just test-api` and `just lint-bot` both pass.
</success_criteria>

<output>
Create `.planning/quick/260605-gjy-start-only-rollover-title/260605-gjy-SUMMARY.md` when done
</output>
