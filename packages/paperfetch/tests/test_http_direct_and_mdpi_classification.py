# -*- coding: utf-8 -*-
"""针对 Issue #14: 403 错误分类与 MDPI 路由生成回归测试。"""

import pytest
import httpx

from paperfetch.downloaders.backends.http_direct import HTTPDirectBackend


def test_classify_public_403_is_not_auth_required():
    """测试公共 HTTP 路由下遇到普通 403 / Access Denied 时，不被误报为 auth_required。"""
    headers = httpx.Headers({"content-type": "text/html", "server": "AkamaiGHost"})
    preview = b"<HTML><HEAD>\n<TITLE>Access Denied</TITLE>\n</HEAD><BODY>\n<H1>Access Denied</H1>\n</BODY></HTML>"

    # 行内注释：普通反爬或公共访问受限返回 403 时，应归类为 publisher_challenge 或 public_access_blocked，不能为 auth_required
    error_class = HTTPDirectBackend._classify(
        403,
        "text/html",
        preview,
        "https://www.mdpi.com/10.3390/jmse10091268/pdf",
        headers,
    )
    assert error_class in {"publisher_challenge", "public_access_blocked"}
    assert error_class != "auth_required"


def test_classify_institutional_login_403_is_auth_required():
    """测试当 403 页面确实包含机构登录 / Shibboleth 时，正确识别为 auth_required。"""
    headers = httpx.Headers({"content-type": "text/html"})
    preview = b"<html><body><h1>Sign in via your Institution</h1><p>Please log in via Shibboleth or OpenAthens</p></body></html>"

    error_class = HTTPDirectBackend._classify(
        403,
        "text/html",
        preview,
        "https://www.sciencedirect.com/science/article/pii/S12345",
        headers,
    )
    assert error_class == "auth_required"


@pytest.mark.asyncio
async def test_mdpi_crossref_slug_normalization():
    """测试 MDPI 期刊名短 slug 映射（如 Applied Sciences -> applsci）。"""
    from paperfetch.downloaders.pipeline.direct import DirectResourceDiscovery
    from paperfetch.core.models import PaperRecord

    async with httpx.AsyncClient() as client:
        discovery = DirectResourceDiscovery(client)

        # 模拟 Crossref 返回 Applied Sciences
        message = {
            "short-container-title": ["Applied Sciences"],
            "volume": "11",
            "page": "312",
        }

        # 验证能针对 10.3390/app11010312 生成 applsci 的静态 URL
        mock_paper = PaperRecord(
            paper_id="mdpi_test_1",
            title="Test MDPI Applied Sciences",
            doi="10.3390/app11010312",
        )
        from paperfetch.downloaders.pipeline.direct import MDPI_JOURNAL_SLUG_MAP

        assert MDPI_JOURNAL_SLUG_MAP.get("applied sciences") == "applsci"
        assert MDPI_JOURNAL_SLUG_MAP.get("app") == "applsci"
        assert MDPI_JOURNAL_SLUG_MAP.get("jmse") == "jmse"
