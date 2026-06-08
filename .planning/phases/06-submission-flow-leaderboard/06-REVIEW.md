---
phase: 06-submission-flow-leaderboard
reviewed: 2026-05-30T01:52:39Z
depth: standard
files_reviewed: 7
files_reviewed_list:
  - apps/api/repository/tournaments_repository.py
  - apps/api/routes/v3/tournaments.py
  - apps/api/services/exceptions/tournaments.py
  - apps/api/services/tournament_service.py
  - apps/api/tests/integration/test_tournaments_integration.py
  - apps/api/tests/services/test_tournament_service.py
  - libs/sdk/src/genjishimada_sdk/tournaments.py
findings:
  critical: 2
  warning: 6
  info: 4
  total: 12
status: issues_found
---

# Phase 6: Code Review Report

**Reviewed:** 2026-05-30T01:52:39Z
**Depth:** standard
**Files Reviewed:** 7
**Status:** issues_found

## Summary

This phase implements the tournament submission flow, leaderboard, and supporting cycle/category management endpoints. The overall architecture is sound and follows project conventions closely. However, two critical issues were found: SQL injection vulnerabilities in the repository's dynamic query builders (field names are not whitelisted before being interpolated into SQL), and a data integrity flaw where `cross_write_to_core` can silently skip the cross-domain write if `map_flags` returns no rows (e.g. map deleted between cycle creation and submission). Six warnings cover robustness gaps: a crash-on-None in `select_map`/`reroll_map`/`choose_map`, an unvalidated status filter that returns silent empty results for invalid values, a missing transaction in `choose_map` that can leave the system in a state with no pending cycle, incorrect LRU fallback logic that picks the wrong map when a map appears in multiple cycles, and an undocumented behavior around the tournament submission vs. core completion cross-write.

---

## Critical Issues

### CR-01: SQL Injection via Unwhitelisted Column Names in `update_config` and `update_category`

**File:** `apps/api/repository/tournaments_repository.py:72-78`, `215-225`
**Issue:** Both `update_config` and `update_category` build dynamic `UPDATE` queries by directly interpolating dictionary keys as column names into the SQL string:

```python
# update_config, line 75:
set_clauses.append(f"{field} = ${idx}")

# update_category, line 217-221:
set_clauses.append(f"{field} = ${idx}::jsonb")
# ...
set_clauses.append(f"{field} = ${idx}")
```

The `field` variable comes from the `updates` dict passed by the service. Although the current service code only ever assigns hard-coded string literals as keys (`"blacklist_weeks"`, `"name"`, `"difficulties"`, etc.), the repository method accepts an arbitrary `dict` with no column whitelist. Any future caller or test that passes an attacker-influenced key — even indirectly — would inject arbitrary SQL into the SET clause. The values are parameterised correctly (`$N`), but column names cannot be parameterised in asyncpg, so the names must be validated explicitly.

**Fix:** Add a frozenset whitelist in each method and validate before building the clause:

```python
_ALLOWED_CONFIG_FIELDS = frozenset({"blacklist_weeks"})
_ALLOWED_CATEGORY_FIELDS = frozenset({
    "name", "difficulties", "cycle_frequency", "participation_xp",
    "placement_xp", "streak_xp", "champion_role_id", "is_active",
})

async def update_config(self, updates: dict, *, conn: Connection | None = None) -> None:
    if not updates:
        return
    unknown = set(updates) - _ALLOWED_CONFIG_FIELDS
    if unknown:
        raise ValueError(f"Unknown config fields: {unknown}")
    # ... rest unchanged
```

Apply the same guard at the top of `update_category`.

---

### CR-02: `cross_write_to_core` Silently Skips the Cross-Write When `map_flags` Returns No Rows

**File:** `apps/api/repository/tournaments_repository.py:843-868`
**Issue:** The `computed` CTE depends on `map_flags`, which queries `core.maps WHERE m.id = $3`. If the map row is missing (e.g. deleted between cycle creation and submission, which should be impossible via FK but can happen in test environments or via direct DB manipulation), `map_flags` returns zero rows, `computed` returns zero rows, and the `CROSS JOIN computed co` in the final INSERT produces zero rows. The INSERT is silently skipped and `fetchval` returns `None`.

The service at line 519-527 of `tournament_service.py` does not check this return value at all:

```python
await self._tournament_repo.cross_write_to_core(
    tournament_completion_id=row["id"],
    ...
)
```

The result is: the tournament completion is recorded in `tournaments.completions`, the API returns HTTP 201, but nothing is written to `core.completions`. This silently breaks the "latest = fastest" invariant described in the project constraints.

**Fix:** Check the return value in the service and at minimum log a warning:

