# Phase 3: Repository Layer - Research

**Researched:** 2026-05-29
**Domain:** Raw SQL data access layer (asyncpg repository pattern)
**Confidence:** HIGH

## Summary

Phase 3 implements a single `TournamentRepository(BaseRepository)` class in `apps/api/repository/tournaments_repository.py` containing all raw SQL methods for tournament CRUD operations. This is a purely internal phase with no external dependencies to install -- the entire implementation uses existing codebase patterns (asyncpg, `BaseRepository`, repository exceptions) and writes raw SQL against the `tournaments` schema created in Phase 1.

The critical technical challenges are: (1) the cross-write CTE that must conditionally insert into `core.completions` while avoiding the speed enforcement trigger, and (2) the leaderboard query that must use `DISTINCT ON` for best-per-user selection followed by `RANK() OVER` for tier-then-time ranking. Both patterns have well-established precedents in the existing `completions_repository.py` and `store_repository.py`.

**Primary recommendation:** Implement as a single file (`tournaments_repository.py`) with methods grouped by table domain, following the exact patterns from `completions_repository.py` for exception handling and `store_repository.py` for singleton config queries.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Single `tournaments_repository.py` file in `apps/api/repository/` following the existing one-file-per-domain pattern (completions_repository.py, store_repository.py, maps_repository.py). A single `TournamentRepository(BaseRepository)` class contains all tournament-related queries.
- **D-02:** Provider function `provide_tournament_repository(state: State) -> TournamentRepository` at the bottom of the file, following existing convention.
- **D-03:** Cross-write to `core.completions` uses a CTE that first checks the user's current best time, then conditionally inserts only when the tournament time is strictly faster. This prevents unnecessary trigger errors from `core.enforce_speed_rules_nonlegacy_only()` while the trigger still validates as a safety net.
- **D-04:** The cross-write CTE must set `tournament_completion_id` on the inserted `core.completions` row for metadata linking (per Phase 1 D-09).
- **D-05:** If the CTE determines the tournament time is NOT faster, the cross-write is a no-op (no insert, no error). The tournament completion still exists in `tournaments.completions` regardless.
- **D-06:** Leaderboard returns best-per-user using `DISTINCT ON (user_id)` with `ORDER BY user_id, verified DESC, time ASC` to select each user's best submission. Then an outer query applies `RANK() OVER (ORDER BY verified DESC, time ASC)` for tier-then-time ranking. This matches the ranking index on `tournaments.completions`.
- **D-07:** Leaderboard query joins `core.users` to get display name (using `COALESCE(global_name, nickname, 'Unknown')` per existing completions pattern).
- **D-08:** Build ALL repository methods upfront covering every tournament table. The success criteria explicitly requires "all CRUD operations across tournament tables." Downstream phases (4-10) only add service and controller layers on top.
- **D-09:** Method groups to implement:
  - **Config:** `fetch_config()`, `update_config(blacklist_weeks)`
  - **Categories:** `create_category()`, `fetch_category(id)`, `fetch_categories()`, `update_category(id, updates)`, `delete_category(id)`, `check_active_cycle_for_category(id)` (returns bool)
  - **Cycles:** `create_cycle(category_id, map_id)`, `fetch_cycle(id)`, `fetch_active_cycle(category_id)`, `update_cycle_status(id, status, timestamps)`, `fetch_cycle_history(category_id, limit, offset)`
  - **Completions:** `create_tournament_completion(...)`, `fetch_leaderboard(cycle_id)`, `fetch_user_completion(cycle_id, user_id)`, `cross_write_to_core(user_id, map_id, time, ...)` (CTE per D-03)
  - **Streaks:** `fetch_streak(user_id)`, `upsert_streak(user_id, cycle_id)`
  - **Map Selection:** `fetch_eligible_maps(difficulties, blacklist_weeks)`, `fetch_least_recently_used_map(difficulties)` (fallback when pool exhausted)
  - **Pending Transitions:** `create_pending_transition(cycle_id, event_type, payload)`, `fetch_unpublished_transitions()`, `mark_transition_published(id)`
