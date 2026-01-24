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
SELECT m.id, v.user_id, v.quality
FROM (
    VALUES
        ('4EASY', 100000000000000000, 5),
        ('4EASY', 100000000000000001, 4),
        ('5EASY', 100000000000000000, 3),
        ('5EASY', 100000000000000001, 4),
        ('6EASY', 100000000000000000, 5)
) AS v(code, user_id, quality)
JOIN core.maps m ON m.code = v.code;

-- =============================================================================
-- ADDITIONAL COMPLETIONS FOR MAP STATISTICS
-- =============================================================================

-- More completions to test completion time statistics
INSERT INTO core.completions (map_id, user_id, time, verified, screenshot, verified_by, message_id)
SELECT m.id, v.user_id, v.time, v.verified, v.screenshot, v.verified_by, v.message_id
FROM (
    VALUES
        ('1EASY', 100000000000000000, 11000, TRUE, 'https://example.com/s1.png', 202, 13),
        ('1EASY', 100000000000000001, 13000, TRUE, 'https://example.com/s2.png', 202, 14),
        ('1EASY', 100000000000000002, 14000, TRUE, 'https://example.com/s3.png', 202, 15)
) AS v(code, user_id, time, verified, screenshot, verified_by, message_id)
JOIN core.maps m ON m.code = v.code;
