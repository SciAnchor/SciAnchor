from __future__ import annotations

import json

from research_harness._selfdev.writing_logic_gate_runtime import (
    section_draft_logic_gate_block,
)
from research_harness.execution.harness import ResearchHarnessBackend
from research_harness.orchestrator import OrchestratorService
from research_harness.provenance.recorder import ProvenanceRecorder
from research_harness.storage.db import Database


def test_gate_recompute_blocks_faked_pass_when_bundle_invalid():
    """A self-declared passing report must NOT bypass the gate when the plan
    carries raw bundle inputs — the gate recomputes from them, so a hand-written
    ``{"status": "pass"}`` over invalid inputs is rejected."""
    plan = {
        "manuscript_logic_gate_report": {
            "schema_version": "rh.manuscript.logic_gate_report.v1",
            "status": "pass",
            "blockers": [],
        },
        "fine_logic_audit_report": _passing_fine_logic_audit_report(),
        # raw bundle input present but invalid -> recompute must block
        "core_claim_contract": {},
    }
    block = section_draft_logic_gate_block(
        db=None, section="introduction", topic_id=1, paper_plan=plan
    )
    assert block is not None
    assert block.gate_status != "pass"
    assert block.blockers  # recomputed structural blockers, not the faked empty list


def _passing_plan() -> dict:
    return {
        "manuscript_logic_gate_report": {
            "schema_version": "rh.manuscript.logic_gate_report.v1",
            "status": "pass",
            "blockers": [],
        },
        "fine_logic_audit_report": _passing_fine_logic_audit_report(),
    }


def _seed_one_paper(db: Database, topic_id: int) -> None:
    """Attach one paper to the topic so the evidence pool size is 1 (a [9]
    citation is then out of range and trips the citation audit)."""
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO papers (title, status) VALUES (?, 'meta_only')",
            ("Seed paper for evidence audit",),
        )
        paper_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (?, ?, 'high')",
            (paper_id, topic_id),
        )
        conn.commit()
    finally:
        conn.close()


def test_section_draft_strict_evidence_blocks_out_of_range_citations(db, monkeypatch):
    import pytest

    import research_harness.execution.llm_primitives as llm_primitives
    from research_harness.execution.llm_primitives import (
        SectionEvidenceUnsupportedError,
        section_draft,
    )

    topic_id = _seed_topic(db)
    _seed_one_paper(db, topic_id)
    monkeypatch.setenv("CODEX_ENABLED", "1")
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    # Draft cites [9] but the topic has no evidence papers -> out of range.
    monkeypatch.setattr(
        llm_primitives,
        "_client_chat",
        lambda *a, **k: json.dumps(
            {"content": "A bold claim [9].", "citations_used": [9], "word_count": 4}
        ),
    )

    # strict mode -> hard block
    with pytest.raises(SectionEvidenceUnsupportedError):
        section_draft(
            db=db,
            section="introduction",
            topic_id=topic_id,
            paper_plan=_passing_plan(),
            strict_evidence=True,
        )

    # default (warn-only) -> still succeeds
    out = section_draft(
        db=db,
        section="introduction",
        topic_id=topic_id,
        paper_plan=_passing_plan(),
        strict_evidence=False,
    )
    assert out.draft.content


def test_section_draft_strict_evidence_env_var_enables_block(db, monkeypatch):
    import pytest

    import research_harness.execution.llm_primitives as llm_primitives
    from research_harness.execution.llm_primitives import (
        SectionEvidenceUnsupportedError,
        section_draft,
    )

    topic_id = _seed_topic(db)
    _seed_one_paper(db, topic_id)
    monkeypatch.setenv("CODEX_ENABLED", "1")
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.setenv("RH_SECTION_DRAFT_STRICT_EVIDENCE", "1")
    monkeypatch.setattr(
        llm_primitives,
        "_client_chat",
        lambda *a, **k: json.dumps(
            {"content": "Another claim [7].", "citations_used": [7], "word_count": 4}
        ),
    )
    with pytest.raises(SectionEvidenceUnsupportedError):
        section_draft(
            db=db,
            section="introduction",
            topic_id=topic_id,
            paper_plan=_passing_plan(),
        )


def test_gate_now_applies_to_body_sections():
    """Body sections (results/method/etc.) are gated too: drafting one without a
    passing PAPER_PLAN is blocked, with a passing plan it proceeds."""
    blocked = section_draft_logic_gate_block(
        db=None, section="results", topic_id=1, paper_plan={}
    )
    assert blocked is not None
    assert blocked.required_report == "manuscript_logic_gate_report"

    passing_plan = {
        "manuscript_logic_gate_report": {
            "schema_version": "rh.manuscript.logic_gate_report.v1",
            "status": "pass",
            "blockers": [],
        },
        "fine_logic_audit_report": _passing_fine_logic_audit_report(),
    }
    assert (
        section_draft_logic_gate_block(
            db=None, section="results", topic_id=1, paper_plan=passing_plan
        )
        is None
    )


