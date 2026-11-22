"""Private research delivery protocol checks for RH self-development."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


REQUIRED_ENTRY_MODES = ("protocol_call", "human_in_loop_call")
REQUIRED_ARTIFACTS = (
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
REQUIRED_FALSE_BOUNDARIES = (
    "adds_public_tool",
    "adds_cli_command",
    "adds_http_route",
    "adds_python_facade_method",
    "adds_storage_schema",
    "uses_network",
    "uses_real_llm",
)

ACTIVE_ARTIFACT_STATES = ("active", "current", "present", "ready", "recorded")

PAPER_PROFILE_REQUIRED_FIELDS = ("discipline", "research_type", "study_design")
STEM_DISCIPLINES = (
    "ai",
    "computer_science",
    "cs",
    "data",
    "ecology",
    "engineering",
    "environmental_science",
    "ml",
    "physical_science",
    "stem",
    "systems",
)
# Ecology/environmental science writes like STEM (IMRaD + statistics) but
# must never inherit ML-baseline or clinical search defaults.
ECOLOGY_DISCIPLINES = ("ecology", "environmental_science")
BIOMEDICAL_DISCIPLINES = (
    "biomedical",
    "clinical",
    "life_science",
    "medical",
    "medicine",
    "public_health",
)
SOCIAL_SCIENCE_DISCIPLINES = (
    "communication",
    "economics",
    "education",
    "edu",
    "political_science",
    "psychology",
    "psy",
    "social_science",
    "sociology",
)
HUMANITIES_DISCIPLINES = (
    "archive",
    "art_history",
    "cultural_studies",
    "history",
    "humanities",
    "literary_studies",
    "philosophy",
)
LAW_POLICY_DISCIPLINES = (
    "governance",
    "law",
    "law_policy",
    "policy",
    "regulation",
)
ML_RESEARCH_TYPES = ("empirical_ml", "system_benchmark")
EDUCATION_DISCIPLINES = ("education", "edu")
PSYCHOLOGY_DISCIPLINES = ("psychology", "psy")

PROTOCOL_PREREQUISITES: Mapping[str, tuple[str, ...]] = {
    "IDEA_REPORT": ("RESEARCH_BRIEF",),
    "RESEARCH_PROPOSAL": ("IDEA_REPORT",),
    "EVALUATION": ("RESEARCH_PROPOSAL",),
    "EXPERIMENT_GOAL": ("RESEARCH_PROPOSAL", "EVALUATION"),
    "EXPERIMENT_PLAN": ("EXPERIMENT_GOAL", "EVALUATION"),
    "IMPACT_REPORT": ("EXPERIMENT_PLAN",),
    "CLAIMS_FROM_RESULTS": ("IMPACT_REPORT",),
    "PAPER_PLAN": ("RESEARCH_PROPOSAL", "EVALUATION"),
    "AUTO_REVIEW": ("PAPER_PLAN",),
    "PRESUBMISSION_AUDIT": ("PAPER_PLAN", "AUTO_REVIEW"),
    "PAPER_PACKAGE": (
        "RESEARCH_PROPOSAL",
        "EVALUATION",
        "PAPER_PLAN",
        "AUTO_REVIEW",
        "PRESUBMISSION_AUDIT",
    ),
    "REBUTTAL_PACKAGE": ("PAPER_PACKAGE",),
}

HUMAN_REQUEST_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("rebuttal", "response", "reviewer response", "camera-ready"), "REBUTTAL_PACKAGE"),
    (("submit", "submission", "publication", "package"), "PAPER_PACKAGE"),
    (("audit", "ready", "presubmission"), "PRESUBMISSION_AUDIT"),
    (("review", "critique", "check"), "AUTO_REVIEW"),
    (("write", "writing", "manuscript", "paper"), "PAPER_PLAN"),
    (("experiment", "baseline", "metric", "evaluation plan"), "EXPERIMENT_PLAN"),
    (("claim", "result", "impact"), "CLAIMS_FROM_RESULTS"),
    (("proposal", "direction"), "RESEARCH_PROPOSAL"),
    (("idea", "gap", "opportunity"), "IDEA_REPORT"),
    (("brief", "scope", "topic", "venue"), "RESEARCH_BRIEF"),
)

TOPIC_TO_PROPOSAL_PAYLOADS: Mapping[str, Mapping[str, Any]] = {
    "RESEARCH_BRIEF": {
        "schema_version": "rh.delivery.research_brief.v1",
        "stage": "init",
        "gate": "topic_readiness",
        "owner_skill": "research-init",
        "required_fields": (
            "topic_statement",
            "target_venue",
            "paper_type",
            "scope_constraints",
            "success_criteria",
            "seed_evidence",
            "evidence_anchors",
            "support_status",
            "missing_evidence_warnings",
            "promotion_blockers",
        ),
        "forbidden_claims": (
            "submission_readiness",
            "novelty_proof",
            "result_claim",
        ),
    },
    "IDEA_REPORT": {
        "schema_version": "rh.delivery.idea_report.v1",
        "stage": "analyze",
        "gate": "opportunity_evidence",
        "owner_skill": "gap-analysis",
        "required_fields": (
            "observed_problem",
            "candidate_opportunity",
            "in_domain_evidence",
            "cross_topic_analogies",
            "novelty_risks",
            "evidence_anchors",
            "support_status",
            "missing_evidence_warnings",
            "promotion_blockers",
        ),
        "forbidden_claims": (
            "submission_readiness",
            "novelty_proof",
            "observed_result",
        ),
    },
    "RESEARCH_PROPOSAL": {
        "schema_version": "rh.delivery.research_proposal.v1",
        "stage": "propose",
        "gate": "proposal_readiness",
        "owner_skill": "gap-analysis",
        "required_fields": (
            "selected_direction",
            "research_questions",
            "baseline_expectations",
            "assumptions",
            "validation_plan_summary",
            "evidence_boundary",
            "evidence_anchors",
            "support_status",
            "missing_evidence_warnings",
            "promotion_blockers",
        ),
        "forbidden_claims": (
            "submission_readiness",
            "novelty_proof",
            "observed_result",
        ),
    },
    "EVALUATION": {
        "schema_version": "rh.delivery.evaluation.v1",
        "stage": "propose",
        "gate": "go_no_go",
        "owner_skill": "evidence-gating",
        "required_fields": (
            "decision",
            "decision_rationale",
            "minimum_evidence_to_advance",
            "unresolved_objections",
            "evidence_anchors",
            "support_status",
            "missing_evidence_warnings",
            "promotion_blockers",
        ),
        "forbidden_claims": (
            "submission_readiness",
            "novelty_proof",
            "observed_result",
        ),
    },
}

EXPERIMENT_TO_CLAIMS_PAYLOADS: Mapping[str, Mapping[str, Any]] = {
    "EXPERIMENT_GOAL": {
        "schema_version": "rh.delivery.experiment_goal.v1",
        "stage": "experiment",
        "gate": "experiment_scope",
        "owner_skill": "evidence-gating",
        "required_fields": (
            "target_claim",
            "hypothesis",
            "question",
            "scope",
            "result_state",
            "evidence_anchors",
            "support_status",
            "missing_evidence_warnings",
            "promotion_blockers",
        ),
        "forbidden_claims": (
            "planned_as_observed_result",
            "observed_result",
            "unsupported_contribution_claim",
        ),
    },
    "EXPERIMENT_PLAN": {
        "schema_version": "rh.delivery.experiment_plan.v1",
        "stage": "experiment",
        "gate": "experiment_readiness",
        "owner_skill": "evidence-gating",
        "required_fields": (
            "hypothesis",
            "baselines",
            "metrics",
            "acceptance_criteria",
            "failure_criteria",
            "stop_rules",
            "ablation_plan",
            "risk_controls",
            "result_state",
            "evidence_anchors",
            "support_status",
            "missing_evidence_warnings",
            "promotion_blockers",
        ),
        "forbidden_claims": (
            "planned_as_observed_result",
            "observed_result",
            "unsupported_contribution_claim",
        ),
    },
    "IMPACT_REPORT": {
        "schema_version": "rh.delivery.impact_report.v1",
        "stage": "experiment",
        "gate": "result_claim_alignment",
        "owner_skill": "evidence-gating",
        "required_fields": (
            "source_result_artifacts",
            "observations",
            "limitations",
            "negative_results",
            "claim_implications",
            "result_state",
            "evidence_anchors",
            "support_status",
            "missing_evidence_warnings",
            "promotion_blockers",
        ),
        "forbidden_claims": (
            "planned_as_observed_result",
            "unsupported_contribution_claim",
            "submission_readiness",
        ),
    },
    "CLAIMS_FROM_RESULTS": {
        "schema_version": "rh.delivery.claims_from_results.v1",
        "stage": "analyze",
        "gate": "evidence_strength",
        "owner_skill": "claim-extraction",
        "required_fields": (
            "source_result_artifacts",
            "claims",
            "claim_strength",
            "competing_evidence",
            "limitations",
            "result_state",
            "evidence_anchors",
            "support_status",
            "missing_evidence_warnings",
            "promotion_blockers",
        ),
        "forbidden_claims": (
            "planned_as_observed_result",
            "unsupported_contribution_claim",
            "submission_readiness",
        ),
    },
}

PAPER_PLAN_AUDIT_PACKAGE_PAYLOADS: Mapping[str, Mapping[str, Any]] = {
    "PAPER_PLAN": {
        "schema_version": "rh.delivery.paper_plan.v1",
        "stage": "write",
        "gate": "write_readiness",
        "owner_skill": "section-drafting",
        "required_fields": (
            "paper_profile",
            "domain_writing_profile",
            "core_claim_contract",
            "argument_tree",
            "term_registry",
            "promise_realization_matrix",
            "paragraph_intent_tree",
            "manuscript_logic_gate_report",
            "argument_link_map",
            "assumption_warrant_table",
            "claim_certainty_audit",
            "paragraph_flow_audit",
            "intro_logic_map",
            "figure_table_message_audit",
            "writing_defect_log",
            "fine_logic_audit_report",
            "claims_evidence_matrix",
            "section_plan",
            "figure_table_plan",
            "unsupported_claims",
            "reviewer_risks",
            "source_artifacts",
            "evidence_anchors",
            "support_status",
            "missing_evidence_warnings",
            "promotion_blockers",
        ),
        "forbidden_claims": (
            "chat_only_output",
            "unrecorded_chat_output",
            "unsupported_contribution_claim",
        ),
    },
    "AUTO_REVIEW": {
        "schema_version": "rh.delivery.auto_review.v1",
        "stage": "review",
        "gate": "review_readiness",
        "owner_skill": "provenance-review",
        "required_fields": (
            "review_scope",
            "critical_findings",
            "claim_risks",
            "evidence_gaps",
            "required_repairs",
            "source_artifacts",
            "evidence_anchors",
            "support_status",
            "missing_evidence_warnings",
            "promotion_blockers",
        ),
        "forbidden_claims": (
            "chat_only_output",
            "unrecorded_chat_output",
            "submission_ready_without_qa",
        ),
    },
    "PRESUBMISSION_AUDIT": {
        "schema_version": "rh.delivery.presubmission_audit.v1",
        "stage": "write",
        "gate": "submission_readiness",
        "owner_skill": "paper-writing",
        "required_fields": (
            "citation_integrity",
            "final_bundle_quality",
            "provenance_summary",
            "figure_table_quality",
            "package_readiness",
            "unresolved_blockers",
            "source_artifacts",
            "evidence_anchors",
            "support_status",
            "missing_evidence_warnings",
            "promotion_blockers",
        ),
        "forbidden_claims": (
            "chat_only_output",
            "unrecorded_chat_output",
            "submission_ready_without_qa",
        ),
    },
    "PAPER_PACKAGE": {
        "schema_version": "rh.delivery.paper_package.v1",
        "stage": "write",
        "gate": "package_readiness",
        "owner_skill": "publication-pack",
        "required_fields": (
            "component_artifact_ids",
            "missing_required_components",
            "qa_checks",
            "publication_pack_artifact",
            "final_bundle_artifact",
            "source_artifacts",
            "evidence_anchors",
            "support_status",
            "missing_evidence_warnings",
            "promotion_blockers",
        ),
        "forbidden_claims": (
            "chat_only_output",
            "unrecorded_chat_output",
            "submission_ready_without_qa",
        ),
    },
}

REBUTTAL_CAMERA_READY_PAYLOADS: Mapping[str, Mapping[str, Any]] = {
    "REBUTTAL_PACKAGE": {
        "schema_version": "rh.delivery.rebuttal_package.v1",
        "stage": "write",
        "gate": "response_readiness",
        "owner_skill": "publication-pack",
        "required_fields": (
            "reviewer_comments",
            "response_evidence",
            "revision_deltas",
            "camera_ready_replay",
            "final_package_delta",
            "source_artifacts",
            "evidence_anchors",
            "support_status",
            "missing_evidence_warnings",
            "promotion_blockers",
        ),
        "forbidden_claims": (
            "unrecorded_reviewer_response",
            "chat_only_output",
            "unrecorded_chat_output",
            "submission_ready_without_qa",
        ),
    },
}


@dataclass(frozen=True)
class DeliveryArtifactRecord:
    artifact: str
    stage: str
    gate: str
    owner_skill: str
    recording_surface: str
    source_of_truth: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class DeliveryProtocolContract:
    schema_version: str
    source_of_truth: str
    public_surface: str
    runtime_dependency: str
    entry_modes: tuple[str, ...]
    records: tuple[DeliveryArtifactRecord, ...]
    missing: tuple[str, ...]
    boundary_violations: tuple[str, ...]
    status: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["entry_modes"] = list(self.entry_modes)
        payload["records"] = [record.to_dict() for record in self.records]
        payload["missing"] = list(self.missing)
        payload["boundary_violations"] = list(self.boundary_violations)
        return payload


@dataclass(frozen=True)
class DeliveryProtocolDecision:
    entry_mode: str
    request: str
    inferred_from: str
    artifact: str
    stage: str
    gate: str
    owner_skill: str
    recording_surface: str
    artifact_state: str
    action: str
    status: str
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["blockers"] = list(self.blockers)
        return payload


@dataclass(frozen=True)
class DeliveryArtifactPayloadContract:
    artifact: str
    schema_version: str
    artifact_role: str
    stage: str
    gate: str
    owner_skill: str
    recording_surface: str
    public_surface: str
    runtime_dependency: str
    required_fields: tuple[str, ...]
    forbidden_claims: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["required_fields"] = list(self.required_fields)
        payload["forbidden_claims"] = list(self.forbidden_claims)
        return payload


@dataclass(frozen=True)
class DeliveryArtifactPayloadValidation:
    artifact: str
    schema_version: str
    missing_fields: tuple[str, ...]
    forbidden_claim_hits: tuple[str, ...]
    boundary_violations: tuple[str, ...]
    status: str

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["missing_fields"] = list(self.missing_fields)
        payload["forbidden_claim_hits"] = list(self.forbidden_claim_hits)
        payload["boundary_violations"] = list(self.boundary_violations)
        return payload


@dataclass(frozen=True)
class DeliveryArtifactPromotionPlan:
    entry_mode: str
    request: str
    artifact: str
    stage: str
    gate: str
    owner_skill: str
    recording_surface: str
    payload_schema_version: str
    payload_summary: Mapping[str, int]
    validation_status: str
    action: str
    status: str
    dry_run: bool
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["payload_summary"] = dict(self.payload_summary)
        payload["blockers"] = list(self.blockers)
        return payload


@dataclass(frozen=True)
class DeliveryStageReadiness:
    entry_mode: str
    request: str
    artifact: str
    stage: str
    gate: str
    owner_skill: str
    recording_surface: str
    action: str
    status: str
    validation_status: str
    promotion_status: str
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["blockers"] = list(self.blockers)
        return payload


@dataclass(frozen=True)
class DeliveryPaperProductionSnapshot:
    status: str
    next_artifact: str
    next_action: str
    summary: Mapping[str, int]
    records: tuple[DeliveryStageReadiness, ...]
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["summary"] = dict(self.summary)
        payload["records"] = [record.to_dict() for record in self.records]
        payload["blockers"] = list(self.blockers)
        return payload


@dataclass(frozen=True)
class DeliveryPaperProfileRoute:
    schema_version: str
    status: str
    discipline: str
    research_type: str
    study_design: str
    paper_type: str
    target_venue: str
    domain_skill: str
    domain_profile: str
    method_route: str
    reporting_map: str
    evidence_rule: str
    venue_profile: str
    public_surface: str
    runtime_dependency: str
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["blockers"] = list(self.blockers)
        return payload


@dataclass(frozen=True)
class DeliveryVenueOverlay:
    """Deterministic submission-constraint overlay for a target venue.

    ``build_paper_profile_route`` only passes the raw ``target_venue`` string
    through as ``venue_profile``; this overlay classifies that venue into a
    family and resolves the submission constraints (review model, anonymization,
    format family, required declarations) a delivery-protocol paper plan must honor.
    """

    schema_version: str
    status: str
    target_venue: str
    venue_family: str
    review_model: str
    anonymization_required: bool
    format_family: str
    required_declarations: tuple[str, ...]
    public_surface: str
    runtime_dependency: str
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["required_declarations"] = list(self.required_declarations)
        payload["blockers"] = list(self.blockers)
        return payload


@dataclass(frozen=True)
class DeliveryDomainMethodSearchProfile:
    schema_version: str
    status: str
    discipline: str
    research_type: str
    study_design: str
    paper_type: str
    target_venue: str
    domain_skill: str
    method_route: str
    search_route: str
    search_strategies: tuple[str, ...]
    method_requirements: tuple[str, ...]
    baseline_anchor_fields: tuple[str, ...]
    evidence_table_schema: tuple[str, ...]
    excluded_defaults: tuple[str, ...]
    public_surface: str
    runtime_dependency: str
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["search_strategies"] = list(self.search_strategies)
        payload["method_requirements"] = list(self.method_requirements)
        payload["baseline_anchor_fields"] = list(self.baseline_anchor_fields)
        payload["evidence_table_schema"] = list(self.evidence_table_schema)
        payload["excluded_defaults"] = list(self.excluded_defaults)
        payload["blockers"] = list(self.blockers)
        return payload


@dataclass(frozen=True)
class DeliveryEvaluationGateProfile:
    schema_version: str
    status: str
    discipline: str
    research_type: str
    study_design: str
    paper_type: str
    target_venue: str
    domain_skill: str
    evaluation_route: str
    scoring_axes: tuple[str, ...]
    verdict_options: tuple[str, ...]
    decision: str
    pilot_required: bool
    pilot_catalog: tuple[str, ...]
    required_artifacts: tuple[str, ...]
    problem_anchor_required: bool
    problem_anchor_status: str
    baseline_mode: str
    paper_access_status: str
    fatal_flaws: tuple[str, ...]
    feasibility_risks: Mapping[str, str]
    scorecard: Mapping[str, int]
    warnings: tuple[str, ...]
    public_surface: str
    runtime_dependency: str
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["scoring_axes"] = list(self.scoring_axes)
        payload["verdict_options"] = list(self.verdict_options)
        payload["pilot_catalog"] = list(self.pilot_catalog)
        payload["required_artifacts"] = list(self.required_artifacts)
        payload["fatal_flaws"] = list(self.fatal_flaws)
        payload["feasibility_risks"] = dict(self.feasibility_risks)
        payload["scorecard"] = dict(self.scorecard)
        payload["warnings"] = list(self.warnings)
        payload["blockers"] = list(self.blockers)
        return payload


@dataclass(frozen=True)
class DeliveryExperimentGroundingProfile:
    schema_version: str
    status: str
    discipline: str
    research_type: str
    study_design: str
    paper_type: str
    target_venue: str
    domain_skill: str
    experiment_route: str
    result_state: str
    experiment_goal_status: str
    experiment_plan_status: str
    paper_profile_status: str
    variable_grounding_status: str
    codebook_status: str
    evidence_reporting_status: str
    pre_deploy_code_review_status: str
    deploy_blocker_count: int
    impact_report_status: str
    impact_claim_binding_status: str
    missing_variables: tuple[str, ...]
    required_artifacts: tuple[str, ...]
    plan_alignment_checks: tuple[str, ...]
    variable_grounding_checks: tuple[str, ...]
    code_review_bug_classes: tuple[str, ...]
    reporting_requirements: tuple[str, ...]
    impact_report_claim_checks: tuple[str, ...]
    decision: str
    public_surface: str
    runtime_dependency: str
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["missing_variables"] = list(self.missing_variables)
        payload["required_artifacts"] = list(self.required_artifacts)
        payload["plan_alignment_checks"] = list(self.plan_alignment_checks)
        payload["variable_grounding_checks"] = list(self.variable_grounding_checks)
        payload["code_review_bug_classes"] = list(self.code_review_bug_classes)
        payload["reporting_requirements"] = list(self.reporting_requirements)
        payload["impact_report_claim_checks"] = list(self.impact_report_claim_checks)
        payload["blockers"] = list(self.blockers)
        return payload


@dataclass(frozen=True)
class DeliveryResultToClaimAnalysisProfile:
    schema_version: str
    status: str
    discipline: str
    research_type: str
    study_design: str
    paper_type: str
    target_venue: str
    domain_skill: str
    analysis_route: str
    result_state: str
    experiment_grounding_status: str
    impact_report_status: str
    claims_from_results_status: str
    result_artifact_status: str
    expected_vs_actual_status: str
    statistical_reporting_status: str
    practical_significance_status: str
    baseline_delta_status: str
    robustness_status: str
    negative_results_status: str
    competing_evidence_status: str
    claim_strength: str
    maximum_allowed_claim_strength: str
    unsupported_claim_ids: tuple[str, ...]
    overclaimed_claim_ids: tuple[str, ...]
    missing_result_artifact_ids: tuple[str, ...]
    evidence_tiers: tuple[str, ...]
    required_artifacts: tuple[str, ...]
    analysis_checks: tuple[str, ...]
    disallowed_claim_language: tuple[str, ...]
    decision: str
    public_surface: str
    runtime_dependency: str
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["unsupported_claim_ids"] = list(self.unsupported_claim_ids)
        payload["overclaimed_claim_ids"] = list(self.overclaimed_claim_ids)
        payload["missing_result_artifact_ids"] = list(self.missing_result_artifact_ids)
        payload["evidence_tiers"] = list(self.evidence_tiers)
        payload["required_artifacts"] = list(self.required_artifacts)
        payload["analysis_checks"] = list(self.analysis_checks)
        payload["disallowed_claim_language"] = list(self.disallowed_claim_language)
        payload["blockers"] = list(self.blockers)
        return payload


@dataclass(frozen=True)
class DeliverySkeletonSourceIntegrityProfile:
    schema_version: str
    status: str
    discipline: str
    research_type: str
    study_design: str
    paper_type: str
    target_venue: str
    domain_skill: str
    integrity_route: str
    skeleton_status: str
    source_trace_status: str
    logic_chain_status: str
    claims_evidence_matrix_status: str
    source_artifact_inventory_status: str
    citation_integrity_status: str
    bib_doi_verification_status: str
    figure_table_reference_status: str
    missing_section_groups: tuple[str, ...]
    stub_section_groups: tuple[str, ...]
    missing_source_trace_claims: tuple[str, ...]
    dangling_citation_keys: tuple[str, ...]
    unverified_bib_entries: tuple[str, ...]
    dangling_table_refs: tuple[str, ...]
    missing_figure_assets: tuple[str, ...]
    required_artifacts: tuple[str, ...]
    required_section_groups: tuple[str, ...]
    skeleton_checks: tuple[str, ...]
    source_trace_checks: tuple[str, ...]
    citation_checks: tuple[str, ...]
    bib_metadata_checks: tuple[str, ...]
    figure_table_checks: tuple[str, ...]
    decision: str
    public_surface: str
    runtime_dependency: str
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["missing_section_groups"] = list(self.missing_section_groups)
        payload["stub_section_groups"] = list(self.stub_section_groups)
        payload["missing_source_trace_claims"] = list(self.missing_source_trace_claims)
        payload["dangling_citation_keys"] = list(self.dangling_citation_keys)
        payload["unverified_bib_entries"] = list(self.unverified_bib_entries)
        payload["dangling_table_refs"] = list(self.dangling_table_refs)
        payload["missing_figure_assets"] = list(self.missing_figure_assets)
        payload["required_artifacts"] = list(self.required_artifacts)
        payload["required_section_groups"] = list(self.required_section_groups)
        payload["skeleton_checks"] = list(self.skeleton_checks)
        payload["source_trace_checks"] = list(self.source_trace_checks)
        payload["citation_checks"] = list(self.citation_checks)
        payload["bib_metadata_checks"] = list(self.bib_metadata_checks)
        payload["figure_table_checks"] = list(self.figure_table_checks)
        payload["blockers"] = list(self.blockers)
        return payload


@dataclass(frozen=True)
class DeliveryPresubmissionSeverityGateProfile:
    schema_version: str
    status: str
    review_target: str
    critical_count: int
    major_count: int
    minor_count: int
    integrity_gate_status: str
    skeleton_source_integrity_status: str
    final_bundle_quality_status: str
    unresolved_critical_findings: tuple[str, ...]
    integrity_failures: tuple[str, ...]
    severity_taxonomy: tuple[str, ...]
    required_artifacts: tuple[str, ...]
    integrity_checks: tuple[str, ...]
    submission_checks: tuple[str, ...]
    decision: str
    public_surface: str
    runtime_dependency: str
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["unresolved_critical_findings"] = list(
            self.unresolved_critical_findings
        )
        payload["integrity_failures"] = list(self.integrity_failures)
        payload["severity_taxonomy"] = list(self.severity_taxonomy)
        payload["required_artifacts"] = list(self.required_artifacts)
        payload["integrity_checks"] = list(self.integrity_checks)
        payload["submission_checks"] = list(self.submission_checks)
        payload["blockers"] = list(self.blockers)
        return payload


@dataclass(frozen=True)
class DeliveryRebuttalReadinessGateProfile:
    schema_version: str
    status: str
    issue_board_status: str
    response_letter_status: str
    revision_plan_status: str
    provenance_gate_status: str
    commitment_gate_status: str
    coverage_gate_status: str
    external_review_status: str
    unresolved_issue_ids: tuple[str, ...]
    orphan_commitment_ids: tuple[str, ...]
    unprovenanced_response_ids: tuple[str, ...]
    pending_user_input_ids: tuple[str, ...]
    issue_status_options: tuple[str, ...]
    required_artifacts: tuple[str, ...]
    provenance_checks: tuple[str, ...]
    commitment_checks: tuple[str, ...]
    coverage_checks: tuple[str, ...]
    response_quality_checks: tuple[str, ...]
    decision: str
    public_surface: str
    runtime_dependency: str
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["unresolved_issue_ids"] = list(self.unresolved_issue_ids)
        payload["orphan_commitment_ids"] = list(self.orphan_commitment_ids)
        payload["unprovenanced_response_ids"] = list(self.unprovenanced_response_ids)
        payload["pending_user_input_ids"] = list(self.pending_user_input_ids)
        payload["issue_status_options"] = list(self.issue_status_options)
        payload["required_artifacts"] = list(self.required_artifacts)
        payload["provenance_checks"] = list(self.provenance_checks)
        payload["commitment_checks"] = list(self.commitment_checks)
        payload["coverage_checks"] = list(self.coverage_checks)
        payload["response_quality_checks"] = list(self.response_quality_checks)
        payload["blockers"] = list(self.blockers)
        return payload


def build_paper_profile_route(
    *,
    discipline: str,
    research_type: str,
    study_design: str,
    paper_type: str,
    target_venue: str = "",
) -> DeliveryPaperProfileRoute:
    """Route an paper profile to RH writing controls.

    This helper is deterministic and side-effect free. It does not inspect DB
    state, perform IO, call providers, or import an external runtime package.
    """

    normalized_discipline = _paper_profile_key(discipline)
    normalized_research_type = _paper_profile_key(research_type)
    normalized_study_design = _paper_profile_key(study_design)
    normalized_paper_type = _paper_profile_key(paper_type)
    normalized_target_venue = str(target_venue or "").strip()
    blockers = _paper_profile_blockers(
        discipline=normalized_discipline,
        research_type=normalized_research_type,
        study_design=normalized_study_design,
    )

    route = _paper_profile_route_values(
        discipline=normalized_discipline,
        research_type=normalized_research_type,
        study_design=normalized_study_design,
        paper_type=normalized_paper_type,
        target_venue=normalized_target_venue,
    )
    if route is None:
        blockers = tuple([*blockers, "unknown_paper_profile_route"])
        route = _empty_paper_profile_route()

    return DeliveryPaperProfileRoute(
        schema_version="rh.delivery.paper_profile.v1",
        status="success" if not blockers else "blocked",
        discipline=normalized_discipline,
        research_type=normalized_research_type,
        study_design=normalized_study_design,
        paper_type=normalized_paper_type,
        target_venue=normalized_target_venue,
        domain_skill=route["domain_skill"],
        domain_profile=route["domain_profile"],
        method_route=route["method_route"],
        reporting_map=route["reporting_map"],
        evidence_rule=route["evidence_rule"],
        venue_profile=route["venue_profile"],
        public_surface="none",
        runtime_dependency="none",
        blockers=blockers,
    )


def build_delivery_venue_overlay(
    *,
    target_venue: str,
) -> DeliveryVenueOverlay:
    """Resolve venue-specific submission constraints for a target venue.

    This helper is deterministic and side-effect free. It does not inspect DB
    state, perform IO, call providers, or import an external runtime package.
    Unrecognized or empty venues return a ``blocked`` overlay rather than a
    silent default, so a paper plan cannot inherit the wrong submission rules.
    """

    normalized_target_venue = str(target_venue or "").strip()
    venue_key = _paper_profile_key(normalized_target_venue)

    if not venue_key:
        return _empty_venue_overlay(normalized_target_venue, ("missing:target_venue",))

    family = _venue_family(venue_key)
    overlay = _VENUE_FAMILY_OVERLAYS.get(family)
    if overlay is None:
        return _empty_venue_overlay(normalized_target_venue, ("unknown_venue",))

    return DeliveryVenueOverlay(
        schema_version="rh.delivery.venue_overlay.v1",
        status="success",
        target_venue=normalized_target_venue,
        venue_family=family,
        review_model=overlay["review_model"],
        anonymization_required=overlay["anonymization_required"],
        format_family=overlay["format_family"],
        required_declarations=overlay["required_declarations"],
        public_surface="none",
        runtime_dependency="none",
        blockers=(),
    )


def build_domain_method_search_profile(
    *,
    discipline: str,
    research_type: str,
    study_design: str,
    paper_type: str,
    target_venue: str = "",
) -> DeliveryDomainMethodSearchProfile:
    """Route discovery, baseline, and method planning for a paper profile.

    This private contract helper performs no IO, search calls, network access,
    provider calls, database reads, or artifact writes.
    """

    paper_profile = build_paper_profile_route(
        discipline=discipline,
        research_type=research_type,
        study_design=study_design,
        paper_type=paper_type,
        target_venue=target_venue,
    )
    spec = _domain_method_search_values(
        discipline=paper_profile.discipline,
        research_type=paper_profile.research_type,
        study_design=paper_profile.study_design,
        paper_type=paper_profile.paper_type,
        target_venue=paper_profile.target_venue,
        domain_skill=paper_profile.domain_skill,
    )
    blockers = tuple(f"paper_profile:{item}" for item in paper_profile.blockers)
    if spec is None:
        spec = _empty_domain_method_search_values()
        blockers = tuple([*blockers, "missing_domain_method_search_profile"])

    return DeliveryDomainMethodSearchProfile(
        schema_version="rh.delivery.domain_method_search_profile.v1",
        status="success" if not blockers else "blocked",
        discipline=paper_profile.discipline,
        research_type=paper_profile.research_type,
        study_design=paper_profile.study_design,
        paper_type=paper_profile.paper_type,
        target_venue=paper_profile.target_venue,
        domain_skill=paper_profile.domain_skill,
        method_route=spec["method_route"],
        search_route=spec["search_route"],
        search_strategies=tuple(spec["search_strategies"]),
        method_requirements=tuple(spec["method_requirements"]),
        baseline_anchor_fields=tuple(spec["baseline_anchor_fields"]),
        evidence_table_schema=tuple(spec["evidence_table_schema"]),
        excluded_defaults=tuple(spec["excluded_defaults"]),
        public_surface="none",
        runtime_dependency="none",
        blockers=blockers,
    )


def build_delivery_evaluation_gate_profile(
    *,
    discipline: str,
    research_type: str,
    study_design: str,
    paper_type: str,
    problem_anchor_status: str,
    baseline_mode: str,
    paper_access_status: str,
    fatal_flaws: tuple[str, ...] | list[str],
    feasibility_risks: Mapping[str, str],
    scorecard: Mapping[str, int],
    target_venue: str = "",
) -> DeliveryEvaluationGateProfile:
    """Build a private go/no-go profile for idea evaluation.

    This helper is deterministic and side-effect free. It only normalizes
    caller-provided facts; it does not read papers, write artifacts, run
    pilots, advance stages, or import external runtime code.
    """

    paper_profile = build_paper_profile_route(
        discipline=discipline,
        research_type=research_type,
        study_design=study_design,
        paper_type=paper_type,
        target_venue=target_venue,
    )
    spec = _evaluation_gate_values(
        discipline=paper_profile.discipline,
        research_type=paper_profile.research_type,
        paper_type=paper_profile.paper_type,
        domain_skill=paper_profile.domain_skill,
    )
    normalized_anchor_status = _evaluation_gate_key(problem_anchor_status)
    normalized_baseline_mode = _evaluation_mode_key(baseline_mode)
    normalized_access_status = _evaluation_gate_key(paper_access_status)
    normalized_flaws = tuple(
        str(item).strip() for item in fatal_flaws if str(item).strip()
    )
    normalized_risks = {
        str(key).strip(): _evaluation_gate_key(value)
        for key, value in feasibility_risks.items()
    }
    normalized_scorecard = {
        str(key).strip(): int(value) for key, value in scorecard.items()
    }

    blockers = list(f"paper_profile:{item}" for item in paper_profile.blockers)
    warnings: list[str] = []
    if normalized_anchor_status != "frozen":
        blockers.append("problem_anchor_not_frozen")
    if normalized_access_status != "verified":
        blockers.append("paper_access_blocked")
    if normalized_baseline_mode not in spec["baseline_modes"]:
        blockers.append(f"baseline_mode_unsupported:{normalized_baseline_mode}")

    critical_flaw = _has_critical_fatal_flaw(normalized_flaws)
    if critical_flaw:
        blockers.append("critical_fatal_flaw")
    elif len(normalized_flaws) >= 2:
        blockers.append("too_many_fatal_flaws")

    psy_edu_soft_gate = _psy_edu_soft_gate_fires(
        paper_profile.discipline,
        normalized_scorecard,
    )
    if psy_edu_soft_gate:
        warnings.append("soft_gate:psy_edu_axes_1_3_below_5")

    decision, pilot_required = _evaluation_gate_decision(
        blockers=tuple(blockers),
        warnings=tuple(warnings),
        scorecard=normalized_scorecard,
        feasibility_risks=normalized_risks,
        scoring_axes=tuple(spec["scoring_axes"]),
    )

    return DeliveryEvaluationGateProfile(
        schema_version="rh.delivery.evaluation_gate_profile.v1",
        status="success" if not blockers else "blocked",
        discipline=paper_profile.discipline,
        research_type=paper_profile.research_type,
        study_design=paper_profile.study_design,
        paper_type=paper_profile.paper_type,
        target_venue=paper_profile.target_venue,
        domain_skill=paper_profile.domain_skill,
        evaluation_route=str(spec["evaluation_route"]),
        scoring_axes=tuple(spec["scoring_axes"]),
        verdict_options=(
            "strong-accept",
            "accept-revisions",
            "pending-pilot",
            "reject",
        ),
        decision=decision,
        pilot_required=pilot_required,
        pilot_catalog=tuple(spec["pilot_catalog"]),
        required_artifacts=(
            "PROBLEM_ANCHOR",
            "RESEARCH_PROPOSAL",
            "DOMAIN_METHOD_SEARCH_PROFILE",
            "EVALUATION",
            "baseline_access_table",
        ),
        problem_anchor_required=True,
        problem_anchor_status=normalized_anchor_status,
        baseline_mode=normalized_baseline_mode,
        paper_access_status=normalized_access_status,
        fatal_flaws=normalized_flaws,
        feasibility_risks=normalized_risks,
        scorecard=normalized_scorecard,
        warnings=tuple(warnings),
        public_surface="none",
        runtime_dependency="none",
        blockers=tuple(blockers),
    )


def build_delivery_experiment_grounding_profile(
    *,
    discipline: str,
    research_type: str,
    study_design: str,
    paper_type: str,
    experiment_goal_status: str,
    experiment_plan_status: str,
    paper_profile_status: str,
    variable_grounding_status: str,
    codebook_status: str,
    evidence_reporting_status: str,
    pre_deploy_code_review_status: str,
    deploy_blocker_count: int,
    impact_report_status: str,
    impact_claim_binding_status: str,
    result_state: str,
    missing_variables: tuple[str, ...] | list[str],
    target_venue: str = "",
) -> DeliveryExperimentGroundingProfile:
    """Build a private experiment-grounding gate for paper-bound results.

    This helper is deterministic and side-effect free. It does not parse plans,
    inspect codebooks, run code review, deploy jobs, read result files, record
    artifacts, call providers, or import external runtime code.
    """

    paper_profile = build_paper_profile_route(
        discipline=discipline,
        research_type=research_type,
        study_design=study_design,
        paper_type=paper_type,
        target_venue=target_venue,
    )
    spec = _experiment_grounding_values(
        discipline=paper_profile.discipline,
        research_type=paper_profile.research_type,
        study_design=paper_profile.study_design,
        paper_type=paper_profile.paper_type,
        domain_skill=paper_profile.domain_skill,
    )
    normalized_goal_status = _evaluation_gate_key(experiment_goal_status)
    normalized_plan_status = _evaluation_gate_key(experiment_plan_status)
    normalized_profile_status = _evaluation_gate_key(paper_profile_status)
    normalized_variable_status = _evaluation_gate_key(variable_grounding_status)
    normalized_codebook_status = _evaluation_gate_key(codebook_status)
    normalized_reporting_status = _evaluation_gate_key(evidence_reporting_status)
    normalized_review_status = _evaluation_gate_key(pre_deploy_code_review_status)
    normalized_impact_status = _evaluation_gate_key(impact_report_status)
    normalized_claim_binding_status = _evaluation_gate_key(impact_claim_binding_status)
    normalized_result_state = _evaluation_gate_key(result_state)
    normalized_missing_variables = tuple(
        str(item).strip() for item in missing_variables if str(item).strip()
    )
    normalized_deploy_blockers = max(0, int(deploy_blocker_count))

    blockers = list(f"paper_profile:{item}" for item in paper_profile.blockers)
    if normalized_profile_status != "recorded":
        blockers.append("paper_profile_not_recorded")
    if normalized_goal_status != "aligned":
        blockers.append("experiment_goal_not_aligned")
    if normalized_plan_status != "profile_aligned":
        blockers.append("experiment_plan_not_profile_aligned")
    if normalized_variable_status != "verified":
        if normalized_missing_variables:
            blockers.extend(
                f"variable_grounding_missing:{variable}"
                for variable in normalized_missing_variables
            )
        else:
            blockers.append("variable_grounding_unverified")
    if normalized_codebook_status != "verified":
        blockers.append("codebook_unverified")
    if normalized_reporting_status != "aligned":
        blockers.append("evidence_reporting_not_aligned")
    if normalized_review_status != "pass":
        blockers.append("pre_deploy_code_review_blocked")
    if normalized_deploy_blockers > 0:
        blockers.append(f"deploy_blockers:{normalized_deploy_blockers}")
    if normalized_result_state == "completed":
        if normalized_impact_status != "claim_bound":
            blockers.append(f"impact_report_{normalized_impact_status}")
        if normalized_claim_binding_status != "verified":
            blockers.append(
                f"impact_report_claim_binding_{normalized_claim_binding_status}"
            )

    return DeliveryExperimentGroundingProfile(
        schema_version="rh.delivery.experiment_grounding_profile.v1",
        status="success" if not blockers else "blocked",
        discipline=paper_profile.discipline,
        research_type=paper_profile.research_type,
        study_design=paper_profile.study_design,
        paper_type=paper_profile.paper_type,
        target_venue=paper_profile.target_venue,
        domain_skill=paper_profile.domain_skill,
        experiment_route=str(spec["experiment_route"]),
        result_state=normalized_result_state,
        experiment_goal_status=normalized_goal_status,
        experiment_plan_status=normalized_plan_status,
        paper_profile_status=normalized_profile_status,
        variable_grounding_status=normalized_variable_status,
        codebook_status=normalized_codebook_status,
        evidence_reporting_status=normalized_reporting_status,
        pre_deploy_code_review_status=normalized_review_status,
        deploy_blocker_count=normalized_deploy_blockers,
        impact_report_status=normalized_impact_status,
        impact_claim_binding_status=normalized_claim_binding_status,
        missing_variables=normalized_missing_variables,
        required_artifacts=(
            "PAPER_PROFILE",
            "DOMAIN_METHOD_SEARCH_PROFILE",
            "EVALUATION_GATE_PROFILE",
            "EXPERIMENT_GOAL",
            "EXPERIMENT_PLAN",
            "variable_grounding_report",
            "codebook_or_variable_dictionary",
            "pre_deploy_code_review_report",
            "result_artifacts",
            "IMPACT_REPORT",
        ),
        plan_alignment_checks=tuple(spec["plan_alignment_checks"]),
        variable_grounding_checks=(
            "plan_variable_references",
            "codebook_or_data_dictionary",
            "profile_specific_required_fields",
            "reviewer_challenge_for_absent_variables",
        ),
        code_review_bug_classes=(
            "variable_grounding",
            "data_split_and_leakage",
            "metric_formula",
            "seeds_and_reproducibility",
            "ground_truth_source",
        ),
        reporting_requirements=tuple(spec["reporting_requirements"]),
        impact_report_claim_checks=(
            "expected_vs_actual_result_table",
            "claim_strength_boundary",
            "limitations_and_negative_results",
            "follow_up_experiment_gaps",
            "no_exploratory_positioning",
        ),
        decision=_experiment_grounding_decision(
            blockers=tuple(blockers),
            result_state=normalized_result_state,
        ),
        public_surface="none",
        runtime_dependency="none",
        blockers=tuple(blockers),
    )


def build_delivery_result_to_claim_analysis_profile(
    *,
    discipline: str,
    research_type: str,
    study_design: str,
    paper_type: str,
    result_state: str,
    experiment_grounding_status: str,
    impact_report_status: str,
    claims_from_results_status: str,
    result_artifact_status: str,
    expected_vs_actual_status: str,
    statistical_reporting_status: str,
    practical_significance_status: str,
    baseline_delta_status: str,
    robustness_status: str,
    negative_results_status: str,
    competing_evidence_status: str,
    claim_strength: str,
    unsupported_claim_ids: tuple[str, ...] | list[str],
    overclaimed_claim_ids: tuple[str, ...] | list[str],
    missing_result_artifact_ids: tuple[str, ...] | list[str],
    target_venue: str = "",
) -> DeliveryResultToClaimAnalysisProfile:
    """Build a private result-to-claim analysis gate profile.

    This helper is deterministic and side-effect free. It does not parse result
    tables, compute statistics, judge claims from prose, write artifacts, call
    providers, or import external runtime code.
    """

    paper_profile = build_paper_profile_route(
        discipline=discipline,
        research_type=research_type,
        study_design=study_design,
        paper_type=paper_type,
        target_venue=target_venue,
    )
    spec = _result_to_claim_analysis_values(
        discipline=paper_profile.discipline,
        research_type=paper_profile.research_type,
        study_design=paper_profile.study_design,
        paper_type=paper_profile.paper_type,
        domain_skill=paper_profile.domain_skill,
    )
    normalized_result_state = _evaluation_gate_key(result_state)
    normalized_grounding_status = _evaluation_gate_key(experiment_grounding_status)
    normalized_impact_status = _evaluation_gate_key(impact_report_status)
    normalized_claims_status = _evaluation_gate_key(claims_from_results_status)
    normalized_result_artifact_status = _evaluation_gate_key(result_artifact_status)
    normalized_expected_actual_status = _evaluation_gate_key(expected_vs_actual_status)
    normalized_statistical_status = _evaluation_gate_key(statistical_reporting_status)
    normalized_practical_status = _evaluation_gate_key(practical_significance_status)
    normalized_baseline_status = _evaluation_gate_key(baseline_delta_status)
    normalized_robustness_status = _evaluation_gate_key(robustness_status)
    normalized_negative_status = _evaluation_gate_key(negative_results_status)
    normalized_competing_status = _evaluation_gate_key(competing_evidence_status)
    normalized_claim_strength = str(claim_strength or "").strip()
    normalized_unsupported_claims = _clean_tuple(unsupported_claim_ids)
    normalized_overclaimed_claims = _clean_tuple(overclaimed_claim_ids)
    normalized_missing_result_artifacts = _clean_tuple(missing_result_artifact_ids)

    maximum_allowed = str(spec["maximum_allowed_claim_strength"])
    blockers = list(f"paper_profile:{item}" for item in paper_profile.blockers)
    required_statuses = {
        "result_state": (normalized_result_state, "completed"),
        "experiment_grounding": (normalized_grounding_status, "pass"),
        "impact_report": (normalized_impact_status, "claim_bound"),
        "claims_from_results": (normalized_claims_status, "drafted"),
        "result_artifact": (normalized_result_artifact_status, "verified"),
        "expected_vs_actual": (normalized_expected_actual_status, "verified"),
        "statistical_reporting": (normalized_statistical_status, "verified"),
        "practical_significance": (normalized_practical_status, "verified"),
        "robustness": (normalized_robustness_status, "verified"),
        "negative_results": (normalized_negative_status, "recorded"),
        "competing_evidence": (normalized_competing_status, "addressed"),
    }
    for label, (actual, expected) in required_statuses.items():
        if actual != expected:
            blockers.append(f"{label}_{actual or 'missing'}")
    if normalized_baseline_status not in ("verified", "not_applicable"):
        blockers.append(f"baseline_delta_{normalized_baseline_status}")
    blockers.extend(
        f"unsupported_claim:{claim}" for claim in normalized_unsupported_claims
    )
    blockers.extend(
        f"overclaimed_claim:{claim}" for claim in normalized_overclaimed_claims
    )
    blockers.extend(
        f"missing_result_artifact:{artifact}"
        for artifact in normalized_missing_result_artifacts
    )
    if _claim_strength_rank(normalized_claim_strength) < _claim_strength_rank(
        maximum_allowed
    ):
        blockers.append(
            f"claim_strength_exceeds_boundary:{normalized_claim_strength}>{maximum_allowed}"
        )

    return DeliveryResultToClaimAnalysisProfile(
        schema_version="rh.delivery.result_to_claim_analysis_profile.v1",
        status="success" if not blockers else "blocked",
        discipline=paper_profile.discipline,
        research_type=paper_profile.research_type,
        study_design=paper_profile.study_design,
        paper_type=paper_profile.paper_type,
        target_venue=paper_profile.target_venue,
        domain_skill=paper_profile.domain_skill,
        analysis_route=str(spec["analysis_route"]),
        result_state=normalized_result_state,
        experiment_grounding_status=normalized_grounding_status,
        impact_report_status=normalized_impact_status,
        claims_from_results_status=normalized_claims_status,
        result_artifact_status=normalized_result_artifact_status,
        expected_vs_actual_status=normalized_expected_actual_status,
        statistical_reporting_status=normalized_statistical_status,
        practical_significance_status=normalized_practical_status,
        baseline_delta_status=normalized_baseline_status,
        robustness_status=normalized_robustness_status,
        negative_results_status=normalized_negative_status,
        competing_evidence_status=normalized_competing_status,
        claim_strength=normalized_claim_strength,
        maximum_allowed_claim_strength=maximum_allowed,
        unsupported_claim_ids=normalized_unsupported_claims,
        overclaimed_claim_ids=normalized_overclaimed_claims,
        missing_result_artifact_ids=normalized_missing_result_artifacts,
        evidence_tiers=(
            "A_confirmed",
            "B_empirical_strong",
            "C_empirical_limited",
            "D_exploratory",
            "E_speculative",
            "F_unsupported_or_blocked",
        ),
        required_artifacts=(
            "EXPERIMENT_GROUNDING_PROFILE",
            "IMPACT_REPORT",
            "CLAIMS_FROM_RESULTS",
            "result_artifacts",
            "relative_delta_table",
            "statistical_summary",
            "negative_results_log",
            "competing_evidence_notes",
        ),
        analysis_checks=tuple(spec["analysis_checks"]),
        disallowed_claim_language=tuple(spec["disallowed_claim_language"]),
        decision=_result_to_claim_analysis_decision(tuple(blockers)),
        public_surface="none",
        runtime_dependency="none",
        blockers=tuple(blockers),
    )


def build_delivery_skeleton_source_integrity_profile(
    *,
    discipline: str,
    research_type: str,
    study_design: str,
    paper_type: str,
    skeleton_status: str,
    source_trace_status: str,
    logic_chain_status: str,
    claims_evidence_matrix_status: str,
    source_artifact_inventory_status: str,
    citation_integrity_status: str,
    bib_doi_verification_status: str,
    figure_table_reference_status: str,
    missing_section_groups: tuple[str, ...] | list[str],
    stub_section_groups: tuple[str, ...] | list[str],
    missing_source_trace_claims: tuple[str, ...] | list[str],
    dangling_citation_keys: tuple[str, ...] | list[str],
    unverified_bib_entries: tuple[str, ...] | list[str],
    dangling_table_refs: tuple[str, ...] | list[str],
    missing_figure_assets: tuple[str, ...] | list[str],
    target_venue: str = "",
) -> DeliverySkeletonSourceIntegrityProfile:
    """Build a private skeleton/source/citation integrity gate profile.

    This helper is deterministic and side-effect free. It only normalizes
    caller-provided gate statuses; it does not read LaTeX, parse BibTeX, scan
    figures, call DOI services, write artifacts, or import external runtime
    code.
    """

    paper_profile = build_paper_profile_route(
        discipline=discipline,
        research_type=research_type,
        study_design=study_design,
        paper_type=paper_type,
        target_venue=target_venue,
    )
    spec = _skeleton_source_integrity_values(
        discipline=paper_profile.discipline,
        research_type=paper_profile.research_type,
        study_design=paper_profile.study_design,
        paper_type=paper_profile.paper_type,
        domain_skill=paper_profile.domain_skill,
    )
    normalized_skeleton_status = _evaluation_gate_key(skeleton_status)
    normalized_source_trace_status = _evaluation_gate_key(source_trace_status)
    normalized_logic_chain_status = _evaluation_gate_key(logic_chain_status)
    normalized_claims_matrix_status = _evaluation_gate_key(
        claims_evidence_matrix_status
    )
    normalized_source_inventory_status = _evaluation_gate_key(
        source_artifact_inventory_status
    )
    normalized_citation_status = _evaluation_gate_key(citation_integrity_status)
    normalized_bib_status = _evaluation_gate_key(bib_doi_verification_status)
    normalized_figure_table_status = _evaluation_gate_key(figure_table_reference_status)
    normalized_missing_sections = _clean_tuple(missing_section_groups)
    normalized_stub_sections = _clean_tuple(stub_section_groups)
    normalized_missing_source_claims = _clean_tuple(missing_source_trace_claims)
    normalized_dangling_cites = _clean_tuple(dangling_citation_keys)
    normalized_unverified_bib = _clean_tuple(unverified_bib_entries)
    normalized_dangling_tables = _clean_tuple(dangling_table_refs)
    normalized_missing_figures = _clean_tuple(missing_figure_assets)

    blockers = list(f"paper_profile:{item}" for item in paper_profile.blockers)
    if normalized_skeleton_status != "complete":
        if normalized_missing_sections:
            blockers.extend(
                f"skeleton_missing:{section}" for section in normalized_missing_sections
            )
        else:
            blockers.append(f"skeleton_{normalized_skeleton_status}")
    blockers.extend(f"skeleton_stub:{section}" for section in normalized_stub_sections)
    if normalized_source_trace_status != "verified":
        if normalized_missing_source_claims:
            blockers.extend(
                f"source_trace_missing:{claim}"
                for claim in normalized_missing_source_claims
            )
        else:
            blockers.append(f"source_trace_{normalized_source_trace_status}")
    if normalized_logic_chain_status != "consistent":
        blockers.append(f"logic_chain_{normalized_logic_chain_status}")
    if normalized_claims_matrix_status != "verified":
        blockers.append(f"claims_evidence_matrix_{normalized_claims_matrix_status}")
    if normalized_source_inventory_status != "verified":
        blockers.append(
            f"source_artifact_inventory_{normalized_source_inventory_status}"
        )
    if normalized_citation_status != "verified":
        if normalized_dangling_cites:
            blockers.extend(
                f"citation_dangling:{key}" for key in normalized_dangling_cites
            )
        else:
            blockers.append(f"citation_integrity_{normalized_citation_status}")
    if normalized_bib_status != "verified":
        if normalized_unverified_bib:
            blockers.extend(
                f"bib_doi_verification_{normalized_bib_status}:{entry}"
                for entry in normalized_unverified_bib
            )
        else:
            blockers.append(f"bib_doi_verification_{normalized_bib_status}")
    if normalized_figure_table_status != "verified":
        if normalized_dangling_tables:
            blockers.extend(
                f"table_ref_dangling:{ref}" for ref in normalized_dangling_tables
            )
        if normalized_missing_figures:
            blockers.extend(
                f"figure_asset_missing:{asset}" for asset in normalized_missing_figures
            )
        if not normalized_dangling_tables and not normalized_missing_figures:
            blockers.append(f"figure_table_reference_{normalized_figure_table_status}")

    return DeliverySkeletonSourceIntegrityProfile(
        schema_version="rh.delivery.skeleton_source_integrity_profile.v1",
        status="success" if not blockers else "blocked",
        discipline=paper_profile.discipline,
        research_type=paper_profile.research_type,
        study_design=paper_profile.study_design,
        paper_type=paper_profile.paper_type,
        target_venue=paper_profile.target_venue,
        domain_skill=paper_profile.domain_skill,
        integrity_route=str(spec["integrity_route"]),
        skeleton_status=normalized_skeleton_status,
        source_trace_status=normalized_source_trace_status,
        logic_chain_status=normalized_logic_chain_status,
        claims_evidence_matrix_status=normalized_claims_matrix_status,
        source_artifact_inventory_status=normalized_source_inventory_status,
        citation_integrity_status=normalized_citation_status,
        bib_doi_verification_status=normalized_bib_status,
        figure_table_reference_status=normalized_figure_table_status,
        missing_section_groups=normalized_missing_sections,
        stub_section_groups=normalized_stub_sections,
        missing_source_trace_claims=normalized_missing_source_claims,
        dangling_citation_keys=normalized_dangling_cites,
        unverified_bib_entries=normalized_unverified_bib,
        dangling_table_refs=normalized_dangling_tables,
        missing_figure_assets=normalized_missing_figures,
        required_artifacts=(
            "PAPER_PLAN",
            "PAPER_PROFILE",
            "DOMAIN_WRITING_PROFILE",
            "Claims-Evidence Matrix",
            "source_artifacts",
            "logic_skeleton",
            "main_tex_or_manuscript_source",
            "refs_bib_or_citation_registry",
            "figure_table_plan",
            "citation_integrity",
            "bib_doi_verification",
        ),
        required_section_groups=tuple(spec["required_section_groups"]),
        skeleton_checks=(
            "section_group_completeness",
            "non_empty_section_body",
            "venue_required_sections_override",
            "section_to_contribution_mapping",
        ),
        source_trace_checks=tuple(spec["source_trace_checks"]),
        citation_checks=(
            "cite_key_to_verified_bib_entry",
            "no_dangling_citations",
            "table_ref_label_bidirectional",
            "figure_asset_resolves",
            "no_svg_only_figure_assets",
        ),
        bib_metadata_checks=(
            "doi_or_primary_metadata_verified",
            "title_author_year_venue_match",
            "no_memory_or_baseline_table_inferred_entries",
            "citation_claim_support_checked",
            "no_banned_submission_entry_types",
        ),
        figure_table_checks=(
            "includegraphics_target_exists",
            "orphan_figure_warn_only",
            "table_ref_has_label",
            "table_label_reverse_reference_warn_only",
            "standalone_readability_review_required",
        ),
        decision=_skeleton_source_integrity_decision(tuple(blockers)),
        public_surface="none",
        runtime_dependency="none",
        blockers=tuple(blockers),
    )


def build_delivery_presubmission_severity_gate_profile(
    *,
    target: str,
    critical_count: int,
    major_count: int,
    minor_count: int,
    integrity_gate_status: str,
    skeleton_source_integrity_status: str,
    final_bundle_quality_status: str,
    unresolved_critical_findings: tuple[str, ...] | list[str],
    integrity_failures: tuple[str, ...] | list[str],
) -> DeliveryPresubmissionSeverityGateProfile:
    """Build a private presubmission severity and integrity gate profile.

    This helper is deterministic and side-effect free. It does not call an
    external reviewer, inspect paper text, parse findings, write artifacts, or
    advance submission state.
    """

    review_target = str(target).strip()
    normalized_target = _paper_profile_key(review_target)
    normalized_integrity_status = _evaluation_gate_key(integrity_gate_status)
    normalized_skeleton_status = _evaluation_gate_key(skeleton_source_integrity_status)
    normalized_bundle_status = _evaluation_gate_key(final_bundle_quality_status)
    normalized_critical_count = max(0, int(critical_count))
    normalized_major_count = max(0, int(major_count))
    normalized_minor_count = max(0, int(minor_count))
    normalized_critical_findings = _clean_tuple(unresolved_critical_findings)
    normalized_integrity_failures = _clean_tuple(integrity_failures)

    blockers: list[str] = []
    if normalized_target != "paper_presubmission":
        blockers.append(f"review_target_unsupported:{normalized_target}")
    if normalized_critical_count > 0:
        blockers.append(f"critical_findings:{normalized_critical_count}")
        blockers.extend(
            f"critical_finding:{finding}" for finding in normalized_critical_findings
        )
    if normalized_integrity_status != "pass":
        blockers.append(f"integrity_gate_{normalized_integrity_status}")
    blockers.extend(
        f"integrity_failure:{failure}" for failure in normalized_integrity_failures
    )
    if normalized_skeleton_status != "pass":
        blockers.append(f"skeleton_source_integrity_{normalized_skeleton_status}")
    if normalized_bundle_status != "pass":
        blockers.append(f"final_bundle_quality_{normalized_bundle_status}")

    return DeliveryPresubmissionSeverityGateProfile(
        schema_version="rh.delivery.presubmission_severity_gate.v1",
        status="success" if not blockers else "blocked",
        review_target=review_target,
        critical_count=normalized_critical_count,
        major_count=normalized_major_count,
        minor_count=normalized_minor_count,
        integrity_gate_status=normalized_integrity_status,
        skeleton_source_integrity_status=normalized_skeleton_status,
        final_bundle_quality_status=normalized_bundle_status,
        unresolved_critical_findings=normalized_critical_findings,
        integrity_failures=normalized_integrity_failures,
        severity_taxonomy=("CRITICAL", "MAJOR", "MINOR"),
        required_artifacts=(
            "PRESUBMISSION_AUDIT",
            "AUTO_REVIEW",
            "SKELETON_SOURCE_INTEGRITY_PROFILE",
            "final_bundle_quality_report",
            "citation_integrity",
            "figure_table_quality",
            "provenance_summary",
        ),
        integrity_checks=(
            "quoted_text_present_in_source",
            "critical_finding_has_concrete_fix",
            "no_fabricated_quotes",
            "severity_assignment_follows_taxonomy",
            "grammar_rule_ids_present",
            "banned_vocabulary_scan_attested",
            "final_score_matches_severity_counts",
        ),
        submission_checks=(
            "critical_count_zero",
            "skeleton_source_integrity_passed",
            "final_bundle_quality_passed",
            "citation_and_figure_checks_passed",
            "provenance_summary_recorded",
        ),
        decision=_presubmission_severity_decision(tuple(blockers)),
        public_surface="none",
        runtime_dependency="none",
        blockers=tuple(blockers),
    )


def build_delivery_rebuttal_readiness_gate_profile(
    *,
    issue_board_status: str,
    response_letter_status: str,
    revision_plan_status: str,
    provenance_gate_status: str,
    commitment_gate_status: str,
    coverage_gate_status: str,
    external_review_status: str,
    unresolved_issue_ids: tuple[str, ...] | list[str],
    orphan_commitment_ids: tuple[str, ...] | list[str],
    unprovenanced_response_ids: tuple[str, ...] | list[str],
    pending_user_input_ids: tuple[str, ...] | list[str],
) -> DeliveryRebuttalReadinessGateProfile:
    """Build a private rebuttal issue/provenance/commitment/coverage gate.

    This helper is deterministic and side-effect free. It does not parse
    reviewer comments, call external reviewers, edit manuscripts, render DOCX,
    zip files, write artifacts, or import external runtime code.
    """

    normalized_issue_board_status = _evaluation_gate_key(issue_board_status)
    normalized_response_status = _evaluation_gate_key(response_letter_status)
    normalized_revision_status = _evaluation_gate_key(revision_plan_status)
    normalized_provenance_status = _evaluation_gate_key(provenance_gate_status)
    normalized_commitment_status = _evaluation_gate_key(commitment_gate_status)
    normalized_coverage_status = _evaluation_gate_key(coverage_gate_status)
    normalized_external_review_status = _evaluation_gate_key(external_review_status)
    normalized_unresolved_issues = _clean_tuple(unresolved_issue_ids)
    normalized_orphan_commitments = _clean_tuple(orphan_commitment_ids)
    normalized_unprovenanced_responses = _clean_tuple(unprovenanced_response_ids)
    normalized_pending_user_input = _clean_tuple(pending_user_input_ids)

    blockers: list[str] = []
    if normalized_issue_board_status != "complete":
        blockers.append(f"issue_board_{normalized_issue_board_status}")
    if normalized_response_status != "drafted":
        blockers.append(f"response_letter_{normalized_response_status}")
    if normalized_revision_status != "complete":
        blockers.append(f"revision_plan_{normalized_revision_status}")
    if normalized_provenance_status != "pass":
        blockers.append(f"provenance_gate_{normalized_provenance_status}")
    if normalized_commitment_status != "pass":
        blockers.append(f"commitment_gate_{normalized_commitment_status}")
    if normalized_coverage_status != "pass":
        blockers.append(f"coverage_gate_{normalized_coverage_status}")
    if normalized_external_review_status in ("failed", "blocked"):
        blockers.append(f"external_review_{normalized_external_review_status}")
    blockers.extend(f"coverage_missing:{item}" for item in normalized_unresolved_issues)
    blockers.extend(
        f"orphan_commitment:{item}" for item in normalized_orphan_commitments
    )
    blockers.extend(
        f"unprovenanced_response:{item}" for item in normalized_unprovenanced_responses
    )
    blockers.extend(
        f"needs_user_input:{item}" for item in normalized_pending_user_input
    )

    return DeliveryRebuttalReadinessGateProfile(
        schema_version="rh.delivery.rebuttal_readiness_gate.v1",
        status="success" if not blockers else "blocked",
        issue_board_status=normalized_issue_board_status,
        response_letter_status=normalized_response_status,
        revision_plan_status=normalized_revision_status,
        provenance_gate_status=normalized_provenance_status,
        commitment_gate_status=normalized_commitment_status,
        coverage_gate_status=normalized_coverage_status,
        external_review_status=normalized_external_review_status,
        unresolved_issue_ids=normalized_unresolved_issues,
        orphan_commitment_ids=normalized_orphan_commitments,
        unprovenanced_response_ids=normalized_unprovenanced_responses,
        pending_user_input_ids=normalized_pending_user_input,
        issue_status_options=(
            "answered",
            "deferred_intentionally",
            "needs_user_input",
        ),
        required_artifacts=(
            "REBUTTAL_PACKAGE",
            "ISSUE_BOARD",
            "RESPONSE_LETTER",
            "REVISION_PLAN",
            "response_evidence",
            "revision_deltas",
            "camera_ready_replay",
        ),
        provenance_checks=(
            "every_factual_sentence_has_source",
            "no_fabricated_numbers",
            "no_fabricated_citations",
            "new_references_verified",
            "response_sources_are_allowed",
        ),
        commitment_checks=(
            "no_orphan_commitments",
            "letter_promises_match_revision_plan",
            "revision_plan_items_have_issue_ids",
            "future_work_only_is_not_a_paper_edit_promise",
        ),
        coverage_checks=(
            "every_reviewer_concern_resolved",
            "editor_comments_take_precedence",
            "deferred_issues_have_rationale",
            "critical_issues_not_deferred",
        ),
        response_quality_checks=(
            "neutral_professional_tone",
            "no_aggressive_phrasing",
            "no_excessive_apology",
            "batched_external_review_recorded_or_explicitly_deferred",
            "camera_ready_replay_delta_recorded",
        ),
        decision=_rebuttal_readiness_decision(tuple(blockers)),
        public_surface="none",
        runtime_dependency="none",
        blockers=tuple(blockers),
    )


def build_default_delivery_protocol_fixture() -> dict[str, Any]:
    """Build the private RH research delivery protocol fixture."""

    contracts = _all_payload_contracts()
    return {
        "schema_version": "rh.delivery_protocol.v1",
        "status": "local_fixture_only",
        "source_of_truth": "research_harness",
        "public_surface": "none",
        "runtime_dependency": "none",
        "entry_modes": list(REQUIRED_ENTRY_MODES),
        "required_artifacts": list(REQUIRED_ARTIFACTS),
        "boundaries": {boundary: False for boundary in REQUIRED_FALSE_BOUNDARIES},
        "artifact_records": [
            {
                "artifact": artifact,
                "stage": contracts[artifact].stage,
                "gate": contracts[artifact].gate,
                "owner_skill": contracts[artifact].owner_skill,
                "recording_surface": contracts[artifact].recording_surface,
                "source_of_truth": "research_harness",
            }
            for artifact in REQUIRED_ARTIFACTS
        ],
    }


def build_delivery_protocol_contract(
    fixture: Mapping[str, Any],
) -> DeliveryProtocolContract:
    """Normalize and validate the local research delivery protocol fixture."""

    entry_modes = tuple(str(mode) for mode in fixture.get("entry_modes") or ())
    records = tuple(
        _artifact_record(item)
        for item in fixture.get("artifact_records") or ()
        if isinstance(item, Mapping)
    )
    present_artifacts = tuple(record.artifact for record in records)
    missing = _missing_entries(entry_modes, present_artifacts, records)
    boundary_violations = _boundary_violations(fixture)

    return DeliveryProtocolContract(
        schema_version=str(fixture.get("schema_version") or ""),
        source_of_truth=str(fixture.get("source_of_truth") or ""),
        public_surface=str(fixture.get("public_surface") or ""),
        runtime_dependency=str(fixture.get("runtime_dependency") or ""),
        entry_modes=entry_modes,
        records=records,
        missing=missing,
        boundary_violations=boundary_violations,
        status="success" if not missing and not boundary_violations else "error",
    )


def resolve_delivery_protocol_request(
    fixture: Mapping[str, Any],
    *,
    entry_mode: str,
    request: str,
    artifact_states: Mapping[str, str] | None = None,
) -> DeliveryProtocolDecision:
    """Resolve an request to the next RH protocol artifact.

    This is a private self-development contract helper. It performs no IO,
    network access, LLM calls, or artifact writes.
    """

    contract = build_delivery_protocol_contract(fixture)
    normalized_entry_mode = str(entry_mode or "")
    normalized_request = str(request or "").strip()
    states = {str(k): str(v) for k, v in (artifact_states or {}).items()}

    if contract.status != "success":
        return _error_decision(
            normalized_entry_mode,
            normalized_request,
            "invalid_protocol_contract",
        )
    if normalized_entry_mode not in contract.entry_modes:
        return _error_decision(
            normalized_entry_mode,
            normalized_request,
            f"unsupported_entry_mode:{normalized_entry_mode}",
        )

    records_by_artifact = {record.artifact: record for record in contract.records}
    artifact = _resolve_requested_artifact(
        records_by_artifact,
        entry_mode=normalized_entry_mode,
        request=normalized_request,
    )
    if not artifact:
        return _error_decision(
            normalized_entry_mode,
            normalized_request,
            "unknown_protocol_artifact",
        )

    record = records_by_artifact[artifact]
    artifact_state = _artifact_state(states, artifact)
    blockers = _prerequisite_blockers(artifact, states)

    if blockers:
        return _decision(
            normalized_entry_mode,
            normalized_request,
            artifact_state=artifact_state,
            record=record,
            action="satisfy_prerequisites",
            status="blocked",
            blockers=blockers,
        )

    if _is_active_state(artifact_state):
        return _decision(
            normalized_entry_mode,
            normalized_request,
            artifact_state=artifact_state,
            record=record,
            action="reuse_recorded_artifact",
            status="satisfied",
            blockers=(),
        )

    return _decision(
        normalized_entry_mode,
        normalized_request,
        artifact_state=artifact_state,
        record=record,
        action="run_owner_skill_and_record",
        status="ready_to_run",
        blockers=(),
    )


def build_topic_to_proposal_artifact_contracts() -> dict[
    str, DeliveryArtifactPayloadContract
]:
    """Build private payload contracts for the delivery-protocol topic-to-proposal lane."""

    return _build_payload_contracts(TOPIC_TO_PROPOSAL_PAYLOADS)


def build_experiment_to_claims_artifact_contracts() -> dict[
    str, DeliveryArtifactPayloadContract
]:
    """Build private payload contracts for experiment-to-claims artifacts."""

    return _build_payload_contracts(EXPERIMENT_TO_CLAIMS_PAYLOADS)


def build_paper_plan_audit_package_artifact_contracts() -> dict[
    str, DeliveryArtifactPayloadContract
]:
    """Build private payload contracts for paper plan, audit, and package artifacts."""

    return _build_payload_contracts(PAPER_PLAN_AUDIT_PACKAGE_PAYLOADS)


def build_rebuttal_camera_ready_artifact_contracts() -> dict[
    str, DeliveryArtifactPayloadContract
]:
    """Build private payload contracts for rebuttal and camera-ready replay."""

    return _build_payload_contracts(REBUTTAL_CAMERA_READY_PAYLOADS)


def validate_delivery_artifact_payload(
    artifact: str,
    payload: Mapping[str, Any],
) -> DeliveryArtifactPayloadValidation:
    """Validate a private delivery-protocol paper-production artifact payload.

    This helper is deterministic and side-effect free. It does not inspect DB
    state, perform IO, call LLMs, or record artifacts.
    """

    normalized_artifact = str(artifact or "").strip().upper()
    contracts = _all_payload_contracts()
    contract = contracts.get(normalized_artifact)
    if contract is None:
        return DeliveryArtifactPayloadValidation(
            artifact=normalized_artifact,
            schema_version=str(payload.get("schema_version") or ""),
            missing_fields=(),
            forbidden_claim_hits=(),
            boundary_violations=("unknown_artifact",),
            status="error",
        )

    missing_fields = _missing_payload_fields(contract, payload)
    forbidden_claim_hits = _forbidden_claim_hits(contract, payload)
    boundary_violations = _payload_boundary_violations(contract, payload)
    status = (
        "success"
        if not missing_fields and not forbidden_claim_hits and not boundary_violations
        else "error"
    )

    return DeliveryArtifactPayloadValidation(
        artifact=contract.artifact,
        schema_version=str(payload.get("schema_version") or contract.schema_version),
        missing_fields=missing_fields,
        forbidden_claim_hits=forbidden_claim_hits,
        boundary_violations=boundary_violations,
        status=status,
    )


def plan_delivery_artifact_promotion(
    fixture: Mapping[str, Any],
    *,
    entry_mode: str,
    request: str,
    payload: Mapping[str, Any],
    artifact_states: Mapping[str, str] | None = None,
) -> DeliveryArtifactPromotionPlan:
    """Create a dry-run RH artifact recording intent for a valid payload."""

    decision = resolve_delivery_protocol_request(
        fixture,
        entry_mode=entry_mode,
        request=request,
        artifact_states=artifact_states,
    )
    artifact = decision.artifact
    validation = (
        validate_delivery_artifact_payload(artifact, payload) if artifact else None
    )

    if decision.status == "error":
        return _promotion_plan(
            decision=decision,
            validation=validation,
            payload=payload,
            action="clarify_request",
            status="blocked",
            blockers=decision.blockers,
        )

    if decision.status == "blocked":
        return _promotion_plan(
            decision=decision,
            validation=validation,
            payload=payload,
            action=decision.action,
            status="blocked",
            blockers=decision.blockers,
        )

    if validation is None or validation.status != "success":
        return _promotion_plan(
            decision=decision,
            validation=validation,
            payload=payload,
            action="repair_payload",
            status="blocked",
            blockers=_validation_blockers(validation),
        )

    return _promotion_plan(
        decision=decision,
        validation=validation,
        payload=payload,
        action="record_artifact_intent",
        status="ready_to_record",
        blockers=(),
    )


def evaluate_delivery_stage_readiness(
    fixture: Mapping[str, Any],
    *,
    entry_mode: str,
    request: str,
    payload: Mapping[str, Any],
    artifact_states: Mapping[str, str] | None = None,
) -> DeliveryStageReadiness:
    """Evaluate private delivery-protocol readiness without advancing state."""

    decision = resolve_delivery_protocol_request(
        fixture,
        entry_mode=entry_mode,
        request=request,
        artifact_states=artifact_states,
    )
    validation = (
        validate_delivery_artifact_payload(decision.artifact, payload)
        if decision.artifact
        else None
    )

    if decision.status == "satisfied":
        return _stage_readiness(
            decision=decision,
            validation=validation,
            promotion_status="not_needed",
            action=decision.action,
            status="satisfied",
            blockers=_validation_blockers(validation)
            if validation is not None and validation.status != "success"
            else (),
        )

    promotion = plan_delivery_artifact_promotion(
        fixture,
        entry_mode=entry_mode,
        request=request,
        payload=payload,
        artifact_states=artifact_states,
    )
    if promotion.status == "ready_to_record":
        return _stage_readiness(
            decision=decision,
            validation=validation,
            promotion_status=promotion.status,
            action=promotion.action,
            status="ready_to_advance",
            blockers=(),
        )

    return _stage_readiness(
        decision=decision,
        validation=validation,
        promotion_status=promotion.status,
        action=promotion.action,
        status="blocked",
        blockers=promotion.blockers,
    )


def build_delivery_paper_production_snapshot(
    fixture: Mapping[str, Any],
    *,
    artifact_states: Mapping[str, str] | None = None,
    payloads: Mapping[str, Mapping[str, Any]] | None = None,
) -> DeliveryPaperProductionSnapshot:
    """Build a private read-only delivery-protocol paper-production runbook snapshot."""

    contract = build_delivery_protocol_contract(fixture)
    if contract.status != "success":
        return DeliveryPaperProductionSnapshot(
            status="blocked",
            next_artifact="",
            next_action="repair_protocol_contract",
            summary={
                "total": 0,
                "satisfied": 0,
                "ready_to_advance": 0,
                "blocked": 0,
            },
            records=(),
            blockers=tuple(
                [f"missing:{item}" for item in contract.missing]
                + [f"boundary:{item}" for item in contract.boundary_violations]
            ),
        )

    states = {str(key): str(value) for key, value in (artifact_states or {}).items()}
    payload_by_artifact = {
        str(key).strip().upper(): value for key, value in (payloads or {}).items()
    }
    records: list[DeliveryStageReadiness] = []
    first_ready: DeliveryStageReadiness | None = None
    first_blocker: tuple[str, str] | None = None

    for record in contract.records:
        state = _artifact_state(states, record.artifact)
        if _is_active_state(state):
            readiness = evaluate_delivery_stage_readiness(
                fixture,
                entry_mode="protocol_call",
                request=record.artifact,
                payload=payload_by_artifact.get(record.artifact, {}),
                artifact_states=states,
            )
            records.append(readiness)
            continue

        payload = payload_by_artifact.get(record.artifact)
        if payload is None:
            missing_payload_readiness = _missing_payload_readiness(record, state)
            records.append(missing_payload_readiness)
            if first_blocker is None:
                first_blocker = (
                    "provide_payload",
                    *missing_payload_readiness.blockers,
                )
            continue

        readiness = evaluate_delivery_stage_readiness(
            fixture,
            entry_mode="protocol_call",
            request=record.artifact,
            payload=payload,
            artifact_states=states,
        )
        records.append(readiness)
        if readiness.status == "ready_to_advance" and first_ready is None:
            first_ready = readiness
        elif readiness.status == "blocked" and first_blocker is None:
            first_blocker = (readiness.action, *readiness.blockers)

    summary = _snapshot_summary(records)
    if summary["satisfied"] == summary["total"]:
        return DeliveryPaperProductionSnapshot(
            status="complete",
            next_artifact="",
            next_action="none",
            summary=summary,
            records=tuple(records),
            blockers=(),
        )
    if first_ready is not None:
        return DeliveryPaperProductionSnapshot(
            status="in_progress",
            next_artifact=first_ready.artifact,
            next_action=first_ready.action,
            summary=summary,
            records=tuple(records),
            blockers=(),
        )

    return DeliveryPaperProductionSnapshot(
        status="blocked",
        next_artifact="",
        next_action=first_blocker[0] if first_blocker is not None else "none",
        summary=summary,
        records=tuple(records),
        blockers=tuple(first_blocker[1:]) if first_blocker is not None else (),
    )


def _paper_profile_key(value: str) -> str:
    return str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")


def _paper_profile_blockers(
    *,
    discipline: str,
    research_type: str,
    study_design: str,
) -> tuple[str, ...]:
    blockers: list[str] = []
    values = {
        "discipline": discipline,
        "research_type": research_type,
        "study_design": study_design,
    }
    for field in PAPER_PROFILE_REQUIRED_FIELDS:
        if not values[field]:
            blockers.append(f"missing:{field}")

    if not discipline:
        blockers.append("no_silent_stem_default")
    if research_type in ML_RESEARCH_TYPES and not _is_stem_discipline(discipline):
        blockers.append("route_mismatch:empirical_ml_requires_stem_family")
    return tuple(blockers)


def _paper_profile_route_values(
    *,
    discipline: str,
    research_type: str,
    study_design: str,
    paper_type: str,
    target_venue: str,
) -> dict[str, str] | None:
    if discipline in ECOLOGY_DISCIPLINES:
        return {
            "domain_skill": "domain-writing-stem",
            "domain_profile": "STEM_ENGINEERING_WRITING_PROFILE",
            "method_route": "ecology-method-search",
            "reporting_map": "ecology-field-experiment",
            "evidence_rule": "design-and-uncertainty-bounded",
            "venue_profile": target_venue,
        }
    if _is_stem_discipline(discipline):
        return {
            "domain_skill": "domain-writing-stem",
            "domain_profile": "STEM_ENGINEERING_WRITING_PROFILE",
            "method_route": "domain-method-search-stem",
            "reporting_map": "ml-empirical-method"
            if research_type in ML_RESEARCH_TYPES
            else "stem-method-or-system",
            "evidence_rule": "ml-benchmark"
            if research_type in ML_RESEARCH_TYPES or study_design == "benchmark"
            else "stem-reproducible-evidence",
            "venue_profile": target_venue,
        }
    if _is_biomedical_discipline(discipline):
        return {
            "domain_skill": "domain-writing-biomedical",
            "domain_profile": "BIOMEDICAL_WRITING_PROFILE",
            "method_route": "biomedical-method-search",
            "reporting_map": "biomedical-clinical"
            if research_type in ("intervention_study", "diagnostic", "cohort")
            else "biomedical-observational-or-mechanism",
            "evidence_rule": "intervention-and-quasi-experiment"
            if study_design in ("rct", "quasi_experiment", "pre_post")
            else "biomedical-study-design-bounded",
            "venue_profile": target_venue,
        }
    if _is_social_science_discipline(discipline):
        return {
            "domain_skill": "domain-writing-social-science",
            "domain_profile": "SOCIAL_SCIENCE_WRITING_PROFILE",
            "method_route": "social-science-method-search",
            "reporting_map": _social_science_reporting_map(
                research_type=research_type,
                study_design=study_design,
            ),
            "evidence_rule": _social_science_evidence_rule(
                study_design=study_design,
            ),
            "venue_profile": target_venue,
        }
    if _is_humanities_discipline(discipline):
        return {
            "domain_skill": "domain-writing-humanities",
            "domain_profile": "HUMANITIES_WRITING_PROFILE",
            "method_route": "humanities-method-search",
            "reporting_map": "humanities-source-context",
            "evidence_rule": "interpretive-source-grounding",
            "venue_profile": target_venue,
        }
    if _is_law_policy_discipline(discipline):
        return {
            "domain_skill": "domain-writing-law-policy",
            "domain_profile": "LAW_POLICY_WRITING_PROFILE",
            "method_route": "law-policy-method-search",
            "reporting_map": "law-policy-analysis",
            "evidence_rule": "authority-tradeoff-implementation",
            "venue_profile": target_venue,
        }
    if paper_type in ("policy", "position"):
        return {
            "domain_skill": "domain-writing-law-policy",
            "domain_profile": "LAW_POLICY_WRITING_PROFILE",
            "method_route": "law-policy-method-search",
            "reporting_map": "law-policy-analysis",
            "evidence_rule": "authority-tradeoff-implementation",
            "venue_profile": target_venue,
        }
    return None


# Submission-constraint overlay per venue family. Keys are resolved by
# ``_venue_family`` from the normalized venue string. Each overlay is the
# deterministic set of constraints a delivery-protocol paper plan must honor for that
# family; unknown venues never fall through to a default (see
# ``build_delivery_venue_overlay``).
_VENUE_FAMILY_OVERLAYS: dict[str, dict[str, Any]] = {
    "ml_conference": {
        "review_model": "double_blind",
        "anonymization_required": True,
        "format_family": "latex-two-column",
        "required_declarations": (
            "reproducibility_statement",
            "limitations",
            "broader_impacts",
        ),
    },
    "nlp_conference": {
        "review_model": "double_blind",
        "anonymization_required": True,
        "format_family": "latex-two-column",
        "required_declarations": (
            "limitations",
            "ethics_statement",
            "reproducibility_statement",
        ),
    },
    "systems_conference": {
        "review_model": "double_blind",
        "anonymization_required": True,
        "format_family": "latex-two-column",
        "required_declarations": (
            "artifact_availability",
            "ethics_statement",
        ),
    },
    "general_science_journal": {
        "review_model": "single_blind",
        "anonymization_required": False,
        "format_family": "journal-single-column",
        "required_declarations": (
            "data_availability",
            "competing_interests",
            "author_contributions",
        ),
    },
    "clinical_journal": {
        "review_model": "single_blind",
        "anonymization_required": False,
        "format_family": "journal-single-column",
        "required_declarations": (
            "ethics_approval",
            "trial_registration",
            "competing_interests",
            "data_availability",
        ),
    },
    "nature_partner_journal": {
        "review_model": "single_blind",
        "anonymization_required": False,
        "format_family": "journal-single-column",
        "required_declarations": (
            "data_availability",
            "code_availability",
            "ethics_approval",
            "competing_interests",
            "author_contributions",
        ),
    },
    "workshop": {
        "review_model": "double_blind",
        "anonymization_required": True,
        "format_family": "latex-two-column",
        "required_declarations": ("limitations",),
    },
    "environmental_science_journal": {
        "review_model": "single_blind",
        "anonymization_required": False,
        "format_family": "journal-single-column",
        "required_declarations": (
            "data_availability",
            "competing_interests",
            "author_contributions",
        ),
    },
    "earth_science_journal": {
        "review_model": "single_blind",
        "anonymization_required": False,
        "format_family": "journal-single-column",
        "required_declarations": (
            "data_availability",
            "code_availability",
            "competing_interests",
        ),
    },
    "energy_engineering_journal": {
        "review_model": "single_blind",
        "anonymization_required": False,
        "format_family": "journal-single-column",
        "required_declarations": (
            "data_availability",
            "code_availability",
            "competing_interests",
        ),
    },
    "engineering_journal": {
        "review_model": "single_blind",
        "anonymization_required": False,
        "format_family": "journal-single-column",
        "required_declarations": (
            "data_availability",
            "code_availability",
            "competing_interests",
        ),
    },
    "life_science_journal": {
        "review_model": "single_blind",
        "anonymization_required": False,
        "format_family": "journal-single-column",
        "required_declarations": (
            "data_availability",
            "competing_interests",
            "ethics_statement",
        ),
    },
    "neuroscience_journal": {
        "review_model": "single_blind",
        "anonymization_required": False,
        "format_family": "journal-single-column",
        "required_declarations": (
            "data_availability",
            "competing_interests",
            "ethics_statement",
        ),
    },
    "social_science_journal": {
        "review_model": "single_blind",
        "anonymization_required": False,
        "format_family": "journal-single-column",
        "required_declarations": (
            "data_availability",
            "competing_interests",
            "author_contributions",
            "ethics_statement",
        ),
    },
}

# Venue tokens (matched as substrings of the normalized venue key) mapped to a
# family. Order matters: a "workshop" at a host conference (e.g. "ICLR Workshop
# on Agents") is a workshop, so that token is checked before host-conference
# tokens that would otherwise claim it.
_VENUE_FAMILY_TOKENS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("workshop",), "workshop"),
    (
        (
            "neurips",
            "nips",
            "icml",
            "iclr",
            "kdd",
            "aaai",
            "ijcai",
            "cvpr",
            "iccv",
            "eccv",
            "wacv",
            "ccf_a",
        ),
        "ml_conference",
    ),
    (("acl", "emnlp", "naacl", "coling", "eacl", "tacl"), "nlp_conference"),
    (
        (
            "sosp",
            "osdi",
            "nsdi",
            "sigcomm",
            "usenix",
            "eurosys",
            "asplos",
            "isca",
            "micro",
            "fast",
            "atc",
        ),
        "systems_conference",
    ),
    (("nature", "science_journal", "pnas", "cell"), "general_science_journal"),
    (("npj",), "nature_partner_journal"),
    (
        ("clinical_journal", "jama", "lancet", "nejm", "bmj", "plos_medicine"),
        "clinical_journal",
    ),
    (
        (
            "environmental_research_letters",
            "environmental_research",
            "environmental_science",
            "environment",
        ),
        "environmental_science_journal",
    ),
    (
        (
            "journal_of_hydrometeorology",
            "hydrometeorology",
            "hydrology",
            "meteorology",
            "climate",
            "geophysical",
            "earth_science",
        ),
        "earth_science_journal",
    ),
    (
        (
            "applied_energy",
            "energy_and_buildings",
            "energy_policy",
            "renewable_energy",
            "energy",
        ),
        "energy_engineering_journal",
    ),
    (
        (
            "pattern_recognition_letters",
            "pattern_recognition",
            "ieee",
            "acm",
            "elsevier_engineering",
        ),
        "engineering_journal",
    ),
    (
        (
            "bioinformatics",
            "nucleic_acids_research",
            "plos_biology",
            "bmc_biology",
            "genome_biology",
            # Ecology / environmental-science journals write like life science
            # (IMRaD + field statistics, data-availability declarations).
            "global_change_biology",
            "functional_ecology",
            "journal_of_ecology",
            "ecology_letters",
            "molecular_ecology",
            "new_phytologist",
            "plant_and_soil",
            "agricultural_and_forest_meteorology",
            "science_of_the_total_environment",
        ),
        "life_science_journal",
    ),
    (
        (
            "humanities_and_social_sciences_communications",
            "humanities_social_sciences_communications",
            "humanities_and_social_sciences",
            "social_sciences_communications",
            "social_science",
            "social_sciences",
            "humanities_social",
        ),
        "social_science_journal",
    ),
    (
        (
            "network_neuroscience",
            "neuroscience",
            "brain",
            "neuroimage",
        ),
        "neuroscience_journal",
    ),
)


def _venue_family(venue_key: str) -> str:
    for tokens, family in _VENUE_FAMILY_TOKENS:
        if any(token in venue_key for token in tokens):
            return family
    return "unknown"


def _social_science_reporting_map(*, research_type: str, study_design: str) -> str:
    if research_type == "survey_correlational":
        return "psychology-survey-correlational"
    if study_design == "observational":
        return "social-science-observational"
    if study_design == "panel":
        return "social-science-panel"
    if study_design in {"quasi_experiment", "natural_experiment"}:
        return "social-science-quasi-experimental"
    return "social-science-method-reporting"


def _social_science_evidence_rule(*, study_design: str) -> str:
    if study_design == "cross_sectional":
        return "cross-sectional-survey"
    if study_design == "observational":
        return "observational-spatiotemporal-association"
    if study_design == "panel":
        return "panel-identification-bounded"
    return "design-and-identification-bounded"


def _empty_venue_overlay(
    target_venue: str, blockers: tuple[str, ...]
) -> DeliveryVenueOverlay:
    return DeliveryVenueOverlay(
        schema_version="rh.delivery.venue_overlay.v1",
        status="blocked",
        target_venue=target_venue,
        venue_family="unknown",
        review_model="unknown",
        anonymization_required=False,
        format_family="unknown",
        required_declarations=(),
        public_surface="none",
        runtime_dependency="none",
        blockers=blockers,
    )


def _domain_method_search_values(
    *,
    discipline: str,
    research_type: str,
    study_design: str,
    paper_type: str,
    target_venue: str,
    domain_skill: str,
) -> dict[str, tuple[str, ...] | str] | None:
    if discipline in ECOLOGY_DISCIPLINES:
        return {
            "method_route": "ecology-method-search",
            "search_route": "ecology-evidence-search",
            "search_strategies": (
                "species_system_anchor_search",
                "trait_mechanism_search",
                "treatment_gradient_design_search",
                "ecology_meta_analysis_positioning",
            ),
            "method_requirements": (
                "species_or_system_boundary_required",
                "experimental_design_replication_required",
                "effect_size_or_uncertainty_required",
                "site_climate_context_required",
                "no_clinical_framing",
            ),
            "baseline_anchor_fields": (
                "species_or_system",
                "treatment",
                "response_trait",
                "design",
                "site_context",
            ),
            "evidence_table_schema": (
                "study",
                "year",
                "system",
                "species",
                "treatment",
                "response",
                "effect",
                "site",
            ),
            "excluded_defaults": (
                "ml-baseline-search",
                "github-code-baseline-required",
                "clinical-trial-default",
            ),
        }
    if _is_stem_discipline(discipline) and research_type in ML_RESEARCH_TYPES:
        return {
            "method_route": "domain-method-search-stem",
            "search_route": "ml-baseline-search",
            "search_strategies": (
                "recent_sota_reverse_search",
                "code_available_baseline_search",
                "citation_network_baseline_search",
            ),
            "method_requirements": (
                "mandatory_interpretable_baseline",
                "recent_baseline_window",
                "dataset_metric_alignment",
                "no_data_leakage",
                "seed_and_split_reporting",
            ),
            "baseline_anchor_fields": (
                "task",
                "dataset",
                "metric",
                "method",
                "code_availability",
                "source_table_or_figure",
            ),
            "evidence_table_schema": (
                "method",
                "year",
                "venue",
                "dataset",
                "metric",
                "value",
                "source_table_or_figure",
            ),
            "excluded_defaults": (
                "no_silent_stem_default",
                "no_median_split_for_continuous_outcomes",
                "no_cherry_picked_seed",
            ),
        }
    if discipline in PSYCHOLOGY_DISCIPLINES or (
        _is_social_science_discipline(discipline)
        and research_type == "survey_correlational"
    ):
        return {
            "method_route": "psychology-method-search",
            "search_route": "psychology-variable-scale-search",
            "search_strategies": (
                "variable_combination_search",
                "scale_provenance_search",
                "meta_analysis_positioning",
            ),
            "method_requirements": (
                "scale_reliability_validity",
                "effect_size_reporting",
                "sample_population_boundary",
                "no_cross_sectional_causal_language",
                "multiple_comparison_control",
            ),
            "baseline_anchor_fields": (
                "variables",
                "scale",
                "population",
                "sample_size",
                "effect_size",
                "analysis_method",
            ),
            "evidence_table_schema": (
                "study",
                "year",
                "sample_size",
                "population",
                "scale",
                "variable",
                "effect_size",
                "method",
            ),
            "excluded_defaults": (
                "ml-baseline-search",
                "github-code-baseline-required",
                "baseline_ablation_rhetoric",
            ),
        }
    if discipline in EDUCATION_DISCIPLINES and research_type == "intervention_study":
        return {
            "method_route": "education-method-search-path-2",
            "search_route": "education-intervention-effect-search",
            "search_strategies": (
                "intervention_effect_anchor_search",
                "construct_measure_search",
                "education_meta_analysis_search",
                "venue_keyword_search",
            ),
            "method_requirements": (
                "effect_size_required",
                "construct_reliability_required",
                "control_group_or_limitation",
                "treatment_fidelity_required",
                "triangulation_plan",
            ),
            "baseline_anchor_fields": (
                "intervention_type",
                "construct_measure",
                "student_level",
                "design",
                "control_group",
                "effect_size",
            ),
            "evidence_table_schema": (
                "study",
                "year",
                "intervention",
                "sample_size",
                "construct",
                "measure",
                "design",
                "effect_size",
                "venue",
            ),
            "excluded_defaults": (
                "path_1_ml_default",
                "accuracy_as_intervention_evidence",
                "no_silent_stem_default",
            ),
        }
    if _is_social_science_discipline(discipline):
        return {
            "method_route": "social-science-method-search",
            "search_route": "social-science-evidence-search",
            "search_strategies": (
                "theory_construct_search",
                "operationalization_search",
                "population_context_search",
                "identification_strategy_search",
            ),
            "method_requirements": (
                "construct_operationalization_required",
                "sample_or_case_boundary_required",
                "identification_strategy_required",
                "uncertainty_or_robustness_required",
                "no_unwarranted_causal_language",
            ),
            "baseline_anchor_fields": (
                "theory",
                "construct",
                "population_or_case",
                "identification_strategy",
                "spatiotemporal_unit",
            ),
            "evidence_table_schema": (
                "study",
                "year",
                "context",
                "construct",
                "data_source",
                "method",
                "spatiotemporal_unit",
                "main_finding",
            ),
            "excluded_defaults": (
                "ml-baseline-search",
                "github-code-baseline-required",
                "metric_benchmark_default",
            ),
        }
    if _is_humanities_discipline(discipline):
        return {
            "method_route": "humanities-method-search",
            "search_route": "humanities-source-context-search",
            "search_strategies": (
                "corpus_archive_search",
                "theory_lens_search",
                "nearby_interpretive_debate_search",
            ),
            "method_requirements": (
                "source_context_required",
                "archive_or_corpus_boundary",
                "counter_reading_tracking",
            ),
            "baseline_anchor_fields": (
                "corpus_or_archive",
                "source_context",
                "theory_lens",
                "scholarly_debate",
            ),
            "evidence_table_schema": (
                "source",
                "date_or_period",
                "archive_or_corpus",
                "context",
                "interpretive_claim",
            ),
            "excluded_defaults": (
                "ml-baseline-search",
                "metric_benchmark_default",
                "baseline_ablation_rhetoric",
            ),
        }
    if _is_law_policy_discipline(discipline) or paper_type in ("policy", "position"):
        return {
            "method_route": "law-policy-method-search",
            "search_route": "law-policy-authority-search",
            "search_strategies": (
                "authority_precedent_search",
                "policy_evidence_search",
                "implementation_case_search",
            ),
            "method_requirements": (
                "jurisdiction_required",
                "authority_hierarchy_required",
                "stakeholder_tradeoff_required",
                "implementation_feasibility_required",
            ),
            "baseline_anchor_fields": (
                "jurisdiction",
                "authority",
                "policy_arena",
                "stakeholder",
                "implementation_path",
            ),
            "evidence_table_schema": (
                "authority_or_source",
                "jurisdiction",
                "policy_issue",
                "method",
                "policy_implication",
            ),
            "excluded_defaults": (
                "ml-baseline-search",
                "metric_benchmark_default",
                "no_silent_stem_default",
            ),
        }
    if domain_skill:
        return {
            "method_route": f"{domain_skill}-method-search",
            "search_route": f"{domain_skill}-evidence-search",
            "search_strategies": (
                "domain_evidence_search",
                "method_anchor_search",
                "venue_profile_search",
            ),
            "method_requirements": (
                "paper_profile_required",
                "discipline_specific_method_boundary",
                "evidence_strength_alignment",
            ),
            "baseline_anchor_fields": (
                "discipline",
                "research_type",
                "study_design",
                "evidence_anchor",
            ),
            "evidence_table_schema": (
                "source",
                "year",
                "method",
                "evidence_anchor",
                "claim_boundary",
            ),
            "excluded_defaults": ("no_silent_stem_default",),
        }
    return None


def _empty_domain_method_search_values() -> dict[str, tuple[str, ...] | str]:
    return {
        "method_route": "",
        "search_route": "",
        "search_strategies": (),
        "method_requirements": (),
        "baseline_anchor_fields": (),
        "evidence_table_schema": (),
        "excluded_defaults": (),
    }


def _evaluation_gate_values(
    *,
    discipline: str,
    research_type: str,
    paper_type: str,
    domain_skill: str,
) -> dict[str, tuple[str, ...] | str]:
    if _is_stem_discipline(discipline):
        return {
            "evaluation_route": "ml-ai-data-evaluation",
            "scoring_axes": (
                "Higher",
                "Faster",
                "Stronger",
                "Cheaper",
                "Broader",
            ),
            "pilot_catalog": (
                "subset_training_run",
                "single_metric_reproduction",
                "baseline_delta_check",
                "data_leakage_probe",
            ),
            "baseline_modes": (
                "extract-only",
                "github-replication",
                "official-code-replication",
            ),
        }
    if discipline in PSYCHOLOGY_DISCIPLINES or discipline in EDUCATION_DISCIPLINES:
        return {
            "evaluation_route": "psy-edu-framing-evaluation",
            "scoring_axes": (
                "Theoretical Framing",
                "Construct Validity",
                "Mechanism Specificity",
                "Population & Setting",
                "Discussion Engagement & Venue Fit",
            ),
            "pilot_catalog": (
                "literature_deepening",
                "construct_theorization",
                "mechanism_mapping",
                "public_dataset_pilot_analysis",
                "questionnaire_pilot",
                "interview_pilot",
            ),
            "baseline_modes": (
                "extract-only",
                "public-dataset-analysis",
                "questionnaire-pilot",
                "interview-pilot",
            ),
        }
    if _is_biomedical_discipline(discipline):
        return {
            "evaluation_route": "biomedical-evidence-evaluation",
            "scoring_axes": (
                "Clinical Or Biological Rationale",
                "Population Or Model Fit",
                "Study Design Validity",
                "Ethics And Data Access",
                "Effect Or Mechanism Evidence",
            ),
            "pilot_catalog": (
                "protocol_feasibility_check",
                "public_dataset_signal_analysis",
                "cohort_availability_check",
                "mechanism_evidence_review",
            ),
            "baseline_modes": (
                "extract-only",
                "public-dataset-analysis",
                "cohort-access-check",
            ),
        }
    if _is_humanities_discipline(discipline):
        return {
            "evaluation_route": "humanities-problem-anchor-evaluation",
            "scoring_axes": (
                "Source Corpus Fit",
                "Interpretive Problem Clarity",
                "Theory Lens Fit",
                "Counter Reading Coverage",
                "Contribution To Debate",
            ),
            "pilot_catalog": (
                "archive_access_check",
                "corpus_sample_reading",
                "theory_lens_probe",
                "counter_reading_map",
            ),
            "baseline_modes": (
                "extract-only",
                "archive-access-check",
                "corpus-sampling",
            ),
        }
    if _is_law_policy_discipline(discipline) or paper_type in ("policy", "position"):
        return {
            "evaluation_route": "law-policy-authority-evaluation",
            "scoring_axes": (
                "Authority Fit",
                "Jurisdiction Boundary",
                "Normative Problem Clarity",
                "Stakeholder Tradeoff",
                "Implementation Feasibility",
            ),
            "pilot_catalog": (
                "authority_access_check",
                "jurisdiction_scope_review",
                "implementation_case_probe",
                "stakeholder_tradeoff_map",
            ),
            "baseline_modes": (
                "extract-only",
                "authority-access-check",
                "case-comparison",
            ),
        }
    return {
        "evaluation_route": f"{domain_skill or 'unknown'}-evaluation",
        "scoring_axes": (
            "Problem Anchor Clarity",
            "Evidence Access",
            "Method Fit",
            "Feasibility",
            "Venue Fit",
        ),
        "pilot_catalog": (
            "evidence_access_check",
            "method_anchor_probe",
            "scope_reduction_probe",
        ),
        "baseline_modes": ("extract-only",),
    }


def _experiment_grounding_values(
    *,
    discipline: str,
    research_type: str,
    study_design: str,
    paper_type: str,
    domain_skill: str,
) -> dict[str, tuple[str, ...] | str]:
    if _is_stem_discipline(discipline):
        return {
            "experiment_route": "ml-ai-data-experiment-grounding"
            if research_type in ML_RESEARCH_TYPES or study_design == "benchmark"
            else "stem-experiment-grounding",
            "plan_alignment_checks": (
                "paper_profile_selected",
                "experiment_goal_claim_alignment",
                "dataset_baseline_metric_alignment",
                "success_and_failure_criteria",
                "ablation_and_seed_plan",
            ),
            "reporting_requirements": (
                "dataset_split_license_access",
                "baseline_comparator",
                "primary_metric_and_threshold",
                "seeds_and_split_reporting",
                "leakage_checks",
                "reproducibility_outputs",
            ),
        }
    if discipline in EDUCATION_DISCIPLINES and research_type == "intervention_study":
        return {
            "experiment_route": "education-intervention-grounding",
            "plan_alignment_checks": (
                "paper_profile_selected",
                "experiment_goal_claim_alignment",
                "intervention_control_alignment",
                "outcome_measure_fidelity",
                "effect_size_ci_plan",
            ),
            "reporting_requirements": (
                "setting_participants_assignment",
                "comparison_or_control_condition",
                "validated_outcome_measure",
                "treatment_fidelity_required",
                "effect_size_ci_exact_p",
                "attrition_missingness_sensitivity",
            ),
        }
    if discipline in PSYCHOLOGY_DISCIPLINES or (
        _is_social_science_discipline(discipline)
        and research_type == "survey_correlational"
    ):
        return {
            "experiment_route": "social-science-experiment-grounding",
            "plan_alignment_checks": (
                "paper_profile_selected",
                "experiment_goal_claim_alignment",
                "construct_variable_scale_grounding",
                "population_sampling_alignment",
                "causal_language_boundary",
            ),
            "reporting_requirements": (
                "construct_scale_item_source",
                "reliability_validity_target",
                "covariate_model_comparison",
                "effect_size_ci_exact_p",
                "missing_data_exclusion_rule",
                "cross_sectional_causal_limit",
            ),
        }
    if _is_biomedical_discipline(discipline):
        return {
            "experiment_route": "biomedical-experiment-grounding",
            "plan_alignment_checks": (
                "paper_profile_selected",
                "experiment_goal_claim_alignment",
                "population_or_model_fit",
                "exposure_intervention_outcome_alignment",
                "ethics_and_data_access_boundary",
            ),
            "reporting_requirements": (
                "population_or_model_system",
                "intervention_exposure_outcome",
                "cohort_or_trial_design",
                "effect_size_ci_safety",
                "ethics_data_access_status",
                "clinical_or_biological_limitations",
            ),
        }
    if _is_humanities_discipline(discipline):
        return {
            "experiment_route": "humanities-source-grounding",
            "plan_alignment_checks": (
                "paper_profile_selected",
                "experiment_goal_claim_alignment",
                "corpus_archive_source_alignment",
                "theory_lens_fit",
                "counter_reading_coverage",
            ),
            "reporting_requirements": (
                "corpus_or_archive_boundary",
                "source_context",
                "interpretive_claim_map",
                "counter_reading_tracking",
                "audit_trail",
            ),
        }
    if _is_law_policy_discipline(discipline) or paper_type in ("policy", "position"):
        return {
            "experiment_route": "law-policy-authority-grounding",
            "plan_alignment_checks": (
                "paper_profile_selected",
                "experiment_goal_claim_alignment",
                "authority_jurisdiction_alignment",
                "policy_evidence_fit",
                "stakeholder_tradeoff_coverage",
            ),
            "reporting_requirements": (
                "authority_hierarchy",
                "jurisdiction_scope",
                "implementation_case",
                "stakeholder_tradeoff",
                "normative_boundary",
            ),
        }
    return {
        "experiment_route": f"{domain_skill or 'unknown'}-experiment-grounding",
        "plan_alignment_checks": (
            "paper_profile_selected",
            "experiment_goal_claim_alignment",
            "domain_method_fit",
            "evidence_reporting_alignment",
        ),
        "reporting_requirements": (
            "domain_specific_data_source",
            "domain_specific_comparator",
            "domain_specific_outcome",
            "claim_strength_boundary",
        ),
    }


def _result_to_claim_analysis_values(
    *,
    discipline: str,
    research_type: str,
    study_design: str,
    paper_type: str,
    domain_skill: str,
) -> dict[str, tuple[str, ...] | str]:
    common_checks = (
        "expected_vs_actual_result_table",
        "statistical_and_practical_significance_separated",
        "claim_strength_boundary",
        "limitations_and_negative_results",
        "competing_evidence_addressed",
        "no_exploratory_positioning",
    )
    if _is_stem_discipline(discipline):
        return {
            "analysis_route": "ml-ai-data-result-to-claim-analysis"
            if research_type in ML_RESEARCH_TYPES or study_design == "benchmark"
            else "stem-result-to-claim-analysis",
            "maximum_allowed_claim_strength": "B_empirical_strong",
            "analysis_checks": common_checks
            + (
                "baseline_delta_check",
                "relative_delta_table",
                "seed_and_split_robustness",
                "ablation_or_sensitivity_context",
            ),
            "disallowed_claim_language": (
                "universal_or_mechanism_proof_language",
                "tested_outside_dataset_scope",
                "solve_or_first_claim_without_novelty_proof",
                "practical_significance_without_effect_context",
            ),
        }
    if discipline in PSYCHOLOGY_DISCIPLINES or (
        _is_social_science_discipline(discipline)
        and research_type == "survey_correlational"
    ):
        return {
            "analysis_route": "social-science-result-to-claim-analysis",
            "maximum_allowed_claim_strength": "C_empirical_limited",
            "analysis_checks": common_checks
            + (
                "construct_measure_result_mapping",
                "effect_size_ci_exact_p",
                "cross_sectional_causal_limit",
                "alternative_explanation_check",
            ),
            "disallowed_claim_language": (
                "causal_effect_language",
                "temporal_precedence_language",
                "mechanism_proof_language",
                "population_generalization_without_sampling_support",
            ),
        }
    if discipline in EDUCATION_DISCIPLINES and research_type == "intervention_study":
        return {
            "analysis_route": "education-intervention-result-to-claim-analysis",
            "maximum_allowed_claim_strength": "B_empirical_strong",
            "analysis_checks": common_checks
            + (
                "intervention_effect_size_context",
                "treatment_fidelity_and_attrition",
                "construct_validity_check",
                "technology_wrapper_overclaim_check",
            ),
            "disallowed_claim_language": (
                "causal_effect_without_design_identification",
                "broad_generalization_without_setting_boundary",
                "learning_gain_without_measure_validity",
                "policy_recommendation_without_tradeoff_evidence",
            ),
        }
    if _is_biomedical_discipline(discipline):
        return {
            "analysis_route": "biomedical-result-to-claim-analysis",
            "maximum_allowed_claim_strength": "B_empirical_strong",
            "analysis_checks": common_checks
            + (
                "population_or_model_result_boundary",
                "effect_size_ci_safety_context",
                "clinical_or_biological_mechanism_boundary",
                "ethics_data_access_limitations",
            ),
            "disallowed_claim_language": (
                "clinical_efficacy_without_trial_support",
                "mechanism_proof_without_mechanistic_evidence",
                "safety_claim_without_safety_data",
                "population_transfer_without_boundary",
            ),
        }
    if _is_humanities_discipline(discipline):
        return {
            "analysis_route": "humanities-source-to-claim-analysis",
            "maximum_allowed_claim_strength": "C_empirical_limited",
            "analysis_checks": common_checks
            + (
                "source_context_to_interpretive_claim",
                "counter_reading_addressed",
                "corpus_boundary_stated",
                "theory_lens_scope",
            ),
            "disallowed_claim_language": (
                "population_prevalence_language",
                "causal_effect_language",
                "exhaustive_historical_proof",
                "archive_scope_overgeneralization",
            ),
        }
    if _is_law_policy_discipline(discipline) or paper_type in ("policy", "position"):
        return {
            "analysis_route": "law-policy-authority-to-claim-analysis",
            "maximum_allowed_claim_strength": "C_empirical_limited",
            "analysis_checks": common_checks
            + (
                "authority_hierarchy_to_claim",
                "jurisdiction_scope_boundary",
                "stakeholder_tradeoff_evidence",
                "implementation_case_limitations",
            ),
            "disallowed_claim_language": (
                "universal_legal_rule_language",
                "policy_effect_without_implementation_evidence",
                "jurisdiction_transfer_without_boundary",
                "stakeholder_tradeoff_omission",
            ),
        }
    return {
        "analysis_route": f"{domain_skill or 'unknown'}-result-to-claim-analysis",
        "maximum_allowed_claim_strength": "C_empirical_limited",
        "analysis_checks": common_checks
        + (
            "domain_specific_result_boundary",
            "evidence_strength_alignment",
        ),
        "disallowed_claim_language": (
            "unsupported_positive_claim",
            "scope_free_generalization",
        ),
    }


def _experiment_grounding_decision(
    *,
    blockers: tuple[str, ...],
    result_state: str,
) -> str:
    if any(blocker.startswith("impact_report_") for blocker in blockers):
        return "block_claims_until_impact_report_bound"
    if any(
        blocker.startswith(prefix)
        for blocker in blockers
        for prefix in (
            "pre_deploy_code_review",
            "deploy_blockers",
            "variable_grounding",
            "codebook",
        )
    ):
        return "block_deploy_until_code_review_passes"
    if blockers:
        return "repair_experiment_grounding"
    if result_state == "completed":
        return "ready_for_claim_extraction"
    return "ready_for_experiment_execution"


def _result_to_claim_analysis_decision(blockers: tuple[str, ...]) -> str:
    if not blockers:
        return "ready_for_claim_safe_writing"
    return "block_claims_until_result_analysis_passes"


def _skeleton_source_integrity_values(
    *,
    discipline: str,
    research_type: str,
    study_design: str,
    paper_type: str,
    domain_skill: str,
) -> dict[str, tuple[str, ...] | str]:
    default_sections = (
        "Introduction",
        "Related Work or Literature Review",
        "Methods or Approach",
        "Results or Findings",
        "Discussion",
        "Conclusion",
    )
    default_trace_checks = (
        "claim_to_source_trace",
        "logic_skeleton_cell_trace",
        "contribution_to_section_trace",
        "limitation_challenge_module_chain",
        "unsupported_claim_inventory_empty",
    )
    if paper_type in ("review", "survey") or study_design == "review":
        return {
            "integrity_route": "review-skeleton-source-integrity",
            "required_section_groups": (
                "Introduction",
                "Background or Search Strategy",
                "Taxonomy or Synthesis",
                "Open Problems or Discussion",
                "Conclusion",
            ),
            "source_trace_checks": (
                *default_trace_checks,
                "search_strategy_to_source_pool_trace",
                "taxonomy_cell_to_paper_set_trace",
            ),
        }
    if _is_humanities_discipline(discipline):
        return {
            "integrity_route": "humanities-source-context-integrity",
            "required_section_groups": (
                "Introduction",
                "Source Context or Background",
                "Interpretive Analysis",
                "Counter Reading or Discussion",
                "Conclusion",
            ),
            "source_trace_checks": (
                *default_trace_checks,
                "source_context_trace",
                "interpretive_claim_to_primary_source_trace",
                "counter_reading_trace",
            ),
        }
    if _is_law_policy_discipline(discipline) or paper_type in ("policy", "position"):
        return {
            "integrity_route": "law-policy-authority-integrity",
            "required_section_groups": (
                "Introduction",
                "Legal or Policy Background",
                "Analysis",
                "Implementation or Tradeoffs",
                "Conclusion",
            ),
            "source_trace_checks": (
                *default_trace_checks,
                "authority_hierarchy_trace",
                "jurisdiction_scope_trace",
                "stakeholder_tradeoff_trace",
            ),
        }
    if discipline in PSYCHOLOGY_DISCIPLINES or _is_social_science_discipline(
        discipline
    ):
        return {
            "integrity_route": "social-science-skeleton-source-integrity",
            "required_section_groups": default_sections,
            "source_trace_checks": (
                *default_trace_checks,
                "construct_operationalization_trace",
                "scale_or_measure_source_trace",
                "effect_size_claim_trace",
                "causal_language_boundary_trace",
            ),
        }
    if _is_biomedical_discipline(discipline):
        return {
            "integrity_route": "biomedical-skeleton-source-integrity",
            "required_section_groups": default_sections,
            "source_trace_checks": (
                *default_trace_checks,
                "population_intervention_outcome_trace",
                "ethics_data_access_trace",
                "effect_or_mechanism_claim_trace",
            ),
        }
    if _is_stem_discipline(discipline):
        return {
            "integrity_route": "default-empirical-skeleton-source-integrity"
            if research_type in (*ML_RESEARCH_TYPES, "empirical")
            else "stem-skeleton-source-integrity",
            "required_section_groups": default_sections,
            "source_trace_checks": (
                *default_trace_checks,
                "dataset_baseline_metric_trace",
                "ablation_claim_trace",
                "reproducibility_artifact_trace",
            ),
        }
    return {
        "integrity_route": f"{domain_skill or 'unknown'}-skeleton-source-integrity",
        "required_section_groups": default_sections,
        "source_trace_checks": default_trace_checks,
    }


def _skeleton_source_integrity_decision(blockers: tuple[str, ...]) -> str:
    if not blockers:
        return "ready_for_presubmission_audit"
    if any(
        blocker.startswith(("citation_", "bib_doi_verification_", "table_ref_"))
        for blocker in blockers
    ):
        return "block_package_until_source_integrity_passes"
    if any(
        blocker.startswith(("skeleton_", "source_trace_", "logic_chain_"))
        for blocker in blockers
    ):
        return "repair_manuscript_structure_and_trace"
    return "block_package_until_source_integrity_passes"


def _presubmission_severity_decision(blockers: tuple[str, ...]) -> str:
    if not blockers:
        return "ready_for_publication_pack"
    if any(blocker.startswith("critical_") for blocker in blockers):
        return "block_submission_until_critical_fixed"
    if any(blocker.startswith("integrity_") for blocker in blockers):
        return "repair_presubmission_integrity_gate"
    return "block_submission_until_qa_passes"


def _rebuttal_readiness_decision(blockers: tuple[str, ...]) -> str:
    if not blockers:
        return "ready_for_rebuttal_package"
    if all(blocker.startswith("needs_user_input") for blocker in blockers):
        return "wait_for_user_input_before_rebuttal"
    return "block_rebuttal_until_gates_pass"


def _evaluation_gate_decision(
    *,
    blockers: tuple[str, ...],
    warnings: tuple[str, ...],
    scorecard: Mapping[str, int],
    feasibility_risks: Mapping[str, str],
    scoring_axes: tuple[str, ...],
) -> tuple[str, bool]:
    if "critical_fatal_flaw" in blockers or "too_many_fatal_flaws" in blockers:
        return "reject_direction", False
    if blockers:
        return "block_until_problem_anchor_and_access", False
    if any(value == "red" for value in feasibility_risks.values()):
        return "reject_direction", False
    if any(value == "yellow" for value in feasibility_risks.values()):
        return "run_signal_pilot", True
    if "soft_gate:psy_edu_axes_1_3_below_5" in warnings:
        return "run_signal_pilot", True

    top_scores = [scorecard.get(axis, 0) for axis in scoring_axes]
    if sum(1 for score in top_scores if score >= 8) >= 2:
        return "advance_full_experiment", False
    return "run_signal_pilot", True


def _has_critical_fatal_flaw(fatal_flaws: tuple[str, ...]) -> bool:
    return any("critical" in flaw.casefold() for flaw in fatal_flaws)


def _psy_edu_soft_gate_fires(
    discipline: str,
    scorecard: Mapping[str, int],
) -> bool:
    if discipline not in (*PSYCHOLOGY_DISCIPLINES, *EDUCATION_DISCIPLINES):
        return False
    for axis in (
        "Theoretical Framing",
        "Construct Validity",
        "Mechanism Specificity",
    ):
        if scorecard.get(axis, 10) <= 4:
            return True
    return False


def _evaluation_gate_key(value: str) -> str:
    return str(value or "").strip().casefold().replace(" ", "_").replace("-", "_")


def _evaluation_mode_key(value: str) -> str:
    return str(value or "").strip().casefold().replace(" ", "-").replace("_", "-")


def _clean_tuple(values: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    return tuple(str(value).strip() for value in values if str(value).strip())


def _claim_strength_rank(value: str) -> int:
    order = {
        "A_confirmed": 0,
        "B_empirical_strong": 1,
        "C_empirical_limited": 2,
        "D_exploratory": 3,
        "E_speculative": 4,
        "F_unsupported_or_blocked": 5,
    }
    return order.get(str(value or "").strip(), len(order))


def _empty_paper_profile_route() -> dict[str, str]:
    return {
        "domain_skill": "",
        "domain_profile": "",
        "method_route": "",
        "reporting_map": "",
        "evidence_rule": "",
        "venue_profile": "",
    }


def _is_stem_discipline(discipline: str) -> bool:
    return discipline in STEM_DISCIPLINES


def _is_biomedical_discipline(discipline: str) -> bool:
    return discipline in BIOMEDICAL_DISCIPLINES


def _is_social_science_discipline(discipline: str) -> bool:
    return discipline in SOCIAL_SCIENCE_DISCIPLINES


def _is_humanities_discipline(discipline: str) -> bool:
    return discipline in HUMANITIES_DISCIPLINES


def _is_law_policy_discipline(discipline: str) -> bool:
    return discipline in LAW_POLICY_DISCIPLINES


def _build_payload_contracts(
    specs: Mapping[str, Mapping[str, Any]],
) -> dict[str, DeliveryArtifactPayloadContract]:
    return {
        artifact: DeliveryArtifactPayloadContract(
            artifact=artifact,
            schema_version=str(spec["schema_version"]),
            artifact_role="advisory_compiled_view",
            stage=str(spec["stage"]),
            gate=str(spec["gate"]),
            owner_skill=str(spec["owner_skill"]),
            recording_surface="orchestrator_record_artifact",
            public_surface="none",
            runtime_dependency="none",
            required_fields=tuple(str(field) for field in spec["required_fields"]),
            forbidden_claims=tuple(str(claim) for claim in spec["forbidden_claims"]),
        )
        for artifact, spec in specs.items()
    }


def _all_payload_contracts() -> dict[str, DeliveryArtifactPayloadContract]:
    return {
        **build_topic_to_proposal_artifact_contracts(),
        **build_experiment_to_claims_artifact_contracts(),
        **build_paper_plan_audit_package_artifact_contracts(),
        **build_rebuttal_camera_ready_artifact_contracts(),
    }


def _missing_payload_fields(
    contract: DeliveryArtifactPayloadContract,
    payload: Mapping[str, Any],
) -> tuple[str, ...]:
    missing: list[str] = []
    for field in contract.required_fields:
        if field not in payload:
            missing.append(field)
    return tuple(missing)


def _forbidden_claim_hits(
    contract: DeliveryArtifactPayloadContract,
    payload: Mapping[str, Any],
) -> tuple[str, ...]:
    hits: list[str] = []
    for claim in contract.forbidden_claims:
        if _payload_contains_forbidden_claim(payload, claim):
            hits.append(claim)
    return tuple(hits)


def _payload_contains_forbidden_claim(payload: Mapping[str, Any], claim: str) -> bool:
    value = payload.get(claim)
    if _truthy_forbidden_value(value):
        return True

    for field in ("flags", "claim_flags", "claims", "forbidden_claims"):
        if _nested_contains_claim(payload.get(field), claim):
            return True
    return False


def _nested_contains_claim(value: Any, claim: str) -> bool:
    if isinstance(value, str):
        return value == claim
    if isinstance(value, Mapping):
        return any(
            key == claim
            and _truthy_forbidden_value(item)
            or _nested_contains_claim(item, claim)
            for key, item in value.items()
        )
    if isinstance(value, list | tuple | set | frozenset):
        return any(_nested_contains_claim(item, claim) for item in value)
    return False


def _truthy_forbidden_value(value: Any) -> bool:
    if value is None or value is False:
        return False
    if value == "" or value == () or value == [] or value == {}:
        return False
    return True


def _payload_boundary_violations(
    contract: DeliveryArtifactPayloadContract,
    payload: Mapping[str, Any],
) -> tuple[str, ...]:
    violations: list[str] = []
    expected = {
        "schema_version": contract.schema_version,
        "recording_surface": contract.recording_surface,
        "public_surface": contract.public_surface,
        "runtime_dependency": contract.runtime_dependency,
    }
    for key, expected_value in expected.items():
        if str(payload.get(key) or "") != expected_value:
            violations.append(key)
    return tuple(violations)


def _promotion_plan(
    *,
    decision: DeliveryProtocolDecision,
    validation: DeliveryArtifactPayloadValidation | None,
    payload: Mapping[str, Any],
    action: str,
    status: str,
    blockers: tuple[str, ...],
) -> DeliveryArtifactPromotionPlan:
    return DeliveryArtifactPromotionPlan(
        entry_mode=decision.entry_mode,
        request=decision.request,
        artifact=decision.artifact,
        stage=decision.stage,
        gate=decision.gate,
        owner_skill=decision.owner_skill,
        recording_surface=decision.recording_surface,
        payload_schema_version=validation.schema_version
        if validation is not None
        else str(payload.get("schema_version") or ""),
        payload_summary=_payload_summary(payload),
        validation_status=validation.status if validation is not None else "not_run",
        action=action,
        status=status,
        dry_run=True,
        blockers=blockers,
    )


def _stage_readiness(
    *,
    decision: DeliveryProtocolDecision,
    validation: DeliveryArtifactPayloadValidation | None,
    promotion_status: str,
    action: str,
    status: str,
    blockers: tuple[str, ...],
) -> DeliveryStageReadiness:
    return DeliveryStageReadiness(
        entry_mode=decision.entry_mode,
        request=decision.request,
        artifact=decision.artifact,
        stage=decision.stage,
        gate=decision.gate,
        owner_skill=decision.owner_skill,
        recording_surface=decision.recording_surface,
        action=action,
        status=status,
        validation_status=validation.status if validation is not None else "not_run",
        promotion_status=promotion_status,
        blockers=blockers,
    )


def _missing_payload_readiness(
    record: DeliveryArtifactRecord,
    artifact_state: str,
) -> DeliveryStageReadiness:
    return DeliveryStageReadiness(
        entry_mode="protocol_call",
        request=record.artifact,
        artifact=record.artifact,
        stage=record.stage,
        gate=record.gate,
        owner_skill=record.owner_skill,
        recording_surface=record.recording_surface,
        action="provide_payload",
        status="blocked",
        validation_status="not_run",
        promotion_status="blocked",
        blockers=(f"missing_payload:{record.artifact}",)
        if artifact_state == "missing"
        else (f"{artifact_state}:{record.artifact}",),
    )


def _snapshot_summary(
    records: tuple[DeliveryStageReadiness, ...] | list[DeliveryStageReadiness],
) -> dict[str, int]:
    summary = {
        "total": len(records),
        "satisfied": 0,
        "ready_to_advance": 0,
        "blocked": 0,
    }
    for record in records:
        if record.status in summary:
            summary[record.status] += 1
    return summary


def _validation_blockers(
    validation: DeliveryArtifactPayloadValidation | None,
) -> tuple[str, ...]:
    if validation is None:
        return ("unknown_artifact",)
    return tuple(
        [f"missing_field:{field}" for field in validation.missing_fields]
        + [f"forbidden_claim:{claim}" for claim in validation.forbidden_claim_hits]
        + [f"boundary:{field}" for field in validation.boundary_violations]
    )


def _payload_summary(payload: Mapping[str, Any]) -> dict[str, int]:
    return {
        "required_field_count": _required_field_count(payload),
        "evidence_anchor_count": _count_items(payload.get("evidence_anchors")),
        "source_artifact_count": _count_items(payload.get("source_artifacts")),
        "promotion_blocker_count": _count_items(payload.get("promotion_blockers")),
        "missing_evidence_warning_count": _count_items(
            payload.get("missing_evidence_warnings")
        ),
    }


def _required_field_count(payload: Mapping[str, Any]) -> int:
    ignored = {
        "schema_version",
        "recording_surface",
        "public_surface",
        "runtime_dependency",
    }
    return len([key for key in payload if key not in ignored])


def _count_items(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, Mapping):
        return len(value)
    if isinstance(value, str):
        return 1 if value else 0
    if isinstance(value, list | tuple | set | frozenset):
        return len(value)
    return 1


def _artifact_record(item: Mapping[str, Any]) -> DeliveryArtifactRecord:
    return DeliveryArtifactRecord(
        artifact=str(item.get("artifact") or ""),
        stage=str(item.get("stage") or ""),
        gate=str(item.get("gate") or ""),
        owner_skill=str(item.get("owner_skill") or ""),
        recording_surface=str(item.get("recording_surface") or ""),
        source_of_truth=str(item.get("source_of_truth") or ""),
    )


def _resolve_requested_artifact(
    records_by_artifact: Mapping[str, DeliveryArtifactRecord],
    *,
    entry_mode: str,
    request: str,
) -> str:
    if entry_mode == "protocol_call":
        requested = request.strip().upper().replace("-", "_").replace(" ", "_")
        if requested in records_by_artifact:
            return requested
        for artifact in records_by_artifact:
            if artifact.lower() == request.strip().lower():
                return artifact
        return ""

    return _infer_human_artifact(request, records_by_artifact)


def _infer_human_artifact(
    request: str,
    records_by_artifact: Mapping[str, DeliveryArtifactRecord],
) -> str:
    normalized = request.casefold()
    for hints, artifact in HUMAN_REQUEST_HINTS:
        if artifact in records_by_artifact and any(
            hint in normalized for hint in hints
        ):
            return artifact
    return ""


def _artifact_state(states: Mapping[str, str], artifact: str) -> str:
    return states.get(artifact) or "missing"


def _is_active_state(state: str) -> bool:
    return state.casefold() in ACTIVE_ARTIFACT_STATES


def _prerequisite_blockers(
    artifact: str,
    states: Mapping[str, str],
) -> tuple[str, ...]:
    blockers: list[str] = []
    for prerequisite in PROTOCOL_PREREQUISITES.get(artifact, ()):
        state = _artifact_state(states, prerequisite)
        if state == "missing":
            blockers.append(f"missing:{prerequisite}")
        elif not _is_active_state(state):
            blockers.append(f"{state}:{prerequisite}")
    return tuple(blockers)


def _decision(
    entry_mode: str,
    request: str,
    *,
    artifact_state: str,
    record: DeliveryArtifactRecord,
    action: str,
    status: str,
    blockers: tuple[str, ...],
) -> DeliveryProtocolDecision:
    return DeliveryProtocolDecision(
        entry_mode=entry_mode,
        request=request,
        inferred_from=entry_mode,
        artifact=record.artifact,
        stage=record.stage,
        gate=record.gate,
        owner_skill=record.owner_skill,
        recording_surface=record.recording_surface,
        artifact_state=artifact_state,
        action=action,
        status=status,
        blockers=blockers,
    )


def _error_decision(
    entry_mode: str,
    request: str,
    blocker: str,
) -> DeliveryProtocolDecision:
    return DeliveryProtocolDecision(
        entry_mode=entry_mode,
        request=request,
        inferred_from=entry_mode,
        artifact="",
        stage="",
        gate="",
        owner_skill="",
        recording_surface="",
        artifact_state="unknown",
        action="clarify_request",
        status="error",
        blockers=(blocker,),
    )


def _missing_entries(
    entry_modes: tuple[str, ...],
    present_artifacts: tuple[str, ...],
    records: tuple[DeliveryArtifactRecord, ...] = (),
) -> tuple[str, ...]:
    missing: list[str] = []
    for mode in REQUIRED_ENTRY_MODES:
        if mode not in entry_modes:
            missing.append(f"entry_mode:{mode}")
    for artifact in REQUIRED_ARTIFACTS:
        if artifact not in present_artifacts:
            missing.append(f"artifact:{artifact}")
    for record in records:
        if not record.owner_skill:
            missing.append(f"owner_skill:{record.artifact}")
    return tuple(missing)


def _boundary_violations(fixture: Mapping[str, Any]) -> tuple[str, ...]:
    boundaries = fixture.get("boundaries")
    if not isinstance(boundaries, Mapping):
        return ("boundaries",)

    violations: list[str] = []
    for key in REQUIRED_FALSE_BOUNDARIES:
        if boundaries.get(key) is not False:
            violations.append(key)
    if fixture.get("source_of_truth") != "research_harness":
        violations.append("source_of_truth")
    if fixture.get("public_surface") != "none":
        violations.append("public_surface")
    if fixture.get("runtime_dependency") != "none":
        violations.append("runtime_dependency")
    return tuple(violations)
