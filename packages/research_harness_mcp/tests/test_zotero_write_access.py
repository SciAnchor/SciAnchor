"""Focused tests for Zotero write-access helper extraction."""

from __future__ import annotations


def test_zotero_write_access_helpers_preserve_http_api_aliases():
    from research_harness_mcp import http_api, zotero_write_access

    assert http_api._zotero_api_library_id is zotero_write_access.zotero_api_library_id
    assert (
        http_api._create_zotero_write_client
        is zotero_write_access.create_zotero_write_client
    )
    assert http_api._zotero_write_adapter is zotero_write_access.zotero_write_adapter


def test_zotero_api_library_id_maps_local_user_library_to_configured_id(monkeypatch):
    from research_harness_mcp import zotero_write_access

    monkeypatch.setenv("ZOTERO_LIBRARY_ID", "16929158")
    monkeypatch.setenv("ZOTERO_LIBRARY_TYPE", "user")

    assert zotero_write_access.zotero_api_library_id("1", "user") == "16929158"
    assert zotero_write_access.zotero_api_library_id(None, "user") == "16929158"
    assert zotero_write_access.zotero_api_library_id("42", "user") == "42"


def test_zotero_api_library_id_uses_matching_configured_type_only(monkeypatch):
    from research_harness_mcp import zotero_write_access

    monkeypatch.setenv("ZOTERO_LIBRARY_ID", "GROUP42")
    monkeypatch.setenv("ZOTERO_LIBRARY_TYPE", "group")

    assert zotero_write_access.zotero_api_library_id(None, "group") == "GROUP42"
    assert zotero_write_access.zotero_api_library_id(None, "user") == ""
    assert zotero_write_access.zotero_api_library_id("1", "group") == "1"


def test_zotero_write_adapter_preserves_env_api_and_local_selection(monkeypatch):
    from research_harness_mcp import zotero_write_access

    monkeypatch.setenv("ZOTERO_ADAPTER", "LOCAL")
    assert (
        zotero_write_access.zotero_write_adapter(
            library_id="99",
            library_type="group",
            api_key="secret",
            desktop_library_id="2",
        )
        == "local"
    )

    monkeypatch.delenv("ZOTERO_ADAPTER", raising=False)
    assert (
        zotero_write_access.zotero_write_adapter(
            library_id="1",
            library_type="user",
            api_key="secret",
            desktop_library_id="1",
        )
        == "web"
    )
    assert (
        zotero_write_access.zotero_write_adapter(
            library_id="1",
            library_type="user",
            api_key="",
            desktop_library_id="1",
        )
        == "connector"
    )
    assert (
        zotero_write_access.zotero_write_adapter(
            library_id="1",
            library_type="group",
            api_key="",
            desktop_library_id="1",
        )
        == "web"
    )


def test_create_zotero_write_client_uses_connector_for_local_user_library(
    monkeypatch,
):
    from research_harness import zotero_resource
    from research_harness_mcp import zotero_write_access

    calls: list[dict] = []
    fake_client = object()

    def fake_create_zotero_resource(**kwargs):
        calls.append(kwargs)
        return fake_client

    monkeypatch.delenv("ZOTERO_ADAPTER", raising=False)
    monkeypatch.setattr(
        zotero_resource,
        "create_zotero_resource",
        fake_create_zotero_resource,
    )

    client, service_library_id = zotero_write_access.create_zotero_write_client(
        library_id="1",
        library_type="user",
        api_key="",
        api_base="https://api.example.invalid",
        desktop_library_id="1",
    )

    assert client is fake_client
    assert service_library_id == "local"
    assert calls == [
        {
            "adapter": "connector",
            "library_id": "1",
            "library_type": "user",
            "api_key": "",
            "base_url": "https://api.example.invalid",
        }
    ]


def test_create_zotero_write_client_uses_web_library_id_for_api_key(
    monkeypatch,
):
    from research_harness import zotero_resource
    from research_harness_mcp import zotero_write_access

    calls: list[dict] = []
    fake_client = object()

    def fake_create_zotero_resource(**kwargs):
        calls.append(kwargs)
        return fake_client

    monkeypatch.delenv("ZOTERO_ADAPTER", raising=False)
    monkeypatch.setattr(
        zotero_resource,
        "create_zotero_resource",
        fake_create_zotero_resource,
    )

    client, service_library_id = zotero_write_access.create_zotero_write_client(
        library_id="16929158",
        library_type="user",
        api_key="secret",
        api_base="https://api.example.invalid",
        desktop_library_id="1",
    )

    assert client is fake_client
    assert service_library_id == "16929158"
    assert calls[0]["adapter"] == "web"
