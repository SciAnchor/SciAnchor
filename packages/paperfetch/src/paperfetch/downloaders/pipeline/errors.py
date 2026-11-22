# -*- coding: utf-8 -*-
"""下载编排中的异常分类体系。

本模块定义了统一的异常类 (DownloadError)，它用于代表并标准化所有发生的下载异常，
替换以往分散在各个文件中混乱的异常继承和繁琐的 isinstance 识别。
"""

from __future__ import annotations

from paperfetch.observability import get_event_logger
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import httpx

logger = get_event_logger("paperfetch.downloaders")


@dataclass
class DownloadError(Exception):
    """所有下载失败的标准化异常。"""

    error_class: str  # 如 "auth_failed", "timeout", "not_pdf", "gateway_fault"
    route: str = ""  # 发生失败的路由
    url: str = ""  # 失败时的请求 URL
    status_code: Optional[int] = None  # HTTP 状态码
    content_type: str = ""  # 响应 content-type
    message: str = ""  # 描述性的详细消息
    diagnostics: Dict[str, Any] = field(default_factory=dict)  # 诊断诊断指标数据

    def __post_init__(self) -> None:
        msg = f"[{self.route}] 下载失败 ({self.error_class}): {self.message or '无详细说明'}"
        if self.status_code is not None:
            msg += f" | Status={self.status_code}"
        Exception.__init__(self, msg)

    @classmethod
    def from_exception(
        cls, exc: Exception, route: str = "", url: str = ""
    ) -> DownloadError:
        """智能异常分类器，自动解析第三方库和原先自定义的异常并转化为标准的 DownloadError。"""
        # 如果本身已是 DownloadError，直接补充路由/URL并返回
        if isinstance(exc, DownloadError):
            if not exc.route:
                exc.route = route
            if not exc.url:
                exc.url = url
            return exc

        # 针对原先 ElseiverAPIDownloadError 的兼容
        if exc.__class__.__name__ == "ElsevierAPIDownloadError":
            return cls(
                error_class=getattr(exc, "error_class", "http_error"),
                route=route or "elsevier_api",
                url=getattr(exc, "url", "") or url,
                status_code=getattr(exc, "status_code", None),
                content_type=getattr(exc, "content_type", ""),
                message=str(exc),
                diagnostics=getattr(exc, "diagnostics", {}) or {},
            )

        # 针对 httpx HTTP 错误的分析
        if isinstance(exc, httpx.HTTPStatusError):
            status_code = exc.response.status_code if exc.response is not None else None
            text = str(exc).lower()
            content_type = (
                exc.response.headers.get("Content-Type", "")
                if exc.response is not None
                else ""
            )

            if (
                status_code in (500, 502, 503, 504)
                or "网关" in text
                or "gateway" in text
            ):
                error_class = "gateway_fault"
            elif status_code == 429:
                error_class = "rate_limited"
            elif status_code in (401, 403):
                error_class = "auth_failed"
            else:
                error_class = "http_error"

            return cls(
                error_class=error_class,
                route=route,
                url=str(exc.request.url) if exc.request is not None else url,
                status_code=status_code,
                content_type=content_type,
                message=str(exc),
            )

        # 针对连接超时及错误分析
        if isinstance(exc, (httpx.TimeoutException, httpx.ConnectTimeout)):
            return cls(error_class="timeout", route=route, url=url, message=str(exc))

        # Playwright 的 TimeoutError 不继承 asyncio.TimeoutError，
        # 但类名稳定为 TimeoutError。必须在兜底 no_result 前保留超时语义。
        if isinstance(exc, TimeoutError) or exc.__class__.__name__ == "TimeoutError":
            return cls(error_class="timeout", route=route, url=url, message=str(exc))

        if isinstance(exc, httpx.ConnectError):
            text = str(exc).lower()
            error_class = "gateway_fault" if "circuit_open" in text else "connect_error"
            return cls(error_class=error_class, route=route, url=url, message=str(exc))

        if isinstance(exc, OSError):
            return cls(
                error_class="local_io_error",
                route=route,
                url=url,
                message=str(exc),
                diagnostics={
                    "stage": "local_state_io",
                    "exception_type": exc.__class__.__name__,
                    "errno": getattr(exc, "errno", None),
                },
            )

        # 针对值异常的错误码解析
        if isinstance(exc, ValueError):
            val_msg = str(exc).lower()
            if val_msg in ("not_a_pdf", "not_pdf"):
                taxonomy = "not_pdf"
            elif "missing_doi" in val_msg:
                taxonomy = "missing_doi"
            elif "pdf_link_not_extracted" in val_msg:
                taxonomy = "pdf_link_not_extracted"
            elif "publisher_pdf_challenge" in val_msg:
                taxonomy = "publisher_pdf_challenge"
            elif "publisher_challenge" in val_msg:
                taxonomy = "publisher_challenge"
            elif "subscription_required" in val_msg:
                taxonomy = "subscription_required"
            elif "publisher_pdf_auth_failed" in val_msg:
                taxonomy = "publisher_pdf_auth_failed"
            elif "publisher_pdf_html_not_pdf" in val_msg:
                taxonomy = "publisher_pdf_html_not_pdf"
            elif "doi_public_resolve_failed" in val_msg:
                taxonomy = "doi_public_resolve_failed"
            elif "gateway" in val_msg:
                taxonomy = "gateway_fault"
            elif "魔数" in val_msg or "magic" in val_msg:
                taxonomy = "magic_bytes_mismatch"
            else:
                taxonomy = "no_result"
            return cls(error_class=taxonomy, route=route, url=url, message=str(exc))

        # 兜底分析
        error_text = str(exc)
        lowered_error = error_text.lower()
        if (
            "page crashed" in lowered_error
            or "target page, context or browser has been closed" in lowered_error
        ):
            taxonomy = "browser_page_crashed"
        elif (
            "chrome-error://chromewebdata" in lowered_error
            or "net::err_" in lowered_error
        ):
            taxonomy = "network_error"
        elif "not_installed" in lowered_error or "tool_missing" in lowered_error:
            taxonomy = "tool_missing"
        else:
            taxonomy = "no_result"
        return cls(error_class=taxonomy, route=route, url=url, message=error_text)
