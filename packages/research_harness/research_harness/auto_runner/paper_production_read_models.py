"""RH-native read models for the paper-production workbench.

The classes in this module are serialization contracts for artifacts, HTTP
read endpoints, and UI panels. They do not perform storage migration, execute
jobs, inspect local process IDs, or decide whether a paper is publication-ready.
Final bundle, publication pack, citation, provenance, and figure gates remain
the authoritative readiness checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


RESEARCH_HYPOTHESIS_TREE_SCHEMA_VERSION = "rh.research_hypothesis_tree.v1"
HYPOTHESIS_EXPERIMENT_JOB_SCHEMA_VERSION = "rh.hypothesis_experiment_job.v1"
PAPER_PRODUCTION_RUN_SNAPSHOT_SCHEMA_VERSION = "rh.paper_production_run_snapshot.v1"
VENUE_COMPLIANCE_REPORT_SCHEMA_VERSION = "rh.venue_compliance_report.v1"
BENCHMARK_RESOURCE_PACK_SCHEMA_VERSION = "rh.resource_pack.benchmark.v1"
WRITING_STYLE_RESOURCE_PACK_SCHEMA_VERSION = "rh.resource_pack.writing_style.v1"
VENUE_KIT_RESOURCE_PACK_SCHEMA_VERSION = "rh.resource_pack.venue_kit.v1"
REFERENCE_CODEBASE_RESOURCE_PACK_SCHEMA_VERSION = (
    "rh.resource_pack.reference_codebase.v1"
)

HYPOTHESIS_STATUSES = (
    "supported",
    "refuted",
    "inconclusive",
    "blocked",
    "untested",
)


def _dict_tuple(items: tuple[Mapping[str, Any], ...]) -> list[dict[str, Any]]:
    return [dict(item) for item in items]


@dataclass(frozen=True)
class HypothesisStopPolicy:
    target_supported: int
    max_tested: int
    max_depth: int

    def to_dict(self) -> dict[str, int]:
        return {
            "target_supported": self.target_supported,
            "max_tested": self.max_tested,
            "max_depth": self.max_depth,
        }


@dataclass(frozen=True)
class HypothesisTreeNode:
    id: str
    statement: str
    rationale: str
    test: str
    status: str
    stage: str
    parent_id: str | None = None
    children: tuple[str, ...] = ()
    plan_artifact_id: str | None = None
    experiment_artifact_id: str | None = None
    result_artifact_id: str | None = None
    report_artifact_id: str | None = None
    claim_ids: tuple[str, ...] = ()
    evidence_refs: tuple[Mapping[str, Any], ...] = ()
    expanded: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "statement": self.statement,
            "rationale": self.rationale,
            "test": self.test,
            "status": self.status,
            "stage": self.stage,
            "parent_id": self.parent_id,
            "children": list(self.children),
            "plan_artifact_id": self.plan_artifact_id,
            "experiment_artifact_id": self.experiment_artifact_id,
            "result_artifact_id": self.result_artifact_id,
            "report_artifact_id": self.report_artifact_id,
            "claim_ids": list(self.claim_ids),
            "evidence_refs": _dict_tuple(self.evidence_refs),
            "expanded": self.expanded,
        }


@dataclass(frozen=True)
class ResearchHypothesisTree:
    topic_id: str
    paper_plan_artifact_id: str | None
    nodes: tuple[HypothesisTreeNode, ...]
    stop_policy: HypothesisStopPolicy

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RESEARCH_HYPOTHESIS_TREE_SCHEMA_VERSION,
            "topic_id": self.topic_id,
            "paper_plan_artifact_id": self.paper_plan_artifact_id,
            "nodes": [node.to_dict() for node in self.nodes],
            "stop_policy": self.stop_policy.to_dict(),
            "status_summary": self.status_summary(),
        }

    def status_summary(self) -> dict[str, int]:
        summary = {status: 0 for status in HYPOTHESIS_STATUSES}
        for node in self.nodes:
            if node.status in summary:
                summary[node.status] += 1
        return summary


@dataclass(frozen=True)
class HypothesisExperimentJob:
    topic_id: str
    hypothesis_id: str
    run_id: str
    status: str
    effective_config: Mapping[str, Any]
    attempts: tuple[Mapping[str, Any], ...]
    events_ref: Mapping[str, Any]
    result_artifact_id: str | None = None
    report_artifact_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": HYPOTHESIS_EXPERIMENT_JOB_SCHEMA_VERSION,
            "topic_id": self.topic_id,
            "hypothesis_id": self.hypothesis_id,
            "run_id": self.run_id,
            "status": self.status,
            "effective_config": dict(self.effective_config),
            "attempts": _dict_tuple(self.attempts),
            "events_ref": dict(self.events_ref),
            "result_artifact_id": self.result_artifact_id,
            "report_artifact_id": self.report_artifact_id,
        }


@dataclass(frozen=True)
class PaperProductionRunSnapshot:
    topic_id: str
    current_stage: str
    current_milestone: str
    active_direction_or_idea: str
    active_hypothesis_id: str | None
    supported: int
    refuted: int
    inconclusive: int
    blocked: int
    blockers: tuple[str, ...]
    next_action: str
    final_bundle_ready: bool
    publication_pack_ready: bool
    venue_compliance_ready: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PAPER_PRODUCTION_RUN_SNAPSHOT_SCHEMA_VERSION,
            "topic_id": self.topic_id,
            "current_stage": self.current_stage,
            "current_milestone": self.current_milestone,
            "active_direction_or_idea": self.active_direction_or_idea,
            "active_hypothesis_id": self.active_hypothesis_id,
            "supported": self.supported,
            "refuted": self.refuted,
            "inconclusive": self.inconclusive,
            "blocked": self.blocked,
            "blockers": list(self.blockers),
            "next_action": self.next_action,
            "final_bundle_ready": self.final_bundle_ready,
            "publication_pack_ready": self.publication_pack_ready,
            "venue_compliance_ready": self.venue_compliance_ready,
        }


@dataclass(frozen=True)
class VenueComplianceReport:
    topic_id: str
    status: str
    latex_compile_success: bool
    disallowed_packages: tuple[str, ...]
    disallowed_commands: tuple[str, ...]
    missing_files: tuple[str, ...]
    undefined_citations: tuple[str, ...]
    undefined_references: tuple[str, ...]
    overfull_box_warnings: tuple[str, ...]
    main_text_page_count: int | None
    page_limit: int | None
    references_appendix_excluded: bool
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": VENUE_COMPLIANCE_REPORT_SCHEMA_VERSION,
            "topic_id": self.topic_id,
            "status": self.status,
            "latex_compile_success": self.latex_compile_success,
            "disallowed_packages": list(self.disallowed_packages),
            "disallowed_commands": list(self.disallowed_commands),
            "missing_files": list(self.missing_files),
            "undefined_citations": list(self.undefined_citations),
            "undefined_references": list(self.undefined_references),
            "overfull_box_warnings": list(self.overfull_box_warnings),
            "main_text_page_count": self.main_text_page_count,
            "page_limit": self.page_limit,
            "references_appendix_excluded": self.references_appendix_excluded,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class BenchmarkResourcePack:
    pack_id: str
    name: str
    dataset: str
    metric: str
    baseline: str
    cited_leaderboard: str
    bibtex_refs: tuple[str, ...]
    protocol: str
    expected_outputs: tuple[str, ...]
    provenance_refs: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": BENCHMARK_RESOURCE_PACK_SCHEMA_VERSION,
            "pack_id": self.pack_id,
            "name": self.name,
            "dataset": self.dataset,
            "metric": self.metric,
            "baseline": self.baseline,
            "cited_leaderboard": self.cited_leaderboard,
            "bibtex_refs": list(self.bibtex_refs),
            "protocol": self.protocol,
            "expected_outputs": list(self.expected_outputs),
            "provenance_refs": _dict_tuple(self.provenance_refs),
        }


@dataclass(frozen=True)
class WritingStyleResourcePack:
    pack_id: str
    name: str
    target_venue: str
    tone: str
    section_guidance: Mapping[str, Any]
    bibtex_refs: tuple[str, ...] = ()
    provenance_refs: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": WRITING_STYLE_RESOURCE_PACK_SCHEMA_VERSION,
            "pack_id": self.pack_id,
            "name": self.name,
            "target_venue": self.target_venue,
            "tone": self.tone,
            "section_guidance": dict(self.section_guidance),
            "bibtex_refs": list(self.bibtex_refs),
            "provenance_refs": _dict_tuple(self.provenance_refs),
        }


@dataclass(frozen=True)
class VenueKitResourcePack:
    pack_id: str
    name: str
    target_venue: str
    template_artifact_id: str | None
    page_limit: int | None
    disallowed_packages: tuple[str, ...]
    disallowed_commands: tuple[str, ...]
    required_sections: tuple[str, ...]
    anonymization_required: bool
    bibtex_refs: tuple[str, ...] = ()
    provenance_refs: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": VENUE_KIT_RESOURCE_PACK_SCHEMA_VERSION,
            "pack_id": self.pack_id,
            "name": self.name,
            "target_venue": self.target_venue,
            "template_artifact_id": self.template_artifact_id,
            "page_limit": self.page_limit,
            "disallowed_packages": list(self.disallowed_packages),
            "disallowed_commands": list(self.disallowed_commands),
            "required_sections": list(self.required_sections),
            "anonymization_required": self.anonymization_required,
            "bibtex_refs": list(self.bibtex_refs),
            "provenance_refs": _dict_tuple(self.provenance_refs),
        }


@dataclass(frozen=True)
class ReferenceCodebaseResourcePack:
    pack_id: str
    name: str
    repo_ref: str
    commit: str
    license: str
    setup: str
    expected_entrypoints: tuple[str, ...]
    provenance_refs: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": REFERENCE_CODEBASE_RESOURCE_PACK_SCHEMA_VERSION,
            "pack_id": self.pack_id,
            "name": self.name,
            "repo_ref": self.repo_ref,
            "commit": self.commit,
            "license": self.license,
            "setup": self.setup,
            "expected_entrypoints": list(self.expected_entrypoints),
            "provenance_refs": _dict_tuple(self.provenance_refs),
        }
