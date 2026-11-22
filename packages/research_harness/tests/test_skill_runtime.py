from __future__ import annotations

from pathlib import Path

from research_harness.orchestrator.artifacts import ArtifactManager
from research_harness.orchestrator.service import OrchestratorService
from research_harness.skill import build_skill_runtime_contract
from research_harness.storage.db import Database


def _setup_topic(db: Database) -> OrchestratorService:
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (id, name, description) VALUES (1, 'runtime-topic', 'runtime test')"
        )
        conn.execute(
            "INSERT INTO projects (topic_id, name, description) VALUES (1, 'runtime', 'runtime test')"
        )
        conn.commit()
    finally:
        conn.close()
    svc = OrchestratorService(db)
    svc.resume_run(1)
    return svc


def _repo_root() -> Path:
    return next(
        p
        for p in Path(__file__).resolve().parents
        if (p / "skills" / "final-bundle-quality" / "skill.yaml").is_file()
    )


def _write_bundle(tmp_path: Path) -> dict[str, str]:
    tex_path = tmp_path / "paper.tex"
    pdf_path = tmp_path / "paper.pdf"
    log_path = tmp_path / "paper.log"
    tex_path.write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "A clean deterministic bundle.\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    pdf_path.write_bytes(b"%PDF-1.4\n% test\n")
    log_path.write_text("", encoding="utf-8")
    return {
        "tex_path": str(tex_path),
        "compiled_pdf_path": str(pdf_path),
        "log_path": str(log_path),
        "output_dir": str(tmp_path),
        "target_profile": "AAAI-style-science-discovery",
    }


def test_final_bundle_quality_evaluator_records_report(db, tmp_path):
    from research_harness.evaluator.runtime import (
        run_evaluator,
        supported_evaluators,
    )

    svc = _setup_topic(db)
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
        run_id="run.final_bundle_quality.runtime",
    )

    assert "final-bundle-quality" in supported_evaluators()
    result = run_evaluator(
        "final-bundle-quality",
        db=db,
        svc=svc,
        topic_id=1,
        stage="evaluate",
        capability_manifest=contract["capability_manifest"],
        run_spec=contract["run_spec"],
        guardrail_results=(),
    )

    assert result.success is True
    assert result.output["artifact_type"] == "final_bundle_quality_report"
    report_id = result.output["artifact_id"]
    artifacts = ArtifactManager(db)
    report = artifacts.get(report_id)
    assert report is not None
    assert report.artifact_type == "final_bundle_quality_report"
    assert report.payload["schema_version"] == (
        "rh.schema.artifact.final_bundle_quality_report.v0"
    )
    assert report.payload["source_artifact_id"] == final_bundle.id
    assert report.payload["issue_counts"] == {
        "blocking": 0,
        "recompile_repairable": 0,
        "layout_only": 0,
        "encoding": 0,
    }
    assert report.payload["promotion_decision"]["action"] == "evaluate"

    trace_id = result.output["run_trace_artifact_id"]
    trace = artifacts.get(trace_id)
    assert trace is not None
    assert trace.artifact_type == "run_trace"
    assert trace.payload["schema_version"] == "rh.trace.v0"
    assert trace.payload["run_id"] == "run.final_bundle_quality.runtime"
    assert trace.payload["status"] == "success"
    assert trace.payload["outputs"]["artifact_ids"] == [report_id]
    assert [step["kind"] for step in trace.payload["steps"]] == [
        "guardrail",
        "tool_call",
        "artifact_write",
    ]
    assert trace.payload["steps"][1]["metadata"]["skill_name"] == (
        "final-bundle-quality"
    )

    grade_id = result.output["runtime_trace_grade_artifact_id"]
    grade = artifacts.get(grade_id)
    assert grade is not None
    assert grade.artifact_type == "runtime_trace_grade"
    assert grade.payload["schema_version"] == (
        "rh.schema.artifact.runtime_trace_grade.v0"
    )
    assert grade.payload["decision"] == "pass"
    assert grade.payload["run_trace_artifact_id"] == trace_id
    assert all(check["passed"] for check in grade.payload["checks"])


