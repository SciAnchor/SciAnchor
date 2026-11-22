"""research_harness.paperindex — compatibility shim.

The paperindex engine lives as a workspace sibling package under
``packages/paperindex``. New code should import ``paperindex`` directly.

Deep imports (``research_harness.paperindex.<submodule>``) keep working:
every paperindex submodule is imported eagerly and aliased in sys.modules
under this package's name, so both names resolve to the *same* module
objects and dataclass/isinstance identity is preserved. Do NOT add real
logic here.
"""

from __future__ import annotations

import importlib
import pkgutil
import sys

import paperindex as _paperindex

for _info in pkgutil.walk_packages(_paperindex.__path__, prefix="paperindex."):
    _module = importlib.import_module(_info.name)
    sys.modules[_info.name.replace("paperindex", __name__, 1)] = _module
    _child = _info.name.split(".", 1)[1]
    if "." not in _child:
        # Bind direct children so `research_harness.paperindex.cards`-style
        # attribute access works; nested attributes ride on the real package.
        globals()[_child] = _module

from paperindex import *  # noqa: E402,F401,F403
from paperindex import __all__, __version__  # noqa: E402,F401
