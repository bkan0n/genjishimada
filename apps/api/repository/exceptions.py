"""Repository-layer exceptions.

These exceptions represent database-level errors and are raised by repositories
when database operations fail. Services catch these and translate to domain exceptions.
"""

from __future__ import annotations


class RepositoryError(Exception):
    """Base exception for repository layer errors."""

    def __init__(self, message: str, **context: object) -> None:
        """Initialize repository error.

        Args:
            message: Human-readable error message.
            **context: Additional context about the error.
        """
        self.message = message
        self.context = context
        super().__init__(message)


class UniqueConstraintViolationError(RepositoryError):
    """Database unique constraint was violated."""

    def __init__(self, constraint_name: str, table: str, detail: str | None = None) -> None:
        """Initialize unique constraint violation.

        Args:
            constraint_name: Name of the violated constraint.
            table: Table where violation occurred.
            detail: Optional detail from database error.
        """
        super().__init__(
            f"Unique constraint '{constraint_name}' violated on table '{table}'",
            constraint_name=constraint_name,
            table=table,
            detail=detail,
        )
        self.constraint_name = constraint_name
        self.table = table
        self.detail = detail


class ForeignKeyViolationError(RepositoryError):
    """Database foreign key constraint was violated."""

    def __init__(self, constraint_name: str, table: str, detail: str | None = None) -> None:
        """Initialize foreign key violation.

        Args:
            constraint_name: Name of the violated constraint.
            table: Table where violation occurred.
            detail: Optional detail from database error.
        """
        super().__init__(
            f"Foreign key constraint '{constraint_name}' violated on table '{table}'",
            constraint_name=constraint_name,
            table=table,
            detail=detail,
        )
        self.constraint_name = constraint_name
        self.table = table
        self.detail = detail


class CheckConstraintViolationError(RepositoryError):
    """Database check constraint was violated."""

    def __init__(self, constraint_name: str, table: str, detail: str | None = None) -> None:
        """Initialize check constraint violation.

        Args:
            constraint_name: Name of the violated constraint.
            table: Table where violation occurred.
            detail: Optional detail from database error.
        """
        super().__init__(
            f"Check constraint '{constraint_name}' violated on table '{table}'",
            constraint_name=constraint_name,
            table=table,
            detail=detail,
        )
        self.constraint_name = constraint_name
        self.table = table
        self.detail = detail


def extract_constraint_name(error: Exception) -> str | None:
    """Extract constraint name from asyncpg error.

    Args:
        error: The asyncpg exception.

    Returns:
        Constraint name if found, None otherwise.
    """
    # asyncpg errors have constraint_name attribute
    return getattr(error, "constraint_name", None)
