"""V4 Maps routes."""

from __future__ import annotations

import datetime as dt
import logging
import re
from typing import Annotated, Literal

from genjishimada_sdk.difficulties import DifficultyTop
from genjishimada_sdk.internal import JobStatusResponse
from genjishimada_sdk.maps import (
    ArchivalStatusPatchRequest,
    GuideFullResponse,
    GuideResponse,
    GuideURL,
    LinkMapsCreateRequest,
    MapCategory,
    MapCreateRequest,
    MapCreationJobResponse,
    MapMasteryCreateRequest,
    MapMasteryCreateResponse,
    MapMasteryResponse,
    MapPartialResponse,
    MapPatchRequest,
    MapResponse,
    Mechanics,
    OverwatchCode,
    OverwatchMap,
    PlaytestStatus,
    QualityValueRequest,
    Restrictions,
    SendToPlaytestRequest,
    SortKey,
    Tags,
    TrendingMapResponse,
    UnlinkMapsCreateRequest,
)
from genjishimada_sdk.newsfeed import NewsfeedEvent, NewsfeedGuide, NewsfeedLegacyRecord
from genjishimada_sdk.xp import XP_AMOUNTS, XpGrantRequest
from litestar import Controller, delete, get, patch, post
from litestar.connection import Request
from litestar.di import Provide
from litestar.params import Body, Parameter
from litestar.response import Response, Stream
from litestar.status_codes import (
    HTTP_201_CREATED,
    HTTP_204_NO_CONTENT,
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
)

from repository.maps_repository import provide_maps_repository
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
from services.lootbox_service import LootboxService, provide_lootbox_service
from services.maps_service import MapsService, provide_maps_service
from services.newsfeed_service import NewsfeedService, provide_newsfeed_service
from services.users_service import UsersService, provide_users_service
from utilities.errors import CustomHTTPException
from utilities.map_search import CompletionFilter, MapSearchFilters, MedalFilter, PlaytestFilter

log = logging.getLogger(__name__)


