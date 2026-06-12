---
phase: 13-skill-score
reviewed: 2026-06-12T00:00:00Z
depth: standard
files_reviewed: 18
files_reviewed_list:
  - apps/api/migrations/0027_skill_score.sql
  - apps/api/repository/skill_repository.py
  - apps/api/services/skill_service.py
  - apps/api/services/exceptions/skill.py
  - apps/api/routes/v3/skill.py
  - apps/api/events/skill.py
  - apps/api/events/schemas.py
  - apps/api/app.py
  - apps/api/services/completions_service.py
  - apps/api/routes/v3/completions.py
  - apps/api/repository/community_repository.py
  - apps/api/services/community_service.py
  - apps/api/routes/v3/community.py
  - libs/sdk/src/genjishimada_sdk/skill.py
  - libs/sdk/src/genjishimada_sdk/users.py
  - libs/sdk/src/genjishimada_sdk/__init__.py
  - apps/api/tests/integration/test_skill.py
findings:
  critical: 1
  warning: 6
  info: 3
  total: 10
status: issues_found
---

# Phase 13: Code Review Report

**Reviewed:** 2026-06-12
**Depth:** standard
**Files Reviewed:** 18
**Status:** issues_found

## Summary

Phase 13 adds a hybrid skill-score feature (schema + scorer + read endpoints + superuser weight config + leaderboard column). The core scorer math is a clean, bounded port; the weight-column allow-list (`_WEIGHT_COLUMNS`), the gamma DB CHECK + service pre-check, the lean-snapshot read/COALESCE(0) contract, and the superuser-only PATCH guard are all correctly implemented. The in-flight collapse guard is race-free under the single-threaded event loop (no `await` between the `locked()` check and `acquire()`), and the snapshot replace is correctly wrapped in a single TRUNCATE+upsert transaction.

The dominant defect is a **missing recompute emit on the `moderate_completion` path** — a verification-state-change route that flips `verified` and adds/removes suspicious flags but never fires `skill.recompute.requested`, leaving the snapshot stale until the nightly backstop. Secondary concerns: raw SQL interpolation of `sort_column`/`sort_direction` in the leaderboard query (relies solely on the `Literal` type holding, with no SQL-boundary allow-list unlike the sibling weight code), an `ORDER BY nickname` ambiguity risk, and a post-commit recompute that is fire-and-forget but can run on a released pool.

## Critical Issues

### CR-01: `moderate_completion` never emits a skill recompute despite changing verification + suspicious state

**File:** `apps/api/services/completions_service.py:1411-1507`
**Issue:** The prompt requires the recompute emit to fire from *every* verification-state-change path. `verify_completion` (line 1091-1094), `set_suspicious_flags` (line 1291), and `remove_suspicious_flags` (line 1320) all emit. But `moderate_completion` is a separate route (`PUT /completions/{id}/moderate`) that:
- flips verification via `update_completion_verified` when `verified != old_verified` (lines 1449-1478), and
- inserts a suspicious flag via `insert_suspicious_flag_by_completion_id` (lines 1480-1500) / deletes one via `delete_suspicious_flag` (lines 1502-1507).

Both mutations change a row's skill eligibility exactly like the paths that *do* emit, yet `moderate_completion` fires no `skill.recompute.requested`. The skill snapshot therefore goes stale after any moderation verify/unverify/flag/unflag and is only self-healed by the 04:00 UTC nightly backstop — a freshness violation of SPEC req 8/9 for this entire endpoint. The method does not even accept a `skill_service`/`request` emit handle, so the route (`completions.py:365-379`) cannot thread one in.

**Fix:** Thread the emit handle into `moderate_completion` and fire it whenever verification or suspicious state actually changed:
```python
async def moderate_completion(
    self,
    completion_id: int,
    data: CompletionModerateRequest,
    notification_service: NotificationsService | None = None,
    headers: Headers | None = None,
    *,
    request: Request | None = None,
    skill_service: SkillService | None = None,
) -> None:
    ...
    skill_dirty = False
    # in the verified branch, after a real flip:
    if verified != old_verified:
        skill_dirty = True
        ...
    # in the mark/unmark suspicious branches, when a flag is actually added/removed:
    if data.mark_suspicious and not existing:
        skill_dirty = True
    if data.unmark_suspicious and deleted_count > 0:
        skill_dirty = True
    ...
    if skill_dirty:
        self._emit_skill_recompute(request, skill_service, reason="skill.recompute.requested:moderate")
```
Then inject `skill_service`/`request` in `moderate_completion` route handler (`routes/v3/completions.py:365`) — the controller already declares `skill_service` as a dependency (line 78), so it is available to add.

