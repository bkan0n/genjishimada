# Phase 12: Overhaul of tournaments - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-01
**Phase:** 12-overhaul-of-tournaments
**Areas discussed:** Cadence model, Grid anchor & boundary, Combined announcement, Live cycle migration

---

## Cadence model

| Option | Description | Selected |
|--------|-------------|----------|
| Single global cadence | All categories start AND end together every period; drops per-category frequency; makes 'one shared start/end event' literally true | ✓ |
| Per-category, grid-anchored | Keep weekly+biweekly coexisting on a shared grid; biweekly transitions every other boundary; 'one unit' only partly true | |

**User's choice:** Single global cadence
**Notes:** Amends PROJECT.md's "per-category cycle frequency" requirement.

| Option | Description | Selected |
|--------|-------------|----------|
| Admin-configurable (global) | One tournament-wide frequency setting (weekly/biweekly) on tournaments.config; replaces per-category cycle_frequency | ✓ |
| Fixed weekly | Hardcode 7-day period; drops biweekly | |
| Keep both columns, ignore biweekly | Leave cycle_frequency but read only global value | |

**User's choice:** Admin-configurable (global)

| Option | Description | Selected |
|--------|-------------|----------|
| Both global | One transitions_paused + one debug_cycle_seconds for whole tournament; migrate/drop per-category cols | ✓ |
| Keep per-category | Leave levers on tournaments.categories | |

**User's choice:** Both global

| Option | Description | Selected |
|--------|-------------|----------|
| Explicit tournament entity | New top-level row per rotation (e.g. tournaments.editions) holding shared timing; cycles become children | ✓ |
| Keep cycles, shared anchor | No new table; all cycles read one shared epoch/grid from config | |
| Let research/planner decide | Capture intent, planner picks schema | |

**User's choice:** Explicit tournament entity

---

## Grid anchor & boundary

| Option | Description | Selected |
|--------|-------------|----------|
| Fixed wall-clock anchor | Configured weekday + time slot (e.g. Mon 00:00 UTC); predictable for players | ✓ |
| Floating from epoch | First start = epoch; every edition = epoch + N×period; arbitrary slot | |

**User's choice:** Fixed wall-clock anchor

| Option | Description | Selected |
|--------|-------------|----------|
| Admin-configurable | weekday + time + tz in tournaments.config; changes apply next edition, locked mid-edition | ✓ |
| Hardcoded constant | Fixed slot in code/migration | |

**User's choice:** Admin-configurable

| Option | Description | Selected |
|--------|-------------|----------|
| Record grid times | edition times = exact grid boundary regardless of cron lateness; cron only flips status | ✓ |
| Record execution time | Keep writing now() at flip (the current drift cause) | |

**User's choice:** Record grid times (core drift fix)

| Option | Description | Selected |
|--------|-------------|----------|
| Start now, end on boundary | First edition starts now(), ends on next boundary (short first edition) | |
| Snap to next boundary | First edition starts at next anchor slot; startup gap acceptable; no exceptions to grid rule | ✓ |
| You decide | Let planner pick | |

**User's choice:** Snap to next boundary

---

## Combined announcement

| Option | Description | Selected |
|--------|-------------|----------|
| One combined message | Single announcement: results of N + start of N+1; new combined event replaces started/completed pair | ✓ |
| Two messages, guaranteed grouped | Keep separate events, guaranteed one each per rollover | |

**User's choice:** One combined message

| Option | Description | Selected |
|--------|-------------|----------|
| Conditional sections | Optional 'results' + optional 'starting' parts; render whichever present | ✓ |
| Always both w/ placeholders | Always render both with placeholder copy | |
| (free text) | User clarified pause semantics | ✓ |

**User's choice (free text):** "By pausing, I actually meant that it should pause the next cycle from
starting, not ending. This is so we can have a hiatus of tournaments if necessary."
**Notes:** Reflected back and confirmed ("Yes correct"). Pause = suppress next start (hiatus); active
edition always runs full term and announces results. Resume → next edition at next grid boundary.
Debug-cycle-length just shrinks the grid period; current edition still ends on its computed boundary.
This confirms conditional-sections: normal=results+start, hiatus-entry=results-only, resume=start-only.

| Option | Description | Selected |
|--------|-------------|----------|
| Single rollover row | One pending_transitions row per rollover (edition_rollover); payload all categories; one idempotency key | ✓ |
| Keep per-cycle rows, merge at publish | Keep per-category rows, poller merges into combined event | |
| You decide | Planner picks outbox/event shape | |

**User's choice:** Single rollover row

---

## Live cycle migration

| Option | Description | Selected |
|--------|-------------|----------|
| Fresh restart | Finalize/discard in-flight cycles, bootstrap first edition fresh | ✓ |
| Migrate in place | Wrap current cycles into synthetic first edition, preserve standings | |
| You decide | Planner picks based on liveness | |

**User's choice:** Fresh restart

| Option | Description | Selected |
|--------|-------------|----------|
| Wipe everything | Drop all cycles + tournament completions, start clean | ✓ |
| Preserve completed history | Keep completed cycles as archive, back-fill | |
| You decide | Planner decides | |

**User's choice:** Wipe everything

| Option | Description | Selected |
|--------|-------------|----------|
| Null the FK, keep core times | Set tournament_completion_id = NULL, keep legit PB times on main leaderboard | ✓ |
| Cascade-delete core rows | Delete cross-written core.completions rows | |

**User's choice:** Null the FK, keep core times

---

## Claude's Discretion

- Exact table/column names (`tournaments.editions`, config home for global cadence/anchor/pause/debug).
- Migration file number(s) after 0023 and single-vs-multiple migration split.
- Exact combined `TournamentRolloverEvent` struct/routing-key/outbox `event_type` value.
- Grid boundary computation (anchor + timezone, DST, interval math) and exact stored grid timestamps.
- Where per-category leaderboards / champion roles / XP / streaks attach under the edition entity.
- Fate of existing per-cycle API endpoints + frontend-spec updates.
- Existing Discord champion-role holders at the fresh-restart cutover.

## Deferred Ideas

- Preserve historical completed cycles / past-champions archive across migration (declined now — fresh
  restart wipes; revisit for a future production-data schema change).
- Per-edition vs per-category leaderboard surfacing / reshaped public API + frontend-spec rewrite
  (downstream of edition entity; planner discretion, possible follow-up phase).
