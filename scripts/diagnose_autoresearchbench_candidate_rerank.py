#!/usr/bin/env python3
"""Diagnose AutoResearchBench candidate ranking/retrieval without printing gold.

The script reads a local task pack with ``gold.json`` files and an existing
candidate BM25 score report. It only emits aggregate metrics for reranking
strategies over the score report's already-recorded candidate sets.

When ``--candidate-source`` is provided, the script also runs explicitly marked
source-retrieval diagnostics over the same non-gold candidate corpus. These
strategies are fresh retrieval experiments, not rerankers over recorded traces.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "packages" / "research_harness"
SCRIPT_ROOT = REPO_ROOT / "scripts"
sys.path.insert(0, str(PACKAGE_ROOT))
sys.path.insert(0, str(SCRIPT_ROOT))

from build_autoresearchbench_arxiv_candidates import (  # noqa: E402
    task_query_variants,
)
from research_harness.eval.researchflowbench.baseline import (  # noqa: E402
    _build_autoresearchbench_candidate_source,
)


SCHEMA_VERSION = "researchflowbench.autoresearchbench_candidate_rerank.v0.1"
EXPECTED_TRACE_SCHEMA_VERSION = (
    "researchflowbench.autoresearchbench_candidate_trace.v0.1"
)
EXPECTED_TRACE_BASELINE_ID = "autoresearchbench_candidate_bm25"
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]{2,}")
DEFAULT_SELECTION_KS = (1, 5, 10, 20, 50)
STRATEGY_IDS = (
    "bm25_order",
    "title_token_overlap",
    "title_overlap_bm25_blend",
    "arxiv_first_bm25",
)
SOURCE_REQUIRED_STRATEGY_IDS = (
    "metadata_field_overlap_bm25_blend",
    "query_variant_rrf_bm25",
    "query_variant_rrf_field_blend",
    "idf_query_rrf_bm25",
    "idf_query_rrf_field_blend",
    "idf_window_rrf_bm25",
    "idf_window_rrf_field_blend",
)
SOURCE_RETRIEVAL_STRATEGY_IDS = (
    "query_variant_rrf_bm25",
    "query_variant_rrf_field_blend",
    "idf_query_rrf_bm25",
    "idf_query_rrf_field_blend",
    "idf_window_rrf_bm25",
    "idf_window_rrf_field_blend",
)
RRF_RANK_CONSTANT = 60.0
IDF_WINDOW_SIZES = (8, 5, 3)
IDF_WINDOW_TOP_PER_SIZE = 2
STOPWORDS = frozenset(
    {
        "about",
        "all",
        "and",
        "are",
        "based",
        "find",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "of",
        "on",
        "paper",
        "papers",
        "research",
        "that",
        "the",
        "this",
        "to",
        "using",
        "what",
        "which",
        "with",
    }
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-pack", required=True, type=Path)
    parser.add_argument("--score-file", required=True, type=Path)
    parser.add_argument("--candidate-source", type=Path, default=None)
    parser.add_argument("--candidate-search-k", type=int, default=50)
    parser.add_argument("--exclude-raw-query", action="store_true")
    parser.add_argument(
        "--strategy",
        default="",
        help="comma-separated strategy IDs to run; default runs all available strategies",
    )
    parser.add_argument(
        "--task-id",
        default="",
        help="comma-separated task IDs to score; default scores every task in task pack",
    )
    parser.add_argument(
        "--selection-k",
        default=",".join(str(value) for value in DEFAULT_SELECTION_KS),
        help="comma-separated reranked candidate counts to score",
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    payload = diagnose_candidate_rerank(
        task_pack=args.task_pack,
        score_file=args.score_file,
        candidate_source=args.candidate_source,
        candidate_search_k=args.candidate_search_k,
        include_raw_query=not args.exclude_raw_query,
        selection_ks=_parse_selection_ks(args.selection_k),
        selected_strategy_ids=_parse_strategy_ids(args.strategy),
        selected_task_ids=_parse_task_ids(args.task_id),
    )
    rendered = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


def diagnose_candidate_rerank(
    *,
    task_pack: Path,
    score_file: Path,
    candidate_source: Path | None = None,
    candidate_search_k: int = 50,
    include_raw_query: bool = True,
    selection_ks: Iterable[int] = DEFAULT_SELECTION_KS,
    selected_strategy_ids: Iterable[str] | None = None,
    selected_task_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Return aggregate candidate-reranking diagnostics for local gold scoring."""

    if candidate_search_k < 1:
        raise ValueError("candidate_search_k must be positive")
    task_filter_ids = _normalize_task_ids(selected_task_ids)
    tasks = _filter_tasks(
        _load_gold_tasks(task_pack),
        selected_task_ids=task_filter_ids,
    )
    if not tasks:
        raise ValueError("task_pack contains no scoreable AutoResearchBench gold tasks")
    traces = _load_score_traces(score_file)
    source = (
        _build_autoresearchbench_candidate_source(candidate_source)
        if candidate_source is not None
        else None
    )
    available_strategy_ids = STRATEGY_IDS + (
        SOURCE_REQUIRED_STRATEGY_IDS if source is not None else ()
    )
    strategy_ids = _select_strategy_ids(
        available_strategy_ids,
        selected_strategy_ids=selected_strategy_ids,
    )
    strategies: list[dict[str, Any]] = []
    normalized_selection_ks = tuple(
        dict.fromkeys(k for k in selection_ks if isinstance(k, int) and k > 0)
    )
    if not normalized_selection_ks:
        raise ValueError("selection_ks must contain at least one positive integer")

    source_search_cache: dict[tuple[int, str, int, str], tuple[Any, ...]] = {}
    for strategy_id in strategy_ids:
        ranked_by_task = {
            task["task_id"]: _rerank_candidates(
                traces.get(task["task_id"], ()),
                query=task["question"],
                strategy_id=strategy_id,
                candidate_source=source,
                candidate_search_k=candidate_search_k,
                include_raw_query=include_raw_query,
                source_search_cache=source_search_cache,
            )
            for task in tasks
        }
        for selection_k in normalized_selection_ks:
            scores = []
            for task in tasks:
                ranked = ranked_by_task[task["task_id"]][:selection_k]
                if task["task_type"] == "wide":
                    score = _score_wide(
                        task,
                        (str(candidate.get("arxiv_id") or "") for candidate in ranked),
                    )
                else:
                    score = _score_deep(
                        task,
                        (str(candidate.get("title") or "") for candidate in ranked),
                    )
                scores.append(score)
            strategies.append(
                {
                    "strategy_id": strategy_id,
                    "strategy_kind": _strategy_kind(strategy_id),
                    "strategy_dependency_kind": _strategy_dependency_kind(strategy_id),
                    "selection_k": selection_k,
                    "metrics": _aggregate_metrics(scores),
                    "by_type": _aggregate_by_type(scores),
                }
            )

    return {
        "schema_version": SCHEMA_VERSION,
        "task_pack": str(task_pack),
        "score_file": str(score_file),
        "candidate_source": str(candidate_source)
        if candidate_source is not None
        else "",
        "candidate_source_record_count": (
            len(source.records_by_id) if source is not None else 0
        ),
        "candidate_source_compatibility": _candidate_source_compatibility(
            score_file=score_file,
            traces=traces,
            source=source,
            candidate_source=candidate_source,
            task_ids=(str(task["task_id"]) for task in tasks),
        ),
        "candidate_search_k": candidate_search_k if source is not None else 0,
        "include_raw_query": include_raw_query if source is not None else False,
        "score_candidate_top_k": _score_candidate_top_k(score_file),
        "task_count": len(tasks),
        "selected_task_ids": list(task_filter_ids or ()),
        "strategy_count": len(strategies),
        "selected_strategy_ids": list(strategy_ids),
        "strategy_kinds": sorted(
            {str(strategy.get("strategy_kind") or "") for strategy in strategies}
        ),
        "strategy_dependency_kinds": sorted(
            {
                str(strategy.get("strategy_dependency_kind") or "")
                for strategy in strategies
            }
        ),
        "strategies": strategies,
        "gold_detail_emitted": False,
    }


