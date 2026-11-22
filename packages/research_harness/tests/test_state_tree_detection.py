"""Tests for state-tree detection and DB-adjacent state-dir resolution."""

from __future__ import annotations

from pathlib import Path

from research_harness._core.config import (
    RuntimeConfig,
    default_state_dir,
    detect_state_trees,
    state_dir_for_db_path,
)


def _fake_checkout(root: Path) -> Path:
    marker = root / "packages" / "research_harness"
    marker.mkdir(parents=True, exist_ok=True)
    (marker / "pyproject.toml").write_text("[project]\nname='research_harness'\n")
    return root


def test_state_dir_for_db_path_standard_layout(tmp_path: Path) -> None:
    db = tmp_path / ".research-harness" / "pool.db"
    assert state_dir_for_db_path(db) == db.parent
    assert state_dir_for_db_path(str(db)) == db.parent


def test_state_dir_for_db_path_rejects_ad_hoc_locations(tmp_path: Path) -> None:
    assert state_dir_for_db_path(tmp_path / "pool.db") is None
    assert state_dir_for_db_path(None) is None


def test_default_state_dir_prefers_db_adjacent_tree(tmp_path: Path) -> None:
    db = tmp_path / "elsewhere" / ".research-harness" / "pool.db"
    assert default_state_dir(db) == db.parent


def test_default_state_dir_follows_env_db(tmp_path: Path, monkeypatch) -> None:
    checkout = _fake_checkout(tmp_path / "checkout")
    env_tree = tmp_path / "custom" / ".research-harness"
    monkeypatch.setenv("RESEARCH_HARNESS_DB_PATH", str(env_tree / "pool.db"))
    monkeypatch.delenv("RESEARCH_HUB_DB_PATH", raising=False)

    result = default_state_dir(None, cwd=checkout)

    assert result.resolve() == (env_tree / "pool.db").expanduser().resolve().parent


def test_default_state_dir_defaults_to_workspace_tree(
    tmp_path: Path, monkeypatch
) -> None:
    checkout = _fake_checkout(tmp_path / "checkout")
    monkeypatch.delenv("RESEARCH_HARNESS_DB_PATH", raising=False)
    monkeypatch.delenv("RESEARCH_HUB_DB_PATH", raising=False)

    result = default_state_dir(None, cwd=checkout)

    assert result.resolve() == (checkout / ".research-harness").resolve()


def test_detect_state_trees_reports_sizes_and_resolution(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    home_tree = home / ".research-harness"
    home_tree.mkdir(parents=True)
    (home_tree / "pool.db").write_bytes(b"x" * 10)
    monkeypatch.setattr(Path, "home", lambda: home)

    checkout = _fake_checkout(tmp_path / "checkout")
    ws_tree = checkout / ".research-harness"
    (ws_tree / "auto_runner" / "checkpoints").mkdir(parents=True)
    (ws_tree / "pool.db").write_bytes(b"y" * 20)
    (ws_tree / "auto_runner" / "checkpoints" / "topic_1.json").write_text("{}")

    config = RuntimeConfig(
        db_path=ws_tree / "pool.db",
        source="project-default",
        workspace_root=checkout,
    )
    trees = detect_state_trees(config)
    by_path = {tree["path"]: tree for tree in trees}

    ws_entry = by_path[str(ws_tree.resolve())]
    assert ws_entry["pool_db_exists"] is True
    assert ws_entry["pool_db_bytes"] == 20
    assert ws_entry["checkpoint_count"] == 1
    assert ws_entry["is_resolved"] is True

    home_entry = by_path[str(home_tree.resolve())]
    assert home_entry["pool_db_bytes"] == 10
    assert home_entry["is_resolved"] is False

    nonempty = [tree for tree in trees if tree["pool_db_bytes"] > 0]
    assert len(nonempty) == 2


def test_detect_state_trees_is_read_only(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    checkout = _fake_checkout(tmp_path / "checkout")

    config = RuntimeConfig(
        db_path=checkout / ".research-harness" / "pool.db",
        source="project-default",
        workspace_root=checkout,
        research_workspace_root=tmp_path / "rh-workspace",
    )
    detect_state_trees(config)

    assert not (checkout / ".research-harness").exists()
    assert not (home / ".research-harness").exists()
    assert not (tmp_path / "rh-workspace" / ".research-harness").exists()
