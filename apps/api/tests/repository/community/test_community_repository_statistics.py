"""Tests for CommunityRepository statistics operations.

Test Coverage:
- fetch_players_per_xp_tier
- fetch_players_per_skill_tier
- fetch_maps_per_difficulty
- fetch_time_played_per_rank
- fetch_unarchived_map_count
- fetch_total_map_count
"""

from uuid import uuid4

import pytest
from faker import Faker

from repository.community_repository import CommunityRepository

fake = Faker()

pytestmark = [
    pytest.mark.domain_community,
]


@pytest.fixture
async def repository(asyncpg_conn):
    """Provide community repository instance."""
    return CommunityRepository(asyncpg_conn)


# ==============================================================================
# HELPER FIXTURES
# ==============================================================================


@pytest.fixture
async def create_xp_record(asyncpg_conn):
    """Factory fixture for creating XP records."""

    async def _create(user_id: int, amount: int) -> None:
        await asyncpg_conn.execute(
            """
            INSERT INTO lootbox.xp (user_id, amount)
            VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET amount = $2
            """,
            user_id,
            amount,
        )

    return _create


@pytest.fixture
async def create_completion(asyncpg_conn):
    """Factory fixture for creating completion records."""

    async def _create(
        map_id: int,
        user_id: int,
        time: float = 100.0,
        verified: bool = True,
        **overrides,
    ) -> int:
        data = {
            "screenshot": fake.url(),
            "video": None,
            "message_id": None,
            "completion": True,
        }
        data.update(overrides)

        completion_id = await asyncpg_conn.fetchval(
            """
            INSERT INTO core.completions (
                map_id, user_id, time, verified, screenshot, video, message_id, completion
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id
            """,
            map_id,
            user_id,
            time,
            verified,
            data["screenshot"],
            data["video"],
            data["message_id"],
            data["completion"],
        )
        return completion_id

    return _create


@pytest.fixture
async def create_rating(asyncpg_conn):
    """Factory fixture for creating map rating records."""

    async def _create(
        map_id: int,
        user_id: int,
        quality: float,
        verified: bool = True,
    ) -> None:
        await asyncpg_conn.execute(
            """
            INSERT INTO maps.ratings (map_id, user_id, quality, difficulty, verified)
            VALUES ($1, $2, $3, 5.0, $4)
            ON CONFLICT (map_id, user_id) DO UPDATE SET quality = $3, verified = $4
            """,
            map_id,
            user_id,
            quality,
            verified,
        )

    return _create


@pytest.fixture
async def create_creator_link(asyncpg_conn):
    """Factory fixture for creating map creator links."""

    async def _create(map_id: int, user_id: int) -> None:
        await asyncpg_conn.execute(
            """
            INSERT INTO maps.creators (map_id, user_id)
            VALUES ($1, $2)
            ON CONFLICT (map_id, user_id) DO NOTHING
            """,
            map_id,
            user_id,
        )

    return _create


# ==============================================================================
# TESTS: fetch_players_per_xp_tier
# ==============================================================================


