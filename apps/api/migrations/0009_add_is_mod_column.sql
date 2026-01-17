BEGIN;

-- Add is_mod column to core.users table
ALTER TABLE core.users
ADD COLUMN IF NOT EXISTS is_mod boolean DEFAULT FALSE NOT NULL;

COMMENT ON COLUMN core.users.is_mod IS 'Whether the user has moderator/admin permissions';

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_users_is_mod ON core.users (is_mod) WHERE is_mod = TRUE;

COMMIT;
