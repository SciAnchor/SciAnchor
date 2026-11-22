from __future__ import annotations

import json

import pytest

from paperfetch.core.settings import (
    SETTINGS_BY_NAME,
    capability_proxy,
    config_schema_payload,
    load_settings,
    reset_settings,
    unknown_settings_env,
)


pytestmark = [pytest.mark.unit, pytest.mark.contract]


def test_unregistered_managed_settings_are_errors(monkeypatch):
    monkeypatch.setenv("SPC_UNREGISTERED_KNOB", "1")
    monkeypatch.setenv("PDF_DOWNLOAD_PROXY_MODE", "proxy")
    unknown = unknown_settings_env()
    assert "SPC_UNREGISTERED_KNOB" in unknown
    assert "PDF_DOWNLOAD_PROXY_MODE" in unknown


def test_schema_config_lists_registered_fields(capsys):
    from paperfetch.cli.root import main

    assert main(["schema", "config"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "spc.result.v2"
    names = {item["name"] for item in payload["data"]["fields"]}
    assert names == set(SETTINGS_BY_NAME)
    assert "publishers" not in payload["data"]
    assert not any(name.startswith(("CSTCLOUD_", "CSUST_")) for name in names)


def test_settings_schema_json_matches_registry(tmp_path):
    from pathlib import Path

    from paperfetch.core.settings import write_settings_schema_json

    generated = write_settings_schema_json(tmp_path / "settings.schema.json")
    committed = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "paperfetch"
        / "data"
        / "config"
        / "settings.schema.json"
    )
    assert json.loads(committed.read_text(encoding="utf-8")) == json.loads(
        generated.read_text(encoding="utf-8")
    )
    assert {
        item["name"]
        for item in json.loads(generated.read_text(encoding="utf-8"))["fields"]
    } == set(SETTINGS_BY_NAME)
