"""Service-layer domain exceptions."""

from .auth import (
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
    UsernameValidationError,
    UserNotFoundError,
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
