"""Opt-in manuscript planning and exact full-source revision contracts."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from research_harness.execution import llm_primitives as llm, prompts
from research_harness.primitives.registry import get_primitive_spec
from research_harness.primitives.types import WritingArchitectureOutput


@pytest.fixture
def plan_bundle():
    plan = json.loads(
        (
            Path(__file__).parent
            / "fixtures/writing/example_paper_plan_with_logic_reports.json"
        ).read_text()
    )
    plan["paragraph_intent_tree"] = [
        *plan["paragraph_intent_tree"],
        {**plan["paragraph_intent_tree"][1], "paragraph_id": "intro-2"},
        {
            **plan["paragraph_intent_tree"][2],
            "section": "experiments",
            "paragraph_id": "experiments-2",
        },
    ]
    coarse = (
        "core_claim_contract",
        "argument_tree",
        "term_registry",
        "promise_realization_matrix",
        "paragraph_intent_tree",
    )
    fine = (
        "argument_link_map",
        "assumption_warrant_table",
        "claim_certainty_audit",
        "paragraph_flow_audit",
        "intro_logic_map",
        "figure_table_message_audit",
        "writing_defect_log",
    )
    return {
        "schema_version": "rh.manuscript.logic_bundle.v1",
        **{key: plan[key] for key in coarse},
        "fine_logic_audit": {
            "schema_version": "rh.manuscript.fine_logic_audit.v1",
            **{key: plan[key] for key in fine},
        },
    }


def context_for(bundle):
    ids = set()

    def collect(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"evidence_ids", "backing_evidence_ids"}:
                    ids.update(item)
                else:
                    collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(bundle)
    return {
        "allowed_evidence": [{"id": identity} for identity in sorted(ids)],
        "sections": ["abstract", "introduction", "method", "experiments"],
        "proposal": "A frozen contribution",
    }


@pytest.fixture
def provider(monkeypatch):
    state = SimpleNamespace(response={}, prompts=[])
    monkeypatch.setattr(
        llm, "_get_client", lambda *a, **kw: SimpleNamespace(model="offline")
    )

    def chat(client, prompt):
        state.prompts.append(prompt)
        return (
            state.response
            if isinstance(state.response, str)
            else json.dumps(state.response)
        )

    monkeypatch.setattr(llm, "_client_chat", chat)
    monkeypatch.setattr(llm, "eag_revision_guidance", lambda *a: "")
    return state


def architecture(db, context, provider, bundle):
    provider.response = {
        "sections": [
            {"section": section, "target_words": 500} for section in context["sections"]
        ],
        "manuscript_logic_bundle": bundle,
    }
    return llm.writing_architecture(
        db=db,
        topic_id=1,
        contributions="Frozen mechanism",
        writing_patterns="Exemplar pattern",
        outline="Existing outline",
        manuscript_logic_context=context,
    )


def test_optional_architecture_preserves_default_behavior(db, provider):
    provider.response = {"paper_title": "Legacy", "sections": []}
    result = llm.writing_architecture(db=db, topic_id=1, contributions="Mechanism")
    assert result.paper_title == "Legacy"
    assert result.manuscript_logic_bundle == {}
    assert WritingArchitectureOutput().manuscript_logic_bundle == {}
    assert "manuscript_logic_bundle" not in provider.prompts[0]


def test_architecture_returns_validated_raw_bundle_without_context_truncation(
    db, provider, plan_bundle
):
    context = {
        **context_for(plan_bundle),
        "science": "x" * 25000 + "EXACT_TAIL_\u8bc1\u636e",
    }
    before = deepcopy(context)
    result = architecture(db, context, provider, plan_bundle)
    assert result.manuscript_logic_bundle == plan_bundle
    assert context == before
    assert "EXACT_TAIL_\u8bc1\u636e" in provider.prompts[0]
    assert all(
        item["id"] in provider.prompts[0] for item in context["allowed_evidence"]
    )
    assert "rh.manuscript.logic_bundle.v1" in provider.prompts[0]
    llm.validate_manuscript_logic_bundle(result.manuscript_logic_bundle, context)


@pytest.mark.parametrize(
    "change",
    [
        "missing",
        "coarse",
        "fine",
        "unknown_evidence",
        "missing_section",
        "bad_schema",
        "wrong_type",
    ],
)
def test_architecture_refuses_invalid_plan(db, provider, plan_bundle, change):
    context = context_for(plan_bundle)
    if change == "missing":
        plan_bundle = {}
    elif change == "coarse":
        plan_bundle["core_claim_contract"]["one_sentence_claim"] = ""
    elif change == "fine":
        plan_bundle["fine_logic_audit"]["intro_logic_map"] = {}
    elif change == "unknown_evidence":
        plan_bundle["argument_tree"]["problems"][0]["evidence_ids"] = [
            "invented:result"
        ]
    elif change == "missing_section":
        context = {**context, "sections": [*context["sections"], "results"]}
    elif change == "bad_schema":
        plan_bundle["schema_version"] = "wrong"
    else:
        plan_bundle["paragraph_intent_tree"] = "not a list"
    with pytest.raises(ValueError, match="logic|evidence|section|bundle"):
        architecture(db, context, provider, plan_bundle)


@pytest.mark.parametrize(
    "context",
    [
        True,
        {},
        {"sections": []},
        {"sections": ["method"], "allowed_evidence": []},
        {"sections": ["method", "method"], "allowed_evidence": [{"id": "p1"}]},
        {"sections": ["method"], "allowed_evidence": [{"id": "p1"}, {"id": "p1"}]},
        {
            "sections": ["method"],
            "allowed_evidence": [{"id": "p1"}],
            "text": "x" * 100001,
        },
        {
            "sections": ["method"],
            "allowed_evidence": [{"id": "p1"}],
            "number": float("nan"),
        },
    ],
)
def test_invalid_context_fails_before_provider(db, provider, context):
    with pytest.raises(ValueError):
        llm.writing_architecture(
            db=db,
            topic_id=1,
            contributions="Mechanism",
            manuscript_logic_context=context,
        )
    assert provider.prompts == []


@pytest.mark.parametrize("field", ["allowed_certainty", "actual_certainty"])
def test_logic_bundle_rejects_unknown_certainty_labels(
    db, provider, plan_bundle, field
):
    context = context_for(plan_bundle)
    plan_bundle["fine_logic_audit"]["claim_certainty_audit"][0][field] = (
        "invented_universal"
    )
    with pytest.raises(ValueError, match="certainty"):
        architecture(db, context, provider, plan_bundle)


@pytest.mark.parametrize(
    "target,field,value",
    [
        ("argument_tree", "section_ids", ["missing-section"]),
        ("argument_link_map", "paragraph_ids", ["missing-paragraph"]),
        ("figure_table_message_audit", "supports_claim_ids", ["missing-claim"]),
        ("claim_certainty_audit", "claim_id", "missing-claim"),
        ("paragraph_flow_audit", "paragraph_id", "missing-paragraph"),
    ],
)
def test_logic_bundle_rejects_unresolved_references(
    db, provider, plan_bundle, target, field, value
):
    context = context_for(plan_bundle)
    rows = (
        plan_bundle["argument_tree"]["problems"]
        if target == "argument_tree"
        else plan_bundle["fine_logic_audit"][target]
    )
    rows[0][field] = value
    with pytest.raises(ValueError, match="reference"):
        architecture(db, context, provider, plan_bundle)


@pytest.mark.parametrize(
    "target,field",
    [("paragraph_intent_tree", "paragraph_id"), ("argument_link_map", "claim_id")],
)
def test_logic_bundle_rejects_duplicate_target_ids(
    db, provider, plan_bundle, target, field
):
    context = context_for(plan_bundle)
    rows = (
        plan_bundle[target]
        if target == "paragraph_intent_tree"
        else plan_bundle["fine_logic_audit"][target]
    )
    rows[1][field] = rows[0][field]
    with pytest.raises(ValueError, match="unique"):
        architecture(db, context, provider, plan_bundle)


def full_source():
    return (
        "\\documentclass{article}\n\\begin{document}\n"
        + "Preserved prose. " * 900
        + "\nUnique old phrase.\n\\includegraphics{plot.pdf}\n\\label{sec:main}\nThe value is 0.42.\n"
        "\\appendix\nComplete appendix tail.\n\\end{document}\n"
    )


def test_full_manuscript_exact_edits_preserve_complete_input_and_feedback(db, provider):
    source = full_source()
    provider.response = {
        "edits": [
            {"old_text": "Unique old phrase.", "new_text": "Unique revised phrase."}
        ],
        "changes_made": ["Clarified the unique phrase"],
    }
    result = llm.section_revise(
        db=db,
        section="full_manuscript",
        content=source,
        review_feedback="r" * 6500 + "FEEDBACK_TAIL",
        evidence_text="e" * 21000 + "EVIDENCE_TAIL",
        full_manuscript=True,
    )
    assert result.revised_content == source.replace(
        "Unique old phrase.", "Unique revised phrase."
    )
    assert not result.reverted
    assert source in provider.prompts[0]
    assert (
        "FEEDBACK_TAIL" in provider.prompts[0]
        and "EVIDENCE_TAIL" in provider.prompts[0]
    )
    assert result.changes_made == ["Clarified the unique phrase"]
    assert result.manuscript_edits == provider.response["edits"]
    assert result.repair_deferred == []


def test_full_manuscript_tracks_finding_repairs_and_explicit_deferrals(db, provider):
    provider.response = {
        "edits": [
            {
                "old_text": "Unique old phrase.",
                "new_text": "Unique revised phrase.",
                "finding_id": "F1",
            }
        ],
        "changes_made": ["Clarified F1"],
        "repair_deferred": [
            {"finding_id": "F2", "reason": "Requires additional measured evidence"}
        ],
    }
    result = llm.section_revise(
        db=db,
        section="full_manuscript",
        content=full_source(),
        review_feedback='{"findings": [{"id": "F1"}, {"id": "F2"}]}',
        full_manuscript=True,
    )
    assert result.manuscript_edits == provider.response["edits"]
    assert result.repair_deferred == provider.response["repair_deferred"]


def test_full_manuscript_can_defer_all_findings_without_claiming_a_fix(db, provider):
    provider.response = {
        "edits": [],
        "changes_made": [],
        "repair_deferred": [{"finding_id": "F2", "reason": "Requires new evidence"}],
    }
    result = llm.section_revise(
        db=db,
        section="full_manuscript",
        content=full_source(),
        review_feedback="Fix F2",
        full_manuscript=True,
    )
    assert result.revised_content == full_source()
    assert result.manuscript_edits == []
    assert result.changes_made == []
    assert result.repair_deferred == provider.response["repair_deferred"]


@pytest.mark.parametrize(
    "response",
    [
        '{"edits": [',
        '{"edits": [], "edits": [], "changes_made": []}',
        '{"edits": [], "changes_made": NaN}',
        [],
        {"revised_content": "partial manuscript"},
        {"edits": [], "changes_made": []},
        {"edits": [{"old_text": "", "new_text": "new"}], "changes_made": ["change"]},
        {
            "edits": [{"old_text": "Preserved prose.", "new_text": "new"}],
            "changes_made": ["change"],
        },
        {
            "edits": [{"old_text": "absent", "new_text": "new"}],
            "changes_made": ["change"],
        },
        {
            "edits": [
                {"old_text": "Unique old phrase.", "new_text": "Unique old phrase."}
            ],
            "changes_made": ["change"],
        },
        {
            "edits": [{"old_text": "Unique old phrase.", "new_text": None}],
            "changes_made": ["change"],
        },
        {
            "edits": [
                {"old_text": "Unique old phrase.", "new_text": "changed", "position": 1}
            ],
            "changes_made": ["change"],
        },
        {
            "edits": [{"old_text": "Unique old phrase.", "new_text": "x" * 20000}],
            "changes_made": ["change"],
        },
        {
            "edits": [
                {"old_text": "Unique old phrase.", "new_text": "changed"},
                {"old_text": "old phrase.", "new_text": "changed"},
            ],
            "changes_made": ["change"],
        },
        {
            "edits": [{"old_text": "Unique old phrase.", "new_text": "changed"}],
            "changes_made": ["change"],
            "extra": True,
        },
        {
            "edits": [
                {
                    "old_text": "Unique old phrase.",
                    "new_text": "changed",
                    "finding_id": "",
                }
            ],
            "changes_made": ["change"],
        },
        {
            "edits": [],
            "changes_made": [],
            "repair_deferred": [{"finding_id": "F1", "reason": ""}],
        },
        {
            "edits": [],
            "changes_made": [],
            "repair_deferred": [{"finding_id": "F1", "reason": "Wait", "extra": True}],
        },
    ],
)
def test_full_manuscript_refuses_ambiguous_truncated_or_oversized_edits(
    db, provider, response
):
    provider.response = response
    with pytest.raises(ValueError):
        llm.section_revise(
            db=db,
            section="full_manuscript",
            content=full_source(),
            review_feedback="Fix",
            full_manuscript=True,
        )


@pytest.mark.parametrize(
    "old,new",
    [
        ("0.42", "0.43"),
        ("\\label{sec:main}", ""),
        ("\\includegraphics{plot.pdf}", "\\includegraphics{other.pdf}"),
        ("\\documentclass{article}", "\\documentclass{book}"),
    ],
)
def test_full_manuscript_reverts_damage_to_protected_material(db, provider, old, new):
    provider.response = {
        "edits": [{"old_text": old, "new_text": new}],
        "changes_made": ["Change"],
    }
    result = llm.section_revise(
        db=db,
        section="full_manuscript",
        content=full_source(),
        review_feedback="Fix",
        full_manuscript=True,
    )
    assert result.reverted
    assert result.revised_content == full_source()
    assert result.manuscript_edits == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("content", "x" * 250001),
        ("review_feedback", "x" * 100001),
        ("evidence_text", "x" * 100001),
        ("full_manuscript", "true"),
    ],
)
def test_full_manuscript_limits_fail_before_provider(db, provider, field, value):
    kwargs = {
        "content": full_source(),
        "review_feedback": "Fix",
        "full_manuscript": True,
        field: value,
    }
    with pytest.raises(ValueError):
        llm.section_revise(db=db, section="full_manuscript", **kwargs)
    assert provider.prompts == []


def test_section_default_prompt_and_response_remain_compatible(db, provider):
    provider.response = {"revised_content": "Revised text", "changes_made": ["Change"]}
    result = llm.section_revise(
        db=db, section="method", content="Original text", review_feedback="Fix"
    )
    assert result.revised_content == "Revised text"
    prompt = prompts.section_revise_prompt("method", "x" * 11000 + "TAIL", "Fix")
    assert "TAIL" not in prompt


def test_existing_primitive_schemas_expose_only_optional_extensions():
    revise = get_primitive_spec("section_revise").input_schema
    architecture = get_primitive_spec("writing_architecture").input_schema
    assert revise["properties"]["full_manuscript"]["default"] is False
    assert "full_manuscript" not in revise["required"]
    assert architecture["properties"]["manuscript_logic_context"]["type"] == "object"
    assert "manuscript_logic_context" not in architecture["required"]


def test_actual_tracked_backend_records_valid_plan_revision_and_blocked_plan(
    db, provider, plan_bundle, monkeypatch
):
    from research_harness.execution import harness
    from research_harness.execution.tracked import TrackedBackend
    from research_harness.provenance.recorder import ProvenanceRecorder

    monkeypatch.setattr(
        harness,
        "resolve_llm_config",
        lambda: SimpleNamespace(provider="codex", model="offline", api_key=""),
    )
    with db.connect() as conn:
        topic_id = conn.execute(
            "INSERT INTO topics(name,description) VALUES (?,?)",
            ("manuscript-modes", "Offline integration"),
        ).lastrowid
    recorder = ProvenanceRecorder(db)
    backend = TrackedBackend(harness.ResearchHarnessBackend(db), recorder)
    context = context_for(plan_bundle)
    provider.response = {
        "sections": [{"section": section} for section in context["sections"]],
        "manuscript_logic_bundle": plan_bundle,
    }
    plan = backend.execute(
        "writing_architecture",
        topic_id=topic_id,
        contributions="Frozen mechanism",
        manuscript_logic_context=context,
        _stage="write",
    )
    assert plan.success and plan.output.manuscript_logic_bundle == plan_bundle
    provider.response = {
        "edits": [
            {
                "old_text": "Unique old phrase.",
                "new_text": "Unique revised phrase.",
                "finding_id": "F1",
            }
        ],
        "changes_made": ["Clarified F1"],
    }
    revision = backend.execute(
        "section_revise",
        topic_id=topic_id,
        section="full_manuscript",
        content=full_source(),
        review_feedback='{"finding_id":"F1"}',
        full_manuscript=True,
        _stage="write",
    )
    assert (
        revision.success and revision.output.manuscript_edits[0]["finding_id"] == "F1"
    )
    provider.response = {"manuscript_logic_bundle": {"status": "pass"}}
    blocked = backend.execute(
        "writing_architecture",
        topic_id=topic_id,
        contributions="Frozen mechanism",
        manuscript_logic_context=context,
        _stage="write",
    )
    assert not blocked.success and "logic bundle" in blocked.error
    records = recorder.list_records(topic_id=topic_id)
    assert len(records) == 3
    assert sum(record.success for record in records) == 2
    assert all(
        record.stage == "write" and record.input_hash and record.output_hash
        for record in records
    )


@pytest.mark.parametrize(
    "new", ["New claim with 7 observations.", "\\cite{invented}", "\\input{other.tex}"]
)
def test_full_manuscript_rejects_new_protected_material(db, provider, new):
    provider.response = {
        "edits": [{"old_text": "Unique old phrase.", "new_text": new}],
        "changes_made": ["Introduced unsupported material"],
    }
    result = llm.section_revise(
        db=db,
        section="full_manuscript",
        content=full_source(),
        review_feedback="Fix",
        full_manuscript=True,
    )
    assert result.reverted and result.revised_content == full_source()


@pytest.mark.parametrize(
    "formula",
    [
        "$f(x)=x+y$",
        "$$f(x)=x+y$$",
        r"\(f(x)=x+y\)",
        r"\[f(x)=x+y\]",
        r"\begin{equation}f(x)=x+y\end{equation}",
        r"\begin{align*}f(x)&=x+y\end{align*}",
    ],
)
def test_full_manuscript_preserves_formula_contents(db, provider, formula):
    source = full_source().replace("Unique old phrase.", formula)
    provider.response = {
        "edits": [{"old_text": "x+y", "new_text": "x-y"}],
        "changes_made": ["Changed a formula"],
    }
    result = llm.section_revise(
        db=db,
        section="full_manuscript",
        content=source,
        review_feedback="Fix",
        full_manuscript=True,
    )
    assert result.reverted and result.revised_content == source


def test_an_oversized_manuscript_response_names_its_size():
    """A0114's writing_architecture died three times on "exceeds its JSON size limit",
    which says neither the size nor which of the two checks refused."""
    with pytest.raises(ValueError) as excinfo:
        llm._strict_manuscript_json("x" * 11, limit=10)
    assert "11 characters" in str(excinfo.value) and "10" in str(excinfo.value)
    with pytest.raises(ValueError, match="NoneType"):
        llm._strict_manuscript_json(None, limit=10)
