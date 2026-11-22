from __future__ import annotations

import json

from research_harness.orchestrator import OrchestratorService


def _insert_topic(db) -> int:
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO topics (name, description) VALUES (?, ?)",
            ("rollback-governance-topic", "Rollback governance invariant test"),
        )
        topic_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO projects (id, topic_id, name, description) VALUES (?, ?, ?, ?)",
            (topic_id, topic_id, "rollback-governance-topic", "stub"),
        )
        conn.commit()
        return topic_id
    finally:
        conn.close()


def test_stale_artifact_gate_block_records_replayable_rollback_event(db) -> None:
    topic_id = _insert_topic(db)
    svc = OrchestratorService(db)
    svc.init_run(topic_id=topic_id)

    upstream = svc.record_artifact(
        topic_id=topic_id,
        stage="build",
        artifact_type="literature_map",
        title="Literature Map",
        payload={"clusters": [{"id": "cluster-1"}]},
    )
    downstream = svc.record_artifact(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="direction_proposal",
        title="Direction Proposal",
        payload={"research_question": "Which mechanism should be tested?"},
        dependency_artifact_ids=[upstream.id],
    )
    svc.record_artifact(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="baseline_matrix",
        title="Baseline Matrix",
        payload={"baselines": [{"baseline_id": "b1"}], "coverage": {}},
    )

    svc.mark_artifact_stale(upstream.id, reason="paper pool changed")

    assert svc.check_gate(topic_id, stage="analyze") == "fail"

    conn = db.connect()
    try:
        issue_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM review_issues
            WHERE topic_id = ?
              AND category = 'stale_artifact'
              AND blocking = 1
            """,
            (topic_id,),
        ).fetchone()["count"]
        gate_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM project_artifacts
            WHERE topic_id = ?
              AND artifact_type = 'gate_decision'
              AND status = 'active'
            """,
            (topic_id,),
        ).fetchone()["count"]
        rollback_rows = conn.execute(
            """
            SELECT payload_json
            FROM project_artifacts
            WHERE topic_id = ?
              AND artifact_type = 'rollback_event'
              AND status = 'active'
            """,
            (topic_id,),
        ).fetchall()
    finally:
        conn.close()

    assert issue_count == 1
    assert gate_count == 1
    assert len(rollback_rows) == 1
    payload = json.loads(rollback_rows[0]["payload_json"])
    assert payload["object_type"] == "rollback_event"
    assert payload["stage"] == "analyze"
    assert payload["reason_codes"] == ["stale_artifact"]
    assert payload["affected_artifact_ids"] == [downstream.id]
    assert payload["rollback_cone"]["affected_artifact_ids"] == [downstream.id]
    assert "paper pool changed" in payload["violations"][0]["metadata"]["stale_reason"]

    assert svc.check_gate(topic_id, stage="analyze") == "fail"
    conn = db.connect()
    try:
        counts = conn.execute(
            """
            SELECT
              SUM(CASE WHEN artifact_type = 'rollback_event' AND status = 'active' THEN 1 ELSE 0 END)
                AS active_rollback_count,
              SUM(CASE WHEN artifact_type = 'gate_decision' AND status = 'active' THEN 1 ELSE 0 END)
                AS active_gate_count
            FROM project_artifacts
            WHERE topic_id = ?
            """,
            (topic_id,),
        ).fetchone()
        issue_count_after = conn.execute(
            "SELECT COUNT(*) AS count FROM review_issues WHERE topic_id = ?",
            (topic_id,),
        ).fetchone()["count"]
    finally:
        conn.close()

    assert counts["active_rollback_count"] == 1
    assert counts["active_gate_count"] == 1
    assert issue_count_after == 1
