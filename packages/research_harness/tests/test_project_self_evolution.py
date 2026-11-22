from __future__ import annotations

import json

from research_harness.evolution.harness import (
    ImprovementCandidate,
    PDFQualityIssue,
    PDFQualityReplayTrajectory,
    PDFQualitySignal,
    PDFQualityTrajectoryPoint,
    build_candidate_archive_record_from_researchflowbench_score,
    build_champion_registry_entry,
    build_replay_split,
    collect_candidate_archive_records_from_artifacts,
    collect_final_bundle_replay_discovery_report,
    collect_pdf_quality_replay_trajectory,
    evaluate_pdf_quality_replay_trajectory,
    record_pdf_quality_trajectory_gate_report,
    record_self_evolution_archive_from_artifacts,
    scan_pdf_quality_bundle,
    triage_pdf_quality_signal,
)
from research_harness.orchestrator.service import OrchestratorService


def test_replay_split_requires_source_and_promotion_examples() -> None:
    incubating = build_replay_split(candidate_id="candidate.empty")

    assert incubating.incubating is True
    assert "missing source replay references" in incubating.reasons
    assert "not enough promotion replay examples" in incubating.reasons

    ready = build_replay_split(
        candidate_id="candidate.ready",
        source_refs=("project_artifacts:1",),
        promotion_test_refs=("litsearch.q1",),
    )

    assert ready.incubating is False


def test_champion_registry_promotes_only_replay_ready_candidates() -> None:
    candidate = ImprovementCandidate(
        candidate_id="candidate.rfb.litsearch.q1",
        finding_id="finding.rfb.litsearch.q1",
        title="LitSearch replay candidate",
        target_kind="benchmark:litsearch",
        affected_surfaces=("eval", "retrieval"),
        priority_score=2,
        verification_plan=("Replay LitSearch promotion split.",),
        status="verified",
    )
    record = build_candidate_archive_record_from_researchflowbench_score(
        candidate,
        benchmark_id="litsearch",
        task_id="litsearch.q1",
        score={
            "task_id": "litsearch.q1",
            "recall_at_k": 1.0,
            "source_refs": ("project_artifacts:10",),
            "promotion_test_refs": ("litsearch.q1",),
        },
        split="promotion_test",
        gate_action="promote",
        artifact_refs=("project_artifacts:10:researchflowbench_score_report",),
    )

    champion = build_champion_registry_entry(
        target_kind="benchmark:litsearch",
        archive_records=(record,),
    )

    assert champion is not None
    assert champion.champion_candidate_id == "candidate.rfb.litsearch.q1"
    assert champion.replay_refs == ("litsearch.q1",)
    assert champion.promotion_strength == "promotion_test_replay"


