"""Tests for the enriched numbered evidence list used by section drafting."""

from __future__ import annotations

import json

import pytest

from research_harness._workflow.execution import llm_primitives
from research_harness.execution.compiled_summary import format_compiled_for_evidence
from research_harness.storage.db import Database


COMPILED = {
    "overview": "Adaptive gating model.",
    "claims": [
        {
            "claim": "Gating cuts MSE by 3.1%",
            "evidence": "Table 2",
            "strength": "strong",
        },
        "Second claim as plain string",
    ],
    "metrics": [
        {"dataset": "ETTh1", "metric": "MSE", "value": "0.371", "baseline": "0.383"},
    ],
    "limitations": ["Only tested on hourly data"],
}


@pytest.fixture
def db(tmp_path):
    db = Database(tmp_path / "t.db")
    db.migrate()
    return db


@pytest.fixture
def topic_id(db):
    conn = db.connect()
    try:
        cur = conn.execute("INSERT INTO topics (name, description) VALUES ('t', 't')")
        tid = int(cur.lastrowid)
        conn.commit()
    finally:
        conn.close()
    return tid


def _add_paper(
    db,
    topic_id,
    title,
    *,
    relevance="high",
    citations=10,
    compiled=None,
    abstract="Some abstract text.",
):
    conn = db.connect()
    try:
        cur = conn.execute(
            """
            INSERT INTO papers (title, authors, year, venue, abstract, citation_count, compiled_summary)
            VALUES (?, 'A. Author', 2026, 'NeurIPS', ?, ?, ?)
            """,
            (title, abstract, citations, json.dumps(compiled) if compiled else ""),
        )
        pid = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (?, ?, ?)",
            (pid, topic_id, relevance),
        )
        conn.commit()
    finally:
        conn.close()
    return pid


def _add_claim_note(db, topic_id, paper_id, content):
    conn = db.connect()
    try:
        conn.execute(
            """
            INSERT INTO topic_paper_notes (paper_id, topic_id, note_type, content)
            VALUES (?, ?, 'claim', ?)
            """,
            (paper_id, topic_id, content),
        )
        conn.commit()
    finally:
        conn.close()


class TestFormatCompiledForEvidence:
    def test_digest_contains_numbers_and_limitation(self):
        digest = format_compiled_for_evidence(COMPILED)
        assert "Gating cuts MSE by 3.1%" in digest
        assert "evidence: Table 2" in digest
        assert "strength: strong" in digest
        assert "ETTh1/MSE = 0.371 (baseline: 0.383)" in digest
        assert "Limitation: Only tested on hourly data" in digest

    def test_plain_string_claims_supported(self):
        digest = format_compiled_for_evidence(COMPILED)
        assert "Second claim as plain string" in digest

    def test_empty(self):
        assert format_compiled_for_evidence({}) == ""

    def test_max_chars(self):
        assert len(format_compiled_for_evidence(COMPILED, max_chars=80)) <= 80


