"""Integration tests for store service quest provisioning."""

import pytest
import msgspec
from litestar.datastructures import State
from uuid import uuid4

from repository.lootbox_repository import LootboxRepository
from repository.store_repository import StoreRepository
from services.store_service import StoreService

pytestmark = [
    pytest.mark.integration,
    pytest.mark.domain_store,
]


@pytest.mark.asyncio
async def test_ensure_user_quests_for_rotation_idempotent(asyncpg_pool, create_test_user):
    """Ensures quest provisioning is idempotent per user/rotation."""
    user_id = await create_test_user()
    store_repo = StoreRepository(asyncpg_pool)
    lootbox_repo = LootboxRepository(asyncpg_pool)
    service = StoreService(asyncpg_pool, State(), store_repo, lootbox_repo)

    rotation_id = await service.ensure_user_quests_for_rotation(user_id)
    rotation_id_again = await service.ensure_user_quests_for_rotation(user_id)

    assert rotation_id == rotation_id_again

    async with asyncpg_pool.acquire() as conn:
        total = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM store.user_quest_progress
            WHERE user_id = $1 AND rotation_id = $2
            """,
            user_id,
            rotation_id,
        )
        global_count = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM store.user_quest_progress
            WHERE user_id = $1 AND rotation_id = $2 AND quest_id IS NOT NULL
            """,
            user_id,
            rotation_id,
        )
        bounty_count = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM store.user_quest_progress
            WHERE user_id = $1 AND rotation_id = $2 AND quest_id IS NULL
            """,
            user_id,
            rotation_id,
        )

    assert total == 6
    assert global_count == 5
    assert bounty_count == 1


@pytest.mark.asyncio
async def test_generate_personal_improvement_bounty(asyncpg_pool, create_test_user, create_test_map, create_test_completion):
    """Personal improvement bounty uses beat_time requirements."""
    user_id = await create_test_user()
    map_id = await create_test_map(medals={"gold": 30.0, "silver": 45.0, "bronze": 60.0})
    await create_test_completion(user_id, map_id, time=70.0)

    store_repo = StoreRepository(asyncpg_pool)
    lootbox_repo = LootboxRepository(asyncpg_pool)
    service = StoreService(asyncpg_pool, State(), store_repo, lootbox_repo)

    bounty = await service._generate_personal_improvement_bounty(user_id, uuid4())

    quest_data = bounty["quest_data"]
    requirements = quest_data["requirements"]
    assert quest_data["bounty_type"] == "personal_improvement"
    assert requirements["type"] == "beat_time"
    assert requirements["map_id"] == map_id
    assert requirements["target_time"] == 70.0 * 0.9  # percentile == user time, falls back to personal_best
    assert requirements["target_type"] == "personal_best"
    assert requirements["current_best"] == 70.0


@pytest.mark.asyncio
async def test_generate_rival_challenge_bounty(asyncpg_pool, create_test_user, create_test_map, create_test_completion):
    """Rival challenge bounty uses beat_rival requirements."""
    user_id = await create_test_user()
    rival_id = await create_test_user()
    map_id = await create_test_map()

    # Create completions where rival is 10-20% faster (within beatable range)
    await create_test_completion(user_id, map_id, time=100.0)
    await create_test_completion(rival_id, map_id, time=85.0)  # 15% faster

    store_repo = StoreRepository(asyncpg_pool)
    lootbox_repo = LootboxRepository(asyncpg_pool)
    service = StoreService(asyncpg_pool, State(), store_repo, lootbox_repo)

    # Mock the repository methods to ensure rival and beatable map are found
    async def mock_find_rivals(*args, **kwargs):
        return [{"user_id": rival_id, "username": "TestRival"}]

    async def mock_find_beatable_rival_map(*args, **kwargs):
        return {
            "map_id": map_id,
            "code": "TEST1",
            "map_name": "Test Map",
            "rival_time": 85.0,
            "user_time": 100.0,
        }

    # Patch the repository methods
    original_find_rivals = store_repo.find_rivals
    original_find_beatable = store_repo.find_beatable_rival_map
    store_repo.find_rivals = mock_find_rivals
    store_repo.find_beatable_rival_map = mock_find_beatable_rival_map

    try:
        bounty = await service._generate_rival_challenge_bounty(user_id, uuid4())

        quest_data = bounty["quest_data"]
        requirements = quest_data["requirements"]
        assert quest_data["bounty_type"] == "rival_challenge"
        assert requirements["type"] == "beat_rival"
        assert requirements["map_id"] == map_id
        assert requirements["rival_user_id"] == rival_id
        assert requirements["rival_time"] == 85.0
        assert requirements["target_time"] == 85.0
    finally:
        # Restore original methods
        store_repo.find_rivals = original_find_rivals
        store_repo.find_beatable_rival_map = original_find_beatable


@pytest.mark.asyncio
async def test_generate_gap_filling_bounty(asyncpg_pool, create_test_user, create_test_map):
    """Gap filling bounty uses complete_map requirements."""
    user_id = await create_test_user()
    await create_test_map()

    store_repo = StoreRepository(asyncpg_pool)
    lootbox_repo = LootboxRepository(asyncpg_pool)
    service = StoreService(asyncpg_pool, State(), store_repo, lootbox_repo)

    bounty = await service._generate_gap_filling_bounty(user_id, uuid4())

    quest_data = bounty["quest_data"]
    requirements = quest_data["requirements"]
    assert quest_data["bounty_type"] == "gap_filling"
    assert requirements["type"] == "complete_map"
    assert requirements["map_id"] is not None


@pytest.mark.asyncio
async def test_event_matches_complete_difficulty_range(asyncpg_pool):
    """Event matching honors complete_difficulty_range requirements."""
    store_repo = StoreRepository(asyncpg_pool)
    lootbox_repo = LootboxRepository(asyncpg_pool)
    service = StoreService(asyncpg_pool, State(), store_repo, lootbox_repo)

    requirements = {"type": "complete_difficulty_range", "difficulty": "easy", "min_count": 2}
    assert service._event_matches_quest(requirements, "completion", {"difficulty": "easy"}) is True
    assert service._event_matches_quest(requirements, "completion", {"difficulty": "hard"}) is False
    assert service._event_matches_quest(requirements, "medal", {"difficulty": "easy"}) is False


@pytest.mark.asyncio
async def test_event_matches_beat_rival(asyncpg_pool):
    """Event matching requires matching map for beat_rival."""
    store_repo = StoreRepository(asyncpg_pool)
    lootbox_repo = LootboxRepository(asyncpg_pool)
    service = StoreService(asyncpg_pool, State(), store_repo, lootbox_repo)

    requirements = {"type": "beat_rival", "map_id": 101}
    assert service._event_matches_quest(requirements, "completion", {"map_id": 101}) is True
    assert service._event_matches_quest(requirements, "completion", {"map_id": 202}) is False
    assert service._event_matches_quest(requirements, "medal", {"map_id": 101}) is False


@pytest.mark.asyncio
async def test_calculate_progress_complete_difficulty_range(asyncpg_pool):
    """Progress for complete_difficulty_range counts unique maps."""
    store_repo = StoreRepository(asyncpg_pool)
    lootbox_repo = LootboxRepository(asyncpg_pool)
    service = StoreService(asyncpg_pool, State(), store_repo, lootbox_repo)

    requirements = {"type": "complete_difficulty_range", "difficulty": "easy", "min_count": 2}
    progress = {"current": 0, "completed_map_ids": []}

    updated = service._calculate_new_progress(progress, requirements, {"map_id": 1})
    assert updated["current"] == 1
    assert 1 in updated["completed_map_ids"]

    unchanged = service._calculate_new_progress(updated, requirements, {"map_id": 1})
    assert unchanged["current"] == 1


@pytest.mark.asyncio
async def test_calculate_progress_beat_rival(asyncpg_pool):
    """Progress for beat_rival tracks best and last attempts."""
    store_repo = StoreRepository(asyncpg_pool)
    lootbox_repo = LootboxRepository(asyncpg_pool)
    service = StoreService(asyncpg_pool, State(), store_repo, lootbox_repo)

    requirements = {"type": "beat_rival", "map_id": 101, "target_time": 90.0}
    progress = {}

    updated = service._calculate_new_progress(progress, requirements, {"time": 100.0})
    assert updated["last_attempt"] == 100.0
    assert updated["best_attempt"] == 100.0

    updated = service._calculate_new_progress(updated, requirements, {"time": 90.0})
    assert updated["last_attempt"] == 90.0
    assert updated["best_attempt"] == 90.0


@pytest.mark.asyncio
async def test_is_quest_complete_beat_rival(asyncpg_pool):
    """Beat rival completes when best attempt is under target time."""
    store_repo = StoreRepository(asyncpg_pool)
    lootbox_repo = LootboxRepository(asyncpg_pool)
    service = StoreService(asyncpg_pool, State(), store_repo, lootbox_repo)

    requirements = {"type": "beat_rival", "target_time": 90.0}
    assert service._is_quest_complete({"best_attempt": 80.0}, requirements) is True
    assert service._is_quest_complete({"best_attempt": 95.0}, requirements) is False


@pytest.mark.asyncio
async def test_update_quest_progress_returns_progress_id(asyncpg_pool, create_test_user, create_test_map):
    """update_quest_progress returns progress_id for completed quests."""
    user_id = await create_test_user()
    map_id = await create_test_map()

    store_repo = StoreRepository(asyncpg_pool)
    lootbox_repo = LootboxRepository(asyncpg_pool)
    service = StoreService(asyncpg_pool, State(), store_repo, lootbox_repo)

    async with asyncpg_pool.acquire() as conn:
        await conn.execute("SELECT store.check_and_generate_quest_rotation()")
        rotation_id = await conn.fetchval(
            "SELECT current_rotation_id FROM store.quest_config WHERE id = 1",
        )

        requirements = {"type": "complete_map", "map_id": map_id, "target": "complete"}
        quest_data = {
            "name": "Test Quest",
            "description": "Complete the test map",
            "difficulty": "easy",
            "coin_reward": 10,
            "xp_reward": 5,
            "requirements": requirements,
        }
        quest_id = await conn.fetchval(
            """
            INSERT INTO store.quests (name, description, quest_type, difficulty, coin_reward, xp_reward, requirements)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
            RETURNING id
            """,
            quest_data["name"],
            quest_data["description"],
            "global",
            quest_data["difficulty"],
            quest_data["coin_reward"],
            quest_data["xp_reward"],
            msgspec.json.encode(requirements).decode(),
        )
        progress_id = await conn.fetchval(
            """
            INSERT INTO store.user_quest_progress (user_id, rotation_id, quest_id, quest_data, progress)
            VALUES ($1, $2, $3, $4::jsonb, $5::jsonb)
            RETURNING id
            """,
            user_id,
            rotation_id,
            quest_id,
            msgspec.json.encode(quest_data).decode(),
            msgspec.json.encode({"completed": False}).decode(),
        )

    completed = await service.update_quest_progress(
        user_id=user_id,
        event_type="completion",
        event_data={
            "map_id": map_id,
            "difficulty": "Easy",
            "category": "Classic",
            "time": 30.0,
            "medal": None,
        },
    )

    assert len(completed) == 1
    assert completed[0]["progress_id"] == progress_id
    assert completed[0]["name"] == "Test Quest"

    async with asyncpg_pool.acquire() as conn:
        completed_at = await conn.fetchval(
            "SELECT completed_at FROM store.user_quest_progress WHERE id = $1",
            progress_id,
        )
    assert completed_at is not None


@pytest.mark.asyncio
async def test_claim_quest_updates_coin_and_xp(asyncpg_pool, create_test_user):
    """Claiming a quest grants coins and XP via lootbox.xp."""
    user_id = await create_test_user()

    store_repo = StoreRepository(asyncpg_pool)
    lootbox_repo = LootboxRepository(asyncpg_pool)
    service = StoreService(asyncpg_pool, State(), store_repo, lootbox_repo)

    async with asyncpg_pool.acquire() as conn:
        await conn.execute("SELECT store.check_and_generate_quest_rotation()")
        rotation_id = await conn.fetchval(
            "SELECT current_rotation_id FROM store.quest_config WHERE id = 1",
        )

        quest_data = {
            "name": "Claim Test",
            "description": "Claim quest rewards",
            "difficulty": "easy",
            "coin_reward": 100,
            "xp_reward": 25,
            "requirements": {"type": "complete_map", "map_id": 1, "target": "complete"},
        }
        progress_id = await conn.fetchval(
            """
            INSERT INTO store.user_quest_progress (user_id, rotation_id, quest_data, progress, completed_at)
            VALUES ($1, $2, $3::jsonb, $4::jsonb, now())
            RETURNING id
            """,
            user_id,
            rotation_id,
            msgspec.json.encode(quest_data).decode(),
            msgspec.json.encode({"completed": True}).decode(),
        )

    result = await service.claim_quest(user_id=user_id, progress_id=progress_id)

    assert result.success is True
    assert result.coins_earned == 100
    assert result.xp_earned == 25
    assert result.new_coin_balance == 100
    assert result.new_xp == 25

    async with asyncpg_pool.acquire() as conn:
        coins = await conn.fetchval("SELECT coins FROM core.users WHERE id = $1", user_id)
        xp_amount = await conn.fetchval("SELECT amount FROM lootbox.xp WHERE user_id = $1", user_id)
        claimed_at = await conn.fetchval(
            "SELECT claimed_at FROM store.user_quest_progress WHERE id = $1",
            progress_id,
        )

    assert coins == 100
    assert xp_amount == 25
    assert claimed_at is not None


@pytest.mark.asyncio
async def test_admin_update_user_quest_round_trip(asyncpg_pool, create_test_user):
    """Admin can complete and then un-complete a quest with auto-patched progress."""
    user_id = await create_test_user()

    store_repo = StoreRepository(asyncpg_pool)
    lootbox_repo = LootboxRepository(asyncpg_pool)
    service = StoreService(asyncpg_pool, State(), store_repo, lootbox_repo)

    async with asyncpg_pool.acquire() as conn:
        await conn.execute("SELECT store.check_and_generate_quest_rotation()")
        rotation_id = await conn.fetchval(
            "SELECT current_rotation_id FROM store.quest_config WHERE id = 1",
        )

        quest_data = {
            "name": "Admin Patch Test",
            "description": "Complete 5 maps",
            "difficulty": "easy",
            "coin_reward": 50,
            "xp_reward": 10,
            "requirements": {"type": "complete_maps", "count": 5, "difficulty": "any"},
        }
        progress_id = await conn.fetchval(
            """
            INSERT INTO store.user_quest_progress (user_id, rotation_id, quest_data, progress)
            VALUES ($1, $2, $3::jsonb, $4::jsonb)
            RETURNING id
            """,
            user_id,
            rotation_id,
            msgspec.json.encode(quest_data).decode(),
            msgspec.json.encode({"current": 2, "completed_map_ids": [1, 2]}).decode(),
        )

    # Mark as complete
    from genjishimada_sdk.store import AdminUpdateUserQuestRequest

    result = await service.admin_update_user_quest(
        user_id, progress_id, AdminUpdateUserQuestRequest(completed=True)
    )
    assert result.success is True

    # Verify DB: completed_at set, progress auto-patched
    async with asyncpg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT completed_at, progress FROM store.user_quest_progress WHERE id = $1",
            progress_id,
        )
    assert row["completed_at"] is not None
    assert row["progress"]["current"] == 5

    # Un-complete
    result = await service.admin_update_user_quest(
        user_id, progress_id, AdminUpdateUserQuestRequest(completed=False)
    )
    assert result.success is True

    # Verify DB: completed_at cleared
    async with asyncpg_pool.acquire() as conn:
        completed_at = await conn.fetchval(
            "SELECT completed_at FROM store.user_quest_progress WHERE id = $1",
            progress_id,
        )
    assert completed_at is None


@pytest.mark.asyncio
async def test_personal_improvement_bounty_falls_back_when_user_faster_than_percentile(
    asyncpg_pool, create_test_user, create_test_map, create_test_completion,
):
    """Fast user gets personal_best target when their time already beats the percentile."""
    fast_user = await create_test_user()
    slow_user_1 = await create_test_user()
    slow_user_2 = await create_test_user()
    map_id = await create_test_map(medals={"gold": 10.0, "silver": 20.0, "bronze": 30.0})

    # Slow users with high times push the 60th percentile above the fast user's best
    await create_test_completion(slow_user_1, map_id, time=200.0)
    await create_test_completion(slow_user_2, map_id, time=180.0)
    await create_test_completion(fast_user, map_id, time=25.0)

    store_repo = StoreRepository(asyncpg_pool)
    lootbox_repo = LootboxRepository(asyncpg_pool)
    service = StoreService(asyncpg_pool, State(), store_repo, lootbox_repo)

    bounty = await service._generate_personal_improvement_bounty(fast_user, uuid4())

    requirements = bounty["quest_data"]["requirements"]
    # The percentile target would be >= 25.0, so it should fall back to personal_best
    assert requirements["target_type"] == "personal_best"
    assert requirements["target_time"] == 25.0 * 0.9
    assert requirements["current_best"] == 25.0
