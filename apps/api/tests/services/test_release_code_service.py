"""Unit tests for MapsService.release_code."""

import pytest

from services.exceptions.maps import (
    MapNotArchivedError,
    MapNotFoundError,
    UnresolvedChangeRequestsError,
)


class TestReleaseCodeExceptions:
    """Verify new domain exceptions exist and carry correct context."""

    def test_map_not_archived_error(self):
        """MapNotArchivedError stores code in context."""
        err = MapNotArchivedError("ABCDE")
        assert "ABCDE" in str(err)
        assert err.context["code"] == "ABCDE"

    def test_unresolved_change_requests_error(self):
        """UnresolvedChangeRequestsError stores code and count."""
        err = UnresolvedChangeRequestsError("ABCDE", count=3)
        assert "ABCDE" in str(err)
        assert err.context["code"] == "ABCDE"
        assert err.context["count"] == 3


from services.maps_service import MapsService


class TestReleaseCodeService:
    """MapsService.release_code unit tests."""

    async def test_map_not_found_raises(self, mock_pool, mock_state, mock_maps_repo):
        """MapNotFoundError raised when map doesn't exist."""
        service = MapsService(mock_pool, mock_state, mock_maps_repo)
        mock_maps_repo.lookup_map_id.return_value = None

        with pytest.raises(MapNotFoundError):
            await service.release_code("NOPE1")

    async def test_map_not_archived_raises(self, mock_pool, mock_state, mock_maps_repo):
        """MapNotArchivedError raised when map is not archived."""
        service = MapsService(mock_pool, mock_state, mock_maps_repo)
        mock_maps_repo.lookup_map_id.return_value = 42
        mock_maps_repo.is_map_archived.return_value = False

        with pytest.raises(MapNotArchivedError):
            await service.release_code("ACTIV")

    async def test_unresolved_crs_raises(self, mock_pool, mock_state, mock_maps_repo):
        """UnresolvedChangeRequestsError raised when open CRs exist."""
        service = MapsService(mock_pool, mock_state, mock_maps_repo)
        mock_maps_repo.lookup_map_id.return_value = 42
        mock_maps_repo.is_map_archived.return_value = True
        mock_maps_repo.has_unresolved_change_requests.return_value = True

        with pytest.raises(UnresolvedChangeRequestsError):
            await service.release_code("HASCR")

    async def test_happy_path_calls_release(self, mock_pool, mock_state, mock_maps_repo):
        """Successful release calls repository.release_code in transaction."""
        service = MapsService(mock_pool, mock_state, mock_maps_repo)
        mock_maps_repo.lookup_map_id.return_value = 42
        mock_maps_repo.is_map_archived.return_value = True
        mock_maps_repo.has_unresolved_change_requests.return_value = False

        await service.release_code("REL01")

        mock_maps_repo.release_code.assert_called_once()
