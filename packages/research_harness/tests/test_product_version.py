"""Product SemVer is one number across the two installable packages."""

from __future__ import annotations

import re
from pathlib import Path

import click.testing

import research_harness
import research_harness_mcp
from research_harness.cli import main

ROOT = Path(__file__).resolve().parents[3]
_VERSION = re.compile(r'^version = "([^"]+)"$', re.M)


def _pyproject_version(path: Path) -> str:
    match = _VERSION.search(path.read_text(encoding="utf-8"))
    assert match, path
    return match.group(1)


def test_installable_packages_share_product_version():
    core = _pyproject_version(ROOT / "packages" / "research_harness" / "pyproject.toml")
    mcp = _pyproject_version(
        ROOT / "packages" / "research_harness_mcp" / "pyproject.toml"
    )
    assert (
        core
        == mcp
        == research_harness.__version__
        == research_harness_mcp.__version__
        == "1.5.0"
    )


def test_cli_reports_product_version():
    result = click.testing.CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "1.5.0" in result.output