## Warnings

### WR-01: Leaderboard `sort_column` / `sort_direction` are interpolated raw into SQL with no SQL-boundary allow-list

**File:** `apps/api/repository/community_repository.py:80, 232`
**Issue:** `sort_values` (= `sort_column` for the non-`skill_rank` branch) and `sort_direction` are f-string-interpolated directly into the query (`ORDER BY {sort_values} {sort_direction}`). Safety rests *entirely* on the `Literal[...]` type annotation being enforced at every call site. This is inconsistent with the defense-in-depth pattern the same phase uses for weights (`skill_repository.py:_WEIGHT_COLUMNS` rejects unknown column names at the SQL boundary). A future internal caller, a refactor that loosens the type, or a `# type: ignore` would turn this into SQL injection. The repository must not trust the type system as its only guard for interpolated identifiers.
**Fix:** Validate against an explicit allow-list inside the repo before interpolating, mirroring `_WEIGHT_COLUMNS`:
```python
_SORT_COLUMNS = frozenset({
    "xp_amount", "nickname", "prestige_level", "wr_count", "map_count",
    "playtest_count", "discord_tag", "skill_rank", "skill_score",
})
if sort_column not in _SORT_COLUMNS:
    raise ValueError(f"invalid sort_column: {sort_column!r}")
if sort_direction not in ("asc", "desc"):
    raise ValueError(f"invalid sort_direction: {sort_direction!r}")
```

### WR-02: `ORDER BY nickname` is ambiguous — `nickname` appears in two CTE scopes

**File:** `apps/api/repository/community_repository.py:185, 210, 232`
**Issue:** When `sort_column="nickname"`, the final clause is `ORDER BY nickname asc`. The outer SELECT aliases `u.nickname AS nickname` (line 210), but the `xp_tiers` subquery also projects `coalesce(own.username, nickname) AS nickname` (line 185), and the WHERE clause references a bare `nickname` (line 229). Relying on Postgres resolving the unqualified `nickname` in ORDER BY to the outer output column is fragile; if the projection shifts, the sort silently changes meaning or errors with "column reference is ambiguous." The leaderboard sort is a user-facing contract, so a silent reordering is a real defect risk.
**Fix:** Sort by the output column position or a fully-qualified/unique alias. Simplest: alias the outer column distinctly (e.g., `u.nickname AS lb_nickname`) and order by that, or `ORDER BY 2 {sort_direction}` against a fixed projection. Confirm the chosen approach against the existing pre-skill behavior so no regression is introduced.

### WR-03: Post-commit recompute is fire-and-forget on the request app pool and can run against a released/closed pool

**File:** `apps/api/services/completions_service.py:1002-1008`; `apps/api/events/skill.py:16-29`
**Issue:** `_emit_skill_recompute` does `request.app.emit(...)`, whose listener runs `recompute_all()` in the background after the response returns. `recompute_all` reads weights + the full input query + writes the whole snapshot on the app pool. There is no error capture around the listener body beyond Litestar's default; a recompute failure (e.g., pool drained at shutdown, a transient DB error) is dropped with only a debug log at entry (line 28). The integration test harness itself documents this exact hazard (`test_skill.py:55-69`: "the background listener runs on the app's OWN pool — which the AsyncTestClient may have already released, producing a logged (non-fatal) listener error"), confirming the failure mode is reachable in practice, not hypothetical. A dropped recompute leaves the snapshot stale until 04:00 UTC.
**Fix:** Wrap the listener body in try/except that captures to Sentry (consistent with the nightly poller at `app.py:147-148`), so a missed event is observable rather than silently swallowed:
```python
async def handle_skill_recompute(event, skill_service) -> None:
    try:
        await skill_service.recompute_all()
    except Exception:
        log.exception("[!] skill recompute (reason=%s) failed", event.reason)
        sentry_sdk.capture_exception()
```

### WR-04: Recompute reruns full snapshot on every coalesced trigger even when inputs are unchanged

**File:** `apps/api/services/skill_service.py:184-191`
**Issue:** The collapse guard sets `rerun_requested=True` unconditionally on entry (line 184) and the holder loops while the flag is set (line 189). Because the flag is set *before* the `locked()` check, the holding coroutine always executes at least one extra loop iteration whenever any second trigger arrives during a run — even if that second trigger's underlying input change was already captured by the in-progress `_do_recompute`. Under a burst of verify/flag events (e.g., a moderator clearing a queue), this produces back-to-back full input-query + full snapshot rebuilds with no dedup window. This is correctness-safe (the final snapshot is consistent) but degrades to an unbounded sequential rebuild chain proportional to burst size. Functionally a robustness concern, not data loss.
**Fix:** Acceptable to leave for now given correctness holds, but consider a short debounce (collect triggers for N ms before the holder reruns) or skipping the rerun when no new trigger arrived after the snapshot write began. At minimum, document that burst size N implies up to N sequential rebuilds so operators can reason about load.

