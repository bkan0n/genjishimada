import functools
import re
import typing
from collections.abc import Awaitable, Callable
from logging import getLogger
from typing import Optional

import asyncpg
from litestar.exceptions import HTTPException
from litestar.status_codes import HTTP_400_BAD_REQUEST

if typing.TYPE_CHECKING:
    from typing import ParamSpec, TypeVar

    P = ParamSpec("P")
    R = TypeVar("R")

log = getLogger(__name__)

__all__ = ["ConstraintHandler", "CustomHTTPException", "DomainError", "handle_db_exceptions", "parse_pg_detail"]


def parse_pg_detail(detail: str | None) -> Optional[dict[str, str]]:
    """Extract column names and values from a Postgres error 'detail' string.

    "Key (map_id, mechanic_id)=(1, 2) already exists."
    Returns a dict: {'map_id': '1', 'mechanic_id': '2'}
    Returns None if no match is found.

    Args:
        detail (str): Postgres error 'detail' string.

    Returns:
        Optional[dict[str, str]]: Column names and values.

    """
    if detail is None:
        return None
    match = re.search(r"\((.*?)\)=\((.*?)\)", detail)
    if match:
        columns = [col.strip() for col in match.group(1).split(",")]
        values = [val.strip() for val in match.group(2).split(",")]
        return dict(zip(columns, values))
    return None


class CustomHTTPException(HTTPException): ...


class ConstraintHandler(typing.TypedDict):
    """Type definition for constraint error handlers."""

    message: str
    status_code: int


def handle_db_exceptions(
    unique_constraints: dict[str, ConstraintHandler] | None = None,
    fk_constraints: dict[str, ConstraintHandler] | None = None,
) -> Callable[..., typing.Any]:
    """Decorator to catch asyncpg constraint violations and convert to CustomHTTPException.

    Args:
        unique_constraints: Mapping of constraint names to error messages for unique violations.
        fk_constraints: Mapping of constraint names to error messages for foreign key violations.

    Returns:
        Decorator function that wraps async functions with exception handling.

    Example:
        @handle_db_exceptions(
            unique_constraints={
                "maps_code_key": ConstraintHandler(
                    message="Provided code already exists.",
                    status_code=HTTP_400_BAD_REQUEST
                )
            }
        )
        async def create_map(...):
            ...
    """
    unique_constraints = unique_constraints or {}
    fk_constraints = fk_constraints or {}

    def decorator(func: Callable[..., Awaitable[typing.Any]]) -> Callable[..., Awaitable[typing.Any]]:
        @functools.wraps(func)
        async def wrapper(*args: object, **kwargs: object) -> object:
            try:
                return await func(*args, **kwargs)
            except asyncpg.exceptions.UniqueViolationError as e:
                if e.constraint_name in unique_constraints:
                    handler = unique_constraints[e.constraint_name]
                    raise CustomHTTPException(
                        detail=handler["message"],
                        status_code=handler["status_code"],
                        extra=parse_pg_detail(e.detail),
                    ) from e

                log.warning(
                    "Unhandled UniqueViolationError - constraint: %s, detail: %s",
                    e.constraint_name,
                    e.detail,
                    exc_info=e,
                )
                raise CustomHTTPException(
                    detail="A unique constraint violation occurred.",
                    status_code=HTTP_400_BAD_REQUEST,
                    extra={"constraint": e.constraint_name},
                ) from e

            except asyncpg.exceptions.ForeignKeyViolationError as e:
                if e.constraint_name in fk_constraints:
                    handler = fk_constraints[e.constraint_name]
                    raise CustomHTTPException(
                        detail=handler["message"],
                        status_code=handler["status_code"],
                        extra=parse_pg_detail(e.detail),
                    ) from e

                log.warning(
                    "Unhandled ForeignKeyViolationError - constraint: %s, detail: %s",
                    e.constraint_name,
                    e.detail,
                    exc_info=e,
                )
                raise CustomHTTPException(
                    detail="A foreign key constraint violation occurred.",
                    status_code=HTTP_400_BAD_REQUEST,
                    extra={"constraint": e.constraint_name},
                ) from e

            except asyncpg.exceptions.CheckViolationError as e:
                log.warning(
                    "CheckViolationError - constraint: %s, detail: %s",
                    e.constraint_name,
                    e.detail,
                    exc_info=e,
                )
                raise CustomHTTPException(
                    detail="A check constraint violation occurred.",
                    status_code=HTTP_400_BAD_REQUEST,
                    extra={"constraint": e.constraint_name},
                ) from e

        return wrapper

    return decorator


class DomainError(Exception):
    """Base exception for domain-level business rule violations.

    Attributes:
        message: Human-readable error message.
        context: Additional context about the error.

    """

    def __init__(self, message: str, **context: typing.Any) -> None:  # noqa: ANN401
        """Initialize domain error.

        Args:
            message: Human-readable error message.
            **context: Additional context (e.g., field names, identifiers).

        """
        super().__init__(message)
        self.message = message
        self.context = context
