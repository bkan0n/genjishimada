from typing import Literal

import msgspec
from msgspec import Struct

__all__ = (
    "OpAlias",
    "OpBase",
    "OpClaim",
    "OpCreate",
    "OpEdit",
    "OpIncrementUsage",
    "OpPurge",
    "OpRemove",
    "OpRemoveById",
    "OpTransfer",
    "TagOp",
    "TagRowDTO",
    "TagsAutocompleteRequest",
    "TagsAutocompleteResponse",
    "TagsMutateRequest",
    "TagsMutateResponse",
    "TagsMutateResult",
    "TagsSearchFilters",
    "TagsSearchResponse",
)


class TagsSearchFilters(Struct, omit_defaults=True):
    """Search filters for tag queries.

    Attributes:
        guild_id: Discord guild identifier that owns the tags.
        name: Raw tag name to search for.
        fuzzy: Whether to enable fuzzy matching.
        include_aliases: Whether to include aliases in results.
        only_aliases: Whether to return only alias rows.
        owner_id: Filter by tag owner.
        random: Whether to return a random tag.
        by_id: Lookup a specific tag by ID.
        include_content: Include content body in results.
        include_rank: Include ranking information in results.
        sort_by: Sorting column for the result set.
        sort_dir: Sorting direction for results.
        limit: Maximum number of rows to return.
        offset: Number of rows to skip for pagination.
    """

    guild_id: int
    # filters
    name: str | None = None  # raw name
    fuzzy: bool = False  # fuzzy (pg_trgm)
    include_aliases: bool = True
    only_aliases: bool = False
    owner_id: int | None = None
    # special modes
    random: bool = False  # random tag
    by_id: int | None = None  # lookup by tag_id
    # output controls
    include_content: bool = False  # return content
    include_rank: bool = False
    # sorting & paging
    sort_by: Literal["name", "uses", "created_at"] = "name"
    sort_dir: Literal["asc", "desc"] = "asc"
    limit: int = 20
    offset: int = 0


class TagRowDTO(Struct, omit_defaults=True):
    """Represents a tag row with optional metadata.

    Attributes:
        id: Unique tag identifier.
        guild_id: Discord guild that owns the tag.
        name: Tag name.
        owner_id: Identifier of the tag owner.
        is_alias: Whether the tag is an alias.
        canonical_name: Canonical tag name when this row is an alias.
        uses: Number of times the tag has been used.
        content: Tag content payload.
        rank: Optional ranking position for search results.
    """

    id: int
    guild_id: int
    name: str
    owner_id: int
    is_alias: bool = False
    canonical_name: str | None = None
    uses: int | None = None
    content: str | None = None
    rank: int | None = None


class TagsSearchResponse(Struct):
    """Response for tag search queries.

    Attributes:
        items: Matching tags.
        total: Optional total for pagination.
        suggestions: Optional fallback suggestions for fuzzy matches.
    """

    items: list[TagRowDTO]
    total: int | None = None  # optionally returned for paging UIs
    suggestions: list[str] | None = None  # for fuzzy fallbacks


class OpBase(Struct, tag_field="op"):
    """Discriminated union base; JSON will include an 'op' field with the tag."""

    @property
    def op(self) -> str:
        """Return the operation type."""
        ti = msgspec.inspect.type_info(type(self))
        return "" if ti.tag is None else ti.tag  # pyright: ignore[reportAttributeAccessIssue]


class OpCreate(OpBase, tag="create"):
    """Create a new tag.

    Attributes:
        guild_id: Discord guild identifier that owns the tag.
        name: Name of the tag to create.
        content: Content body of the tag.
        owner_id: Identifier of the user creating the tag.
    """

    guild_id: int
    name: str
    content: str
    owner_id: int


class OpAlias(OpBase, tag="alias"):
    """Create an alias for an existing tag.

    Attributes:
        guild_id: Discord guild identifier that owns the tag.
        new_name: Alias name to create.
        old_name: Existing tag to alias.
        owner_id: Identifier of the user creating the alias.
    """

    guild_id: int
    new_name: str
    old_name: str
    owner_id: int


