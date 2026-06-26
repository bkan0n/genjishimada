"""Integration tests for the dynamic map-content controller (phase 15).

Covers the HTTP surface added in plan 15-04:
  REQ-03  POST /api/v3/content/maps  — mixed-multipart {name, banner} -> 201
  REQ-04  replace-banner — re-posting an existing name -> 201 inserted:false,
          banner re-uploaded to the same stripped key (overwrite semantics)
  REQ-15  appears-everywhere — a newly-created name shows on the full-list read
          endpoint AND is accepted by a core.maps write (FK resolves) with no redeploy

The banner upload is stubbed at ``ImageStorageService.upload_map_banner`` so the
tests need no MinIO/S3; the stub also records its calls so replace-banner can
assert the stripped-key overwrite.
"""

from __future__ import annotations

import pytest

import services.image_storage_service as image_storage_module

pytestmark = [
    pytest.mark.integration,
    pytest.mark.domain_content,
]

MAPS_URL = "/api/v3/content/maps"
MAP_NAMES_URL = "/api/v3/utilities/map-names"

# A 1x1 PNG (smallest valid-ish payload; the service never parses the bytes).
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture
def banner_spy(monkeypatch):
    """Stub ImageStorageService.upload_map_banner and record its calls.

    Returns the list of ``(content, content_type, map_name)`` tuples it was
    called with, so replace-banner can assert the same stripped key is reused.
    """
    calls: list[tuple[bytes, str, str]] = []

    def _fake_init(self) -> None:
        # Skip the real boto3 client construction (no valid S3 endpoint in tests).
        self.client = None

    def _fake_upload(self, content: bytes, content_type: str, map_name: str) -> str:
        calls.append((content, content_type, map_name))
        import re

        stripped = re.sub(r"[^a-zA-Z0-9]", "", map_name).lower().strip().replace(" ", "")
        return f"https://cdn.test/assets/map_banners/{stripped}.png"

    monkeypatch.setattr(
        image_storage_module.ImageStorageService,
        "__init__",
        _fake_init,
    )
    monkeypatch.setattr(
        image_storage_module.ImageStorageService,
        "upload_map_banner",
        _fake_upload,
    )
    return calls


def _strip_key(name: str) -> str:
    import re

    return re.sub(r"[^a-zA-Z0-9]", "", name).lower().strip().replace(" ", "")


class TestCreateMap:
    """POST /api/v3/content/maps"""

    async def test_create_map(self, test_client, banner_spy):
        """REQ-03: multipart name+banner -> 201 with inserted:true."""
        name = "Brand New Map Create"
        response = await test_client.post(
            MAPS_URL,
            data={"name": name},
            files={"banner": ("banner.png", _PNG_BYTES, "image/png")},
        )

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["name"] == name
        assert body["inserted"] is True
        # Banner was uploaded exactly once, at this map's stripped key.
        assert len(banner_spy) == 1
        assert banner_spy[0][2] == name

    async def test_create_map_empty_name_returns_422(self, test_client, banner_spy):
        """Empty name is rejected at the HTTP boundary (REQ-05, service guard)."""
        response = await test_client.post(
            MAPS_URL,
            data={"name": "   "},
            files={"banner": ("banner.png", _PNG_BYTES, "image/png")},
        )

        assert response.status_code == 422, response.text

    async def test_requires_auth(self, unauthenticated_client):
        """Create without auth returns 401 (the write is behind the scope guard)."""
        response = await unauthenticated_client.post(
            MAPS_URL,
            data={"name": "No Auth Map"},
            files={"banner": ("banner.png", _PNG_BYTES, "image/png")},
        )

        assert response.status_code == 401


class TestReplaceBanner:
    """POST /api/v3/content/maps (re-post == replace-banner)"""

    async def test_replace_banner(self, test_client, banner_spy):
        """REQ-04: re-posting the same name -> 201 inserted:false, same key re-uploaded."""
        name = "Brand New Map Replace"
        first = await test_client.post(
            MAPS_URL,
            data={"name": name},
            files={"banner": ("a.png", _PNG_BYTES, "image/png")},
        )
        assert first.status_code == 201, first.text
        assert first.json()["inserted"] is True

        new_bytes = _PNG_BYTES + b"-v2"
        second = await test_client.post(
            MAPS_URL,
            data={"name": name},
            files={"banner": ("b.png", new_bytes, "image/png")},
        )
        assert second.status_code == 201, second.text
        body = second.json()
        assert body["name"] == name
        # ON CONFLICT DO NOTHING: the row already existed, so nothing was inserted.
        assert body["inserted"] is False

        # Both uploads targeted the SAME stripped key (overwrite semantics).
        assert len(banner_spy) == 2
        assert banner_spy[0][2] == name
        assert banner_spy[1][2] == name
        assert _strip_key(banner_spy[0][2]) == _strip_key(banner_spy[1][2])
        # The second upload carried the new bytes (the banner was actually replaced).
        assert banner_spy[1][0] == new_bytes


class TestAppearsEverywhere:
    """REQ-15: a newly-added map appears on read surfaces with no redeploy."""

    async def test_appears_everywhere(self, test_client, banner_spy, create_test_map):
        """Created name shows in the full-list endpoint AND is accepted by a core.maps write."""
        name = "Brand New Appears Map"
        created = await test_client.post(
            MAPS_URL,
            data={"name": name},
            files={"banner": ("banner.png", _PNG_BYTES, "image/png")},
        )
        assert created.status_code == 201, created.text

        # (1) Read surface: the full-list endpoint includes the new name immediately.
        listed = await test_client.get(MAP_NAMES_URL)
        assert listed.status_code == 200, listed.text
        assert name in listed.json()

        # (2) Submission/read path: a core.maps write with the new map_name succeeds.
        # The maps_map_name_names_fk FK (migration 0032) only resolves because the
        # name now exists in maps.names — proving the new map is usable with no redeploy.
        map_id = await create_test_map(map_name=name)
        assert isinstance(map_id, int)
