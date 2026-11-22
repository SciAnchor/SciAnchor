"""Shared contracts for ResearchFlowBench external adapters."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Protocol, runtime_checkable


@runtime_checkable
class ExternalBenchmarkAdapter(Protocol):
    """Minimal interface implemented by benchmark-specific adapters."""

    benchmark_id: str
    adapter_contract: str

    def manifest(self) -> dict:
        """Return a JSON-serializable adapter manifest."""

    def write_task_pack(
        self,
        output_dir: str | Path,
        *,
        include_gold: bool = False,
    ) -> dict:
        """Write RH-formatted visible tasks and optional judge-only gold."""


def iter_records(root: str | Path) -> Iterable[dict[str, Any]]:
    """Yield JSON/JSONL/parquet records from a file or directory."""

    root_path = Path(root)
    if root_path.is_file():
        yield from records_from_file(root_path)
        return
    for path in sorted(root_path.rglob("*")):
        if path.suffix.lower() in {".jsonl", ".json", ".parquet"}:
            yield from records_from_file(path)


def records_from_file(path: Path) -> Iterable[dict[str, Any]]:
    """Yield records from one supported data file."""

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
                "Reading parquet benchmark exports requires pyarrow. Install "
                "`pyarrow` or export the official dataset to JSONL first."
            ) from exc
        table = pq.read_table(path)
        yield from table.to_pylist()
        return
    raise ValueError(f"unsupported benchmark file: {path}")


def first_text(record: dict[str, Any], keys: tuple[str, ...]) -> str:
    """Return the first non-empty text value for candidate keys."""

    for key in keys:
        value = record.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def first_list(record: dict[str, Any], keys: tuple[str, ...]) -> tuple[Any, ...]:
    """Return the first list-like value for candidate keys."""

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


def normalize_id(value: Any) -> str:
    """Normalize benchmark IDs without changing their namespace."""

    return str(value).strip()


def write_json(path: Path, payload: dict) -> None:
    """Write a stable JSON file."""

    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
