from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any


def test_topic_workspace_helper_preserves_http_api_wrapper(
    monkeypatch,
    tmp_path: Path,
):
    from research_harness_mcp import http_api, topic_workspace_http

    calls: list[dict[str, Any]] = []

    def fake_materialize_topic_workspace_http(**kwargs: Any) -> str:
        calls.append(kwargs)
        return "/tmp/topic-7"

    monkeypatch.setattr(http_api, "DB_PATH", tmp_path / "pool.db")
    monkeypatch.setattr(
        topic_workspace_http,
        "materialize_topic_workspace_http",
        fake_materialize_topic_workspace_http,
    )

    assert (
        http_api._materialize_topic_workspace_http(
            topic_id=7,
            topic_name="Human-AI Topic",
            description="Study handoff quality",
            target_venue="ICLR",
            deadline="2026-07-01",
            domain_name="Agents",
        )
        == "/tmp/topic-7"
    )
    assert calls == [
        {
            "db_path": tmp_path / "pool.db",
            "topic_id": 7,
            "topic_name": "Human-AI Topic",
            "description": "Study handoff quality",
            "target_venue": "ICLR",
            "deadline": "2026-07-01",
            "domain_name": "Agents",
        }
    ]


def test_materialize_topic_workspace_http_passes_runtime_config_and_domain(
    tmp_path: Path,
):
    from research_harness_mcp import topic_workspace_http

    db_path = tmp_path / "pool.db"
    workspace_root = tmp_path / "workspaces"
    workspace_path = workspace_root / "topic-7"
    calls: dict[str, Any] = {}

    def fake_load_runtime_config(*, explicit_db_path: Path):
        calls["explicit_db_path"] = explicit_db_path
        return SimpleNamespace(research_workspace_root=workspace_root)

    def fake_materialize_topic_workspace(**kwargs: Any):
        calls["workspace_kwargs"] = kwargs
        return SimpleNamespace(workspace_path=workspace_path)

    assert topic_workspace_http.materialize_topic_workspace_http(
        db_path=db_path,
        topic_id=7,
        topic_name="Human-AI Topic",
        description="Study handoff quality",
        target_venue="ICLR",
        deadline="2026-07-01",
        domain_name="Agents",
        load_runtime_config_fn=fake_load_runtime_config,
        materialize_topic_workspace_fn=fake_materialize_topic_workspace,
    ) == str(workspace_path)
    assert calls == {
        "explicit_db_path": db_path,
        "workspace_kwargs": {
            "workspace_root": workspace_root,
            "topic_id": 7,
            "topic_name": "Human-AI Topic",
            "description": "Study handoff quality",
            "target_venue": "ICLR",
            "deadline": "2026-07-01",
            "db_path": db_path,
            "workspace_domain": "Agents",
        },
    }


def test_materialize_topic_workspace_http_preserves_none_result(tmp_path: Path):
    from research_harness_mcp import topic_workspace_http

    assert (
        topic_workspace_http.materialize_topic_workspace_http(
            db_path=tmp_path / "pool.db",
            topic_id=8,
            topic_name="No Workspace",
            load_runtime_config_fn=lambda *, explicit_db_path: SimpleNamespace(
                research_workspace_root=tmp_path
            ),
            materialize_topic_workspace_fn=lambda **_kwargs: None,
        )
        is None
    )
