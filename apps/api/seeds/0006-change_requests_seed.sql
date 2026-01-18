-- Change requests seed data for testing change request endpoints

-- =============================================================================
-- CHANGE REQUEST TEST USERS
-- =============================================================================

INSERT INTO core.users (
    id, nickname, global_name, coins
)
VALUES (
    400, 'ChangeRequestUser', 'ChangeRequestUser', 0
), (
    401, 'ChangeRequestResolver', 'ChangeRequestResolver', 0
);

-- =============================================================================
-- CHANGE REQUESTS
-- =============================================================================

-- Open change requests (unresolved)
INSERT INTO public.change_requests (
    thread_id, code, user_id, content, change_request_type, creator_mentions, resolved
)
VALUES (
    1000000001, '1EASY', 400, 'Please update the difficulty', 'Difficulty Change', '<@100000000000000001>', FALSE
), (
    1000000002, '2EASY', 400, 'Map description needs updating', 'Map Edit Required', '<@100000000000000002>', FALSE
);

-- Resolved change request
INSERT INTO public.change_requests (
    thread_id, code, user_id, content, change_request_type, creator_mentions, resolved
)
VALUES (
    1000000003, '3EASY', 400, 'This was resolved', 'Other', '<@100000000000000001>', TRUE
);

-- Stale change request (older than 2 weeks, not alerted, not resolved)
INSERT INTO public.change_requests (
    thread_id, code, user_id, content, change_request_type, creator_mentions, resolved, created_at, alerted
)
VALUES (
    1000000004, '4EASY', 400, 'This is stale', 'Difficulty Change', '<@100000000000000001>', FALSE, now() - INTERVAL '20 days', FALSE
);

-- Already alerted change request (should not appear in stale list)
INSERT INTO public.change_requests (
    thread_id, code, user_id, content, change_request_type, creator_mentions, resolved, created_at, alerted
)
VALUES (
    1000000005,
    '5EASY',
    400,
    'This was alerted',
    'Map Edit Required',
    '<@100000000000000001>',
    FALSE,
    now() - INTERVAL '20 days',
    TRUE
);
