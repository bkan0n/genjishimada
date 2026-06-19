---
phase: 14-skill-score-dashboard
plan: 03
subsystem: skill-dashboard-repository
tags: [asyncpg, repository, skill-score, capture, pagination, idor]

# Dependency graph
requires:
  - phase: 14-skill-score-dashboard
    provides: "Migration 0031 (skill.score_history + skill.score_change) — Plan 14-01"
  - phase: 14-skill-score-dashboard
    provides: "SDK response structs + CauseCategory Literal — Plan 14-02 (read methods map to these field names)"
provides:
  - "SkillRepository.fetch_all_snapshots — one-query prev score+breakdown bulk read (D-05, before TRUNCATE)"
  - "SkillRepository.bulk_insert_history / bulk_insert_changes — append-only executemany inserts (D-02, NO TRUNCATE)"
  - "SkillRepository.fetch_history — windowed (captured_at >= since) ASC history read (SPEC req 3)"
  - "SkillRepository.fetch_changes — newest-first paginated feed, omits diff jsonb (SPEC req 4, Warning 4)"
  - "SkillRepository.fetch_change — drill-down with ownership predicate (SPEC req 5, T-14-06 IDOR mitigation)"
  - "CompletionsRepository.fetch_completion_owner_by_message — actor_user_id owner lookup (A4)"
affects:
  - "14-04 capture wiring (calls fetch_all_snapshots before replace_snapshot + the two bulk inserts; flag/unflag emit sites call fetch_completion_owner_by_message)"
  - "14-05 dashboard routes/service (call fetch_history/fetch_changes/fetch_change)"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Append-only bulk insert: executemany + Pool-vs-Connection fork minus TRUNCATE (forward-only capture tables)"
    - "IDOR mitigation in SQL: ownership predicate WHERE change_id=$1 AND user_id=$2 → None → route 404 (not 403)"
    - "Feed SELECT omits the heavy diff jsonb (Warning 4 — only the drill-down deserializes per-map array)"
    - "Owner lookup lives on the repo that owns the table (completions owns core.completions) — no cross-service private access"

key-files:
  created: []
  modified:
    - "apps/api/repository/skill_repository.py (+6 methods: fetch_all_snapshots, bulk_insert_history, bulk_insert_changes, fetch_history, fetch_changes, fetch_change; +datetime import)"
    - "apps/api/repository/completions_repository.py (+1 method: fetch_completion_owner_by_message)"

key-decisions:
  - "fetch_changes deliberately omits diff from its SELECT (Warning 4) — only fetch_change (drill-down) selects diff"
  - "fetch_change carries the ownership predicate in SQL (change_id=$1 AND user_id=$2), so IDOR mitigation lives at the data layer, not just the route (T-14-06)"
  - "fetch_completion_owner_by_message placed on CompletionsRepository (A4) — mirrors the suspicious-flag message_id/verification_id resolution model, yields user_id not completion id"

requirements-completed: [REQ-14-1, REQ-14-2, REQ-14-3, REQ-14-4, REQ-14-5, REQ-14-6, REQ-14-7]

# Metrics
duration: 14min
completed: 2026-06-16
tasks: 2
files: 2
---

# Phase 14 Plan 03: Skill Dashboard Repository Methods Summary

**Six new data-access methods on `SkillRepository` (the capture-layer prev-snapshot bulk read, two append-only bulk inserts, plus the windowed history read, paginated newest-first feed, and ownership-checked single-change drill-down) and one completion-owner lookup on `CompletionsRepository` — all `*, conn`-keyword, positional-param-only, `just lint-api` clean, with the Phase 13 scorer/snapshot methods byte-for-byte untouched.**

## Performance

- **Duration:** ~14 min
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

**Task 1 — Capture layer (`apps/api/repository/skill_repository.py`):**
- `fetch_all_snapshots(*, conn=None) -> dict[int, dict]` — ONE `SELECT user_id, skill_score, breakdown FROM skill.snapshot`, returning `{user_id: {"skill_score", "breakdown"}}`. Single round-trip (not per-user, Pitfall 3); `breakdown` decodes via the jsonb codec. Callable BEFORE `replace_snapshot` so Wave 3 reads prev state before the TRUNCATE (Pitfall 1 / D-05).
- `bulk_insert_history(rows, *, conn=None) -> None` — append-only `executemany` `INSERT INTO skill.score_history (user_id, captured_at, skill_score)` with the same Pool-vs-Connection fork as `replace_snapshot` but **no TRUNCATE**; empty-list-safe early return.
- `bulk_insert_changes(rows, *, conn=None) -> None` — append-only `executemany` over the 8 `skill.score_change` columns; `r["diff"]` passed as a raw Python dict (jsonb codec serializes it — no `json.dumps`). Empty-list-safe.

