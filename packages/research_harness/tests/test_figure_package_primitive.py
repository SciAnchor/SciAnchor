"""Public figure_package primitive wraps build_figure_package (fake provider)."""

from __future__ import annotations

from pathlib import Path

import pytest

from research_harness.primitives.result_figure_impls import figure_package
from research_harness.visualization.figure_package_contracts import SCHEMA_FIGURE_TASK


def _task(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": SCHEMA_FIGURE_TASK,
        "task_id": "task-uf09-public",
        "target_venue": "Information Processing & Management",
        "context_type": "partial_context",
        "requested_action": "create",
    }
    payload.update(overrides)
    return payload


def test_figure_package_requires_output_dir() -> None:
    with pytest.raises(ValueError, match="output_dir"):
        figure_package(task=_task())


def test_figure_package_requires_task(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="task"):
        figure_package(output_dir=str(tmp_path))


def test_insufficient_task_is_pending_without_package(tmp_path: Path) -> None:
    result = figure_package(
        task=_task(paper_context={}),
        output_dir=str(tmp_path),
    )
    assert result.status == "pending"
    assert result.package is None
    assert list(tmp_path.iterdir()) == []


def test_public_path_does_not_accept_provider(tmp_path: Path) -> None:
    class _Probe:
        called = False

        def generate(self, request):  # pragma: no cover - must not run
            self.called = True
            raise AssertionError("public figure_package must not take a provider")

    result = figure_package(
        task=_task(paper_context={}),
        output_dir=str(tmp_path),
        provider=_Probe(),  # type: ignore[call-arg]
    )
    assert result.status == "pending"
    assert _Probe.called is False
