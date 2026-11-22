"""数据集下载的主机级协调、确定性路由与审计报告。"""

from __future__ import annotations

import contextlib
import getpass
import hashlib
import json
import os
import re
import socket
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence
from urllib.parse import parse_qsl, urlsplit

from paperfetch.observability import get_event_logger
from paperfetch.utils.client import normalize_proxy_url

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows uses msvcrt.
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - POSIX uses fcntl.
    msvcrt = None


PLAN_SCHEMA = "spc.dataset-acquisition-plan.v1"
STATE_SCHEMA = "spc.dataset-download-state.v1"
REPORT_SCHEMA = "spc.dataset-acquisition-report.v1"
DEFAULT_DATASET_CONCURRENCY = 2
MAX_DATASET_CONCURRENCY = 4
DEFAULT_LOCK_TIMEOUT_SECONDS = 30.0
_SENSITIVE_QUERY_KEY = re.compile(
    r"(?:x-amz-|signature|sig$|token|key|auth|credential|policy|expires|session)",
    re.IGNORECASE,
)


logger = get_event_logger("paperfetch.datasets.acquisition")


class AcquisitionError(RuntimeError):
    """确定性下载协调的基础异常。"""

    error_code = "acquisition_failed"
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


class AcquisitionConfigurationError(AcquisitionError, ValueError):
    """路由或并发配置无效。"""

    error_code = "invalid_acquisition_configuration"
    error_class = "invalid_configuration"


class AcquisitionBusy(AcquisitionError):
    """主机、来源或数据集资源未能在时限内取得。"""

    error_code = "resource_busy"
    error_class = "resource_busy"


