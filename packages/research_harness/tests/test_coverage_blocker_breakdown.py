"""Tests for the coverage-eligibility blocker breakdown (P-2).

Motivating incident (topic 73 / run 32, 2026-08-08):

    linked 137 | screened_in 110 | annotated 42 | strict-coverage eligible 11

Every number the run could see suggested progress; the one that gated the
stage did not move. The postmortem: the run "optimized raw downloads and
annotations instead of the actual eligibility predicate".

`_is_coverage_eligible` tests six independent conditions and returns a single
bool, so a paper that fails is simply absent from the count with no statement
of which condition failed. This module turns that bool into an attributed
breakdown, so an operator can answer: what is missing, and which repair buys
the most eligible papers?
"""

from __future__ import annotations

from research_harness.paper_pool_audit import (
    COVERAGE_BLOCKER_SCHEMA,
    coverage_blocker_breakdown,
    explain_coverage_ineligibility,
)


def _row(**overrides) -> dict:
    row = {
        "relevance": "high",
        "screening_status": "screened_in",
        "manuscript_eligible": 1,
        "status": "annotated",
        "pdf_path": "/tmp/p.pdf",
    }
    row.update(overrides)
    return row


def test_schema_id_is_stable() -> None:
    assert COVERAGE_BLOCKER_SCHEMA == "rh.schema.report.coverage_blockers.v1"


def test_eligible_paper_reports_no_blockers() -> None:
    assert explain_coverage_ineligibility(_row()) == []


def test_missing_metadata_is_attributed() -> None:
    """55 of 137 records had blank titles from OA ingestion — the single
    largest blocker, and it was invisible."""
    blockers = explain_coverage_ineligibility(_row(), metadata_reason="empty_title")
    assert blockers == ["metadata_unusable"]


def test_noise_and_duplicate_are_attributed_separately() -> None:
    assert explain_coverage_ineligibility(_row(), noise_reason="off_topic") == [
        "flagged_noise"
    ]
    assert explain_coverage_ineligibility(_row(), is_duplicate_secondary=True) == [
        "duplicate_secondary"
    ]


def test_screening_conditions_are_attributed() -> None:
    assert explain_coverage_ineligibility(_row(relevance="dismissed")) == [
        "dismissed_or_excluded"
    ]
    assert explain_coverage_ineligibility(_row(screening_status="pending")) == [
        "not_screened_in"
    ]
    assert explain_coverage_ineligibility(_row(manuscript_eligible=0)) == [
        "not_manuscript_eligible"
    ]


def test_fulltext_conditions_are_attributed() -> None:
    assert explain_coverage_ineligibility(_row(status="meta_only")) == ["not_annotated"]
    assert explain_coverage_ineligibility(_row(pdf_path="")) == ["no_pdf_path"]


def test_all_failing_conditions_are_reported_not_just_the_first() -> None:
    """Reporting only the first blocker would understate repair cost: a paper
    needing three fixes must not look like a one-fix win."""
    blockers = explain_coverage_ineligibility(
        _row(status="meta_only", pdf_path="", screening_status="pending")
    )
    assert set(blockers) == {"not_screened_in", "not_annotated", "no_pdf_path"}


def test_breakdown_counts_and_ranks_repair_opportunities() -> None:
    rows = (
        [(_row(), "", "", False)] * 11  # the 11 eligible
        + [(_row(status="meta_only"), "empty_title", "", False)] * 55  # metadata
        + [(_row(status="meta_only"), "", "", False)] * 40  # annotation only
        + [(_row(), "", "off_topic", False)] * 1  # noise
    )
    report = coverage_blocker_breakdown(rows, min_coverage_eligible=50)

    assert report["schema"] == COVERAGE_BLOCKER_SCHEMA
    assert report["eligible"] == 11
    assert report["required"] == 50
    assert report["shortfall"] == 39

    counts = {row["blocker"]: row["papers"] for row in report["blockers"]}
    assert counts["metadata_unusable"] == 55
    assert counts["not_annotated"] == 95  # 55 + 40 both lack annotation
    assert counts["flagged_noise"] == 1

    # Ranked by how many papers are blocked ONLY by that condition — those are
    # the ones a single repair actually converts.
    top = report["single_blocker_ranking"][0]
    assert top["blocker"] == "not_annotated"
    assert top["papers"] == 40


def test_breakdown_reports_whether_shortfall_is_closable() -> None:
    """If every remaining paper is noise or duplicate, more acquisition is the
    only path — saying so prevents another eight-hour repair loop."""
    rows = [(_row(), "", "", False)] * 11 + [(_row(), "", "off_topic", False)] * 3
    report = coverage_blocker_breakdown(rows, min_coverage_eligible=50)
    assert report["repairable_papers"] == 0
    assert report["shortfall_closable_by_repair"] is False


def test_breakdown_on_empty_pool_does_not_raise() -> None:
    report = coverage_blocker_breakdown([], min_coverage_eligible=50)
    assert report["eligible"] == 0
    assert report["blockers"] == []
