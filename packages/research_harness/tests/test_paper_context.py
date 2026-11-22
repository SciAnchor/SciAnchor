"""Tests for the shared paper context threaded through section drafting."""

from __future__ import annotations

import json

import pytest

from research_harness.execution.paper_context import (
    PaperContext,
    build_paper_context,
    digest_section,
    render_paper_context,
)
from research_harness.storage.db import Database


PLAN = {
    "core_claim_contract": {
        "one_sentence_claim": "We transform static routing into adaptive gating via GateFormer.",
        "central_problem": "Static mixture routing cannot adapt granularity per token.",
        "allowed_focus": ["adaptive routing", "efficiency"],
    },
    "argument_tree": {
        "root_claim": "Adaptive gating beats static routing.",
        "problems": [
            {
                "problem_id": "P1",
                "statement": "Routing granularity is fixed at training time",
                "contribution_id": "C1",
                "evidence_ids": ["tab:main"],
                "section_ids": ["experiments"],
            },
            {
                "problem_id": "P2",
                "statement": "Gate collapse under distribution shift",
                "contribution_id": "C2",
                "evidence_ids": ["fig:shift"],
                "section_ids": ["experiments"],
            },
        ],
    },
    "term_registry": [
        {"term": "GateFormer", "definition": "our adaptive gating architecture"},
        {"term": "gate collapse", "definition": "degenerate routing distribution"},
    ],
    "promise_realization_matrix": [
        {
            "promise": "3.1% average MSE reduction",
            "made_in": "introduction",
            "realized_by": ["experiments"],
            "evidence_ids": ["tab:main"],
        }
    ],
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
        cur = conn.execute(
            "INSERT INTO topics (name, description, contributions) VALUES (?, ?, ?)",
            ("t", "t", "C1: adaptive gating. C2: collapse-resistant training."),
        )
        tid = int(cur.lastrowid)
        conn.commit()
    finally:
        conn.close()
    return tid


class TestBuildPaperContext:
    def test_from_supplied_plan(self, db, topic_id):
        ctx = build_paper_context(db, topic_id, paper_plan=PLAN)
        assert "adaptive gating" in ctx.one_sentence_claim
        assert ctx.central_problem
        assert len(ctx.gaps) == 2
        assert len(ctx.term_registry) == 2
        assert len(ctx.promises) == 1
        assert "C1" in ctx.contributions

    def test_writing_architecture_feeds_outline_sections(self, db, topic_id):
        payload = {
            "paper_title": "GateFormer: Adaptive Gating",
            "sections": [
                {
                    "section": "experiments",
                    "argument_strategy": "prove C1 on three benchmarks",
                    "key_evidence": ["tab:main"],
                },
                {"section": "intro", "argument_strategy": "stakes first"},
            ],
        }
        conn = db.connect()
        try:
            conn.execute(
                """
                INSERT INTO project_artifacts
                    (topic_id, stage, artifact_type, status, title, payload_json)
                VALUES (?, 'write', 'writing_architecture', 'active', 't', ?)
                """,
                (topic_id, json.dumps(payload)),
            )
            conn.commit()
        finally:
            conn.close()

        ctx = build_paper_context(db, topic_id, paper_plan=PLAN)
        assert ctx.title == "GateFormer: Adaptive Gating"
        assert "experiments" in ctx.outline_sections
        # "intro" alias normalized to "introduction"
        assert "introduction" in ctx.outline_sections

    def test_never_raises_on_missing_everything(self, db):
        ctx = build_paper_context(db, 999999)
        assert isinstance(ctx, PaperContext)
        ctx_none = build_paper_context(None, None)
        assert ctx_none.is_empty()

    def test_title_from_outline_fallback(self, db, topic_id):
        ctx = build_paper_context(
            db, topic_id, paper_plan=PLAN, outline="Working title: My Great Paper"
        )
        assert ctx.title == "My Great Paper"


class TestRenderPaperContext:
    def _ctx(self, db, topic_id) -> PaperContext:
        return build_paper_context(db, topic_id, paper_plan=PLAN)

    def test_experiments_sees_promises_to_realize(self, db, topic_id):
        rendered = render_paper_context(self._ctx(db, topic_id), "experiments")
        assert "PAPER CONTEXT" in rendered
        assert "Promises this section MUST realize" in rendered
        assert "3.1% average MSE reduction" in rendered

    def test_introduction_sees_promises_it_makes(self, db, topic_id):
        rendered = render_paper_context(self._ctx(db, topic_id), "introduction")
        assert "Promises this section makes" in rendered

    def test_gaps_and_terms_rendered(self, db, topic_id):
        rendered = render_paper_context(self._ctx(db, topic_id), "related_work")
        assert "[P1]" in rendered
        assert "contribution C1" in rendered
        assert "GateFormer" in rendered
        assert "verbatim" in rendered

    def test_empty_context_renders_empty(self):
        assert render_paper_context(PaperContext(), "introduction") == ""

    def test_max_chars_respected(self, db, topic_id):
        rendered = render_paper_context(
            self._ctx(db, topic_id), "experiments", max_chars=200
        )
        assert len(rendered) <= 200

    def test_drafted_digests_visible_to_later_sections(self, db, topic_id):
        ctx = self._ctx(db, topic_id)
        ctx.drafted["introduction"] = "We present GateFormer. It adapts. (900 words)"
        rendered = render_paper_context(ctx, "experiments")
        assert "Already drafted sections" in rendered
        assert "We present GateFormer" in rendered
        # A section never sees its own digest
        own = render_paper_context(ctx, "introduction")
        assert "Already drafted sections" not in own


class TestRoundTrip:
    def test_to_dict_from_dict(self, db, topic_id):
        ctx = build_paper_context(db, topic_id, paper_plan=PLAN)
        ctx.drafted["introduction"] = "digest"
        clone = PaperContext.from_dict(ctx.to_dict())
        assert clone.one_sentence_claim == ctx.one_sentence_claim
        assert clone.gaps == ctx.gaps
        assert clone.drafted == ctx.drafted

    def test_from_dict_malformed(self):
        assert PaperContext.from_dict(None).is_empty()
        assert PaperContext.from_dict({"gaps": None}).is_empty()


class TestDigestSection:
    def test_digest_shape(self):
        content = (
            "GateFormer adapts routing granularity per token. This closes gap P1. "
            "More prose follows here.\n"
            "\\begin{itemize}\n"
            "\\item \\textbf{Adaptive gating}: per-token granularity.\n"
            "\\end{itemize}\n"
        )
        digest = digest_section(content)
        assert "GateFormer adapts routing" in digest
        assert "Contributions listed" in digest
        assert "words)" in digest

    def test_empty(self):
        assert digest_section("") == ""
