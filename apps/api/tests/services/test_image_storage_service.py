"""Unit tests for ImageStorageService."""

import hashlib
from datetime import datetime, timezone
from unittest.mock import ANY, patch

import pytest

from services.image_storage_service import ImageStorageService, _ext_from_content_type

# No domain marker - this is an infrastructure service


class TestContentTypeMapping:
    """Test _ext_from_content_type helper function."""

    def test_jpeg_content_type(self):
        """JPEG content type maps to 'jpg'."""
        assert _ext_from_content_type("image/jpeg") == "jpg"

    def test_png_content_type(self):
        """PNG content type maps to 'png'."""
        assert _ext_from_content_type("image/png") == "png"

    def test_webp_content_type(self):
        """WebP content type maps to 'webp'."""
        assert _ext_from_content_type("image/webp") == "webp"

    def test_avif_content_type(self):
        """AVIF content type maps to 'avif'."""
        assert _ext_from_content_type("image/avif") == "avif"

    def test_gif_content_type(self):
        """GIF content type maps to 'gif'."""
        assert _ext_from_content_type("image/gif") == "gif"

    def test_heic_content_type(self):
        """HEIC content type maps to 'heic'."""
        assert _ext_from_content_type("image/heic") == "heic"

    def test_unknown_content_type(self):
        """Unknown content type maps to 'bin'."""
        assert _ext_from_content_type("application/octet-stream") == "bin"

    def test_case_insensitive(self):
        """Content type matching is case insensitive."""
        assert _ext_from_content_type("IMAGE/JPEG") == "jpg"
        assert _ext_from_content_type("Image/PNG") == "png"


class TestUploadScreenshot:
    """Test upload_screenshot business logic."""

    @patch("services.image_storage_service.S3_PUBLIC_URL", "https://cdn.example.com")
    @patch("services.image_storage_service.boto3.client")
    def test_upload_screenshot_generates_correct_key(self, mock_boto3_client, mocker):
        """upload_screenshot generates key with hash, date, and extension."""
        mock_s3 = mocker.Mock()
        mock_boto3_client.return_value = mock_s3

        service = ImageStorageService()
        image_data = b"fake image data"
        content_type = "image/png"

        # Mock datetime to control date
        fake_now = datetime(2025, 9, 7, 12, 0, 0, tzinfo=timezone.utc)
        with patch("services.image_storage_service.dt.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now

            result = service.upload_screenshot(image_data, content_type)

        # Verify key structure
        expected_hash = hashlib.blake2b(image_data, digest_size=16).hexdigest()
        expected_key = f"screenshots/2025/09/07/{expected_hash}.png"

        # Verify S3 upload was called with correct key
        mock_s3.upload_fileobj.assert_called_once()
        call_args = mock_s3.upload_fileobj.call_args
        assert call_args[0][2] == expected_key  # key

        # Verify URL uses the patched public URL
        assert result == f"https://cdn.example.com/{expected_key}"

    @patch("services.image_storage_service.boto3.client")
    def test_upload_screenshot_sets_content_type(self, mock_boto3_client, mocker):
        """upload_screenshot sets correct Content-Type header."""
        mock_s3 = mocker.Mock()
        mock_boto3_client.return_value = mock_s3

        service = ImageStorageService()
        image_data = b"test data"
        content_type = "image/webp"

        service.upload_screenshot(image_data, content_type)

        # Verify ExtraArgs has correct ContentType
        call_args = mock_s3.upload_fileobj.call_args
        extra_args = call_args[1]["ExtraArgs"]
        assert extra_args["ContentType"] == "image/webp"

    @patch("services.image_storage_service.boto3.client")
    def test_upload_screenshot_sets_cache_control(self, mock_boto3_client, mocker):
        """upload_screenshot sets immutable cache control header."""
        mock_s3 = mocker.Mock()
        mock_boto3_client.return_value = mock_s3

        service = ImageStorageService()
        image_data = b"test data"

        service.upload_screenshot(image_data, "image/png")

        # Verify CacheControl header
        call_args = mock_s3.upload_fileobj.call_args
        extra_args = call_args[1]["ExtraArgs"]
        assert extra_args["CacheControl"] == "public, max-age=31536000, immutable"

    @patch("services.image_storage_service.boto3.client")
    def test_upload_screenshot_different_content_types(self, mock_boto3_client, mocker):
        """upload_screenshot uses correct extension for different content types."""
        mock_s3 = mocker.Mock()
        mock_boto3_client.return_value = mock_s3

        service = ImageStorageService()
        image_data = b"test"

        test_cases = [
            ("image/jpeg", ".jpg"),
            ("image/png", ".png"),
            ("image/webp", ".webp"),
            ("image/avif", ".avif"),
        ]

        for content_type, expected_ext in test_cases:
            mock_s3.reset_mock()
            service.upload_screenshot(image_data, content_type)

            # Get the key that was used
            call_args = mock_s3.upload_fileobj.call_args
            key = call_args[0][2]

            assert key.endswith(expected_ext), f"Expected {expected_ext} for {content_type}, got {key}"

    @patch("services.image_storage_service.boto3.client")
    def test_upload_screenshot_same_image_same_key(self, mock_boto3_client, mocker):
        """Same image content produces same key (deterministic hash)."""
        mock_s3 = mocker.Mock()
        mock_boto3_client.return_value = mock_s3

        service = ImageStorageService()
        image_data = b"same content"

        # Upload same image twice
        fake_now = datetime(2025, 9, 7, 12, 0, 0, tzinfo=timezone.utc)
        with patch("services.image_storage_service.dt.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now

            result1 = service.upload_screenshot(image_data, "image/png")

            mock_s3.reset_mock()

            result2 = service.upload_screenshot(image_data, "image/png")

        # Same content = same key = same URL
        assert result1 == result2
