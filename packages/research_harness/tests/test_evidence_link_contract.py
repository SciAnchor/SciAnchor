from __future__ import annotations

import json

from research_harness.execution.harness import ResearchHarnessBackend
from research_harness.orchestrator import OrchestratorService
from research_harness.orchestrator.invariants import InvariantChecker, is_blocking
from research_harness.primitives import (
    CitationCandidate,
    EvidenceLink,
    EvidenceSpan,
    PRIMITIVE_REGISTRY,
)


def test_evidence_link_preserves_support_span_and_citation_candidate() -> None:
    link = EvidenceLink(
        claim_id="claim-1",
        source_type="paper",
        source_id="paper-7",
        support_status="partial",
        evidence_span={
            "paper_id": 7,
            "section": "Results",
            "snippet": "The ablation improves conversion lift only for high-volume campaigns.",
            "page": 4,
        },
        citation_candidate={
            "paper_id": 7,
            "identifier": "arxiv:2401.00001",
            "title": "Budget Pacing Under Delayed Feedback",
            "doi": "10.5555/example",
        },
    )

    assert link.support_status == "partial"
    assert isinstance(link.evidence_span, EvidenceSpan)
    assert link.evidence_span.paper_id == 7
    assert link.evidence_span.section == "Results"
    assert isinstance(link.citation_candidate, CitationCandidate)
    assert link.citation_candidate.identifier == "arxiv:2401.00001"


def test_evidence_link_registry_exposes_typed_contract_fields() -> None:
    schema = PRIMITIVE_REGISTRY["evidence_link"].input_schema
    properties = schema["properties"]

    assert "support_status" in properties
    assert "evidence_span" in properties
    assert "citation_candidate" in properties
    assert properties["support_status"]["enum"] == [
        "supports",
        "partial",
        "contradicts",
        "unsupported",
        "unknown",
    ]


def test_evidence_link_backend_accepts_new_contract_fields(db) -> None:
    backend = ResearchHarnessBackend(db=db)

    result = backend.execute(
        "evidence_link",
        claim_id="claim-1",
        source_type="paper",
        source_id="paper-7",
        support_status="supports",
        evidence_span={
            "paper_id": 7,
            "section": "Method",
            "snippet": "The method constrains spend by campaign-level budget pacing.",
        },
        citation_candidate={
            "paper_id": 7,
            "identifier": "doi:10.5555/example",
            "title": "Pacing With Budget Constraints",
        },
    )

    assert result.success is True
    assert result.output is not None
    link = result.output.link
    assert link.support_status == "supports"
    assert link.evidence_span is not None
    assert link.evidence_span.section == "Method"
    assert link.citation_candidate is not None
    assert link.citation_candidate.title == "Pacing With Budget Constraints"


def _insert_topic(db) -> int:
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO topics (name, description) VALUES (?, ?)",
            ("evidence-link-topic", "Evidence link invariant test"),
        )
        topic_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO projects (id, topic_id, name, description) VALUES (?, ?, ?, ?)",
            (topic_id, topic_id, "evidence-link-topic", "stub"),
        )
        conn.commit()
        return topic_id
    finally:
        conn.close()


def _insert_evidence_links_artifact(db, topic_id: int, payload: dict) -> None:
    import json

    conn = db.connect()
    try:
        conn.execute(
            """
            INSERT INTO project_artifacts
              (topic_id, stage, artifact_type, title, payload_json, status, version)
            VALUES (?, 'analyze', 'evidence_links', 'Evidence links', ?, 'active', 1)
            """,
            (topic_id, json.dumps(payload)),
        )
        conn.commit()
    finally:
        conn.close()


def test_unsupported_evidence_links_block_write_gate(db) -> None:
    topic_id = _insert_topic(db)
    _insert_evidence_links_artifact(
        db,
        topic_id,
        {
            "evidence_links": [
                {
                    "claim_id": "claim-unsupported",
                    "source_type": "paper",
                    "source_id": "paper-7",
                    "support_status": "unsupported",
                },
                {
                    "claim_id": "claim-ok",
                    "source_type": "paper",
                    "source_id": "paper-8",
                    "support_status": "supports",
                },
            ]
        },
    )

    checker = InvariantChecker(db)
    violations = checker.check_unsupported_evidence_links(topic_id, "write")

    assert len(violations) == 1
    assert violations[0].check == "unsupported_evidence_link"
    assert violations[0].severity == "high"
    assert is_blocking(violations[0])
    assert "claim-unsupported" in violations[0].message
    assert checker.check_all(topic_id, "write")[0].check == "unsupported_evidence_link"


