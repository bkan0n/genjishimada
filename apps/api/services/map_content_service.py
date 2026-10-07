"""Map content service: runtime map-name validation + dynamic map creation.

This is the service-layer runtime gate that replaced the removed `OverwatchMap`
Literal (phase 15). `create_map` adds a NEW map name (empty-name guard REQ-05,
stripped-key collision guard REQ-06/D-07, banner upload REQ-07, idempotent insert);
`validate_map_name` is the consumer-side "did you mean" validator (REQ-02) for paths
that accept a free-form name (e.g. submission) — NOT used by `create_map`.
"""

from __future__ import annotations

import asyncio
import difflib
import re
from collections.abc import Callable
from typing import TYPE_CHECKING

from genjishimada_sdk.helpers import sanitize_string
from litestar.datastructures import State
from litestar.status_codes import HTTP_404_NOT_FOUND, HTTP_409_CONFLICT, HTTP_422_UNPROCESSABLE_ENTITY

from repository.map_content_repository import MapContentRepository
from services.image_storage_service import ImageStorageService
from utilities.errors import CustomHTTPException
from utilities.transactions import transactional

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

    @transactional
    async def create_map(self, name: str, banner: bytes, content_type: str) -> dict:
        """Create a canonical name or replace its banner while reserving legacy keys."""
        self._validate_name(name)
        await self._map_content_repo.lock_names(exclusive=True)
        existing = await self._map_content_repo.fetch_all_map_names()
        owners = await self._map_content_repo.fetch_name_owners()
        if name in owners and owners[name] != name:
            raise CustomHTTPException(
                detail=f"'{name}' is a previous name of '{owners[name]}'. Use the current canonical name.",
                status_code=HTTP_409_CONFLICT,
            )
        # Preserve POST's existing 422 collision contract for current names.
        self._check_collisions(name, name, {other: other for other in existing}, HTTP_422_UNPROCESSABLE_ENTITY)
        self._check_collisions(name, name, owners, HTTP_409_CONFLICT)
        await self._storage_write(self._image_svc.upload_map_banner, banner, content_type, name)
        return await self._map_content_repo.insert_map_name(name)

    @transactional
    async def rename_map(self, old_name: str, name: str) -> dict:
        """Rename an exact current name while preserving references and artwork."""
        self._validate_name(old_name)
        self._validate_name(name)
        await self._map_content_repo.lock_names(exclusive=True)
        owners = await self._map_content_repo.fetch_name_owners()
        if owners.get(old_name) != old_name:
            raise CustomHTTPException(
                detail=f"Current map '{old_name}' was not found. Refresh and select the existing map.",
                status_code=HTTP_404_NOT_FOUND,
            )
        if old_name == name:
            return {"old_name": old_name, "name": name, "renamed": False}
        self._check_collisions(name, old_name, owners, HTTP_409_CONFLICT)
        own_names = {spelling for spelling, owner in owners.items() if owner == old_name}
        await self._storage_write(self._image_svc.preserve_map_artwork, old_name, name, own_names)
        await self._map_content_repo.rename_map_name(old_name, name)
        return {"old_name": old_name, "name": name, "renamed": True}

    @staticmethod
    async def _storage_write(operation: Callable[..., object], *args: object) -> None:
        """Keep the ownership transaction alive until uncancellable S3 I/O finishes."""
        task = asyncio.create_task(asyncio.to_thread(operation, *args))
        cancelled = False
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                if cancelled:
                    raise asyncio.CancelledError from None
                raise
        if cancelled:
            raise asyncio.CancelledError
        task.result()

    @staticmethod
    def _validate_name(name: str) -> None:
        if not name.strip() or not _strip_key(name):
            raise CustomHTTPException(
                detail="Map name must contain at least one ASCII letter or digit for its artwork key.",
                status_code=HTTP_422_UNPROCESSABLE_ENTITY,
            )

    @staticmethod
    def _check_collisions(name: str, owner: str, owners: dict[str, str], status_code: int) -> None:
        banner_key, mastery_key = _strip_key(name), sanitize_string(name)
        for spelling, existing_owner in owners.items():
            if existing_owner == owner:
                continue
            if spelling == name or _strip_key(spelling) == banner_key or sanitize_string(spelling) == mastery_key:
                raise CustomHTTPException(
                    detail=f"'{name}' collides with reserved name or artwork for '{existing_owner}' ('{spelling}').",
                    status_code=status_code,
                )

    @transactional
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
        await self._map_content_repo.lock_names()
        name = await self._map_content_repo.resolve_name(name)
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
