"""Fail-closed dream firewall: the formal RH path refuses dream bundles.

A dream-marked final_bundle never passes the commit or write gates.
"""

from __future__ import annotations

from research_harness.orchestrator.artifacts import ArtifactManager
from research_harness.orchestrator.invariants import InvariantChecker


def _create_topic(db, name: str) -> int:
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO topics (name, description, target_venue) VALUES (?, ?, ?)",
            (name, "topic for dream firewall tests", "CCF-A"),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def _record_bundle(db, topic_id: int, writing_mode: str):
    return ArtifactManager(db).record(
        topic_id=topic_id,
        stage="write",
        artifact_type="final_bundle",
        title="Final Bundle",
        payload={"writing_mode": writing_mode, "pdf_info": {"pages": 10}},
    )


def test_dream_bundle_blocks_write_gate_by_default(db, monkeypatch):
    topic_id = _create_topic(db, "dream-firewall-default-topic")
    bundle = _record_bundle(db, topic_id, "dream/advisor_ideal")

    violations = InvariantChecker(db).check_dream_firewall(topic_id, "write")

    assert len(violations) == 1
    assert violations[0].check == "dream_firewall"
    assert violations[0].severity == "critical"
    assert violations[0].artifact_id == bundle.id
    assert "refuses dream bundles" in violations[0].message
    # The firewall guards commit and write gates, not earlier stages.
    assert InvariantChecker(db).check_dream_firewall(topic_id, "analyze") == []


def test_no_environment_switch_opens_the_firewall(db, monkeypatch):
    monkeypatch.setenv("RESEARCH_HARNESS_DREAM_SANDBOX", "1")
    topic_id = _create_topic(db, "dream-firewall-sandbox-topic")
    _record_bundle(db, topic_id, "dream/advisor_ideal")

    violations = InvariantChecker(db).check_dream_firewall(topic_id, "write")
    assert [v.check for v in violations] == ["dream_firewall"]


def test_non_dream_bundle_passes_the_firewall(db, monkeypatch):
    topic_id = _create_topic(db, "dream-firewall-main-topic")
    _record_bundle(db, topic_id, "main")

    assert InvariantChecker(db).check_dream_firewall(topic_id, "write") == []


def test_check_all_wires_the_firewall(db, monkeypatch):
    topic_id = _create_topic(db, "dream-firewall-check-all-topic")
    _record_bundle(db, topic_id, "dream/advisor_ideal")

    violations = InvariantChecker(db).check_all(topic_id, "write")

    assert "dream_firewall" in {v.check for v in violations}
