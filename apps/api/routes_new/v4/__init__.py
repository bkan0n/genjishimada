"""V4 API routes."""

import importlib
import inspect
import os
import pathlib

from litestar import Controller, Router

MODULE_PATH = pathlib.Path(__file__).parent
MODULE_NAME = __name__

route_handlers = []

for item in os.listdir(MODULE_PATH):
    item_path = MODULE_PATH / item

    if item_path.is_file() and item.endswith(".py") and item != "__init__.py":
        mod_name = f"{MODULE_NAME}.{item[:-3]}"
        mod = importlib.import_module(mod_name)

        for _, obj in inspect.getmembers(mod):
            if isinstance(obj, Router) or (
                inspect.isclass(obj) and issubclass(obj, Controller) and obj.__module__ == mod.__name__
            ):
                route_handlers.append(obj)
