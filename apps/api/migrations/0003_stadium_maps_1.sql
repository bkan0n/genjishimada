-- Stadium maps batch 1.
--
-- These six names are now also seeded idempotently by the rewritten 0001_init.sql
-- maps.names block (D-08/D-09), so these inserts MUST be ON CONFLICT DO NOTHING or a
-- fresh from-migrations apply raises a duplicate-PK violation when 0003 replays the
-- names 0001 already inserted. (Latent non-idempotency bug surfaced by the seed rewrite.)
INSERT INTO maps.names (name)
VALUES
    ('Arena Victoriae'),
    ('Redwood Dam'),
    ('Thames District'),
    ('Gogadoro'),
    ('Powder Keg Mine'),
    ('Place Lacroix')
ON CONFLICT DO NOTHING;
