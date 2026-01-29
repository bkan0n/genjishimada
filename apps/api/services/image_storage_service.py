import datetime as dt
import hashlib
import io
import logging
import os

import boto3
from botocore.config import Config

logger = logging.getLogger(__name__)

R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "")
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "genji-parkour-images")
S3_PUBLIC_URL = os.getenv("S3_PUBLIC_URL", "https://cdn.bkan0n.com")


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
        # Use custom S3 endpoint if provided (e.g., MinIO for local dev),
        # otherwise fall back to R2
        endpoint_url = S3_ENDPOINT_URL or f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com"

        self.client = boto3.client(
            service_name="s3",
            endpoint_url=endpoint_url,
            region_name="auto",  # R2 region is 'auto' (or wnam/enam/weur/eeur/apac)
            config=Config(s3={"addressing_style": "path"}),  # path-style works well with R2 endpoint
        )

    def upload_screenshot(self, image: bytes, content_type: str) -> str:
        """Upload image to S3-compatible stroage.

        Args:
            image (bytes): THe image in bytes form.
            content_type (str): The content type of the image.
        """
        # 1) Build a stable, unique key
        digest = hashlib.blake2b(image, digest_size=16).hexdigest()  # short but collision-resistant
        today = dt.datetime.now(dt.timezone.utc).strftime("%Y/%m/%d")
        ext = _ext_from_content_type(content_type)
        key = f"screenshots/{today}/{digest}.{ext}"

        # 2) Upload to S3-compatible storage with proper headers
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

        # 3) Return the PUBLIC URL (CDN for production, direct S3 URL for local dev)
        #    Example result: https://cdn.bkan0n.com/screenshots/2025/09/07/abcd1234.webp
        return f"{S3_PUBLIC_URL}/{key}"


async def provide_image_storage_service() -> ImageStorageService:
    """Litestar DI provider for `ImageStorageService`.

    Returns:
        ImageStorageService: Service instance.

    """
    return ImageStorageService()
