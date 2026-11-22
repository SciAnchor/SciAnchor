"""Tests for the finished-topic feedback-reinforcement loop (S3)."""

from __future__ import annotations

from research_harness.auto_runner import checkpoint as ckpt
from research_harness.auto_runner.feedback_loop import (
    apply_revision_plan,
    build_revision_plan,
    feedback_add,
    feedback_address,
    feedback_list,
)
from research_harness.orchestrator.service import OrchestratorService


def _make_topic(db, name: str = "feedback-loop-test") -> int:
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO topics (name, description) VALUES (?, ?)", (name, name)
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def _seed_write_artifacts(db, topic_id: int) -> None:
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
        topic_id, stage="write", artifact_type="draft_pack", title="draft pack"
    )
    svc.record_artifact(
        topic_id, stage="write", artifact_type="final_bundle", title="bundle"
    )


def test_feedback_items_coexist(db):
    topic_id = _make_topic(db)

    first = feedback_add(
        db, topic=topic_id, target_kind="section", target="related_work", note="weak"
    )
    second = feedback_add(
        db, topic=topic_id, target_kind="claim", target="C3", note="overclaims"
    )

    assert first["status"] == "success"
    assert second["status"] == "success"
    assert first["feedback_artifact_id"] != second["feedback_artifact_id"]
    listing = feedback_list(db, topic=topic_id, status="open")
    assert listing["count"] == 2


def test_feedback_add_validates_inputs(db):
    topic_id = _make_topic(db)

    assert (
        feedback_add(db, topic=topic_id, target_kind="chapter", target="x", note="y")[
            "status"
        ]
        == "error"
    )
    assert (
        feedback_add(db, topic=topic_id, target_kind="section", target="x", note="  ")[
            "status"
        ]
        == "error"
    )
    assert (
        feedback_add(db, topic=9999, target_kind="section", target="x", note="y")[
            "status"
        ]
        == "error"
    )


def test_plan_mapping_section_only(db):
    topic_id = _make_topic(db)
    feedback_add(
        db, topic=topic_id, target_kind="section", target="related_work", note="weak"
    )

    plan = build_revision_plan(db, topic=topic_id, record=False)

    assert plan["status"] == "success"
    payload = plan["plan"]
    assert payload["reentry_stage"] == "write"
    assert payload["invalidate"]["sections"] == ["related_work"]
    assert "draft_pack" in payload["invalidate"]["types"]
    assert "evidence_pack" not in payload["invalidate"]["types"]
    context = payload["stage_context_injection"]["human_feedback_context"]
    assert context["sections_scope"] == ["related_work"]
    assert "related_work" in context["instructions"]


def test_plan_mapping_claim_and_mixed(db):
    topic_id = _make_topic(db)
    feedback_add(db, topic=topic_id, target_kind="claim", target="C1", note="weak")

    claim_plan = build_revision_plan(db, topic=topic_id, record=False)["plan"]
    assert claim_plan["reentry_stage"] == "analyze"
    assert "evidence_pack" in claim_plan["invalidate"]["types"]
    assert claim_plan["invalidate"]["sections"] == []

    feedback_add(
        db, topic=topic_id, target_kind="experiment", target="ablation", note="rerun"
    )
    mixed_plan = build_revision_plan(db, topic=topic_id, record=False)["plan"]
    # analyze precedes experiment in stage order
    assert mixed_plan["reentry_stage"] == "analyze"
    assert "verified_registry" in mixed_plan["invalidate"]["types"]


def test_plan_requires_open_feedback(db):
    topic_id = _make_topic(db)

    assert build_revision_plan(db, topic=topic_id)["status"] == "error"


def test_apply_dry_run_mutates_nothing(db, tmp_path):
    topic_id = _make_topic(db)
    _seed_write_artifacts(db, topic_id)
    feedback_add(
        db, topic=topic_id, target_kind="section", target="related_work", note="weak"
    )

    result = apply_revision_plan(
        db, topic=topic_id, base_dir=tmp_path / "state", dry_run=True
    )

    assert result["status"] == "success"
    assert result["dry_run"] is True
    assert result["reset"]["superseded"]
    svc = OrchestratorService(db)
    assert svc.get_run(topic_id) is None  # no run created
    assert svc.get_latest_artifact(topic_id, "write", "draft_pack") is not None
    assert not (tmp_path / "state").exists()


def test_apply_supersedes_and_reenters_write(db, tmp_path):
    topic_id = _make_topic(db)
    _seed_write_artifacts(db, topic_id)
    OrchestratorService(db).resume_run(topic_id)
    feedback_add(
        db, topic=topic_id, target_kind="section", target="related_work", note="weak"
    )
    state_dir = tmp_path / "state"

    result = apply_revision_plan(db, topic=topic_id, base_dir=state_dir)

    assert result["status"] == "success"
    assert result["reentry_stage"] == "write"
    svc = OrchestratorService(db)
    run = svc.get_run(topic_id)
    assert run is not None and run.current_stage == "write"
    # write-required artifacts superseded so freshness cannot skip the stage
    assert svc.get_latest_artifact(topic_id, "write", "draft_pack") is None
    superseded_types = {item["type"] for item in result["reset"]["superseded"]}
    assert "human_feedback_record" not in superseded_types
    # feedback records survive
    assert feedback_list(db, topic=topic_id, status="open")["count"] == 1

    checkpoint_data = ckpt.load_checkpoint(ckpt.checkpoint_path(state_dir, topic_id))
    assert checkpoint_data is not None
    assert checkpoint_data["current_stage"] == "write"
    assert checkpoint_data["stage_state"] == "pending"
    context = checkpoint_data["stage_context"]["human_feedback_context"]
    assert context["sections_scope"] == ["related_work"]
    # section filter hit only the targeted section draft
    section_rows = [
        item
        for item in result["reset"]["superseded"]
        if item["type"] == "section_draft"
    ]
    assert len(section_rows) == 1
    assert "Related Work" in section_rows[0]["title"]


def test_address_flips_status_and_clears_context(db, tmp_path):
    topic_id = _make_topic(db)
    _seed_write_artifacts(db, topic_id)
    OrchestratorService(db).resume_run(topic_id)
    added = feedback_add(
        db, topic=topic_id, target_kind="section", target="related_work", note="weak"
    )
    state_dir = tmp_path / "state"
    apply_revision_plan(db, topic=topic_id, base_dir=state_dir)

    result = feedback_address(
        db,
        topic=topic_id,
        feedback_artifact_id=added["feedback_artifact_id"],
        addressed_by_artifact_id=1234,
        note="rewritten",
        base_dir=state_dir,
    )

    assert result["status"] == "success"
    assert result["open_remaining"] == 0
    assert result["feedback_context_cleared"] is True
    assert result["item"]["status"] == "addressed"
    assert result["item"]["addressed_by_artifact_id"] == 1234
    checkpoint_data = ckpt.load_checkpoint(ckpt.checkpoint_path(state_dir, topic_id))
    assert "human_feedback_context" not in checkpoint_data["stage_context"]
    assert feedback_list(db, topic=topic_id, status="open")["count"] == 0
    assert feedback_list(db, topic=topic_id, status="addressed")["count"] == 1
