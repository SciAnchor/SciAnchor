"""Tests for evidence-bound publication pack generation."""

from __future__ import annotations

import json

from research_harness.execution.local import LocalBackend
from research_harness.execution.latex_compiler import template_fingerprint
from research_harness.orchestrator.artifacts import ArtifactManager
from research_harness.orchestrator.invariants import ARTIFACT_SCHEMAS, InvariantChecker
from research_harness.primitives.registry import get_primitive_spec
from research_harness.primitives.types import PaperFinalizeOutput
from research_harness.primitives.types import PublicationPackOutput
from research_harness.primitives.types import PublicationRunOutput


def _create_topic(db, name: str = "publication-pack-topic") -> int:
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO topics (name, description, target_venue) VALUES (?, ?, ?)",
            (name, "topic for publication pack tests", "ICLR"),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def _link_usable_papers(db, topic_id: int, count: int) -> None:
    conn = db.connect()
    try:
        for index in range(1, count + 1):
            cur = conn.execute(
                """
                INSERT INTO papers (title, year, venue, doi, abstract, status, pdf_path)
                VALUES (?, ?, ?, ?, ?, 'annotated', ?)
""",
                (
                    f"Screened Paper {index}",
                    2024 + (index % 2),
                    "Test Venue",
                    f"10.1/{index}",
                    f"Screened abstract {index}",
                    f"/tmp/screened-{index}.pdf",
                ),
            )
            conn.execute(
                "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (?, ?, 'high')",
                (int(cur.lastrowid), topic_id),
            )
        conn.commit()
    finally:
        conn.close()


def test_publication_pack_primitive_builds_contract_from_topic_artifacts(db):
    topic_id = _create_topic(db)
    artifacts = ArtifactManager(db)
    evidence = artifacts.record(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="evidence_pack",
        title="Evidence Pack",
        payload={
            "claims": [
                {
                    "claim_id": "c1",
                    "text": "Method improves robustness",
                    "paper_ids": [1],
                }
            ]
        },
    )
    draft = artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack",
        payload={
            "sections": {"introduction": "Claim-backed introduction [paper:1]."},
            "evidence_map": [{"sentence_index": 0, "claim_id": "c1", "paper_id": 1}],
        },
    )

    spec = get_primitive_spec("publication_pack_generate")
    assert spec is not None
    assert spec.requires_llm is False

    result = LocalBackend(db).execute(
        "publication_pack_generate",
        topic_id=topic_id,
        target_profile="high-impact-general",
    )

    assert result.success, result.error
    assert isinstance(result.output, PublicationPackOutput)
    output = result.output
    assert output.topic_id == topic_id
    assert output.target_profile == "high-impact-general"
    assert output.ready_for_review is True
    assert output.artifact_review_ready is True
    assert output.layout_review_ready is False
    assert output.scientific_review_ready is False
    assert output.lifecycle_closed is False
    assert output.submission_ready is False
    assert output.components["manuscript_sections"].artifact_id == draft.id
    assert output.components["evidence_pack"].artifact_id == evidence.id
    assert output.components["figure_plan"].status == "missing"
    assert "figure_plan" in output.missing_optional
    assert output.contract["artifact_type"] == "publication_pack"
    assert output.contract["must_trace_claims_to"] == [
        "paper_id",
        "claim_id",
        "artifact_id",
    ]
    assert {item["artifact_type"] for item in output.source_artifacts} >= {
        "draft_pack",
        "evidence_pack",
    }
    qa_by_name = {check["check"]: check for check in output.qa_checks}
    assert qa_by_name["citation_integrity"]["passed"] is False
    assert qa_by_name["figure_contract"]["passed"] is False
    assert qa_by_name["final_bundle"]["passed"] is False
    assert qa_by_name["provenance_summary"]["passed"] is False
    assert qa_by_name["orchestrator_readiness"]["passed"] is False
    assert qa_by_name["orchestrator_readiness"]["lifecycle_verified"] is False
    assert [action["component"] for action in output.next_actions] == [
        "citation_integrity",
        "figure_plan",
        "final_bundle",
        "process_summary",
    ]
    assert output.next_actions[0]["recommended_tool"] == "citation_sanitize"


def test_publication_pack_keeps_artifact_ready_separate_from_submission_ready(db):
    topic_id = _create_topic(db, "publication-pack-submission-ready-topic")
    artifacts = ArtifactManager(db)
    artifacts.record(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="evidence_pack",
        title="Evidence Pack",
        payload={"claims": [{"claim_id": "c1", "paper_ids": [1]}]},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack",
        payload={"sections": {"abstract": "Evidence-backed abstract [paper:1]."}},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="citation_sanitization_report",
        title="Citation Report",
        payload={"status": "pass"},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="figure_plan",
        title="Figure Plan",
        payload={"figures": []},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="final_bundle",
        title="Final Bundle",
        payload={"pdf": "paper.pdf"},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="process_summary",
        title="Process Summary",
        payload={"summary": "All key provenance reviewed."},
    )

    result = LocalBackend(db).execute(
        "publication_pack_generate",
        topic_id=topic_id,
    )

    assert result.success, result.error
    output = result.output
    assert isinstance(output, PublicationPackOutput)
    assert output.ready_for_review is True
    assert output.artifact_review_ready is True
    assert output.layout_review_ready is False
    assert output.lifecycle_closed is False
    assert output.submission_ready is False
    qa_by_name = {check["check"]: check for check in output.qa_checks}
    assert qa_by_name["orchestrator_readiness"]["passed"] is False
    assert qa_by_name["orchestrator_readiness"]["lifecycle_verified"] is False