class OpEdit(OpBase, tag="edit"):
    """Update the content of an existing tag.

    Attributes:
        guild_id: Discord guild identifier that owns the tag.
        name: Name of the tag to edit.
        new_content: Replacement content for the tag.
        owner_id: Identifier of the user editing the tag.
    """

    guild_id: int
    name: str
    new_content: str
    owner_id: int


class OpRemove(OpBase, tag="remove"):
    """Delete a tag by name.

    Attributes:
        guild_id: Discord guild identifier that owns the tag.
        name: Name of the tag to remove.
        requester_id: Identifier of the user requesting removal.
    """

    guild_id: int
    name: str
    requester_id: int


class OpRemoveById(OpBase, tag="remove_by_id"):
    """Delete a tag by its identifier.

    Attributes:
        guild_id: Discord guild identifier that owns the tag.
        tag_id: Identifier of the tag to remove.
        requester_id: Identifier of the user requesting removal.
    """

    guild_id: int
    tag_id: int
    requester_id: int


class OpClaim(OpBase, tag="claim"):
    """Claim ownership of an existing tag.

    Attributes:
        guild_id: Discord guild identifier that owns the tag.
        name: Name of the tag to claim.
        requester_id: Identifier of the user requesting ownership.
    """

    guild_id: int
    name: str
    requester_id: int


class OpTransfer(OpBase, tag="transfer"):
    """Transfer tag ownership to another user.

    Attributes:
        guild_id: Discord guild identifier that owns the tag.
        name: Name of the tag to transfer.
        new_owner_id: Identifier of the user receiving ownership.
        requester_id: Identifier of the user requesting the transfer.
    """

    guild_id: int
    name: str
    new_owner_id: int
    requester_id: int


class OpPurge(OpBase, tag="purge"):
    """Bulk-remove all tags belonging to an owner.

    Attributes:
        guild_id: Discord guild identifier that owns the tag collection.
        owner_id: Identifier of the owner whose tags are purged.
        requester_id: Identifier of the user requesting the purge.
    """

    guild_id: int
    owner_id: int
    requester_id: int


class OpIncrementUsage(OpBase, tag="increment_usage"):
    """Increment the usage count for a tag.

    Attributes:
        guild_id: Discord guild identifier that owns the tag.
        name: Name of the tag to increment.
    """

    guild_id: int
    name: str


TagOp = OpCreate | OpAlias | OpEdit | OpRemove | OpRemoveById | OpClaim | OpTransfer | OpPurge | OpIncrementUsage


class TagsMutateRequest(Struct):
    """Batch request to mutate tags.

    Attributes:
        ops: Ordered list of tag operations to perform.
    """

    ops: list[TagOp]


class TagsMutateResult(Struct, omit_defaults=True):
    """Result of a single tag mutation operation.

    Attributes:
        ok: Whether the operation succeeded.
        message: Optional human-readable message.
        affected: Number of rows affected by the operation.
        tag_id: Identifier of the tag affected, if applicable.
    """

    ok: bool
    message: str | None = None
    affected: int | None = None
    tag_id: int | None = None


class TagsMutateResponse(Struct):
    """Response containing results for each mutation operation.

    Attributes:
        results: Ordered list of operation results.
    """

    results: list[TagsMutateResult]


class TagsAutocompleteRequest(Struct):
    """Request payload for tag autocomplete queries.

    Attributes:
        guild_id: Discord guild identifier that owns the tags.
        q: User-entered query string.
        mode: Autocomplete mode controlling alias inclusion.
        owner_id: Filter results by owner.
        limit: Maximum number of suggestions to return.
    """

    guild_id: int
    q: str
    mode: Literal["aliased", "non_aliased", "owned_aliased", "owned_non_aliased"] = "aliased"
    owner_id: int | None = None
    limit: int = 12


class TagsAutocompleteResponse(Struct):
    """Autocomplete suggestions for a tag query.

    Attributes:
        items: Ordered list of suggested tag names.
    """

    items: list[str]
