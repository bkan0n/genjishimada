-- Release map code: allow code reuse for archived maps
--
-- Drops NOT NULL on code columns so released maps can have code = NULL.
-- Adds original_code audit column to preserve the released code.

BEGIN;

-- Allow core.maps.code to be NULL (released maps)
ALTER TABLE core.maps ALTER COLUMN code DROP NOT NULL;

-- Audit column: preserves the map code after a release-code operation
ALTER TABLE core.maps ADD COLUMN original_code text;
COMMENT ON COLUMN core.maps.original_code IS 'Preserves the map code after a release-code operation. NULL for active maps.';

-- Allow change_requests.code to be NULL (cascaded from release via ON UPDATE CASCADE)
ALTER TABLE public.change_requests ALTER COLUMN code DROP NOT NULL;

-- Allow edit_requests.code to be NULL (cleared explicitly during release)
ALTER TABLE maps.edit_requests ALTER COLUMN code DROP NOT NULL;

COMMIT;
