"""Tests for gap_ground_verify v1.1 pure helpers (no LLM, no network).

v1.1 = contribution-level multi-query retrieval (each decorrelated query is an
independent capture attempt) + governed acceptance of the verdict via
governance_gate (the r(rho) rule).
"""

from __future__ import annotations

from dataclasses import dataclass

from research_harness._workflow.execution.llm_primitives import (
    _apply_gap_governance,
    _merge_capture_candidates,
)


@dataclass
class _P:
    title: str = ""
    arxiv_id: str = ""
    doi: str = ""
    relevance_score: float = 0.0


def test_merge_dedups_across_queries_and_counts_captures():
    a = _P(title="Paper A", arxiv_id="2401.00001", relevance_score=1.0)
    a_dup = _P(title="Paper A (v2)", arxiv_id="2401.00001", relevance_score=3.0)
    b = _P(title="Paper B", doi="10.1/b", relevance_score=2.0)
    per_query = [
        ("q1", [a, b]),
        ("q2", [a_dup]),
        ("q3", []),  # missed capture
    ]
    merged, captures = _merge_capture_candidates(per_query, max_candidates=10)
    assert captures == 2  # q1 and q2 captured, q3 missed
    assert len(merged) == 2  # A deduped by arxiv_id
    # Dedup keeps the higher-relevance copy. Where it lands is q2's business:
    # order is now each query's own ranking, taken in turn, because scores from
    # different queries and providers were never on one scale to sort by.
    kept = next(p for p in merged if p.arxiv_id == "2401.00001")
    assert kept.relevance_score == 3.0


def test_merge_respects_max_candidates_by_rank():
    papers = [
        _P(title=f"p{i}", doi=f"10.1/{i}", relevance_score=float(i)) for i in range(10)
    ]
    merged, captures = _merge_capture_candidates([("q", papers)], max_candidates=3)
    assert captures == 1
    assert [p.relevance_score for p in merged] == [9.0, 8.0, 7.0]


def test_merge_skips_keyless_candidates():
    merged, captures = _merge_capture_candidates([("q", [_P()])], max_candidates=5)
    assert merged == []
    assert captures == 1  # the query returned something, even if unusable


def test_open_with_enough_captures_is_accepted():
    # rho=0.7, alpha=0.1 -> need 6 anchors; 6 captures -> accept unchanged
    verdict, conf, action, trust, note = _apply_gap_governance(
        "open", 0.8, capture_queries=6, judge_model="gpt-5.5", alpha=0.1
    )
    assert action == "accept"
    assert verdict == "open"
    assert conf == 0.8
    assert "governance" in note


def test_open_with_sparse_capture_downgrades_to_inconclusive():
    # 1 successful capture round == effectively single-shot coverage
    verdict, conf, action, trust, note = _apply_gap_governance(
        "open", 0.9, capture_queries=1, judge_model="gpt-5.5", alpha=0.1
    )
    assert action == "require_external"
    assert verdict == "inconclusive"
    assert conf < 0.9


def test_open_with_partial_captures_keeps_verdict_but_discounts():
    verdict, conf, action, trust, note = _apply_gap_governance(
        "open", 0.9, capture_queries=4, judge_model="gpt-5.5", alpha=0.1
    )
    assert action == "require_external"
    assert verdict == "open"  # multi-query coverage, just needs more anchors
    assert conf <= trust
    assert conf < 0.9


def test_occupied_verdict_passes_through():
    verdict, conf, action, trust, note = _apply_gap_governance(
        "occupied", 0.6, capture_queries=0, judge_model="gpt-5.5", alpha=0.1
    )
    assert action == "accept_verdict"
    assert verdict == "occupied"
    assert conf == 0.6


def test_registry_spec_exposes_governance_alpha():
    from research_harness.primitives.registry import get_primitive_spec

    spec = get_primitive_spec("gap_ground_verify")
    assert spec is not None
    assert "governance_alpha" in spec.input_schema["properties"]


def test_published_no_later_uses_arxiv_month_precision():
    from research_harness._workflow.execution.llm_primitives import (
        _published_no_later,
    )

    @dataclass
    class _Dated:
        arxiv_id: str = ""
        year: int | None = None

    # arXiv YYMM: 2609 = 2026-09, after an August cutoff
    assert _published_no_later(_Dated(arxiv_id="2609.00001"), "2026-08") is False
    assert _published_no_later(_Dated(arxiv_id="2608.00001"), "2026-08") is True
    assert _published_no_later(_Dated(arxiv_id="2512.09999"), "2026-08") is True
    # year-only metadata: same-year kept (month unknown, fails open)
    assert _published_no_later(_Dated(year=2026), "2026-08") is True
    assert _published_no_later(_Dated(year=2027), "2026-08") is False
    # no date metadata at all: kept
    assert _published_no_later(_Dated(), "2026-08") is True


def test_merge_gives_every_capture_attempt_a_share():
    """One dense query family must not spend the whole candidate budget.

    The claim is decomposed precisely so several independent attempts are made
    on the hidden pre-empting literature. Ranking the union by score undoes
    that: a query whose index is dense and whose scores run high fills every
    slot, and the clinical queries that named the cohort return nothing the
    judge ever sees. A real run retrieved twenty-five papers on hypernetworks,
    LoRA and time-series forecasting, and the panel's own note said the hits
    were off-topic and therefore could not establish vacancy.
    """
    dense = [
        _P(title=f"generic ml {i}", doi=f"10.1/ml{i}", relevance_score=0.9)
        for i in range(10)
    ]
    clinical = [
        _P(title=f"cohort study {i}", doi=f"10.1/clin{i}", relevance_score=0.3)
        for i in range(10)
    ]

    merged, captures = _merge_capture_candidates(
        [("generic method terms", dense), ("cohort terms", clinical)], max_candidates=6
    )

    assert captures == 2
    titles = [p.title for p in merged]
    assert sum("cohort study" in t for t in titles) == 3, titles
    assert sum("generic ml" in t for t in titles) == 3, titles
