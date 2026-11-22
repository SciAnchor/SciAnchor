"""Tests for durable research-state update recording."""

from __future__ import annotations

import json
import os

from research_harness.cli import main
from research_harness.execution.local import LocalBackend
from research_harness.orchestrator.artifacts import ArtifactManager
from research_harness.orchestrator.invariants import ARTIFACT_SCHEMAS, InvariantChecker
from research_harness.primitives.registry import get_primitive_spec
from research_harness.primitives.types import ResearchStateUpdateOutput
from research_harness.storage.db import Database


def _create_topic(db, name: str = "research-state-topic") -> int:
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO topics (name, description) VALUES (?, ?)",
            (name, "topic for research state update tests"),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def test_research_state_update_records_structured_artifact(db):
    topic_id = _create_topic(db)

    spec = get_primitive_spec("research_state_update")
    assert spec is not None
    assert spec.requires_llm is False

    result = LocalBackend(db).execute(
        "research_state_update",
        topic_id=topic_id,
        stage="analyze",
        event_type="failure_fix",
        title="Gap timeout recovery",
        summary="gap_detect timed out; fallback gap map recorded",
        failure_reasons=["gap_detect timed out after 300s"],
        fix_records=["recorded fallback gap map from claim evidence"],
        contradictions=["workflow advertised full analyze automation"],
        review_feedback=["add timeout-aware gap chunking"],
        evidence_refs=[{"artifact_id": 12, "artifact_type": "evidence_pack"}],
        next_actions=["rerun gap_detect on core-paper subset"],
    )

    assert result.success, result.error
    assert isinstance(result.output, ResearchStateUpdateOutput)
    output = result.output
    assert output.research_state_update_artifact_id > 0
    assert output.failure_reasons == ["gap_detect timed out after 300s"]
    assert output.fix_records == ["recorded fallback gap map from claim evidence"]
    assert output.contradictions == ["workflow advertised full analyze automation"]
    assert output.review_feedback == ["add timeout-aware gap chunking"]

    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT stage, artifact_type, payload_json FROM project_artifacts WHERE id = ?",
            (output.research_state_update_artifact_id,),
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    assert row["stage"] == "analyze"
    assert row["artifact_type"] == "research_state_update"
    payload = json.loads(row["payload_json"])
    assert payload["research_state_update_artifact_id"] == (
        output.research_state_update_artifact_id
    )
    assert payload["event_type"] == "failure_fix"


def test_research_state_update_artifact_schema_is_registered():
    assert ARTIFACT_SCHEMAS["research_state_update"]["required_fields"] == [
        "event_type"
    ]


def test_research_state_update_keeps_prior_events_active(db):
    topic_id = _create_topic(db, "research-state-log-topic")
    backend = LocalBackend(db)

    first = backend.execute(
        "research_state_update",
        topic_id=topic_id,
        stage="build",
        event_type="failure",
        failure_reasons=["paper_acquire timed out"],
    )
    second = backend.execute(
        "research_state_update",
        topic_id=topic_id,
        stage="build",
        event_type="fix",
        fix_records=["added chunked acquisition follow-up"],
    )

    assert first.success, first.error
    assert second.success, second.error
    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT id, status FROM project_artifacts
            WHERE topic_id = ? AND stage = 'build'
              AND artifact_type = 'research_state_update'
            ORDER BY id
            """,
            (topic_id,),
        ).fetchall()
    finally:
        conn.close()

    assert len(rows) == 2
    assert {row["status"] for row in rows} == {"active"}


def test_stale_research_state_update_does_not_block_stage_gate(db):
    topic_id = _create_topic(db, "research-state-stale-topic")
    artifact = ArtifactManager(db).record(
        topic_id=topic_id,
        stage="write",
        artifact_type="research_state_update",
        title="Historical failure state",
        payload={"event_type": "failure", "failure_reasons": ["old draft stale"]},
    )
    conn = db.connect()
    try:
        conn.execute(
            """
            UPDATE project_artifacts
            SET stale = 1, stale_reason = 'upstream draft superseded'
            WHERE id = ?
            """,
            (artifact.id,),
        )
        conn.commit()
    finally:
        conn.close()

    assert InvariantChecker(db).check_no_stale_artifacts(topic_id, "write") == []


def test_research_state_record_cli_json_records_artifact(runner):
    db_path = os.environ["RESEARCH_HUB_DB_PATH"]
    db = Database(db_path)
    db.migrate()
    _create_topic(db, "research-state-cli")

    result = runner.invoke(
        main,
        [
            "--json",
            "research-state",
            "record",
            "--topic",
            "research-state-cli",
            "--stage",
            "build",
            "--event-type",
            "coverage_fix",
            "--failure",
            "build gate needed 50 papers",
            "--fix",
            "expanded pool with paper_search auto-ingest",
            "--contradiction",
            "publication package existed before build gate passed",
            "--review",
            "do not label as submission-ready until orchestrator reaches write",
            "--next-action",
            "refresh publication_run after gate advancement",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["stage"] == "build"
    assert payload["event_type"] == "coverage_fix"
    assert payload["research_state_update_artifact_id"] > 0
    assert payload["failure_reasons"] == ["build gate needed 50 papers"]
    assert payload["fix_records"] == ["expanded pool with paper_search auto-ingest"]
