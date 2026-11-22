# -*- coding: utf-8 -*-
"""针对 Issue #20: 元数据慢网络超时配置与精细异常分类回归测试。"""

import os
from unittest.mock import AsyncMock, patch
import pytest
import httpx

from paperfetch.utils.client import create_metadata_client, _metadata_timeout
from paperfetch.papers.lookup import PaperLookupService, LookupRequest, PaperLookupError


def test_metadata_timeout_env_override(monkeypatch):
    """测试通过环境变量自定义元数据客户端超时时间。"""
    monkeypatch.setenv("METADATA_CONNECT_TIMEOUT", "18.5")
    monkeypatch.setenv("METADATA_READ_TIMEOUT", "45.0")

    timeout = _metadata_timeout()
    assert timeout.connect == 18.5
    assert timeout.read == 45.0

    client = create_metadata_client()
    assert client.timeout.connect == 18.5
    assert client.timeout.read == 45.0


@pytest.mark.asyncio
async def test_paper_lookup_connect_timeout_classification():
    """测试当元数据服务连接超时时，精准分类为 connect_timeout。"""
    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get.side_effect = httpx.ConnectTimeout(
        "Connection timed out to Europe PMC"
    )

    service = PaperLookupService(mock_client)
    req = LookupRequest(identifier_type="doi", value="10.1000/182")

    # 行内注释：必须抛出具有精确 error_class="connect_timeout" 的 PaperLookupError
    with pytest.raises(PaperLookupError) as exc_info:
        await service.lookup(req)

    assert exc_info.value.code == "metadata_transport_failed"
    assert exc_info.value.error_class == "connect_timeout"
    assert "connect_timeout" in exc_info.value.message