- **D-10:** Repository catches asyncpg constraint violations and re-raises as existing repository exception types (per Phase 2 D-07). Key constraint mappings:
  - `tournaments.categories` name UNIQUE -> `UniqueConstraintViolationError`
  - `tournaments.completions (cycle_id, user_id, inserted_at)` UNIQUE -> `UniqueConstraintViolationError`
  - FK violations on user_id, map_id, category_id, cycle_id -> `ForeignKeyViolationError`
  - CHECK violations on cycle_frequency, status -> `CheckConstraintViolationError`
- **D-11:** Use `extract_constraint_name(e)` helper from `repository.exceptions` for consistent constraint name extraction (matching completions_repository.py pattern).

### Claude's Discretion
- Exact method signatures (parameter names, return types) -- follow existing repository patterns (`dict`, `list[dict]`, `int | None`)
- SQL query formatting and CTE structure -- use triple-quoted strings with indentation per convention
- Whether `fetch_cycle_history` returns `tuple[int, list[dict]]` (with count) or `list[dict]` -- follow whichever existing pattern fits best
- Whether to add `fetch_cycle_results(cycle_id)` separately or combine with leaderboard query
- Order of methods within the class -- group by table/domain area

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.
</user_constraints>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Tournament CRUD SQL | Database / Storage | -- | Raw data access via asyncpg against PostgreSQL |
| Cross-write CTE | Database / Storage | -- | Atomic conditional insert spans two tables in same DB |
| Leaderboard ranking | Database / Storage | -- | Window functions computed in PostgreSQL |
| Map eligibility filtering | Database / Storage | -- | Query-time filtering based on cycle history |
| Exception translation | API / Backend | Database / Storage | Repository catches asyncpg errors, re-raises structured |
| DI provider | API / Backend | -- | Litestar dependency injection wiring |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| asyncpg | >=0.30.0 | PostgreSQL async driver | Already in use, all repository code uses this [VERIFIED: codebase] |
| litestar | >=2.16.0 | State/DI types for provider function | Already in use [VERIFIED: codebase] |
| msgspec | >=0.19.0 | JSONB encoding for payload columns | Already in use for JSONB handling [VERIFIED: codebase] |

No new packages need to be installed. This phase uses only existing dependencies.

## Package Legitimacy Audit

No new packages required. All libraries referenced are existing dependencies already in the project's `pyproject.toml` files.

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Architecture Patterns

### System Architecture Diagram

```
TournamentRepository (single class)
    |
    v
BaseRepository._get_connection(conn) --> asyncpg.Connection | Pool
    |
    +--- Config methods -------> tournaments.config (singleton, WHERE id = 1)
    +--- Category methods -----> tournaments.categories (CRUD)
    +--- Cycle methods ---------> tournaments.cycles (lifecycle status management)
    +--- Completion methods ----> tournaments.completions (submissions, leaderboard)
    |       |
    |       +--- cross_write_to_core() --CTE--> core.completions (conditional insert)
    |                                              |
    |                                              v
    |                               enforce_speed_rules_nonlegacy_only() trigger
    |                               (safety net -- CTE pre-checks to avoid trigger errors)
    |
    +--- Streak methods --------> tournaments.streaks (upsert pattern)
    +--- Map Selection methods -> core.maps + tournaments.cycles (join + filter)
    +--- Transition methods ----> tournaments.pending_transitions (outbox pattern)
    |
    v
Repository Exceptions (asyncpg -> UniqueConstraintViolationError, etc.)
```

### Recommended Project Structure
```
apps/api/repository/
    tournaments_repository.py    # NEW -- TournamentRepository class + provide_tournament_repository()
    base.py                      # Existing -- BaseRepository (unchanged)
    exceptions.py                # Existing -- exception types + extract_constraint_name (unchanged)
```