def _load_gold_tasks(task_pack: Path) -> tuple[dict[str, Any], ...]:
    tasks: list[dict[str, Any]] = []
    for gold_path in sorted((task_pack / "tasks").glob("*/gold.json")):
        input_path = gold_path.parent / "input.json"
        if not input_path.exists():
            continue
        visible = json.loads(input_path.read_text(encoding="utf-8"))
        gold = json.loads(gold_path.read_text(encoding="utf-8"))
        tasks.append(
            {
                "task_id": str(visible.get("task_id") or gold_path.parent.name),
                "question": str(
                    visible.get("question")
                    or (visible.get("input") or {}).get("question")
                    or ""
                ),
                "task_type": str(visible.get("task_type") or "deep"),
                "answer_titles": tuple(
                    str(item) for item in gold.get("answer_titles") or ()
                ),
                "answer_arxiv_ids": tuple(
                    str(item) for item in gold.get("answer_arxiv_ids") or ()
                ),
            }
        )
    return tuple(tasks)


def _filter_tasks(
    tasks: tuple[dict[str, Any], ...],
    *,
    selected_task_ids: Iterable[str] | None,
) -> tuple[dict[str, Any], ...]:
    if selected_task_ids is None:
        return tasks
    selected = tuple(dict.fromkeys(str(task_id) for task_id in selected_task_ids))
    selected_set = set(selected)
    filtered = tuple(task for task in tasks if str(task["task_id"]) in selected_set)
    missing = sorted(selected_set - {str(task["task_id"]) for task in filtered})
    if missing:
        raise ValueError(f"task IDs not found in task pack: {missing}")
    return filtered


