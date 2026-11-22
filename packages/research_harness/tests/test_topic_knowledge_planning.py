from __future__ import annotations

import dataclasses


def _evaluation_case(name: str):
    from research_harness.knowledge.knowledge_evaluation import (
        build_private_knowledge_evaluation_corpus,
    )

    cases = {case.name: case for case in build_private_knowledge_evaluation_corpus()}
    return cases[name]


def test_private_multi_step_dry_run_planner_is_bounded_and_evidence_grounded() -> None:
    from research_harness.knowledge.knowledge_consumption import KnowledgeContextRequest
    from research_harness.knowledge.knowledge_planning import (
        simulate_private_knowledge_dry_run_plan,
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
                "paper_search",
                "claim_extract",
                "gap_detect",
                "section_draft",
                "paper_ingest",
            ],
        },
    )
    readiness = build_topic_knowledge_readiness_report(
        snapshot,
        case.wiki_export,
        search_queries=(case.request.query,),
    )

    report = simulate_private_knowledge_dry_run_plan(
        KnowledgeContextRequest(
            topic_id=case.request.topic_id,
            query=case.request.query,
            user_brief="Dry-run a bounded private research advancement plan.",
        ),
        snapshot=snapshot,
        wiki_export=case.wiki_export,
        readiness_report=readiness,
        max_steps=3,
    )

    assert report.status == "ready"
    assert report.blocked_reason == ""
    assert report.execution_performed is False
    assert [step.action_name for step in report.steps] == [
        "paper_search",
        "claim_extract",
        "gap_detect",
    ]
    assert [step.mode for step in report.steps] == [
        "executable",
        "executable",
        "advisory",
    ]
    assert all(step.dry_run for step in report.steps)
    assert all(step.evidence_anchors for step in report.steps)
    assert report.steps[0].required_inputs["auto_ingest"] is False
    assert report.steps[1].required_inputs["paper_ids"] == [1]
    assert report.steps[2].blocked_reason == "action_gate_deferred"
    assert "paper_ingest" not in {step.action_name for step in report.steps}
    assert report.executable_action_allowlist == (
        "baseline_identify",
        "claim_extract",
        "consistency_check",
        "paper_search",
        "paper_summarize",
    )


def test_private_multi_step_dry_run_planner_blocks_stale_and_forbidden_actions() -> (
    None
):
    from research_harness.knowledge.knowledge_consumption import KnowledgeContextRequest
    from research_harness.knowledge.knowledge_planning import (
        simulate_private_knowledge_dry_run_plan,
    )

    stale_case = _evaluation_case("stale_snapshot")
    stale_report = simulate_private_knowledge_dry_run_plan(
        stale_case.request,
        snapshot=stale_case.snapshot,
        wiki_export=stale_case.wiki_export,
        readiness_report=stale_case.readiness_report,
    )

    assert stale_report.status == "blocked"
    assert stale_report.steps == ()
    assert stale_report.blocked_reason == "snapshot_stale"
    assert stale_report.execution_performed is False

    rich_case = _evaluation_case("evidence_rich")
    forbidden_report = simulate_private_knowledge_dry_run_plan(
        KnowledgeContextRequest(
            topic_id=rich_case.request.topic_id,
            query=rich_case.request.query,
            action_name="paper_ingest",
        ),
        snapshot=rich_case.snapshot,
        wiki_export=rich_case.wiki_export,
        readiness_report=rich_case.readiness_report,
    )

    assert forbidden_report.status == "blocked"
    assert len(forbidden_report.steps) == 1
    assert forbidden_report.steps[0].action_name == "paper_ingest"
    assert forbidden_report.steps[0].mode == "blocked"
    assert forbidden_report.steps[0].blocked_reason == "action_forbidden"
    assert forbidden_report.execution_performed is False
