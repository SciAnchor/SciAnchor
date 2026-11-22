"""Private paper-storyline graph helpers.

This module turns evidence-grounded discovery artifacts into claim-safe writing
inputs. It deliberately does not draft paper prose or integrate with public
section drafting surfaces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .experiment_design import ExperimentDesignBrief
from .innovation_opportunity import InnovationOpportunityReport
from .method_improvement import MethodImprovementReport
from .research_wiki_insights import ResearchWikiEvidenceAnchor
from .wiki_context_pack import WikiContextPack


PAPER_STORYLINE_GRAPH_SCHEMA_VERSION = "paper_storyline_graph.v1"
SECTION_EVIDENCE_PACK_SCHEMA_VERSION = "section_evidence_pack.v1"
_CLAIM_ROLES = {"contribution_claim", "novelty_claim", "result_claim"}


@dataclass(frozen=True)
class PaperStorylineNode:
    node_id: str
    node_role: str
    label: str
    summary: str
    claim_status: str
    source_artifacts: tuple[str, ...]
    evidence_anchors: tuple[ResearchWikiEvidenceAnchor, ...]
    warnings: tuple[str, ...] = ()
    field_provenance: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PaperStorylineEdge:
    source_node_id: str
    target_node_id: str
    relation: str
    field_provenance: str


@dataclass(frozen=True)
class SectionEvidencePack:
    schema_version: str
    artifact_role: str
    topic_id: int
    section_name: str
    required_claim_statuses: tuple[str, ...]
    nodes: tuple[PaperStorylineNode, ...]
    evidence_anchors: tuple[ResearchWikiEvidenceAnchor, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class PaperStorylineGraph:
    schema_version: str
    artifact_role: str
    topic_id: int
    opportunity_id: str
    nodes: tuple[PaperStorylineNode, ...]
    edges: tuple[PaperStorylineEdge, ...]
    section_packs: tuple[SectionEvidencePack, ...]
    claim_integrity: dict[str, int]
    warnings: tuple[str, ...]
    evidence_anchors: tuple[ResearchWikiEvidenceAnchor, ...]
    field_provenance: dict[str, str] = field(default_factory=dict)

    def nodes_by_role(self, node_role: str) -> tuple[PaperStorylineNode, ...]:
        return tuple(node for node in self.nodes if node.node_role == node_role)


def build_paper_storyline_graph(
    *,
    context_pack: WikiContextPack,
    opportunity_report: InnovationOpportunityReport,
    experiment_brief: ExperimentDesignBrief,
    method_report: MethodImprovementReport | None = None,
    section_names: tuple[str, ...] = (
        "introduction",
        "related_work",
        "method",
        "experiments",
        "limitations",
    ),
) -> PaperStorylineGraph:
    """Build a private ``paper_storyline_graph.v1``."""

    opportunity = _selected_opportunity(opportunity_report, experiment_brief)
    method_report = method_report or _empty_method_report(experiment_brief)
    nodes = _storyline_nodes(
        context_pack=context_pack,
        opportunity_report=opportunity_report,
        experiment_brief=experiment_brief,
        method_report=method_report,
    )
    edges = _storyline_edges(nodes)
    claim_integrity = _claim_integrity(nodes)
    warnings = _graph_warnings(
        nodes=nodes,
        context_pack=context_pack,
        opportunity_report=opportunity_report,
        experiment_brief=experiment_brief,
        method_report=method_report,
    )
    graph_without_packs = PaperStorylineGraph(
        schema_version=PAPER_STORYLINE_GRAPH_SCHEMA_VERSION,
        artifact_role="advisory_compiled_view",
        topic_id=opportunity_report.topic_id,
        opportunity_id=opportunity.opportunity_id,
        nodes=nodes,
        edges=edges,
        section_packs=(),
        claim_integrity=claim_integrity,
        warnings=warnings,
        evidence_anchors=_dedupe_anchors(
            tuple(anchor for node in nodes for anchor in node.evidence_anchors)
        ),
        field_provenance={
            "nodes": "context_opportunity_experiment_and_method_artifacts",
            "edges": "storyline_role_order",
            "claim_integrity": "claim_status_and_evidence_anchor_counts",
        },
    )
    section_packs = build_section_evidence_packs(
        graph_without_packs,
        section_names=section_names,
    )
    return PaperStorylineGraph(
        **{
            **graph_without_packs.__dict__,
            "section_packs": section_packs,
        }
    )


def build_section_evidence_packs(
    graph: PaperStorylineGraph,
    *,
    section_names: tuple[str, ...] = (
        "introduction",
        "related_work",
        "method",
        "experiments",
        "limitations",
    ),
) -> tuple[SectionEvidencePack, ...]:
    """Build section-specific evidence packs from a storyline graph."""

    return tuple(
        _section_pack(graph=graph, section_name=section_name)
        for section_name in section_names
    )


def paper_storyline_graph_to_dict(graph: PaperStorylineGraph) -> dict[str, Any]:
    """Serialize a storyline graph into deterministic plain data."""

    return {
        "schema_version": graph.schema_version,
        "artifact_role": graph.artifact_role,
        "topic_id": graph.topic_id,
        "opportunity_id": graph.opportunity_id,
        "claim_integrity": dict(graph.claim_integrity),
        "warnings": list(graph.warnings),
        "field_provenance": dict(graph.field_provenance),
        "nodes": [_node_to_dict(node) for node in graph.nodes],
        "edges": [_edge_to_dict(edge) for edge in graph.edges],
        "section_packs": section_evidence_packs_to_dict(graph.section_packs),
        "evidence_anchors": [
            _evidence_anchor_to_dict(anchor) for anchor in graph.evidence_anchors
        ],
    }


def section_evidence_packs_to_dict(
    packs: tuple[SectionEvidencePack, ...],
) -> list[dict[str, Any]]:
    return [
        {
            "schema_version": pack.schema_version,
            "artifact_role": pack.artifact_role,
            "topic_id": pack.topic_id,
            "section_name": pack.section_name,
            "required_claim_statuses": list(pack.required_claim_statuses),
            "warnings": list(pack.warnings),
            "nodes": [_node_to_dict(node) for node in pack.nodes],
            "evidence_anchors": [
                _evidence_anchor_to_dict(anchor) for anchor in pack.evidence_anchors
            ],
        }
        for pack in packs
    ]


def render_paper_storyline_graph_markdown(graph: PaperStorylineGraph) -> str:
    """Render a concise deterministic Markdown graph summary."""

    lines = [
        "# Paper Storyline Graph",
        "",
        f"- Topic id: {graph.topic_id}",
        f"- Opportunity id: {graph.opportunity_id}",
        f"- Unsupported claims: {graph.claim_integrity['unsupported_claim_count']}",
        "",
    ]
    if graph.warnings:
        _append_section(lines, "Warnings", graph.warnings)
    for title, role in (
        ("Problem", "problem"),
        ("Idea", "idea"),
        ("Method", "method"),
        ("Contribution claims", "contribution_claim"),
        ("Limitations", "limitation"),
    ):
        values = tuple(
            f"{node.label} [{node.claim_status}]" for node in graph.nodes_by_role(role)
        )
        _append_section(lines, title, values)
    return "\n".join(lines).rstrip() + "\n"


def _selected_opportunity(
    report: InnovationOpportunityReport,
    brief: ExperimentDesignBrief,
):
    for opportunity in report.opportunities:
        if opportunity.opportunity_id == brief.opportunity_id:
            return opportunity
    if not report.opportunities:
        raise ValueError("innovation opportunity report has no opportunities")
    return report.opportunities[0]


def _storyline_nodes(
    *,
    context_pack: WikiContextPack,
    opportunity_report: InnovationOpportunityReport,
    experiment_brief: ExperimentDesignBrief,
    method_report: MethodImprovementReport,
) -> tuple[PaperStorylineNode, ...]:
    opportunity = _selected_opportunity(opportunity_report, experiment_brief)
    method_recommendation = (
        method_report.recommendations[0] if method_report.recommendations else None
    )
    nodes = [
        _node(
            node_id="problem",
            node_role="problem",
            label=opportunity.anchor_observation,
            summary=opportunity.observed_problem,
            support_level=opportunity.support_level,
            source_artifacts=("innovation_opportunity_report.v1",),
            evidence_anchors=opportunity.evidence_anchors,
            provenance="opportunity_observed_problem",
        ),
        _node(
            node_id="gap",
            node_role="gap",
            label=opportunity.abstract_challenge,
            summary=opportunity.observed_problem,
            support_level=opportunity.support_level,
            source_artifacts=("innovation_opportunity_report.v1",),
            evidence_anchors=opportunity.evidence_anchors,
            provenance="opportunity_abstract_challenge",
        ),
        _node(
            node_id="idea",
            node_role="idea",
            label=opportunity.transfer_mechanism,
            summary=opportunity.proposed_storyline,
            support_level=opportunity.support_level,
            source_artifacts=("innovation_opportunity_report.v1",),
            evidence_anchors=opportunity.evidence_anchors,
            warnings=opportunity.novelty_risks,
            provenance="opportunity_advisory_storyline",
        ),
        _node(
            node_id="method",
            node_role="method",
            label=method_report.method_name,
            summary=(
                method_recommendation.recommended_change
                if method_recommendation
                else experiment_brief.hypothesis
            ),
            support_level=method_report.support_level,
            source_artifacts=(
                "method_improvement_report.v1",
                "experiment_design_brief.v1",
            ),
            evidence_anchors=method_report.evidence_anchors,
            provenance="method_recommendation_or_experiment_hypothesis",
        ),
        _node(
            node_id="experiment",
            node_role="experiment",
            label=experiment_brief.target_task,
            summary="; ".join(experiment_brief.acceptance_criteria),
            support_level=experiment_brief.support_level,
            source_artifacts=("experiment_design_brief.v1",),
            evidence_anchors=experiment_brief.evidence_anchors,
            provenance="experiment_design_acceptance_criteria",
        ),
        _node(
            node_id="result_plan",
            node_role="result",
            label="planned validation outputs",
            summary="; ".join(experiment_brief.expected_outputs),
            support_level=experiment_brief.support_level,
            source_artifacts=("experiment_design_brief.v1",),
            evidence_anchors=experiment_brief.evidence_anchors,
            provenance="experiment_design_expected_outputs",
        ),
        _node(
            node_id="limitation",
            node_role="limitation",
            label="claim remains bounded by available evidence",
            summary=_limitation_summary(
                opportunity_report=opportunity_report,
                experiment_brief=experiment_brief,
                method_report=method_report,
            ),
            support_level="weakly_supported",
            source_artifacts=(
                "innovation_opportunity_report.v1",
                "experiment_design_brief.v1",
                "method_improvement_report.v1",
            ),
            evidence_anchors=_dedupe_anchors(
                (
                    *opportunity.evidence_anchors,
                    *experiment_brief.evidence_anchors,
                    *method_report.evidence_anchors,
                )
            ),
            warnings=("cross-domain analogy is inspiration, not proof of novelty",),
            provenance="artifact_warnings_and_support_levels",
        ),
        _node(
            node_id="contribution_claim",
            node_role="contribution_claim",
            label="evidence-grounded verifier-gated synthesis contribution",
            summary=_contribution_summary(opportunity, experiment_brief, method_report),
            support_level=_combined_claim_support(
                opportunity.support_level,
                experiment_brief.support_level,
                method_report.support_level,
            ),
            source_artifacts=(
                "innovation_opportunity_report.v1",
                "experiment_design_brief.v1",
                "method_improvement_report.v1",
            ),
            evidence_anchors=_dedupe_anchors(
                (
                    *opportunity.evidence_anchors,
                    *experiment_brief.evidence_anchors,
                    *method_report.evidence_anchors,
                )
            ),
            warnings=_claim_warnings(opportunity, experiment_brief, method_report),
            provenance="support_level_and_evidence_anchors",
        ),
    ]
    if context_pack.pages:
        nodes.append(
            _node(
                node_id="related_evidence",
                node_role="related_work",
                label=context_pack.pages[0].title,
                summary=context_pack.pages[0].excerpt,
                support_level="evidence_bound",
                source_artifacts=("wiki_context_pack.v1",),
                evidence_anchors=context_pack.pages[0].evidence_anchors,
                provenance="wiki_context_page",
            )
        )
    return tuple(nodes)


def _node(
    *,
    node_id: str,
    node_role: str,
    label: str,
    summary: str,
    support_level: str,
    source_artifacts: tuple[str, ...],
    evidence_anchors: tuple[ResearchWikiEvidenceAnchor, ...],
    provenance: str,
    warnings: tuple[str, ...] = (),
) -> PaperStorylineNode:
    anchors = _dedupe_anchors(evidence_anchors)
    claim_status = _claim_status(
        support_level=support_level,
        evidence_anchors=anchors,
        node_role=node_role,
    )
    node_warnings = list(warnings)
    if claim_status == "unsupported" and node_role in _CLAIM_ROLES:
        node_warnings.append("claim_lacks_evidence_anchors")
    return PaperStorylineNode(
        node_id=node_id,
        node_role=node_role,
        label=" ".join(str(label or node_id).split()),
        summary=" ".join(str(summary or label or node_id).split()),
        claim_status=claim_status,
        source_artifacts=source_artifacts,
        evidence_anchors=anchors,
        warnings=tuple(dict.fromkeys(node_warnings)),
        field_provenance={
            "label": provenance,
            "summary": provenance,
            "claim_status": "support_level_and_evidence_anchors",
        },
    )


def _claim_status(
    *,
    support_level: str,
    evidence_anchors: tuple[ResearchWikiEvidenceAnchor, ...],
    node_role: str,
) -> str:
    if not evidence_anchors and node_role in _CLAIM_ROLES:
        return "unsupported"
    if support_level == "evidence_bound" and evidence_anchors:
        return "evidence_bound"
    if support_level == "speculative":
        return "speculative" if evidence_anchors else "unsupported"
    return "weakly_supported" if evidence_anchors else "unsupported"


def _storyline_edges(
    nodes: tuple[PaperStorylineNode, ...],
) -> tuple[PaperStorylineEdge, ...]:
    order = [
        "problem",
        "gap",
        "idea",
        "method",
        "experiment",
        "result_plan",
        "contribution_claim",
        "limitation",
    ]
    node_ids = {node.node_id for node in nodes}
    edges: list[PaperStorylineEdge] = []
    for source, target in zip(order, order[1:]):
        if source in node_ids and target in node_ids:
            edges.append(
                PaperStorylineEdge(
                    source_node_id=source,
                    target_node_id=target,
                    relation="supports_storyline_step",
                    field_provenance="fixed_storyline_role_order",
                )
            )
    if "related_evidence" in node_ids and "problem" in node_ids:
        edges.append(
            PaperStorylineEdge(
                source_node_id="related_evidence",
                target_node_id="problem",
                relation="provides_background_evidence",
                field_provenance="wiki_context_pack",
            )
        )
    return tuple(edges)


def _section_pack(
    *,
    graph: PaperStorylineGraph,
    section_name: str,
) -> SectionEvidencePack:
    roles = _section_roles(section_name)
    nodes = tuple(node for node in graph.nodes if node.node_role in roles)
    required_statuses = _required_statuses(section_name)
    warnings = []
    if any(
        node.claim_status == "unsupported" and node.node_role in _CLAIM_ROLES
        for node in nodes
    ):
        warnings.append("unsupported_claims_present")
    return SectionEvidencePack(
        schema_version=SECTION_EVIDENCE_PACK_SCHEMA_VERSION,
        artifact_role="advisory_compiled_view",
        topic_id=graph.topic_id,
        section_name=section_name,
        required_claim_statuses=required_statuses,
        nodes=nodes,
        evidence_anchors=_dedupe_anchors(
            tuple(anchor for node in nodes for anchor in node.evidence_anchors)
        ),
        warnings=tuple(warnings),
    )


def _section_roles(section_name: str) -> tuple[str, ...]:
    normalized = section_name.lower().replace("-", "_")
    mapping = {
        "abstract": (
            "problem",
            "idea",
            "method",
            "contribution_claim",
            "limitation",
        ),
        "introduction": (
            "problem",
            "gap",
            "idea",
            "contribution_claim",
            "limitation",
        ),
        "related_work": ("related_work", "gap", "limitation"),
        "method": ("method", "idea", "experiment"),
        "experiments": ("experiment", "result", "limitation"),
        "limitations": ("limitation", "contribution_claim"),
    }
    return mapping.get(normalized, ("problem", "idea", "contribution_claim"))


def _required_statuses(section_name: str) -> tuple[str, ...]:
    normalized = section_name.lower().replace("-", "_")
    if normalized in {"abstract", "introduction", "conclusion"}:
        return ("evidence_bound", "weakly_supported")
    if normalized == "limitations":
        return ("evidence_bound", "weakly_supported", "speculative")
    return ("evidence_bound", "weakly_supported")


def _claim_integrity(nodes: tuple[PaperStorylineNode, ...]) -> dict[str, int]:
    claim_nodes = [node for node in nodes if node.node_role in _CLAIM_ROLES]
    return {
        "claim_count": len(claim_nodes),
        "evidence_bound_claim_count": sum(
            node.claim_status == "evidence_bound" for node in claim_nodes
        ),
        "weakly_supported_claim_count": sum(
            node.claim_status == "weakly_supported" for node in claim_nodes
        ),
        "speculative_claim_count": sum(
            node.claim_status == "speculative" for node in claim_nodes
        ),
        "unsupported_claim_count": sum(
            node.claim_status == "unsupported" for node in claim_nodes
        ),
    }


def _graph_warnings(
    *,
    nodes: tuple[PaperStorylineNode, ...],
    context_pack: WikiContextPack,
    opportunity_report: InnovationOpportunityReport,
    experiment_brief: ExperimentDesignBrief,
    method_report: MethodImprovementReport,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if context_pack.degraded:
        warnings.append("context_pack_degraded")
    if context_pack.truncated:
        warnings.append("context_pack_truncated")
    warnings.extend(opportunity_report.warnings)
    warnings.extend(experiment_brief.warnings)
    warnings.extend(method_report.warnings)
    if any(
        node.claim_status == "unsupported" and node.node_role in _CLAIM_ROLES
        for node in nodes
    ):
        warnings.append("unsupported_claims_present")
    if any(node.claim_status == "speculative" for node in nodes):
        warnings.append("speculative_claims_present")
    return tuple(dict.fromkeys(warnings))


def _combined_claim_support(*support_levels: str) -> str:
    if any(level == "speculative" for level in support_levels):
        return "speculative"
    if all(level == "evidence_bound" for level in support_levels):
        return "evidence_bound"
    return "weakly_supported"


def _contribution_summary(
    opportunity,
    brief: ExperimentDesignBrief,
    method_report: MethodImprovementReport,
) -> str:
    return (
        f"{opportunity.proposed_storyline} The validation plan tests "
        f"{brief.hypothesis} and method repair recommends "
        f"{method_report.recommendations[0].recommended_change if method_report.recommendations else method_report.method_name}."
    )


def _limitation_summary(
    *,
    opportunity_report: InnovationOpportunityReport,
    experiment_brief: ExperimentDesignBrief,
    method_report: MethodImprovementReport,
) -> str:
    values = [
        "cross-domain analogies do not prove novelty",
        *opportunity_report.warnings,
        *experiment_brief.warnings,
        *method_report.warnings,
    ]
    return "; ".join(dict.fromkeys(value for value in values if value))


def _claim_warnings(
    opportunity,
    brief: ExperimentDesignBrief,
    method_report: MethodImprovementReport,
) -> tuple[str, ...]:
    warnings = [*opportunity.novelty_risks, *brief.warnings, *method_report.warnings]
    if opportunity.support_level != "evidence_bound":
        warnings.append("opportunity_not_evidence_bound")
    if brief.support_level != "evidence_bound":
        warnings.append("experiment_brief_not_evidence_bound")
    if method_report.support_level != "evidence_bound":
        warnings.append("method_report_not_evidence_bound")
    return tuple(dict.fromkeys(warnings))


def _empty_method_report(brief: ExperimentDesignBrief) -> MethodImprovementReport:
    return MethodImprovementReport(
        schema_version="method_improvement_report.v1",
        artifact_role="advisory_compiled_view",
        topic_id=brief.topic_id,
        opportunity_id=brief.opportunity_id,
        method_name=brief.hypothesis,
        support_level=brief.support_level,
        failure_diagnoses=(),
        recommendations=(),
        warnings=("method_improvement_report_missing",),
        evidence_anchors=brief.evidence_anchors,
    )


def _node_to_dict(node: PaperStorylineNode) -> dict[str, Any]:
    return {
        "node_id": node.node_id,
        "node_role": node.node_role,
        "label": node.label,
        "summary": node.summary,
        "claim_status": node.claim_status,
        "source_artifacts": list(node.source_artifacts),
        "warnings": list(node.warnings),
        "field_provenance": dict(node.field_provenance),
        "evidence_anchors": [
            _evidence_anchor_to_dict(anchor) for anchor in node.evidence_anchors
        ],
    }


def _edge_to_dict(edge: PaperStorylineEdge) -> dict[str, str]:
    return {
        "source_node_id": edge.source_node_id,
        "target_node_id": edge.target_node_id,
        "relation": edge.relation,
        "field_provenance": edge.field_provenance,
    }


def _evidence_anchor_to_dict(
    anchor: ResearchWikiEvidenceAnchor,
) -> dict[str, Any]:
    return {
        "page_path": anchor.page_path,
        "paper_id": anchor.paper_id,
        "source_type": anchor.source_type,
        "source_id": anchor.source_id,
        "source_hash": anchor.source_hash,
        "section_anchor": anchor.section_anchor,
        "evidence_snippet": anchor.evidence_snippet,
    }


def _dedupe_anchors(
    anchors: tuple[ResearchWikiEvidenceAnchor, ...],
) -> tuple[ResearchWikiEvidenceAnchor, ...]:
    by_key = {
        (
            anchor.page_path,
            anchor.paper_id,
            anchor.source_type,
            anchor.source_id,
            anchor.source_hash,
            anchor.section_anchor,
            anchor.evidence_snippet,
        ): anchor
        for anchor in anchors
    }
    return tuple(by_key[key] for key in sorted(by_key))


def _append_section(
    lines: list[str],
    title: str,
    values: tuple[str, ...],
) -> None:
    lines.extend([f"## {title}", ""])
    if values:
        lines.extend(f"- {value}" for value in values)
    else:
        lines.append("- none")
    lines.append("")
