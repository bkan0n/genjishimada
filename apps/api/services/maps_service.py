"""Service for maps business logic."""

from __future__ import annotations

import datetime as dt
from typing import TYPE_CHECKING

from asyncpg import Pool
from genjishimada_sdk.maps import (
    ArchivalStatusPatchRequest,
    GuideFullResponse,
    GuideResponse,
    LinkMapsCreateRequest,
    MapCreateRequest,
    MapCreationJobResponse,
    MapMasteryCreateRequest,
    MapMasteryCreateResponse,
    MapMasteryResponse,
    MapPartialResponse,
    MapPatchRequest,
    MapResponse,
    OverwatchCode,
    PlaytestCreatedEvent,
    PlaytestCreatePartialRequest,
    QualityValueRequest,
    SendToPlaytestRequest,
    TrendingMapResponse,
    UnlinkMapsCreateRequest,
)
from genjishimada_sdk.newsfeed import (
    NewsfeedArchive,
    NewsfeedBulkArchive,
    NewsfeedEvent,
    NewsfeedLinkedMap,
    NewsfeedNewMap,
    NewsfeedUnlinkedMap,
)
from genjishimada_sdk.internal import JobStatusResponse
from litestar.datastructures import Headers, State
from litestar.status_codes import HTTP_400_BAD_REQUEST
import msgspec

from repository.maps_repository import MapsRepository
from repository.exceptions import (
    UniqueConstraintViolationError,
    ForeignKeyViolationError,
)
from services.exceptions.maps import (
    AlreadyInPlaytestError,
    CreatorNotFoundError,
    DuplicateCreatorError,
    DuplicateGuideError,
    DuplicateMechanicError,
    DuplicateRestrictionError,
    GuideNotFoundError,
    LinkedMapError,
    MapCodeExistsError,
    MapNotFoundError,
)
from .base import BaseService

if TYPE_CHECKING:
    from services.newsfeed_service import NewsfeedService


