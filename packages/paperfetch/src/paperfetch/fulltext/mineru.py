# -*- coding: utf-8 -*-
"""MinerU PDF 解析：服务 paper download / seed-pack enrich / paper parse。"""

import os
import random
import shutil
import zipfile
import uuid
import time
import re
from paperfetch.observability import get_event_logger
import asyncio
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any

from paperfetch.core.action import BaseAction
from paperfetch.core.context import CuratorContext
from paperfetch.core.models import PaperRecord, FulltextStatus
from paperfetch.downloaders.pdf_common import redact_url
from paperfetch.utils.client import create_external_service_client

logger = get_event_logger("paperfetch.fulltext.mineru")

_MINERU_STAGE_KEYS = {
    "申请上传链接": "service_submit",
    "上传 PDF 到预签名 URL": "artifact_upload",
    "查询解析结果": "service_poll",
    "下载 MinerU 结果 zip": "artifact_download",
}


def _mineru_stage_key(stage: str) -> str:
    return _MINERU_STAGE_KEYS.get(stage, stage)


def _mineru_error_summary(exc: BaseException | str) -> str:
    """Return a non-empty, URL-redacted exception-chain summary."""
    if isinstance(exc, BaseException):
        parts: List[str] = []
        current: Optional[BaseException] = exc
        seen: set[int] = set()
        while current is not None and id(current) not in seen and len(parts) < 4:
            seen.add(id(current))
            detail = str(current).strip()
            label = type(current).__name__
            parts.append(f"{label}: {detail}" if detail else label)
            current = current.__cause__ or current.__context__
        summary = " <- ".join(parts)
    else:
        summary = str(exc).strip() or "unknown_error"
    summary = re.sub(
        r"https?://[^\s'\"<>]+",
        lambda match: redact_url(match.group(0)),
        summary,
        flags=re.IGNORECASE,
    )
    return summary[:500]


def _classify_mineru_failure(stage: str, exc: BaseException | str) -> str:
    import httpx

    stage = _mineru_stage_key(stage)
    text = _mineru_error_summary(exc).lower()
    if isinstance(exc, MinerUAuthError):
        return "service_auth_error"
    if isinstance(exc, MinerURateLimitError):
        return "service_rate_limited"
    if stage == "service_auth":
        return "service_auth_error"
    if "ssl" in text or "tls" in text or "unexpected_eof_while_reading" in text:
        return (
            "artifact_tls_error"
            if stage.startswith("artifact_")
            else "service_tls_error"
        )
    if isinstance(exc, (MinerUZipPathError, MinerUZipContentError, zipfile.BadZipFile)):
        return "artifact_zip_invalid"
    if isinstance(exc, OSError):
        return "local_io_error"
    if isinstance(
        exc,
        (
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.WriteTimeout,
            asyncio.TimeoutError,
        ),
    ):
        return (
            "artifact_timeout" if stage.startswith("artifact_") else "service_timeout"
        )
    if stage == "artifact_download":
        return "artifact_download_failed"
    if stage == "artifact_upload":
        return "artifact_upload_failed"
    if stage == "artifact_extract":
        return "artifact_extract_failed"
    if stage == "local_input":
        return "local_input_error"
    if isinstance(exc, httpx.NetworkError):
        return (
            "artifact_download_failed"
            if stage.startswith("artifact_")
            else "service_connection_error"
        )
    if stage.startswith("service_"):
        return "service_error"
    return "mineru_unclassified_error"


def _record_mineru_failure(
    status: FulltextStatus,
    stage: str,
    exc: BaseException | str,
    *,
    attempt: Optional[int] = None,
    max_attempts: Optional[int] = None,
    retryable: Optional[bool] = None,
    append_attempt: bool = True,
) -> str:
    stage_key = _mineru_stage_key(stage)
    failure_class = _classify_mineru_failure(stage_key, exc)
    summary = _mineru_error_summary(exc)
    status.mineru_status = "failed"
    status.mineru_failure_stage = stage_key
    status.mineru_failure_class = failure_class
    status.mineru_error_summary = summary
    if append_attempt:
        status.mineru_attempts.append(
            {
                "stage": stage_key,
                "failure_class": failure_class,
                "error_summary": summary,
                "attempt": attempt,
                "max_attempts": max_attempts,
                "retryable": retryable,
            }
        )
    return summary


def _clear_mineru_terminal_failure(
    status: FulltextStatus, *, reset_attempts: bool = False
) -> None:
    status.mineru_failure_stage = None
    status.mineru_failure_class = None
    status.mineru_error_summary = None
    if reset_attempts:
        status.mineru_attempts = []


def find_mineru_full_markdown(root_dir: str) -> Optional[str]:
    if not root_dir:
        return None
    markdown_path = os.path.join(root_dir, "full.md")
    return markdown_path if MinerUParseAction.path_exists(markdown_path) else None


