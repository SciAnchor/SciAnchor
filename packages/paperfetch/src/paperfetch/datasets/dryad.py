"""可审计的 Dryad 数据集发现、下载、续传与校验。"""

from __future__ import annotations

import gzip
import os
import queue
import re
import tempfile
import time
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Optional
from urllib.parse import quote, urljoin

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from paperfetch.datasets.acquisition import (
    AcquisitionBusy,
    DownloadCoordinator,
    build_acquisition_plan,
    default_host_id,
    error_payload,
    resolve_coordination_root,
    resolve_http_route,
    source_route_from_environment,
    write_acquisition_report,
)
from paperfetch.datasets.geo import atomic_write_json, load_json, sha256_file
from paperfetch.observability import get_event_logger

DRYAD_ROOT = "https://datadryad.org"
DRYAD_DOI_PATTERN = re.compile(r"^10\.5061/dryad\.[A-Za-z0-9]+$", re.IGNORECASE)
STATE_FILENAME = "download_state.json"
ARCHIVE_FILENAME = "archive.json"
DEFAULT_MAX_DOWNLOAD_GB = 20.0
logger = get_event_logger("paperfetch.datasets.dryad")


class DryadDataError(RuntimeError):
    """Dryad 数据获取的基础异常。"""

    error_code = "dryad_acquisition_failed"
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


class DryadAuthenticationRequired(DryadDataError):
    """API 文件通路需要有效凭证。"""

    error_code = "dryad_authentication_required"
    error_class = "authentication_required"


class DryadBrowserRequired(DryadDataError):
    """公共 WAF 通路使用当前受控 Linux 浏览器执行。"""

    error_code = "dryad_browser_route_required"
    error_class = "browser_required"


class DryadLargeDownloadBlocked(DryadDataError):
    """所选数据集超过已配置的大文件门禁。"""

    error_code = "large_download_approval_required"
    error_class = "policy_blocked"

    def __init__(self, plan: dict[str, Any]):
        self.plan = plan
        super().__init__(
            "Dryad 下载需要明确授权："
            f"总大小 {plan['totals']['known_bytes']} 字节超过限制 "
            f"{plan['size_gate']['max_bytes']} 字节"
        )


@dataclass(frozen=True)
class DryadRemoteFile:
    file_id: int
    path: str
    size_bytes: int
    digest: str
    api_download_url: str
    public_download_url: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_dryad_doi(value: str) -> str:
    candidate = str(value or "").strip()
    if candidate.lower().startswith("doi:"):
        candidate = candidate[4:]
    if candidate.lower().startswith("https://doi.org/"):
        candidate = candidate[len("https://doi.org/") :]
    if not DRYAD_DOI_PATTERN.fullmatch(candidate):
        raise DryadDataError(
            f"无效的 Dryad DOI：{value!r}",
            error_code="invalid_dryad_doi",
            error_class="invalid_argument",
        )
    prefix, suffix = candidate.split("/", 1)
    return f"{prefix}/{suffix.lower()}"


def dryad_slug(doi: str) -> str:
    return normalize_dryad_doi(doi).split("/", 1)[1]


def resolve_dryad_root(output_dir: Optional[str | os.PathLike[str]] = None) -> Path:
    configured = output_dir or os.getenv("SPC_DRYAD_DATA_ROOT") or "~/.cache/spc/dryad"
    return Path(configured).expanduser().resolve()


def _new_session(proxy: Optional[str]) -> requests.Session:
    retry = Retry(
        total=5,
        connect=3,
        read=3,
        status=5,
        backoff_factor=0.75,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.trust_env = False
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "User-Agent": "SPC-Dryad/0.3",
            "Accept-Encoding": "gzip, deflate",
        }
    )
    if proxy:
        session.proxies.update({"http": proxy, "https": proxy})
    return session


def _safe_relative_path(value: str) -> Path:
    posix = PurePosixPath(str(value or ""))
    if (
        not posix.parts
        or posix.is_absolute()
        or any(part in {"", ".", ".."} for part in posix.parts)
    ):
        raise DryadDataError(
            f"不安全的 Dryad 文件路径：{value!r}",
            error_code="unsafe_dataset_path",
            error_class="invalid_argument",
        )
    return Path(*posix.parts)


def _response_is_html(response: requests.Response) -> bool:
    content_type = str(response.headers.get("Content-Type") or "").lower()
    return "text/html" in content_type


