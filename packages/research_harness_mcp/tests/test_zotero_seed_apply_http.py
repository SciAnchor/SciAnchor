"""Focused HTTP tests for Zotero seed-paper apply route extraction."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field


class _ZoteroSeedPaperApplyRequest(BaseModel):
    query: str = Field(min_length=1)
    topic_id: int | None = None
    topic_name: str = ""
    topic_description: str = ""
    candidate_sources: list[str] = Field(default_factory=list)
    target_collection_key: str = ""
    parent_collection_key: str = ""
    target_collection_name: str = ""
    target_collection_path: str = ""
    library_id: str | int | None = None
    library_type: Literal["user", "group"] = "user"
    request_deep_read: bool = False
    request_pdf_attachment: bool = False
    request_pdf_annotations: bool = False
    target_is_topic_collection: bool = False
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
                "planned_count": len(kwargs["paper_ids"]),
                "synced_count": 0 if kwargs["dry_run"] else len(kwargs["paper_ids"]),
                "dry_run": kwargs["dry_run"],
                "topic_collection_key": "TOPICCOLL",
                "records": [
                    {"paper_id": paper_id, "title": f"Paper {paper_id}"}
                    for paper_id in kwargs["paper_ids"]
                ],
            }
        )


def test_zotero_seed_apply_module_imports_and_route_order_is_preserved():
    from research_harness_mcp import http_api, zotero_seed_apply_http

    assert callable(zotero_seed_apply_http.register_zotero_seed_apply_routes)

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


def _build_zotero_seed_apply_client(
    db_path: Path,
    *,
    token_required: bool = False,
    existing_sources: dict[str, int] | None = None,
    ingest_error_sources: set[str] | None = None,
) -> tuple[TestClient, dict[str, Any]]:
    from research_harness_mcp import zotero_seed_apply_http

    calls: dict[str, Any] = {
        "token_paths": [],
        "topics": [],
        "api_factory": [],
        "find_existing": [],
        "ingest": [],
        "deep_read": [],
        "tool": [],
        "annotations": [],
        "library_ids": [],
        "client_calls": [],
        "services": [],
        "push_calls": [],
        "receipts": [],
    }
    existing_sources = dict(existing_sources or {})
    ingest_error_sources = set(ingest_error_sources or set())

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

    def get_or_create_topic(**kwargs: Any) -> tuple[int, bool]:
        calls["topics"].append(kwargs)
        topic_id = kwargs["topic_id"] or 42
        return int(topic_id), kwargs["topic_id"] is None

    def find_existing(
        _conn: sqlite3.Connection, topic_id: int, source: str
    ) -> int | None:
        calls["find_existing"].append({"topic_id": topic_id, "source": source})
        return existing_sources.get(source)

    def ingest_paper(api: Any, *, source: str, topic_id: int, relevance: str) -> dict:
        calls["ingest"].append(
            {
                "api": api,
                "source": source,
                "topic_id": topic_id,
                "relevance": relevance,
            }
        )
        if source in ingest_error_sources:
            raise RuntimeError(f"ingest failed for {source}")
        return {"paper_id": 11 if source == "new-source" else 12}

    def deep_read_paper(api: Any, *, paper_id: int, topic_id: int, focus: str) -> dict:
        calls["deep_read"].append(
            {"api": api, "paper_id": paper_id, "topic_id": topic_id, "focus": focus}
        )
        return {"paper_id": paper_id, "status": "deep_read"}

    def run_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        calls["tool"].append({"name": name, "arguments": dict(arguments)})
        return {"status": "ok"}

    def apply_annotations(**kwargs: Any) -> list[dict[str, Any]]:
        calls["annotations"].append(kwargs)
        return [
            {
                "paper_id": kwargs["paper_ids"][0],
                "profile": "zotero-content-primitives-v2",
                "planned_count": 2,
                "applied_count": 2,
                "verified_count": 2,
                "missing_count": 0,
            }
        ]

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
            "paper_count": len(kwargs["push_result"].to_dict()["records"])
            if kwargs["push_result"] is not None
            else 0,
            "ingest_errors": kwargs["ingest_errors"],
            "postprocess_errors": kwargs["postprocess_errors"],
            "pdf_annotation_receipts": kwargs["pdf_annotation_receipts"],
        }

    app = FastAPI()
    zotero_seed_apply_http.register_zotero_seed_apply_routes(
        app,
        zotero_seed_paper_apply_request_model=_ZoteroSeedPaperApplyRequest,
        require_zotero_chat_token=require_token,
        get_db_context=get_db_context,
        db_path_provider=lambda: db_path,
        last_zotero_path_segment=lambda path: str(path).split("/")[-1].strip(),
        get_or_create_zotero_seed_topic=get_or_create_topic,
        research_api_factory=lambda: calls["api_factory"].append("api") or "api",
        find_paper_id_in_topic_by_source=find_existing,
        ingest_paper_impl=ingest_paper,
        deep_read_paper_impl=deep_read_paper,
        run_tool=run_tool,
        apply_rh_pdf_annotations_for_papers=apply_annotations,
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


def test_zotero_seed_apply_preserves_dry_run_response_and_skips_client(
    tmp_path: Path,
):
    db_path = tmp_path / "zotero-seed-apply.db"
    db_path.touch()
    client, calls = _build_zotero_seed_apply_client(
        db_path,
        existing_sources={"existing-source": 7},
    )

    response = client.post(
        "/api/zotero/seed-papers/apply",
        json={
            "query": "bootstrap query",
            "candidate_sources": ["existing-source", "new-source"],
            "target_collection_key": "CURRDIR1",
            "target_collection_path": "Research Harness / Topic From Path",
            "library_id": "1",
            "library_type": "user",
            "request_deep_read": True,
            "request_pdf_annotations": True,
            "dry_run": True,
        },
    )

    assert response.status_code == 200, response.text
    assert calls["token_paths"] == ["/api/zotero/seed-papers/apply"]
    assert calls["client_calls"] == []
    assert calls["tool"] == []
    assert calls["deep_read"] == []
    assert calls["annotations"] == []
    assert calls["topics"][0]["topic_name"] == "Topic From Path"
    assert "Initial query: bootstrap query" in calls["topics"][0]["description"]
    assert calls["library_ids"] == [("1", "user")]
    assert calls["ingest"] == [
        {
            "api": "api",
            "source": "new-source",
            "topic_id": 42,
            "relevance": "high",
        }
    ]
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
            "Topic From Path",
            {
                "topic_collection_name": "Topic From Path",
                "target_collection_key": None,
                "parent_collection_key": "CURRDIR1",
                "include_notes": True,
                "dry_run": True,
                "paper_ids": [7, 11],
            },
        )
    ]
    assert response.json() == {
        "status": "success",
        "summary": "Seed papers applied to topic 42",
        "output": {
            "topic_id": 42,
            "topic_name": "Topic From Path",
            "created_topic": True,
            "query": "bootstrap query",
            "paper_ids": [7, 11],
            "ingested_count": 2,
            "ingest_errors": [],
            "postprocess_errors": [],
            "pdf_annotation_receipts": [],
            "push": {
                "planned_count": 2,
                "synced_count": 0,
                "dry_run": True,
                "topic_collection_key": "TOPICCOLL",
                "records": [
                    {"paper_id": 7, "title": "Paper 7"},
                    {"paper_id": 11, "title": "Paper 11"},
                ],
            },
            "workflow_receipt": {
                "schema": "rh-zotero-workflow-receipt/v1",
                "action_type": "zotero_seed_paper_search",
                "topic_id": 42,
                "topic_name": "Topic From Path",
                "paper_count": 2,
                "ingest_errors": [],
                "postprocess_errors": [],
                "pdf_annotation_receipts": [],
            },
        },
    }


def test_zotero_seed_apply_preserves_validation_and_token_gate(tmp_path: Path):
    db_path = tmp_path / "zotero-seed-apply-validation.db"
    db_path.touch()
    client, calls = _build_zotero_seed_apply_client(db_path, token_required=True)
    valid_body = {
        "query": "query",
        "candidate_sources": ["new-source"],
        "target_collection_key": "CURRDIR1",
        "dry_run": True,
    }

    blocked = client.post("/api/zotero/seed-papers/apply", json=valid_body)
    allowed = client.post(
        "/api/zotero/seed-papers/apply",
        headers={"X-RH-Zotero-Token": "secret"},
        json=valid_body,
    )
    missing_sources = client.post(
        "/api/zotero/seed-papers/apply",
        headers={"X-RH-Zotero-Token": "secret"},
        json={"query": "query", "target_collection_key": "CURRDIR1"},
    )
    missing_collection = client.post(
        "/api/zotero/seed-papers/apply",
        headers={"X-RH-Zotero-Token": "secret"},
        json={"query": "query", "candidate_sources": ["new-source"]},
    )

    assert blocked.status_code == 401
    assert allowed.status_code == 200, allowed.text
    assert missing_sources.status_code == 400
    assert missing_sources.json() == {"detail": "candidate_sources is required"}
    assert missing_collection.status_code == 400
    assert missing_collection.json() == {"detail": "target_collection_key is required"}
    assert calls["token_paths"] == [
        "/api/zotero/seed-papers/apply",
        "/api/zotero/seed-papers/apply",
        "/api/zotero/seed-papers/apply",
        "/api/zotero/seed-papers/apply",
    ]


def test_zotero_seed_apply_rejects_non_dry_run_before_client(tmp_path: Path):
    db_path = tmp_path / "zotero-seed-apply-postprocess.db"
    db_path.touch()
    client, calls = _build_zotero_seed_apply_client(db_path)

    response = client.post(
        "/api/zotero/seed-papers/apply",
        json={
            "query": "query",
            "topic_id": 5,
            "topic_name": "Existing Topic",
            "candidate_sources": ["new-source"],
            "target_collection_key": "CURRDIR1",
            "parent_collection_key": "PARENT1",
            "target_is_topic_collection": True,
            "request_deep_read": True,
            "request_pdf_attachment": True,
            "request_pdf_annotations": True,
            "dry_run": False,
        },
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
    assert calls["tool"] == []
    assert calls["deep_read"] == []
    assert calls["annotations"] == []
    assert calls["push_calls"] == []


def test_zotero_seed_apply_preserves_ingest_errors(tmp_path: Path):
    db_path = tmp_path / "zotero-seed-apply-ingest-error.db"
    db_path.touch()
    client, calls = _build_zotero_seed_apply_client(
        db_path,
        ingest_error_sources={"bad-source"},
    )

    response = client.post(
        "/api/zotero/seed-papers/apply",
        json={
            "query": "query",
            "candidate_sources": ["bad-source"],
            "target_collection_key": "CURRDIR1",
            "dry_run": True,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()["output"]
    assert payload["paper_ids"] == []
    assert payload["push"] is None
    assert payload["ingest_errors"] == [
        {"source": "bad-source", "error": "ingest failed for bad-source"}
    ]
    assert calls["services"] == []
    assert calls["receipts"][0]["push_result"] is None
    assert calls["receipts"][0]["dry_run"] is True
