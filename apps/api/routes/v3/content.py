"""V3 Content routes for movement techniques."""

from __future__ import annotations

from typing import Literal

import msgspec
from litestar import Controller, delete, get, post, put
from litestar.di import Provide
from litestar.exceptions import HTTPException
from litestar.status_codes import (
    HTTP_201_CREATED,
    HTTP_204_NO_CONTENT,
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
    HTTP_409_CONFLICT,
)

from repository.content_repository import provide_content_repository
from repository.exceptions import ForeignKeyViolationError
from services.content_service import ContentService, provide_content_service
from services.exceptions.content import (
    CategoryNotFoundError,
    DifficultyNotFoundError,
    DuplicateNameError,
    TechniqueNotFoundError,
)

# ---------------------------------------------------------------------------
# Request structs
# ---------------------------------------------------------------------------


class CreateCategoryRequest(msgspec.Struct, frozen=True):
    """Request body for creating a movement technique category."""

    name: str


class UpdateCategoryRequest(msgspec.Struct, frozen=True):
    """Request body for updating a movement technique category."""

    name: str


class CreateDifficultyRequest(msgspec.Struct, frozen=True):
    """Request body for creating a movement technique difficulty level."""

    name: str


class UpdateDifficultyRequest(msgspec.Struct, frozen=True):
    """Request body for updating a movement technique difficulty level."""

    name: str


class ReorderRequest(msgspec.Struct, frozen=True):
    """Request body for reordering a category or difficulty."""

    direction: Literal["up", "down"]


class CreateTipInput(msgspec.Struct, frozen=True):
    """A single tip to create alongside a technique."""

    text: str
    sort_order: int


class CreateVideoInput(msgspec.Struct, frozen=True):
    """A single video resource to create alongside a technique."""

    url: str
    caption: str | None = None
    sort_order: int = 0


class CreateTechniqueRequest(msgspec.Struct, frozen=True):
    """Request body for creating a movement technique."""

    name: str
    description: str | None = None
    category_id: int | None = None
    difficulty_id: int | None = None
    tips: list[CreateTipInput] = []
    videos: list[CreateVideoInput] = []


class UpdateTechniqueRequest(msgspec.Struct):
    """Request body for partially updating a movement technique."""

    name: str | msgspec.UnsetType = msgspec.UNSET
    description: str | None | msgspec.UnsetType = msgspec.UNSET
    category_id: int | None | msgspec.UnsetType = msgspec.UNSET
    difficulty_id: int | None | msgspec.UnsetType = msgspec.UNSET
    tips: list[CreateTipInput] | msgspec.UnsetType = msgspec.UNSET
    videos: list[CreateVideoInput] | msgspec.UnsetType = msgspec.UNSET


# ---------------------------------------------------------------------------
# Response structs
# ---------------------------------------------------------------------------


class TipOut(msgspec.Struct, frozen=True):
    """A single tip for a movement technique."""

    id: int
    text: str
    sort_order: int


class VideoOut(msgspec.Struct, frozen=True):
    """A single video resource for a movement technique."""

    id: int
    url: str
    caption: str | None
    sort_order: int


class CategoryOut(msgspec.Struct, frozen=True):
    """A movement technique category."""

    id: int
    name: str
    sort_order: int


class DifficultyOut(msgspec.Struct, frozen=True):
    """A movement technique difficulty level."""

    id: int
    name: str
    sort_order: int


class TechniqueOut(msgspec.Struct, frozen=True):
    """A movement technique with nested tips and videos."""

    id: int
    name: str
    description: str | None
    display_order: int
    category_id: int | None
    category_name: str | None
    difficulty_id: int | None
    difficulty_name: str | None
    tips: list[TipOut]
    videos: list[VideoOut]


class CategoryListResponse(msgspec.Struct, frozen=True):
    """Response envelope for the categories list endpoint."""

    categories: list[CategoryOut]


class DifficultyListResponse(msgspec.Struct, frozen=True):
    """Response envelope for the difficulties list endpoint."""

    difficulties: list[DifficultyOut]


class TechniqueListResponse(msgspec.Struct, frozen=True):
    """Response envelope for the techniques list endpoint."""

    techniques: list[TechniqueOut]


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------