def test_evaluator_runtime_aliases_promoted_skill_runtime(db, tmp_path):
    from research_harness.evaluator.runtime import (
        EvaluatorResult,
        run_evaluator,
        supported_evaluators,
    )

    svc = _setup_topic(db)
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
        run_id="run.final_bundle_quality.evaluator_alias",
    )

    assert "final-bundle-quality" in supported_evaluators()
    result = run_evaluator(
        "final-bundle-quality",
        db=db,
        svc=svc,
        topic_id=1,
        stage="evaluate",
        capability_manifest=contract["capability_manifest"],
        run_spec=contract["run_spec"],
        guardrail_results=(),
    )

    assert isinstance(result, EvaluatorResult)
    assert result.success is True
    assert result.output["artifact_type"] == "final_bundle_quality_report"


def test_publication_pack_evaluator_records_pack_and_trace(db):
    from research_harness.evaluator.runtime import (
        run_evaluator,
        supported_evaluators,
    )

    svc = _setup_topic(db)
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
        run_id="run.publication_pack.runtime",
    )

    assert "publication-pack" in supported_evaluators()
    result = run_evaluator(
        "publication-pack",
        db=db,
        svc=svc,
        topic_id=1,
        stage="write",
        capability_manifest=contract["capability_manifest"],
        run_spec=contract["run_spec"],
        guardrail_results=(),
    )

    assert result.success is True
    assert result.output["artifact_type"] == "publication_pack"
    pack_id = result.output["artifact_id"]
    pack = artifacts.get(pack_id)
    assert pack is not None
    assert pack.artifact_type == "publication_pack"
    assert pack.payload["schema_version"] == "rh.schema.artifact.publication_pack.v0"
    assert pack.payload["topic_id"] == 1
    assert pack.payload["ready_for_review"] is True
    assert pack.payload["components"]["manuscript_sections"]["artifact_id"] == draft.id
    assert pack.payload["components"]["evidence_pack"]["artifact_id"] == evidence.id

    trace_id = result.output["run_trace_artifact_id"]
    trace = artifacts.get(trace_id)
    assert trace is not None
    assert trace.artifact_type == "run_trace"
    assert trace.payload["run_id"] == "run.publication_pack.runtime"
    assert trace.payload["outputs"]["artifact_ids"] == [pack_id]
    assert trace.payload["steps"][1]["metadata"]["skill_name"] == "publication-pack"

    grade_id = result.output["runtime_trace_grade_artifact_id"]
    grade = artifacts.get(grade_id)
    assert grade is not None
    assert grade.artifact_type == "runtime_trace_grade"
    assert grade.payload["decision"] == "pass"
    assert all(check["passed"] for check in grade.payload["checks"])


def test_publication_pack_evaluator_rejects_superseded_input_artifacts(db):
    from research_harness.evaluator.runtime import run_evaluator

    svc = _setup_topic(db)
    artifacts = ArtifactManager(db)
    superseded_draft = artifacts.record(
        topic_id=1,
        stage="write",
        artifact_type="draft_pack",
        title="Old Draft Pack",
        payload={"sections": {"abstract": "Old draft [paper:1]."}},
    )
    artifacts.record(
        topic_id=1,
        stage="write",
        artifact_type="draft_pack",
        title="Current Draft Pack",
        payload={"sections": {"abstract": "Current draft [paper:1]."}},
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
            f"artifact:draft_pack:{superseded_draft.id}",
            f"artifact:evidence_pack:{evidence.id}",
        ),
        run_id="run.publication_pack.superseded_input",
    )

    result = run_evaluator(
        "publication-pack",
        db=db,
        svc=svc,
        topic_id=1,
        stage="write",
        capability_manifest=contract["capability_manifest"],
        run_spec=contract["run_spec"],
        guardrail_results=(),
    )

    assert result.success is False
    assert "active and non-stale" in result.error
    assert result.output["run_trace"]["status"] == "failed"
    assert result.output["runtime_trace_grade"]["decision"] == "pass"
    assert artifacts.list_by_topic(1, artifact_type="publication_pack") == []


