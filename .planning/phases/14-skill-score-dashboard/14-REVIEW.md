---
phase: 14-skill-score-dashboard
reviewed: 2026-06-16T00:00:00Z
depth: standard
files_reviewed: 11
files_reviewed_list:
  - apps/api/events/schemas.py
  - apps/api/events/skill.py
  - apps/api/migrations/0031_skill_history.sql
  - apps/api/repository/completions_repository.py
  - apps/api/repository/skill_repository.py
  - apps/api/routes/v3/skill.py
  - apps/api/services/completions_service.py
  - apps/api/services/skill_service.py
  - apps/api/tests/integration/test_skill_dashboard.py
  - apps/api/tests/services/test_skill_service.py
  - libs/sdk/src/genjishimada_sdk/skill.py
findings:
  critical: 1
  warning: 5
  info: 4
  total: 10
status: issues_found
---

# Phase 14: Code Review Report

**Reviewed:** 2026-06-16T00:00:00Z
**Depth:** standard
**Files Reviewed:** 11
**Status:** issues_found

## Summary

Reviewed the skill-score dashboard phase: three new GET dashboard routes (history / changes / change-detail), the `PATCH /skill/tiers` percentile update, the forward-only capture tables (migration 0031), the per-change diff/cause capture wired into the single `_do_recompute` routine, and the in-process recompute event plumbing through `completions_service`.

The SQL is consistently parameterized (no injection found — the dynamic `update_weights` SET clause is built from a hard-coded allow-list, and every read binds `since`/`limit`/`offset`/`user_id` positionally). The IDOR mitigation on the change drill-down (ownership predicate in SQL → 404) is correct. Scope gating on the PATCH routes is present.

The most serious issue is a **conservation-breaking correctness bug in `_build_diff`**: it keys the per-map impact diff on the non-unique display `map_name`, so any player whose breakdown contains two maps with the same display name silently loses contributions and breaks the documented `Σ impact == delta` invariant. The integration test masks this by deliberately using a single map (and even notes the maps all share the name "Hanamura"). Several warnings cover stale-weight semantics on `PATCH /config`, an over-broad exception swallow with no Sentry capture in the recompute listener, and fragility when the weight/tier config row is missing.

## Critical Issues

### CR-01: `_build_diff` keys on non-unique `map_name`, silently dropping contributions and breaking the `Σ impact == delta` conservation invariant

**File:** `apps/api/services/skill_service.py:247-254` (producer: `_player_breakdown:216`)
**Issue:** `_build_diff` collapses both breakdowns into dicts keyed by `map_name`:

```python
prev_by_map = {row["map_name"]: float(row.get("contribution") or 0.0) for row in prev_breakdown}
new_by_map = {row["map_name"]: float(row.get("contribution") or 0.0) for row in new_breakdown}
```

`map_name` is a **display string**, not a stable id — `_player_breakdown` sets it to `r.get("map_name") or r.get("code") or f"map {r.get('map_id')}"`. Two genuinely different maps can share a display name (the integration `seed.make_map` factory hard-codes `map_name='Hanamura'` for *every* map, and real data has duplicate map names). When that happens, the dict comprehension keeps only the **last** row's contribution for that name and discards the others.

Consequences:
- `Σ new_by_map.values()` no longer equals the player's `skill_score` (which is `Σ contribution`), so the per-row diff written to `skill.score_change.diff` no longer conserves: `Σ impact != delta`.
- The change drill-down (`GET /changes/{id}`) then violates its own documented contract `sum(main_causes.impact) + other_factors == delta within 1e-6` (SDK `SkillChangeDetailResponse` docstring, route description, D-06/D-07), because `other_factors` is derived from the collapsed map list while `delta` comes from the (correct) scalar scores.
- The loss is silent and forward-only — a wrong impact array is persisted into `skill.score_change` and history is not re-cuttable.

The integration test `test_conservation_from_real_recompute` does NOT catch this — it deliberately uses a *single* map and comments that "multiple maps would collapse." That collapse is exactly this bug, not an unrelated edge.

**Fix:** Key the diff on a stable identifier (carry `map_id`/`code` through the breakdown input into `_build_diff`, join on it, keep `map_name` for display only):

