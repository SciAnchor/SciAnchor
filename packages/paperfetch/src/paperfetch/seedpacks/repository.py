"""SPC 1.0 Seed Pack 原子事实仓储。

`papers.jsonl` 是唯一可变论文事实源；`manifest.json` 只保存静态包身份。
事务在锁内完成重新读取、全量模型校验、实际文件检查、暂存、原子替换和
结果重载。旧 0.x Seed Pack 必须显式拒绝，绝不静默混写。
"""

from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterator, Sequence

from pydantic import ValidationError

from paperfetch.artifacts.store import ArtifactStoreError, probe_artifact
from paperfetch.papers.models import PaperRecord
from paperfetch.seedpacks.models import SeedPackManifest


class SeedPackError(RuntimeError):
    def __init__(self, code: str, message: str, *, stage: str = "seed_pack") -> None:
        super().__init__(message)
        self.code = code
        self.stage = stage


@dataclass(frozen=True)
class SeedPackSnapshot:
    manifest: SeedPackManifest
    papers: tuple[PaperRecord, ...]
    artifact_count: int


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_text(path: Path, content: str) -> None:
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)
    _fsync_directory(path.parent)


@contextmanager
def _write_lock(path: Path, timeout_seconds: float) -> Iterator[None]:
    if timeout_seconds <= 0:
        raise SeedPackError(
            "seed_pack_lock_timeout_invalid", "锁等待时间必须大于零", stage="lock"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if handle.seek(0, os.SEEK_END) == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (BlockingIOError, OSError) as exc:
                if time.monotonic() >= deadline:
                    raise SeedPackError(
                        "seed_pack_lock_timeout",
                        "等待 Seed Pack 写锁超时",
                        stage="lock",
                    ) from exc
                time.sleep(0.05)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class SeedPackRepository:
    MANIFEST = "manifest.json"
    PAPERS = "papers.jsonl"
    LEGACY_PAPERS = "seed_papers.jsonl"

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    @property
    def manifest_path(self) -> Path:
        return self.root / self.MANIFEST

    @property
    def papers_path(self) -> Path:
        return self.root / self.PAPERS

    @property
    def internal_root(self) -> Path:
        return self.root / ".spc"

    @classmethod
    def initialize(
        cls, root: str | Path, *, name: str | None = None
    ) -> "SeedPackRepository":
        repository = cls(root)
        if (repository.root / cls.LEGACY_PAPERS).exists():
            raise SeedPackError(
                "unsupported_legacy_seed_pack",
                "检测到 0.x Seed Pack；1.0 拒绝静默迁移或混写",
                stage="initialize",
            )
        if repository.manifest_path.exists() or repository.papers_path.exists():
            raise SeedPackError(
                "seed_pack_already_exists",
                "目标目录已经包含 Seed Pack",
                stage="initialize",
            )
        repository.root.mkdir(parents=True, exist_ok=True)
        unexpected = [item for item in repository.root.iterdir() if item.name != ".spc"]
        if unexpected:
            raise SeedPackError(
                "seed_pack_directory_not_empty",
                "目标目录非空，拒绝覆盖既有文件",
                stage="initialize",
            )
        for relative in ("transactions", "staging", "locks", "audit"):
            (repository.internal_root / relative).mkdir(parents=True, exist_ok=True)
        manifest = SeedPackManifest(name=name)
        _atomic_text(
            repository.manifest_path,
            json.dumps(
                manifest.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
        )
        _atomic_text(repository.papers_path, "")
        repository.load(probe_artifacts=True)
        return repository

    def _require_v1(self) -> None:
        if (self.root / self.LEGACY_PAPERS).exists():
            raise SeedPackError(
                "unsupported_legacy_seed_pack",
                "检测到 0.x Seed Pack；请显式迁移到新目录",
                stage="load",
            )
        if not self.manifest_path.is_file() or not self.papers_path.is_file():
            raise SeedPackError(
                "seed_pack_not_found", "目录不是完整的 SPC 1.0 Seed Pack", stage="load"
            )

    def _load_manifest(self) -> SeedPackManifest:
        try:
            return SeedPackManifest.model_validate_json(
                self.manifest_path.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, ValidationError, ValueError) as exc:
            raise SeedPackError(
                "seed_pack_manifest_invalid", "Seed Pack manifest 无效", stage="load"
            ) from exc

    def _load_papers(self) -> list[PaperRecord]:
        records: list[PaperRecord] = []
        try:
            with self.papers_path.open("r", encoding="utf-8") as handle:
                for line_number, line in enumerate(handle, start=1):
                    if not line.strip():
                        continue
                    try:
                        records.append(PaperRecord.model_validate_json(line))
                    except (ValidationError, ValueError) as exc:
                        raise SeedPackError(
                            "paper_record_invalid",
                            f"papers.jsonl 第 {line_number} 行无效",
                            stage="load",
                        ) from exc
        except (OSError, UnicodeError) as exc:
            if isinstance(exc, SeedPackError):
                raise
            raise SeedPackError(
                "seed_pack_read_failed", "读取 papers.jsonl 失败", stage="load"
            ) from exc
        self._validate_records(records)
        return records

    @staticmethod
    def _validate_records(records: Sequence[PaperRecord]) -> None:
        paper_ids: set[str] = set()
        identifier_owners: dict[tuple[str, str], str] = {}
        for record in records:
            PaperRecord.model_validate(record.model_dump(mode="python"))
            if record.paper_id in paper_ids:
                raise SeedPackError(
                    "duplicate_paper_id", "Seed Pack 含重复 paper_id", stage="validate"
                )
            paper_ids.add(record.paper_id)
            for field in ("doi", "pubmed_id", "pmc_id", "arxiv_id"):
                value = getattr(record.identifiers, field)
                if value is None:
                    continue
                key = (field, value.casefold())
                owner = identifier_owners.get(key)
                if owner is not None and owner != record.paper_id:
                    raise SeedPackError(
                        "duplicate_strong_identifier",
                        f"Seed Pack 含重复 DOI/PMID/PMCID/arXiv 标识：{field}",
                        stage="validate",
                    )
                identifier_owners[key] = record.paper_id

    def _probe_records(self, records: Sequence[PaperRecord]) -> int:
        artifact_ids: set[str] = set()
        for record in records:
            pointers = [record.fulltext.pdf.artifact, record.fulltext.parse.artifact]
            for pointer in pointers:
                if pointer is None:
                    continue
                try:
                    probe_artifact(
                        self.root, pointer, expected_paper_id=record.paper_id
                    )
                except ArtifactStoreError as exc:
                    raise SeedPackError(
                        exc.code, str(exc), stage="physical_probe"
                    ) from exc
                artifact_ids.add(pointer.artifact_id)
        return len(artifact_ids)

    def load(self, *, probe_artifacts: bool = True) -> SeedPackSnapshot:
        self._require_v1()
        manifest = self._load_manifest()
        records = self._load_papers()
        artifact_count = self._probe_records(records) if probe_artifacts else 0
        return SeedPackSnapshot(
            manifest=manifest, papers=tuple(records), artifact_count=artifact_count
        )

    def _serialize_records(self, records: Sequence[PaperRecord]) -> str:
        self._validate_records(records)
        return "".join(record.model_dump_json() + "\n" for record in records)

    def transact(
        self,
        action: str,
        mutate: Callable[[tuple[PaperRecord, ...]], Sequence[PaperRecord]],
        *,
        lock_timeout_seconds: float = 30.0,
    ) -> SeedPackSnapshot:
        """更新唯一权威论文文件；任何校验失败均发生在 os.replace 前。"""

        self._require_v1()
        transaction_id = uuid.uuid4().hex
        lock_path = self.internal_root / "locks" / "write.lock"
        with _write_lock(lock_path, lock_timeout_seconds):
            current = self.load(probe_artifacts=True)
            try:
                proposed = tuple(mutate(current.papers))
            except SeedPackError:
                raise
            except Exception as exc:
                raise SeedPackError(
                    "seed_pack_mutation_failed",
                    "Seed Pack 变更函数失败",
                    stage="mutate",
                ) from exc
            payload = self._serialize_records(proposed)
            self._probe_records(proposed)
            staging = self.internal_root / "staging" / f"papers-{transaction_id}.jsonl"
            _atomic_text(staging, payload)
            try:
                # staging 必须通过同一模型的重新加载，不能信任内存对象。
                staged_records: list[PaperRecord] = []
                with staging.open("r", encoding="utf-8") as handle:
                    for line in handle:
                        if line.strip():
                            staged_records.append(PaperRecord.model_validate_json(line))
                self._validate_records(staged_records)
                self._probe_records(staged_records)
                transaction = {
                    "schema_version": "spc.seed-pack-transaction.v1",
                    "transaction_id": transaction_id,
                    "seed_pack_id": current.manifest.seed_pack_id,
                    "action": action,
                    "status": "prepared",
                    "record_count_before": len(current.papers),
                    "record_count_after": len(staged_records),
                    "created_at": _utc_iso(),
                }
                transaction_path = (
                    self.internal_root / "transactions" / f"{transaction_id}.json"
                )
                _atomic_text(
                    transaction_path,
                    json.dumps(
                        transaction, ensure_ascii=False, indent=2, sort_keys=True
                    )
                    + "\n",
                )
                backup = (
                    self.internal_root
                    / "staging"
                    / f"papers-{transaction_id}.before.jsonl"
                )
                shutil.copyfile(self.papers_path, backup)
                try:
                    os.replace(staging, self.papers_path)
                    _fsync_directory(self.root)
                    reloaded = self.load(probe_artifacts=True)
                    if tuple(
                        item.model_dump(mode="json") for item in reloaded.papers
                    ) != tuple(item.model_dump(mode="json") for item in staged_records):
                        raise SeedPackError(
                            "seed_pack_reload_mismatch",
                            "原子替换后的唯一权威论文文件与事务结果不一致",
                            stage="reload",
                        )
                except BaseException:
                    os.replace(backup, self.papers_path)
                    _fsync_directory(self.root)
                    self.load(probe_artifacts=True)
                    raise
                finally:
                    if backup.exists():
                        backup.unlink()
                transaction["status"] = "committed"
                transaction["committed_at"] = _utc_iso()
                try:
                    # 审计记录不是业务事实；提交后写审计失败不能反转业务成功。
                    _atomic_text(
                        transaction_path,
                        json.dumps(
                            transaction, ensure_ascii=False, indent=2, sort_keys=True
                        )
                        + "\n",
                    )
                except OSError:
                    pass
            finally:
                if staging.exists():
                    staging.unlink()
            return reloaded

    def add(
        self,
        records: Sequence[PaperRecord],
        *,
        lock_timeout_seconds: float = 30.0,
    ) -> SeedPackSnapshot:
        additions = tuple(records)
        if not additions:
            raise SeedPackError(
                "paper_additions_empty", "没有待新增论文", stage="mutate"
            )
        return self.transact(
            "add",
            lambda current: (*current, *additions),
            lock_timeout_seconds=lock_timeout_seconds,
        )

    def replace(
        self,
        records: Sequence[PaperRecord],
        *,
        lock_timeout_seconds: float = 30.0,
    ) -> SeedPackSnapshot:
        replacements = {record.paper_id: record for record in records}
        if not replacements:
            raise SeedPackError(
                "paper_replacements_empty", "没有待更新论文", stage="mutate"
            )
        if len(replacements) != len(records):
            raise SeedPackError(
                "duplicate_paper_id", "更新集合含重复 paper_id", stage="mutate"
            )

        def mutate(current: tuple[PaperRecord, ...]) -> tuple[PaperRecord, ...]:
            current_ids = {item.paper_id for item in current}
            missing = set(replacements).difference(current_ids)
            if missing:
                raise SeedPackError(
                    "paper_not_found",
                    "更新集合含 Seed Pack 中不存在的论文",
                    stage="mutate",
                )
            updated: list[PaperRecord] = []
            for item in current:
                replacement = replacements.get(item.paper_id)
                if replacement is None:
                    updated.append(item)
                    continue
                if replacement.revision != item.revision + 1:
                    raise SeedPackError(
                        "paper_revision_conflict",
                        "论文 revision 必须在 papers.jsonl 当前记录基础上递增一次",
                        stage="mutate",
                    )
                if replacement.created_at != item.created_at:
                    raise SeedPackError(
                        "paper_identity_conflict",
                        "更新不得修改 created_at",
                        stage="mutate",
                    )
                updated.append(replacement)
            return tuple(updated)

        return self.transact(
            "replace", mutate, lock_timeout_seconds=lock_timeout_seconds
        )
