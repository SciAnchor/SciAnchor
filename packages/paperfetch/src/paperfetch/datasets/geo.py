"""轻量、可审计的 GEO/GSE 下载与本地归档实现。

公共契约从已经选定的 GSE accession 开始；科研数据集发现和队列纳入决策不属于 SPC。
"""

from __future__ import annotations

from paperfetch.core.environment import SERVER_PRODUCTION_ROOT
import contextlib
import gzip
import hashlib
import json
import os
import re
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional
from urllib.parse import quote, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from paperfetch.datasets.acquisition import (
    AcquisitionBusy,
    DownloadCoordinator,
    RouteDecision,
    build_acquisition_plan,
    default_host_id,
    error_payload,
    resolve_coordination_root,
    source_route_from_environment,
    write_acquisition_report,
)
from paperfetch.observability import get_event_logger

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback is exercised downstream.
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - POSIX uses fcntl instead.
    msvcrt = None


GSE_PATTERN = re.compile(r"^GSE([1-9]\d*)$", re.IGNORECASE)
ACCESSION_PATTERNS = {
    "sra_projects": re.compile(r"\b(?:SRP|ERP|DRP)\d{3,}\b", re.IGNORECASE),
    "sra_runs": re.compile(r"\b(?:SRR|ERR|DRR)\d{3,}\b", re.IGNORECASE),
    "sra_experiments": re.compile(r"\b(?:SRX|ERX|DRX)\d{3,}\b", re.IGNORECASE),
    "sra_samples": re.compile(r"\b(?:SRS|ERS|DRS)\d{3,}\b", re.IGNORECASE),
    "bioprojects": re.compile(r"\bPRJ[A-Z]{2}\d{3,}\b", re.IGNORECASE),
    "biosamples": re.compile(r"\bSAM[NED]\d{3,}\b", re.IGNORECASE),
}
DEFAULT_MAX_DOWNLOAD_GB = 20.0
GEO_FTP_ROOT = "https://ftp.ncbi.nlm.nih.gov/geo/series"
GEO_SAMPLE_ROOT = "https://ftp.ncbi.nlm.nih.gov/geo/samples"
STATE_FILENAME = "download_state.json"
ARCHIVE_FILENAME = "archive.json"
logger = get_event_logger("paperfetch.datasets.geo")