def test_publication_pack_backfill_compiles_final_bundle_from_latest_draft(
    db, tmp_path, monkeypatch
):
    from research_harness.primitives import writing_impls

    topic_id = _create_topic(db, "publication-pack-compiled-final-bundle-topic")
    artifacts = ArtifactManager(db)
    artifacts.record(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="evidence_pack",
        title="Evidence Pack",
        payload={"claims": [{"claim_id": "c1", "paper_ids": [1]}]},
    )
    draft = artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack",
        payload={
            "title": "Compiled Draft",
            "sections": {
                "abstract": "Evidence-backed abstract [paper:1].",
                "introduction": "The `gap_detect` primitive is tracked.",
            },
        },
    )
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% test\n")

    def fake_finalize(**kwargs):
        assert kwargs["template"] == "aaai"
        assert kwargs["authors"] == ["Anonymous"]
        assert kwargs["sections"] == {
            "introduction": "The `gap_detect` primitive is tracked."
        }
        return PaperFinalizeOutput(
            success=True,
            tex_path=str(tmp_path / "paper.tex"),
            pdf_path=str(pdf_path),
            pages=6,
            word_count=6,
            sections_assembled=1,
            template_used="aaai",
        )

    monkeypatch.setattr(writing_impls, "paper_finalize", fake_finalize)
    monkeypatch.setattr(
        writing_impls,
        "_publication_output_dir",
        lambda db, topic_id, target_profile: tmp_path,
    )

    result = LocalBackend(db).execute(
        "publication_pack_backfill",
        topic_id=topic_id,
        target_profile="aaai",
        components=["final_bundle"],
    )

    assert result.success, result.error
    conn = db.connect()
    try:
        row = conn.execute(
            """
            SELECT payload_json
            FROM project_artifacts
            WHERE topic_id = ? AND artifact_type = 'final_bundle'
            ORDER BY id DESC LIMIT 1
            """,
            (topic_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    payload = json.loads(row["payload_json"])
    assert payload["compiled_pdf_path"] == str(pdf_path)
    assert payload["pages"] == 6
    assert payload["template"] == "aaai"
    assert payload["source_draft_artifact_id"] == draft.id


def test_publication_pack_backfill_refreshes_final_bundle_when_draft_is_newer(
    db, tmp_path, monkeypatch
):
    from research_harness.primitives import writing_impls

    topic_id = _create_topic(db, "publication-pack-refresh-newer-draft-topic")
    artifacts = ArtifactManager(db)
    artifacts.record(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="evidence_pack",
        title="Evidence Pack",
        payload={"claims": [{"claim_id": "c1", "paper_ids": [1]}]},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Old Draft Pack",
        payload={
            "title": "Old Draft",
            "sections": {"introduction": "Old draft text."},
        },
    )
    old_pdf = tmp_path / "old.pdf"
    old_pdf.write_bytes(b"%PDF-1.4\n% old\n")
    artifacts.record(
        topic_id=topic_id,
        stage="finalize",
        artifact_type="final_bundle",
        title="Old Final Bundle",
        payload={
            "status": "ready",
            "compiled_pdf_path": str(old_pdf),
            "page_limit_evidence": {"content_pages": 6},
            "anonymization_evidence": {"passed": True},
            "bibliography_style_evidence": {"passed": True},
        },
    )
    new_draft = artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="New Draft Pack",
        payload={
            "title": "New Draft",
            "sections": {"introduction": "New draft text."},
        },
    )
    new_pdf = tmp_path / "new.pdf"
    new_pdf.write_bytes(b"%PDF-1.4\n% new\n")

    def fake_finalize(**kwargs):
        assert kwargs["sections"]["introduction"] == "New draft text."
        return PaperFinalizeOutput(
            success=True,
            tex_path=str(tmp_path / "paper.tex"),
            pdf_path=str(new_pdf),
            pages=6,
            word_count=3,
            sections_assembled=1,
            template_used="aaai",
        )

    monkeypatch.setattr(writing_impls, "paper_finalize", fake_finalize)
    monkeypatch.setattr(
        writing_impls,
        "_publication_output_dir",
        lambda db, topic_id, target_profile: tmp_path,
    )

    result = LocalBackend(db).execute(
        "publication_pack_backfill",
        topic_id=topic_id,
        target_profile="aaai",
        components=["final_bundle"],
    )

    assert result.success, result.error
    assert any(
        artifact["component"] == "final_bundle"
        for artifact in result.output.created_artifacts
    )
    conn = db.connect()
    try:
        row = conn.execute(
            """
            SELECT payload_json
            FROM project_artifacts
            WHERE topic_id = ? AND artifact_type = 'final_bundle'
            ORDER BY id DESC LIMIT 1
            """,
            (topic_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    payload = json.loads(row["payload_json"])
    assert payload["compiled_pdf_path"] == str(new_pdf)
    assert payload["source_draft_artifact_id"] == new_draft.id


def test_publication_pack_backfill_refreshes_pdf_quality_regression(
    db, tmp_path, monkeypatch
):
    from research_harness.primitives import writing_impls

    topic_id = _create_topic(db, "publication-pack-refresh-pdf-quality-topic")
    artifacts = ArtifactManager(db)
    artifacts.record(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="evidence_pack",
        title="Evidence Pack",
        payload={"claims": [{"claim_id": "c1", "paper_ids": [1]}]},
    )
    draft = artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack",
        payload={
            "title": "PDF Quality Draft",
            "sections": {"introduction": "Draft text."},
        },
    )
    old_dir = tmp_path / "old"
    old_dir.mkdir()
    old_tex = old_dir / "paper.tex"
    old_pdf = old_dir / "paper.pdf"
    old_log = old_dir / "paper.log"
    old_tex.write_text(
        "\\section{Results}\n\textbf{Lost bold backslash.}\n",
        encoding="utf-8",
    )
    old_pdf.write_bytes(b"%PDF-1.4\n% old\n")
    old_log.write_text("", encoding="utf-8")
    artifacts.record(
        topic_id=topic_id,
        stage="finalize",
        artifact_type="final_bundle",
        title="Quality-Regressed Final Bundle",
        payload={
            "status": "ready",
            "tex_path": str(old_tex),
            "compiled_pdf_path": str(old_pdf),
            "output_dir": str(old_dir),
            "page_limit_evidence": {"content_pages": 6},
            "anonymization_evidence": {"passed": True},
            "bibliography_style_evidence": {"passed": True},
        },
    )
    new_pdf = tmp_path / "new.pdf"
    new_pdf.write_bytes(b"%PDF-1.4\n% new\n")

    def fake_finalize(**kwargs):
        return PaperFinalizeOutput(
            success=True,
            tex_path=str(tmp_path / "paper.tex"),
            pdf_path=str(new_pdf),
            pages=6,
            word_count=2,
            sections_assembled=1,
            template_used="aaai",
        )

    monkeypatch.setattr(writing_impls, "paper_finalize", fake_finalize)
    monkeypatch.setattr(
        writing_impls,
        "_publication_output_dir",
        lambda db, topic_id, target_profile: tmp_path,
    )

    result = LocalBackend(db).execute(
        "publication_pack_backfill",
        topic_id=topic_id,
        target_profile="aaai",
        components=["final_bundle"],
    )

    assert result.success, result.error
    assert any(
        artifact["component"] == "final_bundle"
        for artifact in result.output.created_artifacts
    )
    conn = db.connect()
    try:
        row = conn.execute(
            """
            SELECT payload_json
            FROM project_artifacts
            WHERE topic_id = ? AND artifact_type = 'final_bundle'
            ORDER BY id DESC LIMIT 1
            """,
            (topic_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    payload = json.loads(row["payload_json"])
    assert payload["compiled_pdf_path"] == str(new_pdf)
    assert payload["source_draft_artifact_id"] == draft.id


def test_publication_pack_backfill_does_not_recompile_for_layout_warnings_only(
    db, tmp_path, monkeypatch
):
    from research_harness.primitives import writing_impls

    topic_id = _create_topic(db, "publication-pack-layout-warning-topic")
    artifacts = ArtifactManager(db)
    artifacts.record(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="evidence_pack",
        title="Evidence Pack",
        payload={"claims": [{"claim_id": "c1", "paper_ids": [1]}]},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack",
        payload={
            "title": "Layout Warning Draft",
            "sections": {"introduction": "Draft text."},
        },
    )
    output_dir = tmp_path / "bundle"
    output_dir.mkdir()
    tex_path = output_dir / "paper.tex"
    pdf_path = output_dir / "paper.pdf"
    log_path = output_dir / "paper.log"
    tex_path.write_text(r"\section{Results}" "\nClean text.\n", encoding="utf-8")
    pdf_path.write_bytes(b"%PDF-1.4\n% old\n")
    log_path.write_text(
        "Overfull \\hbox (26.57275pt too wide) in paragraph at lines 12--13\n",
        encoding="utf-8",
    )
    artifacts.record(
        topic_id=topic_id,
        stage="finalize",
        artifact_type="final_bundle",
        title="Layout-Warning Final Bundle",
        payload={
            "status": "ready",
            "tex_path": str(tex_path),
            "compiled_pdf_path": str(pdf_path),
            "output_dir": str(output_dir),
            "pages": 6,
            "template": "aaai",
            "template_fingerprint": template_fingerprint("aaai"),
            "page_limit_evidence": {"content_pages": 6},
            "anonymization_evidence": {"passed": True},
            "bibliography_style_evidence": {"passed": True},
        },
    )

    def fail_finalize(**kwargs):
        raise AssertionError(f"unexpected finalization: {kwargs}")

    monkeypatch.setattr(writing_impls, "paper_finalize", fail_finalize)

    result = LocalBackend(db).execute(
        "publication_pack_backfill",
        topic_id=topic_id,
        target_profile="aaai",
        components=["final_bundle"],
    )

    assert result.success, result.error
    assert all(
        artifact["component"] != "final_bundle"
        for artifact in result.output.created_artifacts
    )
    assert {"component": "final_bundle", "reason": "already_present"} in (
        result.output.skipped_actions
    )


def test_publication_pack_backfill_refreshes_template_fingerprint_gap(
    db, tmp_path, monkeypatch
):
    from research_harness.primitives import writing_impls

    topic_id = _create_topic(db, "publication-pack-template-fingerprint-topic")
    artifacts = ArtifactManager(db)
    artifacts.record(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="evidence_pack",
        title="Evidence Pack",
        payload={"claims": [{"claim_id": "c1", "paper_ids": [1]}]},
    )
    draft = artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack",
        payload={
            "title": "Template Fingerprint Draft",
            "sections": {"introduction": "Draft text."},
        },
    )
    old_pdf = tmp_path / "old.pdf"
    old_pdf.write_bytes(b"%PDF-1.4\n% old\n")
    artifacts.record(
        topic_id=topic_id,
        stage="finalize",
        artifact_type="final_bundle",
        title="Old Template Final Bundle",
        payload={
            "status": "ready",
            "compiled_pdf_path": str(old_pdf),
            "pages": 6,
            "template": "aaai",
            "template_fingerprint": "old-template-policy",
            "page_limit_evidence": {"content_pages": 6},
            "anonymization_evidence": {"passed": True},
            "bibliography_style_evidence": {"passed": True},
        },
    )
    new_pdf = tmp_path / "new.pdf"
    new_pdf.write_bytes(b"%PDF-1.4\n% new\n")

    def fake_finalize(**kwargs):
        return PaperFinalizeOutput(
            success=True,
            tex_path=str(tmp_path / "paper.tex"),
            pdf_path=str(new_pdf),
            pages=6,
            word_count=2,
            sections_assembled=1,
            template_used="aaai",
        )

    monkeypatch.setattr(writing_impls, "paper_finalize", fake_finalize)
    monkeypatch.setattr(
        writing_impls,
        "_publication_output_dir",
        lambda db, topic_id, target_profile: tmp_path,
    )

    result = LocalBackend(db).execute(
        "publication_pack_backfill",
        topic_id=topic_id,
        target_profile="aaai",
        components=["final_bundle"],
    )

    assert result.success, result.error
    assert any(
        artifact["component"] == "final_bundle"
        for artifact in result.output.created_artifacts
    )
    conn = db.connect()
    try:
        row = conn.execute(
            """
            SELECT payload_json
            FROM project_artifacts
            WHERE topic_id = ? AND artifact_type = 'final_bundle'
            ORDER BY id DESC LIMIT 1
            """,
            (topic_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    payload = json.loads(row["payload_json"])
    assert payload["compiled_pdf_path"] == str(new_pdf)
    assert payload["source_draft_artifact_id"] == draft.id
    assert payload["template_fingerprint"] == template_fingerprint("aaai")


def test_publication_pack_backfill_refreshes_invalid_utf8_warning(
    db, tmp_path, monkeypatch
):
    from research_harness.primitives import writing_impls

    topic_id = _create_topic(db, "publication-pack-invalid-utf8-topic")
    artifacts = ArtifactManager(db)
    artifacts.record(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="evidence_pack",
        title="Evidence Pack",
        payload={"claims": [{"claim_id": "c1", "paper_ids": [1]}]},
    )
    draft = artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack",
        payload={
            "title": "Invalid UTF-8 Draft",
            "sections": {"introduction": "Draft text."},
        },
    )
    output_dir = tmp_path / "bundle"
    output_dir.mkdir()
    tex_path = output_dir / "paper.tex"
    pdf_path = output_dir / "paper.pdf"
    log_path = output_dir / "paper.log"
    tex_path.write_text(r"\section{Results}" "\nClean text.\n", encoding="utf-8")
    pdf_path.write_bytes(b"%PDF-1.4\n% old\n")
    log_path.write_text(
        "Invalid UTF-8 byte or sequence at line 11 replaced by U+FFFD.\n",
        encoding="utf-8",
    )
    artifacts.record(
        topic_id=topic_id,
        stage="finalize",
        artifact_type="final_bundle",
        title="Invalid-UTF8 Final Bundle",
        payload={
            "status": "ready",
            "tex_path": str(tex_path),
            "compiled_pdf_path": str(pdf_path),
            "output_dir": str(output_dir),
            "pages": 6,
            "page_limit_evidence": {"content_pages": 6},
            "anonymization_evidence": {"passed": True},
            "bibliography_style_evidence": {"passed": True},
        },
    )
    new_pdf = tmp_path / "new.pdf"
    new_pdf.write_bytes(b"%PDF-1.4\n% new\n")

    def fake_finalize(**kwargs):
        return PaperFinalizeOutput(
            success=True,
            tex_path=str(tmp_path / "paper.tex"),
            pdf_path=str(new_pdf),
            pages=6,
            word_count=2,
            sections_assembled=1,
            template_used="aaai",
        )

    monkeypatch.setattr(writing_impls, "paper_finalize", fake_finalize)
    monkeypatch.setattr(
        writing_impls,
        "_publication_output_dir",
        lambda db, topic_id, target_profile: tmp_path,
    )

    result = LocalBackend(db).execute(
        "publication_pack_backfill",
        topic_id=topic_id,
        target_profile="aaai",
        components=["final_bundle"],
    )

    assert result.success, result.error
    assert any(
        artifact["component"] == "final_bundle"
        for artifact in result.output.created_artifacts
    )
    conn = db.connect()
    try:
        row = conn.execute(
            """
            SELECT payload_json
            FROM project_artifacts
            WHERE topic_id = ? AND artifact_type = 'final_bundle'
            ORDER BY id DESC LIMIT 1
            """,
            (topic_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    payload = json.loads(row["payload_json"])
    assert payload["compiled_pdf_path"] == str(new_pdf)
    assert payload["source_draft_artifact_id"] == draft.id


def test_compiled_final_bundle_uses_page_evidence_when_compiler_pages_are_zero(
    db, tmp_path, monkeypatch
):
    from research_harness.primitives import writing_impls

    topic_id = _create_topic(db, "publication-pack-page-fallback-topic")
    artifacts = ArtifactManager(db)
    draft = artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack",
        payload={
            "title": "Page Fallback Draft",
            "sections": {"introduction": "Draft text."},
        },
    )
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% new\n")

    def fake_finalize(**kwargs):
        return PaperFinalizeOutput(
            success=True,
            tex_path=str(tmp_path / "paper.tex"),
            pdf_path=str(pdf_path),
            pages=0,
            word_count=2,
            sections_assembled=1,
            template_used="aaai",
        )

    monkeypatch.setattr(writing_impls, "paper_finalize", fake_finalize)
    monkeypatch.setattr(
        writing_impls,
        "_publication_output_dir",
        lambda db, topic_id, target_profile: tmp_path,
    )
    monkeypatch.setattr(
        writing_impls,
        "_content_page_evidence",
        lambda pdf_path: {"full_pages": 7, "content_pages": 6},
    )

    payload = writing_impls._compiled_final_bundle_payload(
        db=db,
        topic_id=topic_id,
        target_profile="aaai",
    )

    assert payload is not None
    assert payload["pages"] == 7
    assert payload["full_pages"] == 7
    assert payload["content_pages"] == 6
    assert payload["paper_finalize"]["pages"] == 7
    assert payload["source_draft_artifact_id"] == draft.id


def test_compiled_final_bundle_marks_under_threshold_reference_pool_interim(
    db, tmp_path, monkeypatch
):
    from research_harness.primitives import writing_impls

    topic_id = _create_topic(db, "publication-pack-reference-pool-interim-topic")
    artifacts = ArtifactManager(db)
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack",
        payload={
            "title": "Reference Pool Draft",
            "sections": {"introduction": "Draft."},
        },
    )
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% test\n")

    def fake_finalize(**kwargs):
        return PaperFinalizeOutput(
            success=True,
            tex_path=str(tmp_path / "paper.tex"),
            pdf_path=str(pdf_path),
            pages=4,
            word_count=1,
            sections_assembled=1,
            template_used="aaai",
        )

    monkeypatch.setattr(writing_impls, "paper_finalize", fake_finalize)
    monkeypatch.setattr(
        writing_impls,
        "_publication_output_dir",
        lambda db, topic_id, target_profile: tmp_path,
    )

    payload = writing_impls._compiled_final_bundle_payload(
        db=db,
        topic_id=topic_id,
        target_profile="aaai",
    )

    assert payload is not None
    assert payload["status"] == "ready_interim"
    assert payload["finality_status"] == "interim_ready"
    assert payload["is_interim"] is True
    assert payload["reference_pool_evidence"]["passed"] is False
    assert payload["reference_pool_evidence"]["usable_screened_paper_count"] == 0
    assert (
        payload["interim_boundary"]["reason"] == "reference_pool_below_final_threshold"
    )


def test_compiled_final_bundle_marks_reference_pool_final_ready(
    db, tmp_path, monkeypatch
):
    from research_harness.primitives import writing_impls

    topic_id = _create_topic(db, "publication-pack-reference-pool-final-topic")
    _link_usable_papers(db, topic_id, 40)
    artifacts = ArtifactManager(db)
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack",
        payload={
            "title": "Reference Pool Draft",
            "sections": {"introduction": "Draft."},
        },
    )
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% test\n")

    def fake_finalize(**kwargs):
        return PaperFinalizeOutput(
            success=True,
            tex_path=str(tmp_path / "paper.tex"),
            pdf_path=str(pdf_path),
            pages=4,
            word_count=1,
            sections_assembled=1,
            template_used="aaai",
        )

    monkeypatch.setattr(writing_impls, "paper_finalize", fake_finalize)
    monkeypatch.setattr(
        writing_impls,
        "_publication_output_dir",
        lambda db, topic_id, target_profile: tmp_path,
    )

    payload = writing_impls._compiled_final_bundle_payload(
        db=db,
        topic_id=topic_id,
        target_profile="aaai",
    )

    assert payload is not None
    assert payload["status"] == "ready"
    assert payload["finality_status"] == "final_ready"
    assert payload["is_interim"] is False
    assert payload["reference_pool_evidence"]["passed"] is True
    assert payload["reference_pool_evidence"]["usable_screened_paper_count"] == 40


def test_write_gate_blocks_final_ready_under_reference_pool_threshold(db):
    topic_id = _create_topic(db, "publication-pack-reference-pool-invariant-topic")
    artifacts = ArtifactManager(db)
    final_bundle = artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="final_bundle",
        title="Final Bundle",
        payload={
            "status": "ready",
            "finality_status": "final_ready",
            "reference_pool_evidence": {
                "passed": False,
                "usable_screened_paper_count": 12,
                "minimum_required": 40,
            },
            "compiled_pdf_path": "paper.pdf",
        },
    )

    violations = InvariantChecker(db).check_final_publication_boundaries(
        topic_id, "write"
    )

    assert any(
        violation.check == "final_reference_pool_gate"
        and violation.artifact_id == final_bundle.id
        for violation in violations
    )


def test_publication_pack_backfill_refreshes_missing_page_metadata(
    db, tmp_path, monkeypatch
):
    from research_harness.primitives import writing_impls

    topic_id = _create_topic(db, "publication-pack-page-metadata-refresh-topic")
    artifacts = ArtifactManager(db)
    artifacts.record(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="evidence_pack",
        title="Evidence Pack",
        payload={"claims": [{"claim_id": "c1", "paper_ids": [1]}]},
    )
    draft = artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack",
        payload={
            "title": "Page Metadata Draft",
            "sections": {"introduction": "Draft text."},
        },
    )
    old_pdf = tmp_path / "old.pdf"
    old_pdf.write_bytes(b"%PDF-1.4\n% old\n")
    artifacts.record(
        topic_id=topic_id,
        stage="finalize",
        artifact_type="final_bundle",
        title="Page-Metadata Final Bundle",
        payload={
            "status": "ready",
            "compiled_pdf_path": str(old_pdf),
            "pages": 0,
            "page_limit_evidence": {"full_pages": 7, "content_pages": 6},
            "anonymization_evidence": {"passed": True},
            "bibliography_style_evidence": {"passed": True},
        },
    )
    new_pdf = tmp_path / "new.pdf"
    new_pdf.write_bytes(b"%PDF-1.4\n% new\n")

    def fake_finalize(**kwargs):
        return PaperFinalizeOutput(
            success=True,
            tex_path=str(tmp_path / "paper.tex"),
            pdf_path=str(new_pdf),
            pages=0,
            word_count=2,
            sections_assembled=1,
            template_used="aaai",
        )

    monkeypatch.setattr(writing_impls, "paper_finalize", fake_finalize)
    monkeypatch.setattr(
        writing_impls,
        "_publication_output_dir",
        lambda db, topic_id, target_profile: tmp_path,
    )
    monkeypatch.setattr(
        writing_impls,
        "_content_page_evidence",
        lambda pdf_path: {"full_pages": 7, "content_pages": 6},
    )

    result = LocalBackend(db).execute(
        "publication_pack_backfill",
        topic_id=topic_id,
        target_profile="aaai",
        components=["final_bundle"],
    )

    assert result.success, result.error
    assert any(
        artifact["component"] == "final_bundle"
        for artifact in result.output.created_artifacts
    )
    conn = db.connect()
    try:
        row = conn.execute(
            """
            SELECT payload_json
            FROM project_artifacts
            WHERE topic_id = ? AND artifact_type = 'final_bundle'
            ORDER BY id DESC LIMIT 1
            """,
            (topic_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    payload = json.loads(row["payload_json"])
    assert payload["pages"] == 7
    assert payload["source_draft_artifact_id"] == draft.id


def test_publication_pack_backfill_includes_planned_figure_in_compiled_bundle(
    db, tmp_path, monkeypatch
):
    from research_harness.primitives import writing_impls

    topic_id = _create_topic(db, "publication-pack-compiled-figure-topic")
    artifacts = ArtifactManager(db)
    artifacts.record(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="evidence_pack",
        title="Evidence Pack",
        payload={"claims": [{"claim_id": "c1", "paper_ids": [1]}]},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack",
        payload={
            "title": "Compiled Figure Draft",
            "sections": {
                "abstract": "Evidence-backed abstract [paper:1].",
                "method": "Research Harness implements a staged contract.",
            },
        },
    )
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "out"
    source_dir.mkdir()
    output_dir.mkdir()
    asset_path = source_dir / "architecture.png"
    asset_path.write_bytes(b"fake image bytes")
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="figure_plan",
        title="Figure Plan",
        payload={
            "items": [
                {
                    "figure_id": "fig:rh-arch",
                    "kind": "architecture_figure",
                    "caption": "Research Harness architecture.",
                    "asset_path": str(asset_path),
                }
            ]
        },
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="figure_asset",
        title="Figure Asset",
        payload={"asset_path": str(asset_path)},
    )
    pdf_path = output_dir / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% fake\n")

    def fake_finalize(**kwargs):
        method = kwargs["sections"]["method"]
        assert r"\includegraphics" in method
        assert "architecture.png" in method
        assert (output_dir / "architecture.png").exists()
        return PaperFinalizeOutput(
            success=True,
            tex_path=str(output_dir / "paper.tex"),
            pdf_path=str(pdf_path),
            pages=6,
            word_count=6,
            sections_assembled=1,
            template_used="aaai",
        )

    monkeypatch.setattr(writing_impls, "paper_finalize", fake_finalize)
    monkeypatch.setattr(
        writing_impls,
        "_publication_output_dir",
        lambda db, topic_id, target_profile: output_dir,
    )

    result = LocalBackend(db).execute(
        "publication_pack_backfill",
        topic_id=topic_id,
        target_profile="aaai",
        components=["final_bundle"],
    )

    assert result.success, result.error
    conn = db.connect()
    try:
        row = conn.execute(
            """
            SELECT payload_json
            FROM project_artifacts
            WHERE topic_id = ? AND artifact_type = 'final_bundle'
            ORDER BY id DESC LIMIT 1
            """,
            (topic_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    payload = json.loads(row["payload_json"])
    assert payload["figure_assets"][0]["figure_id"] == "fig:rh-arch"
    assert payload["figure_placement_evidence"]["passed"] is True
    assert payload["figure_placement_evidence"]["expected_figures"] == 1


def test_publication_pack_requires_venue_compliance_for_aaai_profile(db):
    topic_id = _create_topic(db, "publication-pack-aaai-compliance-topic")
    artifacts = ArtifactManager(db)
    artifacts.record(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="evidence_pack",
        title="Evidence Pack",
        payload={"claims": [{"claim_id": "c1", "paper_ids": [1]}]},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack",
        payload={"sections": {"abstract": "Evidence-backed abstract [paper:1]."}},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="citation_sanitization_report",
        title="Citation Report",
        payload={"status": "pass"},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="figure_plan",
        title="Figure Plan",
        payload={"figures": []},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="final_bundle",
        title="Final Bundle",
        payload={"pdf": "paper.pdf"},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="process_summary",
        title="Process Summary",
        payload={"summary": "All key provenance reviewed."},
    )

    result = LocalBackend(db).execute(
        "publication_pack_generate",
        topic_id=topic_id,
        target_profile="AAAI-style-science-discovery",
    )

    assert result.success, result.error
    output = result.output
    assert isinstance(output, PublicationPackOutput)
    assert output.ready_for_review is True
    assert output.submission_ready is False
    qa_by_name = {check["check"]: check for check in output.qa_checks}
    assert qa_by_name["venue_compliance"]["passed"] is False
    assert qa_by_name["venue_compliance"]["severity"] == "blocking"
    assert any(
        action["component"] == "venue_compliance" for action in output.next_actions
    )

    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="venue_compliance_report",
        title="AAAI Compliance Report",
        payload={"status": "pass"},
    )

    passed = LocalBackend(db).execute(
        "publication_pack_generate",
        topic_id=topic_id,
        target_profile="AAAI-style-science-discovery",
    )

    assert passed.success, passed.error
    assert passed.output.submission_ready is False
    assert passed.output.lifecycle_closed is False


def test_venue_compliance_check_records_failing_report(db):
    topic_id = _create_topic(db, "venue-compliance-failing-topic")
    artifacts = ArtifactManager(db)
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack",
        payload={"sections": {"abstract": "Evidence-backed abstract [paper:1]."}},
    )

    spec = get_primitive_spec("venue_compliance_check")
    assert spec is not None
    assert spec.requires_llm is False

    result = LocalBackend(db).execute(
        "venue_compliance_check",
        topic_id=topic_id,
        target_profile="AAAI-style-science-discovery",
    )

    assert result.success, result.error
    output = result.output
    assert output.status == "fail"
    assert output.passed is False
    assert output.venue_compliance_report_artifact_id > 0
    failed_checks = {check["check"] for check in output.blocking_findings}
    assert "venue_pdf_compile" in failed_checks
    assert "anonymization" in failed_checks
    assert "human_scholarly_review" in failed_checks

    pack = LocalBackend(db).execute(
        "publication_pack_generate",
        topic_id=topic_id,
        target_profile="AAAI-style-science-discovery",
    )
    assert pack.success, pack.error
    assert pack.output.components["venue_compliance"].status == "present"
    assert pack.output.submission_ready is False
    qa_by_name = {check["check"]: check for check in pack.output.qa_checks}
    assert qa_by_name["venue_compliance"]["passed"] is False
    assert "present but not passing" in qa_by_name["venue_compliance"]["details"]


def test_venue_compliance_check_can_pass_with_explicit_venue_evidence(db, tmp_path):
    topic_id = _create_topic(db, "venue-compliance-passing-topic")
    artifacts = ArtifactManager(db)
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% test\n")
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack",
        payload={"sections": {"abstract": "Evidence-backed abstract [paper:1]."}},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="citation_sanitization_report",
        title="Citation Report",
        payload={"removed_count": 0},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="figure_asset",
        title="Figure Asset",
        payload={"asset_path": "figure.png"},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="final_bundle",
        title="Final Bundle",
        payload={"compiled_pdf_path": str(pdf_path), "pages": 6},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="scholarly_review_report",
        title="Scholarly Review",
        payload={"status": "approved"},
    )

    result = LocalBackend(db).execute(
        "venue_compliance_check",
        topic_id=topic_id,
        target_profile="AAAI-style-science-discovery",
        anonymous=True,
        bibliography_style="aaai",
        figure_qa_passed=True,
    )

    assert result.success, result.error
    output = result.output
    assert output.status == "pass"
    assert output.passed is True
    assert output.blocking_findings == []
    assert all(check["passed"] for check in output.checks)


def test_venue_compliance_check_infers_figure_placement_from_final_bundle_evidence(
    db, tmp_path
):
    topic_id = _create_topic(db, "venue-compliance-figure-evidence-topic")
    artifacts = ArtifactManager(db)
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% test\n")
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack",
        payload={"sections": {"abstract": "Evidence-backed abstract [paper:1]."}},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="citation_sanitization_report",
        title="Citation Report",
        payload={"removed_count": 0},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="figure_asset",
        title="Figure Asset",
        payload={"asset_path": "figure.png"},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="final_bundle",
        title="Final Bundle",
        payload={
            "compiled_pdf_path": str(pdf_path),
            "pages": 6,
            "figure_placement_evidence": {
                "passed": True,
                "expected_figures": 1,
                "detected_images": 1,
                "image_pages": [1],
            },
        },
    )

    result = LocalBackend(db).execute(
        "venue_compliance_check",
        topic_id=topic_id,
        target_profile="AAAI-style-science-discovery",
        anonymous=True,
        bibliography_style="aaai",
        human_review_approved=True,
    )

    assert result.success, result.error
    output = result.output
    qa_by_name = {check["check"]: check for check in output.checks}
    assert qa_by_name["figure_placement"]["passed"] is True
    assert output.passed is True


