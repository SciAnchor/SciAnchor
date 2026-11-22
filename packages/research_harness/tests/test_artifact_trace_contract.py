from __future__ import annotations

import json

from research_harness.orchestrator import OrchestratorService
from research_harness.orchestrator.invariants import InvariantChecker, is_blocking


def _insert_topic(db) -> int:
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO topics (name, description) VALUES (?, ?)",
            ("artifact-trace-topic", "Artifact trace invariant test"),
        )
        topic_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO projects (id, topic_id, name, description) VALUES (?, ?, ?, ?)",
            (topic_id, topic_id, "artifact-trace-topic", "stub"),
        )
        conn.commit()
        return topic_id
    finally:
        conn.close()


def test_publication_pack_without_source_artifact_trace_blocks_write_gate(
    db, monkeypatch
) -> None:
    # Under test: this invariant's own gate verdict/governance rows.
    # The orthogonal EAG exemplar-anchor invariant (default ON) would add
    # its own finding/row; it has its own coverage in test_eag_write_anchor.py.
    monkeypatch.setenv("RESEARCH_HARNESS_EAG_WRITE_GATE", "0")
    topic_id = _insert_topic(db)
    svc = OrchestratorService(db)
    svc.init_run(topic_id=topic_id)
    svc.record_artifact(
        topic_id=topic_id,
        stage="write",
        artifact_type="publication_pack",
        title="Publication Pack",
        payload={
            "components": {"manuscript": "draft"},
            "contract": {"artifact_type": "publication_pack"},
            "source_artifacts": [],
        },
    )

    checker = InvariantChecker(db)
    violations = checker.check_artifact_trace_linkage(topic_id, "write")

    assert len(violations) == 1
    assert violations[0].check == "artifact_trace_linkage"
    assert violations[0].severity == "high"
    assert violations[0].metadata["artifact_type"] == "publication_pack"
    assert is_blocking(violations[0])

    assert svc.check_gate(topic_id, stage="write") == "fail"

    conn = db.connect()
    try:
        issue_rows = conn.execute(
            """
            SELECT review_type, category, severity, blocking, affected_object_type,
                   affected_object_id
            FROM review_issues
            WHERE topic_id = ?
            """,
            (topic_id,),
        ).fetchall()
        gate_rows = conn.execute(
            """
            SELECT payload_json
            FROM project_artifacts
            WHERE topic_id = ?
              AND artifact_type = 'gate_decision'
              AND status = 'active'
            """,
            (topic_id,),
        ).fetchall()
    finally:
        conn.close()

    assert len(issue_rows) == 1
    assert issue_rows[0]["review_type"] == "gate_invariant"
    assert issue_rows[0]["category"] == "artifact_trace_linkage"
    assert issue_rows[0]["severity"] == "high"
    assert issue_rows[0]["blocking"] == 1
    assert issue_rows[0]["affected_object_type"] == "project_artifact"

    assert len(gate_rows) == 1
    payload = json.loads(gate_rows[0]["payload_json"])
    assert payload["object_type"] == "gate_decision"
    assert payload["decision"] == "fail"
    assert payload["reason_codes"] == ["artifact_trace_linkage"]
    assert payload["violations"][0]["metadata"]["artifact_type"] == "publication_pack"

    assert svc.check_gate(topic_id, stage="write") == "fail"
    conn = db.connect()
    try:
        issue_count = conn.execute(
            "SELECT COUNT(*) AS count FROM review_issues WHERE topic_id = ?",
            (topic_id,),
        ).fetchone()["count"]
        active_gate_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM project_artifacts
            WHERE topic_id = ?
              AND artifact_type = 'gate_decision'
              AND status = 'active'
            """,
            (topic_id,),
        ).fetchone()["count"]
    finally:
        conn.close()

    assert issue_count == 1
    assert active_gate_count == 1


def test_artifact_trace_linkage_accepts_dependency_edges(db) -> None:
    topic_id = _insert_topic(db)
    svc = OrchestratorService(db)
    svc.init_run(topic_id=topic_id)
    draft = svc.record_artifact(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack",
        payload={"sections": {"introduction": "Traceable draft [paper:1]."}},
    )
    svc.record_artifact(
        topic_id=topic_id,
        stage="write",
        artifact_type="publication_pack",
        title="Publication Pack",
        payload={
            "components": {"manuscript_sections": {"artifact_id": draft.id}},
            "contract": {"artifact_type": "publication_pack"},
            "source_artifacts": [],
        },
        dependency_artifact_ids=[draft.id],
    )

    assert InvariantChecker(db).check_artifact_trace_linkage(topic_id, "write") == []


def test_artifact_trace_linkage_accepts_payload_artifact_refs(db) -> None:
    topic_id = _insert_topic(db)
    svc = OrchestratorService(db)
    svc.init_run(topic_id=topic_id)
    source = svc.record_artifact(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack",
        payload={"sections": {"introduction": "Traceable draft [paper:1]."}},
    )
    svc.record_artifact(
        topic_id=topic_id,
        stage="write",
        artifact_type="publication_pack",
        title="Publication Pack",
        payload={
            "components": {"manuscript_sections": {"artifact_id": source.id}},
            "contract": {"artifact_type": "publication_pack"},
            "source_artifacts": [
                {
                    "artifact_id": source.id,
                    "artifact_type": "draft_pack",
                    "role": "manuscript_sections",
                }
            ],
        },
    )

    assert InvariantChecker(db).check_artifact_trace_linkage(topic_id, "write") == []


def test_artifact_trace_linkage_rejects_stale_payload_artifact_refs(db) -> None:
    topic_id = _insert_topic(db)
    svc = OrchestratorService(db)
    svc.init_run(topic_id=topic_id)
    source = svc.record_artifact(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack",
        payload={"sections": {"introduction": "Traceable draft [paper:1]."}},
    )
    svc.mark_artifact_stale(source.id, reason="draft superseded", propagate=False)
    svc.record_artifact(
        topic_id=topic_id,
        stage="write",
        artifact_type="publication_pack",
        title="Publication Pack",
        payload={
            "components": {"manuscript_sections": {"artifact_id": source.id}},
            "contract": {"artifact_type": "publication_pack"},
            "source_artifacts": [
                {
                    "artifact_id": source.id,
                    "artifact_type": "draft_pack",
                    "role": "manuscript_sections",
                }
            ],
        },
    )

    violations = InvariantChecker(db).check_artifact_trace_linkage(topic_id, "write")

    assert len(violations) == 1
    assert violations[0].check == "artifact_trace_linkage"
    assert violations[0].metadata["payload_artifact_ref_ids"] == [source.id]
    assert violations[0].metadata["valid_payload_artifact_ref_ids"] == []


def test_artifact_trace_linkage_rejects_unrelated_payload_artifact_refs(db) -> None:
    topic_id = _insert_topic(db)
    svc = OrchestratorService(db)
    svc.init_run(topic_id=topic_id)
    unrelated = svc.record_artifact(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="gap_detect",
        title="Gap Detect",
        payload={"gaps": [{"id": "g1"}]},
    )
    svc.record_artifact(
        topic_id=topic_id,
        stage="write",
        artifact_type="publication_pack",
        title="Publication Pack",
        payload={
            "components": {"manuscript_sections": "missing"},
            "contract": {"artifact_type": "publication_pack"},
            "source_artifacts": [
                {
                    "artifact_id": unrelated.id,
                    "artifact_type": "gap_detect",
                    "role": "unrelated",
                }
            ],
        },
    )

    violations = InvariantChecker(db).check_artifact_trace_linkage(topic_id, "write")

    assert len(violations) == 1
    assert violations[0].check == "artifact_trace_linkage"
    assert violations[0].metadata["payload_artifact_ref_ids"] == [unrelated.id]
    assert violations[0].metadata["valid_payload_artifact_ref_ids"] == []


def test_artifact_trace_linkage_rejects_mixed_valid_and_invalid_refs(db) -> None:
    topic_id = _insert_topic(db)
    svc = OrchestratorService(db)
    svc.init_run(topic_id=topic_id)
    valid_source = svc.record_artifact(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack",
        payload={"sections": {"introduction": "Traceable draft [paper:1]."}},
    )
    unrelated = svc.record_artifact(
        topic_id=topic_id,
        stage="analyze",
        artifact_type="gap_detect",
        title="Gap Detect",
        payload={"gaps": [{"id": "g1"}]},
    )
    svc.record_artifact(
        topic_id=topic_id,
        stage="write",
        artifact_type="publication_pack",
        title="Publication Pack",
        payload={
            "components": {"manuscript_sections": "draft"},
            "contract": {"artifact_type": "publication_pack"},
            "source_artifacts": [
                {
                    "artifact_id": valid_source.id,
                    "artifact_type": "draft_pack",
                    "role": "manuscript_sections",
                },
                {
                    "artifact_id": unrelated.id,
                    "artifact_type": "gap_detect",
                    "role": "unrelated",
                },
            ],
        },
    )

    violations = InvariantChecker(db).check_artifact_trace_linkage(topic_id, "write")

    assert len(violations) == 1
    assert violations[0].check == "artifact_trace_linkage"
    assert violations[0].metadata["valid_payload_artifact_ref_ids"] == [valid_source.id]
    assert violations[0].metadata["invalid_payload_artifact_ref_ids"] == [unrelated.id]


def test_artifact_trace_linkage_accepts_dict_artifact_refs(db) -> None:
    topic_id = _insert_topic(db)
    svc = OrchestratorService(db)
    svc.init_run(topic_id=topic_id)
    source = svc.record_artifact(
        topic_id=topic_id,
        stage="write",
        artifact_type="final_bundle",
        title="Final Bundle",
        payload={"bundle": "ready"},
    )
    svc.record_artifact(
        topic_id=topic_id,
        stage="write",
        artifact_type="publication_pack",
        title="Publication Pack",
        payload={
            "components": {"final_bundle": "attached"},
            "contract": {"artifact_type": "publication_pack"},
            "source_artifacts": [],
            "artifact_refs": {
                "source_final_bundle": f"project_artifacts:{source.id}:final_bundle"
            },
        },
    )

    assert InvariantChecker(db).check_artifact_trace_linkage(topic_id, "write") == []


def test_unrelated_nested_artifact_id_does_not_satisfy_trace_linkage(db) -> None:
    topic_id = _insert_topic(db)
    svc = OrchestratorService(db)
    svc.init_run(topic_id=topic_id)
    source = svc.record_artifact(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack",
        payload={"sections": {"introduction": "Traceable draft [paper:1]."}},
    )
    svc.record_artifact(
        topic_id=topic_id,
        stage="write",
        artifact_type="publication_pack",
        title="Publication Pack",
        payload={
            "components": {"manuscript_sections": {"artifact_id": source.id}},
            "contract": {"artifact_type": "publication_pack"},
            "source_artifacts": [],
            "debug": {"artifact_id": source.id},
        },
    )

    violations = InvariantChecker(db).check_artifact_trace_linkage(topic_id, "write")

    assert len(violations) == 1
    assert violations[0].check == "artifact_trace_linkage"


def test_artifact_trace_linkage_accepts_figure_plan_refs(db) -> None:
    """figure_plan is a first-class publication-pack component and must count
    as a valid trace source (regression: packs referencing their figure_plan
    were blocked as having an invalid ref)."""
    topic_id = _insert_topic(db)
    svc = OrchestratorService(db)
    svc.init_run(topic_id=topic_id)
    draft = svc.record_artifact(
        topic_id=topic_id,
        stage="write",
        artifact_type="draft_pack",
        title="Draft Pack",
        payload={"sections": {"introduction": "Traceable draft."}},
    )
    figure_plan = svc.record_artifact(
        topic_id=topic_id,
        stage="write",
        artifact_type="figure_plan",
        title="Figure Plan",
        payload={"architecture_figure": {"output_path": "figures/arch.pdf"}},
    )
    svc.record_artifact(
        topic_id=topic_id,
        stage="write",
        artifact_type="publication_pack",
        title="Publication Pack",
        payload={
            "components": {"manuscript_sections": {"artifact_id": draft.id}},
            "contract": {"artifact_type": "publication_pack"},
            "source_artifacts": [
                {
                    "artifact_id": draft.id,
                    "artifact_type": "draft_pack",
                    "role": "manuscript_sections",
                },
                {
                    "artifact_id": figure_plan.id,
                    "artifact_type": "figure_plan",
                    "role": "figure_plan",
                },
            ],
        },
    )

    assert InvariantChecker(db).check_artifact_trace_linkage(topic_id, "write") == []
