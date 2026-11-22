from __future__ import annotations

from research_harness._selfdev.manuscript_logic_gate import (
    CORE_CLAIM_CONTRACT_SCHEMA_VERSION,
    FINE_LOGIC_AUDIT_SCHEMA_VERSION,
    MANUSCRIPT_LOGIC_BUNDLE_SCHEMA_VERSION,
    evaluate_fine_logic_audit,
    evaluate_manuscript_logic_bundle,
)


def _valid_bundle() -> dict[str, object]:
    return {
        "schema_version": MANUSCRIPT_LOGIC_BUNDLE_SCHEMA_VERSION,
        "core_claim_contract": {
            "schema_version": CORE_CLAIM_CONTRACT_SCHEMA_VERSION,
            "paper_id": "eventtempo",
            "title": "EventTempo: Forecast-Origin-Safe Event State for Forecasting",
            "one_sentence_claim": (
                "EventTempo improves event-conditioned forecasting by compiling "
                "visible event evidence into forecast-origin-safe event states "
                "before it can revise a numerical forecast."
            ),
            "central_problem": (
                "Forecasting systems need to use external events without future "
                "leakage or harmful event-driven revisions."
            ),
            "paper_type": "original-research",
            "target_venue": "CCF-A",
            "allowed_focus": (
                "forecast-origin-safe event state",
                "target-window alignment",
                "rollback of harmful event revisions",
            ),
            "forbidden_focus": (
                "general multimodal forecasting survey",
                "open-ended agent workflow platform",
            ),
        },
        "argument_tree": {
            "root_claim": "forecast-origin-safe event states improve event-conditioned forecasting",
            "problems": [
                {
                    "problem_id": "p1",
                    "statement": "event evidence may be invisible at the forecast origin",
                    "contribution_id": "c1",
                    "evidence_ids": ["paper:1", "audit:forecast-origin"],
                    "section_ids": ["introduction", "method", "experiments"],
                },
                {
                    "problem_id": "p2",
                    "statement": "event impact windows may not align with target horizons",
                    "contribution_id": "c2",
                    "evidence_ids": ["paper:2", "table:event-window"],
                    "section_ids": ["method", "experiments"],
                },
                {
                    "problem_id": "p3",
                    "statement": "irrelevant or stale events can cause harmful revisions",
                    "contribution_id": "c3",
                    "evidence_ids": ["paper:3", "table:rollback"],
                    "section_ids": ["method", "experiments"],
                },
            ],
        },
        "term_registry": [
            {
                "term": "forecast-origin-safe event state",
                "definition": (
                    "An event representation containing only evidence visible at "
                    "the forecast origin."
                ),
                "first_use": "abstract",
                "allowed_aliases": ["event state"],
                "forbidden_aliases": ["safe event", "secure event"],
            },
            {
                "term": "target-window alignment",
                "definition": (
                    "The check that an event's plausible impact interval overlaps "
                    "the forecast horizon being revised."
                ),
                "first_use": "introduction",
                "allowed_aliases": ["window alignment"],
                "forbidden_aliases": [],
            },
            {
                "term": "rollback",
                "definition": "A control action that cancels harmful event-driven revisions.",
                "first_use": "method",
                "allowed_aliases": [],
                "forbidden_aliases": [],
            },
        ],
        "promise_realization_matrix": [
            {
                "promise": "avoid future event leakage",
                "made_in": "abstract",
                "realized_by": [
                    "method:state-construction",
                    "experiment:forecast-origin-audit",
                ],
                "evidence_ids": ["audit:forecast-origin"],
            },
            {
                "promise": "reduce harmful event revisions",
                "made_in": "introduction",
                "realized_by": ["method:rollback", "experiment:rollback-quality"],
                "evidence_ids": ["table:rollback"],
            },
        ],
        "paragraph_intent_tree": [
            {
                "section": "abstract",
                "paragraph_id": "abs-1",
                "intent": "state problem, method, and evidence without introducing side claims",
                "serves_claim": True,
                "allowed_terms": [
                    "forecast-origin-safe event state",
                    "target-window alignment",
                    "rollback",
                ],
            },
            {
                "section": "introduction",
                "paragraph_id": "intro-1",
                "intent": "motivate event-conditioned forecasting as a deployment risk",
                "serves_claim": True,
                "allowed_terms": ["forecast-origin-safe event state"],
            },
            {
                "section": "method",
                "paragraph_id": "method-1",
                "intent": "define event state construction and control actions",
                "serves_claim": True,
                "allowed_terms": [
                    "forecast-origin-safe event state",
                    "target-window alignment",
                    "rollback",
                ],
            },
        ],
        "fine_logic_audit": _valid_fine_logic_audit(),
    }