```python
prev_by_key = {row["map_id"]: row for row in prev_breakdown}
new_by_key = {row["map_id"]: row for row in new_breakdown}
maps = []
for key in {*prev_by_key, *new_by_key}:
    p, n = prev_by_key.get(key), new_by_key.get(key)
    prev_c = float((p or {}).get("contribution") or 0.0)
    new_c = float((n or {}).get("contribution") or 0.0)
    maps.append({"map": (n or p)["map_name"], "prev": prev_c, "new": new_c, "impact": new_c - prev_c})
```

Add a regression test with two distinct maps sharing a display name and assert conservation still holds. Note `SkillBreakdownRow` has no `map_id` field today, so the diff input must carry the id even if the stored breakdown JSONB does not.

## Warnings

### WR-01: `PATCH /skill/config` claims scores update "right away" but the awaited recompute can no-op when one is already in flight

**File:** `apps/api/routes/v3/skill.py:258-293`, `apps/api/services/skill_service.py:297-311`
**Issue:** The route awaits `recompute_all(...)` after persisting weights and the endpoint description promises scores "reflect the new weights right away." But `recompute_all` returns *immediately without awaiting any rebuild* whenever `_GUARD.lock.locked()` — it only appends its descriptor and sets `rerun_requested`, then returns. In that case the route responds 200 with the new `weights` body while the rebuild that applies them has not yet run (it runs later as a coalesced rerun under whichever task holds the lock). A client reading `GET /skill/users/{id}` right after the 200 may still see old scores. The new weights are eventually applied (the rerun calls `fetch_weights`), but the synchronous "right away" promise is not honored under contention.

**Fix:** Soften the endpoint/docstring wording to "schedules a recompute," or, if synchronous freshness is required, have the PATCH path await actual completion of the rerun that drained its descriptor.

### WR-02: Recompute listener swallows all exceptions with no Sentry capture

**File:** `apps/api/events/skill.py:46-51`
**Issue:** The listener catches `Exception` and only `log.exception(...)`. Elsewhere the codebase pairs broad catches with `sentry_sdk.capture_exception(e)` (e.g. `completions_service.attempt_auto_verify_async`). A persistently failing recompute (bad/missing weight row, schema drift) is invisible to error tracking and leaves the snapshot stale until the nightly backstop, with no monitoring signal. The "log and continue" intent is fine, but it must still report.

**Fix:** Add `sentry_sdk.capture_exception(...)` alongside `log.exception(...)`.

### WR-03: `_do_recompute` / read paths raise a raw msgspec ValidationError 500 when `skill.weight_config` (or `tier_config`) row is missing

