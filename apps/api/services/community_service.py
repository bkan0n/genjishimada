"""Community service for leaderboard and statistics queries."""

from __future__ import annotations

from typing import Literal

import msgspec
from asyncpg import Pool
from genjishimada_sdk.completions import MapRecordProgressionResponse, TimePlayedPerRankResponse
from genjishimada_sdk.maps import (
    MapCompletionStatisticsResponse,
    MapCountsResponse,
    MapPerDifficultyStatisticsResponse,
    OverwatchCode,
    PopularMapsStatisticsResponse,
    TopCreatorsResponse,
)
from genjishimada_sdk.users import CommunityLeaderboardResponse
from genjishimada_sdk.xp import PlayersPerSkillTierResponse, PlayersPerXPTierResponse
from litestar.datastructures import State

from repository.community_repository import CommunityRepository

from .base import BaseService


class CommunityService(BaseService):
    """Service for community statistics business logic."""

    def __init__(self, pool: Pool, state: State, community_repo: CommunityRepository) -> None:
        """Initialize community service.

        Args:
            pool: AsyncPG connection pool.
            state: Application state.
            community_repo: Community repository.
        """
        super().__init__(pool, state)
        self._community_repo = community_repo

    async def get_community_leaderboard(  # noqa: PLR0913
        self,
        name: str | None = None,
        tier_name: str | None = None,
        skill_rank: str | None = None,
        sort_column: Literal[
            "xp_amount",
            "nickname",
            "prestige_level",
            "wr_count",
            "map_count",
            "playtest_count",
            "discord_tag",
            "skill_rank",
        ] = "xp_amount",
        sort_direction: Literal["asc", "desc"] = "asc",
        page_size: int = 10,
        page_number: int = 1,
    ) -> list[CommunityLeaderboardResponse]:
        """Get community leaderboard with filtering and pagination."""
        rows = await self._community_repo.fetch_community_leaderboard(
            name=name,
            tier_name=tier_name,
            skill_rank=skill_rank,
            sort_column=sort_column,
            sort_direction=sort_direction,
            page_size=page_size,
            page_number=page_number,
        )
        return msgspec.convert(rows, list[CommunityLeaderboardResponse])

    async def get_players_per_xp_tier(self) -> list[PlayersPerXPTierResponse]:
        """Get player counts per XP tier."""
        rows = await self._community_repo.fetch_players_per_xp_tier()
        return msgspec.convert(rows, list[PlayersPerXPTierResponse])

    async def get_players_per_skill_tier(self) -> list[PlayersPerSkillTierResponse]:
        """Get player counts per skill tier."""
        rows = await self._community_repo.fetch_players_per_skill_tier()
        return msgspec.convert(rows, list[PlayersPerSkillTierResponse])

    async def get_map_completion_statistics(self, code: OverwatchCode) -> list[MapCompletionStatisticsResponse]:
        """Get completion stats for a map."""
        rows = await self._community_repo.fetch_map_completion_statistics(code)
        return msgspec.convert(rows, list[MapCompletionStatisticsResponse])

    async def get_maps_per_difficulty(self) -> list[MapPerDifficultyStatisticsResponse]:
        """Get map counts per difficulty."""
        rows = await self._community_repo.fetch_maps_per_difficulty()
        return msgspec.convert(rows, list[MapPerDifficultyStatisticsResponse])

    async def get_popular_maps(self) -> list[PopularMapsStatisticsResponse]:
        """Get popular maps per difficulty."""
        rows = await self._community_repo.fetch_popular_maps()
        return msgspec.convert(rows, list[PopularMapsStatisticsResponse])

    async def get_popular_creators(self) -> list[TopCreatorsResponse]:
        """Get popular creators by average quality."""
        rows = await self._community_repo.fetch_popular_creators()
        return msgspec.convert(rows, list[TopCreatorsResponse])

    async def get_unarchived_map_count(self) -> list[MapCountsResponse]:
        """Get unarchived map counts by name."""
        rows = await self._community_repo.fetch_unarchived_map_count()
        return msgspec.convert(rows, list[MapCountsResponse])

    async def get_total_map_count(self) -> list[MapCountsResponse]:
        """Get total map counts by name."""
        rows = await self._community_repo.fetch_total_map_count()
        return msgspec.convert(rows, list[MapCountsResponse])

    async def get_map_record_progression(self, user_id: int, code: OverwatchCode) -> list[MapRecordProgressionResponse]:
        """Get record progression for a map and user."""
        rows = await self._community_repo.fetch_map_record_progression(user_id, code)
        return msgspec.convert(rows, list[MapRecordProgressionResponse])

    async def get_time_played_per_rank(self) -> list[TimePlayedPerRankResponse]:
        """Get total time played per difficulty rank."""
        rows = await self._community_repo.fetch_time_played_per_rank()
        return msgspec.convert(rows, list[TimePlayedPerRankResponse])


async def provide_community_service(
    state: State,
    community_repo: CommunityRepository,
) -> CommunityService:
    """Litestar DI provider for CommunityService."""
    return CommunityService(state.db_pool, state, community_repo)
