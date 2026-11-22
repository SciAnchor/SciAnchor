#!/usr/bin/env python3
"""Diagnose AutoResearchBench candidate-source coverage without printing gold.

The script reads a local task pack with ``gold.json`` files and a separate
non-gold candidate-source root. It reports aggregate coverage and top-k hit
counts only; answer titles and answer arXiv ids are never emitted.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO_ROOT / "packages" / "research_harness"
sys.path.insert(0, str(PACKAGE_ROOT))

from research_harness.eval.researchflowbench.baseline import (  # noqa: E402
    _build_autoresearchbench_candidate_source,
)


SCHEMA_VERSION = "researchflowbench.autoresearchbench_candidate_coverage.v0.1"
TITLE_TOKEN_RE = re.compile(r"[^a-z0-9]+")
ARXIV_ID_RE = re.compile(r"(?i)(\d{4}\.\d{4,5})(?:v\d+)?")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task-pack", required=True, type=Path)
    parser.add_argument("--candidate-source", required=True, type=Path)
    parser.add_argument("--score-file", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    payload = diagnose_candidate_coverage(
        task_pack=args.task_pack,
        candidate_source=args.candidate_source,
        score_file=args.score_file,
    )
    rendered = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


def diagnose_candidate_coverage(
    *,
    task_pack: Path,
    candidate_source: Path,
    score_file: Path | None = None,
) -> dict[str, Any]:
    """Return aggregate coverage/ranking diagnostics for local gold scoring."""

    tasks = _load_gold_tasks(task_pack)
    source_payload = _load_candidate_source_sets(candidate_source)
    predictions = _load_score_predictions(score_file) if score_file is not None else {}
    by_type = {
        "deep": _empty_type_counts(),
        "wide": _empty_type_counts(),
        "unknown": _empty_type_counts(),
    }
    for task in tasks:
        task_type = task["task_type"] if task["task_type"] in by_type else "unknown"
        counts = by_type[task_type]
        title_covered = bool(task["answer_titles"] & source_payload["titles"])
        arxiv_covered = bool(task["answer_arxiv_ids"] & source_payload["arxiv_ids"])
        prediction = predictions.get(task["task_id"], {})
        title_top = bool(task["answer_titles"] & set(prediction.get("titles", ())))
        arxiv_top = bool(
            task["answer_arxiv_ids"] & set(prediction.get("arxiv_ids", ()))
        )
        counts["task_count"] += 1
        counts["title_covered_task_count"] += int(title_covered)
        counts["arxiv_covered_task_count"] += int(arxiv_covered)
        counts["any_covered_task_count"] += int(title_covered or arxiv_covered)
        counts["title_top_hit_task_count"] += int(title_top)
        counts["arxiv_top_hit_task_count"] += int(arxiv_top)
        counts["any_top_hit_task_count"] += int(title_top or arxiv_top)
        counts["covered_but_not_top_task_count"] += int(
            (title_covered or arxiv_covered) and not (title_top or arxiv_top)
        )

    task_count = len(tasks)
    return {
        "schema_version": SCHEMA_VERSION,
        "task_pack": str(task_pack),
        "candidate_source": str(candidate_source),
        "score_file": str(score_file) if score_file is not None else "",
        "task_count": task_count,
        "candidate_source_record_count": source_payload["record_count"],
        "candidate_source_records_with_arxiv": source_payload["records_with_arxiv"],
        "candidate_source_unique_arxiv_ids": len(source_payload["arxiv_ids"]),
        "score_candidate_top_k": _score_candidate_top_k(score_file),
        "by_type": by_type,
        "gold_detail_emitted": False,
    }


def _empty_type_counts() -> dict[str, int]:
    return {
        "task_count": 0,
        "title_covered_task_count": 0,
        "arxiv_covered_task_count": 0,
        "any_covered_task_count": 0,
        "title_top_hit_task_count": 0,
        "arxiv_top_hit_task_count": 0,
        "any_top_hit_task_count": 0,
        "covered_but_not_top_task_count": 0,
    }


def _load_gold_tasks(task_pack: Path) -> list[dict[str, Any]]:
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
                "task_type": str(visible.get("task_type") or "unknown"),
                "answer_titles": {
                    normalized
                    for item in gold.get("answer_titles") or ()
                    if (normalized := _normalize_title(str(item)))
                },
                "answer_arxiv_ids": {
                    normalized
                    for item in gold.get("answer_arxiv_ids") or ()
                    if (normalized := _normalize_arxiv_id(str(item)))
                },
            }
        )
    return tasks


def _load_candidate_source_sets(candidate_source: Path) -> dict[str, Any]:
    source = _build_autoresearchbench_candidate_source(candidate_source)
    titles: set[str] = set()
    arxiv_ids: set[str] = set()
    records_with_arxiv = 0
    for record in source.records_by_id.values():
        title = _normalize_title(record.get("title") or "")
        arxiv_id = _normalize_arxiv_id(record.get("arxiv_id") or "")
        if title:
            titles.add(title)
        if arxiv_id:
            arxiv_ids.add(arxiv_id)
            records_with_arxiv += 1
    return {
        "record_count": len(source.records_by_id),
        "records_with_arxiv": records_with_arxiv,
        "titles": titles,
        "arxiv_ids": arxiv_ids,
    }


def _load_score_predictions(score_file: Path) -> dict[str, dict[str, tuple[str, ...]]]:
    payload = json.loads(score_file.read_text(encoding="utf-8"))
    predictions: dict[str, dict[str, tuple[str, ...]]] = {}
    for score in payload.get("scores") or ():
        if not isinstance(score, dict):
            continue
        task_id = str(score.get("task_id") or "")
        if not task_id:
            continue
        predictions[task_id] = {
            "titles": tuple(
                normalized
                for item in score.get("predicted_titles") or ()
                if (normalized := _normalize_title(str(item)))
            ),
            "arxiv_ids": tuple(
                normalized
                for item in score.get("predicted_arxiv_ids") or ()
                if (normalized := _normalize_arxiv_id(str(item)))
            ),
        }
    return predictions


def _score_candidate_top_k(score_file: Path | None) -> int:
    if score_file is None:
        return 0
    payload = json.loads(score_file.read_text(encoding="utf-8"))
    return int((payload.get("metadata") or {}).get("candidate_top_k") or 0)


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", TITLE_TOKEN_RE.sub(" ", title.lower())).strip()


def _normalize_arxiv_id(arxiv_id: str) -> str:
    cleaned = re.sub(r"(?i)arxiv:", "", arxiv_id).strip()
    match = ARXIV_ID_RE.search(cleaned)
    return match.group(1) if match else cleaned.lower()


if __name__ == "__main__":
    raise SystemExit(main())
