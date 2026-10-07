import datetime as dt
import hashlib
import io
import logging
import os
import re

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from genjishimada_sdk.helpers import sanitize_string
from litestar.status_codes import HTTP_409_CONFLICT

from utilities.errors import CustomHTTPException

logger = logging.getLogger(__name__)

R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "")
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "genji-parkour-images")
S3_PUBLIC_URL = os.getenv("S3_PUBLIC_URL", "https://cdn.genji.pk")


_content_type_ext = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/avif": "avif",
    "image/gif": "gif",
    "image/heic": "heic",
}


def _ext_from_content_type(ct: str) -> str:
    return _content_type_ext.get(ct.lower(), "bin")


class ImageStorageService:
    def __init__(self) -> None:
        """Initialize the ImageStorageService."""
        endpoint_url = S3_ENDPOINT_URL or f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"

        self.client = boto3.client(
            service_name="s3",
            endpoint_url=endpoint_url,
            region_name="auto",
            config=Config(s3={"addressing_style": "path"}),
        )

    def upload_screenshot(self, image: bytes, content_type: str) -> str:
        """Upload image to S3-compatible stroage.

        Args:
            image (bytes): THe image in bytes form.
            content_type (str): The content type of the image.
        """
        digest = hashlib.blake2b(image, digest_size=16).hexdigest()
        today = dt.datetime.now(dt.timezone.utc).strftime("%Y/%m/%d")
        ext = _ext_from_content_type(content_type)
        key = f"screenshots/{today}/{digest}.{ext}"

        fileobj = io.BytesIO(image)
        self.client.upload_fileobj(
            fileobj,
            S3_BUCKET_NAME,
            key,
            ExtraArgs={
                "ContentType": content_type,
                "CacheControl": "public, max-age=31536000, immutable",
            },
        )
        return f"{S3_PUBLIC_URL}/{key}"

    @staticmethod
    def map_artwork_keys(name: str) -> list[str]:
        """Return the existing SDK's banner and mastery reader paths."""
        banner = re.sub(r"[^a-zA-Z0-9]", "", name).lower()
        mastery = sanitize_string(name)
        levels = ("placeholder", "rookie", "explorer", "trailblazer", "pathfinder", "specialist", "prodigy")
        return [f"assets/map_banners/{banner}.png", *[f"assets/mastery/{mastery}_{level}.webp" for level in levels]]

    def _read_optional_object(self, key: str) -> bytes | None:
        try:
            response = self.client.get_object(Bucket=S3_BUCKET_NAME, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404", "NotFound"}:
                return None
            raise
        body = response["Body"]
        try:
            return body.read()
        finally:
            body.close()

    def preserve_map_artwork(self, old_name: str, name: str, own_names: set[str]) -> None:
        """Preflight and copy optional artwork without deleting compatibility objects.

        The caller holds the database's map ownership lock throughout. Existing
        different bytes are replaceable only at keys already owned by this map.
        All conflicts are checked before any copy; unexpected storage errors abort.
        """
        owned_keys = {key for spelling in own_names for key in self.map_artwork_keys(spelling)}
        copies: list[tuple[str, str]] = []
        for source, destination in zip(self.map_artwork_keys(old_name), self.map_artwork_keys(name), strict=True):
            if source == destination:
                continue
            content = self._read_optional_object(source)
            existing = self._read_optional_object(destination)
            if content is None and existing is not None:
                raise CustomHTTPException(
                    detail=f"Artwork exists at '{destination}' but no source artwork can replace it.",
                    status_code=HTTP_409_CONFLICT,
                )
            if content is None or existing == content:
                continue
            if existing is not None and destination not in owned_keys:
                raise CustomHTTPException(
                    detail=f"Artwork already exists at '{destination}' with different content.",
                    status_code=HTTP_409_CONFLICT,
                )
            copies.append((source, destination))
        for source, destination in copies:
            self.client.copy_object(
                Bucket=S3_BUCKET_NAME, Key=destination, CopySource={"Bucket": S3_BUCKET_NAME, "Key": source}
            )

    def upload_map_banner(self, content: bytes, content_type: str, map_name: str) -> str:
        """Upload a map banner keyed by the stripped map name.

        The object key MUST match ``get_map_banner()``'s read path byte-for-byte
        (``libs/sdk/.../maps.py``): ``assets/map_banners/{stripped}.png`` where
        ``stripped = re.sub(r"[^a-zA-Z0-9]", "", map_name).lower().strip().replace(" ", "")``.
        The extension is ALWAYS ``.png`` regardless of the source content-type because
        the read path hardcodes ``.png`` — uploading a webp/jpeg under a different
        extension would produce an unresolvable banner URL.

        Args:
            content (bytes): The banner image bytes.
            content_type (str): The source content type (passed through as ``ContentType``).
            map_name (str): The map name; reduced to the stripped key for the object path.

        Returns:
            str: The public CDN URL of the stored banner.
        """
        stripped = re.sub(r"[^a-zA-Z0-9]", "", map_name).lower().strip().replace(" ", "")
        key = f"assets/map_banners/{stripped}.png"

        fileobj = io.BytesIO(content)
        self.client.upload_fileobj(
            fileobj,
            S3_BUCKET_NAME,
            key,
            ExtraArgs={
                "ContentType": content_type,
                # Banners are replaceable (unlike immutable screenshots), so use a
                # shorter max-age and allow revalidation. Replace-banner CDN
                # staleness is accepted as eventual (Open Q1).
                "CacheControl": "public, max-age=3600, must-revalidate",
            },
        )
        return f"{S3_PUBLIC_URL}/{key}"


async def provide_image_storage_service() -> ImageStorageService:
    """Litestar DI provider for `ImageStorageService`.

    Returns:
        ImageStorageService: Service instance.

    """
    return ImageStorageService()
