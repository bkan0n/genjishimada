-- Migration: Add skill score history + per-change capture tables
-- Description: Two forward-only capture tables in the skill schema (D-01). skill.score_history
--              is a lean per-user time-series (composite PK covers all /history window reads).
--              skill.score_change is the rich per-change record (cause + prev/new/delta + all-maps
--              impact diff jsonb, D-04). cause_category is text + CHECK (codebase idiom; no DB enum).
--              Forward-only: the migration adds no rows (SPEC req 1 — pre-phase scores are
--              unrecoverable). No pg_cron: the nightly recompute is an app-side lifespan task, so
--              this migration applies cleanly on a fresh test DB via conftest.py:_apply_sql_dir.
-- Date: 2026-06-16

BEGIN;

CREATE SCHEMA IF NOT EXISTS skill;

-- Lean per-user time-series (D-01): one row per user-with-data per recompute (D-02), even on
-- delta=0. All rows from one recompute share a single captured_at (the existing computed_at minted
-- at the top of _do_recompute). The composite PK (user_id, captured_at) covers every /history
-- window read — no extra index needed on this table.
CREATE TABLE IF NOT EXISTS skill.score_history (
    user_id bigint NOT NULL,
    captured_at timestamptz NOT NULL,
    skill_score double precision NOT NULL,
    PRIMARY KEY (user_id, captured_at)
);

-- Rich per-change record (D-01): one row per user-with-data per recompute. diff (D-04) is the
-- precomputed all-maps impact array {"maps":[{"map","prev","new","impact"},...]} round-tripped by
-- the existing jsonb<->msgspec codec (no manual JSON). cause_category is text + CHECK constraining
-- the closed set at the DB layer (T-14-01) — the codebase has no Postgres enum in any skill
-- migration. reason is the free-text channel ("global recalculation" for SYSTEM, etc.).
CREATE TABLE IF NOT EXISTS skill.score_change (
    change_id bigserial PRIMARY KEY,
    user_id bigint NOT NULL,
    captured_at timestamptz NOT NULL,
    previous_score double precision NOT NULL,
    new_score double precision NOT NULL,
    delta double precision NOT NULL,
    cause_category text NOT NULL CHECK (cause_category IN ('PLAYER_ACTION', 'MAP_ENVIRONMENT', 'SYSTEM')),
    reason text,
    diff jsonb NOT NULL DEFAULT '{}'::jsonb  -- all-maps impact array (D-04); jsonb<->msgspec codec
);

-- Feed index backing the newest-first /changes read (ORDER BY captured_at DESC per user).
CREATE INDEX IF NOT EXISTS skill_score_change_user_captured_idx
    ON skill.score_change (user_id, captured_at DESC);

COMMIT;
