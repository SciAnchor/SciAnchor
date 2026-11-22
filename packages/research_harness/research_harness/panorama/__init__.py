"""Domain Panorama KB: direction-level living knowledge base (L1 facts + L2 views).

L1 is a self-contained SQLite store (papers remain sourced from the RH pool DB
and are referenced by id/external ids, never duplicated as truth). L2 views are
regenerable markdown, never hand-edited.
"""

from .store import PanoramaStore, default_panorama_root

__all__ = ["PanoramaStore", "default_panorama_root"]
