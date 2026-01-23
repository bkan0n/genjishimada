CREATE TABLE IF NOT EXISTS maps.tags
(
    id       int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name     text UNIQUE NOT NULL,
    position int UNIQUE
);
COMMENT ON COLUMN maps.tags.position IS 'Visual ordering position for consistency';

CREATE TABLE IF NOT EXISTS maps.tag_links
(
    map_id int REFERENCES core.maps (id) ON UPDATE CASCADE ON DELETE CASCADE,
    tag_id int REFERENCES maps.tags (id) ON UPDATE CASCADE ON DELETE CASCADE,
    PRIMARY KEY (map_id, tag_id)
);
CREATE INDEX IF NOT EXISTS idx_tag_links_tag_id ON maps.tag_links (tag_id);

INSERT INTO maps.tags (
    name, position
)
VALUES (
    'Other Heroes', 1
), (
    'XP Based', 2
), (
    'Custom Grav/Speed', 3
)
ON CONFLICT (name) DO NOTHING;
