"""Newsfeed v4 controller."""

from __future__ import annotations

from typing import Annotated, Literal

import litestar
from genjishimada_sdk.newsfeed import NewsfeedEvent, NewsfeedEventType, PublishNewsfeedJobResponse
from litestar.datastructures import State
from litestar.di import Provide
from litestar.params import Parameter
from litestar.status_codes import HTTP_201_CREATED

from repository.newsfeed_repository import NewsfeedRepository
from services.newsfeed_service import NewsfeedService


async def provide_newsfeed_repository(state: State) -> NewsfeedRepository:
    """Provide newsfeed repository.

    Args:
        state: Application state.

    Returns:
        NewsfeedRepository instance.
    """
    return NewsfeedRepository(pool=state.db_pool)


async def provide_newsfeed_service(state: State, newsfeed_repo: NewsfeedRepository) -> NewsfeedService:
    """Provide newsfeed service.

    Args:
        state: Application state.
        newsfeed_repo: Newsfeed repository instance.

    Returns:
        NewsfeedService instance.
    """
    return NewsfeedService(pool=state.db_pool, state=state, newsfeed_repo=newsfeed_repo)


class NewsfeedController(litestar.Controller):
    """Newsfeed v4 controller."""

    tags = ["Newsfeed"]
    path = "/newsfeed"
    dependencies = {
        "newsfeed_repo": Provide(provide_newsfeed_repository),
        "newsfeed_service": Provide(provide_newsfeed_service),
    }

    @litestar.post(
        path="/",
        summary="Create Newsfeed Event",
        description=(
            "Insert a newsfeed event and immediately publish its ID to RabbitMQ. "
            "The request body must be a valid NewsfeedEvent; the response is the numeric ID of the newly created row."
        ),
        status_code=HTTP_201_CREATED,
    )
    async def create_newsfeed_event(
        self,
        request: litestar.Request,
        newsfeed_service: NewsfeedService,
        data: NewsfeedEvent,
    ) -> PublishNewsfeedJobResponse:
        """Create a newsfeed event and publish its ID.

        Args:
            request: Request object.
            newsfeed_service: Injected service instance.
            data: Event payload to persist and publish.

        Returns:
            PublishNewsfeedJobResponse with job status and event ID.
        """
        return await newsfeed_service.create_and_publish(event=data, headers=request.headers)

    @litestar.get(
        path="/",
        summary="List Newsfeed Events",
        description=(
            "Return a paginated list of newsfeed events ordered by most recent first. "
            'Supports an optional type filter via the "type" query parameter and fixed page sizes (10, 20, 25, 50).'
        ),
    )
    async def get_newsfeed_events(
        self,
        newsfeed_service: NewsfeedService,
        page_size: int = 10,
        page_number: int = 1,
        event_type: Annotated[NewsfeedEventType | None, Parameter(query="type")] = None,
    ) -> list[NewsfeedEvent] | None:
        """List newsfeed events with pagination and optional type filter.

        Args:
            newsfeed_service: Injected service instance.
            page_size: Number of rows per page.
            page_number: 1-based page number (default 1).
            event_type: Optional event type filter.

        Returns:
            Events ordered by recency, or None if no events exist.
        """
        return await newsfeed_service.list_events(limit=page_size, page_number=page_number, type_=event_type)

    @litestar.get(
        path="/{newsfeed_id:int}",
        summary="Get Newsfeed Event",
        description="Fetch a single newsfeed event by its ID. Returns the event payload and metadata if present.",
        include_in_schema=False,
    )
    async def get_newsfeed_event(
        self,
        newsfeed_service: NewsfeedService,
        newsfeed_id: int,
    ) -> NewsfeedEvent | None:
        """Fetch a single newsfeed event by ID.

        Args:
            newsfeed_service: Injected service instance.
            newsfeed_id: The event ID.

        Returns:
            The resolved event or None if not found.
        """
        return await newsfeed_service.get_event(newsfeed_id)
