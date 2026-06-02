# Phase 2: SDK Types & Domain Exceptions - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md -- this log preserves the alternatives considered.

**Date:** 2026-05-29
**Phase:** 02-SDK Types & Domain Exceptions
**Areas discussed:** SDK Module Organization, Event Type Scope, Response Type Granularity, Exception Granularity
**Mode:** --auto (all decisions auto-selected)

---

## SDK Module Organization

| Option | Description | Selected |
|--------|-------------|----------|
| Single tournaments.py | One file following existing one-file-per-domain pattern | [auto] |
| Split submodules | Separate files for config, cycles, completions, events | |

**User's choice:** [auto] Single tournaments.py (recommended default)
**Notes:** Existing SDK modules each cover their entire domain in one file. Tournament structs (~20-30 types) fit comfortably.

---

## Event Type Scope

| Option | Description | Selected |
|--------|-------------|----------|
| All events upfront | Define all 4 tournament event types now | [auto] |
| Incremental per phase | Only define events needed by the next 1-2 phases | |

**User's choice:** [auto] All events upfront (recommended default)
**Notes:** Struct definitions are lightweight. Having them available from Phase 3 onward prevents SDK churn in later phases.

---

## Response Type Granularity

| Option | Description | Selected |
|--------|-------------|----------|
| Distinct types per use case | Separate struct for each response shape (config, category, cycle, leaderboard entry, etc.) | [auto] |
| Minimal with optional fields | Fewer types, more None-defaulted fields | |

**User's choice:** [auto] Distinct types per use case (recommended default)
**Notes:** Follows completions pattern (CompletionResponse, CompletionSubmissionResponse, DashboardCompletionResponse are all distinct). Different consumers need different shapes.

---

## Exception Granularity

| Option | Description | Selected |
|--------|-------------|----------|
| One per business rule violation | ~8 specific exception classes under TournamentsError base | [auto] |
| Broad categories only | 3-4 general exceptions (not found, conflict, validation) | |

**User's choice:** [auto] One per business rule violation (recommended default)
**Notes:** Matches existing density in completions (7 exceptions) and maps (12+ exceptions). Each exception maps to a distinct HTTP error message.

---

## Claude's Discretion

- Exact field names on SDK structs (follow existing patterns)
- Struct field ordering (required first, defaulted last)
- Whether to define JSONB sub-structs for placement_xp/streak_xp (preferred for type safety)

## Deferred Ideas

None -- auto mode stayed within phase scope.
