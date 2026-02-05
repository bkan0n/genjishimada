-- Migration 0015: Coin Store rotation history + replacement

-- Optional index for latest-rotation selection
CREATE INDEX IF NOT EXISTS idx_rotations_available_from
    ON store.rotations (available_from DESC);

-- Ensure only one active rotation remains (expire older actives)
WITH latest AS (
    SELECT rotation_id
    FROM store.rotations
    WHERE available_from <= now() AND available_until > now()
    GROUP BY rotation_id
    ORDER BY max(available_from) DESC
    LIMIT 1
)
UPDATE store.rotations
SET available_until = now()
WHERE available_until > now()
  AND rotation_id NOT IN (SELECT rotation_id FROM latest);

-- Replace generate_rotation to:
-- 1) expire active rotation
-- 2) keep history (no delete)
-- 3) exclude items from last two rotations
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
    v_temp_count int;
    v_recent_rotation_ids uuid[];
BEGIN
    v_rotation_id := gen_random_uuid();

    SELECT * INTO v_config FROM store.config WHERE id = 1;

    -- Expire any currently active rotation immediately
    UPDATE store.rotations
    SET available_until = now()
    WHERE store.rotations.available_from <= now() AND store.rotations.available_until > now();

    -- Collect the last two rotations for exclusion
    SELECT array_agg(r.rotation_id)
    INTO v_recent_rotation_ids
    FROM (
        SELECT store.rotations.rotation_id
        FROM store.rotations
        GROUP BY store.rotations.rotation_id
        ORDER BY max(store.rotations.available_from) DESC
        LIMIT 2
    ) r;

    v_recent_rotation_ids := COALESCE(v_recent_rotation_ids, ARRAY[]::uuid[]);

    v_available_until := now() + (v_config.rotation_period_days || ' days')::interval;

    v_legendary_count := 1;
    v_epic_count := (random() * 2)::int;
    IF v_epic_count = 0 THEN v_epic_count := 1; END IF;
    v_rare_count := p_item_count - v_legendary_count - v_epic_count;

    IF v_rare_count < 0 THEN
        RAISE EXCEPTION 'Insufficient item_count (%): need at least % items (1 legendary + % epic)',
            p_item_count, v_legendary_count + v_epic_count, v_epic_count;
    END IF;

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
          SELECT 1
          FROM store.rotations sr
          WHERE sr.rotation_id = ANY(v_recent_rotation_ids)
            AND sr.item_name = r.name
            AND sr.item_type = r.type
            AND sr.key_type = r.key_type
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
          SELECT 1
          FROM store.rotations sr
          WHERE sr.rotation_id = ANY(v_recent_rotation_ids)
            AND sr.item_name = r.name
            AND sr.item_type = r.type
            AND sr.key_type = r.key_type
      )
    ORDER BY random()
    LIMIT v_epic_count;

    GET DIAGNOSTICS v_temp_count = ROW_COUNT;
    v_items_generated := v_items_generated + v_temp_count;

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
          SELECT 1
          FROM store.rotations sr
          WHERE sr.rotation_id = ANY(v_recent_rotation_ids)
            AND sr.item_name = r.name
            AND sr.item_type = r.type
            AND sr.key_type = r.key_type
      )
    ORDER BY random()
    LIMIT v_rare_count;

    GET DIAGNOSTICS v_temp_count = ROW_COUNT;
    v_items_generated := v_items_generated + v_temp_count;

    UPDATE store.config
    SET last_rotation_at = now(),
        next_rotation_at = v_available_until
    WHERE id = 1;

    RETURN QUERY SELECT v_rotation_id, v_items_generated, v_available_until;
END;
$$;
