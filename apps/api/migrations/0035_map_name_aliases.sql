-- Keep compatibility names attached to the same row across repeated renames.
ALTER TABLE maps.names ADD COLUMN mastery_enabled boolean NOT NULL DEFAULT true;
UPDATE maps.names SET mastery_enabled = false WHERE name = 'Adlersbrunn';

CREATE TABLE maps.name_aliases (
    previous_name text PRIMARY KEY,
    canonical_name text NOT NULL REFERENCES maps.names(name) ON UPDATE CASCADE ON DELETE RESTRICT,
    CONSTRAINT map_name_alias_not_current CHECK (previous_name <> canonical_name)
);
CREATE INDEX map_name_aliases_canonical_idx ON maps.name_aliases(canonical_name);
COMMENT ON TABLE maps.name_aliases IS
    'Permanent compatibility names; API writers serialize canonical and alias ownership with one advisory lock.';
