from __future__ import annotations

import json
from pathlib import Path

from research_harness.orchestrator.service import OrchestratorService


def _seed_topic_project(conn, topic_id: int = 1) -> None:
    conn.execute(
        "INSERT INTO topics (id, name, description, status) VALUES (?, ?, ?, ?)",
        (
            topic_id,
            "eventgraph-urban-sports-consumption",
            "ArcGIS sports-event consumption spatiotemporal analysis",
            "active",
        ),
    )
    conn.execute(
        "INSERT INTO projects (id, topic_id, name, description) VALUES (?, ?, ?, ?)",
        (topic_id, topic_id, "EventGraph", "EventGraph test project"),
    )


def _seed_paper(
    conn,
    paper_id: int,
    title: str,
    *,
    topic_id: int = 1,
    status: str = "meta_only",
    relevance: str = "medium",
    year: int | None = 2026,
    venue: str = "Test Venue",
    doi: str | None = None,
    url: str | None = None,
    pdf_path: str = "",
    abstract: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO papers
            (id, title, year, venue, doi, url, pdf_path, status, abstract)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (paper_id, title, year, venue, doi, url, pdf_path, status, abstract),
    )
    conn.execute(
        "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (?, ?, ?)",
        (paper_id, topic_id, relevance),
    )


def _record_required_build_artifacts(svc: OrchestratorService, topic_id: int) -> None:
    for artifact_type in (
        "literature_map",
        "paper_pool_snapshot",
        "citation_expansion_report",
        "acquisition_report",
    ):
        svc.record_artifact(
            topic_id=topic_id,
            stage="build",
            artifact_type=artifact_type,
            title=artifact_type,
            payload={"status": "active", "artifact_type": artifact_type},
        )


def _seed_topic39_style_noisy_pool(conn, *, topic_id: int = 1) -> None:
    _seed_paper(conn, 1, "", doi="10.test/empty", topic_id=topic_id)
    _seed_paper(
        conn,
        2,
        "Retro-Augmented Spatiotemporal Causal Decision Trees for Cellular Rejuvenation",
        doi="10.test/cellular",
        topic_id=topic_id,
    )
    _seed_paper(
        conn,
        3,
        "Transaction Fraud Detection Method Based on Event Temporal Graph Attention Network",
        doi="10.test/fraud",
        topic_id=topic_id,
    )
    _seed_paper(
        conn,
        4,
        "Proceedings of the 6th National Big Data Health Science Conference",
        doi="10.test/health",
        topic_id=topic_id,
    )
    _seed_paper(
        conn,
        5,
        "Visualizing urban mobility",
        url="https://example.test/visual-a",
        topic_id=topic_id,
    )
    _seed_paper(
        conn,
        6,
        "Visualizing urban mobility",
        url="https://example.test/visual-b",
        topic_id=topic_id,
    )
    for offset in range(7, 45):
        _seed_paper(
            conn,
            offset,
            f"Generic urban mobility candidate {offset}",
            url=f"https://example.test/generic-{offset}",
            topic_id=topic_id,
        )
    _seed_paper(
        conn,
        45,
        "Causal spatiotemporal graph learning for sports event consumption",
        status="annotated",
        relevance="high",
        year=2025,
        venue="KDD",
        doi="10.test/core",
        pdf_path="/tmp/core.pdf",
        abstract="sports event consumption mobility GIS causal graph evaluation",
        topic_id=topic_id,
    )


def _seed_screened_relevant_pool(conn, *, topic_id: int = 1) -> None:
    abstract = (
        "dataset source ArcGIS hotspot GIS spatial statistics causal "
        "difference-in-differences spatiotemporal graph learning sports event "
        "consumption economic impact baseline evaluation protocol"
    )
    for offset in range(1, 51):
        _seed_paper(
            conn,
            100 + offset,
            f"Screened urban sports event consumption evidence {offset}",
            topic_id=topic_id,
            status="annotated",
            relevance="high",
            year=2024 + (offset % 2),
            venue="KDD",
            doi=f"10.test/screened-{offset}",
            pdf_path=f"/tmp/screened-{offset}.pdf",
            abstract=abstract,
        )


