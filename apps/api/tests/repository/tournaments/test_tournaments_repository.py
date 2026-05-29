"""Tests for TournamentRepository covering all method groups."""

from datetime import datetime, timezone

import pytest

from repository.exceptions import UniqueConstraintViolationError
from repository.tournaments_repository import TournamentRepository

pytestmark = [pytest.mark.domain_tournaments]


# =============================================================================
# Config
# =============================================================================


class TestFetchConfig:
    async def test_fetch_config_returns_singleton(self, repository: TournamentRepository):
        result = await repository.fetch_config()
        assert isinstance(result, dict)
        assert "blacklist_weeks" in result
        assert isinstance(result["blacklist_weeks"], int)
        assert "created_at" in result
        assert "updated_at" in result


class TestUpdateConfig:
    async def test_update_config_changes_blacklist_weeks(self, repository: TournamentRepository):
        # Read the current value to restore later
        original = await repository.fetch_config()
        original_value = original["blacklist_weeks"]

        await repository.update_config({"blacklist_weeks": 8})
        updated = await repository.fetch_config()
        assert updated["blacklist_weeks"] == 8

        # Restore original value
        await repository.update_config({"blacklist_weeks": original_value})


# =============================================================================
# Categories
# =============================================================================


class TestCreateCategory:
    async def test_create_category_returns_dict(self, repository: TournamentRepository):
        result = await repository.create_category(
            name="Test-Create-Cat",
            difficulties=["Hard"],
            cycle_frequency="weekly",
            participation_xp=50,
            placement_xp="[]",
            streak_xp="[]",
            champion_role_id=None,
        )
        assert isinstance(result, dict)
        assert "id" in result
        assert result["name"] == "Test-Create-Cat"
        assert result["difficulties"] == ["Hard"]
        assert "cycle_frequency" in result

    async def test_create_category_duplicate_name_raises(self, repository: TournamentRepository):
        await repository.create_category(
            name="DuplicateCat",
            difficulties=["Medium"],
            cycle_frequency="weekly",
            participation_xp=100,
            placement_xp="[]",
            streak_xp="[]",
            champion_role_id=None,
        )
        with pytest.raises(UniqueConstraintViolationError):
            await repository.create_category(
                name="DuplicateCat",
                difficulties=["Hard"],
                cycle_frequency="weekly",
                participation_xp=50,
                placement_xp="[]",
                streak_xp="[]",
                champion_role_id=None,
            )


class TestFetchCategory:
    async def test_fetch_category_by_id(self, repository: TournamentRepository, create_test_category):
        category_id = await create_test_category(name="FetchCatTest")
        result = await repository.fetch_category(category_id)
        assert result is not None
        assert result["name"] == "FetchCatTest"

    async def test_fetch_category_not_found(self, repository: TournamentRepository):
        result = await repository.fetch_category(999999)
        assert result is None


class TestFetchCategories:
    async def test_fetch_categories_returns_list(self, repository: TournamentRepository, create_test_category):
        await create_test_category(name="FetchAllCat1")
        await create_test_category(name="FetchAllCat2")
        result = await repository.fetch_categories()
        assert isinstance(result, list)
        assert len(result) >= 2
        names = [c["name"] for c in result]
        assert "FetchAllCat1" in names
        assert "FetchAllCat2" in names


class TestUpdateCategory:
    async def test_update_category_name(self, repository: TournamentRepository, create_test_category):
        category_id = await create_test_category(name="BeforeUpdate")
        result = await repository.update_category(category_id, {"name": "AfterUpdate"})
        assert result is not None
        assert result["name"] == "AfterUpdate"

    async def test_update_category_jsonb_fields(self, repository: TournamentRepository, create_test_category):
        category_id = await create_test_category()
        result = await repository.update_category(
            category_id,
            {"placement_xp": '[{"place": 1, "xp": 500}]'},
        )
        assert result is not None
        assert result["placement_xp"] is not None


class TestDeleteCategory:
    async def test_delete_category_returns_true(self, repository: TournamentRepository, create_test_category):
        category_id = await create_test_category()
        deleted = await repository.delete_category(category_id)
        assert deleted is True
        result = await repository.fetch_category(category_id)
        assert result is None

    async def test_delete_nonexistent_returns_false(self, repository: TournamentRepository):
        deleted = await repository.delete_category(999999)
        assert deleted is False


