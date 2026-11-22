"""Shape-lock tests for the split CLI trends command module."""

from __future__ import annotations

from dataclasses import dataclass

from click.testing import CliRunner

from research_harness.cli import main
from research_harness.cli_trends import register


@dataclass(frozen=True)
class _Cluster:
    name: str
    publishability_score: float
    velocity_yoy: float


def test_cli_trends_module_exports_register() -> None:
    assert callable(register)
    assert "trends" in main.commands


def test_trends_refresh_help_still_registered_from_split_module() -> None:
    result = CliRunner().invoke(main, ["trends", "refresh", "--help"])

    assert result.exit_code == 0, result.output
    assert "--tier" in result.output
    assert "--dry-run" in result.output


def test_trends_refresh_invokes_pipeline_with_existing_output_shape(
    runner: CliRunner, monkeypatch
) -> None:
    calls: list[tuple[str, bool]] = []

    def fake_refresh_trends(conn, *, tier: str, dry_run: bool):
        assert conn is not None
        calls.append((tier, dry_run))
        return [_Cluster("agent evaluation", 7.5, 12.0)]

    monkeypatch.setattr("research_harness.trends.refresh_trends", fake_refresh_trends)

    result = runner.invoke(
        main,
        ["trends", "refresh", "--tier", "premium", "--dry-run"],
    )

    assert result.exit_code == 0, result.output
    assert calls == [("premium", True)]
    assert "[DRY RUN] Found 1 trend clusters:" in result.output
    assert "agent evaluation" in result.output
    assert "score=7.5" in result.output
    assert "velocity=12%" in result.output
