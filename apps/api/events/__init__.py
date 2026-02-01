"""Litestar event listeners registry."""

from __future__ import annotations

import importlib
from pathlib import Path
from pkgutil import iter_modules

from litestar.events.listener import EventListener

_listeners: list[EventListener] = []

_pkg_path = Path(__file__).resolve().parent
for module_info in iter_modules([str(_pkg_path)]):
    if module_info.name.startswith("_") or module_info.name == "__init__":
        continue
    module = importlib.import_module(f"{__name__}.{module_info.name}")
    for obj in vars(module).values():
        if isinstance(obj, EventListener):
            _listeners.append(obj)

listeners = tuple(_listeners)

__all__ = ["listeners"]
