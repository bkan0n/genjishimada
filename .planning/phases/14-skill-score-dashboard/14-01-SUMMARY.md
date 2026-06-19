---
phase: 14-skill-score-dashboard
plan: 01
subsystem: database
tags: [postgres, migration, skill-score, jsonb, asyncpg]

# Dependency graph
requires:
  - phase: 13-skill-score
    provides: "skill schema + skill.snapshot (source of previous_score + prev breakdown for D-05 capture)"
provides:
  - "Migration 0031 creating skill.score_history (lean per-user time-series, composite PK)"
  - "skill.score_change rich per-change capture table (prev/new/delta + cause + diff jsonb)"
  - "cause_category CHECK closed set (PLAYER_ACTION/MAP_ENVIRONMENT/SYSTEM), no DB enum"
  - "Feed index skill_score_change_user_captured_idx for newest-first /changes reads"
affects: [14-03 skill_repository bulk inserts/reads, 14-04 capture wiring, 14-05 dashboard routes]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Forward-only capture tables: no backfill INSERT, no pg_cron, BEGIN/COMMIT-wrapped DDL"
    - "text + CHECK for closed sets (cause_category) paired with SDK msgspec Literal — never a Postgres enum"

key-files:
  created:
    - apps/api/migrations/0031_skill_history.sql
  modified: []

key-decisions:
  - "Two tables per D-01: lean score_history (composite PK covers /history reads, no extra index) + rich score_change (bigserial PK)"
  - "cause_category as text + CHECK (T-14-01), consistent with skill migration idiom (no CREATE TYPE)"
  - "diff jsonb DEFAULT '{}' round-trips via the existing jsonb<->msgspec codec; stores all-maps impact array (D-04)"
  - "Forward-only: migration inserts no rows (D-03); no pg_cron (nightly recompute is app-side lifespan task)"

patterns-established:
  - "Append-only skill capture tables (no TRUNCATE, no backfill) mirroring 0027 DDL header/transaction style"

requirements-completed: [REQ-14-1, REQ-14-2, REQ-14-3]

# Metrics
duration: 12min
completed: 2026-06-16
---

# Phase 14 Plan 01: Skill Score History Migration Summary

**Migration 0031 adds two forward-only `skill`-schema capture tables — lean `skill.score_history` (composite-PK time-series) and rich `skill.score_change` (prev/new/delta + cause CHECK + all-maps impact `diff` jsonb) — the data foundation for the per-user skill dashboard.**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-06-16
- **Completed:** 2026-06-16
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments
- `skill.score_history`: `(user_id bigint, captured_at timestamptz, skill_score double precision)` with composite `PRIMARY KEY (user_id, captured_at)` — covers all `/history` window reads with no extra index.
- `skill.score_change`: `change_id bigserial PK` + `user_id, captured_at, previous_score, new_score, delta, cause_category text, reason text, diff jsonb DEFAULT '{}'` with the closed-set CHECK on `cause_category`.
- Feed index `skill_score_change_user_captured_idx ON skill.score_change (user_id, captured_at DESC)` backing the newest-first `/changes` feed.
- Forward-only: no backfill INSERT, no pg_cron; idempotent `CREATE SCHEMA/TABLE/INDEX IF NOT EXISTS` wrapped in `BEGIN;`/`COMMIT;`.
- Migration applied cleanly on the fresh pytest-databases test DB at session start (`conftest.py:_apply_sql_dir`) — the 4 existing `test_skill.py` integration tests pass, confirming valid SQL with no impact on Phase 13.

## Task Commits

1. **Task 1: Create migration 0031 with score_history + score_change tables** - `5f4e29c` (feat)

**Plan metadata:** committed with this SUMMARY.

## Files Created/Modified
- `apps/api/migrations/0031_skill_history.sql` - New forward-only DDL: `skill.score_history` + `skill.score_change` tables, `cause_category` CHECK, feed index.

## Decisions Made
None beyond the locked plan decisions (D-01 storage shape, D-03 forward-only, D-04 diff jsonb). All column types, names, and the index name follow the D-01 sketch and the 0027/0028 skill-migration idioms (`bigint`/`double precision`/`timestamptz`/`jsonb`, text+CHECK not enum, `bigserial` for the synthetic PK per RESEARCH A5).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Plan's `<verify>` one-liner has an unsatisfiable CHECK assertion**
- **Found during:** Task 1 (migration verification)
- **Issue:** The plan's automated verify command asserts `"cause_category IN ('PLAYER_ACTION','MAP_ENVIRONMENT','SYSTEM')" in sql.replace(' ','')`. It strips spaces from the SQL but NOT from its own search string (`cause_category IN (` retains spaces around `IN`), so the assertion can never match any valid SQL — it is a defect in the verification command, not the migration.
- **Fix:** Did not alter the migration to satisfy a buggy literal check. Confirmed the migration satisfies the actual acceptance criterion — the CHECK is present whitespace-insensitively (`check.replace(' ','') in sql.replace(' ','')` returns True) — and that all other verify assertions (`score_history`, `score_change`, `change_id bigserial`, no `CREATE TYPE`, no `INSERT`, `BEGIN`/`COMMIT`) pass. Also reformatted the file to single-space column separation and removed the literal words `CREATE TYPE`/`INSERT`/`backfill INSERT` from comments so the literal `'CREATE TYPE' not in sql.upper()` and `'INSERT' not in sql.upper()` assertions hold against comment text.
- **Files modified:** apps/api/migrations/0031_skill_history.sql
- **Verification:** Whitespace-insensitive CHECK presence True; all other plan assertions pass; `grep -ci pg_cron` returns 0; 4 `test_skill.py` integration tests pass (migration applied at session start).
- **Committed in:** 5f4e29c (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug — in the plan's verify command, not the implementation)
**Impact on plan:** No scope change. The migration meets every acceptance criterion as written; only the plan's verify one-liner was unsatisfiable.

## Issues Encountered
- No local Postgres container was running, so the migration could not be applied against a standalone throwaway DB directly. Instead used the plan's primary acceptance path: running an existing skill integration test, which provisions a fresh pytest-databases Postgres and applies every `migrations/*.sql` (including 0031) in sorted order at session start. Any DDL error in 0031 would abort `_apply_sql_dir` and fail all tests; the 4 tests passing confirms the migration applies cleanly with both tables resolvable.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Both capture tables exist for Wave 2 (14-03) to add bulk-insert + windowed-read + IDOR-checked lookup repository methods, and Wave 3 (14-04) to wire capture into `_do_recompute`.
- Scorer/tier tables (`skill.snapshot`, `skill.weight_config`, `skill.tier_config`) untouched — Phase 13 immutability preserved.

## Self-Check: PASSED

- FOUND: apps/api/migrations/0031_skill_history.sql
- FOUND: .planning/phases/14-skill-score-dashboard/14-01-SUMMARY.md
- FOUND: commit 5f4e29c

---
*Phase: 14-skill-score-dashboard*
*Completed: 2026-06-16*
