# -*- coding: utf-8 -*-
"""智能批量下载编排引擎。

执行两阶段批量调度：
1. 缓存预检：秒级确认本地或全局已归档的 PDF。
2. 快速通道并发：对开放获取、arXiv、官方 API 与公开 HTTP/浏览器渠道执行有界并发抓取。
"""

from __future__ import annotations

import asyncio
from paperfetch.observability import get_event_logger
import os
import sys
from typing import Any, Dict, List, Optional

from rich.progress import (
    Progress,
    SpinnerColumn,
    TextColumn,
    BarColumn,
    TimeElapsedColumn,
)
from rich.console import Console

from paperfetch.core.models import PaperRecord
from paperfetch.downloaders.pipeline.scheduler import DownloadScheduler
from paperfetch.downloaders.pipeline.resolver import PDFResolver
from paperfetch.downloaders.pipeline.direct import DirectDownloadPipeline
from paperfetch.core.settings import get_settings

logger = get_event_logger("paperfetch.downloaders.pipeline.orchestrator")


class BatchOrchestrator:
    """智能批量下载编排器。"""

    def __init__(
        self,
        scheduler: DownloadScheduler,
        resolver: PDFResolver,
        *,
        route_mode: str = "auto",
    ) -> None:
        self.scheduler = scheduler
        self.resolver = resolver
        # 公开版只有开放获取/官方 API 路线；``auto`` 与 ``public`` 行为一致。
        self.route_mode = route_mode
        self.direct_pipeline = DirectDownloadPipeline(scheduler)
        self._progress_tasks: Dict[str, Any] = {}
        self._progress_completed: set[str] = set()

    async def orchestrate(
        self,
        papers: List[PaperRecord],
        pdf_dir: str,
        on_paper_done: Optional[Any] = None,
    ) -> None:
        """执行缓存预检与快速通道两阶段编排下载管线。"""
        run_context = getattr(self.scheduler, "run_context", None)
        if run_context is not None:
            try:
                run_context.batch_mode = True
            except Exception:
                pass

        prepared: Dict[str, Dict[str, Any]] = {}
        remaining: List[PaperRecord] = []

        # =============================================================
        # 阶段 0：缓存命中预检
        # =============================================================
        logger.info("[下载编排] 阶段 0：开始 PDF 缓存预检")
        for paper in papers:
            self.scheduler._reset_status_for_attempt(paper.fulltext_status)
            candidates = list(self.resolver.resolve(paper, pdf_dir))
            paper.fulltext_status.candidate_pdf_urls = [
                c.audit_dict() for c in candidates
            ]

            target = self.resolver.target_file(paper, pdf_dir)
            prepared[paper.paper_id] = {"candidates": candidates, "target": target}

            # 判断是否命中缓存
            if not await self.scheduler.try_cache_routes(paper, candidates, target):
                remaining.append(paper)
            else:
                logger.info("[下载编排] 缓存命中，论文=%s", paper.doi or paper.paper_id)
                await self._notify_paper_done(on_paper_done, paper)

        if not remaining:
            logger.info("[下载编排] 全部论文命中缓存")
            return

        self._progress_tasks.clear()
        self._progress_completed.clear()
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=Console(stderr=True),
            disable=self._progress_disabled(),
        ) as progress:
            overall_task = progress.add_task(
                "[green]批量下载论文", total=len(remaining)
            )
            for paper in remaining:
                self._paper_task(progress, paper, "等待调度")

            # =============================================================
            # 阶段 1：一级与二级快速通道并发下载
            # =============================================================
            fast_routes = {"elsevier_api", "publisher_api_springer"}

            fast_papers: List[PaperRecord] = []
            for paper in remaining:
                if paper.fulltext_status.download_status != "downloaded":
                    fast_papers.append(paper)

            if fast_papers:
                phase1_concurrency = self._phase1_paper_concurrency()
                logger.info(
                    "[下载编排] 阶段 1：开始直连通道下载，并发上限=%d",
                    phase1_concurrency,
                )
                semaphore = asyncio.Semaphore(phase1_concurrency)

                async def run_limited_fast_paper(paper: PaperRecord) -> None:
                    async with semaphore:
                        await self._run_fast_paper(
                            paper,
                            prepared[paper.paper_id],
                            fast_routes,
                            progress,
                            overall_task,
                            on_paper_done,
                        )

                await asyncio.gather(
                    *(run_limited_fast_paper(paper) for paper in fast_papers)
                )

            # =============================================================
            # 终局：未成功的论文统一收敛为失败
            # =============================================================
            for paper in remaining:
                status = paper.fulltext_status
                if status.download_status == "downloaded":
                    continue
                status.download_status = "failed"
                status.failure_reason = "all_routes_failed"
                status.failure_taxonomy = status.failure_taxonomy or "no_result"
                paper_task = self._paper_task(progress, paper, "终局")
                progress.update(
                    paper_task,
                    description=self._progress_description(
                        paper, "失败", status.failure_taxonomy or "无可用路由", "red"
                    ),
                )
                self._complete_progress(progress, overall_task, paper)
                await self._notify_paper_done(on_paper_done, paper)

    async def _run_fast_paper(
        self,
        paper: PaperRecord,
        prep: Dict[str, Any],
        routes: set[str],
        progress: Progress,
        overall_task: Any,
        on_paper_done: Optional[Any],
    ) -> None:
        candidates = self._fast_candidates(prep["candidates"], routes)
        paper_task = self._paper_task(progress, paper, "直连通道")

        def on_attempt(candidate, state):
            if state == "started":
                progress.update(
                    paper_task,
                    description=f"[cyan]直连 {paper.doi or paper.paper_id} | 尝试 [bold]{candidate.route}[/bold]",
                )
            elif state.startswith("failed"):
                err_type = state.split(":", 1)[1] if ":" in state else "failed"
                progress.update(
                    paper_task,
                    description=f"[cyan]直连 {paper.doi or paper.paper_id} | [red]{candidate.route} 失败（{err_type}）[/red]",
                )

        await self.direct_pipeline.run(
            paper,
            prep["target"],
            candidates,
            on_candidate_attempt=on_attempt,
        )

        success = paper.fulltext_status.download_status == "downloaded"
        successful_route = paper.fulltext_status.successful_route
        err_class = paper.fulltext_status.failure_taxonomy or "failed"
        desc = (
            self._progress_description(
                paper, "成功", successful_route or "未知", "green"
            )
            if success
            else self._progress_description(paper, "直连失败", err_class, "yellow")
        )
        progress.update(paper_task, description=desc)

        if success:
            self._complete_progress(progress, overall_task, paper)
            await self._notify_paper_done(on_paper_done, paper)

    @staticmethod
    def _fast_candidates(candidates: List[Any], routes: set[str]) -> List[Any]:
        return [candidate for candidate in candidates if candidate.route in routes]

    @staticmethod
    def _phase1_paper_concurrency() -> int:
        raw = os.environ.get("SPC_PHASE1_PAPER_CONCURRENCY")
        if raw is not None:
            try:
                return max(1, min(4, int(raw)))
            except (TypeError, ValueError):
                return 2
        return max(
            1, min(4, get_settings().integer("SPC_PHASE1_PAPER_CONCURRENCY", minimum=1))
        )

    @staticmethod
    def _progress_disabled() -> bool:
        from paperfetch.core.settings import get_settings

        return get_settings().boolean("SPC_NO_PROGRESS") or not sys.stderr.isatty()

    @staticmethod
    def _publisher_label(paper: PaperRecord) -> str:
        if paper.publisher:
            return str(paper.publisher)
        for candidate in paper.fulltext_status.candidate_pdf_urls:
            metadata = candidate.get("metadata") or {}
            publisher = metadata.get("database_label") or metadata.get("database_key")
            if publisher:
                return str(publisher)
        return str(
            paper.journal
            or paper.venue
            or ((paper.doi or "未知出版社").split("/", 1)[0])
        )

    def _progress_description(
        self,
        paper: PaperRecord,
        state: str,
        detail: str,
        color: str,
    ) -> str:
        identifier = paper.doi or paper.paper_id
        return (
            f"[{color}]{state}[/{color}] | DOI={identifier} | "
            f"出版社={self._publisher_label(paper)} | 详情={detail}"
        )

    def _paper_task(self, progress: Progress, paper: PaperRecord, state: str) -> Any:
        task = self._progress_tasks.get(paper.paper_id)
        description = self._progress_description(paper, state, "-", "cyan")
        if task is None:
            task = progress.add_task(description, total=1)
            self._progress_tasks[paper.paper_id] = task
        else:
            progress.update(task, description=description)
        return task

    def _complete_progress(
        self,
        progress: Progress,
        overall_task: Any,
        paper: PaperRecord,
    ) -> None:
        if paper.paper_id in self._progress_completed:
            return
        self._progress_completed.add(paper.paper_id)
        task = self._progress_tasks.get(paper.paper_id)
        if task is not None:
            progress.update(task, completed=1)
        if overall_task is not None:
            progress.advance(overall_task)

    async def _notify_paper_done(
        self, callback: Optional[Any], paper: PaperRecord
    ) -> None:
        if callback is None:
            return
        try:
            import inspect

            result = callback(paper)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            logger.warning(
                "[下载编排] 完成回调执行失败，论文=%s，原因=%s", paper.paper_id, exc
            )
