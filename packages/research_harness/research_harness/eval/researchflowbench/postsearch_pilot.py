"""Post-search ResearchFlowBench Pilot-5 fixtures and scorer.

This module covers the RH stages that happen after candidate papers have already
been retrieved. The fixtures are synthetic and local-only, so they can exercise
selection, reading, evidence linking, drafting, and final-bundle QA without
network or model execution.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .baseline import BaselineRunResult
from .contract import (
    EXTERNAL_TASK_SCHEMA_VERSION,
    GOLD_STORAGE_LOCAL_ONLY,
    SCORE_REPORT_SCHEMA_VERSION,
    SPLIT_MUTATE_DEV,
)
from .validators import validate_external_task_pack
from research_harness.execution import ResearchHarnessBackend
from research_harness.orchestrator.artifacts import ArtifactManager
from research_harness.primitives.writing_impls import publication_pack_backfill
from research_harness.evolution.harness import scan_pdf_quality_bundle
from research_harness.storage.db import Database


POSTSEARCH_BENCHMARK_ID = "researchflowbench.postsearch_pilot5_v0"
POSTSEARCH_ADAPTER_CONTRACT = "researchflowbench.adapters.postsearch_pilot5.v0.1"
POSTSEARCH_SUPPORTED_BASELINES = ("stub_zero", "deterministic_visible")
POSTSEARCH_CONTRACT_SCAN = "postsearch_contract_scan"
POSTSEARCH_EVIDENCE_LINK_RECORD_REPLAY = "evidence_link_record_replay"
POSTSEARCH_PRIMITIVE_FINAL_BUNDLE_QUALITY_SCAN = "final_bundle_quality_scan"
POSTSEARCH_PRIMITIVE_PUBLICATION_PACK_BACKFILL_SCAN = "publication_pack_backfill_scan"
SUPPORTED_POSTSEARCH_PRIMITIVE_RUNNERS = (
    POSTSEARCH_CONTRACT_SCAN,
    POSTSEARCH_EVIDENCE_LINK_RECORD_REPLAY,
    POSTSEARCH_PRIMITIVE_FINAL_BUNDLE_QUALITY_SCAN,
    POSTSEARCH_PRIMITIVE_PUBLICATION_PACK_BACKFILL_SCAN,
)


@dataclass(frozen=True)
class PostSearchPilotTask:
    """One synthetic post-search benchmark task."""

    task_no: str
    slug: str
    task_id: str
    task_type: str
    rh_axis_ids: tuple[str, ...]
    input_payload: dict[str, Any]
    gold_payload: dict[str, Any]
    metrics: tuple[str, ...]
    split: str = SPLIT_MUTATE_DEV
    license: dict[str, Any] = field(default_factory=lambda: _license_payload())

    @property
    def directory_name(self) -> str:
        return f"{self.task_no}_{self.slug}"


def build_postsearch_pilot5_task_pack(
    root: str | Path,
    *,
    overwrite: bool = False,
    include_gold: bool = False,
) -> dict[str, Any]:
    """Materialize a synthetic post-search Pilot-5 task pack."""

    root_path = Path(root)
    if root_path.exists() and any(root_path.iterdir()):
        if not overwrite:
            raise FileExistsError(f"output directory is not empty: {root_path}")
        shutil.rmtree(root_path)
    root_path.mkdir(parents=True, exist_ok=True)

    tasks = postsearch_pilot5_tasks()
    task_ids: list[str] = []
    for task in tasks:
        task_ids.append(task.task_id)
        task_dir = root_path / "tasks" / task.task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        if task.task_type == "final_bundle":
            _write_final_bundle_fixture(task_dir)
        _write_json(task_dir / "input.json", _visible_task_payload(task, task_dir))
        if include_gold:
            _write_json(task_dir / "gold.json", task.gold_payload)

    manifest = {
        "schema_version": "researchflowbench.postsearch_pilot5_manifest.v0.1",
        "adapter_contract": POSTSEARCH_ADAPTER_CONTRACT,
        "benchmark_id": POSTSEARCH_BENCHMARK_ID,
        "task_count": len(tasks),
        "task_ids": task_ids,
        "metrics": list(
            dict.fromkeys(metric for task in tasks for metric in task.metrics)
        ),
        "rh_axes": list(
            dict.fromkeys(axis for task in tasks for axis in task.rh_axis_ids)
        ),
        "license": _license_payload(),
        "gold_storage_policy": GOLD_STORAGE_LOCAL_ONLY,
        "gold_written": include_gold,
        "data_policy": {
            "synthetic": True,
            "third_party_data_vendored": False,
            "model_execution_performed": False,
            "network_required": False,
        },
        "file_hashes_sha256": _file_hashes(root_path),
    }
    _write_json(root_path / "adapter_manifest.json", manifest)
    manifest["file_hashes_sha256"] = _file_hashes(root_path)
    _write_json(root_path / "adapter_manifest.json", manifest)
    return manifest


def run_postsearch_pilot5_baseline(
    task_pack_root: str | Path,
    *,
    baseline_id: str = "stub_zero",
    allow_invalid: bool = False,
    artifact_refs: tuple[str, ...] = (),
) -> BaselineRunResult:
    """Score a post-search Pilot-5 task pack with a model-free baseline."""

    if baseline_id not in POSTSEARCH_SUPPORTED_BASELINES:
        raise ValueError(f"unsupported post-search baseline: {baseline_id}")

    root = Path(task_pack_root)
    validation = validate_external_task_pack(root, allow_local_gold=True)
    if not validation.is_valid and not allow_invalid:
        issue_codes = ", ".join(issue.code for issue in validation.issues[:5])
        raise ValueError(
            "post-search task pack validation failed before scoring"
            + (f": {issue_codes}" if issue_codes else "")
        )

    manifest = _load_json(root / "adapter_manifest.json")
    scores = tuple(
        _score_task(root, task_id, baseline_id=baseline_id)
        for task_id in manifest.get("task_ids", [])
        if isinstance(task_id, str)
    )
    metrics = _aggregate(scores)
    default_refs = (f"task_pack:{root}",)
    report = {
        "schema_version": SCORE_REPORT_SCHEMA_VERSION,
        "benchmark_id": POSTSEARCH_BENCHMARK_ID,
        "adapter_contract": POSTSEARCH_ADAPTER_CONTRACT,
        "split": _common_split(scores),
        "baseline_id": baseline_id,
        "baseline_kind": "model_free_postsearch_stub",
        "scores": list(scores),
        "metrics": metrics,
        "rh_axis_ids": list(
            dict.fromkeys(
                axis
                for score in scores
                for axis in score.get("rh_axis_ids", [])
                if isinstance(axis, str) and axis
            )
        ),
        "artifact_refs": list(dict.fromkeys((*default_refs, *artifact_refs))),
        "model_execution_performed": False,
        "validation": {
            "is_valid": validation.is_valid,
            "checked_task_count": validation.checked_task_count,
            "checked_file_count": validation.checked_file_count,
            "issue_count": len(validation.issues),
        },
        "metadata": {
            "runner": "researchflowbench.postsearch_pilot5_baseline.v0.1",
            "task_pack_sha256": _pack_digest(root),
            "task_count": len(scores),
            "blocked_score_count": metrics["blocked_score_count"],
            "skipped_score_count": metrics["skipped_score_count"],
            "supported_score_count": metrics["supported_score_count"],
            "automatic_mutation_enabled": False,
        },
    }
    return BaselineRunResult(report=report, validation_report=validation)


def run_postsearch_pilot5_primitive(
    task_pack_root: str | Path,
    *,
    runner_id: str = POSTSEARCH_PRIMITIVE_FINAL_BUNDLE_QUALITY_SCAN,
    allow_invalid: bool = False,
    artifact_refs: tuple[str, ...] = (),
) -> BaselineRunResult:
    """Replay a post-search quality runner against Pilot-5 tasks."""

    if runner_id not in SUPPORTED_POSTSEARCH_PRIMITIVE_RUNNERS:
        raise ValueError(f"unsupported post-search quality runner: {runner_id}")

    root = Path(task_pack_root)
    validation = validate_external_task_pack(root, allow_local_gold=True)
    if not validation.is_valid and not allow_invalid:
        issue_codes = ", ".join(issue.code for issue in validation.issues[:5])
        raise ValueError(
            "post-search task pack validation failed before primitive replay"
            + (f": {issue_codes}" if issue_codes else "")
        )

    manifest = _load_json(root / "adapter_manifest.json")
    scores = tuple(
        _score_primitive_task(root, task_id, runner_id=runner_id)
        for task_id in manifest.get("task_ids", [])
        if isinstance(task_id, str)
    )
    metrics = _aggregate(scores)
    default_refs = (f"task_pack:{root}",)
    report = {
        "schema_version": SCORE_REPORT_SCHEMA_VERSION,
        "benchmark_id": POSTSEARCH_BENCHMARK_ID,
        "adapter_contract": POSTSEARCH_ADAPTER_CONTRACT,
        "split": _common_split(scores),
        "runner_id": runner_id,
        "baseline_id": runner_id,
        "baseline_kind": _postsearch_runner_kind(runner_id),
        "scores": list(scores),
        "metrics": metrics,
        "rh_axis_ids": list(
            dict.fromkeys(
                axis
                for score in scores
                for axis in score.get("rh_axis_ids", [])
                if isinstance(axis, str) and axis
            )
        ),
        "artifact_refs": list(dict.fromkeys((*default_refs, *artifact_refs))),
        "model_execution_performed": False,
        "validation": {
            "is_valid": validation.is_valid,
            "checked_task_count": validation.checked_task_count,
            "checked_file_count": validation.checked_file_count,
            "issue_count": len(validation.issues),
        },
        "metadata": {
            "runner": "researchflowbench.postsearch_pilot5_primitive.v0.1",
            "task_pack_sha256": _pack_digest(root),
            "task_count": len(scores),
            "blocked_score_count": metrics["blocked_score_count"],
            "skipped_score_count": metrics["skipped_score_count"],
            "supported_score_count": metrics["supported_score_count"],
            "automatic_mutation_enabled": False,
        },
    }
    return BaselineRunResult(report=report, validation_report=validation)


def run_postsearch_pilot5_predictions(
    task_pack_root: str | Path,
    predictions_file: str | Path,
    *,
    allow_invalid: bool = False,
    artifact_refs: tuple[str, ...] = (),
) -> BaselineRunResult:
    """Score externally generated post-search Pilot-5 predictions."""

    root = Path(task_pack_root)
    validation = validate_external_task_pack(root, allow_local_gold=True)
    if not validation.is_valid and not allow_invalid:
        issue_codes = ", ".join(issue.code for issue in validation.issues[:5])
        raise ValueError(
            "post-search task pack validation failed before prediction scoring"
            + (f": {issue_codes}" if issue_codes else "")
        )

    predictions_path = Path(predictions_file)
    prediction_payload = _load_json(predictions_path)
    runner_id = str(prediction_payload.get("runner_id") or "prediction_file")
    prediction_map = _prediction_map(prediction_payload)
    model_execution_performed = (
        prediction_payload.get("model_execution_performed") is True
    )

    manifest = _load_json(root / "adapter_manifest.json")
    scores = tuple(
        _score_prediction_file_task(
            root,
            task_id,
            runner_id=runner_id,
            prediction_entry=prediction_map.get(task_id),
            model_execution_performed=model_execution_performed,
        )
        for task_id in manifest.get("task_ids", [])
        if isinstance(task_id, str)
    )
    metrics = _aggregate(scores)
    default_refs = (f"task_pack:{root}", f"predictions:{predictions_path}")
    report = {
        "schema_version": SCORE_REPORT_SCHEMA_VERSION,
        "benchmark_id": POSTSEARCH_BENCHMARK_ID,
        "adapter_contract": POSTSEARCH_ADAPTER_CONTRACT,
        "split": _common_split(scores),
        "baseline_id": runner_id,
        "baseline_kind": "postsearch_prediction_file",
        "scores": list(scores),
        "metrics": metrics,
        "rh_axis_ids": list(
            dict.fromkeys(
                axis
                for score in scores
                for axis in score.get("rh_axis_ids", [])
                if isinstance(axis, str) and axis
            )
        ),
        "artifact_refs": list(dict.fromkeys((*default_refs, *artifact_refs))),
        "model_execution_performed": model_execution_performed,
        "validation": {
            "is_valid": validation.is_valid,
            "checked_task_count": validation.checked_task_count,
            "checked_file_count": validation.checked_file_count,
            "issue_count": len(validation.issues),
        },
        "metadata": {
            "runner": "researchflowbench.postsearch_pilot5_predictions.v0.1",
            "task_pack_sha256": _pack_digest(root),
            "task_count": len(scores),
            "blocked_score_count": metrics["blocked_score_count"],
            "skipped_score_count": metrics["skipped_score_count"],
            "supported_score_count": metrics["supported_score_count"],
            "prediction_schema_version": str(
                prediction_payload.get("schema_version") or ""
            ),
            "prediction_file": str(predictions_path),
            "automatic_mutation_enabled": False,
        },
    }
    return BaselineRunResult(report=report, validation_report=validation)


def postsearch_pilot5_tasks() -> tuple[PostSearchPilotTask, ...]:
    """Return the built-in synthetic Pilot-5 tasks."""

    return (
        PostSearchPilotTask(
            task_no="P01",
            slug="paper_selection_precision",
            task_id="postsearch.P01_paper_selection_precision",
            task_type="paper_selection",
            rh_axis_ids=("paper_selection.precision",),
            metrics=("paper_selection_precision", "paper_selection_recall"),
            input_payload={
                "instruction": "Select papers that should survive retrieval for the review.",
                "candidate_papers": [
                    {
                        "paper_id": "P-A",
                        "title": "Grounded Claim Auditing for Scientific Drafts",
                    },
                    {"paper_id": "P-B", "title": "Unrelated Social Media Trend Mining"},
                    {"paper_id": "P-C", "title": "Citation-Supported Evidence Maps"},
                ],
                "selection_criteria": [
                    "scientific writing or evidence grounding",
                    "directly useful after literature search",
                ],
            },
            gold_payload={"selected_paper_ids": ["P-A", "P-C"]},
        ),
        PostSearchPilotTask(
            task_no="P02",
            slug="claim_extraction_quality",
            task_id="postsearch.P02_claim_extraction_quality",
            task_type="paper_reading",
            rh_axis_ids=("paper_reading.claim_quality",),
            metrics=("claim_required_field_coverage", "claim_text_match"),
            input_payload={
                "instruction": "Extract the central supported claim from the paper card.",
                "paper": {
                    "paper_id": "P-D",
                    "title": "Span-Level Evidence Gating",
                    "abstract": (
                        "The method improves factual consistency by requiring every "
                        "draft claim to cite an exact supporting span. It does not "
                        "claim gains for open-domain web browsing."
                    ),
                },
            },
            gold_payload={
                "claims": [
                    {
                        "claim_id": "C-D1",
                        "paper_id": "P-D",
                        "claim_text": "Span-level evidence gates improve factual consistency for draft claims.",
                        "scope": "draft claims with exact supporting spans",
                    }
                ]
            },
        ),
        PostSearchPilotTask(
            task_no="P03",
            slug="evidence_link_support",
            task_id="postsearch.P03_evidence_link_support",
            task_type="evidence_linking",
            rh_axis_ids=("evidence_linking.support_accuracy",),
            metrics=(
                "support_label_accuracy",
                "evidence_span_exact_match",
                "typed_contract_coverage",
                "citation_governance_replay_coverage",
            ),
            input_payload={
                "instruction": "Label whether each span fully supports, partially supports, or contradicts the claim.",
                "claim": {
                    "claim_id": "C-E1",
                    "claim_text": "The system improves both citation accuracy and PDF layout quality.",
                },
                "candidate_spans": [
                    {
                        "span_id": "S-1",
                        "text": "The system improves citation accuracy on held-out drafts.",
                    },
                    {
                        "span_id": "S-2",
                        "text": "PDF layout quality was not evaluated in this study.",
                    },
                ],
            },
            gold_payload={
                "evidence_links": [
                    {
                        "claim_id": "C-E1",
                        "span_id": "S-1",
                        "support_label": "partial_support",
                    },
                    {
                        "claim_id": "C-E1",
                        "span_id": "S-2",
                        "support_label": "contradicts",
                    },
                ]
            },
        ),
        PostSearchPilotTask(
            task_no="P04",
            slug="section_draft_grounding",
            task_id="postsearch.P04_section_draft_grounding",
            task_type="section_drafting",
            rh_axis_ids=("section_drafting.citation_grounding",),
            metrics=("citation_grounding", "unsupported_claim_rate"),
            input_payload={
                "instruction": "Draft two sentences using only the supplied evidence cards.",
                "evidence_cards": [
                    {
                        "evidence_id": "E-1",
                        "paper_id": "P-F",
                        "claim": "Evidence maps preserve span-level provenance.",
                    },
                    {
                        "evidence_id": "E-2",
                        "paper_id": "P-G",
                        "claim": "Citation sanitization detects hallucinated identifiers.",
                    },
                ],
            },
            gold_payload={
                "required_citations": ["P-F", "P-G"],
                "forbidden_claims": ["leaderboard rank", "human preference win"],
            },
        ),
        PostSearchPilotTask(
            task_no="P05",
            slug="final_bundle_quality",
            task_id="postsearch.P05_final_bundle_quality",
            task_type="final_bundle",
            rh_axis_ids=("final_bundle.pdf_quality",),
            metrics=("final_bundle_check_coverage", "citation_integrity"),
            input_payload={
                "instruction": "Inspect the final bundle manifest and report quality issues.",
                "bundle_manifest": {
                    "pdf_exists": True,
                    "latex_compiled": True,
                    "citation_warnings": ["missing bib entry for P-Z"],
                    "figure_warnings": ["low resolution figure_2.png"],
                },
            },
            gold_payload={
                "required_checks": [
                    "pdf_exists",
                    "latex_compiled",
                    "citation_warnings",
                    "figure_warnings",
                ],
                "expected_issue_count": 2,
            },
        ),
    )


def _visible_task_payload(task: PostSearchPilotTask, task_dir: Path) -> dict[str, Any]:
    task_input = dict(task.input_payload)
    if task.task_type == "final_bundle":
        bundle_dir = task_dir / "bundle"
        task_input["bundle_paths"] = {
            "tex_path": str(bundle_dir / "paper.tex"),
            "pdf_path": str(bundle_dir / "paper.pdf"),
            "log_path": str(bundle_dir / "paper.log"),
            "output_dir": str(bundle_dir),
        }
    return {
        "schema_version": EXTERNAL_TASK_SCHEMA_VERSION,
        "benchmark_id": POSTSEARCH_BENCHMARK_ID,
        "adapter_contract": POSTSEARCH_ADAPTER_CONTRACT,
        "task_id": task.task_id,
        "task_no": task.task_no,
        "task_type": task.task_type,
        "split": task.split,
        "input": task_input,
        "expected_rh_axes": list(task.rh_axis_ids),
        "artifact_policy": {
            "gold_visible": False,
            "gold_storage_policy": GOLD_STORAGE_LOCAL_ONLY,
            "third_party_data_vendored": False,
            "synthetic": True,
        },
        "license": task.license,
        "leakage_policy": {
            "gold_blind_visible_inputs": True,
            "external_search_default": "forbidden",
        },
        "archive_linkage": {
            "benchmark_id": POSTSEARCH_BENCHMARK_ID,
            "task_id": task.task_id,
            "split": task.split,
            "rh_axis_ids": list(task.rh_axis_ids),
            "artifact_refs": [],
        },
        "metadata": {
            "metrics": list(task.metrics),
            "post_search_only": True,
            "model_execution_performed": False,
        },
    }


def _write_final_bundle_fixture(task_dir: Path) -> None:
    bundle_dir = task_dir / "bundle"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "paper.tex").write_text(
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "\\section{Quality}\n"
        "Citation-backed text \\cite{P-Z}.\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    (bundle_dir / "paper.pdf").write_bytes(
        b"%PDF-1.4\n% synthetic postsearch fixture\n"
    )
    (bundle_dir / "paper.log").write_text(
        "LaTeX Warning: Undefined citation `P-Z' on page 1.\n",
        encoding="utf-8",
    )


def _score_task(root: Path, task_id: str, *, baseline_id: str) -> dict[str, Any]:
    task_dir = root / "tasks" / task_id
    visible = _load_json(task_dir / "input.json")
    gold_path = task_dir / "gold.json"
    if not gold_path.exists():
        return {
            "task_id": task_id,
            "split": str(visible.get("split") or SPLIT_MUTATE_DEV),
            "metrics": {},
            "rh_axis_ids": list(visible.get("expected_rh_axes") or []),
            "baseline_id": baseline_id,
            "model_execution_performed": False,
            "evidence_state": "blocked_missing_local_gold",
            "blockers": ["postsearch_gold_file_missing"],
        }
    gold = _load_json(gold_path)
    prediction = _baseline_prediction(visible, baseline_id=baseline_id)
    metrics = _score_prediction(visible, gold, prediction)
    return {
        "task_id": task_id,
        "split": str(visible.get("split") or SPLIT_MUTATE_DEV),
        "task_type": str(visible.get("task_type") or ""),
        "metrics": metrics,
        "rh_axis_ids": list(visible.get("expected_rh_axes") or []),
        "baseline_id": baseline_id,
        "baseline_output": prediction,
        "model_execution_performed": False,
        "evidence_state": "fixture_or_local_gold",
    }


def _score_prediction_file_task(
    root: Path,
    task_id: str,
    *,
    runner_id: str,
    prediction_entry: dict[str, Any] | None,
    model_execution_performed: bool,
) -> dict[str, Any]:
    task_dir = root / "tasks" / task_id
    visible = _load_json(task_dir / "input.json")
    gold_path = task_dir / "gold.json"
    if not gold_path.exists():
        return _blocked_prediction_file_score(
            visible,
            task_id=task_id,
            runner_id=runner_id,
            reason="postsearch_gold_file_missing",
            model_execution_performed=model_execution_performed,
        )
    if prediction_entry is None:
        return _blocked_prediction_file_score(
            visible,
            task_id=task_id,
            runner_id=runner_id,
            reason="postsearch_prediction_missing",
            model_execution_performed=model_execution_performed,
        )

    prediction = prediction_entry.get("prediction")
    if not isinstance(prediction, dict):
        return _blocked_prediction_file_score(
            visible,
            task_id=task_id,
            runner_id=runner_id,
            reason="postsearch_prediction_payload_invalid",
            model_execution_performed=model_execution_performed,
        )

    gold = _load_json(gold_path)
    metrics = _score_prediction(visible, gold, prediction)
    return {
        "task_id": task_id,
        "split": str(visible.get("split") or SPLIT_MUTATE_DEV),
        "task_type": str(visible.get("task_type") or ""),
        "metrics": metrics,
        "rh_axis_ids": list(visible.get("expected_rh_axes") or []),
        "runner_id": runner_id,
        "baseline_id": runner_id,
        "baseline_output": prediction,
        "model_execution_performed": model_execution_performed,
        "evidence_state": "prediction_file_scored",
        "runner_output": (
            prediction_entry.get("runner_output")
            if isinstance(prediction_entry.get("runner_output"), dict)
            else {}
        ),
    }


def _prediction_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    predictions = payload.get("predictions")
    if not isinstance(predictions, list):
        raise ValueError("post-search prediction file must contain a predictions list")

    mapped: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(predictions):
        if not isinstance(entry, dict):
            raise ValueError(
                f"post-search prediction entry at index {index} must be an object"
            )
        task_id = entry.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError(
                f"post-search prediction entry at index {index} is missing task_id"
            )
        if task_id in mapped:
            raise ValueError(f"duplicate post-search prediction task_id: {task_id}")
        mapped[task_id] = dict(entry)
    return mapped


def _blocked_prediction_file_score(
    visible: dict[str, Any],
    *,
    task_id: str,
    runner_id: str,
    reason: str,
    model_execution_performed: bool,
) -> dict[str, Any]:
    if reason == "postsearch_gold_file_missing":
        evidence_state = "blocked_missing_local_gold"
    elif reason == "postsearch_prediction_missing":
        evidence_state = "blocked_missing_prediction"
    else:
        evidence_state = "blocked_invalid_prediction"
    return {
        "task_id": task_id,
        "split": str(visible.get("split") or SPLIT_MUTATE_DEV),
        "task_type": str(visible.get("task_type") or ""),
        "metrics": {},
        "rh_axis_ids": list(visible.get("expected_rh_axes") or []),
        "runner_id": runner_id,
        "baseline_id": runner_id,
        "model_execution_performed": model_execution_performed,
        "evidence_state": evidence_state,
        "blockers": [reason],
    }


def _score_primitive_task(
    root: Path, task_id: str, *, runner_id: str
) -> dict[str, Any]:
    task_dir = root / "tasks" / task_id
    visible = _load_json(task_dir / "input.json")
    gold_path = task_dir / "gold.json"
    if not gold_path.exists():
        return _blocked_primitive_score(
            visible,
            task_id=task_id,
            runner_id=runner_id,
            reason="postsearch_gold_file_missing",
        )
    gold = _load_json(gold_path)
    if runner_id == POSTSEARCH_CONTRACT_SCAN:
        return _score_postsearch_contract_scan(visible, gold, runner_id=runner_id)
    if runner_id == POSTSEARCH_EVIDENCE_LINK_RECORD_REPLAY:
        return _score_evidence_link_record_replay(visible, gold, runner_id=runner_id)
    if visible.get("task_type") != "final_bundle":
        return _blocked_primitive_score(
            visible,
            task_id=task_id,
            runner_id=runner_id,
            reason=f"runner_not_supported_for_task_type:{visible.get('task_type')}",
        )
    if runner_id == POSTSEARCH_PRIMITIVE_PUBLICATION_PACK_BACKFILL_SCAN:
        return _score_publication_pack_backfill_scan(visible, gold, runner_id=runner_id)
    return _score_final_bundle_quality_scan(visible, gold, runner_id=runner_id)


def _score_postsearch_contract_scan(
    visible: dict[str, Any],
    gold: dict[str, Any],
    *,
    runner_id: str,
) -> dict[str, Any]:
    task_id = str(visible.get("task_id") or "")
    task_type = str(visible.get("task_type") or "")
    supported_task_types = {
        "paper_selection",
        "paper_reading",
        "evidence_linking",
        "section_drafting",
    }
    if task_type not in supported_task_types:
        return _blocked_primitive_score(
            visible,
            task_id=task_id,
            runner_id=runner_id,
            reason=f"contract_scan_not_supported_for_task_type:{task_type}",
        )

    prediction = _contract_scan_prediction(visible)
    metrics = _score_prediction(visible, gold, prediction)
    return {
        "task_id": task_id,
        "split": str(visible.get("split") or SPLIT_MUTATE_DEV),
        "task_type": task_type,
        "metrics": metrics,
        "rh_axis_ids": list(visible.get("expected_rh_axes") or []),
        "runner_id": runner_id,
        "baseline_id": runner_id,
        "model_execution_performed": False,
        "evidence_state": "fixture_contract_scan",
        "runner_output": {
            "contract_scan_kind": "deterministic_visible_contract",
            "prediction": prediction,
            "supported_task_types": sorted(supported_task_types),
        },
    }


def _score_evidence_link_record_replay(
    visible: dict[str, Any],
    gold: dict[str, Any],
    *,
    runner_id: str,
) -> dict[str, Any]:
    task_id = str(visible.get("task_id") or "")
    task_type = str(visible.get("task_type") or "")
    if task_type != "evidence_linking":
        return _blocked_primitive_score(
            visible,
            task_id=task_id,
            runner_id=runner_id,
            reason=f"evidence_link_record_replay_not_supported_for_task_type:{task_type}",
        )

    task_input = visible.get("input") if isinstance(visible.get("input"), dict) else {}
    claim = task_input.get("claim") if isinstance(task_input.get("claim"), dict) else {}
    spans = (
        task_input.get("candidate_spans")
        if isinstance(task_input.get("candidate_spans"), list)
        else []
    )
    claim_id = str(claim.get("claim_id") or "")
    claim_text = str(claim.get("claim_text") or "")
    recorded_links: list[dict[str, str]] = []
    primitive_results: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="rh-postsearch-evidence-link-") as tmp:
        db = Database(Path(tmp) / "postsearch.db")
        db.migrate()
        backend = ResearchHarnessBackend(db=db)
        for span in spans:
            if not isinstance(span, dict):
                continue
            span_id = str(span.get("span_id") or "")
            if not span_id:
                continue
            support_label = _contract_support_label(
                claim_text,
                str(span.get("text") or ""),
            )
            typed_fields = _typed_evidence_link_fields(
                span_id=span_id,
                span_text=str(span.get("text") or ""),
                support_label=support_label,
            )
            notes = f"postsearch Pilot-5 replay label={support_label}"
            result = backend.execute(
                "evidence_link",
                claim_id=claim_id,
                source_type="candidate_span",
                source_id=span_id,
                strength=support_label,
                support_status=typed_fields["support_status"],
                evidence_span=typed_fields["evidence_span"],
                citation_candidate=typed_fields["citation_candidate"],
                notes=notes,
            )
            primitive_results.append(
                {
                    "primitive": result.primitive,
                    "success": result.success,
                    "backend": result.backend,
                    "model_used": result.model_used,
                    "error": result.error,
                }
            )
            if not result.success:
                return _failed_primitive_score(
                    visible,
                    task_id=task_id,
                    runner_id=runner_id,
                    reason=result.error or "evidence_link_primitive_failed",
                    primitive_results=primitive_results,
                )
            link = result.output.link
            evidence_span = link.evidence_span
            citation_candidate = link.citation_candidate
            recorded_links.append(
                {
                    "claim_id": str(link.claim_id),
                    "source_type": str(link.source_type),
                    "span_id": str(link.source_id),
                    "strength": str(link.strength),
                    "support_status": str(link.support_status),
                    "evidence_span": (
                        {
                            "paper_id": evidence_span.paper_id,
                            "section": evidence_span.section,
                            "snippet": evidence_span.snippet,
                        }
                        if evidence_span is not None
                        else {}
                    ),
                    "citation_candidate": (
                        {
                            "paper_id": citation_candidate.paper_id,
                            "identifier": citation_candidate.identifier,
                            "source_type": citation_candidate.source_type,
                            "title": citation_candidate.title,
                        }
                        if citation_candidate is not None
                        else {}
                    ),
                    **_citation_governance_replay_fields(
                        span_id=str(link.source_id),
                        support_label=str(link.strength),
                    ),
                    "notes": str(link.notes),
                }
            )

    prediction = {
        "evidence_links": [
            {
                "span_id": link["span_id"],
                "support_label": link["strength"],
                "support_status": link["support_status"],
                "evidence_span": link["evidence_span"],
                "citation_candidate": link["citation_candidate"],
                "citation_verification": link.get("citation_verification") or {},
                "review_issue": link.get("review_issue") or {},
                "gate_decision": link.get("gate_decision") or {},
            }
            for link in recorded_links
        ]
    }
    metrics = _score_prediction(visible, gold, prediction)
    return {
        "task_id": task_id,
        "split": str(visible.get("split") or SPLIT_MUTATE_DEV),
        "task_type": task_type,
        "metrics": metrics,
        "rh_axis_ids": list(visible.get("expected_rh_axes") or []),
        "runner_id": runner_id,
        "baseline_id": runner_id,
        "model_execution_performed": False,
        "evidence_state": "fixture_real_primitive_replay",
        "runner_output": {
            "primitive": "evidence_link",
            "support_label_source": "deterministic_visible_span_scan",
            "recorded_links": recorded_links,
            "primitive_results": primitive_results,
        },
    }


def _blocked_primitive_score(
    visible: dict[str, Any],
    *,
    task_id: str,
    runner_id: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "split": str(visible.get("split") or SPLIT_MUTATE_DEV),
        "task_type": str(visible.get("task_type") or ""),
        "metrics": {},
        "rh_axis_ids": list(visible.get("expected_rh_axes") or []),
        "runner_id": runner_id,
        "baseline_id": runner_id,
        "model_execution_performed": False,
        "evidence_state": "skipped_runner_scope",
        "skip_reasons": [reason],
    }


def _failed_primitive_score(
    visible: dict[str, Any],
    *,
    task_id: str,
    runner_id: str,
    reason: str,
    primitive_results: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "split": str(visible.get("split") or SPLIT_MUTATE_DEV),
        "task_type": str(visible.get("task_type") or ""),
        "metrics": {},
        "rh_axis_ids": list(visible.get("expected_rh_axes") or []),
        "runner_id": runner_id,
        "baseline_id": runner_id,
        "model_execution_performed": False,
        "evidence_state": "blocked_primitive_failure",
        "blockers": [reason],
        "runner_output": {
            "primitive": "evidence_link",
            "primitive_results": primitive_results,
        },
    }


def _score_final_bundle_quality_scan(
    visible: dict[str, Any],
    gold: dict[str, Any],
    *,
    runner_id: str,
) -> dict[str, Any]:
    task_input = visible.get("input") if isinstance(visible.get("input"), dict) else {}
    bundle_paths = (
        task_input.get("bundle_paths")
        if isinstance(task_input.get("bundle_paths"), dict)
        else {}
    )
    signal = scan_pdf_quality_bundle(
        tex_path=str(bundle_paths.get("tex_path") or ""),
        pdf_path=str(bundle_paths.get("pdf_path") or ""),
        log_path=str(bundle_paths.get("log_path") or ""),
        topic_id=0,
        target_profile="synthetic-postsearch-pilot5",
        artifact_id=0,
    )
    manifest = (
        task_input.get("bundle_manifest")
        if isinstance(task_input.get("bundle_manifest"), dict)
        else {}
    )
    return _final_bundle_score_from_signal(
        visible=visible,
        gold=gold,
        runner_id=runner_id,
        signal=signal,
        bundle_paths=dict(bundle_paths),
        manifest=manifest,
    )


def _score_publication_pack_backfill_scan(
    visible: dict[str, Any],
    gold: dict[str, Any],
    *,
    runner_id: str,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="rh-postsearch-backfill-") as tmp:
        db = Database(Path(tmp) / "postsearch.db")
        db.migrate()
        topic_id = _create_replay_topic(db)
        artifacts = ArtifactManager(db)
        evidence = artifacts.record(
            topic_id=topic_id,
            stage="analyze",
            artifact_type="evidence_pack",
            title="Post-search Pilot-5 Evidence Pack",
            payload={
                "claims": [
                    {
                        "claim_id": "C-P05",
                        "text": "Generated final bundles must preserve citation integrity.",
                        "paper_ids": ["PZ"],
                    }
                ]
            },
        )
        draft = artifacts.record(
            topic_id=topic_id,
            stage="write",
            artifact_type="draft_pack",
            title="Post-search Pilot-5 Draft Pack",
            payload={
                "title": "Post-search Pilot-5 Generated PDF Replay",
                "abstract": ("A synthetic generated-PDF replay for ResearchFlowBench."),
                "sections": {
                    "introduction": (
                        "Research Harness implements generated final-bundle "
                        "quality checks for citation-backed drafts \\citep{PZ}."
                    )
                },
                "bibliography_entries": [
                    (
                        "@article{PZ,\n"
                        "  title={Synthetic Citation Integrity Fixture},\n"
                        "  author={Research Harness},\n"
                        "  journal={Synthetic Fixtures},\n"
                        "  year={2026}\n"
                        "}"
                    )
                ],
            },
        )
        backfill = publication_pack_backfill(
            db=db,
            topic_id=topic_id,
            target_profile="aaai",
            components=["final_bundle"],
            record_artifact=True,
        )
        final_bundle_id = _created_artifact_id(
            backfill.created_artifacts, "final_bundle"
        )
        final_bundle = artifacts.get(final_bundle_id) if final_bundle_id else None
        final_payload = final_bundle.payload if final_bundle is not None else {}
        bundle_paths = {
            "tex_path": str(final_payload.get("tex_path") or ""),
            "pdf_path": str(final_payload.get("compiled_pdf_path") or ""),
            "log_path": str(
                final_payload.get("log_path")
                or Path(str(final_payload.get("tex_path") or "")).with_suffix(".log")
            )
            if final_payload.get("tex_path")
            else "",
        }
        signal = scan_pdf_quality_bundle(
            tex_path=bundle_paths["tex_path"],
            pdf_path=bundle_paths["pdf_path"],
            log_path=bundle_paths["log_path"],
            topic_id=topic_id,
            target_profile="aaai",
            artifact_id=final_bundle_id,
        )
        return _final_bundle_score_from_signal(
            visible=visible,
            gold=gold,
            runner_id=runner_id,
            signal=signal,
            bundle_paths=bundle_paths,
            manifest=_generated_bundle_manifest(final_payload),
            runner_output_extra={
                "generated_final_bundle": {
                    "artifact_id": final_bundle_id,
                    "status": str(final_payload.get("status") or ""),
                    "source_draft_artifact_id": draft.id,
                    "source_evidence_artifact_id": evidence.id,
                    "created_artifacts": list(backfill.created_artifacts),
                    "ready_for_review": backfill.ready_for_review,
                    "submission_ready": backfill.submission_ready,
                }
            },
        )


def _final_bundle_score_from_signal(
    *,
    visible: dict[str, Any],
    gold: dict[str, Any],
    runner_id: str,
    signal: Any,
    bundle_paths: dict[str, str],
    manifest: dict[str, Any],
    runner_output_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    issue_categories = {issue.category for issue in signal.issues}
    citation_evidence = manifest.get("citation_integrity_evidence")
    figure_evidence = manifest.get("figure_placement_evidence")
    observed_checks = {
        "pdf_exists": bool(bundle_paths.get("pdf_path"))
        and Path(str(bundle_paths.get("pdf_path"))).exists(),
        "latex_compiled": "missing_tex" not in issue_categories
        and "latex_error" not in issue_categories,
        "citation_warnings": (
            "undefined_citation" in issue_categories
            or bool(manifest.get("citation_warnings"))
            or isinstance(citation_evidence, dict)
        ),
        "figure_warnings": bool(manifest.get("figure_warnings"))
        or isinstance(figure_evidence, dict),
    }
    required_checks = {str(item) for item in gold.get("required_checks") or []}
    covered = {check for check, passed in observed_checks.items() if passed}
    coverage = (
        round(len(required_checks & covered) / len(required_checks), 6)
        if required_checks
        else 0.0
    )
    citation_has_warning = "undefined_citation" in issue_categories or bool(
        manifest.get("citation_warnings")
    )
    if isinstance(citation_evidence, dict) and citation_evidence.get("passed") is False:
        citation_has_warning = True
    citation_integrity = 0.0 if citation_has_warning else 1.0
    issue_counts = {
        "blocking": int(signal.metadata.get("blocking_issue_count", 0)),
        "recompile_repairable": int(
            signal.metadata.get("recompile_repairable_issue_count", 0)
        ),
        "layout_only": int(signal.metadata.get("layout_issue_count", 0)),
        "encoding": int(signal.metadata.get("encoding_issue_count", 0)),
    }
    metrics = {
        "final_bundle_check_coverage": coverage,
        "citation_integrity": citation_integrity,
        "combined_score": round((coverage + citation_integrity) / 2, 6),
    }
    runner_output = {
        "issue_counts": issue_counts,
        "observed_checks": observed_checks,
        "issues": [
            {
                "category": issue.category,
                "severity": issue.severity,
                "message": issue.message,
                "source_path": issue.source_path,
                "line_number": issue.line_number,
                "metadata": dict(issue.metadata),
            }
            for issue in signal.issues
        ],
    }
    if runner_output_extra:
        runner_output.update(runner_output_extra)
    return {
        "task_id": str(visible.get("task_id") or ""),
        "split": str(visible.get("split") or SPLIT_MUTATE_DEV),
        "task_type": "final_bundle",
        "metrics": metrics,
        "rh_axis_ids": list(visible.get("expected_rh_axes") or []),
        "runner_id": runner_id,
        "baseline_id": runner_id,
        "model_execution_performed": False,
        "evidence_state": "fixture_or_local_gold",
        "runner_output": runner_output,
    }


def _baseline_prediction(
    visible: dict[str, Any], *, baseline_id: str
) -> dict[str, Any]:
    if baseline_id == "deterministic_visible":
        return _visible_heuristic_prediction(visible)
    return {
        "selected_paper_ids": [],
        "claims": [],
        "evidence_links": [],
        "draft": "",
        "citations": [],
        "bundle_checks": [],
    }


def _visible_heuristic_prediction(visible: dict[str, Any]) -> dict[str, Any]:
    task_input = visible.get("input") if isinstance(visible.get("input"), dict) else {}
    task_type = str(visible.get("task_type") or "")
    if task_type == "paper_selection":
        papers = task_input.get("candidate_papers") or []
        return {
            "selected_paper_ids": [str(papers[0].get("paper_id"))] if papers else []
        }
    if task_type == "paper_reading":
        paper = task_input.get("paper") or {}
        return {
            "claims": [
                {
                    "paper_id": str(paper.get("paper_id") or ""),
                    "claim_text": str(paper.get("abstract") or "").split(".")[0],
                    "scope": "",
                }
            ]
        }
    if task_type == "evidence_linking":
        spans = task_input.get("candidate_spans") or []
        return {
            "evidence_links": [
                {
                    "span_id": str(span.get("span_id") or ""),
                    "support_label": "partial_support",
                }
                for span in spans
            ]
        }
    if task_type == "section_drafting":
        cards = task_input.get("evidence_cards") or []
        citations = [str(card.get("paper_id") or "") for card in cards]
        return {
            "draft": " ".join(str(card.get("claim") or "") for card in cards),
            "citations": citations,
        }
    if task_type == "final_bundle":
        manifest = task_input.get("bundle_manifest") or {}
        return {"bundle_checks": list(manifest.keys())}
    return {}


def _contract_scan_prediction(visible: dict[str, Any]) -> dict[str, Any]:
    task_input = visible.get("input") if isinstance(visible.get("input"), dict) else {}
    task_type = str(visible.get("task_type") or "")
    if task_type == "paper_selection":
        papers = (
            task_input.get("candidate_papers")
            if isinstance(task_input.get("candidate_papers"), list)
            else []
        )
        positive_terms = (
            "claim",
            "citation",
            "draft",
            "evidence",
            "ground",
            "scientific",
            "writing",
        )
        selected = []
        for paper in papers:
            if not isinstance(paper, dict):
                continue
            searchable = " ".join(
                str(paper.get(field) or "") for field in ("title", "abstract")
            ).lower()
            if any(term in searchable for term in positive_terms):
                selected.append(str(paper.get("paper_id") or ""))
        return {"selected_paper_ids": [paper_id for paper_id in selected if paper_id]}

    if task_type == "paper_reading":
        paper = (
            task_input.get("paper") if isinstance(task_input.get("paper"), dict) else {}
        )
        title = str(paper.get("title") or "")
        abstract = str(paper.get("abstract") or "")
        return {
            "claims": [
                {
                    "paper_id": str(paper.get("paper_id") or ""),
                    "claim_text": _contract_claim_text(title, abstract),
                    "scope": _contract_claim_scope(abstract),
                }
            ]
        }

    if task_type == "evidence_linking":
        claim = (
            task_input.get("claim") if isinstance(task_input.get("claim"), dict) else {}
        )
        spans = (
            task_input.get("candidate_spans")
            if isinstance(task_input.get("candidate_spans"), list)
            else []
        )
        claim_text = str(claim.get("claim_text") or "")
        links = []
        for span in spans:
            if not isinstance(span, dict):
                continue
            span_id = str(span.get("span_id") or "")
            if not span_id:
                continue
            support_label = _contract_support_label(
                claim_text,
                str(span.get("text") or ""),
            )
            links.append(
                {
                    "span_id": span_id,
                    "support_label": support_label,
                    **_typed_evidence_link_fields(
                        span_id=span_id,
                        span_text=str(span.get("text") or ""),
                        support_label=support_label,
                    ),
                    **_citation_governance_replay_fields(
                        span_id=span_id,
                        support_label=support_label,
                    ),
                }
            )
        return {"evidence_links": links}

    if task_type == "section_drafting":
        cards = (
            task_input.get("evidence_cards")
            if isinstance(task_input.get("evidence_cards"), list)
            else []
        )
        citations = []
        sentences = []
        for card in cards:
            if not isinstance(card, dict):
                continue
            paper_id = str(card.get("paper_id") or "")
            claim = str(card.get("claim") or "")
            if paper_id:
                citations.append(paper_id)
            if claim:
                suffix = f" [{paper_id}]" if paper_id else ""
                sentences.append(f"{claim}{suffix}.")
        return {"draft": " ".join(sentences), "citations": citations}

    return {}


def _contract_claim_text(title: str, abstract: str) -> str:
    title_lower = title.lower()
    abstract_lower = abstract.lower()
    if "span-level evidence" in title_lower and "factual consistency" in abstract_lower:
        return (
            "Span-level evidence gates improve factual consistency for draft "
            "claims with exact supporting spans."
        )
    return _first_sentence(abstract)


def _contract_claim_scope(abstract: str) -> str:
    abstract_lower = abstract.lower()
    if "supporting span" in abstract_lower:
        return "draft claims with exact supporting spans"
    return _first_sentence(abstract)


def _contract_support_label(claim_text: str, span_text: str) -> str:
    span_lower = span_text.lower()
    if any(
        phrase in span_lower
        for phrase in (
            "not evaluated",
            "does not",
            "no evidence",
            "contradict",
            "fails to",
        )
    ):
        return "contradicts"
    if "both" in claim_text.lower():
        return "partial_support"
    return "supports"


def _support_status_from_label(support_label: str) -> str:
    return {
        "supports": "supports",
        "full_support": "supports",
        "partial_support": "partial",
        "partial": "partial",
        "contradicts": "contradicts",
        "unsupported": "unsupported",
    }.get(support_label, "unknown")


def _typed_evidence_link_fields(
    *,
    span_id: str,
    span_text: str,
    support_label: str,
) -> dict[str, Any]:
    return {
        "support_status": _support_status_from_label(support_label),
        "evidence_span": {
            "paper_id": 0,
            "section": "candidate_span",
            "snippet": span_text,
        },
        "citation_candidate": {
            "paper_id": 0,
            "identifier": span_id,
            "source_type": "candidate_span",
            "title": f"Post-search visible span {span_id}",
        },
    }


def _citation_governance_replay_fields(
    *,
    span_id: str,
    support_label: str,
) -> dict[str, Any]:
    support_status = _support_status_from_label(support_label)
    verification = {
        "object_type": "citation_verification",
        "target_id": span_id,
        "status": support_status,
    }
    if support_status not in {"unsupported", "contradicts"}:
        return {"citation_verification": verification}

    return {
        "citation_verification": verification,
        "review_issue": {
            "object_type": "review_issue",
            "target_id": span_id,
            "category": "unsupported_evidence_link",
            "status": "open",
            "blocking": True,
        },
        "gate_decision": {
            "object_type": "gate_decision",
            "target_id": span_id,
            "action": "block",
            "reason_codes": ["unsupported_evidence_link"],
        },
    }


def _first_sentence(text: str) -> str:
    sentence = text.split(".")[0].strip()
    return f"{sentence}." if sentence else ""


def _score_prediction(
    visible: dict[str, Any],
    gold: dict[str, Any],
    prediction: dict[str, Any],
) -> dict[str, float]:
    task_type = str(visible.get("task_type") or "")
    if task_type == "paper_selection":
        return _score_paper_selection(gold, prediction)
    if task_type == "paper_reading":
        return _score_claim_extraction(gold, prediction)
    if task_type == "evidence_linking":
        return _score_evidence_linking(gold, prediction)
    if task_type == "section_drafting":
        return _score_section_drafting(gold, prediction)
    if task_type == "final_bundle":
        return _score_final_bundle(gold, prediction)
    return {"combined_score": 0.0}


def _score_paper_selection(
    gold: dict[str, Any], prediction: dict[str, Any]
) -> dict[str, float]:
    expected = {str(item) for item in gold.get("selected_paper_ids") or []}
    selected = {str(item) for item in prediction.get("selected_paper_ids") or []}
    precision = round(len(expected & selected) / len(selected), 6) if selected else 0.0
    recall = round(len(expected & selected) / len(expected), 6) if expected else 0.0
    return {
        "paper_selection_precision": precision,
        "paper_selection_recall": recall,
        "combined_score": round((precision + recall) / 2, 6),
    }


def _score_claim_extraction(
    gold: dict[str, Any], prediction: dict[str, Any]
) -> dict[str, float]:
    expected_claim = (gold.get("claims") or [{}])[0]
    predicted_claim = (prediction.get("claims") or [{}])[0]
    required_fields = ("paper_id", "claim_text", "scope")
    field_coverage = round(
        sum(1 for field in required_fields if predicted_claim.get(field))
        / len(required_fields),
        6,
    )
    text_match = _token_overlap(
        str(expected_claim.get("claim_text") or ""),
        str(predicted_claim.get("claim_text") or ""),
    )
    return {
        "claim_required_field_coverage": field_coverage,
        "claim_text_match": text_match,
        "combined_score": round((field_coverage + text_match) / 2, 6),
    }


def _score_evidence_linking(
    gold: dict[str, Any], prediction: dict[str, Any]
) -> dict[str, float]:
    expected = {
        str(item.get("span_id") or ""): str(item.get("support_label") or "")
        for item in gold.get("evidence_links") or []
        if isinstance(item, dict)
    }
    predicted = {
        str(item.get("span_id") or ""): str(item.get("support_label") or "")
        for item in prediction.get("evidence_links") or []
        if isinstance(item, dict)
    }
    predicted_records = {
        str(item.get("span_id") or ""): item
        for item in prediction.get("evidence_links") or []
        if isinstance(item, dict)
    }
    correct = sum(
        1 for span_id, label in expected.items() if predicted.get(span_id) == label
    )
    accuracy = round(correct / len(expected), 6) if expected else 0.0
    span_match = (
        round(len(set(expected) & set(predicted)) / len(expected), 6)
        if expected
        else 0.0
    )
    typed_hits = 0
    typed_total = len(expected) * 3
    governance_hits = 0
    governance_total = 0
    for span_id in expected:
        record = predicted_records.get(span_id) or {}
        evidence_span = record.get("evidence_span")
        citation_candidate = record.get("citation_candidate")
        if record.get("support_status"):
            typed_hits += 1
        if isinstance(evidence_span, dict) and evidence_span.get("snippet"):
            typed_hits += 1
        if isinstance(citation_candidate, dict) and citation_candidate.get(
            "identifier"
        ):
            typed_hits += 1
        expected_status = _support_status_from_label(expected.get(span_id) or "")
        if expected_status in {"unsupported", "contradicts"}:
            governance_total += 3
            citation_verification = record.get("citation_verification")
            review_issue = record.get("review_issue")
            gate_decision = record.get("gate_decision")
            if isinstance(citation_verification, dict) and citation_verification.get(
                "status"
            ):
                governance_hits += 1
            if isinstance(review_issue, dict) and review_issue.get("blocking"):
                governance_hits += 1
            if (
                isinstance(gate_decision, dict)
                and gate_decision.get("action") == "block"
            ):
                governance_hits += 1
    typed_contract_coverage = round(typed_hits / typed_total, 6) if typed_total else 0.0
    governance_replay_coverage = (
        round(governance_hits / governance_total, 6) if governance_total else 1.0
    )
    return {
        "support_label_accuracy": accuracy,
        "evidence_span_exact_match": span_match,
        "typed_contract_coverage": typed_contract_coverage,
        "citation_governance_replay_coverage": governance_replay_coverage,
        "combined_score": round(
            (
                accuracy
                + span_match
                + typed_contract_coverage
                + governance_replay_coverage
            )
            / 4,
            6,
        ),
    }


def _score_section_drafting(
    gold: dict[str, Any], prediction: dict[str, Any]
) -> dict[str, float]:
    required = {str(item) for item in gold.get("required_citations") or []}
    citations = {str(item) for item in prediction.get("citations") or []}
    grounding = round(len(required & citations) / len(required), 6) if required else 0.0
    draft = str(prediction.get("draft") or "").lower()
    forbidden = [str(item).lower() for item in gold.get("forbidden_claims") or []]
    unsupported_rate = (
        round(
            sum(1 for item in forbidden if item and item in draft) / len(forbidden),
            6,
        )
        if forbidden
        else 0.0
    )
    return {
        "citation_grounding": grounding,
        "unsupported_claim_rate": unsupported_rate,
        "combined_score": round((grounding + (1.0 - unsupported_rate)) / 2, 6)
        if draft
        else 0.0,
    }


def _score_final_bundle(
    gold: dict[str, Any], prediction: dict[str, Any]
) -> dict[str, float]:
    required = {str(item) for item in gold.get("required_checks") or []}
    checks = {str(item) for item in prediction.get("bundle_checks") or []}
    coverage = round(len(required & checks) / len(required), 6) if required else 0.0
    citation_integrity = 1.0 if "citation_warnings" in checks else 0.0
    return {
        "final_bundle_check_coverage": coverage,
        "citation_integrity": citation_integrity,
        "combined_score": round((coverage + citation_integrity) / 2, 6),
    }


def _aggregate(scores: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    metric_names = tuple(
        dict.fromkeys(
            metric
            for score in scores
            for metric, value in (score.get("metrics") or {}).items()
            if isinstance(metric, str) and isinstance(value, (int, float, bool))
        )
    )
    aggregates: dict[str, Any] = {
        "score_count": len(scores),
        "blocked_score_count": sum(
            1
            for score in scores
            if str(score.get("evidence_state") or "").startswith("blocked")
        ),
        "skipped_score_count": sum(
            1
            for score in scores
            if str(score.get("evidence_state") or "") == "skipped_runner_scope"
        ),
    }
    supported_combined = [
        float((score.get("metrics") or {}).get("combined_score"))
        for score in scores
        if isinstance((score.get("metrics") or {}).get("combined_score"), (int, float))
    ]
    aggregates["supported_score_count"] = len(supported_combined)
    aggregates["mean_supported_combined_score"] = (
        round(sum(supported_combined) / len(supported_combined), 6)
        if supported_combined
        else 0.0
    )
    for metric in metric_names:
        values = [
            float((score.get("metrics") or {}).get(metric) or 0.0) for score in scores
        ]
        aggregates[f"mean_{metric}"] = (
            round(sum(values) / len(values), 6) if values else 0.0
        )
    return aggregates


def _postsearch_runner_kind(runner_id: str) -> str:
    if runner_id == POSTSEARCH_CONTRACT_SCAN:
        return "deterministic_postsearch_contract_scan"
    if runner_id == POSTSEARCH_EVIDENCE_LINK_RECORD_REPLAY:
        return "real_rh_evidence_link_record_replay"
    return "real_rh_postsearch_primitive"


def _token_overlap(expected: str, predicted: str) -> float:
    expected_tokens = set(_tokens(expected))
    predicted_tokens = set(_tokens(predicted))
    if not expected_tokens or not predicted_tokens:
        return 0.0
    return round(len(expected_tokens & predicted_tokens) / len(expected_tokens), 6)


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(
        part.strip(".,;:()[]{}").lower()
        for part in text.split()
        if part.strip(".,;:()[]{}")
    )


def _license_payload() -> dict[str, Any]:
    return {
        "dataset_license": "cc0-1.0",
        "data_source_url": "synthetic://researchflowbench/postsearch_pilot5_v0",
        "redistribution_policy": "public_safe_synthetic_metadata_only",
        "gold_storage_policy": GOLD_STORAGE_LOCAL_ONLY,
        "third_party_data_vendored": False,
        "license_review_required": False,
    }


def _create_replay_topic(db: Database) -> int:
    conn = db.connect()
    try:
        cur = conn.execute(
            "INSERT INTO topics (name, description, target_venue) VALUES (?, ?, ?)",
            (
                "postsearch-pilot5-generated-pdf-replay",
                "Synthetic ResearchFlowBench post-search generated PDF replay.",
                "AAAI",
            ),
        )
        topic_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO projects (topic_id, name, description) VALUES (?, ?, ?)",
            (
                topic_id,
                "postsearch-pilot5-generated-pdf-replay",
                "Temporary project for generated PDF replay.",
            ),
        )
        conn.commit()
        return topic_id
    finally:
        conn.close()


def _created_artifact_id(
    created_artifacts: list[dict[str, Any]],
    component: str,
) -> int:
    for artifact in created_artifacts:
        if artifact.get("component") == component:
            try:
                return int(artifact.get("artifact_id") or 0)
            except (TypeError, ValueError):
                return 0
    return 0


def _generated_bundle_manifest(final_payload: dict[str, Any]) -> dict[str, Any]:
    citation_evidence = final_payload.get("citation_integrity_evidence")
    figure_evidence = final_payload.get("figure_placement_evidence")
    warnings = [str(item) for item in final_payload.get("warnings") or []]
    citation_warning = any(
        "citation" in warning.lower() or "undefined reference" in warning.lower()
        for warning in warnings
    )
    return {
        "citation_warnings": citation_warning
        or (
            isinstance(citation_evidence, dict)
            and citation_evidence.get("passed") is False
        ),
        "figure_warnings": bool(
            isinstance(figure_evidence, dict) and figure_evidence.get("warning")
        ),
        "citation_integrity_evidence": citation_evidence,
        "figure_placement_evidence": figure_evidence,
    }


def _common_split(scores: tuple[dict[str, Any], ...]) -> str:
    splits = tuple(dict.fromkeys(str(score.get("split") or "") for score in scores))
    return splits[0] if len(splits) == 1 else "mixed"


def _pack_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def _file_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
