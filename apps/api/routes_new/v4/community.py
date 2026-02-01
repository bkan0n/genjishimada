"""V4 Community routes."""

from __future__ import annotations

from typing import Annotated, Literal

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
from litestar import Controller, get
from litestar.di import Provide
from litestar.params import Parameter

from repository.community_repository import provide_community_repository
from services.community_service import CommunityService, provide_community_service


class CommunityController(Controller):
    """Endpoints for community statistics and leaderboards."""

    path = "/community"
    tags = ["Community"]
    dependencies = {
        "community_repo": Provide(provide_community_repository),
        "community_service": Provide(provide_community_service),
    }

    @get(
        path="/leaderboard",
        summary="List Community Leaderboard",
        description=(
            "Return leaderboard rows with optional filters (name, XP tier, skill rank), "
            "sorting (xp_amount, nickname, prestige_level, wr_count, map_count, playtest_count, "
            "discord_tag, skill_rank), and pagination."
        ),
    )
    async def get_community_leaderboard(  # noqa: PLR0913
        self,
        community_service: CommunityService,
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
        page_number: Annotated[int, Parameter(ge=1)] = 1,
    ) -> list[CommunityLeaderboardResponse]:
        """Retrieve leaderboard rows with filters, sorting, and pagination.

        Args:
            community_service: Community service dependency.
            name: Optional search string (nickname/global name).
            tier_name: Exact XP tier name to match.
            skill_rank: Exact derived skill rank to match.
            sort_column: Column to sort by.
            sort_direction: Sort direction, "asc" or "desc".
            page_size: Page size; one of 10, 20, 25, 50.
            page_number: 1-based page number.

        Returns:
            list[CommunityLeaderboardResponse]: Paged leaderboard results.
        """
        return await community_service.get_community_leaderboard(
            name,
            tier_name,
            skill_rank,
            sort_column,
            sort_direction,
            page_size,
            page_number,
        )

    @get(
        path="/statistics/xp/players",
        summary="Players Per XP Tier",
        description="Count the number of players in each main XP tier.",
    )
    async def get_players_per_xp_tier(self, community_service: CommunityService) -> list[PlayersPerXPTierResponse]:
        """Return player counts per XP main tier.

        Args:
            community_service: Community service dependency.

        Returns:
            list[PlayersPerXPTierResponse]: Counts per XP tier.
        """
        return await community_service.get_players_per_xp_tier()

    @get(
        path="/statistics/skill/players",
        summary="Players Per Skill Tier",
        description="Count the number of players per derived skill rank (Ninja → God).",
    )
    async def get_players_per_skill_tier(
        self, community_service: CommunityService
    ) -> list[PlayersPerSkillTierResponse]:
        """Return player counts per derived skill rank.

        Args:
            community_service: Community service dependency.

        Returns:
            list[PlayersPerSkillTierResponse]: Counts per skill rank.
        """
        return await community_service.get_players_per_skill_tier()

    @get(
        path="/statistics/maps/completions",
        summary="Map Completion Time Stats",
        description="Return min, max, and average verified completion times for a map code.",
    )
    async def get_map_completion_statistics(
        self, community_service: CommunityService, code: OverwatchCode
    ) -> list[MapCompletionStatisticsResponse]:
        """Return summary completion time statistics for a map.

        Args:
            community_service: Community service dependency.
            code: Overwatch map code.

        Returns:
            list[MapCompletionStatisticsResponse]: Min/max/avg completion times.
        """
        return await community_service.get_map_completion_statistics(code)

    @get(
        path="/statistics/maps/difficulty",
        summary="Maps Per Difficulty",
        description="Count official, visible maps per base difficulty (stripping '+'/'-').",
    )
    async def get_maps_per_difficulty(
        self, community_service: CommunityService
    ) -> list[MapPerDifficultyStatisticsResponse]:
        """Return counts of maps per base difficulty.

        Args:
            community_service: Community service dependency.

        Returns:
            list[MapPerDifficultyStatisticsResponse]: Counts per base difficulty.
        """
        return await community_service.get_maps_per_difficulty()

    @get(
        path="/statistics/maps/popular",
        summary="Top Maps by Difficulty",
        description="Return the top 5 maps per base difficulty ranked by completions (tiebreaker: quality).",
    )
    async def get_popular_maps(self, community_service: CommunityService) -> list[PopularMapsStatisticsResponse]:
        """Return top maps per difficulty by completions/quality.

        Args:
            community_service: Community service dependency.

        Returns:
            list[PopularMapsStatisticsResponse]: Ranked top maps per difficulty.
        """
        return await community_service.get_popular_maps()

    @get(
        path="/statistics/creators/popular",
        summary="Top Creators by Average Quality",
        description="Return creators with ≥3 rated maps, ranked by average quality.",
    )
    async def get_popular_creators(self, community_service: CommunityService) -> list[TopCreatorsResponse]:
        """Return top creators by average quality (min 3 maps).

        Args:
            community_service: Community service dependency.

        Returns:
            list[TopCreatorsResponse]: Creator averages and counts.
        """
        return await community_service.get_popular_creators()

    @get(
        path="/statistics/maps/unarchived",
        summary="Unarchived Maps by Name",
        description="Count non-archived, non-hidden maps grouped by map name.",
    )
    async def get_unarchived_map_count(self, community_service: CommunityService) -> list[MapCountsResponse]:
        """Return counts of unarchived, visible maps per name.

        Args:
            community_service: Community service dependency.

        Returns:
            list[MapCountsResponse]: Per-name counts.
        """
        return await community_service.get_unarchived_map_count()

    @get(
        path="/statistics/maps/all",
        summary="All Maps by Name",
        description="Count all maps grouped by map name, regardless of archive/visibility.",
    )
    async def get_total_map_count(self, community_service: CommunityService) -> list[MapCountsResponse]:
        """Return counts of all maps per name.

        Args:
            community_service: Community service dependency.

        Returns:
            list[MapCountsResponse]: Per-name counts for all maps.
        """
        return await community_service.get_total_map_count()

    @get(
        path="/statistics/maps/{code:str}/user/{user_id:int}",
        summary="Map Record Progression for User",
        description="Return a user's record times over time for the specified map code.",
    )
    async def get_map_record_progression(
        self,
        community_service: CommunityService,
        user_id: int,
        code: OverwatchCode,
    ) -> list[MapRecordProgressionResponse]:
        """Return a user's record progression for a map.

        Args:
            community_service: Community service dependency.
            user_id: Target user ID.
            code: Overwatch map code.

        Returns:
            list[MapRecordProgressionResponse]: Time-series of records.
        """
        return await community_service.get_map_record_progression(user_id, code)

    @get(
        path="/statistics/ranks/time-played",
        summary="Time Played per Base Difficulty",
        description="Sum verified playtime across maps, grouped by base difficulty (stripping '+'/'-').",
    )
    async def get_time_played_per_rank(self, community_service: CommunityService) -> list[TimePlayedPerRankResponse]:
        """Return total verified playtime by base difficulty.

        Args:
            community_service: Community service dependency.

        Returns:
            list[TimePlayedPerRankResponse]: Total seconds by base difficulty.
        """
        return await community_service.get_time_played_per_rank()
