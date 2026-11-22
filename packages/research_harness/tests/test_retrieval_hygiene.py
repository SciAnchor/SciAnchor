"""Tests for retrieval evidence hygiene (E2/E3/E6–E8)."""

from __future__ import annotations

from research_harness.retrieval_hygiene import (
    arxiv_query_forms,
    audit_retrieved_rows,
    expand_synonym_queries,
    filter_numeric_evidence_methods,
    is_admissible_numeric_evidence,
    literal_match_report,
    provider_allowlist_for_text,
    recommend_index_route,
    sanitize_numeric_evidence_items,
    synonym_family_zero_hits,
    uncovered_index_note,
)


def test_arxiv_query_forms_single_token() -> None:
    forms = arxiv_query_forms("sycophancy")
    assert forms[0] == 'all:"sycophancy"'
    assert "all:sycophancy" in forms
    # Single token: no AND expansion.
    assert not any(" AND " in f for f in forms)


def test_arxiv_query_forms_multiword_unions_phrase_and_and() -> None:
    forms = arxiv_query_forms("process mining reward")
    assert 'all:"process mining reward"' in forms
    assert 'abs:"process mining reward"' in forms
    assert "all:process AND all:mining AND all:reward" in forms
    assert "abs:process AND abs:mining AND abs:reward" in forms
    # Stable, deduped order.
    assert len(forms) == len(set(forms))


def test_literal_match_flags_inflated_api_total() -> None:
    # "paper outlines" stem-pollutes "paper outline" (E6 strengthened case).
    texts = [
        "This paper outlines a new method.",
        "The paper outlines prior work.",
        "paper outline generation for agents",
    ]
    report = literal_match_report(texts, "paper outline", api_total=945)
    assert report["phrase_hits"] == 1
    assert report["stem_conjunct_hits"] >= 1
    assert report["usable_as_denominator"] is False
    assert any("novelty denominator" in n for n in report["notes"])


def test_literal_match_stem_conjunct_blocks_empty_cell() -> None:
    texts = [
        "Auditable decision traces for agentic routing under load.",
        "Interpretable and auditable clinical prediction with route logs.",
    ]
    report = literal_match_report(texts, "auditable routing", api_total=5)
    assert report["phrase_hits"] == 0
    assert report["stem_conjunct_hits"] == 2
    assert report["usable_as_denominator"] is False
    assert any("human review" in n for n in report["notes"])


def test_literal_match_clean_phrase_is_usable() -> None:
    texts = [
        "We study process mining reward signals.",
        "Unrelated topic about transformers.",
    ]
    report = literal_match_report(texts, "process mining reward", api_total=2)
    assert report["phrase_hits"] == 1
    assert report["usable_as_denominator"] is True
    assert report["notes"] == []


def test_audit_retrieved_rows_flags_low_abstract_coverage() -> None:
    rows = [
        {"title": "A paper about widgets", "abstract": ""},
        {"title": "Another widget study", "abstract": ""},
        {"title": "Widgets with abstract", "abstract": "We study widgets carefully."},
    ]
    report = audit_retrieved_rows(rows, "widgets", api_total=100)
    assert report["rows_with_abstract"] == 1
    assert report["abstract_coverage"] < 0.5
    assert report["usable_as_denominator"] is False
    assert any("lower bounds only" in n for n in report["notes"])


def test_numeric_evidence_requires_grep_method() -> None:
    assert is_admissible_numeric_evidence("grep") is True
    assert is_admissible_numeric_evidence("summary") is False
    assert is_admissible_numeric_evidence("webfetch") is False


def test_recommend_index_route_human_factors() -> None:
    route = recommend_index_route("function allocation under automation transparency")
    assert route["matched"] is True
    assert route["domain"] == "human_factors"
    assert "crossref" in route["primary_indexes"]
    note = uncovered_index_note(
        "function allocation under automation transparency",
        providers_queried=["arxiv", "local"],
    )
    assert "primary index" in note
    assert "crossref" in note


def test_synonym_family_zero_hits_flags_lexicon() -> None:
    report = synonym_family_zero_hits(
        {"ask for help": 0, "expert calls": 4, "escalation rate": 0}
    )
    assert report["suspect_lexicon"] is True
    assert "ask for help" in report["zero_families"]
    assert "expert calls" in report["nonzero_families"]
    assert "Suspect lexicon" in report["note"]


def test_filter_numeric_evidence_methods() -> None:
    ok, bad = filter_numeric_evidence_methods(
        [
            {"value": 12, "method": "grep"},
            {"value": 100, "method": "webfetch"},
            {"value": 3, "method": "summary"},
        ]
    )
    assert len(ok) == 1 and ok[0]["value"] == 12
    assert {b["method"] for b in bad} == {"webfetch", "summary"}


def test_provider_allowlist_for_text_pins_known_suite() -> None:
    allow = provider_allowlist_for_text(
        "function allocation under automation transparency"
    )
    assert allow is not None
    assert "crossref" in allow
    assert "pubmed" in allow
    assert "dblp" not in allow  # not in local provider suite
    assert provider_allowlist_for_text("totally unknown domain xyz") is None


def test_expand_synonym_queries_adds_known_family() -> None:
    qs = expand_synonym_queries(["ask for help budget", "raw gap"])
    assert "ask for help budget" in qs
    assert any("expert calls" == q for q in qs)
    assert any("escalation rate" == q for q in qs)


def test_sanitize_numeric_evidence_items_keeps_non_numeric() -> None:
    out = sanitize_numeric_evidence_items(
        [
            {"title": "A", "evidence": "overlaps mechanism"},
            {"title": "B", "value": 100, "method": "webfetch"},
            {"title": "C", "n": 12, "method": "grep"},
        ]
    )
    titles = {r["title"] for r in out["kept"]}
    assert titles == {"A", "C"}
    assert len(out["rejected"]) == 1
    assert "E10" in out["note"]