def test_unsupported_evidence_links_record_replayable_gate_governance(
    db, monkeypatch
) -> None:
    # Under test: this invariant's own gate verdict/governance rows.
    # The orthogonal EAG exemplar-anchor invariant (default ON) would add
    # its own finding/row; it has its own coverage in test_eag_write_anchor.py.
    monkeypatch.setenv("RESEARCH_HARNESS_EAG_WRITE_GATE", "0")
    topic_id = _insert_topic(db)
    _insert_evidence_links_artifact(
        db,
        topic_id,
        {
            "evidence_links": [
                {
                    "claim_id": "claim-unsupported",
                    "source_type": "paper",
                    "source_id": "paper-7",
                    "support_status": "unsupported",
                    "evidence_span": {
                        "paper_id": 7,
                        "section": "Evaluation",
                        "snippet": "The paper does not evaluate delayed-feedback budgets.",
                    },
                    "citation_candidate": {
                        "paper_id": 7,
                        "identifier": "doi:10.5555/unsupported",
                        "title": "Unsupported Citation Candidate",
                        "doi": "10.5555/unsupported",
                    },
                }
            ]
        },
    )

    svc = OrchestratorService(db)
    decision = svc.check_gate(topic_id, stage="write")

    assert decision == "fail"
    conn = db.connect()
    try:
        citation_rows = conn.execute(
            """
            SELECT title, status, matched_doi, source
            FROM citation_verifications
            WHERE topic_id = ?
            """,
            (topic_id,),
        ).fetchall()
        issue_rows = conn.execute(
            """
            SELECT review_type, severity, category, summary, blocking, affected_object_type
            FROM review_issues
            WHERE topic_id = ?
            """,
            (topic_id,),
        ).fetchall()
        gate_rows = conn.execute(
            """
            SELECT id, payload_json
            FROM project_artifacts
            WHERE topic_id = ?
              AND artifact_type = 'gate_decision'
              AND status = 'active'
            """,
            (topic_id,),
        ).fetchall()
    finally:
        conn.close()

    assert len(citation_rows) == 1
    assert citation_rows[0]["title"] == "Unsupported Citation Candidate"
    assert citation_rows[0]["status"] == "unsupported"
    assert citation_rows[0]["matched_doi"] == "10.5555/unsupported"
    assert citation_rows[0]["source"] == "orchestrator_gate:unsupported_evidence_link"

    assert len(issue_rows) == 1
    assert issue_rows[0]["review_type"] == "citation_governance"
    assert issue_rows[0]["severity"] == "high"
    assert issue_rows[0]["category"] == "unsupported_evidence_link"
    assert issue_rows[0]["blocking"] == 1
    assert issue_rows[0]["affected_object_type"] == "evidence_link"
    assert "claim-unsupported" in issue_rows[0]["summary"]

    assert len(gate_rows) == 1
    payload = json.loads(gate_rows[0]["payload_json"])
    assert payload["object_type"] == "gate_decision"
    assert payload["decision"] == "fail"
    assert payload["action"] == "block"
    assert payload["reason_codes"] == ["unsupported_evidence_link"]
    assert payload["violations"][0]["metadata"]["claim_id"] == "claim-unsupported"
    assert (
        payload["violations"][0]["metadata"]["citation_candidate"]["identifier"]
        == "doi:10.5555/unsupported"
    )
    assert payload["citation_verification_ids"]
    assert payload["review_issue_ids"]

    assert svc.check_gate(topic_id, stage="write") == "fail"
    conn = db.connect()
    try:
        citation_count = conn.execute(
            "SELECT COUNT(*) AS count FROM citation_verifications WHERE topic_id = ?",
            (topic_id,),
        ).fetchone()["count"]
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

    assert citation_count == 1
    assert issue_count == 1
    assert active_gate_count == 1


def test_unsupported_evidence_links_do_not_block_non_write_stage(db) -> None:
    topic_id = _insert_topic(db)
    _insert_evidence_links_artifact(
        db,
        topic_id,
        {"evidence_links": [{"claim_id": "claim-1", "support_status": "contradicts"}]},
    )

    violations = InvariantChecker(db).check_unsupported_evidence_links(
        topic_id,
        "analyze",
    )

    assert violations == []
