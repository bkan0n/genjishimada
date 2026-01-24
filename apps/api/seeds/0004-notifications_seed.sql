-- Notifications seed data for testing notification endpoints

-- =============================================================================
-- NOTIFICATION TEST USERS
-- =============================================================================

INSERT INTO core.users (id, nickname, global_name, coins)
VALUES
  (300, 'NotificationUser1', 'NotificationUser1', 0),
  (301, 'NotificationUser2', 'NotificationUser2', 0),
  (302, 'NotificationUser3', 'NotificationUser3', 0),
  (303, 'NotificationUser4', 'NotificationUser4', 0);

-- =============================================================================
-- NOTIFICATION EVENTS (for event retrieval tests)
-- =============================================================================

-- User 300 has 3 notifications: 1 read, 2 unread
INSERT INTO notifications.events (id, user_id, event_type, title, body, metadata)
VALUES
  (1, 300, 'verification_approved', 'Completion Verified', 'Your completion on 1EASY was verified!', '{"map_code": "1EASY"}'),
  (2, 300, 'skill_role_update', 'Skill Role Updated', 'Your skill role changed to Gold!', '{"new_role": "Gold"}'),
  (3, 300, 'map_edit_approved', 'Map Edit Approved', 'Your map edit for 2EASY was approved!', '{"map_code": "2EASY"}');

-- Mark first notification as read
UPDATE notifications.events SET read_at = now() WHERE id = 1;

-- User 301 has 1 dismissed notification
INSERT INTO notifications.events (id, user_id, event_type, title, body, metadata, dismissed_at)
VALUES
  (4, 301, 'lootbox_earned', 'Lootbox Reward', 'You received a new skin!', '{"reward": "skin"}', now());

-- =============================================================================
-- NOTIFICATION PREFERENCES (for preference tests)
-- =============================================================================

-- User 301 has mixed preferences
INSERT INTO notifications.preferences (user_id, event_type, channel, enabled)
VALUES
  (301, 'completion_verified', 'discord_dm', TRUE),
  (301, 'completion_verified', 'web', TRUE),
  (301, 'skill_role_update', 'discord_dm', FALSE),
  (301, 'skill_role_update', 'web', TRUE),
  (301, 'map_edit_approved', 'discord_dm', TRUE),
  (301, 'map_edit_approved', 'web', FALSE);

-- User 302 has no preferences (defaults apply)

-- =============================================================================
-- UPDATE SEQUENCE
-- =============================================================================

SELECT setval('notifications.events_id_seq', 100);
