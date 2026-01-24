import asyncpg
import pytest
from litestar.status_codes import HTTP_400_BAD_REQUEST

from utilities.errors import ConstraintHandler, CustomHTTPException, handle_db_exceptions


class MockUniqueViolation(asyncpg.exceptions.UniqueViolationError):
    """Mock UniqueViolationError for testing."""

    def __init__(self, constraint_name: str, detail: str | None = None) -> None:
        self.constraint_name = constraint_name
        self.detail = detail
        super().__init__(f"duplicate key value violates unique constraint \"{constraint_name}\"")


class MockForeignKeyViolation(asyncpg.exceptions.ForeignKeyViolationError):
    """Mock ForeignKeyViolationError for testing."""

    def __init__(self, constraint_name: str, detail: str | None = None) -> None:
        self.constraint_name = constraint_name
        self.detail = detail
        super().__init__(f"insert or update on table violates foreign key constraint \"{constraint_name}\"")


@pytest.mark.asyncio
async def test_handle_unique_constraint_with_mapping() -> None:
    """Test that known unique constraints are converted to CustomHTTPException."""

    @handle_db_exceptions(
        unique_constraints={
            "test_unique": ConstraintHandler(message="Test unique error", status_code=HTTP_400_BAD_REQUEST)
        }
    )
    async def raise_unique_error() -> None:
        raise MockUniqueViolation("test_unique", "Key (id)=(1) already exists.")

    with pytest.raises(CustomHTTPException) as exc_info:
        await raise_unique_error()

    assert exc_info.value.detail == "Test unique error"
    assert exc_info.value.status_code == HTTP_400_BAD_REQUEST
    assert exc_info.value.extra == {"id": "1"}


@pytest.mark.asyncio
async def test_handle_unknown_unique_constraint() -> None:
    """Test that unknown unique constraints get generic error message."""

    @handle_db_exceptions()
    async def raise_unknown_unique() -> None:
        raise MockUniqueViolation("unknown_constraint")

    with pytest.raises(CustomHTTPException) as exc_info:
        await raise_unknown_unique()

    assert exc_info.value.detail == "A unique constraint violation occurred."
    assert exc_info.value.status_code == HTTP_400_BAD_REQUEST
    assert exc_info.value.extra == {"constraint": "unknown_constraint"}


@pytest.mark.asyncio
async def test_handle_foreign_key_constraint_with_mapping() -> None:
    """Test that known foreign key constraints are converted to CustomHTTPException."""

    @handle_db_exceptions(
        fk_constraints={
            "test_fk": ConstraintHandler(message="Test FK error", status_code=HTTP_400_BAD_REQUEST)
        }
    )
    async def raise_fk_error() -> None:
        raise MockForeignKeyViolation("test_fk", "Key (user_id)=(999) is not present in table.")

    with pytest.raises(CustomHTTPException) as exc_info:
        await raise_fk_error()

    assert exc_info.value.detail == "Test FK error"
    assert exc_info.value.status_code == HTTP_400_BAD_REQUEST
    assert exc_info.value.extra == {"user_id": "999"}


@pytest.mark.asyncio
async def test_handle_unknown_foreign_key_constraint() -> None:
    """Test that unknown FK constraints get generic error message."""

    @handle_db_exceptions()
    async def raise_unknown_fk() -> None:
        raise MockForeignKeyViolation("unknown_fk")

    with pytest.raises(CustomHTTPException) as exc_info:
        await raise_unknown_fk()

    assert exc_info.value.detail == "A foreign key constraint violation occurred."
    assert exc_info.value.status_code == HTTP_400_BAD_REQUEST


@pytest.mark.asyncio
async def test_decorator_preserves_function_behavior() -> None:
    """Test that decorator doesn't interfere with normal function execution."""

    @handle_db_exceptions()
    async def normal_function(x: int) -> int:
        return x * 2

    result = await normal_function(5)
    assert result == 10


@pytest.mark.asyncio
async def test_decorator_allows_other_exceptions() -> None:
    """Test that non-constraint exceptions are not caught."""

    @handle_db_exceptions()
    async def raise_value_error() -> None:
        raise ValueError("Not a constraint error")

    with pytest.raises(ValueError, match="Not a constraint error"):
        await raise_value_error()
