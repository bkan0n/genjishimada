-- Seed data for testing map tag filtering

-- =============================================================================
-- TAG LINKS FOR EXISTING MAPS
-- =============================================================================

-- Map 1 (1EASY) - "Other Heroes" tag
INSERT INTO maps.tag_links (map_id, tag_id)
SELECT 1, id FROM maps.tags WHERE name = 'Other Heroes'
ON CONFLICT (map_id, tag_id) DO NOTHING;

-- Map 2 (2EASY) - "XP Based" tag
INSERT INTO maps.tag_links (map_id, tag_id)
SELECT 2, id FROM maps.tags WHERE name = 'XP Based'
ON CONFLICT (map_id, tag_id) DO NOTHING;

-- Map 3 (4EASY) - "Low Grav/Speed" tag
INSERT INTO maps.tag_links (map_id, tag_id)
SELECT 3, id FROM maps.tags WHERE name = 'Low Grav/Speed'
ON CONFLICT (map_id, tag_id) DO NOTHING;

-- Map 4 (5EASY) - Multiple tags: "Other Heroes" and "XP Based"
INSERT INTO maps.tag_links (map_id, tag_id)
SELECT 4, id FROM maps.tags WHERE name = 'Other Heroes'
ON CONFLICT (map_id, tag_id) DO NOTHING;

INSERT INTO maps.tag_links (map_id, tag_id)
SELECT 4, id FROM maps.tags WHERE name = 'XP Based'
ON CONFLICT (map_id, tag_id) DO NOTHING;

-- Map 5 (6EASY) - "Low Grav/Speed" tag
INSERT INTO maps.tag_links (map_id, tag_id)
SELECT 5, id FROM maps.tags WHERE name = 'Low Grav/Speed'
ON CONFLICT (map_id, tag_id) DO NOTHING;
