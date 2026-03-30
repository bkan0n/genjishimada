"""Content repository for movement technique data access."""

from __future__ import annotations

import asyncpg
from asyncpg import Connection
from litestar.datastructures import State

from repository.exceptions import ForeignKeyViolationError, UniqueConstraintViolationError, extract_constraint_name

from .base import BaseRepository


class ContentRepository(BaseRepository):
    """Repository for content (movement techniques) data access."""

    async def fetch_categories(
        self,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch all movement technique categories ordered by sort_order.

        Returns:
            list[dict]: Category rows with id, name, sort_order.
        """
        _conn = self._get_connection(conn)
        query = """
        SELECT id, name, sort_order
        FROM content.movement_tech_categories
        ORDER BY sort_order
        """
        rows = await _conn.fetch(query)
        return [dict(row) for row in rows]

    async def fetch_difficulties(
        self,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch all movement technique difficulties ordered by sort_order.

        Returns:
            list[dict]: Difficulty rows with id, name, sort_order.
        """
        _conn = self._get_connection(conn)
        query = """
        SELECT id, name, sort_order
        FROM content.movement_tech_difficulties
        ORDER BY sort_order
        """
        rows = await _conn.fetch(query)
        return [dict(row) for row in rows]

    async def fetch_techniques(
        self,
        *,
        conn: Connection | None = None,
    ) -> list[dict]:
        """Fetch all movement techniques with nested tips and videos.

        Joins techniques with categories, difficulties, tips, and videos.
        Uses json_agg with FILTER to prevent null entries when no tips/videos exist.

        Returns:
            list[dict]: Technique rows with nested tips and videos arrays.
        """
        _conn = self._get_connection(conn)
        query = """
        SELECT
            t.id,
            t.name,
            t.description,
            t.display_order,
            t.category_id,
            c.name AS category_name,
            t.difficulty_id,
            d.name AS difficulty_name,
            COALESCE(
                json_agg(
                    json_build_object(
                        'id', tip.id,
                        'text', tip.text,
                        'sort_order', tip.sort_order
                    ) ORDER BY tip.sort_order
                ) FILTER (WHERE tip.id IS NOT NULL),
                '[]'::json
            ) AS tips,
            COALESCE(
                json_agg(
                    json_build_object(
                        'id', vid.id,
                        'url', vid.url,
                        'caption', vid.caption,
                        'sort_order', vid.sort_order
                    ) ORDER BY vid.sort_order
                ) FILTER (WHERE vid.id IS NOT NULL),
                '[]'::json
            ) AS videos
        FROM content.movement_techniques t
        LEFT JOIN content.movement_tech_categories c ON t.category_id = c.id
        LEFT JOIN content.movement_tech_difficulties d ON t.difficulty_id = d.id
        LEFT JOIN content.movement_tech_tips tip ON t.id = tip.technique_id
        LEFT JOIN content.movement_tech_videos vid ON t.id = vid.technique_id
        GROUP BY
            t.id,
            t.name,
            t.description,
            t.display_order,
            t.category_id,
            c.name,
            t.difficulty_id,
            d.name
        ORDER BY t.display_order
        """
        rows = await _conn.fetch(query)
        return [dict(row) for row in rows]

    # -------------------------------------------------------------------------
    # Category CRUD + reorder
    # -------------------------------------------------------------------------

    async def create_category(
        self,
        name: str,
        *,
        conn: Connection | None = None,
    ) -> dict:
        """Insert a new category with sort_order = MAX(sort_order) + 1.

        Args:
            name: Category name (must be unique).
            conn: Optional connection for transaction participation.

        Returns:
            dict: Created category row (id, name, sort_order).

        Raises:
            UniqueConstraintViolationError: If name already exists.
        """
        _conn = self._get_connection(conn)
        query = """
        INSERT INTO content.movement_tech_categories (name, sort_order)
        VALUES ($1, COALESCE((SELECT MAX(sort_order) FROM content.movement_tech_categories), 0) + 1)
        RETURNING id, name, sort_order
        """
        try:
            row = await _conn.fetchrow(query, name)
        except asyncpg.UniqueViolationError as e:
            constraint = extract_constraint_name(e)
            raise UniqueConstraintViolationError(
                constraint_name=constraint or "unknown",
                table="content.movement_tech_categories",
                detail=str(e),
            ) from e
        return dict(row)  # type: ignore[arg-type]

    async def create_difficulty(
        self,
        name: str,
        *,
        conn: Connection | None = None,
    ) -> dict:
        """Insert a new difficulty with sort_order = MAX(sort_order) + 1.

        Args:
            name: Difficulty name (must be unique).
            conn: Optional connection for transaction participation.

        Returns:
            dict: Created difficulty row (id, name, sort_order).

        Raises:
            UniqueConstraintViolationError: If name already exists.
        """
        _conn = self._get_connection(conn)
        query = """
        INSERT INTO content.movement_tech_difficulties (name, sort_order)
        VALUES ($1, COALESCE((SELECT MAX(sort_order) FROM content.movement_tech_difficulties), 0) + 1)
        RETURNING id, name, sort_order
        """
        try:
            row = await _conn.fetchrow(query, name)
        except asyncpg.UniqueViolationError as e:
            constraint = extract_constraint_name(e)
            raise UniqueConstraintViolationError(
                constraint_name=constraint or "unknown",
                table="content.movement_tech_difficulties",
                detail=str(e),
            ) from e
        return dict(row)  # type: ignore[arg-type]

    async def fetch_category_by_id(
        self,
        category_id: int,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Fetch a single category by primary key.

        Args:
            category_id: Category primary key.
            conn: Optional connection for transaction participation.

        Returns:
            dict if found, None otherwise.
        """
        _conn = self._get_connection(conn)
        query = """
        SELECT id, name, sort_order
        FROM content.movement_tech_categories
        WHERE id = $1
        """
        row = await _conn.fetchrow(query, category_id)
        return dict(row) if row else None

    async def fetch_difficulty_by_id(
        self,
        difficulty_id: int,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Fetch a single difficulty by primary key.

        Args:
            difficulty_id: Difficulty primary key.
            conn: Optional connection for transaction participation.

        Returns:
            dict if found, None otherwise.
        """
        _conn = self._get_connection(conn)
        query = """
        SELECT id, name, sort_order
        FROM content.movement_tech_difficulties
        WHERE id = $1
        """
        row = await _conn.fetchrow(query, difficulty_id)
        return dict(row) if row else None

    async def update_category(
        self,
        category_id: int,
        name: str,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Update a category's name by id.

        Args:
            category_id: Category primary key.
            name: New name (must be unique).
            conn: Optional connection for transaction participation.

        Returns:
            Updated dict if found, None if id not found.

        Raises:
            UniqueConstraintViolationError: If name already exists.
        """
        _conn = self._get_connection(conn)
        query = """
        UPDATE content.movement_tech_categories
        SET name = $1
        WHERE id = $2
        RETURNING id, name, sort_order
        """
        try:
            row = await _conn.fetchrow(query, name, category_id)
        except asyncpg.UniqueViolationError as e:
            constraint = extract_constraint_name(e)
            raise UniqueConstraintViolationError(
                constraint_name=constraint or "unknown",
                table="content.movement_tech_categories",
                detail=str(e),
            ) from e
        return dict(row) if row else None

    async def update_difficulty(
        self,
        difficulty_id: int,
        name: str,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Update a difficulty's name by id.

        Args:
            difficulty_id: Difficulty primary key.
            name: New name (must be unique).
            conn: Optional connection for transaction participation.

        Returns:
            Updated dict if found, None if id not found.

        Raises:
            UniqueConstraintViolationError: If name already exists.
        """
        _conn = self._get_connection(conn)
        query = """
        UPDATE content.movement_tech_difficulties
        SET name = $1
        WHERE id = $2
        RETURNING id, name, sort_order
        """
        try:
            row = await _conn.fetchrow(query, name, difficulty_id)
        except asyncpg.UniqueViolationError as e:
            constraint = extract_constraint_name(e)
            raise UniqueConstraintViolationError(
                constraint_name=constraint or "unknown",
                table="content.movement_tech_difficulties",
                detail=str(e),
            ) from e
        return dict(row) if row else None

    async def delete_category(
        self,
        category_id: int,
        *,
        conn: Connection | None = None,
    ) -> bool:
        """Delete a category by id.

        Args:
            category_id: Category primary key.
            conn: Optional connection for transaction participation.

        Returns:
            True if a row was deleted, False if id not found.
        """
        _conn = self._get_connection(conn)
        result = await _conn.execute(
            "DELETE FROM content.movement_tech_categories WHERE id = $1",
            category_id,
        )
        # result is a string like "DELETE N"
        return result == "DELETE 1"

    async def delete_difficulty(
        self,
        difficulty_id: int,
        *,
        conn: Connection | None = None,
    ) -> bool:
        """Delete a difficulty by id.

        Args:
            difficulty_id: Difficulty primary key.
            conn: Optional connection for transaction participation.

        Returns:
            True if a row was deleted, False if id not found.
        """
        _conn = self._get_connection(conn)
        result = await _conn.execute(
            "DELETE FROM content.movement_tech_difficulties WHERE id = $1",
            difficulty_id,
        )
        return result == "DELETE 1"

    async def normalize_category_sort_order(
        self,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Re-assign contiguous sort_order values (1, 2, 3 …) to all categories.

        Uses ROW_NUMBER() ordered by the current sort_order so relative positions
        are preserved after a delete.

        Args:
            conn: Optional connection for transaction participation.
        """
        _conn = self._get_connection(conn)
        query = """
        UPDATE content.movement_tech_categories AS c
        SET sort_order = ranked.rn
        FROM (
            SELECT id, ROW_NUMBER() OVER (ORDER BY sort_order) AS rn
            FROM content.movement_tech_categories
        ) AS ranked
        WHERE c.id = ranked.id
        """
        await _conn.execute(query)

    async def normalize_difficulty_sort_order(
        self,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Re-assign contiguous sort_order values (1, 2, 3 …) to all difficulties.

        Args:
            conn: Optional connection for transaction participation.
        """
        _conn = self._get_connection(conn)
        query = """
        UPDATE content.movement_tech_difficulties AS d
        SET sort_order = ranked.rn
        FROM (
            SELECT id, ROW_NUMBER() OVER (ORDER BY sort_order) AS rn
            FROM content.movement_tech_difficulties
        ) AS ranked
        WHERE d.id = ranked.id
        """
        await _conn.execute(query)

    async def swap_category_sort_order(
        self,
        id_a: int,
        id_b: int,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Swap sort_order between two categories.

        Args:
            id_a: First category id.
            id_b: Second category id.
            conn: Optional connection for transaction participation.
        """
        _conn = self._get_connection(conn)
        query = """
        UPDATE content.movement_tech_categories AS c
        SET sort_order = CASE
            WHEN c.id = $1 THEN other.sort_order
            WHEN c.id = $2 THEN self.sort_order
        END
        FROM content.movement_tech_categories AS self,
             content.movement_tech_categories AS other
        WHERE self.id = $1
          AND other.id = $2
          AND c.id IN ($1, $2)
        """
        await _conn.execute(query, id_a, id_b)

    async def swap_difficulty_sort_order(
        self,
        id_a: int,
        id_b: int,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Swap sort_order between two difficulties.

        Args:
            id_a: First difficulty id.
            id_b: Second difficulty id.
            conn: Optional connection for transaction participation.
        """
        _conn = self._get_connection(conn)
        query = """
        UPDATE content.movement_tech_difficulties AS d
        SET sort_order = CASE
            WHEN d.id = $1 THEN other.sort_order
            WHEN d.id = $2 THEN self.sort_order
        END
        FROM content.movement_tech_difficulties AS self,
             content.movement_tech_difficulties AS other
        WHERE self.id = $1
          AND other.id = $2
          AND d.id IN ($1, $2)
        """
        await _conn.execute(query, id_a, id_b)

    # -------------------------------------------------------------------------
    # Technique CRUD + reorder
    # -------------------------------------------------------------------------

    async def create_technique(
        self,
        name: str,
        description: str | None,
        category_id: int | None,
        difficulty_id: int | None,
        *,
        conn: Connection | None = None,
    ) -> dict:
        """Insert a new technique with display_order = MAX(display_order) + 1.

        Args:
            name: Technique name.
            description: Optional description text.
            category_id: Optional FK to movement_tech_categories.
            difficulty_id: Optional FK to movement_tech_difficulties.
            conn: Optional connection for transaction participation.

        Returns:
            dict: Created technique row (id, name, description, display_order, category_id, difficulty_id).

        Raises:
            ForeignKeyViolationError: If category_id or difficulty_id does not exist.
        """
        _conn = self._get_connection(conn)
        query = """
        INSERT INTO content.movement_techniques (name, description, category_id, difficulty_id, display_order)
        VALUES (
            $1,
            $2,
            $3,
            $4,
            COALESCE((SELECT MAX(display_order) FROM content.movement_techniques), 0) + 1
        )
        RETURNING id, name, description, display_order, category_id, difficulty_id
        """
        try:
            row = await _conn.fetchrow(query, name, description, category_id, difficulty_id)
        except asyncpg.ForeignKeyViolationError as e:
            constraint = extract_constraint_name(e)
            raise ForeignKeyViolationError(
                constraint_name=constraint or "unknown",
                table="content.movement_techniques",
                detail=str(e),
            ) from e
        return dict(row)  # type: ignore[arg-type]

    async def insert_technique_tips(
        self,
        technique_id: int,
        tips_data: list[dict],
        *,
        conn: Connection | None = None,
    ) -> None:
        """Bulk-insert tips for a technique.

        Args:
            technique_id: Technique primary key.
            tips_data: List of dicts with keys ``text`` and ``sort_order``.
            conn: Optional connection for transaction participation.
        """
        if not tips_data:
            return
        _conn = self._get_connection(conn)
        query = """
        INSERT INTO content.movement_tech_tips (technique_id, text, sort_order)
        VALUES ($1, $2, $3)
        """
        await _conn.executemany(
            query,
            [(technique_id, tip["text"], tip["sort_order"]) for tip in tips_data],
        )

    async def insert_technique_videos(
        self,
        technique_id: int,
        videos_data: list[dict],
        *,
        conn: Connection | None = None,
    ) -> None:
        """Bulk-insert videos for a technique.

        Args:
            technique_id: Technique primary key.
            videos_data: List of dicts with keys ``url``, ``caption``, and ``sort_order``.
            conn: Optional connection for transaction participation.
        """
        if not videos_data:
            return
        _conn = self._get_connection(conn)
        query = """
        INSERT INTO content.movement_tech_videos (technique_id, url, caption, sort_order)
        VALUES ($1, $2, $3, $4)
        """
        await _conn.executemany(
            query,
            [(technique_id, vid["url"], vid.get("caption"), vid["sort_order"]) for vid in videos_data],
        )

    async def delete_technique_tips(
        self,
        technique_id: int,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Delete all tips for a technique (used before full replacement).

        Args:
            technique_id: Technique primary key.
            conn: Optional connection for transaction participation.
        """
        _conn = self._get_connection(conn)
        await _conn.execute(
            "DELETE FROM content.movement_tech_tips WHERE technique_id = $1",
            technique_id,
        )

    async def delete_technique_videos(
        self,
        technique_id: int,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Delete all videos for a technique (used before full replacement).

        Args:
            technique_id: Technique primary key.
            conn: Optional connection for transaction participation.
        """
        _conn = self._get_connection(conn)
        await _conn.execute(
            "DELETE FROM content.movement_tech_videos WHERE technique_id = $1",
            technique_id,
        )

    async def fetch_technique_by_id(
        self,
        technique_id: int,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Fetch a single technique with nested tips and videos by primary key.

        Uses the same json_agg FILTER/COALESCE pattern as fetch_techniques.

        Args:
            technique_id: Technique primary key.
            conn: Optional connection for transaction participation.

        Returns:
            dict with nested tips/videos if found, None otherwise.
        """
        _conn = self._get_connection(conn)
        query = """
        SELECT
            t.id,
            t.name,
            t.description,
            t.display_order,
            t.category_id,
            c.name AS category_name,
            t.difficulty_id,
            d.name AS difficulty_name,
            COALESCE(
                json_agg(
                    json_build_object(
                        'id', tip.id,
                        'text', tip.text,
                        'sort_order', tip.sort_order
                    ) ORDER BY tip.sort_order
                ) FILTER (WHERE tip.id IS NOT NULL),
                '[]'::json
            ) AS tips,
            COALESCE(
                json_agg(
                    json_build_object(
                        'id', vid.id,
                        'url', vid.url,
                        'caption', vid.caption,
                        'sort_order', vid.sort_order
                    ) ORDER BY vid.sort_order
                ) FILTER (WHERE vid.id IS NOT NULL),
                '[]'::json
            ) AS videos
        FROM content.movement_techniques t
        LEFT JOIN content.movement_tech_categories c ON t.category_id = c.id
        LEFT JOIN content.movement_tech_difficulties d ON t.difficulty_id = d.id
        LEFT JOIN content.movement_tech_tips tip ON t.id = tip.technique_id
        LEFT JOIN content.movement_tech_videos vid ON t.id = vid.technique_id
        WHERE t.id = $1
        GROUP BY
            t.id,
            t.name,
            t.description,
            t.display_order,
            t.category_id,
            c.name,
            t.difficulty_id,
            d.name
        """
        row = await _conn.fetchrow(query, technique_id)
        return dict(row) if row else None

    async def update_technique(  # noqa: PLR0913
        self,
        technique_id: int,
        name: str,
        description: str | None,
        category_id: int | None,
        difficulty_id: int | None,
        *,
        conn: Connection | None = None,
    ) -> dict | None:
        """Update the core technique row (not tips/videos).

        Args:
            technique_id: Technique primary key.
            name: New name.
            description: New description (or None to clear).
            category_id: New category FK (or None).
            difficulty_id: New difficulty FK (or None).
            conn: Optional connection for transaction participation.

        Returns:
            Updated dict if found, None if id not found.

        Raises:
            ForeignKeyViolationError: If category_id or difficulty_id does not exist.
        """
        _conn = self._get_connection(conn)
        query = """
        UPDATE content.movement_techniques
        SET name = $1, description = $2, category_id = $3, difficulty_id = $4
        WHERE id = $5
        RETURNING id, name, description, display_order, category_id, difficulty_id
        """
        try:
            row = await _conn.fetchrow(query, name, description, category_id, difficulty_id, technique_id)
        except asyncpg.ForeignKeyViolationError as e:
            constraint = extract_constraint_name(e)
            raise ForeignKeyViolationError(
                constraint_name=constraint or "unknown",
                table="content.movement_techniques",
                detail=str(e),
            ) from e
        return dict(row) if row else None

    async def delete_technique(
        self,
        technique_id: int,
        *,
        conn: Connection | None = None,
    ) -> bool:
        """Delete a technique by id.  Tips and videos are removed via CASCADE.

        Args:
            technique_id: Technique primary key.
            conn: Optional connection for transaction participation.

        Returns:
            True if a row was deleted, False if id not found.
        """
        _conn = self._get_connection(conn)
        result = await _conn.execute(
            "DELETE FROM content.movement_techniques WHERE id = $1",
            technique_id,
        )
        return result == "DELETE 1"

    async def swap_technique_display_order(
        self,
        id_a: int,
        id_b: int,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Swap display_order between two techniques.

        Args:
            id_a: First technique id.
            id_b: Second technique id.
            conn: Optional connection for transaction participation.
        """
        _conn = self._get_connection(conn)
        query = """
        UPDATE content.movement_techniques AS t
        SET display_order = CASE
            WHEN t.id = $1 THEN other.display_order
            WHEN t.id = $2 THEN self.display_order
        END
        FROM content.movement_techniques AS self,
             content.movement_techniques AS other
        WHERE self.id = $1
          AND other.id = $2
          AND t.id IN ($1, $2)
        """
        await _conn.execute(query, id_a, id_b)

    async def normalize_technique_display_order(
        self,
        *,
        conn: Connection | None = None,
    ) -> None:
        """Re-assign contiguous display_order values (1, 2, 3 …) to all techniques.

        Uses ROW_NUMBER() ordered by the current display_order so relative positions
        are preserved after a delete.

        Args:
            conn: Optional connection for transaction participation.
        """
        _conn = self._get_connection(conn)
        query = """
        UPDATE content.movement_techniques AS t
        SET display_order = ranked.rn
        FROM (
            SELECT id, ROW_NUMBER() OVER (ORDER BY display_order) AS rn
            FROM content.movement_techniques
        ) AS ranked
        WHERE t.id = ranked.id
        """
        await _conn.execute(query)


async def provide_content_repository(state: State) -> ContentRepository:
    """Litestar DI provider for ContentRepository."""
    return ContentRepository(state.db_pool)
