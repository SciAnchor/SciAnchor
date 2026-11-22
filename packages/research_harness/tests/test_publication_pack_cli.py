"""CLI coverage for publication-pack readiness generation."""

from __future__ import annotations

import json
import os

from research_harness.cli import main
from research_harness.orchestrator.artifacts import ArtifactManager
from research_harness.storage.db import Database


def _seed_topic_with_publication_inputs(db_path: str) -> int:
    db = Database(db_path)
    db.migrate()
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO topics (name, description, target_venue) VALUES (?, ?, ?)",
            ("publication-cli", "CLI publication pack test", "ICLR"),
        )
        conn.commit()
        topic_id = int(cur.lastrowid)
    finally:
        conn.close()

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
        payload={"sections": {"intro": "Evidence-backed intro [paper:1]."}},
    )
    return topic_id


def test_publication_pack_generate_json_records_artifact(runner):
    db_path = os.environ["RESEARCH_HUB_DB_PATH"]
    topic_id = _seed_topic_with_publication_inputs(db_path)

    result = runner.invoke(
        main,
        [
            "--json",
            "publication-pack",
            "generate",
            "--topic",
            "publication-cli",
            "--target-profile",
            "nature-brief",
            "--record-artifact",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["topic_id"] == topic_id
    assert payload["target_profile"] == "nature-brief"
    assert payload["ready_for_review"] is True
    assert payload["submission_ready"] is False
    assert payload["publication_pack_artifact_id"] > 0
    assert payload["components"]["manuscript_sections"]["status"] == "present"
    assert payload["components"]["evidence_pack"]["status"] == "present"
    assert payload["next_actions"][0]["component"] == "citation_integrity"
    assert "figure_plan" in payload["missing_optional"]

    db = Database(db_path)
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT artifact_type, payload_json FROM project_artifacts WHERE id = ?",
            (payload["publication_pack_artifact_id"],),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["artifact_type"] == "publication_pack"
    artifact_payload = json.loads(row["payload_json"])
    assert (
        artifact_payload["publication_pack_artifact_id"]
        == payload["publication_pack_artifact_id"]
    )


def test_publication_pack_generate_text_shows_missing_required(runner):
    db = Database(os.environ["RESEARCH_HUB_DB_PATH"])
    db.migrate()
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (name, description) VALUES (?, ?)",
            ("publication-cli-empty", "no artifacts yet"),
        )
        conn.commit()
    finally:
        conn.close()

    result = runner.invoke(
        main,
        [
            "publication-pack",
            "generate",
            "--topic",
            "publication-cli-empty",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Publication pack: not ready; submission checks pending" in result.output
    assert "missing required: manuscript_sections, evidence_pack" in result.output
    assert "next actions: manuscript_sections, evidence_pack" in result.output


def test_publication_pack_backfill_json_records_safe_artifacts(runner):
    db_path = os.environ["RESEARCH_HUB_DB_PATH"]
    topic_id = _seed_topic_with_publication_inputs(db_path)

    result = runner.invoke(
        main,
        [
            "--json",
            "publication-pack",
            "backfill",
            "--topic",
            "publication-cli",
            "--record-artifact",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["topic_id"] == topic_id
    assert payload["created_count"] == 4
    assert {item["artifact_type"] for item in payload["created_artifacts"]} == {
        "citation_sanitization_report",
        "process_summary",
        "final_bundle",
        "publication_pack",
    }
    assert payload["ready_for_review"] is True
    assert payload["submission_ready"] is False


def test_publication_pack_run_json_records_publication_run(runner):
    db_path = os.environ["RESEARCH_HUB_DB_PATH"]
    topic_id = _seed_topic_with_publication_inputs(db_path)

    result = runner.invoke(
        main,
        [
            "--json",
            "publication-pack",
            "run",
            "--topic",
            "publication-cli",
            "--target-profile",
            "aaai",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["topic_id"] == topic_id
    assert payload["target_profile"] == "aaai"
    assert payload["ready_for_review"] is True
    assert payload["submission_ready"] is False
    assert payload["status"] == "blocked"
    blocking_checks = {check["check"] for check in payload["blocking_checks"]}
    assert "venue_compliance" in blocking_checks
    assert "orchestrator_readiness" in blocking_checks
    assert any(
        action["component"] == "venue_compliance" for action in payload["next_actions"]
    )
    assert payload["publication_pack_artifact_id"] > 0
    assert payload["publication_run_artifact_id"] > 0

    db = Database(db_path)
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT artifact_type FROM project_artifacts WHERE id = ?",
            (payload["publication_run_artifact_id"],),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["artifact_type"] == "publication_run"


def test_publication_pack_venue_check_json_records_report(runner):
    db_path = os.environ["RESEARCH_HUB_DB_PATH"]
    topic_id = _seed_topic_with_publication_inputs(db_path)

    result = runner.invoke(
        main,
        [
            "--json",
            "publication-pack",
            "venue-check",
            "--topic",
            "publication-cli",
            "--target-profile",
            "aaai",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["topic_id"] == topic_id
    assert payload["target_profile"] == "aaai"
    assert payload["status"] == "fail"
    assert payload["passed"] is False
    assert payload["venue_compliance_report_artifact_id"] > 0
    assert any(
        item["check"] == "venue_pdf_compile" for item in payload["blocking_findings"]
    )

    db = Database(db_path)
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT artifact_type FROM project_artifacts WHERE id = ?",
            (payload["venue_compliance_report_artifact_id"],),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["artifact_type"] == "venue_compliance_report"
