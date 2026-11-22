# -*- coding: utf-8 -*-
"""面向路由的 PDF 下载管线组件包。

集成路由分类、批量编排、浏览器自动化、官方 API 抓取及验证审计机制。
"""

from __future__ import annotations

from paperfetch.downloaders.pipeline.manager import PDFDownloadManager
from paperfetch.downloaders.pipeline.report import build_download_run_report
from paperfetch.downloaders.pipeline.errors import DownloadError
from paperfetch.downloaders.base import DownloaderBackend, DownloadContext
from paperfetch.downloaders.registry import BackendRegistry
from paperfetch.downloaders.pipeline.direct import (
    DiscoveredPDFResource,
    PDFTransferCandidate,
)

# 执行自动扫描以激活所有注册在 backends/ 下的下载后端
BackendRegistry.discover()

__all__ = [
    "PDFDownloadManager",
    "build_download_run_report",
    "DownloadError",
    "DownloaderBackend",
    "DownloadContext",
    "BackendRegistry",
    "DiscoveredPDFResource",
    "PDFTransferCandidate",
]