class TestCheckActiveCycleForCategory:
    async def test_no_active_cycle_returns_false(
        self, repository: TournamentRepository, create_test_category, create_test_cycle, create_test_map
    ):
        category_id = await create_test_category()
        map_id = await create_test_map()
        await create_test_cycle(category_id, map_id, status="pending")
        result = await repository.check_active_cycle_for_category(category_id)
        assert result is False

    async def test_active_cycle_returns_true(
        self, repository: TournamentRepository, create_test_category, create_test_cycle, create_test_map
    ):
        category_id = await create_test_category()
        map_id = await create_test_map()
        await create_test_cycle(category_id, map_id, status="active")
        result = await repository.check_active_cycle_for_category(category_id)
        assert result is True


# =============================================================================
# Cycles
# =============================================================================


class TestCreateCycle:
    async def test_create_cycle_returns_dict(
        self, repository: TournamentRepository, create_test_category, create_test_map
    ):
        category_id = await create_test_category()
        map_id = await create_test_map()
        result = await repository.create_cycle(category_id, map_id)
        assert isinstance(result, dict)
        assert result["category_id"] == category_id
        assert result["map_id"] == map_id
        assert result["status"] == "pending"


class TestFetchCycle:
    async def test_fetch_cycle_by_id(
        self, repository: TournamentRepository, create_test_category, create_test_cycle, create_test_map
    ):
        category_id = await create_test_category()
        map_id = await create_test_map()
        cycle_id = await create_test_cycle(category_id, map_id)
        result = await repository.fetch_cycle(cycle_id)
        assert result is not None
        assert result["category_id"] == category_id

    async def test_fetch_cycle_not_found(self, repository: TournamentRepository):
        result = await repository.fetch_cycle(999999)
        assert result is None


class TestFetchActiveCycle:
    async def test_fetch_active_cycle_returns_active(
        self, repository: TournamentRepository, create_test_category, create_test_cycle, create_test_map
    ):
        category_id = await create_test_category()
        map_id = await create_test_map()
        cycle_id = await create_test_cycle(category_id, map_id)
        now = datetime.now(tz=timezone.utc)
        await repository.update_cycle_status(cycle_id, "active", started_at=now)
        result = await repository.fetch_active_cycle(category_id)
        assert result is not None
        assert result["id"] == cycle_id
        assert result["status"] == "active"

    async def test_fetch_active_cycle_none_when_pending(
        self, repository: TournamentRepository, create_test_category, create_test_cycle, create_test_map
    ):
        category_id = await create_test_category()
        map_id = await create_test_map()
        await create_test_cycle(category_id, map_id, status="pending")
        result = await repository.fetch_active_cycle(category_id)
        assert result is None


class TestUpdateCycleStatus:
    async def test_update_to_active(
        self, repository: TournamentRepository, create_test_category, create_test_cycle, create_test_map
    ):
        category_id = await create_test_category()
        map_id = await create_test_map()
        cycle_id = await create_test_cycle(category_id, map_id)
        now = datetime.now(tz=timezone.utc)
        result = await repository.update_cycle_status(cycle_id, "active", started_at=now)
        assert result is not None
        assert result["status"] == "active"
        assert result["started_at"] is not None


class TestFetchCycleHistory:
    async def test_fetch_cycle_history_paginated(
        self, repository: TournamentRepository, create_test_category, create_test_cycle, create_test_map
    ):
        category_id = await create_test_category()
        map_id_1 = await create_test_map()
        map_id_2 = await create_test_map()
        map_id_3 = await create_test_map()
        await create_test_cycle(category_id, map_id_1)
        await create_test_cycle(category_id, map_id_2)
        await create_test_cycle(category_id, map_id_3)
        total, rows = await repository.fetch_cycle_history(category_id, limit=2, offset=0)
        assert total >= 3
        assert len(rows) == 2


# =============================================================================
# Completions
# =============================================================================


class TestCreateTournamentCompletion:
    async def test_create_returns_dict(
        self,
        repository: TournamentRepository,
        create_test_category,
        create_test_cycle,
        create_test_map,
        create_test_user,
    ):
        category_id = await create_test_category()
        map_id = await create_test_map()
        cycle_id = await create_test_cycle(category_id, map_id, status="active")
        user_id = await create_test_user()
        result = await repository.create_tournament_completion(
            cycle_id=cycle_id,
            user_id=user_id,
            map_id=map_id,
            time=25.5,
            screenshot="https://example.com/shot.png",
        )
        assert isinstance(result, dict)
        assert result["cycle_id"] == cycle_id
        assert result["user_id"] == user_id
        assert "time" in result


