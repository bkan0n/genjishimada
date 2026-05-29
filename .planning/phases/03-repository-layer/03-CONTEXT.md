# Phase 3: Repository Layer - Context

**Gathered:** 2026-05-29
**Status:** Ready for planning

<domain>
## Phase Boundary

Implement a `TournamentRepository` class with raw SQL data access methods for all tournament database operations — config, categories, cycles, completions, streaks, and pending_transitions. No services, no controllers, no routes. Just the data access layer that downstream phases import.

</domain>

<decisions>
## Implementation Decisions

### Repository Class Organization
- **D-01:** Single `tournaments_repository.py` file in `apps/api/repository/` following the existing one-file-per-domain pattern (completions_repository.py, store_repository.py, maps_repository.py). A single `TournamentRepository(BaseRepository)` class contains all tournament-related queries.
- **D-02:** Provider function `provide_tournament_repository(state: State) -> TournamentRepository` at the bottom of the file, following existing convention.

### Cross-Write CTE Design
- **D-03:** Cross-write to `core.completions` uses a CTE that first checks the user's current best time, then conditionally inserts only when the tournament time is strictly faster. This prevents unnecessary trigger errors from `core.enforce_speed_rules_nonlegacy_only()` while the trigger still validates as a safety net.
- **D-04:** The cross-write CTE must set `tournament_completion_id` on the inserted `core.completions` row for metadata linking (per Phase 1 D-09).
- **D-05:** If the CTE determines the tournament time is NOT faster, the cross-write is a no-op (no insert, no error). The tournament completion still exists in `tournaments.completions` regardless.

### Leaderboard Query Strategy
- **D-06:** Leaderboard returns best-per-user using `DISTINCT ON (user_id)` with `ORDER BY user_id, verified DESC, time ASC` to select each user's best submission. Then an outer query applies `RANK() OVER (ORDER BY verified DESC, time ASC)` for tier-then-time ranking. This matches the ranking index on `tournaments.completions`.
- **D-07:** Leaderboard query joins `core.users` to get display name (using `COALESCE(global_name, nickname, 'Unknown')` per existing completions pattern).

### Method Scope
- **D-08:** Build ALL repository methods upfront covering every tournament table. The success criteria explicitly requires "all CRUD operations across tournament tables." Downstream phases (4-10) only add service and controller layers on top.
- **D-09:** Method groups to implement:
  - **Config:** `fetch_config()`, `update_config(blacklist_weeks)`
  - **Categories:** `create_category()`, `fetch_category(id)`, `fetch_categories()`, `update_category(id, updates)`, `delete_category(id)`, `check_active_cycle_for_category(id)` (returns bool)
  - **Cycles:** `create_cycle(category_id, map_id)`, `fetch_cycle(id)`, `fetch_active_cycle(category_id)`, `update_cycle_status(id, status, timestamps)`, `fetch_cycle_history(category_id, limit, offset)`
  - **Completions:** `create_tournament_completion(...)`, `fetch_leaderboard(cycle_id)`, `fetch_user_completion(cycle_id, user_id)`, `cross_write_to_core(user_id, map_id, time, ...)` (CTE per D-03)
  - **Streaks:** `fetch_streak(user_id)`, `upsert_streak(user_id, cycle_id)`
  - **Map Selection:** `fetch_eligible_maps(difficulties, blacklist_weeks)`, `fetch_least_recently_used_map(difficulties)` (fallback when pool exhausted)
  - **Pending Transitions:** `create_pending_transition(cycle_id, event_type, payload)`, `fetch_unpublished_transitions()`, `mark_transition_published(id)`

### Exception Handling
- **D-10:** Repository catches asyncpg constraint violations and re-raises as existing repository exception types (per Phase 2 D-07). Key constraint mappings:
  - `tournaments.categories` name UNIQUE → `UniqueConstraintViolationError`
  - `tournaments.completions (cycle_id, user_id, inserted_at)` UNIQUE → `UniqueConstraintViolationError`
  - FK violations on user_id, map_id, category_id, cycle_id → `ForeignKeyViolationError`
  - CHECK violations on cycle_frequency, status → `CheckConstraintViolationError`
