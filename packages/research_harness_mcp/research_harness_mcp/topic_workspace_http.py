"""Private HTTP adapter helpers for topic workspace materialization."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from research_harness.config import load_runtime_config
from research_harness.topic_workspace import materialize_topic_workspace


def materialize_topic_workspace_http(
    *,
    db_path: Path,
    topic_id: int,
    topic_name: str,
    description: str = "",
    target_venue: str = "",
    deadline: str = "",
    domain_name: str | None = None,
    load_runtime_config_fn: Callable[..., Any] = load_runtime_config,
    materialize_topic_workspace_fn: Callable[..., Any] = materialize_topic_workspace,
) -> str | None:
    runtime_config = load_runtime_config_fn(explicit_db_path=db_path)
    result = materialize_topic_workspace_fn(
        workspace_root=runtime_config.research_workspace_root,
        topic_id=topic_id,
        topic_name=topic_name,
        description=description,
        target_venue=target_venue,
        deadline=deadline,
        db_path=db_path,
        workspace_domain=domain_name,
    )
    return str(result.workspace_path) if result is not None else None
