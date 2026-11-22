# -*- coding: utf-8 -*-
"""SPC 出站流量分类契约与按类别出口探测。"""

from urllib.parse import urlsplit

import pytest

from paperfetch.network import (
    load_traffic_classes,
    probe_traffic_class,
    probe_traffic_classes,
)
from paperfetch.network.traffic_classes import SCHEMA_VERSION, classify_host


def _class_by_id(class_id: str):
    for item in load_traffic_classes():
        if item.id == class_id:
            return item
    raise AssertionError(f"契约缺少类别 {class_id}")


def test_contract_loads_with_expected_schema_and_requirements():
    classes = load_traffic_classes()
    assert {item.id for item in classes} == {"paper_download", "data_download"}
    for item in classes:
        assert item.exit_requirement in {"single_exit", "stable_exit"}
        assert item.rationale.strip(), f"{item.id} 必须说明出口要求的依据"
        assert item.domains
    assert _class_by_id("paper_download").requires_single_exit
    assert _class_by_id("data_download").requires_stable_exit


def test_schema_version_mismatch_is_rejected(tmp_path):
    bad = tmp_path / "traffic_classes.json"
    bad.write_text(
        '{"schema_version": "spc.traffic-classes.v0", "classes": []}', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="schema 版本"):
        load_traffic_classes(bad)


def test_data_source_roots_are_covered_by_data_class():
    """数据源常量新增而分类未跟进时必须失败。"""
    from paperfetch.datasets.dryad import DRYAD_ROOT
    from paperfetch.datasets.geo import GEO_FTP_ROOT
    from paperfetch.datasets.mirbase import MIRBASE_CURRENT_ROOT
    from paperfetch.datasets.ncbi import EUTILS_ROOT

    classes = load_traffic_classes()
    for root in (GEO_FTP_ROOT, DRYAD_ROOT, EUTILS_ROOT, MIRBASE_CURRENT_ROOT):
        host = urlsplit(root).hostname
        assert classify_host(host, classes) == "data_download", (
            f"{host} 未纳入数据下载分类"
        )


def test_paper_and_data_classes_do_not_overlap():
    paper = _class_by_id("paper_download")
    data = _class_by_id("data_download")
    for domain in data.domains:
        assert classify_host(domain, (paper, data)) == "data_download"
    for domain in paper.domains:
        assert classify_host(domain, (paper, data)) == "paper_download"


def test_classify_host_prefers_longest_suffix():
    classes = load_traffic_classes()
    # iop.org 与 iopscience.iop.org 同时存在，结果不得依赖声明顺序
    assert classify_host("iopscience.iop.org", classes) == "paper_download"
    assert classify_host("ftp.ncbi.nlm.nih.gov", classes) == "data_download"
    assert classify_host("FTP.NCBI.NLM.NIH.GOV.", classes) == "data_download"


def test_classify_host_returns_none_for_unrelated_host():
    assert classify_host("example.com", load_traffic_classes()) is None
    assert classify_host("", load_traffic_classes()) is None
    # 不得被子串误伤：notncbi.nlm.nih.gov.evil.com 不属于数据类
    assert classify_host("evil.com", load_traffic_classes()) is None


class _StubResponse:
    def __init__(self, status_code: int, content: bytes):
        self.status_code = status_code
        self.content = content
        self.text = content.decode("utf-8", "ignore")


class _StubClient:
    def __init__(self, response=None, error=None, **kwargs):
        self.kwargs = kwargs
        self._response = response
        self._error = error

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get(self, url):
        if self._error is not None:
            raise self._error
        return self._response


def _patch_client(monkeypatch, response=None, error=None, captured=None):
    import httpx

    def factory(**kwargs):
        if captured is not None:
            captured.update(kwargs)
        return _StubClient(response=response, error=error, **kwargs)

    monkeypatch.setattr(httpx, "Client", factory)


def test_data_class_probe_requires_real_bytes(monkeypatch):
    """状态 200 但零字节必须判为 no_bytes，不能算通过。"""
    data = _class_by_id("data_download")
    _patch_client(monkeypatch, response=_StubResponse(200, b""))
    result = probe_traffic_class(data, "http://127.0.0.1:7897")
    assert result["outcome"] == "no_bytes"
    assert result["bytes_received"] == 0

    _patch_client(monkeypatch, response=_StubResponse(200, b"User-agent: *\n"))
    result = probe_traffic_class(data, "http://127.0.0.1:7897")
    assert result["outcome"] == "ok"
    assert result["bytes_received"] > 0


def test_paper_class_probe_accepts_redirect_to_sso(monkeypatch):
    """论文类入口通常 30x 跳转到 SSO，收到 HTTP 响应即视为通路存在。"""
    paper = _class_by_id("paper_download")
    _patch_client(monkeypatch, response=_StubResponse(302, b""))
    result = probe_traffic_class(paper, "http://127.0.0.1:7897")
    assert result["outcome"] == "ok"
    assert result["http_status"] == 302


