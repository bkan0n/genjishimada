-- Migration 0013: Coin Store
-- Creates store schema, tables, and PL/pgSQL functions for rotation management

-- Create store schema
CREATE SCHEMA IF NOT EXISTS store;

-- Store configuration (singleton table)
CREATE TABLE store.config (
    id                    int GENERATED ALWAYS AS IDENTITY PRIMARY KEY CHECK (id = 1),
    rotation_period_days  int NOT NULL DEFAULT 7,
    last_rotation_at      timestamptz NOT NULL DEFAULT now(),
    next_rotation_at      timestamptz NOT NULL DEFAULT now() + interval '7 days',
    active_key_type       text NOT NULL DEFAULT 'Classic',

    CONSTRAINT fk_active_key_type FOREIGN KEY (active_key_type)
        REFERENCES lootbox.key_types(name) ON DELETE CASCADE
);

COMMENT ON TABLE store.config IS 'Store configuration (singleton)';
COMMENT ON COLUMN store.config.rotation_period_days IS 'How often the store rotates (days)';
COMMENT ON COLUMN store.config.active_key_type IS 'Current active key type (cheaper pricing)';

-- Current rotation items
CREATE TABLE store.rotations (
    id              int GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    rotation_id     uuid NOT NULL,
    item_name       text NOT NULL,
    item_type       text NOT NULL,
    key_type        text NOT NULL,
    rarity          text NOT NULL,
    price           int NOT NULL,
    available_from  timestamptz NOT NULL DEFAULT now(),
    available_until timestamptz NOT NULL,
    created_at      timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT fk_reward_item FOREIGN KEY (item_name, item_type, key_type)
        REFERENCES lootbox.reward_types(name, type, key_type) ON DELETE CASCADE,
    CONSTRAINT unique_rotation_item UNIQUE (rotation_id, item_name, item_type, key_type)
);

CREATE INDEX idx_rotations_active ON store.rotations (available_from, available_until);
CREATE INDEX idx_rotations_rotation_id ON store.rotations (rotation_id);

COMMENT ON TABLE store.rotations IS 'Current items available in rotating store';
COMMENT ON COLUMN store.rotations.rotation_id IS 'UUID grouping items in the same rotation period';

-- Purchase history (audit log)
CREATE TABLE store.purchases (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id        bigint NOT NULL,
    purchase_type  text NOT NULL CHECK (purchase_type IN ('key', 'item')),
    item_name      text,
    item_type      text,
    key_type       text NOT NULL,
    quantity       int NOT NULL DEFAULT 1,
    price_paid     int NOT NULL,
    rotation_id    uuid,
    purchased_at   timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES core.users(id) ON DELETE CASCADE
);

CREATE INDEX idx_purchases_user ON store.purchases (user_id, purchased_at DESC);
CREATE INDEX idx_purchases_rotation ON store.purchases (rotation_id);

COMMENT ON TABLE store.purchases IS 'Audit log of all store purchases';
COMMENT ON COLUMN store.purchases.purchase_type IS 'Either "key" or "item"';
COMMENT ON COLUMN store.purchases.quantity IS 'Number of keys purchased (1, 3, or 5)';

