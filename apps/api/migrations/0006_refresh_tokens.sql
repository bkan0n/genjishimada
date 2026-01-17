CREATE TABLE users.remember_tokens
(
    id           uuid PRIMARY KEY     DEFAULT gen_random_uuid(),
    user_id      bigint      NOT NULL REFERENCES core.users (id) ON UPDATE CASCADE ON DELETE CASCADE,
    token_hash   varchar(64) NOT NULL,
    expires_at   timestamptz NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    last_used_at timestamptz,
    ip_address   inet,
    user_agent   text
);

CREATE INDEX idx_remember_tokens_user_id ON users.remember_tokens (user_id);
CREATE INDEX idx_remember_tokens_hash ON users.remember_tokens (token_hash);