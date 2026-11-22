"""Tests for scoped manuscript artifact supersede."""

from __future__ import annotations

from research_harness._workflow.execution.artifact_reset import (
    DEFAULT_RESET_TYPES,
    PROTECTED_ARTIFACT_TYPES,
    supersede_manuscript_artifacts,
)
from research_harness.orchestrator.service import OrchestratorService


def _make_topic(db, name: str = "artifact-reset-test") -> int:
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO topics (name, description) VALUES (?, ?)", (name, name)
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def _seed(db, topic_id: int) -> None:
    svc = OrchestratorService(db)
    svc.record_artifact(
        topic_id,
        stage="write",
        artifact_type="section_draft",
        title="Related Work draft",
        payload={"section": "related_work"},
        supersede_previous=False,
    )
    svc.record_artifact(
        topic_id,
        stage="write",
        artifact_type="section_draft",
        title="Methods draft",
        payload={"section": "methods"},
        supersede_previous=False,
    )
    svc.record_artifact(
        topic_id, stage="write", artifact_type="draft_pack", title="pack"
    )


def test_section_filter_narrows_section_drafts_only(db):
    topic_id = _make_topic(db)
    _seed(db, topic_id)

    result = supersede_manuscript_artifacts(
        db,
        topic_id=topic_id,
        stages=["write"],
        sections=["related_work"],
    )

    by_type: dict[str, list[str]] = {}
    for item in result["superseded"]:
        by_type.setdefault(item["type"], []).append(item["title"])
    assert by_type["draft_pack"] == ["pack"]
    assert by_type["section_draft"] == ["Related Work draft"]
    assert result["section_match_fallback"] is False
    # Methods draft remains active
    svc = OrchestratorService(db)
    remaining = [
        artifact.title
        for artifact in svc.list_artifacts(topic_id, stage="write")
        if artifact.artifact_type == "section_draft"
    ]
    assert remaining == ["Methods draft"]


def test_section_zero_match_falls_back_to_all_sections(db):
    topic_id = _make_topic(db)
    _seed(db, topic_id)

    result = supersede_manuscript_artifacts(
        db,
        topic_id=topic_id,
        stages=["write"],
        sections=["nonexistent-section"],
        dry_run=True,
    )

    assert result["section_match_fallback"] is True
    section_titles = {
        item["title"]
        for item in result["superseded"]
        if item["type"] == "section_draft"
    }
    assert section_titles == {"Related Work draft", "Methods draft"}


def test_protected_types_never_superseded(db):
    topic_id = _make_topic(db)
    svc = OrchestratorService(db)
    svc.record_artifact(
        topic_id,
        stage="write",
        artifact_type="human_feedback_record",
        title="feedback",
        supersede_previous=False,
    )

    result = supersede_manuscript_artifacts(
        db,
        topic_id=topic_id,
        stages=["write"],
        types=set(DEFAULT_RESET_TYPES) | set(PROTECTED_ARTIFACT_TYPES),
    )

    assert result["superseded"] == []
    assert (
        svc.get_latest_artifact(topic_id, "write", "human_feedback_record") is not None
    )


def test_dry_run_lists_without_mutation(db):
    topic_id = _make_topic(db)
    _seed(db, topic_id)

    result = supersede_manuscript_artifacts(
        db, topic_id=topic_id, stages=["write"], dry_run=True
    )

    assert len(result["superseded"]) == 3
    svc = OrchestratorService(db)
    assert svc.get_latest_artifact(topic_id, "write", "draft_pack") is not None


def test_reset_run_cli_section_passthrough(runner):
    import json
    import os

    from research_harness.cli import main
    from research_harness.storage.db import Database

    db = Database(os.environ["RESEARCH_HARNESS_DB_PATH"])
    db.migrate()
    topic_id = _make_topic(db, "cli-reset-section")
    _seed(db, topic_id)

    result = runner.invoke(
        main,
        [
            "--json",
            "paper-production",
            "reset-run",
            "--topic",
            str(topic_id),
            "--section",
            "related_work",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["section_filter"] == ["related_work"]
    assert payload["section_match_fallback"] is False
    section_rows = [
        item for item in payload["superseded"] if item["type"] == "section_draft"
    ]
    assert [item["title"] for item in section_rows] == ["Related Work draft"]