```python
core_id = await self._tournament_repo.cross_write_to_core(
    tournament_completion_id=row["id"],
    user_id=data.user_id,
    map_id=cycle["map_id"],
    time=data.time,
    screenshot=data.screenshot,
    video=data.video,
    conn=conn,  # type: ignore[arg-type]
)
if core_id is None:
    log.warning(
        "[!] cross_write_to_core returned None for tournament completion %s "
        "(map_id=%s, user=%s, time=%s) — possible data integrity violation",
        row["id"], cycle["map_id"], data.user_id, data.time,
    )
```

Additionally, restructure `computed` to use a scalar subquery so it always produces exactly one row regardless of whether `core.maps` has the row:

```sql
computed AS (
    SELECT (
        COALESCE(
            (SELECT (m.playtesting = 'In Progress') OR NOT m.official
             FROM core.maps m WHERE m.id = $3),
            FALSE
        )
        OR ($6::text IS NULL OR $6::text = '')
    ) AS completion_flag
)
```

---

## Warnings

### WR-01: `select_map`, `reroll_map`, and `choose_map` Will Raise Unhandled Exception if Re-fetch Returns `None`

**File:** `apps/api/services/tournament_service.py:298-303`, `395-400`, `461-466`
**Issue:** After creating a cycle, each of these three methods calls `fetch_pending_cycle` a second time to get the joined row with map details, then passes the result directly to `msgspec.convert`. The return type is `dict | None`. If the row is missing (a race condition, a concurrent delete, or a bug in the DB), `msgspec.convert(None, TournamentNextCycleResponse)` will raise a `ValidationError` or `TypeError` from msgspec rather than a domain exception, producing an unhandled 500 response.

**Fix:** Assert the re-fetch result is not None in all three locations:

```python
result = await self._tournament_repo.fetch_pending_cycle(category_id, conn=conn)
if result is None:
    raise RuntimeError(
        f"Pending cycle missing immediately after creation for category {category_id}"
    )
return msgspec.convert(result, TournamentNextCycleResponse)
```

---

### WR-02: `status` Query Parameter in `list_cycles` Is Not Validated Against Allowed Values

**File:** `apps/api/routes/v3/tournaments.py:494`
**Issue:** The `status` query parameter is typed as `str | None` with no constraint. An invalid value such as `?status=garbage` passes through the controller into the service and then into the repository WHERE clause as a parameterised value. SQL injection is not possible because asyncpg parameterises the value, but the invalid status silently returns an empty result set with HTTP 200 — giving the caller no indication that their filter was invalid. The valid values are defined as `CycleStatus = Literal["pending", "active", "finalizing", "completed"]` in the SDK.

**Fix:** Change the parameter type to use the SDK type alias:

```python
from genjishimada_sdk.tournaments import CycleStatus

status: Annotated[CycleStatus | None, Parameter(description="Filter by cycle status", required=False)] = None,
```

Litestar will reject invalid values at deserialization with a 400 response.

---

### WR-03: `choose_map` Uses No Transaction — Partial Failure Can Delete a Pending Cycle Permanently

**File:** `apps/api/services/tournament_service.py:423-466`
**Issue:** `choose_map` acquires a connection with `async with self._pool.acquire() as conn` but does not open a transaction (`conn.transaction()`). The sequence is: delete existing pending cycle → create new cycle → re-fetch. If `create_cycle` fails after `delete_cycle` succeeds (e.g. a FK violation because the map was just archived), the pending cycle is permanently gone and the category has no next cycle. The category is now in an inconsistent state without any error visible to the caller beyond the 500.

The same issue applies to `reroll_map` (line 344), which also acquires a connection without a transaction.

**Fix:** Wrap both operations in a transaction:

```python
async with self._pool.acquire() as conn, conn.transaction():
    ...
```

`submit_completion` already does this correctly at line 491. Apply the same pattern to `choose_map` and `reroll_map`.

---

### WR-04: `fetch_least_recently_used_map` Incorrect Due to Multi-Row JOIN — Returns Wrong Map

**File:** `apps/api/repository/tournaments_repository.py:593-605`
**Issue:** The LRU fallback query uses a plain `LEFT JOIN tournaments.cycles cy ON cy.map_id = m.id`. When a map has been used in multiple cycles, this JOIN produces multiple rows for that map. The `ORDER BY cy.started_at ASC NULLS FIRST` then sorts by the *oldest* cycle of each map rather than the *most recent* use. A map last used 2 weeks ago (with an older first use 10 weeks ago) will sort by the 10-week row and appear before a map used only 5 weeks ago — reversing the intended LRU order.

**Fix:** Use an aggregated subquery to find each map's most-recent use:

```sql
SELECT m.id, m.code, m.map_name, m.difficulty
FROM core.maps m
LEFT JOIN (
    SELECT map_id, MAX(started_at) AS last_used
    FROM tournaments.cycles
    GROUP BY map_id
) recent ON recent.map_id = m.id
WHERE m.official = TRUE
  AND m.archived = FALSE
  AND m.code IS NOT NULL
  AND regexp_replace(m.difficulty, '\s*[-+]\s*$', '', '') = ANY($1)
ORDER BY recent.last_used ASC NULLS FIRST
LIMIT 1
```

