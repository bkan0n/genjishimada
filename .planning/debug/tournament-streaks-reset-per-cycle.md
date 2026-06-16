---
status: fixed
trigger: Some prod users do not have tournament streaks they should have, after one tournament.
created: 2026-06-16
updated: 2026-06-16
root_cause: Streak advance + reset ran once PER CHILD CYCLE; in a multi-category edition each category's reset sweep zeroed users who played a sibling category. Confirmed in prod (edition 1 = cycles 1+2; the 10 cycle-1-only players were all reset to 0 by cycle 2's sweep).
fix: Split rewards by scope — award_cycle_placements (per cycle) vs award_edition_streaks (once per edition over the union of all child-cycle participants, +1 per tournament). Reset only zeroes users who played NO child cycle.
files_changed: apps/api/services/tournament_reward_service.py, apps/api/services/tournament_outbox_service.py, apps/api/tests/services/test_tournament_reward_service.py, apps/api/tests/repository/tournaments/test_outbox_poller.py
verification: just lint-api clean; tournament unit+integration suites pass (33 + 60 + 85). Prod backfill SQL provided to repair the 17 edition-1 participants.
---

# Debug: tournament streaks missing for some users

## Symptoms
- Expected: users who participated in the (single) tournament have a streak >= 1.
- Actual: some participants have current_streak = 0 (no streak).
- Timeline: first/only tournament so far.

## Current Focus
- hypothesis: `_reset_non_participant_streaks` runs ONCE PER CHILD CYCLE, but an
  edition has one child cycle per category. Processing category B's reset sweep
  zeroes the streaks of users who participated in category A but not B — even
  though they participated in the edition. Only participants of the LAST-iterated
  child cycle keep a non-zero streak.
- next_action: confirm in prod that the edition had >1 child cycle and that the
  zeroed users participated in a non-last category; then fix reset to be
  edition-level (union of all child-cycle participants).

## Evidence
- `apps/api/services/tournament_outbox_service.py`
  - `process_awaiting_results_editions` (combined branch, ~L435-439) loops
    `for child in children:` calling `award_cycle_end(entry)` then
    `_reset_non_participant_streaks(entry)` per child cycle.
  - drain branch (~L227-229) does the same `for entry in event.results:`.
  - `_reset_non_participant_streaks` (~L469-496): non_participants =
    fetch_all_streak_user_ids() - fetch_cycle_participants(event.cycle_id). Reset
    is scoped to ONE cycle's participants, not the edition's union.
- `apps/api/repository/tournaments_repository.py`
  - `fetch_cycle_participants` = `SELECT DISTINCT user_id FROM tournaments.completions WHERE cycle_id = $1`.
  - `advance_streak(participated=False)` sets current_streak=0, last_cycle_id=cycle.
- Schema: `tournaments.cycles.edition_id` (0024) — one child cycle per category
  per edition (migration 0024 cron pre-rolls "one child cycle per active category").

## Trace (single edition, categories A=cycle1, B=cycle2; iteration order 1 then 2)
- User played only A: advance(c1)->streak=1; reset(c1) excludes them (participant);
  advance(c2) skips them; reset(c2): tracked & not a c2 participant -> RESET to 0. ❌
- User played only B (last cycle): advance(c2)->streak=1; reset(c2) excludes them. ✅
- => only last-iterated cycle's participants keep a streak.

## Eliminated
- (none yet) streak_xp threshold misconfig would suppress the bonus XP but not
  zero the streak count itself; symptom is the streak record being 0.
</content>
</invoke>