### Pattern 1: BaseRepository Extension with Optional Connection
**What:** Every method accepts `*, conn: Connection | None = None` and uses `_conn = self._get_connection(conn)` to support both standalone calls and transaction participation.
**When to use:** Every repository method.
**Example:**
```python
# Source: apps/api/repository/store_repository.py (existing pattern)
async def fetch_config(
    self,
    *,
    conn: Connection | None = None,
) -> dict:
    """Fetch tournament configuration."""
    _conn = self._get_connection(conn)
    query = "SELECT * FROM tournaments.config WHERE id = 1"
    row = await _conn.fetchrow(query)
    return dict(row) if row else {}
```

### Pattern 2: Constraint Violation Exception Handling
**What:** Catch specific asyncpg exception types, extract constraint name, re-raise as repository exceptions with structured context.
**When to use:** Any INSERT/UPDATE/DELETE that could violate a constraint.
**Example:**
```python
# Source: apps/api/repository/completions_repository.py (existing pattern)
try:
    result = await _conn.fetchval(query, *args)
    return result
except UniqueViolationError as e:
    constraint_name = extract_constraint_name(e) or "unknown"
    raise UniqueConstraintViolationError(
        constraint_name, "tournaments.completions", str(e)
    ) from e
except ForeignKeyViolationError as e:
    constraint_name = extract_constraint_name(e) or "unknown"
    raise RepoFKError(
        constraint_name, "tournaments.completions", str(e)
    ) from e
```

### Pattern 3: Dynamic UPDATE with set_clauses
**What:** Build UPDATE queries dynamically from a dict of updates, with positional parameter indexing.
**When to use:** `update_category()` and `update_config()` where only changed fields should be SET.
**Example:**
```python
# Source: apps/api/repository/store_repository.py (existing pattern)
set_clauses: list[str] = []
values: list[object] = []
idx = 1
for field, value in updates.items():
    if field in ("placement_xp", "streak_xp"):
        set_clauses.append(f"{field} = ${idx}::jsonb")
    else:
        set_clauses.append(f"{field} = ${idx}")
    values.append(value)
    idx += 1
set_clauses.append(f"updated_at = now()")
query = f"UPDATE tournaments.categories SET {', '.join(set_clauses)} WHERE id = ${idx}"
values.append(category_id)
await _conn.execute(query, *values)
```

### Pattern 4: Paginated History with Count
**What:** Return `tuple[int, list[dict]]` with total count + paginated results for history/archive queries.
**When to use:** `fetch_cycle_history()`.
**Example:**
```python
# Source: apps/api/repository/store_repository.py:fetch_quest_history (existing pattern)
total = await _conn.fetchval(
    "SELECT COUNT(*) FROM tournaments.cycles WHERE category_id = $1",
    category_id,
)
rows = await _conn.fetch(
    """
    SELECT id, category_id, map_id, status, started_at, ended_at, created_at
    FROM tournaments.cycles
    WHERE category_id = $1
    ORDER BY created_at DESC
    LIMIT $2 OFFSET $3
    """,
    category_id, limit, offset,
)
return total or 0, [dict(row) for row in rows]
```

### Anti-Patterns to Avoid
- **Using `handle_db_exceptions` decorator:** Per CLAUDE.md, this is the old pattern being superseded by the three-tier exception hierarchy. New code should use explicit try/except blocks in the repository, not the decorator.
- **Returning raw `asyncpg.Record` objects:** Always convert via `dict(row)` or `[dict(row) for row in rows]`. Records are not serializable outside asyncpg context.
- **F-string interpolation in SQL:** Always use positional `$N` parameters. Never inject values via f-strings into query text (only column/table names for dynamic SET clauses).
- **Catching broad `Exception`:** Catch specific asyncpg types (`UniqueViolationError`, `ForeignKeyViolationError`, `CheckViolationError`). Let unexpected errors propagate.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Connection management | Custom pool/connection logic | `BaseRepository._get_connection(conn)` | Already handles connection vs pool fallback [VERIFIED: codebase] |
| Constraint name extraction | Manual string parsing | `extract_constraint_name(e)` from `repository.exceptions` | Standardized helper using `getattr(error, "constraint_name", None)` [VERIFIED: codebase] |
| JSONB encoding | Custom JSON serialization | `$N::jsonb` cast in SQL with msgspec encoding via `_async_pg_init` codecs | Custom codecs already configured in `app.py` [VERIFIED: codebase] |
| Difficulty matching | Python-side filtering | SQL `regexp_replace(m.difficulty, '\\s*[-+]\\s*$', '', '')` | Established pattern for converting DifficultyAll -> DifficultyTop in queries [VERIFIED: codebase] |

