# Phase 3: Repository Layer - Pattern Map

**Mapped:** 2026-05-29
**Files analyzed:** 1 new file
**Analogs found:** 3 / 1

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `apps/api/repository/tournaments_repository.py` | repository | CRUD | `apps/api/repository/completions_repository.py` | exact |

**Secondary analogs:**
- `apps/api/repository/store_repository.py` -- singleton config queries, dynamic UPDATE, paginated history, `regexp_replace` difficulty
- `apps/api/repository/base.py` -- base class (inherited, not copied)

## Pattern Assignments

### `apps/api/repository/tournaments_repository.py` (repository, CRUD)

**Primary Analog:** `apps/api/repository/completions_repository.py`
**Secondary Analog:** `apps/api/repository/store_repository.py`

---

**Imports pattern** (`completions_repository.py` lines 1-19):
```python
"""Repository for completions domain database operations."""

from __future__ import annotations

from typing import Any

from asyncpg import Connection, Pool
from asyncpg.exceptions import CheckViolationError, ForeignKeyViolationError, UniqueViolationError
from litestar.datastructures import State

from repository.base import BaseRepository
from repository.exceptions import (
    CheckConstraintViolationError,
    UniqueConstraintViolationError,
    extract_constraint_name,
)
from repository.exceptions import (
    ForeignKeyViolationError as RepoFKError,
)
```
**Key detail:** `ForeignKeyViolationError` is aliased to `RepoFKError` to avoid name collision with `asyncpg.exceptions.ForeignKeyViolationError`. The tournament repository must follow this exact alias pattern.

---

**Class declaration + `__init__` pattern** (`completions_repository.py` lines 22-31):
```python
class CompletionsRepository(BaseRepository):
    """Repository for completions domain."""

    def __init__(self, pool: Pool) -> None:
        """Initialize repository.

        Args:
            pool: AsyncPG connection pool.
        """
        super().__init__(pool)
```

---

**Method signature pattern** (`completions_repository.py` lines 33-41, `store_repository.py` lines 72-88):

All repository methods use `*, conn: Connection | None = None` as keyword-only parameter and call `_conn = self._get_connection(conn)` at the start:

```python
async def fetch_user_completions(
    self,
    user_id: int,
    difficulty: str | None,
    page_size: int,
    page_number: int,
    *,
    conn: Connection | None = None,
) -> list[dict]:
    """Fetch verified completions for a user.

    Args:
        user_id: User ID to fetch completions for.
        difficulty: Optional difficulty filter.
        page_size: Number of results per page.
        page_number: Page number (1-indexed).
        conn: Optional connection for transaction support.

    Returns:
        List of completion records as dicts.
    """
    _conn = self._get_connection(conn)
```

---

**Singleton config fetch pattern** (`store_repository.py` lines 72-88):
```python
async def fetch_config(
    self,
    *,
    conn: Connection | None = None,
) -> dict:
    """Fetch store configuration.

    Args:
        conn: Optional connection for transaction support.

    Returns:
        Config dict or empty dict if not found.
    """
    _conn = self._get_connection(conn)
    query = "SELECT * FROM store.config WHERE id = 1"
    row = await _conn.fetchrow(query)
    return dict(row) if row else {}
```

---

**Dynamic UPDATE with set_clauses pattern** (`store_repository.py` lines 96-112):
```python
async def update_quest_config(
    self,
    updates: dict,
    *,
    conn: Connection | None = None,
) -> None:
    """Update quest configuration fields."""
    if not updates:
        return
    _conn = self._get_connection(conn)
    set_clauses = []
    values: list[object] = []
    for idx, (field, value) in enumerate(updates.items(), start=1):
        set_clauses.append(f"{field} = ${idx}")
        values.append(value)
    query = f"UPDATE store.quest_config SET {', '.join(set_clauses)} WHERE id = 1"
    await _conn.execute(query, *values)
```
**For JSONB fields**, use conditional `::jsonb` cast (`store_repository.py` lines 1002-1009):
```python
if quest_data is not None:
    set_clauses.append(f"quest_data = ${idx}::jsonb")
    values.append(quest_data)
    idx += 1
```

---

