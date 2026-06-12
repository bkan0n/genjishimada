-- Migration: Add skill schema + snapshot + weight config
-- Description: Creates the skill schema with a lean per-player snapshot table
--              (only players with >=1 eligible run get a row, D-07) and a
--              single-row typed weight config table seeded with the
--              community-adopted defaults (D-09). No pg_cron block — the nightly
--              rebuild backstop is an app-side lifespan task (plan 13-05), so this
--              migration applies cleanly on a fresh test DB with no pg_cron present.
-- Date: 2026-06-12

BEGIN;

CREATE SCHEMA IF NOT EXISTS skill;

-- Lean per-player snapshot (D-07): only players with >=1 eligible completion get a
-- row. Zero-score players are handled at read time (LEFT JOIN + COALESCE(0)).
CREATE TABLE IF NOT EXISTS skill.snapshot
(
    user_id      bigint PRIMARY KEY,
    skill_score  double precision NOT NULL,
    maps_cleared integer          NOT NULL,
    video_clears integer          NOT NULL,
    hardest_raw  double precision NOT NULL,
    breakdown    jsonb            NOT NULL DEFAULT '[]'::jsonb,  -- per-map array (D-06); jsonb<->msgspec codec
    computed_at  timestamptz      NOT NULL DEFAULT now()
);

-- Single typed-column weight config row (D-09): one column per weight, NOT key/value.
-- gamma >= 0.5 is enforced at the schema level so the farm-enabling gamma=0 is
-- never representable as a shipped weight (SPEC Constraint; T-13-01).
CREATE TABLE IF NOT EXISTS skill.weight_config
(
    id             integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    diff_base      double precision NOT NULL,
    gamma          double precision NOT NULL,
    time_bonus     double precision NOT NULL,
    shrink_k       double precision NOT NULL,
    wr_bonus       double precision NOT NULL,
    partial_factor double precision NOT NULL,
    medal_gold     double precision NOT NULL,
    medal_silver   double precision NOT NULL,
    medal_bronze   double precision NOT NULL,
    CONSTRAINT weight_config_gamma_floor CHECK (gamma >= 0.5)
);

-- Seed the single config row with the adopted defaults (D-09) only if empty, so a
-- re-run of the migration is idempotent and never inserts a second row (T-13-02).
INSERT INTO skill.weight_config (
    diff_base, gamma, time_bonus, shrink_k, wr_bonus, partial_factor,
    medal_gold, medal_silver, medal_bronze
)
SELECT 1.44, 0.68, 0.55, 10.0, 0.10, 0.60, 1.12, 1.07, 1.03
WHERE NOT EXISTS (SELECT 1 FROM skill.weight_config);

COMMIT;
