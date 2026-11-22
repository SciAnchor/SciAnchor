"""Tests for the unified topic_state introspection (rh.topic_state.v1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_harness._core.config import RuntimeConfig
from research_harness.auto_runner import checkpoint as ckpt
from research_harness.auto_runner.topic_state import (
    TOPIC_STATE_SCHEMA_VERSION,
    topic_state,
)
from research_harness.orchestrator.service import OrchestratorService


@pytest.fixture(autouse=True)
def _hermetic_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)


def _config_for(db) -> RuntimeConfig:
    return RuntimeConfig(db_path=Path(db.db_path), source="explicit")


def _make_topic(db, name: str = "topic-state-test") -> int:
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO topics (name, description) VALUES (?, ?)", (name, name)
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def _state(db, topic, state_dir):
    return topic_state(
        db, topic=topic, base_dir=state_dir, runtime_config=_config_for(db)
    )


def test_missing_topic(db, tmp_path):
    result = _state(db, 999, tmp_path / "state")

    assert result["schema_version"] == TOPIC_STATE_SCHEMA_VERSION
    assert result["topic"] is None
    assert result["next_action"]["code"] == "missing_topic"


def test_not_started_topic(db, tmp_path):
    topic_id = _make_topic(db)

    result = _state(db, topic_id, tmp_path / "state")

    assert result["next_action"]["code"] == "not_started"
    assert any(
        "paper-production start" in cmd for cmd in result["next_action"]["commands"]
    )


def test_pending_decision_beats_everything(db, tmp_path):
    topic_id = _make_topic(db)
    OrchestratorService(db).resume_run(topic_id)
    state_dir = tmp_path / "state"
    checkpoint_data = ckpt.new_checkpoint(topic_id, mode="standard")
    ckpt.set_human_decision_request(
        checkpoint_data,
        stage="init",
        checkpoint="paper_production_evidence_gate",
        reason_code="insufficient_seed_papers",
        prompt="Broaden the search?",
        options=[{"action": "broaden_search", "recommended": True}],
    )
    checkpoint_data["stage_state"] = "error"  # would otherwise be fix_last_error
    ckpt.save_checkpoint(ckpt.checkpoint_path(state_dir, topic_id), checkpoint_data)

    result = _state(db, topic_id, state_dir)

    assert result["next_action"]["code"] == "answer_pending_decision"
    assert result["pending_decision"]["reason_code"] == "insufficient_seed_papers"
    assert any("broaden_search" in cmd for cmd in result["next_action"]["commands"])


def test_stopped_by_human(db, tmp_path):
    topic_id = _make_topic(db)
    OrchestratorService(db).resume_run(topic_id)
    state_dir = tmp_path / "state"
    checkpoint_data = ckpt.new_checkpoint(topic_id, mode="standard")
    checkpoint_data["human_decision"].update(
        {"requested": False, "selected": "stop", "decision_status": "stopped"}
    )
    ckpt.save_checkpoint(ckpt.checkpoint_path(state_dir, topic_id), checkpoint_data)

    result = _state(db, topic_id, state_dir)

    assert result["next_action"]["code"] == "stopped_by_human"


def test_db_checkpoint_mismatch(db, tmp_path):
    topic_id = _make_topic(db)
    OrchestratorService(db).resume_run(topic_id)  # run at init
    state_dir = tmp_path / "state"
    checkpoint_data = ckpt.new_checkpoint(topic_id, mode="standard")
    checkpoint_data["current_stage"] = "write"
    ckpt.save_checkpoint(ckpt.checkpoint_path(state_dir, topic_id), checkpoint_data)

    result = _state(db, topic_id, state_dir)

    assert "db_checkpoint_mismatch" in result["blockers"]
    assert result["next_action"]["code"] == "db_checkpoint_mismatch"


def test_fix_last_error(db, tmp_path):
    topic_id = _make_topic(db)
    run = OrchestratorService(db).resume_run(topic_id)
    state_dir = tmp_path / "state"
    checkpoint_data = ckpt.new_checkpoint(topic_id, mode="standard")
    checkpoint_data["current_stage"] = run.current_stage
    checkpoint_data["stage_state"] = "error"
    checkpoint_data["last_error"]["message"] = "provider timeout"
    ckpt.save_checkpoint(ckpt.checkpoint_path(state_dir, topic_id), checkpoint_data)

    result = _state(db, topic_id, state_dir)

    assert result["next_action"]["code"] == "fix_last_error"
    assert "provider timeout" in result["next_action"]["summary"]


def test_finished_ready_for_feedback(db, tmp_path):
    topic_id = _make_topic(db)
    svc = OrchestratorService(db)
    svc.resume_run(topic_id)
    svc.resume_run(topic_id, force_stage="write")
    state_dir = tmp_path / "state"
    checkpoint_data = ckpt.new_checkpoint(topic_id, mode="standard")
    checkpoint_data["current_stage"] = "write"
    checkpoint_data["stage_state"] = "complete"
    ckpt.save_checkpoint(ckpt.checkpoint_path(state_dir, topic_id), checkpoint_data)

    result = _state(db, topic_id, state_dir)

    assert result["next_action"]["code"] == "finished_ready_for_feedback"
    assert any("rh feedback" in cmd for cmd in result["next_action"]["commands"])


def test_resume_default(db, tmp_path):
    topic_id = _make_topic(db)
    run = OrchestratorService(db).resume_run(topic_id)
    state_dir = tmp_path / "state"
    checkpoint_data = ckpt.new_checkpoint(topic_id, mode="standard")
    checkpoint_data["current_stage"] = run.current_stage
    ckpt.save_checkpoint(ckpt.checkpoint_path(state_dir, topic_id), checkpoint_data)

    result = _state(db, topic_id, state_dir)

    assert result["next_action"]["code"] == "resume"


def test_payload_shape_is_stable(db, tmp_path):
    topic_id = _make_topic(db)
    OrchestratorService(db).resume_run(topic_id)
    state_dir = tmp_path / "state"
    checkpoint_data = ckpt.new_checkpoint(topic_id, mode="standard")
    ckpt.save_checkpoint(ckpt.checkpoint_path(state_dir, topic_id), checkpoint_data)

    result = _state(db, topic_id, state_dir)

    assert set(result) == {
        "schema_version",
        "topic",
        "resolution",
        "state_trees",
        "orchestrator",
        "checkpoint",
        "pending_decision",
        "feedback",
        "classification",
        "state_consistency",
        "blockers",
        "warnings",
        "next_action",
    }
    assert result["feedback"] == {"open_count": 0, "open_items": []}
    resolution = result["resolution"]
    assert resolution["db_path"] == str(db.db_path)
    assert resolution["state_dir"] == str(state_dir)
    assert isinstance(result["state_trees"], list)
    assert set(result["next_action"]) == {"code", "summary", "commands"}
