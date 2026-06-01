-- Migration: Add tournaments schema
-- Description: Creates the tournaments schema with config, categories, cycles,
--              completions, streaks, and pending_transitions tables.
--              Also adds tournament_completion_id FK column to core.completions.
-- Date: 2026-05-29

BEGIN;

-- Create tournaments schema
CREATE SCHEMA IF NOT EXISTS tournaments;

-- =============================================================================
-- tournaments.config (singleton)
-- =============================================================================

CREATE TABLE IF NOT EXISTS tournaments.config
(
    id              int         GENERATED ALWAYS AS IDENTITY PRIMARY KEY CHECK (id = 1),
    blacklist_weeks int         NOT NULL DEFAULT 4 CHECK (blacklist_weeks > 0),
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE tournaments.config IS 'Tournament global configuration (singleton)';
COMMENT ON COLUMN tournaments.config.blacklist_weeks IS 'Number of weeks a map is excluded after being used in any category';

-- =============================================================================
-- tournaments.categories
-- =============================================================================

CREATE TABLE IF NOT EXISTS tournaments.categories
(
    id               int         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name             text        NOT NULL UNIQUE,
    difficulties     text[]      NOT NULL,
    cycle_frequency  text        NOT NULL DEFAULT 'weekly'
                     CHECK (cycle_frequency IN ('weekly', 'biweekly')),
    participation_xp int         NOT NULL DEFAULT 0,
    placement_xp     jsonb       NOT NULL DEFAULT '[]'::jsonb,
    streak_xp        jsonb       NOT NULL DEFAULT '[]'::jsonb,
    champion_role_id bigint,
    is_active        boolean     NOT NULL DEFAULT TRUE,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE tournaments.categories IS 'Tournament difficulty categories with per-category XP config';
COMMENT ON COLUMN tournaments.categories.difficulties IS 'Array of DifficultyTop values this category includes';
COMMENT ON COLUMN tournaments.categories.cycle_frequency IS 'How often cycles rotate: weekly or biweekly';
COMMENT ON COLUMN tournaments.categories.participation_xp IS 'Flat XP bonus for first submission per cycle';
COMMENT ON COLUMN tournaments.categories.placement_xp IS 'JSON array of {place: N, xp: N} placement bonuses';
COMMENT ON COLUMN tournaments.categories.streak_xp IS 'JSON array of {threshold: N, xp: N} streak bonuses';
COMMENT ON COLUMN tournaments.categories.champion_role_id IS 'Discord role ID for category champion';

-- =============================================================================
-- tournaments.cycles
-- =============================================================================

CREATE TABLE IF NOT EXISTS tournaments.cycles
(
    id          int         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    category_id int         NOT NULL REFERENCES tournaments.categories(id) ON DELETE CASCADE,
    map_id      int         NOT NULL REFERENCES core.maps(id) ON DELETE RESTRICT,
    status      text        NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'active', 'finalizing', 'completed')),
    started_at  timestamptz,
    ended_at    timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cycles_category_id ON tournaments.cycles (category_id);
CREATE INDEX IF NOT EXISTS idx_cycles_map_id ON tournaments.cycles (map_id);
CREATE INDEX IF NOT EXISTS idx_cycles_status ON tournaments.cycles (status);
CREATE INDEX IF NOT EXISTS idx_cycles_category_status ON tournaments.cycles (category_id, status);
CREATE INDEX IF NOT EXISTS idx_cycles_started_at ON tournaments.cycles (started_at);

COMMENT ON TABLE tournaments.cycles IS 'Tournament cycles -- one per category per rotation period';
COMMENT ON COLUMN tournaments.cycles.status IS 'Lifecycle: pending -> active -> finalizing -> completed';
COMMENT ON COLUMN tournaments.cycles.started_at IS 'When cycle became active (NULL while pending)';
COMMENT ON COLUMN tournaments.cycles.ended_at IS 'When cycle was finalized (NULL while active)';

-- =============================================================================
-- tournaments.completions
-- =============================================================================

CREATE TABLE IF NOT EXISTS tournaments.completions
(
    id          int            GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cycle_id    int            NOT NULL REFERENCES tournaments.cycles(id) ON DELETE CASCADE,
    user_id     bigint         NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    map_id      int            NOT NULL REFERENCES core.maps(id) ON DELETE CASCADE,
    time        numeric(10, 2) NOT NULL,
    screenshot  text           NOT NULL,
    video       text,
    verified    boolean        NOT NULL DEFAULT FALSE,
    completion  boolean        NOT NULL DEFAULT FALSE,
    inserted_at timestamptz    NOT NULL DEFAULT now(),
    UNIQUE (cycle_id, user_id, inserted_at)
);

CREATE INDEX IF NOT EXISTS idx_tournament_completions_cycle_id ON tournaments.completions (cycle_id);
CREATE INDEX IF NOT EXISTS idx_tournament_completions_user_id ON tournaments.completions (user_id);
CREATE INDEX IF NOT EXISTS idx_tournament_completions_map_id ON tournaments.completions (map_id);
CREATE INDEX IF NOT EXISTS idx_tournament_completions_cycle_user ON tournaments.completions (cycle_id, user_id);
-- Leaderboard query index: tier-then-time ranking per D-02
CREATE INDEX IF NOT EXISTS idx_tournament_completions_ranking
    ON tournaments.completions (cycle_id, verified DESC, time ASC);

COMMENT ON TABLE tournaments.completions IS 'Tournament-specific completion records, separate from core.completions';
COMMENT ON COLUMN tournaments.completions.verified IS 'Whether the completion has been verified (affects ranking tier)';
COMMENT ON COLUMN tournaments.completions.video IS 'URL to uploaded video (does not affect ranking per D-02)';
COMMENT ON COLUMN tournaments.completions.completion IS 'Whether submission counts as a full completion';

-- =============================================================================
-- tournaments.streaks
-- =============================================================================

CREATE TABLE IF NOT EXISTS tournaments.streaks
(
    id             int         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id        bigint      NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    current_streak int         NOT NULL DEFAULT 0,
    max_streak     int         NOT NULL DEFAULT 0,
    last_cycle_id  int         REFERENCES tournaments.cycles(id) ON DELETE SET NULL,
    updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_streaks_user_id ON tournaments.streaks (user_id);

COMMENT ON TABLE tournaments.streaks IS 'Per-user weekly participation streak tracking';
COMMENT ON COLUMN tournaments.streaks.current_streak IS 'Consecutive cycles with at least one submission';
COMMENT ON COLUMN tournaments.streaks.max_streak IS 'Highest streak ever achieved';
COMMENT ON COLUMN tournaments.streaks.last_cycle_id IS 'Last cycle the user participated in';

-- =============================================================================
-- tournaments.pending_transitions
-- =============================================================================

CREATE TABLE IF NOT EXISTS tournaments.pending_transitions
(
    id         int         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cycle_id   int         NOT NULL REFERENCES tournaments.cycles(id) ON DELETE CASCADE,
    event_type text        NOT NULL CHECK (event_type IN ('cycle_started', 'cycle_completed')),
    payload    jsonb       NOT NULL DEFAULT '{}'::jsonb,
    published  boolean     NOT NULL DEFAULT FALSE,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_pending_transitions_unpublished
    ON tournaments.pending_transitions (published, created_at)
    WHERE published = FALSE;
CREATE INDEX IF NOT EXISTS idx_pending_transitions_cycle_id ON tournaments.pending_transitions (cycle_id);

COMMENT ON TABLE tournaments.pending_transitions IS 'Outbox table for cycle transition events to be published to RabbitMQ';
COMMENT ON COLUMN tournaments.pending_transitions.published IS 'Whether this event has been picked up and published to RabbitMQ';

-- =============================================================================
-- Singleton config initialization
-- =============================================================================

INSERT INTO tournaments.config (id, blacklist_weeks)
OVERRIDING SYSTEM VALUE
VALUES (1, 4)
ON CONFLICT (id) DO NOTHING;

-- =============================================================================
-- ALTER TABLE core.completions (per D-09)
-- =============================================================================

ALTER TABLE core.completions
    ADD COLUMN IF NOT EXISTS tournament_completion_id int
    REFERENCES tournaments.completions(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_completions_tournament_completion_id
    ON core.completions (tournament_completion_id)
    WHERE tournament_completion_id IS NOT NULL;

COMMENT ON COLUMN core.completions.tournament_completion_id IS 'Link to tournament completion that produced this record (NULL for non-tournament submissions)';

COMMIT;
