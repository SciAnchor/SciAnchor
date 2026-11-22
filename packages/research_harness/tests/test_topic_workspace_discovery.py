from __future__ import annotations

from pathlib import Path


def test_discover_topic_id_from_workspace_reads_parent_markdown(tmp_path: Path) -> None:
    from research_harness.topic_workspace import discover_topic_id_from_workspace

    workspace = tmp_path / "rh-workspace" / "domain" / "topic"
    nested = workspace / "06-writing"
    nested.mkdir(parents=True)
    (workspace / "README.md").write_text(
        "# Topic\n\nCanonical Research Harness topic: `topic` (topic id: 42).\n",
        encoding="utf-8",
    )

    assert discover_topic_id_from_workspace(nested) == 42


def test_discover_topic_id_from_workspace_returns_none_without_marker(
    tmp_path: Path,
) -> None:
    from research_harness.topic_workspace import discover_topic_id_from_workspace

    workspace = tmp_path / "rh-workspace" / "topic"
    workspace.mkdir(parents=True)
    (workspace / "README.md").write_text("# Topic\n", encoding="utf-8")

    assert discover_topic_id_from_workspace(workspace) is None


def test_discover_topic_id_from_workspace_requires_rh_workspace_root(
    tmp_path: Path,
) -> None:
    from research_harness.topic_workspace import discover_topic_id_from_workspace

    project = tmp_path / "ordinary-project"
    nested = project / "notes"
    nested.mkdir(parents=True)
    (project / "README.md").write_text(
        "# Project\n\nHistorical note: topic id: 99.\n",
        encoding="utf-8",
    )

    assert discover_topic_id_from_workspace(nested) is None