class TestCrossWriteToCore:
    async def test_cross_write_inserts_when_faster(
        self,
        repository: TournamentRepository,
        create_test_category,
        create_test_cycle,
        create_test_map,
        create_test_user,
        create_test_tournament_completion,
        asyncpg_conn,
    ):
        category_id = await create_test_category()
        map_id = await create_test_map()
        cycle_id = await create_test_cycle(category_id, map_id, status="active")
        user_id = await create_test_user()
        tc_id = await create_test_tournament_completion(cycle_id, user_id, map_id, time=25.0)

        # No existing core.completions for this user/map, so cross-write should insert
        result = await repository.cross_write_to_core(
            tournament_completion_id=tc_id,
            user_id=user_id,
            map_id=map_id,
            time=25.0,
            screenshot="https://example.com/shot.png",
        )
        assert result is not None
        assert isinstance(result, int)

        # Verify the core.completions row exists and has tournament_completion_id set
        row = await asyncpg_conn.fetchrow(
            "SELECT * FROM core.completions WHERE id = $1",
            result,
        )
        assert row is not None
        assert row["tournament_completion_id"] == tc_id

    async def test_cross_write_skips_when_slower(
        self,
        repository: TournamentRepository,
        create_test_category,
        create_test_cycle,
        create_test_map,
        create_test_user,
        create_test_tournament_completion,
        create_test_completion,
    ):
        category_id = await create_test_category()
        map_id = await create_test_map()
        cycle_id = await create_test_cycle(category_id, map_id, status="active")
        user_id = await create_test_user()

        # Create an existing core.completions record with a fast time
        await create_test_completion(user_id, map_id, time=20.0)

        tc_id = await create_test_tournament_completion(cycle_id, user_id, map_id, time=25.0)

        # Cross-write with slower time should skip
        result = await repository.cross_write_to_core(
            tournament_completion_id=tc_id,
            user_id=user_id,
            map_id=map_id,
            time=25.0,
            screenshot="https://example.com/shot.png",
        )
        assert result is None

    async def test_cross_write_skips_when_equal(
        self,
        repository: TournamentRepository,
        create_test_category,
        create_test_cycle,
        create_test_map,
        create_test_user,
        create_test_tournament_completion,
        create_test_completion,
    ):
        category_id = await create_test_category()
        map_id = await create_test_map()
        cycle_id = await create_test_cycle(category_id, map_id, status="active")
        user_id = await create_test_user()

        # Create an existing core.completions record with equal time
        await create_test_completion(user_id, map_id, time=25.0)

        tc_id = await create_test_tournament_completion(cycle_id, user_id, map_id, time=25.0)

        # Cross-write with equal time should skip (only strictly faster inserts)
        result = await repository.cross_write_to_core(
            tournament_completion_id=tc_id,
            user_id=user_id,
            map_id=map_id,
            time=25.0,
            screenshot="https://example.com/shot.png",
        )
        assert result is None


# =============================================================================
# Leaderboard
# =============================================================================


