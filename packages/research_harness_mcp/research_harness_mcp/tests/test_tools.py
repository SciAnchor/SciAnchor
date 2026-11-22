"""Tests for MCP tool definitions and execution."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_harness.storage.db import Database


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    db_path = tmp_path / "test.db"
    database = Database(db_path)
    database.migrate()
    return database


@pytest.fixture()
def _env_db(db: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(db.db_path))
    monkeypatch.setenv("RESEARCH_HUB_DB_PATH", str(db.db_path))
    monkeypatch.setenv("RESEARCH_HARNESS_BACKEND", "local")
    monkeypatch.setenv("RESEARCH_HUB_BACKEND", "local")


# ---------------------------------------------------------------------------
# Tool listing
# ---------------------------------------------------------------------------


def test_list_tool_definitions() -> None:
    from research_harness_mcp.tools import list_tool_definitions
    from research_harness_mcp.tool_surface import PUBLIC_MCP_TOOL_NAMES

    tools = list_tool_definitions()
    names = {t.name for t in tools}

    assert len(tools) == len(PUBLIC_MCP_TOOL_NAMES)
    assert names == set(PUBLIC_MCP_TOOL_NAMES)

    # Primitives
    assert "paper_search" in names
    assert "claim_extract" in names
    assert "gap_detect" in names
    assert "figure_generate" in names

    # Convenience
    assert "topic_list" in names
    assert "provenance_summary" in names
    assert "provenance_export" in names
    assert "advisory_check" in names
    assert "zotero_sync" in names

    # Paperindex
    assert "paperindex_search" in names

    # Internal primitives remain executable for compatibility, but they should
    # no longer be advertised to agents through tools/list.
    assert "code_generate" not in names

    # LG10 public-productization boundary preview.
    assert "productization_boundary" in names


def test_figure_generate_public_mcp_schema_exposes_illustration_route() -> None:
    from research_harness_mcp.tools import list_tool_definitions

    tools = {tool.name: tool for tool in list_tool_definitions()}
    schema = tools["figure_generate"].inputSchema
    properties = schema["properties"]

    assert schema["required"] == ["topic_id", "items", "output_dir"]
    assert "illustration" in properties["model"]["description"]
    assert "illustration-fake" in properties["model"]["description"]
    assert properties["evidence_boundary"]["enum"] == [
        "conceptual",
        "planned_protocol",
        "evidence_backed",
        "mixed",
    ]
    assert properties["illustration_fake"]["default"] is False
    assert properties["figure_contract"]["type"] == "object"


def test_paper_task_intake_public_mcp_schema_exposes_durable_entrypoint() -> None:
    from research_harness_mcp.tools import list_tool_definitions
    from research_harness_mcp.tool_surface import PUBLIC_MCP_TOOL_CONTRACTS

    tools = {tool.name: tool for tool in list_tool_definitions()}
    schema = tools["paper_task_intake"].inputSchema
    description = PUBLIC_MCP_TOOL_CONTRACTS["paper_task_intake"].description

    assert schema["required"] == ["task", "target_venue"]
    assert schema["properties"]["mode"]["enum"] == [
        "explore",
        "standard",
        "strict",
        "demo",
    ]
    assert "When to use" in description
    assert "PAPER_PLAN" in description
    assert "RH_STATE" in description
    assert "durable" in description


def test_public_tool_contracts_are_agent_facing() -> None:
    from research_harness_mcp.tool_surface import (
        PUBLIC_MCP_TOOL_CONTRACTS,
        PUBLIC_MCP_TOOL_NAMES,
    )

    assert set(PUBLIC_MCP_TOOL_CONTRACTS) == set(PUBLIC_MCP_TOOL_NAMES)
    for name in PUBLIC_MCP_TOOL_NAMES:
        contract = PUBLIC_MCP_TOOL_CONTRACTS[name]
        assert len(contract.description) >= 80
        assert "When to use" in contract.description
        assert "When not to use" in contract.description
        assert contract.output_schema.get("type") == "object"
        assert len(contract.error_examples) >= 2
        for example in contract.error_examples:
            assert example.get("error")
            assert example.get("message")
            assert example.get("suggestion")


def test_tool_definitions_have_schemas() -> None:
    from research_harness_mcp.tools import list_tool_definitions
    from research_harness_mcp.tool_surface import PUBLIC_MCP_TOOL_CONTRACTS

    for tool in list_tool_definitions():
        assert tool.name
        assert tool.description
        assert tool.inputSchema is not None
        assert tool.description == PUBLIC_MCP_TOOL_CONTRACTS[tool.name].description


# ---------------------------------------------------------------------------
# HarnessResponse envelope — all tool results now have these keys
# ---------------------------------------------------------------------------

ENVELOPE_KEYS = {
    "status",
    "summary",
    "output",
    "next_actions",
    "artifacts",
    "recovery_hint",
    "primitive",
    "backend",
    "model_used",
    "cost_usd",
    "session_advisory",
}


def _assert_envelope(result: dict) -> None:
    """Assert result conforms to HarnessResponse envelope."""
    assert ENVELOPE_KEYS.issubset(result.keys()), (
        f"Missing keys: {ENVELOPE_KEYS - result.keys()}"
    )
    assert result["status"] in ("success", "error", "warning")
    assert isinstance(result["summary"], str)
    assert isinstance(result["next_actions"], list)
    assert isinstance(result["artifacts"], list)


def _seed_zotero_db(db: Database) -> None:
    import json

    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (name, description) VALUES ('demo-topic', '')")
        conn.execute(
            """
            INSERT INTO papers
                (title, authors, year, venue, doi, arxiv_id, url, abstract, status, deep_read)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Agentic Zotero MCP Sync",
                json.dumps(["Ada Lovelace"]),
                2026,
                "ICLR",
                "10.1234/zotero-mcp",
                "2601.99999",
                "https://arxiv.org/abs/2601.99999",
                "A paper for Zotero MCP sync tests.",
                "pdf_ready",
                1,
            ),
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')"
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Primitive tool execution
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_env_db")
def test_execute_paper_search(monkeypatch: pytest.MonkeyPatch) -> None:
    import research_harness_mcp.tools as tools_module
    from research_harness.service import ServiceResult
    from research_harness_mcp.tools import execute_tool

    class FakeResearchService:
        def __init__(self, db) -> None:
            self.db = db

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            return ServiceResult(
                command=name,
                status="success",
                summary="Found 1 papers via local",
                output={"papers": [{"title": "Attention Is All You Need"}]},
                metadata={
                    "primitive": name,
                    "backend": "local",
                    "model_used": "",
                    "cost_usd": 0.0,
                    "provenance_recorded_by": "TrackedBackend",
                },
            )

    monkeypatch.setattr(tools_module, "ResearchService", FakeResearchService)

    result = execute_tool("paper_search", {"query": "attention"})
    _assert_envelope(result)
    assert result["status"] == "success"
    assert result["output"]["papers"]


@pytest.mark.usefixtures("_env_db")
def test_paper_search_routes_through_service_preserving_mcp_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import research_harness_mcp.tools as tools_module
    from research_harness.service import ServiceResult
    from research_harness_mcp.tools import execute_tool

    calls: list[tuple[str, dict]] = []

    class FakeResearchService:
        def __init__(self, db) -> None:
            self.db = db

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            calls.append((name, dict(arguments)))
            return ServiceResult(
                command=name,
                status="success",
                summary="Found 1 papers via local",
                output={"papers": [{"id": 1, "title": "Service Search Paper"}]},
                next_actions=("paper_ingest top results",),
                artifacts=({"kind": "paper_search"},),
                metadata={
                    "primitive": name,
                    "backend": "local",
                    "model_used": "",
                    "cost_usd": 0.12,
                    "provenance_recorded_by": "TrackedBackend",
                },
            )

    monkeypatch.setattr(tools_module, "ResearchService", FakeResearchService)
    tools_module._SESSION_ACTIVITY["last_topic_id"] = None
    tools_module._SESSION_ACTIVITY["streak"] = 0

    def fake_execute_primitive(name: str, arguments: dict) -> dict:
        raise AssertionError(f"{name} should route through service")

    monkeypatch.setattr(tools_module, "_execute_primitive", fake_execute_primitive)

    result = execute_tool("paper_search", {"query": "service"})

    _assert_envelope(result)
    assert calls == [("paper_search", {"query": "service"})]
    assert result["status"] == "success"
    assert result["primitive"] == "paper_search"
    assert result["backend"] == "local"
    assert result["cost_usd"] == 0.12
    assert result["summary"] == "Found 1 papers via local"
    assert result["output"] == {"papers": [{"id": 1, "title": "Service Search Paper"}]}
    assert result["next_actions"] == ["paper_ingest top results"]
    assert result["artifacts"] == [{"kind": "paper_search"}]
    assert result["session_advisory"] == ""