class MapsController(Controller):
    """Base maps operations."""

    tags = ["Maps"]
    path = "/maps"
    dependencies = {
        "maps_repo": Provide(provide_maps_repository),
        "maps_service": Provide(provide_maps_service),
        "newsfeed_service": Provide(provide_newsfeed_service),
        "lootbox_service": Provide(provide_lootbox_service),
        "users_service": Provide(provide_users_service),
    }

    @get(
        "/",
        summary="Search Maps",
        description="Search and filter maps with comprehensive filtering options.",
        opt={"required_scopes": {"maps:read"}},
    )
    async def get_maps_endpoint(  # noqa: PLR0913
        self,
        maps_service: MapsService,
        # Core filters
        code: Annotated[OverwatchCode | None, Parameter(description="Filter by map code")] = None,
        playtest_status: Annotated[PlaytestStatus | None, Parameter(description="Filter by playtest status")] = None,
        archived: Annotated[bool | None, Parameter(description="Filter by archived status")] = None,
        hidden: Annotated[bool | None, Parameter(description="Filter by hidden status")] = None,
        official: Annotated[bool | None, Parameter(description="Filter by official status")] = None,
        playtest_thread_id: Annotated[int | None, Parameter(description="Filter by playtest thread ID")] = None,
        # Map attributes
        category: Annotated[list[MapCategory] | None, Parameter(description="Filter by category list")] = None,
        map_name: Annotated[list[OverwatchMap] | None, Parameter(description="Filter by map name list")] = None,
        difficulty_exact: Annotated[
            DifficultyTop | None, Parameter(description="Filter by exact difficulty tier")
        ] = None,
        difficulty_range_min: Annotated[
            DifficultyTop | None, Parameter(description="Filter by minimum difficulty")
        ] = None,
        difficulty_range_max: Annotated[
            DifficultyTop | None, Parameter(description="Filter by maximum difficulty")
        ] = None,
        # Related data (AND semantics)
        mechanics: Annotated[
            list[Mechanics] | None, Parameter(description="Filter by mechanics (AND semantics)")
        ] = None,
        restrictions: Annotated[
            list[Restrictions] | None, Parameter(description="Filter by restrictions (AND semantics)")
        ] = None,
        tags: Annotated[list[Tags] | None, Parameter(description="Filter by tags (AND semantics)")] = None,
        # Creator filters
        creator_ids: Annotated[list[int] | None, Parameter(description="Filter by creator user IDs")] = None,
        creator_names: Annotated[list[str] | None, Parameter(description="Filter by creator names")] = None,
        # User context
        user_id: Annotated[int | None, Parameter(description="User ID for completion/medal filtering")] = None,
        medal_filter: Annotated[MedalFilter, Parameter(description="Medal filter (All/With/Without)")] = "All",
        completion_filter: Annotated[
            CompletionFilter, Parameter(description="Completion filter (All/With/Without)")
        ] = "All",
        playtest_filter: Annotated[PlaytestFilter, Parameter(description="Playtest filter (All/Only/None)")] = "All",
        # Quality
        minimum_quality: Annotated[int | None, Parameter(description="Minimum average quality rating")] = None,
        # Pagination
        page_size: Annotated[Literal[10, 20, 25, 50, 12], Parameter(description="Results per page")] = 10,
        page_number: Annotated[int, Parameter(description="Page number (1-indexed)")] = 1,
        # Sorting
        sort: Annotated[list[SortKey] | None, Parameter(description="List of 'field:direction' sort keys")] = None,
        # Special
        finalized_playtests: Annotated[bool | None, Parameter(description="Filter finalized playtests")] = None,
        return_all: Annotated[bool, Parameter(description="Return all results without pagination")] = False,
        force_filters: Annotated[bool, Parameter(description="Force filters even with code param")] = False,
    ) -> list[MapResponse]:
        """Search maps with full filtering support.

        Returns:
            List of maps matching filters.

        Raises:
            CustomHTTPException: On validation errors.
        """
        try:
            filters = MapSearchFilters(
                code=code,
                playtesting=playtest_status,
                archived=archived,
                hidden=hidden,
                official=official,
                playtest_thread_id=playtest_thread_id,
                category=category,
                map_name=map_name,
                difficulty_exact=difficulty_exact,
                difficulty_range_min=difficulty_range_min,
                difficulty_range_max=difficulty_range_max,
                mechanics=mechanics,
                restrictions=restrictions,
                tags=tags,
                creator_ids=creator_ids,
                creator_names=creator_names,
                user_id=user_id,
                medal_filter=medal_filter,
                completion_filter=completion_filter,
                playtest_filter=playtest_filter,
                minimum_quality=minimum_quality,
                page_size=page_size,
                page_number=page_number,
                sort=sort,
                finalized_playtests=finalized_playtests,
                return_all=return_all,
                force_filters=force_filters,
            )

            return await maps_service.fetch_maps(filters=filters, single=False)

        except ValueError as e:
            raise CustomHTTPException(
                detail=f"Invalid filter parameters: {e}",
                status_code=HTTP_400_BAD_REQUEST,
            ) from e

    @get(
        "/{code:str}/partial",
        summary="Get Partial Map",
        opt={"required_scopes": {"maps:read"}},
    )
    async def get_partial_map_endpoint(
        self,
        code: OverwatchCode,
        maps_service: MapsService,
    ) -> MapPartialResponse:
        """Get partial map data.

        Args:
            code: Map code.
            maps_service: Maps service.

        Returns:
            Partial map response.

        Raises:
            CustomHTTPException: If map not found.
        """
        try:
            return await maps_service.fetch_partial_map(code)

        except MapNotFoundError as e:
            raise CustomHTTPException(
                detail=f"No map found with code: {code}",
                status_code=HTTP_404_NOT_FOUND,
            ) from e

    @post(
        "/",
        summary="Create Map",
        status_code=HTTP_201_CREATED,
        opt={"required_scopes": {"maps:write"}},
    )
    async def create_map_endpoint(
        self,
        data: Annotated[MapCreateRequest, Body(title="Map creation request")],
        maps_service: MapsService,
        newsfeed_service: NewsfeedService,
        request: Request,
    ) -> MapCreationJobResponse:
        """Create a new map.

        Args:
            data: Map creation request.
            maps_service: Maps service.
            newsfeed_service: Newsfeed service.
            request: Request object.

        Returns:
            Map creation response with optional job status.

        Raises:
            CustomHTTPException: On validation or business rule errors.
        """
        try:
            return await maps_service.create_map(data, request.headers, newsfeed_service)

        except MapCodeExistsError as e:
            raise CustomHTTPException(
                detail="Provided code already exists.",
                status_code=HTTP_400_BAD_REQUEST,
            ) from e

        except DuplicateMechanicError as e:
            raise CustomHTTPException(
                detail="You have a duplicate mechanic.",
                status_code=HTTP_400_BAD_REQUEST,
            ) from e

        except DuplicateRestrictionError as e:
            raise CustomHTTPException(
                detail="You have a duplicate restriction.",
                status_code=HTTP_400_BAD_REQUEST,
            ) from e

        except DuplicateCreatorError as e:
            raise CustomHTTPException(
                detail="You have a duplicate creator ID.",
                status_code=HTTP_400_BAD_REQUEST,
            ) from e

        except CreatorNotFoundError as e:
            raise CustomHTTPException(
                detail="There is no user associated with supplied ID.",
                status_code=HTTP_400_BAD_REQUEST,
            ) from e

    @patch(
        "/{code:str}",
        summary="Update Map",
        opt={"required_scopes": {"maps:write"}},
    )
    async def update_map_endpoint(  # noqa: PLR0913
        self,
        code: OverwatchCode,
        data: Annotated[MapPatchRequest, Body(title="Map update request")],
        request: Request,
        maps_service: MapsService,
        newsfeed_service: NewsfeedService,
        users_service: UsersService,
    ) -> MapResponse:
        """Update a map.

        Args:
            code: Map code to update.
            data: Partial update request.
            request: Request object.
            maps_service: Maps service.
            newsfeed_service: Newsfeed service.
            users_service: Users service.

        Returns:
            Updated map response.

        Raises:
            CustomHTTPException: On validation or business rule errors.
        """
        try:
            updated_map, original_map = await maps_service.update_map(code, data)

            # Helper to get user name
            async def _get_user_coalesced_name(user_id: int) -> str:
                user = await users_service.get_user(user_id)
                if user:
                    return user.coalesced_name or "Unknown User"
                return "Unknown User"

            # Generate and publish newsfeed event
            await newsfeed_service.generate_map_edit_newsfeed(
                original_map,
                data,
                "",
                request.headers,
                get_creator_name=_get_user_coalesced_name,
            )

            return updated_map

        except MapNotFoundError as e:
            raise CustomHTTPException(
                detail=f"No map found with code: {code}",
                status_code=HTTP_404_NOT_FOUND,
            ) from e

        except MapCodeExistsError as e:
            raise CustomHTTPException(
                detail="Provided code already exists.",
                status_code=HTTP_400_BAD_REQUEST,
            ) from e

        except DuplicateMechanicError as e:
            raise CustomHTTPException(
                detail="You have a duplicate mechanic.",
                status_code=HTTP_400_BAD_REQUEST,
            ) from e

        except DuplicateRestrictionError as e:
            raise CustomHTTPException(
                detail="You have a duplicate restriction.",
                status_code=HTTP_400_BAD_REQUEST,
            ) from e

        except DuplicateCreatorError as e:
            raise CustomHTTPException(
                detail="You have a duplicate creator ID.",
                status_code=HTTP_400_BAD_REQUEST,
            ) from e

        except CreatorNotFoundError as e:
            raise CustomHTTPException(
                detail="There is no user associated with supplied ID.",
                status_code=HTTP_400_BAD_REQUEST,
            ) from e

    @get(
        "/{code:str}/exists",
        summary="Check Code Exists",
        opt={"required_scopes": {"maps:read"}},
    )
    async def check_code_exists_endpoint(
        self,
        code: str,
        maps_service: MapsService,
    ) -> bool:
        """Check if a map code exists with format validation.

        Args:
            code: Map code to check.
            maps_service: Maps service.

        Returns:
            True if code exists, False otherwise.

        Raises:
            CustomHTTPException: 400 if code format invalid.
        """
        # Validate code format
        if not re.match(r"^[A-Z0-9]{4,6}$", code):
            raise CustomHTTPException(
                detail="Provided code is not valid. Must follow regex ^[A-Z0-9]{4,6}$",
                status_code=HTTP_400_BAD_REQUEST,
                extra={"code": code},
            )

        return await maps_service.check_code_exists(code)

    @get(
        "/{code:str}/plot",
        summary="Get Map Plot Data",
        opt={"required_scopes": {"maps:read"}},
    )
    async def get_map_plot_endpoint(
        self,
        code: OverwatchCode,
        maps_service: MapsService,
    ) -> Stream:
        """Get playtest plot image for a map.

        Args:
            code: Map code.
            maps_service: Maps service.

        Returns:
            Plot data object.

        Raises:
            CustomHTTPException: If map not found.
        """
        try:
            return await maps_service.get_playtest_plot(code=code)

        except MapNotFoundError as e:
            raise CustomHTTPException(
                detail=f"No map found with code: {code}",
                status_code=HTTP_404_NOT_FOUND,
            ) from e

    @get(
        "/{code:str}/guides",
        summary="Get Guides",
        opt={"required_scopes": {"maps:read"}},
    )
    async def get_guides_endpoint(
        self,
        maps_service: MapsService,
        code: OverwatchCode,
        include_records: bool = False,
    ) -> list[GuideFullResponse]:
        """Get guides for a map.

        Args:
            code: Map code.
            include_records: Whether to include completion records.
            maps_service: Maps service.

        Returns:
            List of guides.

        Raises:
            CustomHTTPException: If map not found.
        """
        try:
            return await maps_service.get_guides(code, include_records)

        except MapNotFoundError as e:
            raise CustomHTTPException(
                detail=f"No map found with code: {code}",
                status_code=HTTP_404_NOT_FOUND,
            ) from e

    @post(
        "/{code:str}/guides",
        summary="Create Guide",
        status_code=HTTP_201_CREATED,
        opt={"required_scopes": {"maps:write"}},
    )
    async def create_guide_endpoint(  # noqa: PLR0913
        self,
        code: OverwatchCode,
        data: Annotated[GuideResponse, Body(title="Guide data")],
        request: Request,
        maps_service: MapsService,
        lootbox_service: LootboxService,
        newsfeed_service: NewsfeedService,
        users_service: UsersService,
    ) -> Response[GuideResponse]:
        """Create a guide for a map.

        Args:
            code: Map code.
            data: Guide data with user_id and url.
            request: Request object.
            maps_service: Maps service.
            lootbox_service: Lootbox service.
            newsfeed_service: Newsfeed service.
            users_service: Users service.

        Returns:
            Created guide.

        Raises:
            CustomHTTPException: On error.
        """
        try:
            guide, context = await maps_service.create_guide(code, data)

            # Grant XP if map is official
            map_data = context["map_data"]
            if map_data.official:
                xp_amount = XP_AMOUNTS["Guide"]
                await lootbox_service.grant_user_xp(
                    request.headers,
                    data.user_id,
                    XpGrantRequest(amount=xp_amount, type="Guide"),
                )

            # Get user name for newsfeed
            user = await users_service.get_user(user_id=data.user_id)
            user_name = (user.coalesced_name or "Unknown User") if user else "Unknown User"

            # Create and publish newsfeed event
            event_payload = NewsfeedGuide(
                code=code,
                guide_url=data.url,
                name=user_name,
            )
            event = NewsfeedEvent(
                id=None,
                timestamp=dt.datetime.now(dt.timezone.utc),
                payload=event_payload,
                event_type="guide",
            )
            await newsfeed_service.create_and_publish(event=event, headers=request.headers)

            return Response(guide, status_code=HTTP_201_CREATED)

        except MapNotFoundError as e:
            raise CustomHTTPException(
                detail=f"No map found with code: {code}",
                status_code=HTTP_404_NOT_FOUND,
            ) from e

        except DuplicateGuideError as e:
            raise CustomHTTPException(
                detail=f"User {data.user_id} already has a guide for map {code}",
                status_code=HTTP_400_BAD_REQUEST,
            ) from e

    @patch(
        "/{code:str}/guides/{user_id:int}",
        summary="Update Guide",
        opt={"required_scopes": {"maps:write"}},
    )
    async def update_guide_endpoint(
        self,
        code: OverwatchCode,
        user_id: int,
        url: GuideURL,
        maps_service: MapsService,
    ) -> GuideResponse:
        """Update a guide.

        Args:
            code: Map code.
            user_id: User ID who owns the guide.
            url: New URL.
            maps_service: Maps service.

        Returns:
            Updated guide.

        Raises:
            CustomHTTPException: On error.
        """
        try:
            return await maps_service.update_guide(code, user_id, url)

        except MapNotFoundError as e:
            raise CustomHTTPException(
                detail=f"No map found with code: {code}",
                status_code=HTTP_404_NOT_FOUND,
            ) from e

        except GuideNotFoundError as e:
            raise CustomHTTPException(
                detail=f"No guide found for map {code} by user {user_id}",
                status_code=HTTP_404_NOT_FOUND,
            ) from e

    @delete(
        "/{code:str}/guides/{user_id:int}",
        summary="Delete Guide",
        status_code=HTTP_204_NO_CONTENT,
        opt={"required_scopes": {"maps:write"}},
    )
    async def delete_guide_endpoint(
        self,
        code: OverwatchCode,
        user_id: int,
        maps_service: MapsService,
    ) -> Response[None]:
        """Delete a guide.

        Args:
            code: Map code.
            user_id: User ID who owns the guide.
            maps_service: Maps service.

        Returns:
            Empty response with 204 status.

        Raises:
            CustomHTTPException: On error.
        """
        try:
            await maps_service.delete_guide(code, user_id)
            return Response(None, status_code=HTTP_204_NO_CONTENT)

        except MapNotFoundError as e:
            raise CustomHTTPException(
                detail=f"No map found with code: {code}",
                status_code=HTTP_404_NOT_FOUND,
            ) from e

        except GuideNotFoundError as e:
            raise CustomHTTPException(
                detail=f"No guide found for map {code} by user {user_id}",
                status_code=HTTP_404_NOT_FOUND,
            ) from e

    @get(
        "/{code:str}/affected",
        summary="Get Affected Users",
        opt={"required_scopes": {"maps:read"}},
    )
    async def get_affected_users_endpoint(
        self,
        code: OverwatchCode,
        maps_service: MapsService,
    ) -> list[int]:
        """Get IDs of users affected by a map change.

        Args:
            code: Map code.
            maps_service: Maps service.

        Returns:
            List of affected user IDs.

        Raises:
            CustomHTTPException: If map not found.
        """
        try:
            return await maps_service.get_affected_users(code)

        except MapNotFoundError as e:
            raise CustomHTTPException(
                detail=f"No map found with code: {code}",
                status_code=HTTP_404_NOT_FOUND,
            ) from e

    @get(
        "/mastery",
        summary="Get Mastery Data",
        opt={"required_scopes": {"maps:read"}},
    )
    async def get_mastery_endpoint(
        self,
        maps_service: MapsService,
        user_id: int,
        map_name: OverwatchMap | None = None,
    ) -> list[MapMasteryResponse]:
        """Get mastery data for a user.

        Args:
            user_id: Target user ID.
            map_name: Optional map name filter.
            maps_service: Maps service.

        Returns:
            List of mastery records.
        """
        return await maps_service.get_map_mastery_data(user_id, map_name)

    @post(
        "/mastery",
        summary="Update Mastery",
        opt={"required_scopes": {"maps:write"}},
    )
    async def update_mastery_endpoint(
        self,
        data: Annotated[MapMasteryCreateRequest, Body(title="Mastery data")],
        maps_service: MapsService,
    ) -> MapMasteryCreateResponse | None:
        """Create or update mastery data.

        Args:
            data: Mastery payload.
            maps_service: Maps service.

        Returns:
            Result of the mastery operation.
        """
        return await maps_service.update_mastery(data)

    @post(
        "/{code:str}/legacy",
        summary="Convert to Legacy",
        opt={"required_scopes": {"maps:write"}},
    )
    async def convert_to_legacy_endpoint(
        self,
        code: OverwatchCode,
        request: Request,
        maps_service: MapsService,
        newsfeed_service: NewsfeedService,
        reason: str = "",
    ) -> Response[None]:
        """Convert map to legacy status.

        Args:
            code: Map code.
            request: Request object.
            maps_service: Maps service.
            newsfeed_service: Newsfeed service.
            reason: Reason for legacy conversion.

        Returns:
            Empty response with 204 status.

        Raises:
            CustomHTTPException: If map not found.
        """
        try:
            affected_count, _context = await maps_service.convert_to_legacy(code, reason)

            # Create and publish newsfeed event
            event_payload = NewsfeedLegacyRecord(
                code=code,
                affected_count=affected_count,
                reason=reason,
            )
            event = NewsfeedEvent(
                id=None,
                timestamp=dt.datetime.now(dt.timezone.utc),
                payload=event_payload,
                event_type="legacy_record",
            )
            await newsfeed_service.create_and_publish(event=event, headers=request.headers)

            return Response(None, status_code=HTTP_204_NO_CONTENT)

        except MapNotFoundError as e:
            raise CustomHTTPException(
                detail=f"No map found with code: {code}",
                status_code=HTTP_404_NOT_FOUND,
            ) from e

    @patch(
        "/archive",
        summary="Set Archive Status",
        opt={"required_scopes": {"maps:write"}},
    )
    async def set_archive_status_endpoint(
        self,
        data: Annotated[ArchivalStatusPatchRequest, Body(title="Archive request")],
        maps_service: MapsService,
        newsfeed_service: NewsfeedService,
        request: Request,
    ) -> None:
        """Set archive status for one or more maps.

        Args:
            data: Archive request.
            maps_service: Maps service.
            newsfeed_service: Newsfeed service.
            request: Request object.

        Raises:
            CustomHTTPException: If any map not found.
        """
        try:
            await maps_service.set_archive_status(data, request.headers, newsfeed_service)

        except MapNotFoundError as e:
            raise CustomHTTPException(
                detail=str(e),
                status_code=HTTP_404_NOT_FOUND,
            ) from e

    @post(
        "/{code:str}/quality",
        summary="Override Quality Votes",
        opt={"required_scopes": {"maps:admin"}},
    )
    async def override_quality_votes_endpoint(
        self,
        code: OverwatchCode,
        data: Annotated[QualityValueRequest, Body(title="Quality value")],
        maps_service: MapsService,
    ) -> None:
        """Override quality votes for a map (admin only).

        Args:
            code: Map code.
            data: Quality value to set.
            maps_service: Maps service.

        Raises:
            CustomHTTPException: If map not found.
        """
        try:
            await maps_service.override_quality_votes(code, data)

        except MapNotFoundError as e:
            raise CustomHTTPException(
                detail=f"No map found with code: {code}",
                status_code=HTTP_404_NOT_FOUND,
            ) from e

    @get(
        "/trending",
        summary="Get Trending Maps",
        opt={"required_scopes": {"maps:read"}},
    )
    async def get_trending_maps_endpoint(
        self,
        maps_service: MapsService,
        limit: Literal[1, 3, 5, 10, 15, 20, 25] = 10,
    ) -> list[TrendingMapResponse]:
        """Get trending maps by clicks/ratings.

        Args:
            maps_service: Maps service.
            limit: Maximum number of trending maps to return.

        Returns:
            List of trending maps.
        """
        return await maps_service.get_trending_maps(limit=limit)

    @post(
        "/{code:str}/playtest",
        summary="Send to Playtest",
        opt={"required_scopes": {"maps:write"}},
    )
    async def send_to_playtest_endpoint(
        self,
        code: OverwatchCode,
        data: Annotated[SendToPlaytestRequest, Body(title="Playtest request")],
        maps_service: MapsService,
        request: Request,
    ) -> JobStatusResponse:
        """Send a map back to playtest.

        Args:
            code: Map code.
            data: Playtest request.
            maps_service: Maps service.
            request: Request object.

        Returns:
            Job status response.

        Raises:
            CustomHTTPException: On error.
        """
        try:
            return await maps_service.send_to_playtest(code, data, request.headers)

        except MapNotFoundError as e:
            raise CustomHTTPException(
                detail=f"No map found with code: {code}",
                status_code=HTTP_404_NOT_FOUND,
            ) from e

        except AlreadyInPlaytestError as e:
            raise CustomHTTPException(
                detail=f"Map {code} is already in playtest",
                status_code=HTTP_400_BAD_REQUEST,
            ) from e

    @post(
        "/link-codes",
        summary="Link Map Codes",
        opt={"required_scopes": {"maps:write"}},
    )
    async def link_map_codes_endpoint(
        self,
        data: Annotated[LinkMapsCreateRequest, Body(title="Link request")],
        maps_service: MapsService,
        newsfeed_service: NewsfeedService,
        request: Request,
    ) -> JobStatusResponse | None:
        """Link official and unofficial map codes.

        If a map needs to be cloned, returns the job status for tracking.
        If both maps already exist, returns None.

        Args:
            data: Link request.
            maps_service: Maps service.
            newsfeed_service: Newsfeed service.
            request: Request object.

        Returns:
            Job status if a clone operation was performed, None otherwise.

        Raises:
            CustomHTTPException: On error.
        """
        try:
            return await maps_service.link_map_codes(data, request.headers, newsfeed_service)

        except MapNotFoundError as e:
            raise CustomHTTPException(
                detail=str(e),
                status_code=HTTP_404_NOT_FOUND,
            ) from e

        except LinkedMapError as e:
            raise CustomHTTPException(
                detail=str(e),
                status_code=HTTP_400_BAD_REQUEST,
            ) from e

    @delete(
        "/link-codes",
        summary="Unlink Map Codes",
        status_code=HTTP_204_NO_CONTENT,
        opt={"required_scopes": {"maps:write"}},
    )
    async def unlink_map_codes_endpoint(
        self,
        data: Annotated[UnlinkMapsCreateRequest, Body(title="Unlink request")],
        maps_service: MapsService,
        newsfeed_service: NewsfeedService,
        request: Request,
    ) -> Response[None]:
        """Unlink map codes.

        Args:
            data: Unlink request with official_code, unofficial_code, and reason.
            maps_service: Maps service.
            newsfeed_service: Newsfeed service.
            request: Request object.

        Returns:
            Empty response with 204 status.

        Raises:
            CustomHTTPException: If map not found.
        """
        try:
            await maps_service.unlink_map_codes(data, request.headers, newsfeed_service)
            return Response(None, status_code=HTTP_204_NO_CONTENT)

        except MapNotFoundError as e:
            raise CustomHTTPException(
                detail=str(e),
                status_code=HTTP_404_NOT_FOUND,
            ) from e