def _validate_local_file(path: Path, remote: DryadRemoteFile) -> dict[str, Any]:
    if not path.exists():
        raise DryadDataError(
            f"Dryad 文件下载后不存在：{remote.path}",
            error_code="downloaded_file_missing",
            error_class="integrity_mismatch",
        )
    size = path.stat().st_size
    if size != remote.size_bytes:
        raise DryadDataError(
            f"Dryad 文件大小不一致：{remote.path}，预期={remote.size_bytes}，实际={size}",
            error_code="download_size_mismatch",
            error_class="integrity_mismatch",
        )
    digest = sha256_file(path)
    if digest.lower() != remote.digest.lower():
        raise DryadDataError(
            f"Dryad 文件 SHA-256 不一致：{remote.path}，预期={remote.digest}，实际={digest}",
            error_code="download_digest_mismatch",
            error_class="integrity_mismatch",
        )
    with path.open("rb") as handle:
        prefix = handle.read(512).lstrip().lower()
    if prefix.startswith((b"<html", b"<!doctype html")):
        raise DryadDataError(
            f"Dryad 文件实际为 HTML 挑战页：{remote.path}",
            error_code="unexpected_html_content",
            error_class="identity_mismatch",
        )
    format_status = "not_applicable"
    suffix = path.suffix.lower()
    if suffix == ".zip":
        try:
            with zipfile.ZipFile(path) as archive:
                bad_member = archive.testzip()
        except zipfile.BadZipFile as exc:
            raise DryadDataError(
                f"Dryad ZIP 文件无效：{remote.path}",
                error_code="invalid_zip_archive",
                error_class="integrity_mismatch",
            ) from exc
        if bad_member:
            raise DryadDataError(
                f"Dryad ZIP CRC 校验失败：{remote.path}:{bad_member}",
                error_code="zip_crc_failed",
                error_class="integrity_mismatch",
            )
        format_status = "zip_crc_ok"
    elif suffix == ".gz":
        try:
            with gzip.open(path, "rb") as handle:
                handle.read(1)
        except (OSError, EOFError) as exc:
            raise DryadDataError(
                f"Dryad gzip 文件无效：{remote.path}",
                error_code="invalid_gzip_archive",
                error_class="integrity_mismatch",
            ) from exc
        format_status = "gzip_ok"
    elif suffix in {".csv", ".tsv", ".txt", ".md", ".json"}:
        try:
            path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DryadDataError(
                f"Dryad 文本文件不是 UTF-8：{remote.path}",
                error_code="invalid_text_encoding",
                error_class="integrity_mismatch",
            ) from exc
        format_status = "utf8_ok"
    return {
        "path": remote.path,
        "bytes": size,
        "sha256": digest,
        "format_status": format_status,
    }


