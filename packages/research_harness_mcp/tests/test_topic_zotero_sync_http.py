"""Focused HTTP tests for topic Zotero sync route extraction."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field


class _ZoteroSyncRequest(BaseModel):
    direction: Literal["push", "pull", "both"] = "push"
    root_collection: str = "Research Harness"
    topic_collection_name: str | None = None
    target_collection_key: str | None = None
    parent_collection_key: str | None = None
    target_collection_name: str | None = None
    target_collection_path: str | None = None
    library_id: str | int | None = None
    library_type: Literal["user", "group"] = "user"
    api_key: str | None = None
    api_base: str | None = None
    limit: int | None = Field(default=None, ge=1)
    paper_ids: list[int] = Field(default_factory=list)
    skip_notes: bool = False
    force: bool = False
    include_rh_generated: bool = False
    dry_run: bool = True


class _SyncResult:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def to_dict(self) -> dict[str, Any]:
        return self._payload


class _SyncService:
    def __init__(self, calls: dict[str, Any], **kwargs: Any) -> None:
        self._calls = calls
        calls["services"].append(kwargs)

    def sync_topic(self, topic_name: str, **kwargs: Any) -> _SyncResult:
        self._calls["push_calls"].append((topic_name, kwargs))
        return _SyncResult(
            {
                "planned_count": 1,
                "synced_count": 0,
                "dry_run": kwargs["dry_run"],
                "records": [{"title": "Agentic Zotero", "deep_read": True}],
            }
        )

    def pull_topic(self, topic_name: str, **kwargs: Any) -> _SyncResult:
        self._calls["pull_calls"].append((topic_name, kwargs))
        return _SyncResult({"pulled_count": 1, "topic": topic_name})


def test_topic_zotero_sync_module_imports_and_route_order_is_preserved():
    from research_harness_mcp import http_api, topic_zotero_sync_http

    assert callable(topic_zotero_sync_http.register_topic_zotero_sync_routes)

    def route_index(path: str, method: str) -> int:
        for index, route in enumerate(http_api.app.routes):
            if route.path == path and method in route.methods:
                return index
        raise AssertionError(f"route not registered: {method} {path}")

    assert (
        route_index("/api/topics/{topic_id}/zotero-sync", "POST")
        < route_index("/api/zotero/seed-papers/apply", "POST")
        < route_index("/api/zotero/chat", "POST")
    )


def _seed_topic(db_path: Path, *, topic_id: int = 1) -> None:
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("CREATE TABLE topics (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute(
            "INSERT INTO topics (id, name) VALUES (?, ?)", (topic_id, "demo-topic")
        )
        conn.commit()


def _build_topic_zotero_sync_client(
    db_path: Path,
    *,
    token_required: bool = False,
) -> tuple[TestClient, dict[str, Any]]:
    from research_harness_mcp import topic_zotero_sync_http

    calls: dict[str, Any] = {
        "token_paths": [],
        "library_ids": [],
        "client_calls": [],
        "services": [],
        "push_calls": [],
        "pull_calls": [],
        "receipts": [],
    }

    @contextmanager
    def get_db_context():
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def require_token(request: Request) -> None:
        calls["token_paths"].append(request.url.path)
        if token_required and request.headers.get("X-RH-Zotero-Token") != "secret":
            raise HTTPException(status_code=401, detail="Unauthorized")

    def zotero_api_library_id(value: str | int | None, library_type: str) -> str:
        calls["library_ids"].append((value, library_type))
        return "library-web"

    def create_zotero_write_client(**kwargs: Any) -> tuple[str, str]:
        calls["client_calls"].append(kwargs)
        return "zotero-client", "library-client"

    def build_workflow_receipt(**kwargs: Any) -> dict[str, Any]:
        calls["receipts"].append(kwargs)
        return {
            "schema": "rh-zotero-workflow-receipt/v1",
            "action_type": kwargs["action_type"],
            "topic_id": kwargs["topic_id"],
            "topic_name": kwargs["topic_name"],
            "include_notes": kwargs["include_notes"],
        }

    app = FastAPI()
    topic_zotero_sync_http.register_topic_zotero_sync_routes(
        app,
        zotero_sync_request_model=_ZoteroSyncRequest,
        require_zotero_chat_token=require_token,
        get_db_context=get_db_context,
        db_path_provider=lambda: db_path,
        zotero_api_library_id=zotero_api_library_id,
        create_zotero_write_client=create_zotero_write_client,
        build_zotero_workflow_receipt=build_workflow_receipt,
        zotero_sync_service_factory=lambda **kwargs: _SyncService(calls, **kwargs),
        env_get=lambda key, default="": {
            "ZOTERO_LIBRARY_TYPE": "user",
            "ZOTERO_API_KEY": "",
            "ZOTERO_API_BASE": "",
        }.get(key, default),
    )
    return TestClient(app), calls


def test_topic_zotero_sync_preserves_push_dry_run_response_shape(tmp_path: Path):
    db_path = tmp_path / "topic-zotero-sync.db"
    _seed_topic(db_path)
    client, calls = _build_topic_zotero_sync_client(db_path)

    response = client.post(
        "/api/topics/1/zotero-sync",
        json={
            "direction": "push",
            "dry_run": True,
            "limit": 1,
            "target_collection_name": "Target",
            "topic_collection_name": "Topic Collection",
            "skip_notes": True,
        },
    )

    assert response.status_code == 200, response.text
    assert calls["token_paths"] == ["/api/topics/1/zotero-sync"]
    assert calls["library_ids"] == [(None, "user")]
    assert calls["client_calls"] == []
    assert calls["services"] == [
        {
            "db_path": db_path,
            "client": None,
            "library_id": "library-web",
            "library_type": "user",
        }
    ]
    assert calls["push_calls"] == [
        (
            "demo-topic",
            {
                "root_collection": "Research Harness",
                "topic_collection_name": "Topic Collection",
                "target_collection_key": None,
                "parent_collection_key": None,
                "include_notes": False,
                "dry_run": True,
                "limit": 1,
                "force": False,
                "paper_ids": [],
            },
        )
    ]
    assert response.json() == {
        "status": "success",
        "summary": "Zotero push sync completed for topic 1",
        "output": {
            "topic_id": 1,
            "topic": "demo-topic",
            "direction": "push",
            "dry_run": True,
            "push": {
                "planned_count": 1,
                "synced_count": 0,
                "dry_run": True,
                "records": [{"title": "Agentic Zotero", "deep_read": True}],
            },
            "pull": None,
            "workflow_receipt": {
                "schema": "rh-zotero-workflow-receipt/v1",
                "action_type": "sync_rh_papers_to_collection",
                "topic_id": 1,
                "topic_name": "demo-topic",
                "include_notes": False,
            },
        },
    }


def test_topic_zotero_sync_preserves_missing_topic_404(tmp_path: Path):
    db_path = tmp_path / "topic-zotero-sync-missing.db"
    _seed_topic(db_path)
    client, calls = _build_topic_zotero_sync_client(db_path)

    response = client.post(
        "/api/topics/999/zotero-sync",
        json={"direction": "push", "dry_run": True},
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Topic not found"}
    assert calls["services"] == []
    assert calls["client_calls"] == []


def test_topic_zotero_sync_preserves_token_gate(tmp_path: Path):
    db_path = tmp_path / "topic-zotero-sync-token.db"
    _seed_topic(db_path)
    client, calls = _build_topic_zotero_sync_client(db_path, token_required=True)

    blocked = client.post(
        "/api/topics/1/zotero-sync",
        json={"direction": "push", "dry_run": True},
    )
    allowed = client.post(
        "/api/topics/1/zotero-sync",
        headers={"X-RH-Zotero-Token": "secret"},
        json={"direction": "push", "dry_run": True},
    )

    assert blocked.status_code == 401
    assert allowed.status_code == 200, allowed.text
    assert calls["token_paths"] == [
        "/api/topics/1/zotero-sync",
        "/api/topics/1/zotero-sync",
    ]
    assert len(calls["services"]) == 1


def test_topic_zotero_sync_pull_and_both_dry_run_defer_before_client(
    tmp_path: Path,
):
    db_path = tmp_path / "topic-zotero-sync-deferred.db"
    _seed_topic(db_path)
    client, calls = _build_topic_zotero_sync_client(db_path)

    for direction in ("pull", "both"):
        response = client.post(
            "/api/topics/1/zotero-sync",
            json={"direction": direction, "dry_run": True},
        )

        assert response.status_code == 400
        assert response.json() == {
            "detail": (
                "stable Zotero dry-run only supports direction=push; "
                f"{direction} dry-run requires Zotero read access and remains deferred"
            )
        }

    assert calls["client_calls"] == []
    assert calls["services"] == []
    assert calls["push_calls"] == []
    assert calls["pull_calls"] == []


def test_topic_zotero_sync_non_dry_run_defers_before_client(tmp_path: Path):
    db_path = tmp_path / "topic-zotero-sync-real-deferred.db"
    _seed_topic(db_path)
    client, calls = _build_topic_zotero_sync_client(db_path)

    for direction in ("push", "pull", "both"):
        response = client.post(
            "/api/topics/1/zotero-sync",
            json={"direction": direction, "dry_run": False},
        )

        assert response.status_code == 400
        assert response.json() == {
            "detail": (
                "real Zotero sync/apply is deferred; stable Zotero routing only "
                "supports direction=push with dry_run=true"
            )
        }

    assert calls["client_calls"] == []
    assert calls["services"] == []
    assert calls["push_calls"] == []
    assert calls["pull_calls"] == []
