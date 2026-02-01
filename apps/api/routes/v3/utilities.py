"""V4 Utilities routes."""

from __future__ import annotations

from typing import Annotated

from genjishimada_sdk.logs import LogCreateRequest, MapClickCreateRequest
from litestar import Controller, get, post
from litestar.datastructures import UploadFile
from litestar.di import Provide
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Response
from litestar.status_codes import HTTP_204_NO_CONTENT

from repository.utilities_repository import provide_utilities_repository
from services.image_storage_service import ImageStorageService, provide_image_storage_service
from services.utilities_service import LogClicksDebug, UtilitiesService, provide_utilities_service


class UtilitiesController(Controller):
    """Controller for utilities endpoints."""

    tags = ["Utilities"]
    path = "/utilities"
    dependencies = {
        "utilities_repo": Provide(provide_utilities_repository),
        "utilities_service": Provide(provide_utilities_service),
    }

    @post(
        "/image",
        dependencies={"image_svc": Provide(provide_image_storage_service)},
        summary="Upload Image",
        description="Upload an image or screenshot file to the CDN. The file must be sent as multipart/form-data.",
        sync_to_thread=False,
        request_max_body_size=1024 * 1024 * 25,  # 25MB
    )
    def upload_image(
        self,
        data: Annotated[UploadFile, Body(media_type=RequestEncodingType.MULTI_PART)],
        image_svc: ImageStorageService,
    ) -> str:
        """Upload an image/screenshot to CDN.

        This is a synchronous endpoint that directly uploads to S3.

        Args:
            data: Uploaded file received as multipart form-data.
            image_svc: Service responsible for handling CDN uploads.

        Returns:
            The public CDN URL of the uploaded screenshot (200 OK).
        """
        content = data.file.read()
        return image_svc.upload_screenshot(content, data.content_type)

    @post(
        "/log",
        include_in_schema=False,
    )
    async def log_analytics(
        self,
        utilities_service: UtilitiesService,
        data: Annotated[LogCreateRequest, Body(title="Analytics log request")],
    ) -> Response:
        """Log Discord interaction command information.

        Internal endpoint not included in public API schema.

        Args:
            utilities_service: Service dependency.
            data: Analytics log request.

        Returns:
            Empty response with 204 No Content.
        """
        await utilities_service.log_analytics(data)
        return Response(None, status_code=HTTP_204_NO_CONTENT)

    @post(
        "/log-map-click",
        summary="Log Map Code Clicks",
        description="Log when a user clicks on a Map Code Copy button.",
    )
    async def log_map_click(
        self,
        utilities_service: UtilitiesService,
        data: Annotated[MapClickCreateRequest, Body(title="Map click request")],
    ) -> Response:
        """Log the click on a 'copy code' button on the website.

        Args:
            utilities_service: Service dependency.
            data: Map click request.

        Returns:
            Empty response with 204 No Content.
        """
        await utilities_service.log_map_click(data)
        return Response(None, status_code=HTTP_204_NO_CONTENT)

    @get("/log-map-click")
    async def get_log_map_clicks(
        self,
        utilities_service: UtilitiesService,
    ) -> list[LogClicksDebug]:
        """Get log clicks for debugging.

        DEBUG ONLY - Returns recent map click logs.

        Args:
            utilities_service: Service dependency.

        Returns:
            List of recent click logs (200 OK).
        """
        return await utilities_service.fetch_map_clicks_debug(limit=100)
