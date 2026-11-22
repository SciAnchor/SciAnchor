# -*- coding: utf-8 -*-
"""Elsevier 官方 Article Retrieval API PDF 下载器。"""

from __future__ import annotations

import os
from typing import Any, Optional

import httpx

from paperfetch.downloaders.backends.publisher_api.base import PublisherAPIBackend
from paperfetch.downloaders.pdf_common import (
    PDFDownloadResult,
    build_pdf_result,
    verify_pdf_file,
)
from paperfetch.downloaders.pipeline.errors import DownloadError
from paperfetch.downloaders.registry import BackendRegistry
from paperfetch.observability import get_event_logger
from paperfetch.utils.client import async_request_with_retry

logger = get_event_logger(__name__)


@BackendRegistry.register
class ElsevierAPIBackend(PublisherAPIBackend):
    """Elsevier 官方 API 下载后端。"""

    route_key = "elsevier_api"
    display_name = "Elsevier Article API"
    supported_routes = frozenset({"elsevier_api", "publisher_api_elsevier"})

    publisher_name = "Elsevier"
    database_key = "sciencedirect"
    api_key_env_vars = ("ELSEVIER_API_KEY", "ELS_API_KEY")
    supported_doi_prefixes = frozenset({"10.1016/"})

    def __init__(self, api_key: Optional[str] = None) -> None:
        super().__init__(api_key)

    async def _fetch_pdf(self, doi: str, client: httpx.AsyncClient) -> httpx.Response:
        api_key = self.get_api_key()
        url = f"https://api.elsevier.com/content/article/doi/{doi}"
        headers = {
            "Accept": "application/pdf",
            "X-ELS-APIKey": api_key or "",
            "User-Agent": "paperfetch/2.0",
        }

        # 官方文档要求以 application/pdf 作为 Accept 请求头以直接获取二进制文件
        response = await async_request_with_retry(
            client,
            "GET",
            url,
            timeout=60.0,
            headers=headers,
        )
        return response

    async def _execute_download(
        self, doi: str, client: Any, target_file: str
    ) -> PDFDownloadResult:
        try:
            response = await self._fetch_pdf(doi, client)
            content_type = response.headers.get("Content-Type", "")

            # 状态码异常分类
            if response.status_code in (401, 403):
                raise DownloadError(
                    "auth_failed",
                    route=self.route_key,
                    url=str(response.url),
                    status_code=response.status_code,
                    content_type=content_type,
                )
            if response.status_code == 404:
                raise DownloadError(
                    "not_found",
                    route=self.route_key,
                    url=str(response.url),
                    status_code=response.status_code,
                    content_type=content_type,
                )
            if response.status_code >= 400:
                raise DownloadError(
                    "http_error",
                    route=self.route_key,
                    url=str(response.url),
                    status_code=response.status_code,
                    content_type=content_type,
                )

            # 检查 Elsevier 的全文权限警告，拦截 1 页预览 PDF 并抛出 subscription_required
            els_status = (
                response.headers.get("X-ELS-Status")
                or response.headers.get("x-els-status")
                or ""
            )
            if (
                "limited to first page" in els_status.lower()
                or "not entitled" in els_status.lower()
            ):
                logger.event(
                    "publisher_api.elsevier.subscription",
                    phase="transfer",
                    action="retrieve_article",
                    outcome="degraded",
                    level="INFO",
                    doi=doi,
                    publisher_key="elsevier",
                    route=self.route_key,
                    error_class="subscription_required",
                    message="Elsevier API 未提供全文，继续公开资源发现",
                    diagnostics={"authorization_status": els_status},
                )
                raise DownloadError(
                    "subscription_required",
                    route=self.route_key,
                    url=str(response.url),
                    status_code=response.status_code,
                    content_type=content_type,
                    message="Elsevier API 当前凭证无订阅全文权限",
                    diagnostics={"authorization_status": els_status},
                )

            # 校验 PDF
            if (
                "application/pdf" not in content_type.lower()
                and not response.content.startswith(b"%PDF")
            ):
                raise DownloadError(
                    "not_pdf",
                    route=self.route_key,
                    url=str(response.url),
                    status_code=response.status_code,
                    content_type=content_type,
                )

            # 保存文件
            os.makedirs(os.path.dirname(target_file), exist_ok=True)
            with open(target_file, "wb") as f:
                f.write(response.content)

            if not verify_pdf_file(target_file):
                raise DownloadError(
                    "magic_bytes_mismatch",
                    route=self.route_key,
                    url=str(response.url),
                    status_code=response.status_code,
                    content_type=content_type,
                )

            return build_pdf_result(
                target_file, str(response.url), self.route_key, content_type
            )
        except Exception as e:
            if isinstance(e, DownloadError):
                raise e
            raise DownloadError(
                "http_error", route=self.route_key, message=str(e)
            ) from e
