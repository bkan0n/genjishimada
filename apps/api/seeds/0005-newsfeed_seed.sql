-- Newsfeed seed data for testing newsfeed endpoints

-- =============================================================================
-- NEWSFEED EVENTS
-- =============================================================================

-- Various event types for listing and filtering tests
INSERT INTO public.newsfeed (id, timestamp, payload)
OVERRIDING SYSTEM VALUE
VALUES
  (1, now() - interval '1 day', '{"type": "legacy_record", "code": "1EASY", "affected_count": 2, "reason": "Legacy cleanup"}'),
  (2, now() - interval '2 days', '{"type": "new_map", "code": "2EASY", "map_name": "Hanamura", "difficulty": "Easy", "creators": ["Creator1"], "official": true}'),
  (3, now() - interval '3 days', '{"type": "guide", "code": "3EASY", "guide_url": "https://youtube.com/watch?v=xyz", "name": "GuideMaker"}'),
  (4, now() - interval '4 days', '{"type": "record", "code": "1MEDIU", "map_name": "Hanamura", "time": 23456, "video": "https://youtube.com/watch?v=abc", "rank_num": 1, "name": "AnotherPlayer", "medal": "Gold", "difficulty": "Easy"}'),
  (5, now() - interval '5 days', '{"type": "archive", "code": "OLDMAP", "map_name": "Hanamura", "creators": ["OldCreator"], "difficulty": "Hard", "reason": "Broken"}');

-- =============================================================================
-- UPDATE SEQUENCE
-- =============================================================================

SELECT setval('public.newsfeed_id_seq', 100);
