-- Migration: Add skill.tier_config for the percentile-based tier system
-- Description: Creates a single-row config table holding the percentile-based TIER
--              boundaries (7 boundaries -> icon ranks 1..8, 0 = Unranked) layered on
--              top of the existing numeric skill_score (migration 0027). The
--              `percentiles` array is the ONLY tunable — boundaries are DERIVED from
--              the live distribution by recompute_all (no hardcoded score cutoffs,
--              mirroring the 0027 "no hardcoded weights" rule). Boundaries start EMPTY
--              and are filled by the first qualifying recompute; reads treat an empty
--              boundaries array as "everyone Unranked". Applies cleanly on a fresh
--              test DB (schema `skill` already created by 0027).
-- Date: 2026-06-12

BEGIN;

CREATE SCHEMA IF NOT EXISTS skill;

-- Single-row tier config (one row, like skill.weight_config): the 7 computed cut-point
-- scores, the 7 configurable percentiles that produce them, and when they were computed.
-- 7 boundaries mint integer tiers 1..8 via width_bucket; tier 0 is reserved for Unranked.
CREATE TABLE IF NOT EXISTS skill.tier_config
(
    id          integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    boundaries  float8[]    NOT NULL DEFAULT '{}'::float8[],  -- 7 computed cut-points; empty until first qualifying recompute
    percentiles float8[]    NOT NULL,                          -- 7 configurable percentiles; the ONLY tunable
    computed_at timestamptz NOT NULL DEFAULT now()
);

-- Seed the single config row with the default percentile array only if empty, so a
-- re-run of the migration is idempotent and never inserts a second row. NO hardcoded
-- SCORE cutoffs — boundaries start empty and are filled by recompute_all.
INSERT INTO skill.tier_config (boundaries, percentiles)
SELECT '{}'::float8[], ARRAY[0.50, 0.70, 0.85, 0.93, 0.97, 0.99, 0.995]::float8[]
WHERE NOT EXISTS (SELECT 1 FROM skill.tier_config);

COMMIT;