def test_manual_archive_run_records_archive_and_champion_packs(db) -> None:
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (id, name, description) VALUES (8, ?, ?)",
            ("self-evolution-mvp", "MVP self-evolution"),
        )
        conn.execute(
            "INSERT INTO projects (id, topic_id, name, description) VALUES (8, 8, ?, ?)",
            ("self-evolution-mvp", "MVP self-evolution"),
        )
        conn.execute(
            """
            INSERT INTO project_artifacts
                (id, project_id, topic_id, stage, artifact_type, status, stale,
                 title, payload_json)
            VALUES (?, ?, ?, 'eval', 'researchflowbench_score_report', 'active',
                    0, ?, ?)
            """,
            (
                801,
                8,
                8,
                "LitSearch score report",
                json.dumps(
                    {
                        "benchmark_id": "litsearch",
                        "gate_action": "promote",
                        "scores": [
                            {
                                "task_id": "litsearch.q1",
                                "split": "promotion_test",
                                "recall_at_k": 1.0,
                                "source_refs": ["project_artifacts:801"],
                                "promotion_test_refs": ["litsearch.q1"],
                            }
                        ],
                    }
                ),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    records = collect_candidate_archive_records_from_artifacts(db, topic_id=8)
    assert len(records) == 1
    assert records[0].gate_action == "promote"

    summary = record_self_evolution_archive_from_artifacts(
        OrchestratorService(db),
        db,
        topic_id=8,
    )

    assert summary["record_count"] == 1
    assert summary["champion_entry_count"] == 1
    assert summary["mutation_performed"] is False
    assert summary["archive_artifact_id"]
    assert summary["champion_artifact_id"]


def test_pdf_quality_scan_and_triage_are_deterministic(tmp_path) -> None:
    tex_path = tmp_path / "paper.tex"
    log_path = tmp_path / "paper.log"
    pdf_path = tmp_path / "paper.pdf"
    tex_path.write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\includegraphics{missing-figure.png}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    log_path.write_text("Overfull \\hbox (12.0pt too wide)\n", encoding="utf-8")
    pdf_path.write_bytes(b"%PDF-1.4\n")

    signal = scan_pdf_quality_bundle(
        tex_path=str(tex_path),
        pdf_path=str(pdf_path),
        log_path=str(log_path),
        topic_id=8,
        target_profile="aaai",
        artifact_id=716,
    )
    finding = triage_pdf_quality_signal(signal)

    assert signal.metadata["issue_count"] >= 1
    assert finding.source_kind == "pdf_quality_signal"
    assert "final_bundle" in finding.affected_surfaces


def test_pdf_quality_trajectory_gate_records_replay_decision(db) -> None:
    trajectory = PDFQualityReplayTrajectory(
        topic_id=8,
        target_profile="aaai",
        points=(
            PDFQualityTrajectoryPoint(
                artifact_id=716,
                topic_id=8,
                target_profile="aaai",
                evidence_source="project_artifacts:716:final_bundle",
                issue_count=3,
                blocking_issue_count=1,
            ),
            PDFQualityTrajectoryPoint(
                artifact_id=771,
                topic_id=8,
                target_profile="aaai",
                evidence_source="project_artifacts:771:final_bundle",
                issue_count=0,
                blocking_issue_count=0,
            ),
        ),
    )

    result = evaluate_pdf_quality_replay_trajectory(trajectory)

    assert result.passed is True
    assert result.action == "ready_for_held_out_replay"

    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (id, name, description) VALUES (8, ?, ?)",
            ("trajectory-topic", "Trajectory topic"),
        )
        conn.execute(
            "INSERT INTO projects (id, topic_id, name, description) VALUES (8, 8, ?, ?)",
            ("trajectory-topic", "Trajectory topic"),
        )
        conn.execute(
            """
            INSERT INTO project_artifacts
                (id, project_id, topic_id, stage, artifact_type, status, stale,
                 title, payload_json)
            VALUES (?, ?, ?, 'write', 'final_bundle', 'active', 0, ?, ?)
            """,
            (716, 8, 8, "Final bundle v1", json.dumps({})),
        )
        conn.execute(
            """
            INSERT INTO project_artifacts
                (id, project_id, topic_id, stage, artifact_type, status, stale,
                 title, payload_json)
            VALUES (?, ?, ?, 'write', 'final_bundle', 'active', 0, ?, ?)
            """,
            (771, 8, 8, "Final bundle v2", json.dumps({})),
        )
        conn.commit()
    finally:
        conn.close()

    artifact = record_pdf_quality_trajectory_gate_report(
        OrchestratorService(db),
        topic_id=8,
        result=result,
    )

    assert artifact.artifact_type == "pdf_quality_trajectory_gate_report"
    assert artifact.payload["result"]["action"] == "ready_for_held_out_replay"


def test_final_bundle_replay_discovery_excludes_source_topic(db) -> None:
    conn = db.connect()
    try:
        for topic_id, name in ((8, "source"), (9, "held-out")):
            conn.execute(
                "INSERT INTO topics (id, name, description) VALUES (?, ?, ?)",
                (topic_id, name, name),
            )
            conn.execute(
                "INSERT INTO projects (id, topic_id, name, description) VALUES (?, ?, ?, ?)",
                (topic_id, topic_id, name, name),
            )
        for artifact_id, topic_id in ((716, 8), (901, 9)):
            conn.execute(
                """
                INSERT INTO project_artifacts
                    (id, project_id, topic_id, stage, artifact_type, status, stale,
                     title, payload_json)
                VALUES (?, ?, ?, 'write', 'final_bundle', 'active', 0, ?, ?)
                """,
                (
                    artifact_id,
                    topic_id,
                    topic_id,
                    f"Final bundle {artifact_id}",
                    json.dumps({"target_profile": "aaai"}),
                ),
            )
        conn.commit()
    finally:
        conn.close()

    report = collect_final_bundle_replay_discovery_report(
        db,
        source_topic_id=8,
        source_artifact_ids=(716,),
        target_profile="aaai",
    )

    assert report.accepted_artifact_ids == (901,)
    rejected = {candidate.artifact_id: candidate for candidate in report.candidates}
    assert rejected[716].accepted is False
    assert "same source topic" in rejected[716].exclusion_reasons


def test_pdf_quality_replay_trajectory_uses_durable_snapshots(db) -> None:
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (id, name, description) VALUES (8, ?, ?)",
            ("snapshot-topic", "Snapshot topic"),
        )
        conn.execute(
            "INSERT INTO projects (id, topic_id, name, description) VALUES (8, 8, ?, ?)",
            ("snapshot-topic", "Snapshot topic"),
        )
        conn.execute(
            """
            INSERT INTO project_artifacts
                (id, project_id, topic_id, stage, artifact_type, status, stale,
                 title, payload_json)
            VALUES (?, ?, ?, 'write', 'final_bundle', 'active', 0, ?, ?)
            """,
            (
                716,
                8,
                8,
                "Final bundle snapshot",
                json.dumps(
                    {
                        "pdf_quality_snapshot": {
                            "artifact_id": 716,
                            "target_profile": "aaai",
                            "issue_count": 2,
                            "blocking_issue_count": 1,
                        }
                    }
                ),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    trajectory = collect_pdf_quality_replay_trajectory(
        db,
        topic_id=8,
        target_profile="aaai",
    )

    assert trajectory.metadata["path_scan_used"] is False
    assert len(trajectory.points) == 1
    assert trajectory.points[0].artifact_id == 716
    assert trajectory.points[0].blocking_issue_count == 1


def test_pdf_quality_signal_can_be_constructed_for_replay_gate() -> None:
    signal = PDFQualitySignal(
        topic_id=8,
        target_profile="aaai",
        artifact_id=716,
        issues=(
            PDFQualityIssue(
                category="layout",
                severity="high",
                message="Overfull hbox",
            ),
        ),
    )

    finding = triage_pdf_quality_signal(signal)

    assert finding.priority in {"P0", "P1", "P2", "P3"}
