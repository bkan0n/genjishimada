"""Tags service for business logic and mutate dispatch."""

from __future__ import annotations

from logging import getLogger

from asyncpg import Pool
from genjishimada_sdk.tags import (
    OpAlias,
    OpClaim,
    OpCreate,
    OpEdit,
    OpIncrementUsage,
    OpPurge,
    OpRemove,
    OpRemoveById,
    OpTransfer,
    TagOp,
    TagsAutocompleteRequest,
    TagsAutocompleteResponse,
    TagsMutateResponse,
    TagsMutateResult,
    TagsSearchFilters,
    TagsSearchResponse,
)
from litestar.datastructures import State

from repository.tags_repository import TagsRepository
from services.base import BaseService

log = getLogger(__name__)


class TagsService(BaseService):
    """Business logic for tag operations."""

    def __init__(self, pool: Pool, state: State, tags_repo: TagsRepository) -> None:
        super().__init__(pool, state)
        self._tags_repo = tags_repo

    async def search_tags(self, filters: TagsSearchFilters) -> TagsSearchResponse:
        """Search tags with dynamic filters.

        Args:
            filters: Search filter parameters.

        Returns:
            TagsSearchResponse with matching items and optional suggestions.
        """
        return await self._tags_repo.search_tags(filters)

    async def mutate_tags(self, ops: list[TagOp]) -> TagsMutateResponse:
        """Execute a batch of tag mutation operations.

        Each operation is dispatched independently; a failure in one does not
        block subsequent operations.

        Args:
            ops: Ordered list of tag operations to perform.

        Returns:
            TagsMutateResponse with a result for each operation.
        """
        results: list[TagsMutateResult] = []
        for op in ops:
            result = await self._execute_op(op)
            results.append(result)
        return TagsMutateResponse(results=results)

    async def autocomplete_tags(self, filters: TagsAutocompleteRequest) -> TagsAutocompleteResponse:
        """Provide tag name suggestions for autocomplete.

        Args:
            filters: Autocomplete request parameters.

        Returns:
            TagsAutocompleteResponse with matching tag names.
        """
        return await self._tags_repo.autocomplete_tags(filters)

    async def _execute_op(self, op: TagOp) -> TagsMutateResult:  # noqa: PLR0911, PLR0912
        """Dispatch a single tag operation to the appropriate repository method.

        Args:
            op: The tag operation to execute.

        Returns:
            TagsMutateResult indicating success or failure.
        """
        try:
            match op.op:
                case "create":
                    assert isinstance(op, OpCreate)
                    tag_id = await self._tags_repo.create_tag(
                        op.guild_id,
                        op.name,
                        op.content,
                        op.owner_id,
                    )
                    return TagsMutateResult(ok=True, tag_id=tag_id, message="Tag created")

                case "alias":
                    assert isinstance(op, OpAlias)
                    affected = await self._tags_repo.create_alias(
                        op.guild_id,
                        op.new_name,
                        op.old_name,
                        op.owner_id,
                    )
                    return TagsMutateResult(ok=True, affected=affected, message="Alias created")

                case "edit":
                    assert isinstance(op, OpEdit)
                    affected = await self._tags_repo.edit_tag(
                        op.guild_id,
                        op.name,
                        op.new_content,
                        op.owner_id,
                    )
                    return TagsMutateResult(ok=True, affected=affected, message="Tag edited")

                case "remove":
                    assert isinstance(op, OpRemove)
                    found = await self._tags_repo.remove_tag_by_name(op.guild_id, op.name)
                    if not found:
                        return TagsMutateResult(ok=False, message="Tag not found")
                    return TagsMutateResult(ok=True, message="Tag deleted")

                case "remove_by_id":
                    assert isinstance(op, OpRemoveById)
                    affected = await self._tags_repo.remove_tag_by_id(op.guild_id, op.tag_id)
                    return TagsMutateResult(ok=True, affected=affected, message="Tag deleted")

                case "increment_usage":
                    assert isinstance(op, OpIncrementUsage)
                    await self._tags_repo.increment_usage(op.guild_id, op.name)
                    return TagsMutateResult(ok=True, message="Usage incremented")

                case "transfer":
                    assert isinstance(op, OpTransfer)
                    found = await self._tags_repo.transfer_tag(
                        op.guild_id,
                        op.name,
                        op.new_owner_id,
                        op.requester_id,
                    )
                    if not found:
                        return TagsMutateResult(ok=False, message="No permission or tag not found")
                    return TagsMutateResult(ok=True, message="Ownership transferred")

                case "purge":
                    assert isinstance(op, OpPurge)
                    affected = await self._tags_repo.purge_tags(op.guild_id, op.owner_id)
                    return TagsMutateResult(ok=True, affected=affected, message="User purged")

                case "claim":
                    assert isinstance(op, OpClaim)
                    found = await self._tags_repo.claim_tag(
                        op.guild_id,
                        op.name,
                        op.requester_id,
                    )
                    if not found:
                        return TagsMutateResult(ok=False, message="Tag not found")
                    return TagsMutateResult(ok=True, message="Tag claimed")

                case _:
                    return TagsMutateResult(ok=False, message=f"Unknown op {op.op}")

        except Exception as e:
            log.exception("Tag operation %s failed", op.op)
            return TagsMutateResult(ok=False, message=str(e))


async def provide_tags_service(
    state: State,
    tags_repo: TagsRepository,
) -> TagsService:
    """Litestar DI provider for TagsService.

    Args:
        state: Litestar application state with db_pool.
        tags_repo: Tags repository instance.

    Returns:
        A new TagsService instance.
    """
    return TagsService(state.db_pool, state, tags_repo)