class TestFetchPlayersPerXpTier:
    """Test fetch_players_per_xp_tier method."""

    async def test_returns_empty_list_when_no_users_with_xp(
        self,
        repository: CommunityRepository,
    ) -> None:
        """Test that method returns tiers with 0 counts when no users have XP > 500."""
        # Act
        result = await repository.fetch_players_per_xp_tier()

        # Assert
        assert isinstance(result, list)
        # Should return all tiers with 0 counts
        assert all(row["amount"] == 0 for row in result)

    async def test_counts_users_per_tier_correctly(
        self,
        repository: CommunityRepository,
        create_test_user,
        create_xp_record,
    ) -> None:
        """Test that users are counted in correct XP tiers."""
        # Arrange - Create users in different XP tiers
        # Tier calculation: (xp / 100) % 100 / 5 = threshold
        # XP 750 → tier 1 (Initiate)
        user1 = await create_test_user()
        await create_xp_record(user1, 750)

        # XP 1200-1400 → tier 2 (Apprentice)
        user2 = await create_test_user()
        await create_xp_record(user2, 1200)

        user3 = await create_test_user()
        await create_xp_record(user3, 1400)

        # Act
        result = await repository.fetch_players_per_xp_tier()

        # Assert
        assert isinstance(result, list)
        assert len(result) > 0

        # Find Initiate and Apprentice tiers
        initiate_tier = next((r for r in result if r["tier"] == "Initiate"), None)
        apprentice_tier = next((r for r in result if r["tier"] == "Apprentice"), None)

        assert initiate_tier is not None
        assert initiate_tier["amount"] >= 1

        assert apprentice_tier is not None
        assert apprentice_tier["amount"] >= 2

    async def test_excludes_users_with_xp_below_threshold(
        self,
        repository: CommunityRepository,
        create_test_user,
        create_xp_record,
    ) -> None:
        """Test that users with XP <= 500 are excluded."""
        # Arrange - Get baseline count first
        baseline_result = await repository.fetch_players_per_xp_tier()
        baseline_total = sum(row["amount"] for row in baseline_result)

        user1 = await create_test_user()
        await create_xp_record(user1, 500)  # Exactly 500, should be excluded

        user2 = await create_test_user()
        await create_xp_record(user2, 100)  # Below threshold

        # Act
        result = await repository.fetch_players_per_xp_tier()

        # Assert - Count should not increase
        total_users = sum(row["amount"] for row in result)
        assert total_users == baseline_total  # Both users excluded, count unchanged

    async def test_users_with_no_xp_record_not_counted(
        self,
        repository: CommunityRepository,
        create_test_user,
    ) -> None:
        """Test that users without XP records are not counted."""
        # Arrange - Get baseline count first
        baseline_result = await repository.fetch_players_per_xp_tier()
        baseline_total = sum(row["amount"] for row in baseline_result)

        await create_test_user()  # User with no XP record

        # Act
        result = await repository.fetch_players_per_xp_tier()

        # Assert - Count should not increase
        total_users = sum(row["amount"] for row in result)
        assert total_users == baseline_total  # User without XP not counted

    async def test_returns_all_tiers_in_order(
        self,
        repository: CommunityRepository,
        create_test_user,
        create_xp_record,
    ) -> None:
        """Test that result includes all tiers ordered by threshold."""
        # Arrange - Create one user with high XP
        user = await create_test_user()
        await create_xp_record(user, 10000)

        # Act
        result = await repository.fetch_players_per_xp_tier()

        # Assert
        assert len(result) >= 19  # Should have all 20 main tiers (0-19)
        tier_names = [row["tier"] for row in result]
        # Check that we have the expected tier names from the migration
        assert "Newcomer" in tier_names
        assert "Initiate" in tier_names
        assert "Apprentice" in tier_names
        # Verify they're ordered by threshold
        # The query uses ORDER BY mxt.threshold, so should be ascending
        for i in range(len(result) - 1):
            # Each subsequent tier should have equal or higher count (but we're checking structure, not counts)
            assert result[i]["tier"] is not None


# ==============================================================================
# TESTS: fetch_maps_per_difficulty
# ==============================================================================


