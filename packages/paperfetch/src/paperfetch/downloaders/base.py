# -*- coding: utf-8 -*-
"""下载器基础接口与上下文模型。

本模块定义了所有下载后端所必须实现的抽象基类 (DownloaderBackend)
以及路由候选与运行上下文模型。
"""

from __future__ import annotations

from paperfetch.observability import get_event_logger
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import os
from typing import Any, AsyncIterator, Dict, Optional
from contextlib import asynccontextmanager

from paperfetch.core.models import PaperRecord
from urllib.parse import urlsplit
from paperfetch.downloaders.pdf_common import PDFDownloadResult, redact_url

logger = get_event_logger(__name__)


@dataclass
class PDFRouteCandidate:
    """代表一个候选 PDF 下载路由项。"""

    route: str
    url: Optional[str] = None
    referer: Optional[str] = None
    priority: int = 100
    source: str = "resolver"
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def host(self) -> str:
        if not self.url:
            return self.route
        try:
            return urlsplit(self.url).netloc.lower() or self.route
        except Exception:
            return self.route

    def audit_dict(self) -> Dict[str, Any]:
        return {
            "route": self.route,
            "url": redact_url(self.url),
            "host": self.host,
            "source": self.source,
            "priority": self.priority,
            "metadata": self.metadata,
        }


@dataclass
class DownloadContext:
    """提供给具体下载后端的执行上下文。"""

    paper: PaperRecord
    candidate: PDFRouteCandidate
    target_file: str
    run_context: Any  # DownloadRunContext
    client: Optional[Any] = None


class DownloaderBackend(ABC):
    """所有下载后端的抽象基类。"""

    # 子类必须覆写的元数据
    route_key: str  # 核心路由标识，例如 "elsevier_api"
    display_name: str  # 人类可读名称
    supported_routes: frozenset[str]  # 所支持的路由键集合，用于匹配路由候选

    # 标志位
    requires_browser: bool = False  # 是否需要启动 Playwright 浏览器
    supports_batch: bool = False  # 是否支持在单个浏览器会话中批量执行
    concurrency_group: str = "direct"  # 并发分组，例如 "direct", "browser"

    @abstractmethod
    async def download(self, ctx: DownloadContext) -> PDFDownloadResult:
        """执行单篇论文的下载。

        Args:
            ctx: 下载上下文，包含论文信息和目标路径。

        Returns:
            PDFDownloadResult: 下载成功的结果。

        Raises:
            Exception: 任何下载失败的异常，后续会被统一分类。
        """
        pass

    def classify_error(self, exc: Exception) -> Any:
        """将原始异常分类为统一 of DownloadError。

        子类可以重写此方法以提供特定后端的精细化异常映射。
        """
        from paperfetch.downloaders.pipeline.errors import DownloadError

        return DownloadError.from_exception(exc, route=self.route_key)

    async def close(self) -> None:
        """释放该后端所持有的任何持久化资源（如 HTTP 客户端或链接）。"""
        pass


@dataclass
class DownloadRunContext:
    """保存单次下载任务运行的依赖预检结果与路由开关。"""

    preflight: Dict[str, Any] = field(default_factory=dict)
    batch_mode: bool = False

    @classmethod
    def create(cls) -> "DownloadRunContext":
        return cls()
