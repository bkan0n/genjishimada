"""Service for playtest business logic."""

from __future__ import annotations

from typing import TYPE_CHECKING

import msgspec
from asyncpg import Pool
from genjishimada_sdk.difficulties import (
    DIFFICULTY_MIDPOINTS,
    DifficultyAll,
    convert_raw_difficulty_to_difficulty_all,
)
from genjishimada_sdk.internal import JobStatusResponse
from genjishimada_sdk.maps import (
    PlaytestApprovedEvent,
    PlaytestForceAcceptedEvent,
    PlaytestForceDeniedEvent,
    PlaytestPatchRequest,
    PlaytestResetEvent,
    PlaytestResponse,
    PlaytestThreadAssociateRequest,
    PlaytestVote,
    PlaytestVoteCastEvent,
    PlaytestVoteRemovedEvent,
    PlaytestVotesResponse,
    PlaytestVoteWithUser,
)
from litestar.datastructures import Headers, State

from repository.exceptions import CheckConstraintViolationError
from repository.playtest_repository import PlaytestRepository
from services.exceptions.playtest import (
    InvalidPatchError,
    PlaytestNotFoundError,
    PlaytestStateError,
    VoteConstraintError,
    VoteNotFoundError,
)

from .base import BaseService

if TYPE_CHECKING:
    pass


