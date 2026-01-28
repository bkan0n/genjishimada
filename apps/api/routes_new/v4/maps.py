"""V4 Maps routes."""

from __future__ import annotations

import logging
from typing import Annotated, Literal

from genjishimada_sdk.difficulties import DifficultyTop
from genjishimada_sdk.internal import JobStatusResponse
from genjishimada_sdk.maps import (
    ArchivalStatusPatchRequest,
    GuideFullResponse,
    GuideResponse,
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
from litestar import Controller, delete, get, patch, post
from litestar.connection import Request
from litestar.di import Provide
from litestar.params import Body, Parameter
from litestar.response import Response
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
from services.maps_service import MapsService, provide_maps_service
from services.newsfeed_service import NewsfeedService, provide_newsfeed_service
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
        playtesting: Annotated[PlaytestStatus | None, Parameter(description="Filter by playtest status")] = None,
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
                playtesting=playtesting,
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
    ) -> Response[MapCreationJobResponse]:
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
            result = await maps_service.create_map(data, request.headers, newsfeed_service)
            return Response(result, status_code=HTTP_201_CREATED)

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
    async def update_map_endpoint(
        self,
        code: OverwatchCode,
        data: Annotated[MapPatchRequest, Body(title="Map update request")],
        maps_service: MapsService,
    ) -> MapResponse:
        """Update a map.

        Args:
            code: Map code to update.
            data: Partial update request.
            maps_service: Maps service.

        Returns:
            Updated map response.

        Raises:
            CustomHTTPException: On validation or business rule errors.
        """
        try:
            return await maps_service.update_map(code, data)

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
        code: OverwatchCode,
        maps_service: MapsService,
    ) -> bool:
        """Check if a map code exists.

        Args:
            code: Map code.
            maps_service: Maps service.

        Returns:
            True if code exists, False otherwise.
        """
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
    ) -> object:
        """Get playtest plot data for a map.

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
    async def create_guide_endpoint(
        self,
        code: OverwatchCode,
        data: Annotated[GuideResponse, Body(title="Guide data")],
        maps_service: MapsService,
    ) -> Response[GuideResponse]:
        """Create a guide for a map.

        Args:
            code: Map code.
            data: Guide data with user_id and url.
            maps_service: Maps service.

        Returns:
            Created guide.

        Raises:
            CustomHTTPException: On error.
        """
        try:
            result = await maps_service.create_guide(code, data)
            return Response(result, status_code=HTTP_201_CREATED)

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
        url: str,
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
        "/{code:str}/mastery",
        summary="Get Mastery Data",
        opt={"required_scopes": {"maps:read"}},
    )
    async def get_mastery_endpoint(
        self,
        maps_service: MapsService,
        user_id: int,
        code: OverwatchCode | None = None,
    ) -> list[MapMasteryResponse]:
        """Get mastery data for a user.

        Args:
            user_id: Target user ID.
            code: Optional map code filter.
            maps_service: Maps service.

        Returns:
            List of mastery records.
        """
        return await maps_service.get_map_mastery_data(user_id, code)

    @post(
        "/{code:str}/mastery",
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
        maps_service: MapsService,
    ) -> int:
        """Convert map to legacy status.

        Args:
            code: Map code.
            maps_service: Maps service.

        Returns:
            Number of completions converted.

        Raises:
            CustomHTTPException: If map not found.
        """
        try:
            return await maps_service.convert_to_legacy(code)

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
    ) -> list[TrendingMapResponse]:
        """Get trending maps by clicks/ratings.

        Args:
            maps_service: Maps service.

        Returns:
            List of trending maps.
        """
        return await maps_service.get_trending_maps()

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
    ) -> None:
        """Link official and unofficial map codes.

        Args:
            data: Link request.
            maps_service: Maps service.
            newsfeed_service: Newsfeed service.
            request: Request object.

        Raises:
            CustomHTTPException: On error.
        """
        try:
            await maps_service.link_map_codes(data, request.headers, newsfeed_service)

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