def test_build_gate_reports_actionable_screening_reasons(db, conn) -> None:
    _seed_topic_project(conn)
    conn.commit()
    svc = OrchestratorService(db)
    svc.resume_run(1, mode="strict", force_stage="build")
    _record_required_build_artifacts(svc, topic_id=1)

    _seed_topic39_style_noisy_pool(conn)
    conn.commit()

    status = svc.get_status(1)

    assert status["gate"]["decision"] == "needs_coverage"
    assert status["gate"]["can_advance"] is False
    reason_codes = {reason["code"] for reason in status["gate"]["reasons"]}
    assert "too_many_meta_only" in reason_codes
    assert "off_topic_core_candidates" in reason_codes
    assert "empty_title_candidates" in reason_codes
    assert "duplicate_title_candidates" in reason_codes
    assert "insufficient_coverage_eligible_papers" in reason_codes
    assert status["gate"]["paper_pool_audit"]["counts"]["meta_only"] == 44
    assert status["gate"]["coverage"]["linked_paper_count"] == 45
    assert status["gate"]["coverage"]["annotated_pdf_count"] == 1
    assert status["gate"]["coverage"]["required_count"] == 50
    assert status["gate"]["coverage"]["failed_check"] == "annotated_pdf_count"
    # BUG-004: no domain profile -> no required roles (was global-default fallback).
    assert status["gate"]["coverage"]["missing_roles"] == []
    assert status["gate"]["paper_pool_audit"]["required_roles"] == []
    assert any(
        "paper_pool_audit" in action for action in status["gate"]["recovery_actions"]
    )


def test_build_gate_details_use_social_science_observational_roles(db, conn) -> None:
    """Topic-specific evidence portfolios come from the plan, not gate code."""
    _seed_topic_project(conn)
    conn.commit()
    svc = OrchestratorService(db)
    svc.resume_run(1, mode="strict", force_stage="build")
    svc.record_artifact(
        topic_id=1,
        stage="init",
        artifact_type="paper_plan",
        title="HSSC intake plan",
        payload={
            "domain_profile": {
                "discipline": "social_science",
                "study_design": "observational",
                "required_evidence_roles": [
                    "dataset_source",
                    "gis_spatial_statistics",
                    "causal_identification",
                    "sports_event_consumption",
                    "baseline_evaluation",
                ],
            }
        },
    )
    _record_required_build_artifacts(svc, topic_id=1)

    _seed_paper(
        conn,
        201,
        "Annotated POI dataset for sports event consumption",
        status="annotated",
        relevance="high",
        year=2024,
        venue="HSSC",
        doi="10.test/social-dataset",
        pdf_path="/tmp/social-dataset.pdf",
        abstract="point of interest transaction mobility record",
    )
    conn.execute(
        """
        UPDATE paper_topics
        SET screening_status = 'screened_in', manuscript_eligible = 1
        WHERE topic_id = 1 AND paper_id = 201
        """
    )
    conn.commit()

    status = svc.get_status(1)

    required_roles = status["gate"]["paper_pool_audit"]["required_roles"]
    assert "spatiotemporal_graph_learning" not in required_roles
    assert required_roles == [
        "dataset_source",
        "gis_spatial_statistics",
        "causal_identification",
        "sports_event_consumption",
        "baseline_evaluation",
    ]


def test_build_gate_default_social_science_roles_are_topic_agnostic(db, conn) -> None:
    """Without an explicit plan role list, the discipline default must not
    demand topic-specific evidence such as sports_event_consumption."""
    _seed_topic_project(conn)
    conn.commit()
    svc = OrchestratorService(db)
    svc.resume_run(1, mode="strict", force_stage="build")
    svc.record_artifact(
        topic_id=1,
        stage="init",
        artifact_type="paper_plan",
        title="Generic social-science observational plan",
        payload={
            "domain_profile": {
                "discipline": "social_science",
                "study_design": "observational",
            }
        },
    )
    _record_required_build_artifacts(svc, topic_id=1)

    status = svc.get_status(1)

    required_roles = status["gate"]["paper_pool_audit"]["required_roles"]
    assert required_roles == [
        "dataset_source",
        "causal_identification",
        "baseline_evaluation",
    ]
    assert "sports_event_consumption" not in required_roles
    assert "gis_spatial_statistics" not in required_roles


def test_build_gate_passes_with_screened_relevant_coverage(db, conn) -> None:
    _seed_topic_project(conn)
    conn.commit()
    svc = OrchestratorService(db)
    svc.resume_run(1, mode="strict", force_stage="build")
    _record_required_build_artifacts(svc, topic_id=1)
    _seed_screened_relevant_pool(conn)
    conn.commit()

    status = svc.get_status(1)

    assert status["gate"]["decision"] == "pass"
    assert status["gate"]["can_advance"] is True
    assert status["gate"]["reasons"] == []
    assert status["gate"]["paper_pool_audit"]["counts"]["coverage_eligible"] == 50

    result = svc.advance(1, actor="test")

    assert result["success"] is True
    assert result["from_stage"] == "build"
    assert result["to_stage"] == "analyze"