def _valid_fine_logic_audit() -> dict[str, object]:
    return {
        "schema_version": FINE_LOGIC_AUDIT_SCHEMA_VERSION,
        "argument_link_map": [
            {
                "claim_id": "c1",
                "claim": "Forecast-origin-safe event states reduce leakage risk.",
                "grounds": "Event evidence is filtered by forecast-origin visibility.",
                "evidence_ids": ["audit:forecast-origin"],
                "warrant": (
                    "A state cannot leak future events when every event token is "
                    "selected only from evidence visible at the forecast origin."
                ),
                "backing": "Forecast-origin audit enumerates visible event timestamps.",
                "qualifier": "for event-conditioned forecasting tasks with timestamped evidence",
                "rebuttal_or_alternative": (
                    "Static text fusion is weaker because it does not expose a "
                    "forecast-origin visibility check."
                ),
                "paragraph_ids": ["intro-2", "method-1"],
            },
            {
                "claim_id": "c2",
                "claim": "Rollback reduces harmful event-driven revisions.",
                "grounds": "Stale or irrelevant event states are canceled before update.",
                "evidence_ids": ["table:rollback"],
                "warrant": (
                    "Canceling revisions whose validation score drops prevents those "
                    "events from changing the final forecast."
                ),
                "backing": "Rollback ablation reports fewer harmful revisions.",
                "qualifier": "on evaluated event windows",
                "rebuttal_or_alternative": "Always-on event fusion remains as the negative control.",
                "paragraph_ids": ["method-1", "experiments-2"],
            },
        ],
        "assumption_warrant_table": [
            {
                "assumption_id": "a1",
                "assumption": "Event timestamps indicate when evidence became visible.",
                "why_needed": "The visibility warrant depends on a timestamp boundary.",
                "where_to_state": "method:state-construction",
                "backing_evidence_ids": ["audit:forecast-origin"],
                "risk_if_omitted": "Readers may not accept that future leakage is controlled.",
            }
        ],
        "claim_certainty_audit": [
            {
                "claim_id": "c1",
                "claim": "Forecast-origin-safe event states reduce leakage risk.",
                "evidence_strength": "strong",
                "allowed_certainty": "bounded",
                "actual_certainty": "bounded",
                "status": "ok",
                "required_scope": "event-conditioned forecasting tasks",
            },
            {
                "claim_id": "c2",
                "claim": "Rollback reduces harmful event-driven revisions.",
                "evidence_strength": "medium",
                "allowed_certainty": "bounded",
                "actual_certainty": "bounded",
                "status": "ok",
                "required_scope": "evaluated event windows",
            },
        ],
        "paragraph_flow_audit": [
            {
                "paragraph_id": "intro-1",
                "topic_sentence": "External events can improve forecasts only when they are visible.",
                "old_info_link": "event-conditioned forecasting",
                "new_stress_info": "forecast-origin visibility",
                "transition_relation": "problem-definition",
                "signal_word_valid": True,
                "chain": ["event use", "visibility risk", "state construction"],
                "status": "ok",
            },
            {
                "paragraph_id": "intro-2",
                "topic_sentence": "This visibility constraint motivates event states.",
                "old_info_link": "forecast-origin visibility",
                "new_stress_info": "event state construction",
                "transition_relation": "solution-introduction",
                "signal_word_valid": True,
                "chain": ["visibility risk", "event state", "evaluation"],
                "status": "ok",
            },
        ],
        "intro_logic_map": {
            "problem_relevance": "Forecasting deployments act on changing external events.",
            "problem_hardness": "Events can appear after the forecast origin or miss the target window.",
            "prior_shortcomings": "Static fusion and post-hoc event text do not enforce origin visibility.",
            "keen_insight": "Treat event evidence as a forecast-origin-safe state before forecast revision.",
            "technical_challenges": "Visibility, window alignment, and harmful revision rollback.",
            "validation_plan": "Leakage audit, alignment ablation, and rollback evaluation.",
            "assessment": "The paper reports safer event-conditioned forecasts on evaluated horizons.",
        },
        "figure_table_message_audit": [
            {
                "asset_id": "table:rollback",
                "asset_type": "table",
                "intended_message": "Rollback cancels harmful event-driven revisions.",
                "major_finding": "Rollback lowers harmful revision count in the ablation.",
                "supports_claim_ids": ["c2"],
                "evidence_ids": ["table:rollback"],
                "status": "ok",
            }
        ],
        "writing_defect_log": [],
    }


