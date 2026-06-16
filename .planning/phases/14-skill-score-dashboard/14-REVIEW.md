---
phase: 14-skill-score-dashboard
reviewed: 2026-06-16T00:00:00Z
depth: standard
files_reviewed: 11
files_reviewed_list:
  - apps/api/migrations/0031_skill_history.sql
  - libs/sdk/src/genjishimada_sdk/skill.py
  - apps/api/events/schemas.py
  - apps/api/events/skill.py
  - apps/api/repository/skill_repository.py
  - apps/api/repository/completions_repository.py
  - apps/api/services/skill_service.py
  - apps/api/services/completions_service.py
  - apps/api/routes/v3/skill.py
  - apps/api/tests/services/test_skill_service.py
  - apps/api/tests/integration/test_skill_dashboard.py
findings:
  critical: 0
  warning: 3
  info: 3
  total: 6
status: issues_found
---

# Phase 14: Code Review Report

**Reviewed:** 2026-06-16
**Depth:** standard
**Files Reviewed:** 11
**Status:** issues_found

## Summary

This phase adds a forward-only skill-score history and per-change attribution layer (`skill.score_history`, `skill.score_change`) riding the Phase 13 `_do_recompute` routine, plus three new GET endpoints (`/history`, `/changes`, `/changes/{change_id}`). The implementation is structurally sound. No blockers were found.

Specific items reviewed per the prompt:

- **SQL injection / parameterization:** All new SQL uses `$N` positional params. The `window` literal is mapped to a `timedelta` dict at service layer and never interpolated. The `update_weights` SET clause is built exclusively from the `_WEIGHT_COLUMNS` allow-list with values bound positionally.
- **IDOR on drill-down:** `fetch_change` correctly scopes `WHERE change_id = $1 AND user_id = $2`. The route returns 404 on `None` without confirming existence to non-owners.
- **Conservation invariant:** `sum(main_causes.impact) + other_factors == delta` holds at both write-time (by construction: `Σ impact = Σ(new_c - prev_c) = new_score - prev_score = delta`) and read-time (top-N cut preserves the identity, residual tail is summed).
- **`_RecomputeGuard` concurrency:** The asyncio single-threaded execution model ensures `lock.locked()` and `async with _GUARD.lock` are safe — `asyncio.Lock.acquire()` sets `_locked=True` atomically before any yield when the lock is free. Descriptor drain inside the `while` loop correctly coalesces burst arrivals.
- **TRUNCATE ordering:** `fetch_all_snapshots(conn=conn)` is called before `replace_snapshot` inside the outer transaction — prev snapshot is read before TRUNCATE. Correct.
- **Phase 13 scorer math:** `_map_score`, `_player_score`, `_player_breakdown` are unmodified from Phase 13.
- **Litestar / project conventions:** Three-layer architecture respected. `log` + `%s` format used. Google docstrings present. Type annotations complete. No raw string formatting in SQL.

Three warnings and three info items found below.

## Warnings

### WR-01: Docstring in `update_tiers` Route Claims Wrong Percentile Count

**File:** `apps/api/routes/v3/skill.py:234`
**Issue:** The `Raises:` block in the `update_tiers` docstring reads "if the percentiles are not exactly **6** values strictly within (0, 1) and strictly increasing." The actual enforcement (`_TIER_PERCENTILE_COUNT = 7` in `skill_service.py`) requires exactly **7** values. The mismatch will appear verbatim in the generated OpenAPI/Scalar docs and mislead API consumers.
**Fix:** Change "6" to "7" in the docstring:
```python
        Raises:
            HTTPException: 400 if the percentiles are not exactly 7 values strictly within
                (0, 1) and strictly increasing.
```

### WR-02: `replace_snapshot` Opens a Redundant Nested SAVEPOINT When Called From a Transaction

**File:** `apps/api/repository/skill_repository.py:201-231`
**Issue:** When called from `_do_recompute` (which already holds an outer `async with conn.transaction()`), `replace_snapshot` receives a `PoolConnectionProxy` as `conn`. The `isinstance(_conn, Pool)` check is `False`, so `_do_replace(_conn)` is called. Inside `_do_replace`, `async with c.transaction()` opens a **SAVEPOINT** inside the outer transaction. The TRUNCATE and bulk-INSERT therefore execute inside an unnecessary savepoint. On any exception inside `_do_replace`, asyncpg rolls back the savepoint but the exception still propagates outward, causing the outer transaction to also roll back — so atomicity is preserved — but the savepoint is dead overhead and the code is misleading: a reader of `_do_replace` cannot tell whether they are getting a real transaction or a savepoint, and the "Runs inside a single transaction" contract in the docstring is now ambiguous.

In future maintenance, a developer who wants to add explicit error handling inside `_do_replace` that catches and re-raises a transformed exception could unintentionally suppress the propagation, breaking outer-transaction rollback.

