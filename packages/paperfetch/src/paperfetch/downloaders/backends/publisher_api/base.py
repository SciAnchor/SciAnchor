# -*- coding: utf-8 -*-
"""出版商官方 API 下载器基类。

管理 API 凭据校验、DOI 范围匹配以及通用的下载与验证逻辑。
"""

from __future__ import annotations

from paperfetch.observability import get_event_logger
import os
from abc import ABC, abstractmethod
from typing import Any, Optional

import httpx

from paperfetch.downloaders.base import DownloaderBackend, DownloadContext
from paperfetch.downloaders.pdf_common import (
    PDFDownloadResult,
    verify_pdf_file,
    build_pdf_result,
)
from paperfetch.downloaders.pipeline.errors import DownloadError

logger = get_event_logger(__name__)


class PublisherAPIBackend(DownloaderBackend, ABC):
    """出版商官方 API 统一基类。"""

    concurrency_group = "direct"  # 通常 API 调用也是高并发直连

    # 子类需要指定的元数据
    publisher_name: str
    api_key_env_vars: tuple[str, ...]
    supported_doi_prefixes: frozenset[str]

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key

    def is_configured(self) -> bool:
        """验证该出版商 API 所需的 API Key 是否在环境变量中配置，或已被显式注入。"""
        if getattr(self, "api_key", None):
            return True
        return any(
            os.getenv(var) and os.getenv(var).strip() for var in self.api_key_env_vars
        )

    def get_api_key(self) -> Optional[str]:
        """获取配置的第一个有效的 API Key。"""
        if getattr(self, "api_key", None):
            return getattr(self, "api_key")
        for var in self.api_key_env_vars:
            val = os.getenv(var)
            if val and val.strip():
                return val.strip()
        return None

    def can_handle(self, doi: Optional[str]) -> bool:
        """判断该 DOI 是否属于该出版商所管理的 DOI 前缀。"""
        if not doi:
            return False
        cleaned = doi.strip().lower()
        # 移除前缀
        for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
            if cleaned.startswith(prefix):
                cleaned = cleaned[len(prefix) :]
                break
        cleaned = cleaned.lstrip("/")
        return any(
            cleaned.startswith(p_prefix) for p_prefix in self.supported_doi_prefixes
        )

    @abstractmethod
    async def _fetch_pdf(self, doi: str, client: httpx.AsyncClient) -> httpx.Response:
        """具体子类实现实际的官方 API 获取请求。

        Returns:
            httpx.Response: 请求响应对象。
        """
        pass

    async def download(self, ctx: DownloadContext) -> PDFDownloadResult:
        paper = ctx.paper
        target_file = ctx.target_file

        if not paper.doi:
            raise ValueError("missing_doi")

        if not self.is_configured():
            raise ValueError("missing_credentials")

        # 提取规范化的 DOI
        doi = paper.doi.strip()
        for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
            if doi.lower().startswith(prefix):
                doi = doi[len(prefix) :]
                break
        doi = doi.lstrip("/")

        client_to_use = getattr(ctx, "client", None)
        if client_to_use is not None:
            return await self._execute_download(doi, client_to_use, target_file)
        else:
            async with httpx.AsyncClient(verify=False, follow_redirects=True) as client:
                return await self._execute_download(doi, client, target_file)

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
            raise DownloadError("http_error", route=self.route_key, message=str(e))