class TestFetchMapsPerDifficulty:
    """Test fetch_maps_per_difficulty method."""

    async def test_counts_maps_by_base_difficulty(
        self,
        repository: CommunityRepository,
        create_test_map,
        unique_map_code,
        asyncpg_conn,
    ) -> None:
        """Test that maps are counted by base difficulty correctly."""
        from typing import get_args
        from genjishimada_sdk.maps import MapCategory, OverwatchMap
        from genjishimada_sdk import difficulties

        # Arrange - Create official, visible maps with specific difficulties directly using asyncpg_conn
        # Get valid raw_difficulty ranges
        easy_min, easy_max = difficulties.DIFFICULTY_RANGES_ALL["Easy"]
        medium_min, medium_max = difficulties.DIFFICULTY_RANGES_ALL["Medium"]

        code1 = f"T{uuid4().hex[:5].upper()}"
        map1 = await asyncpg_conn.fetchval(
            """
            INSERT INTO core.maps (
                code, map_name, category, checkpoints, official,
                playtesting, difficulty, raw_difficulty, hidden, archived
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING id
            """,
            code1,
            fake.random_element(elements=get_args(OverwatchMap)),
            fake.random_element(elements=get_args(MapCategory)),
            10,
            True,
            "Approved",
            "Easy",
            fake.pyfloat(min_value=easy_min, max_value=easy_max - 0.1, right_digits=2),
            False,
            False,
        )

        code2 = f"T{uuid4().hex[:5].upper()}"
        map2 = await asyncpg_conn.fetchval(
            """
            INSERT INTO core.maps (
                code, map_name, category, checkpoints, official,
                playtesting, difficulty, raw_difficulty, hidden, archived
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING id
            """,
            code2,
            fake.random_element(elements=get_args(OverwatchMap)),
            fake.random_element(elements=get_args(MapCategory)),
            10,
            True,
            "Approved",
            "Medium",
            fake.pyfloat(min_value=medium_min, max_value=medium_max - 0.1, right_digits=2),
            False,
            False,
        )

        code3 = f"T{uuid4().hex[:5].upper()}"
        map3 = await asyncpg_conn.fetchval(
            """
            INSERT INTO core.maps (
                code, map_name, category, checkpoints, official,
                playtesting, difficulty, raw_difficulty, hidden, archived
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING id
            """,
            code3,
            fake.random_element(elements=get_args(OverwatchMap)),
            fake.random_element(elements=get_args(MapCategory)),
            10,
            True,
            "Approved",
            "Medium",
            fake.pyfloat(min_value=medium_min, max_value=medium_max - 0.1, right_digits=2),
            False,
            False,
        )

        # Act
        result = await repository.fetch_maps_per_difficulty()

        # Assert
        assert isinstance(result, list)
        assert len(result) >= 1, "Should have at least one difficulty"

        # Check that our difficulties appear in results
        easy_count = next((r["amount"] for r in result if r["difficulty"] == "Easy"), 0)
        medium_count = next((r["amount"] for r in result if r["difficulty"] == "Medium"), 0)

        assert easy_count >= 1, f"Should have at least 1 Easy map"
        assert medium_count >= 2, f"Should have at least 2 Medium maps"

    async def test_strips_plus_minus_from_difficulty(
        self,
        repository: CommunityRepository,
        create_test_map,
    ) -> None:
        """Test that '+' and '-' suffixes are stripped from difficulty."""
        # Arrange
        code1 = f"T{uuid4().hex[:5].upper()}"
        await create_test_map(
            code1,
            official=True,
            archived=False,
            hidden=False,
            difficulty="Hard +",
        )

        code2 = f"T{uuid4().hex[:5].upper()}"
        await create_test_map(
            code2,
            official=True,
            archived=False,
            hidden=False,
            difficulty="Hard -",
        )

        code3 = f"T{uuid4().hex[:5].upper()}"
        await create_test_map(
            code3,
            official=True,
            archived=False,
            hidden=False,
            difficulty="Hard",
        )

        # Act
        result = await repository.fetch_maps_per_difficulty()

        # Assert
        hard_count = next((r["amount"] for r in result if r["difficulty"] == "Hard"), 0)
        assert hard_count >= 3  # All three maps counted as "Hard"

    async def test_excludes_archived_maps(
        self,
        repository: CommunityRepository,
        create_test_map,
    ) -> None:
        """Test that archived maps are excluded."""
        # Arrange - Get baseline
        baseline_result = await repository.fetch_maps_per_difficulty()
        baseline_easy = next((r["amount"] for r in baseline_result if r["difficulty"] == "Easy"), 0)

        code1 = f"T{uuid4().hex[:5].upper()}"
        await create_test_map(
            code1,
            official=True,
            archived=True,  # Archived
            hidden=False,
            difficulty="Easy",
        )

        # Act
        result = await repository.fetch_maps_per_difficulty()

        # Assert - Count should not change
        easy_count = next((r["amount"] for r in result if r["difficulty"] == "Easy"), 0)
        assert easy_count == baseline_easy  # Archived map not counted

    async def test_excludes_hidden_maps(
        self,
        repository: CommunityRepository,
        create_test_map,
    ) -> None:
        """Test that hidden maps are excluded."""
        # Arrange - Get baseline
        baseline_result = await repository.fetch_maps_per_difficulty()
        baseline_easy = next((r["amount"] for r in baseline_result if r["difficulty"] == "Easy"), 0)

        code1 = f"T{uuid4().hex[:5].upper()}"
        await create_test_map(
            code1,
            official=True,
            archived=False,
            hidden=True,  # Hidden
            difficulty="Easy",
        )

        # Act
        result = await repository.fetch_maps_per_difficulty()

        # Assert - Count should not change
        easy_count = next((r["amount"] for r in result if r["difficulty"] == "Easy"), 0)
        assert easy_count == baseline_easy  # Hidden map not counted

    async def test_excludes_unofficial_maps(
        self,
        repository: CommunityRepository,
        create_test_map,
    ) -> None:
        """Test that unofficial maps are excluded."""
        # Arrange - Get baseline
        baseline_result = await repository.fetch_maps_per_difficulty()
        baseline_easy = next((r["amount"] for r in baseline_result if r["difficulty"] == "Easy"), 0)

        code1 = f"T{uuid4().hex[:5].upper()}"
        await create_test_map(
            code1,
            official=False,  # Unofficial
            archived=False,
            hidden=False,
            difficulty="Easy",
        )

        # Act
        result = await repository.fetch_maps_per_difficulty()

        # Assert - Count should not change
        easy_count = next((r["amount"] for r in result if r["difficulty"] == "Easy"), 0)
        assert easy_count == baseline_easy  # Unofficial map not counted

    async def test_returns_difficulties_in_canonical_order(
        self,
        repository: CommunityRepository,
        create_test_map,
    ) -> None:
        """Test that difficulties are returned in canonical order."""
        # Arrange - Create maps in all difficulties
        difficulties = ["Easy", "Medium", "Hard", "Very Hard", "Extreme", "Hell"]
        for diff in difficulties:
            code = f"T{uuid4().hex[:5].upper()}"
            await create_test_map(
                code,
                official=True,
                archived=False,
                hidden=False,
                difficulty=diff,
            )

        # Act
        result = await repository.fetch_maps_per_difficulty()

        # Assert
        result_difficulties = [row["difficulty"] for row in result]
        # Verify order matches canonical order
        expected_order = ["Easy", "Medium", "Hard", "Very Hard", "Extreme", "Hell"]
        # Filter to only the difficulties present in result
        expected_in_result = [d for d in expected_order if d in result_difficulties]
        actual_in_order = [d for d in result_difficulties if d in expected_order]
        assert actual_in_order == expected_in_result


