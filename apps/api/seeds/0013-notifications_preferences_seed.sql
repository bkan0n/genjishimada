-- Ensure notification preferences cover verification_approved for user 301

INSERT INTO notifications.preferences (user_id, event_type, channel, enabled)
VALUES
  (301, 'verification_approved', 'discord_dm', FALSE);
