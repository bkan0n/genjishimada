"""Tags API endpoints."""

from __future__ import annotations

from genjishimada_sdk.tags import (
    TagsAutocompleteRequest,
    TagsAutocompleteResponse,
    TagsMutateRequest,
    TagsMutateResponse,
    TagsSearchFilters,
    TagsSearchResponse,
)
from litestar import Controller, post
from litestar.di import Provide

from repository.tags_repository import provide_tags_repository
from services.tags_service import TagsService, provide_tags_service


class TagsController(Controller):
    """Tags search, mutate, and autocomplete endpoints."""

    tags = ["Tags"]
    path = "/tags"
    dependencies = {
        "tags_repo": Provide(provide_tags_repository),
        "tags_service": Provide(provide_tags_service),
    }

    @post(path="/search")
    async def search(self, tags_service: TagsService, data: TagsSearchFilters) -> TagsSearchResponse:
        """Search tags with filtering, sorting, and pagination."""
        return await tags_service.search_tags(data)

    @post(path="/mutate")
    async def mutate(self, tags_service: TagsService, data: TagsMutateRequest) -> TagsMutateResponse:
        """Process a batch of tag mutation operations."""
        return await tags_service.mutate_tags(data.ops)

    @post(path="/autocomplete")
    async def autocomplete(
        self,
        tags_service: TagsService,
        data: TagsAutocompleteRequest,
    ) -> TagsAutocompleteResponse:
        """Get tag name autocomplete suggestions."""
        return await tags_service.autocomplete_tags(data)
