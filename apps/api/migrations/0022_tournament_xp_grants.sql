-- Migration 0022: Tournament XP grants ledger
-- Description: Creates tournaments.xp_grants, the double-grant ledger that makes
--              tournament reward grants idempotent against the Phase-7 outbox's
--              at-least-once re-delivery. api.xp.grant is in IGNORE_IDEMPOTENCY, so
--              the UNIQUE(cycle_id, user_id, reason) constraint here is the only real
--              double-grant guard: claim_xp_grant uses ON CONFLICT DO NOTHING so a
--              replayed finalization or outbox re-delivery cannot double-pay.
-- Date: 2026-05-30

BEGIN;

-- =============================================================================
-- tournaments.xp_grants (double-grant ledger)
-- =============================================================================

CREATE TABLE IF NOT EXISTS tournaments.xp_grants
(
    id         int         GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    cycle_id   int         NOT NULL REFERENCES tournaments.cycles(id) ON DELETE CASCADE,
    user_id    bigint      NOT NULL REFERENCES core.users(id) ON DELETE CASCADE,
    reason     text        NOT NULL CHECK (reason IN ('participation', 'placement', 'streak')),
    amount     int         NOT NULL,
    granted_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (cycle_id, user_id, reason)
);

CREATE INDEX IF NOT EXISTS idx_xp_grants_cycle ON tournaments.xp_grants (cycle_id);
CREATE INDEX IF NOT EXISTS idx_xp_grants_user ON tournaments.xp_grants (user_id);

COMMENT ON TABLE tournaments.xp_grants IS 'Idempotency ledger for tournament XP grants -- one row per (cycle, user, reason) guards against outbox at-least-once double-pay';
COMMENT ON COLUMN tournaments.xp_grants.cycle_id IS 'Cycle the grant belongs to';
COMMENT ON COLUMN tournaments.xp_grants.user_id IS 'Discord snowflake of the user receiving the grant (bigint)';
COMMENT ON COLUMN tournaments.xp_grants.reason IS 'Grant category: participation, placement, or streak';
COMMENT ON COLUMN tournaments.xp_grants.amount IS 'XP amount granted for this (cycle, user, reason) claim';

COMMIT;
