"""Integration tests for dynamic map management schema (migrations 0001 + 0032).

Verifies the phase-15 durability/integrity work against the migrated test DB:
  * test_phantom_maps    (REQ-13): the 7 phantom Literal-only maps are reconciled
                                    into maps.names (all 70 names present).
  * test_seed_idempotent (REQ-12): re-applying the 0001 ON CONFLICT seed block
                                    raises no duplicate-PK error and the row count
                                    is unchanged.
  * test_map_name_fk     (REQ-11): the maps_map_name_names_fk FK exists; inserting a
                                    core.maps row whose map_name is absent from
                                    maps.names raises a foreign-key violation; a row
                                    whose map_name IS present succeeds.

Direct DB introspection / DML via the asyncpg_pool fixture. The -k filters in
15-VALIDATION resolve to these names (phantom_maps / seed_idempotent / map_name_fk).
"""

import asyncpg
import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.domain_maps,
]

# The 7 phantom Literal-only maps reconciled into maps.names by migration 0032 (D-08)
# and the rewritten 0001 seed (D-09). They passed the old OverwatchMap Literal request
# validation but had no maps.names row, so they failed the maps.mastery FK and never
# appeared in autocomplete — a real pre-existing drift bug between the 70-entry Literal
# and the 63-row table.
_PHANTOM_MAPS = [
    "Arena Victoriae",
    "Gogadoro",
    "Neon Junction",
    "Place Lacroix",
    "Powder Keg Mine",
    "Redwood Dam",
    "Thames District",
]


class TestMapManagementSchema:
    """Verify phantom reconciliation, seed idempotency, and the map_name FK backstop."""

    async def test_phantom_maps(self, asyncpg_pool):
        """All 7 phantom names are present in maps.names after migrations apply (REQ-13)."""
        async with asyncpg_pool.acquire() as conn:
            present = await conn.fetchval(
                "SELECT count(*) FROM maps.names WHERE name = ANY($1::text[])",
                _PHANTOM_MAPS,
            )
            assert present == len(_PHANTOM_MAPS)

    async def test_seed_idempotent(self, asyncpg_pool):
        """Re-applying the 0001 ON CONFLICT seed block is replay-safe (REQ-12).

        The latent bug (D-09) was 63 plain INSERTs: a second apply raised a
        duplicate-PK violation. With ON CONFLICT DO NOTHING, re-applying any subset
        of the seeded names raises no error and leaves the row count unchanged.
        """
        async with asyncpg_pool.acquire() as conn:
            before = await conn.fetchval("SELECT count(*) FROM maps.names")

            # Re-apply a representative slice of the committed seed (incl. an
            # apostrophe-bearing name and the phantoms) using the exact ON CONFLICT
            # shape from 0001_init.sql. This must not raise.
            await conn.execute(
                """
                INSERT INTO maps.names (name)
                VALUES
                    ('Hanamura'),
                    ('Busan'),
                    ('King''s Row'),
                    ('Arena Victoriae'),
                    ('Gogadoro'),
                    ('Neon Junction'),
                    ('Place Lacroix'),
                    ('Powder Keg Mine'),
                    ('Redwood Dam'),
                    ('Thames District')
                ON CONFLICT DO NOTHING
                """
            )

            after = await conn.fetchval("SELECT count(*) FROM maps.names")
            assert after == before

    async def test_map_name_fk_constraint_exists(self, asyncpg_pool):
        """The maps_map_name_names_fk FK on core.maps.map_name exists (REQ-11)."""
        async with asyncpg_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT confupdtype, confrelid::regclass::text AS referenced_table
                FROM pg_constraint
                WHERE conname = 'maps_map_name_names_fk'
                  AND conrelid = 'core.maps'::regclass
                  AND contype = 'f'
                """
            )
            assert row is not None, "maps_map_name_names_fk FK is missing on core.maps"
            assert row["referenced_table"] == "maps.names"
            # 'c' = ON UPDATE CASCADE (D-11). pg_constraint.confupdtype is a "char"
            # column → asyncpg returns it as a single byte.
            assert row["confupdtype"] == b"c"

    async def test_map_name_fk_rejects_orphan(self, asyncpg_pool):
        """Inserting core.maps with a map_name absent from maps.names raises FK violation (REQ-11)."""
        async with asyncpg_pool.acquire() as conn:
            tr = conn.transaction()
            await tr.start()
            try:
                await conn.execute("SAVEPOINT fk_orphan")
                with pytest.raises(asyncpg.ForeignKeyViolationError):
                    await conn.execute(
                        """
                        INSERT INTO core.maps (code, map_name, category, checkpoints, difficulty, raw_difficulty)
                        VALUES ('FKOR1', 'Definitely Not A Real Overwatch Map', 'Mildcore', 3, 'Easy', 3.00)
                        """
                    )
                await conn.execute("ROLLBACK TO SAVEPOINT fk_orphan")
            finally:
                await tr.rollback()

    async def test_map_name_fk_accepts_known(self, asyncpg_pool):
        """Inserting core.maps with a map_name present in maps.names succeeds (REQ-11)."""
        async with asyncpg_pool.acquire() as conn:
            tr = conn.transaction()
            await tr.start()
            try:
                # 'Hanamura' is in the seed; the FK must accept it.
                map_id = await conn.fetchval(
                    """
                    INSERT INTO core.maps (code, map_name, category, checkpoints, difficulty, raw_difficulty)
                    VALUES ('FKOK1', 'Hanamura', 'Mildcore', 3, 'Easy', 3.00)
                    RETURNING id
                    """
                )
                assert map_id is not None
            finally:
                # Roll back so the shared session DB is left untouched.
                await tr.rollback()
