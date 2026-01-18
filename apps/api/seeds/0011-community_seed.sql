-- Community seed data for testing community/statistics endpoints

-- =============================================================================
-- XP DATA FOR LEADERBOARD
-- =============================================================================

-- Add XP to existing users for leaderboard tests
INSERT INTO lootbox.xp (user_id, amount)
VALUES
  (100000000000000000, 100000),
  (100000000000000001, 150000),
  (100000000000000002, 75000),
  (100000000000000003, 50000);

-- =============================================================================
-- ADDITIONAL QUALITY VOTES FOR STATISTICS
-- =============================================================================

-- Quality votes for popular maps statistics
INSERT INTO maps.ratings (map_id, user_id, quality)
VALUES
  (3, 100000000000000000, 5),
  (3, 100000000000000001, 4),
  (4, 100000000000000000, 3),
  (4, 100000000000000001, 4),
  (5, 100000000000000000, 5);

-- =============================================================================
-- ADDITIONAL COMPLETIONS FOR MAP STATISTICS
-- =============================================================================

-- More completions to test completion time statistics
INSERT INTO core.completions (map_id, user_id, time, verified, screenshot, verified_by, message_id)
VALUES
  (1, 100000000000000000, 11000, TRUE, 'https://example.com/s1.png', 202, 13),
  (1, 100000000000000001, 13000, TRUE, 'https://example.com/s2.png', 202, 14),
  (1, 100000000000000002, 14000, TRUE, 'https://example.com/s3.png', 202, 15);
