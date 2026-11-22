"""Tests for the plugin discovery mechanism."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


@pytest.fixture
def _reset_registry():
    """Snapshot the provider registry and restore after each test."""
    from llm_router import client as client_mod

    before = dict(client_mod._PROVIDER_REGISTRY)
    yield
    client_mod._PROVIDER_REGISTRY.clear()
    client_mod._PROVIDER_REGISTRY.update(before)


def _write_plugin(path: Path, name: str, text: str) -> None:
    path.write_text(
        textwrap.dedent(f"""\
        from llm_router import register_provider

        def _chat_{name}(prompt, model, **_):
            return {text!r}

        register_provider({name!r}, _chat_{name})
        """),
        encoding="utf-8",
    )


def _isolated_providers(
    *,
    project_root: Path,
    home: Path,
    explicit_plugins: str | None,
) -> list[str]:
    env = os.environ.copy()
    env["HOME"] = str(home)
    if explicit_plugins is None:
        env.pop("LLM_ROUTER_PLUGINS", None)
    else:
        env["LLM_ROUTER_PLUGINS"] = explicit_plugins

    code = (
        "import json, sys; "
        f"sys.path.insert(0, {str(project_root)!r}); "
        "from llm_router import list_providers; "
        "print(json.dumps(list_providers()))"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", code],
        check=True,
        capture_output=True,
        env=env,
        text=True,
    )
    return json.loads(result.stdout)


def test_env_plugin_loads_single_file(tmp_path, monkeypatch, _reset_registry):
    plugin_file = tmp_path / "my_provider.py"
    _write_plugin(plugin_file, "my_test_single", "ok-single")

    monkeypatch.setenv("LLM_ROUTER_PLUGINS", str(plugin_file))

    from llm_router import get_provider, list_providers, load_plugins

    load_plugins()

    assert "my_test_single" in list_providers()
    assert get_provider("my_test_single")("hi", "") == "ok-single"


def test_env_plugin_loads_directory(tmp_path, monkeypatch, _reset_registry):
    (tmp_path / "a.py").write_text(
        "from llm_router import register_provider\n"
        "register_provider('plug_a', lambda p, m, **_: 'A')\n",
        encoding="utf-8",
    )
    (tmp_path / "b.py").write_text(
        "from llm_router import register_provider\n"
        "register_provider('plug_b', lambda p, m, **_: 'B')\n",
        encoding="utf-8",
    )
    (tmp_path / "_skipped.py").write_text(
        "raise RuntimeError('underscore prefix should be ignored')\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("LLM_ROUTER_PLUGINS", str(tmp_path))

    from llm_router import list_providers, load_plugins

    load_plugins()

    providers = list_providers()
    assert "plug_a" in providers
    assert "plug_b" in providers


def test_broken_plugin_does_not_break_router(
    tmp_path,
    monkeypatch,
    caplog,
    _reset_registry,
):
    good = tmp_path / "good.py"
    _write_plugin(good, "still_works", "ok")

    bad = tmp_path / "bad.py"
    bad.write_text("raise RuntimeError('boom')\n", encoding="utf-8")

    monkeypatch.setenv("LLM_ROUTER_PLUGINS", str(tmp_path))

    from llm_router import list_providers, load_plugins

    load_plugins()

    assert "still_works" in list_providers()


def test_missing_plugin_path_is_silent(tmp_path, monkeypatch, _reset_registry):
    monkeypatch.setenv(
        "LLM_ROUTER_PLUGINS",
        str(tmp_path / "does-not-exist.py"),
    )

    from llm_router import load_plugins

    # Must not raise
    load_plugins()


def test_explicit_plugin_dir_does_not_scan_home(tmp_path):
    project_root = Path(__file__).parents[1]
    fake_home = tmp_path / "home"
    home_plugins = fake_home / ".config" / "llm_router" / "plugins"
    trusted_plugins = tmp_path / "trusted"
    home_plugins.mkdir(parents=True)
    trusted_plugins.mkdir()
    _write_plugin(home_plugins / "home.py", "from_home", "home")
    _write_plugin(trusted_plugins / "trusted.py", "from_trusted", "trusted")

    providers = _isolated_providers(
        project_root=project_root,
        home=fake_home,
        explicit_plugins=str(trusted_plugins),
    )

    assert "from_trusted" in providers
    assert "from_home" not in providers


@pytest.mark.parametrize("explicit_plugins", [None, ""])
def test_default_dir_scanned_when_env_unset_or_empty(tmp_path, explicit_plugins):
    project_root = Path(__file__).parents[1]
    fake_home = tmp_path / "home"
    home_plugins = fake_home / ".config" / "llm_router" / "plugins"
    home_plugins.mkdir(parents=True)
    _write_plugin(home_plugins / "home.py", "from_home", "home")

    providers = _isolated_providers(
        project_root=project_root,
        home=fake_home,
        explicit_plugins=explicit_plugins,
    )

    assert "from_home" in providers