@pytest.mark.usefixtures("_env_db")
def test_paper_ingest_routes_through_service_preserving_mcp_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import research_harness_mcp.tools as tools_module
    from research_harness.service import ServiceResult
    from research_harness_mcp.tools import execute_tool

    calls: list[tuple[str, dict]] = []

    class FakeResearchService:
        def __init__(self, db) -> None:
            self.db = db

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            calls.append((name, dict(arguments)))
            return ServiceResult(
                command=name,
                status="success",
                summary="Ingested: Service Routed Ingest (status=new)",
                output={
                    "paper_id": 42,
                    "title": "Service Routed Ingest",
                    "status": "new",
                    "merged_fields": [],
                    "enriched_fields": {},
                    "duplicate_candidates": [],
                    "html_ingest": {},
                    "knowledge_refresh": {},
                },
                next_actions=("paper_summarize — generate structured summary",),
                artifacts=("paper:42",),
                metadata={
                    "primitive": name,
                    "backend": "local",
                    "model_used": "",
                    "cost_usd": 0.02,
                    "provenance_recorded_by": "TrackedBackend",
                },
            )

    monkeypatch.setattr(tools_module, "ResearchService", FakeResearchService)
    tools_module._SESSION_ACTIVITY["last_topic_id"] = None
    tools_module._SESSION_ACTIVITY["streak"] = 0

    def fake_execute_primitive(name: str, arguments: dict) -> dict:
        raise AssertionError(f"{name} should route through service")

    monkeypatch.setattr(tools_module, "_execute_primitive", fake_execute_primitive)

    result = execute_tool(
        "paper_ingest",
        {"source": "10.1000/service-route", "topic_id": 3, "relevance": "high"},
    )

    _assert_envelope(result)
    assert calls == [
        (
            "paper_ingest",
            {"source": "10.1000/service-route", "topic_id": 3, "relevance": "high"},
        )
    ]
    assert result["status"] == "success"
    assert result["primitive"] == "paper_ingest"
    assert result["backend"] == "local"
    assert result["cost_usd"] == 0.02
    assert result["summary"] == "Ingested: Service Routed Ingest (status=new)"
    assert result["output"]["paper_id"] == 42
    assert result["artifacts"] == ["paper:42"]
    assert result["session_advisory"] == ""


@pytest.mark.usefixtures("_env_db")
def test_paper_summarize_routes_through_service_preserving_mcp_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import research_harness_mcp.tools as tools_module
    from research_harness.service import ServiceResult
    from research_harness_mcp.tools import execute_tool

    calls: list[tuple[str, dict]] = []

    class FakeResearchService:
        def __init__(self, db) -> None:
            self.db = db

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            calls.append((name, dict(arguments)))
            return ServiceResult(
                command=name,
                status="success",
                summary="Summarized paper 7",
                output={
                    "paper_id": 7,
                    "summary": "Service Summary",
                    "focus": "method",
                    "confidence": 0.9,
                },
                next_actions=("claim_extract paper 7",),
                artifacts=({"kind": "summary", "paper_id": 7},),
                metadata={
                    "primitive": name,
                    "backend": "local",
                    "model_used": "local-test",
                    "cost_usd": 0.03,
                    "provenance_recorded_by": "TrackedBackend",
                },
            )

    monkeypatch.setattr(tools_module, "ResearchService", FakeResearchService)

    def fake_execute_primitive(name: str, arguments: dict) -> dict:
        raise AssertionError(f"{name} should route through service")

    monkeypatch.setattr(tools_module, "_execute_primitive", fake_execute_primitive)

    result = execute_tool("paper_summarize", {"paper_id": 7, "focus": "method"})

    _assert_envelope(result)
    assert calls == [("paper_summarize", {"paper_id": 7, "focus": "method"})]
    assert result["status"] == "success"
    assert result["primitive"] == "paper_summarize"
    assert result["backend"] == "local"
    assert result["model_used"] == "local-test"
    assert result["cost_usd"] == 0.03
    assert result["summary"] == "Summarized paper 7"
    assert result["output"] == {
        "paper_id": 7,
        "summary": "Service Summary",
        "focus": "method",
        "confidence": 0.9,
    }
    assert result["next_actions"] == ["claim_extract paper 7"]
    assert result["artifacts"] == [{"kind": "summary", "paper_id": 7}]
    assert result["session_advisory"] == ""


@pytest.mark.usefixtures("_env_db")
def test_claim_extract_routes_through_service_preserving_mcp_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import research_harness_mcp.tools as tools_module
    from research_harness.service import ServiceResult
    from research_harness_mcp.tools import execute_tool

    calls: list[tuple[str, dict]] = []

    class FakeResearchService:
        def __init__(self, db) -> None:
            self.db = db

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            calls.append((name, dict(arguments)))
            return ServiceResult(
                command=name,
                status="success",
                summary="Extracted 1 claims from 1 papers",
                output={
                    "claims": [
                        {
                            "claim_id": "claim-service-route",
                            "content": "Service routing preserves claim evidence.",
                            "paper_ids": [7],
                            "evidence_type": "finding",
                            "confidence": 0.88,
                            "source_section": "results",
                            "modality": "text",
                            "evidence_spans": [
                                {
                                    "paper_id": 7,
                                    "section": "results",
                                    "snippet": "service route evidence",
                                    "page": None,
                                    "start_char": None,
                                    "end_char": None,
                                }
                            ],
                        }
                    ],
                    "papers_processed": 1,
                },
                next_actions=("evidence_link claim-service-route",),
                artifacts=({"kind": "claims", "topic_id": 3},),
                metadata={
                    "primitive": name,
                    "backend": "local",
                    "model_used": "local-test",
                    "cost_usd": 0.07,
                    "provenance_recorded_by": "TrackedBackend",
                },
            )

    monkeypatch.setattr(tools_module, "ResearchService", FakeResearchService)

    def fake_execute_primitive(name: str, arguments: dict) -> dict:
        raise AssertionError(f"{name} should route through service")

    monkeypatch.setattr(tools_module, "_execute_primitive", fake_execute_primitive)

    result = execute_tool(
        "claim_extract",
        {"paper_ids": [7], "topic_id": 3, "focus": "method"},
    )

    _assert_envelope(result)
    assert calls == [
        (
            "claim_extract",
            {"paper_ids": [7], "topic_id": 3, "focus": "method"},
        )
    ]
    assert result["status"] == "success"
    assert result["primitive"] == "claim_extract"
    assert result["backend"] == "local"
    assert result["model_used"] == "local-test"
    assert result["cost_usd"] == 0.07
    assert result["summary"] == "Extracted 1 claims from 1 papers"
    assert result["output"]["papers_processed"] == 1
    assert result["output"]["claims"][0]["claim_id"] == "claim-service-route"
    assert result["next_actions"] == ["evidence_link claim-service-route"]
    assert result["artifacts"] == [{"kind": "claims", "topic_id": 3}]
    assert result["session_advisory"] == ""


