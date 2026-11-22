"""Private, bounded read-only replay of the local RH source."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


class LocalRhSourceReplayError(RuntimeError):
    """Raised when the local RH source cannot be replayed safely."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class LocalRhCounts:
    logical_rows: int
    physical_files: int
    unique_content_hashes: int
    resolvable_paths: int
    stale_paths: int
    empty_paths: int
    derived_json_files: int
    derived_artifact_directories: int


@dataclass(frozen=True)
class LocalRhSourceReplay:
    snapshot_id: str
    observed_at: str
    scan_host_id: str
    counts: LocalRhCounts
    stable_evidence_sha256: str
    sqlite_access: str = "immutable_query_only"
    raw_payloads_retained: bool = False

    def to_portable(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["counts"] = asdict(self.counts)
        return payload


_HASH_CHUNK_BYTES = 1024 * 1024


def replay_local_rh_source(
    *,
    rh_root: Path,
    snapshot_id: str,
    observed_at: str,
    scan_host_id: str,
) -> LocalRhSourceReplay:
    """Read local RH state and assets into a deterministic aggregate report."""

    root = _validated_root(rh_root)
    if not snapshot_id or not observed_at or not scan_host_id:
        raise LocalRhSourceReplayError("empty_invocation_field")
    state = root / ".research-harness"
    downloads = state / "downloads"
    artifacts = state / "artifacts"
    database = state / "pool.db"
    _require_directory(state, "state_unreadable")
    _require_directory(downloads, "downloads_unreadable")
    _require_directory(artifacts, "artifacts_unreadable")
    _require_regular_file(database, "database_unreadable")

    files = _file_fingerprints(downloads)
    logical_rows, path_fingerprints = _read_paper_rows(database, root, state, downloads)
    derived_json_files, derived_directories, artifact_fingerprints = (
        _artifact_fingerprints(artifacts)
    )
    counts = LocalRhCounts(
        logical_rows=logical_rows,
        physical_files=len(files),
        unique_content_hashes=len({item[2] for item in files}),
        resolvable_paths=sum(item[1] == "resolvable" for item in path_fingerprints),
        stale_paths=sum(item[1] == "stale" for item in path_fingerprints),
        empty_paths=sum(item[1] == "empty" for item in path_fingerprints),
        derived_json_files=derived_json_files,
        derived_artifact_directories=derived_directories,
    )
    stable_payload = {
        "counts": asdict(counts),
        "downloads": files,
        "paths": path_fingerprints,
        "artifacts": artifact_fingerprints,
        "sqlite_access": "immutable_query_only",
    }
    stable_digest = hashlib.sha256(
        json.dumps(stable_payload, ensure_ascii=True, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return LocalRhSourceReplay(
        snapshot_id=snapshot_id,
        observed_at=observed_at,
        scan_host_id=scan_host_id,
        counts=counts,
        stable_evidence_sha256=stable_digest,
    )


def _validated_root(root: Path) -> Path:
    candidate = Path(root)
    if not candidate.is_absolute() or candidate in (Path("/"), Path.home()):
        raise LocalRhSourceReplayError("unsafe_rh_root")
    _reject_symlink_components(candidate)
    if not candidate.is_dir():
        raise LocalRhSourceReplayError("unsafe_rh_root")
    return candidate


def _reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        if current.is_symlink():
            raise LocalRhSourceReplayError("symlinked_source_component")


def _require_directory(path: Path, code: str) -> None:
    if path.is_symlink():
        raise LocalRhSourceReplayError(f"{path.name}_symlink")
    if not path.is_dir():
        raise LocalRhSourceReplayError(code)
    _reject_symlink_components(path)


def _require_regular_file(path: Path, code: str) -> None:
    if path.is_symlink():
        raise LocalRhSourceReplayError("database_symlink")
    if not path.is_file():
        raise LocalRhSourceReplayError(code)


def _file_fingerprints(root: Path) -> tuple[tuple[str, int, str], ...]:
    rows: list[tuple[str, int, str]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise LocalRhSourceReplayError("download_symlink")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        rows.append((relative, path.stat().st_size, _sha256_file(path)))
    return tuple(rows)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _read_paper_rows(
    database: Path, root: Path, state: Path, downloads: Path
) -> tuple[int, tuple[tuple[str, str], ...]]:
    uri = f"file:{database}?mode=ro&immutable=1"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise LocalRhSourceReplayError("database_unreadable") from exc
    try:
        connection.execute("PRAGMA query_only=ON")
        query_only = connection.execute("PRAGMA query_only").fetchone()
        if query_only != (1,):
            raise LocalRhSourceReplayError("database_not_query_only")
        rows = connection.execute("SELECT pdf_path FROM papers ORDER BY id").fetchall()
    except sqlite3.Error as exc:
        raise LocalRhSourceReplayError("papers_table_unreadable") from exc
    finally:
        connection.close()

    paths: list[tuple[str, str]] = []
    for (value,) in rows:
        raw = value if isinstance(value, str) else ""
        if not raw:
            paths.append(("", "empty"))
            continue
        candidate = Path(raw)
        if not candidate.is_absolute():
            root_candidate = root / candidate
            state_candidate = state / candidate
            candidate = root_candidate if root_candidate.exists() else state_candidate
        if candidate.is_symlink():
            raise LocalRhSourceReplayError("paper_path_symlink")
        try:
            candidate.relative_to(downloads)
        except ValueError:
            paths.append((raw, "stale"))
            continue
        paths.append((raw, "resolvable" if candidate.is_file() else "stale"))
    return len(rows), tuple(paths)


def _artifact_fingerprints(root: Path) -> tuple[int, int, tuple[tuple[str, int], ...]]:
    json_files = 0
    directories = 0
    entries: list[tuple[str, int]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise LocalRhSourceReplayError("artifact_symlink")
        if path.is_dir():
            directories += 1
        elif path.is_file():
            relative = path.relative_to(root).as_posix()
            if path.suffix.lower() == ".json":
                json_files += 1
            entries.append((relative, path.stat().st_size))
    return json_files, directories, tuple(entries)