class PlaytestService(BaseService):
    """Service for playtest business logic."""

    def __init__(
        self,
        pool: Pool,
        state: State,
        playtest_repo: PlaytestRepository,
    ) -> None:
        """Initialize service."""
        super().__init__(pool, state)
        self._playtest_repo = playtest_repo

    async def get_playtest(self, thread_id: int) -> PlaytestResponse:
        """Fetch playtest metadata.

        Args:
            thread_id: Forum thread ID.

        Returns:
            Playtest response.

        Raises:
            PlaytestNotFoundError: If playtest doesn't exist.
        """
        row = await self._playtest_repo.fetch_playtest(thread_id)
        if row is None:
            raise PlaytestNotFoundError(thread_id)

        return msgspec.convert(row, PlaytestResponse, from_attributes=True)

    async def get_votes(self, thread_id: int) -> PlaytestVotesResponse:
        """Get all votes and average for a playtest.

        Args:
            thread_id: Forum thread ID.

        Returns:
            Votes response with player votes and average.
        """
        rows = await self._playtest_repo.fetch_playtest_votes(thread_id)
        player_votes = msgspec.convert(rows, list[PlaytestVoteWithUser] | None) or []
        values = [v.difficulty for v in player_votes]
        average = round(sum(values) / len(values), 2) if values else 0

        return PlaytestVotesResponse(player_votes, average)

    async def cast_vote(
        self,
        thread_id: int,
        user_id: int,
        data: PlaytestVote,
        headers: Headers,
    ) -> JobStatusResponse:
        """Cast or update a vote.

        Args:
            thread_id: Forum thread ID.
            user_id: Voter's user ID.
            data: Vote payload.
            headers: Request headers for RabbitMQ idempotency.

        Returns:
            Job status response.

        Raises:
            VoteConstraintError: If vote fails constraint (no submission).
        """
        try:
            await self._playtest_repo.cast_vote(
                thread_id,
                user_id,
                data.difficulty,
            )
        except CheckConstraintViolationError as e:
            raise VoteConstraintError(
                "Vote failed. You do not have a verified, non-completion submission associated with this map."
            ) from e

        # Publish vote event
        payload = PlaytestVoteCastEvent(
            thread_id=thread_id,
            voter_id=user_id,
            difficulty_value=data.difficulty,
        )
        return await self.publish_message(
            routing_key="api.playtest.vote.cast",
            data=payload,
            headers=headers,
        )

    async def delete_vote(
        self,
        thread_id: int,
        user_id: int,
        headers: Headers,
    ) -> JobStatusResponse:
        """Delete a user's vote.

        Args:
            thread_id: Forum thread ID.
            user_id: Voter's user ID.
            headers: Request headers for RabbitMQ idempotency.

        Returns:
            Job status response.

        Raises:
            VoteNotFoundError: If user has no vote.
        """
        # Check vote exists
        exists = await self._playtest_repo.check_vote_exists(thread_id, user_id)
        if not exists:
            raise VoteNotFoundError(thread_id, user_id)

        # Delete vote
        await self._playtest_repo.delete_vote(thread_id, user_id)

        # Publish removal event
        payload = PlaytestVoteRemovedEvent(thread_id=thread_id, voter_id=user_id)
        return await self.publish_message(
            routing_key="api.playtest.vote.remove",
            data=payload,
            headers=headers,
        )

    async def delete_all_votes(self, thread_id: int) -> None:
        """Delete all votes for a playtest (moderator action).

        Args:
            thread_id: Forum thread ID.
        """
        await self._playtest_repo.delete_all_votes(thread_id)

    async def edit_playtest_meta(
        self,
        thread_id: int,
        data: PlaytestPatchRequest,
    ) -> None:
        """Update playtest metadata.

        Args:
            thread_id: Forum thread ID.
            data: Patch request with UNSET fields ignored.

        Raises:
            InvalidPatchError: If all fields are UNSET.
        """
        # Filter out UNSET fields
        cleaned = {k: v for k, v in msgspec.structs.asdict(data).items() if v is not msgspec.UNSET}

        if not cleaned:
            raise InvalidPatchError("All fields cannot be UNSET.")

        await self._playtest_repo.update_playtest_meta(thread_id, cleaned)

    async def associate_playtest_meta(
        self,
        data: PlaytestThreadAssociateRequest,
    ) -> PlaytestResponse:
        """Associate playtest with Discord thread.

        Args:
            data: Association request.

        Returns:
            Updated playtest response.

        Raises:
            PlaytestNotFoundError: If association fails.
        """
        await self._playtest_repo.associate_thread(
            data.playtest_id,
            data.thread_id,
        )

        # Fetch and return updated playtest
        row = await self._playtest_repo.fetch_playtest(data.thread_id)
        if row is None:
            raise PlaytestNotFoundError(data.thread_id)

        return msgspec.convert(row, PlaytestResponse, from_attributes=True)

    async def approve(
        self,
        thread_id: int,
        verifier_id: int,
        headers: Headers,
    ) -> JobStatusResponse:
        """Approve a playtest (normal flow).

        Calculates average difficulty from votes, updates map to approved,
        marks playtest completed, and publishes approval event.

        Args:
            thread_id: Forum thread ID.
            verifier_id: Verifier's user ID.
            headers: Request headers for RabbitMQ idempotency.

        Returns:
            Job status response.

        Raises:
            PlaytestNotFoundError: If playtest doesn't exist.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            # Get map ID
            map_id = await self._playtest_repo.get_map_id_from_thread(
                thread_id,
                conn=conn,  # type: ignore[arg-type]
            )
            if map_id is None:
                raise PlaytestNotFoundError(thread_id)

            # Calculate average difficulty
            difficulty = await self._playtest_repo.get_average_difficulty(
                thread_id,
                conn=conn,  # type: ignore[arg-type]
            )
            if difficulty is None:
                raise PlaytestStateError("Cannot approve playtest with no votes.")

            # Approve playtest
            await self._playtest_repo.approve_playtest(
                map_id,
                thread_id,
                difficulty,
                conn=conn,  # type: ignore[arg-type]
            )

            # Get additional data for event
            primary_creator_id = await self._playtest_repo.get_primary_creator(
                map_id,
                conn=conn,  # type: ignore[arg-type]
            )
            code = await self._playtest_repo.get_map_code(
                map_id,
                conn=conn,  # type: ignore[arg-type]
            )

        if code is None:
            raise PlaytestStateError("Map code not found for playtest.")
        if primary_creator_id is None:
            raise PlaytestStateError("Primary creator not found for map.")

        # Publish approval event
        payload = PlaytestApprovedEvent(
            code=code,
            thread_id=thread_id,
            difficulty=convert_raw_difficulty_to_difficulty_all(difficulty),
            verifier_id=verifier_id,
            primary_creator_id=primary_creator_id,
        )
        idempotency_key = f"playtest:approve:{thread_id}"
        return await self.publish_message(
            routing_key="api.playtest.approve",
            data=payload,
            headers=headers,
            idempotency_key=idempotency_key,
        )

    async def force_accept(
        self,
        thread_id: int,
        difficulty: DifficultyAll,
        verifier_id: int,
        headers: Headers,
    ) -> JobStatusResponse:
        """Force accept playtest with custom difficulty.

        Args:
            thread_id: Forum thread ID.
            difficulty: Custom difficulty rating.
            verifier_id: Verifier's user ID.
            headers: Request headers for RabbitMQ idempotency.

        Returns:
            Job status response.

        Raises:
            PlaytestNotFoundError: If playtest doesn't exist.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            # Get map ID
            map_id = await self._playtest_repo.get_map_id_from_thread(
                thread_id,
                conn=conn,  # type: ignore[arg-type]
            )
            if map_id is None:
                raise PlaytestNotFoundError(thread_id)

            # Get raw difficulty from tier
            raw_difficulty = DIFFICULTY_MIDPOINTS[difficulty]

            # Force accept
            await self._playtest_repo.force_accept_playtest(
                map_id,
                thread_id,
                raw_difficulty,
                conn=conn,  # type: ignore[arg-type]
            )

        # Publish force accept event
        payload = PlaytestForceAcceptedEvent(
            thread_id=thread_id,
            difficulty=difficulty,
            verifier_id=verifier_id,
        )
        idempotency_key = f"playtest:force_accept:{thread_id}"
        return await self.publish_message(
            routing_key="api.playtest.force_accept",
            data=payload,
            headers=headers,
            idempotency_key=idempotency_key,
        )

    async def force_deny(
        self,
        thread_id: int,
        verifier_id: int,
        reason: str,
        headers: Headers,
    ) -> JobStatusResponse:
        """Force deny playtest with reason.

        Args:
            thread_id: Forum thread ID.
            verifier_id: Verifier's user ID.
            reason: Denial reason.
            headers: Request headers for RabbitMQ idempotency.

        Returns:
            Job status response.

        Raises:
            PlaytestNotFoundError: If playtest doesn't exist.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            # Get map ID
            map_id = await self._playtest_repo.get_map_id_from_thread(
                thread_id,
                conn=conn,  # type: ignore[arg-type]
            )
            if map_id is None:
                raise PlaytestNotFoundError(thread_id)

            # Force deny
            await self._playtest_repo.force_deny_playtest(
                map_id,
                thread_id,
                conn=conn,  # type: ignore[arg-type]
            )

        # Publish force deny event
        payload = PlaytestForceDeniedEvent(
            thread_id=thread_id,
            verifier_id=verifier_id,
            reason=reason,
        )
        idempotency_key = f"playtest:force_deny:{thread_id}"
        return await self.publish_message(
            routing_key="api.playtest.force_deny",
            data=payload,
            headers=headers,
            idempotency_key=idempotency_key,
        )

    async def reset(  # noqa: PLR0913
        self,
        thread_id: int,
        verifier_id: int,
        reason: str,
        remove_votes: bool,
        remove_completions: bool,
        headers: Headers,
    ) -> JobStatusResponse:
        """Reset playtest.

        Optionally removes votes and/or completions.

        Args:
            thread_id: Forum thread ID.
            verifier_id: Verifier's user ID.
            reason: Reset reason.
            remove_votes: Whether to delete votes.
            remove_completions: Whether to delete completions.
            headers: Request headers for RabbitMQ idempotency.

        Returns:
            Job status response.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            if remove_votes:
                await self._playtest_repo.delete_all_votes(
                    thread_id,
                    conn=conn,  # type: ignore[arg-type]
                )

            if remove_completions:
                await self._playtest_repo.delete_completions_for_playtest(
                    thread_id,
                    conn=conn,  # type: ignore[arg-type]
                )

        # Publish reset event
        payload = PlaytestResetEvent(
            thread_id=thread_id,
            verifier_id=verifier_id,
            reason=reason,
            remove_votes=remove_votes,
            remove_completions=remove_completions,
        )
        idempotency_key = f"playtest:reset:{thread_id}"
        return await self.publish_message(
            routing_key="api.playtest.reset",
            data=payload,
            headers=headers,
            idempotency_key=idempotency_key,
        )


async def provide_playtest_service(
    state: State,
    playtest_repo: PlaytestRepository,
) -> PlaytestService:
    """Litestar DI provider for service."""
    return PlaytestService(state.db_pool, state, playtest_repo)