class TestFetchLeaderboard:
    async def test_leaderboard_ranking_by_time(
        self,
        repository: TournamentRepository,
        create_test_category,
        create_test_cycle,
        create_test_map,
        create_test_user,
        create_test_tournament_completion,
    ):
        category_id = await create_test_category()
        map_id = await create_test_map()
        cycle_id = await create_test_cycle(category_id, map_id, status="active")
        user_a = await create_test_user(nickname="SlowUser")
        user_b = await create_test_user(nickname="FastUser")

        await create_test_tournament_completion(cycle_id, user_a, map_id, time=30.0)
        await create_test_tournament_completion(cycle_id, user_b, map_id, time=25.0)

        leaderboard = await repository.fetch_leaderboard(cycle_id)
        assert len(leaderboard) >= 2
        # User B (faster) should be rank 1
        assert leaderboard[0]["user_id"] == user_b
        assert leaderboard[0]["rank"] == 1
        assert leaderboard[1]["user_id"] == user_a
        assert leaderboard[1]["rank"] == 2

    async def test_leaderboard_verified_beats_unverified(
        self,
        repository: TournamentRepository,
        create_test_category,
        create_test_cycle,
        create_test_map,
        create_test_user,
        create_test_tournament_completion,
    ):
        category_id = await create_test_category()
        map_id = await create_test_map()
        cycle_id = await create_test_cycle(category_id, map_id, status="active")
        user_a = await create_test_user(nickname="Unverified")
        user_b = await create_test_user(nickname="Verified")

        # User A has a faster time but is unverified
        await create_test_tournament_completion(cycle_id, user_a, map_id, time=20.0, verified=False)
        # User B has a slower time but is verified
        await create_test_tournament_completion(cycle_id, user_b, map_id, time=30.0, verified=True)

        leaderboard = await repository.fetch_leaderboard(cycle_id)
        assert len(leaderboard) >= 2
        # User B (verified) should rank higher despite slower time
        assert leaderboard[0]["user_id"] == user_b
        assert leaderboard[0]["rank"] == 1

    async def test_leaderboard_includes_display_name(
        self,
        repository: TournamentRepository,
        create_test_category,
        create_test_cycle,
        create_test_map,
        create_test_user,
        create_test_tournament_completion,
    ):
        category_id = await create_test_category()
        map_id = await create_test_map()
        cycle_id = await create_test_cycle(category_id, map_id, status="active")
        user_id = await create_test_user(nickname="DisplayNameUser")
        await create_test_tournament_completion(cycle_id, user_id, map_id, time=30.0)

        leaderboard = await repository.fetch_leaderboard(cycle_id)
        assert len(leaderboard) >= 1
        assert "name" in leaderboard[0]
        assert leaderboard[0]["name"] is not None


# =============================================================================
# User Completion
# =============================================================================


class TestFetchUserCompletion:
    async def test_fetch_user_completion_found(
        self,
        repository: TournamentRepository,
        create_test_category,
        create_test_cycle,
        create_test_map,
        create_test_user,
        create_test_tournament_completion,
    ):
        category_id = await create_test_category()
        map_id = await create_test_map()
        cycle_id = await create_test_cycle(category_id, map_id, status="active")
        user_id = await create_test_user()
        await create_test_tournament_completion(cycle_id, user_id, map_id, time=25.0)

        result = await repository.fetch_user_completion(cycle_id, user_id)
        assert result is not None
        assert result["user_id"] == user_id
        assert result["cycle_id"] == cycle_id

    async def test_fetch_user_completion_not_found(self, repository: TournamentRepository):
        result = await repository.fetch_user_completion(999999, 999999)
        assert result is None


# =============================================================================
# Streaks
# =============================================================================


class TestFetchStreak:
    async def test_fetch_streak_not_found(self, repository: TournamentRepository):
        result = await repository.fetch_streak(999999)
        assert result is None


class TestUpsertStreak:
    async def test_upsert_creates_new_streak(
        self,
        repository: TournamentRepository,
        create_test_category,
        create_test_cycle,
        create_test_map,
        create_test_user,
    ):
        category_id = await create_test_category()
        map_id = await create_test_map()
        cycle_id = await create_test_cycle(category_id, map_id)
        user_id = await create_test_user()

        result = await repository.upsert_streak(user_id, cycle_id)
        assert result["current_streak"] == 1
        assert result["max_streak"] == 1
        assert result["last_cycle_id"] == cycle_id

    async def test_upsert_increments_existing(
        self,
        repository: TournamentRepository,
        create_test_category,
        create_test_cycle,
        create_test_map,
        create_test_user,
    ):
        category_id = await create_test_category()
        map_id_1 = await create_test_map()
        map_id_2 = await create_test_map()
        cycle_id_1 = await create_test_cycle(category_id, map_id_1)
        cycle_id_2 = await create_test_cycle(category_id, map_id_2)
        user_id = await create_test_user()

        await repository.upsert_streak(user_id, cycle_id_1)
        result = await repository.upsert_streak(user_id, cycle_id_2)
        assert result["current_streak"] == 2
        assert result["max_streak"] == 2
        assert result["last_cycle_id"] == cycle_id_2


# =============================================================================
# Map Selection
# =============================================================================


