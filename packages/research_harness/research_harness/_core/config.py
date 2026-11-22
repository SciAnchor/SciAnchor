"""Core runtime config resolution for research-harness."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


GLOBAL_DB_PATH = Path.home() / ".research-harness" / "pool.db"
CONFIG_DIRNAME = ".research-harness"
CONFIG_FILENAME = "config.json"
DEFAULT_BACKEND = "local"


@dataclass
class RuntimeConfig:
    db_path: Path
    source: str
    workspace_root: Path | None = None
    research_workspace_root: Path | None = None
    config_path: Path | None = None
    execution_backend: str = DEFAULT_BACKEND


def find_workspace_root(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "packages" / "research_harness" / "pyproject.toml").exists():
            return candidate
    return None


def default_project_db_path(workspace_root: Path) -> Path:
    return workspace_root / CONFIG_DIRNAME / "pool.db"


def _resolve_execution_backend(
    explicit_backend: str | None,
    config_data: dict[str, object] | None = None,
) -> str:
    if explicit_backend:
        return explicit_backend
    env_backend = os.environ.get("RESEARCH_HARNESS_BACKEND") or os.environ.get(
        "RESEARCH_HUB_BACKEND"
    )
    if env_backend:
        return env_backend
    if config_data:
        configured = config_data.get("execution_backend")
        if isinstance(configured, str) and configured:
            return configured
    return DEFAULT_BACKEND


def _env_flag_enabled(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _resolve_research_workspace_root(
    config_data: dict[str, object] | None,
    workspace_root: Path | None,
) -> Path | None:
    if _env_flag_enabled("RESEARCH_HARNESS_DISABLE_WORKSPACE_MATERIALIZATION"):
        return None

    explicit = os.environ.get("RESEARCH_HARNESS_WORKSPACE_ROOT") or os.environ.get(
        "RH_WORKSPACE_ROOT"
    )
    if explicit:
        return Path(explicit).expanduser().resolve()

    if config_data:
        configured = config_data.get("research_workspace_root")
        if isinstance(configured, str) and configured.strip():
            candidate = Path(configured).expanduser()
            if not candidate.is_absolute() and workspace_root is not None:
                candidate = workspace_root / candidate
            return candidate.resolve()

    default = Path.home() / "code" / "rh-workspace"
    if default.exists():
        return default.resolve()
    return None


def load_runtime_config(
    explicit_db_path: str | Path | None = None,
    explicit_backend: str | None = None,
    cwd: Path | None = None,
) -> RuntimeConfig:
    workspace_root = find_workspace_root(cwd)
    config_path = (
        workspace_root / CONFIG_DIRNAME / CONFIG_FILENAME if workspace_root else None
    )

    config_data: dict[str, object] | None = None
    if config_path and config_path.exists():
        config_data = json.loads(config_path.read_text())

    execution_backend = _resolve_execution_backend(explicit_backend, config_data)
    research_workspace_root = _resolve_research_workspace_root(
        config_data, workspace_root
    )

    if explicit_db_path:
        return RuntimeConfig(
            db_path=Path(explicit_db_path).expanduser().resolve(),
            source="explicit",
            workspace_root=workspace_root,
            research_workspace_root=research_workspace_root,
            config_path=config_path,
            execution_backend=execution_backend,
        )

    env_db_path = os.environ.get("RESEARCH_HARNESS_DB_PATH") or os.environ.get(
        "RESEARCH_HUB_DB_PATH"
    )
    if env_db_path:
        return RuntimeConfig(
            db_path=Path(env_db_path).expanduser().resolve(),
            source="env",
            workspace_root=workspace_root,
            research_workspace_root=research_workspace_root,
            config_path=config_path,
            execution_backend=execution_backend,
        )

    if workspace_root:
        if config_data:
            configured = config_data.get("db_path")
            if configured:
                candidate = Path(str(configured))
                if not candidate.is_absolute():
                    candidate = workspace_root / candidate
                return RuntimeConfig(
                    db_path=candidate.resolve(),
                    source="project-config",
                    workspace_root=workspace_root,
                    research_workspace_root=research_workspace_root,
                    config_path=config_path,
                    execution_backend=execution_backend,
                )
        return RuntimeConfig(
            db_path=default_project_db_path(workspace_root).resolve(),
            source="project-default",
            workspace_root=workspace_root,
            research_workspace_root=research_workspace_root,
            config_path=config_path,
            execution_backend=execution_backend,
        )

    return RuntimeConfig(
        db_path=GLOBAL_DB_PATH,
        source="global-default",
        workspace_root=None,
        research_workspace_root=research_workspace_root,
        config_path=None,
        execution_backend=execution_backend,
    )


def state_dir_for_db_path(db_path: Path | str | None) -> Path | None:
    """Return the state dir owning ``db_path`` when it uses the standard layout.

    A DB participates in a state tree only when it lives directly inside a
    ``.research-harness`` directory; ad-hoc DB locations return ``None`` so
    callers fall back to workspace-based resolution.
    """
    if db_path is None:
        return None
    parent = Path(db_path).expanduser().parent
    if parent.name == CONFIG_DIRNAME:
        return parent
    return None


def default_state_dir(
    db_path: Path | str | None = None,
    cwd: Path | None = None,
) -> Path:
    """Resolve the auto-runner state dir, keeping it adjacent to the effective DB.

    Preference order: the tree owning ``db_path`` (when it uses the standard
    ``.research-harness`` layout) > the tree owning the resolved runtime DB >
    ``<workspace_root>/.research-harness`` > ``~/.research-harness``. This keeps
    checkpoints next to the database even when the DB comes from ``--db``/env
    overrides, closing the checkpoint/DB split-brain path.
    """
    tree = state_dir_for_db_path(db_path)
    if tree is not None:
        return tree
    tree = state_dir_for_db_path(load_runtime_config(cwd=cwd).db_path)
    if tree is not None:
        return tree
    workspace_root = find_workspace_root(cwd)
    if workspace_root is not None:
        return workspace_root / CONFIG_DIRNAME
    return Path.home() / CONFIG_DIRNAME


def state_path(
    *parts: str, db_path: Path | str | None = None, cwd: Path | None = None
) -> Path:
    """A path inside this process's state tree. Use instead of ``Path(".research-harness")/x``.

    A module-level relative literal resolves against the *current working directory*. On a
    development machine the cwd is always the checkout, so it coincides with the real state
    tree and nothing looks wrong; anywhere else it is whatever directory the caller happened to
    be in, and the write lands in a stray `.research-harness` beside the caller while the real
    tree never sees it. `rh paper acquire` had never run on a multi-tenant host for exactly
    this reason -- it died on `PermissionError: '.research-harness'` in a home the service
    account could traverse but not write.

    ``default_state_dir`` already resolves this correctly and keeps the state adjacent to the
    effective database. This is that resolution with the join attached, so there is one way to
    spell it rather than five.
    """
    return default_state_dir(db_path=db_path, cwd=cwd).joinpath(*parts)


def detect_state_trees(
    runtime_config: RuntimeConfig | None = None,
    cwd: Path | None = None,
) -> list[dict[str, object]]:
    """Read-only scan of candidate ``.research-harness`` state trees.

    Never creates directories or opens databases; safe to call from
    diagnostics. ``is_resolved`` marks the tree owning the currently resolved
    DB path (when that DB uses the standard layout).
    """
    config = runtime_config or load_runtime_config(cwd=cwd)
    candidates: list[Path] = []
    if config.workspace_root is not None:
        candidates.append(config.workspace_root / CONFIG_DIRNAME)
    candidates.append(Path.home() / CONFIG_DIRNAME)
    if config.research_workspace_root is not None:
        candidates.append(config.research_workspace_root / CONFIG_DIRNAME)
    resolved_tree = state_dir_for_db_path(config.db_path)
    if resolved_tree is not None:
        candidates.append(resolved_tree)

    normalized_resolved: Path | None = None
    if resolved_tree is not None:
        normalized_resolved = resolved_tree.expanduser().resolve()

    trees: list[dict[str, object]] = []
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            normalized = candidate.expanduser().resolve()
        except OSError:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        pool_db = normalized / "pool.db"
        try:
            pool_db_bytes = pool_db.stat().st_size if pool_db.exists() else 0
        except OSError:
            pool_db_bytes = 0
        checkpoints_dir = normalized / "auto_runner" / "checkpoints"
        checkpoint_count = (
            len(list(checkpoints_dir.glob("topic_*.json")))
            if checkpoints_dir.is_dir()
            else 0
        )
        trees.append(
            {
                "path": str(normalized),
                "exists": normalized.is_dir(),
                "pool_db_exists": pool_db.exists(),
                "pool_db_bytes": pool_db_bytes,
                "checkpoint_count": checkpoint_count,
                "is_resolved": normalized_resolved is not None
                and normalized == normalized_resolved,
            }
        )
    return trees


def init_project_config(
    workspace_root: Path,
    db_path: str | Path | None = None,
    execution_backend: str = DEFAULT_BACKEND,
    research_workspace_root: str | Path | None = None,
) -> Path:
    config_dir = workspace_root / CONFIG_DIRNAME
    config_dir.mkdir(parents=True, exist_ok=True)
    target = Path(db_path) if db_path else Path(CONFIG_DIRNAME) / "pool.db"
    payload = {
        "db_path": str(target),
        "execution_backend": execution_backend,
    }
    if research_workspace_root:
        payload["research_workspace_root"] = str(Path(research_workspace_root))
    config_path = config_dir / CONFIG_FILENAME
    config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    return config_path