**Key insight:** This phase adds zero new libraries or tools. Every capability is already available in the codebase. The value is in getting the SQL queries right -- particularly the cross-write CTE and leaderboard ranking.

## Common Pitfalls

### Pitfall 1: Speed Enforcement Trigger on Cross-Write
**What goes wrong:** Inserting into `core.completions` without checking if the time is strictly faster triggers `core.enforce_speed_rules_nonlegacy_only()`, which raises a `CHECK` violation error (ERRCODE 23514) with an error message like "completion=TRUE time X must be strictly faster than current best Y".
**Why it happens:** The trigger fires on BEFORE INSERT and checks if `new.time >= best_time`. If the tournament time is slower or equal, the trigger rejects the row.
**How to avoid:** The CTE must first query the user's current best time in `core.completions` and only perform the INSERT when `tournament_time < best_time` (or no existing row). This makes the trigger a safety net, not the primary check.
**Warning signs:** `asyncpg.exceptions.CheckViolationError` with error message containing "must be strictly faster".

### Pitfall 2: DISTINCT ON Ordering Mismatch
**What goes wrong:** Using `DISTINCT ON (user_id)` without matching ORDER BY clause causes PostgreSQL error: "SELECT DISTINCT ON expressions must match initial ORDER BY expressions."
**Why it happens:** PostgreSQL requires `DISTINCT ON` columns to match the leftmost ORDER BY columns exactly.
**How to avoid:** For leaderboard best-per-user: `DISTINCT ON (user_id) ... ORDER BY user_id, verified DESC, time ASC`. The outer query then re-orders with `RANK() OVER`.
**Warning signs:** PostgreSQL syntax error at query execution time.

### Pitfall 3: JSONB Array Columns Require Explicit Cast
**What goes wrong:** Passing Python `list[dict]` directly to asyncpg for JSONB columns fails or produces wrong types without the `::jsonb` cast.
**Why it happens:** asyncpg doesn't automatically infer JSONB from Python dicts/lists. The custom codec in `_async_pg_init` handles `jsonb` format encoding, but the SQL query must specify the cast.
**How to avoid:** Always use `$N::jsonb` in INSERT/UPDATE queries for `placement_xp`, `streak_xp`, and `payload` columns. The msgspec codec will handle serialization.
**Warning signs:** `DataError: invalid input syntax for type json` or unexpected `text` type instead of `jsonb`.

### Pitfall 4: Difficulty Column Stores Extended Values
**What goes wrong:** Filtering `core.maps` by `difficulty IN ('Easy', 'Hard')` misses maps with difficulty "Easy +", "Easy -", "Hard +", "Hard -".
**Why it happens:** The `core.maps.difficulty` column stores `DifficultyAll` values (e.g., "Hard +", "Very Hard -"), not `DifficultyTop` values.
**How to avoid:** Use `regexp_replace(m.difficulty, '\\s*[-+]\\s*$', '', '') = ANY($1)` to strip the +/- suffix before matching against the category's `difficulties` array (which contains `DifficultyTop` values).
**Warning signs:** Eligible map pool returns fewer maps than expected.

### Pitfall 5: Singleton Config Row Missing
**What goes wrong:** `fetch_config()` returns empty dict if the singleton row doesn't exist.
**Why it happens:** The migration inserts the singleton row, but test databases might not have it if migrations ran in wrong order or were skipped.
**How to avoid:** The migration file `0020_tournaments.sql` includes `INSERT INTO tournaments.config ... ON CONFLICT (id) DO NOTHING`. Repository method should handle the empty case gracefully (return empty dict).
**Warning signs:** `NoneType` errors when accessing config fields.

