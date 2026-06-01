"""Integration tests for tournaments schema migration (0020).

Verifies the tournament schema was applied correctly with all tables,
constraints, indexes, singleton config, and the core.completions ALTER TABLE.
Uses direct database introspection via information_schema and pg_indexes.
"""

import asyncpg
import pytest

pytestmark = [
    pytest.mark.integration,
]


class TestTournamentsSchema:
    """Verify tournaments schema structure and constraints."""

    async def test_tournaments_schema_exists(self, asyncpg_pool):
        """The tournaments schema exists in the database."""
        async with asyncpg_pool.acquire() as conn:
            row = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM information_schema.schemata
                WHERE schema_name = 'tournaments'
                """
            )
            assert row == 1

    async def test_tournaments_tables_exist(self, asyncpg_pool):
        """All 7 tournament tables exist in the tournaments schema."""
        async with asyncpg_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'tournaments'
                ORDER BY table_name
                """
            )
            table_names = {row["table_name"] for row in rows}
            assert table_names == {
                "config",
                "categories",
                "cycles",
                "completions",
                "streaks",
                "pending_transitions",
                "xp_grants",
            }

    async def test_config_singleton_constraint(self, asyncpg_pool):
        """The config table rejects inserts with id != 1 via CHECK constraint."""
        async with asyncpg_pool.acquire() as conn:
            tr = conn.transaction()
            await tr.start()
            try:
                await conn.execute("SAVEPOINT test_singleton")
                with pytest.raises(asyncpg.CheckViolationError):
                    await conn.execute(
                        """
                        INSERT INTO tournaments.config (id, blacklist_weeks)
                        OVERRIDING SYSTEM VALUE
                        VALUES (2, 4)
                        """
                    )
                await conn.execute("ROLLBACK TO SAVEPOINT test_singleton")
            finally:
                await tr.rollback()

    async def test_core_completions_tournament_column_exists(self, asyncpg_pool):
        """core.completions has a nullable tournament_completion_id column with no default."""
        async with asyncpg_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'core'
                  AND table_name = 'completions'
                  AND column_name = 'tournament_completion_id'
                """
            )
            assert row is not None
            assert row["is_nullable"] == "YES"
            assert row["column_default"] is None

    async def test_categories_has_xp_columns(self, asyncpg_pool):
        """The categories table has all XP configuration columns (per D-05)."""
        async with asyncpg_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'tournaments'
                  AND table_name = 'categories'
                """
            )
            column_names = {row["column_name"] for row in rows}
            assert "participation_xp" in column_names
            assert "placement_xp" in column_names
            assert "streak_xp" in column_names

    async def test_config_has_no_xp_columns(self, asyncpg_pool):
        """The config table has no XP columns (per D-06)."""
        async with asyncpg_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'tournaments'
                  AND table_name = 'config'
                """
            )
            column_names = {row["column_name"] for row in rows}
            xp_columns = {"participation_xp", "placement_xp", "streak_xp"}
            assert column_names.isdisjoint(xp_columns)

    async def test_cycles_status_check_constraint(self, asyncpg_pool):
        """The cycles table rejects invalid status values via CHECK constraint."""
        async with asyncpg_pool.acquire() as conn:
            tr = conn.transaction()
            await tr.start()
            try:
                await conn.execute("SAVEPOINT test_status")
                # Create a test user for map creator FK
                await conn.execute(
                    """
                    INSERT INTO core.users (id, nickname, global_name)
                    VALUES (999999999999999901, 'tournament_test_user', 'tournament_test_user')
                    ON CONFLICT (id) DO NOTHING
                    """
                )
                # Create a test map for the cycles FK
                map_id = await conn.fetchval(
                    """
                    INSERT INTO core.maps (code, map_name, category, checkpoints, difficulty, raw_difficulty)
                    VALUES ('TSTA1', 'Tournament Test Map', 'Mildcore', 3, 'Easy', 3.00)
                    ON CONFLICT (code) DO UPDATE SET map_name = EXCLUDED.map_name
                    RETURNING id
                    """
                )
                # Create a test category
                category_id = await conn.fetchval(
                    """
                    INSERT INTO tournaments.categories (name, difficulties)
                    VALUES ('test_status_check', ARRAY['Easy'])
                    RETURNING id
                    """
                )

                with pytest.raises(asyncpg.CheckViolationError):
                    await conn.execute(
                        """
                        INSERT INTO tournaments.cycles (category_id, map_id, status)
                        VALUES ($1, $2, 'invalid_status')
                        """,
                        category_id,
                        map_id,
                    )
                await conn.execute("ROLLBACK TO SAVEPOINT test_status")
            finally:
                await tr.rollback()

    async def test_config_singleton_seeded(self, asyncpg_pool):
        """The config singleton exists and blacklist_weeks is seeded defaulting to 4.

        Asserts the column DEFAULT (an immutable schema property that drives the seed
        INSERT) rather than the live row value. The singleton is a shared row that sibling
        integration tests legitimately PATCH (e.g. to 5 or 0) without restoring it, so on
        the session-scoped shared test DB the live value is order/parallelism-dependent.
        The seed invariant — "blacklist_weeks is seeded to 4" — is the column default, which
        no data write can change.
        """
        async with asyncpg_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id
                FROM tournaments.config
                WHERE id = 1
                """
            )
            assert row is not None  # singleton seeded

            default = await conn.fetchval(
                """
                SELECT column_default
                FROM information_schema.columns
                WHERE table_schema = 'tournaments'
                  AND table_name = 'config'
                  AND column_name = 'blacklist_weeks'
                """
            )
            assert default is not None and "4" in default  # DEFAULT 4 → seeded value

    async def test_foreign_key_indexes_exist(self, asyncpg_pool):
        """All FK columns have explicit indexes."""
        async with asyncpg_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = 'tournaments'
                """
            )
            index_names = {row["indexname"] for row in rows}

            expected_indexes = {
                "idx_cycles_category_id",
                "idx_cycles_map_id",
                "idx_tournament_completions_cycle_id",
                "idx_tournament_completions_user_id",
                "idx_tournament_completions_map_id",
                "idx_streaks_user_id",
                "idx_pending_transitions_cycle_id",
            }
            assert expected_indexes.issubset(index_names)


# Wipe statements from migration 0024 (D-13/14/15). Re-running them is idempotent
# against current state and is the intention-revealing way to exercise the wipe in
# a test (the session-setup migration already ran once before any test data exists).
_WIPE_SQL = """
UPDATE core.completions SET tournament_completion_id = NULL
WHERE tournament_completion_id IS NOT NULL;
DELETE FROM tournaments.completions;
DELETE FROM tournaments.cycles;
DELETE FROM tournaments.editions;
DELETE FROM tournaments.pending_transitions;
"""


class TestTournamentsEditionsOverhaul:
    """Migration 0024 schema shape: editions table, global config cols, dropped per-category cols."""

    async def test_overhaul_editions_table_exists(self, asyncpg_pool):
        """tournaments.editions exists with started_at/ends_at/status/created_at + status CHECK."""
        async with asyncpg_pool.acquire() as conn:
            cols = await conn.fetch(
                """
                SELECT column_name, is_nullable, data_type
                FROM information_schema.columns
                WHERE table_schema = 'tournaments' AND table_name = 'editions'
                """
            )
            by_name = {c["column_name"]: c for c in cols}
            assert {"id", "started_at", "ends_at", "status", "created_at"}.issubset(by_name)
            assert by_name["started_at"]["is_nullable"] == "NO"
            assert by_name["ends_at"]["is_nullable"] == "NO"

            # status CHECK rejects an invalid value.
            tr = conn.transaction()
            await tr.start()
            try:
                await conn.execute("SAVEPOINT s_edition_status")
                with pytest.raises(asyncpg.CheckViolationError):
                    await conn.execute(
                        """
                        INSERT INTO tournaments.editions (started_at, ends_at, status)
                        VALUES (now(), now() + interval '1 week', 'bogus')
                        """
                    )
                await conn.execute("ROLLBACK TO SAVEPOINT s_edition_status")
            finally:
                await tr.rollback()

    async def test_overhaul_cycles_has_edition_id(self, asyncpg_pool):
        """tournaments.cycles gained a nullable edition_id FK + index."""
        async with asyncpg_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'tournaments'
                  AND table_name = 'cycles'
                  AND column_name = 'edition_id'
                """
            )
            assert row is not None
            assert row["is_nullable"] == "YES"

            indexes = await conn.fetch(
                "SELECT indexname FROM pg_indexes WHERE schemaname = 'tournaments'"
            )
            assert "idx_cycles_edition_id" in {r["indexname"] for r in indexes}

    async def test_overhaul_config_has_global_columns(self, asyncpg_pool):
        """tournaments.config has cadence/anchor_*/transitions_paused/debug_cycle_seconds (D-02/03/06/07)."""
        async with asyncpg_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT column_name, column_default
                FROM information_schema.columns
                WHERE table_schema = 'tournaments' AND table_name = 'config'
                """
            )
            by_name = {r["column_name"]: r for r in rows}
            for col in (
                "cadence",
                "anchor_weekday",
                "anchor_time",
                "anchor_tz",
                "transitions_paused",
                "debug_cycle_seconds",
            ):
                assert col in by_name, f"missing config column {col}"
            # Documented defaults.
            assert "weekly" in by_name["cadence"]["column_default"]
            assert "1" in by_name["anchor_weekday"]["column_default"]
            assert "UTC" in by_name["anchor_tz"]["column_default"]
            assert by_name["transitions_paused"]["column_default"].lower().startswith("false")

    async def test_overhaul_categories_dropped_per_category_columns(self, asyncpg_pool):
        """tournaments.categories no longer has cycle_frequency/transitions_paused/debug_cycle_seconds (D-02/D-03)."""
        async with asyncpg_pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'tournaments' AND table_name = 'categories'
                """
            )
            column_names = {r["column_name"] for r in rows}
            dropped = {"cycle_frequency", "transitions_paused", "debug_cycle_seconds"}
            assert column_names.isdisjoint(dropped), f"still present: {column_names & dropped}"

    async def test_overhaul_outbox_supports_edition_rollover(self, asyncpg_pool):
        """pending_transitions: nullable cycle_id, edition_id column, event_type CHECK allows edition_rollover."""
        async with asyncpg_pool.acquire() as conn:
            cols = await conn.fetch(
                """
                SELECT column_name, is_nullable
                FROM information_schema.columns
                WHERE table_schema = 'tournaments' AND table_name = 'pending_transitions'
                """
            )
            by_name = {c["column_name"]: c for c in cols}
            assert "edition_id" in by_name
            assert by_name["cycle_id"]["is_nullable"] == "YES"

            # An edition_rollover row with NULL cycle_id is accepted.
            tr = conn.transaction()
            await tr.start()
            try:
                await conn.execute("SAVEPOINT s_outbox")
                edition_id = await conn.fetchval(
                    """
                    INSERT INTO tournaments.editions (started_at, ends_at, status)
                    VALUES (now(), now() + interval '1 week', 'active')
                    RETURNING id
                    """
                )
                await conn.execute(
                    """
                    INSERT INTO tournaments.pending_transitions (cycle_id, edition_id, event_type, payload)
                    VALUES (NULL, $1::int, 'edition_rollover',
                            jsonb_build_object('results', '[]'::jsonb, 'started', '[]'::jsonb,
                                               'edition_id', $1::int))
                    """,
                    edition_id,
                )
                await conn.execute("ROLLBACK TO SAVEPOINT s_outbox")
            finally:
                await tr.rollback()