def _atomic_copy_download(download: Any, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".part", dir=target.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        download.save_as(str(temporary))
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _wait_for_browser_download(
    downloads: "queue.Queue[Any]", page: Any, timeout_seconds: float
) -> Any:
    """Pump the synchronous Playwright loop while waiting for a download event."""
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            return downloads.get_nowait()
        except queue.Empty:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise queue.Empty from None
            # Blocking on Queue.get() prevents sync Playwright from dispatching
            # context/page events. A short Playwright wait yields to its event loop.
            page.wait_for_timeout(min(250, max(1, int(remaining * 1000))))


def _browser_http_session(
    context: Any, page: Any, proxy: Optional[str]
) -> requests.Session:
    """Create a streaming session from the browser's validated, in-memory cookies."""
    session = _new_session(proxy)
    user_agent = str(page.evaluate("navigator.userAgent") or "").strip()
    if user_agent:
        session.headers["User-Agent"] = user_agent
    session.headers["Accept-Encoding"] = "identity"
    for item in context.cookies(DRYAD_ROOT):
        session.cookies.set(
            str(item["name"]),
            str(item["value"]),
            domain=str(item.get("domain") or "datadryad.org"),
            path=str(item.get("path") or "/"),
        )
    return session


def _download_browser_http_file(
    session: requests.Session,
    remote: DryadRemoteFile,
    dataset_dir: Path,
    *,
    force: bool,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Stream a public file with the browser-validated session and Range resume."""
    target = dataset_dir / _safe_relative_path(remote.path)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.parent / f".{target.name}.part"
    if force:
        partial.unlink(missing_ok=True)
    existing = partial.stat().st_size if partial.exists() else 0
    if existing > remote.size_bytes:
        partial.unlink()
        existing = 0
    headers = {"Range": f"bytes={existing}-"} if existing else {}
    started = time.perf_counter()
    response = session.get(
        remote.public_download_url,
        headers=headers,
        stream=True,
        allow_redirects=True,
        timeout=(10.0, timeout_seconds),
    )
    if existing and response.status_code != 206:
        response.close()
        partial.unlink(missing_ok=True)
        existing = 0
        response = session.get(
            remote.public_download_url,
            stream=True,
            allow_redirects=True,
            timeout=(10.0, timeout_seconds),
        )
    if existing and response.status_code == 206:
        content_range = str(response.headers.get("Content-Range") or "")
        if content_range and not content_range.startswith(f"bytes {existing}-"):
            response.close()
            raise DryadDataError(
                f"Dryad 浏览器续传区间不一致：{remote.path}，预期起点={existing}",
                error_code="resume_range_mismatch",
                error_class="integrity_mismatch",
            )
    try:
        response.raise_for_status()
        if _response_is_html(response):
            raise DryadDataError(
                f"Dryad 浏览器会话返回了 HTML 而不是文件：{remote.path}",
                error_code="unexpected_html_content",
                error_class="identity_mismatch",
            )
        mode = "ab" if existing and response.status_code == 206 else "wb"
        with partial.open(mode) as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                handle.write(chunk)
                if handle.tell() > remote.size_bytes:
                    raise DryadDataError(
                        f"Dryad 文件大小超出预期：{remote.path}",
                        error_code="download_size_overrun",
                        error_class="integrity_mismatch",
                    )
            handle.flush()
            os.fsync(handle.fileno())
    except requests.RequestException as exc:
        raise DryadDataError(
            f"Dryad 浏览器流式下载失败：{remote.path}，原因={type(exc).__name__}",
            error_code="browser_stream_failed",
            error_class="network_error",
        ) from exc
    finally:
        response.close()
    actual = partial.stat().st_size if partial.exists() else 0
    if actual != remote.size_bytes:
        raise DryadDataError(
            f"Dryad 浏览器下载不完整：{remote.path}，预期={remote.size_bytes}，实际={actual}",
            error_code="download_incomplete",
            error_class="integrity_mismatch",
        )
    digest = sha256_file(partial)
    if digest.lower() != remote.digest.lower():
        partial.unlink(missing_ok=True)
        raise DryadDataError(
            f"Dryad 文件 SHA-256 不一致：{remote.path}",
            error_code="download_digest_mismatch",
            error_class="integrity_mismatch",
        )
    os.replace(partial, target)
    elapsed_ms = round((time.perf_counter() - started) * 1000)
    return {
        **_validate_local_file(target, remote),
        "route": "browser_http",
        "status": "complete",
        "reused": False,
        "resumed_from": existing,
        "elapsed_ms": elapsed_ms,
        "bytes_per_second": round(
            (remote.size_bytes - existing) / max(elapsed_ms / 1000, 0.001)
        ),
    }


def download_with_browser(
    *,
    doi: str,
    files: list[DryadRemoteFile],
    dataset_dir: Path,
    force: bool,
    proxy: Optional[str],
    timeout_seconds: float,
) -> list[dict[str, Any]]:
    """Download public Dryad files through SPC's controlled local browser."""
    try:
        from playwright.sync_api import sync_playwright
    except (
        ImportError
    ) as exc:  # pragma: no cover - dependency is a production prerequisite.
        raise DryadBrowserRequired(
            "Dryad 浏览器通路需要安装 playwright（pip install 'paperfetch[browser]'）",
            error_code="browser_runtime_missing",
        ) from exc

    executable_path = str(os.getenv("DRYAD_BROWSER_EXECUTABLE_PATH") or "").strip()
    channel = str(os.getenv("DRYAD_BROWSER_CHANNEL") or "").strip()
    headless = str(os.getenv("DRYAD_BROWSER_HEADLESS") or "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    timeout_ms = int(max(10.0, timeout_seconds) * 1000)
    stream_threshold = int(
        float(os.getenv("DRYAD_BROWSER_STREAM_THRESHOLD_MB") or "32") * 1024**2
    )
    results: list[dict[str, Any]] = []
    browser_stream: Optional[requests.Session] = None
    with sync_playwright() as playwright:
        launch_options: dict[str, Any] = {"headless": headless}
        if executable_path:
            launch_options["executable_path"] = executable_path
        elif channel:
            launch_options["channel"] = channel
        if proxy:
            launch_options["proxy"] = {"server": proxy}
        browser = playwright.chromium.launch(**launch_options)
        context = browser.new_context(accept_downloads=True)
        downloads: "queue.Queue[Any]" = queue.Queue()

        def attach(page: Any) -> None:
            page.on("download", downloads.put)

        context.on("page", attach)
        page = context.new_page()
        attach(page)
        page.goto(
            f"{DRYAD_ROOT}/dataset/doi:{normalize_dryad_doi(doi)}",
            wait_until="domcontentloaded",
            timeout=timeout_ms,
        )
        try:
            for remote in files:
                target = dataset_dir / _safe_relative_path(remote.path)
                if target.exists() and not force:
                    try:
                        verified = _validate_local_file(target, remote)
                        results.append(
                            {
                                **verified,
                                "route": "existing",
                                "status": "complete",
                                "reused": True,
                                "resumed_from": 0,
                            }
                        )
                        continue
                    except DryadDataError:
                        pass
                selector = f'a[href="/downloads/file_stream/{remote.file_id}"]'
                page.locator(selector).wait_for(state="visible", timeout=timeout_ms)
                started = time.perf_counter()
                page.locator(selector).click()
                try:
                    download = _wait_for_browser_download(
                        downloads, page, timeout_seconds
                    )
                except queue.Empty as exc:
                    raise DryadDataError(
                        f"等待 Dryad 浏览器下载超时：{remote.path}",
                        error_code="browser_download_timeout",
                        error_class="timeout",
                    ) from exc
                if remote.size_bytes >= stream_threshold:
                    download.cancel()
                    if browser_stream is None:
                        browser_stream = _browser_http_session(context, page, proxy)
                    results.append(
                        _download_browser_http_file(
                            browser_stream,
                            remote,
                            dataset_dir,
                            force=force,
                            timeout_seconds=timeout_seconds,
                        )
                    )
                    continue
                _atomic_copy_download(download, target)
                verified = _validate_local_file(target, remote)
                elapsed_ms = round((time.perf_counter() - started) * 1000)
                results.append(
                    {
                        **verified,
                        "route": "browser",
                        "status": "complete",
                        "reused": False,
                        "resumed_from": 0,
                        "elapsed_ms": elapsed_ms,
                        "bytes_per_second": round(
                            remote.size_bytes / max(elapsed_ms / 1000, 0.001)
                        ),
                    }
                )
        finally:
            if browser_stream is not None:
                browser_stream.close()
            context.close()
            browser.close()
    return results


class DryadDatasetStore:
    """Discover, download, and verify a versioned Dryad dataset."""

    def __init__(
        self,
        output_dir: Optional[str | os.PathLike[str]] = None,
        *,
        token: Optional[str] = None,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        proxy: Optional[str] = None,
        session: Optional[requests.Session] = None,
        max_download_gb: float = DEFAULT_MAX_DOWNLOAD_GB,
        timeout_seconds: float = 180.0,
        browser_downloader: Optional[Callable[..., list[dict[str, Any]]]] = None,
        coordination_root: Optional[str | os.PathLike[str]] = None,
        dataset_concurrency: Optional[int] = None,
        lock_timeout_seconds: float = 30.0,
        host_id: Optional[str] = None,
    ):
        self.root = resolve_dryad_root(output_dir)
        self.token = (
            token if token is not None else os.getenv("DRYAD_API_TOKEN") or ""
        ).strip()
        self.client_id = (
            client_id if client_id is not None else os.getenv("DRYAD_CLIENT_ID") or ""
        ).strip()
        self.client_secret = (
            client_secret
            if client_secret is not None
            else os.getenv("DRYAD_CLIENT_SECRET") or ""
        ).strip()
        self.route_decision = (
            resolve_http_route("proxy" if proxy else "direct", proxy)
            if proxy is not None
            else source_route_from_environment("dryad")
        )
        self.proxy = self.route_decision.proxy_url
        self.session = session or _new_session(self.proxy)
        self._owns_session = session is None
        self.max_download_bytes = int(max_download_gb * 1024**3)
        self.timeout_seconds = max(10.0, float(timeout_seconds))
        self.browser_downloader = browser_downloader or download_with_browser
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

    def __enter__(self) -> "DryadDatasetStore":
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def _get_json(self, url: str) -> dict[str, Any]:
        try:
            response = self.session.get(
                url,
                timeout=(10.0, self.timeout_seconds),
                allow_redirects=True,
            )
            response.raise_for_status()
            payload = response.json()
            response.close()
        except (requests.RequestException, ValueError) as exc:
            raise DryadDataError(
                f"无法读取 Dryad 元数据：{type(exc).__name__}",
                error_code="dryad_metadata_unavailable",
                error_class="network_error",
            ) from exc
        if not isinstance(payload, dict):
            raise DryadDataError(
                "Dryad 元数据响应不是 JSON 对象",
                error_code="dryad_metadata_format_invalid",
                error_class="identity_mismatch",
            )
        return payload

    def discover(self, doi: str) -> tuple[dict[str, Any], list[DryadRemoteFile]]:
        normalized = normalize_dryad_doi(doi)
        dataset_url = (
            f"{DRYAD_ROOT}/api/v2/datasets/{quote('doi:' + normalized, safe='')}"
        )
        dataset = self._get_json(dataset_url)
        actual = str(dataset.get("identifier") or "").removeprefix("doi:")
        if normalize_dryad_doi(actual) != normalized:
            raise DryadDataError(
                f"Dryad 数据集身份不一致：预期={normalized}，实际={actual}",
                error_code="dataset_identity_mismatch",
                error_class="identity_mismatch",
            )
        version_href = str(
            (dataset.get("_links") or {}).get("stash:version", {}).get("href") or ""
        )
        match = re.search(r"/versions/(\d+)$", version_href)
        if not match:
            raise DryadDataError(
                "Dryad 元数据未提供版本标识",
                error_code="dataset_version_missing",
                error_class="identity_mismatch",
            )
        version_id = int(match.group(1))
        files_url = f"{DRYAD_ROOT}/api/v2/versions/{version_id}/files"
        remote_files: list[DryadRemoteFile] = []
        seen_urls: set[str] = set()
        while files_url and files_url not in seen_urls:
            seen_urls.add(files_url)
            payload = self._get_json(files_url)
            embedded = (payload.get("_embedded") or {}).get("stash:files") or []
            for item in embedded:
                api_href = str(
                    (item.get("_links") or {}).get("stash:download", {}).get("href")
                    or ""
                )
                id_match = re.search(r"/files/(\d+)/download$", api_href)
                if not id_match:
                    raise DryadDataError(
                        "Dryad 文件元数据缺少稳定文件 ID",
                        error_code="file_identity_missing",
                        error_class="identity_mismatch",
                    )
                path = str(item.get("path") or "")
                _safe_relative_path(path)
                digest = str(item.get("digest") or "").lower()
                if not re.fullmatch(r"[0-9a-f]{64}", digest):
                    raise DryadDataError(
                        f"Dryad 文件缺少 SHA-256 摘要：{path}",
                        error_code="file_digest_missing",
                        error_class="identity_mismatch",
                    )
                size = item.get("size")
                if not isinstance(size, int) or size < 0:
                    raise DryadDataError(
                        f"Dryad 文件大小无效：{path}",
                        error_code="file_size_invalid",
                        error_class="identity_mismatch",
                    )
                file_id = int(id_match.group(1))
                remote_files.append(
                    DryadRemoteFile(
                        file_id=file_id,
                        path=path,
                        size_bytes=size,
                        digest=digest,
                        api_download_url=urljoin(DRYAD_ROOT, api_href),
                        public_download_url=f"{DRYAD_ROOT}/downloads/file_stream/{file_id}",
                    )
                )
            next_href = str(
                (payload.get("_links") or {}).get("next", {}).get("href") or ""
            )
            files_url = urljoin(DRYAD_ROOT, next_href) if next_href else ""
        metadata = {
            "doi": normalized,
            "title": dataset.get("title"),
            "publication_date": dataset.get("publicationDate"),
            "version_status": dataset.get("versionStatus"),
            "version_id": version_id,
            "license": dataset.get("license"),
        }
        return metadata, sorted(remote_files, key=lambda item: item.path)

    def plan(
        self,
        doi: str,
        filenames: Optional[Iterable[str]] = None,
        *,
        route: str = "auto",
    ) -> dict[str, Any]:
        metadata, available = self.discover(doi)
        requested = {str(item).strip() for item in filenames or [] if str(item).strip()}
        selected = [
            item for item in available if not requested or item.path in requested
        ]
        missing = sorted(requested - {item.path for item in selected})
        if missing:
            raise DryadDataError(
                f"未找到指定的 Dryad 文件：{', '.join(missing)}",
                error_code="dataset_files_not_found",
                error_class="not_found",
            )
        total = sum(item.size_bytes for item in selected)
        requested_route = route.strip().lower()
        if requested_route not in {"auto", "api", "browser"}:
            raise DryadDataError(
                f"未知的 Dryad 下载通路：{route}",
                error_code="unknown_dryad_route",
                error_class="invalid_configuration",
            )
        access_route = requested_route
        if access_route == "auto":
            access_route = "api" if self.token or self._can_refresh_token else "browser"
        plan = {
            "schema_version": "spc.dryad.plan.v1",
            **metadata,
            "files": [item.to_dict() for item in selected],
            "totals": {"files": len(selected), "known_bytes": total},
            "size_gate": {
                "max_bytes": self.max_download_bytes,
                "blocked": total > self.max_download_bytes,
                "approval_flag": "--allow-large",
            },
        }
        acquisition = build_acquisition_plan(
            dataset_ref=f"dataset:dryad:{dryad_slug(metadata['doi'])}@{metadata['version_id']}",
            source="dryad",
            host_id=self.host_id,
            files=plan["files"],
            route=self.route_decision,
            access_route=access_route,
            output_dir=str(self.root / dryad_slug(metadata["doi"])),
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
            "route_audit": acquisition["route"],
            "concurrency": acquisition["concurrency"],
            "created_at": acquisition["created_at"],
            "producer_actor": acquisition["producer_actor"],
            "spc_git_sha": acquisition["spc_git_sha"],
        }

    @property
    def _can_refresh_token(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def _refresh_api_token(self) -> None:
        if not self._can_refresh_token:
            raise DryadAuthenticationRequired(
                "Dryad API 下载需要 DRYAD_API_TOKEN，或同时配置 "
                "DRYAD_CLIENT_ID 与 DRYAD_CLIENT_SECRET"
            )
        try:
            response = self.session.post(
                f"{DRYAD_ROOT}/oauth/token",
                data={"grant_type": "client_credentials"},
                auth=(self.client_id, self.client_secret),
                timeout=(10.0, self.timeout_seconds),
            )
            payload = response.json()
            status_code = response.status_code
            response.close()
        except (requests.RequestException, ValueError) as exc:
            raise DryadAuthenticationRequired(
                f"无法刷新 Dryad API 令牌：{type(exc).__name__}",
                error_code="dryad_token_refresh_failed",
                error_class="network_error",
            ) from exc
        if status_code in {401, 403}:
            raise DryadAuthenticationRequired(
                f"Dryad API 客户端凭证被拒绝（HTTP {status_code}）",
                error_code="dryad_client_credentials_rejected",
            )
        if status_code >= 400:
            raise DryadAuthenticationRequired(
                f"Dryad API 令牌刷新失败（HTTP {status_code}）",
                error_code="dryad_token_refresh_failed",
            )
        token = (
            str(payload.get("access_token") or "").strip()
            if isinstance(payload, dict)
            else ""
        )
        if not token:
            raise DryadAuthenticationRequired(
                "Dryad API 令牌响应未包含 access_token",
                error_code="dryad_token_missing",
            )
        self.token = token

    def _api_headers(self, existing: int) -> dict[str, str]:
        if not self.token:
            self._refresh_api_token()
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept-Encoding": "identity",
        }
        if existing:
            headers["Range"] = f"bytes={existing}-"
        return headers

    def _request_api_file(
        self, remote: DryadRemoteFile, existing: int, *, allow_refresh: bool = True
    ) -> requests.Response:
        response = self.session.get(
            remote.api_download_url,
            headers=self._api_headers(existing),
            stream=True,
            allow_redirects=True,
            timeout=(10.0, self.timeout_seconds),
        )
        if response.status_code == 401 and allow_refresh and self._can_refresh_token:
            response.close()
            self._refresh_api_token()
            return self._request_api_file(remote, existing, allow_refresh=False)
        if response.status_code == 401:
            response.close()
            raise DryadAuthenticationRequired(
                "Dryad API 令牌被拒绝（HTTP 401）",
                error_code="dryad_token_rejected",
            )
        if response.status_code == 403:
            response.close()
            raise DryadAuthenticationRequired(
                "Dryad API 令牌缺少文件下载权限（HTTP 403）",
                error_code="dryad_download_permission_denied",
            )
        return response

    def _download_api_file(
        self, remote: DryadRemoteFile, dataset_dir: Path, *, force: bool
    ) -> dict[str, Any]:
        target = dataset_dir / _safe_relative_path(remote.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and not force:
            try:
                return {
                    **_validate_local_file(target, remote),
                    "route": "existing",
                    "status": "complete",
                    "reused": True,
                    "resumed_from": 0,
                }
            except DryadDataError:
                pass
        partial = target.parent / f".{target.name}.part"
        if force:
            partial.unlink(missing_ok=True)
        existing = partial.stat().st_size if partial.exists() else 0
        if existing > remote.size_bytes:
            partial.unlink()
            existing = 0
        started = time.perf_counter()
        response = self._request_api_file(remote, existing)
        if existing and response.status_code != 206:
            response.close()
            partial.unlink(missing_ok=True)
            existing = 0
            response = self._request_api_file(remote, 0)
        if existing and response.status_code == 206:
            content_range = str(response.headers.get("Content-Range") or "")
            expected_range = f"bytes {existing}-"
            if not content_range.startswith(expected_range):
                response.close()
                raise DryadDataError(
                    f"Dryad API 续传区间不一致：{remote.path}，预期起点={existing}",
                    error_code="resume_range_mismatch",
                    error_class="integrity_mismatch",
                )
        try:
            response.raise_for_status()
            if _response_is_html(response):
                raise DryadDataError(
                    f"Dryad API 返回了 HTML 而不是文件：{remote.path}",
                    error_code="unexpected_html_content",
                    error_class="identity_mismatch",
                )
            mode = "ab" if existing and response.status_code == 206 else "wb"
            with partial.open(mode) as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    handle.write(chunk)
                    if handle.tell() > remote.size_bytes:
                        raise DryadDataError(
                            f"Dryad 文件大小超出预期：{remote.path}",
                            error_code="download_size_overrun",
                            error_class="integrity_mismatch",
                        )
                handle.flush()
                os.fsync(handle.fileno())
        except requests.RequestException as exc:
            raise DryadDataError(
                f"Dryad API 文件下载失败：{remote.path}，原因={type(exc).__name__}",
                error_code="dryad_api_download_failed",
                error_class="network_error",
            ) from exc
        finally:
            response.close()
        if partial.stat().st_size != remote.size_bytes:
            raise DryadDataError(
                f"Dryad 下载不完整：{remote.path}，"
                f"预期={remote.size_bytes}，实际={partial.stat().st_size}",
                error_code="download_incomplete",
                error_class="integrity_mismatch",
            )
        if sha256_file(partial).lower() != remote.digest.lower():
            partial.unlink(missing_ok=True)
            raise DryadDataError(
                f"Dryad 文件 SHA-256 不一致：{remote.path}",
                error_code="download_digest_mismatch",
                error_class="integrity_mismatch",
            )
        os.replace(partial, target)
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        return {
            **_validate_local_file(target, remote),
            "route": "api",
            "status": "complete",
            "reused": False,
            "resumed_from": existing,
            "elapsed_ms": elapsed_ms,
            "bytes_per_second": round(
                (remote.size_bytes - existing) / max(elapsed_ms / 1000, 0.001)
            ),
        }

    def download(
        self,
        doi: str,
        *,
        filenames: Optional[Iterable[str]] = None,
        route: str = "auto",
        force: bool = False,
        allow_large: bool = False,
    ) -> dict[str, Any]:
        plan = self.plan(doi, filenames, route=route)
        if plan["size_gate"]["blocked"] and not allow_large:
            raise DryadLargeDownloadBlocked(plan)
        selected = [DryadRemoteFile(**item) for item in plan["files"]]
        normalized = plan["doi"]
        dataset_dir = self.root / dryad_slug(normalized)
        dataset_dir.mkdir(parents=True, exist_ok=True)
        requested_route = route.strip().lower()
        if "route_audit" not in plan:
            access_route = requested_route
            if access_route == "auto":
                access_route = (
                    "api" if self.token or self._can_refresh_token else "browser"
                )
            acquisition = build_acquisition_plan(
                dataset_ref=f"dataset:dryad:{dryad_slug(normalized)}@{plan['version_id']}",
                source="dryad",
                host_id=self.host_id,
                files=plan["files"],
                route=self.route_decision,
                access_route=access_route,
                output_dir=str(dataset_dir),
                size_gate=plan["size_gate"],
                dataset_concurrency=self.coordinator.dataset_concurrency,
            )
            plan = {
                **plan,
                "dataset_ref": acquisition["dataset_ref"],
                "source_snapshot_digest": acquisition["source_snapshot_digest"],
                "plan_id": acquisition["plan_id"],
                "content_digest": acquisition["content_digest"],
                "host_id": acquisition["host_id"],
                "route_audit": acquisition["route"],
                "producer_actor": acquisition["producer_actor"],
                "spc_git_sha": acquisition["spc_git_sha"],
            }
        selected_route = str(plan["route_audit"]["access_route"])
        state_path = dataset_dir / STATE_FILENAME
        archive_path = dataset_dir / ARCHIVE_FILENAME
        state = {
            "schema_version": "spc.dryad.download-state.v1",
            "doi": normalized,
            "version_id": plan["version_id"],
            "status": "running",
            "route": selected_route,
            "files": {},
            "last_error": None,
        }
        attempts: list[dict[str, Any]] = []
        coordination: dict[str, Any] = {}
        source_lock_key = (
            "browser-global" if selected_route == "browser" else "dryad-api"
        )
        try:
            coordination_context = self.coordinator.acquire(
                dataset_key=plan["dataset_ref"],
                source=source_lock_key,
            )
            coordination = coordination_context.__enter__()
        except AcquisitionBusy as exc:
            failure = error_payload(exc)
            write_acquisition_report(
                dataset_dir,
                plan={**plan, "route": plan["route_audit"]},
                status="failed_retryable",
                attempts=[{"route": selected_route, "status": "resource_busy"}],
                files=[],
                error=failure,
            )
            logger.event(
                "dryad.download.blocked",
                phase="dataset_download",
                action="download_dataset",
                outcome="blocked",
                level="WARNING",
                source="dryad",
                error_class=failure["error_class"],
                message=f"Dryad 数据集下载暂时阻断：{normalized}",
                diagnostics={"doi": normalized, "error_code": failure["error_code"]},
            )
            raise
        try:
            logger.event(
                "dryad.download.started",
                phase="dataset_download",
                action="download_dataset",
                outcome="started",
                source="dryad",
                route=selected_route,
                message=f"开始下载 Dryad 数据集：{normalized}",
                diagnostics={
                    "doi": normalized,
                    "dataset_ref": plan["dataset_ref"],
                    "file_count": len(selected),
                    "transport_route": plan["route_audit"]["resolved_route"],
                },
            )
            atomic_write_json(state_path, state)
            try:
                if selected_route == "api":
                    try:
                        results = [
                            self._download_api_file(remote, dataset_dir, force=force)
                            for remote in selected
                        ]
                        attempts.append({"route": "api", "status": "complete"})
                    except DryadAuthenticationRequired as exc:
                        failure = error_payload(exc)
                        attempts.append(
                            {"route": "api", "status": "authentication_required"}
                        )
                        if requested_route != "auto":
                            raise
                        logger.event(
                            "dryad.download.route_fallback",
                            phase="dataset_download",
                            action="fallback_route",
                            outcome="degraded",
                            level="WARNING",
                            source="dryad",
                            route="api",
                            error_class=failure["error_class"],
                            message="Dryad API 凭证不可用，切换到浏览器通路",
                            diagnostics={
                                "doi": normalized,
                                "error_code": failure["error_code"],
                                "next_route": "browser",
                            },
                        )
                        selected_route = "browser"
                        state["route"] = selected_route
                        atomic_write_json(state_path, state)
                        with self.coordinator.acquire_source(
                            "browser-global"
                        ) as browser_coordination:
                            coordination["fallback_source"] = browser_coordination
                            results = self.browser_downloader(
                                doi=normalized,
                                files=selected,
                                dataset_dir=dataset_dir,
                                force=force,
                                proxy=self.proxy,
                                timeout_seconds=self.timeout_seconds,
                            )
                        attempts.append({"route": "browser", "status": "complete"})
                else:
                    results = self.browser_downloader(
                        doi=normalized,
                        files=selected,
                        dataset_dir=dataset_dir,
                        force=force,
                        proxy=self.proxy,
                        timeout_seconds=self.timeout_seconds,
                    )
                    attempts.append({"route": "browser", "status": "complete"})
                by_path = {item["path"]: item for item in results}
                if set(by_path) != {item.path for item in selected}:
                    raise DryadDataError(
                        "Dryad 下载器未返回全部选定文件的结果",
                        error_code="download_result_incomplete",
                        error_class="integrity_mismatch",
                    )
                state["files"] = by_path
                state["status"] = "complete"
                archive = {
                    "schema_version": "spc.dryad.archive.v1",
                    "doi": normalized,
                    "title": plan.get("title"),
                    "publication_date": plan.get("publication_date"),
                    "version_id": plan["version_id"],
                    "status": "complete",
                    "route": selected_route,
                    "files": results,
                }
                atomic_write_json(state_path, state)
                atomic_write_json(archive_path, archive)
                report = write_acquisition_report(
                    dataset_dir,
                    plan={**plan, "route": plan["route_audit"]},
                    status="complete",
                    attempts=attempts,
                    files=results,
                    coordination=coordination,
                )
                logger.event(
                    "dryad.download.completed",
                    phase="dataset_download",
                    action="download_dataset",
                    outcome="success",
                    source="dryad",
                    route=selected_route,
                    message=f"Dryad 数据集下载完成：{normalized}",
                    diagnostics={
                        "doi": normalized,
                        "dataset_ref": plan["dataset_ref"],
                        "file_count": len(results),
                        "downloaded_bytes": sum(int(item["bytes"]) for item in results),
                    },
                )
                return {
                    "schema_version": "spc.dryad.command-result.v1",
                    "doi": normalized,
                    "status": "complete",
                    "route": selected_route,
                    "dataset_dir": str(dataset_dir),
                    "state_path": str(state_path),
                    "archive_path": str(archive_path),
                    "plan_id": plan["plan_id"],
                    "dataset_ref": plan["dataset_ref"],
                    "resolved_route": selected_route,
                    "transport_route": plan["route_audit"]["resolved_route"],
                    "acquisition_report_path": report["report_path"],
                    "files": {
                        "total": len(results),
                        "complete": len(results),
                        "downloaded_bytes": sum(int(item["bytes"]) for item in results),
                    },
                }
            except Exception as exc:
                failure = error_payload(exc)
                state["status"] = "failed"
                state["last_error"] = failure["message"]
                state["error_code"] = failure["error_code"]
                state["error_class"] = failure["error_class"]
                atomic_write_json(state_path, state)
                write_acquisition_report(
                    dataset_dir,
                    plan={**plan, "route": plan["route_audit"]},
                    status=(
                        "failed_retryable"
                        if isinstance(
                            exc,
                            (
                                AcquisitionBusy,
                                requests.Timeout,
                                requests.ConnectionError,
                            ),
                        )
                        else "failed_terminal"
                    ),
                    attempts=attempts
                    or [{"route": selected_route, "status": "failed"}],
                    files=[],
                    error=failure,
                    coordination=coordination,
                )
                logger.event(
                    "dryad.download.failed",
                    phase="dataset_download",
                    action="download_dataset",
                    outcome="failed",
                    level="ERROR",
                    source="dryad",
                    route=selected_route,
                    error_class=failure["error_class"],
                    message=f"Dryad 数据集下载失败：{normalized}",
                    diagnostics={
                        "doi": normalized,
                        "dataset_ref": plan["dataset_ref"],
                        "error_code": failure["error_code"],
                        "exception_type": type(exc).__name__,
                    },
                )
                raise
        finally:
            coordination_context.__exit__(None, None, None)

    def inspect(self, doi: str, *, verify: bool = False) -> dict[str, Any]:
        normalized = normalize_dryad_doi(doi)
        dataset_dir = self.root / dryad_slug(normalized)
        archive_path = dataset_dir / ARCHIVE_FILENAME
        archive = load_json(archive_path)
        if archive is None:
            return {
                "schema_version": "spc.dryad.command-result.v1",
                "doi": normalized,
                "status": "not_downloaded",
                "dataset_dir": str(dataset_dir),
            }
        entries = archive.get("files") or []
        failed = 0
        files = []
        for entry in entries:
            path = dataset_dir / _safe_relative_path(str(entry.get("path") or ""))
            current = dict(entry)
            if verify:
                if not path.exists():
                    current["verification_error"] = "missing"
                    failed += 1
                elif path.stat().st_size != int(entry.get("bytes") or -1):
                    current["verification_error"] = "size_mismatch"
                    failed += 1
                elif sha256_file(path) != str(entry.get("sha256") or ""):
                    current["verification_error"] = "sha256_mismatch"
                    failed += 1
                else:
                    current["verification_error"] = None
            files.append(current)
        status = "invalid" if failed else str(archive.get("status") or "complete")
        return {
            "schema_version": "spc.dryad.command-result.v1",
            "doi": normalized,
            "status": status,
            "route": archive.get("route"),
            "dataset_dir": str(dataset_dir),
            "archive_path": str(archive_path),
            "files": {
                "total": len(files),
                "complete": len(files) - failed,
                "failed": failed,
                "downloaded_bytes": sum(int(item.get("bytes") or 0) for item in files),
            },
        }
