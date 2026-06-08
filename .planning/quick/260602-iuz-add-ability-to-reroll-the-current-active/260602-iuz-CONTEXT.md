# Quick Task 260602-iuz: Add ability to reroll the current (active) tournament cycle - Context

**Gathered:** 2026-06-02
**Status:** Ready for planning

<domain>
## Task Boundary

Today, `/tournament-reroll` only rerolls the **upcoming** cycle (the pre-staged `status='pending'` cycle in `tournaments.cycles`). This is safe because nobody is playing it yet — `reroll_map(category_id)` simply deletes the pending cycle and creates a fresh pending one with a new map.

This task adds the ability to reroll the **current** cycle — the live `status='active'` cycle that players are actively submitting to.

In scope:
- A way for mods to target the current/active cycle when rerolling.
- Server-side logic to reroll an active cycle safely (per the locked decisions below).
- Player notification of the new map.

Out of scope:
- Changing how upcoming-cycle reroll works (existing behavior must stay byte-for-byte the same by default).
- Reworking cycle lifecycle/edition rollover beyond what's needed to swap the active map.
</domain>

<decisions>
## Implementation Decisions

### Command surface
- **Extend the existing `/tournament-reroll` command** with a new target parameter (e.g. `cycle: upcoming | current`), rather than adding a separate command.
- The parameter **defaults to `upcoming`** so the existing behavior (and existing API calls `reroll_next_cycle` / `choose_next_cycle`) is unchanged when the param is omitted.
- The explicit-choose path (passing a `code`) should also respect the target where it makes sense; if choosing an explicit map for the current cycle is out of scope/ambiguous, the planner may scope current-cycle reroll to the random path first — but the random reroll of the current cycle is the must-have.

### Submission handling (active cycle)
- On a **current-cycle reroll, wipe the active cycle's submissions along with the cycle** and start fresh on the new map. This is an intentional, irreversible reset — the old map's in-progress runs are discarded.
- Because this is destructive to live player data, the implementation must be deliberate: only delete submissions that belong to the cycle being rerolled, scoped by `cycle_id` (do not touch other cycles/categories). Mod-only access control (existing Mod/Sensei gate) still applies.

### Timing + notification
- **Preserve the active cycle's window**: keep the original `started_at` and `ended_at` (same deadline). Do NOT reset the timer to "now". The new map inherits the remaining time on the current cycle.
- **Announce the new map**: emit a cycle-update / announcement so the tournament channel reflects the swapped map for the active cycle. Players on the active cycle must be told the map changed.
- The new cycle row stays `status='active'`.

### Claude's Discretion
- Exact name/type of the new `/tournament-reroll` parameter and how it's surfaced (enum/choice vs boolean) — pick the clearest, consistent with existing transformer/param patterns in `apps/bot/extensions/tournaments.py`.
- Whether the "wipe + swap, preserve window" active reroll is implemented as a new service method (e.g. `reroll_active_cycle`) + new API route, or as a parameterization of the existing reroll path — pick whichever keeps the upcoming path untouched and the diff clean. A new dedicated method/route is preferred for clarity.
- Which existing event/queue is reused for the announcement. Reuse an existing tournament announcement/rollover event (e.g. the cycle-started/rollover pattern in `tournament_outbox_service.py` + the `api.tournament.*` bot consumer) rather than inventing a new pipeline, unless none fits.
- Eligible-map selection for the new active map should reuse the existing eligibility logic (`fetch_eligible_maps` with blacklist + `exclude_map_ids=[old_map_id]`, LRU fallback) — same as upcoming reroll.
</decisions>

<specifics>
## Specific Ideas

Reference implementation to mirror (upcoming-cycle reroll):
- Bot command: `apps/bot/extensions/tournaments.py` ~L892-951 (`tournament_reroll` slash command, Mod/Sensei gate, `reroll_next_cycle` / `choose_next_cycle` API client calls).
- API route: `apps/api/routes/v3/tournaments.py` ~L400-480 (`POST /categories/{category_id}/reroll`, `PATCH /categories/{category_id}/next-cycle`).
- Service: `apps/api/services/tournament_service.py` ~L675-747 (`reroll_map`: fetch pending → delete → select eligible/LRU → create).
- Repository: `apps/api/repository/tournaments_repository.py` — `fetch_pending_cycle` (L1101), `fetch_active_cycle` (L834), `check_active_cycle_for_category` (L283, returns `int | None`), `fetch_eligible_maps`, `fetch_least_recently_used_map`, `create_cycle`, `delete_cycle`.
- SDK: `libs/sdk/src/genjishimada_sdk/tournaments.py` — `CycleStatus` (L46), `TournamentNextCycleResponse` (L323), `TournamentCycleResponse`, `TournamentChooseMapRequest`.
- Events: `apps/api/services/tournament_outbox_service.py` — `TournamentCycleStartedEvent`, `TournamentCycleCompletedEvent`, `TournamentRolloverEvent`; bot consumer `@queue_consumer("api.tournament.rollover", ...)` in `tournaments.py` ~L305.

Key difference for current-cycle reroll vs upcoming:
- Fetch the `status='active'` cycle (via `fetch_active_cycle` / `check_active_cycle_for_category`), not the pending one.
- Delete that active cycle AND its submissions (scoped by cycle_id).
- Create the replacement cycle as `status='active'`, carrying over the SAME `started_at` / `ended_at`.
- Emit an announcement event so the live channel updates.
</specifics>

<canonical_refs>
## Canonical References

- `check_active_cycle_for_category` returns `int | None` (the cycle_id, or None), NOT a bool — this is a Phase-4 contract (commit 4fc56b6). Any new code calling it must treat the return as an optional cycle id.
- Project test-running gotchas (testmon deselection, `-p no:xdist`, multi-file `--no-testmon`) per CLAUDE.md / project memory — the executor must run a TRUE check (`uv run --directory apps/api pytest ... --no-testmon`) rather than trusting a green testmon-cached run.
- Follow Genji's three-layer pattern (route → service → repository), raw AsyncPG SQL (no ORM), msgspec structs in the SDK, and `BaseService.publish_message()` idempotency rules for any new event.
</canonical_refs>