class TestBuildNumberedEvidenceRichMode:
    def test_compiled_digest_injected_for_top_papers(self, db, topic_id, monkeypatch):
        monkeypatch.setattr(
            llm_primitives, "_get_paperindex_context", lambda *a, **k: None
        )
        _add_paper(db, topic_id, "Rich paper", compiled=COMPILED)
        text, ids = llm_primitives._build_numbered_evidence(
            db, topic_id, task_type="section_draft", section="experiments"
        )
        assert len(ids) == 1
        assert "Claim: Gating cuts MSE by 3.1%" in text
        assert "baseline: 0.383" in text

    def test_extracted_claim_notes_injected(self, db, topic_id, monkeypatch):
        monkeypatch.setattr(
            llm_primitives, "_get_paperindex_context", lambda *a, **k: None
        )
        pid = _add_paper(db, topic_id, "Paper with notes")
        _add_claim_note(db, topic_id, pid, "Sharpness-aware training stabilizes gates")
        text, _ = llm_primitives._build_numbered_evidence(
            db, topic_id, task_type="section_draft", section="method"
        )
        assert "Extracted claim: Sharpness-aware training stabilizes gates" in text

    def test_section_scoped_task_query_used(self, db, topic_id, monkeypatch):
        seen: list[str] = []

        def fake_ctx(_db, _pid, task_type):
            seen.append(task_type)
            return "[Section: Results] snippet text"

        monkeypatch.setattr(llm_primitives, "_get_paperindex_context", fake_ctx)
        _add_paper(db, topic_id, "Indexed paper")
        text, _ = llm_primitives._build_numbered_evidence(
            db, topic_id, task_type="section_draft", section="experiments"
        )
        assert seen == ["section_draft:experiments"]
        assert "[Section: Results] snippet text" in text

    def test_unscoped_section_falls_back_to_base_task(self, db, topic_id, monkeypatch):
        seen: list[str] = []

        def fake_ctx(_db, _pid, task_type):
            seen.append(task_type)
            return None

        monkeypatch.setattr(llm_primitives, "_get_paperindex_context", fake_ctx)
        _add_paper(db, topic_id, "Indexed paper")
        llm_primitives._build_numbered_evidence(
            db, topic_id, task_type="section_draft", section="appendix"
        )
        assert seen == ["section_draft"]

    def test_priority_paper_ids_come_first(self, db, topic_id, monkeypatch):
        monkeypatch.setattr(
            llm_primitives, "_get_paperindex_context", lambda *a, **k: None
        )
        _add_paper(db, topic_id, "High relevance", relevance="high", citations=500)
        low_pid = _add_paper(
            db, topic_id, "Low relevance", relevance="low", citations=0
        )
        text, ids = llm_primitives._build_numbered_evidence(
            db, topic_id, priority_paper_ids=[low_pid]
        )
        assert ids[0] == low_pid
        assert text.index("Low relevance") < text.index("High relevance")

    def test_rich_top_k_zero_matches_legacy_format(self, db, topic_id, monkeypatch):
        called = {"n": 0}

        def fake_ctx(*a, **k):
            called["n"] += 1
            return "should not appear"

        monkeypatch.setattr(llm_primitives, "_get_paperindex_context", fake_ctx)
        _add_paper(db, topic_id, "Plain paper", compiled=COMPILED)
        text, _ = llm_primitives._build_numbered_evidence(db, topic_id, rich_top_k=0)
        assert called["n"] == 0
        assert "Claim:" not in text
        assert "Abstract: Some abstract text." in text

    def test_char_budget_stops_enrichment_but_keeps_headers(
        self, db, topic_id, monkeypatch
    ):
        monkeypatch.setattr(
            llm_primitives, "_get_paperindex_context", lambda *a, **k: None
        )
        for i in range(4):
            _add_paper(
                db,
                topic_id,
                f"Paper {i}",
                citations=100 - i,
                compiled=COMPILED,
                abstract="A" * 400,
            )
        text, ids = llm_primitives._build_numbered_evidence(
            db, topic_id, char_budget=500, rich_top_k=4
        )
        # All papers keep their [N] headers so the citation range is intact.
        assert len(ids) == 4
        assert "[4]" in text
        # Enrichment stops once the budget is exhausted: the first paper is
        # enriched (budget not yet hit), later ones are not.
        assert text.count("Claim: Gating cuts MSE by 3.1%") < 4

    def test_out_of_pool_priority_ids_ignored(self, db, topic_id, monkeypatch):
        monkeypatch.setattr(
            llm_primitives, "_get_paperindex_context", lambda *a, **k: None
        )
        pid = _add_paper(db, topic_id, "Only paper")
        _, ids = llm_primitives._build_numbered_evidence(
            db, topic_id, priority_paper_ids=[999999, pid]
        )
        assert ids == [pid]

    def test_restricted_list_holds_only_the_named_evidence(
        self, db, topic_id, monkeypatch
    ):
        """A0114's introduction cited ref41..ref50 against a 40-entry bibliography:
        the numbered list it was shown had been filled out from the topic."""
        monkeypatch.setattr(
            llm_primitives, "_get_paperindex_context", lambda *a, **k: None
        )
        named = [_add_paper(db, topic_id, f"Named {i}") for i in range(3)]
        other = _add_paper(db, topic_id, "Not in the bibliography")
        text, ids = llm_primitives._build_numbered_evidence(
            db, topic_id, priority_paper_ids=named, restrict_to_priority=True
        )
        assert ids == named and "[4]" not in text
        _, wide = llm_primitives._build_numbered_evidence(
            db, topic_id, priority_paper_ids=named
        )
        assert other in wide


class TestCoercePaperIdList:
    def test_accepts_ints_digits_and_paper_markers(self):
        assert llm_primitives._coerce_paper_id_list([3, "7", "paper_11"]) == [3, 7, 11]

    def test_skips_claim_ids_and_junk(self):
        assert (
            llm_primitives._coerce_paper_id_list(["claim_3", "fig:2", None, True]) == []
        )

    def test_empty(self):
        assert llm_primitives._coerce_paper_id_list(None) == []
