"""1.0 官方元数据客户端的代理边界。"""

import pytest

from paperfetch.utils.client import (
    configured_proxy_url,
    normalize_proxy_url,
    create_metadata_client,
    hosts_use_tun_fake_ip,
)


def test_normalize_proxy_url_treats_disable_values_as_missing():
    for value in (None, "", "false", " OFF ", "'none'", '"direct"'):
        assert normalize_proxy_url(value) is None


pytestmark = [pytest.mark.unit, pytest.mark.contract]


@pytest.mark.parametrize(
    "value", ["", "false", "FALSE", "off", "none", "direct", "disabled"]
)
def test_boolean_disabled_proxy_values_mean_direct(monkeypatch, value):
    monkeypatch.setenv("DOWNLOAD_PROXY", value)
    assert configured_proxy_url("DOWNLOAD_PROXY") is None


@pytest.mark.asyncio
async def test_metadata_client_does_not_load_download_proxy(monkeypatch):
    monkeypatch.setenv("DOWNLOAD_PROXY", "http://sensitive.example:1234")
    client = create_metadata_client()
    try:
        assert client._trust_env is False
        assert all(
            "sensitive.example" not in repr(transport)
            for transport in client._mounts.values()
        )
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_metadata_proxy_is_only_used_by_explicit_fallback(monkeypatch):
    monkeypatch.delenv("DOWNLOAD_PROXY", raising=False)
    monkeypatch.setenv("METADATA_PROXY", "http://proxy.example:1234")
    direct = create_metadata_client()
    fallback = create_metadata_client(metadata_proxy_fallback=True)
    try:
        assert direct._spc_transport == "direct"
        assert fallback._spc_transport == "metadata-proxy-fallback"
    finally:
        await direct.aclose()
        await fallback.aclose()


@pytest.mark.asyncio
async def test_metadata_client_never_reuses_download_proxy(monkeypatch):
    monkeypatch.setenv("DOWNLOAD_PROXY", "http://download.example:1234")
    monkeypatch.delenv("METADATA_PROXY", raising=False)
    client = create_metadata_client(metadata_proxy_fallback=True)
    try:
        assert client._spc_transport == "direct"
        assert all(
            "download.example" not in repr(transport)
            for transport in client._mounts.values()
        )
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_external_service_client_never_reuses_download_proxy(monkeypatch):
    from paperfetch.utils.client import create_external_service_client

    monkeypatch.setenv("DOWNLOAD_PROXY", "http://download.example:1234")
    monkeypatch.delenv("MINERU_PROXY", raising=False)
    client = create_external_service_client()
    try:
        assert client._spc_transport == "direct"
        assert all(
            "download.example" not in repr(transport)
            for transport in client._mounts.values()
        )
    finally:
        await client.aclose()


def test_tun_fake_ip_detection_only_accepts_reserved_benchmark_network(monkeypatch):
    import socket

    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.18.1.2", 443)),
        ],
    )
    assert hosts_use_tun_fake_ip(("example.org",)) is True
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.2", 443)),
        ],
    )
    assert hosts_use_tun_fake_ip(("example.org",)) is False


@pytest.mark.asyncio
async def test_download_scheduler_does_not_treat_false_as_proxy_url(
    monkeypatch, tmp_path
):
    from paperfetch.downloaders.pipeline.cache import PDFGlobalCache, PDFVerifier
    from paperfetch.downloaders.pipeline.scheduler import DownloadScheduler

    monkeypatch.setenv("DOWNLOAD_PROXY", "false")
    scheduler = DownloadScheduler(PDFGlobalCache(tmp_path / "cache"), PDFVerifier())
    try:
        assert scheduler.shared_client is not None
    finally:
        await scheduler.close()
