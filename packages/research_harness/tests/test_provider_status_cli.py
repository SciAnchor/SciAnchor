"""Provider status reports exactly the sources the search suite can select.

The public suite is the local PaperVault cache, keyless public scholarly
sources, and SPC when its CLI is installed. No source reads an API key: a key
in the environment is neither reported as a credential nor sent.
"""

from __future__ import annotations

import json

import pytest

from research_harness import env_bootstrap
from research_harness.cli import main
from research_harness.paper_source_clients import (
    KEYLESS_SOURCES,
    available_provider_specs,
    build_provider_suite,
    provider_status_report,
)

KEYLESS = {name for name, _reason in KEYLESS_SOURCES}
ALL = {"papervault", "spc", *KEYLESS}
KEY_ENV = {
    "S2_API_KEY": "s2-token",
    "SEMANTIC_SCHOLAR_API_KEY": "s2-legacy-token",
    "OPENALEX_API_KEY": "openalex-token",
    "PUBMED_API_KEY": "pubmed-token",
}


@pytest.fixture
def spc_on_path(monkeypatch):
    import shutil

    real_which = shutil.which
    monkeypatch.setattr(
        shutil,
        "which",
        lambda name, *a, **k: (
            "/trusted/spc" if name == "spc" else real_which(name, *a, **k)
        ),
    )


@pytest.fixture
def spc_absent(monkeypatch):
    import shutil

    real_which = shutil.which
    monkeypatch.setattr(
        shutil,
        "which",
        lambda name, *a, **k: None if name == "spc" else real_which(name, *a, **k),
    )


def test_keyless_sources_are_enabled_by_default(monkeypatch, spc_absent):
    for name in KEYLESS:
        monkeypatch.delenv(f"{name.upper()}_ENABLE", raising=False)

    specs = {item.name: item for item in available_provider_specs()}

    assert set(specs) == ALL
    assert all(specs[name].enabled for name in KEYLESS)
    assert specs["spc"].enabled is False


@pytest.mark.parametrize("name", sorted(KEYLESS))
def test_a_keyless_source_can_be_disabled(monkeypatch, name):
    monkeypatch.setenv(f"{name.upper()}_ENABLE", "0")

    specs = {item.name: item for item in available_provider_specs()}
    providers = build_provider_suite(fetcher=lambda url, headers: {"data": []})

    assert specs[name].enabled is False
    assert name not in [provider.name for provider in providers]


def test_spc_is_optional_and_joins_when_installed(spc_on_path):
    specs = {item.name: item for item in available_provider_specs()}
    providers = [p.name for p in build_provider_suite(fetcher=lambda u, h: {})]
    assert specs["spc"].enabled is True
    assert "spc" in providers


def test_keys_in_the_environment_are_never_used(monkeypatch):
    for name, value in KEY_ENV.items():
        monkeypatch.setenv(name, value)

    providers = build_provider_suite(fetcher=lambda url, headers: {"data": []})
    report = provider_status_report()

    for provider in providers:
        assert not getattr(provider, "api_key", ""), provider.name
    assert not any(row["credentialed"] for row in report)
    assert all(row["required_env"] == [] for row in report)


def test_search_providers_cli_reports_every_source(runner, monkeypatch, spc_absent):
    for name in KEYLESS:
        monkeypatch.delenv(f"{name.upper()}_ENABLE", raising=False)
    monkeypatch.setenv("PUBMED_ENABLE", "0")

    result = runner.invoke(main, ["--json", "search", "providers"])

    assert result.exit_code == 0, result.output
    mapping = {item["name"]: item for item in json.loads(result.output)}
    assert set(mapping) == ALL
    assert mapping["semantic_scholar"]["ready"] is True
    assert mapping["pubmed"]["enabled"] is False
    assert mapping["spc"]["enabled"] is False


def test_search_providers_does_not_leak_keys_from_shared_env(
    runner, tmp_path, monkeypatch
):
    shared_env = tmp_path / ".config" / "research-harness" / "private.env"
    shared_env.parent.mkdir(parents=True)
    shared_env.write_text(
        "\n".join(f"{key}={value}" for key, value in KEY_ENV.items()),
        encoding="utf-8",
    )
    for name in KEY_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("RESEARCH_HARNESS_AUTO_ENV", "1")
    monkeypatch.setenv("RESEARCH_HARNESS_AUTO_KEYCHAIN", "0")
    monkeypatch.setenv("RESEARCH_HARNESS_ROOT", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    env_bootstrap.reset_ensure_cache_for_tests()

    result = runner.invoke(main, ["--json", "search", "providers"])

    assert result.exit_code == 0, result.output
    providers = {item["name"]: item for item in json.loads(result.output)}
    assert not any(row["credentialed"] for row in providers.values())
    assert all(value not in result.output for value in KEY_ENV.values())
