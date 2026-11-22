"""Private read-only replay of SPC cache and seed-pack source evidence."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class SpcCacheSeedPackReplayError(RuntimeError):
    """Raised when SPC source evidence cannot be read fail-closed."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class SpcSourceCounts:
    cache_physical_pdfs: int
    cache_unique_hashes: int
    seed_pack_physical_pdfs: int
    seed_pack_unique_hashes: int
    seed_pack_logical_rows: int
    run_report_records: int
    run_report_files: int
    coverage_report_files: int
    seed_pack_dirs: int
    cache_seed_overlap_hashes: int


@dataclass(frozen=True)
class SpcCacheSeedPackReplay:
    snapshot_id: str
    observed_at: str
    scan_host_id: str
    counts: SpcSourceCounts
    stable_evidence_sha256: str
    raw_payloads_retained: bool = False

    def to_portable(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["counts"] = asdict(self.counts)
        return payload


_RUN_REPORT_VERSION = "seed-paper-curator.run-report.v1"
_COVERAGE_REPORT_VERSION = "seed-paper-curator.coverage.v3-summary"
_HASH_CHUNK_BYTES = 1024 * 1024
_CONTRACT_NAMES = frozenset(
    {
        "seed_papers.jsonl",
        "run_report.json",
        "coverage_report.json",
        "pack_manifest.json",
        "START_HERE.md",
    }
)


def replay_spc_cache_seed_pack(
    *,
    cache_root: Path,
    seed_pack_root: Path,
    snapshot_id: str,
    observed_at: str,
    scan_host_id: str,
) -> SpcCacheSeedPackReplay:
    """Replay SPC assets into aggregate evidence without importing them."""

    cache_root = _validated_root(cache_root)
    seed_pack_root = _validated_root(seed_pack_root)
    if not snapshot_id or not observed_at or not scan_host_id:
        raise SpcCacheSeedPackReplayError("empty_invocation_field")

    cache_files = _pdf_fingerprints(cache_root, "cache")
    seed_files = _pdf_fingerprints(seed_pack_root, "seed_pack")
    metadata, logical_rows, report_records, report_files, coverage_files, pack_dirs = (
        _read_seed_pack_contract(seed_pack_root)
    )
    counts = SpcSourceCounts(
        cache_physical_pdfs=len(cache_files),
        cache_unique_hashes=len({item[2] for item in cache_files}),
        seed_pack_physical_pdfs=len(seed_files),
        seed_pack_unique_hashes=len({item[2] for item in seed_files}),
        seed_pack_logical_rows=logical_rows,
        run_report_records=report_records,
        run_report_files=report_files,
        coverage_report_files=coverage_files,
        seed_pack_dirs=pack_dirs,
        cache_seed_overlap_hashes=len(
            {item[2] for item in cache_files} & {item[2] for item in seed_files}
        ),
    )
    stable_payload = {
        "counts": asdict(counts),
        "cache_files": cache_files,
        "seed_files": seed_files,
        "metadata": metadata,
        "contract": {
            "run_report_version": _RUN_REPORT_VERSION,
            "coverage_report_version": _COVERAGE_REPORT_VERSION,
        },
    }
    stable_digest = hashlib.sha256(
        json.dumps(stable_payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return SpcCacheSeedPackReplay(
        snapshot_id=snapshot_id,
        observed_at=observed_at,
        scan_host_id=scan_host_id,
        counts=counts,
        stable_evidence_sha256=stable_digest,
    )


def _validated_root(root: Path) -> Path:
    candidate = Path(root)
    if not candidate.is_absolute() or candidate == Path("/"):
        raise SpcCacheSeedPackReplayError("unsafe_source_root")
    _reject_symlink_components(candidate)
    if not candidate.is_dir():
        raise SpcCacheSeedPackReplayError("source_root_unreadable")
    return candidate


def _reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        if current.is_symlink():
            raise SpcCacheSeedPackReplayError("source_symlink_component")


def _pdf_fingerprints(root: Path, source: str) -> tuple[tuple[str, int, str], ...]:
    rows: list[tuple[str, int, str]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise SpcCacheSeedPackReplayError(f"{source}_symlink")
        if path.is_file() and path.suffix.lower() == ".pdf":
            rows.append(
                (
                    path.relative_to(root).as_posix(),
                    path.stat().st_size,
                    _sha256_file(path),
                )
            )
    return tuple(rows)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _read_seed_pack_contract(
    root: Path,
) -> tuple[tuple[tuple[str, int, str], ...], int, int, int, int, int]:
    metadata: list[tuple[str, int, str]] = []
    logical_rows = 0
    report_records = 0
    report_files = 0
    coverage_files = 0
    pack_dirs = 0
    for seed_file in sorted(root.rglob("seed_papers.jsonl")):
        if seed_file.is_symlink():
            raise SpcCacheSeedPackReplayError("seed_papers_symlink")
        pack_dir = seed_file.parent
        pack_dirs += 1
        run_report = _load_json(pack_dir / "run_report.json", "run_report")
        coverage_report = _load_json(
            pack_dir / "coverage_report.json", "coverage_report"
        )
        if run_report.get("report_version") != _RUN_REPORT_VERSION:
            raise SpcCacheSeedPackReplayError("run_report_version_unsupported")
        if coverage_report.get("report_version") != _COVERAGE_REPORT_VERSION:
            raise SpcCacheSeedPackReplayError("coverage_report_version_unsupported")
        papers = run_report.get("papers")
        if not isinstance(papers, list):
            raise SpcCacheSeedPackReplayError("run_report_papers_invalid")
        report_records += len(papers)
        report_files += 1
        coverage_files += 1
        line_digest = hashlib.sha256()
        with seed_file.open("rb") as handle:
            for raw_line in handle:
                if not raw_line.strip():
                    continue
                try:
                    record = json.loads(raw_line)
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise SpcCacheSeedPackReplayError(
                        "seed_papers_invalid_json"
                    ) from exc
                if not isinstance(record, dict):
                    raise SpcCacheSeedPackReplayError("seed_papers_non_object")
                logical_rows += 1
                line_digest.update(
                    json.dumps(record, ensure_ascii=True, sort_keys=True).encode(
                        "utf-8"
                    )
                )
                line_digest.update(b"\n")
        for path in sorted(pack_dir.iterdir()):
            if path.name not in _CONTRACT_NAMES or path.is_symlink():
                if path.is_symlink():
                    raise SpcCacheSeedPackReplayError("contract_symlink")
                continue
            metadata.append(
                (
                    path.relative_to(root).as_posix(),
                    path.stat().st_size,
                    _sha256_file(path),
                )
            )
        metadata.append(
            (
                f"{seed_file.relative_to(root).as_posix()}#logical_digest",
                logical_rows,
                line_digest.hexdigest(),
            )
        )
    return (
        tuple(metadata),
        logical_rows,
        report_records,
        report_files,
        coverage_files,
        pack_dirs,
    )


def _load_json(path: Path, kind: str) -> dict[str, Any]:
    if path.is_symlink():
        raise SpcCacheSeedPackReplayError(f"{kind}_symlink")
    if not path.is_file():
        raise SpcCacheSeedPackReplayError(f"{kind}_missing")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SpcCacheSeedPackReplayError(f"{kind}_invalid_json") from exc
    if not isinstance(value, dict):
        raise SpcCacheSeedPackReplayError(f"{kind}_not_object")
    return value