def _normalize_task_ids(
    selected_task_ids: Iterable[str] | None,
) -> tuple[str, ...] | None:
    if selected_task_ids is None:
        return None
    return tuple(dict.fromkeys(str(task_id) for task_id in selected_task_ids))


def _score_deep(
    task: dict[str, Any],
    candidate_titles: Iterable[str],
) -> dict[str, Any]:
    gold_titles = tuple(title for title in task["answer_titles"] if title)
    predictions = tuple(title for title in candidate_titles if title)
    matched = tuple(
        prediction
        for prediction in predictions
        if any(_titles_match(prediction, gold) for gold in gold_titles)
    )
    accuracy = 1.0 if matched and gold_titles else 0.0
    if not gold_titles and not predictions:
        accuracy = 1.0
    return {
        "task_id": task["task_id"],
        "task_type": task["task_type"],
        "deep_accuracy": accuracy,
        "wide_iou": 0.0,
        "wide_recall": 0.0,
        "wide_precision": 0.0,
        "matched_count": len(matched),
        "predicted_count": len(predictions),
        "gold_count": len(gold_titles),
    }


def _score_wide(
    task: dict[str, Any],
    predicted_arxiv_ids: Iterable[str],
) -> dict[str, Any]:
    gold_ids = {_normalize_arxiv_id(arxiv_id) for arxiv_id in task["answer_arxiv_ids"]}
    pred_ids = {_normalize_arxiv_id(arxiv_id) for arxiv_id in predicted_arxiv_ids}
    gold_ids.discard("")
    pred_ids.discard("")
    intersection = gold_ids & pred_ids
    union = gold_ids | pred_ids
    if not gold_ids and not pred_ids:
        iou = recall = precision = 1.0
    else:
        iou = len(intersection) / len(union) if union else 0.0
        recall = len(intersection) / len(gold_ids) if gold_ids else 0.0
        precision = len(intersection) / len(pred_ids) if pred_ids else 0.0
    return {
        "task_id": task["task_id"],
        "task_type": task["task_type"],
        "deep_accuracy": 0.0,
        "wide_iou": round(iou, 6),
        "wide_recall": round(recall, 6),
        "wide_precision": round(precision, 6),
        "matched_count": len(intersection),
        "predicted_count": len(pred_ids),
        "gold_count": len(gold_ids),
    }


def _load_score_traces(score_file: Path) -> dict[str, tuple[dict[str, Any], ...]]:
    payload = json.loads(score_file.read_text(encoding="utf-8"))
    traces: dict[str, tuple[dict[str, Any], ...]] = {}
    for score in payload.get("scores") or ():
        if not isinstance(score, dict):
            continue
        task_id = str(score.get("task_id") or "")
        candidate_set = (
            (score.get("retrieval_trace") or {}).get("candidate_set")
            if isinstance(score.get("retrieval_trace"), dict)
            else ()
        )
        if task_id:
            traces[task_id] = tuple(
                candidate
                for candidate in candidate_set or ()
                if isinstance(candidate, dict)
            )
    return traces


