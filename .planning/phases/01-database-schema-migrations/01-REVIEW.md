---
phase: 01-database-schema-migrations
reviewed: 2026-05-29T19:33:06Z
depth: standard
files_reviewed: 2
files_reviewed_list:
  - apps/api/migrations/0020_tournaments.sql
  - apps/api/tests/integration/test_tournaments_schema.py
findings:
  critical: 2
  warning: 3
  info: 4
  total: 9
status: issues_found
---

# Phase 01: Code Review Report

**Reviewed:** 2026-05-29T19:33:06Z
**Depth:** standard
**Files Reviewed:** 2
**Status:** issues_found

## Summary

The `0020_tournaments.sql` migration and its accompanying integration tests introduce the tournament schema with 6 tables. The DDL is broadly correct and follows project conventions (text CHECK instead of ENUMs, `IF NOT EXISTS` guards, `GENERATED ALWAYS AS IDENTITY`, positional comments). However, two critical bugs are present: a UNIQUE constraint that provides almost no duplicate protection, and missing `updated_at` triggers on tables that declare the column. Three warnings flag a missing active-cycle uniqueness guard, an inconsistent FK delete action, and an incomplete index coverage test. Four info items cover a denormalized column risk, missing streak categorization, manual transaction management style, and a missing schema-level uniqueness test.

## Critical Issues

### CR-01: `tournaments.completions` UNIQUE Constraint Is Effectively Non-Functional

**File:** `apps/api/migrations/0020_tournaments.sql:98`

**Issue:** The unique constraint `UNIQUE (cycle_id, user_id, inserted_at)` includes `inserted_at`, which defaults to `now()`. Because `inserted_at` is a `timestamptz` with microsecond precision and is set at INSERT time, two submissions from the same user in the same cycle will have different `inserted_at` values and therefore always satisfy the constraint. This means a user can submit an unlimited number of times per cycle with no database-level enforcement preventing duplicates. The intent — one submission per user per cycle — is not enforced.

The same three-column pattern exists on `core.completions` (line 465 of `0001_init.sql`), but `core.completions` deliberately allows multiple submissions per `(map_id, user_id)` pair over time. Tournament cycles have a different business rule: each user competes in a single active cycle.

**Fix:**
```sql
-- Replace:
UNIQUE (cycle_id, user_id, inserted_at)

-- With:
UNIQUE (cycle_id, user_id)
```

If the design intent truly allows multiple submissions per cycle per user (e.g., re-submissions before verification), this constraint should be removed entirely and the business rule documented — but the current constraint gives a false sense of protection while enforcing nothing meaningful.

---

### CR-02: `updated_at` Columns Declared But Never Auto-Updated (Missing Triggers)

**File:** `apps/api/migrations/0020_tournaments.sql:21,44,125`

**Issue:** Three tables declare `updated_at timestamptz NOT NULL DEFAULT now()`:
- `tournaments.config` (line 21)
- `tournaments.categories` (line 44)
- `tournaments.streaks` (line 125)

The project-wide `set_updated_at()` trigger function was created in migration `0001_init.sql` and is attached via `CREATE TRIGGER ... EXECUTE FUNCTION set_updated_at()` for every other table with an `updated_at` column (core.users, core.maps, etc.). No trigger is created in `0020_tournaments.sql`. As a result, `updated_at` will hold the insertion timestamp permanently regardless of subsequent UPDATEs. Any application code reading `updated_at` to detect stale config or changed category XP settings will receive incorrect data.

**Fix:**
```sql
-- After each table creation, add a trigger.
-- For tournaments.config:
DROP TRIGGER IF EXISTS update_tournaments_config_updated_at ON tournaments.config;
CREATE TRIGGER update_tournaments_config_updated_at
    BEFORE UPDATE ON tournaments.config
    FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

-- For tournaments.categories:
DROP TRIGGER IF EXISTS update_tournaments_categories_updated_at ON tournaments.categories;
CREATE TRIGGER update_tournaments_categories_updated_at
    BEFORE UPDATE ON tournaments.categories
    FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

-- For tournaments.streaks:
DROP TRIGGER IF EXISTS update_tournaments_streaks_updated_at ON tournaments.streaks;
CREATE TRIGGER update_tournaments_streaks_updated_at
    BEFORE UPDATE ON tournaments.streaks
    FOR EACH ROW
EXECUTE FUNCTION set_updated_at();
```

