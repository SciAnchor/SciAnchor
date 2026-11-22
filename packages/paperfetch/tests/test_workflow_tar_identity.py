from __future__ import annotations

import gzip
import io
import tarfile

import pytest

from paperfetch.workflows.tar_identity import (
    TarIdentityError,
    build_tar_member_manifest,
    compare_tar_member_manifests,
)


def _gzip(payload: bytes, *, mtime: int) -> bytes:
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=mtime) as handle:
        handle.write(payload)
    return buffer.getvalue()


def _tar(path, member_name: str, payload: bytes, *, mtime: int = 0):
    with tarfile.open(path, "w") as archive:
        info = tarfile.TarInfo(member_name)
        info.size = len(payload)
        info.mtime = mtime
        archive.addfile(info, io.BytesIO(payload))


def test_tar_comparison_separates_package_and_member_identity(tmp_path):
    payload = _gzip(b"same RDS payload", mtime=1)
    left_path = tmp_path / "left.tar"
    right_path = tmp_path / "right.tar"
    _tar(left_path, "GSM1_counts.RDS.gz", payload, mtime=1)
    _tar(right_path, "GSM1_counts.RDS.gz", payload, mtime=2)

    left = build_tar_member_manifest(left_path)
    right = build_tar_member_manifest(right_path)
    comparison = compare_tar_member_manifests(left, right)

    assert comparison["package_sha256_equal"] is False
    assert comparison["member_names_equal"] is True
    assert comparison["compressed_members_equal"] is True
    assert comparison["decompressed_members_compared"] is False


def test_tar_comparison_can_normalize_gzip_wrapper(tmp_path):
    left_path = tmp_path / "left.tar"
    right_path = tmp_path / "right.tar"
    _tar(left_path, "GSM1_counts.RDS.gz", _gzip(b"same RDS payload", mtime=1))
    _tar(right_path, "GSM1_counts.RDS.gz", _gzip(b"same RDS payload", mtime=2))

    left = build_tar_member_manifest(left_path, decompress_gzip_members=True)
    right = build_tar_member_manifest(right_path, decompress_gzip_members=True)
    comparison = compare_tar_member_manifests(left, right)

    assert comparison["compressed_members_equal"] is False
    assert comparison["decompressed_members_compared"] is True
    assert comparison["decompressed_members_equal"] is True


def test_tar_manifest_rejects_unsafe_member_name(tmp_path):
    path = tmp_path / "unsafe.tar"
    _tar(path, "../escape.txt", b"unsafe")

    with pytest.raises(TarIdentityError, match="tar 成员名称不安全"):
        build_tar_member_manifest(path)


def test_tar_manifest_rejects_links(tmp_path):
    path = tmp_path / "link.tar"
    with tarfile.open(path, "w") as archive:
        info = tarfile.TarInfo("linked-data")
        info.type = tarfile.SYMTYPE
        info.linkname = "outside"
        archive.addfile(info)

    with pytest.raises(TarIdentityError, match="不支持的非文件成员"):
        build_tar_member_manifest(path)
