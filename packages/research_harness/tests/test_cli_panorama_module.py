"""Shape-lock and behavior tests for the panorama CLI command module."""

from __future__ import annotations

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_panorama import register


def test_cli_panorama_module_exports_register() -> None:
    assert callable(register)
    assert "panorama" in main.commands


def test_panorama_subcommands_registered() -> None:
    result = CliRunner().invoke(main, ["panorama", "--help"])

    assert result.exit_code == 0, result.output
    for sub in ("init", "import", "views", "pack", "status", "verdict"):
        assert sub in result.output


def test_panorama_init_and_status_roundtrip(tmp_path) -> None:
    runner = CliRunner()
    root = tmp_path / "panorama"

    result = runner.invoke(
        main,
        [
            "panorama",
            "init",
            "test-dir",
            "--title",
            "Test Direction",
            "--rh-domain-id",
            "20",
            "--root",
            str(root),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert (root / "L1" / "panorama.db").exists()

    result = runner.invoke(
        main, ["panorama", "status", "test-dir", "--root", str(root)]
    )
    assert result.exit_code == 0, result.output
    assert "test-dir" in result.output


def test_panorama_verdict_records_and_status_unknown_direction_fails(
    tmp_path,
) -> None:
    runner = CliRunner()
    root = tmp_path / "panorama"
    runner.invoke(
        main,
        ["panorama", "init", "test-dir", "--root", str(root)],
    )

    result = runner.invoke(
        main,
        [
            "panorama",
            "verdict",
            "test-dir",
            "--claim",
            "living multi-source panorama KB with coverage guarantees",
            "--verdict",
            "novel-surface-gap",
            "--evidence-json",
            '{"neighbors": ["XCIENTIST"]}',
            "--root",
            str(root),
        ],
    )
    assert result.exit_code == 0, result.output

    result = runner.invoke(
        main, ["panorama", "status", "no-such-dir", "--root", str(root)]
    )
    assert result.exit_code != 0
    assert "Unknown panorama direction" in result.output
