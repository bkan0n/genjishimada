-- Fix: allow changing a map's code while it has a linked_code.
--
-- The trigger trg_sync_linked_code fires BEFORE UPDATE OF linked_code, code.
-- Its body only handles link/unlink semantics (changes to linked_code), but it
-- also ran for plain `code` renames. On a rename, `linked_code` is unchanged and
-- still non-null, so the function fell through to its "create link" branch and
-- read the partner's back-pointer -- which still referenced the OLD code. The
-- guard `target_current <> new.code` then raised
--   "Code X is already linked to Y, cannot also link to Z"
-- aborting the rename before the FK ON UPDATE CASCADE could fix the partner.
--
-- Fix: early-return for a pure code rename (an UPDATE where linked_code is
-- unchanged). In that case the FK ON UPDATE CASCADE on core.maps.linked_code
-- already keeps the partner's back-pointer in sync, so the link-sync logic must
-- not run. Link/unlink behaviour (changes to linked_code) and INSERTs are
-- unchanged.

BEGIN;

CREATE OR REPLACE FUNCTION core.sync_linked_code() RETURNS trigger
    LANGUAGE plpgsql AS
$$
DECLARE
    target_current text;
BEGIN
    -- Avoid infinite ping-pong when we update the counterpart.
    IF pg_trigger_depth() > 1 THEN RETURN new; END IF;

    -- Pure code rename: linked_code is unchanged on this UPDATE. The FK
    -- ON UPDATE CASCADE already updates the partner's linked_code, so the
    -- link-sync logic below must not run (it would misread the partner's
    -- pre-cascade back-pointer and wrongly reject the rename).
    IF TG_OP = 'UPDATE' AND new.linked_code IS NOT DISTINCT FROM old.linked_code THEN
        RETURN new;
    END IF;

    -- If unlinking (linked_code becomes NULL), clear the counterpart if it points back
    IF new.linked_code IS NULL THEN
        IF old.linked_code IS NOT NULL THEN
            UPDATE core.maps
            SET linked_code = NULL
            WHERE code = old.linked_code AND linked_code = old.code; -- only clear if it points back to us
        END IF;
        RETURN new;
    END IF;

    -- At this point NEW.linked_code is NOT NULL
    IF new.linked_code = new.code THEN RAISE EXCEPTION 'linked_code cannot equal code (%).', new.code; END IF;

    -- Ensure target exists
    PERFORM 1
    FROM core.maps
    WHERE code = new.linked_code;
    IF NOT found THEN RAISE EXCEPTION 'linked_code % does not reference an existing code.', new.linked_code; END IF;

    -- Check the target's current link
    SELECT linked_code
    INTO target_current
    FROM core.maps
    WHERE code = new.linked_code FOR UPDATE;
    -- serialize against concurrent writers on the target

    -- If target already linked to someone else (not us), forbid
    IF target_current IS NOT NULL AND target_current <> new.code THEN
        RAISE EXCEPTION 'Code % is already linked to %, cannot also link to %.', new.linked_code, target_current, new.code;
    END IF;

    -- If target not linked yet, link it back to us
    IF target_current IS NULL THEN
        UPDATE core.maps
        SET linked_code = new.code
        WHERE code = new.linked_code AND linked_code IS NULL; -- idempotent
    END IF;

    RETURN new;
END
$$;

COMMIT;
