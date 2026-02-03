"""Service for maps business logic."""

from __future__ import annotations

import asyncio
import datetime as dt
import inspect
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Literal, overload
from uuid import UUID

import aiohttp
import msgspec
from asyncpg import Pool
from genjishimada_sdk.difficulties import DIFFICULTY_MIDPOINTS, convert_raw_difficulty_to_difficulty_all
from genjishimada_sdk.internal import JobStatusResponse
from genjishimada_sdk.maps import (
    ArchivalStatusPatchRequest,
    Creator,
    GuideFullResponse,
    GuideResponse,
    LinkMapsCreateRequest,
    MapCreateRequest,
    MapCreationJobResponse,
    MapEditCreatedEvent,
    MapEditFieldChange,
    MapEditResolvedEvent,
    MapEditResponse,
    MapEditSubmissionResponse,
    MapMasteryCreateRequest,
    MapMasteryCreateResponse,
    MapMasteryResponse,
    MapPartialResponse,
    MapPatchRequest,
    MapResponse,
    MedalsResponse,
    OverwatchCode,
    OverwatchMap,
    PendingMapEditResponse,
    PlaytestCreatedEvent,
    QualityValueRequest,
    SendToPlaytestRequest,
    TrendingMapResponse,
    UnlinkMapsCreateRequest,
)
from genjishimada_sdk.newsfeed import (
    NewsfeedArchive,
    NewsfeedBulkArchive,
    NewsfeedBulkUnarchive,
    NewsfeedEvent,
    NewsfeedLinkedMap,
    NewsfeedNewMap,
    NewsfeedUnarchive,
    NewsfeedUnlinkedMap,
)
from genjishimada_sdk.notifications import NotificationCreateRequest, NotificationEventType
from litestar.datastructures import Headers, State
from litestar.exceptions import HTTPException
from litestar.response import Stream
from litestar.status_codes import HTTP_200_OK, HTTP_503_SERVICE_UNAVAILABLE

from repository.exceptions import (
    ForeignKeyViolationError,
    UniqueConstraintViolationError,
)
from repository.maps_repository import MapsRepository
from services.exceptions.maps import (
    AlreadyInPlaytestError,
    CreatorNotFoundError,
    DuplicateCreatorError,
    DuplicateGuideError,
    DuplicateMechanicError,
    DuplicateRestrictionError,
    DuplicateTagsError,
    EditRequestNotFoundError,
    GuideNotFoundError,
    LinkedMapError,
    MapCodeExistsError,
    MapNotFoundError,
    MapValidationError,
    PendingEditRequestExistsError,
)
from utilities.jobs import wait_for_job_completion
from utilities.map_search import MapSearchFilters

from .base import BaseService

if TYPE_CHECKING:
    from services.newsfeed_service import NewsfeedService
    from services.notifications_service import NotificationsService
    from services.users_service import UsersService

# Module-level constants and logging
_PREVIEW_MAX_LENGTH = 50
log = logging.getLogger(__name__)