def test_venue_compliance_check_infers_page_anonymization_and_bibliography_evidence(
    db, tmp_path
):
    topic_id = _create_topic(db, "venue-compliance-derived-evidence-topic")
    artifacts = ArtifactManager(db)
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% test\n")
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack",
        payload={"sections": {"abstract": "Evidence-backed abstract [paper:1]."}},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="citation_sanitization_report",
        title="Citation Report",
        payload={"removed_count": 0},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="figure_asset",
        title="Figure Asset",
        payload={"asset_path": "figure.png"},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="final_bundle",
        title="Final Bundle",
        payload={
            "compiled_pdf_path": str(pdf_path),
            "pages": 9,
            "page_limit_evidence": {
                "full_pages": 9,
                "content_pages": 7,
                "references_start_page": 8,
            },
            "anonymization_evidence": {"passed": True},
            "bibliography_style_evidence": {
                "passed": True,
                "style_label": "aaai-author-year-compatible",
                "citation_commands": 2,
                "bibliography_entries": 2,
            },
            "figure_placement_evidence": {
                "passed": True,
                "expected_figures": 1,
                "detected_images": 1,
            },
        },
    )

    result = LocalBackend(db).execute(
        "venue_compliance_check",
        topic_id=topic_id,
        target_profile="AAAI-style-science-discovery",
        human_review_approved=True,
    )

    assert result.success, result.error
    output = result.output
    qa_by_name = {check["check"]: check for check in output.checks}
    assert qa_by_name["page_limit"]["passed"] is True
    assert "technical-content page" in qa_by_name["page_limit"]["finding"]
    assert qa_by_name["anonymization"]["passed"] is True
    assert qa_by_name["bibliography_style"]["passed"] is True
    assert output.passed is True


