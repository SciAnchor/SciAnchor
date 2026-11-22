# -*- coding: utf-8 -*-
"""单篇论文下载路由调度器。

负责逐一执行论文匹配的各个候选路由，包括并发限制、频率退避、
失败历史校验、断路器熔断逻辑，以及统一的异常捕获与状态归档。
"""

from __future__ import annotations

import asyncio
from paperfetch.observability import get_event_logger
import os
import shutil
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

from paperfetch.core.models import FulltextStatus, PaperRecord
from paperfetch.downloaders.base import DownloadContext, PDFRouteCandidate
from paperfetch.downloaders.registry import BackendRegistry
from paperfetch.downloaders.pdf_common import (
    PDFDownloadResult,
    build_pdf_result,
    redact_url,
)
from paperfetch.downloaders.pipeline.errors import DownloadError
from paperfetch.downloaders.pipeline.cache import PDFVerifier
from paperfetch.downloaders.pipeline.resolver import PDFProxyPolicy
from paperfetch.utils.client import configured_proxy_url

logger = get_event_logger("paperfetch.downloaders.pipeline.scheduler")


@dataclass
class PDFRouteAttempt:
    """代表单次路由下载尝试的审计指标记录。"""

    route: str
    url: Optional[str] = None
    host: Optional[str] = None
    skipped: bool = False
    cache_hit: bool = False
    cache_miss: bool = False
    status_code: Optional[int] = None
    content_type: Optional[str] = None
    error_class: Optional[str] = None
    error: Optional[str] = None
    proxy_policy: Optional[str] = None
    proxy_mode: Optional[str] = None
    client_kind: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    duration_ms: int = 0
    queue_ms: int = 0
    decision_reason: Optional[str] = None
    final_url_host: Optional[str] = None
    diagnostics: Optional[Dict[str, Any]] = None

    def audit_dict(self) -> Dict[str, Any]:
        return {
            "route": self.route,
            "url": redact_url(self.url),
            "host": self.host,
            "skipped": self.skipped,
            "cache_hit": self.cache_hit,
            "cache_miss": self.cache_miss,
            "status_code": self.status_code,
            "content_type": self.content_type,
            "error_class": self.error_class,
            "error": self.error,
            "proxy_policy": self.proxy_policy,
            "proxy_mode": self.proxy_mode,
            "client_kind": self.client_kind,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": self.duration_ms,
            "queue_ms": self.queue_ms,
            "decision_reason": self.decision_reason,
            "final_url_host": self.final_url_host,
            "diagnostics": self.diagnostics,
        }


class _SemaphoreGroup:
    """管理跨资源的并发锁锁定状态。"""

    def __init__(self, semaphores: List[asyncio.Semaphore]) -> None:
        self.semaphores = semaphores

    async def __aenter__(self) -> None:
        for sem in self.semaphores:
            await sem.acquire()

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        # 逆序释放
        for sem in reversed(self.semaphores):
            sem.release()


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name)
    if raw in (None, ""):
        return max(minimum, default)
    try:
        return max(minimum, int(raw))
    except ValueError:
        return max(minimum, default)


def _now_iso() -> str:
    return datetime.now().isoformat()


def _ms_between(start: float, end: Optional[float] = None) -> int:
    return int(
        round(((end if end is not None else time.perf_counter()) - start) * 1000)
    )


