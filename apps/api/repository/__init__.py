"""Repository layer for data access."""

from repository.maps_repository import MapsRepository, provide_maps_repository

__all__ = [
    "MapsRepository",
    "provide_maps_repository",
]
