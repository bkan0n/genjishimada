-- Ensure minimum quality tests have verified ratings over the threshold

INSERT INTO maps.ratings (map_id, user_id, quality, verified)
VALUES
  (1, 100000000000000004, 5, TRUE),
  (3, 100000000000000005, 5, TRUE)
ON CONFLICT (map_id, user_id) DO UPDATE
SET quality = EXCLUDED.quality,
    verified = TRUE;
