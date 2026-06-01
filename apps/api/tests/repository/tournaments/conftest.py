"""Tournament repository test fixtures."""

from typing import Any
from uuid import uuid4

import asyncpg
import pytest

from repository.tournaments_repository import TournamentRepository


@pytest.fixture
async def repository(asyncpg_conn: asyncpg.Connection) -> TournamentRepository:
    """Provide tournament repository instance."""
    return TournamentRepository(asyncpg_conn)


@pytest.fixture
async def create_test_category(asyncpg_pool: asyncpg.Pool):
    """Factory fixture for creating test tournament categories.

    Returns a function that creates a category with sensible defaults.

    Usage:
        category_id = await create_test_category()
        category_id = await create_test_category(name="Hard Category", difficulties=["Hard"])
    """

    async def _create(**overrides: Any) -> int:
        data: dict[str, Any] = {
            "name": f"Cat-{uuid4().hex[:6]}",
            "difficulties": ["Medium"],
            "cycle_frequency": "weekly",
            "participation_xp": 100,
            "placement_xp": "[]",
            "streak_xp": "[]",
            "champion_role_id": None,
            "is_active": True,
        }
        data.update(overrides)

        async with asyncpg_pool.acquire() as conn:
            category_id: int = await conn.fetchval(
                """
                INSERT INTO tournaments.categories (
                    name, difficulties, cycle_frequency, participation_xp,
                    placement_xp, streak_xp, champion_role_id, is_active
                )
                VALUES ($1, $2::text[], $3, $4, $5::jsonb, $6::jsonb, $7, $8)
                RETURNING id
                """,
                data["name"],
                data["difficulties"],
                data["cycle_frequency"],
                data["participation_xp"],
                data["placement_xp"],
                data["streak_xp"],
                data["champion_role_id"],
                data["is_active"],
            )
        return category_id

    return _create


@pytest.fixture
async def create_test_cycle(asyncpg_pool: asyncpg.Pool):
    """Factory fixture for creating test tournament cycles.

    Returns a function that creates a cycle with sensible defaults.

    Usage:
        cycle_id = await create_test_cycle(category_id, map_id)
        cycle_id = await create_test_cycle(category_id, map_id, status="active")
    """

    async def _create(category_id: int, map_id: int, **overrides: Any) -> int:
        data: dict[str, Any] = {
            "status": "pending",
            "started_at": None,
            "ended_at": None,
        }
        data.update(overrides)

        async with asyncpg_pool.acquire() as conn:
            cycle_id: int = await conn.fetchval(
                """
                INSERT INTO tournaments.cycles (category_id, map_id, status, started_at, ended_at)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
                """,
                category_id,
                map_id,
                data["status"],
                data["started_at"],
                data["ended_at"],
            )
        return cycle_id

    return _create


@pytest.fixture
async def create_test_tournament_completion(asyncpg_pool: asyncpg.Pool):
    """Factory fixture for creating test tournament completions.

    Returns a function that creates a tournament completion with sensible defaults.

    Usage:
        completion_id = await create_test_tournament_completion(cycle_id, user_id, map_id)
        completion_id = await create_test_tournament_completion(cycle_id, user_id, map_id, time=15.0, verified=True)
    """

    async def _create(cycle_id: int, user_id: int, map_id: int, **overrides: Any) -> int:
        data: dict[str, Any] = {
            "time": 30.0,
            "screenshot": "https://example.com/screenshot.png",
            "video": None,
            "verified": False,
            "completion": False,
        }
        data.update(overrides)

        async with asyncpg_pool.acquire() as conn:
            completion_id: int = await conn.fetchval(
                """
                INSERT INTO tournaments.completions (
                    cycle_id, user_id, map_id, time, screenshot, video, verified, completion
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id
                """,
                cycle_id,
                user_id,
                map_id,
                data["time"],
                data["screenshot"],
                data["video"],
                data["verified"],
                data["completion"],
            )
        return completion_id

    return _create
