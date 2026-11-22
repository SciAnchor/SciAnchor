"""Compatibility shim for execution image generation clients.

The canonical implementation lives under `research_harness._workflow`.
"""

from __future__ import annotations

import sys

from research_harness._workflow.execution import fal_image_client as _canonical

_PUBLIC_MODULE_NAME = __name__

globals().update(_canonical.__dict__)
sys.modules[_PUBLIC_MODULE_NAME] = _canonical