**CTE-based INSERT with completion_flag logic** (`completions_repository.py` lines 1539-1573):
```python
_conn = self._get_connection(conn)
query = """
WITH target_map AS (
    SELECT
        id AS map_id,
        official,
        (playtesting = 'In Progress') AS in_playtest
    FROM core.maps
    WHERE code = $1
),
computed AS (
    SELECT
        map_id,
        (in_playtest
         OR $5::text IS NULL OR $5::text = ''
         OR NOT official) AS completion_flag
    FROM target_map
)
INSERT INTO core.completions (
    map_id, user_id, time, screenshot, video, completion
)
SELECT c.map_id, $2, $3, $4, $5, c.completion_flag
FROM computed c
RETURNING id;
"""

try:
    completion_id = await _conn.fetchval(query, code, user_id, time, screenshot, video)
    return completion_id
except UniqueViolationError as e:
    constraint_name = extract_constraint_name(e) or "unknown"
    raise UniqueConstraintViolationError(constraint_name, "core.completions", str(e)) from e
except ForeignKeyViolationError as e:
    constraint_name = extract_constraint_name(e) or "unknown"
    raise RepoFKError(constraint_name, "core.completions", str(e)) from e
```
**Critical for cross-write CTE:** The tournament cross-write must extend this pattern with additional CTEs (`current_best`, `should_insert`) to conditionally insert only when the tournament time is strictly faster. It must also include `tournament_completion_id` in the INSERT column list.

---

**Exception handling pattern** (`completions_repository.py` lines 1665-1676):

Three-exception catch block with all constraint types:
```python
try:
    await _conn.execute(query, *args)
except UniqueViolationError as e:
    constraint_name = extract_constraint_name(e) or "unknown"
    raise UniqueConstraintViolationError(constraint_name, "core.completions", str(e)) from e
except ForeignKeyViolationError as e:
    constraint_name = extract_constraint_name(e) or "unknown"
    raise RepoFKError(constraint_name, "core.completions", str(e)) from e
except CheckViolationError as e:
    constraint_name = extract_constraint_name(e) or "unknown"
    raise CheckConstraintViolationError(constraint_name, "core.completions", str(e)) from e
```

---

**Paginated history with count pattern** (`store_repository.py` lines 447-485):
```python
async def fetch_quest_history(
    self,
    user_id: int,
    limit: int = 20,
    offset: int = 0,
    *,
    conn: Connection | None = None,
) -> tuple[int, list[dict]]:
    """Fetch completed quest history for a user."""
    _conn = self._get_connection(conn)
    total = await _conn.fetchval(
        """
        SELECT COUNT(*)
        FROM store.user_quest_progress
        WHERE user_id = $1 AND completed_at IS NOT NULL
        """,
        user_id,
    )
    rows = await _conn.fetch(
        """
        SELECT id AS progress_id,
               quest_id,
               quest_data,
               progress,
               completed_at,
               claimed_at,
               coins_rewarded,
               xp_rewarded,
               rotation_id
        FROM store.user_quest_progress
        WHERE user_id = $1 AND completed_at IS NOT NULL
        ORDER BY completed_at DESC
        LIMIT $2 OFFSET $3
        """,
        user_id,
        limit,
        offset,
    )
    return total or 0, [dict(row) for row in rows]
```

---

**Boolean existence check pattern** (`store_repository.py` lines 203-222):
```python
async def has_progress_rows(
    self,
    user_id: int,
    rotation_id: UUID,
    *,
    conn: Connection | None = None,
) -> bool:
    """Check if user has any progress rows for a rotation."""
    _conn = self._get_connection(conn)
    exists = await _conn.fetchval(
        """
        SELECT 1
        FROM store.user_quest_progress
        WHERE user_id = $1 AND rotation_id = $2
        LIMIT 1
        """,
        user_id,
        rotation_id,
    )
    return bool(exists)
```
**Apply to:** `check_active_cycle_for_category(id)` method.

---

**FK error handling in INSERT pattern** (`store_repository.py` lines 842-860):
```python
try:
    await _conn.execute(
        query,
        user_id,
        purchase_type,
        item_name,
        item_type,
        key_type,
        quantity,
        price_paid,
        rotation_id,
    )
except asyncpg.ForeignKeyViolationError as e:
    constraint = extract_constraint_name(e)
    raise ForeignKeyViolationError(
        constraint_name=constraint or "unknown",
        table="store.purchases",
        detail=str(e),
    ) from e
```
**Note:** `store_repository.py` imports `ForeignKeyViolationError` directly from `repository.exceptions` (not aliased) because it only catches `asyncpg.ForeignKeyViolationError` via the `asyncpg` module namespace. The `completions_repository.py` alias pattern is preferred since it catches via the unqualified name.