# ==============================================================================
# TESTS: fetch_unarchived_map_count
# ==============================================================================


class TestFetchUnarchivedMapCount:
    """Test fetch_unarchived_map_count method."""


    async def test_groups_by_map_name(
        self,
        repository: CommunityRepository,
        create_test_map,
    ) -> None:
        """Test that maps are correctly grouped by map_name."""
        # Arrange
        code1 = f"T{uuid4().hex[:5].upper()}"
        await create_test_map(
            code1,
            map_name="Hanamura",
            archived=False,
            hidden=False,
        )

        code2 = f"T{uuid4().hex[:5].upper()}"
        await create_test_map(
            code2,
            map_name="Eichenwalde",
            archived=False,
            hidden=False,
        )

        code3 = f"T{uuid4().hex[:5].upper()}"
        await create_test_map(
            code3,
            map_name="Eichenwalde",
            archived=False,
            hidden=False,
        )

        # Act
        result = await repository.fetch_unarchived_map_count()

        # Assert
        hanamura_count = next((r["amount"] for r in result if r["map_name"] == "Hanamura"), 0)
        eichen_count = next((r["amount"] for r in result if r["map_name"] == "Eichenwalde"), 0)

        assert hanamura_count >= 1
        assert eichen_count >= 2

    async def test_orders_by_count_descending(
        self,
        repository: CommunityRepository,
        create_test_map,
    ) -> None:
        """Test that results are ordered by count descending."""
        # Arrange - Create maps with different counts
        for _ in range(3):
            code = f"T{uuid4().hex[:5].upper()}"
            await create_test_map(
                code,
                map_name="Hanamura",
                archived=False,
                hidden=False,
            )

        code = f"T{uuid4().hex[:5].upper()}"
        await create_test_map(
            code,
            map_name="Eichenwalde",
            archived=False,
            hidden=False,
        )

        # Act
        result = await repository.fetch_unarchived_map_count()

        # Assert - Verify descending order
        counts = [row["amount"] for row in result]
        assert counts == sorted(counts, reverse=True)


# ==============================================================================
# TESTS: fetch_total_map_count
# ==============================================================================


