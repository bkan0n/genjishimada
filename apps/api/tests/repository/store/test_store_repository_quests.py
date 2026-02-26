"""Tests for StoreRepository quest helpers."""

from uuid import uuid4

import pytest

from repository.store_repository import StoreRepository

pytestmark = [
    pytest.mark.domain_store,
]


@pytest.fixture
async def repository(asyncpg_conn):
    """Provide store repository instance."""
    return StoreRepository(asyncpg_conn)


class TestGetRotationWindow:
    async def test_get_rotation_window_returns_window(self, repository: StoreRepository, asyncpg_conn):
        rotation_id = uuid4()

        quest_id = await asyncpg_conn.fetchval(
            """
            INSERT INTO store.quests (name, description, quest_type, difficulty, coin_reward, xp_reward, requirements)
            VALUES ('Test Quest', 'Test', 'global', 'easy', 1, 1, '{}'::jsonb)
            RETURNING id
            """
        )

        await asyncpg_conn.execute(
            """
            INSERT INTO store.quest_rotation
                (rotation_id, quest_id, quest_data, available_from, available_until)
            VALUES ($1, $2, '{}'::jsonb, now(), now() + interval '7 days')
            """,
            rotation_id,
            quest_id,
        )

        window = await repository.get_rotation_window(rotation_id)

        assert window
        assert "available_from" in window
        assert "available_until" in window


class TestBountyDataSources:
    async def test_get_user_completions_returns_rows(
        self,
        repository: StoreRepository,
        asyncpg_conn,
        unique_user_id,
        create_test_map,
    ):
        await asyncpg_conn.execute(
            "INSERT INTO core.users (id, nickname, global_name) VALUES ($1, 'User', 'User')",
            unique_user_id,
        )
        map_id = await create_test_map()

        await asyncpg_conn.execute(
            """
            INSERT INTO core.completions (map_id, user_id, time, screenshot, verified, legacy)
            VALUES ($1, $2, 45.5, 'test.png', true, false)
            """,
            map_id,
            unique_user_id,
        )

        completions = await repository.get_user_completions(unique_user_id)

        assert completions
        assert completions[0]["map_id"] == map_id

    async def test_get_medal_thresholds_returns_values(
        self,
        repository: StoreRepository,
        create_test_map,
    ):
        map_id = await create_test_map(medals={"gold": 30.0, "silver": 45.0, "bronze": 60.0})

        thresholds = await repository.get_medal_thresholds(map_id)

        assert thresholds["gold"] == 30.0
        assert thresholds["silver"] == 45.0
        assert thresholds["bronze"] == 60.0

    async def test_get_percentile_target_time_returns_value(
        self,
        repository: StoreRepository,
        asyncpg_conn,
        unique_user_id,
        create_test_map,
    ):
        await asyncpg_conn.execute(
            "INSERT INTO core.users (id, nickname, global_name) VALUES ($1, 'User', 'User')",
            unique_user_id,
        )
        rival_id = unique_user_id + 1
        await asyncpg_conn.execute(
            "INSERT INTO core.users (id, nickname, global_name) VALUES ($1, 'Rival', 'Rival')",
            rival_id,
        )

        map_id = await create_test_map()

        await asyncpg_conn.execute(
            """
            INSERT INTO core.completions (map_id, user_id, time, screenshot, verified, legacy)
            VALUES ($1, $2, 10.0, 'a.png', true, false),
                   ($1, $3, 20.0, 'b.png', true, false)
            """,
            map_id,
            unique_user_id,
            rival_id,
        )

        target_time = await repository.get_percentile_target_time(map_id, 0.5)

        assert target_time == 15.0

    async def test_get_user_skill_rank_defaults_ninja(
        self,
        repository: StoreRepository,
        asyncpg_conn,
        unique_user_id,
    ):
        await asyncpg_conn.execute(
            "INSERT INTO core.users (id, nickname, global_name) VALUES ($1, 'User', 'User')",
            unique_user_id,
        )

        rank = await repository.get_user_skill_rank(unique_user_id)

        assert rank == "Ninja"

    async def test_find_rivals_returns_other_user(
        self,
        repository: StoreRepository,
        asyncpg_conn,
        unique_user_id,
    ):
        user_id = unique_user_id
        rival_id = unique_user_id + 1
        await asyncpg_conn.execute(
            "INSERT INTO core.users (id, nickname, global_name) VALUES ($1, 'User', 'User')",
            user_id,
        )
        await asyncpg_conn.execute(
            "INSERT INTO core.users (id, nickname, global_name) VALUES ($1, 'Rival', 'Rival')",
            rival_id,
        )

        rivals = await repository.find_rivals(user_id, "Ninja")

        assert rivals
        assert rivals[0]["user_id"] != user_id

    async def test_find_beatable_rival_map_returns_map(
        self,
        repository: StoreRepository,
        asyncpg_conn,
        unique_user_id,
        create_test_map,
    ):
        user_id = unique_user_id
        rival_id = unique_user_id + 1
        await asyncpg_conn.execute(
            "INSERT INTO core.users (id, nickname, global_name) VALUES ($1, 'User', 'User')",
            user_id,
        )
        await asyncpg_conn.execute(
            "INSERT INTO core.users (id, nickname, global_name) VALUES ($1, 'Rival', 'Rival')",
            rival_id,
        )

        map_id = await create_test_map()

        await asyncpg_conn.execute(
            """
            INSERT INTO core.completions (map_id, user_id, time, screenshot, verified, legacy)
            VALUES ($1, $2, 50.0, 'u.png', true, false),
                   ($1, $3, 40.0, 'r.png', true, false)
            """,
            map_id,
            user_id,
            rival_id,
        )

        rival_map = await repository.find_beatable_rival_map(user_id, rival_id)

        assert rival_map is not None
        assert rival_map["map_id"] == map_id

    async def test_get_uncompleted_maps_returns_map(
        self,
        repository: StoreRepository,
        asyncpg_conn,
        unique_user_id,
        create_test_map,
    ):
        await asyncpg_conn.execute(
            "INSERT INTO core.users (id, nickname, global_name) VALUES ($1, 'User', 'User')",
            unique_user_id,
        )
        completed_map_id = await create_test_map()
        await create_test_map()

        await asyncpg_conn.execute(
            """
            INSERT INTO core.completions (map_id, user_id, time, screenshot, verified, legacy)
            VALUES ($1, $2, 50.0, 'u.png', true, false)
            """,
            completed_map_id,
            unique_user_id,
        )

        uncompleted = await repository.get_uncompleted_maps(unique_user_id)

        assert uncompleted
        assert completed_map_id not in {row["map_id"] for row in uncompleted}
