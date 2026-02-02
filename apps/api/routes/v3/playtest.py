"""V4 playtest routes."""

from __future__ import annotations

from typing import Annotated

from genjishimada_sdk.internal import JobStatusResponse
from genjishimada_sdk.maps import (
    PlaytestApproveRequest,
    PlaytestForceAcceptRequest,
    PlaytestForceDenyRequest,
    PlaytestPatchRequest,
    PlaytestResetRequest,
    PlaytestResponse,
    PlaytestThreadAssociateRequest,
    PlaytestVote,
    PlaytestVotesResponse,
)
from litestar import Controller, Request, delete, get, patch, post
from litestar.di import Provide
from litestar.params import Body
from litestar.response import Stream
from litestar.status_codes import (
    HTTP_202_ACCEPTED,
    HTTP_204_NO_CONTENT,
    HTTP_400_BAD_REQUEST,
    HTTP_404_NOT_FOUND,
)

from repository.maps_repository import provide_maps_repository
from repository.playtest_repository import provide_playtest_repository
from services.exceptions.playtest import (
    InvalidPatchError,
    PlaytestNotFoundError,
    PlaytestStateError,
    VoteConstraintError,
    VoteNotFoundError,
)
from services.maps_service import MapsService, provide_maps_service
from services.playtest_service import PlaytestService, provide_playtest_service
from utilities.errors import CustomHTTPException


