"""MCP surface + execution tests for the resource_ready_get public tool."""

from __future__ import annotations

from research_harness.acquisition.resource_ready import content_digest, import_spc_ready
from research_harness.storage.db import Database
from research_harness_mcp.tool_surface import PUBLIC_MCP_TOOL_NAMES
from research_harness_mcp.tools import execute_tool, list_tool_definitions

WORKFLOW_REF = "workflow:npj-gene.glioma@provisional-1"
HOST_ID = "host:example-host-wsl"


def _make_report() -> dict:
    report = {
        "schema_version": "spc.workflow-ready.v1",
        "report_id": "urn:uuid:mcp-test",
        "workflow": {
            "workflow_ref": WORKFLOW_REF,
            "manifest_revision": 1,
            "manifest_digest": "sha256:" + "0" * 64,
        },
        "contract_lifecycle": "provisional",
        "host": {
            "host_id": HOST_ID,
            "platform": "linux",
            "profile_digest": "sha256:" + "1" * 64,
        },
        "producer": {
            "spc_version": "0.1.0",
            "producer_actor": "tb",
            "produced_at": "2026-08-02T00:00:00+00:00",
        },
        "selected_modules": ["m1"],
        "environments": [],
        "datasets": [],
        "resource_status": "ready",
        "blockers": [],
    }
    report["content_digest"] = content_digest(report)
    return report


def test_resource_ready_get_is_advertised() -> None:
    assert "resource_ready_get" in PUBLIC_MCP_TOOL_NAMES
    tools = {tool.name: tool for tool in list_tool_definitions()}
    names = list(tools)
    assert "resource_ready_get" in names
    assert "include_report" not in tools["resource_ready_get"].inputSchema["properties"]


def test_resource_ready_get_execute_roundtrip(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "pool.db"
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db_path))
    monkeypatch.setenv("RESEARCH_HUB_DB_PATH", str(db_path))

    db = Database(db_path)
    db.migrate()
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO topics (name, description) VALUES ('glioma', 'glioma')"
        )
        conn.commit()
        topic_id = int(cur.lastrowid)
    finally:
        conn.close()
    import_spc_ready(db, topic_id, _make_report())

    result = execute_tool(
        "resource_ready_get",
        {"topic_id": topic_id, "workflow_ref": WORKFLOW_REF, "host_id": HOST_ID},
    )
    assert result["status"] == "success"
    assert result["output"]["found"] is True
    assert result["output"]["resource_status"] == "ready"

    missing = execute_tool(
        "resource_ready_get",
        {"topic_id": topic_id, "workflow_ref": WORKFLOW_REF, "host_id": "host:nope"},
    )
    assert missing["output"]["found"] is False


def test_resource_ready_get_public_output_omits_import_path(
    tmp_path, monkeypatch
) -> None:
    db_path = tmp_path / "pool.db"
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db_path))
    monkeypatch.setenv("RESEARCH_HUB_DB_PATH", str(db_path))

    db = Database(db_path)
    db.migrate()
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO topics (name, description) VALUES ('safe-view', 'safe-view')"
        )
        conn.commit()
        topic_id = int(cur.lastrowid)
    finally:
        conn.close()
    import_spc_ready(
        db,
        topic_id,
        _make_report(),
        source_path="/Users/operator/private/workflow_ready.json",
    )

    result = execute_tool(
        "resource_ready_get",
        {
            "topic_id": topic_id,
            "workflow_ref": WORKFLOW_REF,
            "host_id": HOST_ID,
            "include_report": True,
        },
    )

    assert result["status"] == "success"
    assert "source_path" not in result["output"]
    assert "report" not in result["output"]
    assert "/Users/operator" not in repr(result)
