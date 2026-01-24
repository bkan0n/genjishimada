-- Add missing creators for guide test maps

INSERT INTO maps.creators (
    user_id, map_id, is_primary
)
VALUES
    (53, 41, TRUE),
    (54, 41, FALSE),
    (54, 42, TRUE);