- **D-11:** Use `extract_constraint_name(e)` helper from `repository.exceptions` for consistent constraint name extraction (matching completions_repository.py pattern).

### Claude's Discretion
- Exact method signatures (parameter names, return types) — follow existing repository patterns (`dict`, `list[dict]`, `int | None`)
- SQL query formatting and CTE structure — use triple-quoted strings with indentation per convention
- Whether `fetch_cycle_history` returns `tuple[int, list[dict]]` (with count) or `list[dict]` — follow whichever existing pattern fits best
- Whether to add `fetch_cycle_results(cycle_id)` separately or combine with leaderboard query
- Order of methods within the class — group by table/domain area

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing Repository Patterns
- `apps/api/repository/base.py` — `BaseRepository` base class with `_get_connection(conn)` pattern
- `apps/api/repository/completions_repository.py` — Reference for CTE-based queries, exception handling with `extract_constraint_name`, method signatures with `conn: Connection | None = None`
- `apps/api/repository/store_repository.py` — Reference for singleton config queries (`WHERE id = 1`), dynamic UPDATE with set_clauses pattern, JSONB casting (`$N::jsonb`)
- `apps/api/repository/exceptions.py` — `UniqueConstraintViolationError`, `ForeignKeyViolationError`, `CheckConstraintViolationError`, `extract_constraint_name()`

### Database Schema
- `apps/api/migrations/0020_tournaments.sql` — All tournament table definitions, constraints, indexes, and column types
- `apps/api/migrations/0017_fix_speed_trigger_check_verified.sql` — Speed enforcement trigger that cross-write CTE must account for
- `apps/api/migrations/0001_init.sql` — `core.completions` table definition and `core.users`/`core.maps` FK targets

### SDK Types (from Phase 2)
- `libs/sdk/src/genjishimada_sdk/tournaments.py` — All request/response/event Structs that repository return values must be convertible to
- `apps/api/services/exceptions/tournaments.py` — Domain exception classes that the service layer will use to translate repository exceptions

### Prior Phase Context
- `.planning/phases/01-database-schema-migrations/01-CONTEXT.md` — D-01 (boolean verified pattern), D-02 (tier-then-time = verified DESC, time ASC), D-03/D-04 (global cooldown from cycle history), D-05/D-06 (per-category XP, global config only holds blacklist_weeks)
- `.planning/phases/02-sdk-types-domain-exceptions/02-CONTEXT.md` — D-06/D-07 (three-tier exception pattern, existing repo exceptions sufficient)

### Project Planning
- `.planning/PROJECT.md` — Constraints section (no ORM, raw asyncpg, bot never writes to DB)
- `.planning/REQUIREMENTS.md` — Full v1 requirement list with IDs
- `.planning/ROADMAP.md` — Phase 3 success criteria (4 items)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `BaseRepository` from `repository/base.py` — base class with `_pool` and `_get_connection(conn)` for optional transaction participation
- `extract_constraint_name()` from `repository/exceptions.py` — extracts constraint name from asyncpg errors
- `DifficultyTop` type from SDK — the difficulty values used in `tournaments.categories.difficulties` array
- Existing `core.completions` queries in `completions_repository.py` — reference for CTE patterns, JOIN patterns with `core.users` and `core.maps`

### Established Patterns
- All repository methods accept `*, conn: Connection | None = None` as keyword-only parameter
- Use `_conn = self._get_connection(conn)` at method start
- Return `dict(row)` for single rows, `[dict(row) for row in rows]` for lists
- Use `fetchval()` for scalars, `fetchrow()` for single rows, `fetch()` for lists
- Dynamic UPDATE queries use `set_clauses` list with `f"{field} = ${idx}"` pattern (see store_repository.py)
- JSONB values cast with `$N::jsonb` in SQL
- asyncpg exceptions caught and re-raised as repository exceptions in try/except blocks

### Integration Points
- `apps/api/repository/__init__.py` — may need import registration (check if auto-discovered or explicit)
- Provider function will be used by service layer DI in Phase 4+ via `dependencies = {"tournament_repo": Provide(provide_tournament_repository)}`
- Cross-write query inserts into `core.completions` — must match existing column structure exactly

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches following existing codebase patterns.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 3-Repository Layer*
*Context gathered: 2026-05-29*
