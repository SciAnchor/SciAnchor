"""LitSearch adapter for ResearchFlowBench.

The adapter consumes records exported from the official Hugging Face dataset
(`princeton-nlp/LitSearch`) and converts them into RH retrieval tasks. It does
not vendor LitSearch data or hidden gold into this repository.
"""

from __future__ import annotations

import json
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

ADAPTER_CONTRACT = "researchflowbench.adapters.litsearch.v0.1"
BENCHMARK_ID = "litsearch"
RH_AXES = (
    "paper_search.recall",
    "paper_search.rerank_quality",
    "citation.candidate_generation",
)
METRICS = ("retrieval_recall", "rerank_quality")
LICENSE_CONTRACT = ResearchFlowBenchLicenseContract(
    dataset_license="mit",
    data_source_url="https://huggingface.co/datasets/princeton-nlp/LitSearch",
    redistribution_policy="official data must stay local; adapted task metadata is generated from local export",
    gold_storage_policy=GOLD_STORAGE_LOCAL_ONLY,
)


@dataclass(frozen=True)
class LitSearchQuery:
    query_id: str
    query: str
    gold_paper_ids: tuple[str, ...]
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class LitSearchDocument:
    paper_id: str
    title: str = ""
    abstract: str = ""
    outgoing_citation_ids: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class LitSearchTask:
    task_id: str
    query_id: str
    query: str
    gold_paper_ids: tuple[str, ...]
    corpus_paper_ids: tuple[str, ...] = ()
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
            "query_id": self.query_id,
            "query": self.query,
            "input": {
                "query": self.query,
                "corpus_paper_ids": list(self.corpus_paper_ids),
            },
            "expected_rh_axes": list(RH_AXES),
            "artifact_policy": {
                "gold_visible": include_gold,
                "gold_storage_policy": LICENSE_CONTRACT.gold_storage_policy,
                "third_party_data_vendored": False,
            },
            "license": LICENSE_CONTRACT.to_dict(),
            "leakage_policy": dict(LEAKAGE_POLICY_V0),
            "archive_linkage": linkage.to_dict(),
            "corpus_paper_ids": list(self.corpus_paper_ids),
            "metadata": dict(self.metadata),
        }
        if include_gold:
            payload["gold_paper_ids"] = list(self.gold_paper_ids)
        return payload


@dataclass(frozen=True)
class LitSearchScore:
    task_id: str
    recall_at_k: float
    mrr: float
    hit_at_k: bool
    retrieved_count: int
    gold_count: int
    matched_paper_ids: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


