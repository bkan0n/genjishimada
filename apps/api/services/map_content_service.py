"""Map content service: runtime map-name validation + dynamic map creation.

This is the service-layer runtime gate that replaced the removed `OverwatchMap`
Literal (phase 15). `create_map` adds a NEW map name (empty-name guard REQ-05,
stripped-key collision guard REQ-06/D-07, banner upload REQ-07, idempotent insert);
`validate_map_name` is the consumer-side "did you mean" validator (REQ-02) for paths
that accept a free-form name (e.g. submission) — NOT used by `create_map`.
"""

from __future__ import annotations

import difflib
import re
from typing import TYPE_CHECKING

from litestar.datastructures import State
from litestar.status_codes import HTTP_422_UNPROCESSABLE_ENTITY

from repository.map_content_repository import MapContentRepository
from services.image_storage_service import ImageStorageService
from utilities.errors import CustomHTTPException

from .base import BaseService

if TYPE_CHECKING:
    from asyncpg import Pool


def _strip_key(name: str) -> str:
    """Reduce a map name to its banner key, byte-matching get_map_banner().

    Mirrors ``libs/sdk/.../maps.py::get_map_banner``:
    ``re.sub(r"[^a-zA-Z0-9]", "", name).lower().strip().replace(" ", "")``.
    Used both for the collision guard and (indirectly) for the banner object key.

    Args:
        name: The map name.

    Returns:
        str: The stripped key (lowercase alphanumerics only).
    """
    return re.sub(r"[^a-zA-Z0-9]", "", name).lower().strip().replace(" ", "")


class MapContentService(BaseService):
    """Service for dynamic Overwatch map-name validation and creation."""

    def __init__(
        self,
        pool: Pool,
        state: State,
        map_content_repo: MapContentRepository,
        image_svc: ImageStorageService,
    ) -> None:
        """Initialize the map content service.

        Args:
            pool: AsyncPG connection pool.
            state: Application state.
            map_content_repo: Repository for `maps.names` access.
            image_svc: Image storage service (for banner uploads).
        """
        super().__init__(pool, state)
        self._map_content_repo = map_content_repo
        self._image_svc = image_svc

    async def create_map(self, name: str, banner: bytes, content_type: str) -> dict:
        """Add a new Overwatch map: guard, upload its banner, insert idempotently.

        Ordering matters (RESEARCH Pitfall 1 — transaction-abort): all fallible
        NON-DB work (empty guard, collision guard, S3 upload) runs BEFORE the DB
        insert, and the `ON CONFLICT` insert is the only fallible DB statement.
        Because the insert is a single statement it needs no explicit transaction.

        Args:
            name: The new map name.
            banner: The banner image bytes.
            content_type: The banner content type.

        Returns:
            dict: `{"name": name, "inserted": bool}` from the idempotent insert.

        Raises:
            CustomHTTPException: 422 if the name is empty/blank (REQ-05) or its
                stripped key collides with a DIFFERENT existing map (REQ-06/D-07).
        """
        # (1) Empty/blank guard (REQ-05) — before any DB read or upload.
        if not name.strip():
            raise CustomHTTPException(
                detail="Map name must not be empty.",
                status_code=HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # (2) Stripped-key collision guard (REQ-06/D-07). A DIFFERENT existing name
        # whose stripped key matches would have its banner overwritten by this one.
        existing = await self._map_content_repo.fetch_all_map_names()
        target = _strip_key(name)
        for other in existing:
            if other != name and _strip_key(other) == target:
                raise CustomHTTPException(
                    detail=(
                        f"'{name}' collides with existing map '{other}' "
                        f"(both reduce to the banner key '{target}'). "
                        "Choose a name whose stripped key is unique."
                    ),
                    status_code=HTTP_422_UNPROCESSABLE_ENTITY,
                )

        # (3) Upload the banner (REQ-07) — still BEFORE the DB insert.
        self._image_svc.upload_map_banner(banner, content_type, name)

        # (4) Idempotent insert — the only fallible DB statement, single-statement
        # so no explicit transaction needed.
        return await self._map_content_repo.insert_map_name(name)

    async def validate_map_name(self, name: str) -> str:
        """Validate a map name against `maps.names`, suggesting near matches (REQ-02).

        Consumer-side validator (e.g. for the submission path) — NOT called by
        `create_map`. Replaces the removed Literal's terse error with a friendly
        difflib "did you mean".

        Args:
            name: The map name to validate.

        Returns:
            str: The name, if known.

        Raises:
            CustomHTTPException: 422 if the name is unknown, with a difflib
                "Did you mean: ..." hint when close matches exist.
        """
        known = await self._map_content_repo.fetch_all_map_names()
        if name in known:
            return name
        suggestions = difflib.get_close_matches(name, known, n=3, cutoff=0.6)
        hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
        raise CustomHTTPException(
            detail=f"'{name}' is not a known Overwatch map.{hint}",
            status_code=HTTP_422_UNPROCESSABLE_ENTITY,
        )


async def provide_map_content_service(
    state: State,
    map_content_repo: MapContentRepository,
    image_svc: ImageStorageService,
) -> MapContentService:
    """Litestar DI provider for MapContentService.

    Declares `image_svc: ImageStorageService` as a dependency resolved by
    `provide_image_storage_service`; the actual `Provide(...)` wiring for both
    `image_svc` and `map_content_repo` is added at the controller level in plan
    15-04. This provider does NOT construct the ImageStorageService itself.
    """
    return MapContentService(state.db_pool, state, map_content_repo, image_svc)
