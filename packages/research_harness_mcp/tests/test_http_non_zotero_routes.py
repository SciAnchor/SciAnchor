"""Shape tests for non-Zotero HTTP route composition helpers."""

from __future__ import annotations


def test_non_zotero_route_registry_exports_ordered_phases() -> None:
    from research_harness_mcp import http_non_zotero_routes

    assert callable(http_non_zotero_routes.register_routes_before_zotero)
    assert callable(http_non_zotero_routes.register_routes_after_zotero)