**Fix:** Skip the inner `c.transaction()` call when a connection is passed in (i.e., when the outer transaction already exists). The simplest approach: check whether the caller supplied a connection and, if so, execute the TRUNCATE + INSERT directly without wrapping in a new transaction context:
```python
async def _do_replace(c: Connection | PoolConnectionProxy) -> None:
    await c.execute("TRUNCATE skill.snapshot")
    if not rows:
        return
    await c.executemany(...)  # same as before, no wrapping transaction

_conn = self._get_connection(conn)
if isinstance(_conn, Pool):
    async with _conn.acquire() as acquired:
        async with acquired.transaction():
            await _do_replace(acquired)
else:
    # Caller already holds a transaction; execute directly.
    await _do_replace(_conn)
```

### WR-03: Integration Tests Lack `_GUARD` Reset — Module-Scope State Leaks Between Tests

**File:** `apps/api/tests/integration/test_skill_dashboard.py`
**Issue:** `test_skill_service.py` has an `autouse` `_reset_guard` fixture that clears `_GUARD._lock`, `_GUARD.rerun_requested`, and `_GUARD.pending` before and after each test. `test_skill_dashboard.py` has no equivalent fixture. Within a single pytest-xdist worker, tests run sequentially; if any integration test terminates abnormally mid-`recompute_all` (leaving `_GUARD.pending` non-empty or `_GUARD.rerun_requested = True`), the next test in the same worker inherits the dirty guard state and the cause-policy resolution for that test's recompute will be wrong.

This is a latent reliability issue: in the happy path every successful `recompute_all` drains `pending` and clears `rerun_requested` before returning, so the guard is clean. An exception during `_do_recompute` (e.g., a transient DB error in CI) leaves the guard dirty.

**Fix:** Add an autouse `_reset_guard` fixture — mirroring `test_skill_service.py` — at the module level or in the integration `conftest.py`:
```python
import pytest
from services import skill_service as svc

@pytest.fixture(autouse=True)
def _reset_guard():
    svc._GUARD._lock = None
    svc._GUARD.rerun_requested = False
    svc._GUARD.pending.clear()
    yield
    svc._GUARD._lock = None
    svc._GUARD.rerun_requested = False
    svc._GUARD.pending.clear()
```

## Info

### IN-01: `SkillChangeCause.reason` Carries Recompute-Level Reason, Not Per-Map Reason

**File:** `apps/api/services/skill_service.py:571`
**Issue:** In `get_user_change_detail`, every entry in `main_causes` receives the same `reason` from the parent change row (`row["reason"] or row["cause_category"]`). All five top-N entries will display "verified completion" or "global recalculation" regardless of which map they represent. The SDK docstring for `SkillChangeCause.reason` says "Human-readable reason for this **map's** impact," implying a per-map explanation — but the current value is the trigger-level label.

This is a design decision (per-map reasons require deeper instrumentation that does not exist), not a correctness bug. No data is wrong; the label is just coarser than the field name implies. Flag for documentation or a future iteration if the UX team needs per-map attribution language.

**Fix (documentation):** Clarify the SDK field docstring to reflect the actual semantics:
```python
reason: str  # Recompute-level trigger reason shared by all causes in this change.
```

### IN-02: Timing-Dependent 10 ms Sleep in History-Capture Test

**File:** `apps/api/tests/integration/test_skill_dashboard.py:200`
**Issue:** `test_two_recomputes_yield_two_distinct_captured_at` calls `await asyncio.sleep(0.01)` between two `_recompute` calls to ensure distinct `captured_at` timestamps (the composite PK `(user_id, captured_at)` requires them to differ). On a heavily loaded CI runner where `datetime.now(timezone.utc)` might return the same microsecond for both recomputes, this sleep is the only guard. 10 ms is very conservative in practice but is still a timing dependency.

**Fix:** Either assert `len(set(captured)) == len(captured)` with a clearer error message, or insert a synthetic delay via the existing `_insert_history` helper and skip the second `_recompute` for the ordering assertion. Alternatively, capture `datetime.now()` before and after each `_recompute` call to confirm the assertions are timestamp-based and not wall-clock-dependent.

### IN-03: `_emit_skill_recompute` for `flag`/`unflag` Performs an Extra DB Round-Trip Post-Commit

**File:** `apps/api/services/completions_service.py` (Phase-14 additions at flag/unflag sites)
**Issue:** For `flag` and `unflag`, `fetch_completion_owner_by_message` is called after the flag/unflag transaction commits. This is a single additional `SELECT user_id FROM core.completions WHERE …` query per flag/unflag operation — one extra round-trip, not a correctness problem. On extremely high flag/unflag throughput this would add latency, but for a moderation workflow this is negligible. Mentioned for completeness.

If the `owner_id` lookup returns `None` (completion deleted between the commit and the fetch), the code gracefully falls back to `SYSTEM` cause attribution. This is the documented and correct behavior.

**Fix:** No change required. If latency ever becomes a concern, the `user_id` could be captured before the flag/unflag transaction completes and threaded forward. Not recommended without a measured need.

---

_Reviewed: 2026-06-16_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