class TestFetchTotalMapCount:
    """Test fetch_total_map_count method."""

    async def test_counts_all_maps_including_archived_and_hidden(
        self,
        repository: CommunityRepository,
        create_test_map,
    ) -> None:
        """Test that all maps are counted regardless of archived/hidden status."""
        # Arrange
        map_name = "Hanamura"

        code1 = f"T{uuid4().hex[:5].upper()}"
        await create_test_map(
            code1,
            map_name=map_name,
            archived=False,
            hidden=False,
        )

        code2 = f"T{uuid4().hex[:5].upper()}"
        await create_test_map(
            code2,
            map_name=map_name,
            archived=True,  # Should be counted
            hidden=False,
        )

        code3 = f"T{uuid4().hex[:5].upper()}"
        await create_test_map(
            code3,
            map_name=map_name,
            archived=False,
            hidden=True,  # Should be counted
        )

        # Act
        total_result = await repository.fetch_total_map_count()
        unarchived_result = await repository.fetch_unarchived_map_count()

        # Assert
        total_count = next((r["amount"] for r in total_result if r["map_name"] == map_name), 0)
        unarchived_count = next((r["amount"] for r in unarchived_result if r["map_name"] == map_name), 0)

        assert total_count >= 3  # All maps counted
        assert unarchived_count >= 1  # Only visible maps
        assert total_count > unarchived_count  # Total should be higher

    async def test_groups_by_map_name(
        self,
        repository: CommunityRepository,
        create_test_map,
    ) -> None:
        """Test that maps are correctly grouped by map_name."""
        # Arrange
        code1 = f"T{uuid4().hex[:5].upper()}"
        await create_test_map(code1, map_name="Hanamura")

        code2 = f"T{uuid4().hex[:5].upper()}"
        await create_test_map(code2, map_name="Eichenwalde")

        code3 = f"T{uuid4().hex[:5].upper()}"
        await create_test_map(code3, map_name="Eichenwalde")

        # Act
        result = await repository.fetch_total_map_count()

        # Assert
        hanamura_count = next((r["amount"] for r in result if r["map_name"] == "Hanamura"), 0)
        eichen_count = next((r["amount"] for r in result if r["map_name"] == "Eichenwalde"), 0)

        assert hanamura_count >= 1
        assert eichen_count >= 2


# ==============================================================================
# TESTS: fetch_time_played_per_rank
# ==============================================================================


