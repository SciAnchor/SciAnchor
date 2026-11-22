"""Compatibility shim for core runtime config resolution."""

from __future__ import annotations

from research_harness._core.config import (
    CONFIG_DIRNAME,
    CONFIG_FILENAME,
    DEFAULT_BACKEND,
    GLOBAL_DB_PATH,
    RuntimeConfig,
    default_project_db_path,
    default_state_dir,
    detect_state_trees,
    find_workspace_root,
    init_project_config,
    load_runtime_config,
    state_dir_for_db_path,
    state_path,
)

__all__ = [
    "CONFIG_DIRNAME",
    "CONFIG_FILENAME",
    "DEFAULT_BACKEND",
    "GLOBAL_DB_PATH",
    "RuntimeConfig",
    "default_project_db_path",
    "default_state_dir",
    "detect_state_trees",
    "find_workspace_root",
    "init_project_config",
    "load_runtime_config",
    "state_dir_for_db_path",
    "state_path",
]