**File:** `apps/api/services/skill_service.py:348`, `apps/api/repository/skill_repository.py:329-347`, `445-458`
**Issue:** `fetch_weights()` returns `{}` when no config row exists, and `msgspec.convert({}, Weights)` then raises because every `Weights` field is required with no default. Migration 0027 seeds the row, but a partial/failed migration, a manual `TRUNCATE`, or an environment that skipped 0027 turns *every* recompute into a hard failure (caught only by WR-02's broad handler on the event path; surfaced as a 500 on `update_config`). The same fragility hits `get_weights()` (`GET /skill/config` → 500) and `fetch_tier_config()` (`{}` → `SkillTiersResponse` requires `computed_at` → raises).

**Fix:** Raise a clear domain error ("skill weight/tier config not seeded") at the repository boundary or degrade with a logged fallback — fail loudly with a descriptive message rather than an opaque ValidationError 500.

### WR-04: Cause attribution silently demotes a real PLAYER_ACTION trigger to SYSTEM under any concurrent recompute

**File:** `apps/api/services/skill_service.py:297-331`
**Issue:** A clean single-actor verify is attributed PLAYER_ACTION only when exactly one descriptor is drained. Since every coalesced caller appends to the shared module-scope `_GUARD.pending` and the holder drains *all* pending descriptors per loop iteration, two near-simultaneous verifies (or a verify overlapping the nightly/PATCH SYSTEM trigger) collapse to `(SYSTEM, None)` — the actor loses PLAYER_ACTION attribution. This is documented as D-09 behavior, but it means per-user actor/bystander labelling is racy and will frequently degrade to SYSTEM under normal production bursts. The tests only exercise serial, manually-driven recomputes, so they never observe the demotion.

**Fix:** If accurate attribution matters, attribute per-descriptor (track the actor set across drained PLAYER_ACTION descriptors and split actor vs bystander against it) rather than collapsing any multi-descriptor batch to SYSTEM. Otherwise document the demotion as an explicit known limitation in the route/SDK so consumers do not treat PLAYER_ACTION as reliable.

### WR-05: `get_user_history` percent_change is forced to 0.0 when the first in-window point is 0, masking real growth

**File:** `apps/api/services/skill_service.py:503`
**Issue:** `percent_change = (point_change / first * 100.0) if first != 0 else 0.0`. A player whose earliest in-window score is exactly 0 (new player who later climbs) reports `percent_change == 0.0` even though `point_change` is large and positive — a misleading metric that contradicts the visible `point_change`. The zero-guard prevents div-by-zero but produces a false 0%.

**Fix:** When `first == 0` and `last != 0`, return `None` (make the SDK field `float | None`) or otherwise signal "n/a," so the frontend renders something truthful instead of 0%.

## Info

### IN-01: `_map_score` recomputed redundantly across `_player_score` and `_player_breakdown`

**File:** `apps/api/services/skill_service.py:179-227`
**Issue:** For each player, `_player_score` and `_player_breakdown` both call `_map_score(r, w)` for every row, and `_do_recompute` invokes both — so each per-map score is computed at least twice per recompute. Functionally correct (totals match) but duplicative.
**Fix:** Compute `_map_score` once per row and feed the scored list to both the aggregate and breakdown builders.

### IN-02: `bulk_insert_history` plain INSERT can abort a recompute on a same-instant `captured_at` collision

**File:** `apps/api/repository/skill_repository.py:253-282`, `apps/api/migrations/0031_skill_history.sql:19-24`
**Issue:** `score_history` PK is `(user_id, captured_at)`. `bulk_insert_history` does a plain INSERT with no conflict clause; two recomputes that mint the same `captured_at` for the same user (sub-microsecond burst) raise a unique violation inside the capture transaction and abort the whole rebuild. The test fixture itself relies on `ON CONFLICT ... DO UPDATE`, but production has no such guard. Unlikely given microsecond resolution, but the failure mode is an aborted recompute, not a no-op.
**Fix:** Add `ON CONFLICT (user_id, captured_at) DO NOTHING` (or `DO UPDATE`) to `bulk_insert_history`.

### IN-03: `SkillRecomputeRequestedEvent.cause_category` validation is normalization, not rejection — docstring mismatch

**File:** `apps/api/events/schemas.py:55-57`, `apps/api/services/skill_service.py:333-346`
**Issue:** The event field is a free `str` and the docstring says "the service validates it against the closed set." In practice `_resolve_cause_policy` only checks equality with `_PLAYER_ACTION`; any other non-SYSTEM value silently falls through to `(SYSTEM, None)`. A bad value never reaches the DB CHECK because the written `cause_category` is always one of the three constants — so it is normalized, not validated/rejected. Low risk; the doc claim is inaccurate.
**Fix:** Reword to "normalizes any unrecognized category to SYSTEM," or add an explicit membership check that raises on an unexpected value.

### IN-04: Integration recompute tests use a separate pool as "last-writer" and can race the shared snapshot under xdist

**File:** `apps/api/tests/integration/test_skill_dashboard.py:46-57`, `493-527`
**Issue:** `_recompute` builds a separate `SkillService` on the test's `asyncpg_pool` and runs `recompute_all`, which TRUNCATEs+replaces the *global* snapshot, while HTTP reads go through the app pool. Under pytest-xdist (8 workers) a sibling test's global rebuild can replace the snapshot between this test's recompute and its read. The conservation test is robust (per-row invariant), but the cause-attribution tests read "latest by captured_at," which another worker can overwrite — a latent flaky-test pattern.
**Fix:** Scope skill assertions to data the test alone produced (filter by its own users and recompute window) or isolate the skill schema per worker.

---

_Reviewed: 2026-06-16T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
