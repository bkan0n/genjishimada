# Phase 3: Repository Layer - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md -- this log preserves the alternatives considered.

**Date:** 2026-05-29
**Phase:** 03-Repository Layer
**Areas discussed:** Repository class organization, Cross-write CTE design, Leaderboard query strategy, Method scope breadth
**Mode:** --auto (all decisions auto-selected)

---

## Repository Class Organization

| Option | Description | Selected |
|--------|-------------|----------|
| Single file | One `tournaments_repository.py` matching existing one-file-per-domain pattern | [auto] |
| Split by sub-domain | Separate files for config, cycles, completions, etc. | |

**User's choice:** [auto] Single file (recommended default)
**Notes:** Every existing domain (completions, maps, store, playtest) uses a single repository file. No precedent for splitting.

---

## Cross-Write CTE Design

| Option | Description | Selected |
|--------|-------------|----------|
| CTE with conditional INSERT | Check best time first, only insert if faster; trigger validates as safety net | [auto] |
| INSERT and catch trigger exception | Let the speed trigger reject and catch the error | |
| Temporarily disable trigger | Disable trigger for the cross-write row, re-enable after | |

**User's choice:** [auto] CTE with conditional INSERT (recommended default)
**Notes:** The speed enforcement trigger fires on INSERT to core.completions. A CTE pre-check avoids unnecessary trigger errors. If time is not faster, the cross-write is a no-op -- tournament completion still exists in tournaments.completions.

---

## Leaderboard Query Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| DISTINCT ON + RANK() | DISTINCT ON (user_id) for best-per-user, then RANK() in outer query | [auto] |
| Window function only | RANK() over all submissions, filter rank=1 | |
| Subquery approach | Subquery for best per user, then rank results | |

**User's choice:** [auto] DISTINCT ON + RANK() (recommended default)
**Notes:** PostgreSQL-idiomatic. Leverages the ranking index (cycle_id, verified DESC, time ASC). Returns one row per user with their best submission, then ranks across users.

---

## Method Scope Breadth

| Option | Description | Selected |
|--------|-------------|----------|
| All methods upfront | Build complete repository covering all tournament tables | [auto] |
| Incremental per phase | Only methods needed for Phase 4 now, add rest later | |

**User's choice:** [auto] All methods upfront (recommended default)
**Notes:** Phase 3 success criteria explicitly states "all CRUD operations across tournament tables." Building everything now means Phases 4-10 only need services and controllers.

---

## Claude's Discretion

- Exact method signatures (parameter names, return types)
- SQL query formatting and CTE structure
- Whether fetch_cycle_history includes total count
- Whether to add fetch_cycle_results separately or combine with leaderboard
- Order of methods within the class

## Deferred Ideas

None -- discussion stayed within phase scope.
