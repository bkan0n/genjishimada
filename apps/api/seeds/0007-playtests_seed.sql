-- Playtests seed data for testing playtest endpoints

SET migration.skip_verified_check = true;

-- =============================================================================
-- PLAYTEST TEST MAPS
-- =============================================================================

INSERT INTO core.maps(code, map_name, category, checkpoints, description, raw_difficulty)
VALUES
  ('PTEST1', 'Hanamura', 'Classic', 10, 'Playtest Map 1', 3.5),
  ('PTEST2', 'Hanamura', 'Classic', 15, 'Playtest Map 2', 4.5),
  ('PTEST3', 'Hanamura', 'Classic', 20, 'Playtest Map 3 - No votes', 5.0);

-- =============================================================================
-- PLAYTEST CREATORS
-- =============================================================================

-- Get map IDs (assuming 43, 44, 45 based on previous seed adding 42 maps)
INSERT INTO maps.creators (user_id, map_id, is_primary)
VALUES
  (100000000000000001, 43, TRUE),
  (100000000000000002, 44, TRUE),
  (100000000000000003, 45, TRUE);

-- =============================================================================
-- PLAYTEST METADATA
-- =============================================================================

INSERT INTO playtests.meta (thread_id, map_id, verification_id, initial_difficulty)
VALUES
  (2000000001, 43, 3000000001, 3.5),
  (2000000002, 44, 3000000002, 4.5),
  (2000000003, 45, NULL, 5.0);

-- =============================================================================
-- PLAYTEST VOTES
-- =============================================================================

-- Need verified completions first for votes to be valid
INSERT INTO core.completions (map_id, user_id, time, verified, screenshot, verified_by, completion, message_id)
VALUES
  (43, 200, 30000, TRUE, 'https://example.com/pt1.png', 202, TRUE, 10),
  (43, 201, 31000, TRUE, 'https://example.com/pt2.png', 202, TRUE, 11),
  (44, 200, 40000, TRUE, 'https://example.com/pt3.png', 202, TRUE, 12);

-- Playtest 1 has 2 votes
INSERT INTO playtests.votes (playtest_thread_id, user_id, map_id, difficulty)
VALUES
  (2000000001, 200, 43, 3.5),
  (2000000001, 201, 43, 4.0);

-- Playtest 2 has 1 vote
INSERT INTO playtests.votes (playtest_thread_id, user_id, map_id, difficulty)
VALUES
  (2000000002, 200, 44, 5.0);

-- Playtest 3 has no votes (for empty state tests)
