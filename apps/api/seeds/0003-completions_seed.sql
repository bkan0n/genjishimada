-- Completions seed data for testing completion endpoints

-- =============================================================================
-- COMPLETION TEST USERS
-- =============================================================================

INSERT INTO core.users (
    id, nickname, global_name, coins
)
VALUES (
    200, 'CompletionUser1', 'CompletionUser1', 100
), (
    201, 'CompletionUser2', 'CompletionUser2', 200
), (
    202, 'CompletionVerifier', 'CompletionVerifier', 500
);

-- Overwatch usernames for completion users (needed for leaderboard display)
INSERT INTO users.overwatch_usernames (
    user_id, username, is_primary
)
VALUES (
    200, 'CompletionPlayer#1234', TRUE
), (
    201, 'AnotherPlayer#5678', TRUE
);

-- =============================================================================
-- VERIFIED COMPLETIONS (for leaderboard and user completion tests)
-- =============================================================================

-- Map 1 (1EASY) completions - two users with different times
INSERT INTO core.completions (
    map_id, user_id, time, verified, video, screenshot, verified_by, message_id
)
VALUES (
    1, 200, 12345, TRUE, NULL, 'https://example.com/screenshot1.png', 202, 1
), (
    1, 201, 15000, TRUE, NULL, 'https://example.com/screenshot2.png', 202, 2
);

-- Map 2 (2EASY) completions - one user
INSERT INTO core.completions (
    map_id, user_id, time, verified, video, screenshot, verified_by, message_id
)
VALUES (
    2, 200, 20000, TRUE, NULL, 'https://example.com/screenshot3.png', 202, 3
);

-- Map 3 (4EASY) completions - multiple users with close times for medal tests
INSERT INTO core.completions (
    map_id, user_id, time, verified, video, screenshot, verified_by, message_id
)
VALUES (
    3, 200, 10000, TRUE, NULL, 'https://example.com/screenshot_gold.png', 202, 4
), (
    3, 201, 10500, TRUE, NULL, 'https://example.com/screenshot_silver.png', 202, 5
);

-- =============================================================================
-- PENDING COMPLETIONS (for verification queue tests)
-- =============================================================================

INSERT INTO core.completions (
    map_id, user_id, time, verified, video, screenshot, message_id
)
VALUES (
    4, 201, 30000, FALSE, 'https://youtube.com/watch?v=abc123', 'https://example.com/screenshot4.png', 6
), (
    5, 200, 25000, FALSE, NULL, 'https://example.com/screenshot5.png', 7
);

-- =============================================================================
-- LEGACY COMPLETIONS (for legacy completion tests)
-- =============================================================================

INSERT INTO core.completions (
    map_id, user_id, time, verified, video, screenshot, verified_by, legacy, message_id
)
VALUES (
    6, 200, 50000, TRUE, NULL, 'https://example.com/legacy1.png', 202, TRUE, 8
), (
    6, 201, 55000, TRUE, NULL, 'https://example.com/legacy2.png', 202, TRUE, 9
);

-- =============================================================================
-- QUALITY VOTES (for quality rating tests)
-- =============================================================================

INSERT INTO maps.ratings (
    map_id, user_id, quality
)
VALUES (
    1, 200, 4
), (
    1, 201, 5
), (
    2, 200, 3
);

-- =============================================================================
-- XP DATA (for world record XP check tests)
-- =============================================================================

INSERT INTO lootbox.xp (
    user_id, amount
)
VALUES (
    200, 50000
), (
    201, 75000
);
