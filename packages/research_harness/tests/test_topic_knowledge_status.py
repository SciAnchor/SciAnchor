from __future__ import annotations

import dataclasses
import json


def _evaluation_case(name: str):
    from research_harness.knowledge.knowledge_evaluation import (
        build_private_knowledge_evaluation_corpus,
    )

    cases = {case.name: case for case in build_private_knowledge_evaluation_corpus()}
    return cases[name]


def test_knowledge_status_payload_is_versioned_read_only_and_public_safe() -> None:
    from research_harness.knowledge.knowledge_status import (
        build_knowledge_status_payload,
    )

    case = _evaluation_case("evidence_rich")
    payload = build_knowledge_status_payload(
        snapshot=case.snapshot,
        wiki_export=case.wiki_export,
        readiness_report=case.readiness_report,
        max_next_actions=5,
    )

    assert payload["schema_version"] == "knowledge_status.v1"
    assert payload["topic_id"] == case.snapshot.topic_id
    assert payload["status"] == "ready"
    assert payload["readiness_status"] == "ready"
    assert payload["snapshot"] == {
        "artifact_ref": f"artifact:topic_knowledge_snapshot:{case.snapshot.artifact_id}",
        "source_hash": case.snapshot.source_hash,
        "is_current": True,
    }
    assert payload["coverage"]["normalized_claims"] == 1
    assert payload["coverage"]["semantic_atoms"] == 3
    assert payload["wiki"]["page_count"] == len(case.wiki_export.pages)
    assert payload["wiki"]["searchable_page_count"] == len(case.wiki_export.pages)
    assert payload["wiki"]["validation_issue_count"] == 0
    assert payload["wiki"]["insight_count"] >= 0
    assert payload["links"]["snapshot_artifact"] == payload["snapshot"]["artifact_ref"]
    assert payload["next_actions"] == [
        {
            "action_name": "claim_extract",
            "mode": "executable",
            "reason": "existing RH action selected from readiness report",
        }
    ]

    encoded = json.dumps(payload, sort_keys=True)
    forbidden_fragments = (
        "hidden_gold",
        "benchmark_reference",
        "unreviewed_private_notes",
        "/tmp/research-harness-private-knowledge-eval",
        ".research-harness",
        "paper_ingest",
    )
    for fragment in forbidden_fragments:
        assert fragment not in encoded


def test_knowledge_status_payload_marks_stale_and_degraded_states() -> None:
    from research_harness.knowledge.knowledge_status import (
        build_knowledge_status_payload,
    )

    stale_case = _evaluation_case("stale_snapshot")
    stale_payload = build_knowledge_status_payload(
        snapshot=stale_case.snapshot,
        wiki_export=stale_case.wiki_export,
        readiness_report=stale_case.readiness_report,
    )

    assert stale_payload["status"] == "stale"
    assert stale_payload["readiness_status"] == "stale"
    assert stale_payload["snapshot"]["is_current"] is False
    assert "snapshot_stale" in stale_payload["warnings"]

    weak_case = _evaluation_case("weak_unresolved_wikilink")
    degraded_payload = build_knowledge_status_payload(
        snapshot=weak_case.snapshot,
        wiki_export=weak_case.wiki_export,
        readiness_report=weak_case.readiness_report,
    )

    assert degraded_payload["status"] == "degraded"
    assert degraded_payload["readiness_status"] == "needs_attention"
    assert "unresolved_wikilink" in degraded_payload["warnings"]


def test_knowledge_status_payload_filters_and_limits_next_actions() -> None:
    from research_harness.knowledge.knowledge_status import (
        build_knowledge_status_payload,
    )
    from research_harness.knowledge.topic_knowledge_readiness import (
        build_topic_knowledge_readiness_report,
    )

    case = _evaluation_case("evidence_rich")
    snapshot = dataclasses.replace(
        case.snapshot,
        payload={
            **case.snapshot.payload,
            "next_actions": [
                "claim_extract",
                "gap_detect",
                "section_draft",
                "paper_ingest",
                "unknown_action",
            ],
        },
    )
    readiness = build_topic_knowledge_readiness_report(snapshot, case.wiki_export)

    payload = build_knowledge_status_payload(
        snapshot=snapshot,
        wiki_export=case.wiki_export,
        readiness_report=readiness,
        max_next_actions=2,
    )

    assert payload["next_actions"] == [
        {
            "action_name": "claim_extract",
            "mode": "executable",
            "reason": "existing RH action selected from readiness report",
        },
        {
            "action_name": "gap_detect",
            "mode": "advisory",
            "reason": "existing RH action selected from readiness report",
        },
    ]
    assert all(
        action["action_name"] != "paper_ingest" for action in payload["next_actions"]
    )