def test_manuscript_logic_gate_accepts_single_claim_logic_bundle() -> None:
    report = evaluate_manuscript_logic_bundle(_valid_bundle())

    assert report.status == "pass"
    assert report.blockers == ()
    assert report.metrics == {
        "problem_count": 3,
        "term_count": 3,
        "promise_count": 2,
        "paragraph_count": 3,
        "side_claim_count": 0,
        "argument_link_count": 2,
        "assumption_count": 1,
        "claim_certainty_count": 2,
        "paragraph_flow_count": 2,
        "figure_table_message_count": 1,
        "writing_defect_count": 0,
    }


def test_fine_logic_audit_report_can_be_embedded_in_paper_plan() -> None:
    report = evaluate_fine_logic_audit(_valid_fine_logic_audit())

    assert report.to_dict() == {
        "schema_version": "rh.manuscript.fine_logic_audit_report.v1",
        "status": "pass",
        "blockers": [],
        "warnings": [],
        "metrics": {
            "argument_link_count": 2,
            "assumption_count": 1,
            "claim_certainty_count": 2,
            "paragraph_flow_count": 2,
            "figure_table_message_count": 1,
            "writing_defect_count": 0,
        },
    }


def test_manuscript_logic_gate_rejects_eventtempo_style_drift() -> None:
    bundle = {
        **_valid_bundle(),
        "core_claim_contract": {
            **_valid_bundle()["core_claim_contract"],
            "one_sentence_claim": "",
            "allowed_focus": (
                "event-conditioned forecasting",
                "static text fusion",
                "LLM agents",
                "reflection",
                "causal augmentation",
                "event-conditioned evaluation",
            ),
        },
        "argument_tree": {
            "root_claim": "EventTempo is a dynamic event-state control framework",
            "problems": [
                *_valid_bundle()["argument_tree"]["problems"],  # type: ignore[index]
                {
                    "problem_id": "p4",
                    "statement": "agent reflection needs a memory workflow",
                    "contribution_id": "c4",
                    "evidence_ids": [],
                    "section_ids": ["introduction"],
                },
            ],
        },
        "term_registry": [
            *_valid_bundle()["term_registry"],  # type: ignore[misc]
            {
                "term": "mechanism drift",
                "definition": "",
                "first_use": "abstract",
                "allowed_aliases": [],
                "forbidden_aliases": [],
            },
            {
                "term": "safe event",
                "definition": "ambiguous shorthand",
                "first_use": "abstract",
                "allowed_aliases": [],
                "forbidden_aliases": [],
            },
        ],
        "promise_realization_matrix": [
            *_valid_bundle()["promise_realization_matrix"],  # type: ignore[misc]
            {
                "promise": "provide unified modeling of all event risks",
                "made_in": "abstract",
                "realized_by": [],
                "evidence_ids": [],
            },
        ],
        "paragraph_intent_tree": [
            *_valid_bundle()["paragraph_intent_tree"],  # type: ignore[misc]
            {
                "section": "introduction",
                "paragraph_id": "intro-2",
                "intent": "list all related hot terms",
                "serves_claim": False,
                "allowed_terms": ["LLM agents", "reflection", "causal augmentation"],
            },
        ],
    }

    report = evaluate_manuscript_logic_bundle(bundle)

    assert report.status == "block"
    assert "missing:core_claim_contract.one_sentence_claim" in report.blockers
    assert "too_many:core_claim_contract.allowed_focus" in report.blockers
    assert "too_many:argument_tree.problems" in report.blockers
    assert "missing:argument_tree.problem.p4.evidence_ids" in report.blockers
    assert "missing:term_registry.mechanism drift.definition" in report.blockers
    assert "undefined_or_forbidden:paragraph.intro-2.term.LLM agents" in report.blockers
    assert (
        "unrealized:promise.provide unified modeling of all event risks"
        in report.blockers
    )
    assert "side_claim:paragraph.intro-2" in report.blockers


