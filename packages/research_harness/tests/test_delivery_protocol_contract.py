from __future__ import annotations

import json
from pathlib import Path

from research_harness._selfdev.delivery_protocol import (
    build_delivery_evaluation_gate_profile,
    build_delivery_experiment_grounding_profile,
    build_delivery_presubmission_severity_gate_profile,
    build_delivery_rebuttal_readiness_gate_profile,
    build_delivery_result_to_claim_analysis_profile,
    build_delivery_skeleton_source_integrity_profile,
    build_domain_method_search_profile,
    build_experiment_to_claims_artifact_contracts,
    build_paper_profile_route,
    build_paper_plan_audit_package_artifact_contracts,
    build_rebuttal_camera_ready_artifact_contracts,
    build_topic_to_proposal_artifact_contracts,
    build_delivery_protocol_contract,
    build_delivery_paper_production_snapshot,
    evaluate_delivery_stage_readiness,
    plan_delivery_artifact_promotion,
    resolve_delivery_protocol_request,
    validate_delivery_artifact_payload,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
PROTOCOL_FIXTURE = (
    REPO_ROOT
    / "packages/research_harness/tests/fixtures/workflows/delivery_protocol.json"
)
PROTOCOL_DOC = REPO_ROOT / "docs/research-delivery-protocol.md"


def _fixture() -> dict[str, object]:
    return json.loads(PROTOCOL_FIXTURE.read_text(encoding="utf-8"))


def _valid_research_brief_payload() -> dict[str, object]:
    return {
        "schema_version": "rh.delivery.research_brief.v1",
        "recording_surface": "orchestrator_record_artifact",
        "public_surface": "none",
        "runtime_dependency": "none",
        "topic_statement": "Evidence-grounded paper writing",
        "target_venue": "workshop",
        "paper_type": "system",
        "scope_constraints": ["local private helper only"],
        "success_criteria": ["contract validates"],
        "seed_evidence": ["paper:p1"],
        "evidence_anchors": ["paper:p1"],
        "support_status": "seeded",
        "missing_evidence_warnings": [],
        "promotion_blockers": [],
    }


def _valid_paper_plan_payload() -> dict[str, object]:
    return {
        "schema_version": "rh.delivery.paper_plan.v1",
        "recording_surface": "orchestrator_record_artifact",
        "public_surface": "none",
        "runtime_dependency": "none",
        "core_claim_contract": {
            "schema_version": "rh.manuscript.core_claim_contract.v1",
            "one_sentence_claim": "Verifier-gated synthesis improves evidence retention.",
            "central_problem": "Long synthesis chains lose source provenance.",
            "paper_type": "system",
            "target_venue": "workshop",
            "allowed_focus": ["evidence retention", "source provenance"],
        },
        "argument_tree": {
            "root_claim": "Verifier-gated synthesis improves evidence retention.",
            "problems": [
                {
                    "problem_id": "p1",
                    "statement": "synthesis loses evidence links",
                    "contribution_id": "c1",
                    "evidence_ids": ["paper:p1"],
                    "section_ids": ["introduction", "method"],
                }
            ],
        },
        "term_registry": [
            {
                "term": "verifier-gated synthesis",
                "definition": "A synthesis process checked by a provenance verifier.",
                "first_use": "abstract",
                "allowed_aliases": [],
                "forbidden_aliases": [],
            }
        ],
        "promise_realization_matrix": [
            {
                "promise": "improve evidence retention",
                "made_in": "abstract",
                "realized_by": ["experiment:source-link-retention"],
                "evidence_ids": ["paper:p1"],
            }
        ],
        "paragraph_intent_tree": [
            {
                "section": "introduction",
                "paragraph_id": "intro-1",
                "intent": "motivate provenance loss as the central problem",
                "serves_claim": True,
                "allowed_terms": ["verifier-gated synthesis"],
            }
        ],
        "manuscript_logic_gate_report": {
            "schema_version": "rh.manuscript.logic_gate_report.v1",
            "status": "pass",
            "blockers": [],
        },
        "argument_link_map": [
            {
                "claim_id": "c1",
                "claim": "Verifier-gated synthesis improves evidence retention.",
                "grounds": "The workflow binds claims to source artifact ids.",
                "evidence_ids": ["paper:p1"],
                "warrant": "A claim with source-bound evidence is auditable.",
                "backing": "The provenance record links the claim to source artifacts.",
                "qualifier": "for evaluated synthesis artifacts",
                "rebuttal_or_alternative": "Ungated synthesis may still be faster but less auditable.",
                "paragraph_ids": ["intro-1"],
            }
        ],
        "assumption_warrant_table": [
            {
                "assumption_id": "a1",
                "assumption": "Source artifact ids resolve to reviewable evidence.",
                "why_needed": "The audit depends on evidence being inspectable.",
                "where_to_state": "method",
                "backing_evidence_ids": ["paper:p1"],
                "risk_if_omitted": "Readers cannot evaluate the provenance claim.",
            }
        ],
        "claim_certainty_audit": [
            {
                "claim_id": "c1",
                "claim": "Verifier-gated synthesis improves evidence retention.",
                "evidence_strength": "bounded",
                "allowed_certainty": "bounded",
                "actual_certainty": "bounded",
                "status": "ok",
                "required_scope": "evaluated synthesis artifacts",
            }
        ],
        "paragraph_flow_audit": [
            {
                "paragraph_id": "intro-1",
                "topic_sentence": "Evidence retention is the central review risk.",
                "old_info_link": "evidence-bound writing",
                "new_stress_info": "source provenance",
                "transition_relation": "problem-definition",
                "signal_word_valid": True,
                "chain": ["evidence retention", "source provenance"],
                "status": "ok",
            }
        ],
        "intro_logic_map": {
            "problem_relevance": "Long synthesis workflows lose source links.",
            "problem_hardness": "Evidence chains cross many generated artifacts.",
            "prior_shortcomings": "Ungated drafting can preserve prose without provenance.",
            "keen_insight": "Gate paper plans before prose generation.",
            "technical_challenges": "Claim binding, artifact source integrity, and review readiness.",
            "validation_plan": "Contract tests and provenance-linked section drafting.",
            "assessment": "The paper plan is ready only after fine-logic checks pass.",
        },
        "figure_table_message_audit": [
            {
                "asset_id": "fig:workflow",
                "asset_type": "figure",
                "intended_message": "The verifier binds claims before drafting.",
                "major_finding": "Claim evidence links are visible in the paper plan.",
                "supports_claim_ids": ["c1"],
                "evidence_ids": ["paper:p1"],
                "status": "ok",
            }
        ],
        "writing_defect_log": [],
        "fine_logic_audit_report": {
            "schema_version": "rh.manuscript.fine_logic_audit_report.v1",
            "status": "pass",
            "blockers": [],
        },
        "paper_profile": {
            "schema_version": "rh.delivery.paper_profile.v1",
            "discipline": "ai",
            "research_type": "empirical-ml",
            "study_design": "benchmark",
            "paper_type": "method",
            "target_venue": "workshop",
            "domain_profile": "domain-writing-stem",
            "method_route": "domain-method-search-stem",
            "reporting_map": "ml-empirical-method",
            "evidence_rule": "ml-benchmark",
            "venue_profile": "workshop",
        },
        "domain_writing_profile": {
            "profile_id": "STEM_ENGINEERING_WRITING_PROFILE",
            "domain_skill": "domain-writing-stem",
            "claim_boundary": "tested benchmark datasets",
            "evidence_shape": "task dataset metric baseline ablation",
        },
        "claims_evidence_matrix": [{"claim_id": "c1", "paper_ids": ["p1"]}],
        "section_plan": [{"section": "Introduction", "claim_ids": ["c1"]}],
        "figure_table_plan": [{"kind": "figure", "source_artifact_id": "a1"}],
        "unsupported_claims": [],
        "reviewer_risks": ["baseline comparison may need more detail"],
        "source_artifacts": ["artifact:proposal"],
        "evidence_anchors": ["paper:p1"],
        "support_status": "evidence_bound",
        "missing_evidence_warnings": [],
        "promotion_blockers": [],
    }


def test_delivery_protocol_fixture_preserves_rh_primary_boundary() -> None:
    fixture = _fixture()

    assert fixture["schema_version"] == "rh.delivery_protocol.v1"
    assert fixture["source_of_truth"] == "research_harness"
    assert fixture["public_surface"] == "none"
    assert fixture["runtime_dependency"] == "none"
    assert fixture["boundaries"] == {
        "adds_public_tool": False,
        "adds_cli_command": False,
        "adds_http_route": False,
        "adds_python_facade_method": False,
        "adds_storage_schema": False,
        "uses_network": False,
        "uses_real_llm": False,
    }


def test_delivery_protocol_contract_maps_all_required_artifacts() -> None:
    contract = build_delivery_protocol_contract(_fixture())

    assert contract.status == "success"
    assert contract.missing == ()
    assert contract.entry_modes == ("protocol_call", "human_in_loop_call")
    assert contract.boundary_violations == ()

    by_artifact = {record.artifact: record for record in contract.records}
    assert tuple(by_artifact) == (
        "RESEARCH_BRIEF",
        "IDEA_REPORT",
        "RESEARCH_PROPOSAL",
        "EVALUATION",
        "EXPERIMENT_GOAL",
        "EXPERIMENT_PLAN",
        "IMPACT_REPORT",
        "CLAIMS_FROM_RESULTS",
        "PAPER_PLAN",
        "AUTO_REVIEW",
        "PRESUBMISSION_AUDIT",
        "PAPER_PACKAGE",
        "REBUTTAL_PACKAGE",
    )
    assert by_artifact["RESEARCH_BRIEF"].stage == "init"
    assert by_artifact["EXPERIMENT_PLAN"].stage == "experiment"
    assert by_artifact["PAPER_PLAN"].gate == "write_readiness"
    assert by_artifact["RESEARCH_BRIEF"].owner_skill == "research-init"
    assert by_artifact["RESEARCH_PROPOSAL"].owner_skill == "gap-analysis"
    assert by_artifact["EXPERIMENT_PLAN"].owner_skill == "evidence-gating"
    assert by_artifact["PAPER_PLAN"].owner_skill == "section-drafting"
    assert by_artifact["PRESUBMISSION_AUDIT"].owner_skill == "paper-writing"
    assert by_artifact["PAPER_PACKAGE"].owner_skill == "publication-pack"
    assert by_artifact["REBUTTAL_PACKAGE"].owner_skill == "publication-pack"
    assert by_artifact["REBUTTAL_PACKAGE"].recording_surface == (
        "orchestrator_record_artifact"
    )


def test_delivery_protocol_contract_reports_missing_required_entries() -> None:
    fixture = _fixture()
    incomplete = {
        **fixture,
        "entry_modes": ["protocol_call"],
        "artifact_records": list(fixture["artifact_records"])[:-1],
    }

    contract = build_delivery_protocol_contract(incomplete)

    assert contract.status == "error"
    assert "entry_mode:human_in_loop_call" in contract.missing
    assert "artifact:REBUTTAL_PACKAGE" in contract.missing


def test_delivery_protocol_contract_rejects_missing_owner_skill() -> None:
    fixture = _fixture()
    first_record = {**fixture["artifact_records"][0], "owner_skill": ""}
    invalid = {
        **fixture,
        "artifact_records": [first_record, *fixture["artifact_records"][1:]],
    }

    contract = build_delivery_protocol_contract(invalid)

    assert contract.status == "error"
    assert "owner_skill:RESEARCH_BRIEF" in contract.missing


def test_delivery_protocol_doc_matches_fixture_artifacts() -> None:
    fixture = _fixture()
    doc = PROTOCOL_DOC.read_text(encoding="utf-8")

    for artifact in fixture["required_artifacts"]:
        assert artifact in doc

    for mode in fixture["entry_modes"]:
        assert mode in doc

    assert "The protocol has no external runtime dependency" in doc
    assert "These names are RH artifact conventions, not new database tables" in doc


def test_delivery_protocol_call_resolves_explicit_artifact_to_owner_gate() -> None:
    decision = resolve_delivery_protocol_request(
        _fixture(),
        entry_mode="protocol_call",
        request="PAPER_PLAN",
        artifact_states={
            "RESEARCH_PROPOSAL": "active",
            "EVALUATION": "active",
        },
    )

    assert decision.status == "ready_to_run"
    assert decision.action == "run_owner_skill_and_record"
    assert decision.artifact == "PAPER_PLAN"
    assert decision.stage == "write"
    assert decision.gate == "write_readiness"
    assert decision.owner_skill == "section-drafting"
    assert decision.recording_surface == "orchestrator_record_artifact"
    assert decision.artifact_state == "missing"
    assert decision.blockers == ()


def test_delivery_protocol_call_reuses_active_artifact() -> None:
    decision = resolve_delivery_protocol_request(
        _fixture(),
        entry_mode="protocol_call",
        request="PRESUBMISSION_AUDIT",
        artifact_states={
            "RESEARCH_PROPOSAL": "active",
            "EVALUATION": "active",
            "PAPER_PLAN": "active",
            "AUTO_REVIEW": "active",
            "PRESUBMISSION_AUDIT": "active",
        },
    )

    assert decision.status == "satisfied"
    assert decision.action == "reuse_recorded_artifact"
    assert decision.artifact == "PRESUBMISSION_AUDIT"
    assert decision.blockers == ()


def test_delivery_human_in_loop_call_infers_nearest_missing_artifact() -> None:
    decision = resolve_delivery_protocol_request(
        _fixture(),
        entry_mode="human_in_loop_call",
        request="Can we start writing the manuscript now?",
        artifact_states={
            "RESEARCH_PROPOSAL": "active",
            "EVALUATION": "active",
        },
    )

    assert decision.status == "ready_to_run"
    assert decision.inferred_from == "human_in_loop_call"
    assert decision.artifact == "PAPER_PLAN"
    assert decision.owner_skill == "section-drafting"


def test_delivery_protocol_blocks_package_when_prerequisites_are_missing() -> None:
    decision = resolve_delivery_protocol_request(
        _fixture(),
        entry_mode="protocol_call",
        request="PAPER_PACKAGE",
        artifact_states={"PAPER_PLAN": "active"},
    )

    assert decision.status == "blocked"
    assert decision.action == "satisfy_prerequisites"
    assert decision.artifact == "PAPER_PACKAGE"
    assert "missing:RESEARCH_PROPOSAL" in decision.blockers
    assert "missing:EVALUATION" in decision.blockers
    assert "missing:AUTO_REVIEW" in decision.blockers
    assert "missing:PRESUBMISSION_AUDIT" in decision.blockers


def test_delivery_protocol_rejects_unknown_human_request() -> None:
    decision = resolve_delivery_protocol_request(
        _fixture(),
        entry_mode="human_in_loop_call",
        request="Make the system magical.",
        artifact_states={},
    )

    assert decision.status == "error"
    assert decision.action == "clarify_request"
    assert decision.artifact == ""
    assert "unknown_protocol_artifact" in decision.blockers


def test_topic_to_proposal_contracts_define_required_payloads() -> None:
    contracts = build_topic_to_proposal_artifact_contracts()

    assert tuple(contracts) == (
        "RESEARCH_BRIEF",
        "IDEA_REPORT",
        "RESEARCH_PROPOSAL",
        "EVALUATION",
    )

    for artifact, contract in contracts.items():
        assert contract.artifact == artifact
        assert contract.schema_version.startswith("rh.delivery.")
        assert contract.artifact_role == "advisory_compiled_view"
        assert "evidence_anchors" in contract.required_fields
        assert "support_status" in contract.required_fields
        assert "missing_evidence_warnings" in contract.required_fields
        assert "promotion_blockers" in contract.required_fields
        assert contract.owner_skill
        assert contract.stage
        assert contract.gate


def test_topic_to_proposal_contracts_keep_go_no_go_gate_strict() -> None:
    contracts = build_topic_to_proposal_artifact_contracts()
    evaluation = contracts["EVALUATION"]

    assert evaluation.gate == "go_no_go"
    assert "decision" in evaluation.required_fields
    assert "minimum_evidence_to_advance" in evaluation.required_fields
    assert "unresolved_objections" in evaluation.required_fields
    assert "submission_readiness" in evaluation.forbidden_claims
    assert "novelty_proof" in evaluation.forbidden_claims


def test_topic_to_proposal_contracts_do_not_create_public_surface_or_runtime() -> None:
    contracts = build_topic_to_proposal_artifact_contracts()

    for contract in contracts.values():
        assert contract.public_surface == "none"
        assert contract.runtime_dependency == "none"
        assert contract.recording_surface == "orchestrator_record_artifact"


def test_experiment_to_claims_contracts_define_required_payloads() -> None:
    contracts = build_experiment_to_claims_artifact_contracts()

    assert tuple(contracts) == (
        "EXPERIMENT_GOAL",
        "EXPERIMENT_PLAN",
        "IMPACT_REPORT",
        "CLAIMS_FROM_RESULTS",
    )

    for artifact, contract in contracts.items():
        assert contract.artifact == artifact
        assert contract.schema_version.startswith("rh.delivery.")
        assert contract.artifact_role == "advisory_compiled_view"
        assert "evidence_anchors" in contract.required_fields
        assert "support_status" in contract.required_fields
        assert "result_state" in contract.required_fields
        assert "missing_evidence_warnings" in contract.required_fields
        assert "promotion_blockers" in contract.required_fields
        assert "planned_as_observed_result" in contract.forbidden_claims


def test_experiment_plan_contract_requires_falsifiable_design_fields() -> None:
    contracts = build_experiment_to_claims_artifact_contracts()
    experiment_plan = contracts["EXPERIMENT_PLAN"]

    for field in (
        "hypothesis",
        "baselines",
        "metrics",
        "acceptance_criteria",
        "failure_criteria",
        "stop_rules",
    ):
        assert field in experiment_plan.required_fields
    assert "observed_result" in experiment_plan.forbidden_claims


def test_claims_from_results_contract_requires_strength_labels() -> None:
    contracts = build_experiment_to_claims_artifact_contracts()
    claims = contracts["CLAIMS_FROM_RESULTS"]

    assert claims.owner_skill == "claim-extraction"
    assert "claim_strength" in claims.required_fields
    assert "source_result_artifacts" in claims.required_fields
    assert "competing_evidence" in claims.required_fields
    assert "unsupported_contribution_claim" in claims.forbidden_claims


def test_paper_plan_audit_package_contracts_define_required_payloads() -> None:
    contracts = build_paper_plan_audit_package_artifact_contracts()

    assert tuple(contracts) == (
        "PAPER_PLAN",
        "AUTO_REVIEW",
        "PRESUBMISSION_AUDIT",
        "PAPER_PACKAGE",
    )

    for artifact, contract in contracts.items():
        assert contract.artifact == artifact
        assert contract.schema_version.startswith("rh.delivery.")
        assert contract.artifact_role == "advisory_compiled_view"
        assert "evidence_anchors" in contract.required_fields
        assert "source_artifacts" in contract.required_fields
        assert "promotion_blockers" in contract.required_fields
        assert "chat_only_output" in contract.forbidden_claims
        assert contract.public_surface == "none"
        assert contract.runtime_dependency == "none"


def test_paper_plan_contract_requires_claims_evidence_matrix() -> None:
    contracts = build_paper_plan_audit_package_artifact_contracts()
    paper_plan = contracts["PAPER_PLAN"]

    assert paper_plan.owner_skill == "section-drafting"
    assert "paper_profile" in paper_plan.required_fields
    assert "domain_writing_profile" in paper_plan.required_fields
    assert "core_claim_contract" in paper_plan.required_fields
    assert "argument_tree" in paper_plan.required_fields
    assert "term_registry" in paper_plan.required_fields
    assert "promise_realization_matrix" in paper_plan.required_fields
    assert "paragraph_intent_tree" in paper_plan.required_fields
    assert "manuscript_logic_gate_report" in paper_plan.required_fields
    assert "argument_link_map" in paper_plan.required_fields
    assert "assumption_warrant_table" in paper_plan.required_fields
    assert "claim_certainty_audit" in paper_plan.required_fields
    assert "paragraph_flow_audit" in paper_plan.required_fields
    assert "intro_logic_map" in paper_plan.required_fields
    assert "figure_table_message_audit" in paper_plan.required_fields
    assert "writing_defect_log" in paper_plan.required_fields
    assert "fine_logic_audit_report" in paper_plan.required_fields
    assert "claims_evidence_matrix" in paper_plan.required_fields
    assert "section_plan" in paper_plan.required_fields
    assert "figure_table_plan" in paper_plan.required_fields
    assert "unsupported_claims" in paper_plan.required_fields


def test_paper_profile_route_links_domain_method_reporting_and_evidence() -> None:
    route = build_paper_profile_route(
        discipline="biomedical",
        research_type="intervention-study",
        study_design="rct",
        paper_type="empirical",
        target_venue="clinical-journal",
    )

    assert route.status == "success"
    assert route.schema_version == "rh.delivery.paper_profile.v1"
    assert route.domain_skill == "domain-writing-biomedical"
    assert route.domain_profile == "BIOMEDICAL_WRITING_PROFILE"
    assert route.method_route == "biomedical-method-search"
    assert route.reporting_map == "biomedical-clinical"
    assert route.evidence_rule == "intervention-and-quasi-experiment"
    assert route.venue_profile == "clinical-journal"
    assert route.blockers == ()
    assert route.public_surface == "none"
    assert route.runtime_dependency == "none"


def test_paper_profile_route_rejects_ambiguous_or_stem_defaulted_inputs() -> None:
    ambiguous = build_paper_profile_route(
        discipline="",
        research_type="survey-correlational",
        study_design="cross_sectional",
        paper_type="empirical",
    )
    assert ambiguous.status == "blocked"
    assert "missing:discipline" in ambiguous.blockers
    assert "no_silent_stem_default" in ambiguous.blockers

    mismatch = build_paper_profile_route(
        discipline="social_science",
        research_type="empirical-ml",
        study_design="benchmark",
        paper_type="method",
    )
    assert mismatch.status == "blocked"
    assert "route_mismatch:empirical_ml_requires_stem_family" in mismatch.blockers


def test_domain_method_search_profile_routes_ml_baseline_discovery() -> None:
    profile = build_domain_method_search_profile(
        discipline="ai",
        research_type="empirical-ml",
        study_design="benchmark",
        paper_type="method",
    )

    assert profile.status == "success"
    assert profile.schema_version == "rh.delivery.domain_method_search_profile.v1"
    assert profile.domain_skill == "domain-writing-stem"
    assert profile.method_route == "domain-method-search-stem"
    assert profile.search_route == "ml-baseline-search"
    assert "recent_sota_reverse_search" in profile.search_strategies
    assert "code_available_baseline_search" in profile.search_strategies
    assert "citation_network_baseline_search" in profile.search_strategies
    assert "mandatory_interpretable_baseline" in profile.method_requirements
    assert "no_data_leakage" in profile.method_requirements
    assert "dataset" in profile.baseline_anchor_fields
    assert "source_table_or_figure" in profile.evidence_table_schema
    assert "no_silent_stem_default" in profile.excluded_defaults
    assert profile.public_surface == "none"
    assert profile.runtime_dependency == "none"
    assert profile.blockers == ()


def test_domain_method_search_profile_routes_psychology_without_ml_defaults() -> None:
    profile = build_domain_method_search_profile(
        discipline="psychology",
        research_type="survey-correlational",
        study_design="cross_sectional",
        paper_type="empirical",
    )

    assert profile.status == "success"
    assert profile.domain_skill == "domain-writing-social-science"
    assert profile.method_route == "psychology-method-search"
    assert profile.search_route == "psychology-variable-scale-search"
    assert "variable_combination_search" in profile.search_strategies
    assert "scale_provenance_search" in profile.search_strategies
    assert "meta_analysis_positioning" in profile.search_strategies
    assert "no_cross_sectional_causal_language" in profile.method_requirements
    assert "scale_reliability_validity" in profile.method_requirements
    assert "effect_size" in profile.baseline_anchor_fields
    assert "ml-baseline-search" in profile.excluded_defaults
    assert "github-code-baseline-required" in profile.excluded_defaults


def test_domain_method_search_profile_routes_education_intervention_path() -> None:
    profile = build_domain_method_search_profile(
        discipline="education",
        research_type="intervention-study",
        study_design="quasi_experiment",
        paper_type="intervention",
        target_venue="APER",
    )

    assert profile.status == "success"
    assert profile.domain_skill == "domain-writing-social-science"
    assert profile.method_route == "education-method-search-path-2"
    assert profile.search_route == "education-intervention-effect-search"
    assert "intervention_effect_anchor_search" in profile.search_strategies
    assert "construct_measure_search" in profile.search_strategies
    assert "effect_size_required" in profile.method_requirements
    assert "treatment_fidelity_required" in profile.method_requirements
    assert "construct_measure" in profile.baseline_anchor_fields
    assert "effect_size" in profile.evidence_table_schema


def test_domain_method_search_profile_rejects_ambiguous_route() -> None:
    profile = build_domain_method_search_profile(
        discipline="",
        research_type="empirical-ml",
        study_design="benchmark",
        paper_type="method",
    )

    assert profile.status == "blocked"
    assert "paper_profile:missing:discipline" in profile.blockers
    assert "paper_profile:no_silent_stem_default" in profile.blockers
    assert "missing_domain_method_search_profile" in profile.blockers


def test_evaluation_gate_profile_routes_ml_full_experiment_when_ready() -> None:
    profile = build_delivery_evaluation_gate_profile(
        discipline="ai",
        research_type="empirical-ml",
        study_design="benchmark",
        paper_type="method",
        problem_anchor_status="frozen",
        baseline_mode="github-replication",
        paper_access_status="verified",
        fatal_flaws=(),
        feasibility_risks={"compute": "green", "data": "green"},
        scorecard={"Higher": 8, "Faster": 8, "Broader": 6},
    )

    assert profile.status == "success"
    assert profile.schema_version == "rh.delivery.evaluation_gate_profile.v1"
    assert profile.evaluation_route == "ml-ai-data-evaluation"
    assert profile.problem_anchor_required is True
    assert profile.baseline_mode == "github-replication"
    assert profile.paper_access_status == "verified"
    assert profile.verdict_options == (
        "strong-accept",
        "accept-revisions",
        "pending-pilot",
        "reject",
    )
    assert profile.decision == "advance_full_experiment"
    assert profile.pilot_required is False
    assert profile.public_surface == "none"
    assert profile.runtime_dependency == "none"
    assert profile.blockers == ()


def test_evaluation_gate_profile_routes_psy_edu_framing_pilot() -> None:
    profile = build_delivery_evaluation_gate_profile(
        discipline="education",
        research_type="intervention-study",
        study_design="quasi_experiment",
        paper_type="intervention",
        problem_anchor_status="frozen",
        baseline_mode="extract-only",
        paper_access_status="verified",
        fatal_flaws=(),
        feasibility_risks={"compute": "green", "data": "green"},
        scorecard={
            "Theoretical Framing": 4,
            "Construct Validity": 6,
            "Mechanism Specificity": 6,
            "Population & Setting": 6,
        },
    )

    assert profile.status == "success"
    assert profile.evaluation_route == "psy-edu-framing-evaluation"
    assert "Theoretical Framing" in profile.scoring_axes
    assert "literature_deepening" in profile.pilot_catalog
    assert "construct_theorization" in profile.pilot_catalog
    assert profile.decision == "run_signal_pilot"
    assert profile.pilot_required is True
    assert "soft_gate:psy_edu_axes_1_3_below_5" in profile.warnings
    assert profile.blockers == ()


def test_evaluation_gate_profile_rejects_critical_fatal_flaw() -> None:
    profile = build_delivery_evaluation_gate_profile(
        discipline="psychology",
        research_type="survey-correlational",
        study_design="cross_sectional",
        paper_type="empirical",
        problem_anchor_status="frozen",
        baseline_mode="extract-only",
        paper_access_status="verified",
        fatal_flaws=("P1:CRITICAL",),
        feasibility_risks={"data": "green"},
        scorecard={"Theoretical Framing": 3, "Construct Validity": 5},
    )

    assert profile.status == "blocked"
    assert profile.decision == "reject_direction"
    assert "critical_fatal_flaw" in profile.blockers
    assert profile.pilot_required is False


def test_evaluation_gate_profile_blocks_missing_problem_and_access() -> None:
    profile = build_delivery_evaluation_gate_profile(
        discipline="ai",
        research_type="empirical-ml",
        study_design="benchmark",
        paper_type="method",
        problem_anchor_status="draft",
        baseline_mode="github-replication",
        paper_access_status="blocked",
        fatal_flaws=(),
        feasibility_risks={"compute": "green"},
        scorecard={"Higher": 8, "Faster": 8},
    )

    assert profile.status == "blocked"
    assert profile.decision == "block_until_problem_anchor_and_access"
    assert "problem_anchor_not_frozen" in profile.blockers
    assert "paper_access_blocked" in profile.blockers
    assert "PROBLEM_ANCHOR" in profile.required_artifacts
    assert "baseline_access_table" in profile.required_artifacts


def test_experiment_grounding_profile_routes_ml_plan_code_review_and_impact() -> None:
    profile = build_delivery_experiment_grounding_profile(
        discipline="ai",
        research_type="empirical-ml",
        study_design="benchmark",
        paper_type="method",
        experiment_goal_status="aligned",
        experiment_plan_status="profile-aligned",
        paper_profile_status="recorded",
        variable_grounding_status="verified",
        codebook_status="verified",
        evidence_reporting_status="aligned",
        pre_deploy_code_review_status="pass",
        deploy_blocker_count=0,
        impact_report_status="claim-bound",
        impact_claim_binding_status="verified",
        result_state="completed",
        missing_variables=(),
    )

    assert profile.status == "success"
    assert profile.schema_version == "rh.delivery.experiment_grounding_profile.v1"
    assert profile.experiment_route == "ml-ai-data-experiment-grounding"
    assert profile.domain_skill == "domain-writing-stem"
    assert "PAPER_PROFILE" in profile.required_artifacts
    assert "EXPERIMENT_GOAL" in profile.required_artifacts
    assert "EXPERIMENT_PLAN" in profile.required_artifacts
    assert "IMPACT_REPORT" in profile.required_artifacts
    assert "dataset_baseline_metric_alignment" in profile.plan_alignment_checks
    assert "data_split_and_leakage" in profile.code_review_bug_classes
    assert "metric_formula" in profile.code_review_bug_classes
    assert "seeds_and_split_reporting" in profile.reporting_requirements
    assert "expected_vs_actual_result_table" in profile.impact_report_claim_checks
    assert profile.decision == "ready_for_claim_extraction"
    assert profile.public_surface == "none"
    assert profile.runtime_dependency == "none"
    assert profile.blockers == ()


def test_experiment_grounding_profile_blocks_variable_and_code_review_gaps() -> None:
    profile = build_delivery_experiment_grounding_profile(
        discipline="psychology",
        research_type="survey-correlational",
        study_design="cross_sectional",
        paper_type="empirical",
        experiment_goal_status="aligned",
        experiment_plan_status="profile-aligned",
        paper_profile_status="recorded",
        variable_grounding_status="missing",
        codebook_status="missing",
        evidence_reporting_status="aligned",
        pre_deploy_code_review_status="blocked",
        deploy_blocker_count=2,
        impact_report_status="not-started",
        impact_claim_binding_status="not-started",
        result_state="planned",
        missing_variables=("self_efficacy_score", "learning_anxiety"),
    )

    assert profile.status == "blocked"
    assert profile.experiment_route == "social-science-experiment-grounding"
    assert "construct_variable_scale_grounding" in profile.plan_alignment_checks
    assert "variable_grounding_missing:self_efficacy_score" in profile.blockers
    assert "variable_grounding_missing:learning_anxiety" in profile.blockers
    assert "codebook_unverified" in profile.blockers
    assert "pre_deploy_code_review_blocked" in profile.blockers
    assert "deploy_blockers:2" in profile.blockers
    assert profile.decision == "block_deploy_until_code_review_passes"


def test_experiment_grounding_profile_blocks_unbound_completed_results() -> None:
    profile = build_delivery_experiment_grounding_profile(
        discipline="education",
        research_type="intervention-study",
        study_design="quasi_experiment",
        paper_type="intervention",
        experiment_goal_status="aligned",
        experiment_plan_status="profile-aligned",
        paper_profile_status="recorded",
        variable_grounding_status="verified",
        codebook_status="verified",
        evidence_reporting_status="aligned",
        pre_deploy_code_review_status="pass",
        deploy_blocker_count=0,
        impact_report_status="missing",
        impact_claim_binding_status="missing",
        result_state="completed",
        missing_variables=(),
    )

    assert profile.status == "blocked"
    assert profile.experiment_route == "education-intervention-grounding"
    assert "outcome_measure_fidelity" in profile.plan_alignment_checks
    assert "impact_report_missing" in profile.blockers
    assert "impact_report_claim_binding_missing" in profile.blockers
    assert "claim_strength_boundary" in profile.impact_report_claim_checks
    assert profile.decision == "block_claims_until_impact_report_bound"


def test_result_to_claim_analysis_profile_routes_claim_safe_ml_results() -> None:
    profile = build_delivery_result_to_claim_analysis_profile(
        discipline="ai",
        research_type="empirical-ml",
        study_design="benchmark",
        paper_type="method",
        result_state="completed",
        experiment_grounding_status="pass",
        impact_report_status="claim-bound",
        claims_from_results_status="drafted",
        result_artifact_status="verified",
        expected_vs_actual_status="verified",
        statistical_reporting_status="verified",
        practical_significance_status="verified",
        baseline_delta_status="verified",
        robustness_status="verified",
        negative_results_status="recorded",
        competing_evidence_status="addressed",
        claim_strength="B_empirical_strong",
        unsupported_claim_ids=(),
        overclaimed_claim_ids=(),
        missing_result_artifact_ids=(),
    )

    assert profile.status == "success"
    assert profile.schema_version == "rh.delivery.result_to_claim_analysis_profile.v1"
    assert profile.analysis_route == "ml-ai-data-result-to-claim-analysis"
    assert profile.domain_skill == "domain-writing-stem"
    assert profile.claim_strength == "B_empirical_strong"
    assert "A_confirmed" in profile.evidence_tiers
    assert "F_unsupported_or_blocked" in profile.evidence_tiers
    assert "CLAIMS_FROM_RESULTS" in profile.required_artifacts
    assert "relative_delta_table" in profile.required_artifacts
    assert "statistical_summary" in profile.required_artifacts
    assert "expected_vs_actual_result_table" in profile.analysis_checks
    assert "statistical_and_practical_significance_separated" in profile.analysis_checks
    assert "baseline_delta_check" in profile.analysis_checks
    assert "universal_or_mechanism_proof_language" in profile.disallowed_claim_language
    assert profile.decision == "ready_for_claim_safe_writing"
    assert profile.public_surface == "none"
    assert profile.runtime_dependency == "none"
    assert profile.blockers == ()


def test_result_to_claim_analysis_profile_blocks_overclaims_and_missing_results() -> (
    None
):
    profile = build_delivery_result_to_claim_analysis_profile(
        discipline="psychology",
        research_type="survey-correlational",
        study_design="cross_sectional",
        paper_type="empirical",
        result_state="completed",
        experiment_grounding_status="pass",
        impact_report_status="claim-bound",
        claims_from_results_status="drafted",
        result_artifact_status="missing",
        expected_vs_actual_status="missing",
        statistical_reporting_status="missing",
        practical_significance_status="missing",
        baseline_delta_status="not-applicable",
        robustness_status="missing",
        negative_results_status="missing",
        competing_evidence_status="unaddressed",
        claim_strength="A_confirmed",
        unsupported_claim_ids=("C3",),
        overclaimed_claim_ids=("C1", "C2"),
        missing_result_artifact_ids=("result-table-2",),
    )

    assert profile.status == "blocked"
    assert profile.analysis_route == "social-science-result-to-claim-analysis"
    assert profile.maximum_allowed_claim_strength == "C_empirical_limited"
    assert "result_artifact_missing" in profile.blockers
    assert "expected_vs_actual_missing" in profile.blockers
    assert "statistical_reporting_missing" in profile.blockers
    assert "practical_significance_missing" in profile.blockers
    assert "negative_results_missing" in profile.blockers
    assert "competing_evidence_unaddressed" in profile.blockers
    assert "unsupported_claim:C3" in profile.blockers
    assert "overclaimed_claim:C1" in profile.blockers
    assert "overclaimed_claim:C2" in profile.blockers
    assert "missing_result_artifact:result-table-2" in profile.blockers
    assert (
        "claim_strength_exceeds_boundary:A_confirmed>C_empirical_limited"
        in profile.blockers
    )
    assert "causal_effect_language" in profile.disallowed_claim_language
    assert profile.decision == "block_claims_until_result_analysis_passes"
    assert profile.public_surface == "none"
    assert profile.runtime_dependency == "none"


def test_skeleton_source_integrity_profile_routes_complete_empirical_paper() -> None:
    profile = build_delivery_skeleton_source_integrity_profile(
        discipline="ai",
        research_type="empirical-ml",
        study_design="benchmark",
        paper_type="method",
        skeleton_status="complete",
        source_trace_status="verified",
        logic_chain_status="consistent",
        claims_evidence_matrix_status="verified",
        source_artifact_inventory_status="verified",
        citation_integrity_status="verified",
        bib_doi_verification_status="verified",
        figure_table_reference_status="verified",
        missing_section_groups=(),
        stub_section_groups=(),
        missing_source_trace_claims=(),
        dangling_citation_keys=(),
        unverified_bib_entries=(),
        dangling_table_refs=(),
        missing_figure_assets=(),
        target_venue="workshop",
    )

    assert profile.status == "success"
    assert profile.schema_version == "rh.delivery.skeleton_source_integrity_profile.v1"
    assert profile.integrity_route == "default-empirical-skeleton-source-integrity"
    assert profile.domain_skill == "domain-writing-stem"
    assert profile.required_section_groups == (
        "Introduction",
        "Related Work or Literature Review",
        "Methods or Approach",
        "Results or Findings",
        "Discussion",
        "Conclusion",
    )
    assert "PAPER_PLAN" in profile.required_artifacts
    assert "Claims-Evidence Matrix" in profile.required_artifacts
    assert "source_artifacts" in profile.required_artifacts
    assert "main_tex_or_manuscript_source" in profile.required_artifacts
    assert "refs_bib_or_citation_registry" in profile.required_artifacts
    assert "section_group_completeness" in profile.skeleton_checks
    assert "non_empty_section_body" in profile.skeleton_checks
    assert "claim_to_source_trace" in profile.source_trace_checks
    assert "logic_skeleton_cell_trace" in profile.source_trace_checks
    assert "cite_key_to_verified_bib_entry" in profile.citation_checks
    assert "doi_or_primary_metadata_verified" in profile.bib_metadata_checks
    assert profile.decision == "ready_for_presubmission_audit"
    assert profile.public_surface == "none"
    assert profile.runtime_dependency == "none"
    assert profile.blockers == ()


def test_skeleton_source_integrity_profile_blocks_trace_and_citation_gaps() -> None:
    profile = build_delivery_skeleton_source_integrity_profile(
        discipline="psychology",
        research_type="survey-correlational",
        study_design="cross_sectional",
        paper_type="empirical",
        skeleton_status="missing",
        source_trace_status="missing",
        logic_chain_status="broken",
        claims_evidence_matrix_status="missing",
        source_artifact_inventory_status="stale",
        citation_integrity_status="dangling",
        bib_doi_verification_status="failed",
        figure_table_reference_status="missing",
        missing_section_groups=("Methods or Approach",),
        stub_section_groups=("Discussion",),
        missing_source_trace_claims=("claim:construct-validity",),
        dangling_citation_keys=("smith2024scale",),
        unverified_bib_entries=("lee2025measurement",),
        dangling_table_refs=("tab:constructs",),
        missing_figure_assets=("figures/path-diagram.pdf",),
    )

    assert profile.status == "blocked"
    assert profile.integrity_route == "social-science-skeleton-source-integrity"
    assert "skeleton_missing:Methods or Approach" in profile.blockers
    assert "skeleton_stub:Discussion" in profile.blockers
    assert "source_trace_missing:claim:construct-validity" in profile.blockers
    assert "logic_chain_broken" in profile.blockers
    assert "claims_evidence_matrix_missing" in profile.blockers
    assert "source_artifact_inventory_stale" in profile.blockers
    assert "citation_dangling:smith2024scale" in profile.blockers
    assert "bib_doi_verification_failed:lee2025measurement" in profile.blockers
    assert "table_ref_dangling:tab:constructs" in profile.blockers
    assert "figure_asset_missing:figures/path-diagram.pdf" in profile.blockers
    assert "construct_operationalization_trace" in profile.source_trace_checks
    assert profile.decision == "block_package_until_source_integrity_passes"


def test_presubmission_audit_contract_requires_submission_gates() -> None:
    contracts = build_paper_plan_audit_package_artifact_contracts()
    audit = contracts["PRESUBMISSION_AUDIT"]

    for field in (
        "citation_integrity",
        "final_bundle_quality",
        "provenance_summary",
        "figure_table_quality",
        "package_readiness",
    ):
        assert field in audit.required_fields
    assert "submission_ready_without_qa" in audit.forbidden_claims


def test_paper_package_contract_requires_recorded_components() -> None:
    contracts = build_paper_plan_audit_package_artifact_contracts()
    package = contracts["PAPER_PACKAGE"]

    assert package.owner_skill == "publication-pack"
    assert "component_artifact_ids" in package.required_fields
    assert "missing_required_components" in package.required_fields
    assert "qa_checks" in package.required_fields
    assert "unrecorded_chat_output" in package.forbidden_claims


def test_rebuttal_camera_ready_contracts_define_required_payloads() -> None:
    contracts = build_rebuttal_camera_ready_artifact_contracts()

    assert tuple(contracts) == ("REBUTTAL_PACKAGE",)
    rebuttal = contracts["REBUTTAL_PACKAGE"]

    assert rebuttal.schema_version == "rh.delivery.rebuttal_package.v1"
    assert rebuttal.artifact_role == "advisory_compiled_view"
    assert rebuttal.owner_skill == "publication-pack"
    assert rebuttal.gate == "response_readiness"
    for field in (
        "reviewer_comments",
        "response_evidence",
        "revision_deltas",
        "camera_ready_replay",
        "final_package_delta",
        "source_artifacts",
        "evidence_anchors",
        "promotion_blockers",
    ):
        assert field in rebuttal.required_fields


def test_rebuttal_contract_forbids_unrecorded_responses() -> None:
    rebuttal = build_rebuttal_camera_ready_artifact_contracts()["REBUTTAL_PACKAGE"]

    assert "unrecorded_reviewer_response" in rebuttal.forbidden_claims
    assert "chat_only_output" in rebuttal.forbidden_claims
    assert "submission_ready_without_qa" in rebuttal.forbidden_claims
    assert rebuttal.public_surface == "none"
    assert rebuttal.runtime_dependency == "none"


def test_presubmission_severity_gate_blocks_critical_findings() -> None:
    profile = build_delivery_presubmission_severity_gate_profile(
        target="paper-presubmission",
        critical_count=1,
        major_count=2,
        minor_count=4,
        integrity_gate_status="pass",
        skeleton_source_integrity_status="pass",
        final_bundle_quality_status="pass",
        unresolved_critical_findings=("contribution does not map to Section 3",),
        integrity_failures=(),
    )

    assert profile.status == "blocked"
    assert profile.schema_version == "rh.delivery.presubmission_severity_gate.v1"
    assert profile.review_target == "paper-presubmission"
    assert profile.severity_taxonomy == ("CRITICAL", "MAJOR", "MINOR")
    assert profile.required_artifacts == (
        "PRESUBMISSION_AUDIT",
        "AUTO_REVIEW",
        "SKELETON_SOURCE_INTEGRITY_PROFILE",
        "final_bundle_quality_report",
        "citation_integrity",
        "figure_table_quality",
        "provenance_summary",
    )
    assert "critical_findings:1" in profile.blockers
    assert "critical_finding:contribution does not map to Section 3" in profile.blockers
    assert "severity_assignment_follows_taxonomy" in profile.integrity_checks
    assert "quoted_text_present_in_source" in profile.integrity_checks
    assert profile.decision == "block_submission_until_critical_fixed"
    assert profile.public_surface == "none"
    assert profile.runtime_dependency == "none"


def test_presubmission_severity_gate_allows_submission_when_clean() -> None:
    profile = build_delivery_presubmission_severity_gate_profile(
        target="paper-presubmission",
        critical_count=0,
        major_count=1,
        minor_count=3,
        integrity_gate_status="pass",
        skeleton_source_integrity_status="pass",
        final_bundle_quality_status="pass",
        unresolved_critical_findings=(),
        integrity_failures=(),
    )

    assert profile.status == "success"
    assert profile.critical_count == 0
    assert profile.decision == "ready_for_publication_pack"
    assert profile.blockers == ()


def test_rebuttal_readiness_gate_blocks_uncovered_or_unprovenanced_issues() -> None:
    profile = build_delivery_rebuttal_readiness_gate_profile(
        issue_board_status="complete",
        response_letter_status="drafted",
        revision_plan_status="missing",
        provenance_gate_status="failed",
        commitment_gate_status="failed",
        coverage_gate_status="failed",
        external_review_status="not-run",
        unresolved_issue_ids=("R1-C2", "R2-C1"),
        orphan_commitment_ids=("R1-C2-edit",),
        unprovenanced_response_ids=("R2-C1-sentence-3",),
        pending_user_input_ids=("R3-C4",),
    )

    assert profile.status == "blocked"
    assert profile.schema_version == "rh.delivery.rebuttal_readiness_gate.v1"
    assert profile.required_artifacts == (
        "REBUTTAL_PACKAGE",
        "ISSUE_BOARD",
        "RESPONSE_LETTER",
        "REVISION_PLAN",
        "response_evidence",
        "revision_deltas",
        "camera_ready_replay",
    )
    assert profile.issue_status_options == (
        "answered",
        "deferred_intentionally",
        "needs_user_input",
    )
    assert "revision_plan_missing" in profile.blockers
    assert "coverage_missing:R1-C2" in profile.blockers
    assert "coverage_missing:R2-C1" in profile.blockers
    assert "orphan_commitment:R1-C2-edit" in profile.blockers
    assert "unprovenanced_response:R2-C1-sentence-3" in profile.blockers
    assert "needs_user_input:R3-C4" in profile.blockers
    assert "no_orphan_commitments" in profile.commitment_checks
    assert "every_factual_sentence_has_source" in profile.provenance_checks
    assert "every_reviewer_concern_resolved" in profile.coverage_checks
    assert profile.decision == "block_rebuttal_until_gates_pass"
    assert profile.public_surface == "none"
    assert profile.runtime_dependency == "none"


def test_delivery_payload_validator_accepts_complete_private_payload() -> None:
    payload = _valid_paper_plan_payload()

    result = validate_delivery_artifact_payload("PAPER_PLAN", payload)

    assert result.status == "success"
    assert result.artifact == "PAPER_PLAN"
    assert result.schema_version == "rh.delivery.paper_plan.v1"
    assert result.missing_fields == ()
    assert result.forbidden_claim_hits == ()
    assert result.boundary_violations == ()


def test_delivery_payload_validator_reports_missing_required_fields() -> None:
    payload = {
        "schema_version": "rh.delivery.evaluation.v1",
        "recording_surface": "orchestrator_record_artifact",
        "public_surface": "none",
        "runtime_dependency": "none",
        "decision": "blocked",
        "decision_rationale": "Need more evidence before proposal promotion.",
    }

    result = validate_delivery_artifact_payload("EVALUATION", payload)

    assert result.status == "error"
    assert "minimum_evidence_to_advance" in result.missing_fields
    assert "unresolved_objections" in result.missing_fields
    assert "evidence_anchors" in result.missing_fields
    assert "promotion_blockers" in result.missing_fields


def test_delivery_payload_validator_reports_forbidden_claim_flags() -> None:
    payload = {
        "schema_version": "rh.delivery.rebuttal_package.v1",
        "recording_surface": "orchestrator_record_artifact",
        "public_surface": "none",
        "runtime_dependency": "none",
        "reviewer_comments": [{"reviewer": "R1", "comment_id": "r1c1"}],
        "response_evidence": [{"comment_id": "r1c1", "artifact_id": "a1"}],
        "revision_deltas": [{"section": "Results", "artifact_id": "a2"}],
        "camera_ready_replay": {"status": "pending"},
        "final_package_delta": {"changed_artifacts": ["a2"]},
        "source_artifacts": ["artifact:paper_package"],
        "evidence_anchors": ["claim:c1"],
        "support_status": "partially_supported",
        "missing_evidence_warnings": [],
        "promotion_blockers": [],
        "flags": ["unrecorded_reviewer_response"],
        "claim_flags": {"submission_ready_without_qa": True},
    }

    result = validate_delivery_artifact_payload("REBUTTAL_PACKAGE", payload)

    assert result.status == "error"
    assert "unrecorded_reviewer_response" in result.forbidden_claim_hits
    assert "submission_ready_without_qa" in result.forbidden_claim_hits


def test_delivery_payload_validator_enforces_private_recording_boundaries() -> None:
    payload = {
        "schema_version": "rh.delivery.research_brief.v1",
        "recording_surface": "chat_only",
        "public_surface": "mcp",
        "runtime_dependency": "external_runtime",
        "topic_statement": "Evidence-grounded paper writing",
        "target_venue": "workshop",
        "paper_type": "system",
        "scope_constraints": ["local private helper only"],
        "success_criteria": ["contract validates"],
        "seed_evidence": ["paper:p1"],
        "evidence_anchors": ["paper:p1"],
        "support_status": "seeded",
        "missing_evidence_warnings": [],
        "promotion_blockers": [],
    }

    result = validate_delivery_artifact_payload("RESEARCH_BRIEF", payload)

    assert result.status == "error"
    assert result.boundary_violations == (
        "recording_surface",
        "public_surface",
        "runtime_dependency",
    )


def test_delivery_payload_validator_rejects_schema_version_mismatch() -> None:
    payload = {
        "schema_version": "rh.delivery.paper_package.v0",
        "recording_surface": "orchestrator_record_artifact",
        "public_surface": "none",
        "runtime_dependency": "none",
        "component_artifact_ids": ["draft:1", "bundle:1"],
        "missing_required_components": [],
        "qa_checks": [{"name": "citation", "status": "passed"}],
        "publication_pack_artifact": "publication_pack:1",
        "final_bundle_artifact": "final_bundle:1",
        "source_artifacts": ["draft_pack:1"],
        "evidence_anchors": ["paper:p1"],
        "support_status": "evidence_bound",
        "missing_evidence_warnings": [],
        "promotion_blockers": [],
    }

    result = validate_delivery_artifact_payload("PAPER_PACKAGE", payload)

    assert result.status == "error"
    assert result.boundary_violations == ("schema_version",)


def test_delivery_payload_validator_rejects_unknown_artifact() -> None:
    result = validate_delivery_artifact_payload(
        "UNKNOWN_ARTIFACT",
        {
            "recording_surface": "orchestrator_record_artifact",
            "public_surface": "none",
            "runtime_dependency": "none",
        },
    )

    assert result.status == "error"
    assert result.artifact == "UNKNOWN_ARTIFACT"
    assert result.boundary_violations == ("unknown_artifact",)


def test_delivery_promotion_planner_builds_dry_run_record_intent() -> None:
    plan = plan_delivery_artifact_promotion(
        _fixture(),
        entry_mode="protocol_call",
        request="RESEARCH_BRIEF",
        payload=_valid_research_brief_payload(),
        artifact_states={},
    )

    assert plan.status == "ready_to_record"
    assert plan.dry_run is True
    assert plan.action == "record_artifact_intent"
    assert plan.recording_surface == "orchestrator_record_artifact"
    assert plan.artifact == "RESEARCH_BRIEF"
    assert plan.owner_skill == "research-init"
    assert plan.stage == "init"
    assert plan.gate == "topic_readiness"
    assert plan.payload_schema_version == "rh.delivery.research_brief.v1"
    assert plan.payload_summary == {
        "required_field_count": 10,
        "evidence_anchor_count": 1,
        "source_artifact_count": 0,
        "promotion_blocker_count": 0,
        "missing_evidence_warning_count": 0,
    }
    assert plan.validation_status == "success"
    assert plan.blockers == ()


def test_delivery_promotion_planner_blocks_invalid_payload() -> None:
    payload = {
        **_valid_research_brief_payload(),
        "public_surface": "mcp",
    }

    plan = plan_delivery_artifact_promotion(
        _fixture(),
        entry_mode="protocol_call",
        request="RESEARCH_BRIEF",
        payload=payload,
        artifact_states={},
    )

    assert plan.status == "blocked"
    assert plan.action == "repair_payload"
    assert plan.validation_status == "error"
    assert "boundary:public_surface" in plan.blockers


def test_delivery_promotion_planner_blocks_protocol_prerequisites() -> None:
    payload = _valid_paper_plan_payload()

    plan = plan_delivery_artifact_promotion(
        _fixture(),
        entry_mode="protocol_call",
        request="PAPER_PLAN",
        payload=payload,
        artifact_states={},
    )

    assert plan.status == "blocked"
    assert plan.action == "satisfy_prerequisites"
    assert plan.validation_status == "success"
    assert "missing:RESEARCH_PROPOSAL" in plan.blockers
    assert "missing:EVALUATION" in plan.blockers


def test_delivery_stage_readiness_reports_satisfied_active_artifact() -> None:
    readiness = evaluate_delivery_stage_readiness(
        _fixture(),
        entry_mode="protocol_call",
        request="RESEARCH_BRIEF",
        payload=_valid_research_brief_payload(),
        artifact_states={"RESEARCH_BRIEF": "active"},
    )

    assert readiness.status == "satisfied"
    assert readiness.action == "reuse_recorded_artifact"
    assert readiness.artifact == "RESEARCH_BRIEF"
    assert readiness.owner_skill == "research-init"
    assert readiness.recording_surface == "orchestrator_record_artifact"
    assert readiness.validation_status == "success"
    assert readiness.blockers == ()


def test_delivery_stage_readiness_reports_ready_to_advance() -> None:
    readiness = evaluate_delivery_stage_readiness(
        _fixture(),
        entry_mode="protocol_call",
        request="RESEARCH_BRIEF",
        payload=_valid_research_brief_payload(),
        artifact_states={},
    )

    assert readiness.status == "ready_to_advance"
    assert readiness.action == "record_artifact_intent"
    assert readiness.artifact == "RESEARCH_BRIEF"
    assert readiness.stage == "init"
    assert readiness.gate == "topic_readiness"
    assert readiness.validation_status == "success"
    assert readiness.promotion_status == "ready_to_record"
    assert readiness.blockers == ()


def test_delivery_stage_readiness_blocks_invalid_payload() -> None:
    readiness = evaluate_delivery_stage_readiness(
        _fixture(),
        entry_mode="protocol_call",
        request="RESEARCH_BRIEF",
        payload={
            **_valid_research_brief_payload(),
            "runtime_dependency": "external_runtime",
        },
        artifact_states={},
    )

    assert readiness.status == "blocked"
    assert readiness.action == "repair_payload"
    assert readiness.validation_status == "error"
    assert readiness.promotion_status == "blocked"
    assert "boundary:runtime_dependency" in readiness.blockers


def test_delivery_stage_readiness_blocks_missing_prerequisites() -> None:
    readiness = evaluate_delivery_stage_readiness(
        _fixture(),
        entry_mode="protocol_call",
        request="PAPER_PLAN",
        payload=_valid_paper_plan_payload(),
        artifact_states={},
    )

    assert readiness.status == "blocked"
    assert readiness.action == "satisfy_prerequisites"
    assert readiness.validation_status == "success"
    assert readiness.promotion_status == "blocked"
    assert "missing:RESEARCH_PROPOSAL" in readiness.blockers
    assert "missing:EVALUATION" in readiness.blockers


def test_delivery_paper_production_snapshot_identifies_next_ready_artifact() -> None:
    snapshot = build_delivery_paper_production_snapshot(
        _fixture(),
        artifact_states={"RESEARCH_BRIEF": "active"},
        payloads={
            "IDEA_REPORT": {
                "schema_version": "rh.delivery.idea_report.v1",
                "recording_surface": "orchestrator_record_artifact",
                "public_surface": "none",
                "runtime_dependency": "none",
                "observed_problem": "Writing plans drift from evidence.",
                "candidate_opportunity": "Protocol-bound paper production.",
                "in_domain_evidence": ["paper:p1"],
                "cross_topic_analogies": [],
                "novelty_risks": ["needs stronger baseline positioning"],
                "evidence_anchors": ["paper:p1"],
                "support_status": "seeded",
                "missing_evidence_warnings": [],
                "promotion_blockers": [],
            }
        },
    )

    assert snapshot.status == "in_progress"
    assert snapshot.next_artifact == "IDEA_REPORT"
    assert snapshot.next_action == "record_artifact_intent"
    assert snapshot.summary["satisfied"] == 1
    assert snapshot.summary["ready_to_advance"] == 1
    assert snapshot.summary["blocked"] == 11
    assert snapshot.records[0].artifact == "RESEARCH_BRIEF"
    assert snapshot.records[0].status == "satisfied"
    assert snapshot.records[1].artifact == "IDEA_REPORT"
    assert snapshot.records[1].status == "ready_to_advance"
    assert snapshot.blockers == ()


def test_delivery_paper_production_snapshot_reports_missing_payload_blocker() -> None:
    snapshot = build_delivery_paper_production_snapshot(
        _fixture(),
        artifact_states={"RESEARCH_BRIEF": "active"},
        payloads={},
    )

    assert snapshot.status == "blocked"
    assert snapshot.next_artifact == ""
    assert snapshot.next_action == "provide_payload"
    assert snapshot.summary["satisfied"] == 1
    assert snapshot.summary["ready_to_advance"] == 0
    assert "missing_payload:IDEA_REPORT" in snapshot.blockers


def test_delivery_paper_production_snapshot_reports_complete_state() -> None:
    active_states = {
        artifact: "active" for artifact in _fixture()["required_artifacts"]
    }

    snapshot = build_delivery_paper_production_snapshot(
        _fixture(),
        artifact_states=active_states,
        payloads={},
    )

    assert snapshot.status == "complete"
    assert snapshot.next_artifact == ""
    assert snapshot.next_action == "none"
    assert snapshot.summary["satisfied"] == len(active_states)
    assert snapshot.summary["blocked"] == 0
    assert snapshot.blockers == ()
