"""ResearchFlowBench metric map.

This module is the canonical bridge between public benchmark metrics and the
Research Harness capability surface they exercise.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class RHMetricAxis:
    """A measurable RH capability axis."""

    axis_id: str
    stage: str
    component: str
    capability: str
    observed_signal: str
    failure_modes: tuple[str, ...]
    evidence_contracts: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ExternalMetricMapping:
    """Mapping from an external benchmark metric to RH metric axes."""

    benchmark_id: str
    public_metric: str
    public_label: str
    rh_axis_ids: tuple[str, ...]
    interpretation: str
    adapter_contract: str
    primary: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


_RH_METRIC_AXES: tuple[RHMetricAxis, ...] = (
    RHMetricAxis(
        axis_id="paper_search.recall",
        stage="build",
        component="paper_search",
        capability="Find relevant papers for a research query.",
        observed_signal="Gold paper appears in the retrieved candidate set.",
        failure_modes=(
            "missed_known_relevant_paper",
            "query_under_specification",
            "corpus_identifier_mismatch",
        ),
        evidence_contracts=(
            "retrieved_paper_ids",
            "query_text",
            "corpus_id_namespace",
        ),
    ),
    RHMetricAxis(
        axis_id="paper_search.rerank_quality",
        stage="build",
        component="paper_search",
        capability="Rank relevant papers near the top of the candidate list.",
        observed_signal="Relevant papers receive high rank positions.",
        failure_modes=(
            "relevant_paper_buried",
            "abstract_keyword_overfit",
            "weak_query_intent_matching",
        ),
        evidence_contracts=(
            "ordered_retrieved_paper_ids",
            "ranked_scores",
            "gold_paper_ids",
        ),
    ),
    RHMetricAxis(
        axis_id="retrieval.provenance_coverage",
        stage="build",
        component="retrieval_log",
        capability="Preserve source, query, and rank provenance for retrieval outputs.",
        observed_signal="Every candidate can be traced to a query, source, and rank.",
        failure_modes=(
            "missing_retrieval_source",
            "rank_without_query_context",
            "untraceable_candidate",
        ),
        evidence_contracts=(
            "retrieval_trace",
            "source_name",
            "rank",
            "query_hash",
        ),
    ),
    RHMetricAxis(
        axis_id="literature.set_completion",
        stage="build",
        component="literature_mapping",
        capability="Complete a target set of papers across multiple query intents.",
        observed_signal="Retrieved set overlaps the expected paper set for a wide query.",
        failure_modes=(
            "partial_cluster_coverage",
            "missed_subtopic",
            "duplicate_heavy_candidate_set",
        ),
        evidence_contracts=(
            "retrieved_paper_id_set",
            "gold_paper_id_set",
            "dedupe_report",
        ),
    ),
    RHMetricAxis(
        axis_id="deep_research.discovery_accuracy",
        stage="build",
        component="deep_research",
        capability="Resolve deep literature-discovery questions to the intended paper.",
        observed_signal="The final selected paper matches the gold answer.",
        failure_modes=(
            "wrong_anchor_paper",
            "stopped_before_citation_trace",
            "overtrusted_surface_match",
        ),
        evidence_contracts=(
            "final_answer_paper_ids",
            "search_trace",
            "selection_rationale",
        ),
    ),
    RHMetricAxis(
        axis_id="citation.candidate_generation",
        stage="write",
        component="citation_sanitize",
        capability="Generate citation candidates that can support draft claims.",
        observed_signal="Candidate citations include known support papers.",
        failure_modes=(
            "unsupported_claim_candidate",
            "missing_known_support",
            "hallucinated_identifier",
        ),
        evidence_contracts=(
            "claim_text",
            "candidate_paper_ids",
            "citation_verification_status",
        ),
    ),
    RHMetricAxis(
        axis_id="paper_selection.precision",
        stage="build",
        component="literature_mapping",
        capability="Filter retrieved candidates into a high-precision working set.",
        observed_signal="Selected papers match the gold relevant set after retrieval.",
        failure_modes=(
            "irrelevant_candidate_survives",
            "relevant_candidate_dropped_after_search",
            "selection_criteria_ignored",
        ),
        evidence_contracts=(
            "candidate_paper_ids",
            "selected_paper_ids",
            "selection_rationale",
        ),
    ),
    RHMetricAxis(
        axis_id="paper_reading.claim_quality",
        stage="analyze",
        component="claim_extract",
        capability="Extract scoped claims from a paper without overclaiming.",
        observed_signal="Extracted claims preserve paper id, claim text, and evidence scope.",
        failure_modes=(
            "claim_scope_overreach",
            "missing_claim_scope",
            "paper_identity_lost",
        ),
        evidence_contracts=(
            "paper_id",
            "claim_text",
            "claim_scope",
        ),
    ),
    RHMetricAxis(
        axis_id="gap_detection.novelty_accuracy",
        stage="analyze",
        component="gap_detect",
        capability="Distinguish real research gaps from false novelty claims.",
        observed_signal="Gap decisions reflect baseline coverage, negative evidence, and novelty limits.",
        failure_modes=(
            "false_novelty_claim",
            "baseline_coverage_ignored",
            "negative_evidence_dropped",
        ),
        evidence_contracts=(
            "gap_claim_id",
            "baseline_ids",
            "novelty_decision",
        ),
    ),
    RHMetricAxis(
        axis_id="baseline_identification.coverage",
        stage="analyze",
        component="baseline_identify",
        capability="Identify the strongest and most relevant baseline methods.",
        observed_signal="Baseline set covers expected method families and update-sensitive prior work.",
        failure_modes=(
            "missing_strong_baseline",
            "stale_baseline_retained",
            "method_cluster_boundary_error",
        ),
        evidence_contracts=(
            "baseline_ids",
            "method_family",
            "selection_rationale",
        ),
    ),
    RHMetricAxis(
        axis_id="evidence_linking.support_accuracy",
        stage="analyze",
        component="evidence_link",
        capability="Assign support labels between claims and exact evidence spans.",
        observed_signal="Support, partial support, and contradiction labels match gold links.",
        failure_modes=(
            "partial_support_marked_full",
            "contradiction_dropped",
            "overbroad_evidence_span",
        ),
        evidence_contracts=(
            "claim_id",
            "evidence_span_id",
            "support_label",
        ),
    ),
    RHMetricAxis(
        axis_id="proposal.direction_quality",
        stage="propose",
        component="direction_ranking",
        capability="Rank research directions using evidence, baselines, and risk.",
        observed_signal="Chosen directions preserve novelty, feasibility, and baseline-aware risk signals.",
        failure_modes=(
            "weak_direction_promoted",
            "risk_signal_ignored",
            "baseline_overlap_underestimated",
        ),
        evidence_contracts=(
            "direction_id",
            "ranking_rationale",
            "risk_assessment",
        ),
    ),
    RHMetricAxis(
        axis_id="section_drafting.citation_grounding",
        stage="write",
        component="section_draft",
        capability="Draft sections whose claims are grounded in supplied evidence citations.",
        observed_signal="Required citations are present and forbidden unsupported claims are absent.",
        failure_modes=(
            "unsupported_claim_inserted",
            "required_citation_missing",
            "evidence_card_ignored",
        ),
        evidence_contracts=(
            "section_text",
            "citation_paper_ids",
            "evidence_card_refs",
        ),
    ),
    RHMetricAxis(
        axis_id="governance.rollback_blocking",
        stage="cross_stage",
        component="semantic_governance",
        capability="Block, abstain, or roll back outputs when evidence contracts fail.",
        observed_signal="Gate decisions and rollback events are emitted before unsupported outputs persist.",
        failure_modes=(
            "unsupported_output_not_blocked",
            "stale_artifact_not_rolled_back",
            "abstention_missing",
        ),
        evidence_contracts=(
            "gate_decision",
            "rollback_event",
            "review_issue",
        ),
    ),
    RHMetricAxis(
        axis_id="final_bundle.pdf_quality",
        stage="write",
        component="final_bundle",
        capability="Check final PDF/LaTeX/citation/figure quality before release.",
        observed_signal="Final bundle QA checks cover PDF, LaTeX, citations, and figure warnings.",
        failure_modes=(
            "pdf_not_verified",
            "citation_warning_unreported",
            "figure_quality_warning_unreported",
        ),
        evidence_contracts=(
            "pdf_exists",
            "latex_compiled",
            "citation_warnings",
            "figure_warnings",
        ),
    ),
)


_EXTERNAL_METRIC_MAPPINGS: tuple[ExternalMetricMapping, ...] = (
    ExternalMetricMapping(
        benchmark_id="litsearch",
        public_metric="retrieval_recall",
        public_label="Retrieval Recall",
        rh_axis_ids=("paper_search.recall", "citation.candidate_generation"),
        interpretation=(
            "Calibrates whether RH can surface known relevant papers for realistic "
            "ML/NLP literature-search queries."
        ),
        adapter_contract="researchflowbench.adapters.litsearch.v0.1",
        primary=True,
    ),
    ExternalMetricMapping(
        benchmark_id="litsearch",
        public_metric="rerank_quality",
        public_label="Rerank Quality",
        rh_axis_ids=("paper_search.rerank_quality",),
        interpretation=(
            "Calibrates whether RH ranks known relevant papers high enough to be "
            "usable by downstream mapping and citation workflows."
        ),
        adapter_contract="researchflowbench.adapters.litsearch.v0.1",
    ),
    ExternalMetricMapping(
        benchmark_id="autoresearchbench",
        public_metric="deep_accuracy",
        public_label="Deep Accuracy",
        rh_axis_ids=(
            "deep_research.discovery_accuracy",
            "retrieval.provenance_coverage",
        ),
        interpretation=(
            "Calibrates deep literature-discovery accuracy and whether the path to "
            "the selected paper is auditable."
        ),
        adapter_contract="researchflowbench.adapters.autoresearchbench.v0.1",
        primary=True,
    ),
    ExternalMetricMapping(
        benchmark_id="autoresearchbench",
        public_metric="wide_iou",
        public_label="Wide IoU",
        rh_axis_ids=("literature.set_completion", "retrieval.provenance_coverage"),
        interpretation=(
            "Calibrates broad set-completion quality for literature mapping tasks."
        ),
        adapter_contract="researchflowbench.adapters.autoresearchbench.v0.1",
    ),
    ExternalMetricMapping(
        benchmark_id="researcherbench",
        public_metric="coverage",
        public_label="Coverage",
        rh_axis_ids=("literature.set_completion",),
        interpretation="Tracks whether RH reports cover the expected research facets.",
        adapter_contract="researchflowbench.adapters.researcherbench.planned.v0.1",
    ),
    ExternalMetricMapping(
        benchmark_id="researcherbench",
        public_metric="faithfulness",
        public_label="Faithfulness",
        rh_axis_ids=("citation.candidate_generation", "retrieval.provenance_coverage"),
        interpretation="Tracks whether report claims are grounded in traceable evidence.",
        adapter_contract="researchflowbench.adapters.researcherbench.planned.v0.1",
    ),
)


def list_rh_metric_axes() -> tuple[RHMetricAxis, ...]:
    """Return all RH metric axes."""

    return _RH_METRIC_AXES


def list_external_metric_mappings() -> tuple[ExternalMetricMapping, ...]:
    """Return all known external metric mappings."""

    return _EXTERNAL_METRIC_MAPPINGS


def metric_mappings_for_benchmark(
    benchmark_id: str,
) -> tuple[ExternalMetricMapping, ...]:
    """Return metric mappings for one external benchmark."""

    return tuple(
        mapping
        for mapping in _EXTERNAL_METRIC_MAPPINGS
        if mapping.benchmark_id == benchmark_id
    )


def metric_map_payload() -> dict:
    """Return the complete metric map as a stable JSON payload."""

    return {
        "schema_version": "researchflowbench.metric_map.v0.1",
        "rh_axes": [axis.to_dict() for axis in _RH_METRIC_AXES],
        "external_metric_mappings": [
            mapping.to_dict() for mapping in _EXTERNAL_METRIC_MAPPINGS
        ],
    }
