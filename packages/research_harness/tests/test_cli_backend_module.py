"""Shape-lock tests for the split CLI backend command module."""

from __future__ import annotations

import json
import os
import stat

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_backend import register


def test_cli_backend_module_exports_register() -> None:
    assert callable(register)
    assert "backend" in main.commands


def test_backend_list_still_registered_from_split_module(runner: CliRunner) -> None:
    result = runner.invoke(main, ["--json", "backend", "list"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == ["claude_code", "local", "research_harness"]


def test_cli_loads_private_env_without_overriding_process_env(
    runner: CliRunner, tmp_path, monkeypatch
) -> None:
    home = tmp_path / "home"
    config_dir = home / ".config" / "research-harness"
    config_dir.mkdir(parents=True)
    (config_dir / "private.env").write_text(
        "\n".join(
            [
                "OPENAI_API_KEY=file-key",
                "OPENAI_BASE_URL=https://proxy.example/v1",
                "export SEMANTIC_SCHOLAR_API_KEY=s2-file-key",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    # This test exercises the autoload itself; opt back in over the
    # suite-wide RESEARCH_HARNESS_AUTO_ENV=0 isolation.
    monkeypatch.setenv("RESEARCH_HARNESS_AUTO_ENV", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "process-key")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("SEMANTIC_SCHOLAR_API_KEY", raising=False)

    result = runner.invoke(main, ["--json", "backend", "list"])

    assert result.exit_code == 0, result.output
    assert os.environ["OPENAI_API_KEY"] == "process-key"
    assert os.environ["OPENAI_BASE_URL"] == "https://proxy.example/v1"
    assert os.environ["SEMANTIC_SCHOLAR_API_KEY"] == "s2-file-key"


def test_cli_env_autoload_can_be_disabled(
    runner: CliRunner, tmp_path, monkeypatch
) -> None:
    home = tmp_path / "home"
    config_dir = home / ".config" / "research-harness"
    config_dir.mkdir(parents=True)
    (config_dir / "private.env").write_text(
        "OPENAI_BASE_URL=https://proxy.example/v1\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("RESEARCH_HARNESS_AUTO_ENV", "0")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    result = runner.invoke(main, ["--json", "backend", "list"])

    assert result.exit_code == 0, result.output
    assert "OPENAI_BASE_URL" not in os.environ


def test_cli_loads_rh_root_env_for_figure_backends(
    runner: CliRunner, tmp_path, monkeypatch
) -> None:
    root = tmp_path / "rh-root"
    root.mkdir()
    (root / ".env").write_text(
        "\n".join(
            [
                "GOOGLE_API_KEY=google-secret",
                "RESEARCH_HARNESS_FIGURE_GEMINI_MODEL=gemini-2.5-flash-image",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("RESEARCH_HARNESS_ROOT", str(root))
    # Exercise the root-env autoload explicitly; keep the developer's real
    # private.env out of view so values come from the root .env alone.
    monkeypatch.setenv("RESEARCH_HARNESS_AUTO_ENV", "1")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("RESEARCH_HARNESS_AUTO_KEYCHAIN", "0")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("RESEARCH_HARNESS_FIGURE_GEMINI_MODEL", raising=False)

    result = runner.invoke(main, ["--json", "backend", "list"])

    assert result.exit_code == 0, result.output
    assert os.environ["GOOGLE_API_KEY"] == "google-secret"
    assert os.environ["RESEARCH_HARNESS_FIGURE_GEMINI_MODEL"] == (
        "gemini-2.5-flash-image"
    )
    assert "google-secret" not in result.output


def test_cli_loads_figure_backend_keychain_secrets(
    runner: CliRunner, tmp_path, monkeypatch
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    security = bin_dir / "security"
    security.write_text(
        "#!/usr/bin/env bash\n"
        "service=''\n"
        "while [[ $# -gt 0 ]]; do\n"
        '  if [[ "$1" == \'-s\' ]]; then service="$2"; shift 2; continue; fi\n'
        "  shift\n"
        "done\n"
        'case "$service" in\n'
        "  research-harness:GOOGLE_API_KEY) printf '%s' 'google-secret' ;;\n"
        "  research-harness:RESEARCH_HARNESS_FIGURE_GEMINI_MODEL) printf '%s' 'gemini-2.5-flash-image' ;;\n"
        "  *) exit 44 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    security.chmod(security.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("USER", "tester")
    # Exercise the Keychain autoload explicitly over the suite-wide opt-out,
    # with an empty HOME so the stubbed `security` is the only source.
    monkeypatch.setenv("RESEARCH_HARNESS_AUTO_ENV", "1")
    monkeypatch.setenv("RESEARCH_HARNESS_AUTO_KEYCHAIN", "1")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("RESEARCH_HARNESS_FIGURE_GEMINI_MODEL", raising=False)

    result = runner.invoke(main, ["--json", "backend", "list"])

    assert result.exit_code == 0, result.output
    assert os.environ["GOOGLE_API_KEY"] == "google-secret"
    assert os.environ["RESEARCH_HARNESS_FIGURE_GEMINI_MODEL"] == (
        "gemini-2.5-flash-image"
    )
    assert "google-secret" not in result.output


def test_cli_keychain_autoload_can_be_disabled(
    runner: CliRunner, tmp_path, monkeypatch
) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    security = bin_dir / "security"
    security.write_text(
        "#!/usr/bin/env bash\nprintf '%s' 'secret'\n",
        encoding="utf-8",
    )
    security.chmod(security.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("USER", "tester")
    monkeypatch.setenv("RESEARCH_HARNESS_AUTO_ENV", "0")
    monkeypatch.setenv("RESEARCH_HARNESS_AUTO_KEYCHAIN", "0")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    result = runner.invoke(main, ["--json", "backend", "list"])

    assert result.exit_code == 0, result.output
    assert "GOOGLE_API_KEY" not in os.environ
