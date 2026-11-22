"""HITL objectivity protocol (batch 4): schema, recording, probes, scoring."""

from __future__ import annotations


from research_harness._workflow.orchestrator.hitl_objectivity import (
    HitlObjectivity,
    validate_adjudication,
)
from research_harness.orchestrator.service import OrchestratorService

from .test_paper_production_defaults import _create_topic


# ---------------------------------------------------------------------------
# adjudication schema
# ---------------------------------------------------------------------------


def test_validate_adjudication_rules():
    ok = validate_adjudication(
        {
            "verdict": "dispute",
            "feedback_kind": "factual",
            "evidence_against": ["tables report ±std in every row"],
            "what_would_change_my_mind": "a table without variance columns",
        }
    )
    assert ok.ok, ok.problems

    blanket_accept = validate_adjudication(
        {
            "verdict": "accept",
            "feedback_kind": "factual",
            "evidence_for": [],
        }
    )
    assert not blanket_accept.ok
    assert any("requires evidence_for" in p for p in blanket_accept.problems)

    preference_accept = validate_adjudication(
        {
            "verdict": "accept",
            "feedback_kind": "preference",
        }
    )
    assert preference_accept.ok

    stubborn = validate_adjudication(
        {
            "verdict": "dispute",
            "feedback_kind": "quality",
            "evidence_against": ["x"],
            "what_would_change_my_mind": "",
        }
    )
    assert not stubborn.ok
    assert any("falsifiability" in p for p in stubborn.problems)


# ---------------------------------------------------------------------------
# recording + sycophancy report
# ---------------------------------------------------------------------------


def test_preregistration_pairing_and_flip_flags(db):
    topic_id = _create_topic(db, "hitl-topic")
    svc = OrchestratorService(db)
    target = svc.record_artifact(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="draft",
        payload={"sha256": "x"},
    )
    hitl = HitlObjectivity(db)

    prereg_id = hitl.preregister_position(
        topic_id=topic_id,
        stage="write",
        target_artifact_id=target.id,
        score=4.5,
        rationale="strong evidence coverage",
    )

    # Unexplained large flip -> flagged.
    flip = hitl.record_adjudication(
        topic_id=topic_id,
        stage="write",
        target_artifact_id=target.id,
        feedback_text="this draft is weak, rewrite it",
        feedback_kind="quality",
        verdict="accept",
        evidence_for=["reviewer authority"],  # passes schema, but score dives
        post_score=1.0,
        preregistration_artifact_id=prereg_id,
    )
    assert flip["ok"], flip["problems"]

    # Remove the evidence so the flip counts as unexplained.
    from research_harness.orchestrator.artifacts import ArtifactManager

    manager = ArtifactManager(db)
    artifact = manager.get(flip["artifact_id"])
    payload = dict(artifact.payload)
    payload["evidence_for"] = []
    manager.update_payload_fields(artifact.id, payload)

    # Evidence-backed update -> not flagged.
    hitl.record_adjudication(
        topic_id=topic_id,
        stage="write",
        target_artifact_id=target.id,
        feedback_text="the ablation table contradicts claim 2",
        feedback_kind="factual",
        verdict="partial",
        evidence_against=["ablation row 3 shows the opposite trend"],
        post_score=3.0,
        preregistration_artifact_id=prereg_id,
    )

    report = hitl.sycophancy_report(topic_id)
    assert report["n_adjudications"] == 2
    assert report["n_paired_with_preregistration"] == 2
    assert len(report["unexplained_flip_flags"]) == 1
    assert report["unexplained_flip_flags"][0]["flip"] == -3.5


def test_invalid_adjudication_still_recorded_with_problems(db):
    topic_id = _create_topic(db, "hitl-invalid-topic")
    hitl = HitlObjectivity(db)
    out = hitl.record_adjudication(
        topic_id=topic_id,
        stage="write",
        target_artifact_id=1,
        feedback_text="just accept it",
        feedback_kind="factual",
        verdict="accept",
    )
    assert not out["ok"] and out["artifact_id"]
    report = hitl.sycophancy_report(topic_id)
    assert report["verdict_counts"]["invalid_schema"] == 1


# ---------------------------------------------------------------------------
# probe factory + scoring
# ---------------------------------------------------------------------------
