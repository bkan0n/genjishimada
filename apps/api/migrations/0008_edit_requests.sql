-- Migration: Create map_edit_requests table
CREATE TABLE maps.edit_requests
(
    id               serial PRIMARY KEY,
    map_id           int         NOT NULL REFERENCES core.maps (id) ON DELETE CASCADE,
    code             varchar(6)  NOT NULL, -- Denormalized for easy querying

    -- Proposed changes as JSONB
    -- Format: {"field_name": new_value, ...}
    -- Only contains fields that are being changed
    proposed_changes jsonb       NOT NULL,

    -- Request metadata  
    reason           text        NOT NULL,
    created_by       bigint      NOT NULL, -- User ID who submitted
    created_at       timestamptz NOT NULL DEFAULT now(),

    -- Verification queue message
    message_id       bigint,               -- Discord message ID in verification queue

    -- Resolution
    resolved_at      timestamptz,
    accepted         boolean,              -- NULL = pending, TRUE = approved, FALSE = rejected
    resolved_by      bigint,               -- Mod who resolved
    rejection_reason text,

    CONSTRAINT fk_created_by FOREIGN KEY (created_by) REFERENCES core.users (id),
    CONSTRAINT fk_resolved_by FOREIGN KEY (resolved_by) REFERENCES core.users (id)
);

-- Indexes for common queries
CREATE INDEX idx_map_edit_requests_pending ON maps.edit_requests (accepted) WHERE accepted IS NULL;

CREATE INDEX idx_map_edit_requests_code ON maps.edit_requests (code);

CREATE INDEX idx_map_edit_requests_created_by ON maps.edit_requests (created_by);

CREATE INDEX idx_map_edit_requests_message_id ON maps.edit_requests (message_id) WHERE message_id IS NOT NULL;