"""ResearchFlowBench task-pack construction helpers.

The builder is intentionally model-free. It materializes public-safe synthetic
Pilot-20 packs, then routes the generated files through the existing validators
before callers use the pack in a benchmark run.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ._runtime_common import EXTERNAL_SEARCH_TOOLS, sha256_file
from .leakage import validate_leakage_audit
from .preflight import validate_allowed_tools_preflight
from .validators import ValidationReport, validate_pilot20_task_pack


@dataclass(frozen=True)
class ResearchFlowBenchTaskSpec:
    """One synthetic Pilot-20 task to materialize."""

    task_no: str
    slug: str
    stage: str
    task_id: str
    corrupted_case_id: str
    expected_semantic_objects: tuple[str, ...]
    expected_rh_axes: tuple[str, ...]
    prompt: str
    prompt_context: str
    outcome_oracle: dict[str, Any]
    process_oracle: dict[str, Any]
    allowed_tools: tuple[str, ...] = ("local_static_corpus",)
    external_search_policy: str = "forbidden_in_v0"
    split: str = "draft_dev"
    status: str = "draft_not_release_grade"
    synthetic: bool = True
    visibility: str = "public_safe_synthetic_fixture"
    source_snapshot_id: str = "synthetic_public_static_corpus_v0"
    local_corpus_content: str = ""

    @property
    def directory(self) -> str:
        return f"tasks/{self.task_no}_{self.slug}"

    @property
    def template_id(self) -> str:
        return f"researchflowbench.synthetic-{self.task_no}"

    @property
    def gold_asset_id(self) -> str:
        return f"evidence.{self.task_no}.synthetic_public"

    @property
    def hidden_canary(self) -> str:
        return f"SYNTHETIC_HIDDEN_CANARY_{self.task_no}"

    @property
    def judge_canary(self) -> str:
        return f"SYNTHETIC_JUDGE_CANARY_{self.task_no}"


@dataclass(frozen=True)
class ResearchFlowBenchPackSpec:
    """Synthetic Pilot-20 pack specification."""

    pack_id: str = "researchflowbench.synthetic_public_pilot20_v0"
    schema_version: str = "researchflowbench.pilot20_manifest.v0.synthetic"
    synthetic: bool = True
    visibility: str = "public_safe_synthetic_fixture"
    model_execution_performed: bool = False
    tasks: tuple[ResearchFlowBenchTaskSpec, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TaskPackBuildResult:
    """Result of materializing and validating a task pack."""

    root: Path
    task_count: int
    validation_report: ValidationReport
    preflight_reports: tuple[dict[str, Any], ...] = ()
    leakage_reports: tuple[dict[str, Any], ...] = ()


class TaskPackBuildError(RuntimeError):
    """Raised when strict task-pack construction produces invalid output."""


def synthetic_pilot20_pack_spec() -> ResearchFlowBenchPackSpec:
    """Return the public-safe synthetic Pilot-20 v0 seed specification."""

    return ResearchFlowBenchPackSpec(
        tasks=tuple(_task(*blueprint) for blueprint in _PILOT20_BLUEPRINTS)
    )


_PILOT20_BLUEPRINTS: tuple[
    tuple[str, str, str, str, str, tuple[str, ...], tuple[str, ...]], ...
] = (
    (
        "T01",
        "full_context_citation_eval",
        "literature",
        "rfb.synthetic.full_context_citation_eval.0001",
        "C01_full_context_citation_contradiction",
        (
            "claim",
            "citation_link",
            "evidence_span",
            "review_issue",
            "gate_decision",
            "run_trace",
        ),
        (
            "citation.candidate_generation",
            "evidence_linking.support_accuracy",
            "section_drafting.citation_grounding",
        ),
    ),
    (
        "T02",
        "open_world_attribution_abstain",
        "literature",
        "rfb.synthetic.open_world_attribution_abstain.0001",
        "C02_open_world_ambiguous_or_missing_source",
        (
            "paper",
            "claim",
            "evidence_span",
            "citation_link",
            "review_issue",
            "gate_decision",
            "run_trace",
        ),
        (
            "paper_search.recall",
            "citation.candidate_generation",
            "governance.rollback_blocking",
        ),
    ),
    (
        "T03",
        "partial_support_claim",
        "synthesis",
        "rfb.synthetic.partial_support_claim.0001",
        "C03_composite_claim_partial_support",
        (
            "claim",
            "evidence_span",
            "citation_link",
            "review_issue",
            "gate_decision",
            "run_trace",
        ),
        (
            "paper_reading.claim_quality",
            "evidence_linking.support_accuracy",
            "citation.candidate_generation",
        ),
    ),
    (
        "T04",
        "evidence_stale_propagation",
        "rollback",
        "rfb.synthetic.evidence_stale_propagation.0001",
        "C04_evidence_correction_stale_propagation",
        (
            "evidence_span",
            "citation_link",
            "claim",
            "section_draft",
            "gate_decision",
            "rollback_event",
            "run_trace",
        ),
        (
            "evidence_linking.support_accuracy",
            "section_drafting.citation_grounding",
            "governance.rollback_blocking",
        ),
    ),
    (
        "T05",
        "false_novelty_baseline_gap",
        "planning",
        "rfb.synthetic.false_novelty_baseline_gap.0001",
        "C05_false_novelty_missing_close_priors",
        (
            "claim",
            "baseline",
            "evidence_span",
            "review_issue",
            "gate_decision",
            "rollback_event",
            "run_trace",
        ),
        (
            "gap_detection.novelty_accuracy",
            "baseline_identification.coverage",
            "governance.rollback_blocking",
        ),
    ),
    (
        "T06",
        "query_intent_decomposition",
        "build",
        "rfb.synthetic.query_intent_decomposition.0001",
        "C06_query_intent_under_specification",
        (
            "query",
            "paper",
            "evidence_span",
            "retrieval_trace",
            "gate_decision",
            "run_trace",
        ),
        ("paper_search.recall", "literature.set_completion"),
    ),
    (
        "T07",
        "rerank_near_miss",
        "build",
        "rfb.synthetic.rerank_near_miss.0001",
        "C07_relevant_paper_buried_by_surface_match",
        (
            "paper",
            "retrieval_trace",
            "ranked_result",
            "review_issue",
            "gate_decision",
            "run_trace",
        ),
        ("paper_search.rerank_quality", "retrieval.provenance_coverage"),
    ),
    (
        "T08",
        "dedupe_author_title_variant",
        "build",
        "rfb.synthetic.dedupe_author_title_variant.0001",
        "C08_duplicate_paper_variant_split",
        (
            "paper",
            "dedupe_decision",
            "retrieval_trace",
            "review_issue",
            "gate_decision",
            "run_trace",
        ),
        (
            "literature.set_completion",
            "paper_selection.precision",
            "retrieval.provenance_coverage",
        ),
    ),
    (
        "T09",
        "citation_identifier_hallucination",
        "write",
        "rfb.synthetic.citation_identifier_hallucination.0001",
        "C09_hallucinated_identifier_in_citation",
        (
            "claim",
            "citation_link",
            "paper",
            "review_issue",
            "gate_decision",
            "run_trace",
        ),
        ("citation.candidate_generation", "governance.rollback_blocking"),
    ),
    (
        "T10",
        "baseline_cluster_boundary",
        "analyze",
        "rfb.synthetic.baseline_cluster_boundary.0001",
        "C10_baseline_family_boundary_confusion",
        (
            "baseline",
            "paper_cluster",
            "claim",
            "review_issue",
            "gate_decision",
            "run_trace",
        ),
        (
            "baseline_identification.coverage",
            "gap_detection.novelty_accuracy",
            "deep_research.discovery_accuracy",
        ),
    ),
    (
        "T11",
        "negative_evidence_preservation",
        "synthesis",
        "rfb.synthetic.negative_evidence_preservation.0001",
        "C11_negative_evidence_dropped",
        (
            "claim",
            "evidence_span",
            "citation_link",
            "review_issue",
            "gate_decision",
            "run_trace",
        ),
        (
            "paper_reading.claim_quality",
            "evidence_linking.support_accuracy",
            "citation.candidate_generation",
        ),
    ),
    (
        "T12",
        "cross_topic_provenance_guard",
        "governance",
        "rfb.synthetic.cross_topic_provenance_guard.0001",
        "C12_cross_topic_source_contamination",
        (
            "paper",
            "retrieval_trace",
            "citation_link",
            "review_issue",
            "gate_decision",
            "run_trace",
        ),
        (
            "retrieval.provenance_coverage",
            "citation.candidate_generation",
            "governance.rollback_blocking",
        ),
    ),
    (
        "T13",
        "claim_scope_overreach",
        "write",
        "rfb.synthetic.claim_scope_overreach.0001",
        "C13_claim_scope_exceeds_evidence",
        (
            "claim",
            "evidence_span",
            "section_draft",
            "review_issue",
            "gate_decision",
            "run_trace",
        ),
        (
            "paper_reading.claim_quality",
            "evidence_linking.support_accuracy",
            "section_drafting.citation_grounding",
        ),
    ),
    (
        "T14",
        "multi_source_rank_conflict",
        "build",
        "rfb.synthetic.multi_source_rank_conflict.0001",
        "C14_conflicting_rank_sources_unresolved",
        (
            "paper",
            "retrieval_trace",
            "ranked_result",
            "review_issue",
            "gate_decision",
            "run_trace",
        ),
        ("paper_search.rerank_quality", "retrieval.provenance_coverage"),
    ),
    (
        "T15",
        "survey_facet_gap",
        "analyze",
        "rfb.synthetic.survey_facet_gap.0001",
        "C15_missing_subtopic_facet",
        (
            "paper_cluster",
            "baseline",
            "claim",
            "review_issue",
            "gate_decision",
            "run_trace",
        ),
        (
            "gap_detection.novelty_accuracy",
            "baseline_identification.coverage",
            "literature.set_completion",
        ),
    ),
    (
        "T16",
        "deep_anchor_selection",
        "build",
        "rfb.synthetic.deep_anchor_selection.0001",
        "C16_wrong_anchor_paper_selected",
        (
            "query",
            "paper",
            "retrieval_trace",
            "selection_rationale",
            "gate_decision",
            "run_trace",
        ),
        ("deep_research.discovery_accuracy", "paper_search.recall"),
    ),
    (
        "T17",
        "evidence_link_granularity",
        "synthesis",
        "rfb.synthetic.evidence_link_granularity.0001",
        "C17_overbroad_evidence_span",
        (
            "claim",
            "evidence_span",
            "citation_link",
            "review_issue",
            "gate_decision",
            "run_trace",
        ),
        ("evidence_linking.support_accuracy", "citation.candidate_generation"),
    ),
    (
        "T18",
        "artifact_trace_completeness",
        "governance",
        "rfb.synthetic.artifact_trace_completeness.0001",
        "C18_missing_artifact_trace_edge",
        (
            "artifact_ref",
            "retrieval_trace",
            "gate_decision",
            "review_issue",
            "run_trace",
        ),
        ("retrieval.provenance_coverage", "governance.rollback_blocking"),
    ),
    (
        "T19",
        "stale_baseline_after_update",
        "rollback",
        "rfb.synthetic.stale_baseline_after_update.0001",
        "C19_stale_baseline_after_pool_update",
        (
            "baseline",
            "paper",
            "rollback_event",
            "review_issue",
            "gate_decision",
            "run_trace",
        ),
        (
            "baseline_identification.coverage",
            "gap_detection.novelty_accuracy",
            "governance.rollback_blocking",
        ),
    ),
    (
        "T20",
        "final_bundle_citation_integrity",
        "write",
        "rfb.synthetic.final_bundle_citation_integrity.0001",
        "C20_final_bundle_unsupported_citation",
        (
            "section_draft",
            "claim",
            "citation_link",
            "review_issue",
            "gate_decision",
            "run_trace",
        ),
        (
            "section_drafting.citation_grounding",
            "final_bundle.pdf_quality",
            "citation.candidate_generation",
            "governance.rollback_blocking",
        ),
    ),
)


def build_synthetic_pilot20_task_pack(
    root: str | Path,
    *,
    spec: ResearchFlowBenchPackSpec | None = None,
    overwrite: bool = False,
    strict: bool = True,
) -> TaskPackBuildResult:
    """Materialize a synthetic Pilot-20 task pack under ``root``."""

    return build_pilot20_task_pack(
        spec or synthetic_pilot20_pack_spec(),
        root,
        overwrite=overwrite,
        strict=strict,
    )


def build_pilot20_task_pack(
    spec: ResearchFlowBenchPackSpec,
    root: str | Path,
    *,
    overwrite: bool = False,
    strict: bool = True,
) -> TaskPackBuildResult:
    """Write a Pilot-20 task pack and validate the generated contracts."""

    root_path = Path(root)
    _prepare_root(root_path, overwrite=overwrite)
    _write_pack_files(root_path, spec)
    validation_report = validate_pilot20_task_pack(root_path)
    task_dirs = tuple(sorted((root_path / "tasks").glob("T*_*/")))
    preflight_reports = tuple(
        validate_allowed_tools_preflight(path) for path in task_dirs
    )
    leakage_reports = tuple(validate_leakage_audit(path) for path in task_dirs)
    result = TaskPackBuildResult(
        root=root_path,
        task_count=len(task_dirs),
        validation_report=validation_report,
        preflight_reports=preflight_reports,
        leakage_reports=leakage_reports,
    )
    if strict:
        failures = _strict_failures(result)
        if failures:
            raise TaskPackBuildError(
                "ResearchFlowBench task-pack build failed: "
                + ", ".join(sorted(set(failures)))
            )
    return result


def _task(
    task_no: str,
    slug: str,
    stage: str,
    task_id: str,
    corrupted_case_id: str,
    expected_semantic_objects: tuple[str, ...],
    expected_rh_axes: tuple[str, ...],
) -> ResearchFlowBenchTaskSpec:
    return ResearchFlowBenchTaskSpec(
        task_no=task_no,
        slug=slug,
        stage=stage,
        task_id=task_id,
        corrupted_case_id=corrupted_case_id,
        expected_semantic_objects=expected_semantic_objects,
        expected_rh_axes=expected_rh_axes,
        prompt=(
            f"# Synthetic ResearchFlowBench {task_no} prompt\n\n"
            "Use only the local static corpus fixture exposed for this public-safe test.\n"
            "This fixture contains synthetic text only and performs no model experiment.\n"
        ),
        prompt_context=f"Synthetic public-safe context for {task_no}.",
        outcome_oracle={"expected": f"Synthetic outcome oracle for {task_no}."},
        process_oracle={"expected": f"Synthetic process oracle for {task_no}."},
        local_corpus_content=f"Synthetic public-safe local corpus record for {task_no}.",
    )


def _prepare_root(root: Path, *, overwrite: bool) -> None:
    if root.exists() and any(root.iterdir()):
        if not overwrite:
            raise FileExistsError(f"output directory is not empty: {root}")
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)


def _write_pack_files(root: Path, spec: ResearchFlowBenchPackSpec) -> None:
    (root / "README.md").write_text(_pack_readme(spec), encoding="utf-8")
    _write_json(
        root / "README.fixture.json",
        {
            "description": "Synthetic Pilot-20 task pack used for public validator tests.",
            "model_execution_performed": spec.model_execution_performed,
            "pack_id": spec.pack_id,
            "synthetic": spec.synthetic,
            "task_count": len(spec.tasks),
            "visibility": spec.visibility,
        },
    )
    schemas_dir = root / "schemas"
    _write_json(
        schemas_dir / "goldgraph_asset_schema_v0.json",
        {"asset_types": ["evidence_span_seed"], "synthetic": spec.synthetic},
    )
    _write_json(
        schemas_dir / "semantic_object_contract_v0_1.json",
        {
            "object_types": sorted(
                {
                    object_type
                    for task in spec.tasks
                    for object_type in task.expected_semantic_objects
                }
            ),
            "synthetic": spec.synthetic,
        },
    )
    _write_jsonl(
        root / "goldgraph_seed_assets.jsonl",
        [_goldgraph_asset(spec, task) for task in spec.tasks],
    )
    _write_jsonl(
        root / "corrupted_evidence_cases.jsonl",
        [_corruption_case(task) for task in spec.tasks],
    )
    for task in spec.tasks:
        _write_task(root, spec, task)

    inventory = _file_inventory(root)
    file_hashes = {rel_path: sha256_file(root / rel_path) for rel_path in inventory}
    manifest = {
        "schema_version": spec.schema_version,
        "pack_id": spec.pack_id,
        "synthetic": spec.synthetic,
        "visibility": spec.visibility,
        "model_execution_performed": spec.model_execution_performed,
        "asset_counts": {"evidence_span_seed": len(spec.tasks)},
        "expected_rh_axes": sorted(
            {axis for task in spec.tasks for axis in task.expected_rh_axes}
        ),
        "tasks": [_manifest_task_entry(task) for task in spec.tasks],
        "file_inventory": inventory,
        "file_hashes_sha256": file_hashes,
    }
    _write_json(root / "pilot20_manifest_draft.json", manifest)


def _write_task(
    root: Path, spec: ResearchFlowBenchPackSpec, task: ResearchFlowBenchTaskSpec
) -> None:
    task_dir = root / task.directory
    tool_dir = task_dir / "tool_fixtures"
    calibration_dir = task_dir / "calibration_refs"
    task_dir.mkdir(parents=True, exist_ok=True)
    tool_dir.mkdir(parents=True, exist_ok=True)
    calibration_dir.mkdir(parents=True, exist_ok=True)

    (task_dir / "prompt.md").write_text(task.prompt, encoding="utf-8")
    _write_json(task_dir / "task.json", _task_payload(spec, task))
    _write_json(task_dir / "input_bundle.json", _input_bundle(task))
    _write_json(task_dir / "gold_bundle.json", _gold_bundle(task))
    _write_json(task_dir / "judge_bundle.json", _judge_bundle(task))
    _write_json(tool_dir / "allowed_tools_contract.json", _allowed_tools_contract(task))
    _write_jsonl(tool_dir / "local_static_corpus.jsonl", [_local_corpus_record(task)])
    _write_json(
        calibration_dir / "dev_example_ids.json",
        {
            "schema_version": "researchflowbench.dev_example_ids.v0.synthetic",
            "synthetic": task.synthetic,
            "task_id": task.task_id,
            "example_ids": [],
            "corrupted_case_ids": [task.corrupted_case_id],
        },
    )
    visible_files = [
        "prompt.md",
        "input_bundle.json",
        "tool_fixtures/local_static_corpus.jsonl",
    ]
    _write_json(
        tool_dir / "visible_input_manifest.json",
        {
            "schema_version": "researchflowbench.visible_input_manifest.v0.synthetic",
            "synthetic": task.synthetic,
            "task_id": task.task_id,
            "external_search_policy": task.external_search_policy,
            "gold_blind": True,
            "judge_only_hidden": ["gold_bundle.json", "judge_bundle.json"],
            "visible_to_agent": visible_files,
            "file_hashes_sha256": {
                rel_path: sha256_file(task_dir / rel_path) for rel_path in visible_files
            },
        },
    )


def _task_payload(
    spec: ResearchFlowBenchPackSpec, task: ResearchFlowBenchTaskSpec
) -> dict[str, Any]:
    return {
        "schema_version": "researchflowbench.task.v0.synthetic",
        "task_id": task.task_id,
        "pilot_pack_id": spec.pack_id,
        "template_id": task.template_id,
        "stage": task.stage,
        "status": task.status,
        "split": task.split,
        "synthetic": task.synthetic,
        "visibility": task.visibility,
        "source_snapshot_id": task.source_snapshot_id,
        "allowed_tools": list(task.allowed_tools),
        "external_search_policy": task.external_search_policy,
        "gold_asset_ids": [task.gold_asset_id],
        "corrupted_case_ids": [task.corrupted_case_id],
        "expected_semantic_objects": list(task.expected_semantic_objects),
        "expected_rh_axes": list(task.expected_rh_axes),
        "scoring": _scoring(),
    }


def _input_bundle(task: ResearchFlowBenchTaskSpec) -> dict[str, Any]:
    return {
        "schema_version": "researchflowbench.input_bundle.v0.synthetic",
        "synthetic": task.synthetic,
        "task_id": task.task_id,
        "allowed_tools": list(task.allowed_tools),
        "external_search_policy": task.external_search_policy,
        "prompt_context": task.prompt_context,
        "visible_local_corpus_record_ids": [task.gold_asset_id],
        "expected_rh_axes": list(task.expected_rh_axes),
    }


def _gold_bundle(task: ResearchFlowBenchTaskSpec) -> dict[str, Any]:
    return {
        "schema_version": "researchflowbench.gold_bundle.v0.synthetic",
        "synthetic": task.synthetic,
        "task_id": task.task_id,
        "judge_only": True,
        "release_grade": False,
        "human_calibration_required": True,
        "gold_asset_ids": [task.gold_asset_id],
        "corrupted_case_ids": [task.corrupted_case_id],
        "outcome_oracle": task.outcome_oracle,
        "process_oracle": task.process_oracle,
        "leakage_canaries": [task.hidden_canary],
    }


def _judge_bundle(task: ResearchFlowBenchTaskSpec) -> dict[str, Any]:
    return {
        "schema_version": "researchflowbench.judge_bundle.v0.synthetic",
        "synthetic": task.synthetic,
        "task_id": task.task_id,
        "judge_only": True,
        "scoring": _scoring(),
        "expected_rh_axes": list(task.expected_rh_axes),
        "leakage_canaries": [task.judge_canary],
    }


def _allowed_tools_contract(task: ResearchFlowBenchTaskSpec) -> dict[str, Any]:
    return {
        "schema_version": "researchflowbench.allowed_tools_contract.v0.synthetic",
        "synthetic": task.synthetic,
        "task_id": task.task_id,
        "requires_preflight": True,
        "gold_visible": False,
        "judge_visible": False,
        "allowed_tools": [
            {
                "tool_name": tool_name,
                "enabled": True,
                "fixture_path": (
                    "local_static_corpus.jsonl"
                    if tool_name == "local_static_corpus"
                    else ""
                ),
            }
            for tool_name in task.allowed_tools
        ],
        "forbidden_tools": sorted(EXTERNAL_SEARCH_TOOLS),
    }


def _local_corpus_record(task: ResearchFlowBenchTaskSpec) -> dict[str, Any]:
    return {
        "record_id": task.gold_asset_id,
        "semantic_object_type": "evidence_span",
        "content": task.local_corpus_content,
        "source_refs": [f"synthetic-public:{task.task_no}"],
    }


def _goldgraph_asset(
    spec: ResearchFlowBenchPackSpec, task: ResearchFlowBenchTaskSpec
) -> dict[str, Any]:
    return {
        "pack_id": spec.pack_id,
        "schema_version": "researchflowbench.goldgraph_asset.v0.synthetic",
        "asset_id": task.gold_asset_id,
        "asset_type": "evidence_span_seed",
        "maps_to_semantic_object_type": "evidence_span",
        "content": {
            "text": f"Synthetic public-safe evidence asset for {task.task_no}."
        },
        "source_refs": [f"synthetic-public:{task.task_no}"],
        "status": "draft_dev_synthetic",
    }


def _corruption_case(task: ResearchFlowBenchTaskSpec) -> dict[str, Any]:
    return {
        "case_id": task.corrupted_case_id,
        "task": task.task_no,
        "clean_objects": [task.gold_asset_id],
        "corrupted_prompt_object": f"synthetic.corruption.{task.task_no}",
        "expected_states": ["needs_human_review"],
        "expected_edges": ["synthetic_edge"],
        "affected_downstream_objects": list(task.expected_semantic_objects),
        "preserved_objects": [task.gold_asset_id],
        "outcome_oracle": {"expected": "synthetic outcome oracle"},
        "process_oracle": {"expected": "synthetic process oracle"},
        "semantic_trigger_type": "synthetic_public_fixture",
    }


def _manifest_task_entry(task: ResearchFlowBenchTaskSpec) -> dict[str, Any]:
    return {
        "task_no": task.task_no,
        "task_id": task.task_id,
        "directory": task.directory,
        "stage": task.stage,
        "expected_semantic_objects": list(task.expected_semantic_objects),
        "expected_rh_axes": list(task.expected_rh_axes),
        "primary_gold_asset_ids": [task.gold_asset_id],
        "corrupted_case_ids": [task.corrupted_case_id],
    }


def _scoring() -> dict[str, Any]:
    return {
        "outcome": {"rubric": "synthetic outcome axis"},
        "process": {"rubric": "synthetic process axis"},
        "combined": {
            "axis_separation_required": True,
            "rubric": "synthetic combined axis",
        },
    }


def _file_inventory(root: Path) -> list[str]:
    paths = [
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
        and path.name not in {"pilot20_manifest_draft.json", "README.fixture.json"}
    ]
    return sorted(paths)


def _pack_readme(spec: ResearchFlowBenchPackSpec) -> str:
    axes = ", ".join(
        sorted({axis for task in spec.tasks for axis in task.expected_rh_axes})
    )
    return (
        "# ResearchFlowBench Synthetic Pilot-20 v0\n\n"
        "This RH-owned task pack is public-safe synthetic fixture data for "
        "ResearchFlowBench validator, scorer, and archive-ingestion development.\n\n"
        "## Status\n\n"
        "- Split: `draft_dev`\n"
        "- Release readiness: `draft_not_release_grade`\n"
        "- Model execution performed: `false`\n"
        "- Third-party benchmark data vendored: `false`\n"
        "- Gold policy: judge-only synthetic gold in `gold_bundle.json`\n\n"
        "The pack does not make publication-grade benchmark claims. Changing "
        "release labels or public-readiness status requires human approval.\n\n"
        "## Visibility\n\n"
        "Agent-visible inputs are limited to each task's `prompt.md`, "
        "`input_bundle.json`, and `tool_fixtures/local_static_corpus.jsonl`. "
        "`gold_bundle.json` and `judge_bundle.json` are judge-only hidden files. "
        "Leakage canaries are present only in hidden bundles and are audited by "
        "the deterministic validators.\n\n"
        "## Coverage\n\n"
        f"- Task count: `{len(spec.tasks)}` stable T01-T20 task IDs\n"
        f"- Expected RH axes: {axes}\n"
    )


def _strict_failures(result: TaskPackBuildResult) -> list[str]:
    failures = [
        issue.code
        for issue in result.validation_report.issues
        if issue.severity == "error"
    ]
    for report in result.preflight_reports:
        failures.extend(str(item) for item in report.get("failures", []) or [])
    for report in result.leakage_reports:
        failures.extend(str(item) for item in report.get("failures", []) or [])
    return failures


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n"
            for record in records
        ),
        encoding="utf-8",
    )