def restore_mineru_metadata_if_available(
    status: FulltextStatus,
    markdown_path: Optional[str],
    archive_path: Optional[str],
    extracted_dir: Optional[str],
    parse_quality: str = "high",
) -> bool:
    if not markdown_path or not MinerUParseAction.path_exists(markdown_path):
        return False
    status.mineru_status = "parsed"
    _clear_mineru_terminal_failure(status)
    status.mineru_markdown_path = os.path.abspath(markdown_path)
    status.mineru_archive_path = (
        os.path.abspath(archive_path)
        if archive_path and MinerUParseAction.path_exists(archive_path)
        else status.mineru_archive_path
    )
    status.mineru_extracted_dir = (
        os.path.abspath(extracted_dir)
        if extracted_dir and MinerUParseAction.path_isdir(extracted_dir)
        else status.mineru_extracted_dir
    )
    status.parse_quality = parse_quality
    return True


@dataclass
class MinerUParseItem:
    paper: PaperRecord
    data_id: str
    local_path: str
    paper_parsed_dir: str
    target_zip_file: str
    upload_url: Optional[str] = None
    state: str = "pending"
    zip_url: Optional[str] = None
    err_msg: str = ""


class MinerUError(Exception):
    """MinerU 解析基础异常。"""


class MinerUAPIError(MinerUError):
    """MinerU 接口调用或下载异常。"""


class MinerUAuthError(MinerUError):
    """整轮任务的 MinerU 凭证或权限无效时抛出。"""


class MinerURateLimitError(Exception):
    def __init__(self, message: str, retry_after: Optional[float] = None):
        super().__init__(message)
        self.retry_after = retry_after


class MinerUZipPathError(Exception):
    """MinerU zip 包含不安全或不支持的路径时抛出。"""


class MinerUZipContentError(Exception):
    """MinerU zip 缺失必要输出文件时抛出。"""