@pytest.mark.usefixtures("_env_db")
def test_evidence_link_routes_through_service_preserving_mcp_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import research_harness_mcp.tools as tools_module
    from research_harness.service import ServiceResult
    from research_harness_mcp.tools import execute_tool

    calls: list[tuple[str, dict]] = []

    class FakeResearchService:
        def __init__(self, db) -> None:
            self.db = db

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            calls.append((name, dict(arguments)))
            return ServiceResult(
                command=name,
                status="success",
                summary="evidence_link completed (link, created)",
                output={
                    "link": {
                        "claim_id": "claim-service-route",
                        "source_type": "paper",
                        "source_id": "42",
                        "strength": "strong",
                        "notes": "",
                        "support_status": "supports",
                        "evidence_span": {
                            "paper_id": 42,
                            "section": "results",
                            "snippet": "service route evidence",
                        },
                        "citation_candidate": None,
                    },
                    "created": True,
                },
                next_actions=("gap_detect — check for remaining gaps",),
                artifacts=("evidence_link:claim-service-route→42",),
                metadata={
                    "primitive": name,
                    "backend": "local-test",
                    "model_used": "",
                    "cost_usd": 0.04,
                    "provenance_recorded_by": "TrackedBackend",
                },
            )

    monkeypatch.setattr(tools_module, "ResearchService", FakeResearchService)

    def fake_execute_primitive(name: str, arguments: dict) -> dict:
        raise AssertionError(f"{name} should route through service")

    monkeypatch.setattr(tools_module, "_execute_primitive", fake_execute_primitive)

    result = execute_tool(
        "evidence_link",
        {
            "claim_id": "claim-service-route",
            "source_type": "paper",
            "source_id": "42",
            "strength": "strong",
            "support_status": "supports",
        },
    )

    _assert_envelope(result)
    assert calls == [
        (
            "evidence_link",
            {
                "claim_id": "claim-service-route",
                "source_type": "paper",
                "source_id": "42",
                "strength": "strong",
                "support_status": "supports",
            },
        )
    ]
    assert result["status"] == "success"
    assert result["primitive"] == "evidence_link"
    assert result["backend"] == "local-test"
    assert result["cost_usd"] == 0.04
    assert result["summary"] == "evidence_link completed (link, created)"
    assert result["output"]["link"]["claim_id"] == "claim-service-route"
    assert result["artifacts"] == ["evidence_link:claim-service-route→42"]
    assert result["session_advisory"] == ""


@pytest.mark.usefixtures("_env_db")
def test_gap_detect_routes_through_service_preserving_mcp_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import research_harness_mcp.tools as tools_module
    from research_harness.service import ServiceResult
    from research_harness_mcp.tools import execute_tool

    calls: list[tuple[str, dict]] = []

    class FakeResearchService:
        def __init__(self, db) -> None:
            self.db = db

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            calls.append((name, dict(arguments)))
            return ServiceResult(
                command=name,
                status="success",
                summary="Found 1 gaps in 4 papers (1 high)",
                output={
                    "gaps": [
                        {
                            "gap_id": "gap-service-route",
                            "description": "Evaluation lacks longitudinal evidence.",
                            "gap_type": "evaluation",
                            "severity": "high",
                            "related_paper_ids": [4, 5],
                            "confidence": 0.82,
                        }
                    ],
                    "papers_analyzed": 4,
                },
                next_actions=("baseline_identify — identify baselines",),
                artifacts=("gap:gap-service-route",),
                metadata={
                    "primitive": name,
                    "backend": "local-test",
                    "model_used": "",
                    "cost_usd": 0.06,
                    "provenance_recorded_by": "TrackedBackend",
                },
            )

    monkeypatch.setattr(tools_module, "ResearchService", FakeResearchService)
    tools_module._SESSION_ACTIVITY["last_topic_id"] = None
    tools_module._SESSION_ACTIVITY["streak"] = 0

    def fake_execute_primitive(name: str, arguments: dict) -> dict:
        raise AssertionError(f"{name} should route through service")

    monkeypatch.setattr(tools_module, "_execute_primitive", fake_execute_primitive)

    result = execute_tool("gap_detect", {"topic_id": 3, "focus": "evaluation"})

    _assert_envelope(result)
    assert calls == [("gap_detect", {"topic_id": 3, "focus": "evaluation"})]
    assert result["status"] == "success"
    assert result["primitive"] == "gap_detect"
    assert result["backend"] == "local-test"
    assert result["cost_usd"] == 0.06
    assert result["summary"] == "Found 1 gaps in 4 papers (1 high)"
    assert result["output"]["gaps"][0]["gap_id"] == "gap-service-route"
    assert result["next_actions"] == ["baseline_identify — identify baselines"]
    assert result["artifacts"] == ["gap:gap-service-route"]
    assert result["session_advisory"] == ""


@pytest.mark.usefixtures("_env_db")
def test_baseline_identify_routes_through_service_preserving_mcp_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import research_harness_mcp.tools as tools_module
    from research_harness.service import ServiceResult
    from research_harness_mcp.tools import execute_tool

    calls: list[tuple[str, dict]] = []

    class FakeResearchService:
        def __init__(self, db) -> None:
            self.db = db

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            calls.append((name, dict(arguments)))
            return ServiceResult(
                command=name,
                status="success",
                summary="Identified 1 baselines",
                output={
                    "baselines": [
                        {
                            "name": "Service Baseline",
                            "baseline_id": "service-baseline",
                            "method_family": "retrieval",
                            "facets": ["ranking", "evidence"],
                            "relationship_to_proposal": "standard comparison",
                            "paper_ids": [4, 5],
                            "source_paper_ids": [4, 5],
                            "metrics": {"nDCG": "reported"},
                            "notes": "Use for service routing comparison.",
                        }
                    ]
                },
                next_actions=("section_draft methodology",),
                artifacts=({"kind": "baselines", "topic_id": 3},),
                metadata={
                    "primitive": name,
                    "backend": "local",
                    "model_used": "local-test",
                    "cost_usd": 0.09,
                    "provenance_recorded_by": "TrackedBackend",
                },
            )

    monkeypatch.setattr(tools_module, "ResearchService", FakeResearchService)

    def fake_execute_primitive(name: str, arguments: dict) -> dict:
        raise AssertionError(f"{name} should route through service")

    monkeypatch.setattr(tools_module, "_execute_primitive", fake_execute_primitive)

    result = execute_tool(
        "baseline_identify",
        {"topic_id": 3, "focus": "comparison"},
    )

    _assert_envelope(result)
    assert calls == [("baseline_identify", {"topic_id": 3, "focus": "comparison"})]
    assert result["status"] == "success"
    assert result["primitive"] == "baseline_identify"
    assert result["backend"] == "local"
    assert result["model_used"] == "local-test"
    assert result["cost_usd"] == 0.09
    assert result["summary"] == "Identified 1 baselines"
    assert result["output"]["baselines"][0]["baseline_id"] == "service-baseline"
    assert result["next_actions"] == ["section_draft methodology"]
    assert result["artifacts"] == [{"kind": "baselines", "topic_id": 3}]
    assert result["session_advisory"] == ""


@pytest.mark.usefixtures("_env_db")
def test_consistency_check_routes_through_service_preserving_mcp_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import research_harness_mcp.tools as tools_module
    from research_harness.service import ServiceResult
    from research_harness_mcp.tools import execute_tool

    calls: list[tuple[str, dict]] = []

    class FakeResearchService:
        def __init__(self, db) -> None:
            self.db = db

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            calls.append((name, dict(arguments)))
            return ServiceResult(
                command=name,
                status="success",
                summary="Found 1 consistency issue",
                output={
                    "issues": [
                        {
                            "issue_type": "terminology",
                            "severity": "medium",
                            "location": "related_work",
                            "description": "Method naming is inconsistent.",
                            "suggestion": "Use one method name throughout.",
                        }
                    ],
                    "sections_checked": ["intro", "related_work"],
                },
                next_actions=("revise inconsistent terminology",),
                artifacts=({"kind": "consistency_check", "topic_id": 3},),
                metadata={
                    "primitive": name,
                    "backend": "local",
                    "model_used": "local-test",
                    "cost_usd": 0.05,
                    "provenance_recorded_by": "TrackedBackend",
                },
            )

    monkeypatch.setattr(tools_module, "ResearchService", FakeResearchService)

    def fake_execute_primitive(name: str, arguments: dict) -> dict:
        raise AssertionError(f"{name} should route through service")

    monkeypatch.setattr(tools_module, "_execute_primitive", fake_execute_primitive)

    result = execute_tool(
        "consistency_check",
        {"topic_id": 3, "sections": ["intro", "related_work"]},
    )

    _assert_envelope(result)
    assert calls == [
        (
            "consistency_check",
            {"topic_id": 3, "sections": ["intro", "related_work"]},
        )
    ]
    assert result["status"] == "success"
    assert result["primitive"] == "consistency_check"
    assert result["backend"] == "local"
    assert result["model_used"] == "local-test"
    assert result["cost_usd"] == 0.05
    assert result["summary"] == "Found 1 consistency issue"
    assert result["output"]["sections_checked"] == ["intro", "related_work"]
    assert result["output"]["issues"][0]["issue_type"] == "terminology"
    assert result["next_actions"] == ["revise inconsistent terminology"]
    assert result["artifacts"] == [{"kind": "consistency_check", "topic_id": 3}]
    assert result["session_advisory"] == ""


