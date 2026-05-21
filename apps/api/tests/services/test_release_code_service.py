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
