-- Migration: 0007_notification_system.sql
-- Description: Create notification system tables for platform-agnostic notifications

BEGIN;

CREATE SCHEMA IF NOT EXISTS notifications;

CREATE TABLE notifications.events
(
    id           bigserial PRIMARY KEY,
    user_id      bigint      NOT NULL REFERENCES core.users (id) ON DELETE CASCADE,
    event_type   text        NOT NULL,
    title        text        NOT NULL,
    body         text        NOT NULL,
    metadata     jsonb,
    created_at   timestamptz NOT NULL DEFAULT now(),
    read_at      timestamptz,
    dismissed_at timestamptz
);

CREATE INDEX idx_notifications_events_user_unread ON notifications.events (user_id, created_at DESC) WHERE read_at IS NULL;

CREATE INDEX idx_notifications_events_user_active ON notifications.events (user_id, created_at DESC) WHERE dismissed_at IS NULL;

COMMENT ON TABLE notifications.events IS 'Persistent storage for all user notifications';
COMMENT ON COLUMN notifications.events.event_type IS 'Type of notification event for filtering and preferences';
COMMENT ON COLUMN notifications.events.metadata IS 'JSON with event-specific data like map_code, completion_id, urls, etc.';
COMMENT ON COLUMN notifications.events.read_at IS 'When the notification was marked as read, NULL if unread';
COMMENT ON COLUMN notifications.events.dismissed_at IS 'When the notification was dismissed from the tray, NULL if active';

CREATE TABLE notifications.preferences
(
    user_id    bigint  NOT NULL REFERENCES core.users (id) ON DELETE CASCADE,
    event_type text    NOT NULL,
    channel    text    NOT NULL, -- 'discord_dm', 'discord_ping', 'web', 'email' (future)
    enabled    boolean NOT NULL DEFAULT TRUE,
    PRIMARY KEY (user_id, event_type, channel)
);

CREATE INDEX idx_notifications_preferences_user ON notifications.preferences (user_id);

COMMENT ON TABLE notifications.preferences IS 'Per-channel notification preferences for each event type';
COMMENT ON COLUMN notifications.preferences.channel IS 'Delivery channel: discord_dm, discord_ping, web, email (future)';

CREATE TABLE notifications.delivery_log
(
    id            bigserial PRIMARY KEY,
    event_id      bigint NOT NULL REFERENCES notifications.events (id) ON DELETE CASCADE,
    channel       text   NOT NULL,
    status        text   NOT NULL, -- 'pending', 'delivered', 'failed', 'skipped'
    attempted_at  timestamptz,
    delivered_at  timestamptz,
    error_message text,
    UNIQUE (event_id, channel)
);

CREATE INDEX idx_notifications_delivery_pending ON notifications.delivery_log (status, attempted_at) WHERE status = 'pending';

COMMENT ON TABLE notifications.delivery_log IS 'Track delivery status across channels for each notification';

INSERT INTO notifications.preferences (
    user_id, event_type, channel, enabled
)
SELECT
    ns.user_id,
    event_mapping.event_type,
    event_mapping.channel,
    (ns.flags & event_mapping.flag_value) > 0 AS enabled
FROM users.notification_settings ns
CROSS JOIN (
    VALUES (
        1, 'verification_approved', 'discord_dm'
    ),     -- DM_ON_VERIFICATION
        (
            2, 'skill_role_update', 'discord_dm'
        ), -- DM_ON_SKILL_ROLE_UPDATE
        (
            4, 'lootbox_earned', 'discord_dm'
        ), -- DM_ON_LOOTBOX_GAIN
        (
            8, 'record_removed', 'discord_dm'
        ), -- DM_ON_RECORDS_REMOVAL
        (
            16, 'playtest_update', 'discord_dm'
        ), -- DM_ON_PLAYTEST_ALERTS
        (
            32, 'xp_gain', 'discord_ping'
        ), -- PING_ON_XP_GAIN
        (
            64, 'mastery_earned', 'discord_ping'
        ), -- PING_ON_MASTERY
        (
            128, 'rank_up', 'discord_ping'
        ) -- PING_ON_COMMUNITY_RANK_UPDATE
) AS event_mapping(flag_value, event_type, channel)
ON CONFLICT DO NOTHING;

COMMIT;
