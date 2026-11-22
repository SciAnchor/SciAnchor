from __future__ import annotations


def test_research_wiki_preflight_action_policy() -> None:
    from research_harness.knowledge.research_wiki_preflight import (
        action_name_for_workflow_stage,
        requires_research_wiki_preflight,
    )

    assert action_name_for_workflow_stage("analyze") == "science_discovery"
    assert action_name_for_workflow_stage("propose") == "experiment_design"
    assert action_name_for_workflow_stage("experiment") == "method_improvement"
    assert action_name_for_workflow_stage("write") == "paper_writing"

    assert requires_research_wiki_preflight("analyze") is True
    assert requires_research_wiki_preflight("write") is True
    assert requires_research_wiki_preflight("build") is False
    assert requires_research_wiki_preflight("init") is False


def test_research_wiki_preflight_summary_loaded() -> None:
    from research_harness.knowledge.research_wiki_preflight import (
        summarize_research_wiki_preflight,
    )

    summary = summarize_research_wiki_preflight(
        {
            "schema_version": "wiki_context_pack.v1",
            "topic_id": 7,
            "action_name": "paper_writing",
            "paper_wiki_status": "loaded",
            "status_reason": "wiki_context_pack_loaded",
            "degraded": True,
            "warnings": [{"code": "snapshot_stale"}],
            "page_count": 8,
            "evidence_anchor_count": 24,
            "preflight": {
                "priority_evidence_layer": "research_wiki",
                "fallback_allowed": False,
                "fallback_must_be_declared": True,
            },
        },
        stage="write",
    )

    assert summary == {
        "schema_version": "research_wiki_preflight.v1",
        "topic_id": 7,
        "stage": "write",
        "action_name": "paper_writing",
        "paper_wiki_status": "loaded",
        "status_reason": "wiki_context_pack_loaded",
        "priority_evidence_layer": "research_wiki",
        "fallback_allowed": False,
        "fallback_must_be_declared": True,
        "must_not_silent_markdown_fallback": True,
        "degraded": True,
        "warning_codes": ["snapshot_stale"],
        "page_count": 8,
        "evidence_anchor_count": 24,
        "unavailable_reasons": [],
    }


def test_research_wiki_preflight_summary_requires_declared_fallback() -> None:
    from research_harness.knowledge.research_wiki_preflight import (
        summarize_research_wiki_preflight,
    )

    summary = summarize_research_wiki_preflight(
        {
            "schema_version": "wiki_context_pack.v1",
            "topic_id": 7,
            "paper_wiki_status": "unavailable",
            "status_reason": "no_research_wiki_export",
            "unavailable_reasons": ["no current or stale Topic Knowledge snapshot"],
            "warnings": [],
            "preflight": {
                "priority_evidence_layer": "",
                "fallback_allowed": True,
                "fallback_must_be_declared": True,
            },
            "pages": [],
        },
        stage="analyze",
    )

    assert summary["paper_wiki_status"] == "unavailable"
    assert summary["fallback_allowed"] is True
    assert summary["fallback_must_be_declared"] is True
    assert summary["must_not_silent_markdown_fallback"] is True
    assert summary["unavailable_reasons"] == [
        "no current or stale Topic Knowledge snapshot"
    ]