### WR-05: `_jsonb_encoder` re-encodes a `str` as-is, so a string breakdown would silently store unescaped text

**File:** `apps/api/app.py:181-184`; `apps/api/repository/skill_repository.py:194-196`
**Issue:** `replace_snapshot` passes `r["breakdown"]` (a Python `list[dict]`) as the jsonb param, relying on `_jsonb_encoder` to `msgspec.json.encode` it. But `_jsonb_encoder` short-circuits and returns `value` verbatim when `isinstance(value, str)` (line 182). The breakdown is always a list here, so this path is correct today — however the encoder's str passthrough means if any future caller (or a bug upstream) hands a Python `str` that is not valid JSON, it is written into a `jsonb` column and will fail at the DB or, worse, store a malformed value. The skill snapshot relies on this codec for its only structured column.
**Fix:** This is a shared-codec concern, not skill-specific, but worth a guard or comment: the str-passthrough assumes the caller already produced valid JSON text. Prefer encoding non-str values and rejecting/validating str inputs, or document the contract at the `replace_snapshot` call site so a future change cannot pass a raw display string into `breakdown`.

### WR-06: `update_weights` returns `{}` on no-op which `msgspec.convert(..., Weights)` will reject

**File:** `apps/api/repository/skill_repository.py:244-258`; `apps/api/services/skill_service.py:275`
**Issue:** `update_weights` returns `self.fetch_weights()` when `updates` is empty (line 245-246), and `fetch_weights` returns `{}` if the config row is missing (line 227). `SkillService.update_weights` then calls `msgspec.convert(<that dict>, Weights)` (line 275). `Weights` has nine required fields with no defaults, so converting `{}` raises a msgspec validation error surfaced as an opaque 500 rather than a meaningful response. This only triggers if the seeded config row is absent (migration not applied, or row deleted), but the empty-dict branch is dead-end handling that masks the real cause.
**Fix:** Treat a missing config row as an explicit error in the service/repo rather than returning `{}`:
```python
weights = await self._skill_repo.fetch_weights()
if not weights:
    raise SkillError("skill.weight_config row is missing; run migration 0027")
return msgspec.convert(weights, Weights)
```

## Info

### IN-01: `field_rank` is selected and grouped but never consumed by the scorer

**File:** `apps/api/repository/skill_repository.py:46, 74, 93`
**Issue:** `field_rank` is computed in the `field` CTE, projected, and added to GROUP BY, but `skill_service.py` only reads `field_size`, `time_pct`, `video_rank`, `medal`, `fully_verified`, `raw_difficulty`. `field_rank` is dead output that widens the row and the GROUP BY for no consumer.
**Fix:** Drop `field_rank` from the SELECT/GROUP BY unless a downstream consumer is planned; if intentionally reserved, add a comment saying so.

### IN-02: `SkillBreakdownRow` is in `skill.py.__all__` but `Weights`/`SkillConfigUpdateRequest`/`SkillSummaryResponse` ordering is fine — no `Weights` re-export issue, just confirm symmetry

**File:** `libs/sdk/src/genjishimada_sdk/skill.py:5-10`
**Issue:** The module `__all__` lists all four public structs and matches the class definitions; no action required. Noting only that `users.py.__all__` (`users.py:8-22`) does not include any skill symbol, which is correct since `CommunityLeaderboardResponse.skill_score`/`skill_rank` are plain fields, not skill structs. No defect — recorded for completeness of the cross-module export audit.
**Fix:** None.

### IN-03: `_diff_weight` exponent is unbounded if `raw_difficulty` is ever out of the documented 0-10 range

**File:** `apps/api/services/skill_service.py:69-71`
**Issue:** `diff_base ** (raw - 1.5)` assumes `raw` is the documented 0-10 numeric. With the seeded `diff_base=1.44` the max contribution is ~22 (`1.44 ** 8.5`), which is safe. But there is no clamp; a corrupt `raw_difficulty` (negative or very large) would produce an extreme or near-zero floor with no guard. Low risk given the column is DB-controlled, but a defensive clamp would harden the scorer.
**Fix:** Optionally clamp `raw` to the expected `[0, 10]` range before exponentiation, or assert the invariant during ingest.

---

_Reviewed: 2026-06-12_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
