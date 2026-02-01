"""Authentication domain exceptions.

These exceptions represent business rule violations in the auth domain.
They are raised by AuthService and caught by controllers.
"""

from __future__ import annotations

from utilities.errors import DomainError


class AuthError(DomainError):
    """Base for authentication/authorization errors."""


class InvalidCredentialsError(AuthError):
    """User provided invalid credentials."""

    def __init__(self, identifier: str | None = None) -> None:
        super().__init__("Invalid email or password.", identifier=identifier)


class EmailAlreadyExistsError(AuthError):
    """Email address is already registered."""

    def __init__(self, email: str) -> None:
        super().__init__("An account with this email already exists.", email=email)


class RateLimitExceededError(AuthError):
    """Too many attempts for an action."""

    def __init__(self, action: str, retry_after: int | None = None) -> None:
        message = f"Too many {action.replace('_', ' ')} attempts. Please try again later."
        super().__init__(message, action=action, retry_after=retry_after)


class TokenExpiredError(AuthError):
    """Token has expired."""

    def __init__(self, token_type: str) -> None:
        super().__init__(
            f"This {token_type} link has expired. Please request a new one.",
            token_type=token_type,
        )


class TokenAlreadyUsedError(AuthError):
    """Token has already been used."""

    def __init__(self, token_type: str) -> None:
        super().__init__(
            f"This {token_type} link has already been used.",
            token_type=token_type,
        )


class TokenInvalidError(AuthError):
    """Token is invalid or not found."""

    def __init__(self, token_type: str) -> None:
        super().__init__(
            f"Invalid {token_type} token.",
            token_type=token_type,
        )


class EmailAlreadyVerifiedError(AuthError):
    """Email is already verified."""

    def __init__(self) -> None:
        super().__init__("Email is already verified.")


class PasswordValidationError(AuthError):
    """Password doesn't meet requirements."""

    def __init__(self, message: str) -> None:
        super().__init__(message, field="password")


class UsernameValidationError(AuthError):
    """Username doesn't meet requirements."""

    def __init__(self, message: str) -> None:
        super().__init__(message, field="username")


class EmailValidationError(AuthError):
    """Email format is invalid."""

    def __init__(self) -> None:
        super().__init__("Invalid email format.", field="email")


class UserNotFoundError(AuthError):
    """User doesn't exist."""

    def __init__(self, identifier: str | int) -> None:
        super().__init__("No account found with this email.", identifier=identifier)