class TestTournamentsFreshRestartWipe:
    """Fresh-restart wipe preserves core PBs while NULLing the FK (D-13/14/15)."""

    async def test_preserve_pbs_wipe_keeps_core_rows_nulls_fk(
        self,
        asyncpg_pool,
        create_test_map,
        create_test_user,
    ):
        """Wipe NULLs tournament_completion_id on cross-written core rows but KEEPS them."""
        async with asyncpg_pool.acquire() as conn:
            # Seed: edition -> cycle -> tournament completion, cross-written into core.completions.
            map_id = await create_test_map(difficulty="Medium")
            user_id = await create_test_user()
            category_id = await conn.fetchval(
                """
                INSERT INTO tournaments.categories (name, difficulties)
                VALUES ($1, ARRAY['Medium'])
                RETURNING id
                """,
                f"wipe-cat-{user_id}",
            )
            edition_id = await conn.fetchval(
                """
                INSERT INTO tournaments.editions (started_at, ends_at, status)
                VALUES (now() - interval '1 week', now(), 'active')
                RETURNING id
                """
            )
            cycle_id = await conn.fetchval(
                """
                INSERT INTO tournaments.cycles (edition_id, category_id, map_id, status, started_at)
                VALUES ($1, $2, $3, 'active', now() - interval '1 week')
                RETURNING id
                """,
                edition_id,
                category_id,
                map_id,
            )
            tc_id = await conn.fetchval(
                """
                INSERT INTO tournaments.completions
                    (cycle_id, user_id, map_id, time, screenshot, verified, completion)
                VALUES ($1, $2, $3, 12.34, 'https://example.com/s.png', TRUE, TRUE)
                RETURNING id
                """,
                cycle_id,
                user_id,
                map_id,
            )
            # Cross-write into core.completions, linking the tournament completion (the PB).
            core_id = await conn.fetchval(
                """
                INSERT INTO core.completions (map_id, user_id, time, screenshot, tournament_completion_id)
                VALUES ($1, $2, 12.34, 'https://example.com/s.png', $3)
                RETURNING id
                """,
                map_id,
                user_id,
                tc_id,
            )

            # Sanity: the link is set before the wipe.
            assert (
                await conn.fetchval(
                    "SELECT tournament_completion_id FROM core.completions WHERE id = $1", core_id
                )
                == tc_id
            )

            # Run the wipe (D-13/14/15).
            await conn.execute(_WIPE_SQL)

            # (a) core.completions PB row is PRESERVED (not cascade-deleted).
            assert (
                await conn.fetchval("SELECT count(*) FROM core.completions WHERE id = $1", core_id)
            ) == 1
            # (b) its tournament_completion_id is NULLed (FK SET NULL, no cascade).
            assert (
                await conn.fetchval(
                    "SELECT tournament_completion_id FROM core.completions WHERE id = $1", core_id
                )
            ) is None
            # (c) tournament tables are wiped.
            assert (await conn.fetchval("SELECT count(*) FROM tournaments.completions")) == 0
            assert (await conn.fetchval("SELECT count(*) FROM tournaments.cycles")) == 0
            assert (await conn.fetchval("SELECT count(*) FROM tournaments.editions")) == 0