class MinerUParseAction(BaseAction):
    """使用 MinerU API v4 执行 PDF 全文无损结构化解析与解包。"""

    def __init__(
        self,
        enrich_top_k: int = 10,
        max_connection_retries: Optional[int] = None,
        batch_size: Optional[int] = None,
        upload_concurrency: Optional[int] = None,
        download_concurrency: Optional[int] = None,
        poll_interval_seconds: Optional[float] = None,
        poll_timeout_seconds: Optional[float] = None,
        no_cache: bool = False,
        run_code_audit: bool = False,
    ):
        self.enrich_top_k = max(0, enrich_top_k)
        self.max_connection_retries = (
            max_connection_retries
            if max_connection_retries is not None
            else self._env_int("MINERU_CONNECTION_RETRIES", 3)
        )
        self.batch_size = (
            batch_size
            if batch_size is not None
            else self._env_int("MINERU_BATCH_SIZE", 10)
        )
        self.upload_concurrency = (
            upload_concurrency
            if upload_concurrency is not None
            else self._env_int("MINERU_UPLOAD_CONCURRENCY", 3)
        )
        self.download_concurrency = (
            download_concurrency
            if download_concurrency is not None
            else self._env_int("MINERU_DOWNLOAD_CONCURRENCY", 2)
        )
        self.poll_interval_seconds = (
            poll_interval_seconds
            if poll_interval_seconds is not None
            else self._env_float("MINERU_POLL_INTERVAL_SECONDS", 5.0)
        )
        self.poll_timeout_seconds = (
            poll_timeout_seconds
            if poll_timeout_seconds is not None
            else self._env_float("MINERU_POLL_TIMEOUT_SECONDS", 1800.0)
        )
        self.no_cache = no_cache
        self.run_code_audit = run_code_audit

    @staticmethod
    def _env_int(name: str, default: int, minimum: int = 1) -> int:
        raw = os.getenv(name)
        if not raw:
            return max(minimum, default)
        try:
            return max(minimum, int(raw))
        except ValueError:
            logger.warning(f"[MinerU] 环境变量 {name}={raw} 无效，使用默认值 {default}")
            return max(minimum, default)

    @staticmethod
    def _env_float(name: str, default: float, minimum: float = 0.1) -> float:
        raw = os.getenv(name)
        if not raw:
            return max(minimum, default)
        try:
            return max(minimum, float(raw))
        except ValueError:
            logger.warning(f"[MinerU] 环境变量 {name}={raw} 无效，使用默认值 {default}")
            return max(minimum, default)

    @staticmethod
    def _is_retryable_connection_error(exc: Exception) -> bool:
        import httpx

        if isinstance(
            exc,
            (
                httpx.ConnectError,
                httpx.ConnectTimeout,
                httpx.ReadTimeout,
                httpx.WriteTimeout,
                httpx.NetworkError,
                httpx.RemoteProtocolError,
            ),
        ):
            return True
        text = str(exc).lower()
        return (
            "all connection attempts failed" in text
            or "connection" in text
            and "failed" in text
        )

    async def _run_with_connection_retry(
        self, paper: PaperRecord, operation, stage: str
    ) -> Any:
        attempts = max(1, self.max_connection_retries)
        last_exc: Optional[Exception] = None
        for attempt in range(attempts):
            try:
                return await operation()
            except Exception as exc:
                last_exc = exc
                retryable = self._is_retryable_connection_error(exc)
                summary = _record_mineru_failure(
                    paper.fulltext_status,
                    stage,
                    exc,
                    attempt=attempt + 1,
                    max_attempts=attempts,
                    retryable=retryable,
                )
                if not retryable or attempt >= attempts - 1:
                    raise
                # 使用 curate.random 以便测试打桩 mock
                delay = min(30.0, 2.0 * (2**attempt)) + random.uniform(0.0, 0.5)
                logger.warning(
                    f"[MinerU] 连接失败，标题={paper.title[:20]!r}，阶段={_mineru_stage_key(stage)}，尝试={attempt + 1}/{attempts}，重试等待={delay:.1f} 秒，原因={summary}"
                )
                # 使用 asyncio.sleep 以便测试打桩 mock
                await asyncio.sleep(delay)
        if last_exc:
            raise last_exc
        return None

    @staticmethod
    def _retry_after_seconds(resp: Any) -> Optional[float]:
        headers = getattr(resp, "headers", {}) or {}
        retry_after = headers.get("Retry-After") if hasattr(headers, "get") else None
        if not retry_after:
            return None
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            return None

    async def _run_mineru_api_request(
        self, paper: PaperRecord, operation, stage: str
    ) -> Any:
        attempts = max(1, self.max_connection_retries)
        last_response: Any = None
        for attempt in range(attempts):
            resp = await self._run_with_connection_retry(paper, operation, stage)
            last_response = resp
            if resp.status_code in (401, 403):
                try:
                    self._raise_for_mineru_http_error(resp, stage)
                except Exception as exc:
                    _record_mineru_failure(
                        paper.fulltext_status,
                        stage,
                        exc,
                        attempt=attempt + 1,
                        max_attempts=attempts,
                        retryable=False,
                    )
                    raise
            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                _record_mineru_failure(
                    paper.fulltext_status,
                    stage,
                    f"HTTP {resp.status_code}",
                    attempt=attempt + 1,
                    max_attempts=attempts,
                    retryable=True,
                )
                if attempt >= attempts - 1:
                    self._raise_for_mineru_http_error(resp, stage)
                retry_after = self._retry_after_seconds(resp)
                # 使用 curate.random / sleep 确保打桩
                delay = (
                    retry_after
                    if retry_after is not None
                    else min(60.0, 2.0 * (2**attempt)) + random.uniform(0.0, 0.5)
                )
                logger.warning(
                    f"[MinerU] 接口异常，阶段={stage}，HTTP 状态码={resp.status_code}，尝试={attempt + 1}/{attempts}，重试等待={delay:.1f} 秒"
                )
                await asyncio.sleep(delay)
                continue
            try:
                self._raise_for_mineru_http_error(resp, stage)
            except Exception as exc:
                _record_mineru_failure(
                    paper.fulltext_status,
                    stage,
                    exc,
                    attempt=attempt + 1,
                    max_attempts=attempts,
                    retryable=False,
                )
                raise
            return resp
        if last_response is not None:
            self._raise_for_mineru_http_error(last_response, stage)
        raise ValueError(f"{stage} 未返回有效响应")

    async def _run_signed_url_request(
        self, paper: PaperRecord, operation, stage: str
    ) -> Any:
        attempts = max(1, self.max_connection_retries)
        last_response: Any = None
        for attempt in range(attempts):
            resp = await self._run_with_connection_retry(paper, operation, stage)
            last_response = resp
            status_code = getattr(resp, "status_code", 200)
            if status_code == 429 or 500 <= status_code < 600:
                _record_mineru_failure(
                    paper.fulltext_status,
                    stage,
                    f"HTTP {status_code}",
                    attempt=attempt + 1,
                    max_attempts=attempts,
                    retryable=True,
                )
                if attempt >= attempts - 1:
                    resp.raise_for_status()
                retry_after = self._retry_after_seconds(resp)
                delay = (
                    retry_after
                    if retry_after is not None
                    else min(60.0, 2.0 * (2**attempt)) + random.uniform(0.0, 0.5)
                )
                logger.warning(
                    f"[MinerU] 预签名 URL 异常，阶段={stage}，HTTP 状态码={status_code}，尝试={attempt + 1}/{attempts}，重试等待={delay:.1f} 秒"
                )
                await asyncio.sleep(delay)
                continue
            try:
                resp.raise_for_status()
            except Exception as exc:
                _record_mineru_failure(
                    paper.fulltext_status,
                    stage,
                    exc,
                    attempt=attempt + 1,
                    max_attempts=attempts,
                    retryable=False,
                )
                raise
            return resp
        if last_response is not None:
            last_response.raise_for_status()
        raise ValueError(f"{stage} 未返回有效响应")

    @staticmethod
    def _read_file_bytes(path: str) -> bytes:
        with open(MinerUParseAction._filesystem_path(path), "rb") as f:
            return f.read()

    @staticmethod
    def _write_file_bytes(path: str, content: bytes) -> None:
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(MinerUParseAction._filesystem_path(parent), exist_ok=True)
        with open(MinerUParseAction._filesystem_path(path), "wb") as f:
            f.write(content)

    @staticmethod
    def _normal_abs_path(path: str) -> str:
        return os.path.normpath(os.path.abspath(path))

    @staticmethod
    def _filesystem_path(path: str) -> str:
        normalized = MinerUParseAction._normal_abs_path(path)
        if os.name != "nt" or normalized.startswith("\\\\?\\"):
            return normalized
        if normalized.startswith("\\\\"):
            return "\\\\?\\UNC\\" + normalized.lstrip("\\")
        return "\\\\?\\" + normalized

    @staticmethod
    def path_exists(path: str) -> bool:
        return os.path.exists(MinerUParseAction._filesystem_path(path))

    @staticmethod
    def path_isdir(path: str) -> bool:
        return os.path.isdir(MinerUParseAction._filesystem_path(path))

    @staticmethod
    def _assert_path_inside(root_dir: str, candidate_path: str) -> None:
        root_abs = MinerUParseAction._normal_abs_path(root_dir)
        candidate_abs = MinerUParseAction._normal_abs_path(candidate_path)
        try:
            common = os.path.commonpath([root_abs, candidate_abs])
        except ValueError as exc:
            raise MinerUZipPathError(
                f"路径跨盘或无法比较: root={root_abs}, candidate={candidate_abs}"
            ) from exc
        if common != root_abs:
            raise MinerUZipPathError(f"Zip 条目越界: {candidate_abs}")

    @staticmethod
    def _safe_rmtree(path: str, allowed_root: str) -> None:
        path_abs = MinerUParseAction._normal_abs_path(path)
        allowed_abs = MinerUParseAction._normal_abs_path(allowed_root)
        MinerUParseAction._assert_path_inside(allowed_abs, path_abs)
        if path_abs == allowed_abs:
            raise MinerUZipPathError(f"拒绝删除根目录本身: {path_abs}")
        if MinerUParseAction.path_isdir(path_abs):
            shutil.rmtree(MinerUParseAction._filesystem_path(path_abs))

    @staticmethod
    def _safe_replace_dir(staging_dir: str, final_dir: str) -> None:
        final_abs = MinerUParseAction._normal_abs_path(final_dir)
        staging_abs = MinerUParseAction._normal_abs_path(staging_dir)
        parent = os.path.dirname(final_abs)
        if not parent:
            raise MinerUZipPathError(f"无法解析目标父目录: {final_abs}")
        MinerUParseAction._assert_path_inside(parent, final_abs)
        MinerUParseAction._assert_path_inside(parent, staging_abs)
        if MinerUParseAction.path_exists(final_abs):
            MinerUParseAction._safe_rmtree(final_abs, parent)
        os.replace(
            MinerUParseAction._filesystem_path(staging_abs),
            MinerUParseAction._filesystem_path(final_abs),
        )

    def _build_parse_item(
        self, paper: PaperRecord, ctx: CuratorContext, used_data_ids: set[str]
    ) -> Optional[Tuple[MinerUParseItem, bool]]:
        status = paper.fulltext_status
        if status.download_status != "downloaded" or not status.local_path:
            return None
        if not self.path_exists(status.local_path):
            return None

        parsed_dir = os.path.join(ctx.output_dir or "seed_pack/temp", "mineru")
        os.makedirs(self._filesystem_path(parsed_dir), exist_ok=True)
        clean_doi = (
            paper.doi.replace("/", "_").replace("\\", "_")
            if paper.doi
            else uuid.uuid4().hex[:8]
        )
        paper_parsed_dir = os.path.join(parsed_dir, clean_doi)
        target_zip_file = os.path.join(parsed_dir, f"{clean_doi}.zip")

        existing_md = (
            status.mineru_markdown_path
            if status.mineru_markdown_path
            and os.path.basename(status.mineru_markdown_path).lower() == "full.md"
            and self.path_exists(status.mineru_markdown_path)
            else find_mineru_full_markdown(paper_parsed_dir)
        )
        if existing_md:
            logger.info(f"[MinerU] 本地解析成果已存在，跳过请求，DOI={paper.doi}")
            archive = (
                target_zip_file
                if os.path.exists(target_zip_file)
                else status.mineru_archive_path
            )
            extracted = (
                paper_parsed_dir
                if os.path.isdir(paper_parsed_dir)
                else status.mineru_extracted_dir
            )
            restore_mineru_metadata_if_available(
                status,
                existing_md,
                archive,
                extracted,
                parse_quality="high" if os.path.isdir(paper_parsed_dir) else "partial",
            )
            return None, True

        status.mineru_status = "not_attempted"
        _clear_mineru_terminal_failure(status, reset_attempts=True)
        if str(status.failure_reason or "").startswith("MINERU_"):
            status.failure_reason = None

        base_data_id = (
            paper.paper_id or paper.doi or os.path.basename(status.local_path)
        )
        data_id = str(base_data_id)
        suffix = 2
        while data_id in used_data_ids:
            data_id = f"{base_data_id}-{suffix}"
            suffix += 1
        used_data_ids.add(data_id)

        return MinerUParseItem(
            paper=paper,
            data_id=data_id,
            local_path=status.local_path,
            paper_parsed_dir=paper_parsed_dir,
            target_zip_file=target_zip_file,
        ), False

    def _collect_parse_items(
        self, ctx: CuratorContext
    ) -> Tuple[List[MinerUParseItem], int]:
        items: List[MinerUParseItem] = []
        reused_count = 0
        used_data_ids: set[str] = set()
        for paper in ctx.top_seeds[: self.enrich_top_k]:
            built = self._build_parse_item(paper, ctx, used_data_ids)
            if not built:
                continue
            item, reused = built
            if reused:
                reused_count += 1
            elif item:
                items.append(item)
        return items, reused_count

    @staticmethod
    def _chunks(items: List[MinerUParseItem], size: int) -> List[List[MinerUParseItem]]:
        return [items[i : i + size] for i in range(0, len(items), size)]

    @staticmethod
    def _raise_for_mineru_http_error(resp: Any, stage: str) -> None:
        response_text = getattr(resp, "text", "") or ""
        if resp.status_code in (401, 403):
            raise MinerUAuthError(
                f"{stage} 认证失败: HTTP {resp.status_code}, 详情: {response_text[:300]}"
            )
        if resp.status_code == 429:
            raise MinerURateLimitError(
                f"{stage} 触发限流: HTTP 429",
                MinerUParseAction._retry_after_seconds(resp),
            )
        if resp.status_code != 200:
            raise ValueError(
                f"{stage} 异常: HTTP {resp.status_code}, 详情: {response_text[:300]}"
            )

    async def _request_upload_urls(
        self,
        client: Any,
        api_base: str,
        headers: Dict[str, str],
        batch_items: List[MinerUParseItem],
    ) -> str:
        payload = {
            "files": [
                {
                    "name": os.path.basename(item.local_path),
                    "data_id": item.data_id,
                    "is_ocr": True,
                }
                for item in batch_items
            ],
            "model_version": "vlm",
        }
        batch_url = f"{api_base}/file-urls/batch"
        resp = await self._run_mineru_api_request(
            batch_items[0].paper,
            lambda: client.post(batch_url, json=payload, headers=headers),
            "申请上传链接",
        )
        body = resp.json()
        if body.get("code") != 0:
            raise ValueError(f"申请上传链接业务报错: {body.get('msg')}")

        data = body.get("data") or {}
        batch_id = data.get("batch_id")
        upload_urls = data.get("file_urls") or []
        if not batch_id:
            raise ValueError("申请上传链接响应缺少 batch_id")
        if len(upload_urls) != len(batch_items):
            raise ValueError(
                f"申请上传链接响应数量不匹配: expected={len(batch_items)}, got={len(upload_urls)}"
            )

        for item, upload_url in zip(batch_items, upload_urls):
            item.upload_url = upload_url
        return batch_id

    async def _upload_batch_files(
        self, client: Any, batch_items: List[MinerUParseItem]
    ) -> List[MinerUParseItem]:
        import httpx

        sem = asyncio.Semaphore(max(1, self.upload_concurrency))
        failed: List[MinerUParseItem] = []

        async def upload_one(item: MinerUParseItem) -> None:
            if not item.upload_url:
                item.state = "failed"
                item.err_msg = "缺少上传 URL"
                _record_mineru_failure(
                    item.paper.fulltext_status,
                    "service_submit",
                    item.err_msg,
                )
                failed.append(item)
                return
            async with sem:
                stage = "local_read"
                try:
                    file_bytes = await asyncio.to_thread(
                        self._read_file_bytes, item.local_path
                    )
                    logger.info(
                        f"[MinerU] 上传 PDF，数据 ID={item.data_id}，字节数={len(file_bytes)}"
                    )
                    stage = "artifact_upload"
                    await self._run_signed_url_request(
                        item.paper,
                        lambda: client.put(
                            item.upload_url,
                            content=file_bytes,
                            timeout=httpx.Timeout(30.0, read=300.0, write=300.0),
                        ),
                        "上传 PDF 到预签名 URL",
                    )
                except Exception as exc:
                    item.state = "failed"
                    summary = _record_mineru_failure(
                        item.paper.fulltext_status,
                        stage,
                        exc,
                        append_attempt=stage != "artifact_upload",
                    )
                    item.err_msg = f"上传失败: {summary}"
                    failed.append(item)

        await asyncio.gather(*(upload_one(item) for item in batch_items))
        return failed

    @staticmethod
    def _map_extract_results(
        batch_items: List[MinerUParseItem], results_list: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        by_data_id: Dict[str, Dict[str, Any]] = {}
        for task_info in results_list:
            data_id = task_info.get("data_id")
            if data_id:
                by_data_id[str(data_id)] = task_info
        if by_data_id:
            return by_data_id
        if len(batch_items) == 1 and len(results_list) == 1:
            return {
                item.data_id: task_info
                for item, task_info in zip(batch_items, results_list)
            }
        return {}

    async def _poll_batch_results(
        self,
        client: Any,
        api_base: str,
        token: str,
        batch_id: str,
        batch_items: List[MinerUParseItem],
    ) -> List[MinerUParseItem]:
        status_url = f"{api_base}/extract-results/batch/{batch_id}"
        pending = {item.data_id: item for item in batch_items if item.state != "failed"}
        deadline = time.monotonic() + max(
            self.poll_timeout_seconds, self.poll_interval_seconds
        )

        while pending:
            if time.monotonic() >= deadline:
                for item in pending.values():
                    item.state = "failed"
                    item.err_msg = "等待解析超时"
                break

            await asyncio.sleep(self.poll_interval_seconds)
            status_resp = await self._run_mineru_api_request(
                batch_items[0].paper,
                lambda: client.get(
                    status_url, headers={"Authorization": f"Bearer {token}"}
                ),
                "查询解析结果",
            )
            status_res = status_resp.json()
            if status_res.get("code") != 0:
                raise ValueError(f"查询解析结果业务报错: {status_res.get('msg')}")

            results_list = status_res.get("data", {}).get("extract_result", []) or []
            mapped = self._map_extract_results(batch_items, results_list)
            if not mapped:
                if results_list and len(batch_items) > 1:
                    for item in pending.values():
                        item.state = "failed"
                        item.err_msg = "MinerU batch 结果缺少 data_id，无法安全映射"
                    break
                continue

            for data_id, task_info in mapped.items():
                item = pending.get(data_id)
                if not item:
                    continue
                job_status = task_info.get("state", "doing")
                item.state = job_status
                if job_status == "done":
                    item.zip_url = task_info.get("full_zip_url")
                    if item.zip_url:
                        pending.pop(data_id, None)
                    else:
                        item.state = "failed"
                        item.err_msg = "解析完成但响应缺少 zip 链接"
                        pending.pop(data_id, None)
                elif job_status == "failed":
                    item.err_msg = task_info.get("err_msg", "未知业务错误")
                    pending.pop(data_id, None)

        return [item for item in batch_items if item.state == "done" and item.zip_url]

    @staticmethod
    def _normalize_zip_member_name(raw_name: str) -> Optional[str]:
        name = raw_name.replace("\\", "/").strip()
        if not name or name.endswith("/"):
            return None
        if name.startswith("/") or name.startswith("//"):
            raise MinerUZipPathError(f"Zip 条目使用绝对路径: {raw_name}")
        if len(name) >= 2 and name[1] == ":":
            raise MinerUZipPathError(f"Zip 条目包含 Windows 盘符: {raw_name}")
        parts = name.split("/")
        invalid_chars = set('<>:"|?*')
        normalized_parts = []
        for part in parts:
            if part in ("", ".", ".."):
                raise MinerUZipPathError(f"Zip 条目包含非法路径片段: {raw_name}")
            if any(ord(ch) < 32 for ch in part) or any(
                ch in invalid_chars for ch in part
            ):
                raise MinerUZipPathError(f"Zip 条目包含不支持字符: {raw_name}")
            normalized_parts.append(part)
        return "/".join(normalized_parts)

    @staticmethod
    def _validate_mineru_zip_members(member_names: List[str]) -> None:
        if "full.md" not in member_names:
            raise MinerUZipContentError("MinerU zip 缺少根目录 full.md")
        if "layout.json" not in member_names:
            raise MinerUZipContentError("MinerU zip 缺少根目录 layout.json")
        if not any(
            name.endswith("_content_list.json") and "/" not in name
            for name in member_names
        ):
            raise MinerUZipContentError("MinerU zip 缺少根目录 *_content_list.json")
        if not any(
            name.endswith("_model.json") and "/" not in name for name in member_names
        ):
            raise MinerUZipContentError("MinerU zip 缺少根目录 *_model.json")

    @staticmethod
    def _extract_mineru_zip(
        target_zip_file: str, paper_parsed_dir: str
    ) -> Tuple[Optional[str], str]:
        final_dir = MinerUParseAction._normal_abs_path(paper_parsed_dir)
        parent_dir = os.path.dirname(final_dir)
        if not parent_dir:
            raise MinerUZipPathError(f"无法解析解压父目录: {final_dir}")
        os.makedirs(MinerUParseAction._filesystem_path(parent_dir), exist_ok=True)

        staging_dir = f"{final_dir}.tmp-{uuid.uuid4().hex[:8]}"
        if MinerUParseAction.path_exists(staging_dir):
            MinerUParseAction._safe_rmtree(staging_dir, parent_dir)
        os.makedirs(MinerUParseAction._filesystem_path(staging_dir), exist_ok=True)

        try:
            normalized_members: List[str] = []
            with zipfile.ZipFile(
                MinerUParseAction._filesystem_path(target_zip_file)
            ) as zf:
                for info in zf.infolist():
                    member_name = MinerUParseAction._normalize_zip_member_name(
                        info.filename
                    )
                    if member_name is None:
                        continue
                    normalized_members.append(member_name)

                MinerUParseAction._validate_mineru_zip_members(normalized_members)

                seen_members: set[str] = set()
                for info in zf.infolist():
                    member_name = MinerUParseAction._normalize_zip_member_name(
                        info.filename
                    )
                    if member_name is None:
                        continue
                    if member_name in seen_members:
                        raise MinerUZipContentError(
                            f"MinerU zip 包含重复条目: {member_name}"
                        )
                    seen_members.add(member_name)

                    dest_path = os.path.join(staging_dir, *member_name.split("/"))
                    MinerUParseAction._assert_path_inside(staging_dir, dest_path)
                    dest_parent = os.path.dirname(dest_path)
                    if dest_parent:
                        os.makedirs(
                            MinerUParseAction._filesystem_path(dest_parent),
                            exist_ok=True,
                        )
                    with (
                        zf.open(info, "r") as src,
                        open(
                            MinerUParseAction._filesystem_path(dest_path), "wb"
                        ) as dst,
                    ):
                        shutil.copyfileobj(src, dst)

            found_md = os.path.join(final_dir, "full.md")
            MinerUParseAction._safe_replace_dir(staging_dir, final_dir)
            if not MinerUParseAction.path_exists(found_md):
                raise MinerUZipContentError("MinerU zip 解压后缺少 full.md")
            return found_md, "high"
        except Exception:
            if MinerUParseAction.path_exists(staging_dir):
                MinerUParseAction._safe_rmtree(staging_dir, parent_dir)
            raise

    async def _download_and_extract_results(
        self, client: Any, ready_items: List[MinerUParseItem]
    ) -> Tuple[int, int]:
        sem = asyncio.Semaphore(max(1, self.download_concurrency))
        parsed_count = 0
        failed_count = 0
        counter_lock = asyncio.Lock()

        async def download_one(item: MinerUParseItem) -> None:
            nonlocal parsed_count, failed_count
            status = item.paper.fulltext_status
            async with sem:
                try:
                    stage = "artifact_download"
                    temp_zip_path = f"{item.target_zip_file}.{uuid.uuid4().hex}.part"
                    os.makedirs(os.path.dirname(item.target_zip_file), exist_ok=True)
                    logger.info(
                        f"[MinerU] 解析成功，流式下载成果包，URL={redact_url(item.zip_url)}"
                    )

                    # 行内注释：使用指数退避策略流式下载 MinerU 制品 zip，抵抗慢网络与 SSLEOF 异常
                    max_retries = 3
                    for attempt in range(1, max_retries + 1):
                        try:
                            async with client.stream(
                                "GET", item.zip_url, timeout=120.0
                            ) as stream_resp:
                                if stream_resp.status_code >= 400:
                                    raise MinerUAPIError(
                                        f"MinerU zip 下载失败，HTTP状态码={stream_resp.status_code}"
                                    )
                                with open(temp_zip_path, "wb") as f_out:
                                    async for chunk in stream_resp.aiter_bytes(
                                        chunk_size=65536
                                    ):
                                        if chunk:
                                            f_out.write(chunk)
                            # 传输完成，原子替换为最终 zip 文件
                            os.replace(temp_zip_path, item.target_zip_file)
                            break
                        except Exception as dl_err:
                            if os.path.exists(temp_zip_path):
                                try:
                                    os.remove(temp_zip_path)
                                except OSError:
                                    pass
                            _record_mineru_failure(
                                status,
                                stage,
                                dl_err,
                                attempt=attempt,
                                max_attempts=max_retries,
                                retryable=True,
                            )
                            if attempt < max_retries and any(
                                err_kw in type(dl_err).__name__.lower()
                                or err_kw in str(dl_err).lower()
                                for err_kw in (
                                    "ssl",
                                    "eof",
                                    "connection",
                                    "remote",
                                    "transport",
                                    "timeout",
                                    "http",
                                    "50",
                                    "mineruapierror",
                                    "429",
                                )
                            ):
                                backoff_s = 1.5 * attempt
                                logger.warning(
                                    f"[MinerU] 下载 zip 遭遇网络抖动 ({dl_err})，将在 {backoff_s:.1f}s 后重试 ({attempt}/{max_retries})"
                                )
                                await asyncio.sleep(backoff_s)
                            else:
                                raise

                    stage = "artifact_extract"
                    found_md, parse_quality = await asyncio.to_thread(
                        self._extract_mineru_zip,
                        item.target_zip_file,
                        item.paper_parsed_dir,
                    )
                    restore_mineru_metadata_if_available(
                        status,
                        found_md,
                        item.target_zip_file,
                        item.paper_parsed_dir,
                        parse_quality=parse_quality,
                    )
                    logger.info(
                        f"[MinerU] 解析与解包完成，标题={item.paper.title[:20]!r}，路径={item.paper_parsed_dir}"
                    )
                    async with counter_lock:
                        parsed_count += 1
                except Exception as exc:
                    summary = _record_mineru_failure(
                        status,
                        stage,
                        exc,
                        append_attempt=not (
                            stage == "artifact_download"
                            and bool(status.mineru_attempts)
                            and status.mineru_attempts[-1].get("stage")
                            == "artifact_download"
                        ),
                    )
                    logger.warning(
                        f"[MinerU] 成果处理失败，标题={item.paper.title[:20]!r}，阶段={_mineru_stage_key(stage)}，"
                        f"错误={status.mineru_failure_class}，原因={summary}"
                    )
                    async with counter_lock:
                        failed_count += 1

        await asyncio.gather(*(download_one(item) for item in ready_items))
        return parsed_count, failed_count

    async def execute(self, ctx: CuratorContext) -> None:

        token = os.getenv("MINERU_API_TOKEN")
        base_url = os.getenv("MINERU_BASE_URL") or "https://mineru.net"
        api_base = f"{base_url.rstrip('/')}/api/v4"

        if not token:
            logger.warning("[MinerU] 未在环境配置中找到 MINERU_API_TOKEN，跳过解析")
            ctx.add_provenance("MinerUParseAction", "跳过，未配置 API 凭证。")
            return

        logger.info(f"[MinerU] 启动 v4 批量解析，批次大小={self.batch_size}")

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        items, parsed_count = self._collect_parse_items(ctx)
        failed_count = 0
        if not items:
            ctx.add_provenance(
                "MinerUParseAction",
                f"MinerU 解析完毕。成功: {parsed_count}，失败: {failed_count}",
            )
            return

        async with create_external_service_client(timeout=120.0) as client:
            for batch_items in self._chunks(items, max(1, self.batch_size)):
                batch_id = ""
                try:
                    batch_id = await self._request_upload_urls(
                        client, api_base, headers, batch_items
                    )
                    logger.info(
                        f"[MinerU] 批次创建成功，批次 ID={batch_id}，数量={len(batch_items)}"
                    )

                    upload_failed = await self._upload_batch_files(client, batch_items)
                    for item in upload_failed:
                        logger.warning(
                            f"[MinerU] 论文上传失败，标题={item.paper.title[:20]!r}，原因={item.err_msg}"
                        )
                    failed_count += len(upload_failed)

                    ready_items = await self._poll_batch_results(
                        client, api_base, token, batch_id, batch_items
                    )
                    for item in batch_items:
                        if item.state == "failed" and item not in upload_failed:
                            summary = _record_mineru_failure(
                                item.paper.fulltext_status,
                                "service_parse",
                                item.err_msg or "parse_failed",
                            )
                            logger.warning(
                                f"[MinerU] 论文解析失败，标题={item.paper.title[:20]!r}，原因={summary}"
                            )
                            failed_count += 1

                    (
                        batch_parsed,
                        batch_failed,
                    ) = await self._download_and_extract_results(client, ready_items)
                    parsed_count += batch_parsed
                    failed_count += batch_failed

                except MinerUAuthError as exc:
                    summary = _mineru_error_summary(exc)
                    logger.warning(f"[MinerU] 认证失败，原因={summary}")
                    for item in batch_items:
                        if item.paper.fulltext_status.mineru_status not in {
                            "parsed",
                            "failed",
                        }:
                            _record_mineru_failure(
                                item.paper.fulltext_status, "service_auth", exc
                            )
                            failed_count += 1
                    break
                except Exception as exc:
                    stage = "service_poll" if batch_id else "service_submit"
                    summary = _mineru_error_summary(exc)
                    logger.warning(
                        f"[MinerU] 批次处理失败，批次 ID={batch_id or 'pending'}，阶段={stage}，原因={summary}"
                    )
                    for item in batch_items:
                        if item.paper.fulltext_status.mineru_status not in {
                            "parsed",
                            "failed",
                        }:
                            _record_mineru_failure(
                                item.paper.fulltext_status, stage, exc
                            )
                            failed_count += 1

        ctx.add_provenance(
            "MinerUParseAction",
            f"MinerU 解析完毕。成功: {parsed_count}，失败: {failed_count}",
        )
