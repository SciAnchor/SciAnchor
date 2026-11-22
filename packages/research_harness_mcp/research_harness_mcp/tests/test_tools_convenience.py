"""Focused tests for MCP convenience tool definitions."""

from __future__ import annotations


def test_convenience_tool_set_preserves_membership() -> None:
    from research_harness_mcp.tools_convenience import _CONVENIENCE_TOOLS

    assert set(_CONVENIENCE_TOOLS) == {
        "topic_list",
        "topic_show",
        "paper_list",
        "task_list",
        "provenance_summary",
        "provenance_export",
        "provenance_token_report",
        "paper_dismiss",
        "decision_log_record",
        "decision_log_list",
        "search_query_list",
        "search_query_add",
        "advisory_check",
        "topic_knowledge_status",
        "topic_knowledge_refresh",
        "cross_topic_atlas",
        "advisory_list",
        "advisory_acknowledge",
        "zotero_sync",
        "paper_purge",
        "venue_refresh",
        "domain_list",
        "domain_init",
        "domain_show",
        "resource_ready_get",
        "deposit_zenodo",
    }
    for name, tool in _CONVENIENCE_TOOLS.items():
        assert tool.name == name


def test_zotero_sync_definition_preserves_release_boundary_schema() -> None:
    from research_harness_mcp.tools_convenience import _CONVENIENCE_TOOLS

    schema = _CONVENIENCE_TOOLS["zotero_sync"].inputSchema

    assert schema["required"] == ["topic"]
    assert schema["properties"]["direction"]["enum"] == ["push", "pull", "both"]
    assert schema["properties"]["direction"]["default"] == "push"
    assert schema["properties"]["dry_run"]["default"] is True