@pytest.mark.usefixtures("_env_db")
def test_section_draft_routes_through_service_preserving_mcp_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import research_harness_mcp.tools as tools_module
    from research_harness.service import ServiceResult
    from research_harness_mcp.tools import execute_tool

    calls: list[tuple[str, dict]] = []

    class FakeResearchService:
        def __init__(self, db) -> None:
            self.db = db

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            calls.append((name, dict(arguments)))
            return ServiceResult(
                command=name,
                status="success",
                summary="Drafted 'related_work' section — 7 words, 2 citations",
                output={
                    "draft": {
                        "section": "related_work",
                        "content": "Service routed draft cites prior work.",
                        "citations_used": [4, 5],
                        "evidence_ids": ["claim:service-route"],
                        "word_count": 7,
                    },
                    "evidence_map": [
                        {
                            "sentence_index": 0,
                            "sentence_text": ("Service routed draft cites prior work."),
                            "source_paper_id": 4,
                            "relation_type": "compression",
                            "source_span": "results",
                            "confidence": 0.87,
                        }
                    ],
                },
                next_actions=("consistency_check — verify cross-section consistency",),
                artifacts=("draft:related_work",),
                metadata={
                    "primitive": name,
                    "backend": "local",
                    "model_used": "local-test",
                    "cost_usd": 0.11,
                    "provenance_recorded_by": "TrackedBackend",
                },
            )

    monkeypatch.setattr(tools_module, "ResearchService", FakeResearchService)
    tools_module._SESSION_ACTIVITY["last_topic_id"] = None
    tools_module._SESSION_ACTIVITY["streak"] = 0

    def fake_execute_primitive(name: str, arguments: dict) -> dict:
        raise AssertionError(f"{name} should route through service")

    monkeypatch.setattr(tools_module, "_execute_primitive", fake_execute_primitive)

    result = execute_tool(
        "section_draft",
        {
            "topic_id": 3,
            "section": "related_work",
            "evidence_ids": ["claim:service-route"],
        },
    )

    _assert_envelope(result)
    assert calls == [
        (
            "section_draft",
            {
                "topic_id": 3,
                "section": "related_work",
                "evidence_ids": ["claim:service-route"],
            },
        )
    ]
    assert result["status"] == "success"
    assert result["primitive"] == "section_draft"
    assert result["backend"] == "local"
    assert result["model_used"] == "local-test"
    assert result["cost_usd"] == 0.11
    assert result["summary"] == (
        "Drafted 'related_work' section — 7 words, 2 citations"
    )
    assert result["output"]["draft"]["section"] == "related_work"
    assert result["output"]["draft"]["citations_used"] == [4, 5]
    assert result["output"]["evidence_map"][0]["source_paper_id"] == 4
    assert result["next_actions"] == [
        "consistency_check — verify cross-section consistency"
    ]
    assert result["artifacts"] == ["draft:related_work"]
    assert result["session_advisory"] == ""


@pytest.mark.usefixtures("_env_db")
def test_execute_unknown_tool() -> None:
    from research_harness_mcp.tools import execute_tool

    result = execute_tool("nonexistent_tool", {})
    _assert_envelope(result)
    assert result["status"] == "error"
    assert "Unknown tool" in result["output"]["error"]


def test_productization_boundary_requires_explicit_lg10_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import research_harness_mcp.tools as tools_module
    from research_harness_mcp.tools import execute_tool

    def fail_resolve_db():
        raise AssertionError("productization_boundary must not open the database")

    monkeypatch.setattr(tools_module, "_resolve_db", fail_resolve_db)

    result = execute_tool("productization_boundary", {})

    _assert_envelope(result)
    assert result["status"] == "error"
    assert result["primitive"] == "productization_boundary"
    assert result["output"]["code"] == "lg10_opt_in_required"
    assert result["output"]["error"] == (
        "pass experimental_lg10=true to view the LG10 boundary"
    )


def test_productization_boundary_outputs_shape_locked_json_without_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import research_harness_mcp.tools as tools_module
    from research_harness_mcp.tools import execute_tool

    def fail_resolve_db():
        raise AssertionError("productization_boundary must not open the database")

    monkeypatch.setattr(tools_module, "_resolve_db", fail_resolve_db)

    result = execute_tool(
        "productization_boundary",
        {"experimental_lg10": True},
    )

    _assert_envelope(result)
    assert result["status"] == "success"
    assert result["primitive"] == "productization_boundary"
    payload = result["output"]
    assert payload["boundary_id"] == "lg10-public-productization-boundary"
    assert payload["schema_version"] == "lg10_productization_boundary.v1"
    assert payload["scope"] == "public-mcp-opt-in-preview"
    assert payload["lg8_lg9_prerequisite"] == "complete"
    assert payload["lg10_status"] == "gate_bound"
    assert payload["allowed_future_pattern"] == "one_public_surface_per_gate_slice"
    assert payload["public_surfaces"] == [
        "CLI",
        "MCP",
        "HTTP",
        "Python facade",
        "Zotero",
        "doctor",
        "showcase",
        "skills/docs",
    ]
    assert payload["required_pre_implementation_evidence"] == [
        "shape-lock tests",
        "opt-in default",
        "compatibility proof",
        "docs claim review",
        "rollback/fallback plan",
    ]
    assert payload["risk_flags"] == {
        "public_surface_changed": False,
        "storage_or_provenance_changed": False,
        "orchestrator_gate_changed": False,
        "benchmark_claim_changed": False,
        "dependency_changed": False,
    }


