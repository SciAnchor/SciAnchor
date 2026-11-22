"""Content manifests for comparing large Workflow tar artifacts safely."""

from __future__ import annotations

import gzip
import hashlib
import tarfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterable

from paperfetch.datasets.geo import sha256_file
from paperfetch.workflows.contracts import canonical_json_bytes


class TarIdentityError(ValueError):
    """Raised when a tar cannot be represented as a safe deterministic manifest."""


def _hash_stream(stream: BinaryIO, *, chunk_size: int = 1024 * 1024) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    while chunk := stream.read(chunk_size):
        size += len(chunk)
        digest.update(chunk)
    return size, digest.hexdigest()


def _safe_member_name(value: str) -> str:
    candidate = PurePosixPath(value)
    if candidate.is_absolute() or ".." in candidate.parts or not candidate.parts:
        raise TarIdentityError(f"tar 成员名称不安全：{value!r}")
    return candidate.as_posix()


def _member_records(
    archive: tarfile.TarFile,
    members: Iterable[tarfile.TarInfo],
    *,
    decompress_gzip_members: bool,
) -> list[dict[str, object]]:
    records = []
    seen = set()
    for member in members:
        if member.isdir():
            continue
        if not member.isfile():
            raise TarIdentityError(f"tar 包含不支持的非文件成员：{member.name}")
        name = _safe_member_name(member.name)
        if name in seen:
            raise TarIdentityError(f"tar 成员名称重复：{name}")
        seen.add(name)
        raw = archive.extractfile(member)
        if raw is None:
            raise TarIdentityError(f"无法读取 tar 成员：{name}")
        with raw:
            size, digest = _hash_stream(raw)
        if size != member.size:
            raise TarIdentityError(f"tar 成员大小不一致：{name}，{size}/{member.size}")
        record: dict[str, object] = {
            "name": name,
            "size_bytes": size,
            "sha256": digest,
        }
        if decompress_gzip_members and name.lower().endswith(".gz"):
            compressed = archive.extractfile(member)
            if compressed is None:
                raise TarIdentityError(f"无法重新读取 gzip tar 成员：{name}")
            try:
                with (
                    compressed,
                    gzip.GzipFile(fileobj=compressed, mode="rb") as decoded,
                ):
                    decoded_size, decoded_digest = _hash_stream(decoded)
            except (OSError, EOFError) as exc:
                raise TarIdentityError(f"gzip 成员无效：{name}，{exc}") from exc
            record["decompressed_size_bytes"] = decoded_size
            record["decompressed_sha256"] = decoded_digest
        records.append(record)
    return sorted(records, key=lambda item: str(item["name"]))


def build_tar_member_manifest(
    path: str | Path,
    *,
    decompress_gzip_members: bool = False,
) -> dict[str, object]:
    """Hash a tar package and every regular member without extracting to disk."""

    archive_path = Path(path).expanduser().resolve()
    if not archive_path.is_file():
        raise TarIdentityError(f"tar 文件不存在：{archive_path}")
    try:
        with tarfile.open(archive_path, mode="r:*") as archive:
            records = _member_records(
                archive,
                archive.getmembers(),
                decompress_gzip_members=decompress_gzip_members,
            )
    except (tarfile.TarError, OSError) as exc:
        raise TarIdentityError(f"无法检查 tar 文件 {archive_path}：{exc}") from exc
    if not records:
        raise TarIdentityError(f"tar 不包含普通文件：{archive_path}")
    identity_payload = {
        "members": records,
        "decompressed_gzip_members": decompress_gzip_members,
    }
    return {
        "schema_version": "spc.tar-member-manifest.v1",
        "package_path": str(archive_path),
        "package_size_bytes": archive_path.stat().st_size,
        "package_sha256": sha256_file(archive_path),
        "member_count": len(records),
        "member_manifest_sha256": hashlib.sha256(
            canonical_json_bytes(identity_payload)
        ).hexdigest(),
        **identity_payload,
    }


def compare_tar_member_manifests(
    left: dict[str, object],
    right: dict[str, object],
) -> dict[str, object]:
    """Compare package, compressed member, and optional decoded identities."""

    left_members = {str(item["name"]): item for item in left.get("members", [])}
    right_members = {str(item["name"]): item for item in right.get("members", [])}
    left_names = set(left_members)
    right_names = set(right_members)
    common = sorted(left_names & right_names)
    compressed_mismatches = [
        name
        for name in common
        if (
            left_members[name].get("size_bytes"),
            left_members[name].get("sha256"),
        )
        != (
            right_members[name].get("size_bytes"),
            right_members[name].get("sha256"),
        )
    ]
    decoded_available = all(
        "decompressed_sha256" in left_members[name]
        and "decompressed_sha256" in right_members[name]
        for name in common
    )
    decoded_mismatches = []
    if decoded_available:
        decoded_mismatches = [
            name
            for name in common
            if (
                left_members[name].get("decompressed_size_bytes"),
                left_members[name].get("decompressed_sha256"),
            )
            != (
                right_members[name].get("decompressed_size_bytes"),
                right_members[name].get("decompressed_sha256"),
            )
        ]
    same_members = not (left_names ^ right_names)
    return {
        "schema_version": "spc.tar-member-comparison.v1",
        "package_sha256_equal": left.get("package_sha256")
        == right.get("package_sha256"),
        "member_names_equal": same_members,
        "compressed_members_equal": same_members and not compressed_mismatches,
        "decompressed_members_compared": decoded_available,
        "decompressed_members_equal": (
            same_members and decoded_available and not decoded_mismatches
        ),
        "left_only": sorted(left_names - right_names),
        "right_only": sorted(right_names - left_names),
        "compressed_mismatches": compressed_mismatches,
        "decompressed_mismatches": decoded_mismatches,
    }
