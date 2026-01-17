-- Auth seed data for testing authentication endpoints

-- =============================================================================
-- EMAIL AUTH USERS
-- =============================================================================

-- User 100 for verified email auth tests
INSERT INTO core.users (id, nickname, global_name, coins)
VALUES (100, 'EmailAuthUser', 'EmailAuthUser', 100);

-- Pre-hashed password: "TestPassword1!" using bcrypt (12 rounds)
INSERT INTO users.email_auth (user_id, email, password_hash, email_verified_at)
VALUES (100, 'verified@test.com', '$2b$12$d8udxkbBEIrxOdTlzBmUneqisBSWXfra3qUKkR9wfe4yJbuuNqbwi', now());

-- User 101 for unverified email auth tests
INSERT INTO core.users (id, nickname, global_name, coins)
VALUES (101, 'UnverifiedUser', 'UnverifiedUser', 0);

INSERT INTO users.email_auth (user_id, email, password_hash)
VALUES (101, 'unverified@test.com', '$2b$12$d8udxkbBEIrxOdTlzBmUneqisBSWXfra3qUKkR9wfe4yJbuuNqbwi');

-- =============================================================================
-- SESSION USERS
-- =============================================================================

-- User 102 for session tests (is_mod = true for mod check tests)
INSERT INTO core.users (id, nickname, global_name, coins, is_mod)
VALUES (102, 'SessionUser', 'SessionUser', 500, true);

INSERT INTO users.email_auth (user_id, email, password_hash, email_verified_at)
VALUES (102, 'session@test.com', '$2b$12$d8udxkbBEIrxOdTlzBmUneqisBSWXfra3qUKkR9wfe4yJbuuNqbwi', now());

-- User 103 for session tests (non-mod)
INSERT INTO core.users (id, nickname, global_name, coins, is_mod)
VALUES (103, 'SessionUserNonMod', 'SessionUserNonMod', 100, false);

-- =============================================================================
-- PRE-CREATED SESSIONS
-- =============================================================================

INSERT INTO users.sessions (id, user_id, payload, last_activity, ip_address, user_agent)
VALUES ('test-session-id-123', 102, 'eyJ0ZXN0IjoidmFsdWUifQ==', now(), '127.0.0.1', 'Test/1.0');

INSERT INTO users.sessions (id, user_id, payload, last_activity, ip_address, user_agent)
VALUES ('test-session-id-456', 102, 'eyJ0ZXN0IjoidmFsdWUyfQ==', now() - interval '1 hour', '127.0.0.2', 'Test/2.0');

INSERT INTO users.sessions (id, user_id, payload, last_activity, ip_address, user_agent)
VALUES ('test-session-id-789', 103, 'eyJ0ZXN0IjoidmFsdWUzfQ==', now(), '127.0.0.3', 'Test/3.0');
