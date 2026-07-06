-- 0032_dynamic_map_management.sql
--
-- Dynamic Overwatch map management (phase 15).
--
-- Gives the now-dynamic maps.names table durability and integrity after the
-- OverwatchMap Literal was relaxed to `str` (plan 15-01). The map-name validation
-- gate moved off the msgspec decode boundary; this migration adds the DB backstop.
--
-- Three ordered steps (sequence is load-bearing — RESEARCH Pitfall 5):
--   1. Reconcile the 7 phantom Literal-only maps into maps.names (D-08) so the FK
--      can be added without orphaning them.
--   2. Orphan pre-flight (D-11): fail LOUDLY if any core.maps.map_name is absent
--      from maps.names. Local has 0 orphans; prod may differ — the migration must
--      NOT silently skip. The operator reconciles, then re-runs.
--   3. FK backstop (D-11): core.maps.map_name -> maps.names.name (ON UPDATE CASCADE),
--      mirroring the existing maps.mastery.map_name FK (0001_init.sql:1300). This is
--      one-shot DDL (no IF NOT EXISTS on ADD CONSTRAINT).
--
-- No banner_url column is added anywhere (D-06) — reads stay on get_map_banner().

-- 1. Reconcile the 7 phantom Literal-only maps (D-08) so the FK can be added.
INSERT INTO maps.names (name)
VALUES
    ('Arena Victoriae'),
    ('Gogadoro'),
    ('Neon Junction'),
    ('Place Lacroix'),
    ('Powder Keg Mine'),
    ('Redwood Dam'),
    ('Thames District')
ON CONFLICT DO NOTHING;

-- 2. Orphan pre-flight (D-11): fail loudly if any core.maps.map_name is unknown.
DO $$
DECLARE
    orphan text;
BEGIN
    SELECT string_agg(DISTINCT m.map_name, ', ') INTO orphan
    FROM core.maps m
    LEFT JOIN maps.names n ON n.name = m.map_name
    WHERE n.name IS NULL;

    IF orphan IS NOT NULL THEN
        RAISE EXCEPTION 'Cannot add FK: orphan core.maps.map_name values not in maps.names: %', orphan;
    END IF;
END $$;

-- 3. FK backstop (D-11) — mirrors maps.mastery.map_name (0001_init.sql:1300).
ALTER TABLE core.maps
    ADD CONSTRAINT maps_map_name_names_fk
    FOREIGN KEY (map_name) REFERENCES maps.names (name)
    ON UPDATE CASCADE;
