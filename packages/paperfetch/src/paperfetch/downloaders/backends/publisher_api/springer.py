# -*- coding: utf-8 -*-
"""Springer Nature 开放获取与元数据 API PDF 下载器。"""

from __future__ import annotations

from paperfetch.observability import get_event_logger

import httpx

from paperfetch.downloaders.registry import BackendRegistry
from paperfetch.downloaders.backends.publisher_api.base import PublisherAPIBackend
from paperfetch.utils.client import async_request_with_retry

logger = get_event_logger(__name__)


@BackendRegistry.register
class SpringerNatureAPIBackend(PublisherAPIBackend):
    """Springer Nature 官方 API 获取后端。"""

    route_key = "publisher_api_springer"
    display_name = "Springer Nature API"
    supported_routes = frozenset({"publisher_api_springer"})

    publisher_name = "Springer Nature"
    api_key_env_vars = ("SPRINGER_API_KEY",)
    supported_doi_prefixes = frozenset({"10.1007/", "10.1038/", "10.1186/"})

    async def _fetch_pdf(self, doi: str, client: httpx.AsyncClient) -> httpx.Response:
        api_key = self.get_api_key()
        # Springer OpenAccess API JATS 检索元数据，对于 OA 包含 PDF 直链
        url = f"https://api.springernature.com/openaccess/json?q=doi:{doi}&api_key={api_key}"

        # 1. 检索元数据以定位 PDF 链接
        meta_response = await async_request_with_retry(
            client,
            "GET",
            url,
            timeout=15.0,
        )
        if meta_response.status_code != 200:
            return meta_response

        data = meta_response.json()
        records = data.get("records", [])
        if not records:
            # 伪造一个 404
            return httpx.Response(404, request=meta_response.request)

        # 查找 PDF 链接
        pdf_url = None
        for record in records:
            urls = record.get("url", [])
            for u in urls:
                if u.get("format") == "pdf":
                    pdf_url = u.get("value")
                    break
            if pdf_url:
                break

        if not pdf_url:
            return httpx.Response(404, request=meta_response.request)

        # 2. 执行真实的 PDF 文件下载
        response = await async_request_with_retry(
            client,
            "GET",
            pdf_url,
            timeout=45.0,
            headers={
                "User-Agent": "paperfetch/2.0",
            },
        )
        return response