**Task 2 — Read layer + owner lookup:**
- `SkillRepository.fetch_history(user_id, since, *, conn=None) -> list[dict]` — `WHERE user_id=$1 AND captured_at >= $2 ORDER BY captured_at ASC`; `since` bound positionally.
- `SkillRepository.fetch_changes(user_id, since, limit, offset, *, conn=None) -> list[dict]` — feed query selecting only `change_id, captured_at, previous_score, new_score, delta, cause_category, reason` (NO `diff`, Warning 4), `ORDER BY captured_at DESC LIMIT $3 OFFSET $4` (uses the `(user_id, captured_at DESC)` feed index).
- `SkillRepository.fetch_change(user_id, change_id, *, conn=None) -> dict | None` — the only method that SELECTs `diff`; `WHERE change_id=$1 AND user_id=$2` ownership predicate (T-14-06); `fetchrow` → `dict(row) if row else None` (foreign id → None → route 404).
- `CompletionsRepository.fetch_completion_owner_by_message(message_id, verification_id, *, conn=None) -> int | None` — SELECTs `user_id FROM core.completions` using the identical `($1::bigint IS NOT NULL AND message_id=$1::bigint) OR ($1::bigint IS NULL AND verification_id=$2::bigint)` model as the suspicious-flag methods in the same file; `fetchval`. The A4 resolution — flag/unflag emit sites (14-04) call this via `self._completions_repo`.

## Verification Results

- **Task 1 automated verify:** `capture repo methods OK` — the three methods exist; neither insert contains `TRUNCATE skill.score_history`/`TRUNCATE skill.score_change`; both `INSERT INTO` statements present.
- **Task 2 verify (SQL-scoped, see Deviations):** `read repo methods OK` — `fetch_history`/`fetch_changes`/`fetch_change` exist on `SkillRepository`; `fetch_completion_owner_by_message` is NOT on `SkillRepository` and IS on `CompletionsRepository`; ownership predicate `change_id=$1 AND user_id=$2` present; `ORDER BY captured_at DESC` + `LIMIT $3 OFFSET $4` present; `fetch_changes` **SQL** omits `diff` while `fetch_change` **SQL** includes it.
- **`just lint-api`:** ruff format/check + basedpyright — `All checks passed!` / `0 errors, 0 warnings, 0 notes`.
- **Existing tests:** `pytest tests/integration/test_skill.py -x` → **15 passed, 4 deselected** — additive change, no Phase 13 regression.
- **Immutability:** `git diff 3fa8883 HEAD -- apps/api/repository/skill_repository.py` shows **additions only, no removed lines** — `replace_snapshot`, `fetch_snapshot`, `fetch_skill_inputs`, `fetch_weights`, `compute_tier_boundaries`, and the tier methods are byte-for-byte unchanged.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan's Task 2 `<verify>` one-liner false-positives on docstring text**
- **Found during:** Task 2 verification.
- **Issue:** The plan's automated verify asserts `'diff' not in fc` where `fc` is the regex-captured `fetch_changes` method body. The `fetch_changes` docstring legitimately mentions `diff` three times ("deliberately OMITTING the heavy `diff` jsonb…", "selecting `diff` would force…", "the drill-down `fetch_change` is the only method that SELECTs `diff`"), so the substring check fails even though the SQL `SELECT` correctly omits `diff`. This is a defect in the verify command (it scans the whole method body, including the docstring), not the implementation — the same class of bug noted in 14-01's SUMMARY.
- **Fix:** Did NOT remove the explanatory docstring to satisfy a literal substring match (the docstring documenting the Warning-4 omission is load-bearing for future maintainers). Validated the actual acceptance criterion instead: parsed the method with `ast`, stripped the docstring, and confirmed the `fetch_changes` **SQL string** contains no `diff` column while the `fetch_change` **SQL string** does. All other plan assertions (method presence/placement, ownership predicate, DESC ordering, LIMIT/OFFSET) pass against the raw source as written.
- **Files modified:** None (the implementation already satisfies the acceptance criterion; only the plan's verify command was unsatisfiable).
- **Verification:** SQL-scoped check prints `read repo methods OK (SQL-scoped diff check)`.
- **Committed in:** N/A (no implementation change required).

**Total deviations:** 1 (a defect in the plan's Task 2 verify command, not the code). **Impact on plan:** none — every acceptance criterion is met as written.

## Threat Model Notes

- **T-14-06 (Information Disclosure, `fetch_change`) — mitigated:** the ownership predicate `WHERE change_id=$1 AND user_id=$2` is in the SQL, so a foreign `change_id` returns no row → `None` → the route raises 404 (not 403, avoiding existence confirmation / IDOR enumeration). Mitigation lives at the data layer, not just the route.
- **T-14-07 (Tampering, all read queries) — mitigated:** every method uses `$1,$2,…` positional params; `since`/`limit`/`offset` are never string-interpolated into SQL.
- **T-14-08 (DoS, feed page size) — mitigated:** `LIMIT`/`OFFSET` are bound params; the repo trusts the route-validated bound (route caps `limit` in 14-05).
- **No new threat surface** introduced beyond the threat register: the methods are repository reads/writes over the two 0031 tables and a `core.completions` owner read; no new endpoints, auth paths, or trust boundaries.

## Self-Check: PASSED

- FOUND: apps/api/repository/skill_repository.py (6 new methods)
- FOUND: apps/api/repository/completions_repository.py (fetch_completion_owner_by_message)
- FOUND: commit e32fb1a (Task 1)
- FOUND: commit 58cb910 (Task 2)
- FOUND: .planning/phases/14-skill-score-dashboard/14-03-SUMMARY.md

---
*Phase: 14-skill-score-dashboard*
*Completed: 2026-06-16*
