"""Private paper-production runtime context builder.

This module prepares deterministic context for the RH paper-production lane.
It does not run search, call LLMs/providers, write artifacts, or advance
orchestrator stages. Public transports can wrap this later, after the runtime
lane has local evidence.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from research_harness.paper_source_clients import KEYLESS_SOURCES
from research_harness._selfdev.delivery_protocol import (
    build_delivery_experiment_grounding_profile,
    build_delivery_result_to_claim_analysis_profile,
    build_delivery_venue_overlay,
    build_domain_method_search_profile,
    build_paper_plan_audit_package_artifact_contracts,
    build_paper_profile_route,
)


SCHEMA_VERSION = "rh.paper_production_runtime_context.v1"
TOPIC_VENUE_CONTRACT_SCHEMA_VERSION = "rh.topic_venue_contract.v1"
STATE_MACHINE_SCHEMA_VERSION = "rh.paper_production_state_machine.v1"
READINESS_REPORT_SCHEMA_VERSION = "rh.paper_production_readiness_report.v1"
PAPER_PRODUCTION_COMPLETION_CONDITION = (
    "final_bundle_pdf_and_publication_pack_pass_all_quality_gates"
)
ACTIVE_ARTIFACT_STATES = frozenset(
    {"active", "current", "present", "ready", "recorded"}
)
PASSING_GATE_STATES = frozenset({"pass", "passed", "success", "ready", "satisfied"})
BLOCKING_GATE_STATES = frozenset({"fail", "failed", "blocked", "error"})
# Every source build_provider_suite can return: the local cache, the keyless
# public sources, and SPC when installed. Naming a source that the suite does
# not build filters real sources out of every guarded search, so the list is
# derived from the suite's own source table. SPC's fallback ignores it anyway.
GUARDED_PROVIDER_ALLOWLIST = (
    "papervault",
    *(name for name, _reason in KEYLESS_SOURCES),
    "spc",
)
GUARDED_PROVIDER_DENYLIST = ("pasa",)
GUARDED_PER_PROVIDER_LIMIT = 30


@dataclass(frozen=True)
class PaperProductionStage:
    stage_id: str
    objective: str
    rh_capabilities: tuple[str, ...]
    protocol_capabilities: tuple[str, ...]
    required_artifacts: tuple[str, ...]
    quality_gates: tuple[str, ...]
    output_status: str = "required"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["rh_capabilities"] = list(self.rh_capabilities)
        payload["protocol_capabilities"] = list(self.protocol_capabilities)
        payload["required_artifacts"] = list(self.required_artifacts)
        payload["quality_gates"] = list(self.quality_gates)
        return payload


@dataclass(frozen=True)
class PaperProductionStateMachine:
    schema_version: str
    status: str
    completion_condition: str
    stages: tuple[PaperProductionStage, ...]
    external_action_boundaries: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "completion_condition": self.completion_condition,
            "stage_count": len(self.stages),
            "stages": [stage.to_dict() for stage in self.stages],
            "external_action_boundaries": list(self.external_action_boundaries),
        }


@dataclass(frozen=True)
class PaperProductionStageReadiness:
    stage_id: str
    status: str
    required_artifacts: tuple[str, ...]
    present_artifacts: tuple[str, ...]
    missing_artifacts: tuple[str, ...]
    quality_gates: tuple[str, ...]
    passed_gates: tuple[str, ...]
    failed_gates: tuple[str, ...]
    unverified_gates: tuple[str, ...]
    next_action: str
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "required_artifacts",
            "present_artifacts",
            "missing_artifacts",
            "quality_gates",
            "passed_gates",
            "failed_gates",
            "unverified_gates",
            "blockers",
        ):
            payload[key] = list(payload[key])
        return payload


@dataclass(frozen=True)
class PaperProductionReadinessReport:
    schema_version: str
    status: str
    completion_condition: str
    next_stage: str
    next_action: str
    summary: Mapping[str, int]
    stages: tuple[PaperProductionStageReadiness, ...]
    artifact_states: Mapping[str, str]
    gate_states: Mapping[str, str]
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "completion_condition": self.completion_condition,
            "next_stage": self.next_stage,
            "next_action": self.next_action,
            "summary": dict(self.summary),
            "stages": [stage.to_dict() for stage in self.stages],
            "artifact_states": dict(self.artifact_states),
            "gate_states": dict(self.gate_states),
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class PaperProductionEvidencePlan:
    schema_version: str
    status: str
    stage_id: str
    query: str
    provider_mode: str
    search_parameters: Mapping[str, Any]
    tool_sequence: tuple[str, ...]
    minimum_acceptance: Mapping[str, Any]
    expected_artifacts: tuple[str, ...]
    guardrails: tuple[str, ...]
    blockers: tuple[str, ...]
    # Advisory, domain-aware provider ordering (2026-07-05 cross-domain PDF
    # feedback): which sources to trust/screen first for this discipline.
    # Does not change the guarded allowlist.
    provider_preference: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "stage_id": self.stage_id,
            "query": self.query,
            "provider_mode": self.provider_mode,
            "search_parameters": dict(self.search_parameters),
            "tool_sequence": list(self.tool_sequence),
            "minimum_acceptance": dict(self.minimum_acceptance),
            "expected_artifacts": list(self.expected_artifacts),
            "guardrails": list(self.guardrails),
            "blockers": list(self.blockers),
            "provider_preference": list(self.provider_preference),
        }


@dataclass(frozen=True)
class PaperPlanGateProfile:
    schema_version: str
    status: str
    stage_id: str
    required_artifact: str
    required_reports: tuple[str, ...]
    required_upstream_profiles: tuple[str, ...]
    drafting_enabled: bool
    promotion_action: str
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "stage_id": self.stage_id,
            "required_artifact": self.required_artifact,
            "required_reports": list(self.required_reports),
            "required_upstream_profiles": list(self.required_upstream_profiles),
            "drafting_enabled": self.drafting_enabled,
            "promotion_action": self.promotion_action,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class PaperProductionClosurePlan:
    schema_version: str
    status: str
    stage_ids: tuple[str, ...]
    sections_to_draft: tuple[str, ...]
    latex_template: str
    publication_components: tuple[str, ...]
    quality_gates: tuple[str, ...]
    tool_sequence: tuple[str, ...]
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "stage_ids": list(self.stage_ids),
            "sections_to_draft": list(self.sections_to_draft),
            "latex_template": self.latex_template,
            "publication_components": list(self.publication_components),
            "quality_gates": list(self.quality_gates),
            "tool_sequence": list(self.tool_sequence),
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class TopicVenueContract:
    schema_version: str
    status: str
    topic: str
    target_venue: str
    discipline: str
    research_type: str
    study_design: str
    paper_type: str
    audience: str
    page_budget: str
    anonymity_policy: str
    user_visible_promises: tuple[str, ...]
    non_goals: tuple[str, ...]
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["user_visible_promises"] = list(self.user_visible_promises)
        payload["non_goals"] = list(self.non_goals)
        payload["blockers"] = list(self.blockers)
        return payload


@dataclass(frozen=True)
class PaperPlanRequirements:
    artifact: str
    schema_version: str
    owner_skill: str
    required_fields: tuple[str, ...]
    forbidden_claims: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["required_fields"] = list(self.required_fields)
        payload["forbidden_claims"] = list(self.forbidden_claims)
        return payload


@dataclass(frozen=True)
class PaperProductionRuntimeContext:
    schema_version: str
    status: str
    topic_venue_contract: TopicVenueContract
    venue_overlay: dict[str, Any]
    paper_profile: dict[str, Any]
    domain_method_search_profile: dict[str, Any]
    paper_plan_requirements: PaperPlanRequirements
    state_machine: PaperProductionStateMachine
    readiness_report: PaperProductionReadinessReport
    evidence_acquisition_plan: PaperProductionEvidencePlan
    experiment_grounding_profile: dict[str, Any]
    result_to_claim_analysis_profile: dict[str, Any]
    paper_plan_gate_profile: PaperPlanGateProfile
    write_to_pdf_closure_plan: PaperProductionClosurePlan
    next_actions: tuple[dict[str, str], ...]
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "status": self.status,
            "topic_venue_contract": self.topic_venue_contract.to_dict(),
            "venue_overlay": dict(self.venue_overlay),
            "paper_profile": dict(self.paper_profile),
            "domain_method_search_profile": dict(self.domain_method_search_profile),
            "paper_plan_requirements": self.paper_plan_requirements.to_dict(),
            "state_machine": self.state_machine.to_dict(),
            "readiness_report": self.readiness_report.to_dict(),
            "evidence_acquisition_plan": self.evidence_acquisition_plan.to_dict(),
            "experiment_grounding_profile": dict(self.experiment_grounding_profile),
            "result_to_claim_analysis_profile": dict(
                self.result_to_claim_analysis_profile
            ),
            "paper_plan_gate_profile": self.paper_plan_gate_profile.to_dict(),
            "write_to_pdf_closure_plan": self.write_to_pdf_closure_plan.to_dict(),
            "next_actions": [dict(item) for item in self.next_actions],
            "blockers": list(self.blockers),
        }

    def to_stage_context(self) -> dict[str, Any]:
        """Return keys that can be merged into auto-runner stage_context.

        The returned context deliberately carries paper-plan requirements, not
        an active ``paper_plan``. Section drafting should receive ``paper_plan``
        only after PW05 has produced a real plan and logic reports.
        """

        return {
            "topic_description": self.topic_venue_contract.topic,
            "query": self.topic_venue_contract.topic,
            "target_venue": self.topic_venue_contract.target_venue,
            "venue": self.topic_venue_contract.target_venue,
            "target_profile": self.topic_venue_contract.target_venue,
            "topic_venue_contract": self.topic_venue_contract.to_dict(),
            "venue_overlay": dict(self.venue_overlay),
            "paper_profile": dict(self.paper_profile),
            "domain_method_search_profile": dict(self.domain_method_search_profile),
            "paper_plan_requirements": self.paper_plan_requirements.to_dict(),
            "paper_production_state_machine": self.state_machine.to_dict(),
            "paper_production_completion_condition": (
                self.state_machine.completion_condition
            ),
            "paper_production_readiness_report": self.readiness_report.to_dict(),
            "paper_production_next_stage": self.readiness_report.next_stage,
            "paper_production_next_action": self.readiness_report.next_action,
            "paper_production_evidence_plan": (
                self.evidence_acquisition_plan.to_dict()
            ),
            "max_results": self.evidence_acquisition_plan.search_parameters[
                "max_results"
            ],
            "auto_ingest": self.evidence_acquisition_plan.search_parameters[
                "auto_ingest"
            ],
            "local_only": self.evidence_acquisition_plan.search_parameters[
                "local_only"
            ],
            "per_provider_limit": self.evidence_acquisition_plan.search_parameters[
                "per_provider_limit"
            ],
            "provider_allowlist": list(
                self.evidence_acquisition_plan.search_parameters["provider_allowlist"]
            ),
            "provider_denylist": list(
                self.evidence_acquisition_plan.search_parameters["provider_denylist"]
            ),
            "tier_filter": self.evidence_acquisition_plan.search_parameters[
                "tier_filter"
            ],
            "venue_filter": self.evidence_acquisition_plan.search_parameters[
                "venue_filter"
            ],
            "required_baseline_families": (
                self.evidence_acquisition_plan.minimum_acceptance[
                    "required_baseline_families"
                ]
            ),
            "experiment_grounding_profile": dict(self.experiment_grounding_profile),
            "result_to_claim_analysis_profile": dict(
                self.result_to_claim_analysis_profile
            ),
            "paper_plan_gate_profile": self.paper_plan_gate_profile.to_dict(),
            "paper_production_closure_plan": self.write_to_pdf_closure_plan.to_dict(),
            "sections_to_draft": list(self.write_to_pdf_closure_plan.sections_to_draft),
            "template": self.write_to_pdf_closure_plan.latex_template,
            "publication_components": list(
                self.write_to_pdf_closure_plan.publication_components
            ),
            "record_artifact": True,
            "citation_quota": 24,
            "output_dir": "paper-production",
            "paper_plan_ready": self.paper_plan_gate_profile.drafting_enabled,
            "strict_evidence": True,
            "next_actions": [dict(item) for item in self.next_actions],
            "paper_production_context_status": self.status,
            "paper_production_context_blockers": list(self.blockers),
        }


def build_paper_production_runtime_context(
    *,
    topic: str,
    target_venue: str,
    discipline: str = "",
    research_type: str = "",
    study_design: str = "",
    paper_type: str = "",
    audience: str = "",
    page_budget: str = "",
    local_only: bool = False,
) -> PaperProductionRuntimeContext:
    """Build deterministic runtime context for topic-to-PDF paper production."""

    normalized_topic = _clean_text(topic)
    normalized_venue = _clean_text(target_venue)
    inferred = _infer_profile_defaults(
        topic=normalized_topic,
        target_venue=normalized_venue,
        discipline=discipline,
        research_type=research_type,
        study_design=study_design,
        paper_type=paper_type,
    )
    venue_overlay = build_delivery_venue_overlay(
        target_venue=normalized_venue,
    )
    contract = TopicVenueContract(
        schema_version=TOPIC_VENUE_CONTRACT_SCHEMA_VERSION,
        status="success",
        topic=normalized_topic,
        target_venue=normalized_venue,
        discipline=inferred["discipline"],
        research_type=inferred["research_type"],
        study_design=inferred["study_design"],
        paper_type=inferred["paper_type"],
        audience=_clean_text(audience) or _default_audience(normalized_venue),
        page_budget=_clean_text(page_budget) or "venue_overlay_or_user_supplied",
        anonymity_policy=(
            "anonymous"
            if venue_overlay.anonymization_required
            else "venue_or_user_supplied"
        ),
        user_visible_promises=(
            "ground claims in ingested papers, recorded evidence, or explicit blockers",
            "preserve target-venue constraints before final bundle assembly",
            "produce a PDF only after citation, source, and package gates run",
        ),
        non_goals=(
            "do not invent literature, citations, or experiment results",
            "do not claim submission readiness without QA evidence",
            "do not perform external submission or credential mutation",
        ),
        blockers=_contract_blockers(normalized_topic, normalized_venue),
    )
    paper_profile = build_paper_profile_route(
        discipline=inferred["discipline"],
        research_type=inferred["research_type"],
        study_design=inferred["study_design"],
        paper_type=inferred["paper_type"],
        target_venue=normalized_venue,
    )
    method_profile = build_domain_method_search_profile(
        discipline=inferred["discipline"],
        research_type=inferred["research_type"],
        study_design=inferred["study_design"],
        paper_type=inferred["paper_type"],
        target_venue=normalized_venue,
    )
    blockers = _context_blockers(
        contract=contract,
        venue_blockers=tuple(venue_overlay.blockers),
        paper_profile_blockers=tuple(paper_profile.blockers),
        method_profile_blockers=tuple(method_profile.blockers),
    )
    status = "ready_for_evidence_acquisition" if not blockers else "blocked"
    state_machine = build_paper_production_state_machine()
    readiness_report = build_paper_production_readiness_report(
        artifact_states=_initial_artifact_states(
            status=status,
            state_machine=state_machine,
        )
    )
    evidence_plan = build_paper_production_evidence_plan(
        topic=normalized_topic,
        target_venue=normalized_venue,
        venue_overlay=venue_overlay.to_dict(),
        domain_method_search_profile=method_profile.to_dict(),
        status=status,
        local_only=local_only,
    )
    experiment_profile = build_default_experiment_grounding_profile(
        paper_profile=paper_profile.to_dict(),
    )
    result_to_claim_profile = build_default_result_to_claim_analysis_profile(
        paper_profile=paper_profile.to_dict(),
    )
    paper_plan_gate_profile = build_paper_plan_gate_profile(
        experiment_grounding_profile=experiment_profile,
        result_to_claim_analysis_profile=result_to_claim_profile,
        has_active_paper_plan=False,
    )
    closure_plan = build_write_to_pdf_closure_plan(
        venue_overlay=venue_overlay.to_dict(),
        paper_plan_gate_profile=paper_plan_gate_profile,
    )

    return PaperProductionRuntimeContext(
        schema_version=SCHEMA_VERSION,
        status=status,
        topic_venue_contract=contract,
        venue_overlay=venue_overlay.to_dict(),
        paper_profile=paper_profile.to_dict(),
        domain_method_search_profile=method_profile.to_dict(),
        paper_plan_requirements=_paper_plan_requirements(),
        state_machine=state_machine,
        readiness_report=readiness_report,
        evidence_acquisition_plan=evidence_plan,
        experiment_grounding_profile=experiment_profile,
        result_to_claim_analysis_profile=result_to_claim_profile,
        paper_plan_gate_profile=paper_plan_gate_profile,
        write_to_pdf_closure_plan=closure_plan,
        next_actions=_next_actions(status),
        blockers=blockers,
    )


def build_paper_production_state_machine() -> PaperProductionStateMachine:
    """Return the product-grade paper-production stage manifest."""

    return PaperProductionStateMachine(
        schema_version=STATE_MACHINE_SCHEMA_VERSION,
        status="product_chain_manifest",
        completion_condition=PAPER_PRODUCTION_COMPLETION_CONDITION,
        stages=(
            PaperProductionStage(
                stage_id="PW01_TOPIC_AND_VENUE_CONTRACT",
                objective="Freeze topic, target venue, domain, paper type, promises, and non-goals.",
                rh_capabilities=(
                    "topics",
                    "orchestrator_run",
                    "auto_runner_checkpoint",
                    "venue_overlay",
                    "paper_profile_route",
                ),
                protocol_capabilities=(
                    "protocol_call",
                    "human_in_loop_call",
                    "topic_venue_contract",
                    "venue_constraint_gate",
                ),
                required_artifacts=(
                    "topic_venue_contract",
                    "venue_overlay",
                    "PAPER_PROFILE",
                    "DOMAIN_METHOD_SEARCH_PROFILE",
                ),
                quality_gates=(
                    "topic_present",
                    "target_venue_present",
                    "paper_profile_resolved",
                    "external_action_denied_by_default",
                ),
            ),
            PaperProductionStage(
                stage_id="PW02_EVIDENCE_ACQUISITION_AND_READING",
                objective="Acquire, verify, ingest, summarize, and index source literature.",
                rh_capabilities=(
                    "paper_search",
                    "paper_ingest",
                    "paper_verify",
                    "paper_summarize",
                    "paper_sync",
                    "research_wiki",
                    "topic_knowledge",
                ),
                protocol_capabilities=(
                    "source_acquisition_protocol",
                    "evidence_inventory",
                    "wiki_context_pack",
                ),
                required_artifacts=(
                    "paper_pool",
                    "source_inventory",
                    "paper_summary_set",
                    "wiki_context_pack.v1",
                ),
                quality_gates=(
                    "real_or_guarded_evidence_required",
                    "paper_ids_required",
                    "citation_metadata_verified",
                    "weak_evidence_blockers_recorded",
                ),
            ),
            PaperProductionStage(
                stage_id="PW03_GAP_BASELINE_NOVELTY_VALIDATION",
                objective="Prove the paper direction against baselines, gaps, and novelty risks.",
                rh_capabilities=(
                    "claim_extract",
                    "baseline_identify",
                    "gap_detect",
                    "evidence_gating",
                    "adversarial_review",
                ),
                protocol_capabilities=(
                    "IDEA_REPORT",
                    "RESEARCH_PROPOSAL",
                    "EVALUATION_GATE_PROFILE",
                    "PROBLEM_ANCHOR",
                ),
                required_artifacts=(
                    "claim_graph",
                    "baseline_matrix",
                    "gap_report",
                    "EVALUATION_GATE_PROFILE",
                    "PROBLEM_ANCHOR",
                ),
                quality_gates=(
                    "baseline_coverage_required",
                    "novelty_risk_reviewed",
                    "problem_anchor_frozen",
                    "unsupported_gap_claims_blocked",
                ),
            ),
            PaperProductionStage(
                stage_id="PW04_EXPERIMENT_AND_RESULT_TO_CLAIM",
                objective="Ground experiments or validation evidence and convert results to bounded claims.",
                rh_capabilities=(
                    "code_generate",
                    "code_validate",
                    "experiment_run",
                    "verified_registry_build",
                    "verified_registry_check",
                    "consistency_check",
                ),
                protocol_capabilities=(
                    "EXPERIMENT_GROUNDING_PROFILE",
                    "EXPERIMENT_PLAN",
                    "IMPACT_REPORT",
                    "CLAIMS_FROM_RESULTS",
                    "RESULT_TO_CLAIM_ANALYSIS_PROFILE",
                ),
                required_artifacts=(
                    "EXPERIMENT_GROUNDING_PROFILE",
                    "EXPERIMENT_PLAN",
                    "experiment_result_pack.v1",
                    "IMPACT_REPORT",
                    "CLAIMS_FROM_RESULTS",
                    "RESULT_TO_CLAIM_ANALYSIS_PROFILE",
                ),
                quality_gates=(
                    "experiment_goal_matches_problem_anchor",
                    "pre_deploy_code_review_zero_blockers",
                    "result_status_explicit",
                    "claim_strength_not_overstated",
                ),
            ),
            PaperProductionStage(
                stage_id="PW05_PAPER_PLAN_AND_LOGIC_GATES",
                objective="Promote an active paper plan only after evidence, profile, and logic gates pass.",
                rh_capabilities=(
                    "writing_architecture",
                    "outline_generate",
                    "writing_logic_gate_runtime",
                    "fine_logic_audit",
                ),
                protocol_capabilities=(
                    "PAPER_PLAN",
                    "CORE_CLAIM_CONTRACT",
                    "ARGUMENT_TREE",
                    "CLAIMS_EVIDENCE_MATRIX",
                ),
                required_artifacts=(
                    "PAPER_PLAN",
                    "CORE_CLAIM_CONTRACT",
                    "ARGUMENT_TREE",
                    "TERM_REGISTRY",
                    "PROMISE_REALIZATION_MATRIX",
                    "PARAGRAPH_INTENT_TREE",
                    "manuscript_logic_gate_report",
                    "fine_logic_audit_report",
                    "claims_evidence_matrix",
                ),
                quality_gates=(
                    "paper_plan_profile_aligned",
                    "logic_gate_passed",
                    "claims_evidence_matrix_complete",
                    "paper_plan_promoted_before_drafting",
                ),
            ),
            PaperProductionStage(
                stage_id="PW06_SECTION_DRAFTING_AND_REVISION",
                objective="Draft, review, and revise every manuscript section under evidence and domain constraints.",
                rh_capabilities=(
                    "section_draft",
                    "section_review",
                    "section_revise",
                    "run_section_loop",
                    "domain_writing_profiles",
                    "writing_checks",
                ),
                protocol_capabilities=(
                    "DOMAIN_WRITING_PROFILE",
                    "section_evidence_pack",
                    "unsupported_sentence_blockers",
                ),
                required_artifacts=(
                    "DOMAIN_WRITING_PROFILE",
                    "section_draft_pack",
                    "section_review_report",
                    "section_revision_history",
                    "draft_pack",
                ),
                quality_gates=(
                    "active_paper_plan_required",
                    "strict_evidence_required",
                    "unsupported_claims_blocked",
                    "section_review_threshold_met",
                ),
            ),
            PaperProductionStage(
                stage_id="PW07_FIGURE_TABLE_SOURCE_AND_CITATION_INTEGRITY",
                objective="Verify figures, tables, source trace, citations, and BibTeX before final assembly.",
                rh_capabilities=(
                    "figure_suite_plan",
                    "figure_plan",
                    "figure_suite_render",
                    "figure_generate",
                    "figure_quality",
                    "citation_verify",
                    "paper_verify_numbers",
                    "evidence_trace",
                    "provenance_summary",
                ),
                protocol_capabilities=(
                    "SKELETON_SOURCE_INTEGRITY_PROFILE",
                    "source_trace",
                    "citation_integrity",
                    "bib_doi_verification",
                ),
                required_artifacts=(
                    "figure_suite_plan",
                    "figure_plan",
                    "SKELETON_SOURCE_INTEGRITY_PROFILE",
                    "citation_sanitization_report",
                    "source_trace",
                    "bib_doi_verification",
                ),
                quality_gates=(
                    "no_placeholder_figures",
                    "no_dangling_citations",
                    "source_trace_complete",
                    "bib_metadata_verified",
                ),
            ),
            PaperProductionStage(
                stage_id="PW08_LATEX_FINAL_BUNDLE_AND_PDF",
                objective="Compile a venue-shaped LaTeX/PDF bundle from verified manuscript artifacts.",
                rh_capabilities=(
                    "latex_compile",
                    "final_bundle",
                    "final_bundle_quality",
                    "publication_pack_backfill",
                ),
                protocol_capabilities=(
                    "PAPER_PACKAGE",
                    "venue_format_gate",
                    "final_bundle_quality_gate",
                ),
                required_artifacts=(
                    "latex_source",
                    "compiled_pdf",
                    "final_bundle",
                    "final_bundle_quality_report",
                ),
                quality_gates=(
                    "latex_compiles",
                    "pdf_exists",
                    "venue_constraints_checked",
                    "final_bundle_quality_passed",
                ),
            ),
            PaperProductionStage(
                stage_id="PW09_PRESUBMISSION_AUDIT_AND_PUBLICATION_PACK",
                objective="Audit the full package and produce a reviewable publication pack.",
                rh_capabilities=(
                    "adversarial_review",
                    "review_bundle_create",
                    "review_issues",
                    "provenance_review",
                    "publication_pack_generate",
                ),
                protocol_capabilities=(
                    "PRESUBMISSION_AUDIT",
                    "PRESUBMISSION_SEVERITY_GATE_PROFILE",
                    "PAPER_PACKAGE",
                ),
                required_artifacts=(
                    "PRESUBMISSION_AUDIT",
                    "PRESUBMISSION_SEVERITY_GATE_PROFILE",
                    "publication_pack",
                    "PAPER_PACKAGE",
                ),
                quality_gates=(
                    "zero_critical_findings",
                    "provenance_complete",
                    "package_components_present",
                    "readiness_claims_qa_backed",
                ),
            ),
            PaperProductionStage(
                stage_id="PW10_REBUTTAL_CAMERA_READY_AND_REPLAY",
                objective="Preserve reviewer response, camera-ready deltas, and replay evidence.",
                rh_capabilities=(
                    "review_add_issue",
                    "review_respond",
                    "review_resolve",
                    "review_status",
                    "provenance_export",
                    "run_trace",
                ),
                protocol_capabilities=(
                    "REBUTTAL_PACKAGE",
                    "REBUTTAL_READINESS_GATE_PROFILE",
                    "ISSUE_BOARD",
                    "REVISION_PLAN",
                ),
                required_artifacts=(
                    "REBUTTAL_PACKAGE",
                    "REBUTTAL_READINESS_GATE_PROFILE",
                    "ISSUE_BOARD",
                    "REVISION_PLAN",
                    "camera_ready_delta",
                    "final_replay_report",
                ),
                quality_gates=(
                    "reviewer_concerns_covered",
                    "commitments_traceable",
                    "camera_ready_delta_replayable",
                    "durable_completion_event_recorded",
                ),
            ),
        ),
        external_action_boundaries=(
            "credential_mutation",
            "third_party_writes",
            "real_zotero_network_apply",
            "public_deployment",
            "commit_push_pr_release_publish",
        ),
    )


def build_paper_production_readiness_report(
    *,
    artifact_states: Mapping[str, str] | None = None,
    gate_states: Mapping[str, str] | None = None,
    state_machine: PaperProductionStateMachine | None = None,
) -> PaperProductionReadinessReport:
    """Evaluate product-chain readiness from known artifact and gate states.

    The report is deterministic and side-effect free. It does not query the
    database, write artifacts, advance the orchestrator, or call providers.
    """

    machine = state_machine or build_paper_production_state_machine()
    normalized_artifacts = _normalize_states(artifact_states)
    normalized_gates = _normalize_states(gate_states)
    stages: list[PaperProductionStageReadiness] = []
    blockers: list[str] = []

    for stage in machine.stages:
        readiness = _stage_readiness(
            stage=stage,
            artifact_states=normalized_artifacts,
            gate_states=normalized_gates,
        )
        stages.append(readiness)
        blockers.extend(readiness.blockers)

    summary = _readiness_summary(stages)
    first_blocked = next((stage for stage in stages if stage.status == "blocked"), None)
    first_ready = next(
        (stage for stage in stages if stage.status == "ready_to_advance"),
        None,
    )
    if summary["satisfied"] == summary["total"]:
        status = "complete"
        next_stage = ""
        next_action = machine.completion_condition
    elif first_ready is not None:
        status = "ready_to_advance"
        next_stage = first_ready.stage_id
        next_action = first_ready.next_action
    else:
        status = "blocked"
        next_stage = first_blocked.stage_id if first_blocked is not None else ""
        next_action = first_blocked.next_action if first_blocked is not None else ""

    return PaperProductionReadinessReport(
        schema_version=READINESS_REPORT_SCHEMA_VERSION,
        status=status,
        completion_condition=machine.completion_condition,
        next_stage=next_stage,
        next_action=next_action,
        summary=summary,
        stages=tuple(stages),
        artifact_states=normalized_artifacts,
        gate_states=normalized_gates,
        blockers=tuple(dict.fromkeys(blockers)),
    )


def _guarded_provider_allowlist() -> tuple[str, ...]:
    return GUARDED_PROVIDER_ALLOWLIST


def build_paper_production_evidence_plan(
    *,
    topic: str,
    target_venue: str,
    venue_overlay: Mapping[str, Any],
    domain_method_search_profile: Mapping[str, Any],
    status: str,
    local_only: bool = False,
) -> PaperProductionEvidencePlan:
    """Build the guarded evidence-acquisition plan for PW02."""

    topic_text = _clean_text(topic)
    venue_text = _clean_text(target_venue)
    venue_family = str(venue_overlay.get("venue_family") or "")
    method_route = str(domain_method_search_profile.get("method_route") or "")
    search_route = str(domain_method_search_profile.get("search_route") or "")
    provider_mode = "local_only" if local_only else "guarded_provider_fanout"
    search_local_only = bool(local_only)
    provider_allowlist: tuple[str, ...] = (
        () if local_only else _guarded_provider_allowlist()
    )
    provider_denylist: tuple[str, ...] = GUARDED_PROVIDER_DENYLIST
    tier_filter = _evidence_tier_filter(
        venue_family=venue_family,
        route=search_route,
    )
    provider_preference = _provider_preference(
        search_route=search_route,
        venue_family=venue_family,
    )
    blockers: list[str] = []
    if status == "blocked":
        blockers.append("runtime_context_blocked")
        provider_mode = "blocked"
        search_local_only = True
        provider_allowlist = ()
    if not topic_text:
        blockers.append("missing_query")
    if not venue_text:
        blockers.append("missing_target_venue")

    return PaperProductionEvidencePlan(
        schema_version="rh.paper_production_evidence_plan.v1",
        status="ready" if not blockers else "blocked",
        stage_id="PW02_EVIDENCE_ACQUISITION_AND_READING",
        query=topic_text,
        provider_mode=provider_mode,
        search_parameters={
            "query": topic_text,
            "max_results": 500,
            "auto_ingest": True,
            "local_only": search_local_only,
            "per_provider_limit": GUARDED_PER_PROVIDER_LIMIT,
            "provider_allowlist": list(provider_allowlist),
            "provider_denylist": list(provider_denylist),
            "tier_filter": tier_filter,
            "venue_filter": "",
        },
        tool_sequence=(
            "paper_search",
            "paper_ingest",
            "paper_acquire",
            "paper_list",
            "paper_coverage_check",
        ),
        minimum_acceptance={
            "min_total_papers": 25,
            "min_verified_metadata": 20,
            "min_survey_or_benchmark_papers": 3,
            "min_recent_papers": 10,
            "required_baseline_families": _required_baseline_families(method_route),
        },
        expected_artifacts=(
            "paper_pool",
            "source_inventory",
            "paper_summary_set",
            "wiki_context_pack.v1",
        ),
        guardrails=(
            "no_silent_local_only_success",
            "provider_errors_recorded",
            "metadata_verification_required",
            "weak_evidence_blocks_paper_plan_promotion",
        ),
        blockers=tuple(dict.fromkeys(blockers)),
        provider_preference=provider_preference,
    )


def _provider_preference(*, search_route: str, venue_family: str) -> tuple[str, ...]:
    """Domain-aware provider ordering for evidence screening (advisory).

    From the 2026-07-05 cross-domain PDF diagnostics: biomedical topics
    should screen PubMed first (PMID/PMCID for acquisition), CS/ML topics
    arXiv/OpenReview (reliable direct PDFs), ecology and social science
    OpenAlex/Crossref (OA locations and DOIs). The guarded allowlist still
    controls which providers may be queried at all.
    """
    if search_route == "ml-baseline-search":
        return ("arxiv", "openreview", "semantic_scholar", "openalex", "crossref")
    if "clinical" in search_route or venue_family == "clinical_journal":
        return ("pubmed", "openalex", "semantic_scholar", "crossref")
    if (
        search_route == "ecology-evidence-search"
        or venue_family == "life_science_journal"
    ):
        return ("openalex", "pubmed", "crossref", "semantic_scholar")
    if (
        search_route == "social-science-evidence-search"
        or venue_family == "social_science_journal"
    ):
        return ("openalex", "crossref", "semantic_scholar", "google_scholar")
    return ()


def build_default_experiment_grounding_profile(
    *,
    paper_profile: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the conservative PW04 experiment-grounding profile."""

    return build_delivery_experiment_grounding_profile(
        discipline=str(paper_profile.get("discipline") or ""),
        research_type=str(paper_profile.get("research_type") or ""),
        study_design=str(paper_profile.get("study_design") or ""),
        paper_type=str(paper_profile.get("paper_type") or ""),
        target_venue=str(paper_profile.get("target_venue") or ""),
        experiment_goal_status="missing",
        experiment_plan_status="missing",
        paper_profile_status=(
            "recorded" if paper_profile.get("status") == "success" else "missing"
        ),
        variable_grounding_status="missing",
        codebook_status="missing",
        evidence_reporting_status="missing",
        pre_deploy_code_review_status="missing",
        deploy_blocker_count=0,
        impact_report_status="missing",
        impact_claim_binding_status="missing",
        result_state="planned",
        missing_variables=(),
    ).to_dict()


