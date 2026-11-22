from __future__ import annotations

import json
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable

JsonFetcher = Callable[[str, dict[str, str], bytes | None, str | None], Any]
BinaryFetcher = Callable[[str, dict[str, str]], bytes]
Uploader = Callable[[str, bytes], None]

DEFAULT_MINERU_BASE_URL = "https://mineru.net"


class MinerUError(RuntimeError):
    pass


class MinerUAuthError(MinerUError):
    pass


class MinerURateLimitError(MinerUError):
    pass


class MinerUZipPathError(MinerUError):
    pass


class MinerUZipContentError(MinerUError):
    pass


@dataclass(frozen=True)
class MinerUParseItem:
    paper_id: int
    title: str
    pdf_path: Path
    output_dir: Path


@dataclass
class MinerUParseResult:
    paper_id: int
    status: str
    output_dir: str = ""
    markdown_path: str = ""
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class MinerUParseReport:
    dry_run: bool = False
    enabled: bool = False
    processed: int = 0
    parsed: int = 0
    skipped: int = 0
    failed: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MinerUClient:
    def __init__(
        self,
        api_token: str,
        *,
        base_url: str = DEFAULT_MINERU_BASE_URL,
        fetcher: JsonFetcher | None = None,
        binary_fetcher: BinaryFetcher | None = None,
        uploader: Uploader | None = None,
    ):
        self.api_token = api_token.strip()
        self.base_url = base_url.rstrip("/") or DEFAULT_MINERU_BASE_URL
        self.api_base = f"{self.base_url}/api/v4"
        self._fetcher = fetcher or self._default_json_fetcher
        self._binary_fetcher = binary_fetcher or self._default_binary_fetcher
        self._uploader = uploader or self._default_uploader

    def request_upload_urls(self, items: list[MinerUParseItem]) -> dict[str, Any]:
        payload = {
            "files": [
                {"name": item.pdf_path.name, "data_id": str(item.paper_id)}
                for item in items
            ]
        }
        return self._request_json(
            f"{self.api_base}/file-urls/batch",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
        )

    def upload_files(
        self, items: list[MinerUParseItem], upload_response: dict[str, Any]
    ) -> list[MinerUParseItem]:
        failed: list[MinerUParseItem] = []
        upload_items = _extract_upload_items(upload_response)
        by_data_id = {str(item.get("data_id") or ""): item for item in upload_items}
        for item in items:
            upload_item = by_data_id.get(str(item.paper_id))
            upload_url = str((upload_item or {}).get("upload_url") or "")
            if not upload_url:
                failed.append(item)
                continue
            try:
                self._uploader(upload_url, item.pdf_path.read_bytes())
            except Exception:
                failed.append(item)
        return failed

    def poll_batch_results(self, batch_id: str) -> dict[str, Any]:
        poll_interval = _float_env("MINERU_POLL_INTERVAL_SECONDS", 2.0)
        timeout = _float_env("MINERU_POLL_TIMEOUT_SECONDS", 600.0)
        deadline = time.monotonic() + timeout
        while True:
            payload = self._request_json(
                f"{self.api_base}/extract-results/batch/{batch_id}"
            )
            states = [
                str(item.get("state") or "") for item in _extract_result_items(payload)
            ]
            if states and all(state in {"done", "failed"} for state in states):
                return payload
            if time.monotonic() >= deadline:
                raise MinerUError("poll_timeout")
            time.sleep(max(0.1, poll_interval))

    def download_and_extract(
        self, items: list[MinerUParseItem], result_response: dict[str, Any]
    ) -> list[MinerUParseResult]:
        results: list[MinerUParseResult] = []
        by_data_id = {
            str(item.get("data_id") or ""): item
            for item in _extract_result_items(result_response)
        }
        for item in items:
            payload = by_data_id.get(str(item.paper_id)) or {}
            if str(payload.get("state") or "") == "failed":
                results.append(
                    MinerUParseResult(
                        paper_id=item.paper_id,
                        status="failed",
                        error=str(payload.get("err_msg") or "parse_failed"),
                    )
                )
                continue
            zip_url = str(payload.get("full_zip_url") or payload.get("zip_url") or "")
            if not zip_url:
                results.append(
                    MinerUParseResult(
                        paper_id=item.paper_id,
                        status="failed",
                        error="missing_zip_url",
                    )
                )
                continue
            try:
                item.output_dir.parent.mkdir(parents=True, exist_ok=True)
                zip_path = item.output_dir.with_suffix(".zip")
                zip_path.write_bytes(
                    self._binary_fetcher(zip_url, self._auth_headers())
                )
                extract_mineru_zip(zip_path, item.output_dir)
                markdown_path = item.output_dir / "full.md"
                results.append(
                    MinerUParseResult(
                        paper_id=item.paper_id,
                        status="parsed",
                        output_dir=str(item.output_dir),
                        markdown_path=str(markdown_path),
                        metadata={"zip_path": str(zip_path)},
                    )
                )
            except Exception as exc:
                results.append(
                    MinerUParseResult(
                        paper_id=item.paper_id,
                        status="failed",
                        error=str(exc),
                    )
                )
        return results

    def _request_json(
        self, url: str, *, data: bytes | None = None, method: str | None = None
    ) -> dict[str, Any]:
        try:
            payload = self._fetcher(
                url, self._auth_headers(content_type=bool(data)), data, method
            )
        except urllib.error.HTTPError as exc:
            if exc.code in {401, 403}:
                raise MinerUAuthError(f"HTTP {exc.code}") from exc
            if exc.code == 429:
                raise MinerURateLimitError("HTTP 429") from exc
            raise
        return payload if isinstance(payload, dict) else {}

    def _auth_headers(self, *, content_type: bool = False) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.api_token}"}
        if content_type:
            headers["Content-Type"] = "application/json"
        return headers

    @staticmethod
    def _default_json_fetcher(
        url: str, headers: dict[str, str], data: bytes | None, method: str | None
    ) -> Any:
        request = urllib.request.Request(url, headers=headers, data=data, method=method)
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _default_binary_fetcher(url: str, headers: dict[str, str]) -> bytes:
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()

    @staticmethod
    def _default_uploader(url: str, content: bytes) -> None:
        request = urllib.request.Request(url, data=content, method="PUT")
        with urllib.request.urlopen(request, timeout=120):
            return None


