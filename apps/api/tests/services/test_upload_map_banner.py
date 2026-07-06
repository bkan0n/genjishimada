"""Unit tests for ImageStorageService.upload_map_banner.

The banner object key MUST match get_map_banner()'s read path byte-for-byte:
`assets/map_banners/{stripped}.png` where
stripped = re.sub(r"[^a-zA-Z0-9]", "", name).lower().strip().replace(" ", "").
The extension is ALWAYS .png regardless of the source content-type (the read path
hardcodes it). These tests mock the S3 client so no MinIO round-trip is needed.
"""

from unittest.mock import patch

from genjishimada_sdk.maps import get_map_banner

from services.image_storage_service import ImageStorageService

# No domain marker - this is an infrastructure service


def _banner_path_component(name: str) -> str:
    """Return the `assets/map_banners/{stripped}.png` component get_map_banner produces."""
    url = get_map_banner(name)
    # get_map_banner -> https://cdn.genji.pk/assets/map_banners/{stripped}.png
    return url.split("/assets/", 1)[1]  # -> map_banners/{stripped}.png


class TestUploadMapBanner:
    """Test upload_map_banner key derivation and return URL."""

    @patch("services.image_storage_service.S3_PUBLIC_URL", "https://cdn.example.com")
    @patch("services.image_storage_service.boto3.client")
    def test_kings_row_stripped_key(self, mock_boto3_client, mocker):
        """upload_map_banner keys 'King's Row' at assets/map_banners/kingsrow.png."""
        mock_s3 = mocker.Mock()
        mock_boto3_client.return_value = mock_s3

        service = ImageStorageService()
        result = service.upload_map_banner(b"fake banner", "image/png", "King's Row")

        expected_key = "assets/map_banners/kingsrow.png"
        call_args = mock_s3.upload_fileobj.call_args
        assert call_args[0][2] == expected_key
        assert result == f"https://cdn.example.com/{expected_key}"

    @patch("services.image_storage_service.boto3.client")
    def test_non_png_content_type_still_png_key(self, mock_boto3_client, mocker):
        """A non-png content-type still produces a .png key; ContentType is the real type."""
        mock_s3 = mocker.Mock()
        mock_boto3_client.return_value = mock_s3

        service = ImageStorageService()
        service.upload_map_banner(b"fake banner", "image/webp", "Hanamura")

        call_args = mock_s3.upload_fileobj.call_args
        key = call_args[0][2]
        extra_args = call_args[1]["ExtraArgs"]

        assert key == "assets/map_banners/hanamura.png"
        assert key.endswith(".png")
        assert extra_args["ContentType"] == "image/webp"

    @patch("services.image_storage_service.boto3.client")
    def test_accented_name_matches_get_map_banner(self, mock_boto3_client, mocker):
        """The produced key matches get_map_banner()'s path component for an accented name."""
        mock_s3 = mocker.Mock()
        mock_boto3_client.return_value = mock_s3

        service = ImageStorageService()
        name = "Château Guillard"
        service.upload_map_banner(b"fake banner", "image/png", name)

        call_args = mock_s3.upload_fileobj.call_args
        key = call_args[0][2]

        # NB: the accented "â" is REMOVED entirely by [^a-zA-Z0-9] (it is not
        # ASCII-folded to "a"), so "Château Guillard" -> "chteauguillard". This is
        # exactly what get_map_banner() produces, so banner reads still resolve.
        assert key == "assets/map_banners/chteauguillard.png"
        # And it MUST equal get_map_banner's path component byte-for-byte.
        assert key == f"assets/{_banner_path_component(name)}"

    @patch("services.image_storage_service.boto3.client")
    def test_key_matches_get_map_banner_for_kings_row(self, mock_boto3_client, mocker):
        """Cross-check the key against get_map_banner for a punctuated name."""
        mock_s3 = mocker.Mock()
        mock_boto3_client.return_value = mock_s3

        service = ImageStorageService()
        name = "King's Row"
        service.upload_map_banner(b"fake banner", "image/png", name)

        call_args = mock_s3.upload_fileobj.call_args
        key = call_args[0][2]
        assert key == f"assets/{_banner_path_component(name)}"

    @patch("services.image_storage_service.boto3.client")
    def test_sets_cache_control(self, mock_boto3_client, mocker):
        """upload_map_banner sets a CacheControl header on the object."""
        mock_s3 = mocker.Mock()
        mock_boto3_client.return_value = mock_s3

        service = ImageStorageService()
        service.upload_map_banner(b"fake banner", "image/png", "Busan")

        call_args = mock_s3.upload_fileobj.call_args
        extra_args = call_args[1]["ExtraArgs"]
        assert "CacheControl" in extra_args
        assert extra_args["CacheControl"].startswith("public")