class MapsService(BaseService):
    """Service for maps business logic."""

    def __init__(
        self,
        pool: Pool,
        state: State,
        maps_repo: MapsRepository,
    ) -> None:
        """Initialize service."""
        super().__init__(pool, state)
        self._maps_repo = maps_repo

    # Core CRUD operations

    async def create_map(  # noqa: PLR0912, PLR0915
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
            "hidden": data.hidden,
            "archived": False,
            "difficulty": data.difficulty,
            "raw_difficulty": DIFFICULTY_MIDPOINTS[data.difficulty],
            "description": data.description,
            "custom_banner": data.custom_banner,
            "title": data.title,
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
                creators_data = [{"user_id": c.id, "is_primary": c.is_primary} for c in (data.creators or [])]
                await self._maps_repo.insert_creators(
                    map_id,
                    creators_data,
                    conn=conn,  # type: ignore[arg-type]
                )

                # Guide URL (if provided)
                if data.guide_url:
                    await self._maps_repo.insert_guide(
                        map_id,
                        data.guide_url,
                        data.primary_creator_id,
                        conn=conn,  # type: ignore[arg-type]
                    )

                # Mechanics
                if data.mechanics:
                    if len(set(data.mechanics)) != len(data.mechanics):
                        raise DuplicateMechanicError()
                    await self._maps_repo.insert_mechanics(
                        map_id,
                        data.mechanics,  # type: ignore[arg-type]
                        conn=conn,  # type: ignore[arg-type]
                    )

                # Restrictions
                if data.restrictions:
                    if len(set(data.restrictions)) != len(data.restrictions):
                        raise DuplicateRestrictionError()
                    await self._maps_repo.insert_restrictions(
                        map_id,
                        data.restrictions,  # type: ignore[arg-type]
                        conn=conn,  # type: ignore[arg-type]
                    )

                # Tags
                if data.tags:
                    if len(set(data.tags)) != len(data.tags):
                        raise DuplicateTagsError()
                    await self._maps_repo.insert_tags(
                        map_id,
                        data.tags,  # type: ignore[arg-type]
                        conn=conn,  # type: ignore[arg-type]
                    )

                # Medals
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

                # Handle playtest creation if needed
                job_status = None
                if data.playtesting == "In Progress":
                    playtest_id = await self._maps_repo.create_playtest_meta_partial(
                        data.code,
                        map_data["raw_difficulty"],
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
                official=data.official,
                title=data.title,
            )
            event = NewsfeedEvent(
                id=None,
                timestamp=dt.datetime.now(dt.timezone.utc),
                payload=event_payload,
                event_type="new_map",
            )
            await newsfeed_service.create_and_publish(event=event, headers=headers)

        return MapCreationJobResponse(job_status, map_response)

    async def update_map(  # noqa: PLR0912, PLR0915
        self,
        code: OverwatchCode,
        data: MapPatchRequest,
    ) -> tuple[MapResponse, MapResponse]:
        """Update a map.

        Looks up map by code, updates core row and replaces related data.

        Args:
            code: Map code to update.
            data: Partial update request.

        Returns:
            Tuple of (updated map, original map) for newsfeed event generation.

        Raises:
            MapNotFoundError: If map doesn't exist.
            MapCodeExistsError: If new code already exists.
            DuplicateMechanicError: If duplicate mechanic in request.
            DuplicateRestrictionError: If duplicate restriction in request.
            DuplicateCreatorError: If duplicate creator ID in request.
            CreatorNotFoundError: If creator user doesn't exist.
        """
        # Fetch original map for newsfeed comparison
        original_map_result = await self._maps_repo.fetch_maps(single=True, code=code)
        if not original_map_result:
            raise MapNotFoundError(code)
        original_map = msgspec.convert(original_map_result, MapResponse, from_attributes=True)

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
            core_updates["raw_difficulty"] = DIFFICULTY_MIDPOINTS[data.difficulty]
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

                # Update playtest initial_difficulty if difficulty changed during active playtest
                if (
                    data.difficulty is not msgspec.UNSET
                    and original_map.playtesting == "In Progress"
                    and original_map.playtest is not None
                ):
                    await self._maps_repo.update_playtest_initial_difficulty(
                        original_map.playtest.thread_id,
                        DIFFICULTY_MIDPOINTS[data.difficulty],
                        conn=conn,  # type: ignore[arg-type]
                    )

                # Replace related data if provided
                if data.creators is not msgspec.UNSET:
                    await self._maps_repo.delete_creators(map_id, conn=conn)  # type: ignore[arg-type]
                    if data.creators:
                        creators_data = [{"user_id": c.id, "is_primary": c.is_primary} for c in data.creators]
                        await self._maps_repo.insert_creators(
                            map_id,
                            creators_data,
                            conn=conn,  # type: ignore[arg-type]
                        )

                if data.mechanics is not msgspec.UNSET:
                    await self._maps_repo.delete_mechanics(map_id, conn=conn)  # type: ignore[arg-type]
                    if data.mechanics:
                        if len(set(data.mechanics)) != len(data.mechanics):
                            raise DuplicateMechanicError()
                        await self._maps_repo.insert_mechanics(
                            map_id,
                            data.mechanics,
                            conn=conn,  # type: ignore[arg-type]
                        )

                if data.restrictions is not msgspec.UNSET:
                    await self._maps_repo.delete_restrictions(map_id, conn=conn)  # type: ignore[arg-type]
                    if data.restrictions:
                        if len(set(data.restrictions)) != len(data.restrictions):
                            raise DuplicateRestrictionError()
                        await self._maps_repo.insert_restrictions(
                            map_id,
                            data.restrictions,
                            conn=conn,  # type: ignore[arg-type]
                        )

                if data.tags is not msgspec.UNSET:
                    await self._maps_repo.delete_tags(map_id, conn=conn)  # type: ignore[arg-type]
                    if data.tags:
                        if len(set(data.tags)) != len(data.tags):
                            raise DuplicateTagsError()
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

        # Fetch and return updated map with original for comparison
        final_code = data.code if data.code is not msgspec.UNSET else code
        map_data_result = await self._maps_repo.fetch_maps(single=True, code=final_code)
        updated_map = msgspec.convert(map_data_result, MapResponse, from_attributes=True)
        return (updated_map, original_map)

    @overload
    async def fetch_maps(self, *, single: Literal[True], filters: MapSearchFilters) -> MapResponse: ...

    @overload
    async def fetch_maps(self, *, single: Literal[False], filters: MapSearchFilters) -> list[MapResponse]: ...

    async def fetch_maps(
        self,
        *,
        single: bool = False,
        code: str | None = None,
        filters: MapSearchFilters | None = None,
    ) -> MapResponse | list[MapResponse]:
        """Fetch maps with optional filters.

        Args:
            single: If True, return single map; if False, return list.
            code: Optional code filter for single map lookup (legacy).
            filters: Optional MapSearchFilters struct with all criteria.

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
            List of guides with resolved usernames.

        Raises:
            MapNotFoundError: If map doesn't exist.
        """
        # Validate map exists
        map_id = await self._maps_repo.lookup_map_id(code)
        if map_id is None:
            raise MapNotFoundError(code)

        try:
            rows = await self._maps_repo.fetch_guides(code, include_records)
            return msgspec.convert(rows, list[GuideFullResponse], from_attributes=True)
        except Exception as e:
            log.error(f"Unexpected error fetching guides for {code}: {e}", exc_info=True)
            raise

    async def create_guide(
        self,
        code: OverwatchCode,
        data: GuideResponse,
    ) -> tuple[GuideResponse, dict]:
        """Create a guide for a map.

        Args:
            code: Map code.
            data: Guide data with user_id and url.

        Returns:
            Tuple of (created guide, context dict with map_data for newsfeed/XP).

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

        # Fetch map to check if official (needed for XP grant)
        map_data_result = await self._maps_repo.fetch_maps(single=True, code=code)
        map_data = msgspec.convert(map_data_result, MapResponse, from_attributes=True)

        # Return guide + context for controller
        return (
            data,
            {
                "map_data": map_data,
                "code": code,
                "url": data.url,
                "user_id": data.user_id,
            },
        )

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
            GuideNotFoundError: If guide doesn't exist for this user.
        """
        # Validate map exists
        map_id = await self._maps_repo.lookup_map_id(code)
        if map_id is None:
            raise MapNotFoundError(code)

        # Check guide exists
        try:
            guide_exists = await self._maps_repo.check_guide_exists(map_id, user_id)
            if not guide_exists:
                raise GuideNotFoundError(code, user_id)

            await self._maps_repo.update_guide(map_id, user_id, url)
            return GuideResponse(user_id=user_id, url=url)
        except GuideNotFoundError:
            raise
        except Exception as e:
            log.error(f"Unexpected error updating guide for {code}: {e}", exc_info=True)
            raise

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
            GuideNotFoundError: If guide doesn't exist for this user.
        """
        # Validate map exists
        map_id = await self._maps_repo.lookup_map_id(code)
        if map_id is None:
            raise MapNotFoundError(code)

        # Check guide exists
        try:
            guide_exists = await self._maps_repo.check_guide_exists(map_id, user_id)
            if not guide_exists:
                raise GuideNotFoundError(code, user_id)

            await self._maps_repo.delete_guide(map_id, user_id)
        except GuideNotFoundError:
            raise
        except Exception as e:
            log.error(f"Unexpected error deleting guide for {code}: {e}", exc_info=True)
            raise

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

        try:
            return await self._maps_repo.fetch_affected_users(code)
        except Exception as e:
            log.error(f"Unexpected error fetching affected users for {code}: {e}", exc_info=True)
            raise

    async def get_map_mastery_data(
        self,
        user_id: int,
        map_name: OverwatchMap | None = None,
    ) -> list[MapMasteryResponse]:
        """Get mastery data for a user, optionally scoped to a map.

        Args:
            user_id: Target user ID.
            map_name: Optional map name filter. If None, returns all maps.

        Returns:
            List of mastery records for the user.
        """
        rows = await self._maps_repo.fetch_map_mastery(user_id, map_name)
        return msgspec.convert(rows, list[MapMasteryResponse], from_attributes=True)

    async def update_mastery(
        self,
        data: MapMasteryCreateRequest,
    ) -> MapMasteryCreateResponse | None:
        """Update mastery for a user on a map."""
        result = await self._maps_repo.upsert_map_mastery(
            map_name=data.map_name,
            user_id=data.user_id,
            level=data.level,
        )

        if result is None:
            return None

        return msgspec.convert(result, MapMasteryCreateResponse, from_attributes=True)

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
        try:
            # Validate all codes exist
            for code in data.codes:
                map_id = await self._maps_repo.lookup_map_id(code)
                if map_id is None:
                    raise MapNotFoundError(code)

            # Update archive status
            is_archiving = data.status == "Archive"
            await self._maps_repo.set_archive_status(data.codes, is_archiving)

            # Publish newsfeed event
            if len(data.codes) == 1:
                # Single map archive/unarchive
                map_data = await self._maps_repo.fetch_maps(single=True, code=data.codes[0])
                map_response = msgspec.convert(map_data, MapResponse, from_attributes=True)

                event_payload: NewsfeedArchive | NewsfeedBulkArchive
                if is_archiving:
                    event_payload = NewsfeedArchive(
                        code=map_response.code,
                        map_name=map_response.map_name,
                        difficulty=map_response.difficulty,
                        creators=[c.name for c in map_response.creators] if map_response.creators else [],
                        reason="",
                    )
                else:
                    event_payload = NewsfeedUnarchive(  # type: ignore[assignment]
                        code=map_response.code,
                        map_name=map_response.map_name,
                        difficulty=map_response.difficulty,
                        creators=[c.name for c in map_response.creators] if map_response.creators else [],
                        reason="",
                    )
            elif is_archiving:
                event_payload = NewsfeedBulkArchive(
                    codes=data.codes,
                    reason="",
                )
            else:
                event_payload = NewsfeedBulkUnarchive(  # type: ignore[assignment]
                    codes=data.codes,
                    reason="",
                )

            if len(data.codes) == 1:
                event_type = "archive" if is_archiving else "unarchive"
            else:
                event_type = "bulk_archive" if is_archiving else "bulk_unarchive"
            event = NewsfeedEvent(
                id=None,
                timestamp=dt.datetime.now(dt.timezone.utc),
                payload=event_payload,
                event_type=event_type,
            )
            await newsfeed_service.create_and_publish(event=event, headers=headers)
        except MapNotFoundError:
            raise
        except Exception as e:
            log.error(f"Unexpected error setting archive status: {e}", exc_info=True)
            raise

    async def convert_to_legacy(
        self,
        code: OverwatchCode,
        reason: str = "",
    ) -> tuple[int, dict]:
        """Convert map to legacy status (public endpoint).

        Args:
            code: Map code.
            reason: Reason for legacy conversion.

        Returns:
            Tuple of (affected_count, context dict for newsfeed).

        Raises:
            MapNotFoundError: If map doesn't exist.
            MapValidationError: If pending verifications exist.
        """
        # Validate map exists
        map_id = await self._maps_repo.lookup_map_id(code)
        if map_id is None:
            raise MapNotFoundError(code)

        try:
            async with self._pool.acquire() as conn, conn.transaction():
                affected_count = await self._convert_to_legacy_internal(code, conn)  # type: ignore[arg-type]
                return (
                    affected_count,
                    {
                        "code": code,
                        "affected_count": affected_count,
                        "reason": reason,
                    },
                )
        except MapNotFoundError:
            raise
        except Exception as e:
            log.error(f"Unexpected error converting {code} to legacy: {e}", exc_info=True)
            raise

    async def _convert_to_legacy_internal(
        self,
        code: OverwatchCode,
        conn,  # noqa: ANN001
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
            # V3 raises exception (strict behavior)
            raise MapValidationError("Pending verifications exist for this map code.", field="code")

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
        """Override quality votes for a map with validation (admin only).

        Args:
            code: Map code.
            data: Quality value request.

        Raises:
            MapNotFoundError: If map doesn't exist.
            ValueError: If quality value is out of range (1-6).
        """
        # Validate quality value range
        min_quality = 1
        max_quality = 6
        if not min_quality <= data.value <= max_quality:
            raise ValueError(f"Quality must be between {min_quality} and {max_quality} (inclusive).")

        # Validate map exists
        map_id = await self._maps_repo.lookup_map_id(code)
        if map_id is None:
            raise MapNotFoundError(code)

        try:
            await self._maps_repo.override_quality_votes(code, data.value)
        except Exception as e:
            log.error(f"Unexpected error overriding quality for {code}: {e}", exc_info=True)
            raise

    async def get_trending_maps(
        self,
        limit: Literal[1, 3, 5, 10, 15, 20, 25] = 10,
        window_days: int = 14,
    ) -> list[TrendingMapResponse]:
        """Get trending maps with full calculation.

        Args:
            limit: Maximum number of trending maps to return.
            window_days: Time window for trending calculation (default 14 days).

        Returns:
            List of trending maps with scores.
        """
        rows = await self._maps_repo.fetch_trending_maps(
            limit=limit,
            window_days=window_days,
        )
        return msgspec.convert(rows, list[TrendingMapResponse], from_attributes=True)

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

        try:
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
                    DIFFICULTY_MIDPOINTS[data.initial_difficulty],
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
        except (MapNotFoundError, AlreadyInPlaytestError):
            raise
        except Exception as e:
            log.error(f"Unexpected error sending {code} to playtest: {e}", exc_info=True)
            raise

    def _create_cloned_map_data_payload(
        self,
        *,
        map_data: MapResponse,
        code: OverwatchCode,
        is_official: bool,
    ) -> MapCreateRequest:
        """Create a map creation payload by cloning an existing map.

        Generates a MapCreateRequest from an existing MapResponse, preserving all
        core fields such as creators, category, mechanics, and medals, while assigning
        a new map code. The clone is marked as hidden, unofficial, and playtesting-approved.

        Args:
            map_data: The source map data to clone.
            code: The new map code to assign to the cloned map.
            is_official: Whether the cloned map should be official (affects hidden and playtesting).

        Returns:
            MapCreateRequest: The fully prepared request for creating the cloned map.
        """
        creators = [Creator(c.id, c.is_primary) for c in map_data.creators]
        guide_url = map_data.guides[0] if map_data.guides else ""
        return MapCreateRequest(
            code=code,
            map_name=map_data.map_name,
            category=map_data.category,
            creators=creators,
            checkpoints=map_data.checkpoints,
            difficulty=map_data.difficulty,
            official=is_official,
            hidden=is_official,
            playtesting="In Progress" if is_official else "Approved",
            archived=False,
            mechanics=map_data.mechanics,
            restrictions=map_data.restrictions,
            description=map_data.description,
            medals=map_data.medals,
            guide_url=guide_url,
            title=map_data.title,
            custom_banner=map_data.map_banner,
        )

    async def link_map_codes(
        self,
        data: LinkMapsCreateRequest,
        headers: Headers,
        newsfeed_service: NewsfeedService,
    ) -> JobStatusResponse | None:
        """Link official and unofficial map codes, cloning as needed.

        Determines which maps exist and performs the appropriate operation:
        - Clone the official map if only it exists.
        - Clone the unofficial map and initiate playtesting if only it exists.
        - Link both directly if both exist.

        If a playtest is created, spawns a background task to wait for the job
        to complete before publishing the newsfeed event. Otherwise, publishes
        immediately.

        Args:
            data: Link request with official and unofficial codes.
            headers: Request headers for idempotency.
            newsfeed_service: Newsfeed service for event publishing.

        Returns:
            Job status if a clone operation was performed, None otherwise.

        Raises:
            LinkedMapError: If neither map exists or if maps are already linked.
        """
        try:
            # Fetch both maps (may be None)
            official_map_dict = await self._maps_repo.fetch_maps(single=True, code=data.official_code)
            unofficial_map_dict = await self._maps_repo.fetch_maps(single=True, code=data.unofficial_code)

            official_map = (
                msgspec.convert(official_map_dict, MapResponse, from_attributes=True) if official_map_dict else None
            )
            unofficial_map = (
                msgspec.convert(unofficial_map_dict, MapResponse, from_attributes=True) if unofficial_map_dict else None
            )

            # Validate at least one map exists
            if not official_map and not unofficial_map:
                raise LinkedMapError("At least one of official_code or unofficial_code must refer to an existing map.")

            # Check if already linked
            if official_map and official_map.linked_code:
                raise LinkedMapError(
                    f"Official map {data.official_code} is already linked to {official_map.linked_code}"
                )
            if unofficial_map and unofficial_map.linked_code:
                raise LinkedMapError(
                    f"Unofficial map {data.unofficial_code} is already linked to {unofficial_map.linked_code}"
                )

            # Determine operation type
            needs_clone_only = official_map and not unofficial_map
            needs_clone_and_playtest = not official_map and unofficial_map
            needs_link_only = official_map and unofficial_map

            job_status: JobStatusResponse | None = None
            in_playtest = False

            if needs_clone_only:
                log.debug("Cloning official map to create unofficial")
                payload = self._create_cloned_map_data_payload(
                    map_data=official_map,  # type: ignore[arg-type]
                    code=data.unofficial_code,
                    is_official=False,
                )
                creation_response = await self.create_map(payload, headers, newsfeed_service)
                await self._maps_repo.link_map_codes(data.official_code, data.unofficial_code)
                job_status = creation_response.job_status
                in_playtest = False

            elif needs_clone_and_playtest:
                log.debug("Cloning unofficial map to create official + playtest")
                payload = self._create_cloned_map_data_payload(
                    map_data=unofficial_map,  # type: ignore[arg-type]
                    code=data.official_code,
                    is_official=True,
                )
                creation_response = await self.create_map(payload, headers, newsfeed_service)
                await self._maps_repo.link_map_codes(data.official_code, data.unofficial_code)
                job_status = creation_response.job_status
                in_playtest = True

            elif needs_link_only:
                log.debug("Linking existing maps")
                await self._maps_repo.link_map_codes(data.official_code, data.unofficial_code)
                job_status = None
                in_playtest = False

            # Create newsfeed event
            event_payload = NewsfeedLinkedMap(
                official_code=data.official_code,
                unofficial_code=data.unofficial_code,
            )
            event = NewsfeedEvent(
                id=None,
                timestamp=dt.datetime.now(dt.timezone.utc),
                payload=event_payload,
                event_type="linked_map",
            )

            # Handle newsfeed publishing
            if in_playtest and job_status:
                # Spawn background task to wait for job completion before publishing
                task = asyncio.create_task(
                    self._wait_and_publish_linked_map_newsfeed(
                        job_status=job_status,
                        event=event,
                        headers=headers,
                        newsfeed_service=newsfeed_service,
                        official_code=data.official_code,
                    )
                )
                # Store reference to prevent premature garbage collection
                task.add_done_callback(lambda t: None)
            else:
                # Publish immediately
                await newsfeed_service.create_and_publish(event=event, headers=headers)

            return job_status

        except LinkedMapError:
            raise
        except Exception as e:
            log.error(f"Unexpected error linking maps: {e}", exc_info=True)
            raise

    async def _wait_and_publish_linked_map_newsfeed(
        self,
        *,
        job_status: JobStatusResponse,
        event: NewsfeedEvent,
        headers: Headers,
        newsfeed_service: NewsfeedService,
        official_code: OverwatchCode,
    ) -> None:
        """Wait for a job to complete, then publish a linked map newsfeed event.

        Args:
            job_status: The initial job status from map creation.
            event: The newsfeed event to publish.
            headers: HTTP headers for idempotency.
            newsfeed_service: Newsfeed service for publishing.
            official_code: The official map code (to fetch playtest info).
        """
        try:
            # Wait for job completion
            final_status = await wait_for_job_completion(
                job_id=job_status.id,
                fetch_status=self._get_job_status_using_pool,
                timeout=90.0,
            )

            if final_status.status == "succeeded":
                # Fetch map to get playtest ID (using connection pool)
                async with self._pool.acquire() as conn:
                    map_data_dict = await self._maps_repo.fetch_maps(single=True, code=official_code, conn=conn)  # type: ignore[arg-type]
                    map_data = msgspec.convert(map_data_dict, MapResponse, from_attributes=True)

                    # Add playtest ID to event if available
                    if map_data.playtest:
                        assert isinstance(event.payload, NewsfeedLinkedMap)
                        event.payload.playtest_id = map_data.playtest.thread_id

                    # Publish newsfeed event
                    await newsfeed_service.create_and_publish(event=event, headers=headers)
            else:
                log.warning(
                    "Skipping newsfeed publish for job %s (status=%s)",
                    final_status.id,
                    final_status.status,
                )

        except Exception:
            log.exception("Error while waiting for job completion for linked map newsfeed")
            # Don't re-raise - this is a background task

    async def _get_job_status_using_pool(self, job_id: UUID) -> JobStatusResponse | None:
        """Fetch job status using the connection pool.

        Args:
            job_id: The UUID of the job.

        Returns:
            Job status response or None if not found.
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, status, error_code, error_msg, created_at
                FROM public.jobs
                WHERE id = $1
                """,
                job_id,
            )
            if row:
                return msgspec.convert(dict(row), JobStatusResponse, from_attributes=True)
            return None

    async def unlink_map_codes(
        self,
        data: UnlinkMapsCreateRequest,
        headers: Headers,
        newsfeed_service: NewsfeedService,
    ) -> None:
        """Unlink map codes.

        Args:
            data: Unlink request with official and unofficial codes.
            headers: Request headers for idempotency.
            newsfeed_service: Newsfeed service for event publishing.

        Raises:
            MapNotFoundError: If either map doesn't exist.
        """
        try:
            # Validate both maps exist
            official_id = await self._maps_repo.lookup_map_id(data.official_code)
            if official_id is None:
                raise MapNotFoundError(data.official_code)

            unofficial_id = await self._maps_repo.lookup_map_id(data.unofficial_code)
            if unofficial_id is None:
                raise MapNotFoundError(data.unofficial_code)

            # Unlink the codes (uses official_code to find and remove link)
            await self._maps_repo.unlink_map_codes(data.official_code)

            # Publish newsfeed event
            event_payload = NewsfeedUnlinkedMap(
                official_code=data.official_code,
                unofficial_code=data.unofficial_code,
                reason=data.reason,
            )
            event = NewsfeedEvent(
                id=None,
                timestamp=dt.datetime.now(dt.timezone.utc),
                payload=event_payload,
                event_type="unlinked_map",
            )
            await newsfeed_service.create_and_publish(event=event, headers=headers)
        except MapNotFoundError:
            raise
        except Exception as e:
            log.error(f"Unexpected error unlinking {data.official_code}: {e}", exc_info=True)
            raise

    async def get_playtest_plot(
        self,
        *,
        thread_id: int | None = None,
        code: OverwatchCode | None = None,
    ) -> Stream:
        """Get playtest plot as image stream from external plotter service.

        When code is provided (and thread_id is omitted), the initial difficulty may be
        the only datapoint—intended for early initialization before votes exist.

        Args:
            thread_id: Playtest thread ID.
            code: Map code (alternative).

        Returns:
            Stream with WebP image and headers.

        Raises:
            MapNotFoundError: If map doesn't exist.
            ValueError: If neither thread_id nor code provided.
            HTTPException: 503 if plotter service unavailable.
        """
        # Fetch difficulty data based on input
        async with self._pool.acquire() as conn:
            if code and not thread_id:
                # Fetch initial difficulty for new playtest
                rows = await conn.fetch(
                    """
                    WITH target_map AS (
                        SELECT id FROM core.maps WHERE code = $1
                    )
                    SELECT initial_difficulty AS difficulty, 1 AS amount
                    FROM playtests.meta
                    WHERE map_id = (SELECT id FROM target_map) AND completed=FALSE
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    code,
                )
            elif thread_id:
                # Fetch votes + initial difficulty
                rows = await conn.fetch(
                    """
                    SELECT difficulty, count(*) AS amount
                    FROM playtests.votes
                    WHERE playtest_thread_id = $1
                    GROUP BY difficulty
                    UNION ALL
                    SELECT initial_difficulty AS difficulty, 1 AS amount
                    FROM playtests.meta
                    WHERE thread_id = $1
                      AND NOT EXISTS (
                        SELECT 1 FROM playtests.votes WHERE playtest_thread_id = $1
                    )
                    """,
                    thread_id,
                )
            else:
                raise ValueError("At least one of code or thread_id is required")

            if not rows:
                raise MapNotFoundError(code or str(thread_id))

            # Convert to votes dict for plotter API
            votes: dict[str, int] = {
                str(convert_raw_difficulty_to_difficulty_all(row["difficulty"])): row["amount"] for row in rows
            }

        # Call external plotter service
        plotter_url = "http://genjishimada-playtest-plotter:8080/chart"
        try:
            async with (
                aiohttp.ClientSession() as session,
                session.post(
                    plotter_url,
                    json={"votes": votes},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp,
            ):
                if resp.status != HTTP_200_OK:
                    log.error(f"Plotter service returned {resp.status}: {await resp.text()}")
                    raise HTTPException(
                        status_code=HTTP_503_SERVICE_UNAVAILABLE,
                        detail="Chart generation service unavailable",
                    )
                image_bytes = await resp.read()
        except aiohttp.ClientError as e:
            log.error(f"Failed to connect to plotter service: {e}")
            raise HTTPException(
                status_code=HTTP_503_SERVICE_UNAVAILABLE,
                detail="Chart generation service unavailable",
            ) from e

        # Return Stream with headers
        return Stream(
            iter([image_bytes]),
            headers={
                "content-type": "image/webp",
                "content-disposition": 'attachment; filename="playtest.webp"',
            },
        )

    # Edit request operations

    async def create_edit_request(
        self,
        code: str,
        proposed_changes: dict[str, Any],
        reason: str,
        created_by: int,
        headers: Headers,
    ) -> MapEditResponse:
        """Create a new map edit request.

        Args:
            code: Map code.
            proposed_changes: Dict of field -> new_value.
            reason: Reason for the edit.
            created_by: User ID of submitter.
            headers: Request headers for RabbitMQ idempotency.

        Returns:
            Created edit request.

        Raises:
            MapNotFoundError: If map doesn't exist.
            PendingEditRequestExistsError: If map already has pending request.
        """
        # Validate map exists
        map_id = await self._maps_repo.lookup_map_id(code)
        if map_id is None:
            raise MapNotFoundError(code)

        # Check for existing pending request
        existing_id = await self._maps_repo.check_pending_edit_request(map_id)
        if existing_id is not None:
            raise PendingEditRequestExistsError(code, existing_id)

        # Create edit request
        try:
            row = await self._maps_repo.create_edit_request(
                map_id=map_id,
                code=code,
                proposed_changes=proposed_changes,
                reason=reason,
                created_by=created_by,
            )
        except ForeignKeyViolationError as e:
            # Should not happen since we validated map_id, but handle gracefully
            if "created_by" in e.constraint_name:
                raise CreatorNotFoundError() from e
            raise

        # Convert to response
        edit_response = self._row_to_edit_response(row)

        # Publish RabbitMQ event for bot
        await self.publish_message(
            routing_key="api.map_edit.created",
            data=MapEditCreatedEvent(edit_request_id=edit_response.id),
            headers=headers,
            idempotency_key=f"map_edit:created:{edit_response.id}",
        )

        return edit_response

    async def get_edit_request(self, edit_id: int) -> MapEditResponse:
        """Get a specific edit request.

        Args:
            edit_id: Edit request ID.

        Returns:
            Edit request.

        Raises:
            EditRequestNotFoundError: If not found.
        """
        row = await self._maps_repo.fetch_edit_request(edit_id)
        if row is None:
            raise EditRequestNotFoundError(edit_id)

        return self._row_to_edit_response(row)

    async def get_pending_requests(self) -> list[PendingMapEditResponse]:
        """Get all pending edit requests.

        Returns:
            List of pending requests.
        """
        rows = await self._maps_repo.fetch_pending_edit_requests()
        return [
            PendingMapEditResponse(
                id=row["id"],
                code=row["code"],
                message_id=row["message_id"],
            )
            for row in rows
        ]

    async def get_edit_submission(
        self,
        edit_id: int,
        get_creator_name: Callable[[int], str | Awaitable[str]] | None = None,
    ) -> MapEditSubmissionResponse:
        """Get enriched edit submission data for verification queue.

        Args:
            edit_id: Edit request ID.
            get_creator_name: Function to resolve creator names.

        Returns:
            Enriched submission data.

        Raises:
            EditRequestNotFoundError: If not found.
        """
        data = await self._maps_repo.fetch_edit_submission(edit_id)
        if data is None:
            raise EditRequestNotFoundError(edit_id)

        edit_req = data["edit_request"]
        current_map = data["current_map"]
        current_creators = data["current_creators"]
        current_medals = data["current_medals"]
        submitter_name = data["submitter_name"]

        # Parse proposed changes
        proposed_changes = edit_req["proposed_changes"]
        if isinstance(proposed_changes, str):
            proposed_changes = msgspec.json.decode(proposed_changes)

        # Build current map data dict for comparison
        map_data = dict(current_map)
        map_data["creators"] = [{"id": c["user_id"], "is_primary": c["is_primary"]} for c in current_creators]

        # Build human-readable changes
        changes = await self._build_field_changes(
            map_data,
            current_medals,
            proposed_changes,
            get_creator_name=get_creator_name,
        )

        return MapEditSubmissionResponse(
            id=edit_req["id"],
            code=edit_req["code"],
            map_name=edit_req["map_name"],
            difficulty=edit_req["difficulty"],
            changes=changes,
            reason=edit_req["reason"],
            submitter_name=submitter_name,
            submitter_id=edit_req["created_by"],
            created_at=edit_req["created_at"],
            message_id=edit_req["message_id"],
        )

    async def set_edit_message_id(self, edit_id: int, message_id: int) -> None:
        """Set Discord message ID for edit request.

        Args:
            edit_id: Edit request ID.
            message_id: Discord message ID.

        Raises:
            EditRequestNotFoundError: If edit request doesn't exist.
        """
        # Validate exists
        row = await self._maps_repo.fetch_edit_request(edit_id)
        if row is None:
            raise EditRequestNotFoundError(edit_id)

        await self._maps_repo.set_edit_request_message_id(edit_id, message_id)

    async def resolve_edit_request(  # noqa: PLR0913
        self,
        edit_id: int,
        accepted: bool,
        resolved_by: int,
        rejection_reason: str | None,
        send_to_playtest: bool,
        headers: Headers,
        newsfeed_service: NewsfeedService,
        notification_service: NotificationsService,
        user_service: UsersService,
    ) -> None:
        """Resolve an edit request (accept or reject).

        If accepted:
        - Applies proposed changes to map
        - Handles archive separately (special newsfeed)
        - Generates newsfeed for non-archive changes
        - Optionally sends to playtest
        - Sends notification to submitter
        - Publishes RabbitMQ cleanup event

        Args:
            edit_id: Edit request ID.
            accepted: Whether accepted or rejected.
            resolved_by: User ID of resolver.
            rejection_reason: Reason for rejection (if rejected).
            send_to_playtest: Whether to send map to playtest after accepting.
            headers: Request headers for RabbitMQ idempotency.
            newsfeed_service: Newsfeed service.
            notification_service: Notification service.
            user_service: User service.

        Raises:
            EditRequestNotFoundError: If edit request doesn't exist.
            MapNotFoundError: If map doesn't exist.
        """
        # Get edit request
        edit_request = await self.get_edit_request(edit_id)

        if accepted:
            # Get original map for newsfeed comparison
            original_map = msgspec.convert(
                await self._maps_repo.fetch_maps(single=True, code=edit_request.code),
                MapResponse,
                from_attributes=True,
            )

            # Handle archive change separately
            has_archive_change = "archived" in edit_request.proposed_changes
            remaining_changes: dict = {}

            if has_archive_change:
                archived_value = edit_request.proposed_changes["archived"]

                # Perform archive/unarchive via repository
                await self._maps_repo.set_archive_status([edit_request.code], bool(archived_value))

                if archived_value:
                    payload = NewsfeedArchive(
                        code=edit_request.code,
                        map_name=original_map.map_name,
                        creators=[c.name for c in original_map.creators],
                        difficulty=original_map.difficulty,
                        reason=edit_request.reason,
                    )
                    event_type = "archive"
                else:
                    payload = NewsfeedUnarchive(  # type: ignore[assignment]
                        code=edit_request.code,
                        map_name=original_map.map_name,
                        creators=[c.name for c in original_map.creators],
                        difficulty=original_map.difficulty,
                        reason=edit_request.reason,
                    )
                    event_type = "unarchive"

                # Publish newsfeed
                event = NewsfeedEvent(
                    id=None,
                    timestamp=dt.datetime.now(dt.timezone.utc),
                    payload=payload,
                    event_type=event_type,
                )
                await newsfeed_service.create_and_publish(event=event, headers=headers)

                # Remaining changes (without archived)
                remaining_changes = {k: v for k, v in edit_request.proposed_changes.items() if k != "archived"}

                # Apply remaining changes if any
                if remaining_changes:
                    patch_data = self.convert_changes_to_patch(remaining_changes)
                    await self.update_map(edit_request.code, patch_data)
            else:
                # No archive change, apply all changes
                patch_data = self.convert_changes_to_patch(edit_request.proposed_changes)
                await self.update_map(edit_request.code, patch_data)
                remaining_changes = edit_request.proposed_changes

            # Generate newsfeed for non-archive changes
            if remaining_changes:

                async def _get_user_coalesced_name(user_id: int) -> str:
                    user = await user_service.get_user(user_id)
                    if user:
                        return user.coalesced_name or "Unknown User"
                    return "Unknown User"

                newsfeed_patch = self.convert_changes_to_patch(remaining_changes)
                await newsfeed_service.generate_map_edit_newsfeed(
                    original_map,
                    newsfeed_patch,
                    edit_request.reason,
                    headers,
                    get_creator_name=_get_user_coalesced_name,
                )

        # Mark as resolved
        await self._maps_repo.resolve_edit_request(
            edit_id=edit_id,
            accepted=accepted,
            resolved_by=resolved_by,
            rejection_reason=rejection_reason,
        )

        # Send to playtest if requested and accepted
        if accepted and send_to_playtest:
            try:
                # Get difficulty from proposed changes or use original
                playtest_difficulty = edit_request.proposed_changes.get("difficulty")
                if not playtest_difficulty:
                    original_map = msgspec.convert(
                        await self._maps_repo.fetch_maps(single=True, code=edit_request.code),
                        MapResponse,
                        from_attributes=True,
                    )
                    playtest_difficulty = original_map.difficulty

                await self.send_to_playtest(
                    code=edit_request.code,
                    data=SendToPlaytestRequest(initial_difficulty=playtest_difficulty),
                    headers=headers,
                )
            except Exception as e:
                # Log but don't fail resolution
                log.error(
                    f"Failed to send map {edit_request.code} to playtest after edit: {e}",
                    exc_info=True,
                )

        # Send notification to submitter
        await self._send_edit_resolution_notification(
            notification_service,
            edit_request,
            accepted,
            rejection_reason,
            headers,
        )

        # Publish RabbitMQ cleanup event
        await self.publish_message(
            routing_key="api.map_edit.resolved",
            data=MapEditResolvedEvent(
                edit_request_id=edit_id,
                accepted=accepted,
                resolved_by=resolved_by,
                rejection_reason=rejection_reason,
            ),
            headers=headers,
            idempotency_key=f"map_edit:resolved:{edit_id}",
        )

    async def get_user_edit_requests(
        self,
        user_id: int,
        include_resolved: bool = False,
    ) -> list[MapEditResponse]:
        """Get edit requests submitted by a user.

        Args:
            user_id: User ID.
            include_resolved: Whether to include resolved requests.

        Returns:
            List of edit requests.
        """
        rows = await self._maps_repo.fetch_user_edit_requests(
            user_id,
            include_resolved,
        )
        return [self._row_to_edit_response(row) for row in rows]

    # Edit request helper methods

    @staticmethod
    def _row_to_edit_response(row: dict) -> MapEditResponse:
        """Convert database row to MapEditResponse."""
        proposed_changes = row["proposed_changes"]
        if isinstance(proposed_changes, str):
            proposed_changes = msgspec.json.decode(proposed_changes)

        return MapEditResponse(
            id=row["id"],
            map_id=row["map_id"],
            code=row["code"],
            proposed_changes=proposed_changes,
            reason=row["reason"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            message_id=row["message_id"],
            resolved_at=row["resolved_at"],
            accepted=row["accepted"],
            resolved_by=row["resolved_by"],
            rejection_reason=row["rejection_reason"],
        )

    async def _build_field_changes(
        self,
        current_map: dict[str, Any],
        current_medals: dict[str, Any] | None,
        proposed: dict[str, Any],
        get_creator_name: Callable[[int], str | Awaitable[str]] | None = None,
    ) -> list[MapEditFieldChange]:
        """Build human-readable field change list.

        Only includes fields that have actually changed. For creators, compares
        by id and is_primary, ignoring display-only name field.
        """
        changes = []

        for field_name, new_value in proposed.items():
            if field_name == "medals":
                old_value = (
                    {
                        "gold": current_medals["gold"],
                        "silver": current_medals["silver"],
                        "bronze": current_medals["bronze"],
                    }
                    if current_medals
                    else None
                )
            else:
                old_value = current_map.get(field_name)

            # Check if value actually changed (using same logic as newsfeed service)
            if field_name == "creators":
                # Compare only id and is_primary, ignoring name field
                old_normalized = self._normalize_creators_for_comparison(old_value)
                new_normalized = self._normalize_creators_for_comparison(new_value)
                if old_normalized == new_normalized:
                    continue  # Skip unchanged creators
            elif old_value == new_value:
                continue  # Skip unchanged values

            # Format for display
            if field_name == "creators":
                old_display = await self._format_creators_for_display(
                    old_value,
                    get_creator_name,
                )
                new_display = await self._format_creators_for_display(
                    new_value,
                    get_creator_name,
                )
            else:
                old_display = self._format_value_for_display(field_name, old_value)
                new_display = self._format_value_for_display(field_name, new_value)

            # Convert field name to display name
            display_name = field_name.replace("_", " ").title()

            changes.append(
                MapEditFieldChange(
                    field=display_name,
                    old_value=old_display,
                    new_value=new_display,
                )
            )

        return changes

    @staticmethod
    def _normalize_creators_for_comparison(value: Any) -> list[tuple[int, bool]]:  # noqa: ANN401
        """Normalize creators for comparison, extracting only id and is_primary.

        Args:
            value: Creator data (list of dicts or Creator objects, or None).

        Returns:
            Sorted list of (id, is_primary) tuples for comparison.
        """
        if value is None:
            return []

        if not value:
            return []

        if isinstance(value, dict):
            value = [value]

        if not isinstance(value, list):
            return []

        normalized = []
        for creator in value:
            if isinstance(creator, dict):
                creator_id = creator.get("id")
                is_primary = creator.get("is_primary")
            else:
                creator_id = getattr(creator, "id", None)
                is_primary = getattr(creator, "is_primary", None)

            if creator_id is not None and is_primary is not None:
                normalized.append((creator_id, is_primary))

        return sorted(normalized)

    @staticmethod
    async def _format_creators_for_display(
        value: Any,  # noqa: ANN401
        get_creator_name: Callable[[int], str | Awaitable[str]] | None = None,
    ) -> str:
        """Format creator values for display."""
        if value is None:
            return "Not set"

        if not value:
            return "None"

        if isinstance(value, dict):
            value = [value]

        if not isinstance(value, list):
            return str(value)

        rendered = []
        for creator in value:
            if isinstance(creator, dict):
                creator_id = creator.get("id")
                is_primary = creator.get("is_primary")
                name = creator.get("name")
            else:
                creator_id = getattr(creator, "id", None)
                is_primary = getattr(creator, "is_primary", None)
                name = getattr(creator, "name", None)

            if not name and creator_id and get_creator_name:
                resolved = get_creator_name(int(creator_id))
                name = await resolved if inspect.isawaitable(resolved) else resolved
            if not name:
                name = "Unknown User"

            primary_suffix = "primary, " if is_primary else ""
            if creator_id:
                rendered.append(f"{name} ({primary_suffix}{creator_id})")
            else:
                rendered.append(name)

        return ", ".join(rendered)

    @staticmethod
    def _format_value_for_display(
        field: str,
        value: str | float | bool | list | dict | None,
    ) -> str:
        """Format field value for display."""
        if value is None:
            return "Not set"

        # Boolean fields
        if field in ("hidden", "archived", "official"):
            return "Yes" if value else "No"

        # Medal fields
        if field == "medals" and isinstance(value, dict):
            return f"🥇 {value.get('gold')} | 🥈 {value.get('silver')} | 🥉 {value.get('bronze')}"

        # List fields
        if isinstance(value, list):
            return ", ".join(str(v) for v in value) if value else "None"

        return str(value)

    @staticmethod
    def convert_changes_to_patch(proposed_changes: dict[str, Any]) -> MapPatchRequest:
        """Convert proposed_changes dict to MapPatchRequest."""
        kwargs: dict[str, Any] = {}

        for field, field_value in proposed_changes.items():
            if field == "medals" and field_value is not None:
                kwargs[field] = MedalsResponse(**field_value)
            elif field == "creators" and field_value is not None:
                creators = [creator if isinstance(creator, Creator) else Creator(**creator) for creator in field_value]
                kwargs[field] = creators
            else:
                kwargs[field] = field_value

        return MapPatchRequest(**kwargs)

    async def _send_edit_resolution_notification(
        self,
        notification_service: NotificationsService,
        edit_request: MapEditResponse,
        accepted: bool,
        rejection_reason: str | None,
        headers: Headers,
    ) -> None:
        """Send notification to edit request submitter."""
        if accepted:
            event_type = NotificationEventType.MAP_EDIT_APPROVED.value
            title = "Map Edit Approved"
            body = f"Your edit request for {edit_request.code} has been approved and your changes have been applied."
            discord_message = (
                f"✅ Your edit request for **{edit_request.code}** has been **approved**!\n"
                "Your changes have been applied to the map."
            )
        else:
            event_type = NotificationEventType.MAP_EDIT_REJECTED.value
            title = "Map Edit Rejected"
            body = f"Your edit request for {edit_request.code} was rejected."
            if rejection_reason:
                body += f" Reason: {rejection_reason}"
            discord_message = f"❌ Your edit request for **{edit_request.code}** has been **rejected**."
            if rejection_reason:
                discord_message += f"\n**Reason:** {rejection_reason}"

        notification_data = NotificationCreateRequest(
            user_id=edit_request.created_by,
            event_type=event_type,
            title=title,
            body=body,
            discord_message=discord_message,
            metadata={
                "map_code": edit_request.code,
                "edit_id": edit_request.id,
                "rejection_reason": rejection_reason,
            },
        )

        await notification_service.create_and_dispatch(notification_data, headers)


async def provide_maps_service(
    state: State,
    maps_repo: MapsRepository,
) -> MapsService:
    """Litestar DI provider for service."""
    return MapsService(state.db_pool, state, maps_repo)