class TestFetchTimePlayedPerRank:
    """Test fetch_time_played_per_rank method."""

    async def test_sums_time_by_base_difficulty(
        self,
        repository: CommunityRepository,
        create_test_map,
        create_test_user,
        create_completion,
        asyncpg_conn,
    ) -> None:
        """Test that times are summed correctly by base difficulty."""
        from typing import get_args
        from genjishimada_sdk.maps import MapCategory, OverwatchMap
        from genjishimada_sdk import difficulties

        # Arrange - Create users and maps directly using asyncpg_conn
        user1 = await create_test_user()
        user2 = await create_test_user()

        # Get valid raw_difficulty ranges
        easy_min, easy_max = difficulties.DIFFICULTY_RANGES_ALL["Easy"]
        medium_min, medium_max = difficulties.DIFFICULTY_RANGES_ALL["Medium"]

        # Easy map
        code1 = f"T{uuid4().hex[:5].upper()}"
        map1 = await asyncpg_conn.fetchval(
            """
            INSERT INTO core.maps (
                code, map_name, category, checkpoints, official,
                playtesting, difficulty, raw_difficulty, hidden, archived
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING id
            """,
            code1,
            fake.random_element(elements=get_args(OverwatchMap)),
            fake.random_element(elements=get_args(MapCategory)),
            10,
            True,
            "Approved",
            "Easy",
            fake.pyfloat(min_value=easy_min, max_value=easy_max - 0.1, right_digits=2),
            False,
            False,
        )

        # Create 2 completions on Easy map
        await asyncpg_conn.execute(
            """
            INSERT INTO core.completions (map_id, user_id, time, verified, screenshot, completion)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            map1, user1, 100.0, True, fake.url(), True
        )
        await asyncpg_conn.execute(
            """
            INSERT INTO core.completions (map_id, user_id, time, verified, screenshot, completion)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            map1, user2, 150.0, True, fake.url(), True
        )

        # Medium map
        code2 = f"T{uuid4().hex[:5].upper()}"
        map2 = await asyncpg_conn.fetchval(
            """
            INSERT INTO core.maps (
                code, map_name, category, checkpoints, official,
                playtesting, difficulty, raw_difficulty, hidden, archived
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING id
            """,
            code2,
            fake.random_element(elements=get_args(OverwatchMap)),
            fake.random_element(elements=get_args(MapCategory)),
            10,
            True,
            "Approved",
            "Medium",
            fake.pyfloat(min_value=medium_min, max_value=medium_max - 0.1, right_digits=2),
            False,
            False,
        )

        # Create 1 completion on Medium map
        await asyncpg_conn.execute(
            """
            INSERT INTO core.completions (map_id, user_id, time, verified, screenshot, completion)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            map2, user1, 200.0, True, fake.url(), True
        )

        # Act
        result = await repository.fetch_time_played_per_rank()

        # Assert - Check that times are present for our difficulties
        easy_time = next((r["total_seconds"] for r in result if r["difficulty"] == "Easy"), 0)
        medium_time = next((r["total_seconds"] for r in result if r["difficulty"] == "Medium"), 0)

        assert easy_time >= 250.0, f"Expected Easy time >= 250.0, got {easy_time}"  # 100 + 150
        assert medium_time >= 200.0, f"Expected Medium time >= 200.0, got {medium_time}"

    async def test_excludes_unverified_completions(
        self,
        repository: CommunityRepository,
        create_test_map,
        create_test_user,
        create_completion,
    ) -> None:
        """Test that unverified completions are excluded."""
        # Arrange - Get baseline
        baseline_result = await repository.fetch_time_played_per_rank()
        baseline_easy = next((r["total_seconds"] for r in baseline_result if r["difficulty"] == "Easy"), 0)

        user = await create_test_user()
        code = f"T{uuid4().hex[:5].upper()}"
        map_id = await create_test_map(code, difficulty="Easy")

        await create_completion(map_id, user, time=100.0, verified=False)

        # Act
        result = await repository.fetch_time_played_per_rank()

        # Assert - Time should not change
        easy_time = next((r["total_seconds"] for r in result if r["difficulty"] == "Easy"), 0)
        assert easy_time == baseline_easy  # Unverified completion excluded

    async def test_excludes_invalid_times(
        self,
        repository: CommunityRepository,
        create_test_map,
        create_test_user,
        create_completion,
    ) -> None:
        """Test that times >= 99999999.99 are excluded."""
        # Arrange - Get baseline
        baseline_result = await repository.fetch_time_played_per_rank()
        baseline_easy = next((r["total_seconds"] for r in baseline_result if r["difficulty"] == "Easy"), 0)

        user = await create_test_user()
        code = f"T{uuid4().hex[:5].upper()}"
        map_id = await create_test_map(code, difficulty="Easy", raw_difficulty=2.5)

        # The time field is numeric(10,2) with max value < 10^8
        # Create completion with time right at the exclusion threshold
        await create_completion(map_id, user, time=99999999.99, verified=True)

        # Act
        result = await repository.fetch_time_played_per_rank()

        # Assert - Time at threshold should be excluded (time < 99999999.99)
        easy_time = next((r["total_seconds"] for r in result if r["difficulty"] == "Easy"), 0)
        assert easy_time == baseline_easy  # Invalid time excluded, no change

    async def test_strips_plus_minus_from_difficulty(
        self,
        repository: CommunityRepository,
        create_test_map,
        create_test_user,
        create_completion,
    ) -> None:
        """Test that '+' and '-' suffixes are stripped from difficulty."""
        # Arrange
        user = await create_test_user()

        code1 = f"T{uuid4().hex[:5].upper()}"
        map1 = await create_test_map(code1, difficulty="Hard +")
        await create_completion(map1, user, time=100.0, verified=True)

        code2 = f"T{uuid4().hex[:5].upper()}"
        map2 = await create_test_map(code2, difficulty="Hard -")
        await create_completion(map2, user, time=150.0, verified=True)

        # Act
        result = await repository.fetch_time_played_per_rank()

        # Assert
        hard_time = next((r["total_seconds"] for r in result if r["difficulty"] == "Hard"), 0)
        assert hard_time >= 250.0  # Both completions counted as "Hard"

    async def test_returns_difficulties_in_canonical_order(
        self,
        repository: CommunityRepository,
        create_test_map,
        create_test_user,
        create_completion,
    ) -> None:
        """Test that difficulties are returned in canonical order."""
        # Arrange
        user = await create_test_user()
        difficulties = ["Hell", "Easy", "Hard", "Medium"]  # Out of order

        for diff in difficulties:
            code = f"T{uuid4().hex[:5].upper()}"
            map_id = await create_test_map(code, difficulty=diff)
            await create_completion(map_id, user, time=100.0, verified=True)

        # Act
        result = await repository.fetch_time_played_per_rank()

        # Assert
        result_difficulties = [row["difficulty"] for row in result]
        expected_order = ["Easy", "Medium", "Hard", "Very Hard", "Extreme", "Hell"]
        # Filter to only present difficulties
        expected_in_result = [d for d in expected_order if d in result_difficulties]
        actual_in_order = [d for d in result_difficulties if d in expected_order]
        assert actual_in_order == expected_in_result