def test_venue_compliance_check_uses_final_bundle_citation_integrity_evidence(
    db, tmp_path
):
    topic_id = _create_topic(db, "venue-compliance-final-bib-citation-topic")
    artifacts = ArtifactManager(db)
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% test\n")
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack",
        payload={"sections": {"abstract": "Evidence-backed abstract [paper:1]."}},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="citation_sanitization_report",
        title="Citation Report",
        payload={"removed_count": 0},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="figure_asset",
        title="Figure Asset",
        payload={"asset_path": "figure.png"},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="final_bundle",
        title="Final Bundle",
        payload={
            "compiled_pdf_path": str(pdf_path),
            "pages": 6,
            "citation_integrity_evidence": {
                "passed": False,
                "missing_bib_keys": ["ref2"],
            },
        },
    )

    result = LocalBackend(db).execute(
        "venue_compliance_check",
        topic_id=topic_id,
        target_profile="AAAI-style-science-discovery",
        anonymous=True,
        bibliography_style="aaai",
        figure_qa_passed=True,
        human_review_approved=True,
    )

    assert result.success, result.error
    qa_by_name = {check["check"]: check for check in result.output.checks}
    assert qa_by_name["citation_integrity"]["passed"] is False
    assert "BibTeX" in qa_by_name["citation_integrity"]["finding"]