def test_paper_class_probe_fails_when_overseas_entry_is_unreachable(monkeypatch):
    """国内主探针走直连仍会成功；境外入口经死节点失败时必须判为不可用，不能误报 ok。"""
    import httpx

    paper = _class_by_id("paper_download")
    assert paper.extra_probe_urls, "论文类必须带至少一个境外入口探针"
    overseas = paper.extra_probe_urls[0]

    class _SplitClient(_StubClient):
        def get(self, url):
            if url == overseas:
                raise httpx.ConnectError("upstream node dead")
            return _StubResponse(302, b"")

    monkeypatch.setattr(httpx, "Client", lambda **kwargs: _SplitClient(**kwargs))
    result = probe_traffic_class(paper, "http://127.0.0.1:7890")
    assert result["outcome"] == "unreachable"
    assert result["failed_probe_url"] == overseas
    assert result["error_class"] == "ConnectError"


def test_paper_class_probe_fails_when_overseas_entry_returns_5xx(monkeypatch):
    """境外附加入口返回 502/503 代理/网关错误时，同样必须判为不可用/降级。"""
    import httpx

    paper = _class_by_id("paper_download")
    overseas = paper.extra_probe_urls[0]

    class _GatewayErrClient(_StubClient):
        def __init__(self, status_code=502, **kwargs):
            super().__init__(**kwargs)
            self._status_code = status_code

        def get(self, url):
            if url == overseas:
                return _StubResponse(self._status_code, b"Bad Gateway")
            return _StubResponse(200, b"ok")

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _GatewayErrClient(502, **kwargs)
    )
    result = probe_traffic_class(paper, "http://127.0.0.1:7890")
    assert result["outcome"] == "http_error"
    assert result["http_status"] == 502
    assert result["failed_probe_url"] == overseas

    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: _GatewayErrClient(503, **kwargs)
    )
    summary = probe_traffic_classes("http://127.0.0.1:7890")
    assert "paper_download" in summary["degraded"]


def test_proxy_auth_required_is_not_reported_as_healthy(monkeypatch):
    paper = _class_by_id("paper_download")
    _patch_client(monkeypatch, response=_StubResponse(407, b"proxy auth required"))

    result = probe_traffic_class(paper, "http://127.0.0.1:7897")

    assert result["outcome"] == "proxy_auth_required"


def test_probe_masks_proxy_credentials(monkeypatch):
    _patch_client(monkeypatch, response=_StubResponse(200, b"ok"))
    result = probe_traffic_class(
        _class_by_id("data_download"), "http://user:secret@127.0.0.1:7897"
    )
    assert result["proxy"] == "http://127.0.0.1:7897"
    assert "secret" not in str(result)


def test_probe_reports_transport_error_without_raising(monkeypatch):
    _patch_client(monkeypatch, error=OSError("connection refused"))
    result = probe_traffic_class(_class_by_id("data_download"), "http://127.0.0.1:7897")
    assert result["outcome"] == "unreachable"
    assert result["error_class"] == "OSError"
    assert result["elapsed_ms"] is not None


def test_probe_does_not_inherit_environment_proxy(monkeypatch):
    captured: dict = {}
    _patch_client(monkeypatch, response=_StubResponse(200, b"ok"), captured=captured)
    probe_traffic_class(_class_by_id("data_download"), None)
    assert captured["trust_env"] is False, "探测必须显式指定出口，不得继承环境代理"


def test_probe_all_classes_reports_degraded(monkeypatch):
    _patch_client(monkeypatch, response=_StubResponse(200, b""))
    summary = probe_traffic_classes("http://127.0.0.1:7897")
    assert summary["schema_version"] == SCHEMA_VERSION
    # 数据类零字节判定为降级；论文类只要有响应即通过
    assert "data_download" in summary["degraded"]
    assert summary["proxy"] == "http://127.0.0.1:7897"


def test_exit_ip_probe_is_opt_in(monkeypatch):
    from paperfetch.core.settings import reset_settings

    monkeypatch.delenv("SPC_EXIT_IP_PROBE_URL", raising=False)
    reset_settings()
    _patch_client(monkeypatch, response=_StubResponse(200, b"ok"))
    result = probe_traffic_class(_class_by_id("data_download"), None)
    assert result["exit_ip"] is None

    monkeypatch.setenv("SPC_EXIT_IP_PROBE_URL", "https://echo.invalid/ip")
    reset_settings()
    _patch_client(monkeypatch, response=_StubResponse(200, b"203.0.113.7"))
    result = probe_traffic_class(_class_by_id("data_download"), None)
    assert result["exit_ip"] == "203.0.113.7"
