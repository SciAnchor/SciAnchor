"""Model-free ResearchFlowBench baseline runner and scorer."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from paperindex.retrieval import BM25Document, BM25Index

from .contract import SCORE_REPORT_SCHEMA_VERSION
from .litsearch_adapter import LitSearchAdapter, LitSearchTask
from .autoresearchbench_adapter import AutoResearchBenchAdapter, AutoResearchBenchTask
from .validators import (
    ValidationReport,
    validate_external_task_pack,
    validate_pilot20_task_pack,
)


BASELINE_STUB_ZERO = "stub_zero"
BASELINE_DETERMINISTIC_VISIBLE = "deterministic_visible"
BASELINE_LEXICAL_RETRIEVAL = "lexical_retrieval"
BASELINE_BM25_RETRIEVAL = "bm25_retrieval"
BASELINE_AUTORESEARCHBENCH_CANDIDATE_BM25 = "autoresearchbench_candidate_bm25"
AUTORESEARCHBENCH_CANDIDATE_SOURCE_SCHEMA_VERSION = (
    "researchflowbench.autoresearchbench_candidate_source.v0.1"
)
EXTERNAL_PREDICTIONS_SCHEMA_VERSION = "researchflowbench.external_predictions.v0.1"
MAX_EXTERNAL_AGENT_ITERATIONS = 5
_AUTORESEARCHBENCH_FORBIDDEN_CANDIDATE_FIELDS = frozenset(
    {
        "answer",
        "answers",
        "answer_titles",
        "answer_arxiv_ids",
        "gold_titles",
        "gold_paper_ids",
    }
)
_AUTORESEARCHBENCH_ARXIV_ID_RE = re.compile(r"(?i)(\d{4}\.\d{4,5})(?:v\d+)?")
SUPPORTED_BASELINES = (
    BASELINE_STUB_ZERO,
    BASELINE_DETERMINISTIC_VISIBLE,
    BASELINE_LEXICAL_RETRIEVAL,
    BASELINE_BM25_RETRIEVAL,
    BASELINE_AUTORESEARCHBENCH_CANDIDATE_BM25,
)


@dataclass(frozen=True)
class BaselineRunResult:
    """Result of a model-free ResearchFlowBench baseline run."""

    report: dict[str, Any]
    validation_report: ValidationReport

    def to_dict(self) -> dict[str, Any]:
        return {
            "report": self.report,
            "validation_report": self.validation_report.to_dict(),
        }


@dataclass(frozen=True)
class _AutoResearchBenchCandidateSource:
    index: BM25Index
    records_by_id: dict[str, dict[str, str]]
    manifest: dict[str, Any]


def run_pilot20_baseline(
    task_pack_root: str | Path,
    *,
    baseline_id: str = BASELINE_STUB_ZERO,
    allow_invalid: bool = False,
    artifact_refs: tuple[str, ...] = (),
) -> BaselineRunResult:
    """Validate and score a Pilot-20 task pack without model or network calls."""

    if baseline_id not in SUPPORTED_BASELINES:
        raise ValueError(f"unsupported ResearchFlowBench baseline: {baseline_id}")

    root = Path(task_pack_root)
    validation = validate_pilot20_task_pack(root)
    if not validation.is_valid and not allow_invalid:
        issue_codes = ", ".join(issue.code for issue in validation.issues[:5])
        raise ValueError(
            "ResearchFlowBench task pack validation failed before baseline scoring"
            + (f": {issue_codes}" if issue_codes else "")
        )

    manifest = _load_json(root / "pilot20_manifest_draft.json")
    benchmark_id = str(
        manifest.get("pack_id") or "researchflowbench.synthetic_public_pilot20_v0"
    )
    default_refs = (f"task_pack:{root}",)
    resolved_artifact_refs = tuple(dict.fromkeys((*default_refs, *artifact_refs)))

    scores = tuple(
        _score_pilot20_task(root, task_entry, baseline_id=baseline_id)
        for task_entry in manifest.get("tasks", [])
        if isinstance(task_entry, dict)
    )
    split = _common_split(scores)
    rh_axis_ids = tuple(
        dict.fromkeys(
            axis
            for score in scores
            for axis in score.get("rh_axis_ids", [])
            if isinstance(axis, str) and axis
        )
    )
    aggregates = _aggregate_metrics(scores)
    report = {
        "schema_version": SCORE_REPORT_SCHEMA_VERSION,
        "benchmark_id": benchmark_id,
        "split": split,
        "baseline_id": baseline_id,
        "baseline_kind": "model_free_stub",
        "scores": list(scores),
        "metrics": aggregates,
        "rh_axis_ids": list(rh_axis_ids),
        "artifact_refs": list(resolved_artifact_refs),
        "model_execution_performed": False,
        "validation": {
            "is_valid": validation.is_valid,
            "checked_task_count": validation.checked_task_count,
            "checked_file_count": validation.checked_file_count,
            "issue_count": len(validation.issues),
        },
        "metadata": {
            "runner": "researchflowbench.model_free_baseline.v0.1",
            "task_pack_sha256": _pack_digest(root),
            "task_count": len(scores),
            "automatic_mutation_enabled": False,
        },
    }
    return BaselineRunResult(report=report, validation_report=validation)


def run_external_task_pack_baseline(
    task_pack_root: str | Path,
    *,
    baseline_id: str = BASELINE_STUB_ZERO,
    allow_invalid: bool = False,
    artifact_refs: tuple[str, ...] = (),
    evidence_state: str = "fixture_or_local_gold",
    data_root: str | Path | None = None,
    candidate_top_k: int = 20,
) -> BaselineRunResult:
    """Score an adapter-generated external pack with deterministic empty outputs."""

    if candidate_top_k < 1:
        raise ValueError("candidate_top_k must be positive")
    if baseline_id not in {
        BASELINE_STUB_ZERO,
        BASELINE_LEXICAL_RETRIEVAL,
        BASELINE_BM25_RETRIEVAL,
        BASELINE_AUTORESEARCHBENCH_CANDIDATE_BM25,
    }:
        raise ValueError(
            f"unsupported external ResearchFlowBench baseline: {baseline_id}"
        )

    root = Path(task_pack_root)
    validation = validate_external_task_pack(root, allow_local_gold=True)
    if not validation.is_valid and not allow_invalid:
        issue_codes = ", ".join(issue.code for issue in validation.issues[:5])
        raise ValueError(
            "external ResearchFlowBench task pack validation failed before scoring"
            + (f": {issue_codes}" if issue_codes else "")
        )

    manifest = _load_json(root / "adapter_manifest.json")
    benchmark_id = str(manifest.get("benchmark_id") or "")
    retrieval_index = None
    candidate_source = None
    if baseline_id in {BASELINE_LEXICAL_RETRIEVAL, BASELINE_BM25_RETRIEVAL}:
        if benchmark_id != "litsearch":
            raise ValueError(f"{baseline_id} is currently supported only for LitSearch")
        if data_root is None:
            raise ValueError(
                f"{baseline_id} requires --data with a LitSearch export root"
            )
        retrieval_index = _build_litsearch_lexical_index(Path(data_root))
    if baseline_id == BASELINE_AUTORESEARCHBENCH_CANDIDATE_BM25:
        if benchmark_id != "autoresearchbench":
            raise ValueError(
                f"{baseline_id} is currently supported only for AutoResearchBench"
            )
        if data_root is None:
            raise ValueError(
                f"{baseline_id} requires --data with an AutoResearchBench "
                "candidate-source root"
            )
        candidate_source = _build_autoresearchbench_candidate_source(Path(data_root))
    scores = tuple(
        _score_external_task(
            root,
            task_id,
            benchmark_id=benchmark_id,
            baseline_id=baseline_id,
            retrieval_index=retrieval_index,
            candidate_source=candidate_source,
            candidate_top_k=candidate_top_k,
        )
        for task_id in manifest.get("task_ids", [])
        if isinstance(task_id, str)
    )
    scores = tuple(
        score | {"evidence_state": evidence_state}
        if score.get("evidence_state") == "fixture_or_local_gold"
        else score
        for score in scores
    )
    blocked_scores = tuple(
        score
        for score in scores
        if str(score.get("evidence_state") or "").startswith("blocked")
    )
    default_refs = (f"task_pack:{root}",)
    resolved_artifact_refs = tuple(dict.fromkeys((*default_refs, *artifact_refs)))
    report = {
        "schema_version": SCORE_REPORT_SCHEMA_VERSION,
        "benchmark_id": benchmark_id,
        "adapter_contract": str(manifest.get("adapter_contract") or ""),
        "split": _common_split(scores),
        "baseline_id": baseline_id,
        "baseline_kind": (
            "model_free_candidate_retrieval"
            if baseline_id == BASELINE_AUTORESEARCHBENCH_CANDIDATE_BM25
            else "model_free_empty_prediction"
        ),
        "scores": list(scores),
        "metrics": _aggregate_external_metrics(scores),
        "rh_axis_ids": list(
            dict.fromkeys(
                axis
                for score in scores
                for axis in score.get("rh_axis_ids", [])
                if isinstance(axis, str) and axis
            )
        ),
        "artifact_refs": list(resolved_artifact_refs),
        "model_execution_performed": False,
        "validation": {
            "is_valid": validation.is_valid,
            "checked_task_count": validation.checked_task_count,
            "checked_file_count": validation.checked_file_count,
            "issue_count": len(validation.issues),
        },
        "metadata": {
            "runner": "researchflowbench.external_model_free_baseline.v0.1",
            "task_pack_sha256": _pack_digest(root),
            "task_count": len(scores),
            "blocked_score_count": len(blocked_scores),
            "data_root": str(data_root) if data_root is not None else "",
            "candidate_top_k": candidate_top_k,
            "automatic_mutation_enabled": False,
        },
    }
    return BaselineRunResult(report=report, validation_report=validation)


def run_external_task_pack_predictions(
    task_pack_root: str | Path,
    predictions_file: str | Path,
    *,
    allow_invalid: bool = False,
    artifact_refs: tuple[str, ...] = (),
    evidence_state: str = "prediction_file_scored",
    max_agent_iterations: int = MAX_EXTERNAL_AGENT_ITERATIONS,
    max_retrieval_iterations: int = MAX_EXTERNAL_AGENT_ITERATIONS,
    task_ids: tuple[str, ...] = (),
) -> BaselineRunResult:
    """Score external predictions after candidate generation has finished.

    The prediction phase is gold-blind. This scorer is the only phase that reads
    local ``gold.json`` files, mirroring the post-search prediction-file replay
    boundary.
    """

    _validate_external_iteration_limit(
        max_agent_iterations,
        name="max_agent_iterations",
    )
    _validate_external_iteration_limit(
        max_retrieval_iterations,
        name="max_retrieval_iterations",
    )
    root = Path(task_pack_root)
    validation = validate_external_task_pack(root, allow_local_gold=True)
    if not validation.is_valid and not allow_invalid:
        issue_codes = ", ".join(issue.code for issue in validation.issues[:5])
        raise ValueError(
            "external ResearchFlowBench task pack validation failed before "
            "prediction scoring" + (f": {issue_codes}" if issue_codes else "")
        )

    predictions_path = Path(predictions_file)
    prediction_payload = _load_json(predictions_path)
    _validate_external_prediction_contract(prediction_payload)
    runner_id = str(prediction_payload.get("runner_id") or "prediction_file")
    model_execution_performed = (
        prediction_payload.get("model_execution_performed") is True
    )
    _validate_external_prediction_limits(
        prediction_payload,
        max_agent_iterations=max_agent_iterations,
        max_retrieval_iterations=max_retrieval_iterations,
    )
    prediction_map = _external_prediction_map(prediction_payload)

    manifest = _load_json(root / "adapter_manifest.json")
    benchmark_id = str(manifest.get("benchmark_id") or "")
    if benchmark_id != "autoresearchbench":
        raise ValueError(
            "external prediction scoring is currently supported only for "
            "AutoResearchBench"
        )
    if prediction_payload["benchmark_id"] != benchmark_id:
        raise ValueError(
            "external prediction benchmark_id does not match task pack: "
            f"{prediction_payload['benchmark_id']} != {benchmark_id}"
        )
    manifest_task_ids = tuple(
        str(task_id)
        for task_id in manifest.get("task_ids", [])
        if isinstance(task_id, str)
    )
    selected_task_ids = tuple(task_ids) if task_ids else manifest_task_ids
    missing = sorted(set(selected_task_ids) - set(manifest_task_ids))
    if missing:
        raise ValueError(f"task IDs not found in task pack: {missing}")

    scores = tuple(
        _score_external_prediction_task(
            root,
            task_id,
            benchmark_id=benchmark_id,
            runner_id=runner_id,
            prediction_entry=prediction_map.get(task_id),
            model_execution_performed=model_execution_performed,
            evidence_state=evidence_state,
        )
        for task_id in selected_task_ids
    )
    blocked_scores = tuple(
        score
        for score in scores
        if str(score.get("evidence_state") or "").startswith("blocked")
    )
    default_refs = (f"task_pack:{root}", f"predictions:{predictions_path}")
    resolved_artifact_refs = tuple(dict.fromkeys((*default_refs, *artifact_refs)))
    report = {
        "schema_version": SCORE_REPORT_SCHEMA_VERSION,
        "benchmark_id": benchmark_id,
        "adapter_contract": str(manifest.get("adapter_contract") or ""),
        "split": _common_split(scores),
        "baseline_id": runner_id,
        "baseline_kind": "external_prediction_file",
        "scores": list(scores),
        "metrics": _aggregate_external_metrics(scores),
        "rh_axis_ids": list(
            dict.fromkeys(
                axis
                for score in scores
                for axis in score.get("rh_axis_ids", [])
                if isinstance(axis, str) and axis
            )
        ),
        "artifact_refs": list(resolved_artifact_refs),
        "model_execution_performed": model_execution_performed,
        "validation": {
            "is_valid": validation.is_valid,
            "checked_task_count": validation.checked_task_count,
            "checked_file_count": validation.checked_file_count,
            "issue_count": len(validation.issues),
        },
        "metadata": {
            "runner": "researchflowbench.external_predictions.v0.1",
            "task_pack_sha256": _pack_digest(root),
            "task_count": len(scores),
            "selected_task_ids": list(selected_task_ids),
            "blocked_score_count": len(blocked_scores),
            "prediction_schema_version": str(
                prediction_payload.get("schema_version") or ""
            ),
            "prediction_file": str(predictions_path),
            "max_agent_iterations": max_agent_iterations,
            "max_retrieval_iterations": max_retrieval_iterations,
            "automatic_mutation_enabled": False,
        },
    }
    return BaselineRunResult(report=report, validation_report=validation)


def write_score_report(report: dict[str, Any], output_path: str | Path) -> Path:
    """Write a score report JSON file with deterministic formatting."""

    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def build_autoresearchbench_candidate_source(
    source_path: str | Path,
    output_dir: str | Path,
    *,
    source_kind: str = "metadata_jsonl",
    overwrite: bool = False,
    limit: int | None = None,
    source_name: str | None = None,
) -> dict[str, Any]:
    """Build a non-gold AutoResearchBench candidate-source root."""

    source = Path(source_path)
    out = Path(output_dir)
    if limit is not None and limit < 1:
        raise ValueError("candidate source limit must be positive")
    if not source.exists():
        raise ValueError(f"candidate metadata source does not exist: {source}")
    if out.exists() and any(out.iterdir()) and not overwrite:
        raise FileExistsError(f"candidate-source output directory is not empty: {out}")
    out.mkdir(parents=True, exist_ok=True)

    if source_kind == "metadata_jsonl":
        records = _iter_candidate_metadata_jsonl(source, limit=limit)
        source_type = "metadata_jsonl"
    elif source_kind == "research_harness_paper_db":
        records = _iter_candidate_metadata_paper_db(source, limit=limit)
        source_type = "research_harness_paper_db"
    else:
        raise ValueError(
            "source_kind must be metadata_jsonl or research_harness_paper_db"
        )

    record_count = 0
    skipped_count = 0
    duplicate_paper_id_count = 0
    used_paper_ids: set[str] = set()
    corpus_path = out / "candidate_corpus.jsonl"
    with corpus_path.open("w", encoding="utf-8") as handle:
        for line_no, record in enumerate(records, 1):
            normalized = _normalize_autoresearchbench_candidate_record(
                record,
                fallback_id=line_no,
            )
            if normalized is None:
                skipped_count += 1
                continue
            normalized, duplicate = _with_unique_autoresearchbench_candidate_id(
                normalized,
                used_paper_ids=used_paper_ids,
            )
            duplicate_paper_id_count += int(duplicate)
            record_count += 1
            handle.write(
                json.dumps(normalized, sort_keys=True, ensure_ascii=False) + "\n"
            )
    if record_count == 0:
        raise ValueError("candidate source contains no usable paper metadata records")

    manifest = {
        "schema_version": AUTORESEARCHBENCH_CANDIDATE_SOURCE_SCHEMA_VERSION,
        "benchmark_id": "autoresearchbench",
        "records_file": "candidate_corpus.jsonl",
        "gold_label_policy": "no_gold_labels",
        "contains_official_answers": False,
        "source_type": source_type,
        "source_name": source_name or source.name,
        "record_count": record_count,
        "skipped_record_count": skipped_count,
        "duplicate_paper_id_count": duplicate_paper_id_count,
        "third_party_data_vendored": False,
        "builder": (
            "researchflowbench.autoresearchbench_candidate_source_builder.v0.1"
        ),
    }
    (out / "candidate_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def _score_pilot20_task(
    root: Path, task_entry: dict[str, Any], *, baseline_id: str
) -> dict[str, Any]:
    task_dir = root / str(task_entry.get("directory") or "")
    task = _load_json(task_dir / "task.json")
    judge_bundle = _load_json(task_dir / "judge_bundle.json")
    task_id = str(task.get("task_id") or task_entry.get("task_id") or "")
    split = str(task.get("split") or task_entry.get("split") or "draft_dev")
    rh_axis_ids = tuple(str(axis) for axis in task.get("expected_rh_axes") or ())
    expected_objects = tuple(
        str(item) for item in task.get("expected_semantic_objects") or ()
    )
    output = _baseline_output(
        baseline_id=baseline_id,
        task_id=task_id,
        expected_objects=expected_objects,
    )
    object_coverage = _object_coverage(output, expected_objects)
    metrics = {
        "outcome_score": 0.0,
        "process_score": 0.0,
        "combined_score": 0.0,
        "expected_object_coverage": object_coverage,
        "external_search_used": False,
        "model_execution_performed": False,
    }
    return {
        "task_id": task_id,
        "split": split,
        "task_no": str(task_entry.get("task_no") or ""),
        "metrics": metrics,
        "rh_axis_ids": list(rh_axis_ids),
        "baseline_id": baseline_id,
        "baseline_output": output,
        "judge_refs": {
            "judge_only": bool(judge_bundle.get("judge_only")),
            "scoring_axes": sorted((judge_bundle.get("scoring") or {}).keys()),
        },
    }


def _score_external_task(
    root: Path,
    task_id: str,
    *,
    benchmark_id: str,
    baseline_id: str,
    retrieval_index: BM25Index | None = None,
    candidate_source: _AutoResearchBenchCandidateSource | None = None,
    candidate_top_k: int = 20,
) -> dict[str, Any]:
    task_dir = root / "tasks" / task_id
    visible = _load_json(task_dir / "input.json")
    gold_path = task_dir / "gold.json"
    if not gold_path.exists():
        return {
            "task_id": task_id,
            "split": str(visible.get("split") or "mutate_dev"),
            "metrics": {},
            "rh_axis_ids": list(visible.get("expected_rh_axes") or []),
            "baseline_id": BASELINE_STUB_ZERO,
            "model_execution_performed": False,
            "evidence_state": "blocked_missing_local_gold",
            "blockers": ["external_gold_file_missing"],
        }
    gold = _load_json(gold_path)
    if benchmark_id == "litsearch":
        task = LitSearchTask(
            task_id=task_id,
            query_id=str(visible.get("query_id") or task_id),
            query=str(visible.get("query") or ""),
            gold_paper_ids=tuple(
                str(item) for item in gold.get("gold_paper_ids") or ()
            ),
            corpus_paper_ids=tuple(
                str(item) for item in visible.get("corpus_paper_ids") or ()
            ),
            split=str(visible.get("split") or "mutate_dev"),
            metadata=dict(visible.get("metadata") or {}),
        )
        scoring = "bm25" if baseline_id == BASELINE_BM25_RETRIEVAL else "term_frequency"
        retrieved = tuple(
            result.doc_id
            for result in (
                retrieval_index.search(task.query, scoring=scoring)
                if retrieval_index is not None
                else ()
            )
        )
        score = LitSearchAdapter.score_retrieval(task, retrieved)
        payload = score.to_dict()
        payload["split"] = task.split
        payload["metrics"] = {
            "retrieval_recall": payload["recall_at_k"],
            "rerank_quality": payload["mrr"],
            "hit_at_k": payload["hit_at_k"],
        }
        payload["rh_axis_ids"] = list(visible.get("expected_rh_axes") or [])
        payload["baseline_id"] = baseline_id
        payload["model_execution_performed"] = False
        payload["evidence_state"] = "fixture_or_local_gold"
        payload["retrieved_paper_ids"] = list(retrieved[:20])
        return payload
    if benchmark_id == "autoresearchbench":
        task = AutoResearchBenchTask(
            task_id=task_id,
            question=str(
                visible.get("question")
                or (visible.get("input") or {}).get("question")
                or ""
            ),
            task_type=str(visible.get("task_type") or "deep"),
            answer_titles=tuple(str(item) for item in gold.get("answer_titles") or ()),
            answer_arxiv_ids=tuple(
                str(item) for item in gold.get("answer_arxiv_ids") or ()
            ),
            split=str(visible.get("split") or "mutate_dev"),
            metadata=dict(visible.get("metadata") or {}),
        )
        if task.task_type == "wide":
            predicted_arxiv_ids: tuple[str, ...] = ()
            predicted_titles: tuple[str, ...] = ()
            ranked_candidates: tuple[dict[str, Any], ...] = ()
            if (
                baseline_id == BASELINE_AUTORESEARCHBENCH_CANDIDATE_BM25
                and candidate_source is not None
            ):
                ranked_candidates = _retrieve_autoresearchbench_candidates(
                    candidate_source,
                    task.question,
                    top_k=candidate_top_k,
                )
                predicted_arxiv_ids = tuple(
                    candidate["arxiv_id"]
                    for candidate in ranked_candidates
                    if candidate.get("arxiv_id")
                )
                predicted_titles = tuple(
                    candidate["title"]
                    for candidate in ranked_candidates
                    if candidate.get("title")
                )
            score = AutoResearchBenchAdapter.score_wide(task, predicted_arxiv_ids)
        else:
            predicted_arxiv_ids = ()
            predicted_titles = ()
            ranked_candidates = ()
            if (
                baseline_id == BASELINE_AUTORESEARCHBENCH_CANDIDATE_BM25
                and candidate_source is not None
            ):
                ranked_candidates = _retrieve_autoresearchbench_candidates(
                    candidate_source,
                    task.question,
                    top_k=candidate_top_k,
                )
                predicted_titles = tuple(
                    candidate["title"]
                    for candidate in ranked_candidates
                    if candidate.get("title")
                )
                predicted_arxiv_ids = tuple(
                    candidate["arxiv_id"]
                    for candidate in ranked_candidates
                    if candidate.get("arxiv_id")
                )
            score = AutoResearchBenchAdapter.score_deep(task, predicted_titles)
        payload = score.to_dict()
        payload["split"] = task.split
        payload["metrics"] = {
            "deep_accuracy": payload["deep_accuracy"],
            "wide_iou": payload["wide_iou"],
            "wide_recall": payload["wide_recall"],
            "wide_precision": payload["wide_precision"],
        }
        payload["rh_axis_ids"] = list(visible.get("expected_rh_axes") or [])
        payload["baseline_id"] = baseline_id
        payload["model_execution_performed"] = False
        payload["evidence_state"] = "fixture_or_local_gold"
        if baseline_id == BASELINE_AUTORESEARCHBENCH_CANDIDATE_BM25:
            payload["predicted_titles"] = list(predicted_titles)
            payload["predicted_arxiv_ids"] = list(predicted_arxiv_ids)
            payload["retrieval_trace"] = _autoresearchbench_candidate_trace(
                task=task,
                baseline_id=baseline_id,
                ranked_candidates=ranked_candidates,
                candidate_source=candidate_source,
            )
        return payload
    return {
        "task_id": task_id,
        "split": str(visible.get("split") or "mutate_dev"),
        "metrics": {},
        "rh_axis_ids": list(visible.get("expected_rh_axes") or []),
        "baseline_id": baseline_id,
        "model_execution_performed": False,
        "evidence_state": "blocked_unknown_benchmark",
        "blockers": [f"unsupported_benchmark:{benchmark_id}"],
    }


def _build_litsearch_lexical_index(data_root: Path) -> BM25Index:
    corpus_path = data_root / "corpus_clean" / "corpus.jsonl"
    if not corpus_path.exists():
        raise ValueError(f"LitSearch corpus file is required: {corpus_path}")

    documents: list[BM25Document] = []
    with corpus_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                continue
            doc_id = str(
                record.get("corpusid")
                or record.get("corpus_id")
                or record.get("paper_id")
                or ""
            ).strip()
            if not doc_id:
                continue
            text = f"{record.get('title') or ''} {record.get('abstract') or ''}"
            documents.append(BM25Document(doc_id=doc_id, text=text))
    return BM25Index.from_documents(documents)


def _build_autoresearchbench_candidate_source(
    data_root: Path,
) -> _AutoResearchBenchCandidateSource:
    manifest_path = data_root / "candidate_manifest.json"
    if not manifest_path.exists():
        raise ValueError(
            "AutoResearchBench candidate BM25 requires candidate_manifest.json "
            "in a non-gold candidate-source root"
        )
    manifest = _load_json(manifest_path)
    schema_version = str(manifest.get("schema_version") or "")
    if schema_version != AUTORESEARCHBENCH_CANDIDATE_SOURCE_SCHEMA_VERSION:
        raise ValueError(
            "candidate_manifest.json must declare "
            f"schema_version={AUTORESEARCHBENCH_CANDIDATE_SOURCE_SCHEMA_VERSION}"
        )
    if str(manifest.get("benchmark_id") or "") != "autoresearchbench":
        raise ValueError(
            "candidate_manifest.json must declare benchmark_id=autoresearchbench"
        )
    if str(manifest.get("gold_label_policy") or "") != "no_gold_labels":
        raise ValueError("candidate_manifest.json must declare no_gold_labels")
    if bool(manifest.get("contains_official_answers")):
        raise ValueError("candidate source must not contain official answers")

    records_file = str(manifest.get("records_file") or "").strip()
    if not records_file:
        raise ValueError("candidate_manifest.json must declare records_file")
    records_path = Path(records_file)
    if records_path.is_absolute() or ".." in records_path.parts:
        raise ValueError(
            "candidate_manifest.json records_file must stay within the "
            "candidate-source root"
        )
    corpus_path = (data_root / records_path).resolve()
    data_root_resolved = data_root.resolve()
    try:
        corpus_path.relative_to(data_root_resolved)
    except ValueError as exc:
        raise ValueError(
            "candidate_manifest.json records_file must stay within the "
            "candidate-source root"
        ) from exc
    if not corpus_path.exists():
        raise ValueError(
            f"AutoResearchBench candidate corpus file is required: {corpus_path}"
        )

    records_by_id: dict[str, dict[str, str]] = {}
    documents: list[BM25Document] = []
    used_candidate_ids: set[str] = set()
    with corpus_path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                continue
            forbidden = _forbidden_autoresearchbench_candidate_fields(record)
            if forbidden:
                raise ValueError(
                    "AutoResearchBench candidate corpus must not contain gold "
                    f"label fields: {sorted(forbidden)}"
                )
            title = str(record.get("title") or "").strip()
            abstract = str(record.get("abstract") or "").strip()
            doi = str(record.get("doi") or "").strip()
            arxiv_id = _candidate_record_arxiv_id(record)
            paper_id = str(
                record.get("paper_id") or arxiv_id or doi or title or line_no
            ).strip()
            if not paper_id or not (title or abstract):
                continue
            normalized = {
                "candidate_id": paper_id,
                "title": title,
                "abstract": abstract,
                "arxiv_id": arxiv_id,
                "doi": doi,
            }
            normalized, _duplicate = _with_unique_autoresearchbench_candidate_id(
                normalized,
                id_field="candidate_id",
                used_paper_ids=used_candidate_ids,
            )
            candidate_id = normalized["candidate_id"]
            records_by_id[candidate_id] = normalized
            documents.append(
                BM25Document(
                    doc_id=candidate_id,
                    text=f"{title} {abstract} {arxiv_id} {doi}",
                )
            )
    if not documents:
        raise ValueError(
            "AutoResearchBench candidate corpus contains no usable records"
        )
    return _AutoResearchBenchCandidateSource(
        index=BM25Index.from_documents(documents),
        records_by_id=records_by_id,
        manifest=manifest,
    )


def _iter_candidate_metadata_jsonl(
    source: Path,
    *,
    limit: int | None,
) -> tuple[dict[str, Any], ...]:
    records: list[dict[str, Any]] = []
    with source.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            if limit is not None and len(records) >= limit:
                break
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"candidate metadata JSONL has invalid JSON on line {line_no}"
                ) from exc
            if not isinstance(record, dict):
                raise ValueError(
                    f"candidate metadata JSONL line {line_no} is not an object"
                )
            records.append(record)
    return tuple(records)


def _iter_candidate_metadata_paper_db(
    source: Path,
    *,
    limit: int | None,
) -> tuple[dict[str, Any], ...]:
    uri = f"file:{source.resolve()}?mode=ro"
    query = """
        SELECT id, title, abstract, arxiv_id, doi
        FROM papers
        WHERE COALESCE(title, '') != '' OR COALESCE(abstract, '') != ''
        ORDER BY id
    """
    if limit is not None:
        query = f"{query} LIMIT ?"
        params: tuple[Any, ...] = (limit,)
    else:
        params = ()
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        with conn:
            rows = conn.execute(query, params).fetchall()
    except sqlite3.Error as exc:
        raise ValueError(f"failed to read Research Harness paper DB: {source}") from exc
    finally:
        if conn is not None:
            conn.close()
    return tuple(dict(row) for row in rows)


def _normalize_autoresearchbench_candidate_record(
    record: dict[str, Any],
    *,
    fallback_id: int,
) -> dict[str, str] | None:
    forbidden = _forbidden_autoresearchbench_candidate_fields(record)
    if forbidden:
        raise ValueError(
            "AutoResearchBench candidate metadata must not contain gold label "
            f"fields: {sorted(forbidden)}"
        )
    title = str(record.get("title") or "").strip()
    abstract = str(record.get("abstract") or record.get("summary") or "").strip()
    arxiv_id = _candidate_record_arxiv_id(record)
    doi = str(record.get("doi") or "").strip()
    paper_id = str(
        record.get("paper_id")
        or record.get("corpusid")
        or record.get("corpus_id")
        or record.get("id")
        or arxiv_id
        or doi
        or title
        or fallback_id
    ).strip()
    if not paper_id or not (title or abstract):
        return None
    return {
        "paper_id": paper_id,
        "title": title,
        "abstract": abstract,
        "arxiv_id": arxiv_id,
        "doi": doi,
    }


def _candidate_record_arxiv_id(record: dict[str, Any]) -> str:
    explicit = _extract_arxiv_id(
        record.get("arxiv_id"),
        record.get("arxiv"),
        require_marker=False,
    )
    if explicit:
        return explicit
    return _extract_arxiv_id(
        record.get("doi"),
        record.get("url"),
        record.get("paper_id"),
        record.get("id"),
        require_marker=True,
    )


def _extract_arxiv_id(*values: Any, require_marker: bool) -> str:
    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        if require_marker and "arxiv" not in text.lower():
            continue
        match = _AUTORESEARCHBENCH_ARXIV_ID_RE.search(text)
        if match:
            return match.group(1)
    return ""


def _with_unique_autoresearchbench_candidate_id(
    record: dict[str, str],
    *,
    used_paper_ids: set[str],
    id_field: str = "paper_id",
) -> tuple[dict[str, str], bool]:
    paper_id = str(record.get(id_field) or "").strip()
    if not paper_id or paper_id not in used_paper_ids:
        if paper_id:
            used_paper_ids.add(paper_id)
        return record, False

    fingerprint = hashlib.sha256(
        json.dumps(record, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:10]
    candidate_id = f"{paper_id}#{fingerprint}"
    suffix = 2
    while candidate_id in used_paper_ids:
        candidate_id = f"{paper_id}#{fingerprint}-{suffix}"
        suffix += 1
    used_paper_ids.add(candidate_id)
    return {**record, id_field: candidate_id}, True


def _forbidden_autoresearchbench_candidate_fields(record: Any) -> set[str]:
    forbidden: set[str] = set()
    if isinstance(record, dict):
        forbidden.update(_AUTORESEARCHBENCH_FORBIDDEN_CANDIDATE_FIELDS & set(record))
        for value in record.values():
            forbidden.update(_forbidden_autoresearchbench_candidate_fields(value))
    elif isinstance(record, list):
        for item in record:
            forbidden.update(_forbidden_autoresearchbench_candidate_fields(item))
    return forbidden


def _retrieve_autoresearchbench_candidates(
    candidate_source: _AutoResearchBenchCandidateSource,
    query: str,
    *,
    top_k: int = 20,
) -> tuple[dict[str, Any], ...]:
    ranked: list[dict[str, Any]] = []
    for rank, result in enumerate(
        candidate_source.index.search(query, k=top_k, scoring="bm25"), 1
    ):
        record = dict(candidate_source.records_by_id.get(result.doc_id) or {})
        if not record:
            continue
        record["rank"] = rank
        record["score"] = round(float(result.score), 6)
        ranked.append(record)
    return tuple(ranked)


def _autoresearchbench_candidate_trace(
    *,
    task: AutoResearchBenchTask,
    baseline_id: str,
    ranked_candidates: tuple[dict[str, Any], ...],
    candidate_source: _AutoResearchBenchCandidateSource | None,
) -> dict[str, Any]:
    return {
        "schema_version": "researchflowbench.autoresearchbench_candidate_trace.v0.1",
        "task_id": task.task_id,
        "baseline_id": baseline_id,
        "query": task.question,
        "candidate_source_schema_version": str(
            (candidate_source.manifest if candidate_source else {}).get(
                "schema_version"
            )
            or ""
        ),
        "candidate_set": [
            {
                "candidate_id": str(candidate.get("candidate_id") or ""),
                "rank": int(candidate.get("rank") or 0),
                "source": "autoresearchbench_candidate_bm25.candidate_corpus",
                "title": str(candidate.get("title") or ""),
                "arxiv_id": str(candidate.get("arxiv_id") or ""),
                "doi": str(candidate.get("doi") or ""),
                "score": float(candidate.get("score") or 0.0),
            }
            for candidate in ranked_candidates
        ],
        "candidate_ids": [
            str(candidate.get("candidate_id") or "") for candidate in ranked_candidates
        ],
        "retrieval_trace_complete": candidate_source is not None,
    }


def _score_external_prediction_task(
    root: Path,
    task_id: str,
    *,
    benchmark_id: str,
    runner_id: str,
    prediction_entry: dict[str, Any] | None,
    model_execution_performed: bool,
    evidence_state: str,
) -> dict[str, Any]:
    task_dir = root / "tasks" / task_id
    visible = _load_json(task_dir / "input.json")
    gold_path = task_dir / "gold.json"
    if not gold_path.exists():
        return _blocked_external_prediction_score(
            visible,
            task_id=task_id,
            runner_id=runner_id,
            reason="external_gold_file_missing",
            model_execution_performed=model_execution_performed,
        )
    if prediction_entry is None:
        return _blocked_external_prediction_score(
            visible,
            task_id=task_id,
            runner_id=runner_id,
            reason="external_prediction_missing",
            model_execution_performed=model_execution_performed,
        )
    prediction = prediction_entry.get("prediction")
    if not isinstance(prediction, dict):
        return _blocked_external_prediction_score(
            visible,
            task_id=task_id,
            runner_id=runner_id,
            reason="external_prediction_payload_invalid",
            model_execution_performed=model_execution_performed,
        )
    if benchmark_id != "autoresearchbench":
        return _blocked_external_prediction_score(
            visible,
            task_id=task_id,
            runner_id=runner_id,
            reason=f"external_prediction_unsupported_benchmark:{benchmark_id}",
            model_execution_performed=model_execution_performed,
        )

    try:
        score_payload = _score_autoresearchbench_prediction(
            visible,
            _load_json(gold_path),
            prediction,
        )
    except ValueError:
        return _blocked_external_prediction_score(
            visible,
            task_id=task_id,
            runner_id=runner_id,
            reason="external_prediction_payload_invalid",
            model_execution_performed=model_execution_performed,
        )
    runner_output = prediction_entry.get("runner_output")
    return score_payload | {
        "runner_id": runner_id,
        "baseline_id": runner_id,
        "baseline_output": prediction,
        "model_execution_performed": model_execution_performed,
        "evidence_state": evidence_state,
        "runner_output": runner_output if isinstance(runner_output, dict) else {},
    }


def _score_autoresearchbench_prediction(
    visible: dict[str, Any],
    gold: dict[str, Any],
    prediction: dict[str, Any],
) -> dict[str, Any]:
    predicted_titles = _prediction_string_list(prediction, "predicted_titles")
    predicted_arxiv_ids = _prediction_string_list(prediction, "predicted_arxiv_ids")
    task = AutoResearchBenchTask(
        task_id=str(visible.get("task_id") or ""),
        question=str(
            visible.get("question")
            or (visible.get("input") or {}).get("question")
            or ""
        ),
        task_type=str(visible.get("task_type") or "deep"),
        answer_titles=tuple(str(item) for item in gold.get("answer_titles") or ()),
        answer_arxiv_ids=tuple(
            str(item) for item in gold.get("answer_arxiv_ids") or ()
        ),
        split=str(visible.get("split") or "mutate_dev"),
        metadata=dict(visible.get("metadata") or {}),
    )
    score = (
        AutoResearchBenchAdapter.score_wide(task, predicted_arxiv_ids)
        if task.task_type == "wide"
        else AutoResearchBenchAdapter.score_deep(task, predicted_titles)
    )
    payload = score.to_dict()
    payload["split"] = task.split
    payload["metrics"] = {
        "deep_accuracy": payload["deep_accuracy"],
        "wide_iou": payload["wide_iou"],
        "wide_recall": payload["wide_recall"],
        "wide_precision": payload["wide_precision"],
    }
    payload["rh_axis_ids"] = list(visible.get("expected_rh_axes") or [])
    payload["predicted_titles"] = list(predicted_titles)
    payload["predicted_arxiv_ids"] = list(predicted_arxiv_ids)
    return payload


def _prediction_string_list(
    prediction: dict[str, Any], field_name: str
) -> tuple[str, ...]:
    if field_name not in prediction:
        raise ValueError(f"{field_name} is required")
    value = prediction[field_name]
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    return tuple(str(item).strip() for item in value if str(item).strip())


def _validate_external_prediction_contract(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise ValueError("external prediction file must contain a JSON object")

    required = (
        "schema_version",
        "benchmark_id",
        "runner_id",
        "model_execution_performed",
        "predictions",
    )
    for field_name in required:
        if field_name not in payload:
            raise ValueError(
                f"external prediction file missing required field: {field_name}"
            )

    schema_version = payload["schema_version"]
    if schema_version != EXTERNAL_PREDICTIONS_SCHEMA_VERSION:
        raise ValueError(
            "external prediction schema_version must be "
            f"{EXTERNAL_PREDICTIONS_SCHEMA_VERSION}"
        )
    for field_name in ("benchmark_id", "runner_id"):
        if not isinstance(payload[field_name], str) or not payload[field_name].strip():
            raise ValueError(
                f"external prediction {field_name} must be a non-empty string"
            )
    if not isinstance(payload["model_execution_performed"], bool):
        raise ValueError(
            "external prediction model_execution_performed must be boolean"
        )
    if not isinstance(payload["predictions"], list):
        raise ValueError("external prediction file must contain a predictions list")


def _external_prediction_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    predictions = payload.get("predictions")
    if not isinstance(predictions, list):
        raise ValueError("external prediction file must contain a predictions list")

    mapped: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(predictions):
        if not isinstance(entry, dict):
            raise ValueError(
                f"external prediction entry at index {index} must be an object"
            )
        task_id = entry.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError(
                f"external prediction entry at index {index} is missing task_id"
            )
        if task_id in mapped:
            raise ValueError(f"duplicate external prediction task_id: {task_id}")
        mapped[task_id] = dict(entry)
    return mapped


def _blocked_external_prediction_score(
    visible: dict[str, Any],
    *,
    task_id: str,
    runner_id: str,
    reason: str,
    model_execution_performed: bool,
) -> dict[str, Any]:
    if reason == "external_gold_file_missing":
        evidence_state = "blocked_missing_local_gold"
    elif reason == "external_prediction_missing":
        evidence_state = "blocked_missing_prediction"
    else:
        evidence_state = "blocked_invalid_prediction"
    return {
        "task_id": task_id,
        "split": str(visible.get("split") or "mutate_dev"),
        "task_type": str(visible.get("task_type") or ""),
        "metrics": {},
        "rh_axis_ids": list(visible.get("expected_rh_axes") or []),
        "runner_id": runner_id,
        "baseline_id": runner_id,
        "model_execution_performed": model_execution_performed,
        "evidence_state": evidence_state,
        "blockers": [reason],
    }


def _validate_external_iteration_limit(value: int, *, name: str) -> None:
    if value < 1 or value > MAX_EXTERNAL_AGENT_ITERATIONS:
        raise ValueError(
            f"{name} must be between 1 and {MAX_EXTERNAL_AGENT_ITERATIONS}"
        )


def _validate_external_prediction_limits(
    payload: dict[str, Any],
    *,
    max_agent_iterations: int,
    max_retrieval_iterations: int,
) -> None:
    limits = payload.get("execution_limits")
    if isinstance(limits, dict):
        declared_agent = limits.get("max_agent_iterations")
        declared_retrieval = limits.get("max_retrieval_iterations")
        if declared_agent is not None and int(declared_agent) > max_agent_iterations:
            raise ValueError(
                "declared max_agent_iterations exceeds scoring max_agent_iterations"
            )
        if (
            declared_retrieval is not None
            and int(declared_retrieval) > max_retrieval_iterations
        ):
            raise ValueError(
                "declared max_retrieval_iterations exceeds scoring "
                "max_retrieval_iterations"
            )

    predictions = payload.get("predictions")
    if not isinstance(predictions, list):
        return
    for entry in predictions:
        if not isinstance(entry, dict):
            continue
        runner_output = entry.get("runner_output")
        if not isinstance(runner_output, dict):
            continue
        iterations_used = runner_output.get("iterations_used")
        if iterations_used is not None and int(iterations_used) > max_agent_iterations:
            raise ValueError("iterations_used exceeds max_agent_iterations")
        retrieval_iterations_used = runner_output.get("retrieval_iterations_used")
        if (
            retrieval_iterations_used is not None
            and int(retrieval_iterations_used) > max_retrieval_iterations
        ):
            raise ValueError(
                "retrieval_iterations_used exceeds max_retrieval_iterations"
            )


def _baseline_output(
    *,
    baseline_id: str,
    task_id: str,
    expected_objects: tuple[str, ...],
) -> dict[str, Any]:
    if baseline_id == BASELINE_DETERMINISTIC_VISIBLE:
        return {
            "task_id": task_id,
            "status": "stubbed",
            "semantic_objects": [
                {"object_type": object_type, "source": "visible_contract_stub"}
                for object_type in expected_objects[:1]
            ],
            "external_search_used": False,
            "model_execution_performed": False,
        }
    return {
        "task_id": task_id,
        "status": "no_answer_stub",
        "semantic_objects": [],
        "external_search_used": False,
        "model_execution_performed": False,
    }


def _object_coverage(
    output: dict[str, Any], expected_objects: tuple[str, ...]
) -> float:
    if not expected_objects:
        return 0.0
    emitted = {
        str(item.get("object_type") or "")
        for item in output.get("semantic_objects", [])
        if isinstance(item, dict)
    }
    return round(len(set(expected_objects) & emitted) / len(set(expected_objects)), 6)


def _aggregate_metrics(scores: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    if not scores:
        return {
            "score_count": 0,
            "mean_outcome_score": 0.0,
            "mean_process_score": 0.0,
            "mean_combined_score": 0.0,
            "mean_expected_object_coverage": 0.0,
        }
    return {
        "score_count": len(scores),
        "mean_outcome_score": _mean_metric(scores, "outcome_score"),
        "mean_process_score": _mean_metric(scores, "process_score"),
        "mean_combined_score": _mean_metric(scores, "combined_score"),
        "mean_expected_object_coverage": _mean_metric(
            scores, "expected_object_coverage"
        ),
    }


def _aggregate_external_metrics(scores: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    metric_names = tuple(
        dict.fromkeys(
            metric
            for score in scores
            for metric in (score.get("metrics") or {})
            if isinstance(metric, str)
        )
    )
    aggregates: dict[str, Any] = {
        "score_count": len(scores),
        "blocked_score_count": sum(
            1
            for score in scores
            if str(score.get("evidence_state") or "").startswith("blocked")
        ),
    }
    for metric in metric_names:
        aggregates[f"mean_{metric}"] = _mean_metric(scores, metric)
    return aggregates


def _mean_metric(scores: tuple[dict[str, Any], ...], metric_name: str) -> float:
    values = [
        float((score.get("metrics") or {}).get(metric_name) or 0.0) for score in scores
    ]
    return round(sum(values) / len(values), 6) if values else 0.0


def _common_split(scores: tuple[dict[str, Any], ...]) -> str:
    splits = tuple(dict.fromkeys(str(score.get("split") or "") for score in scores))
    if len(splits) == 1:
        return splits[0]
    return "mixed"


def _pack_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON object: {path}")
    return data