### Pitfall 6: tournament_completion_id Column in Cross-Write
**What goes wrong:** Cross-write inserts into `core.completions` but forgets to set the `tournament_completion_id` FK column, breaking the metadata link.
**Why it happens:** The `tournament_completion_id` column was added by ALTER TABLE in migration 0020. The existing INSERT patterns in `completions_repository.py` don't include it since they predate tournaments.
**How to avoid:** The cross-write CTE must include `tournament_completion_id` in the INSERT column list and pass the tournament completion ID as a parameter.
**Warning signs:** `tournament_completion_id` is always NULL on cross-written rows.

## Code Examples

### Cross-Write CTE (Critical Path)
```python
# Pattern derived from: D-03, D-04, D-05, speed trigger in 0017 migration
# This is the most complex query in the repository.
async def cross_write_to_core(
    self,
    tournament_completion_id: int,
    user_id: int,
    map_id: int,
    time: float,
    screenshot: str,
    video: str | None,
    *,
    conn: Connection | None = None,
) -> int | None:
    """Conditionally write tournament completion to core.completions.

    Only inserts when tournament time is strictly faster than the user's
    current best non-legacy time for this map. The CTE pre-checks to
    avoid triggering enforce_speed_rules_nonlegacy_only() errors.

    Args:
        tournament_completion_id: ID of the tournament completion record.
        user_id: User ID.
        map_id: Map ID.
        time: Completion time.
        screenshot: Screenshot URL.
        video: Optional video URL.
        conn: Optional connection for transaction support.

    Returns:
        The new core.completions ID if inserted, None if skipped (time not faster).
    """
    _conn = self._get_connection(conn)
    query = """
        WITH current_best AS (
            SELECT MIN(c.time) AS best_time
            FROM core.completions c
            WHERE c.user_id = $2
              AND c.map_id = $3
              AND c.legacy = FALSE
        ),
        should_insert AS (
            SELECT
                CASE
                    WHEN cb.best_time IS NULL THEN TRUE
                    WHEN $4 < cb.best_time THEN TRUE
                    ELSE FALSE
                END AS do_insert
            FROM current_best cb
        ),
        map_flags AS (
            SELECT
                m.official,
                (m.playtesting = 'In Progress') AS in_playtest
            FROM core.maps m
            WHERE m.id = $3
        ),
        computed AS (
            SELECT
                (mf.in_playtest
                 OR $6::text IS NULL OR $6::text = ''
                 OR NOT mf.official) AS completion_flag
            FROM map_flags mf
        )
        INSERT INTO core.completions (
            map_id, user_id, time, screenshot, video,
            completion, tournament_completion_id
        )
        SELECT $3, $2, $4, $5, $6, co.completion_flag, $1
        FROM should_insert si
        CROSS JOIN computed co
        WHERE si.do_insert = TRUE
        RETURNING id
    """
    return await _conn.fetchval(
        query,
        tournament_completion_id,  # $1
        user_id,                   # $2
        map_id,                    # $3
        time,                      # $4
        screenshot,                # $5
        video,                     # $6
    )
```

### Leaderboard Query
```python
# Pattern derived from: D-06, D-07, completions_repository.py ranking patterns
async def fetch_leaderboard(
    self,
    cycle_id: int,
    *,
    conn: Connection | None = None,
) -> list[dict]:
    """Fetch ranked leaderboard for a tournament cycle.

    Returns best-per-user submissions ranked by tier-then-time:
    verified completions outrank unverified, fastest time wins within tier.

    Args:
        cycle_id: Cycle to fetch leaderboard for.
        conn: Optional connection for transaction support.

    Returns:
        List of ranked leaderboard entry dicts.
    """
    _conn = self._get_connection(conn)
    query = """
        WITH best_per_user AS (
            SELECT DISTINCT ON (tc.user_id)
                tc.user_id,
                tc.time,
                tc.verified,
                tc.completion
            FROM tournaments.completions tc
            WHERE tc.cycle_id = $1
            ORDER BY tc.user_id, tc.verified DESC, tc.time ASC
        )
        SELECT
            RANK() OVER (ORDER BY bpu.verified DESC, bpu.time ASC)::int AS rank,
            bpu.user_id,
            COALESCE(u.global_name, u.nickname, 'Unknown') AS name,
            bpu.time::float AS time,
            bpu.verified,
            bpu.completion
        FROM best_per_user bpu
        JOIN core.users u ON u.id = bpu.user_id
        ORDER BY bpu.verified DESC, bpu.time ASC
    """
    rows = await _conn.fetch(query, cycle_id)
    return [dict(row) for row in rows]
```

