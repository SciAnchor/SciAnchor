"""Tests for auto_runner.tool_dispatch — tool name → execution mapping."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_harness.orchestrator.artifacts import ArtifactManager
from research_harness.runtime import CapabilityManifest, RunSpec, RunVisibleInputs
from research_harness.skill import build_skill_runtime_contract
from research_harness.auto_runner.tool_dispatch import (
    ToolResult,
    _run_automated_adversarial as _run_automated_adversarial_impl,
    dispatch,
    dispatch_stage_tools,
    _build_primitive_params,
    _PRIMITIVE_TOOLS,
)
from research_harness._workflow.orchestrator.invariants import InvariantChecker
from research_harness.storage.db import Database


@pytest.fixture()
def db(tmp_path):
    d = Database(tmp_path / "test.db")
    d.migrate()
    return d


@pytest.fixture()
def svc(db):
    from research_harness.orchestrator.service import OrchestratorService

    return OrchestratorService(db)


def _setup_topic(db: Database, svc) -> None:
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test-topic')")
        conn.execute(
            "INSERT INTO projects (topic_id, name, description) VALUES (1, 'test', 'test')"
        )
        conn.commit()
    finally:
        conn.close()
    svc.resume_run(1)


def _write_bundle(tmp_path: Path) -> dict[str, str]:
    tex_path = tmp_path / "paper.tex"
    pdf_path = tmp_path / "paper.pdf"
    log_path = tmp_path / "paper.log"
    tex_path.write_text(
        "\\documentclass{article}\n\\begin{document}\nClean.\n\\end{document}\n",
        encoding="utf-8",
    )
    pdf_path.write_bytes(b"%PDF-1.4\n% test\n")
    log_path.write_text("", encoding="utf-8")
    return {
        "tex_path": str(tex_path),
        "compiled_pdf_path": str(pdf_path),
        "log_path": str(log_path),
        "target_profile": "AAAI-style-science-discovery",
    }


def test_primitive_tools_are_populated():
    assert "paper_search" in _PRIMITIVE_TOOLS
    assert "select_seeds" in _PRIMITIVE_TOOLS
    assert "expand_citations" in _PRIMITIVE_TOOLS
    assert len(_PRIMITIVE_TOOLS) >= 13


def test_unknown_tool_returns_error(db, svc):
    result = dispatch(
        "nonexistent_tool",
        db=db,
        svc=svc,
        topic_id=1,
        stage="init",
        context={},
    )
    assert not result.success
    assert "Unknown tool" in result.error


def test_orchestrator_status_dispatches(db, svc):
    # Create a topic first
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test-topic')")
        conn.commit()
    finally:
        conn.close()
    svc.resume_run(1)

    result = dispatch(
        "orchestrator_status",
        db=db,
        svc=svc,
        topic_id=1,
        stage="init",
        context={},
    )
    assert result.success
    assert "run" in result.output or "stage" in result.output


def test_paper_list_query(db, svc):
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test')")
        conn.execute(
            "INSERT INTO papers (id, title, year) VALUES (1, 'Test Paper', 2024)"
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')"
        )
        conn.commit()
    finally:
        conn.close()

    result = dispatch(
        "paper_list",
        db=db,
        svc=svc,
        topic_id=1,
        stage="build",
        context={},
    )
    assert result.success
    assert result.output["count"] == 1


def test_section_draft_dispatch_preserves_paper_production_context(
    db, svc, monkeypatch
):
    captured: dict[str, object] = {}

    class FakeBackend:
        def execute(self, name, **params):
            captured["name"] = name
            captured["params"] = params
            return type(
                "FakePrimitiveResult",
                (),
                {"success": True, "output": {"draft": {"content": "ok"}}, "error": ""},
            )()

    monkeypatch.setattr(
        "research_harness.auto_runner.tool_dispatch.create_backend",
        lambda *args, **kwargs: FakeBackend(),
    )
    paper_plan = {
        "schema_version": "rh.delivery.paper_plan.v1",
        "manuscript_logic_gate_report": {"status": "pass", "blockers": []},
        "fine_logic_audit_report": {"status": "pass", "blockers": []},
    }

    result = dispatch(
        "section_draft",
        db=db,
        svc=svc,
        topic_id=1,
        stage="write",
        context={
            "section": "results",
            "outline": "results outline",
            "evidence_ids": ["claim:1"],
            "paper_plan": paper_plan,
            "strict_evidence": True,
            "extra_instructions": "Preserve venue terminology.",
        },
    )

    assert result.success
    assert captured["name"] == "section_draft"
    params = captured["params"]
    assert params["paper_plan"] is paper_plan
    assert params["strict_evidence"] is True
    assert params["extra_instructions"] == "Preserve venue terminology."


def test_paper_search_params_preserve_paper_production_evidence_plan_context():
    context = {
        "query": "Evidence-grounded AI agents for literature review",
        "paper_production_evidence_plan": {
            "search_parameters": {
                "query": "Evidence-grounded AI agents for literature review",
                "max_results": 500,
                "auto_ingest": True,
                "local_only": False,
                "per_provider_limit": 30,
                "provider_allowlist": [
                    "arxiv",
                    "crossref",
                    "openalex",
                    "openreview",
                    "pubmed",
                ],
                "provider_denylist": ["semantic_scholar", "pasa"],
                "tier_filter": "ccf_a",
                "venue_filter": "",
            }
        },
        "max_results": 500,
        "auto_ingest": True,
        "local_only": False,
        "per_provider_limit": 30,
        "provider_allowlist": [
            "arxiv",
            "crossref",
            "openalex",
            "openreview",
            "pubmed",
        ],
        "provider_denylist": ["semantic_scholar", "pasa"],
        "tier_filter": "ccf_a",
        "venue_filter": "",
    }

    params = _build_primitive_params("paper_search", topic_id=1, context=context)

    assert params == {
        "topic_id": 1,
        "query": "Evidence-grounded AI agents for literature review",
        "auto_ingest": True,
        "max_results": 500,
        "local_only": False,
        "per_provider_limit": 30,
        "provider_allowlist": [
            "arxiv",
            "crossref",
            "openalex",
            "openreview",
            "pubmed",
        ],
        "provider_denylist": ["semantic_scholar", "pasa"],
        "tier_filter": "ccf_a",
        "venue_filter": "",
    }


def test_demo_seed_pool_skips_propose_literature_expansion_tools(db, svc, monkeypatch):
    _setup_topic(db, svc)
    calls: list[str] = []

    def fake_dispatch(tool_name, **kwargs):
        calls.append(tool_name)
        return ToolResult(tool=tool_name, success=True, output={"ok": True})

    monkeypatch.setattr(
        "research_harness.auto_runner.tool_dispatch.dispatch", fake_dispatch
    )
    monkeypatch.setattr(
        "research_harness.auto_runner.tool_dispatch._run_automated_adversarial",
        lambda proposal: {
            "verdict": "approved",
            "issues": [],
            "summary": "fixture review",
        },
    )

    result = dispatch_stage_tools(
        db=db,
        svc=svc,
        topic_id=1,
        stage="propose",
        tools=(
            "paper_search",
            "paper_ingest",
            "paper_acquire",
            "orchestrator_record_artifact",
        ),
        context={
            "paper_production_run_policy": {
                "schema_version": "rh.paper_production_run_policy.v1",
                "mode": "demo",
                "evidence_boundary": "demo_limited_seed_pool",
            }
        },
    )

    skipped = {
        item["tool"]: item
        for item in result["tool_results"]
        if item["output"].get("status") == "skipped"
    }
    assert {"paper_search", "paper_ingest", "paper_acquire"} <= set(skipped)
    assert calls == ["orchestrator_record_artifact"]
    assert result["errors"] == []
    assert all(item["success"] for item in skipped.values())


def _insert_seed_papers(db: Database, topic_id: int = 1, count: int = 3) -> None:
    conn = db.connect()
    try:
        for idx in range(1, count + 1):
            conn.execute(
                "INSERT INTO papers (id, title, year, venue) VALUES (?, ?, ?, ?)",
                (idx, f"Seed Paper {idx}", 2020 + idx, "Seed Venue"),
            )
            conn.execute(
                "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (?, ?, 'high')",
                (idx, topic_id),
            )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.parametrize("stage", ("init", "build"))
def test_demo_seed_pool_reuses_existing_seeds_without_literature_expansion(
    db, svc, monkeypatch, stage
):
    _setup_topic(db, svc)
    _insert_seed_papers(db, count=3)
    calls: list[str] = []
    expansion_tools = {
        "paper_search",
        "paper_ingest",
        "paper_acquire",
        "select_seeds",
        "expand_citations",
    }

    def fake_dispatch(tool_name, **kwargs):
        calls.append(tool_name)
        if tool_name in expansion_tools:
            raise AssertionError(f"{tool_name} should be skipped with existing seeds")
        return ToolResult(tool=tool_name, success=True, output={"ok": True})

    monkeypatch.setattr(
        "research_harness.auto_runner.tool_dispatch.dispatch", fake_dispatch
    )

    result = dispatch_stage_tools(
        db=db,
        svc=svc,
        topic_id=1,
        stage=stage,
        tools=(
            "paper_search",
            "paper_ingest",
            "select_seeds",
            "expand_citations",
            "paper_acquire",
            "paper_list",
        ),
        context={
            "paper_production_run_policy": {
                "schema_version": "rh.paper_production_run_policy.v1",
                "mode": "demo",
                "evidence_boundary": "demo_limited_seed_pool",
            }
        },
    )

    assert calls == ["paper_list"]
    skipped = {
        item["tool"]: item
        for item in result["tool_results"]
        if item["output"].get("status") == "skipped"
    }
    assert expansion_tools <= set(skipped)
    assert all(item["success"] for item in skipped.values())
    assert all(
        item["output"]["evidence_boundary"] == "demo_limited_seed_pool"
        for item in skipped.values()
    )
    if stage == "build":
        assert {
            "literature_map",
            "paper_pool_snapshot",
            "citation_expansion_report",
            "acquisition_report",
        } <= {artifact_type for artifact_type, _ in result["auto_artifacts"]}


def test_demo_seed_pool_without_existing_seeds_still_allows_init_literature_expansion(
    db, svc, monkeypatch
):
    _setup_topic(db, svc)
    calls: list[str] = []

    def fake_dispatch(tool_name, **kwargs):
        calls.append(tool_name)
        return ToolResult(tool=tool_name, success=True, output={"papers": []})

    monkeypatch.setattr(
        "research_harness.auto_runner.tool_dispatch.dispatch", fake_dispatch
    )

    result = dispatch_stage_tools(
        db=db,
        svc=svc,
        topic_id=1,
        stage="init",
        tools=("paper_search",),
        context={
            "paper_production_run_policy": {
                "schema_version": "rh.paper_production_run_policy.v1",
                "mode": "demo",
                "evidence_boundary": "demo_limited_seed_pool",
            }
        },
    )

    assert calls == ["paper_search"]
    assert result["tool_results"][0]["success"] is True
    assert result["tool_results"][0]["output"] == {"papers": []}


def test_demo_seed_pool_experiment_injects_local_smoke_before_validation(
    db, svc, monkeypatch
):
    _setup_topic(db, svc)
    calls: list[str] = []

    def fake_dispatch(tool_name, **kwargs):
        calls.append(tool_name)
        context = kwargs["context"]
        if tool_name == "code_validate":
            assert (
                "demo seed-pool smoke experiment"
                in context["_output_code_generate"]["files"]["main.py"]
            )
            return ToolResult(tool=tool_name, success=True, output={"ok": True})
        if tool_name == "experiment_run":
            return ToolResult(
                tool=tool_name,
                success=True,
                output={
                    "metrics": {
                        "demo_smoke/execution_success": 1.0,
                        "demo_smoke/reproducibility_score": 0.75,
                    },
                    "primary_metric_name": "execution_success",
                    "primary_metric_value": 1.0,
                },
            )
        if tool_name == "verified_registry_build":
            return ToolResult(
                tool=tool_name, success=True, output={"whitelist_size": 2}
            )
        if tool_name == "verified_registry_check":
            return ToolResult(tool=tool_name, success=True, output={"ok": True})
        return ToolResult(tool=tool_name, success=True, output={"ok": True})

    monkeypatch.setattr(
        "research_harness.auto_runner.tool_dispatch.dispatch", fake_dispatch
    )

    result = dispatch_stage_tools(
        db=db,
        svc=svc,
        topic_id=1,
        stage="experiment",
        tools=(
            "code_validate",
            "experiment_run",
            "verified_registry_build",
            "verified_registry_check",
        ),
        context={
            "study_spec": {"objective": "run local demo smoke"},
            "paper_production_run_policy": {
                "schema_version": "rh.paper_production_run_policy.v1",
                "mode": "demo",
                "evidence_boundary": "demo_limited_seed_pool",
            },
        },
    )

    assert calls == [
        "code_validate",
        "experiment_run",
        "verified_registry_build",
        "verified_registry_check",
    ]
    assert result["errors"] == []
    auto_types = [artifact_type for artifact_type, _ in result["auto_artifacts"]]
    assert "experiment_code" in auto_types
    assert "experiment_result" in auto_types
    assert "verified_registry" in auto_types


def test_demo_seed_pool_experiment_skips_external_codegen_and_runs_smoke(
    db, svc, monkeypatch
):
    _setup_topic(db, svc)
    calls: list[str] = []

    def fake_dispatch(tool_name, **kwargs):
        calls.append(tool_name)
        if tool_name == "code_generate":
            raise AssertionError("demo smoke experiment should not call code_generate")
        context = kwargs["context"]
        if tool_name == "code_validate":
            assert (
                "demo seed-pool smoke experiment"
                in context["_output_code_generate"]["files"]["main.py"]
            )
            return ToolResult(tool=tool_name, success=True, output={"ok": True})
        if tool_name == "experiment_run":
            return ToolResult(
                tool=tool_name,
                success=True,
                output={
                    "metrics": {"demo_smoke/execution_success": 1.0},
                    "primary_metric_name": "execution_success",
                    "primary_metric_value": 1.0,
                },
            )
        if tool_name == "verified_registry_build":
            return ToolResult(
                tool=tool_name, success=True, output={"whitelist_size": 1}
            )
        if tool_name == "verified_registry_check":
            return ToolResult(tool=tool_name, success=True, output={"ok": True})
        return ToolResult(tool=tool_name, success=True, output={"ok": True})

    monkeypatch.setattr(
        "research_harness.auto_runner.tool_dispatch.dispatch", fake_dispatch
    )

    result = dispatch_stage_tools(
        db=db,
        svc=svc,
        topic_id=1,
        stage="experiment",
        tools=(
            "code_generate",
            "code_validate",
            "experiment_run",
            "verified_registry_build",
            "verified_registry_check",
        ),
        context={
            "study_spec": {"objective": "run local demo smoke"},
            "paper_production_run_policy": {
                "schema_version": "rh.paper_production_run_policy.v1",
                "mode": "demo",
                "evidence_boundary": "demo_limited_seed_pool",
            },
        },
    )

    assert calls == [
        "code_validate",
        "experiment_run",
        "verified_registry_build",
        "verified_registry_check",
    ]
    skipped = [
        item
        for item in result["tool_results"]
        if item["tool"] == "code_generate" and item["output"].get("status") == "skipped"
    ]
    assert skipped
    assert result["errors"] == []
    auto_types = [artifact_type for artifact_type, _ in result["auto_artifacts"]]
    assert "experiment_code" in auto_types
    assert "experiment_result" in auto_types
    assert "verified_registry" in auto_types


def test_demo_seed_pool_write_injects_report_only_paper_plan(db, svc, monkeypatch):
    _setup_topic(db, svc)
    captured: dict[str, object] = {}

    def fake_dispatch(tool_name, **kwargs):
        captured.setdefault("calls", []).append(tool_name)
        if tool_name == "section_draft":
            captured["paper_plan"] = kwargs["context"].get("paper_plan")
            return ToolResult(
                tool=tool_name,
                success=True,
                output={"draft": {"content": "demo section"}},
            )
        return ToolResult(tool=tool_name, success=True, output={"ok": True})

    monkeypatch.setattr(
        "research_harness.auto_runner.tool_dispatch.dispatch", fake_dispatch
    )

    result = dispatch_stage_tools(
        db=db,
        svc=svc,
        topic_id=1,
        stage="write",
        tools=("section_draft",),
        context={
            "section": "introduction",
            "paper_production_run_policy": {
                "schema_version": "rh.paper_production_run_policy.v1",
                "mode": "demo",
                "evidence_boundary": "demo_limited_seed_pool",
            },
            "target_venue": "Journal of Hydrometeorology",
        },
    )

    paper_plan = captured["paper_plan"]
    assert isinstance(paper_plan, dict)
    assert paper_plan["manuscript_logic_gate_report"]["status"] == "pass"
    assert paper_plan["fine_logic_audit_report"]["status"] == "pass"
    assert paper_plan["submission_readiness"] == "not_submission_ready"
    assert paper_plan["target_venue"] == "Journal of Hydrometeorology"
    assert paper_plan["automation_scope"] == "paper_production_demo_pdf_smoke"
    assert result["errors"] == []
    paper_plan_ids = [
        artifact_id
        for artifact_type, artifact_id in result["auto_artifacts"]
        if artifact_type == "PAPER_PLAN"
    ]
    assert paper_plan_ids
    artifact = ArtifactManager(db).get(paper_plan_ids[-1])
    assert artifact is not None
    assert artifact.artifact_type == "PAPER_PLAN"
    assert artifact.payload["submission_readiness"] == "not_submission_ready"


def test_demo_seed_pool_write_produces_local_pdf_closure(db, svc, tmp_path):
    _setup_topic(db, svc)

    result = dispatch_stage_tools(
        db=db,
        svc=svc,
        topic_id=1,
        stage="write",
        tools=("section_draft", "latex_compile", "publication_run"),
        context={
            "sections_to_draft": [
                "abstract",
                "method",
                "experiment_summary",
                "limitations",
            ],
            "output_dir": str(tmp_path / "paper-production-smoke"),
            "paper_production_run_policy": {
                "schema_version": "rh.paper_production_run_policy.v1",
                "mode": "demo",
                "evidence_boundary": "demo_limited_seed_pool",
            },
            "target_venue": "Journal of Hydrometeorology",
            "venue": "Journal of Hydrometeorology",
            "target_profile": "Journal of Hydrometeorology demo smoke",
        },
    )

    assert result["errors"] == []
    auto_types = [artifact_type for artifact_type, _ in result["auto_artifacts"]]
    assert "draft_pack" in auto_types
    assert "final_bundle" in auto_types
    assert "process_summary" in auto_types
    assert "publication_pack" in auto_types

    artifacts = ArtifactManager(db)
    final_bundle_id = [
        artifact_id
        for artifact_type, artifact_id in result["auto_artifacts"]
        if artifact_type == "final_bundle"
    ][-1]
    final_bundle = artifacts.get(final_bundle_id)
    assert final_bundle is not None
    assert final_bundle.stage == "write"
    assert final_bundle.payload["status"] == "ready"
    pdf_path = final_bundle.payload["compiled_pdf_path"]
    assert Path(pdf_path).is_file()
    assert Path(pdf_path).suffix == ".pdf"

    publication_pack_id = [
        artifact_id
        for artifact_type, artifact_id in result["auto_artifacts"]
        if artifact_type == "publication_pack"
    ][-1]
    publication_pack = artifacts.get(publication_pack_id)
    assert publication_pack is not None
    assert publication_pack.stage == "write"
    assert publication_pack.payload["outputs"]["manuscript_pdf_path"] == pdf_path
    assert publication_pack.payload["submission_ready"] is False
    assert publication_pack.payload["readiness_scope"] == "demo_pdf_smoke"
    source_artifacts = publication_pack.payload["source_artifacts"]
    assert {item["artifact_type"]: item["artifact_id"] for item in source_artifacts}[
        "final_bundle"
    ] == final_bundle_id
    assert publication_pack.payload["artifact_refs"]["final_bundle"] == (
        f"project_artifacts:{final_bundle_id}:final_bundle"
    )
    assert InvariantChecker(db).check_artifact_trace_linkage(1, "write") == []


def test_pdf_closure_dispatch_uses_venue_overlay_context(db, svc, monkeypatch):
    captured: dict[str, dict[str, object]] = {}

    class FakeBackend:
        def execute(self, name, **params):
            captured[name] = params
            return type(
                "FakePrimitiveResult",
                (),
                {"success": True, "output": {"ok": True}, "error": ""},
            )()

    monkeypatch.setattr(
        "research_harness.auto_runner.tool_dispatch.create_backend",
        lambda *args, **kwargs: FakeBackend(),
    )
    context = {
        "_drafted_sections": ["abstract"],
        "_output_section_draft_abstract": {"text": "Abstract body."},
        "venue": "NeurIPS",
        "target_venue": "Nature",
        "target_profile": "Nature Article",
        "venue_overlay": {
            "format_family": "nature-article",
            "anonymization_required": False,
        },
        "output_dir": "/tmp/rh-paper",
        "title": "Evidence-first paper",
        "abstract": "Structured abstract.",
        "authors": ["Research Harness"],
        "bibliography_entries": ["@article{seed,title={Seed}}"],
    }

    latex = dispatch(
        "latex_compile",
        db=db,
        svc=svc,
        topic_id=1,
        stage="write",
        context=context,
    )
    publication = dispatch(
        "publication_run",
        db=db,
        svc=svc,
        topic_id=1,
        stage="write",
        context=context,
    )

    assert latex.success
    assert publication.success
    assert captured["latex_compile"]["template"] == "nature-article"
    assert captured["latex_compile"]["title"] == "Evidence-first paper"
    assert captured["latex_compile"]["abstract"] == "Structured abstract."
    assert captured["latex_compile"]["authors"] == ["Research Harness"]
    assert captured["latex_compile"]["bibliography_entries"] == [
        "@article{seed,title={Seed}}"
    ]
    assert captured["publication_run"]["target_profile"] == "Nature Article"


def test_publication_backfill_params_use_paper_production_closure_plan():
    context = {
        "target_profile": "NeurIPS 2026",
        "paper_production_closure_plan": {
            "publication_components": [
                "process_summary",
                "citation_integrity",
                "final_bundle",
                "publication_pack",
            ]
        },
        "publication_components": [
            "process_summary",
            "citation_integrity",
            "final_bundle",
            "publication_pack",
        ],
        "record_artifact": True,
    }

    backfill = _build_primitive_params(
        "publication_pack_backfill",
        topic_id=1,
        context=context,
    )
    run = _build_primitive_params("publication_run", topic_id=1, context=context)

    assert backfill == {
        "topic_id": 1,
        "target_profile": "NeurIPS 2026",
        "components": [
            "process_summary",
            "citation_integrity",
            "final_bundle",
            "publication_pack",
        ],
        "record_artifact": True,
    }
    assert run == backfill


def test_dispatch_stage_tools_runs_multiple(db, svc):
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (id, name) VALUES (1, 'test-topic')")
        conn.commit()
    finally:
        conn.close()
    svc.resume_run(1)

    result = dispatch_stage_tools(
        db=db,
        svc=svc,
        topic_id=1,
        stage="init",
        tools=("paper_list",),
        context={},
    )
    assert "summary" in result
    assert "Stage init" in result["summary"]
    trace_ids = [
        artifact_id
        for artifact_type, artifact_id in result["auto_artifacts"]
        if artifact_type == "run_trace"
    ]
    assert trace_ids
    trace = ArtifactManager(db).get(trace_ids[-1])
    assert trace is not None
    assert trace.artifact_type == "run_trace"
    assert trace.payload["schema_version"] == "rh.trace.v0"
    assert trace.payload["inputs"]["stage"] == "init"
    assert any(step["kind"] == "tool_call" for step in trace.payload.get("steps", []))


def test_init_auto_topic_brief_has_gate_scope_and_no_record_artifact_noise(db, svc):
    _setup_topic(db, svc)

    result = dispatch_stage_tools(
        db=db,
        svc=svc,
        topic_id=1,
        stage="init",
        tools=("orchestrator_record_artifact",),
        context={
            "topic_description": "Evidence-grounded AI agents for literature review",
            "target_venue": "NeurIPS 2026",
            "topic_venue_contract": {
                "non_goals": [
                    "Do not claim PDF readiness before final-bundle and publication-pack gates pass."
                ]
            },
        },
    )

    assert result["errors"] == []
    assert result["tool_results"][0]["success"] is True
    assert result["tool_results"][0]["output"]["skipped"] is True
    topic_brief_ids = [
        artifact_id
        for artifact_type, artifact_id in result["auto_artifacts"]
        if artifact_type == "topic_brief"
    ]
    assert topic_brief_ids
    topic_brief = ArtifactManager(db).get(topic_brief_ids[-1])
    assert topic_brief is not None
    assert topic_brief.payload["scope"] == (
        "Evidence-grounded AI agents for literature review"
    )
    assert topic_brief.payload["target_venue"] == "NeurIPS 2026"
    assert topic_brief.payload["exclusion_criteria"] == [
        "Do not claim PDF readiness before final-bundle and publication-pack gates pass."
    ]


def test_dispatch_stage_tools_blocks_before_tools_when_runtime_gate_fails(
    db, svc, monkeypatch
):
    _setup_topic(db, svc)
    calls: list[str] = []

    def fake_dispatch(tool_name, **kwargs):
        calls.append(tool_name)
        raise AssertionError("dispatch should not run after runtime gate failure")

    monkeypatch.setattr(
        "research_harness.auto_runner.tool_dispatch.dispatch", fake_dispatch
    )
    capability = CapabilityManifest(
        name="paper-list-reader",
        version="0.1.0",
        capability_type="evaluator",
        owner="core",
        license="MIT",
        input_schema="rh.schema.input.paper_list_reader.v0",
        output_schema="rh.schema.artifact.paper_list_report.v0",
        allowed_tools=("paper_list",),
        forbidden_tools=("external.publish",),
        required_artifacts=("final_bundle",),
        produced_artifacts=("paper_list_report",),
        guardrails=("active_final_bundle_required",),
    )
    spec = RunSpec(
        run_id="run.dispatch.blocked",
        task_type="evaluation",
        topic_id=1,
        objective="Verify runtime gate blocks unsafe dispatch.",
        visible_inputs=RunVisibleInputs(
            artifact_refs=("artifact:publication_pack:3",),
        ),
        required_outputs=("unrelated_report",),
        capability_policy={
            "allowed_capabilities": ("other-capability",),
            "allowed_tools": ("paper_list", "external.publish"),
        },
        guardrails={"input": ()},
    )

    result = dispatch_stage_tools(
        db=db,
        svc=svc,
        topic_id=1,
        stage="write",
        tools=("paper_list",),
        context={},
        capability_manifest=capability,
        run_spec=spec,
    )

    assert calls == []
    assert result["runtime_gate"]["passed"] is False
    assert "capability_allowed" in result["errors"][0]
    assert result["tool_results"][0]["tool"] == "runtime_contract"
    trace_ids = [
        artifact_id
        for artifact_type, artifact_id in result["auto_artifacts"]
        if artifact_type == "run_trace"
    ]
    assert trace_ids
    trace = ArtifactManager(db).get(trace_ids[-1])
    assert trace is not None
    assert trace.artifact_type == "run_trace"
    assert trace.payload["status"] == "failed"
    assert any(step["kind"] == "guardrail" for step in trace.payload["steps"])


def test_dispatch_stage_tools_runs_after_runtime_gate_passes(db, svc, monkeypatch):
    calls: list[str] = []

    def fake_dispatch(tool_name, **kwargs):
        calls.append(tool_name)
        return type(
            "FakeResult",
            (),
            {"tool": tool_name, "success": True, "output": {"ok": True}, "error": ""},
        )()

    monkeypatch.setattr(
        "research_harness.auto_runner.tool_dispatch.dispatch", fake_dispatch
    )
    capability = CapabilityManifest(
        name="paper-list-reader",
        version="0.1.0",
        capability_type="evaluator",
        owner="core",
        license="MIT",
        input_schema="rh.schema.input.paper_list_reader.v0",
        output_schema="rh.schema.artifact.paper_list_report.v0",
        allowed_tools=("paper_list",),
        required_artifacts=("final_bundle",),
        produced_artifacts=("paper_list_report",),
        guardrails=("active_final_bundle_required",),
    )
    spec = RunSpec(
        run_id="run.dispatch.allowed",
        task_type="evaluation",
        topic_id=1,
        objective="Verify runtime gate allows valid dispatch.",
        visible_inputs=RunVisibleInputs(
            artifact_refs=("artifact:final_bundle:3",),
        ),
        required_outputs=("paper_list_report",),
        capability_policy={
            "allowed_capabilities": ("paper-list-reader",),
            "allowed_tools": ("paper_list",),
        },
        guardrails={"input": ("active_final_bundle_required",)},
    )

    result = dispatch_stage_tools(
        db=db,
        svc=svc,
        topic_id=1,
        stage="write",
        tools=("paper_list",),
        context={},
        capability_manifest=capability,
        run_spec=spec,
    )

    assert calls == ["paper_list"]
    assert result["runtime_gate"]["passed"] is True
    assert result["tool_results"][0]["success"] is True


@pytest.mark.parametrize("stage", ("analyze", "propose", "experiment", "write"))
def test_demo_seed_pool_skips_literature_expansion_after_build(
    db, svc, monkeypatch, stage
):
    _setup_topic(db, svc)
    calls: list[str] = []
    expansion_tools = {
        "paper_search",
        "paper_ingest",
        "paper_acquire",
        "select_seeds",
        "expand_citations",
    }

    def fake_dispatch(tool_name, **kwargs):
        calls.append(tool_name)
        if tool_name in expansion_tools:
            raise AssertionError(
                f"{tool_name} should be skipped in demo seed-pool mode"
            )
        return type(
            "FakeResult",
            (),
            {
                "tool": tool_name,
                "success": True,
                "output": {"ok": True},
                "error": "",
            },
        )()

    monkeypatch.setattr(
        "research_harness.auto_runner.tool_dispatch.dispatch", fake_dispatch
    )

    result = dispatch_stage_tools(
        db=db,
        svc=svc,
        topic_id=1,
        stage=stage,
        tools=(
            "paper_search",
            "paper_ingest",
            "select_seeds",
            "expand_citations",
            "paper_acquire",
            "paper_list",
        ),
        context={
            "paper_production_run_policy": {
                "schema_version": "rh.paper_production_run_policy.v1",
                "mode": "demo",
                "evidence_boundary": "demo_limited_seed_pool",
            },
            "research_wiki_preflight": {
                "schema_version": "research_wiki_preflight.v1",
                "paper_wiki_status": "loaded",
                "topic_id": 1,
            },
        },
    )

    assert calls == ["paper_list"]
    skipped = [tr for tr in result["tool_results"] if tr["tool"] in expansion_tools]
    assert {tr["tool"] for tr in skipped} == expansion_tools
    assert all(tr["success"] is True for tr in skipped)
    assert all(tr["output"]["status"] == "skipped" for tr in skipped)
    assert all(
        tr["output"]["evidence_boundary"] == "demo_limited_seed_pool" for tr in skipped
    )
    assert all(
        "reuses the build-stage seed pool after build" in tr["output"]["reason"]
        for tr in skipped
    )
    assert result["errors"] == []


def test_dispatch_stage_tools_executes_final_bundle_quality_skill(
    db, svc, tmp_path, monkeypatch
):
    calls: list[str] = []

    def fake_dispatch(tool_name, **kwargs):
        calls.append(tool_name)
        raise AssertionError(
            "stage policy tools should not run in skill execution mode"
        )

    monkeypatch.setattr(
        "research_harness.auto_runner.tool_dispatch.dispatch", fake_dispatch
    )
    _setup_topic(db, svc)
    final_bundle = svc.record_artifact(
        topic_id=1,
        stage="write",
        artifact_type="final_bundle",
        title="Final bundle",
        payload=_write_bundle(tmp_path),
    )
    repo_root = next(
        p
        for p in Path(__file__).resolve().parents
        if (p / "skills" / "final-bundle-quality" / "skill.yaml").is_file()
    )
    contract = build_skill_runtime_contract(
        repo_root,
        "final-bundle-quality",
        topic_id=1,
        artifact_refs=(f"artifact:final_bundle:{final_bundle.id}",),
        literal_inputs={"mode": "quality_scan"},
        run_id="run.final_bundle_quality.dispatch",
    )

    result = dispatch_stage_tools(
        db=db,
        svc=svc,
        topic_id=1,
        stage="evaluate",
        tools=("paper_list",),
        context={},
        capability_manifest=contract["capability_manifest"],
        run_spec=contract["run_spec"],
        execute_skill=True,
    )

    assert calls == []
    assert result["runtime_gate"]["passed"] is True
    assert len(result["tool_results"]) == 1
    assert result["tool_results"][0]["tool"] == "final-bundle-quality"
    assert result["tool_results"][0]["success"] is True
    assert result["tool_results"][0]["error"] == ""
    report_id = result["tool_results"][0]["output"]["artifact_id"]
    trace_id = result["tool_results"][0]["output"]["run_trace_artifact_id"]
    grade_id = result["tool_results"][0]["output"]["runtime_trace_grade_artifact_id"]
    assert ("final_bundle_quality_report", report_id) in result["auto_artifacts"]
    assert ("run_trace", trace_id) in result["auto_artifacts"]
    assert ("runtime_trace_grade", grade_id) in result["auto_artifacts"]
    artifacts = ArtifactManager(db)
    report = artifacts.get(report_id)
    assert report is not None
    assert report.artifact_type == "final_bundle_quality_report"
    assert report.payload["source_artifact_id"] == final_bundle.id
    trace = artifacts.get(trace_id)
    assert trace is not None
    assert trace.artifact_type == "run_trace"
    assert trace.payload["outputs"]["artifact_ids"] == [report_id]
    grade = artifacts.get(grade_id)
    assert grade is not None
    assert grade.artifact_type == "runtime_trace_grade"
    assert grade.payload["decision"] == "pass"


def test_dispatch_stage_tools_executes_publication_pack_skill(db, svc, monkeypatch):
    calls: list[str] = []

    def fake_dispatch(tool_name, **kwargs):
        calls.append(tool_name)
        raise AssertionError(
            "stage policy tools should not run in skill execution mode"
        )

    monkeypatch.setattr(
        "research_harness.auto_runner.tool_dispatch.dispatch", fake_dispatch
    )
    _setup_topic(db, svc)
    artifacts = ArtifactManager(db)
    draft = artifacts.record(
        topic_id=1,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack",
        payload={"sections": {"abstract": "Evidence-backed abstract [paper:1]."}},
    )
    evidence = artifacts.record(
        topic_id=1,
        stage="analyze",
        artifact_type="evidence_pack",
        title="Evidence Pack",
        payload={"claims": [{"claim_id": "c1", "paper_ids": [1]}]},
    )
    repo_root = next(
        p
        for p in Path(__file__).resolve().parents
        if (p / "skills" / "publication-pack" / "skill.yaml").is_file()
    )
    contract = build_skill_runtime_contract(
        repo_root,
        "publication-pack",
        topic_id=1,
        artifact_refs=(
            f"artifact:draft_pack:{draft.id}",
            f"artifact:evidence_pack:{evidence.id}",
        ),
        literal_inputs={"target_profile": "high-impact-general"},
        run_id="run.publication_pack.dispatch",
    )

    result = dispatch_stage_tools(
        db=db,
        svc=svc,
        topic_id=1,
        stage="write",
        tools=("paper_list",),
        context={},
        capability_manifest=contract["capability_manifest"],
        run_spec=contract["run_spec"],
        execute_skill=True,
    )

    assert calls == []
    assert result["runtime_gate"]["passed"] is True
    assert len(result["tool_results"]) == 1
    assert result["tool_results"][0]["tool"] == "publication-pack"
    assert result["tool_results"][0]["success"] is True
    assert result["tool_results"][0]["error"] == ""
    pack_id = result["tool_results"][0]["output"]["artifact_id"]
    trace_id = result["tool_results"][0]["output"]["run_trace_artifact_id"]
    grade_id = result["tool_results"][0]["output"]["runtime_trace_grade_artifact_id"]
    assert ("publication_pack", pack_id) in result["auto_artifacts"]
    assert ("run_trace", trace_id) in result["auto_artifacts"]
    assert ("runtime_trace_grade", grade_id) in result["auto_artifacts"]

    pack = artifacts.get(pack_id)
    assert pack is not None
    assert pack.artifact_type == "publication_pack"
    assert pack.payload["schema_version"] == "rh.schema.artifact.publication_pack.v0"
    assert pack.payload["components"]["manuscript_sections"]["artifact_id"] == draft.id
    assert pack.payload["components"]["evidence_pack"]["artifact_id"] == evidence.id
    trace = artifacts.get(trace_id)
    assert trace is not None
    assert trace.artifact_type == "run_trace"
    assert trace.payload["run_id"] == "run.publication_pack.dispatch"
    assert trace.payload["outputs"]["artifact_ids"] == [pack_id]
    grade = artifacts.get(grade_id)
    assert grade is not None
    assert grade.artifact_type == "runtime_trace_grade"
    assert grade.payload["decision"] == "pass"


def test_automated_adversarial_invalid_verdict_fails_closed(monkeypatch):
    monkeypatch.setattr(
        "research_harness.execution.llm_primitives._get_client",
        lambda **kwargs: object(),
    )
    monkeypatch.setattr(
        "research_harness.execution.llm_primitives._client_chat",
        lambda client, prompt: '{"verdict":"maybe"}',
    )
    monkeypatch.setattr(
        "research_harness.execution.llm_primitives._parse_json",
        lambda raw, primitive: {"verdict": "maybe", "summary": "invalid"},
    )

    result = _run_automated_adversarial_impl({"direction": "test direction"})

    assert result["verdict"] == "revise"
    assert result["issues"][0]["severity"] == "critical"
    assert result["issues"][0]["category"] == "review_unavailable"


def test_automated_adversarial_exception_fails_closed(monkeypatch):
    def fail_get_client(**kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(
        "research_harness.execution.llm_primitives._get_client",
        fail_get_client,
    )

    result = _run_automated_adversarial_impl({"direction": "test direction"})

    assert result["verdict"] == "revise"
    assert result["issues"][0]["severity"] == "critical"
    assert "provider unavailable" in result["summary"]


class TestFigureGenerateWiring:
    """figure_generate joins the write stage with provider-aware gating.

    Without this, the pipeline recorded figure plans but never generated
    figures, so a ready illustration backend still produced PENDING
    fallbacks — which the write gate now blocks.
    """

    def _plan_context(self):
        return {
            "_output_figure_plan": {
                "items": [
                    {
                        "figure_id": "F1",
                        "kind": "figure",
                        "title": "Architecture",
                        "caption": "c",
                    }
                ]
            },
            "_output_figure_suite_plan": {
                "spec": {
                    "figures": [{"figure_id": "F1", "role": "method"}],
                    "target_venue": "IPM",
                    "venue_figure_grammar": {"style_profile": "stem_conference"},
                    "figure_modules": {"method": "illustration"},
                }
            },
            "output_dir": "/tmp/rh-out",
        }

    def test_skipped_without_provider(self):
        from research_harness.auto_runner.tool_dispatch import (
            _context_bound_tool_skip_reason,
        )

        reason = _context_bound_tool_skip_reason(
            "figure_generate", self._plan_context()
        )
        assert "no figure provider configured" in reason

    def test_skipped_without_plan_items(self, monkeypatch):
        from research_harness.auto_runner.tool_dispatch import (
            _context_bound_tool_skip_reason,
        )

        monkeypatch.setenv("RESEARCH_HARNESS_FIGURE_MODEL", "gpt-image-2")
        reason = _context_bound_tool_skip_reason("figure_generate", {})
        assert "requires figure_plan items" in reason

    def test_skipped_without_predraw_fields(self, monkeypatch):
        from research_harness.auto_runner.tool_dispatch import (
            _context_bound_tool_skip_reason,
        )

        monkeypatch.setenv("RESEARCH_HARNESS_FIGURE_MODEL", "gpt-image-2")
        reason = _context_bound_tool_skip_reason(
            "figure_generate",
            {"_output_figure_plan": {"items": [{"figure_id": "F1", "kind": "figure"}]}},
        )
        assert "missing pre-draw fields" in reason
        assert "cannot draw" in reason

    def test_runs_with_explicit_figure_model(self, monkeypatch):
        from research_harness.auto_runner.tool_dispatch import (
            _context_bound_tool_skip_reason,
        )

        monkeypatch.setenv("RESEARCH_HARNESS_FIGURE_MODEL", "gpt-image-2")
        reason = _context_bound_tool_skip_reason(
            "figure_generate", self._plan_context()
        )
        assert reason == ""

    def test_runs_with_ready_illustration_backend(self, monkeypatch):
        from research_harness.auto_runner.tool_dispatch import (
            _context_bound_tool_skip_reason,
        )

        monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
        reason = _context_bound_tool_skip_reason(
            "figure_generate", self._plan_context()
        )
        assert reason == ""

    def test_params_prefer_illustration_and_carry_plan_items(self, monkeypatch):
        from research_harness.auto_runner.tool_dispatch import (
            _build_primitive_params,
        )

        monkeypatch.delenv("RESEARCH_HARNESS_FIGURE_MODEL", raising=False)
        params = _build_primitive_params(
            "figure_generate", topic_id=5, context=self._plan_context()
        )
        assert params["items"][0]["figure_id"] == "F1"
        assert params["output_dir"].endswith("figures")
        assert params["model"] == "illustration"

    def test_params_respect_explicit_model_env(self, monkeypatch):
        from research_harness.auto_runner.tool_dispatch import (
            _build_primitive_params,
        )

        monkeypatch.setenv("RESEARCH_HARNESS_FIGURE_MODEL", "gpt-image-2")
        params = _build_primitive_params(
            "figure_generate", topic_id=5, context=self._plan_context()
        )
        assert "model" not in params

    def test_write_policy_orders_generate_after_plan(self):
        from research_harness.auto_runner.stage_policy import get_policy

        tools = get_policy("write").tools
        assert "figure_generate" in tools
        assert tools.index("figure_suite_plan") < tools.index("figure_plan")
        assert tools.index("figure_plan") < tools.index("figure_suite_render")
        assert tools.index("figure_suite_render") < tools.index("figure_generate")


def test_section_review_params_carry_the_target_venue():
    """section_review caps the abstract band at the venue's own limit, so the auto-runner passes the
    venue it is writing for (target_venue, else venue, else empty)."""
    from research_harness.auto_runner.tool_dispatch import _build_primitive_params

    base = {
        "_drafted_sections": ["abstract"],
        "_output_section_draft_abstract": {"text": "words"},
    }
    for context, expected in (
        ({"target_venue": "npj Digital Medicine"}, "npj Digital Medicine"),
        ({"venue": "Scientific Reports"}, "Scientific Reports"),
        ({}, ""),
    ):
        params = _build_primitive_params(
            "section_review", topic_id=1, context={**base, **context}
        )
        assert params["target_venue"] == expected and params["section"] == "abstract"
