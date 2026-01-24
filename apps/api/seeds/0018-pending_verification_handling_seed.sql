-- Seed data for testing pending verification handling logic
-- Tests for duplicate submission prevention and faster time replacement

-- =============================================================================
-- TEST USERS FOR PENDING VERIFICATION
-- =============================================================================

-- Bot user for auto-rejecting replaced pending verifications
INSERT INTO core.users (
    id, nickname, global_name, coins
)
VALUES (
    969632729643753482, 'Genji Bot', 'Genji Bot', 0
);

INSERT INTO core.users (
    id, nickname, global_name, coins
)
VALUES (
    600, 'PendingUser1', 'PendingVerificationUser1', 100
), (
    601, 'PendingUser2', 'PendingVerificationUser2', 200
), (
    602, 'PendingUser3', 'PendingVerificationUser3', 300
);

-- Overwatch usernames for pending verification users
INSERT INTO users.overwatch_usernames (
    user_id, username, is_primary
)
VALUES (
    600, 'PendingPlayer#1111', TRUE
), (
    601, 'PendingPlayer#2222', TRUE
), (
    602, 'PendingPlayer#3333', TRUE
);

-- =============================================================================
-- TEST MAPS FOR PENDING VERIFICATION
-- =============================================================================
-- These maps are used specifically for pending verification tests
-- Maps 1-10 already exist in init seed, so we'll use existing maps

-- =============================================================================
-- PENDING COMPLETIONS (unverified, no verified_by)
-- =============================================================================

-- User 600: Has pending completion on map 6 (7EASY) with time 100.5
-- This will be used to test rejection of same/slower times
INSERT INTO core.completions (
    map_id, user_id, time, verified, verified_by, video, screenshot, verification_id
)
VALUES (
    6, 600, 100.5, FALSE, NULL, NULL, 'https://example.com/pending600_1.png', 9000000001
);

-- User 601: Has pending completion on map 7 (8EASY) with time 200.75
-- This will be used to test accepting faster time and message deletion
INSERT INTO core.completions (
    map_id, user_id, time, verified, verified_by, video, screenshot, verification_id
)
VALUES (
    7, 601, 200.75, FALSE, NULL, NULL, 'https://example.com/pending601_1.png', 9000000002
);

-- User 602: Has pending completion on map 8 (9EASY) with time 150.25, NO verification_id
-- This will be used to test accepting faster time when no verification message exists
INSERT INTO core.completions (
    map_id, user_id, time, verified, verified_by, video, screenshot, verification_id
)
VALUES (
    8, 602, 150.25, FALSE, NULL, NULL, 'https://example.com/pending602_1.png', NULL
);

-- User 600: Has ANOTHER pending completion on map 5 (6EASY) with time 300.5, with verification_id
-- This will be used for the verification_id presence test
INSERT INTO core.completions (
    map_id, user_id, time, verified, verified_by, video, screenshot, verification_id
)
VALUES (
    5, 600, 300.5, FALSE, NULL, NULL, 'https://example.com/pending600_2.png', 9000000003
);

-- =============================================================================
-- VERIFIED COMPLETIONS FOR COMPARISON
-- =============================================================================

-- User 600: Has verified completion on map 1 to ensure normal submissions still work
INSERT INTO core.completions (
    map_id, user_id, time, verified, verified_by, video, screenshot, message_id
)
VALUES (
    1, 600, 50000, TRUE, 202, NULL, 'https://example.com/verified600_1.png', 9000000100
);