def test_manuscript_logic_gate_rejects_claim_with_evidence_but_missing_warrant() -> (
    None
):
    fine_audit = {
        **_valid_fine_logic_audit(),
        "argument_link_map": [
            {
                **_valid_fine_logic_audit()["argument_link_map"][0],  # type: ignore[index]
                "warrant": "",
            }
        ],
    }
    bundle = {**_valid_bundle(), "fine_logic_audit": fine_audit}

    report = evaluate_manuscript_logic_bundle(bundle)

    assert report.status == "block"
    assert "missing:fine_logic.argument.c1.warrant" in report.blockers


def test_manuscript_logic_gate_rejects_overclaim_certainty_mismatch() -> None:
    fine_audit = {
        **_valid_fine_logic_audit(),
        "claim_certainty_audit": [
            {
                **_valid_fine_logic_audit()["claim_certainty_audit"][0],  # type: ignore[index]
                "evidence_strength": "weak",
                "allowed_certainty": "tentative",
                "actual_certainty": "strong",
                "status": "overclaim",
            }
        ],
    }
    bundle = {**_valid_bundle(), "fine_logic_audit": fine_audit}

    report = evaluate_manuscript_logic_bundle(bundle)

    assert report.status == "block"
    assert "overclaim:fine_logic.claim_certainty.c1" in report.blockers
    assert (
        "mismatch:fine_logic.claim_certainty.c1.actual_exceeds_allowed"
        in report.blockers
    )


def test_manuscript_logic_gate_rejects_intro_without_insight_or_hardness() -> None:
    fine_audit = {
        **_valid_fine_logic_audit(),
        "intro_logic_map": {
            **_valid_fine_logic_audit()["intro_logic_map"],  # type: ignore[arg-type]
            "problem_hardness": "",
            "keen_insight": "",
        },
    }
    bundle = {**_valid_bundle(), "fine_logic_audit": fine_audit}

    report = evaluate_manuscript_logic_bundle(bundle)

    assert report.status == "block"
    assert "missing:fine_logic.intro_logic_map.problem_hardness" in report.blockers
    assert "missing:fine_logic.intro_logic_map.keen_insight" in report.blockers


def test_manuscript_logic_gate_rejects_figure_without_major_finding() -> None:
    fine_audit = {
        **_valid_fine_logic_audit(),
        "figure_table_message_audit": [
            {
                **_valid_fine_logic_audit()["figure_table_message_audit"][0],  # type: ignore[index]
                "major_finding": "",
            }
        ],
    }
    bundle = {**_valid_bundle(), "fine_logic_audit": fine_audit}

    report = evaluate_manuscript_logic_bundle(bundle)

    assert report.status == "block"
    assert (
        "missing:fine_logic.figure_table.table:rollback.major_finding"
        in report.blockers
    )
