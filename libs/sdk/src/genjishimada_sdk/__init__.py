# src/genjishimada_sdk/__init__.py
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

from . import (
    auth,
    change_requests,
    completions,
    difficulties,
    internal,
    logs,
    lootbox,
    maps,
    newsfeed,
    notifications,
    rank_card,
    users,
    xp,
)

__all__ = [
    "auth",
    "change_requests",
    "completions",
    "difficulties",
    "internal",
    "logs",
    "lootbox",
    "maps",
    "newsfeed",
    "notifications",
    "rank_card",
    "users",
    "xp",
]

try:
    __version__ = _pkg_version("genjipk-sdk")
except PackageNotFoundError:
    __version__ = "0.0.0"
