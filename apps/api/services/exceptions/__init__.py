"""Service-layer domain exceptions."""

from .auth import (  # noqa: I001
    AuthError,
    EmailAlreadyExistsError,
    EmailAlreadyVerifiedError,
    EmailValidationError,
    InvalidCredentialsError,
    PasswordValidationError,
    RateLimitExceededError,
    TokenAlreadyUsedError,
    TokenExpiredError,
    TokenInvalidError,
    UserNotFoundError,
    UsernameValidationError,
)

__all__ = [
    "AuthError",
    "EmailAlreadyExistsError",
    "EmailAlreadyVerifiedError",
    "EmailValidationError",
    "InvalidCredentialsError",
    "PasswordValidationError",
    "RateLimitExceededError",
    "TokenAlreadyUsedError",
    "TokenExpiredError",
    "TokenInvalidError",
    "UserNotFoundError",
    "UsernameValidationError",
]