### Eligible Maps Query
```python
# Pattern derived from: D-09, Phase 1 D-03/D-04, regexp_replace pattern from store_repository.py
async def fetch_eligible_maps(
    self,
    difficulties: list[str],
    blacklist_weeks: int,
    *,
    conn: Connection | None = None,
) -> list[dict]:
    """Fetch maps eligible for tournament selection.

    Filters to official, non-archived maps matching the category's
    difficulties, excluding maps used in any tournament cycle within
    the blacklist window.

    Args:
        difficulties: List of DifficultyTop values to match.
        blacklist_weeks: Number of weeks for map cooldown.
        conn: Optional connection for transaction support.

    Returns:
        List of eligible map dicts.
    """
    _conn = self._get_connection(conn)
    query = """
        SELECT m.id, m.code, m.map_name, m.difficulty
        FROM core.maps m
        WHERE m.official = TRUE
          AND m.archived = FALSE
          AND m.code IS NOT NULL
          AND regexp_replace(m.difficulty, '\\s*[-+]\\s*$', '', '') = ANY($1)
          AND m.id NOT IN (
              SELECT cy.map_id
              FROM tournaments.cycles cy
              WHERE cy.started_at > now() - ($2 || ' weeks')::interval
          )
        ORDER BY random()
    """
    rows = await _conn.fetch(query, difficulties, blacklist_weeks)
    return [dict(row) for row in rows]
```

