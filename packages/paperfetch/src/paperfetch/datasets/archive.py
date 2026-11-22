"""公开归档数据集的确定性检查与物化。"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import struct
import time
import uuid
import zlib
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None


SCHEMA = "spc.archive-dataset-record.v1"
_EOCD = b"PK\x05\x06"
_CENTRAL = b"PK\x01\x02"
_LOCAL = b"PK\x03\x04"
_ZENODO_VERSION = re.compile(r"\|\s*Version\s+([^<]+)</span>", re.IGNORECASE)


class ArchiveDatasetError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        error_code: str,
        error_class: str,
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.error_class = error_class
        self.diagnostics = diagnostics or {}


_FALSE_PROXY_VALUES = {"0", "false", "no", "none", "off"}


def _configured_proxy(name: str) -> str | None:
    from paperfetch.core.settings import capability_proxy

    if name != "ARCHIVE_PROXY":
        raise KeyError(f"归档网络只允许 ARCHIVE_PROXY，收到 {name}")
    return capability_proxy("archive")


def _session(proxy: str | None = None) -> requests.Session:
    retry = Retry(
        total=4,
        connect=3,
        read=3,
        status=4,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.trust_env = False
    session.headers.update({"User-Agent": "SPC-ArchiveDataset/0.3"})
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    if proxy:
        session.proxies.update({"http": proxy, "https": proxy})
    return session


def _archive_proxy_mode() -> str:
    from paperfetch.core.settings import get_settings

    return (get_settings().text("ARCHIVE_PROXY_MODE") or "direct").strip().lower()


def _primary_archive_proxy() -> str | None:
    if _archive_proxy_mode() != "proxy":
        return None
    proxy = _configured_proxy("ARCHIVE_PROXY")
    if proxy is None:
        raise ArchiveDatasetError(
            "ARCHIVE_PROXY_MODE=proxy 要求配置 ARCHIVE_PROXY",
            error_code="archive_proxy_not_configured",
            error_class="configuration_error",
        )
    return proxy


def _figshare_archive_fallback_proxy() -> str | None:
    if _archive_proxy_mode() != "proxy":
        return None
    return _configured_proxy("ARCHIVE_PROXY")


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def persist_archive_record(
    output_dir: str | os.PathLike[str], payload: dict[str, Any]
) -> None:
    _atomic_json(
        Path(output_dir).expanduser().resolve() / "archive_dataset_record.json",
        payload,
    )


def _zenodo_record_from_url(value: str | None) -> str | None:
    path = urlsplit(str(value or "")).path
    match = re.search(r"/(?:api/)?records/(\d+)(?:/|$)", path)
    return match.group(1) if match else None


@contextmanager
def _archive_record_lock(output_dir: Path, timeout_seconds: float = 30.0):
    """Serialize inspect/download transactions that share one archive record."""

    path = output_dir / ".archive_dataset_record.lock"
    handle = path.open("a+b")
    acquired = False
    if msvcrt is not None:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    try:
        while True:
            try:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                elif msvcrt is not None:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                acquired = True
                break
            except (BlockingIOError, OSError) as exc:
                if time.monotonic() >= deadline:
                    raise ArchiveDatasetError(
                        "归档数据集记录正由另一个事务更新",
                        error_code="archive_state_busy",
                        error_class="state_conflict",
                    ) from exc
                time.sleep(0.05)
        yield
    finally:
        try:
            if acquired and fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            elif acquired and msvcrt is not None:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            handle.close()


def _safe_name(value: str) -> str:
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ArchiveDatasetError(
            f"归档文件名不安全：{value!r}",
            error_code="unsafe_archive_path",
            error_class="invalid_argument",
        )
    return str(path)


def _digest_spec(value: str | None) -> tuple[str | None, str | None]:
    text = str(value or "").strip().lower()
    if not text:
        return None, None
    if ":" in text:
        algorithm, digest = text.split(":", 1)
        return algorithm, digest
    return "md5", text


def _record_files(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("files") or []
    if isinstance(raw, dict):
        raw = raw.get("entries") or raw.get("items") or []
        if isinstance(raw, dict):
            raw = [{"key": key, **value} for key, value in raw.items()]
    files: list[dict[str, Any]] = []
    for item in raw:
        links = item.get("links") or {}
        url = (
            links.get("content")
            or links.get("download")
            or links.get("self")
            or item.get("download_url")
        )
        checksum = item.get("checksum")
        if not checksum:
            checksum = (
                f"md5:{item.get('supplied_md5') or item.get('computed_md5')}"
                if item.get("supplied_md5") or item.get("computed_md5")
                else None
            )
        algorithm, digest = _digest_spec(checksum)
        files.append(
            {
                "key": _safe_name(str(item.get("key") or item.get("name") or "")),
                "bytes": int(item.get("size") or item.get("size_bytes") or 0),
                "checksum": {"algorithm": algorithm, "value": digest},
                "_url": str(url or ""),
            }
        )
    return files


def _license(payload: dict[str, Any]) -> str | None:
    metadata = payload.get("metadata") or {}
    license_value = metadata.get("license")
    if isinstance(license_value, dict):
        return (
            str(
                license_value.get("id")
                or license_value.get("title")
                or license_value.get("name")
                or ""
            )
            or None
        )
    rights = metadata.get("rights") or []
    if rights and isinstance(rights[0], dict):
        return str(rights[0].get("id") or rights[0].get("title") or "") or None
    return str(license_value or "") or None


def _access_status(payload: dict[str, Any]) -> str | None:
    metadata = payload.get("metadata") or {}
    access = payload.get("access") or {}
    value = (
        (access.get("status") if isinstance(access, dict) else None)
        or metadata.get("access_right")
        or payload.get("access_right")
    )
    return str(value or "").strip().lower() or None


def _access_is_restricted(value: str | None) -> bool:
    return value in {"restricted", "embargoed", "closed"}


@dataclass(frozen=True)
class RemoteArchiveEntry:
    name: str
    compressed_bytes: int
    uncompressed_bytes: int
    compression: int
    crc32: int
    local_header_offset: int

    def packaging_artifact_type(self) -> str | None:
        path = PurePosixPath(self.name)
        parts = {part.lower() for part in path.parts}
        basename = path.name.lower()
        if basename == ".ds_store":
            return "macos_ds_store"
        if basename.startswith("._"):
            return "apple_double"
        if "__macosx" in parts:
            return "macos_metadata_container"
        return None

    def public(self) -> dict[str, Any]:
        artifact_type = self.packaging_artifact_type()
        suffixes = [suffix.lower() for suffix in PurePosixPath(self.name).suffixes]
        return {
            "name": self.name,
            "compressed_bytes": self.compressed_bytes,
            "uncompressed_bytes": self.uncompressed_bytes,
            "type": (
                "packaging_artifact"
                if artifact_type
                else "nii.gz"
                if suffixes[-2:] == [".nii", ".gz"]
                else (suffixes[-1][1:] if suffixes else "none")
            ),
            "packaging_artifact": bool(artifact_type),
            "packaging_artifact_type": artifact_type,
        }


class ZenodoArchiveStore:
    source_name = "zenodo"
    record_label = "Zenodo record"

    def __init__(
        self,
        output_dir: str | os.PathLike[str],
        *,
        lock_timeout_seconds: float = 30.0,
    ) -> None:
        self.output_dir = Path(output_dir).expanduser().resolve()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.lock_timeout_seconds = lock_timeout_seconds
        proxy = _primary_archive_proxy()
        self.session = _session(proxy)
        self._transport = {
            "route": "archive_proxy" if proxy else "direct",
            "trust_env": False,
            "proxy_configured": bool(proxy),
        }
        self._transport_attempts: list[dict[str, Any]] = []

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> "ZenodoArchiveStore":
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()

    def _metadata(self, record: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        response = self.session.get(
            f"https://zenodo.org/api/records/{record}", timeout=30
        )
        requested_record = str(record)
        resolved_record = _zenodo_record_from_url(str(response.url)) or requested_record
        resolution_evidence: list[dict[str, Any]] = []
        for item in response.history:
            location = str(item.headers.get("Location") or "")
            next_record = _zenodo_record_from_url(location)
            resolution_evidence.append(
                {
                    "kind": "http_redirect",
                    "status": int(item.status_code),
                    "from_record": _zenodo_record_from_url(str(item.url))
                    or requested_record,
                    "to_record": next_record,
                }
            )
        self._last_resolution = {
            "requested_record": requested_record,
            "resolved_record": resolved_record,
            "record_resolution": resolution_evidence,
        }
        if response.status_code == 404:
            raise ArchiveDatasetError(
                f"Zenodo record 不存在：{record}",
                error_code="archive_record_not_found",
                error_class="resource_not_found",
            )
        if response.status_code == 410:
            tombstone: dict[str, Any] = {}
            try:
                body = response.json()
                if isinstance(body, dict) and isinstance(body.get("tombstone"), dict):
                    tombstone = body["tombstone"]
            except (ValueError, requests.RequestException):
                pass
            resolution_evidence.append(
                {
                    "kind": "terminal_response",
                    "status": 410,
                    "record": resolved_record,
                    "state": "record_deleted",
                }
            )
            raise ArchiveDatasetError(
                f"Zenodo record 已删除：请求={requested_record}，解析={resolved_record}",
                error_code="archive_record_gone",
                error_class="record_withdrawn",
                diagnostics={
                    "status": "record_gone",
                    "requested_record": requested_record,
                    "resolved_record": resolved_record,
                    "record_exists": False,
                    "requested_record_exists": bool(response.history),
                    "resolved_record_exists": False,
                    "record_resolution": resolution_evidence,
                    "tombstone": {
                        "state": "record_deleted",
                        "removal_date": tombstone.get("removal_date"),
                        "is_visible": tombstone.get("is_visible"),
                        "removal_reason": (tombstone.get("removal_reason") or {}).get(
                            "id"
                        ),
                        "deletion_policy": (tombstone.get("deletion_policy") or {}).get(
                            "id"
                        ),
                    },
                },
            )
        response.raise_for_status()
        payload = response.json()
        files = _record_files(payload)
        return payload, files

    def _public_version(
        self, payload: dict[str, Any], record: str
    ) -> tuple[str | None, str | None]:
        metadata = payload.get("metadata") or {}
        version = str(metadata.get("version") or "").strip()
        if version:
            return version, "zenodo_metadata"
        try:
            response = self.session.get(
                f"https://zenodo.org/records/{record}", timeout=30
            )
            response.raise_for_status()
        except requests.RequestException:
            return None, None
        match = _ZENODO_VERSION.search(response.text)
        if not match:
            return None, None
        version = html.unescape(match.group(1)).strip()
        return (version, "zenodo_public_page") if version else (None, None)

    def _range(self, url: str, start: int, end: int) -> bytes:
        expected = end - start + 1
        with self.session.get(
            url,
            headers={"Range": f"bytes={start}-{end}", "Accept-Encoding": "identity"},
            timeout=(20, 30),
            allow_redirects=True,
            stream=True,
        ) as response:
            content_range = str(response.headers.get("Content-Range") or "")
            if response.status_code != 206 or not content_range.lower().startswith(
                "bytes "
            ):
                raise ArchiveDatasetError(
                    f"远程归档不支持所需 Range 请求，状态={response.status_code}",
                    error_code="remote_range_not_supported",
                    error_class="transport_contract_unavailable",
                )
            chunks: list[bytes] = []
            received = 0
            for chunk in response.iter_content(min(1_048_576, expected)):
                if not chunk:
                    continue
                received += len(chunk)
                if received > expected:
                    raise ArchiveDatasetError(
                        "Range 响应超过请求字节预算",
                        error_code="remote_range_budget_exceeded",
                        error_class="transport_contract_unavailable",
                    )
                chunks.append(chunk)
            if received != expected:
                raise ArchiveDatasetError(
                    f"Range 响应字节数不一致：预期={expected}，实际={received}",
                    error_code="remote_range_incomplete",
                    error_class="network_error",
                )
            return b"".join(chunks)

    def _persist_remote_entry(
        self, archive_key: str, entry_name: str, body: bytes
    ) -> Path:
        archive_token = hashlib.sha256(archive_key.encode("utf-8")).hexdigest()[:16]
        entry_token = hashlib.sha256(entry_name.encode("utf-8")).hexdigest()[:24]
        path = (
            self.output_dir
            / "remote_inventory_entries"
            / archive_token
            / f"{entry_token}.raw"
        )
        _atomic_bytes(path, body)
        return path

    def _remote_zip_inventory(
        self, file: dict[str, Any], max_small_text_bytes: int
    ) -> dict[str, Any]:
        size = int(file["bytes"])
        tail_start = max(0, size - 65_557)
        tail = self._range(file["_url"], tail_start, size - 1)
        index = tail.rfind(_EOCD)
        if index < 0 or len(tail) < index + 22:
            raise ArchiveDatasetError(
                "远程 ZIP 未找到 EOCD",
                error_code="zip_eocd_not_found",
                error_class="archive_format_error",
            )
        (
            _,
            disk,
            central_disk,
            disk_entries,
            total_entries,
            central_size,
            central_offset,
            _,
        ) = struct.unpack_from("<4s4H2LH", tail, index)
        if (
            disk
            or central_disk
            or disk_entries != total_entries
            or 0xFFFF in {disk_entries, total_entries}
        ):
            raise ArchiveDatasetError(
                "当前仅支持单卷非 ZIP64 远程 ZIP",
                error_code="zip_layout_not_supported",
                error_class="archive_format_error",
            )
        central = self._range(
            file["_url"], central_offset, central_offset + central_size - 1
        )
        entries: list[RemoteArchiveEntry] = []
        offset = 0
        while offset < len(central):
            if central[offset : offset + 4] != _CENTRAL or offset + 46 > len(central):
                raise ArchiveDatasetError(
                    "ZIP central directory 结构无效",
                    error_code="zip_central_directory_invalid",
                    error_class="archive_format_error",
                )
            (
                flags,
                method,
                _modified_time,
                _modified_date,
                crc32,
                compressed,
                uncompressed,
            ) = struct.unpack_from("<HHHHLLL", central, offset + 8)
            name_len, extra_len, comment_len = struct.unpack_from(
                "<HHH", central, offset + 28
            )
            local_offset = struct.unpack_from("<L", central, offset + 42)[0]
            name_bytes = central[offset + 46 : offset + 46 + name_len]
            name = name_bytes.decode("utf-8" if flags & 0x800 else "cp437")
            entries.append(
                RemoteArchiveEntry(
                    _safe_name(name),
                    compressed,
                    uncompressed,
                    method,
                    crc32,
                    local_offset,
                )
            )
            offset += 46 + name_len + extra_len + comment_len
        if len(entries) != total_entries:
            raise ArchiveDatasetError(
                f"ZIP entry 数不一致：EOCD={total_entries}，解析={len(entries)}",
                error_code="zip_entry_count_mismatch",
                error_class="archive_format_error",
            )
        small_text: list[dict[str, Any]] = []
        entry_errors: list[dict[str, Any]] = []
        for entry in entries:
            if entry.packaging_artifact_type():
                continue
            if (
                not entry.name.lower().endswith((".json", ".txt"))
                or entry.uncompressed_bytes > max_small_text_bytes
            ):
                continue
            header = self._range(
                file["_url"], entry.local_header_offset, entry.local_header_offset + 29
            )
            if header[:4] != _LOCAL:
                continue
            name_len, extra_len = struct.unpack_from("<HH", header, 26)
            data_start = entry.local_header_offset + 30 + name_len + extra_len
            compressed = self._range(
                file["_url"], data_start, data_start + entry.compressed_bytes - 1
            )
            if entry.compression == 0:
                body = compressed
            elif entry.compression == 8:
                body = zlib.decompress(compressed, -15)
            else:
                continue
            if (
                len(body) != entry.uncompressed_bytes
                or zlib.crc32(body) & 0xFFFFFFFF != entry.crc32
            ):
                raise ArchiveDatasetError(
                    f"远程 ZIP 小文本校验失败：{entry.name}",
                    error_code="remote_entry_integrity_mismatch",
                    error_class="integrity_mismatch",
                )
            item: dict[str, Any] = {
                "name": entry.name,
                "bytes": len(body),
                "sha256": hashlib.sha256(body).hexdigest(),
                "decode_status": "not_attempted",
            }
            try:
                raw_path = self._persist_remote_entry(file["key"], entry.name, body)
                item["raw_path"] = str(raw_path)
            except OSError as exc:
                error = {
                    "entry_path": entry.name,
                    "error_code": "archive_entry_persist_failed",
                    "error_class": "io_error",
                    "operation": "persist_raw_entry",
                    "exception_type": type(exc).__name__,
                }
                item.update({"decode_status": "blocked", "error": error})
                entry_errors.append(error)
                small_text.append(item)
                continue
            encoding_attempts = ["utf-8-sig"]
            try:
                text = body.decode("utf-8-sig", errors="strict")
            except UnicodeDecodeError as exc:
                error = {
                    "entry_path": entry.name,
                    "error_code": "archive_entry_decode_failed",
                    "error_class": "archive_entry_decode_error",
                    "encoding_attempts": encoding_attempts,
                    "failure_byte_offset": exc.start,
                }
                item.update({"decode_status": "failed", "error": error})
                entry_errors.append(error)
                small_text.append(item)
                continue
            item.update(
                {
                    "decode_status": "decoded",
                    "encoding": "utf-8-sig",
                    "encoding_attempts": encoding_attempts,
                }
            )
            if entry.name.lower().endswith(".json"):
                try:
                    item["json"] = json.loads(text)
                except json.JSONDecodeError as exc:
                    error = {
                        "entry_path": entry.name,
                        "error_code": "archive_entry_json_invalid",
                        "error_class": "archive_entry_parse_error",
                        "encoding_attempts": encoding_attempts,
                        "line": exc.lineno,
                        "column": exc.colno,
                    }
                    item.update(
                        {"decode_status": "decoded_parse_failed", "error": error}
                    )
                    entry_errors.append(error)
            else:
                item["text"] = text
            small_text.append(item)
        counts: dict[str, int] = {}
        for entry in entries:
            kind = entry.public()["type"]
            counts[kind] = counts.get(kind, 0) + 1
        packaging_artifacts = [
            entry.public() for entry in entries if entry.packaging_artifact_type()
        ]
        manifest_summaries = []
        for item in small_text:
            value = item.get("json")
            if isinstance(value, dict):
                manifest_summaries.append(
                    {
                        "name": item["name"],
                        "labels": value.get("labels"),
                        "numTraining": value.get("numTraining"),
                        "numTest": value.get("numTest"),
                    }
                )
        return {
            "format": "zip",
            "inventory_method": "http_range_central_directory",
            "payload_bytes_transferred": 0,
            "entry_count": len(entries),
            "scientific_entry_count": len(entries) - len(packaging_artifacts),
            "packaging_artifact_count": len(packaging_artifacts),
            "entry_type_counts": counts,
            "entries": [entry.public() for entry in entries],
            "packaging_artifacts": packaging_artifacts,
            "small_text_entries": small_text,
            "small_text_summary": {
                "selected": len(small_text),
                "decoded": sum(
                    item.get("decode_status") == "decoded" for item in small_text
                ),
                "failed": len(entry_errors),
            },
            "entry_errors": entry_errors,
            "manifest_summaries": manifest_summaries,
        }

    @staticmethod
    def _file_identity(files: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return sorted(
            (
                {
                    "key": item.get("key"),
                    "bytes": int(item.get("bytes") or 0),
                    "checksum": item.get("checksum") or {},
                }
                for item in files
            ),
            key=lambda item: str(item["key"]),
        )

    def _load_existing_record(self) -> dict[str, Any] | None:
        path = self.output_dir / "archive_dataset_record.json"
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ArchiveDatasetError(
                "既有归档数据集记录无法读取",
                error_code="archive_state_invalid",
                error_class="state_conflict",
            ) from exc
        if not isinstance(value, dict) or value.get("schema_version") != SCHEMA:
            raise ArchiveDatasetError(
                "既有归档数据集记录 schema 不兼容",
                error_code="archive_state_schema_conflict",
                error_class="state_conflict",
            )
        return value

    def _compatible_existing_evidence(
        self,
        existing: dict[str, Any] | None,
        *,
        record: str,
        version: str | None,
        files: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if existing is None:
            return None
        compatible = (
            existing.get("source") == self.source_name
            and str(existing.get("record")) == str(record)
            and existing.get("version") == version
            and self._file_identity(existing.get("files") or [])
            == self._file_identity(files)
        )
        if not compatible:
            raise ArchiveDatasetError(
                f"同一输出目录中的归档记录身份与当前 {self.source_name} record/version/files 不一致",
                error_code="archive_state_identity_conflict",
                error_class="state_conflict",
            )
        return existing

    def inspect(
        self,
        record: str,
        *,
        remote_inventory: bool = False,
        max_small_text_bytes: int = 1_048_576,
    ) -> dict[str, Any]:
        with _archive_record_lock(
            self.output_dir, getattr(self, "lock_timeout_seconds", 30.0)
        ):
            return self._inspect_unlocked(
                record,
                remote_inventory=remote_inventory,
                max_small_text_bytes=max_small_text_bytes,
            )

    def _inspect_unlocked(
        self,
        record: str,
        *,
        remote_inventory: bool,
        max_small_text_bytes: int,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        payload, files = self._metadata(record)
        resolution = getattr(
            self,
            "_last_resolution",
            {
                "requested_record": str(record),
                "resolved_record": str(record),
                "record_resolution": [],
            },
        )
        metadata = payload.get("metadata") or {}
        version, version_source = self._public_version(payload, record)
        public_files = [
            {key: value for key, value in file.items() if key != "_url"}
            for file in files
        ]
        access_status = _access_status(payload)
        existing = self._load_existing_record()
        if not files:
            restricted = _access_is_restricted(access_status)
            result = {
                "schema_version": SCHEMA,
                "status": "access_restricted" if restricted else "files_not_available",
                "source": self.source_name,
                "record": str(record),
                **resolution,
                "record_exists": True,
                "concept_record": str(payload.get("conceptrecid") or "") or None,
                "doi": payload.get("doi") or metadata.get("doi"),
                "resource_doi": payload.get("resource_doi"),
                "title": metadata.get("title"),
                "version": version,
                "version_source": version_source,
                "license": _license(payload),
                "access": access_status,
                "files": [],
                "files_visible": False,
                "remote_archives": {},
                "warning_count": 0,
                "warnings": [],
                "materialization": [],
                "readiness": {"manifest_ready": False, "payload_ready": False},
                "transport": getattr(self, "_transport", None),
                "transport_attempts": getattr(self, "_transport_attempts", []),
                "error_code": (
                    "archive_access_restricted"
                    if restricted
                    else "archive_files_not_available"
                ),
                "error_class": "access_restricted"
                if restricted
                else "resource_not_available",
                "access_requirement": "authentication_required" if restricted else None,
                "message": (
                    f"{self.record_label} 存在，但公开 API 不提供受限文件清单"
                    if restricted
                    else f"{self.record_label} 存在，但没有可见文件"
                ),
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
            }
            _atomic_json(self.output_dir / "archive_dataset_record.json", result)
            return result
        existing = self._compatible_existing_evidence(
            existing,
            record=str(record),
            version=version,
            files=public_files,
        )
        inventories: dict[str, Any] = {}
        if remote_inventory:
            for file in files:
                if file["key"].lower().endswith(".zip"):
                    inventories[file["key"]] = self._remote_zip_inventory(
                        file, max_small_text_bytes
                    )
        elif existing:
            inventories = dict(existing.get("remote_archives") or {})
        warnings = [
            {"archive_key": archive_key, **error}
            for archive_key, inventory in inventories.items()
            for error in inventory.get("entry_errors", [])
        ]
        materialized = []
        for file in files:
            target = self.output_dir / file["key"]
            algorithm = file["checksum"]["algorithm"]
            digest = file["checksum"]["value"]
            ready = target.is_file() and target.stat().st_size == file["bytes"]
            if ready and algorithm and digest:
                ready = self._hash_file(target, algorithm) == digest
            materialized.append(
                {
                    "key": file["key"],
                    "path": str(target),
                    "bytes": target.stat().st_size if target.exists() else 0,
                    "checksum_verified": ready,
                }
            )
        readiness = {
            "manifest_ready": bool(files)
            and (not remote_inventory or bool(inventories)),
            "payload_ready": bool(materialized)
            and all(item["checksum_verified"] for item in materialized),
        }
        result = {
            "schema_version": SCHEMA,
            "status": "payload_ready"
            if readiness["payload_ready"]
            else "manifest_ready"
            if readiness["manifest_ready"]
            else "incomplete",
            "source": self.source_name,
            "record": str(record),
            **resolution,
            "record_exists": True,
            "concept_record": str(payload.get("conceptrecid") or "") or None,
            "doi": payload.get("doi") or metadata.get("doi"),
            "resource_doi": payload.get("resource_doi"),
            "title": metadata.get("title"),
            "version": version,
            "version_source": version_source,
            "license": _license(payload),
            "access": access_status,
            "files": public_files,
            "files_visible": True,
            "remote_archives": inventories,
            "warning_count": len(warnings),
            "warnings": warnings,
            "materialization": materialized,
            "readiness": readiness,
            "transport": getattr(self, "_transport", None),
            "transport_attempts": getattr(self, "_transport_attempts", []),
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }
        _atomic_json(self.output_dir / "archive_dataset_record.json", result)
        return result

    @staticmethod
    def _hash_file(path: Path, algorithm: str) -> str:
        hasher = hashlib.new(algorithm)
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest().lower()

    def download(
        self, record: str, key: str, *, resume: bool, verify_checksum: bool
    ) -> dict[str, Any]:
        with _archive_record_lock(
            self.output_dir, getattr(self, "lock_timeout_seconds", 30.0)
        ):
            return self._download_unlocked(
                record,
                key,
                resume=resume,
                verify_checksum=verify_checksum,
            )

    def _download_unlocked(
        self, record: str, key: str, *, resume: bool, verify_checksum: bool
    ) -> dict[str, Any]:
        payload, files = self._metadata(record)
        if not files:
            access_status = _access_status(payload)
            restricted = _access_is_restricted(access_status)
            raise ArchiveDatasetError(
                (
                    f"{self.record_label} 存在，但公开 API 不提供受限文件清单"
                    if restricted
                    else f"{self.record_label} 存在，但没有可见文件"
                ),
                error_code=(
                    "archive_access_restricted"
                    if restricted
                    else "archive_files_not_available"
                ),
                error_class="access_restricted"
                if restricted
                else "resource_not_available",
            )
        version, _version_source = self._public_version(payload, record)
        public_files = [
            {field: value for field, value in item.items() if field != "_url"}
            for item in files
        ]
        self._compatible_existing_evidence(
            self._load_existing_record(),
            record=str(record),
            version=version,
            files=public_files,
        )
        matches = [file for file in files if file["key"] == key]
        if not matches:
            raise ArchiveDatasetError(
                f"{self.record_label} 中未找到文件：{key}",
                error_code="archive_file_not_found",
                error_class="resource_not_found",
            )
        file = matches[0]
        target = self.output_dir / file["key"]
        target.parent.mkdir(parents=True, exist_ok=True)
        partial = target.with_name(target.name + ".part")
        offset = partial.stat().st_size if resume and partial.exists() else 0
        resumed_from_bytes = offset
        stream_attempts = 0
        while (partial.stat().st_size if partial.exists() else 0) < file["bytes"]:
            stream_attempts += 1
            offset = partial.stat().st_size if partial.exists() else 0
            mode = "ab" if offset else "wb"
            try:
                with self.session.get(
                    file["_url"],
                    headers={"Range": f"bytes={offset}-"} if offset else {},
                    stream=True,
                    timeout=(30, 120),
                    allow_redirects=True,
                ) as response:
                    if offset and response.status_code != 206:
                        offset = 0
                        mode = "wb"
                    response.raise_for_status()
                    with partial.open(mode) as handle:
                        for chunk in response.iter_content(4 * 1024 * 1024):
                            if chunk:
                                handle.write(chunk)
                        handle.flush()
                        os.fsync(handle.fileno())
            except requests.RequestException:
                if stream_attempts >= 4:
                    raise
                time.sleep(min(2.0, 0.25 * (2 ** (stream_attempts - 1))))
                continue
            if partial.stat().st_size >= file["bytes"]:
                break
            if stream_attempts >= 4:
                break
        if partial.stat().st_size != file["bytes"]:
            raise ArchiveDatasetError(
                f"下载字节数不一致：预期={file['bytes']}，实际={partial.stat().st_size}",
                error_code="archive_download_incomplete",
                error_class="network_error",
            )
        algorithm = file["checksum"]["algorithm"]
        expected = file["checksum"]["value"]
        actual = self._hash_file(partial, algorithm) if algorithm else None
        if (expected and actual != expected) or (verify_checksum and not expected):
            raise ArchiveDatasetError(
                f"{self.record_label} checksum 校验失败",
                error_code="archive_checksum_mismatch",
                error_class="integrity_mismatch",
            )
        os.replace(partial, target)
        result = self._inspect_unlocked(
            record,
            remote_inventory=False,
            max_small_text_bytes=1_048_576,
        )
        result["download"] = {
            "key": key,
            "path": str(target),
            "bytes": target.stat().st_size,
            "checksum": {
                "algorithm": algorithm,
                "expected": expected,
                "actual": actual,
                "verified": bool(expected and actual == expected),
            },
            "resumed_from_bytes": resumed_from_bytes,
            "stream_attempts": stream_attempts,
        }
        _atomic_json(self.output_dir / "archive_dataset_record.json", result)
        return result


class FigshareArchiveStore(ZenodoArchiveStore):
    """Figshare/ACS Figshare 公共 article 的轻量归档适配器。"""

    source_name = "figshare"
    record_label = "Figshare article"

    def _metadata(self, record: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        url = f"https://api.figshare.com/v2/articles/{record}"
        response = self.session.get(url, timeout=30)
        route = str(getattr(self, "_transport", {}).get("route") or "direct")
        attempts = list(getattr(self, "_transport_attempts", []))
        attempts.append({"route": route, "status": int(response.status_code)})
        fallback_proxy = _figshare_archive_fallback_proxy()
        current_proxy = (
            _configured_proxy("ARCHIVE_PROXY") if route == "archive_proxy" else None
        )
        if (
            response.status_code == 403
            and fallback_proxy
            and fallback_proxy != current_proxy
        ):
            fallback_session = _session(fallback_proxy)
            fallback_response = fallback_session.get(url, timeout=30)
            attempts.append(
                {
                    "route": "archive_proxy_fallback",
                    "status": int(fallback_response.status_code),
                    "trigger": "figshare_rest_http_403",
                }
            )
            if fallback_response.status_code < 400:
                self.session.close()
                self.session = fallback_session
                self._transport = {
                    "route": "archive_proxy_fallback",
                    "trust_env": False,
                    "proxy_configured": True,
                    "trigger": "figshare_rest_http_403",
                }
                response = fallback_response
            else:
                fallback_session.close()
                response = fallback_response
        self._transport_attempts = attempts
        self._last_resolution = {
            "requested_record": str(record),
            "resolved_record": str(record),
            "record_resolution": [],
        }
        if response.status_code == 404:
            raise ArchiveDatasetError(
                f"Figshare article 不存在：{record}",
                error_code="archive_record_not_found",
                error_class="resource_not_found",
            )
        if response.status_code == 403:
            raise ArchiveDatasetError(
                f"Figshare 公共 REST API 拒绝当前网络出口：{record}",
                error_code="archive_repository_access_forbidden",
                error_class="access_blocked",
                diagnostics={
                    "transport": getattr(self, "_transport", None),
                    "transport_attempts": attempts,
                },
            )
        response.raise_for_status()
        raw = response.json()
        payload = {
            **raw,
            "metadata": {
                "title": raw.get("title"),
                "version": raw.get("version"),
                "license": raw.get("license"),
                "access_right": "open",
            },
            "files": raw.get("files") or [],
        }
        return payload, _record_files(payload)

    def _public_version(
        self, payload: dict[str, Any], record: str
    ) -> tuple[str | None, str | None]:
        version = payload.get("version")
        return (
            (str(version), "figshare_metadata") if version is not None else (None, None)
        )