class MovementTechController(Controller):
    """Endpoints for browsing movement technique content."""

    path = "/content/movement-tech"
    tags = ["Content"]
    dependencies = {
        "content_repo": Provide(provide_content_repository),
        "content_service": Provide(provide_content_service),
    }

    # -----------------------------------------------------------------------
    # Public GET endpoints (S02 — unchanged)
    # -----------------------------------------------------------------------

    @get(
        path="/categories",
        summary="List Movement Technique Categories",
        description="Return all movement technique categories ordered by sort_order.",
        opt={"exclude_from_auth": True},
    )
    async def list_categories(self, content_service: ContentService) -> CategoryListResponse:
        """Return all movement technique categories.

        Args:
            content_service: Content service dependency.

        Returns:
            CategoryListResponse: Envelope containing the categories list.
        """
        rows = await content_service.list_categories()
        return CategoryListResponse(categories=msgspec.convert(rows, list[CategoryOut]))

    @get(
        path="/difficulties",
        summary="List Movement Technique Difficulties",
        description="Return all movement technique difficulty levels ordered by sort_order.",
        opt={"exclude_from_auth": True},
    )
    async def list_difficulties(self, content_service: ContentService) -> DifficultyListResponse:
        """Return all movement technique difficulty levels.

        Args:
            content_service: Content service dependency.

        Returns:
            DifficultyListResponse: Envelope containing the difficulties list.
        """
        rows = await content_service.list_difficulties()
        return DifficultyListResponse(difficulties=msgspec.convert(rows, list[DifficultyOut]))

    @get(
        path="/",
        summary="List Movement Techniques",
        description="Return all movement techniques with nested tips and videos.",
        opt={"exclude_from_auth": True},
    )
    async def list_techniques(self, content_service: ContentService) -> TechniqueListResponse:
        """Return all movement techniques with nested tips and videos.

        Args:
            content_service: Content service dependency.

        Returns:
            TechniqueListResponse: Envelope containing the techniques list.
        """
        rows = await content_service.list_techniques()
        return TechniqueListResponse(techniques=msgspec.convert(rows, list[TechniqueOut]))

    # -----------------------------------------------------------------------
    # Admin category endpoints
    # -----------------------------------------------------------------------

    @post(
        path="/categories",
        status_code=HTTP_201_CREATED,
        summary="Create Movement Technique Category",
        description="Create a new movement technique category.",
        opt={"required_scopes": {"content:admin"}},
    )
    async def create_category(
        self,
        data: CreateCategoryRequest,
        content_service: ContentService,
    ) -> CategoryOut:
        """Create a new movement technique category.

        Args:
            data: Request body with the new category name.
            content_service: Content service dependency.

        Returns:
            CategoryOut: The created category.

        Raises:
            HTTPException: 409 if a category with this name already exists.
        """
        try:
            row = await content_service.create_category(data.name)
        except DuplicateNameError as e:
            raise HTTPException(status_code=HTTP_409_CONFLICT, detail=str(e)) from e
        return msgspec.convert(row, CategoryOut)

    @put(
        path="/categories/{category_id:int}",
        summary="Update Movement Technique Category",
        description="Update the name of an existing movement technique category.",
        opt={"required_scopes": {"content:admin"}},
    )
    async def update_category(
        self,
        category_id: int,
        data: UpdateCategoryRequest,
        content_service: ContentService,
    ) -> CategoryOut:
        """Update an existing movement technique category.

        Args:
            category_id: Primary key of the category to update.
            data: Request body with the new name.
            content_service: Content service dependency.

        Returns:
            CategoryOut: The updated category.

        Raises:
            HTTPException: 404 if the category does not exist.
            HTTPException: 409 if a category with this name already exists.
        """
        try:
            row = await content_service.update_category(category_id, data.name)
        except CategoryNotFoundError as e:
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e)) from e
        except DuplicateNameError as e:
            raise HTTPException(status_code=HTTP_409_CONFLICT, detail=str(e)) from e
        return msgspec.convert(row, CategoryOut)

    @delete(
        path="/categories/{category_id:int}",
        status_code=HTTP_204_NO_CONTENT,
        summary="Delete Movement Technique Category",
        description="Delete a movement technique category.",
        opt={"required_scopes": {"content:admin"}},
    )
    async def delete_category(
        self,
        category_id: int,
        content_service: ContentService,
    ) -> None:
        """Delete a movement technique category.

        Args:
            category_id: Primary key of the category to delete.
            content_service: Content service dependency.

        Raises:
            HTTPException: 404 if the category does not exist.
        """
        try:
            await content_service.delete_category(category_id)
        except CategoryNotFoundError as e:
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e)) from e

    @post(
        path="/categories/{category_id:int}/reorder",
        summary="Reorder Movement Technique Category",
        description="Move a movement technique category one position up or down.",
        opt={"required_scopes": {"content:admin"}},
    )
    async def reorder_category(
        self,
        category_id: int,
        data: ReorderRequest,
        content_service: ContentService,
    ) -> CategoryListResponse:
        """Move a category one position up or down.

        Args:
            category_id: Primary key of the category to reorder.
            data: Request body with direction ('up' or 'down').
            content_service: Content service dependency.

        Returns:
            CategoryListResponse: Full ordered list after reordering.

        Raises:
            HTTPException: 404 if the category does not exist.
        """
        try:
            rows = await content_service.reorder_category(category_id, data.direction)
        except CategoryNotFoundError as e:
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e)) from e
        return CategoryListResponse(categories=msgspec.convert(rows, list[CategoryOut]))

    # -----------------------------------------------------------------------
    # Admin difficulty endpoints
    # -----------------------------------------------------------------------

    @post(
        path="/difficulties",
        status_code=HTTP_201_CREATED,
        summary="Create Movement Technique Difficulty",
        description="Create a new movement technique difficulty level.",
        opt={"required_scopes": {"content:admin"}},
    )
    async def create_difficulty(
        self,
        data: CreateDifficultyRequest,
        content_service: ContentService,
    ) -> DifficultyOut:
        """Create a new movement technique difficulty level.

        Args:
            data: Request body with the new difficulty name.
            content_service: Content service dependency.

        Returns:
            DifficultyOut: The created difficulty.

        Raises:
            HTTPException: 409 if a difficulty with this name already exists.
        """
        try:
            row = await content_service.create_difficulty(data.name)
        except DuplicateNameError as e:
            raise HTTPException(status_code=HTTP_409_CONFLICT, detail=str(e)) from e
        return msgspec.convert(row, DifficultyOut)

    @put(
        path="/difficulties/{difficulty_id:int}",
        summary="Update Movement Technique Difficulty",
        description="Update the name of an existing movement technique difficulty level.",
        opt={"required_scopes": {"content:admin"}},
    )
    async def update_difficulty(
        self,
        difficulty_id: int,
        data: UpdateDifficultyRequest,
        content_service: ContentService,
    ) -> DifficultyOut:
        """Update an existing movement technique difficulty level.

        Args:
            difficulty_id: Primary key of the difficulty to update.
            data: Request body with the new name.
            content_service: Content service dependency.

        Returns:
            DifficultyOut: The updated difficulty.

        Raises:
            HTTPException: 404 if the difficulty does not exist.
            HTTPException: 409 if a difficulty with this name already exists.
        """
        try:
            row = await content_service.update_difficulty(difficulty_id, data.name)
        except DifficultyNotFoundError as e:
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e)) from e
        except DuplicateNameError as e:
            raise HTTPException(status_code=HTTP_409_CONFLICT, detail=str(e)) from e
        return msgspec.convert(row, DifficultyOut)

    @delete(
        path="/difficulties/{difficulty_id:int}",
        status_code=HTTP_204_NO_CONTENT,
        summary="Delete Movement Technique Difficulty",
        description="Delete a movement technique difficulty level.",
        opt={"required_scopes": {"content:admin"}},
    )
    async def delete_difficulty(
        self,
        difficulty_id: int,
        content_service: ContentService,
    ) -> None:
        """Delete a movement technique difficulty level.

        Args:
            difficulty_id: Primary key of the difficulty to delete.
            content_service: Content service dependency.

        Raises:
            HTTPException: 404 if the difficulty does not exist.
        """
        try:
            await content_service.delete_difficulty(difficulty_id)
        except DifficultyNotFoundError as e:
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e)) from e

    @post(
        path="/difficulties/{difficulty_id:int}/reorder",
        summary="Reorder Movement Technique Difficulty",
        description="Move a movement technique difficulty level one position up or down.",
        opt={"required_scopes": {"content:admin"}},
    )
    async def reorder_difficulty(
        self,
        difficulty_id: int,
        data: ReorderRequest,
        content_service: ContentService,
    ) -> DifficultyListResponse:
        """Move a difficulty one position up or down.

        Args:
            difficulty_id: Primary key of the difficulty to reorder.
            data: Request body with direction ('up' or 'down').
            content_service: Content service dependency.

        Returns:
            DifficultyListResponse: Full ordered list after reordering.

        Raises:
            HTTPException: 404 if the difficulty does not exist.
        """
        try:
            rows = await content_service.reorder_difficulty(difficulty_id, data.direction)
        except DifficultyNotFoundError as e:
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e)) from e
        return DifficultyListResponse(difficulties=msgspec.convert(rows, list[DifficultyOut]))

    # -----------------------------------------------------------------------
    # Admin technique endpoints
    # -----------------------------------------------------------------------

    @post(
        path="/techniques",
        status_code=HTTP_201_CREATED,
        summary="Create Movement Technique",
        description="Create a new movement technique with optional tips and videos.",
        opt={"required_scopes": {"content:admin"}},
    )
    async def create_technique(
        self,
        data: CreateTechniqueRequest,
        content_service: ContentService,
    ) -> TechniqueOut:
        """Create a new movement technique.

        Args:
            data: Request body with name, description, category_id, difficulty_id, tips, videos.
            content_service: Content service dependency.

        Returns:
            TechniqueOut: The created technique with nested tips and videos.

        Raises:
            HTTPException: 400 if category_id or difficulty_id is invalid.
        """
        tips = [{"text": t.text, "sort_order": t.sort_order} for t in data.tips]
        videos = [{"url": v.url, "caption": v.caption, "sort_order": v.sort_order} for v in data.videos]
        try:
            row = await content_service.create_technique(
                data.name,
                data.description,
                data.category_id,
                data.difficulty_id,
                tips,
                videos,
            )
        except ForeignKeyViolationError as e:
            raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="Invalid category or difficulty ID") from e
        return msgspec.convert(row, TechniqueOut)

    @get(
        path="/techniques/{technique_id:int}",
        summary="Get Movement Technique",
        description="Fetch a single movement technique by ID.",
        opt={"required_scopes": {"content:admin"}},
    )
    async def get_technique(
        self,
        technique_id: int,
        content_service: ContentService,
    ) -> TechniqueOut:
        """Fetch a single movement technique by ID.

        Args:
            technique_id: Primary key of the technique to fetch.
            content_service: Content service dependency.

        Returns:
            TechniqueOut: The technique with nested tips and videos.

        Raises:
            HTTPException: 404 if the technique does not exist.
        """
        try:
            row = await content_service.fetch_technique(technique_id)
        except TechniqueNotFoundError as e:
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e)) from e
        return msgspec.convert(row, TechniqueOut)

    @put(
        path="/techniques/{technique_id:int}",
        summary="Update Movement Technique",
        description="Update a movement technique's fields. Only provided fields are changed.",
        opt={"required_scopes": {"content:admin"}},
    )
    async def update_technique(
        self,
        technique_id: int,
        data: UpdateTechniqueRequest,
        content_service: ContentService,
    ) -> TechniqueOut:
        """Update an existing movement technique.

        Args:
            technique_id: Primary key of the technique to update.
            data: Request body with fields to update (UNSET fields are left unchanged).
            content_service: Content service dependency.

        Returns:
            TechniqueOut: The updated technique with nested tips and videos.

        Raises:
            HTTPException: 404 if the technique does not exist.
            HTTPException: 400 if category_id or difficulty_id is invalid.
        """
        tips: list[dict] | msgspec.UnsetType
        videos: list[dict] | msgspec.UnsetType
        if isinstance(data.tips, msgspec.UnsetType):
            tips = msgspec.UNSET
        else:
            tips = [{"text": t.text, "sort_order": t.sort_order} for t in data.tips]
        if isinstance(data.videos, msgspec.UnsetType):
            videos = msgspec.UNSET
        else:
            videos = [{"url": v.url, "caption": v.caption, "sort_order": v.sort_order} for v in data.videos]
        try:
            row = await content_service.update_technique(
                technique_id,
                data.name,
                data.description,
                data.category_id,
                data.difficulty_id,
                tips,
                videos,
            )
        except TechniqueNotFoundError as e:
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e)) from e
        except ForeignKeyViolationError as e:
            raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail="Invalid category or difficulty ID") from e
        return msgspec.convert(row, TechniqueOut)

    @delete(
        path="/techniques/{technique_id:int}",
        status_code=HTTP_204_NO_CONTENT,
        summary="Delete Movement Technique",
        description="Delete a movement technique.",
        opt={"required_scopes": {"content:admin"}},
    )
    async def delete_technique(
        self,
        technique_id: int,
        content_service: ContentService,
    ) -> None:
        """Delete a movement technique.

        Args:
            technique_id: Primary key of the technique to delete.
            content_service: Content service dependency.

        Raises:
            HTTPException: 404 if the technique does not exist.
        """
        try:
            await content_service.delete_technique(technique_id)
        except TechniqueNotFoundError as e:
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e)) from e

    @post(
        path="/techniques/{technique_id:int}/reorder",
        summary="Reorder Movement Technique",
        description="Move a movement technique one position up or down.",
        opt={"required_scopes": {"content:admin"}},
    )
    async def reorder_technique(
        self,
        technique_id: int,
        data: ReorderRequest,
        content_service: ContentService,
    ) -> TechniqueListResponse:
        """Move a technique one position up or down.

        Args:
            technique_id: Primary key of the technique to reorder.
            data: Request body with direction ('up' or 'down').
            content_service: Content service dependency.

        Returns:
            TechniqueListResponse: Full ordered list after reordering.

        Raises:
            HTTPException: 404 if the technique does not exist.
        """
        try:
            rows = await content_service.reorder_technique(technique_id, data.direction)
        except TechniqueNotFoundError as e:
            raise HTTPException(status_code=HTTP_404_NOT_FOUND, detail=str(e)) from e
        return TechniqueListResponse(techniques=msgspec.convert(rows, list[TechniqueOut]))
