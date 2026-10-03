from __future__ import annotations

import pkgutil

# Registration occurs only after every extension's setup hook has completed.
EXTENSIONS = sorted(module.name for module in pkgutil.iter_modules(__path__, f"{__package__}."))
