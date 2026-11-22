"""Regression tests for consistency_check context separation and cache refresh.

An end-to-end run spent ~1h chasing "stale synthesis" highs because the
cached topic overview was injected as if it were manuscript text and only
refreshed when the paper count changed.
"""

from __future__ import annotations

import json

import pytest

from research_harness._workflow.execution import llm_primitives, prompts
from research_harness._workflow.execution.compiled_summary import (
    invalidate_topic_summary,
)


def _seed_topic(db, topic_id: int = 1) -> None:
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (id, name) VALUES (?, ?)",
            (topic_id, f"topic-{topic_id}"),
        )
        # paper_count matches the (empty) live pool so the cache HITS while
        # holding stale text — the exact failure mode from the 2026-07-02 run,
        # where the pool was stable but the manuscript scope had narrowed.
        conn.execute(
            "INSERT INTO topic_summaries (topic_id, summary, paper_count, paper_ids_json) "
            "VALUES (?, ?, ?, ?)",
            (topic_id, "stale broad-field overview", 0, "[]"),
        )
        conn.commit()
    finally:
        conn.close()


def _cached_summary(db, topic_id: int = 1):
    conn = db.connect()
    try:
        return conn.execute(
            "SELECT summary FROM topic_summaries WHERE topic_id = ?", (topic_id,)
        ).fetchone()
    finally:
        conn.close()


class TestConsistencyCheckPrompt:
    def test_prompt_separates_manuscript_from_literature_context(self):
        prompt = prompts.consistency_check_prompt(
            "Section: method text", literature_context="pool overview text"
        )
        assert "Manuscript sections under review" in prompt
        assert "REFERENCE ONLY" in prompt
        assert "Do NOT report issues about this context itself" in prompt
        assert prompt.index("Section: method text") < prompt.index("pool overview text")

    def test_prompt_demands_single_pass_full_report_with_source(self):
        prompt = prompts.consistency_check_prompt("text")
        assert "ALL issues" in prompt
        assert "single pass" in prompt
        assert '"source"' in prompt
        assert "literature_context" in prompt

    def test_prompt_without_context_has_no_reference_block(self):
        prompt = prompts.consistency_check_prompt("text")
        assert "REFERENCE ONLY" not in prompt


class TestInvalidateTopicSummary:
    def test_deletes_cached_row(self, db):
        _seed_topic(db)
        assert _cached_summary(db) is not None
        assert invalidate_topic_summary(db, 1) is True
        assert _cached_summary(db) is None

    def test_returns_false_when_nothing_cached(self, db):
        assert invalidate_topic_summary(db, 999) is False


class TestConsistencyCheckPrimitive:
    @pytest.fixture
    def fake_llm(self, monkeypatch):
        calls: dict[str, str] = {}

        def _fake_chat(client, prompt):
            calls["prompt"] = prompt
            return json.dumps(
                {
                    "issues": [
                        {
                            "issue_type": "contradiction",
                            "severity": "high",
                            "location": "method",
                            "source": "literature_context",
                            "description": "manuscript narrower than pool",
                            "suggestion": "scope note",
                        },
                        {
                            "issue_type": "notation",
                            "severity": "low",
                            "location": "method",
                            "source": "not-a-valid-source",
                            "description": "symbol drift",
                            "suggestion": "unify",
                        },
                    ]
                }
            )

        monkeypatch.setattr(llm_primitives, "_client_chat", _fake_chat)
        monkeypatch.setattr(llm_primitives, "_get_client", lambda *a, **k: object())
        return calls

    def test_issue_source_parsed_and_defaulted(self, db, fake_llm):
        _seed_topic(db)
        out = llm_primitives.consistency_check(
            db=db, topic_id=1, sections=["method text body"]
        )
        assert out.issues[0].source == "literature_context"
        # invalid source values fall back to manuscript
        assert out.issues[1].source == "manuscript"

    def test_sections_go_into_manuscript_block_not_context(self, db, fake_llm):
        _seed_topic(db)
        llm_primitives.consistency_check(
            db=db, topic_id=1, sections=["UNIQUE-MANUSCRIPT-MARKER"]
        )
        prompt = fake_llm["prompt"]
        manuscript_pos = prompt.index("UNIQUE-MANUSCRIPT-MARKER")
        context_header = prompt.index("Topic literature context")
        assert manuscript_pos < context_header
        assert "stale broad-field overview" in prompt[context_header:]

    def test_refresh_context_invalidates_cache(self, db, fake_llm):
        _seed_topic(db)
        llm_primitives.consistency_check(
            db=db, topic_id=1, sections=["text"], refresh_context=True
        )
        # cached stale overview must be gone (recompiled from live pool,
        # which is empty here)
        assert _cached_summary(db) is None
        assert "stale broad-field overview" not in fake_llm["prompt"]

    def test_without_refresh_cache_is_kept(self, db, fake_llm):
        _seed_topic(db)
        llm_primitives.consistency_check(db=db, topic_id=1, sections=["text"])
        assert _cached_summary(db) is not None
