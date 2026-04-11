"""Content service for movement technique queries."""

from __future__ import annotations

from typing import Literal

import msgspec
from asyncpg import Pool
from litestar.datastructures import State

from repository.content_repository import ContentRepository
from repository.exceptions import UniqueConstraintViolationError

from .base import BaseService
from .exceptions.content import (
    CategoryNotFoundError,
    DifficultyNotFoundError,
    DuplicateNameError,
    TechniqueNotFoundError,
)


class ContentService(BaseService):
    """Service for content (movement techniques) business logic."""

    def __init__(self, pool: Pool, state: State, content_repo: ContentRepository) -> None:
        """Initialize content service.

        Args:
            pool: AsyncPG connection pool.
            state: Application state.
            content_repo: Content repository.
        """
        super().__init__(pool, state)
        self._content_repo = content_repo

    async def list_categories(self) -> list[dict]:
        """Return all movement technique categories.

        Returns:
            list[dict]: Categories ordered by sort_order.
        """
        return await self._content_repo.fetch_categories()

    async def list_difficulties(self) -> list[dict]:
        """Return all movement technique difficulty levels.

        Returns:
            list[dict]: Difficulties ordered by sort_order.
        """
        return await self._content_repo.fetch_difficulties()

    async def list_techniques(self) -> list[dict]:
        """Return all movement techniques with nested tips and videos.

        Returns:
            list[dict]: Techniques ordered by display_order with nested tips and videos.
        """
        return await self._content_repo.fetch_techniques()

    # -------------------------------------------------------------------------
    # Category admin
    # -------------------------------------------------------------------------

    async def create_category(self, name: str) -> dict:
        """Create a new movement technique category.

        Args:
            name: Category name (must be unique).

        Returns:
            dict: Created category (id, name, sort_order).

        Raises:
            DuplicateNameError: If a category with this name already exists.
        """
        try:
            return await self._content_repo.create_category(name)
        except UniqueConstraintViolationError as e:
            raise DuplicateNameError(f"A category named '{name}' already exists.") from e

    async def update_category(self, category_id: int, name: str) -> dict:
        """Update a category's name.

        Args:
            category_id: Category primary key.
            name: New name (must be unique).

        Returns:
            dict: Updated category (id, name, sort_order).

        Raises:
            CategoryNotFoundError: If no category with this id exists.
            DuplicateNameError: If a category with this name already exists.
        """
        try:
            row = await self._content_repo.update_category(category_id, name)
        except UniqueConstraintViolationError as e:
            raise DuplicateNameError(f"A category named '{name}' already exists.") from e
        if row is None:
            raise CategoryNotFoundError(f"Category {category_id} not found.")
        return row

    async def delete_category(self, category_id: int) -> None:
        """Delete a category and re-normalise sort_order in one transaction.

        Args:
            category_id: Category primary key.

        Raises:
            CategoryNotFoundError: If no category with this id exists.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            deleted = await self._content_repo.delete_category(category_id, conn=conn)  # type: ignore[arg-type]
            if not deleted:
                raise CategoryNotFoundError(f"Category {category_id} not found.")
            await self._content_repo.normalize_category_sort_order(conn=conn)  # type: ignore[arg-type]

    async def reorder_category(
        self,
        category_id: int,
        direction: Literal["up", "down"],
    ) -> list[dict]:
        """Move a category one position up or down.

        If the category is already at the boundary (first and moving up, or last
        and moving down) the list is returned unchanged (no-op).

        Args:
            category_id: Category primary key.
            direction: "up" to decrease sort_order, "down" to increase.

        Returns:
            list[dict]: Full ordered category list after the operation.

        Raises:
            CategoryNotFoundError: If no category with this id exists.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            categories = await self._content_repo.fetch_categories(conn=conn)  # type: ignore[arg-type]

            ids = [c["id"] for c in categories]
            if category_id not in ids:
                raise CategoryNotFoundError(f"Category {category_id} not found.")

            idx = ids.index(category_id)
            if direction == "up":
                if idx == 0:
                    return categories  # already first — no-op
                neighbor_id = ids[idx - 1]
            else:
                if idx == len(ids) - 1:
                    return categories  # already last — no-op
                neighbor_id = ids[idx + 1]

            await self._content_repo.swap_category_sort_order(category_id, neighbor_id, conn=conn)  # type: ignore[arg-type]
            await self._content_repo.normalize_category_sort_order(conn=conn)  # type: ignore[arg-type]

        return await self._content_repo.fetch_categories()

    # -------------------------------------------------------------------------
    # Difficulty admin
    # -------------------------------------------------------------------------

    async def create_difficulty(self, name: str) -> dict:
        """Create a new movement technique difficulty level.

        Args:
            name: Difficulty name (must be unique).

        Returns:
            dict: Created difficulty (id, name, sort_order).

        Raises:
            DuplicateNameError: If a difficulty with this name already exists.
        """
        try:
            return await self._content_repo.create_difficulty(name)
        except UniqueConstraintViolationError as e:
            raise DuplicateNameError(f"A difficulty named '{name}' already exists.") from e

    async def update_difficulty(self, difficulty_id: int, name: str) -> dict:
        """Update a difficulty's name.

        Args:
            difficulty_id: Difficulty primary key.
            name: New name (must be unique).

        Returns:
            dict: Updated difficulty (id, name, sort_order).

        Raises:
            DifficultyNotFoundError: If no difficulty with this id exists.
            DuplicateNameError: If a difficulty with this name already exists.
        """
        try:
            row = await self._content_repo.update_difficulty(difficulty_id, name)
        except UniqueConstraintViolationError as e:
            raise DuplicateNameError(f"A difficulty named '{name}' already exists.") from e
        if row is None:
            raise DifficultyNotFoundError(f"Difficulty {difficulty_id} not found.")
        return row

    async def delete_difficulty(self, difficulty_id: int) -> None:
        """Delete a difficulty and re-normalise sort_order in one transaction.

        Args:
            difficulty_id: Difficulty primary key.

        Raises:
            DifficultyNotFoundError: If no difficulty with this id exists.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            deleted = await self._content_repo.delete_difficulty(difficulty_id, conn=conn)  # type: ignore[arg-type]
            if not deleted:
                raise DifficultyNotFoundError(f"Difficulty {difficulty_id} not found.")
            await self._content_repo.normalize_difficulty_sort_order(conn=conn)  # type: ignore[arg-type]

    async def reorder_difficulty(
        self,
        difficulty_id: int,
        direction: Literal["up", "down"],
    ) -> list[dict]:
        """Move a difficulty one position up or down.

        If the difficulty is already at the boundary the list is returned unchanged.

        Args:
            difficulty_id: Difficulty primary key.
            direction: "up" to decrease sort_order, "down" to increase.

        Returns:
            list[dict]: Full ordered difficulty list after the operation.

        Raises:
            DifficultyNotFoundError: If no difficulty with this id exists.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            difficulties = await self._content_repo.fetch_difficulties(conn=conn)  # type: ignore[arg-type]

            ids = [d["id"] for d in difficulties]
            if difficulty_id not in ids:
                raise DifficultyNotFoundError(f"Difficulty {difficulty_id} not found.")

            idx = ids.index(difficulty_id)
            if direction == "up":
                if idx == 0:
                    return difficulties  # already first — no-op
                neighbor_id = ids[idx - 1]
            else:
                if idx == len(ids) - 1:
                    return difficulties  # already last — no-op
                neighbor_id = ids[idx + 1]

            await self._content_repo.swap_difficulty_sort_order(difficulty_id, neighbor_id, conn=conn)  # type: ignore[arg-type]
            await self._content_repo.normalize_difficulty_sort_order(conn=conn)  # type: ignore[arg-type]

        return await self._content_repo.fetch_difficulties()

    # -------------------------------------------------------------------------
    # Technique admin
    # -------------------------------------------------------------------------

    async def create_technique(  # noqa: PLR0913
        self,
        name: str,
        description: str | None,
        instructions: str | None,
        category_id: int | None,
        difficulty_id: int | None,
        tips: list[dict],
        videos: list[dict],
    ) -> dict:
        """Create a new technique with optional nested tips and videos.

        All inserts are wrapped in a single transaction. Raises ForeignKeyViolationError
        if category_id or difficulty_id is invalid — callers (controller) should convert
        this to HTTP 400.

        Args:
            name: Technique name.
            description: Optional description text.
            instructions: Optional free-text instructions block.
            category_id: Optional FK to movement_tech_categories.
            difficulty_id: Optional FK to movement_tech_difficulties.
            tips: List of dicts with keys ``text`` and ``sort_order``.
            videos: List of dicts with keys ``url``, ``caption``, ``sort_order``.

        Returns:
            dict: Full technique row with nested tips and videos.

        Raises:
            ForeignKeyViolationError: If category_id or difficulty_id does not exist.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            row = await self._content_repo.create_technique(
                name,
                description,
                instructions,
                category_id,
                difficulty_id,
                conn=conn,  # type: ignore[arg-type]
            )
            technique_id: int = row["id"]
            if tips:
                await self._content_repo.insert_technique_tips(technique_id, tips, conn=conn)  # type: ignore[arg-type]
            if videos:
                await self._content_repo.insert_technique_videos(technique_id, videos, conn=conn)  # type: ignore[arg-type]
            result = await self._content_repo.fetch_technique_by_id(technique_id, conn=conn)  # type: ignore[arg-type]
        return result  # type: ignore[return-value]

    async def fetch_technique(self, technique_id: int) -> dict:
        """Fetch a single technique by id.

        Args:
            technique_id: Technique primary key.

        Returns:
            dict: Full technique row with nested tips and videos.

        Raises:
            TechniqueNotFoundError: If no technique with this id exists.
        """
        row = await self._content_repo.fetch_technique_by_id(technique_id)
        if row is None:
            raise TechniqueNotFoundError(f"Technique {technique_id} not found.")
        return row

    async def update_technique(  # noqa: PLR0913
        self,
        technique_id: int,
        name: str | msgspec.UnsetType,
        description: str | None | msgspec.UnsetType,
        instructions: str | None | msgspec.UnsetType,
        category_id: int | None | msgspec.UnsetType,
        difficulty_id: int | None | msgspec.UnsetType,
        tips: list[dict] | msgspec.UnsetType,
        videos: list[dict] | msgspec.UnsetType,
    ) -> dict:
        """Update a technique's fields.  Only non-UNSET fields are written.

        Tips and videos are replaced wholesale when provided (not merged).

        Args:
            technique_id: Technique primary key.
            name: New name, or UNSET to leave unchanged.
            description: New description, or UNSET to leave unchanged.
            instructions: New instructions, or UNSET to leave unchanged.
            category_id: New category FK, or UNSET to leave unchanged.
            difficulty_id: New difficulty FK, or UNSET to leave unchanged.
            tips: New list of tip dicts, or UNSET to leave unchanged.
            videos: New list of video dicts, or UNSET to leave unchanged.

        Returns:
            dict: Updated technique row with nested tips and videos.

        Raises:
            TechniqueNotFoundError: If no technique with this id exists.
            ForeignKeyViolationError: If category_id or difficulty_id does not exist.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            # Fetch current values for any UNSET fields
            current = await self._content_repo.fetch_technique_by_id(technique_id, conn=conn)  # type: ignore[arg-type]
            if current is None:
                raise TechniqueNotFoundError(f"Technique {technique_id} not found.")

            resolved_name = current["name"] if isinstance(name, msgspec.UnsetType) else name
            resolved_desc = current["description"] if isinstance(description, msgspec.UnsetType) else description
            resolved_instr = current["instructions"] if isinstance(instructions, msgspec.UnsetType) else instructions
            resolved_cat = current["category_id"] if isinstance(category_id, msgspec.UnsetType) else category_id
            resolved_diff = current["difficulty_id"] if isinstance(difficulty_id, msgspec.UnsetType) else difficulty_id

            await self._content_repo.update_technique(
                technique_id,
                resolved_name,
                resolved_desc,
                resolved_instr,
                resolved_cat,
                resolved_diff,
                conn=conn,  # type: ignore[arg-type]
            )

            if not isinstance(tips, msgspec.UnsetType):
                await self._content_repo.delete_technique_tips(technique_id, conn=conn)  # type: ignore[arg-type]
                if tips:
                    await self._content_repo.insert_technique_tips(technique_id, tips, conn=conn)  # type: ignore[arg-type]

            if not isinstance(videos, msgspec.UnsetType):
                await self._content_repo.delete_technique_videos(technique_id, conn=conn)  # type: ignore[arg-type]
                if videos:
                    await self._content_repo.insert_technique_videos(technique_id, videos, conn=conn)  # type: ignore[arg-type]

            result = await self._content_repo.fetch_technique_by_id(technique_id, conn=conn)  # type: ignore[arg-type]
        return result  # type: ignore[return-value]

    async def delete_technique(self, technique_id: int) -> None:
        """Delete a technique and re-normalise display_order.

        Args:
            technique_id: Technique primary key.

        Raises:
            TechniqueNotFoundError: If no technique with this id exists.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            deleted = await self._content_repo.delete_technique(technique_id, conn=conn)  # type: ignore[arg-type]
            if not deleted:
                raise TechniqueNotFoundError(f"Technique {technique_id} not found.")
            await self._content_repo.normalize_technique_display_order(conn=conn)  # type: ignore[arg-type]

    async def reorder_technique(
        self,
        technique_id: int,
        direction: Literal["up", "down"],
    ) -> list[dict]:
        """Move a technique one position up or down.

        If the technique is already at the boundary the list is returned unchanged.

        Args:
            technique_id: Technique primary key.
            direction: "up" to decrease display_order, "down" to increase.

        Returns:
            list[dict]: Full ordered technique list after the operation.

        Raises:
            TechniqueNotFoundError: If no technique with this id exists.
        """
        async with self._pool.acquire() as conn, conn.transaction():
            techniques = await self._content_repo.fetch_techniques(conn=conn)  # type: ignore[arg-type]

            ids = [t["id"] for t in techniques]
            if technique_id not in ids:
                raise TechniqueNotFoundError(f"Technique {technique_id} not found.")

            idx = ids.index(technique_id)
            if direction == "up":
                if idx == 0:
                    return techniques  # already first — no-op
                neighbor_id = ids[idx - 1]
            else:
                if idx == len(ids) - 1:
                    return techniques  # already last — no-op
                neighbor_id = ids[idx + 1]

            await self._content_repo.swap_technique_display_order(technique_id, neighbor_id, conn=conn)  # type: ignore[arg-type]
            await self._content_repo.normalize_technique_display_order(conn=conn)  # type: ignore[arg-type]

        return await self._content_repo.fetch_techniques()


async def provide_content_service(
    state: State,
    content_repo: ContentRepository,
) -> ContentService:
    """Litestar DI provider for ContentService."""
    return ContentService(state.db_pool, state, content_repo)
