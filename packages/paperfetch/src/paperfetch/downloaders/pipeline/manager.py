# -*- coding: utf-8 -*-
"""下载模块的全局统一管理门面 (PDFDownloadManager)。

包装了底层的缓存、路由排序器、调度器以及批量编排引擎，为外部系统（如 curate 任务）
提供完全向后兼容的一站式下载服务接口。
"""

from __future__ import annotations

from paperfetch.observability import emit_event, get_event_logger
import os
import uuid
from pathlib import Path
from typing import Any, List, Optional

from paperfetch.core.models import FulltextStatus, PaperRecord
from paperfetch.downloaders.pipeline.cache import PDFGlobalCache, PDFVerifier
from paperfetch.downloaders.pipeline.resolver import PDFResolver
from paperfetch.downloaders.pipeline.scheduler import DownloadScheduler
from paperfetch.downloaders.pipeline.orchestrator import BatchOrchestrator
from paperfetch.downloaders.pipeline.events import build_paper_download_events
from paperfetch.downloaders.pipeline.outcome import finalize_download_outcome
from paperfetch.downloaders.base import DownloadRunContext, PDFRouteCandidate

logger = get_event_logger("paperfetch.downloaders.pipeline.manager")


class PDFDownloadManager:
    """PDF 全文下载管线全局总控管理器。"""

    def __init__(
        self,
        output_dir: str,
        cache_root: Path | str | None = None,
        retry_failed: bool = False,
        no_cache: bool = False,
        route_mode: str = "auto",
    ) -> None:
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

        self.verifier = PDFVerifier()
        self.cache = PDFGlobalCache(cache_root)
        self.run_context = DownloadRunContext.create()

        # 实例化单篇调度器与编排器
        self.scheduler = DownloadScheduler(
            self.cache,
            self.verifier,
            retry_failed=retry_failed,
            run_context=self.run_context,
            no_cache=no_cache,
        )
        self.resolver = PDFResolver(
            self.cache, run_context=self.run_context, no_cache=no_cache
        )
        self.orchestrator = BatchOrchestrator(
            self.scheduler, self.resolver, route_mode=route_mode
        )

    async def close(self) -> None:
        """关闭并关闭所关联的一切连接池资源。"""
        # 1. 自动释放统一注册表内注册后端的连接
        from paperfetch.downloaders.registry import BackendRegistry

        for backend_cls in BackendRegistry.all_backends().values():
            try:
                # 释放已实例化单例或静态资源。
                # 调度器持有的共享客户端在下方统一关闭。
                pass
            except Exception:
                pass

        # 2. 释放调度器共享连接
        await self.scheduler.close()

        # Phase 1 浏览器后备使用进程级浏览器，但每次传输使用隔离 context。
        try:
            from paperfetch.downloaders.browser.auth_pool import BrowserPool

            browser_pool = BrowserPool.current_instance()
            if browser_pool is not None:
                await browser_pool.close()
        except Exception as exc:
            logger.debug("[下载管理] OA 浏览器池关闭失败，原因=%s", exc)

    async def download_many(
        self, papers: List[PaperRecord], on_paper_done: Optional[Any] = None
    ) -> None:
        """批量调度下载管线，执行缓存预检与快速通道两阶段编排。"""
        task_id = f"download:{uuid.uuid4().hex}"
        try:
            await self.orchestrator.orchestrate(
                papers, self.output_dir, on_paper_done=on_paper_done
            )
        finally:
            for paper in papers:
                finalize_download_outcome(paper.fulltext_status)
                emit_event(build_paper_download_events(paper, task_id=task_id)[-1])

    async def download_one(self, paper: PaperRecord) -> FulltextStatus:
        """单篇论文下载方法。"""
        await self.download_many([paper])
        return paper.fulltext_status

    async def import_pdf_url(self, paper: PaperRecord, url: str) -> FulltextStatus:
        """强制通过外部提取得到的特定 URL 进行物理 PDF 导入和拦截抓取。"""
        paper.fulltext_status.pdf_url = url
        paper.fulltext_status.pdf_source = "agent_browser"

        status = self.scheduler._reset_status_for_attempt(paper.fulltext_status)
        candidates = [
            PDFRouteCandidate(
                "agent_browser",
                url=url,
                priority=0,
                source="agent_browser",
                metadata={
                    "proxy_mode": "no-proxy",
                    "decision_reason": "agent_browser_direct_probe",
                },
            ),
            PDFRouteCandidate(
                "agent_browser",
                url=url,
                priority=1,
                source="agent_browser",
                metadata={"decision_reason": "agent_browser_proxy_fallback"},
            ),
        ]
        target = self.resolver.target_file(paper, self.output_dir)
        status.candidate_pdf_urls = [candidate.audit_dict() for candidate in candidates]

        # 记录前置强制标志
        previous_retry_failed = self.scheduler.retry_failed
        self.scheduler.retry_failed = True
        try:
            await self.scheduler.attempt_candidates(paper, candidates, target)
        finally:
            self.scheduler.retry_failed = previous_retry_failed

        if status.download_status != "downloaded":
            status.download_status = "failed"
            status.failure_reason = "all_routes_failed"
            status.failure_taxonomy = status.failure_taxonomy or "no_result"

        finalize_download_outcome(status)

        emit_event(
            build_paper_download_events(paper, task_id=f"import:{uuid.uuid4().hex}")[-1]
        )
        return status
