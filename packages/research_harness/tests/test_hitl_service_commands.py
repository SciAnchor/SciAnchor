"""Service-layer contract tests for the nine HITL paper-production commands.

These pin the migration of topic_init / paper_production_* from MCP-side
executors to research_harness.auto_runner.hitl_commands behind
ResearchService, so the public MCP contract stays service-backed.
"""

from __future__ import annotations

import pytest

from research_harness.auto_runner import checkpoint as ckpt
from research_harness.auto_runner import hitl_commands
from research_harness.service import ResearchService
from research_harness.storage.db import Database


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "hitl.db")
    database.migrate()
    return database


def test_topic_init_creates_then_reuses(db):
    service = ResearchService(db=db)

    first = service.invoke(
        "topic_init",
        {"name": "HITL contract topic", "description": "desc", "tags": ["x"]},
    )
    assert first.status == "success"
    payload = first.output["output"]
    assert payload["created"] is True
    assert payload["tags_persisted"] is False

    second = service.invoke("topic_init", {"name": "HITL contract topic"})
    assert second.output["output"]["topic_id"] == payload["topic_id"]
    assert second.output["output"]["created"] is False


def test_pending_decisions_reads_checkpoint_request(db, tmp_path):
    state_dir = tmp_path / "state"
    checkpoint_data = ckpt.new_checkpoint(7, mode="standard")
    checkpoint_data["paper_production_run_policy"] = {"interaction_mode": "checkpoint"}
    ckpt.set_human_decision_request(
        checkpoint_data,
        stage="init",
        checkpoint="paper_production_evidence_gate",
        reason_code="insufficient_seed_papers",
        prompt="Broaden the search?",
        options=[
            {"action": "broaden_search", "recommended": True},
            {"action": "stop", "default_action": True},
        ],
    )
    ckpt.save_checkpoint(ckpt.checkpoint_path(state_dir, 7), checkpoint_data)

    result = hitl_commands.paper_production_pending_decisions(7, base_dir=state_dir)

    assert result["has_pending"] is True
    assert result["decision"]["recommended_action"] == "broaden_search"
    assert result["decision"]["default_action"] == "stop"
    assert result["decision"]["interaction_mode"] == "checkpoint"


def test_set_mode_then_mode_roundtrip(db, tmp_path):
    state_dir = tmp_path / "state"
    checkpoint_data = ckpt.new_checkpoint(9, mode="standard")
    ckpt.save_checkpoint(ckpt.checkpoint_path(state_dir, 9), checkpoint_data)

    changed = hitl_commands.paper_production_set_mode(
        9, mode="autonomous", base_dir=state_dir
    )
    assert changed["status"] == "success"
    assert changed["output"]["new_mode"] == "autonomous"

    current = hitl_commands.paper_production_mode(9, base_dir=state_dir)
    assert current["output"]["interaction_mode"] == "autonomous"
    assert current["output"]["can_auto_decide"] is True

    saved = ckpt.load_checkpoint(ckpt.checkpoint_path(state_dir, 9))
    assert any(
        item.get("event") == "interaction_mode_changed"
        for item in saved.get("history", [])
    )


def test_export_returns_recorded_manuscript_paths(db, tmp_path):
    from research_harness.orchestrator.service import OrchestratorService

    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (name, description) VALUES ('t', 't')")
        conn.execute(
            "INSERT INTO projects (id, topic_id, name, description) "
            "VALUES (1, 1, 'p', 'p')"
        )
        conn.commit()
    finally:
        conn.close()
    svc = OrchestratorService(db)
    tex = tmp_path / "main.tex"
    tex.write_text("\\documentclass{article}\\begin{document}x\\end{document}")
    pdf = tmp_path / "main.pdf"
    pdf.write_bytes(b"%PDF-1.5 fake")
    svc.commit_manuscript_version(topic_id=1, tex_path=str(tex), pdf_path=str(pdf))

    result = ResearchService(db=db).invoke("paper_production_export", {"topic_id": 1})

    output = result.output["output"]
    assert output["files"]["latex"] == [str(tex)]
    assert output["files"]["pdf"] == [str(pdf)]
    assert "final_bundle_quality_report" not in output["artifacts"]


def test_start_rejects_missing_topic_and_invalid_mode(db):
    service = ResearchService(db=db)

    missing = service.invoke(
        "paper_production_start",
        {"topic_id": 424242, "target_venue": "NeurIPS"},
    )
    assert missing.output.get("status") == "error"
    assert "not found" in missing.output.get("summary", "")

    invalid = service.invoke(
        "paper_production_set_mode", {"topic_id": 1, "mode": "bogus"}
    )
    assert invalid.status == "error"


def test_topic_state_service_command(db, tmp_path, monkeypatch):
    from pathlib import Path

    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)

    service = ResearchService(db=db)
    created = service.invoke("topic_init", {"name": "topic-state-service"})
    topic_id = created.output["output"]["topic_id"]

    result = service.invoke("topic_state", {"topic_id": topic_id})

    assert result.status == "success"
    payload = result.output["output"]
    assert payload["schema_version"] == "rh.topic_state.v1"
    assert payload["topic"]["id"] == topic_id
    assert payload["next_action"]["code"] in {"not_started", "resume"}
    assert result.output["next_actions"] == payload["next_action"]["commands"]