### Streak Upsert
```python
# Pattern: PostgreSQL INSERT ... ON CONFLICT ... DO UPDATE (upsert)
async def upsert_streak(
    self,
    user_id: int,
    cycle_id: int,
    *,
    conn: Connection | None = None,
) -> dict:
    """Upsert user participation streak.

    Increments current_streak and updates max_streak if exceeded.
    Creates the streak row if it doesn't exist.

    Args:
        user_id: User ID.
        cycle_id: Current cycle ID.
        conn: Optional connection for transaction support.

    Returns:
        Updated streak dict.
    """
    _conn = self._get_connection(conn)
    query = """
        INSERT INTO tournaments.streaks (user_id, current_streak, max_streak, last_cycle_id, updated_at)
        VALUES ($1, 1, 1, $2, now())
        ON CONFLICT (user_id) DO UPDATE SET
            current_streak = tournaments.streaks.current_streak + 1,
            max_streak = GREATEST(tournaments.streaks.max_streak, tournaments.streaks.current_streak + 1),
            last_cycle_id = $2,
            updated_at = now()
        RETURNING user_id, current_streak, max_streak, last_cycle_id, updated_at
    """
    row = await _conn.fetchrow(query, user_id, cycle_id)
    return dict(row) if row else {}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `handle_db_exceptions` decorator | Three-tier exception hierarchy (repo -> service -> controller) | Recent codebase evolution | New code MUST NOT use decorator, use explicit try/except [VERIFIED: CLAUDE.md] |
| Single `asyncpg.exceptions` catch | `extract_constraint_name(e)` + specific repo exceptions | `repository/exceptions.py` addition | Structured error context propagation [VERIFIED: codebase] |

**Deprecated/outdated:**
- `handle_db_exceptions` decorator in `utilities/errors.py`: Still present on older endpoints but explicitly marked as superseded in CLAUDE.md. New tournament repository code must NOT use this decorator.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `regexp_replace(m.difficulty, '\\s*[-+]\\s*$', '', '')` correctly converts all DifficultyAll values to DifficultyTop values in PostgreSQL | Code Examples (Eligible Maps) | Map selection could miss or include wrong difficulty tiers. Mitigated by existing codebase usage in store_repository.py and community_repository.py. |
| A2 | asyncpg JSONB codec configured in `_async_pg_init` handles Python list/dict -> JSONB encoding transparently when `$N::jsonb` cast is used | Common Pitfalls (Pitfall 3) | JSONB columns could receive malformed data. Mitigated by existing codebase usage in store_repository.py. |
| A3 | `blacklist_weeks` integer can be safely cast to interval via `($N \|\| ' weeks')::interval` in PostgreSQL | Code Examples (Eligible Maps) | Blacklist filtering would fail. Standard PostgreSQL pattern, low risk. |
| A4 | Streak upsert ON CONFLICT on `user_id` works with the unique index `idx_streaks_user_id` (not a constraint) | Code Examples (Streak Upsert) | The `ON CONFLICT (user_id)` clause requires a unique index or constraint. The migration creates `CREATE UNIQUE INDEX idx_streaks_user_id ON tournaments.streaks (user_id)` which satisfies this requirement. |

## Open Questions

1. **Should `fetch_cycle_history` include leaderboard standings for each cycle?**
   - What we know: `TournamentCycleResultsResponse` includes a `standings: list[TournamentLeaderboardEntryResponse]` field, suggesting cycle history should include standings.
   - What's unclear: Whether to embed standings in the history query (expensive N+1 or JOIN) or have a separate `fetch_cycle_results(cycle_id)` method called per-cycle by the service.
   - Recommendation: Implement separate `fetch_cycle_results(cycle_id)` that returns cycle + standings. The service layer can compose history + results. This keeps repository methods simple and avoids N+1 in the repository layer. Per CONTEXT.md Claude's Discretion, this is our call.

2. **Should `cross_write_to_core` handle the `completion` flag logic?**
   - What we know: The existing `completions_repository.create_completion()` uses a CTE to compute `completion_flag` based on `in_playtest`, `video` presence, and `official` status.
   - What's unclear: Whether tournament cross-writes should replicate this logic or simplify it since tournament maps are always official and not in playtest.
   - Recommendation: Replicate the existing completion_flag logic for safety. Tournament maps SHOULD always be official, but the repository shouldn't make that assumption -- the CTE should compute the flag the same way. This is already shown in the code example above.

## Project Constraints (from CLAUDE.md)

- **No ORM:** All database access uses raw SQL via asyncpg. [VERIFIED: CLAUDE.md]
- **Positional parameters:** Use `$1, $2, ...` (asyncpg style). Never f-string interpolation in SQL. [VERIFIED: CLAUDE.md]
- **Type annotations:** All function parameters and return types must be annotated. [VERIFIED: CLAUDE.md]
- **Docstrings:** Google style, required for all public methods. [VERIFIED: CLAUDE.md]
- **Line length:** 120 characters. [VERIFIED: CLAUDE.md]
- **Logger:** `log = getLogger(__name__)` at module level, `%s`-style formatting. [VERIFIED: CLAUDE.md]
- **Imports:** `from __future__ import annotations`, `TYPE_CHECKING` guards for type-only imports. [VERIFIED: codebase]
- **Exception handling:** Use explicit try/except with specific types, NOT `handle_db_exceptions` decorator. Use `from e` to preserve chain. [VERIFIED: CLAUDE.md]
- **Connection pattern:** `*, conn: Connection | None = None` keyword-only, `_conn = self._get_connection(conn)`. [VERIFIED: codebase]
- **Return types:** `dict(row)` for single, `[dict(row) for row in rows]` for lists, `fetchval()` for scalars. [VERIFIED: codebase]
- **JSONB cast:** Use `$N::jsonb` for JSONB columns. [VERIFIED: codebase]
- **Provider function at bottom of file:** `async def provide_tournament_repository(state: State) -> TournamentRepository`. [VERIFIED: codebase]

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.3.5+ with pytest-asyncio (auto mode), pytest-databases[postgres] |
| Config file | `apps/api/pyproject.toml` (pytest section) |
| Quick run command | `uv run --directory apps/api pytest tests/repository/tournaments/ -v -p no:xdist` |
| Full suite command | `just test-api` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SC-1 | TournamentRepository class with CRUD methods | unit | `uv run --directory apps/api pytest tests/repository/tournaments/ -v -p no:xdist` | No -- Wave 0 |
| SC-2 | Methods follow conn pattern | unit | Same as above (tested implicitly by all tests using asyncpg_conn fixture) | No -- Wave 0 |
| SC-3 | Cross-write CTE checks best time | integration | `uv run --directory apps/api pytest tests/repository/tournaments/test_tournaments_repository_cross_write.py -v -p no:xdist` | No -- Wave 0 |
| SC-4 | Leaderboard RANK() OVER ranking | unit | `uv run --directory apps/api pytest tests/repository/tournaments/test_tournaments_repository_leaderboard.py -v -p no:xdist` | No -- Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run --directory apps/api pytest tests/repository/tournaments/ -v -p no:xdist`
- **Per wave merge:** `just test-api`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/repository/tournaments/` directory -- tournament-specific test subdirectory
- [ ] `tests/repository/tournaments/conftest.py` -- tournament test fixtures (create_test_category, create_test_cycle, create_test_tournament_completion factory fixtures)
- [ ] Test files covering each method group (config, categories, cycles, completions, streaks, map selection, transitions)
- [ ] Framework install: none needed -- pytest-databases and pytest-asyncio already configured

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | N/A -- repository layer has no auth logic |
| V3 Session Management | no | N/A |
| V4 Access Control | no | N/A -- access control is service/controller concern |
| V5 Input Validation | yes | Positional parameters prevent SQL injection; constraint checks in DB |
| V6 Cryptography | no | N/A |

### Known Threat Patterns for asyncpg repository

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection | Tampering | Positional `$N` parameters (never f-string interpolation in query values) [VERIFIED: asyncpg built-in] |
| Constraint bypass | Tampering | Database constraints (UNIQUE, FK, CHECK) enforce invariants regardless of application code [VERIFIED: migration 0020] |
| Mass assignment via dynamic UPDATE | Elevation of Privilege | `update_category()` must validate field names against allowlist before building SET clause |

## Sources

### Primary (HIGH confidence)
- `apps/api/repository/base.py` -- BaseRepository class pattern
- `apps/api/repository/completions_repository.py` -- CTE patterns, exception handling, method signatures
- `apps/api/repository/store_repository.py` -- Singleton config queries, dynamic UPDATE, pagination pattern
- `apps/api/repository/exceptions.py` -- Exception types and `extract_constraint_name()`
- `apps/api/migrations/0020_tournaments.sql` -- All tournament table definitions
- `apps/api/migrations/0017_fix_speed_trigger_check_verified.sql` -- Speed enforcement trigger
- `apps/api/migrations/0001_init.sql` -- core.completions and core.maps table definitions
- `libs/sdk/src/genjishimada_sdk/tournaments.py` -- SDK types for response shape reference
- `libs/sdk/src/genjishimada_sdk/difficulties.py` -- DifficultyTop type definition
- `apps/api/services/exceptions/tournaments.py` -- Domain exception classes (downstream consumers)
- `apps/api/tests/conftest.py` -- Test fixture patterns (create_test_map, create_test_user, create_test_completion)
- `CLAUDE.md` -- Project coding standards and conventions

### Secondary (MEDIUM confidence)
- None needed -- all findings are from codebase inspection

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- no new packages, all from existing codebase
- Architecture: HIGH -- direct extension of established repository pattern with 6+ existing examples
- Pitfalls: HIGH -- all derived from actual codebase analysis (trigger behavior, JSONB casting, difficulty column values)
- Cross-write CTE: HIGH -- trigger source code fully read, existing insert patterns analyzed
- Leaderboard query: HIGH -- DISTINCT ON + RANK() OVER is standard PostgreSQL, index exists for it

**Research date:** 2026-05-29
**Valid until:** Indefinite (codebase patterns, not external library versions)
