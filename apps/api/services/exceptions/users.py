"""Users domain exceptions.

These exceptions represent business rule violations in the users domain.
They are raised by UsersService and caught by controllers.
"""

from utilities.errors import DomainError


class UsersError(DomainError):
    """Base for users domain errors."""


class InvalidUserIdError(UsersError):
    """User ID is below the minimum allowed value."""

    def __init__(self, user_id: int, minimum: int = 100_000_000) -> None:
        super().__init__(
            f"Please use create fake member endpoint for user ids less than {minimum}.",
            user_id=user_id,
            minimum=minimum,
        )


class UserAlreadyExistsError(UsersError):
    """User ID already exists in the system."""

    def __init__(self, user_id: int) -> None:
        super().__init__("Provided user_id already exists.", user_id=user_id)


class UserNotFoundError(UsersError):
    """User does not exist."""

    def __init__(self, user_id: int) -> None:
        super().__init__("User not found.", user_id=user_id)


class DuplicateOverwatchUsernameError(UsersError):
    """Duplicate Overwatch username for a user."""

    def __init__(self, user_id: int, username: str) -> None:
        super().__init__("Duplicate Overwatch username provided.", user_id=user_id, username=username)
