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
        """The config singleton row is seeded with blacklist_weeks = 4."""
        async with asyncpg_pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, blacklist_weeks
                FROM tournaments.config
                WHERE id = 1
                """
            )
            assert row is not None
            assert row["blacklist_weeks"] == 4

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