def test_venue_compliance_check_rejects_final_bundle_with_compile_errors(db, tmp_path):
    topic_id = _create_topic(db, "venue-compliance-compile-error-topic")
    artifacts = ArtifactManager(db)
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% test\n")
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack",
        payload={"sections": {"abstract": "Evidence-backed abstract [paper:1]."}},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="citation_sanitization_report",
        title="Citation Report",
        payload={"removed_count": 0},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="figure_asset",
        title="Figure Asset",
        payload={"asset_path": "figure.png"},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="final_bundle",
        title="Final Bundle",
        payload={
            "status": "failed",
            "compiled_pdf_path": str(pdf_path),
            "pages": 6,
            "errors": ["! LaTeX Error: Something's wrong--perhaps a missing item."],
            "paper_finalize": {
                "errors": ["! LaTeX Error: Something's wrong--perhaps a missing item."]
            },
        },
    )

    result = LocalBackend(db).execute(
        "venue_compliance_check",
        topic_id=topic_id,
        target_profile="AAAI-style-science-discovery",
        anonymous=True,
        bibliography_style="aaai",
        figure_qa_passed=True,
        human_review_approved=True,
    )

    assert result.success, result.error
    output = result.output
    qa_by_name = {check["check"]: check for check in output.checks}
    assert qa_by_name["venue_pdf_compile"]["passed"] is False
    assert "compile errors" in qa_by_name["venue_pdf_compile"]["finding"]
    assert output.passed is False


