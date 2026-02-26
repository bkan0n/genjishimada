-- Migration: 0014_quests_system.sql
-- Description: Add quest system tables, indexes, and PL/pgSQL functions
-- Date: 2026-02-04
-- Requirements:
-- - pg_cron extension enabled (CREATE EXTENSION IF NOT EXISTS pg_cron)

BEGIN;

-- store.quests - Global quest templates for random selection
CREATE TABLE store.quests (
    id              int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name            text NOT NULL,
    description     text NOT NULL,
    quest_type      text NOT NULL CHECK (quest_type IN ('global', 'bounty')),
    difficulty      text NOT NULL CHECK (difficulty IN ('easy', 'medium', 'hard')),
    coin_reward     int NOT NULL,
    xp_reward       int NOT NULL,
    requirements    jsonb NOT NULL,
    is_active       boolean DEFAULT true,
    created_at      timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX idx_quests_active ON store.quests (is_active, quest_type, difficulty);

-- store.quest_rotation - Active quests for current rotation
CREATE TABLE store.quest_rotation (
    id              int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    rotation_id     uuid NOT NULL,
    quest_id        int,  -- NULL for personalized bounties
    user_id         bigint,  -- NULL for global quests
    quest_data      jsonb NOT NULL,
    available_from  timestamptz NOT NULL DEFAULT now(),
    available_until timestamptz NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT fk_quest FOREIGN KEY (quest_id) REFERENCES store.quests(id) ON DELETE CASCADE,
    CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES core.users(id) ON DELETE CASCADE,
    CONSTRAINT check_quest_or_user CHECK (
        (quest_id IS NOT NULL AND user_id IS NULL) OR
        (quest_id IS NULL AND user_id IS NOT NULL)
    )
);

CREATE INDEX idx_quest_rotation_active ON store.quest_rotation (rotation_id, available_until);
CREATE INDEX idx_quest_rotation_user ON store.quest_rotation (user_id, available_until);
CREATE INDEX idx_quest_rotation_global ON store.quest_rotation (rotation_id) WHERE user_id IS NULL;

-- Idempotency: prevent duplicate globals or bounties per rotation
CREATE UNIQUE INDEX uq_quest_rotation_global
    ON store.quest_rotation (rotation_id, quest_id)
    WHERE user_id IS NULL;

CREATE UNIQUE INDEX uq_quest_rotation_bounty
    ON store.quest_rotation (rotation_id, user_id)
    WHERE quest_id IS NULL;

-- store.user_quest_progress - Track user progress on quests
CREATE TABLE store.user_quest_progress (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id         bigint NOT NULL,
    rotation_id     uuid NOT NULL,
    quest_id        int,  -- NULL for personalized bounties
    quest_data      jsonb NOT NULL,
    progress        jsonb NOT NULL,
    completed_at    timestamptz,
    claimed_at      timestamptz,
    coins_rewarded  int,
    xp_rewarded     int,
    created_at      timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES core.users(id) ON DELETE CASCADE,
    CONSTRAINT fk_quest FOREIGN KEY (quest_id) REFERENCES store.quests(id) ON DELETE SET NULL
);

CREATE INDEX idx_user_quest_progress_user ON store.user_quest_progress (user_id, completed_at);
CREATE INDEX idx_user_quest_progress_rotation ON store.user_quest_progress (rotation_id);
CREATE INDEX idx_user_quest_progress_unclaimed ON store.user_quest_progress (user_id, completed_at)
    WHERE completed_at IS NOT NULL AND claimed_at IS NULL;

-- One progress row per global quest per user per rotation
CREATE UNIQUE INDEX uq_user_quest_progress_global
    ON store.user_quest_progress (user_id, rotation_id, quest_id)
    WHERE quest_id IS NOT NULL;

-- Exactly one personalized bounty per user per rotation
CREATE UNIQUE INDEX uq_user_quest_progress_bounty
    ON store.user_quest_progress (user_id, rotation_id)
    WHERE quest_id IS NULL;

-- store.quest_config - Singleton configuration table
CREATE TABLE store.quest_config (
    id                      int GENERATED ALWAYS AS IDENTITY PRIMARY KEY CHECK (id = 1),
    rotation_day            int NOT NULL DEFAULT 1 CHECK (rotation_day BETWEEN 1 AND 7),
    rotation_hour           int NOT NULL DEFAULT 0 CHECK (rotation_hour BETWEEN 0 AND 23),
    current_rotation_id     uuid,
    last_rotation_at        timestamptz NOT NULL DEFAULT now(),
    next_rotation_at        timestamptz NOT NULL,
    easy_quest_count        int NOT NULL DEFAULT 2,
    medium_quest_count      int NOT NULL DEFAULT 2,
    hard_quest_count        int NOT NULL DEFAULT 1
);

-- Initialize quest config (Monday 00:00 UTC)
INSERT INTO store.quest_config (
    rotation_day,
    rotation_hour,
    current_rotation_id,
    last_rotation_at,
    next_rotation_at,
    easy_quest_count,
    medium_quest_count,
    hard_quest_count
) VALUES (
    1,
    0,
    NULL,
    now(),
    -- Compute next Monday 00:00 UTC
    date_trunc('week', now()) + interval '7 days',
    2,
    2,
    1
);

-- Easy quests (100 coins, 15 XP)
INSERT INTO store.quests (name, description, quest_type, difficulty, coin_reward, xp_reward, requirements) VALUES
('Warm-Up Round', 'Complete 6 maps this week', 'global', 'easy', 100, 15,
 '{"type": "complete_maps", "count": 6, "difficulty": "any"}'::jsonb),

('Beginner''s Journey', 'Complete 4 Easy difficulty maps', 'global', 'easy', 100, 15,
 '{"type": "complete_maps", "count": 4, "difficulty": "easy"}'::jsonb),

('Medium Mastery', 'Complete 3 Medium difficulty maps', 'global', 'easy', 100, 15,
 '{"type": "complete_maps", "count": 3, "difficulty": "medium"}'::jsonb),

('Classic Explorer', 'Complete 3 Classic category maps', 'global', 'easy', 100, 15,
 '{"type": "complete_maps", "count": 3, "category": "Classic"}'::jsonb),

('Progressive Steps', 'Complete 3 Increasing Difficulty category maps', 'global', 'easy', 100, 15,
 '{"type": "complete_maps", "count": 3, "category": "Increasing Difficulty"}'::jsonb),

('Steady Stride', 'Complete 7 maps this week', 'global', 'easy', 100, 15,
 '{"type": "complete_maps", "count": 7, "difficulty": "any"}'::jsonb);

-- Medium quests (250 coins, 35 XP)
INSERT INTO store.quests (name, description, quest_type, difficulty, coin_reward, xp_reward, requirements) VALUES
('Map Marathon', 'Complete 14 maps this week', 'global', 'medium', 250, 35,
 '{"type": "complete_maps", "count": 14, "difficulty": "any"}'::jsonb),

('Rising Consistency', 'Complete 12 maps this week', 'global', 'medium', 250, 35,
 '{"type": "complete_maps", "count": 12, "difficulty": "any"}'::jsonb),

('Hard Mode', 'Complete 3 Hard difficulty maps', 'global', 'medium', 250, 35,
 '{"type": "complete_maps", "count": 3, "difficulty": "hard"}'::jsonb),

('Very Hard Venture', 'Complete 2 Very Hard difficulty maps', 'global', 'medium', 250, 35,
 '{"type": "complete_maps", "count": 2, "difficulty": "very hard"}'::jsonb),

('Extreme Trial', 'Complete 1 Extreme difficulty map', 'global', 'medium', 250, 35,
 '{"type": "complete_maps", "count": 1, "difficulty": "extreme"}'::jsonb),

('Classic Circuit', 'Complete 5 Classic category maps', 'global', 'medium', 250, 35,
 '{"type": "complete_maps", "count": 5, "category": "Classic"}'::jsonb);

-- Hard quests (500 coins, 75 XP)
INSERT INTO store.quests (name, description, quest_type, difficulty, coin_reward, xp_reward, requirements) VALUES
('Ultra Marathon', 'Complete 20 maps this week', 'global', 'hard', 500, 75,
 '{"type": "complete_maps", "count": 20, "difficulty": "any"}'::jsonb),

('Iron Rhythm', 'Complete 18 maps this week', 'global', 'hard', 500, 75,
 '{"type": "complete_maps", "count": 18, "difficulty": "any"}'::jsonb),

('Hard Specialist', 'Complete 6 Hard difficulty maps', 'global', 'hard', 500, 75,
 '{"type": "complete_maps", "count": 6, "difficulty": "hard"}'::jsonb),

('Very Hard Gauntlet', 'Complete 4 Very Hard difficulty maps', 'global', 'hard', 500, 75,
 '{"type": "complete_maps", "count": 4, "difficulty": "very hard"}'::jsonb),

('Extreme Push', 'Complete 2 Extreme difficulty maps', 'global', 'hard', 500, 75,
 '{"type": "complete_maps", "count": 2, "difficulty": "extreme"}'::jsonb),

('Hell Breaker', 'Complete 1 Hell difficulty map', 'global', 'hard', 500, 75,
 '{"type": "complete_maps", "count": 1, "difficulty": "hell"}'::jsonb),

('Endurance Range', 'Complete 8 maps in the Hard difficulty range', 'global', 'hard', 500, 75,
 '{"type": "complete_difficulty_range", "difficulty": "hard", "min_count": 8}'::jsonb);

-- Auto-claim completed unclaimed quests at rotation
CREATE OR REPLACE FUNCTION store.auto_claim_completed_quests()
RETURNS TABLE (claimed_count int, total_coins int, total_xp int) AS $$
DECLARE
    v_now timestamptz := now();
BEGIN
    RETURN QUERY
    WITH claimed AS (
        UPDATE store.user_quest_progress
        SET claimed_at = v_now,
            coins_rewarded = (quest_data->>'coin_reward')::int,
            xp_rewarded = (quest_data->>'xp_reward')::int
        WHERE completed_at IS NOT NULL
          AND claimed_at IS NULL
        RETURNING user_id, coins_rewarded, xp_rewarded
    ),
    coin_totals AS (
        SELECT user_id, SUM(coins_rewarded) AS coins
        FROM claimed
        GROUP BY user_id
    ),
    xp_totals AS (
        SELECT user_id, SUM(xp_rewarded) AS xp
        FROM claimed
        GROUP BY user_id
    ),
    updated_users AS (
        UPDATE core.users u
        SET coins = u.coins + ct.coins
        FROM coin_totals ct
        WHERE u.id = ct.user_id
        RETURNING u.id
    ),
    inserted_xp AS (
        INSERT INTO lootbox.xp (user_id, amount)
        SELECT user_id, xp
        FROM xp_totals
        ON CONFLICT (user_id) DO UPDATE
            SET amount = lootbox.xp.amount + EXCLUDED.amount
        RETURNING user_id
    )
    SELECT
        COUNT(*)::int AS claimed_count,
        COALESCE(SUM(coins_rewarded), 0)::int AS total_coins,
        COALESCE(SUM(xp_rewarded), 0)::int AS total_xp
    FROM claimed;
END;
$$ LANGUAGE plpgsql;

-- Select random global quests for a rotation
CREATE OR REPLACE FUNCTION store.select_global_quests(
    p_rotation_id uuid,
    p_available_from timestamptz,
    p_available_until timestamptz,
    p_easy_count int,
    p_medium_count int,
    p_hard_count int
)
RETURNS void AS $$
BEGIN
    INSERT INTO store.quest_rotation (rotation_id, quest_id, quest_data, available_from, available_until)
    SELECT
        p_rotation_id,
        q.id,
        jsonb_build_object(
            'name', q.name,
            'description', q.description,
            'difficulty', q.difficulty,
            'coin_reward', q.coin_reward,
            'xp_reward', q.xp_reward,
            'requirements', q.requirements
        ),
        p_available_from,
        p_available_until
    FROM store.quests q
    WHERE q.is_active = true
      AND q.quest_type = 'global'
      AND q.difficulty = 'easy'
    ORDER BY random()
    LIMIT p_easy_count
    ON CONFLICT DO NOTHING;

    INSERT INTO store.quest_rotation (rotation_id, quest_id, quest_data, available_from, available_until)
    SELECT
        p_rotation_id,
        q.id,
        jsonb_build_object(
            'name', q.name,
            'description', q.description,
            'difficulty', q.difficulty,
            'coin_reward', q.coin_reward,
            'xp_reward', q.xp_reward,
            'requirements', q.requirements
        ),
        p_available_from,
        p_available_until
    FROM store.quests q
    WHERE q.is_active = true
      AND q.quest_type = 'global'
      AND q.difficulty = 'medium'
    ORDER BY random()
    LIMIT p_medium_count
    ON CONFLICT DO NOTHING;

    INSERT INTO store.quest_rotation (rotation_id, quest_id, quest_data, available_from, available_until)
    SELECT
        p_rotation_id,
        q.id,
        jsonb_build_object(
            'name', q.name,
            'description', q.description,
            'difficulty', q.difficulty,
            'coin_reward', q.coin_reward,
            'xp_reward', q.xp_reward,
            'requirements', q.requirements
        ),
        p_available_from,
        p_available_until
    FROM store.quests q
    WHERE q.is_active = true
      AND q.quest_type = 'global'
      AND q.difficulty = 'hard'
    ORDER BY random()
    LIMIT p_hard_count
    ON CONFLICT DO NOTHING;
END;
$$ LANGUAGE plpgsql;

-- Insert "new quests available" notifications for all users
CREATE OR REPLACE FUNCTION store.insert_rotation_notifications(
    p_rotation_id uuid
)
RETURNS int AS $$
DECLARE
    v_count int;
BEGIN
    INSERT INTO notifications.events (user_id, event_type, title, body, metadata)
    SELECT
        u.id,
        'quest_rotation',
        'New Weekly Quests',
        'Your new weekly quests are available now.',
        jsonb_build_object('rotation_id', p_rotation_id)
    FROM core.users u
    ON CONFLICT DO NOTHING;

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

-- Generate a new rotation (cleanup old quest_rotation rows)
CREATE OR REPLACE FUNCTION store.generate_quest_rotation(
    p_rotation_id uuid,
    p_rotation_start timestamptz,
    p_rotation_end timestamptz,
    p_easy_count int,
    p_medium_count int,
    p_hard_count int
)
RETURNS void AS $$
BEGIN
    -- Remove old active rotation rows
    DELETE FROM store.quest_rotation
    WHERE available_until <= p_rotation_start;

    -- Insert new global quests
    PERFORM store.select_global_quests(
        p_rotation_id,
        p_rotation_start,
        p_rotation_end,
        p_easy_count,
        p_medium_count,
        p_hard_count
    );

    -- Insert rotation notifications
    PERFORM store.insert_rotation_notifications(p_rotation_id);
END;
$$ LANGUAGE plpgsql;

-- Check if rotation needed and generate if so
CREATE OR REPLACE FUNCTION store.check_and_generate_quest_rotation()
RETURNS TABLE (
    rotation_id uuid,
    generated boolean,
    auto_claimed int,
    global_quests_generated int
) AS $$
DECLARE
    v_config RECORD;
    v_rotation_id uuid;
    v_rotation_start timestamptz;
    v_rotation_end timestamptz;
    v_claimed int;
BEGIN
    -- Lock config row to prevent concurrent rotations
    SELECT * INTO v_config
    FROM store.quest_config
    WHERE id = 1
    FOR UPDATE;

    -- Generate rotation if missing or due
    IF v_config.current_rotation_id IS NULL OR now() >= v_config.next_rotation_at THEN
        v_rotation_start := COALESCE(v_config.next_rotation_at, now());
        v_rotation_end := v_rotation_start + interval '7 days';
        v_rotation_id := gen_random_uuid();

        -- Auto-claim unclaimed completed quests
        SELECT claimed_count INTO v_claimed FROM store.auto_claim_completed_quests();

        -- Generate new rotation
        PERFORM store.generate_quest_rotation(
            v_rotation_id,
            v_rotation_start,
            v_rotation_end,
            v_config.easy_quest_count,
            v_config.medium_quest_count,
            v_config.hard_quest_count
        );

        -- Update config timestamps (strict weekly schedule)
        UPDATE store.quest_config
        SET last_rotation_at = v_rotation_start,
            next_rotation_at = v_rotation_start + interval '7 days',
            current_rotation_id = v_rotation_id
        WHERE id = 1;

        RETURN QUERY
        SELECT
            v_rotation_id,
            TRUE,
            COALESCE(v_claimed, 0),
            (SELECT COUNT(*)::int FROM store.quest_rotation qr WHERE qr.rotation_id = v_rotation_id AND qr.user_id IS NULL);
        RETURN;
    END IF;

    RETURN QUERY
    SELECT v_config.current_rotation_id, FALSE, 0,
           (SELECT COUNT(*)::int FROM store.quest_rotation qr WHERE qr.rotation_id = v_config.current_rotation_id AND qr.user_id IS NULL);
END;
$$ LANGUAGE plpgsql;

-- Prevent duplicate rotation notifications per user per rotation
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_indexes
        WHERE indexname = 'uq_notifications_quest_rotation'
    ) THEN
        CREATE UNIQUE INDEX uq_notifications_quest_rotation
            ON notifications.events (user_id, event_type, (metadata->>'rotation_id'))
            WHERE event_type = 'quest_rotation';
    END IF;
END$$;

-- Schedule quest rotation check (runs every hour at minute 0)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'cron') THEN
        PERFORM cron.schedule(
            'quest-rotation-check',
            '0 * * * *',
            $cron$SELECT store.check_and_generate_quest_rotation()$cron$
        );
    END IF;
END$$;

COMMIT;