class DownloadScheduler:
    """单篇论文的多路由串行/断路尝试调度中心。"""

    def __init__(
        self,
        fetcher_or_cache: Any,
        cache_or_verifier: Any = None,
        verifier: Optional[PDFVerifier] = None,
        retry_failed: bool = False,
        run_context: Optional[Any] = None,
        no_cache: bool = False,
    ) -> None:
        if cache_or_verifier is None or isinstance(cache_or_verifier, PDFVerifier):
            self.cache = fetcher_or_cache
            self.verifier = cache_or_verifier or verifier or PDFVerifier()
            self.retry_failed = retry_failed
        else:
            self.cache = cache_or_verifier
            self.verifier = verifier or PDFVerifier()
            self.retry_failed = retry_failed
        self.run_context = run_context
        self.no_cache = no_cache

        # 并发信号量控制
        self.direct_sem = asyncio.Semaphore(_env_int("PDF_DIRECT_CONCURRENCY", 6))
        host_limit = _env_int("PDF_HOST_CONCURRENCY", 2)
        self.host_sems: Dict[str, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(host_limit)
        )

        self.proxy_policy = PDFProxyPolicy()

        # 共享 HTTP 客户端实例
        proxy_str = configured_proxy_url("DOWNLOAD_PROXY")
        self.shared_client = httpx.AsyncClient(
            follow_redirects=True,
            proxy=proxy_str if proxy_str else None,
            timeout=15.0,
            trust_env=False,
        )
        self.direct_client = httpx.AsyncClient(
            follow_redirects=True, trust_env=False, timeout=15.0
        )

    async def close(self) -> None:
        await self.shared_client.aclose()
        await self.direct_client.aclose()

    def client_for_mode(self, proxy_mode: str) -> Tuple[httpx.AsyncClient, str]:
        if proxy_mode in ("none", "no_proxy", "no-proxy", "direct"):
            return self.direct_client, "direct_client"
        return self.shared_client, "shared_client"

    def _route_semaphores(
        self, candidate: PDFRouteCandidate
    ) -> List[asyncio.Semaphore]:
        return [self.direct_sem, self.host_sems[candidate.host]]

    def _combined_semaphores(
        self, semaphores: List[asyncio.Semaphore]
    ) -> _SemaphoreGroup:
        return _SemaphoreGroup(semaphores)

    def _proxy_mode(self, candidate: PDFRouteCandidate) -> str:
        if candidate.metadata.get("proxy_mode"):
            return str(candidate.metadata["proxy_mode"])
        return self.proxy_policy.mode_for_candidate(candidate)

    def _reset_status_for_attempt(self, status: FulltextStatus) -> FulltextStatus:
        status.download_attempted = True
        status.download_status = "not_attempted"
        status.attempted_routes = []
        status.route_errors = []
        status.download_attempts = []
        status.discovery_events = []
        status.normalized_resources = []
        status.verification = {}
        status.successful_route = None
        status.resolved_pdf_url = None
        status.failure_reason = None
        status.failure_stage = None
        status.failure_taxonomy = None
        status.primary_failure_class = None
        status.last_failure_class = None
        status.attempted_route_summary = []
        status.local_path = None
        status.magic_pdf = False
        status.file_size_bytes = None
        status.sha256 = None
        status.identity_verified = False
        status.identity_status = "not_checked"
        status.identity_confidence = "none"
        status.identity_evidence = {}
        status.content_type = None
        status.cache_hit = False
        status.cache_miss = []
        status.global_cache_path = None
        return status

    def _mark_route(
        self, status: FulltextStatus, route: str, failure_stage: bool = True
    ) -> None:
        if route not in status.attempted_routes:
            status.attempted_routes.append(route)
        if failure_stage:
            status.failure_stage = route

    def _record_attempt(self, status: FulltextStatus, attempt: PDFRouteAttempt) -> None:
        status.download_attempts.append(attempt.audit_dict())
        if attempt.cache_miss:
            if attempt.route not in status.cache_miss:
                status.cache_miss.append(attempt.route)
            return
        if attempt.error_class and not attempt.skipped:
            stage = None
            if isinstance(attempt.diagnostics, dict):
                stage = attempt.diagnostics.get("stage")
            status.failure_stage = str(stage) if stage else attempt.route
            status.failure_taxonomy = attempt.error_class
            status.route_errors.append(
                {
                    "route": attempt.route,
                    "error": attempt.error or attempt.error_class,
                    "error_class": attempt.error_class,
                    "status_code": str(attempt.status_code)
                    if attempt.status_code is not None
                    else "",
                    "content_type": attempt.content_type or "",
                }
            )

    def _apply_success(
        self,
        status: FulltextStatus,
        result: PDFDownloadResult,
        cache_hit: bool = False,
        cached_path: Optional[str] = None,
        verification: Optional[Dict[str, Any]] = None,
    ) -> None:
        status.download_status = "downloaded"
        status.failure_reason = None
        status.failure_stage = None
        status.failure_taxonomy = None
        status.local_path = result.path
        status.magic_pdf = True
        status.pdf_source = result.source
        status.successful_route = result.source
        status.resolved_pdf_url = result.resolved_url
        if result.resolved_url:
            status.pdf_url = result.resolved_url
        status.content_type = result.content_type
        status.file_size_bytes = result.size
        status.sha256 = result.sha256
        verification = verification or {}
        status.identity_verified = bool(verification.get("identity_verified"))
        status.identity_status = str(
            verification.get("identity_status") or "not_checked"
        )
        status.identity_confidence = str(
            verification.get("identity_confidence") or "none"
        )
        status.identity_evidence = dict(verification.get("identity_evidence") or {})
        status.verification = {
            "identity_verified": status.identity_verified,
            "identity_status": status.identity_status,
            "identity_confidence": status.identity_confidence,
            "identity_evidence": status.identity_evidence,
            "sha256": result.sha256,
            "size_bytes": result.size,
        }
        status.cache_hit = cache_hit
        status.global_cache_path = cached_path or status.global_cache_path

    async def attempt_candidates(
        self,
        paper: PaperRecord,
        candidates: List[PDFRouteCandidate],
        target_file: str,
        *,
        on_candidate_attempt: Optional[Callable[[PDFRouteCandidate, str], None]] = None,
    ) -> None:
        """串行尝试为该论文匹配的各个候选路由，直到成功或全部尝试完成。"""
        status = paper.fulltext_status
        for candidate in candidates:
            if status.download_status == "downloaded":
                return

            proxy_mode = self._proxy_mode(candidate)
            client, client_kind = self.client_for_mode(proxy_mode)

            # 1. 路由跳过处理
            if candidate.route.endswith("_skip"):
                self._mark_route(status, candidate.route, failure_stage=False)
                reason = str(
                    candidate.metadata.get("reason") or "skipped_by_route_planner"
                )
                now = _now_iso()
                self._record_attempt(
                    status,
                    PDFRouteAttempt(
                        candidate.route,
                        candidate.url,
                        candidate.host,
                        error_class=reason,
                        error=reason,
                        skipped=True,
                        proxy_policy="none",
                        proxy_mode="none",
                        client_kind="route_planner",
                        started_at=now,
                        ended_at=now,
                        duration_ms=0,
                        queue_ms=0,
                        decision_reason=str(
                            candidate.metadata.get("decision_reason") or reason
                        ),
                    ),
                )
                continue

            # 2. 校验历史失败缓存退避
            if not self.no_cache and self.cache.should_skip(
                paper, candidate, retry_failed=self.retry_failed
            ):
                now = _now_iso()
                self._record_attempt(
                    status,
                    PDFRouteAttempt(
                        candidate.route,
                        candidate.url,
                        candidate.host,
                        skipped=True,
                        error_class="cached_failure",
                        proxy_policy=proxy_mode,
                        proxy_mode=proxy_mode,
                        client_kind="failure_cache",
                        started_at=now,
                        ended_at=now,
                        duration_ms=0,
                        queue_ms=0,
                        decision_reason="failure_cache_ttl",
                    ),
                )
                continue

            self._mark_route(status, candidate.route)

            # 4. 并发获取锁调度
            queue_started = time.perf_counter()
            async with self._combined_semaphores(self._route_semaphores(candidate)):
                queue_ms = _ms_between(queue_started)
                started_perf = time.perf_counter()
                started_at = _now_iso()

                # 7. 从后端注册表查找执行器并下载。
                backend_cls = BackendRegistry.get_backend(candidate.route)
                if not backend_cls:
                    # 记录未支持异常并继续
                    self._record_attempt(
                        status,
                        PDFRouteAttempt(
                            candidate.route,
                            candidate.url,
                            candidate.host,
                            error_class="unsupported_route",
                            error=f"注册表未查找到路由 {candidate.route} 适配后端",
                            started_at=started_at,
                            ended_at=_now_iso(),
                        ),
                    )
                    continue

                backend = backend_cls()
                verification_duration_ms: Optional[int] = None
                try:
                    # 通知开始尝试该具体链路
                    if on_candidate_attempt:
                        on_candidate_attempt(candidate, "started")

                    # 动态组装特定属性
                    ctx = DownloadContext(
                        paper=paper,
                        candidate=candidate,
                        target_file=target_file,
                        run_context=getattr(self, "run_context", None),
                    )
                    # 传入共享客户端。
                    setattr(ctx, "client", client)

                    logger.debug("[下载调度] 选择后端，后端=%s", backend.display_name)
                    logger.info(
                        "[PDF 传输] 开始，DOI=%s，出版社=%s，来源=%s，transport=%s，route=%s，代理=%s",
                        paper.doi or paper.paper_id,
                        paper.publisher or paper.journal or paper.venue or "未知",
                        candidate.source,
                        candidate.metadata.get("transport") or candidate.route,
                        candidate.route,
                        proxy_mode,
                    )
                    result = await backend.download(ctx)

                    # 7. 校验 PDF 物理结构与目标论文身份。
                    verification_started = time.perf_counter()
                    meta = await asyncio.to_thread(
                        self.verifier.verify_file, result.path, paper
                    )
                    verification_duration_ms = _ms_between(verification_started)
                    if not meta.get("valid"):
                        status.verification = {
                            "identity_verified": False,
                            "identity_status": meta.get("identity_status") or "failed",
                            "identity_confidence": meta.get("identity_confidence")
                            or "none",
                            "identity_evidence": meta.get("identity_evidence") or {},
                            "duration_ms": verification_duration_ms,
                            "error_class": meta.get("error_class") or "not_pdf",
                        }
                        if meta.get("error_class") in {
                            "metadata_poisoned",
                            "identity_unverified",
                        }:
                            self.cache.quarantine(paper, result.path, meta)
                        raise DownloadError(
                            meta.get("error_class") or "not_pdf",
                            route=candidate.route,
                            url=result.resolved_url,
                            message="PDF 未通过目标论文身份校验",
                            diagnostics={
                                "identity": meta.get("identity_evidence") or {},
                                "client_config": {
                                    "proxy_mode": proxy_mode,
                                    "trust_env": False
                                    if client_kind == "direct_client"
                                    else True,
                                },
                            },
                        )

                    result.size = meta["size"]
                    result.sha256 = meta["sha256"]

                    # 唯一临时文件通过物理和身份校验后才原子提交到最终路径。
                    if os.path.abspath(result.path) != os.path.abspath(target_file):
                        os.replace(result.path, target_file)
                        result.path = target_file

                    # 8. 存入全局缓存并完成
                    cached_path = self.cache.store_verified(
                        paper,
                        result.path,
                        self.verifier,
                        verification=meta,
                    )
                    self._apply_success(
                        status,
                        result,
                        cached_path=str(cached_path) if cached_path else None,
                        verification=meta,
                    )
                    status.verification["duration_ms"] = verification_duration_ms

                    self._record_attempt(
                        status,
                        PDFRouteAttempt(
                            candidate.route,
                            result.resolved_url or candidate.url,
                            result.resolved_url
                            and PDFProxyPolicy.host_for_url(result.resolved_url)
                            or candidate.host,
                            content_type=result.content_type,
                            proxy_policy=proxy_mode,
                            proxy_mode=proxy_mode,
                            client_kind=client_kind,
                            started_at=started_at,
                            ended_at=_now_iso(),
                            duration_ms=_ms_between(started_perf),
                            queue_ms=queue_ms,
                            decision_reason=str(
                                candidate.metadata.get("decision_reason") or ""
                            ),
                            final_url_host=result.resolved_url
                            and PDFProxyPolicy.host_for_url(result.resolved_url)
                            or candidate.host,
                            diagnostics={
                                "identity": meta.get("identity_evidence") or {}
                            },
                        ),
                    )
                    logger.info(
                        "[PDF 传输] OK，DOI=%s，出版社=%s，transport=%s，route=%s，耗时=%dms",
                        paper.doi or paper.paper_id,
                        paper.publisher or paper.journal or paper.venue or "未知",
                        candidate.metadata.get("transport") or candidate.route,
                        candidate.route,
                        _ms_between(started_perf),
                    )

                    if on_candidate_attempt:
                        on_candidate_attempt(candidate, "success")
                    return

                except Exception as exc:
                    # 转译为 DownloadError
                    if not isinstance(exc, DownloadError):
                        err = DownloadError.from_exception(
                            exc, route=candidate.route, url=candidate.url or ""
                        )
                    else:
                        err = exc

                    if on_candidate_attempt:
                        on_candidate_attempt(candidate, f"failed:{err.error_class}")

                    attempt = PDFRouteAttempt(
                        candidate.route,
                        err.url or candidate.url,
                        candidate.host,
                        status_code=err.status_code,
                        content_type=err.content_type,
                        error_class=err.error_class,
                        error=err.message[:500],
                        proxy_policy=proxy_mode,
                        proxy_mode=proxy_mode,
                        client_kind=client_kind,
                        started_at=started_at,
                        ended_at=_now_iso(),
                        duration_ms=_ms_between(started_perf),
                        queue_ms=queue_ms,
                        decision_reason=str(
                            candidate.metadata.get("decision_reason") or ""
                        ),
                        final_url_host=PDFProxyPolicy.host_for_url(err.url)
                        or candidate.host,
                        diagnostics={
                            **(err.diagnostics or {}),
                            "client_config": {
                                "proxy_mode": proxy_mode,
                                "trust_env": False
                                if client_kind == "direct_client"
                                else True,
                            },
                            "verification_duration_ms": verification_duration_ms,
                        },
                    )

                    self._record_attempt(status, attempt)
                    self.cache.record_failure(paper, candidate, attempt)
                    logger.info(
                        "[PDF 传输] DEGRADED：当前路由未成功，继续后续路由，DOI=%s，出版社=%s，transport=%s，route=%s，错误=%s，耗时=%dms",
                        paper.doi or paper.paper_id,
                        paper.publisher or paper.journal or paper.venue or "未知",
                        candidate.metadata.get("transport") or candidate.route,
                        candidate.route,
                        err.error_class,
                        attempt.duration_ms,
                    )

                finally:
                    close = getattr(backend, "close", None)
                    if close:
                        try:
                            await close()
                        except Exception as close_exc:
                            logger.debug(
                                "[下载调度] 后端关闭失败，后端=%s，原因=%s",
                                getattr(backend, "display_name", candidate.route),
                                close_exc,
                            )

        if status.download_status != "downloaded" and status.download_attempted:
            status.download_status = "failed"
            status.failure_reason = status.failure_reason or "all_routes_failed"

    async def _attempt_candidates(
        self, paper: PaperRecord, candidates: List[PDFRouteCandidate], target_file: str
    ) -> None:
        """为当前调度器 API 提供内部测试入口。"""
        await self.attempt_candidates(paper, candidates, target_file)

    async def try_cache_routes(
        self, paper: PaperRecord, candidates: List[PDFRouteCandidate], target_file: str
    ) -> bool:
        """检查本地和全局缓存，若命中则无需启动路由下载。"""
        if self.no_cache:
            return False
        status = paper.fulltext_status
        for candidate in candidates:
            now = _now_iso()
            if candidate.route == "local_cache":
                self._mark_route(status, "local_cache", failure_stage=False)
                meta = await asyncio.to_thread(
                    self.verifier.verify_file, target_file, paper
                )
                if meta.get("valid"):
                    result = build_pdf_result(
                        target_file,
                        status.resolved_pdf_url or status.pdf_url,
                        "local_cache",
                        status.content_type,
                    )
                    result.size = meta["size"]
                    result.sha256 = meta["sha256"]
                    self._apply_success(
                        status, result, cache_hit=True, verification=meta
                    )
                    self._record_attempt(
                        status,
                        PDFRouteAttempt(
                            "local_cache",
                            cache_hit=True,
                            proxy_policy="none",
                            proxy_mode="none",
                            client_kind="filesystem",
                            started_at=now,
                            ended_at=_now_iso(),
                            duration_ms=0,
                            queue_ms=0,
                            diagnostics={
                                "identity": meta.get("identity_evidence") or {}
                            },
                        ),
                    )
                    return True
                error_class = meta.get("error_class") or "missing_file"
                identity_failure = error_class in {
                    "metadata_poisoned",
                    "identity_unverified",
                }
                if identity_failure and os.path.exists(target_file):
                    self.cache.quarantine(paper, target_file, meta)
                self._record_attempt(
                    status,
                    PDFRouteAttempt(
                        "local_cache",
                        error_class=error_class,
                        error=error_class,
                        cache_miss=not identity_failure,
                        proxy_policy="none",
                        proxy_mode="none",
                        client_kind="filesystem",
                        started_at=now,
                        ended_at=_now_iso(),
                        duration_ms=0,
                        queue_ms=0,
                        diagnostics={"identity": meta.get("identity_evidence") or {}},
                    ),
                )
            elif candidate.route == "global_cache":
                self._mark_route(status, "global_cache", failure_stage=False)
                cached, meta = await asyncio.to_thread(
                    self.cache.inspect_verified,
                    paper,
                    self.verifier,
                )
                if cached:
                    shutil.copy2(cached, target_file)
                    result = build_pdf_result(
                        target_file,
                        status.resolved_pdf_url or status.pdf_url,
                        "global_cache",
                        status.content_type,
                    )
                    result.size = meta["size"]
                    result.sha256 = meta["sha256"]
                    self._apply_success(
                        status,
                        result,
                        cache_hit=True,
                        cached_path=str(cached),
                        verification=meta,
                    )
                    self._record_attempt(
                        status,
                        PDFRouteAttempt(
                            "global_cache",
                            cache_hit=True,
                            proxy_policy="none",
                            proxy_mode="none",
                            client_kind="filesystem",
                            started_at=now,
                            ended_at=_now_iso(),
                            duration_ms=0,
                            queue_ms=0,
                            diagnostics={
                                "identity": meta.get("identity_evidence") or {}
                            },
                        ),
                    )
                    return True
                error_class = meta.get("error_class") or "missing_file"
                identity_failure = error_class in {
                    "metadata_poisoned",
                    "identity_unverified",
                }
                self._record_attempt(
                    status,
                    PDFRouteAttempt(
                        "global_cache",
                        error_class=error_class,
                        error=error_class,
                        cache_miss=not identity_failure,
                        proxy_policy="none",
                        proxy_mode="none",
                        client_kind="filesystem",
                        started_at=now,
                        ended_at=_now_iso(),
                        duration_ms=0,
                        queue_ms=0,
                        diagnostics={"identity": meta.get("identity_evidence") or {}},
                    ),
                )
        return False

    def _attempt_from_exception(
        self, candidate: PDFRouteCandidate, exc: Exception
    ) -> PDFRouteAttempt:
        """为单元测试提供下载尝试异常转换入口。"""
        err = DownloadError.from_exception(
            exc, route=candidate.route, url=candidate.url or ""
        )
        return PDFRouteAttempt(
            route=candidate.route,
            url=err.url or candidate.url,
            host=candidate.host,
            status_code=err.status_code,
            content_type=err.content_type,
            error_class=err.error_class,
            error=err.message[:500],
            diagnostics=err.diagnostics,
            started_at=_now_iso(),
            ended_at=_now_iso(),
        )
