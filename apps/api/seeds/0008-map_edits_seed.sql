-- Map edits seed data for testing map edit endpoints

-- =============================================================================
-- MAP EDIT TEST USERS
-- =============================================================================

INSERT INTO core.users (id, nickname, global_name, coins)
VALUES
  (500, 'MapEditUser', 'MapEditUser', 0),
  (501, 'MapEditResolver', 'MapEditResolver', 0);

-- =============================================================================
-- MAP EDIT REQUESTS
-- =============================================================================

-- Pending edit requests (accepted = NULL means pending)
INSERT INTO maps.edit_requests (id, map_id, code, proposed_changes, reason, created_by, accepted)
VALUES
  (1, 1, '1EASY', '{"description": "Updated description for the map"}', 'Better description needed', 500, NULL),
  (2, 2, '2EASY', '{"checkpoints": 15}', 'Checkpoint count was wrong', 500, NULL);

-- Approved edit request
INSERT INTO maps.edit_requests (id, map_id, code, proposed_changes, reason, created_by, accepted, resolved_by, resolved_at)
VALUES
  (3, 3, '4EASY', '{"difficulty": "Medium"}', 'Should be harder', 500, TRUE, 501, now());

-- Rejected edit request
INSERT INTO maps.edit_requests (id, map_id, code, proposed_changes, reason, created_by, accepted, resolved_by, resolved_at, rejection_reason)
VALUES
  (4, 4, '5EASY', '{"map_name": "Different Map"}', 'Wrong map name', 500, FALSE, 501, now(), 'Map name is correct');

-- Edit request with message ID set (for verification queue tests)
INSERT INTO maps.edit_requests (id, map_id, code, proposed_changes, reason, created_by, accepted, message_id)
VALUES
  (5, 5, '6EASY', '{"mechanics": ["Wallclimb"]}', 'Missing mechanic', 500, NULL, 4000000001);

-- =============================================================================
-- UPDATE SEQUENCE
-- =============================================================================

SELECT setval('maps.edit_requests_id_seq', 100);
