-- Improve error messages in speed enforcement trigger to detect pending verifications

CREATE OR REPLACE FUNCTION core.enforce_speed_rules_nonlegacy_only() RETURNS trigger
    LANGUAGE plpgsql AS
$$
DECLARE
    best_time          numeric;
    best_is_completion boolean;
    best_completed_at  timestamptz;
    map_code           text;
    is_pending         boolean;
BEGIN
    -- Any write that sets the row to legacy = TRUE is always allowed.
    IF new.legacy IS TRUE THEN RETURN new; END IF;

    -- Find the best non-legacy run for this user/map.
    SELECT c.time, c.completion, c.inserted_at, m.code
    INTO best_time, best_is_completion, best_completed_at, map_code
    FROM core.completions c
    JOIN core.maps m ON m.id = c.map_id
    WHERE c.user_id = new.user_id
      AND c.map_id = new.map_id
      AND c.legacy = FALSE
      AND c.verified IS FALSE
      AND c.verified_by IS NULL
      AND (tg_op <> 'UPDATE' OR c.id <> new.id)
    ORDER BY c.time
    LIMIT 1;

    -- No non-legacy rows yet -> nothing to enforce.
    IF best_time IS NULL THEN RETURN new; END IF;

    -- NEW is chronologically older -> skip checks.
    IF new.inserted_at IS NOT NULL AND new.inserted_at < best_completed_at THEN RETURN new; END IF;

    -- Check if we're comparing against a pending verification
    SELECT EXISTS (
        SELECT 1 FROM core.completions c
        WHERE c.user_id = new.user_id
          AND c.map_id = new.map_id
          AND c.time = best_time
          AND c.verified IS FALSE
          AND c.verified_by IS NULL
    ) INTO is_pending;

    -- Apply speed rules with better error messages for pending verifications
    IF new.completion IS TRUE THEN
        IF new.time >= best_time THEN
            IF is_pending THEN
                RAISE EXCEPTION 'You have a pending verification for map % with time %. New submission (%) must be faster or wait for verification.',
                    map_code, best_time, new.time
                USING ERRCODE = '23514';
            ELSE
                RAISE EXCEPTION 'completion=TRUE time % must be strictly faster than current best % (user %, map %, code %)',
                    new.time, best_time, new.user_id, new.map_id, map_code
                USING ERRCODE = '23514';
            END IF;
        END IF;

    ELSE
        IF best_is_completion IS FALSE AND new.time >= best_time THEN
            IF is_pending THEN
                RAISE EXCEPTION 'You have a pending verification for map % with time %. New submission (%) must be faster or wait for verification.',
                    map_code, best_time, new.time
                USING ERRCODE = '23514';
            ELSE
                RAISE EXCEPTION 'completion=FALSE time % must be strictly faster than current best non-completion % (user %, map %, code %)',
                    new.time, best_time, new.user_id, new.map_id, map_code
                USING ERRCODE = '23514';
            END IF;
        END IF;
    END IF;

    RETURN new;
END
$$;