---

**Display name JOIN pattern** (`store_repository.py` line 690):
```python
coalesce(u.global_name, u.nickname, 'Unknown') AS username
```
Used in `JOIN core.users u ON u.id = ...` queries. Apply to leaderboard query.

---

**Difficulty matching pattern** (`community_repository.py` line 107, `store_repository.py` line 566):
```python
regexp_replace(m.difficulty, '\\s*[-+]\\s*$', '', '') AS base_difficulty
```
Strips `+`/`-` suffixes from `DifficultyAll` values to match against `DifficultyTop` values. Apply to `fetch_eligible_maps` and `fetch_least_recently_used_map`.

---

**JSONB `::jsonb` cast pattern** (`store_repository.py` lines 298-299, 343-344):
```python
VALUES ($1, $2, $3::jsonb, $4, $5)
```
Apply to all INSERT/UPDATE operations on `tournaments.categories` columns `placement_xp`, `streak_xp`, and `tournaments.pending_transitions.payload`.

---

**Provider function pattern** (`completions_repository.py` lines 1989-1991, `store_repository.py` lines 1064-1073):
```python
async def provide_completions_repository(state: State) -> CompletionsRepository:
    """Litestar DI provider for CompletionsRepository."""
    return CompletionsRepository(state.db_pool)
```

---

**Upsert (INSERT ... ON CONFLICT ... DO UPDATE) pattern** (`store_repository.py` lines 288-305):
```python
await _conn.execute(
    """
    INSERT INTO store.quest_rotation (
        rotation_id,
        user_id,
        quest_data,
        available_from,
        available_until
    )
    VALUES ($1, $2, $3::jsonb, $4, $5)
    ON CONFLICT DO NOTHING
    """,
    rotation_id,
    user_id,
    quest_data,
    window["available_from"],
    window["available_until"],
)
```
Apply to `upsert_streak()` -- use `ON CONFLICT (user_id) DO UPDATE SET ...` with RETURNING.

---

## Shared Patterns

### Connection Injection
**Source:** `apps/api/repository/base.py` (full file, lines 1-33)
**Apply to:** Every method in `TournamentRepository`
```python
def _get_connection(self, conn: Connection | None = None) -> Connection | Pool:
    return conn or self._pool
```

### Exception Handling
**Source:** `apps/api/repository/exceptions.py` (full file, lines 1-102)
**Apply to:** All INSERT/UPDATE/DELETE operations that could violate constraints

Key types:
- `UniqueConstraintViolationError(constraint_name, table, detail)` -- for UNIQUE violations
- `ForeignKeyViolationError(constraint_name, table, detail)` -- for FK violations (aliased as `RepoFKError`)
- `CheckConstraintViolationError(constraint_name, table, detail)` -- for CHECK violations
- `extract_constraint_name(e)` -- extracts constraint name from asyncpg exception via `getattr(error, "constraint_name", None)`

### Return Value Conventions
**Source:** All repository files
**Apply to:** All methods in `TournamentRepository`
- Single row: `dict(row) if row else {}` or `dict(row) if row else None`
- Multiple rows: `[dict(row) for row in rows]`
- Single scalar: `await _conn.fetchval(query, ...)` returns the value directly
- Boolean check: `return bool(await _conn.fetchval(...))`
- Count + rows: `return total or 0, [dict(row) for row in rows]`

### Import Aliasing for FK Exception
**Source:** `apps/api/repository/completions_repository.py` lines 17-19
**Apply to:** `tournaments_repository.py`
```python
from repository.exceptions import (
    ForeignKeyViolationError as RepoFKError,
)
```
This alias prevents name collision with `asyncpg.exceptions.ForeignKeyViolationError` when both are caught in the same `except` block.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| *(none)* | -- | -- | The single file has strong analogs for all patterns |

## Metadata

**Analog search scope:** `apps/api/repository/`
**Files scanned:** 21 repository files
**Analogs selected:** 3 (completions_repository.py, store_repository.py, base.py)
**Pattern extraction date:** 2026-05-29
