"""AutoResearchBench adapter for ResearchFlowBench.

The adapter consumes a local plaintext JSONL export produced from the official
AutoResearchBench release bundle. It does not decrypt, download, or vendor
benchmark data.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .contract import (
    EXTERNAL_TASK_SCHEMA_VERSION,
    GOLD_STORAGE_LOCAL_ONLY,
    LEAKAGE_POLICY_V0,
    SCORE_REPORT_SCHEMA_VERSION,
    SPLIT_MUTATE_DEV,
    ResearchFlowBenchArchiveLinkage,
    ResearchFlowBenchLicenseContract,
)
from .external_adapter import (
    first_list,
    first_text,
    iter_records,
    normalize_id,
    write_json,
)


ADAPTER_CONTRACT = "researchflowbench.adapters.autoresearchbench.v0.1"
BENCHMARK_ID = "autoresearchbench"
RH_AXES = (
    "deep_research.discovery_accuracy",
    "literature.set_completion",
    "retrieval.provenance_coverage",
)
METRICS = ("deep_accuracy", "wide_iou")
LICENSE_CONTRACT = ResearchFlowBenchLicenseContract(
    dataset_license="apache-2.0",
    data_source_url="https://huggingface.co/datasets/Lk123/AutoResearchBench",
    redistribution_policy=(
        "official plaintext export must stay local; no decrypted benchmark data is vendored"
    ),
    gold_storage_policy=GOLD_STORAGE_LOCAL_ONLY,
)


@dataclass(frozen=True)
class AutoResearchBenchTask:
    task_id: str
    question: str
    task_type: str
    answer_titles: tuple[str, ...] = ()
    answer_arxiv_ids: tuple[str, ...] = ()
    split: str = SPLIT_MUTATE_DEV
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, *, include_gold: bool = True) -> dict:
        linkage = ResearchFlowBenchArchiveLinkage(
            benchmark_id=BENCHMARK_ID,
            task_id=self.task_id,
            split=self.split,
            rh_axis_ids=RH_AXES,
        )
        payload = {
            "schema_version": EXTERNAL_TASK_SCHEMA_VERSION,
            "adapter_contract": ADAPTER_CONTRACT,
            "benchmark_id": BENCHMARK_ID,
            "task_id": self.task_id,
            "split": self.split,
            "question": self.question,
            "input": {"question": self.question, "task_type": self.task_type},
            "task_type": self.task_type,
            "expected_rh_axes": list(RH_AXES),
            "artifact_policy": {
                "gold_visible": include_gold,
                "gold_storage_policy": LICENSE_CONTRACT.gold_storage_policy,
                "third_party_data_vendored": False,
            },
            "license": LICENSE_CONTRACT.to_dict(),
            "leakage_policy": dict(LEAKAGE_POLICY_V0),
            "archive_linkage": linkage.to_dict(),
            "metadata": dict(self.metadata),
        }
        if include_gold:
            payload["answer_titles"] = list(self.answer_titles)
            payload["answer_arxiv_ids"] = list(self.answer_arxiv_ids)
        return payload


@dataclass(frozen=True)
class AutoResearchBenchScore:
    task_id: str
    task_type: str
    deep_accuracy: float = 0.0
    wide_iou: float = 0.0
    wide_recall: float = 0.0
    wide_precision: float = 0.0
    matched_titles: tuple[str, ...] = ()
    matched_arxiv_ids: tuple[str, ...] = ()
    predicted_count: int = 0
    gold_count: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


class AutoResearchBenchAdapter:
    """Convert AutoResearchBench records into RH external tasks."""

    benchmark_id = BENCHMARK_ID
    adapter_contract = ADAPTER_CONTRACT

    def __init__(self, tasks: Iterable[AutoResearchBenchTask]) -> None:
        self._tasks = tuple(tasks)

    @classmethod
    def from_records(
        cls,
        records: Iterable[dict[str, Any]],
        *,
        max_tasks: int | None = None,
    ) -> "AutoResearchBenchAdapter":
        tasks = tuple(
            _task_from_record(record, index) for index, record in enumerate(records)
        )
        if max_tasks is not None:
            tasks = tasks[:max_tasks]
        return cls(tasks)

    @classmethod
    def from_directory(
        cls,
        root: str | Path,
        *,
        max_tasks: int | None = None,
    ) -> "AutoResearchBenchAdapter":
        return cls.from_records(iter_records(root), max_tasks=max_tasks)

    @property
    def task_count(self) -> int:
        return len(self._tasks)

    def tasks(self) -> tuple[AutoResearchBenchTask, ...]:
        return self._tasks

    def manifest(self) -> dict:
        type_counts = {
            task_type: sum(1 for task in self._tasks if task.task_type == task_type)
            for task_type in sorted({task.task_type for task in self._tasks})
        }
        return {
            "schema_version": "researchflowbench.external_adapter_manifest.v0.1",
            "adapter_contract": self.adapter_contract,
            "benchmark_id": self.benchmark_id,
            "task_count": self.task_count,
            "task_type_counts": type_counts,
            "metrics": METRICS,
            "rh_axes": RH_AXES,
            "license": LICENSE_CONTRACT.to_dict(),
            "gold_storage_policy": LICENSE_CONTRACT.gold_storage_policy,
            "score_report_schema_version": SCORE_REPORT_SCHEMA_VERSION,
            "data_policy": (
                "local official AutoResearchBench plaintext export only; no "
                "vendored decrypted data"
            ),
        }

    def write_task_pack(
        self,
        output_dir: str | Path,
        *,
        include_gold: bool = False,
    ) -> dict:
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        tasks_dir = out / "tasks"
        tasks_dir.mkdir(exist_ok=True)

        tasks = self.tasks()
        for task in tasks:
            task_dir = tasks_dir / task.task_id
            task_dir.mkdir(exist_ok=True)
            write_json(task_dir / "input.json", task.to_dict(include_gold=False))
            if include_gold:
                write_json(
                    task_dir / "gold.json",
                    {
                        "schema_version": "researchflowbench.external_gold.v0.1",
                        "task_id": task.task_id,
                        "task_type": task.task_type,
                        "answer_titles": list(task.answer_titles),
                        "answer_arxiv_ids": list(task.answer_arxiv_ids),
                    },
                )

        manifest = self.manifest() | {
            "task_ids": [task.task_id for task in tasks],
            "gold_written": include_gold,
        }
        write_json(out / "adapter_manifest.json", manifest)
        return manifest

    @staticmethod
    def score_deep(
        task: AutoResearchBenchTask,
        candidate_titles: Iterable[str],
    ) -> AutoResearchBenchScore:
        gold_titles = tuple(title for title in task.answer_titles if title)
        predictions = tuple(title for title in candidate_titles if title)
        matched = tuple(
            prediction
            for prediction in predictions
            if any(_titles_match(prediction, gold) for gold in gold_titles)
        )
        accuracy = 1.0 if matched and gold_titles else 0.0
        if not gold_titles and not predictions:
            accuracy = 1.0
        return AutoResearchBenchScore(
            task_id=task.task_id,
            task_type=task.task_type,
            deep_accuracy=accuracy,
            matched_titles=matched,
            predicted_count=len(predictions),
            gold_count=len(gold_titles),
        )

    @staticmethod
    def score_wide(
        task: AutoResearchBenchTask,
        predicted_arxiv_ids: Iterable[str],
    ) -> AutoResearchBenchScore:
        gold_ids = {_normalize_arxiv_id(arxiv_id) for arxiv_id in task.answer_arxiv_ids}
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
        return AutoResearchBenchScore(
            task_id=task.task_id,
            task_type=task.task_type,
            wide_iou=round(iou, 6),
            wide_recall=round(recall, 6),
            wide_precision=round(precision, 6),
            matched_arxiv_ids=tuple(sorted(intersection)),
            predicted_count=len(pred_ids),
            gold_count=len(gold_ids),
        )

    @staticmethod
    def score_report(
        scores: Iterable[AutoResearchBenchScore],
        *,
        split: str = SPLIT_MUTATE_DEV,
        artifact_refs: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        score_payloads = []
        for score in scores:
            payload = score.to_dict()
            payload["split"] = split
            payload["metrics"] = {
                "deep_accuracy": payload["deep_accuracy"],
                "wide_iou": payload["wide_iou"],
                "wide_recall": payload["wide_recall"],
                "wide_precision": payload["wide_precision"],
            }
            payload["rh_axis_ids"] = list(RH_AXES)
            score_payloads.append(payload)
        return {
            "schema_version": SCORE_REPORT_SCHEMA_VERSION,
            "benchmark_id": BENCHMARK_ID,
            "adapter_contract": ADAPTER_CONTRACT,
            "split": split,
            "scores": score_payloads,
            "metrics": list(METRICS),
            "rh_axis_ids": list(RH_AXES),
            "artifact_refs": list(artifact_refs),
            "model_execution_performed": False,
        }


def _task_from_record(record: dict[str, Any], index: int) -> AutoResearchBenchTask:
    question = first_text(record, ("question", "query", "prompt", "input"))
    if not question:
        input_data = record.get("input_data")
        if isinstance(input_data, dict):
            question = first_text(input_data, ("question", "query", "prompt", "input"))
    if not question:
        raise ValueError(f"AutoResearchBench record {index} has no question")

    input_data = (
        record.get("input_data") if isinstance(record.get("input_data"), dict) else {}
    )
    task_type = _normalize_task_type(
        first_text(record, ("search_type", "task_type", "type", "category"))
        or first_text(input_data, ("search_type", "task_type", "type", "category"))
    )
    answer_titles = first_list(
        record, ("answer", "answers", "answer_titles", "gold_titles")
    )
    if not answer_titles:
        answer_titles = first_list(
            input_data, ("answer", "answers", "answer_titles", "gold_titles")
        )
    answer_arxiv_ids = first_list(record, ("arxiv_id", "arxiv_ids", "answer_arxiv_ids"))
    if not answer_arxiv_ids:
        answer_arxiv_ids = first_list(
            input_data, ("arxiv_id", "arxiv_ids", "answer_arxiv_ids")
        )
    if task_type == "unknown":
        task_type = "wide" if answer_arxiv_ids else "deep"

    task_id = first_text(record, ("task_id", "id", "qid", "question_id")) or str(index)
    reserved = {
        "question",
        "query",
        "prompt",
        "input",
        "input_data",
        "search_type",
        "task_type",
        "type",
        "category",
        "answer",
        "answers",
        "answer_titles",
        "gold_titles",
        "arxiv_id",
        "arxiv_ids",
        "answer_arxiv_ids",
        "task_id",
        "id",
        "qid",
        "question_id",
    }
    metadata = {key: value for key, value in record.items() if key not in reserved}
    return AutoResearchBenchTask(
        task_id=f"autoresearchbench.{normalize_id(task_id)}",
        question=question,
        task_type=task_type,
        answer_titles=tuple(
            str(title).strip() for title in answer_titles if str(title).strip()
        ),
        answer_arxiv_ids=tuple(
            _normalize_arxiv_id(arxiv_id)
            for arxiv_id in answer_arxiv_ids
            if _normalize_arxiv_id(arxiv_id)
        ),
        split=SPLIT_MUTATE_DEV,
        metadata=metadata,
    )


def _normalize_task_type(value: str) -> str:
    lowered = value.strip().lower()
    if "wide" in lowered:
        return "wide"
    if "deep" in lowered:
        return "deep"
    return "unknown"


def _normalize_arxiv_id(arxiv_id: Any) -> str:
    cleaned = re.sub(r"(?i)arxiv:", "", str(arxiv_id)).strip()
    match = re.search(r"(\d{4}\.\d{4,5})", cleaned)
    return match.group(1) if match else cleaned


def _titles_match(candidate: str, gold: str) -> bool:
    return _normalize_title(candidate) == _normalize_title(gold)


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", title.lower())).strip()
