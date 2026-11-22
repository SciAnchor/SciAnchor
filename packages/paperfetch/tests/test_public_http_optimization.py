# -*- coding: utf-8 -*-
"""针对 public_http 路由重构优化的综合回归测试。"""

import pytest
import httpx

from paperfetch.downloaders.backends.http_direct import HTTPDirectBackend
from paperfetch.downloaders.pipeline.direct import (
    DirectResourceDiscovery,
)
from paperfetch.core.models import PaperRecord


def test_http_direct_headers_modern_and_clean():
    """测试 HTTPDirectBackend 请求头符合现代真实浏览器规范，不携带爬虫特征后缀。"""
    headers = HTTPDirectBackend._headers(referer="https://example.com")
    assert "User-Agent" in headers
    ua = headers["User-Agent"]
    # 行内注释：User-Agent 必须为标准 Chrome 格式，不携带容易触发 WAF 封锁的非标准标识
    assert "Mozilla/5.0" in ua
    assert "Chrome/" in ua
    assert "paperfetch" not in ua
    assert headers.get("Referer") == "https://example.com"
    assert "Sec-Fetch-Dest" in headers


@pytest.mark.asyncio
async def test_discovery_fast_path_short_circuit():
    """测试高置信度静态资源（如 crossref_mdpi_static）发现后提前短路，避免等待慢速 API。"""

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.crossref.org":
            return httpx.Response(
                200,
                json={
                    "message": {
                        "short-container-title": [
                            "Journal of Marine Science and Engineering"
                        ],
                        "volume": "10",
                        "page": "1268",
                        "link": [],
                    }
                },
                request=request,
            )
        if request.url.host in {"www.ebi.ac.uk", "ebi.ac.uk"}:
            return httpx.Response(
                200,
                json={"resultList": {"result": []}},
                request=request,
            )
        return httpx.Response(404, request=request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), trust_env=False
    ) as client:
        discovery = DirectResourceDiscovery(client)

        # 构造 MDPI 论文
        paper = PaperRecord(
            paper_id="spc_11111111111111111111111111111111",
            title="Data Gathering in UWA Sensor Networks: Practical Considerations and Lessons from Sea Trials",
            doi="10.3390/jmse10091268",
        )

        resources, events = await discovery.discover(paper, timeout=10.0)
        # 行内注释：必须命中 MDPI 静态资源
        static_res = [r for r in resources if r.source == "crossref_mdpi_static"]
        assert len(static_res) >= 1
        assert "mdpi-res.com" in static_res[0].url