## Warnings

### WR-01: No Uniqueness Constraint Preventing Multiple `active` or `pending` Cycles Per Category

**File:** `apps/api/migrations/0020_tournaments.sql:59-74`

**Issue:** The `tournaments.cycles` table has no constraint or partial unique index preventing more than one cycle in `active` or `pending` status for the same category. A bug or race condition in the scheduler could create two concurrent active cycles for the same category, corrupting leaderboards and XP grants. The `idx_cycles_category_status` composite index (line 74) is a query-performance index, not a uniqueness guard.

**Fix:**
```sql
-- Add partial unique index enforcing at most one non-completed cycle per category:
CREATE UNIQUE INDEX IF NOT EXISTS idx_cycles_one_active_per_category
    ON tournaments.cycles (category_id)
    WHERE status IN ('active', 'pending', 'finalizing');
```

This makes the scheduler constraint explicit in the schema rather than relying on application logic alone.

---

### WR-02: `tournaments.completions.map_id` Uses `ON DELETE CASCADE` Inconsistently With `cycles.map_id ON DELETE RESTRICT`

**File:** `apps/api/migrations/0020_tournaments.sql:91`

**Issue:** `tournaments.cycles.map_id` is declared `REFERENCES core.maps(id) ON DELETE RESTRICT`, which correctly prevents a map from being deleted while an active or historical cycle references it. However, `tournaments.completions.map_id` is declared `ON DELETE CASCADE`. If the `RESTRICT` on cycles were ever bypassed (e.g., cycles deleted first, then map deleted), tournament completion records would be silently erased via cascade.

The `map_id` column on `tournaments.completions` is also denormalized — the cycle already carries `map_id`, so `tournaments.completions.map_id` could diverge from `tournaments.cycles.map_id` for the same `cycle_id`. There is no `CHECK` or trigger enforcing their agreement.

**Fix:**
```sql
-- Option A: Remove the denormalized map_id column from tournaments.completions
-- and derive it via JOIN to tournaments.cycles at query time.

-- Option B: If keeping the column, change to RESTRICT to match cycle semantics:
map_id  int  NOT NULL REFERENCES core.maps(id) ON DELETE RESTRICT
```

---

### WR-03: `test_foreign_key_indexes_exist` Tests an Incomplete Subset of Indexes

**File:** `apps/api/tests/integration/test_tournaments_schema.py:177-198`

**Issue:** The test asserts `expected_indexes.issubset(index_names)` for 7 indexes, but the migration creates 13 indexes in the `tournaments` schema. The following indexes created by the migration are not verified by any test:
- `idx_cycles_status`
- `idx_cycles_started_at`
- `idx_cycles_category_status`
- `idx_tournament_completions_cycle_user`
- `idx_tournament_completions_ranking`
- `idx_pending_transitions_unpublished`

Because `issubset` is used, these could be accidentally dropped from a future migration without any test failure. The test name "All FK columns have explicit indexes" implies complete coverage but delivers partial coverage.

**Fix:**
```python
# Use an equality check to catch any missing or extra index regressions:
expected_indexes = {
    "idx_cycles_category_id",
    "idx_cycles_map_id",
    "idx_cycles_status",
    "idx_cycles_category_status",
    "idx_cycles_started_at",
    "idx_tournament_completions_cycle_id",
    "idx_tournament_completions_user_id",
    "idx_tournament_completions_map_id",
    "idx_tournament_completions_cycle_user",
    "idx_tournament_completions_ranking",
    "idx_streaks_user_id",
    "idx_pending_transitions_unpublished",
    "idx_pending_transitions_cycle_id",
}
assert expected_indexes.issubset(index_names)  # keep issubset if PK indexes appear
```

## Info

### IN-01: `tournaments.streaks` Has No `category_id` — Per-Category Streak XP Unenforceable

**File:** `apps/api/migrations/0020_tournaments.sql:118-133`

**Issue:** `tournaments.categories` defines per-category `streak_xp` JSONB (decision D-05), but `tournaments.streaks` has no `category_id` column. Streak tracking is global across all categories. A user participating only in one category will share a global streak counter with all other categories. This means:
- Per-category streak XP thresholds from `categories.streak_xp` cannot be applied correctly without knowing which category the streak is for.
- A user active only in "Expert" will have the same streak number as if they participated in "Easy", since the single row tracks all categories combined.

