"""Tests for lootbox domain exceptions."""

from services.exceptions.lootbox import InsufficientKeysError, LootboxError


class TestExceptions:
    """Test domain exceptions."""

    def test_lootbox_error_base(self) -> None:
        """Test base LootboxError."""
        error = LootboxError("test message")
        assert "test message" in str(error)

    def test_insufficient_keys_error(self) -> None:
        """Test InsufficientKeysError."""
        error = InsufficientKeysError("Classic")
        assert "Classic" in error.message
        assert "enough keys" in error.message.lower()
        assert error.context["key_type"] == "Classic"