def test_gate_report_only_plan_still_trusts_recorded_pass():
    """Plans that carry only the recorded reports (no raw inputs) keep using the
    recorded status — the recompute path must not break report-only flows."""
    plan = {
        "manuscript_logic_gate_report": {
            "schema_version": "rh.manuscript.logic_gate_report.v1",
            "status": "pass",
            "blockers": [],
        },
        "fine_logic_audit_report": _passing_fine_logic_audit_report(),
    }
    block = section_draft_logic_gate_block(
        db=None, section="introduction", topic_id=1, paper_plan=plan
    )
    assert block is None


def _passing_fine_logic_audit_report() -> dict[str, object]:
    return {
        "schema_version": "rh.manuscript.fine_logic_audit_report.v1",
        "status": "pass",
        "blockers": [],
    }


def _seed_topic(db: Database) -> int:
    conn = db.connect()
    try:
        conn.execute(
            "INSERT INTO topics (name, description) VALUES (?, ?)",
            ("writing-logic-topic", "Topic for runtime writing gate tests"),
        )
        topic_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        conn.commit()
        return topic_id
    finally:
        conn.close()


def _record_passing_paper_plan(db: Database, topic_id: int) -> None:
    OrchestratorService(db).record_artifact(
        topic_id=topic_id,
        stage="write",
        artifact_type="PAPER_PLAN",
        title="Paper plan with passing manuscript logic gate",
        payload={
            "manuscript_logic_gate_report": {
                "schema_version": "rh.manuscript.logic_gate_report.v1",
                "status": "pass",
                "blockers": [],
            },
            "fine_logic_audit_report": _passing_fine_logic_audit_report(),
        },
    )


def test_direct_backend_blocks_intro_draft_without_logic_gate(db, monkeypatch):
    import research_harness.execution.llm_primitives as llm_primitives

    topic_id = _seed_topic(db)

    def unexpected_chat(*args, **kwargs):
        del args, kwargs
        raise AssertionError("section_draft should be blocked before LLM execution")

    monkeypatch.setenv("CODEX_ENABLED", "1")
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.setattr(llm_primitives, "_client_chat", unexpected_chat)

    backend = ResearchHarnessBackend(db=db)
    result = backend.execute("section_draft", section="introduction", topic_id=topic_id)

    assert not result.success
    assert "MANUSCRIPT_LOGIC_GATE_REQUIRED" in result.error
    assert "manuscript_logic_gate_report" in result.error


def test_direct_backend_blocks_intro_draft_without_fine_logic_audit(db, monkeypatch):
    import research_harness.execution.llm_primitives as llm_primitives

    topic_id = _seed_topic(db)

    def unexpected_chat(*args, **kwargs):
        del args, kwargs
        raise AssertionError("section_draft should be blocked before LLM execution")

    monkeypatch.setenv("CODEX_ENABLED", "1")
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.setattr(llm_primitives, "_client_chat", unexpected_chat)

    backend = ResearchHarnessBackend(db=db)
    result = backend.execute(
        "section_draft",
        section="introduction",
        topic_id=topic_id,
        paper_plan={
            "manuscript_logic_gate_report": {
                "schema_version": "rh.manuscript.logic_gate_report.v1",
                "status": "pass",
                "blockers": [],
            }
        },
    )

    assert not result.success
    assert "MANUSCRIPT_LOGIC_GATE_REQUIRED" in result.error
    assert "fine_logic_audit_report" in result.error


def test_direct_backend_allows_intro_draft_with_active_logic_gate(db, monkeypatch):
    import research_harness.execution.llm_primitives as llm_primitives

    topic_id = _seed_topic(db)
    _record_passing_paper_plan(db, topic_id)
    chat_calls: list[str] = []

    def fake_chat(_client, prompt: str, **_kwargs):
        chat_calls.append(prompt)
        return json.dumps(
            {
                "content": (
                    "A gated introduction follows the approved paper plan [1]."
                ),
                "citations_used": [1],
                "word_count": 9,
            }
        )

    monkeypatch.setenv("CODEX_ENABLED", "1")
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.setattr(llm_primitives, "_client_chat", fake_chat)

    backend = ResearchHarnessBackend(db=db)
    result = backend.execute("section_draft", section="introduction", topic_id=topic_id)

    assert result.success, result.error
    assert len(chat_calls) == 1
    assert result.output.draft.section == "introduction"
    assert "approved paper plan" in result.output.draft.content


def test_direct_backend_allows_intro_draft_with_explicit_logic_gate(db, monkeypatch):
    import research_harness.execution.llm_primitives as llm_primitives

    topic_id = _seed_topic(db)
    chat_calls: list[str] = []

    def fake_chat(_client, prompt: str, **_kwargs):
        chat_calls.append(prompt)
        return json.dumps(
            {
                "content": "An explicit paper plan gates this introduction [1].",
                "citations_used": [1],
                "word_count": 8,
            }
        )

    monkeypatch.setenv("CODEX_ENABLED", "1")
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.setattr(llm_primitives, "_client_chat", fake_chat)

    backend = ResearchHarnessBackend(db=db)
    result = backend.execute(
        "section_draft",
        section="introduction",
        topic_id=topic_id,
        paper_plan={
            "manuscript_logic_gate_report": {
                "schema_version": "rh.manuscript.logic_gate_report.v1",
                "status": "pass",
                "blockers": [],
            },
            "fine_logic_audit_report": _passing_fine_logic_audit_report(),
        },
    )

    assert result.success, result.error
    assert len(chat_calls) == 1
    assert "explicit paper plan" in result.output.draft.content


