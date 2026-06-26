"""Unit tests for MapContentService.

These are pure unit tests: a mocked ImageStorageService and a mocked
MapContentRepository are injected directly into MapContentService. No app import
(the controller DI graph is wired in plan 15-04). The real-DB repository behavior
is covered in tests/repository/maps/test_map_content_repository.py.
"""

import pytest
from litestar.status_codes import HTTP_422_UNPROCESSABLE_ENTITY

from repository.map_content_repository import MapContentRepository
from services.image_storage_service import ImageStorageService
from services.map_content_service import MapContentService, _strip_key
from utilities.errors import CustomHTTPException

pytestmark = [pytest.mark.domain_maps]


@pytest.fixture
def service(mock_pool, mock_state, mocker):
    """MapContentService with mocked repo + mocked image storage service."""
    repo = mocker.AsyncMock(spec=MapContentRepository)
    image_svc = mocker.Mock(spec=ImageStorageService)
    svc = MapContentService(mock_pool, mock_state, repo, image_svc)
    return svc, repo, image_svc


class TestStripKey:
    """_strip_key must byte-match get_map_banner's derivation."""

    def test_strip_key_matches_get_map_banner(self):
        """_strip_key strips punctuation/accents and lowercases, like get_map_banner."""
        from genjishimada_sdk.maps import get_map_banner

        for name in ["King's Row", "Château Guillard", "Route 66", "Hanamura"]:
            stripped = _strip_key(name)
            assert get_map_banner(name) == f"https://cdn.genji.pk/assets/map_banners/{stripped}.png"


class TestCreateMapEmptyName:
    """REQ-05: empty/blank name -> 422."""

    async def test_empty_name_raises_422(self, service):
        svc, repo, image_svc = service
        with pytest.raises(CustomHTTPException) as exc:
            await svc.create_map("", b"banner", "image/png")
        assert exc.value.status_code == HTTP_422_UNPROCESSABLE_ENTITY
        # Guard fires before any insert/upload.
        repo.insert_map_name.assert_not_called()
        image_svc.upload_map_banner.assert_not_called()

    async def test_blank_name_raises_422(self, service):
        svc, repo, image_svc = service
        with pytest.raises(CustomHTTPException) as exc:
            await svc.create_map("   ", b"banner", "image/png")
        assert exc.value.status_code == HTTP_422_UNPROCESSABLE_ENTITY
        repo.insert_map_name.assert_not_called()
        image_svc.upload_map_banner.assert_not_called()


class TestCreateMapCollision:
    """REQ-06/D-07: a new name colliding on the stripped key with a DIFFERENT existing map -> 422."""

    async def test_punctuation_collision_raises_422(self, service):
        svc, repo, image_svc = service
        repo.fetch_all_map_names.return_value = ["King's Row", "Hanamura"]

        with pytest.raises(CustomHTTPException) as exc:
            await svc.create_map("Kings Row", b"banner", "image/png")

        assert exc.value.status_code == HTTP_422_UNPROCESSABLE_ENTITY
        # Error names the colliding existing map.
        assert "King's Row" in exc.value.detail
        repo.insert_map_name.assert_not_called()
        image_svc.upload_map_banner.assert_not_called()

    async def test_accent_collision_raises_422(self, service):
        svc, repo, image_svc = service
        repo.fetch_all_map_names.return_value = ["Château Guillard", "Hanamura"]

        with pytest.raises(CustomHTTPException) as exc:
            await svc.create_map("Chateau Guillard", b"banner", "image/png")

        assert exc.value.status_code == HTTP_422_UNPROCESSABLE_ENTITY
        assert "Château Guillard" in exc.value.detail
        repo.insert_map_name.assert_not_called()

    async def test_same_name_is_not_a_collision(self, service):
        """An exact-match existing name is idempotent insert, NOT a 422 collision."""
        svc, repo, image_svc = service
        repo.fetch_all_map_names.return_value = ["Hanamura"]
        repo.insert_map_name.return_value = {"name": "Hanamura", "inserted": False}

        result = await svc.create_map("Hanamura", b"banner", "image/png")

        assert result == {"name": "Hanamura", "inserted": False}
        image_svc.upload_map_banner.assert_called_once()


class TestCreateMapHappyPath:
    """Happy path: upload (mocked) banner + insert, returning inserted=True."""

    async def test_create_uploads_and_inserts(self, service):
        svc, repo, image_svc = service
        repo.fetch_all_map_names.return_value = ["Hanamura", "Busan"]
        repo.insert_map_name.return_value = {"name": "Brand New Map", "inserted": True}
        image_svc.upload_map_banner.return_value = "https://cdn.genji.pk/assets/map_banners/brandnewmap.png"

        result = await svc.create_map("Brand New Map", b"banner-bytes", "image/png")

        assert result == {"name": "Brand New Map", "inserted": True}
        image_svc.upload_map_banner.assert_called_once_with(b"banner-bytes", "image/png", "Brand New Map")
        repo.insert_map_name.assert_called_once_with("Brand New Map")

    async def test_upload_precedes_insert(self, service, mocker):
        """Ordering: the banner upload happens BEFORE the DB insert (Pitfall 1)."""
        svc, repo, image_svc = service
        repo.fetch_all_map_names.return_value = []
        repo.insert_map_name.return_value = {"name": "Order Map", "inserted": True}

        manager = mocker.Mock()
        manager.attach_mock(image_svc.upload_map_banner, "upload")
        manager.attach_mock(repo.insert_map_name, "insert")

        await svc.create_map("Order Map", b"banner", "image/png")

        call_order = [c[0] for c in manager.mock_calls if c[0] in ("upload", "insert")]
        assert call_order == ["upload", "insert"]


class TestValidateMapName:
    """REQ-02: validate_map_name accepts known, 422s unknown with a difflib suggestion."""

    async def test_known_name_returned(self, service):
        svc, repo, image_svc = service
        repo.fetch_all_map_names.return_value = ["Hanamura", "Busan", "Ilios"]

        result = await svc.validate_map_name("Hanamura")

        assert result == "Hanamura"

    async def test_unknown_name_raises_422_with_suggestion(self, service):
        svc, repo, image_svc = service
        repo.fetch_all_map_names.return_value = ["Hanamura", "Busan", "Ilios"]

        with pytest.raises(CustomHTTPException) as exc:
            await svc.validate_map_name("Hanmura")

        assert exc.value.status_code == HTTP_422_UNPROCESSABLE_ENTITY
        assert "Did you mean" in exc.value.detail
        assert "Hanamura" in exc.value.detail

    async def test_unknown_name_no_close_match_still_422(self, service):
        svc, repo, image_svc = service
        repo.fetch_all_map_names.return_value = ["Hanamura", "Busan"]

        with pytest.raises(CustomHTTPException) as exc:
            await svc.validate_map_name("zzzzzzzz")

        assert exc.value.status_code == HTTP_422_UNPROCESSABLE_ENTITY


class TestProviderExists:
    """provide_map_content_service must exist (declares image_svc dep) for plan 15-04."""

    def test_provider_importable(self):
        from services.map_content_service import provide_map_content_service

        assert callable(provide_map_content_service)