class LitSearchAdapter:
    """Convert LitSearch query/corpus records into RH retrieval tasks."""

    benchmark_id = BENCHMARK_ID
    adapter_contract = ADAPTER_CONTRACT

    def __init__(
        self,
        queries: Iterable[LitSearchQuery],
        corpus: Iterable[LitSearchDocument] = (),
    ) -> None:
        self._queries = tuple(queries)
        self._corpus = tuple(corpus)

    @classmethod
    def from_records(
        cls,
        query_records: Iterable[dict[str, Any]],
        corpus_records: Iterable[dict[str, Any]] = (),
        *,
        max_queries: int | None = None,
    ) -> "LitSearchAdapter":
        queries = tuple(
            _query_from_record(record, index)
            for index, record in enumerate(query_records)
        )
        if max_queries is not None:
            queries = queries[:max_queries]
        corpus = tuple(_document_from_record(record) for record in corpus_records)
        return cls(queries, corpus)

    @classmethod
    def from_directory(
        cls,
        root: str | Path,
        *,
        max_queries: int | None = None,
        load_corpus: bool = False,
    ) -> "LitSearchAdapter":
        root_path = Path(root)
        query_root = (
            root_path / "query" if (root_path / "query").exists() else root_path
        )
        corpus_root = root_path / "corpus_clean"

        query_records = list(_iter_records(query_root))
        corpus_records = (
            list(_iter_records(corpus_root))
            if load_corpus and corpus_root.exists()
            else []
        )
        return cls.from_records(
            query_records,
            corpus_records,
            max_queries=max_queries,
        )

    @property
    def query_count(self) -> int:
        return len(self._queries)

    @property
    def corpus_count(self) -> int:
        return len(self._corpus)

    def tasks(self) -> tuple[LitSearchTask, ...]:
        corpus_ids = tuple(doc.paper_id for doc in self._corpus)
        return tuple(
            LitSearchTask(
                task_id=f"litsearch.{query.query_id}",
                query_id=query.query_id,
                query=query.query,
                gold_paper_ids=query.gold_paper_ids,
                corpus_paper_ids=corpus_ids,
                split=SPLIT_MUTATE_DEV,
                metadata=query.metadata,
            )
            for query in self._queries
        )

    def manifest(self) -> dict:
        return {
            "schema_version": "researchflowbench.external_adapter_manifest.v0.1",
            "adapter_contract": self.adapter_contract,
            "benchmark_id": self.benchmark_id,
            "task_count": self.query_count,
            "corpus_count": self.corpus_count,
            "metrics": METRICS,
            "rh_axes": RH_AXES,
            "license": LICENSE_CONTRACT.to_dict(),
            "gold_storage_policy": LICENSE_CONTRACT.gold_storage_policy,
            "score_report_schema_version": SCORE_REPORT_SCHEMA_VERSION,
            "data_policy": "local official LitSearch export only; no vendored data",
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
            visible = task.to_dict(include_gold=False)
            (task_dir / "input.json").write_text(
                json.dumps(visible, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            if include_gold:
                (task_dir / "gold.json").write_text(
                    json.dumps(
                        {
                            "schema_version": "researchflowbench.external_gold.v0.1",
                            "task_id": task.task_id,
                            "gold_paper_ids": list(task.gold_paper_ids),
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                    encoding="utf-8",
                )

        manifest = self.manifest() | {
            "task_ids": [task.task_id for task in tasks],
            "gold_written": include_gold,
        }
        (out / "adapter_manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return manifest

    @staticmethod
    def score_retrieval(
        task: LitSearchTask,
        retrieved_paper_ids: Iterable[str],
        *,
        k: int = 20,
    ) -> LitSearchScore:
        retrieved = tuple(_normalize_id(paper_id) for paper_id in retrieved_paper_ids)
        cutoff = retrieved[:k]
        gold = {_normalize_id(paper_id) for paper_id in task.gold_paper_ids}
        matched = tuple(paper_id for paper_id in cutoff if paper_id in gold)
        reciprocal_rank = 0.0
        for index, paper_id in enumerate(retrieved, start=1):
            if paper_id in gold:
                reciprocal_rank = 1.0 / index
                break
        recall = len(set(matched)) / len(gold) if gold else 0.0
        return LitSearchScore(
            task_id=task.task_id,
            recall_at_k=round(recall, 6),
            mrr=round(reciprocal_rank, 6),
            hit_at_k=bool(matched),
            retrieved_count=len(retrieved),
            gold_count=len(gold),
            matched_paper_ids=matched,
        )

    @staticmethod
    def score_report(
        scores: Iterable[LitSearchScore],
        *,
        split: str = SPLIT_MUTATE_DEV,
        artifact_refs: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        score_payloads = []
        for score in scores:
            payload = score.to_dict()
            payload["split"] = split
            payload["metrics"] = {
                "retrieval_recall": payload["recall_at_k"],
                "rerank_quality": payload["mrr"],
                "hit_at_k": payload["hit_at_k"],
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


def _iter_records(root: Path) -> Iterable[dict[str, Any]]:
    if root.is_file():
        yield from _records_from_file(root)
        return
    for path in sorted(root.rglob("*")):
        if path.suffix.lower() in {".jsonl", ".json", ".parquet"}:
            yield from _records_from_file(path)


def _records_from_file(path: Path) -> Iterable[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                yield json.loads(line)
        return
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            yield from data
            return
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            yield from data["data"]
            return
        if isinstance(data, dict):
            yield data
            return
    if suffix == ".parquet":
        try:
            import pyarrow.parquet as pq
        except ImportError as exc:  # pragma: no cover - depends on local extras
            raise RuntimeError(
                "Reading LitSearch parquet exports requires pyarrow. Install "
                "`pyarrow` or export the Hugging Face dataset to JSONL first."
            ) from exc
        table = pq.read_table(path)
        yield from table.to_pylist()
        return
    raise ValueError(f"unsupported LitSearch file: {path}")


def _query_from_record(record: dict[str, Any], index: int) -> LitSearchQuery:
    query_text = _first_text(record, ("query", "question", "search_query", "text"))
    if not query_text:
        raise ValueError(f"LitSearch query record {index} has no query text")

    gold_ids = _first_list(
        record,
        (
            "gold_paper_ids",
            "gold_pids",
            "corpusids",
            "corpus_ids",
            "paper_ids",
            "papers",
            "positive_paper_ids",
            "answer_paper_ids",
            "gold",
        ),
    )
    if not gold_ids:
        raise ValueError(f"LitSearch query record {index} has no gold paper IDs")

    query_id = _first_text(record, ("query_id", "qid", "id")) or str(index)
    reserved = {
        "query",
        "question",
        "search_query",
        "text",
        "gold_paper_ids",
        "gold_pids",
        "corpusids",
        "corpus_ids",
        "paper_ids",
        "papers",
        "positive_paper_ids",
        "answer_paper_ids",
        "gold",
        "query_id",
        "qid",
        "id",
    }
    metadata = {key: value for key, value in record.items() if key not in reserved}
    return LitSearchQuery(
        query_id=_normalize_id(query_id),
        query=query_text,
        gold_paper_ids=tuple(_normalize_id(item) for item in gold_ids),
        metadata=metadata,
    )


def _document_from_record(record: dict[str, Any]) -> LitSearchDocument:
    paper_id = _first_text(
        record,
        ("paper_id", "corpusid", "corpus_id", "doc_id", "s2_id", "id"),
    )
    if not paper_id:
        raise ValueError("LitSearch corpus record has no paper ID")
    citations = _first_list(
        record,
        (
            "outgoing_citation_ids",
            "outgoing_citations",
            "references",
            "citation_ids",
            "citations",
        ),
    )
    reserved = {
        "paper_id",
        "corpusid",
        "corpus_id",
        "doc_id",
        "s2_id",
        "id",
        "title",
        "abstract",
        "outgoing_citation_ids",
        "outgoing_citations",
        "references",
        "citation_ids",
        "citations",
    }
    metadata = {key: value for key, value in record.items() if key not in reserved}
    return LitSearchDocument(
        paper_id=_normalize_id(paper_id),
        title=str(record.get("title") or ""),
        abstract=str(record.get("abstract") or ""),
        outgoing_citation_ids=tuple(_normalize_id(item) for item in citations),
        metadata=metadata,
    )


def _first_text(record: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = record.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _first_list(record: dict[str, Any], keys: tuple[str, ...]) -> tuple[Any, ...]:
    for key in keys:
        value = record.get(key)
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            return tuple(value)
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                continue
            try:
                parsed = json.loads(stripped)
            except json.JSONDecodeError:
                return (stripped,)
            if isinstance(parsed, list):
                return tuple(parsed)
            return (parsed,)
    return ()


def _normalize_id(value: Any) -> str:
    return str(value).strip()