def test_productization_boundary_routes_through_service_without_db(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import research_harness_mcp.tools as tools_module
    from research_harness.service import ServiceResult
    from research_harness_mcp.tools import execute_tool

    calls: list[tuple[str, dict]] = []

    class FakeResearchService:
        def __init__(self, db=None) -> None:
            assert db is None

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            calls.append((name, dict(arguments)))
            return ServiceResult(
                command=name,
                status="success",
                summary="productization_boundary completed successfully.",
                output={
                    "schema_version": "lg10_productization_boundary.v1",
                    "boundary_id": "lg10-public-productization-boundary",
                    "scope": "public-mcp-opt-in-preview",
                    "risk_flags": {
                        "public_surface_changed": False,
                        "storage_or_provenance_changed": False,
                        "orchestrator_gate_changed": False,
                        "benchmark_claim_changed": False,
                        "dependency_changed": False,
                    },
                },
            )

    def fail_resolve_db():
        raise AssertionError("productization_boundary must not open the database")

    def fail_direct_productization_tool(name: str, arguments: dict):
        del name, arguments
        raise AssertionError("productization_boundary should route through service")

    monkeypatch.setattr(tools_module, "ResearchService", FakeResearchService)
    monkeypatch.setattr(tools_module, "_resolve_db", fail_resolve_db)
    monkeypatch.setattr(
        tools_module,
        "_execute_productization_tool",
        fail_direct_productization_tool,
    )

    result = execute_tool(
        "productization_boundary",
        {"experimental_lg10": True},
    )

    _assert_envelope(result)
    assert calls == [
        ("productization_boundary", {"experimental_lg10": True}),
    ]
    assert result["status"] == "success"
    assert result["primitive"] == "productization_boundary"
    assert result["output"]["scope"] == "public-mcp-opt-in-preview"


def test_execute_hidden_primitive_remains_compatible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import research_harness_mcp.tools as tools_module
    from research_harness_mcp.tools import execute_tool, list_tool_definitions

    public_names = {tool.name for tool in list_tool_definitions()}
    assert "code_validate" not in public_names

    def fake_execute_primitive(name: str, arguments: dict) -> dict:
        return {"status": "success", "primitive": name, "arguments": arguments}

    monkeypatch.setattr(tools_module, "_execute_primitive", fake_execute_primitive)

    result = execute_tool("code_validate", {"source": "print('ok')"})

    assert result["status"] == "success"
    assert result["primitive"] == "code_validate"
    assert result["arguments"] == {"source": "print('ok')"}
    assert result["_deprecated"].startswith(
        "code_validate is still executable for compatibility"
    )


@pytest.mark.usefixtures("_env_db")
def test_execute_zotero_sync_push_dry_run(db: Database) -> None:
    from research_harness_mcp.tools import execute_tool

    _seed_zotero_db(db)

    result = execute_tool(
        "zotero_sync",
        {
            "topic": "demo-topic",
            "direction": "push",
            "dry_run": True,
            "limit": 1,
        },
    )

    _assert_envelope(result)
    assert result["status"] == "success"
    assert result["output"]["direction"] == "push"
    assert result["output"]["push"]["planned_count"] == 1
    assert result["output"]["push"]["records"][0]["title"] == "Agentic Zotero MCP Sync"


@pytest.mark.usefixtures("_env_db")
def test_execute_zotero_sync_validates_direction(db: Database) -> None:
    from research_harness_mcp.tools import execute_tool

    _seed_zotero_db(db)

    result = execute_tool(
        "zotero_sync",
        {"topic": "demo-topic", "direction": "sideways", "dry_run": True},
    )

    _assert_envelope(result)
    assert result["status"] == "error"
    assert "direction" in result["output"]["error"]


@pytest.mark.usefixtures("_env_db")
def test_execute_zotero_sync_defers_pull_dry_run_without_zotero_client(
    db: Database,
) -> None:
    from research_harness_mcp.tools import execute_tool

    _seed_zotero_db(db)

    result = execute_tool(
        "zotero_sync",
        {"topic": "demo-topic", "direction": "pull", "dry_run": True},
    )

    _assert_envelope(result)
    assert result["status"] == "error"
    assert result["output"]["error"] == (
        "stable Zotero dry-run only supports direction=push; "
        "pull dry-run requires Zotero read access and remains deferred"
    )


# ---------------------------------------------------------------------------
# Convenience tool execution
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_env_db")
def test_topic_list_empty(db: Database) -> None:
    from research_harness_mcp.tools import execute_tool

    result = execute_tool("topic_list", {})
    _assert_envelope(result)
    assert result["status"] == "success"
    assert result["output"]["topics"] == []


@pytest.mark.usefixtures("_env_db")
def test_topic_list_with_data(db: Database) -> None:
    from research_harness_mcp.tools import execute_tool

    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (name, description, status) VALUES (?, ?, ?)",
            ("auto-bidding", "Auction bidding strategies", "active"),
        )
        conn.commit()
    finally:
        conn.close()

    result = execute_tool("topic_list", {})
    _assert_envelope(result)
    assert len(result["output"]["topics"]) == 1
    assert result["output"]["topics"][0]["name"] == "auto-bidding"


@pytest.mark.usefixtures("_env_db")
def test_topic_show_not_found() -> None:
    from research_harness_mcp.tools import execute_tool

    result = execute_tool("topic_show", {"name": "nonexistent"})
    _assert_envelope(result)
    assert result["status"] == "error"


@pytest.mark.usefixtures("_env_db")
def test_provenance_summary(db: Database) -> None:
    from research_harness_mcp.tools import execute_tool

    result = execute_tool("provenance_summary", {})
    _assert_envelope(result)
    assert result["status"] == "success"
    assert result["output"]["total_operations"] == 0


@pytest.mark.usefixtures("_env_db")
def test_provenance_export(db: Database) -> None:
    from research_harness.primitives.types import PrimitiveResult
    from research_harness.provenance.recorder import ProvenanceRecorder
    from research_harness_mcp.tools import execute_tool

    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (name, description, status) VALUES (?, ?, ?)",
            ("prov-topic", "topic for provenance export", "active"),
        )
        conn.commit()
        topic_id = conn.execute(
            "SELECT id FROM topics WHERE name = ?", ("prov-topic",)
        ).fetchone()[0]
    finally:
        conn.close()

    recorder = ProvenanceRecorder(db)
    recorder.record(
        PrimitiveResult(
            primitive="paper_ingest",
            success=True,
            output={"paper_id": 1},
            started_at="2026-04-03T00:00:00+00:00",
            finished_at="2026-04-03T00:00:01+00:00",
            backend="local",
            model_used="",
            cost_usd=0.0,
        ),
        input_kwargs={"source": "10.1000/test"},
        topic_id=topic_id,
    )

    result = execute_tool("provenance_export", {"topic_id": topic_id, "format": "json"})
    _assert_envelope(result)
    assert result["output"]["format"] == "json"
    assert len(result["output"]["records"]) == 1
    assert result["output"]["records"][0]["primitive"] == "paper_ingest"
    assert result["output"]["records"][0]["topic_id"] == topic_id


@pytest.mark.usefixtures("_env_db")
def test_paper_list_empty() -> None:
    from research_harness_mcp.tools import execute_tool

    result = execute_tool("paper_list", {})
    _assert_envelope(result)
    assert result["output"]["papers"] == []


@pytest.mark.usefixtures("_env_db")
@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected_output"),
    [
        (
            "paper_list",
            {"topic": "service-topic"},
            {"papers": [{"id": 123, "title": "From service"}]},
        ),
        (
            "provenance_summary",
            {"topic_id": 7},
            {"total_operations": 9, "operations_by_backend": {"local": 9}},
        ),
        (
            "provenance_export",
            {"topic_id": 7, "format": "json"},
            {
                "format": "json",
                "records": [{"id": 1, "primitive": "paper_ingest", "topic_id": 7}],
            },
        ),
        (
            "orchestrator_status",
            {"topic_id": 7},
            {
                "run": {"current_stage": "init"},
                "stage": {"missing_artifacts": ["topic_brief"]},
                "gate": {"decision": "needs_approval", "can_advance": False},
            },
        ),
        (
            "orchestrator_gate_check",
            {"topic_id": 7, "stage": "topic_framing"},
            {"gate_decision": "needs_approval"},
        ),
    ],
)
def test_public_read_tools_route_through_service(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    arguments: dict,
    expected_output: dict,
) -> None:
    import research_harness_mcp.tools as tools_module
    from research_harness.service import ServiceResult
    from research_harness_mcp.tools import execute_tool

    calls: list[tuple[str, dict]] = []

    class FakeResearchService:
        def __init__(self, db) -> None:
            self.db = db

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            calls.append((name, dict(arguments)))
            return ServiceResult(
                command=name,
                status="success",
                summary="service-backed result",
                output=expected_output,
            )

    monkeypatch.setattr(tools_module, "ResearchService", FakeResearchService)

    result = execute_tool(tool_name, arguments)

    _assert_envelope(result)
    assert calls == [(tool_name, arguments)]
    assert result["status"] == "success"
    assert result["output"] == expected_output


@pytest.mark.usefixtures("_env_db")
def test_paperindex_search_routes_through_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import research_harness_mcp.tools as tools_module
    from research_harness.service import ServiceResult
    from research_harness_mcp.tools import execute_tool

    calls: list[tuple[str, dict]] = []

    class FakeResearchService:
        def __init__(self, db) -> None:
            self.db = db

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            calls.append((name, dict(arguments)))
            return ServiceResult(
                command=name,
                status="success",
                summary="service-backed paperindex",
                output={"results": [{"paper_id": "p1", "title": "Indexed Paper"}]},
            )

    def fail_paperindex(name: str, arguments: dict) -> dict:
        raise AssertionError(f"{name} should route through service")

    monkeypatch.setattr(tools_module, "ResearchService", FakeResearchService)
    monkeypatch.setattr(tools_module, "_execute_paperindex", fail_paperindex)

    result = execute_tool("paperindex_search", {"query": "indexed", "limit": 1})

    _assert_envelope(result)
    assert calls == [("paperindex_search", {"query": "indexed", "limit": 1})]
    assert result["status"] == "success"
    assert result["output"] == {
        "results": [{"paper_id": "p1", "title": "Indexed Paper"}]
    }