def test_unknown_evaluator_returns_supported_names(db):
    from research_harness.runtime import CapabilityManifest, RunSpec, RunVisibleInputs
    from research_harness.evaluator.runtime import run_evaluator

    svc = _setup_topic(db)
    capability = CapabilityManifest(
        name="not-registered",
        version="0.1.0",
        capability_type="evaluator",
        owner="core",
        license="MIT",
        input_schema="rh.schema.input.not_registered.v0",
        output_schema="rh.schema.artifact.not_registered.v0",
    )
    spec = RunSpec(
        run_id="run.not_registered",
        task_type="evaluation",
        topic_id=1,
        objective="Exercise unknown evaluator handling.",
        visible_inputs=RunVisibleInputs(),
    )

    result = run_evaluator(
        "not-registered",
        db=db,
        svc=svc,
        topic_id=1,
        stage="evaluate",
        capability_manifest=capability,
        run_spec=spec,
    )

    assert result.success is False
    assert "Unsupported evaluator" in result.error
    assert "final-bundle-quality" in result.output["supported_evaluators"]
    assert "publication-pack" in result.output["supported_evaluators"]


def test_final_bundle_quality_refines_under_threshold_final_payload(db, tmp_path):
    from research_harness.evaluator.runtime import run_evaluator

    svc = _setup_topic(db)
    payload = _write_bundle(tmp_path)
    payload.update(
        {
            "finality_status": "final_ready",
            "reference_pool_evidence": {
                "passed": False,
                "usable_screened_paper_count": 12,
                "minimum_required": 40,
            },
        }
    )
    final_bundle = svc.record_artifact(
        topic_id=1,
        stage="write",
        artifact_type="final_bundle",
        title="Final bundle",
        payload=payload,
    )
    contract = build_skill_runtime_contract(
        _repo_root(),
        "final-bundle-quality",
        topic_id=1,
        artifact_refs=(f"artifact:final_bundle:{final_bundle.id}",),
        literal_inputs={"mode": "quality_scan"},
        run_id="run.final_bundle_quality.reference_pool_refine",
    )

    result = run_evaluator(
        "final-bundle-quality",
        db=db,
        svc=svc,
        topic_id=1,
        stage="evaluate",
        capability_manifest=contract["capability_manifest"],
        run_spec=contract["run_spec"],
        guardrail_results=(),
    )

    assert result.success is True
    assert result.output["promotion_decision"]["action"] == "refine"
    assert (
        "below the final-PDF threshold"
        in result.output["promotion_decision"]["reasons"][0]
    )


def test_final_bundle_quality_allows_explicit_interim_boundary(db, tmp_path):
    from research_harness.evaluator.runtime import run_evaluator

    svc = _setup_topic(db)
    payload = _write_bundle(tmp_path)
    payload.update(
        {
            "finality_status": "interim_ready",
            "is_interim": True,
            "interim_boundary": {"statement": "This is an interim draft."},
            "reference_pool_evidence": {
                "passed": False,
                "usable_screened_paper_count": 12,
                "minimum_required": 40,
            },
        }
    )
    final_bundle = svc.record_artifact(
        topic_id=1,
        stage="write",
        artifact_type="final_bundle",
        title="Interim bundle",
        payload=payload,
    )
    contract = build_skill_runtime_contract(
        _repo_root(),
        "final-bundle-quality",
        topic_id=1,
        artifact_refs=(f"artifact:final_bundle:{final_bundle.id}",),
        literal_inputs={"mode": "quality_scan"},
        run_id="run.final_bundle_quality.reference_pool_interim",
    )

    result = run_evaluator(
        "final-bundle-quality",
        db=db,
        svc=svc,
        topic_id=1,
        stage="evaluate",
        capability_manifest=contract["capability_manifest"],
        run_spec=contract["run_spec"],
        guardrail_results=(),
    )

    assert result.success is True
    assert result.output["promotion_decision"]["action"] == "evaluate"
    assert result.output["payload"]["finality"]["is_interim"] is True