def parse_mineru_items(
    items: list[MinerUParseItem], *, dry_run: bool = False
) -> MinerUParseReport:
    token = os.environ.get("MINERU_API_TOKEN", "").strip()
    enabled = os.environ.get("MINERU_ENABLE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    report = MinerUParseReport(dry_run=dry_run, enabled=enabled, processed=len(items))
    if dry_run:
        report.results = [
            {
                "paper_id": item.paper_id,
                "status": "would_parse" if item.pdf_path.exists() else "missing_pdf",
                "pdf_path": str(item.pdf_path),
                "output_dir": str(item.output_dir),
            }
            for item in items
        ]
        report.skipped = len(items)
        return report
    if not enabled:
        report.results = [
            {
                "paper_id": item.paper_id,
                "status": "skipped",
                "reason": "MINERU_ENABLE not set",
            }
            for item in items
        ]
        report.skipped = len(items)
        return report
    if not token:
        report.results = [
            {
                "paper_id": item.paper_id,
                "status": "skipped",
                "reason": "MINERU_API_TOKEN not set",
            }
            for item in items
        ]
        report.skipped = len(items)
        return report
    client = MinerUClient(
        token,
        base_url=os.environ.get("MINERU_BASE_URL", "").strip()
        or DEFAULT_MINERU_BASE_URL,
    )
    pending = [item for item in items if item.pdf_path.exists()]
    missing = [item for item in items if not item.pdf_path.exists()]
    results: list[MinerUParseResult] = [
        MinerUParseResult(item.paper_id, "failed", error="missing_pdf")
        for item in missing
    ]
    if pending:
        upload_response = client.request_upload_urls(pending)
        upload_failed = client.upload_files(pending, upload_response)
        batch_id = str(
            upload_response.get("batch_id") or upload_response.get("id") or ""
        )
        for item in upload_failed:
            results.append(
                MinerUParseResult(item.paper_id, "failed", error="upload_failed")
            )
        poll_items = [item for item in pending if item not in upload_failed]
        if poll_items and batch_id:
            results.extend(
                client.download_and_extract(
                    poll_items, client.poll_batch_results(batch_id)
                )
            )
        elif poll_items:
            results.extend(
                MinerUParseResult(item.paper_id, "failed", error="missing_batch_id")
                for item in poll_items
            )
    report.results = [result.to_dict() for result in results]
    report.parsed = sum(1 for result in results if result.status == "parsed")
    report.failed = sum(1 for result in results if result.status == "failed")
    report.skipped = sum(1 for result in results if result.status == "skipped")
    return report


def extract_mineru_zip(zip_path: Path, output_dir: Path) -> None:
    staging = output_dir.with_name(f".{output_dir.name}.staging")
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path) as archive:
            members = _validate_mineru_zip_members(archive)
            for info, relative in members:
                target = staging / relative
                _assert_path_inside(staging, target)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
        if output_dir.exists():
            shutil.rmtree(output_dir)
        staging.replace(output_dir)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def _validate_mineru_zip_members(
    archive: zipfile.ZipFile,
) -> list[tuple[zipfile.ZipInfo, Path]]:
    members: list[tuple[zipfile.ZipInfo, Path]] = []
    names: set[str] = set()
    for info in archive.infolist():
        relative = _normalize_zip_member_name(info.filename)
        key = relative.as_posix()
        if key in names:
            raise MinerUZipContentError(f"duplicate zip member: {key}")
        names.add(key)
        members.append((info, relative))
    files = {name for name in names if not name.endswith("/")}
    basenames = {Path(name).name for name in files}
    required = {"full.md", "layout.json"}
    missing = sorted(required - basenames)
    if missing:
        raise MinerUZipContentError(
            f"missing required MinerU files: {', '.join(missing)}"
        )
    if not any(name.endswith("_content_list.json") for name in basenames):
        raise MinerUZipContentError("missing MinerU content list JSON")
    if not any(name.endswith("_model.json") for name in basenames):
        raise MinerUZipContentError("missing MinerU model JSON")
    return members


def _normalize_zip_member_name(name: str) -> Path:
    if not name or "\x00" in name:
        raise MinerUZipPathError("invalid zip member name")
    normalized = name.replace("\\", "/")
    posix = PurePosixPath(normalized)
    windows = PureWindowsPath(name)
    if posix.is_absolute() or windows.is_absolute() or windows.drive:
        raise MinerUZipPathError(f"unsafe absolute zip member: {name}")
    parts = [part for part in posix.parts if part not in {"", "."}]
    if not parts or any(part == ".." for part in parts):
        raise MinerUZipPathError(f"unsafe zip member path: {name}")
    for part in parts:
        if any(ord(ch) < 32 for ch in part) or any(ch in '<>:"|?*' for ch in part):
            raise MinerUZipPathError(f"unsafe zip member name: {name}")
    return Path(*parts)


def _assert_path_inside(root: Path, target: Path) -> None:
    root_resolved = root.resolve()
    target_resolved = target.resolve(strict=False)
    if (
        root_resolved != target_resolved
        and root_resolved not in target_resolved.parents
    ):
        raise MinerUZipPathError(f"path escapes extraction root: {target}")


def _extract_upload_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("files", "data", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _extract_result_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("results", "data", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default