@pytest.mark.usefixtures("_env_db")
@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected_output"),
    [
        (
            "skill_list",
            {"category": "writing"},
            {
                "schema_version": "1.0",
                "skills_dir": "skills",
                "skills": [{"name": "paper-writing", "category": "writing"}],
            },
        ),
        (
            "skill_get",
            {"name": "paper-writing", "track": "survey-review"},
            {
                "name": "paper-writing",
                "content": "# Paper Writing",
                "track": {"name": "survey-review", "content": "Track B"},
            },
        ),
    ],
)
def test_skill_tools_route_through_service_preserving_raw_shape(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    arguments: dict,
    expected_output: dict,
) -> None:
    import research_harness_mcp.tools as tools_module
    from research_harness.service import ServiceResult
    from research_harness_mcp.tools import execute_tool

    calls: list[tuple[str, dict]] = []

    class FakeResearchService:
        def __init__(self, db=None) -> None:
            self.db = db

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            calls.append((name, dict(arguments)))
            return ServiceResult(
                command=name,
                status="success",
                summary="service-backed skill list",
                output=expected_output,
            )

    def fail_skill_tool(name: str, arguments: dict) -> dict:
        raise AssertionError(f"{name} should route through service")

    monkeypatch.setattr(tools_module, "ResearchService", FakeResearchService)
    monkeypatch.setattr(
        tools_module,
        "execute_skill_tool",
        fail_skill_tool,
        raising=False,
    )

    result = execute_tool(tool_name, arguments)

    assert calls == [(tool_name, arguments)]
    assert result == expected_output


@pytest.mark.usefixtures("_env_db")
def test_skill_get_missing_name_preserves_raw_error_shape() -> None:
    from research_harness_mcp.tools import execute_tool

    result = execute_tool("skill_get", {})

    assert result == {"error": "missing required argument: name"}


@pytest.mark.usefixtures("_env_db")
def test_skill_get_rejects_track_path_traversal_through_service() -> None:
    from research_harness_mcp.tools import execute_tool

    result = execute_tool(
        "skill_get",
        {"name": "paper-writing", "track": "../../../docs/STATUS"},
    )

    assert "track" not in result
    assert result["track_error"].startswith(
        "track '../../../docs/STATUS' not found for skill 'paper-writing'"
    )
    assert "# Research Harness Status" not in str(result)


@pytest.mark.usefixtures("_env_db")
def test_orchestrator_status_and_gate_check_outputs(db: Database) -> None:
    from research_harness.orchestrator import OrchestratorService
    from research_harness_mcp.tools import execute_tool

    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (id, name, description, status) VALUES (1, ?, ?, ?)",
            ("orch-read-topic", "topic for orchestrator read tools", "active"),
        )
        conn.execute(
            "INSERT INTO projects (id, topic_id, name, description) VALUES (1, 1, ?, ?)",
            ("orch-read-project", "project for orchestrator read tools"),
        )
        conn.commit()
    finally:
        conn.close()

    OrchestratorService(db).init_run(topic_id=1)

    status = execute_tool("orchestrator_status", {"topic_id": 1})
    gate = execute_tool("orchestrator_gate_check", {"topic_id": 1})

    _assert_envelope(status)
    _assert_envelope(gate)
    assert status["status"] == "success"
    assert status["output"]["run"]["current_stage"] == "init"
    assert status["output"]["gate"]["decision"] == "needs_approval"
    assert "db_path" not in status["output"]
    assert gate["status"] == "success"
    assert gate["output"]["gate_decision"] == "needs_approval"
    assert gate["output"]["can_advance"] is False
    assert "reasons" in gate["output"]
    assert "recovery_actions" in gate["output"]


@pytest.mark.usefixtures("_env_db")
def test_orchestrator_resume_routes_through_service_preserving_wrapper_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import research_harness_mcp.tools as tools_module
    from research_harness.service import ServiceResult
    from research_harness_mcp.tools import execute_tool

    calls: list[tuple[str, dict]] = []

    class FakeResearchService:
        def __init__(self, db) -> None:
            self.db = db

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            calls.append((name, dict(arguments)))
            return ServiceResult(
                command=name,
                status="success",
                summary="orchestrator_resume completed successfully.",
                output={
                    "success": True,
                    "run_id": 11,
                    "topic_id": 3,
                    "current_stage": "build",
                    "inferred_stage": "analyze",
                    "stage_status": "in_progress",
                    "stop_before": "write",
                },
            )

    monkeypatch.setattr(tools_module, "ResearchService", FakeResearchService)
    monkeypatch.setattr(tools_module, "_inject_strategy_overlay", lambda raw: "")

    def fake_execute_orchestrator(name: str, arguments: dict) -> dict:
        raise AssertionError(f"{name} should route through service")

    monkeypatch.setattr(
        tools_module,
        "_execute_orchestrator",
        fake_execute_orchestrator,
    )

    result = execute_tool(
        "orchestrator_resume",
        {
            "topic_id": 3,
            "mode": "strict",
            "force_stage": "literature_mapping",
            "stop_before": "draft_preparation",
        },
    )

    _assert_envelope(result)
    assert calls == [
        (
            "orchestrator_resume",
            {
                "topic_id": 3,
                "mode": "strict",
                "force_stage": "literature_mapping",
                "stop_before": "draft_preparation",
            },
        )
    ]
    assert result["status"] == "success"
    assert result["summary"] == (
        "Resumed run at stage: build (inferred from artifacts: analyze)"
    )
    assert result["output"]["run_id"] == 11
    assert result["output"]["current_stage"] == "build"
    assert result["output"]["inferred_stage"] == "analyze"
    assert result["output"]["stop_before"] == "write"
    assert result["next_actions"] == [
        "orchestrator_status — check current stage requirements"
    ]
    assert result["artifacts"] == []
    assert result["recovery_hint"] == ""
    assert result["primitive"] == "orchestrator_resume"
    assert result["backend"] == "orchestrator"
    assert result["model_used"] == ""
    assert result["cost_usd"] == 0.0
    assert result["session_advisory"] == ""
    assert "strategy_overlay" not in result


