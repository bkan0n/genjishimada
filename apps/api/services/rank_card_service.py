"""Service for rank_card business logic."""

from __future__ import annotations

from asyncpg import Pool
from genjishimada_sdk.difficulties import DIFFICULTY_TO_RANK_MAP, Rank
from genjishimada_sdk.helpers import sanitize_string
from genjishimada_sdk.rank_card import AvatarResponse, BackgroundResponse, RankCardBadgeSettings, RankCardResponse
from genjishimada_sdk.users import RankDetailResponse
from litestar.datastructures import State

from repository.rank_card_repository import RankCardRepository
from utilities.shared_queries import get_map_mastery_data, get_user_rank_data

from .base import BaseService
from .exceptions.users import UserNotFoundError


class RankCardService(BaseService):
    """Service for rank_card business logic."""

    def __init__(self, pool: Pool, state: State, rank_card_repo: RankCardRepository) -> None:
        """Initialize service.

        Args:
            pool: AsyncPG connection pool.
            state: Application state.
            rank_card_repo: RankCard repository.
        """
        super().__init__(pool, state)
        self._rank_card_repo = rank_card_repo

    async def _ensure_user_exists(self, user_id: int) -> None:
        """Verify user exists in database.

        Args:
            user_id: User ID to check.

        Raises:
            UserNotFoundError: If user does not exist.
        """
        async with self._pool.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM core.users WHERE id = $1)",
                user_id,
            )
            if not exists:
                raise UserNotFoundError(user_id)

    async def get_background(self, user_id: int) -> BackgroundResponse:
        """Get user's rank card background.

        Args:
            user_id: User ID.

        Returns:
            Background response with name.
        """
        row = await self._rank_card_repo.fetch_background(user_id)
        name = row["name"] if row else "placeholder"
        return BackgroundResponse(name=name)

    async def set_background(self, user_id: int, background: str) -> BackgroundResponse:
        """Set user's rank card background.

        Args:
            user_id: User ID.
            background: Background name.

        Returns:
            Background response with updated name.

        Raises:
            UserNotFoundError: If user does not exist.
        """
        await self._ensure_user_exists(user_id)
        await self._rank_card_repo.upsert_background(user_id, background)
        return BackgroundResponse(name=background)

    async def get_avatar_skin(self, user_id: int) -> AvatarResponse:
        """Get user's avatar skin.

        Args:
            user_id: User ID.

        Returns:
            Avatar response with skin.
        """
        row = await self._rank_card_repo.fetch_avatar(user_id)
        skin = row["skin"] if row else "Overwatch 1"
        return AvatarResponse(skin=skin)

    async def set_avatar_skin(self, user_id: int, skin: str) -> AvatarResponse:
        """Set user's avatar skin.

        Args:
            user_id: User ID.
            skin: Skin name.

        Returns:
            Avatar response with updated skin.

        Raises:
            UserNotFoundError: If user does not exist.
        """
        await self._ensure_user_exists(user_id)
        await self._rank_card_repo.upsert_avatar_skin(user_id, skin)
        return AvatarResponse(skin=skin)

    async def get_avatar_pose(self, user_id: int) -> AvatarResponse:
        """Get user's avatar pose.

        Args:
            user_id: User ID.

        Returns:
            Avatar response with pose.
        """
        row = await self._rank_card_repo.fetch_avatar(user_id)
        pose = row["pose"] if row else "Heroic"
        return AvatarResponse(pose=pose)

    async def set_avatar_pose(self, user_id: int, pose: str) -> AvatarResponse:
        """Set user's avatar pose.

        Args:
            user_id: User ID.
            pose: Pose name.

        Returns:
            Avatar response with updated pose.

        Raises:
            UserNotFoundError: If user does not exist.
        """
        await self._ensure_user_exists(user_id)
        await self._rank_card_repo.upsert_avatar_pose(user_id, pose)
        return AvatarResponse(pose=pose)

    async def get_badges(self, user_id: int) -> RankCardBadgeSettings:
        """Get user's badge settings with resolved URLs.

        Args:
            user_id: User ID.

        Returns:
            Badge settings with resolved URLs for mastery and spray badges.
        """
        row = await self._rank_card_repo.fetch_badges(user_id)
        if not row:
            return RankCardBadgeSettings()

        async with self._pool.acquire() as conn:
            for num in range(1, 7):
                type_col = f"badge_type{num}"
                name_col = f"badge_name{num}"
                url_col = f"badge_url{num}"

                if row[type_col] == "mastery":
                    mastery = await get_map_mastery_data(conn, user_id, row[name_col])  # type: ignore[arg-type]
                    if mastery:
                        row[url_col] = mastery[0].icon_url
                elif row[type_col] == "spray":
                    sanitized = sanitize_string(row[name_col])
                    row[url_col] = f"https://cdn.genji.pk/assets/rank_card/spray/{sanitized}.webp"

        return RankCardBadgeSettings(**row)

    async def set_badges(self, user_id: int, data: RankCardBadgeSettings) -> None:
        """Set user's badge settings.

        Args:
            user_id: User ID.
            data: Badge settings to store.

        Raises:
            UserNotFoundError: If user does not exist.
        """
        await self._ensure_user_exists(user_id)
        await self._rank_card_repo.upsert_badges(
            user_id,
            data.badge_name1,
            data.badge_type1,
            data.badge_name2,
            data.badge_type2,
            data.badge_name3,
            data.badge_type3,
            data.badge_name4,
            data.badge_type4,
            data.badge_name5,
            data.badge_type5,
            data.badge_name6,
            data.badge_type6,
        )

    @staticmethod
    def _find_highest_rank(data: list[RankDetailResponse]) -> Rank:
        """Determine the highest rank achieved by a user.

        Args:
            data: Rank detail entries for the user.

        Returns:
            The name of the highest achieved rank.
        """
        highest: Rank = "Ninja"
        for row in data:
            if row.rank_met:
                highest = DIFFICULTY_TO_RANK_MAP[row.difficulty]
        return highest

    async def get_rank_card_data(self, user_id: int) -> RankCardResponse:
        """Assemble all rank card data for a user.

        Args:
            user_id: User ID.

        Returns:
            Complete rank card information including ranks, nickname, avatar,
            badges, stats, and XP.

        Raises:
            UserNotFoundError: If user does not exist.
        """
        await self._ensure_user_exists(user_id)

        async with self._pool.acquire() as conn:
            rank_data = await get_user_rank_data(conn, user_id)  # type: ignore[arg-type]
            nickname = await self._rank_card_repo.fetch_nickname(user_id, conn=conn)  # type: ignore[arg-type]
            background_row = await self._rank_card_repo.fetch_background(user_id, conn=conn)  # type: ignore[arg-type]
            maps_count = await self._rank_card_repo.fetch_maps_created_count(user_id, conn=conn)  # type: ignore[arg-type]
            playtests_count = await self._rank_card_repo.fetch_playtests_voted_count(user_id, conn=conn)  # type: ignore[arg-type]
            world_records = await self._rank_card_repo.fetch_world_record_count(user_id, conn=conn)  # type: ignore[arg-type]
            avatar_row = await self._rank_card_repo.fetch_avatar(user_id, conn=conn)  # type: ignore[arg-type]
            totals = await self._rank_card_repo.fetch_map_totals(conn=conn)  # type: ignore[arg-type]
            xp_data = await self._rank_card_repo.fetch_community_rank_xp(user_id, conn=conn)  # type: ignore[arg-type]

        badges = await self.get_badges(user_id)

        background = background_row["name"] if background_row else "placeholder"
        avatar_skin = avatar_row["skin"] if avatar_row else "Overwatch 1"
        avatar_pose = avatar_row["pose"] if avatar_row else "Heroic"
        rank = self._find_highest_rank(rank_data)

        difficulties = {}
        for row in rank_data:
            difficulties[row.difficulty] = {
                "completed": row.completions,
                "gold": row.gold,
                "silver": row.silver,
                "bronze": row.bronze,
            }

        for total in totals:
            if total["base_difficulty"] in difficulties:
                difficulties[total["base_difficulty"]]["total"] = total["total"]

        return RankCardResponse(
            rank_name=rank,
            nickname=nickname,
            background=background,
            total_maps_created=maps_count,
            total_playtests=playtests_count,
            world_records=world_records,
            difficulties=difficulties,
            avatar_skin=avatar_skin,
            avatar_pose=avatar_pose,
            badges=badges,
            xp=xp_data["xp"],
            prestige_level=xp_data["prestige_level"],
            community_rank=xp_data["community_rank"],
        )


async def provide_rank_card_service(
    state: State,
    rank_card_repo: RankCardRepository,
) -> RankCardService:
    """Litestar DI provider for service.

    Args:
        state: Application state.
        rank_card_repo: RankCard repository.

    Returns:
        RankCardService instance.
    """
    return RankCardService(state.db_pool, state, rank_card_repo)