---

### WR-05: `submit_completion` Service-Layer Time Check Does Not Account for Cross-Domain Best

**File:** `apps/api/services/tournament_service.py:501-507`
**Issue:** The service checks the user's existing `tournaments.completions` for this cycle before deciding whether to reject a submission as "slower". But `cross_write_to_core` independently checks `core.completions` before writing. The result is a behavioral inconsistency:

- A user with a `core.completions` best of 20s (from a non-tournament run) submits 30s to the tournament. The service allows the tournament completion (no prior tournament entry for this cycle). `cross_write_to_core` skips the core insert (30s is not faster than 20s). HTTP 201 is returned.
- The user's tournament completion is stored at 30s but their core record stays at 20s. The tournament leaderboard shows 30s as their tournament best.

This is defensible as intentional design (tournament participation is separate from global best), but the service docstring and controller docstring describe this as tracking "the user's current best", which is misleading.

**Fix:** Update the docstrings to explicitly state that the time-faster check is scoped to `tournaments.completions` for the current cycle, and that the cross-write to `core.completions` is a separate operation governed by its own comparison against `core.completions`. No code change needed if this is intentional.

---

### WR-06: `update_category` Raises `CategoryLockedError` with Wrong Keyword Argument Name

**File:** `apps/api/services/tournament_service.py:193`
**Issue:** `CategoryLockedError.__init__` signature is `(self, category_id: int, cycle_id: int)` — two positional parameters (line 17 of `exceptions/tournaments.py`). But the call site at line 193 passes `cycle_id` as a keyword argument:

```python
raise CategoryLockedError(category_id, cycle_id=cycle_id)
```

This works at runtime because `cycle_id` is the second positional parameter and can also be passed as keyword. However, in `delete_category` at line 230, the same call pattern is used. The `CategoryLockedError.__init__` does not declare `cycle_id` as keyword-only, so this is technically fine, but it is inconsistent — the first argument is positional and the second is named. If someone later adds `*` to make parameters keyword-only, this breaks silently. The call should be consistent:

```python
raise CategoryLockedError(category_id=category_id, cycle_id=cycle_id)
```

---

## Info

### IN-01: Four Exception Classes Defined but Never Used

**File:** `apps/api/services/exceptions/tournaments.py:39-43`, `64-72`, `75-84`, `97-101`
**Issue:** `CycleAlreadyActiveError`, `DuplicateTournamentCompletionError`, `MapMismatchError`, and `NoCycleActiveError` are defined and exported but not imported anywhere in the service or controller. These are dead code in the current implementation.

**Fix:** Remove them until the features that use them are implemented, or add a comment indicating which future phase will introduce them.

---

### IN-02: `TournamentCompletionCreateRequest.user_id` Is Caller-Supplied — Authorization Gap Not Documented

**File:** `libs/sdk/src/genjishimada_sdk/tournaments.py:331-344`
**Issue:** The `user_id` is a client-supplied field in the POST body rather than being derived from the authenticated session. Any caller with `tournaments:write` scope can submit completions on behalf of arbitrary user IDs. This is consistent with the bot-as-proxy pattern, but it is not documented at the endpoint level.

**Fix:** Add a note in the route docstring: "Callers are trusted to supply the correct `user_id`. This endpoint is intended for internal bot use only and requires `tournaments:write` scope. Do not expose directly to end-user clients."

---

### IN-03: `TournamentCycleResultsResponse` Is Defined and Exported but Never Referenced

**File:** `libs/sdk/src/genjishimada_sdk/tournaments.py:302-323`
**Issue:** `TournamentCycleResultsResponse` is included in `__all__` and has a `standings: list[TournamentLeaderboardEntryResponse]` field, but it is not used in any route, service, or test. It was likely designed for a future "get cycle results with standings" endpoint.

**Fix:** Keep it with a comment if planned soon; otherwise remove it to avoid dead exports.

---

### IN-04: `TournamentNextCycleResponse` Is Missing `started_at` and `ended_at` Fields

**File:** `libs/sdk/src/genjishimada_sdk/tournaments.py:199-221`
**Issue:** `TournamentNextCycleResponse` omits the `started_at` and `ended_at` fields that `fetch_pending_cycle` returns (they are selected explicitly at line 626 in the repository). `msgspec.convert` silently drops unmapped columns. For a pending cycle these will always be `None`, but the struct is asymmetric with `TournamentCycleResponse`, and the omission is not documented.

**Fix:** Either add the fields (`started_at: dt.datetime | None`, `ended_at: dt.datetime | None`) to make the struct consistent, or add a comment explaining the intentional omission.

---

_Reviewed: 2026-05-30T01:52:39Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
