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


async def provide_image_storage_service() -> ImageStorageService:
    """Litestar DI provider for `ImageStorageService`.

    Returns:
        ImageStorageService: Service instance.

    """
    return ImageStorageService()