def build_default_result_to_claim_analysis_profile(
    *,
    paper_profile: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the conservative PW04 result-to-claim profile."""

    return build_delivery_result_to_claim_analysis_profile(
        discipline=str(paper_profile.get("discipline") or ""),
        research_type=str(paper_profile.get("research_type") or ""),
        study_design=str(paper_profile.get("study_design") or ""),
        paper_type=str(paper_profile.get("paper_type") or ""),
        target_venue=str(paper_profile.get("target_venue") or ""),
        result_state="planned",
        experiment_grounding_status="blocked",
        impact_report_status="missing",
        claims_from_results_status="missing",
        result_artifact_status="missing",
        expected_vs_actual_status="missing",
        statistical_reporting_status="missing",
        practical_significance_status="missing",
        baseline_delta_status="missing",
        robustness_status="missing",
        negative_results_status="missing",
        competing_evidence_status="missing",
        claim_strength="B_empirical_strong",
        unsupported_claim_ids=(),
        overclaimed_claim_ids=(),
        missing_result_artifact_ids=(),
    ).to_dict()


def build_paper_plan_gate_profile(
    *,
    experiment_grounding_profile: Mapping[str, Any],
    result_to_claim_analysis_profile: Mapping[str, Any],
    has_active_paper_plan: bool,
) -> PaperPlanGateProfile:
    """Return whether PW05 may promote a PAPER_PLAN into drafting."""

    blockers: list[str] = []
    if experiment_grounding_profile.get("status") != "success":
        blockers.append("experiment_grounding_profile_blocked")
    if result_to_claim_analysis_profile.get("status") != "success":
        blockers.append("result_to_claim_analysis_profile_blocked")
    if not has_active_paper_plan:
        blockers.append("missing_active_PAPER_PLAN")
    return PaperPlanGateProfile(
        schema_version="rh.paper_production_paper_plan_gate.v1",
        status="ready" if not blockers else "blocked",
        stage_id="PW05_PAPER_PLAN_AND_LOGIC_GATES",
        required_artifact="PAPER_PLAN",
        required_reports=(
            "manuscript_logic_gate_report",
            "fine_logic_audit_report",
            "claims_evidence_matrix",
        ),
        required_upstream_profiles=(
            "PAPER_PROFILE",
            "DOMAIN_METHOD_SEARCH_PROFILE",
            "EXPERIMENT_GROUNDING_PROFILE",
            "RESULT_TO_CLAIM_ANALYSIS_PROFILE",
        ),
        drafting_enabled=not blockers,
        promotion_action=(
            "promote_active_paper_plan"
            if not blockers
            else "repair_upstream_profiles_before_paper_plan"
        ),
        blockers=tuple(blockers),
    )


def build_write_to_pdf_closure_plan(
    *,
    venue_overlay: Mapping[str, Any],
    paper_plan_gate_profile: PaperPlanGateProfile,
) -> PaperProductionClosurePlan:
    """Build the deterministic PW06-PW09 writing/PDF/package closure plan."""

    blockers = (
        ("paper_plan_gate_blocked",)
        if not paper_plan_gate_profile.drafting_enabled
        else ()
    )
    return PaperProductionClosurePlan(
        schema_version="rh.paper_production_write_to_pdf_closure_plan.v1",
        status=(
            "ready_for_write_stage"
            if not blockers
            else "blocked_until_paper_plan_ready"
        ),
        stage_ids=(
            "PW06_SECTION_DRAFTING_AND_REVISION",
            "PW07_FIGURE_TABLE_SOURCE_AND_CITATION_INTEGRITY",
            "PW08_LATEX_FINAL_BUNDLE_AND_PDF",
            "PW09_PRESUBMISSION_AUDIT_AND_PUBLICATION_PACK",
        ),
        sections_to_draft=(
            # Abstract is drafted LAST (human practice): drafting it first
            # forces every later section to re-paraphrase the core claim from
            # the plan alone, which is where concept-drift started.
            "introduction",
            "related_work",
            "method",
            "experiments",
            "results",
            "limitations",
            "conclusion",
            "abstract",
        ),
        latex_template=str(venue_overlay.get("format_family") or "generic"),
        publication_components=(
            "process_summary",
            "citation_integrity",
            "final_bundle",
            "publication_pack",
        ),
        quality_gates=(
            "active_paper_plan_required",
            "strict_evidence_required",
            "citation_integrity_verified",
            "latex_compiles",
            "final_bundle_quality_passed",
            "publication_pack_present",
        ),
        tool_sequence=(
            "section_draft",
            "section_review",
            "section_revise",
            "consistency_check",
            "figure_suite_plan",
            "figure_plan",
            "figure_suite_render",
            "figure_generate",
            "paper_verify_numbers",
            "citation_verify",
            "evidence_trace",
            "latex_compile",
            "publication_pack_backfill",
            "publication_run",
        ),
        blockers=blockers,
    )


def _clean_text(value: str) -> str:
    return " ".join(str(value or "").split())


def _normalize_states(states: Mapping[str, str] | None) -> dict[str, str]:
    return {
        str(key).strip(): _profile_key(str(value))
        for key, value in (states or {}).items()
        if str(key).strip()
    }


def _stage_readiness(
    *,
    stage: PaperProductionStage,
    artifact_states: Mapping[str, str],
    gate_states: Mapping[str, str],
) -> PaperProductionStageReadiness:
    present_artifacts = tuple(
        artifact
        for artifact in stage.required_artifacts
        if artifact_states.get(artifact) in ACTIVE_ARTIFACT_STATES
    )
    missing_artifacts = tuple(
        artifact
        for artifact in stage.required_artifacts
        if artifact_states.get(artifact) not in ACTIVE_ARTIFACT_STATES
    )
    passed_gates = tuple(
        gate
        for gate in stage.quality_gates
        if gate_states.get(gate) in PASSING_GATE_STATES
    )
    failed_gates = tuple(
        gate
        for gate in stage.quality_gates
        if gate_states.get(gate) in BLOCKING_GATE_STATES
    )
    unverified_gates = tuple(
        gate
        for gate in stage.quality_gates
        if gate not in passed_gates and gate not in failed_gates
    )
    blockers = tuple(
        [
            *(f"{stage.stage_id}:{artifact}" for artifact in missing_artifacts),
            *(f"{stage.stage_id}:gate:{gate}" for gate in failed_gates),
        ]
    )
    if blockers:
        status = "blocked"
    elif unverified_gates and gate_states:
        status = "ready_to_advance"
    else:
        status = "satisfied"
    return PaperProductionStageReadiness(
        stage_id=stage.stage_id,
        status=status,
        required_artifacts=stage.required_artifacts,
        present_artifacts=present_artifacts,
        missing_artifacts=missing_artifacts,
        quality_gates=stage.quality_gates,
        passed_gates=passed_gates,
        failed_gates=failed_gates,
        unverified_gates=unverified_gates,
        next_action=f"run {', '.join(stage.rh_capabilities)}",
        blockers=blockers,
    )


def _readiness_summary(
    stages: tuple[PaperProductionStageReadiness, ...]
    | list[PaperProductionStageReadiness],
) -> dict[str, int]:
    summary = {
        "total": len(stages),
        "satisfied": 0,
        "ready_to_advance": 0,
        "blocked": 0,
    }
    for stage in stages:
        if stage.status in summary:
            summary[stage.status] += 1
    return summary


def _initial_artifact_states(
    *,
    status: str,
    state_machine: PaperProductionStateMachine,
) -> dict[str, str]:
    if status != "ready_for_evidence_acquisition":
        return {}
    first_stage = state_machine.stages[0]
    return {artifact: "ready" for artifact in first_stage.required_artifacts}


def _evidence_tier_filter(*, venue_family: str, route: str) -> str:
    if venue_family in {"ml_conference", "systems_conference"}:
        return "ccf_a"
    if "clinical" in route or venue_family == "clinical_journal":
        return "cas_q1"
    if venue_family == "social_science_journal":
        return "cas_q2"
    if venue_family in {"law_policy_journal", "humanities_journal"}:
        return ""
    return "ccf_b"


def _required_baseline_families(route: str) -> list[str]:
    if route in {"ml-baseline-search", "domain-method-search-stem"}:
        return ["system", "retrieval", "evaluation", "agent"]
    if route == "biomedical-clinical-search":
        return ["clinical", "intervention", "outcome", "safety"]
    if route == "social-science-method-search":
        return ["theory", "measurement", "population", "identification"]
    if route == "law-policy-source-search":
        return ["legal_authority", "policy_instrument", "jurisdiction", "impact"]
    if route == "humanities-source-search":
        return ["archive", "primary_source", "interpretive_frame", "historiography"]
    return ["method", "baseline", "evaluation"]


def _profile_key(value: str) -> str:
    return _clean_text(value).casefold().replace("-", "_").replace(" ", "_")


def _infer_profile_defaults(
    *,
    topic: str,
    target_venue: str,
    discipline: str,
    research_type: str,
    study_design: str,
    paper_type: str,
) -> dict[str, str]:
    explicit = {
        "discipline": _profile_key(discipline),
        "research_type": _profile_key(research_type),
        "study_design": _profile_key(study_design),
        "paper_type": _profile_key(paper_type),
    }
    if all(explicit.values()):
        return explicit

    topic_key = _profile_key(topic)
    inference_key = _profile_key(f"{topic} {target_venue}")
    inferred_discipline = explicit["discipline"] or _infer_discipline(inference_key)
    inferred_research_type = explicit["research_type"] or _infer_research_type(
        inference_key,
        inferred_discipline,
    )
    inferred_study_design = explicit["study_design"] or _infer_study_design(
        inference_key,
        inferred_discipline,
        inferred_research_type,
    )
    inferred_paper_type = explicit["paper_type"] or _infer_paper_type(
        topic_key,
        inferred_discipline,
        inferred_research_type,
    )
    return {
        "discipline": inferred_discipline,
        "research_type": inferred_research_type,
        "study_design": inferred_study_design,
        "paper_type": inferred_paper_type,
    }


def _key_matches_any(topic_key: str, tokens: tuple[str, ...]) -> bool:
    """Whole-word token matching over a normalized topic key.

    Multi-word tokens (with underscores) and non-ASCII tokens match as
    substrings; single ASCII tokens match whole words (with a plural "s"
    tolerance) so "rna" cannot hide in "international" or "vic" in
    "service".
    """
    words: set[str] | None = None
    for token in tokens:
        if "_" in token or not token.isascii():
            if token in topic_key:
                return True
            continue
        if words is None:
            words = _topic_words(topic_key)
        if token in words or f"{token}s" in words:
            return True
    return False


def _infer_discipline(topic_key: str) -> str:
    if _key_matches_any(
        topic_key,
        (
            "clinical",
            "medical",
            "patient",
            "public_health",
            "primary_care",
            "screening",
            "trial",
        ),
    ):
        return "public_health"
    if _key_matches_any(topic_key, ("education", "student", "teacher", "classroom")):
        return "education"
    if _key_matches_any(topic_key, ("law", "policy", "regulation", "governance")):
        return "policy"
    if _key_matches_any(
        topic_key,
        (
            "bioinformatics",
            "nucleic_acids",
            "rna",
            "protein",
            "pdb",
            "zebrafish",
            "brain",
            "neuroscience",
            "genetic",
            "genome",
        ),
    ):
        return "life_science"
    if _key_matches_any(
        topic_key,
        (
            "energy",
            "building",
            "hydrogen",
            "renewable",
            "power_output",
            "sensor",
        ),
    ):
        return "engineering"
    if _key_matches_any(
        topic_key,
        (
            "environmental",
            "cloud_seeding",
            "hydrometeorology",
            "runoff",
            "vic",
            "noah_mp",
            "weather",
            "climate",
            "geospatial",
        ),
    ):
        return "physical_science"
    if _key_matches_any(topic_key, ("history", "archive", "literary")):
        return "history"
    if _matches_ecology_signals(topic_key):
        return "ecology"
    if _matches_social_science_signals(topic_key):
        return "social_science"
    return "ai"


_ECOLOGY_DISTINCT_WORDS: frozenset[str] = frozenset(
    {
        "ecology",
        "ecological",
        "ecosystem",
        "shrub",
        "vegetation",
        "grassland",
        "dryland",
        "biodiversity",
        "habitat",
        "rhizosphere",
    }
)

_ECOLOGY_GENERIC_WORDS: frozenset[str] = frozenset(
    {
        "plant",
        "soil",
        "species",
        "forest",
        "root",
        "nitrogen",
        "carbon",
        "photosynthesis",
        "nsc",
        "drought",
    }
)


def _matches_ecology_signals(topic_key: str) -> bool:
    """One distinct ecology word, or two generic ones, marks an ecology topic.

    Generic words alone ("carbon" in materials topics, "root" in math/CS)
    must not reroute; pairs like nitrogen+root or soil+species are decisive.
    """
    words = _topic_words(topic_key)
    plural_tolerant = words | {word[:-1] for word in words if word.endswith("s")}
    if plural_tolerant & _ECOLOGY_DISTINCT_WORDS:
        return True
    return len(plural_tolerant & _ECOLOGY_GENERIC_WORDS) >= 2


_SOCIAL_SCIENCE_EXPLICIT_MARKERS: tuple[str, ...] = (
    "humanities_and_social_sciences_communications",
    "humanities_social_sciences_communications",
    "social_science",
    "social_sciences",
    "sociology",
    "socioeconomic",
    "hssc",
    "社会科学",
)

_SOCIAL_SCIENCE_CN_MARKERS: tuple[str, ...] = ("体育", "赛事", "消费", "城市", "时空")

_SOCIAL_SCIENCE_SIGNAL_WORDS: frozenset[str] = frozenset(
    {
        "arcgis",
        "sports",
        "sport",
        "consumption",
        "consumer",
        "tourism",
        "urban",
        "socioeconomic",
    }
)

_SPATIAL_OBSERVATIONAL_WORDS: frozenset[str] = frozenset(
    {"arcgis", "gis", "urban", "spatiotemporal", "spatial", "geospatial"}
)


def _topic_words(topic_key: str) -> set[str]:
    return {word for word in re.split(r"[^a-z0-9]+", topic_key) if word}


def _matches_social_science_signals(topic_key: str) -> bool:
    """True only on explicit or combined social-science signals.

    Single generic tokens must never reroute a CS/engineering topic: as
    substrings, "event" hides in "prevention", "gis" in "logistics", "sport"
    in "transport", "city" in "capacity"; and whole words like "urban" or
    "event" appear in plenty of AI topics. Require an explicit marker, or at
    least two independent whole-word signals / Chinese markers.
    """
    if any(marker in topic_key for marker in _SOCIAL_SCIENCE_EXPLICIT_MARKERS):
        return True
    cn_hits = sum(1 for marker in _SOCIAL_SCIENCE_CN_MARKERS if marker in topic_key)
    if cn_hits >= 2:
        return True
    return len(_topic_words(topic_key) & _SOCIAL_SCIENCE_SIGNAL_WORDS) >= 2


def _infer_research_type(topic_key: str, discipline: str) -> str:
    if discipline == "life_science":
        return "observational"
    if discipline in {"public_health", "clinical", "medical", "medicine"}:
        return "intervention_study" if "intervention" in topic_key else "cohort"
    if discipline in {"education", "social_science", "psychology", "psy"}:
        if any(marker in topic_key for marker in ("时空", "空间")) or (
            _topic_words(topic_key) & _SPATIAL_OBSERVATIONAL_WORDS
        ):
            return "observational"
        return "survey_correlational"
    if discipline in {"policy", "law", "law_policy", "regulation"}:
        return "policy_analysis"
    if discipline in {
        "engineering",
        "physical_science",
        "stem",
        "ecology",
        "environmental_science",
    }:
        return "empirical"
    if "benchmark" in topic_key or "evaluation" in topic_key:
        return "empirical_ml"
    return "system_benchmark"


def _infer_study_design(
    topic_key: str,
    discipline: str,
    research_type: str,
) -> str:
    if "rct" in topic_key or "trial" in topic_key:
        return "rct"
    if discipline in {"education", "social_science", "psychology", "psy"}:
        if research_type == "observational":
            return "observational"
        return "cross_sectional"
    if research_type in {"empirical_ml", "system_benchmark"}:
        return "benchmark"
    if discipline in {"policy", "law", "law_policy", "regulation"}:
        return "comparative_policy_analysis"
    return "quasi_experiment"


def _infer_paper_type(
    topic_key: str,
    discipline: str,
    research_type: str,
) -> str:
    if "review" in topic_key:
        return "review"
    if discipline in {"policy", "law", "law_policy", "regulation"}:
        return "policy"
    if research_type in {"empirical_ml", "system_benchmark"}:
        return "method"
    return "empirical_study"


def _default_audience(target_venue: str) -> str:
    return f"{target_venue} reviewers" if target_venue else "target venue reviewers"


def _contract_blockers(topic: str, target_venue: str) -> tuple[str, ...]:
    blockers: list[str] = []
    if not topic:
        blockers.append("missing_topic")
    if not target_venue:
        blockers.append("missing_target_venue")
    return tuple(blockers)


def _context_blockers(
    *,
    contract: TopicVenueContract,
    venue_blockers: tuple[str, ...],
    paper_profile_blockers: tuple[str, ...],
    method_profile_blockers: tuple[str, ...],
) -> tuple[str, ...]:
    blockers: list[str] = []
    blockers.extend(f"topic_venue_contract:{blocker}" for blocker in contract.blockers)
    blockers.extend(f"venue_overlay:{blocker}" for blocker in venue_blockers)
    blockers.extend(f"paper_profile:{blocker}" for blocker in paper_profile_blockers)
    blockers.extend(
        f"domain_method_search_profile:{blocker}" for blocker in method_profile_blockers
    )
    return tuple(dict.fromkeys(blockers))


def _paper_plan_requirements() -> PaperPlanRequirements:
    contract = build_paper_plan_audit_package_artifact_contracts()["PAPER_PLAN"]
    return PaperPlanRequirements(
        artifact=contract.artifact,
        schema_version=contract.schema_version,
        owner_skill=contract.owner_skill,
        required_fields=contract.required_fields,
        forbidden_claims=contract.forbidden_claims,
    )


def _next_actions(status: str) -> tuple[dict[str, str], ...]:
    if status == "blocked":
        return (
            {
                "stage": "PW01_TOPIC_AND_VENUE_CONTRACT",
                "action": "resolve blocked topic, venue, or paper profile fields",
            },
        )
    return (
        {
            "stage": "PW02_EVIDENCE_ACQUISITION_AND_READING",
            "action": "search, ingest, verify, and summarize source literature",
        },
        {
            "stage": "PW03_GAP_BASELINE_NOVELTY_VALIDATION",
            "action": "build domain-routed baselines, gaps, and novelty evidence",
        },
        {
            "stage": "PW05_PAPER_PLAN_AND_STORYLINE",
            "action": "promote a real PAPER_PLAN only after logic gates pass",
        },
    )