class PlaytestController(Controller):
    """Controller for playtest endpoints."""

    tags = ["Playtest"]
    path = "/maps/playtests"
    dependencies = {
        "playtest_repo": Provide(provide_playtest_repository),
        "playtest_service": Provide(provide_playtest_service),
        "maps_service": Provide(provide_maps_service),
        "maps_repo": Provide(provide_maps_repository),
    }

    @get(
        "/{thread_id:int}",
        summary="Get Playtest Data",
        description="Retrieve the full playtest metadata and related details for a specific thread.",
    )
    async def get_playtest_endpoint(
        self,
        thread_id: int,
        playtest_service: PlaytestService,
    ) -> PlaytestResponse:
        """Get playtest metadata.

        Args:
            thread_id: Playtest thread ID.
            playtest_service: Playtest service.

        Returns:
            Playtest response.

        Raises:
            CustomHTTPException: If not found.
        """
        try:
            return await playtest_service.get_playtest(thread_id)

        except PlaytestNotFoundError as e:
            raise CustomHTTPException(
                detail=f"Playtest {thread_id} not found",
                status_code=HTTP_404_NOT_FOUND,
            ) from e

    @get(
        "/{thread_id:int}/plot",
        summary="Get Playtest Plot Image",
        description="Generate and stream the difficulty distribution plot image for a playtest.",
        include_in_schema=False,
    )
    async def get_playtest_plot_endpoint(
        self,
        thread_id: int,
        maps_service: MapsService,
    ) -> Stream:
        """Get playtest plot data.

        Args:
            thread_id: Playtest thread ID.
            maps_service: Maps service.

        Returns:
            Plot data object.
        """
        return await maps_service.get_playtest_plot(thread_id=thread_id)

    @post(
        "/{thread_id:int}/vote/{user_id:int}",
        summary="Cast Playtest Vote",
        description="Submit a vote for a specific playtest thread on behalf of a user.",
        status_code=HTTP_202_ACCEPTED,
    )
    async def cast_vote_endpoint(
        self,
        request: Request,
        thread_id: int,
        user_id: int,
        data: Annotated[PlaytestVote, Body(title="Vote")],
        playtest_service: PlaytestService,
    ) -> JobStatusResponse:
        """Cast or update vote.

        Args:
            request: Request object.
            thread_id: Playtest thread ID.
            user_id: Voter's user ID.
            data: Vote data.
            playtest_service: Playtest service.

        Returns:
            Job status response.

        Raises:
            CustomHTTPException: On errors.
        """
        try:
            return await playtest_service.cast_vote(
                thread_id,
                user_id,
                data,
                request.headers,
            )

        except VoteConstraintError as e:
            raise CustomHTTPException(
                detail=e.message,
                status_code=HTTP_400_BAD_REQUEST,
            ) from e

    @delete(
        "/{thread_id:int}/vote/{user_id:int}",
        summary="Delete Playtest Vote",
        description="Remove an individual user's vote for a specific playtest thread.",
        status_code=HTTP_202_ACCEPTED,
    )
    async def delete_vote_endpoint(
        self,
        request: Request,
        thread_id: int,
        user_id: int,
        playtest_service: PlaytestService,
    ) -> JobStatusResponse:
        """Delete user's vote.

        Args:
            request: Request object.
            thread_id: Playtest thread ID.
            user_id: Voter's user ID.
            playtest_service: Playtest service.

        Returns:
            Job status response.

        Raises:
            CustomHTTPException: If vote doesn't exist.
        """
        try:
            return await playtest_service.delete_vote(
                thread_id,
                user_id,
                request.headers,
            )

        except VoteNotFoundError as e:
            raise CustomHTTPException(
                detail="You do not have a vote to remove.",
                status_code=HTTP_400_BAD_REQUEST,
            ) from e

    @delete(
        "/{thread_id:int}/vote",
        summary="Delete All Playtest Votes",
        description="Remove all votes associated with a specific playtest thread.",
        status_code=HTTP_204_NO_CONTENT,
    )
    async def delete_all_votes_endpoint(
        self,
        thread_id: int,
        playtest_service: PlaytestService,
    ) -> None:
        """Delete all votes for playtest.

        Args:
            thread_id: Playtest thread ID.
            playtest_service: Playtest service.

        Returns:
            None.
        """
        await playtest_service.delete_all_votes(thread_id)

    @get(
        "/{thread_id:int}/votes",
        summary="Get Playtest Votes",
        description="Retrieve all votes currently associated with a specific playtest thread.",
    )
    async def get_votes_endpoint(
        self,
        thread_id: int,
        playtest_service: PlaytestService,
    ) -> PlaytestVotesResponse:
        """Get all votes for playtest.

        Args:
            thread_id: Playtest thread ID.
            playtest_service: Playtest service.

        Returns:
            Votes response.
        """
        return await playtest_service.get_votes(thread_id)

    @patch(
        "/{thread_id:int}",
        summary="Edit Playtest Metadata",
        description="Update playtest metadata such as verification ID or message references.",
        include_in_schema=False,
        status_code=HTTP_204_NO_CONTENT,
    )
    async def edit_playtest_meta_endpoint(
        self,
        thread_id: int,
        data: Annotated[PlaytestPatchRequest, Body(title="Patch data")],
        playtest_service: PlaytestService,
    ) -> None:
        """Update playtest metadata.

        Args:
            thread_id: Playtest thread ID.
            data: Patch data.
            playtest_service: Playtest service.

        Returns:
            None.

        Raises:
            CustomHTTPException: On validation errors.
        """
        try:
            await playtest_service.edit_playtest_meta(thread_id, data)

        except InvalidPatchError as e:
            raise CustomHTTPException(
                detail=e.message,
                status_code=HTTP_400_BAD_REQUEST,
            ) from e

    @patch(
        "/",
        summary="Associate Playtest Metadata With Map",
        description="Associate a playtest thread with PlaytestMeta for a map.",
        include_in_schema=False,
    )
    async def associate_playtest_meta_endpoint(
        self,
        data: Annotated[PlaytestThreadAssociateRequest, Body(title="Association data")],
        playtest_service: PlaytestService,
    ) -> PlaytestResponse:
        """Associate playtest with thread.

        Args:
            data: Association data.
            playtest_service: Playtest service.

        Returns:
            Updated playtest response.

        Raises:
            CustomHTTPException: If association fails.
        """
        try:
            return await playtest_service.associate_playtest_meta(data)

        except PlaytestNotFoundError as e:
            raise CustomHTTPException(
                detail="Association failed - playtest not found.",
                status_code=HTTP_404_NOT_FOUND,
            ) from e

    @post(
        "/{thread_id:int}/approve",
        summary="Approve Playtest",
        description="Approve a playtest, marking it as verified and setting its difficulty rating.",
        status_code=HTTP_202_ACCEPTED,
    )
    async def approve_playtest_endpoint(
        self,
        request: Request,
        thread_id: int,
        data: Annotated[PlaytestApproveRequest, Body(title="Approve data")],
        playtest_service: PlaytestService,
    ) -> JobStatusResponse:
        """Approve playtest (normal flow).

        Args:
            request: Request object.
            thread_id: Playtest thread ID.
            data: Approval data.
            playtest_service: Playtest service.

        Returns:
            Job status response.

        Raises:
            CustomHTTPException: On errors.
        """
        try:
            return await playtest_service.approve(
                thread_id,
                data.verifier_id,
                request.headers,
            )

        except PlaytestNotFoundError as e:
            raise CustomHTTPException(
                detail=f"Playtest {thread_id} not found",
                status_code=HTTP_404_NOT_FOUND,
            ) from e

        except PlaytestStateError as e:
            raise CustomHTTPException(
                detail=e.message,
                status_code=HTTP_400_BAD_REQUEST,
            ) from e

    @post(
        "/{thread_id:int}/force_accept",
        summary="Force Accept Playtest",
        description="Forcefully accept a playtest regardless of votes, assigning difficulty and verifier.",
        status_code=HTTP_202_ACCEPTED,
    )
    async def force_accept_playtest_endpoint(
        self,
        request: Request,
        thread_id: int,
        data: Annotated[PlaytestForceAcceptRequest, Body(title="Force accept data")],
        playtest_service: PlaytestService,
    ) -> JobStatusResponse:
        """Force accept playtest.

        Args:
            request: Request object.
            thread_id: Playtest thread ID.
            data: Force accept data.
            playtest_service: Playtest service.

        Returns:
            Job status response.

        Raises:
            CustomHTTPException: If playtest not found.
        """
        try:
            return await playtest_service.force_accept(
                thread_id,
                data.difficulty,
                data.verifier_id,
                request.headers,
            )

        except PlaytestNotFoundError as e:
            raise CustomHTTPException(
                detail=f"Playtest {thread_id} not found",
                status_code=HTTP_404_NOT_FOUND,
            ) from e

    @post(
        "/{thread_id:int}/force_deny",
        summary="Force Deny Playtest",
        description="Forcefully deny a playtest regardless of votes, recording the reason for rejection.",
        status_code=HTTP_202_ACCEPTED,
    )
    async def force_deny_playtest_endpoint(
        self,
        request: Request,
        thread_id: int,
        data: Annotated[PlaytestForceDenyRequest, Body(title="Force deny data")],
        playtest_service: PlaytestService,
    ) -> JobStatusResponse:
        """Force deny playtest.

        Args:
            request: Request object.
            thread_id: Playtest thread ID.
            data: Force deny data.
            playtest_service: Playtest service.

        Returns:
            Job status response.

        Raises:
            CustomHTTPException: If playtest not found.
        """
        try:
            return await playtest_service.force_deny(
                thread_id,
                data.verifier_id,
                data.reason,
                request.headers,
            )

        except PlaytestNotFoundError as e:
            raise CustomHTTPException(
                detail=f"Playtest {thread_id} not found",
                status_code=HTTP_404_NOT_FOUND,
            ) from e

    @post(
        "/{thread_id:int}/reset",
        summary="Reset Playtest",
        description="Reset a playtest to its initial state, optionally removing votes and completions.",
        status_code=HTTP_202_ACCEPTED,
    )
    async def reset_playtest_endpoint(
        self,
        request: Request,
        thread_id: int,
        data: Annotated[PlaytestResetRequest, Body(title="Reset data")],
        playtest_service: PlaytestService,
    ) -> JobStatusResponse:
        """Reset playtest.

        Args:
            request: Request object.
            thread_id: Playtest thread ID.
            data: Reset data.
            playtest_service: Playtest service.

        Returns:
            Job status response.
        """
        return await playtest_service.reset(
            thread_id,
            data.verifier_id,
            data.reason,
            data.remove_votes,
            data.remove_completions,
            request.headers,
        )
