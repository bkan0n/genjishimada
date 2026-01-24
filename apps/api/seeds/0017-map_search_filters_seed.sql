-- Seed data to support map search filter tests

INSERT INTO maps.mechanics (name)
VALUES
  ('Bhop'),
  ('Dash'),
  ('Ultimate')
ON CONFLICT (name) DO NOTHING;

INSERT INTO maps.restrictions (name)
VALUES
  ('Wall Climb'),
  ('Bhop')
ON CONFLICT (name) DO NOTHING;

INSERT INTO maps.mechanic_links (map_id, mechanic_id)
SELECT m.id, mech.id
FROM core.maps m
JOIN maps.mechanics mech ON mech.name = 'Bhop'
WHERE m.code = '1EASY'
ON CONFLICT (map_id, mechanic_id) DO NOTHING;

INSERT INTO maps.mechanic_links (map_id, mechanic_id)
SELECT m.id, mech.id
FROM core.maps m
JOIN maps.mechanics mech ON mech.name = 'Dash'
WHERE m.code = '2EASY'
ON CONFLICT (map_id, mechanic_id) DO NOTHING;

INSERT INTO maps.mechanic_links (map_id, mechanic_id)
SELECT m.id, mech.id
FROM core.maps m
JOIN maps.mechanics mech ON mech.name = 'Ultimate'
WHERE m.code = '3EASY'
ON CONFLICT (map_id, mechanic_id) DO NOTHING;

INSERT INTO maps.restriction_links (map_id, restriction_id)
SELECT m.id, res.id
FROM core.maps m
JOIN maps.restrictions res ON res.name = 'Wall Climb'
WHERE m.code = '1EASY'
ON CONFLICT (map_id, restriction_id) DO NOTHING;

INSERT INTO maps.restriction_links (map_id, restriction_id)
SELECT m.id, res.id
FROM core.maps m
JOIN maps.restrictions res ON res.name = 'Bhop'
WHERE m.code = '2EASY'
ON CONFLICT (map_id, restriction_id) DO NOTHING;

INSERT INTO maps.medals (map_id, gold, silver, bronze)
SELECT m.id, 10000, 15000, 20000
FROM core.maps m
WHERE m.code = '1EASY'
ON CONFLICT (map_id) DO UPDATE
SET gold = EXCLUDED.gold,
    silver = EXCLUDED.silver,
    bronze = EXCLUDED.bronze;

UPDATE core.maps
SET archived = TRUE
WHERE code = '1MEDIU';

UPDATE core.maps
SET hidden = TRUE
WHERE code = '9EASY';

UPDATE core.maps
SET official = FALSE
WHERE code = '8EASY';

UPDATE core.maps
SET playtesting = 'In Progress'
WHERE code IN ('2EASY', 'PTEST1', 'PTEST2', 'PTEST3');

UPDATE core.maps
SET playtesting = 'Approved'
WHERE code = '1EASY';

UPDATE playtests.meta
SET completed = FALSE
WHERE thread_id IN (2000000001, 2000000002, 2000000003);
