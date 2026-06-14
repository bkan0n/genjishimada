---
phase: 13-skill-score
plan: 01
subsystem: skill-score
tags: [migration, postgres, ddl, skill]
requires: []
provides:
  - "skill schema"
  - "skill.snapshot (lean per-player snapshot table)"
  - "skill.weight_config (single-row typed weight config, seeded)"
affects:
  - "apps/api/migrations"
tech-stack:
  added: []
  patterns:
    - "Sequential numbered migration (0027) in BEGIN/COMMIT with IF NOT EXISTS DDL (analog 0018)"
    - "Idempotent single-row seed via INSERT ... SELECT ... WHERE NOT EXISTS"
    - "Schema-level CHECK constraint to make an unsafe weight value unrepresentable"
key-files:
  created:
    - apps/api/migrations/0027_skill_score.sql
  modified: []
decisions:
  - "Omitted pg_cron block entirely (D-03): the scorer is Python (SkillService), so a SQL cron cannot reuse the single rebuild routine — the nightly backstop is an app-side lifespan task in plan 13-05. Omission also keeps 'applies cleanly on a fresh test DB' trivially true."
  - "Lean snapshot (D-07): user_id PRIMARY KEY, no FK — only players with >=1 eligible run get a row; zero-score players handled at read time."
  - "Single typed-column weight_config (D-09): one column per weight (medal dict flattened to medal_gold/silver/bronze), not key/value."
  - "CHECK (gamma >= 0.5) (T-13-01): makes the farm-enabling gamma=0 unrepresentable at the schema level."
metrics:
  duration: "~1m"
  completed: 2026-06-12
  tasks: 1
  files: 1
---

# Phase 13 Plan 01: Skill Score Migration Foundation Summary

Migration `0027_skill_score.sql` creates the `skill` schema, a lean per-player
`skill.snapshot` cache table, and a single-row typed `skill.weight_config` table
seeded with the community-adopted defaults — the data foundation every later plan
in the phase reads and writes.

## What Was Built

`apps/api/migrations/0027_skill_score.sql`, a single `BEGIN; ... COMMIT;` migration that:

1. `CREATE SCHEMA IF NOT EXISTS skill`.
2. `skill.snapshot` (lean, D-07): `user_id bigint PRIMARY KEY` (no FK), `skill_score`,
   `maps_cleared`, `video_clears`, `hardest_raw`, `breakdown jsonb DEFAULT '[]'` (per-map
   array, D-06; read via the existing jsonb↔msgspec codec), `computed_at timestamptz`.
3. `skill.weight_config` (single typed-column row, D-09): identity PK plus one
   `double precision NOT NULL` column per weight (`diff_base`, `gamma`, `time_bonus`,
   `shrink_k`, `wr_bonus`, `partial_factor`, `medal_gold/silver/bronze`) and a
   `CHECK (gamma >= 0.5)` constraint.
4. An idempotent seed (`INSERT ... SELECT ... WHERE NOT EXISTS`) of the adopted defaults:
   `diff_base=1.44, gamma=0.68, time_bonus=0.55, shrink_k=10.0, wr_bonus=0.10,
   partial_factor=0.60, medal_gold=1.12, medal_silver=1.07, medal_bronze=1.03`.

No `pg_cron`, `lootbox`, `xp`, or `skill_rank` references anywhere in the file.

## Verification Performed

Applied against a throwaway database (`skill_migration_test`) on the local docker
Postgres (`genjishimada-db-local`), since no test DB DSN was wired:

- **First apply:** exit 0 (`BEGIN / CREATE SCHEMA / CREATE TABLE x2 / INSERT 0 1 / COMMIT`).
- **Tables resolve:** `to_regclass('skill.snapshot')` and `to_regclass('skill.weight_config')` both non-NULL.
- **Seed:** exactly 1 row with all nine adopted defaults verified value-by-value.
- **Idempotent re-apply:** second apply exit 0, `INSERT 0 0`, config row count stays 1.
- **CHECK enforced:** inserting `gamma=0.0` is rejected by `weight_config_gamma_floor`.
- **Forbidden refs:** `grep -v '^--' | grep -c cron` → 0; `grep -ci 'lootbox|xp|skill_rank'` → 0.
- Throwaway DB dropped after verification.

## Deviations from Plan

None - plan executed exactly as written.

## Acceptance Criteria

- [x] `apps/api/migrations/0027_skill_score.sql` exists with skill schema + both tables + seeded config row.
- [x] Applies cleanly on a fresh DB (exit 0); no pg_cron required (0 `cron` references).
- [x] Seed idempotent — count stays 1 across re-applies.
- [x] `CHECK (gamma >= 0.5)` present and enforced; no `lootbox`/`xp`/`skill_rank` references.

## Self-Check: PASSED

- FOUND: apps/api/migrations/0027_skill_score.sql
- FOUND commit: de2456d (feat(13-01): add migration 0027)
