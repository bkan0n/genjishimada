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
from .lootbox import (
    InsufficientKeysError,
    LootboxError,
)

__all__ = [
    "AuthError",
    "EmailAlreadyExistsError",
    "EmailAlreadyVerifiedError",
    "EmailValidationError",
    "InsufficientKeysError",
    "InvalidCredentialsError",
    "LootboxError",
    "PasswordValidationError",
    "RateLimitExceededError",
    "TokenAlreadyUsedError",
    "TokenExpiredError",
    "TokenInvalidError",
    "UserNotFoundError",
    "UsernameValidationError",
]