def test_venue_compliance_check_records_latex_source_and_log_lint(db, tmp_path):
    topic_id = _create_topic(db, "venue-compliance-source-lint-topic")
    artifacts = ArtifactManager(db)
    pdf_path = tmp_path / "paper.pdf"
    tex_path = tmp_path / "paper.tex"
    log_path = tmp_path / "paper.log"
    pdf_path.write_bytes(b"%PDF-1.4\n% test\n")
    tex_path.write_text(
        "\n".join(
            [
                r"\documentclass{article}",
                r"\usepackage{geometry,minted}",
                r"\begin{document}",
                r"\write18{touch unsafe}",
                r"\input{sections/missing}",
                r"\includegraphics{figures/missing}",
                r"\end{document}",
            ]
        ),
        encoding="utf-8",
    )
    log_path.write_text(
        "\n".join(
            [
                "LaTeX Warning: Citation `smith2024' on page 1 undefined on input line 7.",
                "LaTeX Warning: Reference `fig:missing' on page 1 undefined on input line 8.",
                r"Overfull \hbox (8.0pt too wide) in paragraph at lines 10--11",
                "! LaTeX Error: File `figures/log-missing.pdf' not found.",
            ]
        ),
        encoding="utf-8",
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack",
        payload={"sections": {"abstract": "Evidence-backed abstract [paper:1]."}},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="citation_sanitization_report",
        title="Citation Report",
        payload={"removed_count": 0},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="figure_asset",
        title="Figure Asset",
        payload={"asset_path": "figure.png"},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="final_bundle",
        title="Final Bundle",
        payload={
            "compiled_pdf_path": str(pdf_path),
            "tex_path": str(tex_path),
            "log_path": str(log_path),
            "pages": 8,
            "page_limit_evidence": {
                "full_pages": 8,
                "content_pages": 6,
                "references_start_page": 7,
            },
            "citation_integrity_evidence": {"passed": True},
            "anonymization_evidence": {"passed": True},
            "bibliography_style_evidence": {
                "passed": True,
                "style_label": "aaai-author-year-compatible",
            },
            "figure_placement_evidence": {"passed": True},
        },
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="scholarly_review_report",
        title="Scholarly Review",
        payload={"status": "approved"},
    )

    result = LocalBackend(db).execute(
        "venue_compliance_check",
        topic_id=topic_id,
        target_profile="AAAI-style-science-discovery",
    )

    assert result.success, result.error
    output = result.output
    assert output.schema_version == "rh.venue_compliance_report.v1"
    assert output.status == "fail"
    assert output.latex_compile_success is True
    assert output.disallowed_packages == ["geometry", "minted"]
    assert output.disallowed_commands == [r"\write18"]
    assert output.missing_files == [
        "sections/missing",
        "figures/missing",
        "figures/log-missing.pdf",
    ]
    assert output.undefined_citations == ["smith2024"]
    assert output.undefined_references == ["fig:missing"]
    assert output.overfull_box_warnings == [
        r"Overfull \hbox (8.0pt too wide) in paragraph at lines 10--11"
    ]
    assert output.main_text_page_count == 6
    assert output.page_limit == 7
    assert output.references_appendix_excluded is True
    assert "venue_source_lint:failed" in output.blockers
    qa_by_name = {check["check"]: check for check in output.checks}
    assert qa_by_name["venue_source_lint"]["passed"] is False


