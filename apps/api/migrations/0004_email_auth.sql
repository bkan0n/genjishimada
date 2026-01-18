BEGIN;

-- =============================================================================
-- 1. Email Authentication Credentials Table
-- =============================================================================
CREATE TABLE IF NOT EXISTS users.email_auth
(
    user_id           bigint PRIMARY KEY REFERENCES core.users (id) ON UPDATE CASCADE ON DELETE CASCADE,
    email             text NOT NULL,
    password_hash     text NOT NULL,
    email_verified_at timestamptz,
    created_at        timestamptz DEFAULT now(),
    updated_at        timestamptz DEFAULT now()
);

-- Case-insensitive unique index on email
CREATE UNIQUE INDEX IF NOT EXISTS idx_email_auth_email_lower ON users.email_auth (lower(email));

CREATE TRIGGER update_users_email_auth_updated_at
    BEFORE UPDATE
    ON users.email_auth
    FOR EACH ROW
EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE users.email_auth IS 'Email-based authentication credentials for website users';
COMMENT ON COLUMN users.email_auth.email IS 'User email address (stored as-is, uniqueness enforced case-insensitively)';
COMMENT ON COLUMN users.email_auth.password_hash IS 'Bcrypt hashed password';
COMMENT ON COLUMN users.email_auth.email_verified_at IS 'Timestamp when email was verified, NULL if unverified';

-- =============================================================================
-- 2. Email Tokens Table (Verification & Password Reset)
-- =============================================================================
CREATE TABLE IF NOT EXISTS users.email_tokens
(
    id         bigserial PRIMARY KEY,
    user_id    bigint      NOT NULL REFERENCES core.users (id) ON UPDATE CASCADE ON DELETE CASCADE,
    token_hash text        NOT NULL,
    token_type text        NOT NULL CHECK (token_type IN ('verification', 'password_reset')),
    expires_at timestamptz NOT NULL,
    used_at    timestamptz,
    created_at timestamptz DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_email_tokens_user_id ON users.email_tokens (user_id);
CREATE INDEX IF NOT EXISTS idx_email_tokens_expires ON users.email_tokens (expires_at) WHERE used_at IS NULL;

COMMENT ON TABLE users.email_tokens IS 'Tokens for email verification and password reset';
COMMENT ON COLUMN users.email_tokens.token_hash IS 'SHA256 hash of the token (plaintext sent to user via email)';
COMMENT ON COLUMN users.email_tokens.token_type IS 'Either verification or password_reset';
COMMENT ON COLUMN users.email_tokens.used_at IS 'Timestamp when token was consumed, NULL if unused';

-- =============================================================================
-- 3. ID Range Sequence for Email-Based Users
-- =============================================================================
-- Email users get IDs from 100,000,000 to 999,999,999,999,999 (9-15 digits)
CREATE SEQUENCE IF NOT EXISTS users.email_user_id_seq START WITH 100000000 INCREMENT BY 1 MINVALUE 100000000 MAXVALUE 999999999999999 NO CYCLE;

COMMENT ON SEQUENCE users.email_user_id_seq IS 'ID sequence for email-based users (9-15 digit range)';

-- =============================================================================
-- 4. Update Fake Member ID Range Constraint
-- =============================================================================
-- Fake members should now be constrained to IDs below 100,000,000 (8 digits max)
-- This is enforced at application level in create_fake_member method

-- =============================================================================
-- 5. Rate Limiting Table
-- =============================================================================
CREATE TABLE IF NOT EXISTS users.auth_rate_limits
(
    id         bigserial PRIMARY KEY,
    identifier text NOT NULL, -- email or IP address
    action     text NOT NULL, -- 'register', 'login', 'password_reset', 'verification_resend'
    attempt_at timestamptz DEFAULT now(),
    success    boolean     DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_auth_rate_limits_identifier_action ON users.auth_rate_limits (identifier, action, attempt_at DESC);

-- Cleanup old rate limit records (run periodically via cron/scheduler)
-- DELETE FROM users.auth_rate_limits WHERE attempt_at < now() - INTERVAL '24 hours';

COMMENT ON TABLE users.auth_rate_limits IS 'Tracks authentication attempts for rate limiting';


-- =============================================================================
-- 6. Sessions Table (for Laravel custom session driver via API)
-- =============================================================================
CREATE TABLE IF NOT EXISTS users.sessions
(
    id            text PRIMARY KEY,
    user_id       bigint REFERENCES core.users (id) ON UPDATE CASCADE ON DELETE CASCADE,
    payload       text        NOT NULL,
    last_activity timestamptz NOT NULL DEFAULT now(),
    ip_address    text,
    user_agent    text
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON users.sessions (user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_last_activity ON users.sessions (last_activity);

COMMENT ON TABLE users.sessions IS 'User sessions for Laravel website authentication';
COMMENT ON COLUMN users.sessions.id IS 'Session ID (Laravel generated)';
COMMENT ON COLUMN users.sessions.payload IS 'Base64-encoded session data';
COMMENT ON COLUMN users.sessions.last_activity IS 'Last activity timestamp for expiry';

COMMIT;