def _env_float(name: str, default: float, *, minimum: float) -> float:
    try:
        return max(minimum, float(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int, *, minimum: int) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


class GeoDataError(RuntimeError):
    """GEO 数据通路的基础异常。"""

    error_code = "geo_acquisition_failed"
    error_class = "acquisition_failed"

    def __init__(
        self,
        message: str,
        *,
        error_code: str | None = None,
        error_class: str | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code or type(self).error_code
        self.error_class = error_class or type(self).error_class


class GeoFilesystemError(GeoDataError):
    """保留文件系统原始错误和具体操作，供 Agent 诊断与安全续传。"""

    error_code = "filesystem_operation_failed"
    error_class = "io_error"

    def __init__(self, operation: str, path: Path, exc: OSError) -> None:
        self.diagnostics = {
            "operation": operation,
            "path": str(path.resolve()),
            "exception_type": type(exc).__name__,
            "errno": getattr(exc, "errno", None),
            "winerror": getattr(exc, "winerror", None),
            "strerror": getattr(exc, "strerror", None),
        }
        detail = f"{operation} 失败：{type(exc).__name__}"
        if getattr(exc, "errno", None) is not None:
            detail += f" errno={exc.errno}"
        if getattr(exc, "winerror", None) is not None:
            detail += f" WinError={exc.winerror}"
        super().__init__(detail)


class GeoLargeDownloadBlocked(GeoDataError):
    """下载计划超过已配置的大文件门禁。"""

    error_code = "large_download_approval_required"
    error_class = "policy_blocked"

    def __init__(self, plan: dict[str, Any]):
        self.plan = plan
        limit = plan["size_gate"]["max_bytes"]
        total = plan["totals"]["known_bytes"]
        unknown = plan["totals"]["unknown_size_files"]
        if unknown:
            reason = f"以下远端文件大小未知：{', '.join(unknown)}"
        else:
            reason = f"总大小 {total} 字节超过限制 {limit} 字节"
        super().__init__(f"GEO 下载需要明确授权：{reason}")


@dataclass(frozen=True)
class GeoRemoteFile:
    filename: str
    kind: str
    url: str
    size_bytes: Optional[int] = None
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    size_exact: bool = False
    discovery_source: str = "directory_listing"
    source_manifest_url: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_gse_id(value: str) -> str:
    candidate = (value or "").strip().upper()
    if not GSE_PATTERN.fullmatch(candidate):
        raise GeoDataError(
            f"无效的 GSE accession：{value!r}",
            error_code="invalid_gse_accession",
            error_class="invalid_argument",
        )
    return candidate


def geo_ftp_prefix(gse_id: str) -> str:
    normalized = normalize_gse_id(gse_id)
    digits = normalized[3:]
    return "GSEnnn" if len(digits) <= 3 else f"GSE{digits[:-3]}nnn"


def resolve_geo_root(output_dir: Optional[str | os.PathLike[str]] = None) -> Path:
    configured = output_dir or os.getenv("SPC_GEO_DATA_ROOT") or "~/.cache/spc/geo"
    return Path(configured).expanduser().resolve()


def configured_max_download_gb() -> float:
    value = os.getenv("SPC_GEO_MAX_DOWNLOAD_GB")
    if value is None:
        return DEFAULT_MAX_DOWNLOAD_GB
    try:
        return float(value)
    except (TypeError, ValueError):
        return DEFAULT_MAX_DOWNLOAD_GB


def _ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        path.chmod(path.stat().st_mode | 0o2775)


def _chmod_shared_file(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.chmod(0o664)


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    _ensure_directory(path.parent)
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.", dir=path.parent
        )
    except OSError as exc:
        raise GeoFilesystemError("checkpoint_temp_create", path, exc) from exc
    temporary = Path(temporary_name)
    try:
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise GeoFilesystemError(
                "checkpoint_temp_write_fsync", temporary, exc
            ) from exc
        _chmod_shared_file(temporary)
        last_error: OSError | None = None
        for attempt in range(5):
            try:
                os.replace(temporary, path)
                last_error = None
                break
            except OSError as exc:
                last_error = exc
                if attempt < 4:
                    time.sleep(0.05 * (attempt + 1))
        if last_error is not None:
            raise GeoFilesystemError(
                "checkpoint_replace", path, last_error
            ) from last_error
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def load_json(path: Path) -> Optional[dict[str, Any]]:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise GeoDataError(
            f"无法读取 GEO 状态文件 {path}：{exc}",
            error_code="geo_state_read_failed",
            error_class="io_error",
        ) from exc
    if not isinstance(value, dict):
        raise GeoDataError(
            f"GEO 状态文件必须包含 JSON 对象：{path}",
            error_code="geo_state_format_invalid",
            error_class="integrity_mismatch",
        )
    return value


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_size(value: str) -> Optional[int]:
    compact = (value or "").strip().replace(",", "")
    match = re.fullmatch(
        r"(\d+(?:\.\d+)?)\s*([KMGTPE]?)(?:i?B)?", compact, re.IGNORECASE
    )
    if not match:
        return None
    amount = float(match.group(1))
    exponent = "KMGTPE".find(match.group(2).upper()) + 1 if match.group(2) else 0
    return int(amount * (1024**exponent))


class GeoDatasetLock:
    """Cross-process lock scoped to one GSE accession."""

    def __init__(self, path: Path, timeout_seconds: float = 30.0):
        self.path = path
        self.timeout_seconds = timeout_seconds
        self._handle: Any = None

    def __enter__(self) -> "GeoDatasetLock":
        _ensure_directory(self.path.parent)
        self._handle = self.path.open("a+b")
        _chmod_shared_file(self.path)
        if fcntl is None and msvcrt is None:
            return self
        if msvcrt is not None:
            self._handle.seek(0, os.SEEK_END)
            if self._handle.tell() == 0:
                self._handle.write(b"\0")
                self._handle.flush()
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            try:
                if fcntl is not None:
                    fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    self._handle.seek(0)
                    msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
                return self
            except (BlockingIOError, OSError) as exc:
                if time.monotonic() >= deadline:
                    self._handle.close()
                    self._handle = None
                    raise GeoDataError(
                        f"等待数据集锁超时：{self.path.name}",
                        error_code="resource_busy",
                        error_class="resource_busy",
                    ) from exc
                time.sleep(0.1)

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._handle is None:
            return
        try:
            if fcntl is not None:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:
                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            self._handle.close()
            self._handle = None


def _new_http_session() -> requests.Session:
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=0.75,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session = requests.Session()
    decision = source_route_from_environment("geo")
    proxy = decision.proxy_url
    session.trust_env = False
    if proxy:
        session.proxies.update({"http": proxy, "https": proxy})
    session._spc_route_decision = decision
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    tool = os.getenv("NCBI_TOOL", "spc")
    email = os.getenv("NCBI_EMAIL")
    identity = f"{tool}/0.2"
    if email:
        identity = f"{identity} ({email})"
    session.headers.update(
        {"User-Agent": identity, "Accept": "*/*", "Accept-Encoding": "identity"}
    )
    logger.info(
        "[GEO 网络] HTTP 会话已配置，代理=%s",
        ("DOWNLOAD_PROXY/SPC_GEO_PROXY" if proxy else "严格直连"),
        diagnostics={"proxy_mode": (decision.route)},
    )
    return session


class GeoDatasetStore:
    """Discover, download and verify public files attached to GSE records."""

    def __init__(
        self,
        output_dir: Optional[str | os.PathLike[str]] = None,
        *,
        session: Optional[requests.Session] = None,
        timeout_seconds: Optional[float] = None,
        connect_timeout_seconds: Optional[float] = None,
        max_download_gb: float = DEFAULT_MAX_DOWNLOAD_GB,
        lock_timeout_seconds: float = 30.0,
        coordination_root: Optional[str | os.PathLike[str]] = None,
        dataset_concurrency: Optional[int] = None,
        host_id: Optional[str] = None,
    ):
        self.root = resolve_geo_root(output_dir)
        self.session = session or _new_http_session()
        self._owns_session = session is None
        self.route_decision = getattr(
            self.session,
            "_spc_route_decision",
            RouteDecision("direct", None, None, None),
        )
        self.connect_timeout_seconds = (
            max(1.0, float(connect_timeout_seconds))
            if connect_timeout_seconds is not None
            else _env_float("SPC_GEO_CONNECT_TIMEOUT", 15.0, minimum=1.0)
        )
        self.timeout_seconds = (
            max(1.0, float(timeout_seconds))
            if timeout_seconds is not None
            else _env_float("SPC_GEO_READ_TIMEOUT", 300.0, minimum=1.0)
        )
        self.stream_retries = _env_int("SPC_GEO_STREAM_RETRIES", 20, minimum=0)
        self.progress_interval_seconds = _env_float(
            "SPC_GEO_PROGRESS_INTERVAL", 10.0, minimum=0.1
        )
        self.progress_interval_bytes = _env_int(
            "SPC_GEO_PROGRESS_BYTES", 8 * 1024 * 1024, minimum=1024
        )
        self.max_download_bytes = int(max_download_gb * 1024**3)
        self.lock_timeout_seconds = lock_timeout_seconds
        self.host_id = host_id or os.getenv("SPC_HOST_ID") or default_host_id()
        self.coordination_root = resolve_coordination_root(
            coordination_root,
            data_root=self.root,
        )
        self.coordinator = DownloadCoordinator(
            self.coordination_root,
            dataset_concurrency=dataset_concurrency,
            lock_timeout_seconds=lock_timeout_seconds,
        )

    def close(self) -> None:
        if self._owns_session:
            self.session.close()

    def __enter__(self) -> "GeoDatasetStore":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    @staticmethod
    def dataset_base_url(gse_id: str) -> str:
        normalized = normalize_gse_id(gse_id)
        return f"{GEO_FTP_ROOT}/{geo_ftp_prefix(normalized)}/{normalized}"

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault(
            "timeout", (self.connect_timeout_seconds, self.timeout_seconds)
        )
        response = self.session.request(method, url, **kwargs)
        return response

    def _probe(self, url: str) -> tuple[Optional[int], Optional[str], Optional[str]]:
        response = self._request("HEAD", url, allow_redirects=True)
        try:
            if response.status_code in {403, 405}:
                response.close()
                response = self._request("GET", url, stream=True, allow_redirects=True)
            response.raise_for_status()
            size = response.headers.get("Content-Length")
            content_range = response.headers.get("Content-Range")
            if content_range and "/" in content_range:
                size = content_range.rsplit("/", 1)[-1]
            return (
                int(size) if size and size.isdigit() else None,
                response.headers.get("ETag"),
                response.headers.get("Last-Modified"),
            )
        finally:
            response.close()

    def _directory_files(self, url: str, kind: str) -> list[GeoRemoteFile]:
        response = self._request("GET", url)
        if response.status_code == 404:
            response.close()
            return []
        try:
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            files: list[GeoRemoteFile] = []
            for anchor in soup.find_all("a", href=True):
                href = str(anchor.get("href") or "")
                if not href or href.startswith(("?", "#")) or href.endswith("/"):
                    continue
                parsed_href = urlparse(href)
                if parsed_href.scheme or parsed_href.netloc:
                    continue
                filename = Path(unquote(urlparse(href).path)).name
                if not filename or filename in {".", ".."}:
                    continue
                size = None
                row = anchor.find_parent("tr")
                if row is not None:
                    cells = [
                        cell.get_text(" ", strip=True) for cell in row.find_all("td")
                    ]
                    for cell in reversed(cells):
                        size = _parse_size(cell)
                        if size is not None:
                            break
                if size is None and isinstance(anchor.next_sibling, str):
                    for token in reversed(anchor.next_sibling.split()):
                        size = _parse_size(token)
                        if size is not None:
                            break
                files.append(
                    GeoRemoteFile(
                        filename=filename,
                        kind=kind,
                        url=urljoin(url, href),
                        size_bytes=size,
                        size_exact=False,
                    )
                )
            return files
        finally:
            response.close()

    @staticmethod
    def _sample_supplementary_url(filename: str) -> Optional[str]:
        match = re.match(r"^(GSM[1-9]\d*)_", filename, re.IGNORECASE)
        if match is None:
            return None
        gsm = match.group(1).upper()
        digits = gsm[3:]
        prefix = "GSMnnn" if len(digits) <= 3 else f"GSM{digits[:-3]}nnn"
        return f"{GEO_SAMPLE_ROOT}/{prefix}/{gsm}/suppl/{quote(filename)}"

    def _filelist_entries(
        self,
        gse_id: str,
        available: list[GeoRemoteFile],
    ) -> tuple[list[GeoRemoteFile], dict[str, Any]]:
        manifests = [
            item for item in available if item.filename.lower() == "filelist.txt"
        ]
        if not manifests:
            return [], {"status": "not_available", "sources": [], "entries": 0}

        entries: dict[str, GeoRemoteFile] = {}
        sources: list[str] = []
        failures: list[dict[str, str]] = []
        base = self.dataset_base_url(gse_id)
        for manifest in manifests:
            sources.append(manifest.url)
            try:
                response = self._request("GET", manifest.url, allow_redirects=True)
                try:
                    response.raise_for_status()
                    text = response.text
                finally:
                    response.close()
            except requests.RequestException as exc:
                failures.append(
                    {"url": manifest.url, "error_class": type(exc).__name__}
                )
                continue

            for raw_line in text.splitlines():
                columns = raw_line.rstrip("\r\n").split("\t")
                if len(columns) < 4 or columns[0].strip().lower() != "file":
                    continue
                filename = Path(columns[1].strip()).name
                size_text = columns[3].strip()
                if not filename or not size_text.isdigit():
                    continue
                url = self._sample_supplementary_url(filename)
                if url is None:
                    url = f"{base}/suppl/{quote(filename)}"
                entries.setdefault(
                    filename,
                    GeoRemoteFile(
                        filename=filename,
                        kind="supplementary",
                        url=url,
                        size_bytes=int(size_text),
                        size_exact=True,
                        discovery_source="filelist",
                        source_manifest_url=manifest.url,
                    ),
                )

        status = "expanded" if entries else ("failed" if failures else "empty")
        return sorted(entries.values(), key=lambda item: item.filename), {
            "status": status,
            "sources": sources,
            "entries": len(entries),
            "failures": failures,
        }

    def discover(self, gse_id: str) -> list[GeoRemoteFile]:
        normalized = normalize_gse_id(gse_id)
        base = self.dataset_base_url(normalized)
        soft_url = f"{base}/soft/{normalized}_family.soft.gz"
        try:
            soft_size, soft_etag, soft_modified = self._probe(soft_url)
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            raise GeoDataError(
                f"GSE accession 不可用：{normalized}（HTTP {status}）",
                error_code="geo_accession_unavailable",
                error_class="not_found",
            ) from exc
        except requests.RequestException as exc:
            raise GeoDataError(
                f"无法连接 NCBI GEO 获取 {normalized}：{type(exc).__name__}",
                error_code="geo_unreachable",
                error_class="network_error",
            ) from exc

        files = [
            GeoRemoteFile(
                filename=f"{normalized}_family.soft.gz",
                kind="soft",
                url=soft_url,
                size_bytes=soft_size,
                etag=soft_etag,
                last_modified=soft_modified,
                size_exact=soft_size is not None,
            )
        ]
        for folder, kind in (("matrix", "series_matrix"), ("suppl", "supplementary")):
            try:
                files.extend(self._directory_files(f"{base}/{folder}/", kind))
            except requests.RequestException as exc:
                raise GeoDataError(
                    f"无法枚举 {normalized} 的 {kind} 文件：{type(exc).__name__}",
                    error_code="geo_file_listing_failed",
                    error_class="network_error",
                ) from exc

        deduplicated: dict[str, GeoRemoteFile] = {}
        for remote in files:
            if remote.filename not in deduplicated:
                deduplicated[remote.filename] = remote
        return sorted(
            deduplicated.values(), key=lambda item: (item.kind, item.filename)
        )

    def plan(
        self, gse_id: str, filenames: Optional[Iterable[str]] = None
    ) -> dict[str, Any]:
        normalized = normalize_gse_id(gse_id)
        available = self.discover(normalized)
        filelist_entries, filelist_diagnostics = self._filelist_entries(
            normalized, available
        )
        catalog = {item.filename: item for item in available}
        for item in filelist_entries:
            catalog.setdefault(item.filename, item)
        available = sorted(
            catalog.values(), key=lambda item: (item.kind, item.filename)
        )
        requested = {
            Path(item.strip()).name for item in filenames or [] if item.strip()
        }
        if requested:
            selected = [item for item in available if item.filename in requested]
            missing = sorted(requested - {item.filename for item in selected})
            if missing:
                expansion_failed = filelist_diagnostics["status"] == "failed"
                raise GeoDataError(
                    (
                        f"无法从 {normalized} 的 filelist 解析指定文件：{', '.join(missing)}"
                        if expansion_failed
                        else f"{normalized} 的规范化资源目录中没有指定文件：{', '.join(missing)}"
                    ),
                    error_code=(
                        "filelist_entries_not_expanded"
                        if expansion_failed
                        else "selection_resolution_failed"
                    ),
                    error_class=(
                        "source_manifest_error"
                        if expansion_failed
                        else "selection_error"
                    ),
                )
        else:
            selected = available

        exact_selected = []
        for item in selected:
            if item.size_exact:
                exact_selected.append(item)
                continue
            try:
                size, etag, modified = self._probe(item.url)
            except requests.RequestException:
                exact_selected.append(item)
                continue
            exact_selected.append(
                GeoRemoteFile(
                    filename=item.filename,
                    kind=item.kind,
                    url=item.url,
                    size_bytes=size if size is not None else item.size_bytes,
                    etag=etag or item.etag,
                    last_modified=modified or item.last_modified,
                    size_exact=size is not None,
                )
            )
        selected = exact_selected

        unknown = [
            item.filename
            for item in selected
            if item.size_bytes is None or not item.size_exact
        ]
        known_bytes = sum(item.size_bytes or 0 for item in selected)
        block_reasons = []
        if known_bytes > self.max_download_bytes:
            block_reasons.append("known_size_exceeds_limit")
        if unknown:
            block_reasons.append("unknown_remote_size")
        blocked = bool(block_reasons)
        plan = {
            "schema_version": "spc.geo.download-plan.v1",
            "gse_id": normalized,
            "source": "NCBI GEO",
            "dataset_url": self.dataset_base_url(normalized),
            "output_dir": str(self.root / normalized),
            "files": [item.to_dict() for item in selected],
            "discovery": {"filelist": filelist_diagnostics},
            "totals": {
                "files": len(selected),
                "known_bytes": known_bytes,
                "unknown_size_files": unknown,
            },
            "size_gate": {
                "max_bytes": self.max_download_bytes,
                "blocked": blocked,
                "reasons": block_reasons,
                "approval_flag": "--allow-large" if blocked else None,
            },
        }
        provisional = build_acquisition_plan(
            dataset_ref=f"dataset:geo:{normalized}@remote",
            source="ncbi-geo",
            host_id=self.host_id,
            files=plan["files"],
            route=self.route_decision,
            output_dir=plan["output_dir"],
            size_gate=plan["size_gate"],
            dataset_concurrency=self.coordinator.dataset_concurrency,
        )
        snapshot_version = provisional["source_snapshot_digest"].removeprefix(
            "sha256:"
        )[:16]
        acquisition = build_acquisition_plan(
            dataset_ref=f"dataset:geo:{normalized}@{snapshot_version}",
            source="ncbi-geo",
            host_id=self.host_id,
            files=plan["files"],
            route=self.route_decision,
            output_dir=plan["output_dir"],
            size_gate=plan["size_gate"],
            dataset_concurrency=self.coordinator.dataset_concurrency,
        )
        return {
            **plan,
            "dataset_ref": acquisition["dataset_ref"],
            "source_snapshot_digest": acquisition["source_snapshot_digest"],
            "plan_id": acquisition["plan_id"],
            "content_digest": acquisition["content_digest"],
            "host_id": acquisition["host_id"],
            "route": acquisition["route"],
            "concurrency": acquisition["concurrency"],
            "created_at": acquisition["created_at"],
            "producer_actor": acquisition["producer_actor"],
            "spc_git_sha": acquisition["spc_git_sha"],
        }

    def _initial_state(self, plan: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": "spc.geo.download-state.v1",
            "gse_id": plan["gse_id"],
            "status": "not_started",
            "source": plan["source"],
            "dataset_url": plan["dataset_url"],
            "started_at": None,
            "updated_at": utc_now(),
            "completed_at": None,
            "last_error": None,
            "files": {},
        }

    def _merge_plan(self, state: dict[str, Any], plan: dict[str, Any]) -> None:
        entries = state.setdefault("files", {})
        for remote in plan["files"]:
            current = entries.setdefault(remote["filename"], {})
            current.update(
                {
                    "filename": remote["filename"],
                    "kind": remote["kind"],
                    "url": remote["url"],
                    "expected_bytes": remote["size_bytes"],
                    "etag": remote["etag"],
                    "last_modified": remote["last_modified"],
                    "size_exact": remote["size_exact"],
                    "discovery_source": remote.get(
                        "discovery_source", "directory_listing"
                    ),
                    "source_manifest_url": remote.get("source_manifest_url"),
                }
            )
            current.setdefault("status", "pending")
            current.setdefault("downloaded_bytes", 0)
            current.setdefault("retry_count", 0)
            current.setdefault("bytes_per_second", 0.0)
            current.setdefault("eta_seconds", None)
            current.setdefault("last_byte_at", None)
            current.setdefault("sha256", None)
            current.setdefault("relative_path", remote["filename"])
            current.setdefault("reused", False)
            current.setdefault("resumed_from", 0)
            current.setdefault("error", None)
            current.setdefault("error_code", None)
            current.setdefault("error_class", None)
            current.setdefault("error_diagnostics", {})

    def _download_file(
        self,
        remote: GeoRemoteFile,
        directory: Path,
        *,
        force: bool,
        progress_callback: Optional[Callable[[dict[str, Any]], None]] = None,
    ) -> dict[str, Any]:
        target = directory / remote.filename
        partial = directory / f".{remote.filename}.part"
        if target.exists() and not force:
            size = target.stat().st_size
            if (
                not remote.size_exact
                or remote.size_bytes is None
                or size == remote.size_bytes
            ):
                return {
                    "status": "complete",
                    "downloaded_bytes": size,
                    "sha256": sha256_file(target),
                    "relative_path": target.name,
                    "reused": True,
                    "resumed_from": 0,
                    "error": None,
                }

        if force:
            with contextlib.suppress(FileNotFoundError):
                partial.unlink()
        started_at = time.monotonic()
        started_bytes = partial.stat().st_size if partial.exists() else 0
        retry_count = 0
        last_progress_at = started_at
        last_progress_bytes = started_bytes
        expected_size = remote.size_bytes if remote.size_exact else None

        def progress(*, force_emit: bool = False) -> dict[str, Any]:
            nonlocal last_progress_at, last_progress_bytes
            now = time.monotonic()
            progress_path = partial if partial.exists() else target
            downloaded = progress_path.stat().st_size if progress_path.exists() else 0
            elapsed = max(0.001, now - started_at)
            transferred = max(0, downloaded - started_bytes)
            bytes_per_second = transferred / elapsed
            eta_seconds = (
                max(0.0, (expected_size - downloaded) / bytes_per_second)
                if expected_size is not None and bytes_per_second > 0
                else None
            )
            snapshot = {
                "downloaded_bytes": downloaded,
                "expected_bytes": expected_size,
                "retry_count": retry_count,
                "bytes_per_second": round(bytes_per_second, 2),
                "eta_seconds": round(eta_seconds, 1)
                if eta_seconds is not None
                else None,
                "last_byte_at": utc_now(),
            }
            due = (
                force_emit
                or downloaded - last_progress_bytes >= self.progress_interval_bytes
                or now - last_progress_at >= self.progress_interval_seconds
            )
            if due:
                if progress_callback is not None:
                    progress_callback(snapshot)
                logger.event(
                    "geo.download.progress",
                    phase="dataset_download",
                    action="stream",
                    outcome="started",
                    source="ncbi_geo",
                    message=f"GEO 文件下载中，文件={remote.filename}",
                    diagnostics={"filename": remote.filename, **snapshot},
                )
                last_progress_at = now
                last_progress_bytes = downloaded
            return snapshot

        while True:
            existing = partial.stat().st_size if partial.exists() else 0
            headers = {"Range": f"bytes={existing}-"} if existing else {}
            if existing and (remote.etag or remote.last_modified):
                headers["If-Range"] = remote.etag or remote.last_modified or ""
            response: Optional[requests.Response] = None
            encoded_transfer = False
            try:
                logger.event(
                    "geo.download.request_started",
                    phase="dataset_download",
                    action="request_file",
                    outcome="started",
                    source="ncbi_geo",
                    message=f"开始请求 GEO 文件，文件={remote.filename}",
                    diagnostics={
                        "filename": remote.filename,
                        "range_start": existing,
                        "retry_count": retry_count,
                    },
                )
                response = self._request(
                    "GET", remote.url, headers=headers, stream=True
                )
                logger.event(
                    "geo.download.response_headers_received",
                    phase="dataset_download",
                    action="receive_headers",
                    outcome="success",
                    source="ncbi_geo",
                    message=f"已收到 GEO 响应头，文件={remote.filename}",
                    diagnostics={
                        "filename": remote.filename,
                        "status_code": response.status_code,
                        "content_length": response.headers.get("Content-Length"),
                        "content_range": response.headers.get("Content-Range"),
                        "retry_count": retry_count,
                    },
                )
                if response.status_code == 416 and expected_size == existing:
                    try:
                        os.replace(partial, target)
                    except OSError as exc:
                        raise GeoFilesystemError("final_rename", target, exc) from exc
                    break
                if existing and response.status_code in {400, 403, 416}:
                    response.close()
                    response = self._request("GET", remote.url, headers={}, stream=True)
                    existing = 0
                response.raise_for_status()
                append = existing > 0 and response.status_code == 206
                mode = "ab" if append else "wb"
                if not append:
                    existing = 0

                content_type = str(response.headers.get("Content-Type") or "").lower()
                if "text/html" in content_type or "application/xhtml" in content_type:
                    raise GeoDataError(
                        f"GEO 文件返回了非预期内容：{remote.filename}，内容类型={content_type or 'unknown'}",
                        error_code="unexpected_content",
                        error_class="identity_mismatch",
                    )
                content_range = str(response.headers.get("Content-Range") or "")
                content_length = str(response.headers.get("Content-Length") or "")
                content_encoding = str(
                    response.headers.get("Content-Encoding") or ""
                ).lower()
                encoded_transfer = content_encoding not in {"", "identity"}
                if encoded_transfer and append:
                    with contextlib.suppress(FileNotFoundError):
                        partial.unlink()
                    raise requests.ConnectionError(
                        f"encoded ranged response cannot safely resume {remote.filename}"
                    )
                range_match = re.search(r"/(\d+)$", content_range)
                response_total = int(range_match.group(1)) if range_match else None
                if (
                    response_total is None
                    and content_length.isdigit()
                    and content_encoding in {"", "identity"}
                ):
                    response_total = int(content_length) + (existing if append else 0)
                if response_total is not None:
                    expected_size = response_total
                elif content_encoding not in {"", "identity"}:
                    # requests.iter_content transparently decodes compressed bodies;
                    # wire Content-Length and ranged byte offsets no longer describe
                    # the bytes written to disk.
                    expected_size = None

                first_chunk = True
                logger.event(
                    "geo.download.first_byte_waiting",
                    phase="dataset_download",
                    action="receive_first_byte",
                    outcome="started",
                    source="ncbi_geo",
                    message=f"等待 GEO 文件首字节，文件={remote.filename}",
                    diagnostics={
                        "filename": remote.filename,
                        "retry_count": retry_count,
                    },
                )
                try:
                    handle = partial.open(mode)
                except OSError as exc:
                    raise GeoFilesystemError("data_open", partial, exc) from exc
                with handle:
                    _chmod_shared_file(partial)
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        if first_chunk:
                            prefix = chunk[:512].lstrip().lower()
                            if prefix.startswith((b"<!doctype html", b"<html")):
                                raise GeoDataError(
                                    f"GEO 文件返回了 HTML 页面而不是数据：{remote.filename}",
                                    error_code="unexpected_html_content",
                                    error_class="identity_mismatch",
                                )
                            first_chunk = False
                            logger.event(
                                "geo.download.first_byte_received",
                                phase="dataset_download",
                                action="receive_first_byte",
                                outcome="success",
                                source="ncbi_geo",
                                message=f"已收到 GEO 文件首字节，文件={remote.filename}",
                                diagnostics={
                                    "filename": remote.filename,
                                    "first_chunk_bytes": len(chunk),
                                    "retry_count": retry_count,
                                },
                            )
                        try:
                            handle.write(chunk)
                        except OSError as exc:
                            raise GeoFilesystemError(
                                "data_write", partial, exc
                            ) from exc
                        try:
                            handle.flush()
                        except OSError as exc:
                            raise GeoFilesystemError(
                                "data_flush", partial, exc
                            ) from exc
                        progress()
                    try:
                        handle.flush()
                        os.fsync(handle.fileno())
                    except OSError as exc:
                        raise GeoFilesystemError("data_fsync", partial, exc) from exc

                final_size = partial.stat().st_size
                if response_total is not None and final_size < response_total:
                    raise requests.ConnectionError(
                        f"short ranged response for {remote.filename}: {final_size}/{response_total}"
                    )
                if response_total is not None and final_size > response_total:
                    raise GeoDataError(
                        f"GEO 文件大小超出预期：{remote.filename}，预期 {response_total} 字节",
                        error_code="download_size_overrun",
                        error_class="integrity_mismatch",
                    )
                if remote.size_exact and remote.size_bytes != final_size:
                    logger.warning(
                        "[GEO 元数据] 远端 HEAD 大小与安全 GET 不一致，采用 GET 实际大小，文件=%s",
                        remote.filename,
                        diagnostics={
                            "filename": remote.filename,
                            "head_bytes": remote.size_bytes,
                            "get_bytes": final_size,
                            "content_type": content_type,
                        },
                    )
                try:
                    os.replace(partial, target)
                except OSError as exc:
                    raise GeoFilesystemError("final_rename", target, exc) from exc
                break
            except (requests.Timeout, requests.ConnectionError) as exc:
                if encoded_transfer:
                    with contextlib.suppress(FileNotFoundError):
                        partial.unlink()
                if retry_count >= self.stream_retries:
                    raise GeoDataError(
                        f"GEO 流式下载重试耗尽：{remote.filename}，原因={type(exc).__name__}",
                        error_code="stream_retries_exhausted",
                        error_class="network_error",
                    ) from exc
                retry_count += 1
                progress(force_emit=True)
                logger.warning(
                    "[GEO 下载] 连接停顿后自动续传，文件=%s，重试=%s",
                    remote.filename,
                    retry_count,
                    diagnostics={
                        "filename": remote.filename,
                        "retry_count": retry_count,
                        "downloaded_bytes": partial.stat().st_size
                        if partial.exists()
                        else 0,
                        "error_class": type(exc).__name__,
                    },
                )
                time.sleep(min(15.0, 0.75 * (2 ** min(retry_count - 1, 4))))
                continue
            finally:
                if response is not None:
                    response.close()

        _chmod_shared_file(target)
        final_progress = progress(force_emit=True)
        return {
            "status": "complete",
            "downloaded_bytes": target.stat().st_size,
            "sha256": sha256_file(target),
            "relative_path": target.name,
            "retry_count": retry_count,
            "bytes_per_second": final_progress["bytes_per_second"],
            "reused": False,
            "resumed_from": started_bytes,
            "error": None,
        }

    def download(
        self,
        gse_id: str,
        *,
        filenames: Optional[Iterable[str]] = None,
        force: bool = False,
        allow_large: bool = False,
    ) -> dict[str, Any]:
        plan = self.plan(gse_id, filenames)
        if plan["size_gate"]["blocked"] and not allow_large:
            raise GeoLargeDownloadBlocked(plan)

        normalized = plan["gse_id"]
        _ensure_directory(self.root)
        directory = self.root / normalized
        _ensure_directory(directory)
        coordination: dict[str, Any] = {}
        try:
            coordination_context = self.coordinator.acquire(
                dataset_key=plan["dataset_ref"],
                source="ncbi-geo",
            )
            coordination = coordination_context.__enter__()
        except AcquisitionBusy as exc:
            failure = error_payload(exc)
            write_acquisition_report(
                directory,
                plan=plan,
                status="failed_retryable",
                attempts=[
                    {
                        "route": plan["route"]["resolved_route"],
                        "status": "resource_busy",
                    }
                ],
                files=[],
                error=failure,
            )
            logger.event(
                "geo.download.blocked",
                phase="dataset_download",
                action="download_dataset",
                outcome="blocked",
                level="WARNING",
                source="ncbi_geo",
                error_class=failure["error_class"],
                message=f"GEO 数据集下载暂时阻断：{normalized}",
                diagnostics={"gse_id": normalized, "error_code": failure["error_code"]},
            )
            raise
        try:
            logger.event(
                "geo.download.started",
                phase="dataset_download",
                action="download_dataset",
                outcome="started",
                source="ncbi_geo",
                message=f"开始下载 GEO 数据集：{normalized}",
                diagnostics={
                    "gse_id": normalized,
                    "dataset_ref": plan["dataset_ref"],
                    "file_count": len(plan["files"]),
                    "resolved_route": plan["route"]["resolved_route"],
                },
            )
            state_path = directory / STATE_FILENAME
            state = load_json(state_path) or self._initial_state(plan)
            self._merge_plan(state, plan)
            state["acquisition_plan_id"] = plan["plan_id"]
            state["resolved_route"] = plan["route"]["resolved_route"]
            state["status"] = "downloading"
            state["started_at"] = state.get("started_at") or utc_now()
            state["updated_at"] = utc_now()
            state["last_error"] = None
            atomic_write_json(state_path, state)

            selected = {
                item["filename"]: GeoRemoteFile(**item) for item in plan["files"]
            }
            for filename, remote in selected.items():
                entry = state["files"][filename]
                entry["status"] = "downloading"
                entry["error"] = None
                entry["error_code"] = None
                entry["error_class"] = None
                entry["error_diagnostics"] = {}
                state["updated_at"] = utc_now()
                atomic_write_json(state_path, state)
                try:

                    def persist_progress(
                        snapshot: dict[str, Any],
                        current_entry: dict[str, Any] = entry,
                    ) -> None:
                        current_entry.update(snapshot)
                        state["updated_at"] = utc_now()
                        atomic_write_json(state_path, state)

                    entry.update(
                        self._download_file(
                            remote,
                            directory,
                            force=force,
                            progress_callback=persist_progress,
                        )
                    )
                except (GeoDataError, OSError, requests.RequestException) as exc:
                    failure = error_payload(exc)
                    entry["status"] = "failed"
                    entry["error"] = failure["message"]
                    entry["error_code"] = failure["error_code"]
                    entry["error_class"] = failure["error_class"]
                    entry["error_diagnostics"] = dict(
                        getattr(exc, "diagnostics", {}) or {}
                    )
                    partial = directory / f".{filename}.part"
                    entry["downloaded_bytes"] = (
                        partial.stat().st_size if partial.exists() else 0
                    )
                    logger.event(
                        "geo.download.file_failed",
                        phase="dataset_download",
                        action="download_file",
                        outcome="failed",
                        level="ERROR",
                        source="ncbi_geo",
                        error_class=failure["error_class"],
                        message=f"GEO 文件下载失败，文件={filename}",
                        diagnostics={
                            "filename": filename,
                            "error_code": failure["error_code"],
                            "downloaded_bytes": entry["downloaded_bytes"],
                            **entry["error_diagnostics"],
                        },
                    )
                state["updated_at"] = utc_now()
                atomic_write_json(state_path, state)

            failed_entries = [
                entry
                for entry in state.get("files", {}).values()
                if entry.get("status") != "complete"
            ]
            all_errors = [
                f"{entry.get('filename')}: {entry.get('error') or entry.get('status')}"
                for entry in failed_entries
            ]
            failure_classes = [
                str(entry.get("error_class") or "acquisition_failed")
                for entry in failed_entries
            ]
            dataset_error_class = (
                failure_classes[0]
                if failure_classes and len(set(failure_classes)) == 1
                else "multiple_failures"
            )
            state["status"] = "incomplete" if failed_entries else "complete"
            state["last_error"] = "; ".join(all_errors) if all_errors else None
            state["completed_at"] = None if failed_entries else utc_now()
            state["updated_at"] = utc_now()
            atomic_write_json(state_path, state)
            archive = self._build_archive(directory, state)
            atomic_write_json(directory / ARCHIVE_FILENAME, archive)
            report = write_acquisition_report(
                directory,
                plan=plan,
                status="complete"
                if state["status"] == "complete"
                else "failed_retryable",
                attempts=[
                    {
                        "route": plan["route"]["resolved_route"],
                        "status": state["status"],
                        "started_at": state.get("started_at"),
                        "completed_at": state.get("completed_at"),
                    }
                ],
                files=archive["files"],
                error=(
                    {
                        "error_code": "download_incomplete",
                        "error_class": dataset_error_class,
                        "message": state["last_error"],
                    }
                    if state.get("last_error")
                    else None
                ),
                coordination=coordination,
            )
            result = self._result(directory, state, archive)
            result.update(
                {
                    "plan_id": plan["plan_id"],
                    "dataset_ref": plan["dataset_ref"],
                    "resolved_route": plan["route"]["resolved_route"],
                    "acquisition_report_path": report["report_path"],
                }
            )
            succeeded = result["status"] == "complete"
            logger.event(
                "geo.download.completed" if succeeded else "geo.download.incomplete",
                phase="dataset_download",
                action="download_dataset",
                outcome="success" if succeeded else "failed",
                level="INFO" if succeeded else "ERROR",
                source="ncbi_geo",
                error_class=None if succeeded else dataset_error_class,
                message=(
                    f"GEO 数据集下载完成：{normalized}"
                    if succeeded
                    else f"GEO 数据集下载未完成：{normalized}"
                ),
                diagnostics={
                    "gse_id": normalized,
                    "dataset_ref": plan["dataset_ref"],
                    "error_code": None if succeeded else "download_incomplete",
                    "error_class": None if succeeded else dataset_error_class,
                    "complete_files": result.get("files", {}).get("complete", 0),
                    "total_files": result.get("files", {}).get("total", 0),
                },
            )
            return result
        finally:
            coordination_context.__exit__(None, None, None)

    def _parse_soft(self, path: Path) -> dict[str, Any]:
        series: dict[str, Any] = {
            "title": None,
            "summary": [],
            "overall_design": [],
            "series_type": [],
            "submission_date": None,
            "last_update_date": None,
            "pubmed_ids": [],
        }
        samples: list[dict[str, Any]] = []
        current: Optional[dict[str, Any]] = None
        accessions = {key: set() for key in ACCESSION_PATTERNS}
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8", errors="replace") as handle:
            for raw_line in handle:
                line = raw_line.rstrip("\r\n")
                lower_line = line.lower()
                if any(
                    marker in lower_line
                    for marker in ("relation", "sra:", "bioproject")
                ):
                    for key, pattern in ACCESSION_PATTERNS.items():
                        accessions[key].update(
                            match.upper() for match in pattern.findall(line)
                        )
                if line.startswith("^SAMPLE = "):
                    current = {
                        "gsm_id": line.split("=", 1)[1].strip(),
                        "title": None,
                        "source_name": None,
                        "organism": None,
                        "characteristics": [],
                        "library_strategy": None,
                        "relations": [],
                    }
                    samples.append(current)
                    continue
                if not line.startswith("!") or " = " not in line:
                    continue
                key, value = line[1:].split(" = ", 1)
                if key == "Series_title":
                    series["title"] = value
                elif key == "Series_summary":
                    series["summary"].append(value)
                elif key == "Series_overall_design":
                    series["overall_design"].append(value)
                elif key == "Series_type":
                    series["series_type"].append(value)
                elif key == "Series_submission_date":
                    series["submission_date"] = value
                elif key == "Series_last_update_date":
                    series["last_update_date"] = value
                elif key == "Series_pubmed_id":
                    series["pubmed_ids"].append(value)
                elif current is not None:
                    if key == "Sample_title":
                        current["title"] = value
                    elif key.startswith("Sample_source_name"):
                        current["source_name"] = value
                    elif key.startswith("Sample_organism"):
                        current["organism"] = value
                    elif key.startswith("Sample_characteristics"):
                        current["characteristics"].append(value)
                    elif key == "Sample_library_strategy":
                        current["library_strategy"] = value
                    elif key == "Sample_relation":
                        current["relations"].append(value)
        series["summary"] = " ".join(series["summary"])
        series["overall_design"] = " ".join(series["overall_design"])
        series["series_type"] = sorted(set(series["series_type"]))
        return {
            "series": series,
            "sample_count": len(samples),
            "samples": samples,
            "linked_accessions": {
                key: sorted(values) for key, values in accessions.items()
            },
        }

    def _build_archive(self, directory: Path, state: dict[str, Any]) -> dict[str, Any]:
        files = []
        soft_path = None
        for entry in state.get("files", {}).values():
            relative = entry.get("relative_path") or entry.get("filename")
            files.append(
                {
                    "filename": entry.get("filename"),
                    "kind": entry.get("kind"),
                    "relative_path": relative,
                    "status": entry.get("status"),
                    "size_bytes": entry.get("downloaded_bytes", 0),
                    "sha256": entry.get("sha256"),
                    "reused": bool(entry.get("reused")),
                    "resumed_from": int(entry.get("resumed_from") or 0),
                    "retry_count": int(entry.get("retry_count") or 0),
                    "bytes_per_second": entry.get("bytes_per_second"),
                    "error_code": entry.get("error_code"),
                    "error_class": entry.get("error_class"),
                    "error_diagnostics": entry.get("error_diagnostics") or {},
                    "discovery_source": entry.get("discovery_source"),
                    "source_manifest_url": entry.get("source_manifest_url"),
                }
            )
            if entry.get("kind") == "soft" and entry.get("status") == "complete":
                candidate = directory / relative
                if candidate.exists():
                    soft_path = candidate
        metadata = self._parse_soft(soft_path) if soft_path else None
        return {
            "schema_version": "spc.geo.archive.v1",
            "gse_id": state["gse_id"],
            "source": state["source"],
            "dataset_url": state["dataset_url"],
            "status": state["status"],
            "updated_at": utc_now(),
            "files": sorted(files, key=lambda item: item["filename"] or ""),
            "metadata": metadata,
        }

    @staticmethod
    def _result(
        directory: Path, state: dict[str, Any], archive: dict[str, Any]
    ) -> dict[str, Any]:
        entries = list(state.get("files", {}).values())
        first_failure = next(
            (item for item in entries if item.get("status") in {"failed", "invalid"}),
            {},
        )
        return {
            "schema_version": "spc.geo.command-result.v1",
            "gse_id": state["gse_id"],
            "status": state["status"],
            "dataset_dir": str(directory),
            "state_path": str(directory / STATE_FILENAME),
            "archive_path": str(directory / ARCHIVE_FILENAME),
            "files": {
                "total": len(entries),
                "complete": sum(item.get("status") == "complete" for item in entries),
                "failed": sum(
                    item.get("status") in {"failed", "invalid"} for item in entries
                ),
                "downloaded_bytes": sum(
                    int(item.get("downloaded_bytes") or 0) for item in entries
                ),
            },
            "sample_count": ((archive.get("metadata") or {}).get("sample_count")),
            "linked_accessions": (
                (archive.get("metadata") or {}).get("linked_accessions", {})
            ),
            "last_error": state.get("last_error"),
            "error_code": first_failure.get("error_code"),
            "error_class": first_failure.get("error_class"),
        }

    def inspect(self, gse_id: str, *, verify: bool = False) -> dict[str, Any]:
        normalized = normalize_gse_id(gse_id)
        directory = self.root / normalized
        state_path = directory / STATE_FILENAME
        state = load_json(state_path)
        if state is None:
            return {
                "schema_version": "spc.geo.command-result.v1",
                "gse_id": normalized,
                "status": "not_downloaded",
                "dataset_dir": str(directory),
            }
        if verify:
            lock = GeoDatasetLock(
                self.root / ".locks" / f"{normalized}.lock", self.lock_timeout_seconds
            )
            with lock:
                state = load_json(state_path) or state
                for entry in state.get("files", {}).values():
                    if entry.get("status") not in {"complete", "invalid"}:
                        continue
                    path = directory / (entry.get("relative_path") or entry["filename"])
                    error = None
                    if not path.is_file():
                        error = "file_missing"
                    elif (
                        entry.get("downloaded_bytes") is not None
                        and path.stat().st_size != entry["downloaded_bytes"]
                    ):
                        error = "size_mismatch"
                    elif entry.get("sha256") and sha256_file(path) != entry["sha256"]:
                        error = "sha256_mismatch"
                    entry["status"] = "invalid" if error else "complete"
                    entry["error"] = error
                problems = [
                    entry
                    for entry in state.get("files", {}).values()
                    if entry.get("status") != "complete"
                ]
                has_invalid = any(
                    entry.get("status") == "invalid" for entry in problems
                )
                state["status"] = (
                    "invalid"
                    if has_invalid
                    else ("incomplete" if problems else "complete")
                )
                state["last_error"] = (
                    "; ".join(
                        f"{entry.get('filename')}: {entry.get('error') or entry.get('status')}"
                        for entry in problems
                    )
                    if problems
                    else None
                )
                state["updated_at"] = utc_now()
                atomic_write_json(state_path, state)
                archive = self._build_archive(directory, state)
                atomic_write_json(directory / ARCHIVE_FILENAME, archive)
        archive = load_json(directory / ARCHIVE_FILENAME) or self._build_archive(
            directory, state
        )
        return self._result(directory, state, archive)

    def list_local(self, *, verify: bool = False) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        results = []
        for directory in sorted(self.root.iterdir()):
            if directory.is_dir() and GSE_PATTERN.fullmatch(directory.name):
                results.append(self.inspect(directory.name, verify=verify))
        return results


def geo_environment_status(
    output_dir: Optional[str | os.PathLike[str]] = None,
) -> dict[str, Any]:
    root = resolve_geo_root(output_dir)
    probe = root
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    reachable = False
    error = None
    session = _new_http_session()
    try:
        response = session.head(
            "https://ftp.ncbi.nlm.nih.gov/geo/",
            timeout=(5, 10),
            allow_redirects=True,
        )
        reachable = response.status_code < 500
        response.close()
    except requests.RequestException as exc:
        error = f"{type(exc).__name__}: {exc}"
    finally:
        session.close()
    return {
        "root": str(root),
        "root_exists": root.exists(),
        "writable": os.access(probe, os.W_OK),
        "ncbi_geo_reachable": reachable,
        "network_error": error,
        "max_download_gb": configured_max_download_gb(),
        "shared_root_configured": str(root).startswith(f"{SERVER_PRODUCTION_ROOT}/"),
    }