def _bundle_wrong_at(field: str, value: object = ("introduction", "methods")) -> dict:
    """The smallest bundle that reaches the field-type walk, wrong at one field.

    ``made_in``, ``first_use`` and ``where_to_state`` all say *where in the paper*,
    and all three must be one section as a string. A model that reads any of them as
    a list is the same defect in three places.
    """
    value = list(value)
    return {
        "schema_version": "rh.manuscript.logic_bundle.v1",
        "core_claim_contract": {},
        "argument_tree": {},
        "term_registry": [
            {
                "term": "t",
                "first_use": value if field == "first_use" else "introduction",
            }
        ],
        "promise_realization_matrix": [
            {"promise": "p", "made_in": value if field == "made_in" else "introduction"}
        ],
        "paragraph_intent_tree": [],
        "fine_logic_audit": {
            "schema_version": "rh.manuscript.fine_logic_audit.v1",
            "argument_link_map": [],
            "assumption_warrant_table": [
                {
                    "assumption_id": "a1",
                    "where_to_state": value
                    if field == "where_to_state"
                    else "introduction",
                }
            ],
            "claim_certainty_audit": [],
            "paragraph_flow_audit": [],
            "intro_logic_map": {},
            "figure_table_message_audit": [],
            "writing_defect_log": [],
        },
    }


def test_a_wrong_type_refusal_names_the_value_and_the_shape_expected():
    """ "wrong type: made_in" named neither, so the reader could not tell a list from a
    null without the reply — which the same refusal had already thrown away."""
    import pytest

    from research_harness.execution.llm_primitives import _validate_logic_field_types

    for field in ("made_in", "first_use", "where_to_state"):
        with pytest.raises(ValueError) as refusal:
            _validate_logic_field_types(_bundle_wrong_at(field), set())
        message = str(refusal.value)
        assert field in message, message
        assert "list" in message and "introduction" in message, message
        assert "expected a string" in message, message


def test_a_refused_reply_survives_the_primitive_that_refused_it(db, monkeypatch):
    """csmopen12's architecture paid 21803 completion tokens and artifact 6921 kept a
    hash and a field name: the backend turns any exception into output=None, so the
    answer a primitive refuses is destroyed by the refusal and the next round buys it
    again."""
    import research_harness.execution.llm_primitives as llm_primitives

    reply = json.dumps(
        {
            "paper_title": "A title",
            "sections": [{"section": "introduction", "title": "Introduction"}],
            "manuscript_logic_bundle": _bundle_wrong_at("made_in"),
        }
    )

    class _Client:
        model = "test-model"

        def chat(self, _prompt, **_kwargs):
            return reply

    monkeypatch.setenv("CODEX_ENABLED", "1")
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    # Below _client_chat, which is where the reply is stashed: patching _client_chat
    # itself would replace the mechanism under test.
    monkeypatch.setattr(llm_primitives, "_get_client", lambda *a, **k: _Client())

    result = ResearchHarnessBackend(db=db).execute(
        "writing_architecture",
        topic_id=_seed_topic(db),
        contributions="A cord field queried at assigned levels.",
        manuscript_logic_context={
            "sections": ["introduction"],
            "allowed_evidence": [{"id": "E1"}],
        },
    )

    assert not result.success and result.output is None
    assert "made_in" in result.error
    assert result.refused_reply == reply


def test_tracked_backend_records_blocked_intro_draft_as_failed_attempt(
    db,
    monkeypatch,
):
    import research_harness.execution.llm_primitives as llm_primitives
    from research_harness.execution.tracked import TrackedBackend

    topic_id = _seed_topic(db)

    def unexpected_chat(*args, **kwargs):
        del args, kwargs
        raise AssertionError("section_draft should be blocked before LLM execution")

    monkeypatch.setenv("CODEX_ENABLED", "1")
    monkeypatch.setenv("LLM_PROVIDER", "codex")
    monkeypatch.setattr(llm_primitives, "_client_chat", unexpected_chat)

    backend = TrackedBackend(
        inner=ResearchHarnessBackend(db=db),
        recorder=ProvenanceRecorder(db),
    )
    result = backend.execute("section_draft", section="abstract", topic_id=topic_id)

    assert not result.success
    assert "MANUSCRIPT_LOGIC_GATE_REQUIRED" in result.error

    conn = db.connect()
    try:
        row = conn.execute(
            """
            SELECT primitive, success, error
            FROM provenance_records
            WHERE primitive = 'section_draft'
            """
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["primitive"] == "section_draft"
    assert row["success"] == 0
    assert "MANUSCRIPT_LOGIC_GATE_REQUIRED" in row["error"]