@pytest.mark.usefixtures("_env_db")
@pytest.mark.parametrize(
    ("tool_name", "arguments", "service_output", "expected_summary", "expected_next"),
    [
        (
            "orchestrator_record_artifact",
            {
                "topic_id": 3,
                "stage": "build",
                "artifact_type": "literature_map",
                "payload": {"v": 1},
            },
            {
                "success": True,
                "artifact_id": 31,
                "version": 2,
                "stage": "build",
                "type": "literature_map",
            },
            "Recorded artifact: literature_map (id=31)",
            ["orchestrator_gate_check — check if gate now passes"],
        ),
        (
            "orchestrator_advance",
            {"topic_id": 3, "actor": "codex"},
            {"success": True, "from_stage": "build", "to_stage": "analyze"},
            "Advanced to next stage",
            ["orchestrator_status — check new stage requirements"],
        ),
        (
            "adversarial_review",
            {"topic_id": 3, "artifact_id": 9, "focus": "validity"},
            {
                "success": True,
                "verdict": "revise",
                "issues_count": 1,
                "critical_count": 1,
                "backend": "mock",
                "stage": "propose",
            },
            "Independent review (mock): verdict=revise, 1 issues (1 critical)",
            ["Address critical/major issues, then re-run adversarial_review"],
        ),
    ],
)
def test_remaining_orchestrator_tools_route_through_service_preserving_wrapper_shape(
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    arguments: dict,
    service_output: dict,
    expected_summary: str,
    expected_next: list[str],
) -> None:
    import research_harness_mcp.tools as tools_module
    from research_harness.service import ServiceResult
    from research_harness_mcp.tools import execute_tool

    calls: list[tuple[str, dict]] = []

    class FakeResearchService:
        def __init__(self, db) -> None:
            self.db = db

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            calls.append((name, dict(arguments)))
            return ServiceResult(
                command=name,
                status="success",
                summary=f"{name} completed successfully.",
                output=service_output,
            )

    monkeypatch.setattr(tools_module, "ResearchService", FakeResearchService)
    monkeypatch.setattr(tools_module, "_inject_strategy_overlay", lambda raw: "")

    def fake_execute_orchestrator(name: str, arguments: dict) -> dict:
        raise AssertionError(f"{name} should route through service")

    monkeypatch.setattr(
        tools_module,
        "_execute_orchestrator",
        fake_execute_orchestrator,
    )

    result = execute_tool(tool_name, arguments)

    _assert_envelope(result)
    assert calls == [(tool_name, arguments)]
    assert result["status"] == "success"
    assert result["summary"] == expected_summary
    assert result["output"] == service_output
    assert result["next_actions"] == expected_next
    assert result["artifacts"] == []
    assert result["recovery_hint"] == ""
    assert result["primitive"] == tool_name
    assert result["backend"] == "orchestrator"
    assert result["model_used"] == ""
    assert result["cost_usd"] == 0.0
    assert result["session_advisory"] == ""


@pytest.mark.usefixtures("_env_db")
def test_zotero_sync_routes_through_service_preserving_mcp_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import research_harness_mcp.tools as tools_module
    from research_harness.service import ServiceResult
    from research_harness_mcp.tools import execute_tool

    calls: list[tuple[str, dict]] = []
    service_output = {
        "topic": "demo-topic",
        "direction": "push",
        "dry_run": True,
        "push": {"planned_count": 1, "records": [{"title": "Paper"}]},
        "pull": None,
    }

    class FakeResearchService:
        def __init__(self, db) -> None:
            self.db = db

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            calls.append((name, dict(arguments)))
            return ServiceResult(
                command=name,
                status="success",
                summary="zotero_sync completed successfully.",
                output=service_output,
            )

    monkeypatch.setattr(tools_module, "ResearchService", FakeResearchService)

    def fake_execute_convenience(name: str, arguments: dict) -> dict:
        raise AssertionError(f"{name} should route through service")

    monkeypatch.setattr(
        tools_module,
        "_execute_convenience",
        fake_execute_convenience,
    )

    arguments = {
        "topic": "demo-topic",
        "direction": "push",
        "dry_run": True,
        "limit": 1,
    }
    result = execute_tool("zotero_sync", arguments)

    _assert_envelope(result)
    assert calls == [("zotero_sync", arguments)]
    assert result["status"] == "success"
    assert result["summary"] == "zotero_sync completed"
    assert result["output"] == service_output
    assert result["next_actions"] == []
    assert result["artifacts"] == []
    assert result["recovery_hint"] == ""
    assert result["primitive"] == "zotero_sync"
    assert result["backend"] == "local"
    assert result["model_used"] == ""
    assert result["cost_usd"] == 0.0
    assert result["session_advisory"] == ""


@pytest.mark.usefixtures("_env_db")
def test_task_list_empty() -> None:
    from research_harness_mcp.tools import execute_tool

    result = execute_tool("task_list", {})
    _assert_envelope(result)
    assert result["output"]["tasks"] == []


@pytest.mark.usefixtures("_env_db")
def test_advisory_check_routes_through_service_preserving_mcp_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import research_harness_mcp.tools as tools_module
    from research_harness.service import ServiceResult
    from research_harness_mcp.tools import execute_tool

    calls: list[tuple[str, dict]] = []

    class FakeResearchService:
        def __init__(self, db) -> None:
            self.db = db

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            calls.append((name, dict(arguments)))
            return ServiceResult(
                command=name,
                status="success",
                summary="advisory_check completed successfully.",
                output={
                    "advisories": [
                        {
                            "id": 7,
                            "topic_id": 3,
                            "level": "info",
                            "category": "coverage_low",
                            "message": "Topic has only 1 papers.",
                            "details": {"paper_count": 1},
                            "created_at": "2026-04-03T00:00:00",
                            "acknowledged": False,
                            "acknowledged_at": None,
                            "auto_resolved": False,
                        }
                    ],
                    "count": 1,
                },
            )

    monkeypatch.setattr(tools_module, "ResearchService", FakeResearchService)

    def fake_execute_convenience(name: str, arguments: dict) -> dict:
        raise AssertionError(f"{name} should route through service")

    monkeypatch.setattr(
        tools_module,
        "_execute_convenience",
        fake_execute_convenience,
    )

    result = execute_tool("advisory_check", {"topic_id": 3})

    _assert_envelope(result)
    assert calls == [("advisory_check", {"topic_id": 3})]
    assert result["status"] == "success"
    assert result["summary"] == "advisory_check completed"
    assert result["output"]["count"] == 1
    assert result["output"]["advisories"][0]["id"] == 7
    assert result["next_actions"] == []
    assert result["artifacts"] == []
    assert result["recovery_hint"] == ""
    assert result["primitive"] == "advisory_check"
    assert result["backend"] == "local"
    assert result["model_used"] == ""
    assert result["cost_usd"] == 0.0
    assert result["session_advisory"] == ""


@pytest.mark.usefixtures("_env_db")
def test_advisory_check_list_and_acknowledge(db: Database) -> None:
    from research_harness_mcp.tools import execute_tool

    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (id, name, description, status) VALUES (1, ?, ?, ?)",
            ("sparse-topic", "topic with low coverage", "active"),
        )
        conn.execute(
            "INSERT INTO papers (title, year, authors, doi, arxiv_id, s2_id) VALUES (?, ?, ?, ?, ?, ?)",
            (
                "Classic Bidding Paper",
                2021,
                '["Alice", "Alice", "Bob"]',
                "10.1000/sparse-1",
                "2401.00001",
                "s2-sparse-1",
            ),
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')"
        )
        conn.commit()
    finally:
        conn.close()

    checked = execute_tool("advisory_check", {"topic_id": 1})
    _assert_envelope(checked)
    assert checked["status"] == "success"
    assert checked["output"]["count"] >= 1

    listed = execute_tool("advisory_list", {"topic_id": 1})
    _assert_envelope(listed)
    advisories = listed["output"]["advisories"]
    assert advisories
    advisory_id = advisories[0]["id"]

    acked = execute_tool("advisory_acknowledge", {"advisory_id": advisory_id})
    _assert_envelope(acked)
    assert acked["output"]["advisory"]["acknowledged"] is True


@pytest.mark.usefixtures("_env_db")
def test_orchestrator_stale_artifact_tools(db: Database) -> None:
    from research_harness_mcp.tools import execute_tool

    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (id, name, description, status) VALUES (1, ?, ?, ?)",
            ("orch-topic", "topic for orchestrator", "active"),
        )
        conn.execute(
            "INSERT INTO projects (id, topic_id, name, description) VALUES (1, 1, ?, ?)",
            ("orch-project", "project for orchestrator"),
        )
        conn.commit()
    finally:
        conn.close()

    recorded = execute_tool(
        "orchestrator_record_artifact",
        {
            "topic_id": 1,
            "stage": "build",
            "artifact_type": "literature_map",
            "payload": {"v": 1},
        },
    )
    _assert_envelope(recorded)
    artifact_id = recorded["output"]["artifact_id"]

    marked = execute_tool(
        "orchestrator_mark_artifact_stale",
        {"artifact_id": artifact_id, "reason": "source changed"},
    )
    _assert_envelope(marked)
    assert artifact_id in marked["output"]["stale_ids"]

    listed = execute_tool("orchestrator_list_stale_artifacts", {"topic_id": 1})
    _assert_envelope(listed)
    assert listed["output"]["count"] == 1
    assert listed["output"]["artifacts"][0]["id"] == artifact_id

    cleared = execute_tool(
        "orchestrator_clear_artifact_stale", {"artifact_id": artifact_id}
    )
    _assert_envelope(cleared)
    assert cleared["output"]["success"] is True


