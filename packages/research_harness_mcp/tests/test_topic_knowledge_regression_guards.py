from __future__ import annotations

import json


EXPECTED_PUBLIC_MCP_TOOL_NAMES: tuple[str, ...] = (
    "topic_list",
    "topic_show",
    "topic_init",
    "topic_state",
    "paper_search",
    "paper_ingest",
    "paper_list",
    "paper_summarize",
    "claim_extract",
    "evidence_link",
    "gap_detect",
    "baseline_identify",
    "section_draft",
    "figure_generate",
    "consistency_check",
    "orchestrator_status",
    "orchestrator_resume",
    "orchestrator_advance",
    "orchestrator_gate_check",
    "orchestrator_record_artifact",
    "paper_commit_version",
    "paper_task_intake",
    "adversarial_review",
    "advisory_check",
    "provenance_summary",
    "provenance_export",
    "zotero_sync",
    "paperindex_search",
    "paper_production_pending_decisions",
    "paper_production_decide",
    "paper_production_start",
    "paper_production_status",
    "paper_production_resume",
    "paper_production_mode",
    "paper_production_set_mode",
    "paper_production_export",
    "skill_list",
    "skill_get",
    "productization_boundary",
    "topic_knowledge_status",
    "topic_knowledge_refresh",
    "cross_topic_atlas",
    "exemplar_curate",
    "exemplar_retrieve",
    "exemplar_plan",
    "exemplar_generate",
    "exemplar_critique",
    "figure_suite_plan",
    "figure_suite_render",
    "figure_package",
    "manuscript_review",
    "manuscript_polish",
    "resource_ready_get",
    "deposit_zenodo",
)

EXPECTED_PAPER_INGEST_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "source": {"type": "string"},
        "topic_id": {"type": "integer"},
        "relevance": {"type": "string", "enum": ["high", "medium", "low"]},
        "url": {"type": "string"},
    },
    "required": ["source"],
}

EXPECTED_ZOTERO_SYNC_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "topic": {"type": "string", "description": "RH topic name"},
        "direction": {
            "type": "string",
            "enum": ["push", "pull", "both"],
            "default": "push",
        },
        "root_collection": {
            "type": "string",
            "description": "Top-level Zotero collection for RH-managed topics",
            "default": "Research Harness",
        },
        "library_id": {
            "type": "string",
            "description": "Zotero user/group library ID; defaults to env",
        },
        "library_type": {
            "type": "string",
            "enum": ["user", "group"],
            "default": "user",
        },
        "api_key": {
            "type": "string",
            "description": "Zotero API key; defaults to env",
        },
        "api_base": {
            "type": "string",
            "description": "Zotero API base URL override",
        },
        "limit": {"type": "integer", "minimum": 1},
        "skip_notes": {
            "type": "boolean",
            "description": "Do not create/update RH-generated child notes on push",
            "default": False,
        },
        "force": {
            "type": "boolean",
            "description": "Push even if the RH content hash is unchanged",
            "default": False,
        },
        "include_rh_generated": {
            "type": "boolean",
            "description": "When pulling, also import RH-generated Zotero notes",
            "default": False,
        },
        "dry_run": {
            "type": "boolean",
            "description": "Preview without mutating RH/Zotero",
            "default": True,
        },
    },
    "required": ["topic"],
}

EXPECTED_TOPIC_KNOWLEDGE_STATUS_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "topic_id": {"type": "integer", "description": "Positive RH topic id"},
    },
    "required": ["topic_id"],
}

EXPECTED_TOPIC_KNOWLEDGE_REFRESH_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "topic_id": {"type": "integer", "description": "Positive RH topic id"},
        "all": {
            "type": "boolean",
            "default": False,
            "description": "Refresh every topic in the local database",
        },
    },
}

EXPECTED_CROSS_TOPIC_ATLAS_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "topic_ids": {
            "type": "array",
            "items": {"type": "integer"},
            "minItems": 2,
            "description": "Distinct positive RH topic ids",
        },
        "query": {"type": "string"},
        "max_results": {"type": "integer", "minimum": 1, "maximum": 20},
    },
    "required": ["topic_ids"],
}


def _public_tool_by_name(name: str):
    from research_harness_mcp.tools import list_tool_definitions

    return {tool.name: tool for tool in list_tool_definitions()}[name]


def test_topic_knowledge_official_tools_are_public_without_snapshot_surface() -> None:
    from research_harness_mcp.tool_surface import PUBLIC_MCP_TOOL_NAMES
    from research_harness_mcp.tools import list_tool_definitions

    assert PUBLIC_MCP_TOOL_NAMES == EXPECTED_PUBLIC_MCP_TOOL_NAMES

    public_names = tuple(tool.name for tool in list_tool_definitions())
    assert public_names == EXPECTED_PUBLIC_MCP_TOOL_NAMES
    assert "topic_knowledge_snapshot" not in public_names
    assert "cross_topic_knowledge_atlas" not in public_names
    assert {
        "topic_knowledge_status",
        "topic_knowledge_refresh",
        "cross_topic_atlas",
    }.issubset(public_names)


def test_topic_knowledge_public_mcp_schemas_are_stable() -> None:
    assert (
        _public_tool_by_name("topic_knowledge_status").inputSchema
        == EXPECTED_TOPIC_KNOWLEDGE_STATUS_SCHEMA
    )
    assert (
        _public_tool_by_name("topic_knowledge_refresh").inputSchema
        == EXPECTED_TOPIC_KNOWLEDGE_REFRESH_SCHEMA
    )
    assert (
        _public_tool_by_name("cross_topic_atlas").inputSchema
        == EXPECTED_CROSS_TOPIC_ATLAS_SCHEMA
    )


def test_topic_knowledge_layer_does_not_change_public_paper_ingest_schema() -> None:
    paper_ingest = _public_tool_by_name("paper_ingest")

    assert paper_ingest.inputSchema == EXPECTED_PAPER_INGEST_SCHEMA
    schema_text = json.dumps(paper_ingest.inputSchema, sort_keys=True)
    assert "topic_knowledge" not in schema_text
    assert "topic_knowledge_snapshot" not in schema_text


def test_topic_knowledge_layer_does_not_change_zotero_sync_contract() -> None:
    zotero_sync = _public_tool_by_name("zotero_sync")

    assert zotero_sync.inputSchema == EXPECTED_ZOTERO_SYNC_SCHEMA
    schema_text = json.dumps(zotero_sync.inputSchema, sort_keys=True)
    assert "topic_knowledge" not in schema_text
    assert "topic_knowledge_snapshot" not in schema_text


# The zotero-panel side of this contract moved with the plugin to the
# external Zotero side-panel plugin repository (tests/test_panel_assets.py).
