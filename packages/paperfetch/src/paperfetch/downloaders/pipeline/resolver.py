# -*- coding: utf-8 -*-
"""PDF 路由决策解析与代理策略。

负责确定每一篇论文的全部候选下载路由，并进行去重和基于优先级的排序；
同时解析和决定每次请求所使用的 HTTP 代理级别 (PDFProxyPolicy)。
"""

from __future__ import annotations

import json
from paperfetch.observability import get_event_logger
import os
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlsplit

from paperfetch.core.models import FulltextStatus, PaperRecord
from paperfetch.downloaders.base import PDFRouteCandidate
from paperfetch.downloaders.routing.router import PDFDatabaseRouter
from paperfetch.downloaders.pipeline.cache import PDFGlobalCache

logger = get_event_logger("paperfetch.downloaders.pipeline.resolver")


class PDFProxyPolicy:
    """定义文献下载的显式代理路由规则。"""

    def __init__(self, mode: Optional[str] = None) -> None:
        from paperfetch.core.settings import capability_proxy, get_settings

        self.mode = (
            (mode or get_settings().text("DOWNLOAD_PROXY_MODE") or "route-aware")
            .strip()
            .lower()
        )
        self._download_proxy_configured = capability_proxy("download") is not None
        self.no_proxy_routes = {
            route.strip()
            for route in (
                get_settings().text("PDF_DOWNLOAD_NO_PROXY_ROUTES")
                or "public_http,public_browser,elsevier_api,publisher_api_springer"
            ).split(",")
            if route.strip()
        }
        if get_settings().boolean("PDF_DOWNLOAD_NO_PROXY"):
            self.mode = "no-proxy"

    def mode_for_route(self, route: str, url: Optional[str] = None) -> str:
        """根据具体的路由通道及 URL 域名判断是否走代理。"""
        if self.mode in {"none", "no_proxy", "no-proxy", "direct"}:
            return "no-proxy"
        host = self.host_for_url(url)
        if self.is_hard_direct_host(host):
            return "no-proxy"
        if self.mode == "route-aware" and route in self.no_proxy_routes:
            return "no-proxy"
        return "download-proxy" if self._download_proxy_configured else "environment"

    def mode_for_candidate(self, candidate: PDFRouteCandidate) -> str:
        explicit = candidate.metadata.get("proxy_mode")
        if explicit:
            return str(explicit)
        return self.mode_for_route(candidate.route, candidate.url)

    @staticmethod
    def host_for_url(url: Optional[str]) -> str:
        if not url:
            return ""
        try:
            return (
                urlsplit(str(url)).hostname.lower()
                if urlsplit(str(url)).hostname
                else ""
            )
        except Exception:
            return ""

    @staticmethod
    def is_hard_direct_host(host: str) -> bool:
        host = (host or "").lower()
        return host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".localhost")


class PDFResolver:
    """解析论文所有可能获取的路由并按静态优先级排序。"""

    def __init__(
        self,
        cache: PDFGlobalCache,
        run_context: Optional[Any] = None,
        no_cache: bool = False,
    ) -> None:
        self.cache = cache
        self.no_cache = no_cache
        # 兼容旧实例化习惯
        from paperfetch.downloaders.base import DownloadRunContext

        self.run_context = run_context or DownloadRunContext.create()
        self.database_router = PDFDatabaseRouter(self.run_context, self._doi_cache_key)

    def resolve(
        self, paper: PaperRecord, seed_pack_pdf_dir: str
    ) -> List[PDFRouteCandidate]:
        """仅规划缓存与官方 API 路由。公开资源由发现服务处理。"""
        candidates: List[PDFRouteCandidate] = []
        target = self.target_file(paper, seed_pack_pdf_dir)

        # 1. 缓存前置检测优先
        if not self.no_cache:
            candidates.append(
                PDFRouteCandidate("local_cache", metadata={"path": target}, priority=1)
            )
            candidates.append(
                PDFRouteCandidate(
                    "global_cache",
                    metadata={"path": str(self.cache.pdf_path(paper))},
                    priority=2,
                )
            )

        # 基于 DOI 激活出版商官方 API 路由。
        if paper.doi:
            database_plan = self.database_router.plan(paper)
            for candidate in database_plan.candidates:
                candidates.append(candidate)

        return sorted(self._dedupe(candidates), key=lambda item: item.priority)

    @staticmethod
    def _doi_cache_key(doi: Optional[str]) -> str:
        return (doi or "").strip().lower()

    def _metadata_pdf_candidates(self, status: FulltextStatus) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        seen_urls = set()

        def add(
            candidate: Any, source: Optional[str] = None, priority: Optional[int] = None
        ) -> None:
            if isinstance(candidate, str):
                url = candidate.strip()
                item: Dict[str, Any] = {}
            elif isinstance(candidate, dict):
                url = str(
                    candidate.get("url") or candidate.get("pdf_url") or ""
                ).strip()
                item = dict(candidate)
            else:
                return
            if not url or url in seen_urls:
                return
            seen_urls.add(url)
            item["url"] = url
            item["source"] = (
                source or item.get("source") or item.get("pdf_source") or "metadata"
            )
            if priority is not None:
                item["priority"] = priority
            candidates.append(item)

        if status.pdf_url:
            add(
                status.pdf_url,
                source=status.pdf_source or "metadata_primary",
                priority=0,
            )
        for candidate in sorted(
            status.pdf_candidates or [],
            key=lambda item: (
                item.get("priority", 100) if isinstance(item, dict) else 100
            ),
        ):
            add(candidate)
        return candidates

    def target_file(self, paper: PaperRecord, seed_pack_pdf_dir: str) -> str:
        os.makedirs(seed_pack_pdf_dir, exist_ok=True)
        return os.path.join(seed_pack_pdf_dir, f"{self.cache.paper_key(paper)}.pdf")

    def _dedupe(
        self, candidates: Iterable[PDFRouteCandidate]
    ) -> List[PDFRouteCandidate]:
        seen = set()
        result = []
        for candidate in candidates:
            key = (
                candidate.route,
                candidate.url,
                json.dumps(candidate.metadata, sort_keys=True),
            )
            if key not in seen:
                seen.add(key)
                result.append(candidate)
        return result