def error_payload(
    exc: BaseException,
    *,
    error_code: str | None = None,
    error_class: str | None = None,
) -> dict[str, str]:
    """将异常转换为稳定机器码和中文人读消息，避免暴露敏感诊断值。"""

    declared_code = str(getattr(exc, "error_code", "") or "")
    declared_class = str(getattr(exc, "error_class", "") or "")
    resolved_code = error_code or declared_code
    resolved_class = error_class or declared_class
    if not resolved_code:
        if isinstance(exc, OSError):
            resolved_code = "filesystem_operation_failed"
        elif isinstance(exc, ValueError):
            resolved_code = "invalid_argument"
        else:
            resolved_code = "unclassified_error"
    if not resolved_class:
        if isinstance(exc, OSError):
            resolved_class = "io_error"
        elif isinstance(exc, ValueError):
            resolved_class = "invalid_configuration"
        else:
            resolved_class = "internal_error"
    if declared_code or declared_class:
        message = str(exc).strip() or "数据获取失败，未返回详细原因"
    elif isinstance(exc, OSError):
        message = f"文件系统操作失败：{type(exc).__name__}"
    elif isinstance(exc, ValueError):
        message = f"参数或配置无效：{type(exc).__name__}"
    else:
        message = f"数据获取失败：{type(exc).__name__}"
    return {
        "error_code": resolved_code,
        "error_class": resolved_class,
        "message": message,
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_host_id() -> str:
    """生成跨平台稳定且不泄露完整非 ASCII 主机名的主机标识。"""

    hostname = socket.gethostname().strip()
    slug = re.sub(r"[^a-z0-9._-]+", "-", hostname.lower()).strip("-._")
    if slug:
        return f"host:{slug}"
    digest = hashlib.sha256(hostname.encode("utf-8")).hexdigest()[:12]
    return f"host:node-{digest}"


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _ensure_shared_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(OSError):
        path.chmod(path.stat().st_mode | 0o2775)


def _chmod_shared_file(path: Path) -> None:
    with contextlib.suppress(OSError):
        path.chmod(0o664)


def _env_int(name: str, default: int) -> int:
    raw = str(os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise AcquisitionConfigurationError(
            f"环境变量 {name} 必须是整数",
            error_code="invalid_integer_configuration",
        ) from exc


def _env_float(name: str, default: float) -> float:
    raw = str(os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise AcquisitionConfigurationError(
            f"环境变量 {name} 必须是数值",
            error_code="invalid_numeric_configuration",
        ) from exc


def configured_dataset_concurrency(value: int | None = None) -> int:
    resolved = (
        value
        if value is not None
        else _env_int("SPC_DATASET_CONCURRENCY", DEFAULT_DATASET_CONCURRENCY)
    )
    if not 1 <= resolved <= MAX_DATASET_CONCURRENCY:
        raise AcquisitionConfigurationError(
            f"数据集并发数必须在 1 到 {MAX_DATASET_CONCURRENCY} 之间",
            error_code="invalid_dataset_concurrency",
        )
    return resolved


def configured_lock_timeout(value: float | None = None) -> float:
    resolved = (
        value
        if value is not None
        else _env_float(
            "SPC_DATASET_LOCK_TIMEOUT_SECONDS", DEFAULT_LOCK_TIMEOUT_SECONDS
        )
    )
    if resolved <= 0:
        raise AcquisitionConfigurationError(
            "数据集锁等待时间必须大于 0 秒",
            error_code="invalid_lock_timeout",
        )
    return float(resolved)


def resolve_coordination_root(
    value: str | os.PathLike[str] | None = None,
    *,
    data_root: str | os.PathLike[str] | None = None,
) -> Path:
    configured = value or os.getenv("SPC_DOWNLOAD_COORDINATION_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    if data_root is not None:
        root = Path(data_root).expanduser().resolve()
        return (root.parent / ".spc-download").resolve()
    return Path("~/.cache/spc/.spc-download").expanduser().resolve()


@dataclass(frozen=True)
class RouteDecision:
    route: str
    proxy_url: str | None
    proxy_ref: str | None
    proxy_summary: dict[str, Any] | None

    def audit_dict(self) -> dict[str, Any]:
        return {
            "resolved_route": self.route,
            "proxy_ref": self.proxy_ref,
        }


def resolve_http_route(mode: str | None, proxy_url: str | None) -> RouteDecision:
    normalized = str(mode or "route-aware").strip().lower().replace("_", "-")
    if normalized in {"none", "no-proxy"}:
        normalized = "direct"
    if normalized not in {"route-aware", "direct", "proxy"}:
        raise AcquisitionConfigurationError(
            f"未知的数据下载代理模式：{mode!r}",
            error_code="unknown_proxy_mode",
        )

    candidate = normalize_proxy_url(proxy_url)
    if normalized == "direct":
        return RouteDecision("direct", None, None, None)
    if candidate is None:
        if normalized == "proxy":
            raise AcquisitionConfigurationError(
                "代理模式要求配置对应的数据源代理或 DOWNLOAD_PROXY",
                error_code="proxy_not_configured",
            )
        return RouteDecision("direct", None, None, None)

    parsed = urlsplit(candidate)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise AcquisitionConfigurationError(
            "数据下载代理必须是包含主机名的 HTTP(S) URL",
            error_code="invalid_proxy_url",
        )
    try:
        port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    except ValueError as exc:
        raise AcquisitionConfigurationError(
            "数据下载代理端口无效",
            error_code="invalid_proxy_port",
        ) from exc
    public_identity = f"{parsed.scheme.lower()}://{parsed.hostname.lower()}:{port}"
    proxy_ref = (
        "proxy:sha256:"
        + hashlib.sha256(public_identity.encode("utf-8")).hexdigest()[:16]
    )
    return RouteDecision(
        "proxy",
        candidate,
        proxy_ref,
        {"scheme": parsed.scheme.lower(), "host": parsed.hostname, "port": port},
    )


def source_route_from_environment(source: str) -> RouteDecision:
    normalized = source.strip().lower().replace("_", "-")
    names = {
        "geo": ("SPC_GEO_PROXY_MODE", "SPC_GEO_PROXY"),
        "ncbi": ("SPC_NCBI_PROXY_MODE", "SPC_NCBI_PROXY"),
        "dryad": ("SPC_DRYAD_PROXY_MODE", "SPC_DRYAD_PROXY"),
    }
    if normalized not in names:
        raise AcquisitionConfigurationError(
            f"不支持的数据来源：{source!r}",
            error_code="unsupported_dataset_source",
        )
    mode_name, proxy_name = names[normalized]
    mode = os.getenv(mode_name) or "route-aware"
    proxy = os.getenv(proxy_name)
    return resolve_http_route(mode, proxy)


def build_acquisition_plan(
    *,
    dataset_ref: str,
    source: str,
    host_id: str,
    files: Sequence[Mapping[str, Any]],
    route: RouteDecision,
    access_route: str | None = None,
    output_dir: str,
    size_gate: Mapping[str, Any],
    dataset_concurrency: int,
    file_concurrency: int = 1,
    rate_limit: Mapping[str, Any] | None = None,
    producer_actor: str | None = None,
    spc_git_sha: str | None = None,
) -> dict[str, Any]:
    if spc_git_sha is None:
        from paperfetch.runtime_info import collect_runtime_info

        spc_git_sha = collect_runtime_info().get("git_sha")
    normalized_files = [dict(item) for item in files]
    for item in normalized_files:
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        try:
            parsed = urlsplit(url)
        except ValueError as exc:
            raise AcquisitionConfigurationError(
                "数据获取计划包含无效 URL",
                error_code="invalid_dataset_file_url",
            ) from exc
        sensitive_query = any(
            _SENSITIVE_QUERY_KEY.search(key)
            for key, _value in parse_qsl(parsed.query, keep_blank_values=True)
        )
        if parsed.username or parsed.password or sensitive_query:
            raise AcquisitionConfigurationError(
                "数据获取计划不得包含代理认证、访问令牌或签名 URL",
                error_code="sensitive_url_not_allowed",
            )
    snapshot_identity = {
        "source": source,
        "files": [
            {
                key: item.get(key)
                for key in (
                    "url",
                    "path",
                    "filename",
                    "size_bytes",
                    "digest",
                    "etag",
                    "last_modified",
                )
                if item.get(key) is not None
            }
            for item in normalized_files
        ],
    }
    source_snapshot_digest = _digest(snapshot_identity)
    stable = {
        "schema_version": PLAN_SCHEMA,
        "dataset_ref": dataset_ref,
        "source": source,
        "source_snapshot_digest": source_snapshot_digest,
        "host_id": host_id,
        "files": normalized_files,
        "route": {
            **route.audit_dict(),
            "access_route": access_route,
        },
        "output_dir": output_dir,
        "size_gate": dict(size_gate),
        "concurrency": {
            "datasets": configured_dataset_concurrency(dataset_concurrency),
            "files": file_concurrency,
        },
        "rate_limit": dict(rate_limit or {}),
    }
    if file_concurrency != 1:
        raise AcquisitionConfigurationError(
            "下载协议 v1 要求单个数据集的文件并发数为 1",
            error_code="unsupported_file_concurrency",
        )
    content_digest = _digest(stable)
    return {
        **stable,
        "plan_id": content_digest,
        "content_digest": content_digest,
        "created_at": utc_now(),
        "producer_actor": producer_actor or getpass.getuser(),
        "spc_git_sha": spc_git_sha,
    }


class CrossProcessFileLock:
    """Small cross-platform advisory file lock with a bounded wait."""

    def __init__(self, path: Path, timeout_seconds: float):
        self.path = path
        self.timeout_seconds = max(0.0, float(timeout_seconds))
        self._handle: Any = None
        self.contended = False
        self.waited_ms = 0

    def __enter__(self) -> "CrossProcessFileLock":
        _ensure_shared_directory(self.path.parent)
        self._handle = self.path.open("a+b")
        _chmod_shared_file(self.path)
        if fcntl is None and msvcrt is None:
            return self
        if msvcrt is not None:
            self._handle.seek(0, os.SEEK_END)
            if self._handle.tell() == 0:
                self._handle.write(b"\0")
                self._handle.flush()
        wait_started = time.monotonic()
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            try:
                if fcntl is not None:
                    fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                else:
                    self._handle.seek(0)
                    msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
                self.waited_ms = round((time.monotonic() - wait_started) * 1000)
                return self
            except (BlockingIOError, OSError) as exc:
                self.contended = True
                if time.monotonic() >= deadline:
                    self.waited_ms = round((time.monotonic() - wait_started) * 1000)
                    self._handle.close()
                    self._handle = None
                    raise AcquisitionBusy(f"资源正忙：{self.path.name}") from exc
                time.sleep(0.05)

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


def _lock_key(value: str) -> str:
    label = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")[:48] or "resource"
    suffix = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{label}-{suffix}"


class DownloadCoordinator:
    """Enforce host, dataset, and source concurrency without a queue database."""

    def __init__(
        self,
        root: str | os.PathLike[str],
        *,
        dataset_concurrency: int | None = None,
        lock_timeout_seconds: float | None = None,
    ):
        self.root = Path(root).expanduser().resolve()
        self.dataset_concurrency = configured_dataset_concurrency(dataset_concurrency)
        self.lock_timeout_seconds = configured_lock_timeout(lock_timeout_seconds)

    def _acquire_slot(self, deadline: float) -> tuple[CrossProcessFileLock, bool]:
        queued = False
        while True:
            for index in range(self.dataset_concurrency):
                lock = CrossProcessFileLock(
                    self.root / "download-slots" / f"slot-{index}.lock",
                    timeout_seconds=0,
                )
                try:
                    lock.__enter__()
                except AcquisitionBusy:
                    continue
                return lock, queued
            if time.monotonic() >= deadline:
                raise AcquisitionBusy("资源正忙：当前主机的数据集下载槽位已全部占用")
            queued = True
            time.sleep(0.05)

    @contextmanager
    def acquire_source(self, source: str) -> Iterator[dict[str, Any]]:
        """在已有数据集租约中附加来源锁，用于显式路由切换。"""

        requested_at = utc_now()
        wait_started = time.monotonic()
        source_lock = CrossProcessFileLock(
            self.root / "source-streams" / f"{_lock_key(source)}.lock",
            self.lock_timeout_seconds,
        )
        source_lock.__enter__()
        lease = {
            "source": source,
            "coordination_root": str(self.root),
            "requested_at": requested_at,
            "acquired_at": utc_now(),
            "waited_ms": round((time.monotonic() - wait_started) * 1000),
            "queued": source_lock.contended,
        }
        try:
            logger.event(
                "dataset.coordination.source_acquired",
                phase="coordination",
                action="acquire_source_lease",
                outcome="success",
                source=source,
                message="已获取数据来源下载资源",
                diagnostics=lease,
            )
            yield lease
        finally:
            source_lock.__exit__(None, None, None)
            logger.event(
                "dataset.coordination.source_released",
                phase="coordination",
                action="release_source_lease",
                outcome="success",
                source=source,
                message="已释放数据来源下载资源",
                diagnostics=lease,
            )

    @contextmanager
    def acquire(self, *, dataset_key: str, source: str) -> Iterator[dict[str, Any]]:
        requested_at = utc_now()
        wait_started = time.monotonic()
        deadline = time.monotonic() + self.lock_timeout_seconds
        slot: CrossProcessFileLock | None = None
        dataset_lock: CrossProcessFileLock | None = None
        source_lock: CrossProcessFileLock | None = None
        lease_acquired = False
        try:
            remaining = max(0.0, deadline - time.monotonic())
            dataset_lock = CrossProcessFileLock(
                self.root / "datasets" / f"{_lock_key(dataset_key)}.lock",
                remaining,
            )
            dataset_lock.__enter__()
            remaining = max(0.0, deadline - time.monotonic())
            source_lock = CrossProcessFileLock(
                self.root / "source-streams" / f"{_lock_key(source)}.lock",
                remaining,
            )
            source_lock.__enter__()
            slot, slot_queued = self._acquire_slot(deadline)
            waited_ms = round((time.monotonic() - wait_started) * 1000)
            contention = {
                "dataset": dataset_lock.contended,
                "source": source_lock.contended,
                "host_slot": slot_queued,
            }
            lease = {
                "dataset_key": dataset_key,
                "source": source,
                "slot": slot.path.stem,
                "coordination_root": str(self.root),
                "requested_at": requested_at,
                "acquired_at": utc_now(),
                "waited_ms": waited_ms,
                "queued": any(contention.values()),
                "contention": contention,
            }
            lease_acquired = True
            logger.event(
                "dataset.coordination.acquired",
                phase="coordination",
                action="acquire_download_lease",
                outcome="success",
                source=source,
                message="已获取数据集下载资源",
                diagnostics=lease,
            )
            yield lease
        finally:
            if slot is not None:
                slot.__exit__(None, None, None)
            if source_lock is not None:
                source_lock.__exit__(None, None, None)
            if dataset_lock is not None:
                dataset_lock.__exit__(None, None, None)
            if lease_acquired:
                logger.event(
                    "dataset.coordination.released",
                    phase="coordination",
                    action="release_download_lease",
                    outcome="success",
                    source=source,
                    message="已释放数据集下载资源",
                    diagnostics={"dataset_key": dataset_key, "source": source},
                )


class HostRateLimiter:
    """File-backed request pacing shared by users and SPC processes on one host."""

    def __init__(
        self,
        root: str | os.PathLike[str],
        key: str,
        requests_per_second: float,
        *,
        lock_timeout_seconds: float = DEFAULT_LOCK_TIMEOUT_SECONDS,
        clock: Callable[[], float] = time.time,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        if requests_per_second <= 0:
            raise AcquisitionConfigurationError(
                "每秒请求数必须大于 0",
                error_code="invalid_request_rate",
            )
        self.root = Path(root).expanduser().resolve()
        self.key = _lock_key(key)
        self.minimum_interval = 1.0 / float(requests_per_second)
        self.lock_timeout_seconds = configured_lock_timeout(lock_timeout_seconds)
        self.clock = clock
        self.sleeper = sleeper

    def wait(self) -> None:
        directory = self.root / "rate-limits"
        state_path = directory / f"{self.key}.json"
        lock_path = directory / f"{self.key}.lock"
        with CrossProcessFileLock(lock_path, self.lock_timeout_seconds):
            last_started = 0.0
            try:
                payload = json.loads(state_path.read_text(encoding="utf-8"))
                last_started = float(payload.get("last_request_started_epoch") or 0.0)
            except (
                FileNotFoundError,
                OSError,
                ValueError,
                TypeError,
                json.JSONDecodeError,
            ):
                last_started = 0.0
            now = self.clock()
            if last_started > now:
                last_started = 0.0
            delay = self.minimum_interval - (now - last_started)
            if delay > 0:
                self.sleeper(delay)
            started = self.clock()
            _ensure_shared_directory(directory)
            descriptor, name = tempfile.mkstemp(
                prefix=f".{state_path.name}.", dir=directory
            )
            temporary = Path(name)
            try:
                with os.fdopen(
                    descriptor, "w", encoding="utf-8", newline="\n"
                ) as handle:
                    json.dump(
                        {
                            "schema_version": "spc.host-rate-limit-state.v1",
                            "last_request_started_epoch": started,
                        },
                        handle,
                        sort_keys=True,
                    )
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                _chmod_shared_file(temporary)
                os.replace(temporary, state_path)
            finally:
                with contextlib.suppress(FileNotFoundError):
                    temporary.unlink()


def atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    _ensure_shared_directory(path.parent)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        _chmod_shared_file(temporary)
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def write_acquisition_report(
    dataset_dir: str | os.PathLike[str],
    *,
    plan: Mapping[str, Any],
    status: str,
    attempts: Sequence[Mapping[str, Any]],
    files: Sequence[Mapping[str, Any]],
    error: Mapping[str, Any] | None = None,
    coordination: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    completed_at = utc_now()
    body = {
        "schema_version": REPORT_SCHEMA,
        "plan_id": plan.get("plan_id"),
        "dataset_ref": plan.get("dataset_ref"),
        "source_snapshot_digest": plan.get("source_snapshot_digest"),
        "host_id": plan.get("host_id"),
        "route": plan.get("route"),
        "status": status,
        "attempts": [dict(item) for item in attempts],
        "files": [dict(item) for item in files],
        "error": dict(error) if error else None,
        "coordination": dict(coordination or {}),
        "spc_git_sha": plan.get("spc_git_sha"),
        "producer_actor": plan.get("producer_actor"),
        "completed_at": completed_at,
    }
    report_digest = _digest(body)
    report = {**body, "report_id": report_digest, "content_digest": report_digest}
    root = Path(dataset_dir).expanduser().resolve()
    immutable = (
        root / "acquisition-reports" / f"{report_digest.removeprefix('sha256:')}.json"
    )
    latest = root / "acquisition_report.json"
    if immutable.exists():
        existing = json.loads(immutable.read_text(encoding="utf-8"))
        if existing != report:
            raise AcquisitionError(
                f"不可变下载审计报告发生内容冲突：{immutable.name}",
                error_code="immutable_report_collision",
                error_class="integrity_mismatch",
            )
    else:
        atomic_write_json(immutable, report)
    atomic_write_json(latest, report)
    return {**report, "report_path": str(immutable), "latest_report_path": str(latest)}
