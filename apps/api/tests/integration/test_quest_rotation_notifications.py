"""Integration tests for quest rotation notifications."""

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.domain_store,
]


@pytest.mark.asyncio
async def test_rotation_inserts_notifications(asyncpg_pool):
    """Rotation generation inserts quest rotation notifications."""
    async with asyncpg_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO core.users (id, nickname, global_name)
            VALUES (987654321987654321, 'QuestTester', 'QuestTester')
            ON CONFLICT (id) DO NOTHING
            """
        )
        await conn.execute("SELECT store.check_and_generate_quest_rotation()")
        count = await conn.fetchval(
            """
            SELECT COUNT(*) FROM notifications.events
            WHERE event_type = 'quest_rotation'
            """
        )

    assert count >= 1