-- Function to generate a new store rotation
CREATE OR REPLACE FUNCTION store.generate_rotation(
    p_item_count int DEFAULT 5
)
RETURNS TABLE(
    rotation_id uuid,
    items_generated int,
    available_until timestamptz
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_rotation_id uuid;
    v_config record;
    v_available_until timestamptz;
    v_items_generated int := 0;
    v_legendary_count int;
    v_epic_count int;
    v_rare_count int;
BEGIN
    v_rotation_id := gen_random_uuid();

    SELECT * INTO v_config FROM store.config WHERE id = 1;

    v_available_until := now() + (v_config.rotation_period_days || ' days')::interval;

    DELETE FROM store.rotations WHERE store.rotations.available_until < now();

    v_legendary_count := 1;
    v_epic_count := (random() * 2)::int;
    IF v_epic_count = 0 THEN v_epic_count := 1; END IF;
    v_rare_count := p_item_count - v_legendary_count - v_epic_count;

    -- Legendary items
    INSERT INTO store.rotations (
        rotation_id, item_name, item_type, key_type, rarity,
        price, available_from, available_until
    )
    SELECT
        v_rotation_id,
        r.name,
        r.type,
        r.key_type,
        r.rarity,
        3000,
        now(),
        v_available_until
    FROM lootbox.reward_types r
    WHERE r.rarity = 'legendary'
      AND r.type != 'coins'
      AND NOT EXISTS (
          SELECT 1 FROM store.rotations sr
          WHERE sr.item_name = r.name
            AND sr.item_type = r.type
            AND sr.key_type = r.key_type
            AND sr.created_at > now() - (v_config.rotation_period_days * 2 || ' days')::interval
      )
    ORDER BY random()
    LIMIT v_legendary_count;

    GET DIAGNOSTICS v_items_generated = ROW_COUNT;

    -- Epic items
    INSERT INTO store.rotations (
        rotation_id, item_name, item_type, key_type, rarity,
        price, available_from, available_until
    )
    SELECT
        v_rotation_id,
        r.name,
        r.type,
        r.key_type,
        r.rarity,
        1500,
        now(),
        v_available_until
    FROM lootbox.reward_types r
    WHERE r.rarity = 'epic'
      AND r.type != 'coins'
      AND NOT EXISTS (
          SELECT 1 FROM store.rotations sr
          WHERE sr.item_name = r.name
            AND sr.item_type = r.type
            AND sr.key_type = r.key_type
            AND sr.created_at > now() - (v_config.rotation_period_days * 2 || ' days')::interval
      )
    ORDER BY random()
    LIMIT v_epic_count;

    v_items_generated := v_items_generated + ROW_COUNT;

    -- Rare items
    INSERT INTO store.rotations (
        rotation_id, item_name, item_type, key_type, rarity,
        price, available_from, available_until
    )
    SELECT
        v_rotation_id,
        r.name,
        r.type,
        r.key_type,
        r.rarity,
        750,
        now(),
        v_available_until
    FROM lootbox.reward_types r
    WHERE r.rarity = 'rare'
      AND r.type != 'coins'
      AND NOT EXISTS (
          SELECT 1 FROM store.rotations sr
          WHERE sr.item_name = r.name
            AND sr.item_type = r.type
            AND sr.key_type = r.key_type
            AND sr.created_at > now() - (v_config.rotation_period_days * 2 || ' days')::interval
      )
    ORDER BY random()
    LIMIT v_rare_count;

    v_items_generated := v_items_generated + ROW_COUNT;

    UPDATE store.config
    SET last_rotation_at = now(),
        next_rotation_at = v_available_until
    WHERE id = 1;

    RETURN QUERY SELECT v_rotation_id, v_items_generated, v_available_until;
END;
$$;

-- Automatic rotation checker (called by pg_cron)
CREATE OR REPLACE FUNCTION store.check_and_rotate()
RETURNS void
LANGUAGE plpgsql
AS $$
DECLARE
    v_config record;
    v_result record;
BEGIN
    SELECT * INTO v_config FROM store.config WHERE id = 1;

    IF now() >= v_config.next_rotation_at THEN
        SELECT * INTO v_result FROM store.generate_rotation();

        RAISE NOTICE 'Generated new rotation % with % items, expires %',
            v_result.rotation_id, v_result.items_generated, v_result.available_until;
    END IF;
END;
$$;

-- Initialize store config
INSERT INTO store.config (
    id, rotation_period_days, last_rotation_at, next_rotation_at, active_key_type
)
OVERRIDING SYSTEM VALUE
VALUES (
    1, 7, now(), now() + interval '7 days', 'Classic'
)
ON CONFLICT (id) DO NOTHING;

-- Generate initial rotation
SELECT * FROM store.generate_rotation();
