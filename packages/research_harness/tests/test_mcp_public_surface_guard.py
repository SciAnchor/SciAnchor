from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = next(
    path
    for path in Path(__file__).resolve().parents
    if (path / "AGENTS.md").exists() and (path / "scripts").exists()
)


def load_guard_module():
    script_path = REPO_ROOT / "scripts" / "check-mcp-public-surface.py"
    spec = importlib.util.spec_from_file_location("mcp_surface_guard", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mcp_public_surface_guard_accepts_current_contract():
    module = load_guard_module()

    errors = module.validate_public_surface(
        audit_text=module.AUDIT_PATH.read_text(encoding="utf-8"),
        surface_text=module.SURFACE_PATH.read_text(encoding="utf-8"),
    )

    assert errors == []


def test_topic_knowledge_snapshot_is_not_public_mcp_tool_contract():
    module = load_guard_module()

    names = module.parse_public_names_from_source(
        module.SURFACE_PATH.read_text(encoding="utf-8")
    )

    assert "topic_knowledge_snapshot" not in names
    assert "cross_topic_knowledge_atlas" not in names
    assert "topic_knowledge_status" in names
    assert "topic_knowledge_refresh" in names
    assert "cross_topic_atlas" in names
    assert not any(name.startswith("semantic_") for name in names)


def test_delivery_snapshot_remains_python_only_not_public_transport(db):
    module = load_guard_module()
    from research_harness.service import ResearchService

    names = module.parse_public_names_from_source(
        module.SURFACE_PATH.read_text(encoding="utf-8")
    )
    commands = {
        command.name: command for command in ResearchService(db=db).list_commands()
    }
    root = module.ROOT
    transport_sources = [
        root
        / "packages"
        / "research_harness"
        / "research_harness"
        / "cli_registration.py",
        root
        / "packages"
        / "research_harness_mcp"
        / "research_harness_mcp"
        / "http_non_zotero_routes.py",
        root
        / "packages"
        / "research_harness_mcp"
        / "research_harness_mcp"
        / "tool_surface.py",
    ]
    transport_text = "\n".join(
        path.read_text(encoding="utf-8") for path in transport_sources
    )

    assert "delivery_paper_production_snapshot" not in names
    assert commands["delivery_paper_production_snapshot"].visibility == ("python",)
    assert "delivery_paper_production_snapshot" not in transport_text


def test_topic_knowledge_package_all_keeps_private_helpers_unexported():
    import research_harness.knowledge as knowledge

    exported = set(knowledge.__all__)
    private_helpers = {
        "ADVISORY_KNOWLEDGE_ACTIONS",
        "BLOCKED_KNOWLEDGE_ACTIONS",
        "EXECUTABLE_KNOWLEDGE_ACTIONS",
        "FORBIDDEN_KNOWLEDGE_RUN_INPUTS",
        "KnowledgeActionRecommendation",
        "KnowledgeContextPack",
        "KnowledgeContextRequest",
        "KnowledgeExecutionPlan",
        "KnowledgeEvaluationCase",
        "KnowledgeEvaluationOutcome",
        "KnowledgeLoopReport",
        "assemble_knowledge_context",
        "build_knowledge_execution_plan",
        "build_private_knowledge_evaluation_corpus",
        "evaluate_knowledge_quality",
        "evaluate_private_knowledge_corpus",
        "knowledge_execution_plan_to_runspec",
        "plan_knowledge_action",
        "run_private_knowledge_execution_loop",
        "simulate_private_knowledge_dry_run_plan",
    }

    assert exported.isdisjoint(private_helpers)
    assert {
        "TopicKnowledgeSnapshot",
        "build_topic_knowledge_snapshot",
        "get_latest_topic_knowledge_snapshot",
    }.issubset(exported)


def test_mcp_public_surface_guard_detects_doc_table_drift():
    module = load_guard_module()
    audit_text = module.AUDIT_PATH.read_text(encoding="utf-8").replace(
        "| `skill_get` | surface | Read one workflow skill package. |\n",
        "",
    )

    errors = module.validate_public_surface(
        audit_text=audit_text,
        surface_text=module.SURFACE_PATH.read_text(encoding="utf-8"),
    )

    assert any("Tier A table does not match" in error for error in errors)


def test_mcp_public_surface_guard_detects_count_drift():
    module = load_guard_module()
    audit_text = module.AUDIT_PATH.read_text(encoding="utf-8").replace(
        "- Public advertised MCP tools: 54",
        "- Public advertised MCP tools: 40",
    )

    errors = module.validate_public_surface(
        audit_text=audit_text,
        surface_text=module.SURFACE_PATH.read_text(encoding="utf-8"),
    )

    assert any("advertised count" in error for error in errors)