def test_build_gate_details_allow_explicit_demo_limited_seed_pool(db, conn) -> None:
    _seed_topic_project(conn)
    conn.commit()
    svc = OrchestratorService(db)
    svc.resume_run(1, mode="demo", force_stage="build")
    for artifact_type in (
        "literature_map",
        "citation_expansion_report",
        "acquisition_report",
    ):
        svc.record_artifact(
            topic_id=1,
            stage="build",
            artifact_type=artifact_type,
            title=artifact_type,
            payload={"status": "active", "artifact_type": artifact_type},
        )
    svc.record_artifact(
        topic_id=1,
        stage="build",
        artifact_type="paper_pool_snapshot",
        title="paper_pool_snapshot",
        payload={
            "status": "active",
            "paper_count": 3,
            "evidence_boundary": "demo_limited_seed_pool",
            "submission_readiness": "not_submission_ready",
        },
    )
    for offset in range(1, 4):
        _seed_paper(
            conn,
            offset,
            f"Demo seed sports event consumption evidence {offset}",
            topic_id=1,
            status="meta_only",
            url=f"https://example.test/demo-{offset}",
        )
    conn.commit()

    status = svc.get_status(1)

    assert status["gate"]["decision"] == "pass"
    assert status["gate"]["can_advance"] is True
    assert status["gate"]["demo_evidence_boundary"] == {
        "allowed": True,
        "reason": "demo_limited_seed_pool",
    }
    assert status["gate"]["reasons"] == []


def test_failed_build_advance_marks_run_blocked_with_screening_hint(db, conn) -> None:
    _seed_topic_project(conn)
    conn.commit()
    svc = OrchestratorService(db)
    svc.resume_run(1, mode="strict", force_stage="build")
    _record_required_build_artifacts(svc, topic_id=1)
    _seed_topic39_style_noisy_pool(conn)
    conn.commit()

    result = svc.advance(1, actor="test")

    assert result["success"] is False
    assert result["gate_decision"] == "needs_coverage"
    assert result["gate_status"] == "needs_screening"
    assert result["stage_status"] == "blocked"
    assert result["gate_details"]["reasons"]
    assert any("targeted_search" in action for action in result["recovery_actions"])

    blocked = svc.get_status(1)
    assert blocked["run"]["stage_status"] == "blocked"
    assert blocked["run"]["gate_status"] == "needs_screening"

    row = conn.execute(
        """
        SELECT event_type, status, gate_type, rationale, payload_json
        FROM orchestrator_stage_events
        WHERE topic_id = ? AND event_type = 'gate_blocked'
        ORDER BY id DESC LIMIT 1
        """,
        (1,),
    ).fetchone()
    assert row is not None
    assert row["status"] == "blocked"
    assert row["gate_type"] == "coverage_gate"
    assert "needs_screening" in row["rationale"]
    payload = json.loads(row["payload_json"])
    assert payload["gate_status"] == "needs_screening"
    assert payload["gate_details"]["reasons"]


def test_paper_production_runner_reports_build_screening_block(
    db,
    conn,
    tmp_path: Path,
) -> None:
    from research_harness.auto_runner.runner import _paper_production_gate_block

    _seed_topic_project(conn)
    conn.commit()
    svc = OrchestratorService(db)
    svc.resume_run(1, mode="strict", force_stage="build")
    _record_required_build_artifacts(svc, topic_id=1)
    _seed_topic39_style_noisy_pool(conn)
    conn.commit()

    advance_result = svc.advance(1, actor="test")
    gate_block = _paper_production_gate_block(
        db=db,
        topic_id=1,
        stage="build",
        gate_decision=str(advance_result["gate_decision"]),
        checkpoint_path=tmp_path / "checkpoint.json",
        advance_result=advance_result,
    )

    assert gate_block is not None
    assert gate_block["status"] == "blocked"
    assert gate_block["blocker_code"] == "paper_production_screening_gate"
    assert gate_block["gate_status"] == "needs_screening"
    assert gate_block["stage_status"] == "blocked"
    assert "too_many_meta_only" in gate_block["paper_production_gate"]["blockers"]
    assert gate_block["gate_details"]["reasons"]
    assert any("targeted_search" in action for action in gate_block["recovery_actions"])
