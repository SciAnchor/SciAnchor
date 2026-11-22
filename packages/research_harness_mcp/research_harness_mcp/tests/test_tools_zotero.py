"""Focused tests for MCP Zotero tool helpers."""

from __future__ import annotations


def test_zotero_stable_dry_run_boundary_messages_are_preserved() -> None:
    from research_harness_mcp.tools_zotero import (
        _zotero_stable_dry_run_deferred_error,
    )

    assert _zotero_stable_dry_run_deferred_error(direction="push", dry_run=True) == ""
    assert _zotero_stable_dry_run_deferred_error(
        direction="push",
        dry_run=False,
    ) == (
        "real Zotero sync/apply is deferred; stable Zotero routing only "
        "supports direction=push with dry_run=true"
    )
    assert _zotero_stable_dry_run_deferred_error(
        direction="pull",
        dry_run=True,
    ) == (
        "stable Zotero dry-run only supports direction=push; "
        "pull dry-run requires Zotero read access and remains deferred"
    )


def test_execute_zotero_sync_validation_short_circuits_before_client() -> None:
    from research_harness_mcp.tools_zotero import _execute_zotero_sync

    db = object()

    assert _execute_zotero_sync(db, {"direction": "push", "dry_run": True}) == {
        "error": "topic is required"
    }
    assert _execute_zotero_sync(
        db,
        {"topic": "demo-topic", "direction": "sideways", "dry_run": True},
    ) == {"error": "direction must be one of: push, pull, both"}
    assert _execute_zotero_sync(
        db,
        {"topic": "demo-topic", "direction": "both", "dry_run": True},
    ) == {
        "error": (
            "stable Zotero dry-run only supports direction=push; "
            "both dry-run requires Zotero read access and remains deferred"
        )
    }
