"""已验证文件的内容寻址、原子保存和物理校验。"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Mapping

from paperfetch.artifacts.models import (
    ArtifactFile,
    ArtifactKind,
    ArtifactManifest,
    ArtifactPointer,
    ArtifactProducer,
)


class ArtifactStoreError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _safe_join(root: Path, relative: str) -> Path:
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ArtifactStoreError(
            "artifact_path_unsafe", "文件路径越出 Seed Pack"
        ) from exc
    return candidate


def _atomic_json(path: Path, payload: dict) -> None:
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp, path)


def materialize_artifact(
    seed_pack: str | Path,
    *,
    paper_id: str,
    kind: ArtifactKind | str,
    files: Mapping[str, str | Path | tuple[str | Path, str]],
    producer: ArtifactProducer,
    source_artifact_id: str | None = None,
) -> ArtifactPointer:
    """复制已验证阶段输出，生成文件清单，再原子发布目录。"""

    root = Path(seed_pack).resolve()
    kind_value = ArtifactKind(kind)
    if not files:
        raise ArtifactStoreError("artifact_files_empty", "没有待保存的文件")
    sources: list[tuple[str, Path, str, str, int]] = []
    aggregate = hashlib.sha256()
    aggregate.update(kind_value.value.encode("utf-8"))
    aggregate.update((source_artifact_id or "").encode("utf-8"))
    for role, raw_spec in sorted(files.items()):
        if isinstance(raw_spec, tuple):
            raw_path, requested_path = raw_spec
        else:
            raw_path, requested_path = raw_spec, ""
        source = Path(raw_path).resolve()
        if not source.is_file():
            raise ArtifactStoreError(
                "artifact_source_missing", f"待保存文件不存在：{role}"
            )
        digest, size = _sha256_file(source)
        aggregate.update(role.encode("utf-8"))
        aggregate.update(bytes.fromhex(digest))
        if kind_value == ArtifactKind.PAPER_PDF:
            relative_path = "article.pdf"
        elif requested_path:
            relative_path = ArtifactFile(
                role=role,
                path=requested_path,
                sha256=digest,
                size_bytes=size,
            ).path
        elif role == "document_markdown":
            relative_path = "document.md"
        else:
            suffix = "".join(source.suffixes)
            relative_path = f"{role}{suffix}" if suffix else role
        aggregate.update(relative_path.encode("utf-8"))
        sources.append((role, source, relative_path, digest, size))
    artifact_id = f"art_{aggregate.hexdigest()[:32]}"
    category = "pdf" if kind_value == ArtifactKind.PAPER_PDF else "fulltext"
    relative_dir = Path("artifacts") / paper_id / category / artifact_id
    target_dir = root / relative_dir
    manifest_relative = (relative_dir / "manifest.json").as_posix()
    if target_dir.exists():
        pointer = ArtifactPointer(
            artifact_id=artifact_id,
            kind=kind_value,
            manifest_path=manifest_relative,
        )
        probe_artifact(root, pointer, expected_paper_id=paper_id)
        return pointer

    staging_root = root / ".spc" / "staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    stage = staging_root / f"artifact-{artifact_id}-{uuid.uuid4().hex}"
    stage.mkdir()
    artifact_files: list[ArtifactFile] = []
    try:
        for role, source, relative_path, expected_digest, expected_size in sources:
            if kind_value == ArtifactKind.PAPER_PDF:
                with source.open("rb") as handle:
                    if handle.read(5) != b"%PDF-":
                        raise ArtifactStoreError(
                            "artifact_pdf_invalid",
                            "PDF 文件格式无效：缺少 %PDF- 文件头",
                        )
            destination = stage.joinpath(*relative_path.split("/"))
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            actual_digest, actual_size = _sha256_file(destination)
            if (actual_digest, actual_size) != (expected_digest, expected_size):
                raise ArtifactStoreError(
                    "artifact_copy_mismatch", "文件复制后的 SHA-256 或字节数不一致"
                )
            if role == "document_markdown" and actual_size == 0:
                raise ArtifactStoreError(
                    "artifact_markdown_empty", "MinerU Markdown 文件为空"
                )
            artifact_files.append(
                ArtifactFile(
                    role=role,
                    path=relative_path,
                    sha256=actual_digest,
                    size_bytes=actual_size,
                )
            )
        manifest = ArtifactManifest(
            artifact_id=artifact_id,
            paper_id=paper_id,
            kind=kind_value,
            producer=producer,
            source_artifact_id=source_artifact_id,
            files=artifact_files,
        )
        _atomic_json(stage / "manifest.json", manifest.model_dump(mode="json"))
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(stage, target_dir)
        except OSError:
            if not target_dir.exists():
                raise
            shutil.rmtree(stage)
        pointer = ArtifactPointer(
            artifact_id=artifact_id,
            kind=kind_value,
            manifest_path=manifest_relative,
        )
        probe_artifact(root, pointer, expected_paper_id=paper_id)
        return pointer
    except Exception:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        raise


def probe_artifact(
    seed_pack: str | Path,
    pointer: ArtifactPointer,
    *,
    expected_paper_id: str,
) -> ArtifactManifest:
    """从文件清单重载并逐文件校验物理字节，不信任记录中的可用性缓存。"""

    root = Path(seed_pack).resolve()
    manifest_path = _safe_join(root, pointer.manifest_path)
    if not manifest_path.is_file():
        raise ArtifactStoreError(
            "artifact_manifest_missing", "文件清单 manifest.json 不存在"
        )
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = ArtifactManifest.model_validate(payload)
    except Exception as exc:
        raise ArtifactStoreError(
            "artifact_manifest_invalid", "文件清单 manifest.json 格式无效"
        ) from exc
    if manifest.artifact_id != pointer.artifact_id or manifest.kind != pointer.kind:
        raise ArtifactStoreError(
            "artifact_identity_conflict", "文件引用与 manifest.json 中的身份不一致"
        )
    if manifest.paper_id != expected_paper_id:
        raise ArtifactStoreError(
            "artifact_paper_conflict", "该 PDF 或正文文件不属于目标论文"
        )
    base = manifest_path.parent
    for item in manifest.files:
        path = _safe_join(base, item.path)
        if not path.is_file():
            raise ArtifactStoreError(
                "artifact_file_missing", f"文件清单中的实际文件不存在：{item.role}"
            )
        digest, size = _sha256_file(path)
        if digest != item.sha256 or size != item.size_bytes:
            raise ArtifactStoreError(
                "artifact_file_corrupt", f"文件 SHA-256 或字节数校验失败：{item.role}"
            )
    return manifest