class MapsService(BaseService):
    """Service for maps business logic."""

    def __init__(
        self,
        pool: Pool,
        state: State,
        maps_repo: MapsRepository,
    ):
        """Initialize service."""
        super().__init__(pool, state)
        self._maps_repo = maps_repo

    # Core CRUD operations

    async def create_map(
        self,
        data: MapCreateRequest,
        headers: Headers,
        newsfeed_service: NewsfeedService,
    ) -> MapCreationJobResponse:
        """Create a map.

        Within a transaction, inserts the core map row and all related data
        (creators, guide, mechanics, restrictions, medals). If playtesting is
        set, creates a partial playtest meta row and publishes a queue message.

        Args:
            data: Map creation request.
            headers: Request headers for idempotency.
            newsfeed_service: Newsfeed service for event publishing.

        Returns:
            Map creation response with optional job status.

        Raises:
            MapCodeExistsError: If code already exists.
            DuplicateMechanicError: If duplicate mechanic in request.
            DuplicateRestrictionError: If duplicate restriction in request.
            DuplicateCreatorError: If duplicate creator ID in request.
            CreatorNotFoundError: If creator user doesn't exist.
        """
        # Auto-approve non-official maps
        if not data.official and data.playtesting != "Approved":
            data.playtesting = "Approved"

        # Convert request to dict for repository
        map_data = {
            "code": data.code,
            "map_name": data.map_name,
            "category": data.category,
            "checkpoints": data.checkpoints,
            "official": data.official,
            "playtesting": data.playtesting,
            "hidden": data.hidden if data.hidden is not msgspec.UNSET else True,
            "archived": False,
            "difficulty": data.difficulty,
            "raw_difficulty": data.raw_difficulty,
            "description": data.description if data.description is not msgspec.UNSET else None,
            "custom_banner": data.custom_banner if data.custom_banner is not msgspec.UNSET else None,
            "title": data.title if data.title is not msgspec.UNSET else None,
        }

        # Transaction for multi-step operation
        async with self._pool.acquire() as conn, conn.transaction():
            try:
                # Create core map
                map_id = await self._maps_repo.create_core_map(
                    map_data,
                    conn=conn,  # type: ignore[arg-type]
                )

                # Insert related data
                creators_data = [
                    {"user_id": c.user_id, "is_primary": c.is_primary}
                    for c in (data.creators or [])
                ]
                await self._maps_repo.insert_creators(
                    map_id,
                    creators_data,
                    conn=conn,  # type: ignore[arg-type]
                )

                # Guide URL (if provided)
                if data.guide_url is not msgspec.UNSET and data.guide_url:
                    await self._maps_repo.insert_guide(
                        map_id,
                        data.guide_url,
                        data.primary_creator_id if data.primary_creator_id is not msgspec.UNSET else None,
                        conn=conn,  # type: ignore[arg-type]
                    )

                # Mechanics
                if data.mechanics is not msgspec.UNSET and data.mechanics:
                    await self._maps_repo.insert_mechanics(
                        map_id,
                        data.mechanics,
                        conn=conn,  # type: ignore[arg-type]
                    )

                # Restrictions
                if data.restrictions is not msgspec.UNSET and data.restrictions:
                    await self._maps_repo.insert_restrictions(
                        map_id,
                        data.restrictions,
                        conn=conn,  # type: ignore[arg-type]
                    )

                # Tags
                if data.tags is not msgspec.UNSET and data.tags:
                    await self._maps_repo.insert_tags(
                        map_id,
                        data.tags,
                        conn=conn,  # type: ignore[arg-type]
                    )

                # Medals
                if data.medals is not msgspec.UNSET and data.medals:
                    medals_data = {
                        "gold": data.medals.gold,
                        "silver": data.medals.silver,
                        "bronze": data.medals.bronze,
                    }
                    await self._maps_repo.insert_medals(
                        map_id,
                        medals_data,
                        conn=conn,  # type: ignore[arg-type]
                    )

                # Handle playtest creation if needed
                job_status = None
                if data.playtesting == "In Progress":
                    playtest_id = await self._maps_repo.create_playtest_meta_partial(
                        data.code,
                        data.raw_difficulty,
                        conn=conn,  # type: ignore[arg-type]
                    )

                    # Publish RabbitMQ message to bot
                    message_data = PlaytestCreatedEvent(data.code, playtest_id)
                    idempotency_key = f"map:submit:{map_id}"
                    job_status = await self.publish_message(
                        routing_key="api.playtest.create",
                        data=message_data,
                        headers=headers,
                        idempotency_key=idempotency_key,
                    )

            except UniqueConstraintViolationError as e:
                if "maps_code_key" in e.constraint_name:
                    raise MapCodeExistsError(data.code) from e
                if "mechanic_links_pkey" in e.constraint_name:
                    raise DuplicateMechanicError() from e
                if "restriction_links_pkey" in e.constraint_name:
                    raise DuplicateRestrictionError() from e
                if "creators_pkey" in e.constraint_name:
                    raise DuplicateCreatorError() from e
                raise

            except ForeignKeyViolationError as e:
                if "creators_user_id_fkey" in e.constraint_name:
                    raise CreatorNotFoundError() from e
                raise

        # Fetch created map (outside transaction)
        map_data_result = await self._maps_repo.fetch_maps(
            single=True,
            code=data.code,
        )

        # Convert to MapResponse
        map_response = msgspec.convert(map_data_result, MapResponse, from_attributes=True)

        # Publish newsfeed event if approved
        if data.playtesting == "Approved":
            event_payload = NewsfeedNewMap(
                code=map_response.code,
                map_name=map_response.map_name,
                difficulty=map_response.difficulty,
                creators=[c.name for c in map_response.creators] if map_response.creators else [],
                banner_url=map_response.map_banner if hasattr(map_response, "map_banner") else None,
                official=data.official,
                title=data.title if data.title is not msgspec.UNSET else None,
            )
            event = NewsfeedEvent(
                id=None,
                timestamp=dt.datetime.now(dt.timezone.utc),
                payload=event_payload,
                event_type="new_map",
            )
            await newsfeed_service.create_and_publish(event, headers=headers, use_pool=True)

        return MapCreationJobResponse(job_status, map_response)

    async def update_map(
        self,
        code: OverwatchCode,
        data: MapPatchRequest,
    ) -> MapResponse:
        """Update a map.

        Looks up map by code, updates core row and replaces related data.

        Args:
            code: Map code to update.
            data: Partial update request.

        Returns:
            Updated map response.

        Raises:
            MapNotFoundError: If map doesn't exist.
            MapCodeExistsError: If new code already exists.
            DuplicateMechanicError: If duplicate mechanic in request.
            DuplicateRestrictionError: If duplicate restriction in request.
            DuplicateCreatorError: If duplicate creator ID in request.
            CreatorNotFoundError: If creator user doesn't exist.
        """
        # Lookup map ID
        map_id = await self._maps_repo.lookup_map_id(code)
        if map_id is None:
            raise MapNotFoundError(code)

        # Build core map update dict
        core_updates = {}
        if data.code is not msgspec.UNSET:
            core_updates["code"] = data.code
        if data.map_name is not msgspec.UNSET:
            core_updates["map_name"] = data.map_name
        if data.category is not msgspec.UNSET:
            core_updates["category"] = data.category
        if data.checkpoints is not msgspec.UNSET:
            core_updates["checkpoints"] = data.checkpoints
        if data.difficulty is not msgspec.UNSET:
            core_updates["difficulty"] = data.difficulty
        if data.raw_difficulty is not msgspec.UNSET:
            core_updates["raw_difficulty"] = data.raw_difficulty
        if data.description is not msgspec.UNSET:
            core_updates["description"] = data.description
        if data.custom_banner is not msgspec.UNSET:
            core_updates["custom_banner"] = data.custom_banner
        if data.title is not msgspec.UNSET:
            core_updates["title"] = data.title
        if data.hidden is not msgspec.UNSET:
            core_updates["hidden"] = data.hidden
        if data.archived is not msgspec.UNSET:
            core_updates["archived"] = data.archived
        if data.playtesting is not msgspec.UNSET:
            core_updates["playtesting"] = data.playtesting

        # Transaction for multi-step update
        async with self._pool.acquire() as conn, conn.transaction():
            try:
                # Update core map
                if core_updates:
                    await self._maps_repo.update_core_map(
                        code,
                        core_updates,
                        conn=conn,  # type: ignore[arg-type]
                    )

                # Replace related data if provided
                if data.creators is not msgspec.UNSET:
                    await self._maps_repo.delete_creators(map_id, conn=conn)  # type: ignore[arg-type]
                    if data.creators:
                        creators_data = [
                            {"user_id": c.user_id, "is_primary": c.is_primary}
                            for c in data.creators
                        ]
                        await self._maps_repo.insert_creators(
                            map_id,
                            creators_data,
                            conn=conn,  # type: ignore[arg-type]
                        )

                if data.mechanics is not msgspec.UNSET:
                    await self._maps_repo.delete_mechanics(map_id, conn=conn)  # type: ignore[arg-type]
                    if data.mechanics:
                        await self._maps_repo.insert_mechanics(
                            map_id,
                            data.mechanics,
                            conn=conn,  # type: ignore[arg-type]
                        )

                if data.restrictions is not msgspec.UNSET:
                    await self._maps_repo.delete_restrictions(map_id, conn=conn)  # type: ignore[arg-type]
                    if data.restrictions:
                        await self._maps_repo.insert_restrictions(
                            map_id,
                            data.restrictions,
                            conn=conn,  # type: ignore[arg-type]
                        )

                if data.tags is not msgspec.UNSET:
                    await self._maps_repo.delete_tags(map_id, conn=conn)  # type: ignore[arg-type]
                    if data.tags:
                        await self._maps_repo.insert_tags(
                            map_id,
                            data.tags,
                            conn=conn,  # type: ignore[arg-type]
                        )

                if data.medals is not msgspec.UNSET:
                    await self._maps_repo.delete_medals(map_id, conn=conn)  # type: ignore[arg-type]
                    if data.medals:
                        medals_data = {
                            "gold": data.medals.gold,
                            "silver": data.medals.silver,
                            "bronze": data.medals.bronze,
                        }
                        await self._maps_repo.insert_medals(
                            map_id,
                            medals_data,
                            conn=conn,  # type: ignore[arg-type]
                        )

            except UniqueConstraintViolationError as e:
                if "maps_code_key" in e.constraint_name:
                    new_code = data.code if data.code is not msgspec.UNSET else code
                    raise MapCodeExistsError(new_code) from e
                if "mechanic_links_pkey" in e.constraint_name:
                    raise DuplicateMechanicError() from e
                if "restriction_links_pkey" in e.constraint_name:
                    raise DuplicateRestrictionError() from e
                if "creators_pkey" in e.constraint_name:
                    raise DuplicateCreatorError() from e
                raise

            except ForeignKeyViolationError as e:
                if "creators_user_id_fkey" in e.constraint_name:
                    raise CreatorNotFoundError() from e
                raise

        # Fetch and return updated map
        final_code = data.code if data.code is not msgspec.UNSET else code
        map_data_result = await self._maps_repo.fetch_maps(single=True, code=final_code)
        return msgspec.convert(map_data_result, MapResponse, from_attributes=True)

    async def fetch_maps(
        self,
        *,
        single: bool = False,
        code: str | None = None,
        filters: dict | None = None,
    ) -> MapResponse | list[MapResponse]:
        """Fetch maps with optional filters.

        Args:
            single: If True, return single map; if False, return list.
            code: Optional code filter for single map lookup.
            filters: Optional filter criteria.

        Returns:
            Single MapResponse if single=True, otherwise list of MapResponse.
        """
        result = await self._maps_repo.fetch_maps(
            single=single,
            code=code,
            filters=filters,
        )

        if single:
            return msgspec.convert(result, MapResponse, from_attributes=True)
        return msgspec.convert(result, list[MapResponse], from_attributes=True)

    async def fetch_partial_map(self, code: OverwatchCode) -> MapPartialResponse:
        """Fetch partial map data.

        Args:
            code: Map code.

        Returns:
            Partial map response.

        Raises:
            MapNotFoundError: If map doesn't exist.
        """
        result = await self._maps_repo.fetch_partial_map(code)
        if result is None:
            raise MapNotFoundError(code)

        return msgspec.convert(result, MapPartialResponse, from_attributes=True)

    async def check_code_exists(self, code: OverwatchCode) -> bool:
        """Check if map code exists.

        Args:
            code: Map code.

        Returns:
            True if code exists, False otherwise.
        """
        return await self._maps_repo.check_code_exists(code)

    # Guide operations

    async def get_guides(
        self,
        code: OverwatchCode,
        include_records: bool = False,
    ) -> list[GuideFullResponse]:
        """Get guides for a map.

        Args:
            code: Map code.
            include_records: Whether to include completion records.

        Returns:
            List of guides.

        Raises:
            MapNotFoundError: If map doesn't exist.
        """
        # Validate map exists
        map_id = await self._maps_repo.lookup_map_id(code)
        if map_id is None:
            raise MapNotFoundError(code)

        return await self._maps_repo.fetch_guides(code, include_records)

    async def create_guide(
        self,
        code: OverwatchCode,
        data: GuideResponse,
    ) -> GuideResponse:
        """Create a guide for a map.

        Args:
            code: Map code.
            data: Guide data with user_id and url.

        Returns:
            Created guide.

        Raises:
            MapNotFoundError: If map doesn't exist.
            DuplicateGuideError: If user already has guide for this map.
        """
        # Validate map exists
        map_id = await self._maps_repo.lookup_map_id(code)
        if map_id is None:
            raise MapNotFoundError(code)

        try:
            await self._maps_repo.insert_guide(
                map_id,
                data.url,
                data.user_id,
            )
        except UniqueConstraintViolationError as e:
            if "guides_user_id_map_id_unique" in e.constraint_name:
                raise DuplicateGuideError(code, data.user_id) from e
            raise

        return data

    async def update_guide(
        self,
        code: OverwatchCode,
        user_id: int,
        url: str,
    ) -> GuideResponse:
        """Update a guide.

        Args:
            code: Map code.
            user_id: User ID who owns the guide.
            url: New URL.

        Returns:
            Updated guide.

        Raises:
            MapNotFoundError: If map doesn't exist.
            GuideNotFoundError: If guide doesn't exist.
        """
        # Validate map exists
        map_id = await self._maps_repo.lookup_map_id(code)
        if map_id is None:
            raise MapNotFoundError(code)

        # Update guide
        rows_updated = await self._maps_repo.update_guide(map_id, user_id, url)
        if rows_updated == 0:
            raise GuideNotFoundError(code, user_id)

        return GuideResponse(user_id=user_id, url=url)

    async def delete_guide(
        self,
        code: OverwatchCode,
        user_id: int,
    ) -> None:
        """Delete a guide.

        Args:
            code: Map code.
            user_id: User ID who owns the guide.

        Raises:
            MapNotFoundError: If map doesn't exist.
            GuideNotFoundError: If guide doesn't exist.
        """
        # Validate map exists
        map_id = await self._maps_repo.lookup_map_id(code)
        if map_id is None:
            raise MapNotFoundError(code)

        # Delete guide
        rows_deleted = await self._maps_repo.delete_guide(map_id, user_id)
        if rows_deleted == 0:
            raise GuideNotFoundError(code, user_id)

    # Additional operations

    async def get_affected_users(self, code: OverwatchCode) -> list[int]:
        """Get IDs of users affected by a map change.

        Args:
            code: Map code.

        Returns:
            List of affected user IDs.

        Raises:
            MapNotFoundError: If map doesn't exist.
        """
        # Validate map exists
        map_id = await self._maps_repo.lookup_map_id(code)
        if map_id is None:
            raise MapNotFoundError(code)

        return await self._maps_repo.fetch_affected_users(code)

    async def get_map_mastery_data(
        self,
        user_id: int,
        code: OverwatchCode | None = None,
    ) -> list[MapMasteryResponse]:
        """Get mastery data for a user, optionally scoped to a map.

        Args:
            user_id: Target user ID.
            code: Optional map code filter.

        Returns:
            List of mastery records for the user.
        """
        return await self._maps_repo.fetch_map_mastery(user_id, code)

    async def update_mastery(
        self,
        data: MapMasteryCreateRequest,
    ) -> MapMasteryCreateResponse | None:
        """Create or update mastery data.

        Args:
            data: Mastery payload with user_id, map_name, and level.

        Returns:
            Result of the mastery operation, or None if no change.
        """
        return await self._maps_repo.upsert_map_mastery(data)

    async def set_archive_status(
        self,
        data: ArchivalStatusPatchRequest,
        headers: Headers,
        newsfeed_service: NewsfeedService,
    ) -> None:
        """Set archive status for one or more maps.

        Args:
            data: Archive request with codes and archived status.
            headers: Request headers for idempotency.
            newsfeed_service: Newsfeed service for event publishing.

        Raises:
            MapNotFoundError: If any map code doesn't exist.
        """
        # Validate all codes exist
        for code in data.codes:
            map_id = await self._maps_repo.lookup_map_id(code)
            if map_id is None:
                raise MapNotFoundError(code)

        # Update archive status
        await self._maps_repo.set_archive_status(data.codes, data.archived)

        # Publish newsfeed event
        if len(data.codes) == 1:
            # Single map archive
            map_data = await self._maps_repo.fetch_maps(single=True, code=data.codes[0])
            map_response = msgspec.convert(map_data, MapResponse, from_attributes=True)

            event_payload = NewsfeedArchive(
                code=map_response.code,
                map_name=map_response.map_name,
                difficulty=map_response.difficulty,
                creators=[c.name for c in map_response.creators] if map_response.creators else [],
                banner_url=map_response.map_banner if hasattr(map_response, "map_banner") else None,
                archived=data.archived,
            )
        else:
            # Bulk archive
            event_payload = NewsfeedBulkArchive(
                codes=data.codes,
                archived=data.archived,
            )

        event = NewsfeedEvent(
            id=None,
            timestamp=dt.datetime.now(dt.timezone.utc),
            payload=event_payload,
            event_type="archive" if len(data.codes) == 1 else "bulk_archive",
        )
        await newsfeed_service.create_and_publish(event, headers=headers, use_pool=True)

    async def convert_to_legacy(
        self,
        code: OverwatchCode,
    ) -> int:
        """Convert map to legacy status (public endpoint).

        Args:
            code: Map code.

        Returns:
            Number of completions converted.

        Raises:
            MapNotFoundError: If map doesn't exist.
        """
        # Validate map exists
        map_id = await self._maps_repo.lookup_map_id(code)
        if map_id is None:
            raise MapNotFoundError(code)

        async with self._pool.acquire() as conn, conn.transaction():
            return await self._convert_to_legacy_internal(code, conn)  # type: ignore[arg-type]

    async def _convert_to_legacy_internal(
        self,
        code: OverwatchCode,
        conn,
    ) -> int:
        """Internal helper to convert map to legacy (used in transaction).

        Args:
            code: Map code.
            conn: Database connection (transaction).

        Returns:
            Number of completions converted.
        """
        # Check for pending verifications
        has_pending = await self._maps_repo.check_pending_verifications(
            code,
            conn=conn,  # type: ignore[arg-type]
        )
        if has_pending:
            # Allow but log warning (v3 behavior)
            pass

        # Remove medal entries
        await self._maps_repo.remove_map_medal_entries(
            code,
            conn=conn,  # type: ignore[arg-type]
        )

        # Convert completions to legacy
        return await self._maps_repo.convert_completions_to_legacy(
            code,
            conn=conn,  # type: ignore[arg-type]
        )

    async def override_quality_votes(
        self,
        code: OverwatchCode,
        data: QualityValueRequest,
    ) -> None:
        """Override quality votes for a map (admin only).

        Args:
            code: Map code.
            data: Quality value to set.

        Raises:
            MapNotFoundError: If map doesn't exist.
        """
        # Validate map exists
        map_id = await self._maps_repo.lookup_map_id(code)
        if map_id is None:
            raise MapNotFoundError(code)

        await self._maps_repo.override_quality_votes(code, data.quality)

    async def get_trending_maps(self) -> list[TrendingMapResponse]:
        """Get trending maps by clicks/ratings.

        Returns:
            List of trending maps.
        """
        return await self._maps_repo.fetch_trending_maps()

    async def send_to_playtest(
        self,
        code: OverwatchCode,
        data: SendToPlaytestRequest,
        headers: Headers,
    ) -> JobStatusResponse:
        """Send a map back to playtest.

        Converts map to legacy status, creates playtest metadata, and publishes
        RabbitMQ message to bot.

        Args:
            code: Map code.
            data: Playtest request with initial difficulty.
            headers: Request headers for idempotency.

        Returns:
            Job status response.

        Raises:
            MapNotFoundError: If map doesn't exist.
            AlreadyInPlaytestError: If map is already in playtest.
        """
        # Validate map exists and get current state
        map_id = await self._maps_repo.lookup_map_id(code)
        if map_id is None:
            raise MapNotFoundError(code)

        current_map = await self._maps_repo.fetch_maps(single=True, code=code)
        current_map_response = msgspec.convert(current_map, MapResponse, from_attributes=True)
        if current_map_response.playtesting == "In Progress":
            raise AlreadyInPlaytestError(code)

        # Transaction for multi-step operation
        async with self._pool.acquire() as conn, conn.transaction():
            # Convert to legacy
            await self._convert_to_legacy_internal(code, conn)

            # Update playtesting status
            await self._maps_repo.update_core_map(
                code,
                {"playtesting": "In Progress"},
                conn=conn,  # type: ignore[arg-type]
            )

            # Create playtest metadata
            playtest_id = await self._maps_repo.create_playtest_meta_partial(
                code,
                data.initial_difficulty,
                conn=conn,  # type: ignore[arg-type]
            )

        # Publish RabbitMQ message
        message_data = PlaytestCreatedEvent(code, playtest_id)
        idempotency_key = f"map:send-to-playtest:{map_id}:{playtest_id}"
        return await self.publish_message(
            routing_key="api.playtest.create",
            data=message_data,
            headers=headers,
            idempotency_key=idempotency_key,
        )

    async def link_map_codes(
        self,
        data: LinkMapsCreateRequest,
        headers: Headers,
        newsfeed_service: NewsfeedService,
    ) -> None:
        """Link official and unofficial map codes.

        Args:
            data: Link request with official and unofficial codes.
            headers: Request headers for idempotency.
            newsfeed_service: Newsfeed service for event publishing.

        Raises:
            MapNotFoundError: If either map doesn't exist.
            LinkedMapError: If maps are already linked or same code.
        """
        # Validate both maps exist
        official_map_id = await self._maps_repo.lookup_map_id(data.official_code)
        if official_map_id is None:
            raise MapNotFoundError(data.official_code)

        unofficial_map_id = await self._maps_repo.lookup_map_id(data.unofficial_code)
        if unofficial_map_id is None:
            raise MapNotFoundError(data.unofficial_code)

        # Validate not same code
        if data.official_code == data.unofficial_code:
            raise LinkedMapError("Cannot link a map to itself")

        # Fetch both maps to check current state
        official_map = await self._maps_repo.fetch_maps(single=True, code=data.official_code)
        unofficial_map = await self._maps_repo.fetch_maps(single=True, code=data.unofficial_code)

        official_response = msgspec.convert(official_map, MapResponse, from_attributes=True)
        unofficial_response = msgspec.convert(unofficial_map, MapResponse, from_attributes=True)

        # Check if already linked
        if (
            hasattr(official_response, "linked_code")
            and official_response.linked_code == data.unofficial_code
        ):
            raise LinkedMapError("Maps are already linked")

        # Link the codes
        await self._maps_repo.link_map_codes(data.official_code, data.unofficial_code)

        # Publish newsfeed event
        event_payload = NewsfeedLinkedMap(
            official_code=data.official_code,
            unofficial_code=data.unofficial_code,
            official_map_name=official_response.map_name,
            unofficial_map_name=unofficial_response.map_name,
        )
        event = NewsfeedEvent(
            id=None,
            timestamp=dt.datetime.now(dt.timezone.utc),
            payload=event_payload,
            event_type="linked_map",
        )
        await newsfeed_service.create_and_publish(event, headers=headers, use_pool=True)

    async def unlink_map_codes(
        self,
        data: UnlinkMapsCreateRequest,
        headers: Headers,
        newsfeed_service: NewsfeedService,
    ) -> None:
        """Unlink map codes.

        Args:
            data: Unlink request with code to unlink.
            headers: Request headers for idempotency.
            newsfeed_service: Newsfeed service for event publishing.

        Raises:
            MapNotFoundError: If map doesn't exist.
        """
        # Validate map exists
        map_id = await self._maps_repo.lookup_map_id(data.code)
        if map_id is None:
            raise MapNotFoundError(data.code)

        # Fetch map to get current linked code (for newsfeed event)
        map_data = await self._maps_repo.fetch_maps(single=True, code=data.code)
        map_response = msgspec.convert(map_data, MapResponse, from_attributes=True)

        # Unlink the codes
        await self._maps_repo.unlink_map_codes(data.code)

        # Publish newsfeed event (if there was a linked code)
        if hasattr(map_response, "linked_code") and map_response.linked_code:
            event_payload = NewsfeedUnlinkedMap(
                code=data.code,
                previously_linked_code=map_response.linked_code,
            )
            event = NewsfeedEvent(
                id=None,
                timestamp=dt.datetime.now(dt.timezone.utc),
                payload=event_payload,
                event_type="unlinked_map",
            )
            await newsfeed_service.create_and_publish(event, headers=headers, use_pool=True)

    async def get_playtest_plot(self, code: OverwatchCode) -> object:
        """Get playtest plot data (Phase 3 minimal implementation).

        Args:
            code: Map code.

        Returns:
            Plot data object.

        Raises:
            MapNotFoundError: If map doesn't exist.
        """
        # Validate map exists
        map_id = await self._maps_repo.lookup_map_id(code)
        if map_id is None:
            raise MapNotFoundError(code)

        return await self._maps_repo.fetch_playtest_plot_data(code)


async def provide_maps_service(
    state: State,
    maps_repo: MapsRepository,
) -> MapsService:
    """Litestar DI provider for service."""
    return MapsService(state.db_pool, state, maps_repo)