def test_venue_compliance_check_rejects_stale_scholarly_review(db, tmp_path):
    topic_id = _create_topic(db, "venue-compliance-stale-review-topic")
    artifacts = ArtifactManager(db)
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% test\n")
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack v1",
        payload={"sections": {"abstract": "Old draft."}},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="citation_sanitization_report",
        title="Citation Report",
        payload={"removed_count": 0},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="figure_asset",
        title="Figure Asset",
        payload={"asset_path": "figure.png"},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="scholarly_review_report",
        title="Approved Scholarly Review",
        payload={"status": "approved"},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack v2",
        payload={"sections": {"abstract": "New draft."}},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="finalize",
        artifact_type="final_bundle",
        title="Final Bundle",
        payload={
            "compiled_pdf_path": str(pdf_path),
            "pages": 6,
            "page_limit_evidence": {"content_pages": 6, "full_pages": 6},
            "anonymization_evidence": {"passed": True},
            "bibliography_style_evidence": {
                "passed": True,
                "style_label": "aaai-author-year-compatible",
            },
            "figure_placement_evidence": {"passed": True},
        },
    )

    result = LocalBackend(db).execute(
        "venue_compliance_check",
        topic_id=topic_id,
        target_profile="AAAI-style-science-discovery",
        anonymous=True,
        bibliography_style="aaai",
        figure_qa_passed=True,
    )

    assert result.success, result.error
    qa_by_name = {check["check"]: check for check in result.output.checks}
    assert qa_by_name["human_scholarly_review"]["passed"] is False
    assert "stale" in qa_by_name["human_scholarly_review"]["finding"]


def test_publication_pack_blocks_submission_ready_on_unresolved_orchestrator_gate(db):
    topic_id = _create_topic(db, "publication-pack-unresolved-orchestrator-gate-topic")
    artifacts = ArtifactManager(db)
    artifacts.record(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="evidence_pack",
        title="Evidence Pack",
        payload={"claims": [{"claim_id": "c1", "paper_ids": [1]}]},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack",
        payload={"sections": {"abstract": "Evidence-backed abstract [paper:1]."}},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="citation_sanitization_report",
        title="Citation Report",
        payload={"status": "pass"},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="figure_plan",
        title="Figure Plan",
        payload={"figures": []},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="final_bundle",
        title="Final Bundle",
        payload={"pdf": "paper.pdf"},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="process_summary",
        title="Process Summary",
        payload={"summary": "All key provenance reviewed."},
    )

    conn = db.connect()
    try:
        conn.execute(
            """
            INSERT INTO orchestrator_runs
                (topic_id, current_stage, stage_status, gate_status)
            VALUES (?, 'build', 'in_progress', 'needs_coverage')
            """,
            (topic_id,),
        )
        conn.commit()
    finally:
        conn.close()

    result = LocalBackend(db).execute(
        "publication_pack_generate",
        topic_id=topic_id,
    )

    assert result.success, result.error
    output = result.output
    assert isinstance(output, PublicationPackOutput)
    assert output.ready_for_review is True
    assert output.submission_ready is False
    qa_by_name = {check["check"]: check for check in output.qa_checks}
    assert qa_by_name["orchestrator_readiness"]["passed"] is False
    assert "needs_coverage" in qa_by_name["orchestrator_readiness"]["details"]


def test_publication_pack_requires_write_gate_pass_for_submission_ready(
    db, monkeypatch
):
    # Under test: the critical-open-issue path must yield gate=needs_review.
    # The orthogonal EAG exemplar-anchor invariant (default ON) would
    # short-circuit to gate=fail first; it has its own coverage.
    monkeypatch.setenv("RESEARCH_HARNESS_EAG_WRITE_GATE", "0")
    topic_id = _create_topic(db, "publication-pack-write-gate-topic")
    artifacts = ArtifactManager(db)
    artifacts.record(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="evidence_pack",
        title="Evidence Pack",
        payload={"claims": [{"claim_id": "c1", "paper_ids": [1]}]},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack",
        payload={"sections": {"abstract": "Evidence-backed abstract [paper:1]."}},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="citation_sanitization_report",
        title="Citation Report",
        payload={"status": "pass"},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="figure_plan",
        title="Figure Plan",
        payload={"figures": []},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="final_bundle",
        title="Final Bundle",
        payload={"pdf": "paper.pdf"},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="process_summary",
        title="Process Summary",
        payload={"summary": "All key provenance reviewed."},
    )

    conn = db.connect()
    try:
        conn.execute(
            """
            INSERT INTO review_issues
                (topic_id, stage, review_type, severity, category,
                 blocking, status, summary)
            VALUES (?, 'write', 'scholarly', 'critical', 'integrity',
                    1, 'open', 'critical review issue remains open')
            """,
            (topic_id,),
        )
        conn.execute(
            """
            INSERT INTO orchestrator_runs
                (topic_id, current_stage, stage_status, gate_status)
            VALUES (?, 'write', 'in_progress', '')
            """,
            (topic_id,),
        )
        conn.commit()
    finally:
        conn.close()

    result = LocalBackend(db).execute(
        "publication_pack_generate",
        topic_id=topic_id,
    )

    assert result.success, result.error
    output = result.output
    assert isinstance(output, PublicationPackOutput)
    assert output.ready_for_review is True
    assert output.submission_ready is False
    qa_by_name = {check["check"]: check for check in output.qa_checks}
    assert qa_by_name["orchestrator_readiness"]["passed"] is False
    assert "gate=needs_review" in qa_by_name["orchestrator_readiness"]["details"]