# ---------------------------------------------------------------------------
# Harness features — next_actions and recovery_hint
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_env_db")
def test_paper_search_has_next_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    import research_harness_mcp.tools as tools_module
    from research_harness.service import ServiceResult
    from research_harness_mcp.tools import execute_tool

    class FakeResearchService:
        def __init__(self, db) -> None:
            self.db = db

        def invoke(self, name: str, arguments: dict) -> ServiceResult:
            return ServiceResult(
                command=name,
                status="success",
                summary="Found 1 papers via local",
                output={"papers": [{"title": "Test Paper"}]},
                next_actions=("paper_ingest top results",),
                metadata={
                    "primitive": name,
                    "backend": "local",
                    "model_used": "",
                    "cost_usd": 0.0,
                    "provenance_recorded_by": "TrackedBackend",
                },
            )

    monkeypatch.setattr(tools_module, "ResearchService", FakeResearchService)

    result = execute_tool("paper_search", {"query": "test"})
    assert result["status"] == "success"
    assert len(result["next_actions"]) > 0
    assert result["summary"]  # non-empty summary


@pytest.mark.usefixtures("_env_db")
def test_session_advisory_after_consecutive_topic_ops(db: Database) -> None:
    from research_harness_mcp import tools as tools_module
    from research_harness_mcp.tools import execute_tool

    tools_module._SESSION_ACTIVITY["last_topic_id"] = None
    tools_module._SESSION_ACTIVITY["streak"] = 0

    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (id, name, description, status) VALUES (1, ?, ?, ?)",
            ("advisory-topic", "topic for session advisory", "active"),
        )
        conn.commit()
    finally:
        conn.close()

    for query in ("query one", "query two", "query three"):
        result = execute_tool("search_query_add", {"topic_id": 1, "query": query})
        _assert_envelope(result)

    assert "Detected 3 consecutive operations on topic 1" in result["session_advisory"]


@pytest.mark.usefixtures("_env_db")
def test_error_has_recovery_hint() -> None:
    from research_harness_mcp.tools import execute_tool

    result = execute_tool("nonexistent_tool", {})
    assert result["status"] == "error"
    assert result["recovery_hint"]  # non-empty recovery hint


# ---------------------------------------------------------------------------
# Phase 4: experiment handoff + workflow_entry
# ---------------------------------------------------------------------------


def _seed_candidate(db: Database) -> tuple[int, int]:
    """Create a topic + one research_candidate with a live gap. Returns (topic_id, candidate_id)."""
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (id, name, description, status) VALUES (1, ?, ?, ?)",
            ("h-topic", "topic for handoff", "active"),
        )
        conn.execute(
            "INSERT INTO projects (id, topic_id, name, description) VALUES (1, 1, ?, ?)",
            ("h-project", "project for handoff"),
        )
        conn.execute(
            "INSERT INTO gaps (topic_id, description, severity, confidence, "
            "cross_verified) VALUES (1, 'Missing benchmark X', 'high', 0.8, 1)"
        )
        gap_id = conn.execute(
            "SELECT id FROM gaps ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO research_candidates "
            "(scope, title, pitch, llm_score, area_red_ocean, task_red_ocean, "
            " method_red_ocean, opportunity_angle, evidence_gap_ids, "
            " lineage_key, evidence_signature, status) "
            "VALUES ('topic:1', ?, ?, 7.5, 0.3, 0.2, 0.4, 'frontier', ?, "
            " 'lk-1', 'ev-1', 'candidate')",
            (
                "Benchmark-X candidate",
                "Close the missing benchmark gap",
                f"[{gap_id}]",
            ),
        )
        cid = conn.execute(
            "SELECT id FROM research_candidates ORDER BY id DESC LIMIT 1"
        ).fetchone()[0]
        conn.commit()
    finally:
        conn.close()
    return 1, int(cid)


@pytest.mark.usefixtures("_env_db")
def test_experiment_handoff_prepare_creates_brief(db: Database) -> None:
    from research_harness_mcp.tools import execute_tool

    topic_id, candidate_id = _seed_candidate(db)
    result = execute_tool(
        "experiment_handoff_prepare",
        {"topic_id": topic_id, "candidate_id": candidate_id, "notes": "go"},
    )
    _assert_envelope(result)
    assert result["status"] == "success"
    out = result["output"]
    assert out["success"] is True
    assert out["stage"] == "experiment"
    assert out["artifact_type"] == "experiment_brief"

    # Payload has candidate fields + dereferenced evidence
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT payload_json FROM project_artifacts WHERE id = ?",
            (out["artifact_id"],),
        ).fetchone()
    finally:
        conn.close()
    import json as _json

    payload = _json.loads(row["payload_json"])
    assert payload["candidate_id"] == candidate_id
    assert payload["opportunity_angle"] == "frontier"
    assert payload["evidence"]["gaps"]
    assert payload["evidence"]["gaps"][0]["cross_verified"] == 1


@pytest.mark.usefixtures("_env_db")
def test_experiment_handoff_prepare_rejects_wrong_topic(db: Database) -> None:
    from research_harness_mcp.tools import execute_tool

    _, candidate_id = _seed_candidate(db)
    # Pass a topic_id that doesn't match candidate.scope
    result = execute_tool(
        "experiment_handoff_prepare",
        {"topic_id": 999, "candidate_id": candidate_id},
    )
    assert result["status"] == "error"


@pytest.mark.usefixtures("_env_db")
def test_experiment_handoff_submit_promotes_candidate(db: Database) -> None:
    from research_harness_mcp.tools import execute_tool

    topic_id, candidate_id = _seed_candidate(db)
    prep = execute_tool(
        "experiment_handoff_prepare",
        {"topic_id": topic_id, "candidate_id": candidate_id},
    )
    brief_id = prep["output"]["artifact_id"]

    submit = execute_tool(
        "experiment_handoff_submit",
        {
            "topic_id": topic_id,
            "brief_artifact_id": brief_id,
            "handoff_target": "codex",
            "summary": "queued in Codex for experiment kickoff",
        },
    )
    _assert_envelope(submit)
    assert submit["status"] == "success"
    out = submit["output"]
    assert out["success"] is True
    assert out["handoff_target"] == "codex"
    assert out["brief_artifact_id"] == brief_id

    # Candidate flipped to 'promoted'
    conn = db.connect()
    try:
        status = conn.execute(
            "SELECT status FROM research_candidates WHERE id = ?", (candidate_id,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert status == "promoted"


@pytest.mark.usefixtures("_env_db")
def test_experiment_handoff_submit_rejects_non_brief(db: Database) -> None:
    from research_harness_mcp.tools import execute_tool

    topic_id, _ = _seed_candidate(db)
    # Record a non-brief artifact
    recorded = execute_tool(
        "orchestrator_record_artifact",
        {
            "topic_id": topic_id,
            "stage": "build",
            "artifact_type": "literature_map",
            "payload": {"x": 1},
        },
    )
    other_id = recorded["output"]["artifact_id"]

    result = execute_tool(
        "experiment_handoff_submit",
        {
            "topic_id": topic_id,
            "brief_artifact_id": other_id,
            "handoff_target": "codex",
        },
    )
    assert result["status"] == "error"


@pytest.mark.usefixtures("_env_db")
def test_workflow_entry_reports_status_and_next_actions(db: Database) -> None:
    from research_harness_mcp.tools import execute_tool

    topic_id, _ = _seed_candidate(db)

    result = execute_tool("workflow_entry", {"topic_id": topic_id})
    _assert_envelope(result)
    assert result["status"] == "success"
    out = result["output"]
    assert out["success"] is True
    assert out["topic_id"] == topic_id
    assert out["gaps"]["total"] >= 1
    assert out["gaps"]["cross_verified"] >= 1
    assert out["candidates"]["live"] >= 1
    # At least one suggestion (experiment_handoff_prepare) should appear
    assert any("experiment_handoff_prepare" in a for a in out["next_actions"])