If the design truly intends global streaks regardless of category, the `streak_xp` JSONB on `categories` is misleading and the comment on `tournaments.streaks` ("Per-user weekly participation streak tracking") should say "global". If per-category streaks are intended in future phases, the schema needs a `category_id` column now.

**Suggestion:** Add a `category_id` FK column with `UNIQUE (user_id, category_id)`, or document explicitly in the migration comment that streaks are intentionally global and the per-category `streak_xp` is applied at query time by selecting the relevant category's XP config.

---

### IN-02: Manual Transaction/Savepoint Pattern in Tests Is Fragile

**File:** `apps/api/tests/integration/test_tournaments_schema.py:54-69,121-162`

**Issue:** Both constraint tests (`test_config_singleton_constraint`, `test_cycles_status_check_constraint`) manually manage transactions via `conn.transaction()`, `await tr.start()`, `SAVEPOINT`, and `ROLLBACK TO SAVEPOINT` rather than using asyncpg's native nested transaction context manager. This multi-layered approach is error-prone:

1. If `await conn.execute("SAVEPOINT test_singleton")` raises unexpectedly, the `with pytest.raises(...)` block is never entered and the outer `finally: await tr.rollback()` is the only safety net.
2. `ROLLBACK TO SAVEPOINT` does not release the savepoint, so the savepoint remains active until the outer `tr.rollback()`. This is technically fine but adds unnecessary state.
3. The pattern differs from how other tests in the codebase use `async with conn.transaction():` for nested rollback isolation.

**Suggestion:** Use asyncpg's nested transaction context manager:
```python
async with asyncpg_pool.acquire() as conn:
    async with conn.transaction():
        # outer savepoint / rollback happens via context manager
        with pytest.raises(asyncpg.CheckViolationError):
            async with conn.transaction():  # nested = savepoint in asyncpg
                await conn.execute(
                    "INSERT INTO tournaments.config (id, blacklist_weeks) "
                    "OVERRIDING SYSTEM VALUE VALUES (2, 4)"
                )
        # After nested context exits with error, the savepoint is rolled back;
        # the outer transaction is still open and will be rolled back by the
        # context manager on exit.
```

---

### IN-03: No Test for the Uniqueness Gap in `cycles` (One Active Cycle Per Category)

**File:** `apps/api/tests/integration/test_tournaments_schema.py`

**Issue:** There is no test asserting that inserting two cycles with `status = 'active'` for the same `category_id` is rejected. Because no such constraint exists in the migration (see WR-01), this is a schema gap rather than a missing test — but the gap makes the test suite silently allow a critical invariant violation.

**Suggestion:** Once WR-01 is addressed and a partial unique index is added, add a test:
```python
async def test_only_one_active_cycle_per_category(self, asyncpg_pool):
    """Only one active/pending cycle per category is allowed."""
    # (setup user, map, category as in test_cycles_status_check_constraint)
    # Insert first active cycle — should succeed
    # Insert second active cycle for same category — should raise UniqueViolationError
```

---

### IN-04: `core.completions.tournament_completion_id` FK Uses `ON DELETE SET NULL` — Orphan Risk

**File:** `apps/api/migrations/0020_tournaments.sql:170-172`

**Issue:** When a `tournaments.completions` row is deleted, `core.completions.tournament_completion_id` is set to NULL via `ON DELETE SET NULL`. This silently severs the link between the canonical completion record and its tournament origin. If a tournament completion is deleted (e.g., disqualification), the `core.completions` row survives but loses its provenance. Downstream queries checking `tournament_completion_id IS NOT NULL` to identify tournament submissions will silently exclude the disqualified record.

This may be acceptable by design (a disqualified tournament completion stays as a core completion but is no longer flagged as tournament-sourced). If so, it should be documented. If deletion of a tournament completion should also remove or flag the linked `core.completions` row, the action should be `ON DELETE RESTRICT` or a trigger.

**Suggestion:** Add a migration comment explaining the intended behavior when a `tournaments.completions` row is deleted.

---

_Reviewed: 2026-05-29T19:33:06Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
