-- Migration: Add content schema and movement technique tables
-- Description: Creates the content schema with movement_tech_categories,
--              movement_tech_difficulties, movement_techniques,
--              movement_tech_tips, and movement_tech_videos tables for the
--              Movement Techniques feature.
-- Date: 2026-03-29

BEGIN;

CREATE SCHEMA IF NOT EXISTS content;

CREATE TABLE IF NOT EXISTS content.movement_tech_categories
(
    id         int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name       text NOT NULL UNIQUE,
    sort_order int  NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS content.movement_tech_difficulties
(
    id         int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name       text NOT NULL UNIQUE,
    sort_order int  NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS content.movement_techniques
(
    id            int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name          text NOT NULL,
    description   text,
    instructions  text,
    display_order int  NOT NULL,
    category_id   int REFERENCES content.movement_tech_categories (id) ON DELETE SET NULL,
    difficulty_id int REFERENCES content.movement_tech_difficulties (id) ON DELETE SET NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS content.movement_tech_tips
(
    id           int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    technique_id int  NOT NULL REFERENCES content.movement_techniques (id) ON DELETE CASCADE,
    text         text NOT NULL,
    sort_order   int  NOT NULL
);

CREATE TABLE IF NOT EXISTS content.movement_tech_videos
(
    id           int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    technique_id int  NOT NULL REFERENCES content.movement_techniques (id) ON DELETE CASCADE,
    url          text NOT NULL,
    caption      text,
    sort_order   int  NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_movement_techniques_category_id ON content.movement_techniques (category_id);
CREATE INDEX IF NOT EXISTS idx_movement_techniques_difficulty_id ON content.movement_techniques (difficulty_id);
CREATE INDEX IF NOT EXISTS idx_movement_tech_tips_technique_id ON content.movement_tech_tips (technique_id);
CREATE INDEX IF NOT EXISTS idx_movement_tech_videos_technique_id ON content.movement_tech_videos (technique_id);

COMMIT;