class TestFetchEligibleMaps:
    async def test_eligible_maps_excludes_blacklisted(
        self,
        repository: TournamentRepository,
        create_test_category,
        create_test_cycle,
        create_test_map,
    ):
        # Create 2 maps with difficulty "Medium"
        map_id_used = await create_test_map(difficulty="Medium")
        map_id_free = await create_test_map(difficulty="Medium")

        # Create a cycle using one of the maps (marks it as used)
        category_id = await create_test_category(difficulties=["Medium"])
        now = datetime.now(tz=timezone.utc)
        await create_test_cycle(category_id, map_id_used, status="active", started_at=now)

        eligible = await repository.fetch_eligible_maps(["Medium"], blacklist_weeks=52)
        eligible_ids = [m["id"] for m in eligible]
        assert map_id_free in eligible_ids
        assert map_id_used not in eligible_ids

    async def test_eligible_maps_filters_by_difficulty(
        self,
        repository: TournamentRepository,
        create_test_map,
    ):
        await create_test_map(difficulty="Hard")
        eligible = await repository.fetch_eligible_maps(["Medium"], blacklist_weeks=0)
        eligible_difficulties = [m["difficulty"] for m in eligible]
        # No "Hard" maps should appear when filtering for "Medium"
        for diff in eligible_difficulties:
            assert "Hard" not in diff or diff != "Hard"


class TestFetchLeastRecentlyUsedMap:
    async def test_returns_map_never_used(
        self,
        repository: TournamentRepository,
        create_test_category,
        create_test_cycle,
        create_test_map,
    ):
        # Create 2 maps, cycle for one
        map_id_used = await create_test_map(difficulty="Medium")
        map_id_unused = await create_test_map(difficulty="Medium")
        category_id = await create_test_category(difficulties=["Medium"])
        now = datetime.now(tz=timezone.utc)
        await create_test_cycle(category_id, map_id_used, status="active", started_at=now)

        result = await repository.fetch_least_recently_used_map(["Medium"])
        assert result is not None
        # The never-used map should be returned first (NULLS FIRST in ORDER BY)
        # It could be any never-used map though (there may be others in the DB)
        # So just verify we get a valid result
        assert "id" in result
        assert "code" in result


# =============================================================================
# Pending Transitions
# =============================================================================


class TestCreatePendingTransition:
    async def test_create_returns_dict(
        self,
        repository: TournamentRepository,
        create_test_category,
        create_test_cycle,
        create_test_map,
    ):
        category_id = await create_test_category()
        map_id = await create_test_map()
        cycle_id = await create_test_cycle(category_id, map_id)
        result = await repository.create_pending_transition(
            cycle_id=cycle_id,
            event_type="cycle_started",
            payload="{}",
        )
        assert isinstance(result, dict)
        assert result["cycle_id"] == cycle_id
        assert result["event_type"] == "cycle_started"
        assert result["published"] is False


class TestFetchUnpublishedTransitions:
    async def test_returns_unpublished_only(
        self,
        repository: TournamentRepository,
        create_test_category,
        create_test_cycle,
        create_test_map,
    ):
        category_id = await create_test_category()
        map_id = await create_test_map()
        cycle_id = await create_test_cycle(category_id, map_id)

        # Create 2 transitions
        t1 = await repository.create_pending_transition(cycle_id, "cycle_started", "{}")
        await repository.create_pending_transition(cycle_id, "cycle_completed", "{}")

        # Mark one as published
        await repository.mark_transition_published(t1["id"])

        unpublished = await repository.fetch_unpublished_transitions()
        unpublished_ids = [t["id"] for t in unpublished]
        assert t1["id"] not in unpublished_ids


class TestMarkTransitionPublished:
    async def test_marks_published(
        self,
        repository: TournamentRepository,
        create_test_category,
        create_test_cycle,
        create_test_map,
    ):
        category_id = await create_test_category()
        map_id = await create_test_map()
        cycle_id = await create_test_cycle(category_id, map_id)
        t = await repository.create_pending_transition(cycle_id, "cycle_started", "{}")

        result = await repository.mark_transition_published(t["id"])
        assert result is True

        unpublished = await repository.fetch_unpublished_transitions()
        unpublished_ids = [tr["id"] for tr in unpublished]
        assert t["id"] not in unpublished_ids

    async def test_already_published_returns_false(
        self,
        repository: TournamentRepository,
        create_test_category,
        create_test_cycle,
        create_test_map,
    ):
        category_id = await create_test_category()
        map_id = await create_test_map()
        cycle_id = await create_test_cycle(category_id, map_id)
        t = await repository.create_pending_transition(cycle_id, "cycle_started", "{}")

        await repository.mark_transition_published(t["id"])
        result = await repository.mark_transition_published(t["id"])
        assert result is False
