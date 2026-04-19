"""Tags repository for tag data access."""

from __future__ import annotations

from logging import getLogger
from typing import TYPE_CHECKING

from genjishimada_sdk.tags import (
    TagRowDTO,
    TagsAutocompleteRequest,
    TagsAutocompleteResponse,
    TagsSearchFilters,
    TagsSearchResponse,
)
from litestar.datastructures import State

from .base import BaseRepository

if TYPE_CHECKING:
    from asyncpg import Connection

log = getLogger(__name__)


class TagsRepository(BaseRepository):
    """Repository for tag CRUD and search operations."""

    async def search_tags(
        self,
        filters: TagsSearchFilters,
        *,
        conn: Connection | None = None,
    ) -> TagsSearchResponse:
        """Search tags with dynamic filters, sorting, and pagination.

        Builds a SQL query dynamically based on the provided filters. When an exact
        name search yields no results, falls back to fuzzy suggestions.

        Args:
            filters: Search filter parameters.
            conn: Optional connection for transaction participation.

        Returns:
            TagsSearchResponse with matching items and optional suggestions.
        """
        _conn = self._get_connection(conn)

        # Build select columns
        select_cols = [
            "tl.id",
            "tl.location_id AS guild_id",
            "tl.name",
            "tl.owner_id",
            "(tl.tag_id != t.id) AS is_alias",
            "t.name AS canonical_name",
            "t.uses",
        ]
        if filters.include_content:
            select_cols.append("t.content")
        if filters.include_rank:
            select_cols.append("ROW_NUMBER() OVER () AS rank")

        # Build WHERE clauses
        where_clauses: list[str] = []
        params: list[object] = []
        param_idx = 1

        # Always filter by guild_id (location_id)
        where_clauses.append(f"tl.location_id = ${param_idx}")
        params.append(filters.guild_id)
        param_idx += 1

        # Filter by ID
        if filters.by_id is not None:
            where_clauses.append(f"t.id = ${param_idx}")
            params.append(filters.by_id)
            param_idx += 1

        # Filter by name (exact or fuzzy)
        if filters.name is not None:
            if filters.fuzzy:
                where_clauses.append(f"tl.name % ${param_idx}")
                params.append(filters.name)
                param_idx += 1
            else:
                where_clauses.append(f"lower(tl.name) = lower(${param_idx})")
                params.append(filters.name)
                param_idx += 1

        # Filter by owner
        if filters.owner_id is not None:
            where_clauses.append(f"tl.owner_id = ${param_idx}")
            params.append(filters.owner_id)
            param_idx += 1

        # Alias filtering
        if filters.only_aliases:
            where_clauses.append("tl.tag_id != t.id")
        elif not filters.include_aliases:
            where_clauses.append("tl.tag_id = t.id")

        # Build ORDER BY
        if filters.random:
            order_by = "RANDOM()"
        else:
            sort_col_map = {
                "name": "tl.name",
                "uses": "t.uses",
                "created_at": "tl.created_at",
            }
            sort_col = sort_col_map.get(filters.sort_by, "tl.name")
            order_by = f"{sort_col} {filters.sort_dir.upper()}"

        # Build the query
        select_str = ", ".join(select_cols)
        where_str = " AND ".join(where_clauses)
        query_parts = [
            f"SELECT {select_str}",
            "FROM public.tag_lookup tl",
            "INNER JOIN public.tags t ON tl.tag_id = t.id",
            f"WHERE {where_str}",
            f"ORDER BY {order_by}",
            f"LIMIT ${param_idx}",
        ]
        params.append(filters.limit)
        param_idx += 1

        query_parts.append(f"OFFSET ${param_idx}")
        params.append(filters.offset)
        param_idx += 1

        query = "\n".join(query_parts)
        rows = await _conn.fetch(query, *params)

        items = [
            TagRowDTO(
                id=row["id"],
                guild_id=row["guild_id"],
                name=row["name"],
                owner_id=row["owner_id"],
                is_alias=row["is_alias"],
                canonical_name=row["canonical_name"],
                uses=row["uses"],
                content=row.get("content") if filters.include_content else None,
                rank=row.get("rank") if filters.include_rank else None,
            )
            for row in rows
        ]

        # If exact name search returned nothing, provide fuzzy suggestions
        suggestions: list[str] | None = None
        if not items and filters.name and not filters.fuzzy:
            suggestions = await self._suggest_tags(filters.guild_id, filters.name, conn=conn)

        return TagsSearchResponse(items=items, total=len(items), suggestions=suggestions)

    async def _suggest_tags(
        self,
        guild_id: int,
        name: str,
        *,
        conn: Connection | None = None,
    ) -> list[str]:
        """Provide fuzzy tag name suggestions using trigram similarity.

        Args:
            guild_id: Discord guild identifier.
            name: Name to find similar tags for.
            conn: Optional connection for transaction participation.

        Returns:
            List of suggested tag names.
        """
        _conn = self._get_connection(conn)
        rows = await _conn.fetch(
            """
            SELECT tl.name
            FROM public.tag_lookup tl
            WHERE tl.location_id = $1
              AND tl.name % $2
            ORDER BY similarity(tl.name, $2) DESC
            LIMIT 5
            """,
            guild_id,
            name,
        )
        return [row["name"] for row in rows]

    async def create_tag(
        self,
        guild_id: int,
        name: str,
        content: str,
        owner_id: int,
        *,
        conn: Connection | None = None,
    ) -> int:
        """Create a new tag with a corresponding lookup entry.

        Uses a CTE to insert into both tags and tag_lookup atomically.

        Args:
            guild_id: Discord guild identifier.
            name: Tag name.
            content: Tag content body.
            owner_id: User creating the tag.
            conn: Optional connection for transaction participation.

        Returns:
            The ID of the newly created tag.
        """
        _conn = self._get_connection(conn)
        tag_id: int = await _conn.fetchval(
            """
            WITH new_tag AS (
                INSERT INTO public.tags (name, content, owner_id, location_id)
                VALUES ($1, $2, $3, $4)
                RETURNING id
            )
            INSERT INTO public.tag_lookup (name, owner_id, location_id, tag_id)
            SELECT $1, $3, $4, id FROM new_tag
            RETURNING tag_id
            """,
            name,
            content,
            owner_id,
            guild_id,
        )
        return tag_id

    async def create_alias(
        self,
        guild_id: int,
        new_name: str,
        old_name: str,
        owner_id: int,
        *,
        conn: Connection | None = None,
    ) -> int | None:
        """Create an alias pointing to an existing tag.

        Args:
            guild_id: Discord guild identifier.
            new_name: Alias name to create.
            old_name: Existing tag name to alias.
            owner_id: User creating the alias.
            conn: Optional connection for transaction participation.

        Returns:
            The tag_id of the aliased tag, or None if the original tag was not found.
        """
        _conn = self._get_connection(conn)
        tag_id: int | None = await _conn.fetchval(
            """
            INSERT INTO public.tag_lookup (name, owner_id, location_id, tag_id)
            SELECT $1, $3, $4, tl.tag_id
            FROM public.tag_lookup tl
            WHERE lower(tl.name) = lower($2)
              AND tl.location_id = $4
            LIMIT 1
            RETURNING tag_id
            """,
            new_name,
            old_name,
            owner_id,
            guild_id,
        )
        return tag_id

    async def edit_tag(
        self,
        guild_id: int,
        name: str,
        new_content: str,
        owner_id: int,
        *,
        conn: Connection | None = None,
    ) -> bool:
        """Update the content of a tag.

        Only the tag owner can edit. Looks up via tag_lookup to resolve aliases.

        Args:
            guild_id: Discord guild identifier.
            name: Tag name (or alias) to edit.
            new_content: Replacement content.
            owner_id: User requesting the edit (must be owner).
            conn: Optional connection for transaction participation.

        Returns:
            True if the tag was updated, False otherwise.
        """
        _conn = self._get_connection(conn)
        result = await _conn.execute(
            """
            UPDATE public.tags
            SET content = $1
            WHERE id = (
                SELECT tl.tag_id
                FROM public.tag_lookup tl
                WHERE lower(tl.name) = lower($2)
                  AND tl.location_id = $3
                LIMIT 1
            )
            AND owner_id = $4
            """,
            new_content,
            name,
            guild_id,
            owner_id,
        )
        return result == "UPDATE 1"

    async def remove_tag_by_name(
        self,
        guild_id: int,
        name: str,
        *,
        conn: Connection | None = None,
    ) -> bool:
        """Remove a tag and all its lookup entries by name.

        Uses a transaction to first delete from tag_lookup, then from tags.

        Args:
            guild_id: Discord guild identifier.
            name: Tag name to remove.
            conn: Optional connection for transaction participation.

        Returns:
            True if the tag was deleted, False if not found.
        """
        _conn = self._get_connection(conn)

        # Find the tag_id first
        tag_id = await _conn.fetchval(
            """
            SELECT tl.tag_id
            FROM public.tag_lookup tl
            WHERE lower(tl.name) = lower($1)
              AND tl.location_id = $2
            LIMIT 1
            """,
            name,
            guild_id,
        )
        if tag_id is None:
            return False

        # Delete from tag_lookup (all entries for this tag)
        await _conn.execute(
            "DELETE FROM public.tag_lookup WHERE tag_id = $1 AND location_id = $2",
            tag_id,
            guild_id,
        )

        # Delete from tags
        result = await _conn.execute(
            "DELETE FROM public.tags WHERE id = $1 AND location_id = $2",
            tag_id,
            guild_id,
        )
        return result == "DELETE 1"

    async def remove_tag_by_id(
        self,
        guild_id: int,
        tag_id: int,
        *,
        conn: Connection | None = None,
    ) -> bool:
        """Remove a tag and all its lookup entries by tag ID.

        Args:
            guild_id: Discord guild identifier.
            tag_id: ID of the tag to remove.
            conn: Optional connection for transaction participation.

        Returns:
            True if the tag was deleted, False if not found.
        """
        _conn = self._get_connection(conn)

        # Delete from tag_lookup first
        await _conn.execute(
            "DELETE FROM public.tag_lookup WHERE tag_id = $1 AND location_id = $2",
            tag_id,
            guild_id,
        )

        # Delete from tags
        result = await _conn.execute(
            "DELETE FROM public.tags WHERE id = $1 AND location_id = $2",
            tag_id,
            guild_id,
        )
        return result == "DELETE 1"

    async def claim_tag(
        self,
        guild_id: int,
        name: str,
        requester_id: int,
        *,
        conn: Connection | None = None,
    ) -> bool:
        """Claim ownership of a tag.

        Transfers ownership of both the tag and all associated lookup entries.

        Args:
            guild_id: Discord guild identifier.
            name: Tag name to claim.
            requester_id: User claiming the tag.
            conn: Optional connection for transaction participation.

        Returns:
            True if the tag was claimed, False if not found.
        """
        _conn = self._get_connection(conn)

        # Find the tag_id
        tag_id = await _conn.fetchval(
            """
            SELECT tl.tag_id
            FROM public.tag_lookup tl
            WHERE lower(tl.name) = lower($1)
              AND tl.location_id = $2
            LIMIT 1
            """,
            name,
            guild_id,
        )
        if tag_id is None:
            return False

        # Update ownership on tags
        await _conn.execute(
            "UPDATE public.tags SET owner_id = $1 WHERE id = $2",
            requester_id,
            tag_id,
        )

        # Update ownership on tag_lookup
        await _conn.execute(
            "UPDATE public.tag_lookup SET owner_id = $1 WHERE tag_id = $2 AND location_id = $3",
            requester_id,
            tag_id,
            guild_id,
        )
        return True

    async def transfer_tag(
        self,
        guild_id: int,
        name: str,
        new_owner_id: int,
        requester_id: int,
        *,
        conn: Connection | None = None,
    ) -> bool:
        """Transfer tag ownership to another user.

        Only the current owner (requester_id) can transfer.

        Args:
            guild_id: Discord guild identifier.
            name: Tag name to transfer.
            new_owner_id: User receiving ownership.
            requester_id: Current owner requesting the transfer.
            conn: Optional connection for transaction participation.

        Returns:
            True if the tag was transferred, False if not found or not owner.
        """
        _conn = self._get_connection(conn)

        # Find the tag_id and verify ownership
        tag_id = await _conn.fetchval(
            """
            SELECT tl.tag_id
            FROM public.tag_lookup tl
            INNER JOIN public.tags t ON tl.tag_id = t.id
            WHERE lower(tl.name) = lower($1)
              AND tl.location_id = $2
              AND t.owner_id = $3
            LIMIT 1
            """,
            name,
            guild_id,
            requester_id,
        )
        if tag_id is None:
            return False

        # Update ownership on tags
        await _conn.execute(
            "UPDATE public.tags SET owner_id = $1 WHERE id = $2",
            new_owner_id,
            tag_id,
        )

        # Update ownership on tag_lookup
        await _conn.execute(
            "UPDATE public.tag_lookup SET owner_id = $1 WHERE tag_id = $2 AND location_id = $3",
            new_owner_id,
            tag_id,
            guild_id,
        )
        return True

    async def purge_tags(
        self,
        guild_id: int,
        owner_id: int,
        *,
        conn: Connection | None = None,
    ) -> int:
        """Bulk-delete all tags belonging to a specific owner.

        CASCADE on tag_lookup handles cleanup of lookup entries.

        Args:
            guild_id: Discord guild identifier.
            owner_id: Owner whose tags should be purged.
            conn: Optional connection for transaction participation.

        Returns:
            Number of tags deleted.
        """
        _conn = self._get_connection(conn)
        result = await _conn.execute(
            "DELETE FROM public.tags WHERE location_id = $1 AND owner_id = $2",
            guild_id,
            owner_id,
        )
        # result is like "DELETE N"
        return int(result.split(" ")[1])

    async def increment_usage(
        self,
        guild_id: int,
        name: str,
        *,
        conn: Connection | None = None,
    ) -> bool:
        """Increment the usage counter for a tag.

        Args:
            guild_id: Discord guild identifier.
            name: Tag name (resolved via tag_lookup).
            conn: Optional connection for transaction participation.

        Returns:
            True if the tag was found and updated, False otherwise.
        """
        _conn = self._get_connection(conn)
        result = await _conn.execute(
            """
            UPDATE public.tags
            SET uses = uses + 1
            WHERE id = (
                SELECT tl.tag_id
                FROM public.tag_lookup tl
                WHERE lower(tl.name) = lower($1)
                  AND tl.location_id = $2
                LIMIT 1
            )
            """,
            name,
            guild_id,
        )
        return result == "UPDATE 1"

    async def autocomplete_tags(
        self,
        filters: TagsAutocompleteRequest,
        *,
        conn: Connection | None = None,
    ) -> TagsAutocompleteResponse:
        """Provide tag name suggestions for autocomplete.

        Supports aliased, non_aliased, owned_aliased, and owned_non_aliased modes.

        Args:
            filters: Autocomplete request parameters.
            conn: Optional connection for transaction participation.

        Returns:
            TagsAutocompleteResponse with matching tag names.
        """
        _conn = self._get_connection(conn)

        # Choose table based on mode
        if filters.mode in ("non_aliased", "owned_non_aliased"):
            table = "public.tags"
        else:
            table = "public.tag_lookup"

        where_clauses: list[str] = []
        params: list[object] = []
        param_idx = 1

        where_clauses.append(f"location_id = ${param_idx}")
        params.append(filters.guild_id)
        param_idx += 1

        where_clauses.append(f"name % ${param_idx}")
        params.append(filters.q)
        param_idx += 1

        # Owner filter for owned modes
        if filters.mode in ("owned_aliased", "owned_non_aliased") and filters.owner_id is not None:
            where_clauses.append(f"owner_id = ${param_idx}")
            params.append(filters.owner_id)
            param_idx += 1

        where_str = " AND ".join(where_clauses)
        query = f"""
        SELECT name
        FROM {table}
        WHERE {where_str}
        ORDER BY similarity(name, ${param_idx}) DESC
        LIMIT ${param_idx + 1}
        """
        params.append(filters.q)
        params.append(filters.limit)

        rows = await _conn.fetch(query, *params)
        return TagsAutocompleteResponse(items=[row["name"] for row in rows])


async def provide_tags_repository(state: State) -> TagsRepository:
    """Litestar DI provider for TagsRepository.

    Args:
        state: Litestar application state with db_pool.

    Returns:
        A new TagsRepository instance.
    """
    return TagsRepository(pool=state.db_pool)