def test_publication_run_records_one_command_closure_artifact(db):
    topic_id = _create_topic(db, "publication-run-topic")
    artifacts = ArtifactManager(db)
    artifacts.record(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="evidence_pack",
        title="Evidence Pack",
        payload={"claims": [{"claim_id": "c1", "paper_ids": [1]}]},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack",
        payload={"sections": {"abstract": "Evidence-backed abstract [paper:1]."}},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="figure_plan",
        title="Figure Plan",
        payload={"figures": []},
    )

    result = LocalBackend(db).execute(
        "publication_run",
        topic_id=topic_id,
        target_profile="aaai",
    )

    assert result.success, result.error
    output = result.output
    assert isinstance(output, PublicationRunOutput)
    assert output.ready_for_review is True
    assert output.submission_ready is False
    assert output.status == "blocked"
    assert any(check["check"] == "venue_compliance" for check in output.blocking_checks)
    assert output.publication_run_artifact_id > 0
    assert output.publication_pack_artifact_id > 0
    assert {item["artifact_type"] for item in output.created_artifacts} >= {
        "citation_sanitization_report",
        "process_summary",
        "final_bundle",
        "publication_pack",
    }

    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT artifact_type, payload_json FROM project_artifacts WHERE id = ?",
            (output.publication_run_artifact_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["artifact_type"] == "publication_run"
    payload = json.loads(row["payload_json"])
    assert payload["publication_run_artifact_id"] == output.publication_run_artifact_id


def test_publication_run_preserves_orchestrator_blocker(db):
    topic_id = _create_topic(db, "publication-run-orchestrator-blocked-topic")
    artifacts = ArtifactManager(db)
    artifacts.record(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="evidence_pack",
        title="Evidence Pack",
        payload={"claims": [{"claim_id": "c1", "paper_ids": [1]}]},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack",
        payload={"sections": {"abstract": "Evidence-backed abstract [paper:1]."}},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="figure_plan",
        title="Figure Plan",
        payload={"figures": []},
    )
    conn = db.connect()
    try:
        conn.execute(
            """
            INSERT INTO orchestrator_runs
                (topic_id, current_stage, stage_status, gate_status)
            VALUES (?, 'build', 'in_progress', 'needs_coverage')
            """,
            (topic_id,),
        )
        conn.commit()
    finally:
        conn.close()

    result = LocalBackend(db).execute(
        "publication_run",
        topic_id=topic_id,
        target_profile="aaai",
    )

    assert result.success, result.error
    output = result.output
    assert isinstance(output, PublicationRunOutput)
    assert output.ready_for_review is True
    assert output.submission_ready is False
    assert output.status == "blocked"
    assert any(
        check["check"] == "orchestrator_readiness" for check in output.blocking_checks
    )


def test_publication_pack_next_actions_prioritize_missing_required(db):
    topic_id = _create_topic(db, "publication-pack-required-actions-topic")

    result = LocalBackend(db).execute(
        "publication_pack_generate",
        topic_id=topic_id,
    )

    assert result.success, result.error
    output = result.output
    assert isinstance(output, PublicationPackOutput)
    assert output.ready_for_review is False
    assert [action["component"] for action in output.next_actions[:2]] == [
        "manuscript_sections",
        "evidence_pack",
    ]
    assert all(action["severity"] == "blocking" for action in output.next_actions[:2])


def test_publication_pack_backfill_records_safe_qa_artifacts(db):
    topic_id = _create_topic(db, "publication-pack-backfill-topic")
    artifacts = ArtifactManager(db)
    artifacts.record(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="evidence_pack",
        title="Evidence Pack",
        payload={"claims": [{"claim_id": "c1", "paper_ids": [1]}]},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack",
        payload={"sections": {"intro": "Evidence-backed intro without citations."}},
    )

    spec = get_primitive_spec("publication_pack_backfill")
    assert spec is not None
    assert spec.requires_llm is False

    result = LocalBackend(db).execute(
        "publication_pack_backfill",
        topic_id=topic_id,
        target_profile="high-impact-general",
        record_artifact=True,
    )

    assert result.success, result.error
    output = result.output
    assert output.topic_id == topic_id
    assert output.created_count == 4
    assert {item["artifact_type"] for item in output.created_artifacts} == {
        "citation_sanitization_report",
        "process_summary",
        "final_bundle",
        "publication_pack",
    }
    assert output.ready_for_review is True
    assert output.submission_ready is False
    action_components = {
        action["component"] for action in output.remaining_next_actions
    }
    assert "figure_plan" in action_components
    assert "final_bundle" in action_components


def test_publication_pack_backfill_refuses_missing_required_components(db):
    topic_id = _create_topic(db, "publication-pack-backfill-empty-topic")

    result = LocalBackend(db).execute(
        "publication_pack_backfill",
        topic_id=topic_id,
    )

    assert result.success, result.error
    output = result.output
    assert output.created_count == 0
    assert output.ready_for_review is False
    assert [action["component"] for action in output.remaining_next_actions[:2]] == [
        "manuscript_sections",
        "evidence_pack",
    ]
    assert any(
        skipped["component"] == "required_components"
        for skipped in output.skipped_actions
    )


def test_publication_pack_can_record_publication_pack_artifact(db):
    topic_id = _create_topic(db, "publication-pack-record-topic")
    artifacts = ArtifactManager(db)
    artifacts.record(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="evidence_pack",
        title="Evidence Pack",
        payload={"claims": [{"claim_id": "c1", "paper_ids": [1]}]},
    )
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack",
        payload={"sections": {"related_work": "Evidence-backed text [paper:1]."}},
    )

    result = LocalBackend(db).execute(
        "publication_pack_generate",
        topic_id=topic_id,
        record_artifact=True,
    )

    assert result.success, result.error
    output = result.output
    assert isinstance(output, PublicationPackOutput)
    assert output.publication_pack_artifact_id > 0

    conn = db.connect()
    try:
        row = conn.execute(
            """
            SELECT stage, artifact_type, payload_json
            FROM project_artifacts
            WHERE id = ?
            """,
            (output.publication_pack_artifact_id,),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row["stage"] == "write"
    assert row["artifact_type"] == "publication_pack"
    payload = json.loads(row["payload_json"])
    assert (
        payload["publication_pack_artifact_id"] == output.publication_pack_artifact_id
    )
    assert payload["contract"]["artifact_type"] == "publication_pack"
    assert payload["components"]["manuscript_sections"]["status"] == "present"
    assert payload["next_actions"][0]["component"] == "citation_integrity"


def test_publication_pack_artifact_schema_requires_contract_components_and_sources(db):
    assert ARTIFACT_SCHEMAS["publication_pack"]["required_fields"] == [
        "components",
        "contract",
        "source_artifacts",
    ]

    topic_id = _create_topic(db, "publication-pack-schema-topic")
    artifacts = ArtifactManager(db)
    artifacts.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="publication_pack",
        title="Broken Publication Pack",
        payload={"components": {}},
    )

    violations = InvariantChecker(db).check_artifact_schemas(topic_id, "write")
    messages = [v.message for v in violations]
    assert any("missing required field 'contract'" in message for message in messages)
    assert any(
        "missing required field 'source_artifacts'" in message for message in messages
    )
