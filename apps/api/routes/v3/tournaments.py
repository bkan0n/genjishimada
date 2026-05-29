"""Tournaments v3 controller."""

from __future__ import annotations

from typing import Annotated

import litestar
from genjishimada_sdk.tournaments import (
    TournamentCategoryCreateRequest,
    TournamentCategoryPatchRequest,
    TournamentCategoryResponse,
    TournamentConfigPatchRequest,
    TournamentConfigResponse,
)
from litestar.di import Provide
from litestar.params import Body, Parameter
from litestar.response import Response
from litestar.status_codes import (
    HTTP_200_OK,
    HTTP_201_CREATED,
    HTTP_204_NO_CONTENT,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
)

from repository.tournaments_repository import provide_tournament_repository
from services.exceptions.tournaments import (
    CategoryLockedError,
    CategoryNameExistsError,
    CategoryNotFoundError,
)
from services.tournament_service import TournamentService, provide_tournament_service
from utilities.errors import CustomHTTPException


class TournamentsController(litestar.Controller):
    """Tournaments v3 controller."""

    tags = ["Tournaments"]
    path = "/tournaments"
    dependencies = {
        "tournament_repo": Provide(provide_tournament_repository),
        "tournament_service": Provide(provide_tournament_service),
    }

    @litestar.get(
        path="/config",
        summary="Get Tournament Config",
        description="Get global tournament configuration.",
        opt={"required_scopes": {"tournaments:read"}},
    )
    async def get_config(
        self,
        tournament_service: TournamentService,
    ) -> TournamentConfigResponse:
        """Get tournament config.

        Args:
            tournament_service: Tournament service.

        Returns:
            Tournament configuration.
        """
        return await tournament_service.get_config()

    @litestar.patch(
        path="/config",
        summary="Update Tournament Config",
        description="Update global tournament configuration fields.",
        status_code=HTTP_200_OK,
        opt={"required_scopes": {"tournaments:write"}},
    )
    async def update_config(
        self,
        tournament_service: TournamentService,
        data: Annotated[TournamentConfigPatchRequest, Body(title="Config Update")],
    ) -> TournamentConfigResponse:
        """Update tournament config.

        Args:
            tournament_service: Tournament service.
            data: Config update request.

        Returns:
            Updated tournament configuration.
        """
        return await tournament_service.update_config(data)

    @litestar.post(
        path="/categories",
        summary="Create Tournament Category",
        description="Create a new tournament category with difficulty groupings.",
        status_code=HTTP_201_CREATED,
        opt={"required_scopes": {"tournaments:write"}},
    )
    async def create_category(
        self,
        tournament_service: TournamentService,
        data: Annotated[TournamentCategoryCreateRequest, Body(title="Category")],
    ) -> TournamentCategoryResponse:
        """Create a tournament category.

        Args:
            tournament_service: Tournament service.
            data: Category creation request.

        Returns:
            Created tournament category.

        Raises:
            CustomHTTPException: 409 if category name already exists.
        """
        try:
            return await tournament_service.create_category(data)
        except CategoryNameExistsError as e:
            raise CustomHTTPException(
                status_code=HTTP_409_CONFLICT,
                detail=str(e),
            ) from e

    @litestar.get(
        path="/categories",
        summary="List Tournament Categories",
        description="List all tournament categories.",
        opt={"required_scopes": {"tournaments:read"}},
    )
    async def list_categories(
        self,
        tournament_service: TournamentService,
    ) -> list[TournamentCategoryResponse]:
        """List all tournament categories.

        Args:
            tournament_service: Tournament service.

        Returns:
            List of tournament categories.
        """
        return await tournament_service.list_categories()

    @litestar.get(
        path="/categories/{category_id:int}",
        summary="Get Tournament Category",
        description="Get a single tournament category by ID.",
        opt={"required_scopes": {"tournaments:read"}},
    )
    async def get_category(
        self,
        tournament_service: TournamentService,
        category_id: Annotated[int, Parameter(description="Category ID")],
    ) -> TournamentCategoryResponse:
        """Get a single tournament category.

        Args:
            tournament_service: Tournament service.
            category_id: Category ID.

        Returns:
            Tournament category.

        Raises:
            CustomHTTPException: 404 if category not found.
        """
        try:
            return await tournament_service.get_category(category_id)
        except CategoryNotFoundError as e:
            raise CustomHTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=str(e),
            ) from e

    @litestar.patch(
        path="/categories/{category_id:int}",
        summary="Update Tournament Category",
        description="Update a tournament category's fields.",
        status_code=HTTP_200_OK,
        opt={"required_scopes": {"tournaments:write"}},
    )
    async def update_category(
        self,
        tournament_service: TournamentService,
        category_id: Annotated[int, Parameter(description="Category ID")],
        data: Annotated[TournamentCategoryPatchRequest, Body(title="Category Update")],
    ) -> TournamentCategoryResponse:
        """Update a tournament category.

        Args:
            tournament_service: Tournament service.
            category_id: Category ID.
            data: Category update request.

        Returns:
            Updated tournament category.

        Raises:
            CustomHTTPException: 404 if category not found, 409 if locked or name conflict.
        """
        try:
            return await tournament_service.update_category(category_id, data)
        except CategoryNotFoundError as e:
            raise CustomHTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=str(e),
            ) from e
        except (CategoryLockedError, CategoryNameExistsError) as e:
            raise CustomHTTPException(
                status_code=HTTP_409_CONFLICT,
                detail=str(e),
            ) from e

    @litestar.delete(
        path="/categories/{category_id:int}",
        summary="Delete Tournament Category",
        description="Delete a tournament category.",
        status_code=HTTP_204_NO_CONTENT,
        opt={"required_scopes": {"tournaments:write"}},
    )
    async def delete_category(
        self,
        tournament_service: TournamentService,
        category_id: Annotated[int, Parameter(description="Category ID")],
    ) -> Response[None]:
        """Delete a tournament category.

        Args:
            tournament_service: Tournament service.
            category_id: Category ID.

        Returns:
            Empty response with 204 status.

        Raises:
            CustomHTTPException: 404 if category not found, 409 if locked.
        """
        try:
            await tournament_service.delete_category(category_id)
            return Response(None, status_code=HTTP_204_NO_CONTENT)
        except CategoryNotFoundError as e:
            raise CustomHTTPException(
                status_code=HTTP_404_NOT_FOUND,
                detail=str(e),
            ) from e
        except CategoryLockedError as e:
            raise CustomHTTPException(
                status_code=HTTP_409_CONFLICT,
                detail=str(e),
            ) from e