def _candidate_source_compatibility(
    *,
    score_file: Path,
    traces: dict[str, tuple[dict[str, Any], ...]],
    source: Any | None,
    candidate_source: Path | None,
    task_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    if source is None or candidate_source is None:
        return {"checked": False, "warnings": []}

    payload = json.loads(score_file.read_text(encoding="utf-8"))
    metadata = (
        payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    )
    task_filter = set(task_ids) if task_ids is not None else None
    score_data_root = str(metadata.get("data_root") or "")
    data_root_matches = (
        _data_root_matches_candidate_source(
            score_data_root,
            candidate_source=candidate_source,
            score_file=score_file,
        )
        if score_data_root
        else None
    )
    warnings = []
    if data_root_matches is False:
        warnings.append("score_report_data_root_mismatch")

    trace_baseline_ids: set[str] = set()
    trace_schema_versions: set[str] = set()
    candidate_source_schema_versions: set[str] = set()
    missing_trace_count = 0
    incomplete_trace_count = 0
    score_task_ids: set[str] = set()
    for score in payload.get("scores") or ():
        if not isinstance(score, dict):
            continue
        task_id = str(score.get("task_id") or "")
        if task_id:
            score_task_ids.add(task_id)
        if task_filter is not None and task_id not in task_filter:
            continue
        trace = score.get("retrieval_trace")
        if not isinstance(trace, dict):
            missing_trace_count += 1
            continue
        trace_baseline_id = _known_string(trace.get("baseline_id"))
        if trace_baseline_id is not None:
            trace_baseline_ids.add(trace_baseline_id)
        trace_schema_version = _known_string(trace.get("schema_version"))
        if trace_schema_version is not None:
            trace_schema_versions.add(trace_schema_version)
        candidate_source_schema_version = _known_string(
            trace.get("candidate_source_schema_version")
        )
        if candidate_source_schema_version is not None:
            candidate_source_schema_versions.add(candidate_source_schema_version)
        if (
            "retrieval_trace_complete" in trace
            and trace.get("retrieval_trace_complete") is not True
        ):
            incomplete_trace_count += 1

    expected_candidate_source_schema = str(
        (source.manifest or {}).get("schema_version") or ""
    )
    if trace_baseline_ids and trace_baseline_ids != {EXPECTED_TRACE_BASELINE_ID}:
        warnings.append("unexpected_trace_baseline")
    if trace_schema_versions and trace_schema_versions != {
        EXPECTED_TRACE_SCHEMA_VERSION
    }:
        warnings.append("unexpected_trace_schema")
    if candidate_source_schema_versions and candidate_source_schema_versions != {
        expected_candidate_source_schema
    }:
        warnings.append("candidate_source_schema_mismatch")
    missing_score_task_ids = sorted(task_filter - score_task_ids) if task_filter else []
    if missing_score_task_ids:
        warnings.append("missing_score_entry")
    if missing_trace_count:
        warnings.append("missing_retrieval_trace")
    if incomplete_trace_count:
        warnings.append("incomplete_retrieval_trace")

    trace_candidate_ids = {
        str(candidate.get("candidate_id") or "")
        for task_id, candidates in traces.items()
        if task_filter is None or task_id in task_filter
        for candidate in candidates
        if isinstance(candidate, dict) and str(candidate.get("candidate_id") or "")
    }
    missing_source_record_count = sum(
        1
        for candidate_id in trace_candidate_ids
        if candidate_id not in source.records_by_id
    )
    if missing_source_record_count:
        warnings.append("trace_candidate_ids_missing_from_candidate_source")

    return {
        "checked": True,
        "warnings": sorted(set(warnings)),
        "score_report_data_root": score_data_root,
        "candidate_source": str(candidate_source),
        "data_root_matches": data_root_matches,
        "trace_baseline_ids": sorted(trace_baseline_ids),
        "trace_schema_versions": sorted(trace_schema_versions),
        "expected_trace_schema_version": EXPECTED_TRACE_SCHEMA_VERSION,
        "expected_trace_baseline_id": EXPECTED_TRACE_BASELINE_ID,
        "candidate_source_schema_versions": sorted(candidate_source_schema_versions),
        "expected_candidate_source_schema_version": expected_candidate_source_schema,
        "missing_score_count": len(missing_score_task_ids),
        "missing_score_task_ids": missing_score_task_ids,
        "missing_trace_count": missing_trace_count,
        "incomplete_trace_count": incomplete_trace_count,
        "trace_candidate_id_count": len(trace_candidate_ids),
        "missing_source_record_count": missing_source_record_count,
    }


def _known_string(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _data_root_matches_candidate_source(
    score_data_root: str,
    *,
    candidate_source: Path,
    score_file: Path,
) -> bool:
    report_path = Path(score_data_root).expanduser()
    candidate_source_resolved = candidate_source.expanduser().resolve()
    if report_path.is_absolute():
        return report_path.resolve() == candidate_source_resolved
    return any(
        (base / report_path).resolve() == candidate_source_resolved
        for base in (REPO_ROOT, score_file.parent)
    )


def _rerank_candidates(
    candidates: tuple[dict[str, Any], ...],
    *,
    query: str,
    strategy_id: str,
    candidate_source: Any | None = None,
    candidate_search_k: int = 50,
    include_raw_query: bool = True,
    source_search_cache: dict[tuple[int, str, int, str], tuple[Any, ...]] | None = None,
) -> tuple[dict[str, Any], ...]:
    if strategy_id == "bm25_order":
        return tuple(sorted(candidates, key=_original_rank_key))
    if strategy_id == "title_token_overlap":
        return tuple(
            sorted(
                candidates,
                key=lambda candidate: (
                    -_title_overlap(query, candidate),
                    *_original_rank_key(candidate),
                ),
            )
        )
    if strategy_id == "title_overlap_bm25_blend":
        return tuple(
            sorted(
                candidates,
                key=lambda candidate: (
                    -_title_overlap_bm25_blend(query, candidate),
                    *_original_rank_key(candidate),
                ),
            )
        )
    if strategy_id == "arxiv_first_bm25":
        return tuple(
            sorted(
                candidates,
                key=lambda candidate: (
                    0 if str(candidate.get("arxiv_id") or "").strip() else 1,
                    *_original_rank_key(candidate),
                ),
            )
        )
    if strategy_id == "metadata_field_overlap_bm25_blend":
        if candidate_source is None:
            return ()
        return tuple(
            sorted(
                _enrich_trace_candidates(candidates, candidate_source),
                key=lambda candidate: (
                    -_metadata_field_overlap_bm25_blend(query, candidate),
                    *_original_rank_key(candidate),
                ),
            )
        )
    if strategy_id == "query_variant_rrf_bm25":
        if candidate_source is None:
            return ()
        return _query_variant_rrf_candidates(
            candidate_source,
            query=query,
            top_k=candidate_search_k,
            include_raw_query=include_raw_query,
            field_blend=False,
            variant_mode="keyword",
            search_cache=source_search_cache,
        )
    if strategy_id == "query_variant_rrf_field_blend":
        if candidate_source is None:
            return ()
        return _query_variant_rrf_candidates(
            candidate_source,
            query=query,
            top_k=candidate_search_k,
            include_raw_query=include_raw_query,
            field_blend=True,
            variant_mode="keyword",
            search_cache=source_search_cache,
        )
    if strategy_id == "idf_query_rrf_bm25":
        if candidate_source is None:
            return ()
        return _query_variant_rrf_candidates(
            candidate_source,
            query=query,
            top_k=candidate_search_k,
            include_raw_query=include_raw_query,
            field_blend=False,
            variant_mode="idf",
            search_cache=source_search_cache,
        )
    if strategy_id == "idf_query_rrf_field_blend":
        if candidate_source is None:
            return ()
        return _query_variant_rrf_candidates(
            candidate_source,
            query=query,
            top_k=candidate_search_k,
            include_raw_query=include_raw_query,
            field_blend=True,
            variant_mode="idf",
            search_cache=source_search_cache,
        )
    if strategy_id == "idf_window_rrf_bm25":
        if candidate_source is None:
            return ()
        return _query_variant_rrf_candidates(
            candidate_source,
            query=query,
            top_k=candidate_search_k,
            include_raw_query=include_raw_query,
            field_blend=False,
            variant_mode="idf_window",
            search_cache=source_search_cache,
        )
    if strategy_id == "idf_window_rrf_field_blend":
        if candidate_source is None:
            return ()
        return _query_variant_rrf_candidates(
            candidate_source,
            query=query,
            top_k=candidate_search_k,
            include_raw_query=include_raw_query,
            field_blend=True,
            variant_mode="idf_window",
            search_cache=source_search_cache,
        )
    raise ValueError(f"unsupported rerank strategy: {strategy_id}")


def _strategy_kind(strategy_id: str) -> str:
    if strategy_id in SOURCE_RETRIEVAL_STRATEGY_IDS:
        return "source_retrieval"
    return "trace_rerank"


def _strategy_dependency_kind(strategy_id: str) -> str:
    if strategy_id in SOURCE_RETRIEVAL_STRATEGY_IDS:
        return "source_retrieval"
    if strategy_id == "metadata_field_overlap_bm25_blend":
        return "source_augmented_trace_rerank"
    return "trace_only_rerank"


def _title_overlap(query: str, candidate: dict[str, Any]) -> float:
    query_tokens = set(_tokens(query))
    title_tokens = set(_tokens(str(candidate.get("title") or "")))
    if not query_tokens or not title_tokens:
        return 0.0
    return len(query_tokens & title_tokens) / len(query_tokens | title_tokens)


def _title_overlap_bm25_blend(query: str, candidate: dict[str, Any]) -> float:
    score = float(candidate.get("score") or 0.0)
    return (_title_overlap(query, candidate) * 3.0) + (score / (score + 1.0))


def _metadata_field_overlap_bm25_blend(query: str, candidate: dict[str, Any]) -> float:
    score = float(candidate.get("score") or 0.0)
    return (
        (_field_overlap(query, str(candidate.get("title") or "")) * 3.0)
        + (_field_overlap(query, str(candidate.get("abstract") or "")) * 1.5)
        + (score / (score + 1.0))
    )


def _enrich_trace_candidates(
    candidates: tuple[dict[str, Any], ...],
    candidate_source: Any,
) -> tuple[dict[str, Any], ...]:
    enriched: list[dict[str, Any]] = []
    for candidate in candidates:
        candidate_id = str(candidate.get("candidate_id") or "")
        source_record = candidate_source.records_by_id.get(candidate_id, {})
        enriched.append(
            {
                **source_record,
                **candidate,
                "abstract": str(
                    candidate.get("abstract") or source_record.get("abstract") or ""
                ),
                "doi": str(candidate.get("doi") or source_record.get("doi") or ""),
            }
        )
    return tuple(enriched)


def _query_variant_rrf_candidates(
    candidate_source: Any,
    *,
    query: str,
    top_k: int,
    include_raw_query: bool,
    field_blend: bool,
    variant_mode: str,
    search_cache: dict[tuple[int, str, int, str], tuple[Any, ...]] | None = None,
) -> tuple[dict[str, Any], ...]:
    variants = _query_variants(
        query,
        candidate_source=candidate_source,
        include_raw=include_raw_query,
        variant_mode=variant_mode,
    )
    fused: dict[str, dict[str, Any]] = {}
    for variant in variants:
        variant_query = str(variant.get("query") or "").strip()
        if not variant_query:
            continue
        for rank, result in enumerate(
            _cached_candidate_source_search(
                candidate_source,
                query=variant_query,
                top_k=top_k,
                search_cache=search_cache,
            ),
            1,
        ):
            record = candidate_source.records_by_id.get(result.doc_id)
            if not record:
                continue
            accumulator = fused.setdefault(
                result.doc_id,
                {
                    "record": record,
                    "rrf_score": 0.0,
                    "best_bm25": 0.0,
                    "best_rank": rank,
                    "variant_hit_count": 0,
                },
            )
            accumulator["rrf_score"] += 1.0 / (RRF_RANK_CONSTANT + rank)
            accumulator["best_bm25"] = max(
                float(accumulator["best_bm25"]),
                float(result.score),
            )
            accumulator["best_rank"] = min(int(accumulator["best_rank"]), rank)
            accumulator["variant_hit_count"] = int(accumulator["variant_hit_count"]) + 1

    def sort_key(item: tuple[str, dict[str, Any]]) -> tuple[float, float, int, str]:
        candidate_id, accumulator = item
        score = float(accumulator["rrf_score"])
        if field_blend:
            score += _metadata_field_overlap_score(
                query,
                accumulator["record"],
            )
        return (
            -score,
            -float(accumulator["best_bm25"]),
            int(accumulator["best_rank"]),
            candidate_id,
        )

    ranked = []
    source_name = (
        f"autoresearchbench_candidate_{variant_mode}_rrf_field_blend.candidate_corpus"
        if field_blend
        else f"autoresearchbench_candidate_{variant_mode}_rrf_bm25.candidate_corpus"
    )
    for rank, (candidate_id, accumulator) in enumerate(
        sorted(fused.items(), key=sort_key),
        1,
    ):
        record = accumulator["record"]
        rrf_score = float(accumulator["rrf_score"])
        field_score = (
            _metadata_field_overlap_score(query, record) if field_blend else 0.0
        )
        ranked.append(
            {
                **record,
                "candidate_id": candidate_id,
                "rank": rank,
                "score": round(rrf_score + field_score, 8),
                "source": source_name,
                "rrf_score": round(rrf_score, 8),
                "variant_hit_count": int(accumulator["variant_hit_count"]),
            }
        )
    return tuple(ranked)


def _cached_candidate_source_search(
    candidate_source: Any,
    *,
    query: str,
    top_k: int,
    search_cache: dict[tuple[int, str, int, str], tuple[Any, ...]] | None,
) -> tuple[Any, ...]:
    cache_key = (id(candidate_source.index), "bm25", top_k, query)
    if search_cache is None:
        return tuple(candidate_source.index.search(query, k=top_k, scoring="bm25"))
    if cache_key not in search_cache:
        search_cache[cache_key] = tuple(
            candidate_source.index.search(query, k=top_k, scoring="bm25")
        )
    return search_cache[cache_key]


def _query_variants(
    query: str,
    *,
    candidate_source: Any,
    include_raw: bool,
    variant_mode: str,
) -> tuple[dict[str, str], ...]:
    if variant_mode == "keyword":
        variants = task_query_variants(query, include_raw=include_raw)
        if not include_raw:
            variants = [
                variant
                for variant in variants
                if not str(variant.get("variant_id") or "").startswith("raw_visible")
            ]
    elif variant_mode == "idf":
        variants = _idf_query_variants(
            query,
            candidate_source=candidate_source,
            include_raw=include_raw,
        )
    elif variant_mode == "idf_window":
        variants = _idf_window_query_variants(
            query,
            candidate_source=candidate_source,
            include_raw=include_raw,
        )
    else:
        raise ValueError(f"unsupported query variant mode: {variant_mode}")
    if not variants and include_raw:
        variants = [{"variant_id": "raw_visible_fallback", "query": query.strip()}]
    return tuple(
        variant
        for variant in variants
        if isinstance(variant, dict) and str(variant.get("query") or "").strip()
    )


def _idf_query_variants(
    query: str,
    *,
    candidate_source: Any,
    include_raw: bool,
) -> list[dict[str, str]]:
    scored_tokens = _idf_scored_unique_tokens(query, candidate_source)

    variants: list[dict[str, str]] = []
    if include_raw:
        variants.append({"variant_id": "raw_visible", "query": query.strip()})
    rarest = sorted(scored_tokens, key=lambda item: (-item[1], item[2]))
    for size in (16, 12, 8, 5, 3):
        selected = sorted(rarest[:size], key=lambda item: item[2])
        variant_query = " ".join(token for token, _idf, _position in selected)
        if variant_query:
            variants.append(
                {
                    "variant_id": f"idf_keywords{size}",
                    "query": variant_query,
                }
            )
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for variant in variants:
        normalized = " ".join(str(variant.get("query") or "").split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(
            {
                "variant_id": str(variant.get("variant_id") or "idf_query"),
                "query": normalized,
            }
        )
    return deduped


def _idf_window_query_variants(
    query: str,
    *,
    candidate_source: Any,
    include_raw: bool,
) -> list[dict[str, str]]:
    scored_tokens = _idf_scored_ordered_tokens(query, candidate_source)
    variants: list[dict[str, str]] = []
    if include_raw:
        variants.append({"variant_id": "raw_visible", "query": query.strip()})

    for size in IDF_WINDOW_SIZES:
        windows: list[tuple[float, int, str]] = []
        if len(scored_tokens) < size:
            continue
        for start in range(0, len(scored_tokens) - size + 1):
            window = scored_tokens[start : start + size]
            score = sum(idf for _token, idf, _position in window)
            query_text = " ".join(token for token, _idf, _position in window)
            windows.append((score, start, query_text))
        for _score, start, query_text in sorted(
            windows,
            key=lambda item: (-item[0], item[1]),
        )[:IDF_WINDOW_TOP_PER_SIZE]:
            variants.append(
                {
                    "variant_id": f"idf_window{size}_{start}",
                    "query": query_text,
                }
            )

    return _dedupe_query_variants(variants)


def _idf_scored_unique_tokens(
    query: str,
    candidate_source: Any,
) -> list[tuple[str, float, int]]:
    tokens = list(dict.fromkeys(_tokens(query)))
    return _idf_score_tokens(tokens, candidate_source)


def _idf_scored_ordered_tokens(
    query: str,
    candidate_source: Any,
) -> list[tuple[str, float, int]]:
    return _idf_score_tokens(list(_tokens(query)), candidate_source)


def _idf_score_tokens(
    tokens: list[str],
    candidate_source: Any,
) -> list[tuple[str, float, int]]:
    scored_tokens: list[tuple[str, float, int]] = []
    for position, token in enumerate(tokens):
        document_frequency = len(candidate_source.index.postings.get(token, {}))
        if document_frequency <= 0:
            continue
        idf = (candidate_source.index.doc_count - document_frequency + 0.5) / (
            document_frequency + 0.5
        )
        scored_tokens.append((token, idf, position))
    return scored_tokens


def _dedupe_query_variants(
    variants: Iterable[dict[str, str]],
) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for variant in variants:
        normalized = " ".join(str(variant.get("query") or "").split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(
            {
                "variant_id": str(variant.get("variant_id") or "query_variant"),
                "query": normalized,
            }
        )
    return deduped


def _metadata_field_overlap_score(query: str, candidate: dict[str, Any]) -> float:
    return (
        _field_overlap(query, str(candidate.get("title") or "")) * 0.03
        + _field_overlap(query, str(candidate.get("abstract") or "")) * 0.015
    )


def _field_overlap(query: str, text: str) -> float:
    query_tokens = set(_tokens(query))
    field_tokens = set(_tokens(text))
    if not query_tokens or not field_tokens:
        return 0.0
    return len(query_tokens & field_tokens) / len(query_tokens)


def _original_rank_key(candidate: dict[str, Any]) -> tuple[int, float, str]:
    rank = int(candidate.get("rank") or 0)
    score = float(candidate.get("score") or 0.0)
    candidate_id = str(candidate.get("candidate_id") or "")
    return (rank if rank > 0 else 1_000_000, -score, candidate_id)


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(
        token for token in TOKEN_RE.findall(text.lower()) if token not in STOPWORDS
    )


def _titles_match(candidate: str, gold: str) -> bool:
    return _normalize_title(candidate) == _normalize_title(gold)


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", title.lower())).strip()


def _normalize_arxiv_id(arxiv_id: Any) -> str:
    cleaned = re.sub(r"(?i)arxiv:", "", str(arxiv_id)).strip()
    match = re.search(r"(\d{4}\.\d{4,5})", cleaned)
    return match.group(1) if match else cleaned


def _aggregate_metrics(scores: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "score_count": len(scores),
        "mean_deep_accuracy": _mean(scores, "deep_accuracy"),
        "mean_wide_iou": _mean(scores, "wide_iou"),
        "mean_wide_precision": _mean(scores, "wide_precision"),
        "mean_wide_recall": _mean(scores, "wide_recall"),
    }


def _aggregate_by_type(scores: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_type: dict[str, dict[str, Any]] = {
        "deep": _empty_type_counts(),
        "wide": _empty_type_counts(),
        "unknown": _empty_type_counts(),
    }
    for score in scores:
        task_type = str(score.get("task_type") or "unknown")
        counts = by_type[task_type if task_type in by_type else "unknown"]
        counts["task_count"] += 1
        counts["positive_task_count"] += int(
            float(score.get("deep_accuracy") or 0.0) > 0.0
            or float(score.get("wide_iou") or 0.0) > 0.0
        )
        counts["mean_deep_accuracy"] = 0.0
        counts["mean_wide_iou"] = 0.0
        counts["mean_wide_precision"] = 0.0
        counts["mean_wide_recall"] = 0.0

    for task_type, counts in by_type.items():
        typed_scores = [
            score
            for score in scores
            if str(score.get("task_type") or "unknown") == task_type
        ]
        counts["mean_deep_accuracy"] = _mean(typed_scores, "deep_accuracy")
        counts["mean_wide_iou"] = _mean(typed_scores, "wide_iou")
        counts["mean_wide_precision"] = _mean(typed_scores, "wide_precision")
        counts["mean_wide_recall"] = _mean(typed_scores, "wide_recall")
    return by_type


def _empty_type_counts() -> dict[str, Any]:
    return {
        "task_count": 0,
        "positive_task_count": 0,
        "mean_deep_accuracy": 0.0,
        "mean_wide_iou": 0.0,
        "mean_wide_precision": 0.0,
        "mean_wide_recall": 0.0,
    }


def _mean(scores: Iterable[dict[str, Any]], metric_name: str) -> float:
    values = [
        float(score.get(metric_name) or 0.0)
        for score in scores
        if isinstance(score, dict)
    ]
    return round(sum(values) / len(values), 6) if values else 0.0


def _score_candidate_top_k(score_file: Path) -> int:
    payload = json.loads(score_file.read_text(encoding="utf-8"))
    return int((payload.get("metadata") or {}).get("candidate_top_k") or 0)


def _parse_selection_ks(value: str) -> tuple[int, ...]:
    selection_ks = tuple(int(part.strip()) for part in value.split(",") if part.strip())
    if not selection_ks or any(item < 1 for item in selection_ks):
        raise ValueError("--selection-k must contain positive integers")
    return selection_ks


def _parse_strategy_ids(value: str) -> tuple[str, ...] | None:
    strategy_ids = tuple(part.strip() for part in value.split(",") if part.strip())
    return strategy_ids or None


def _parse_task_ids(value: str) -> tuple[str, ...] | None:
    task_ids = tuple(part.strip() for part in value.split(",") if part.strip())
    return task_ids or None


def _select_strategy_ids(
    available_strategy_ids: Iterable[str],
    *,
    selected_strategy_ids: Iterable[str] | None,
) -> tuple[str, ...]:
    available = tuple(available_strategy_ids)
    if selected_strategy_ids is None:
        return available
    selected = tuple(dict.fromkeys(selected_strategy_ids))
    unsupported = sorted(set(selected) - set(available))
    if unsupported:
        raise ValueError(f"unsupported strategy IDs: {unsupported}")
    return tuple(strategy_id for strategy_id in available if strategy_id in selected)


if __name__ == "__main__":
    raise SystemExit(main())
