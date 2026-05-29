# Phase 5: Map Selection & Blacklist - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-29
**Phase:** 5-Map Selection & Blacklist
**Areas discussed:** Pre-roll storage, API endpoint design, Reroll behavior, Pool exhaustion handling
**Mode:** --auto (all decisions auto-selected)

---

## Pre-roll Storage

| Option | Description | Selected |
|--------|-------------|----------|
| Pending cycle records | Store pre-rolled maps as `tournaments.cycles` with `status = 'pending'` | [auto] |
| Separate pre-roll table | New `tournaments.pending_maps` table for pre-rolled selections | |
| In-memory / config JSONB | Store next-map selections in config or ephemeral storage | |

**User's choice:** [auto] Pending cycle records (recommended default)
**Notes:** The schema already has `status = 'pending'` on `tournaments.cycles`. Using existing table avoids schema changes and naturally fits the cycle lifecycle.

---

## API Endpoint Design

| Option | Description | Selected |
|--------|-------------|----------|
| Category-scoped nested | Endpoints nested under `/categories/{id}/...` (next-cycle, select-map, reroll) | [auto] |
| Top-level map-selection | Separate `/tournaments/map-selection/...` endpoints | |
| Single multi-action endpoint | One endpoint with action parameter | |

**User's choice:** [auto] Category-scoped nested endpoints (recommended default)
**Notes:** Follows REST convention — map selection is inherently a per-category operation. Keeps the URL structure intuitive for admins.

---

## Reroll Behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Delete + create new | Delete pending cycle, create fresh one with new selection | [auto] |
| Update map_id in-place | UPDATE the existing pending cycle's map_id column | |

**User's choice:** [auto] Delete + create new (recommended default)
**Notes:** Cleaner semantics, avoids UPDATE on identity columns, produces fresh record timestamps.

---

## Pool Exhaustion Handling

| Option | Description | Selected |
|--------|-------------|----------|
| Raise NoEligibleMapsError | Domain exception → 422, admin must adjust config | [auto] |
| Silent no-op | Return empty response, no cycle created | |
| Relax blacklist automatically | Temporarily reduce blacklist_weeks until a map is found | |

**User's choice:** [auto] Raise NoEligibleMapsError (recommended default)
**Notes:** Explicit failure is better than silent no-op. Admin should know they need more maps or a shorter cooldown. LRU fallback already covers the "pool exhausted but maps exist" case.

---

## Claude's Discretion

- Exact response struct for next-cycle preview
- Whether `choose_map` accepts map_code or map_id
- Whether to add `PendingCycleAlreadyExistsError` or reuse generic conflict
- SQL for fetching pending cycle with joined map info
- Logging format for pool exhaustion warning

## Deferred Ideas

None — all discussion stayed within phase scope.
