from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient


PENDING_PAYLOAD = {
    "schema_version": "rh.pending_decisions.v1",
    "status": "pending_decision",
    "topic_id": 1,
    "has_pending": True,
    "decision": {
        "request_id": "req-1",
        "stage": "PW02_EVIDENCE_ACQUISITION",
        "checkpoint": "evidence_acquisition",
        "reason_code": "insufficient_seed_papers",
        "prompt": "Found 4 seed papers, need 10. How should we acquire more papers?",
        "options": [
            {
                "action": "broaden_search",
                "label": "Expand to external providers",
                "description": "Enable semantic_scholar and pasa for broader coverage",
                "expected_effect": "May find 6+ additional papers",
                "recommended": True,
            },
            {
                "action": "add_papers_manually",
                "label": "Add papers manually",
                "description": "Provide local papers or specific DOI/arXiv IDs",
            },
            {"action": "stop", "label": "Stop workflow"},
        ],
        "recommended_action": "broaden_search",
        "default_action": None,
        "interaction_mode": "checkpoint",
    },
}

NO_PENDING_PAYLOAD = {
    "schema_version": "rh.pending_decisions.v1",
    "status": "no_pending_decisions",
    "topic_id": 1,
    "has_pending": False,
}


class FakeBackend:
    """In-memory stand-ins for the checkpoint/decision/LLM providers."""

    def __init__(self) -> None:
        self.pending: dict[str, Any] = PENDING_PAYLOAD
        self.prompts: list[str] = []
        self.decisions: list[tuple[int, str, str]] = []
        self.reply_fn = lambda prompt: "canned assistant reply"

    def pending_decisions(self, topic_id: int) -> dict[str, Any]:
        return self.pending

    def record_decision(
        self, topic_id: int, choice: str, reasoning: str
    ) -> dict[str, Any]:
        self.decisions.append((topic_id, choice, reasoning))
        self.pending = NO_PENDING_PAYLOAD
        return {
            "schema_version": "rh.paper_production_decision.v1",
            "status": "accepted",
            "topic_id": topic_id,
            "choice": choice,
        }

    def chat_reply(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.reply_fn(prompt)


def _build_client(tmp_path: Path, backend: FakeBackend) -> TestClient:
    from research_harness.storage.db import Database
    from research_harness_mcp.workbench_chat_http import (
        register_workbench_chat_routes,
    )

    db_path = tmp_path / "workbench-chat.db"
    db = Database(db_path)
    db.migrate()
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO topics
                (id, name, description, status, target_venue, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "workbench-chat-topic",
                "Chat workbench topic",
                "active",
                "NeurIPS",
                "2026-07-01T00:00:00Z",
            ),
        )
        conn.commit()

    @contextmanager
    def get_db_context():
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def parse_json_field(value: str | None, default: Any) -> Any:
        if not value:
            return default
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return default

    counter = {"n": 0}

    def now_iso() -> str:
        counter["n"] += 1
        return f"2026-07-05T00:00:{counter['n']:02d}Z"

    app = FastAPI()
    register_workbench_chat_routes(
        app,
        get_db_context=get_db_context,
        row_to_dict=dict,
        parse_json_field=parse_json_field,
        now_iso=now_iso,
        pending_decisions_provider=backend.pending_decisions,
        decision_recorder=backend.record_decision,
        chat_reply_provider=backend.chat_reply,
    )
    return TestClient(app)


def test_workbench_chat_routes_are_registered() -> None:
    from research_harness_mcp import http_api

    paths = {route.path for route in http_api.app.routes}
    assert "/api/workbench/topics/{topic_id}/chat" in paths
    assert "/api/workbench/topics/{topic_id}/pending-decisions" in paths
    assert "/api/workbench/topics/{topic_id}/decisions" in paths


def test_chat_roundtrip_persists_messages_and_surfaces_decision(
    tmp_path: Path,
) -> None:
    backend = FakeBackend()
    client = _build_client(tmp_path, backend)

    initial = client.get("/api/workbench/topics/1/chat")
    assert initial.status_code == 200, initial.text
    assert initial.json()["messages"] == []
    assert initial.json()["pending_decision"]["prompt"].startswith("Found 4 seed")

    sent = client.post(
        "/api/workbench/topics/1/chat",
        json={"message": "现在进行到哪一步了？"},
    )
    assert sent.status_code == 200, sent.text
    payload = sent.json()
    assert [m["role"] for m in payload["messages"]] == ["user", "assistant"]
    assert payload["messages"][1]["content"] == "canned assistant reply"
    assert payload["pending_decision"]["recommended_action"] == "broaden_search"

    prompt = backend.prompts[0]
    assert "workbench-chat-topic" in prompt
    assert "broaden_search" in prompt
    assert "[AI 推荐]" in prompt
    assert "现在进行到哪一步了？" in prompt

    reloaded = client.get("/api/workbench/topics/1/chat")
    assert [m["content"] for m in reloaded.json()["messages"]] == [
        "现在进行到哪一步了？",
        "canned assistant reply",
    ]


def test_chat_reply_failure_is_returned_as_error_message(tmp_path: Path) -> None:
    backend = FakeBackend()
    client = _build_client(tmp_path, backend)

    def broken_reply(prompt: str) -> str:
        raise RuntimeError("no provider configured")

    backend.reply_fn = broken_reply

    sent = client.post("/api/workbench/topics/1/chat", json={"message": "hi"})
    assert sent.status_code == 200, sent.text
    assistant = sent.json()["messages"][1]
    assert assistant["kind"] == "error"
    assert "no provider configured" in assistant["content"]


def test_decision_flow_records_choice_and_clears_pending(tmp_path: Path) -> None:
    backend = FakeBackend()
    client = _build_client(tmp_path, backend)

    rejected = client.post(
        "/api/workbench/topics/1/decisions",
        json={"choice": "not_an_option"},
    )
    assert rejected.status_code == 422
    assert "broaden_search" in rejected.json()["detail"]

    accepted = client.post(
        "/api/workbench/topics/1/decisions",
        json={"choice": "broaden_search", "reasoning": "覆盖面优先"},
    )
    assert accepted.status_code == 200, accepted.text
    payload = accepted.json()
    assert payload["status"] == "accepted"
    assert payload["pending_decision"] is None
    assert backend.decisions == [(1, "broaden_search", "覆盖面优先")]
    assert [m["kind"] for m in payload["messages"]] == ["decision", "decision_ack"]
    assert "Expand to external providers" in payload["messages"][0]["content"]
    assert "覆盖面优先" in payload["messages"][0]["content"]

    reloaded = client.get("/api/workbench/topics/1/chat")
    assert [m["kind"] for m in reloaded.json()["messages"]] == [
        "decision",
        "decision_ack",
    ]

    again = client.post(
        "/api/workbench/topics/1/decisions",
        json={"choice": "broaden_search"},
    )
    assert again.status_code == 409


def test_chat_returns_404_for_missing_topic(tmp_path: Path) -> None:
    backend = FakeBackend()
    client = _build_client(tmp_path, backend)

    assert client.get("/api/workbench/topics/999/chat").status_code == 404
    assert (
        client.post(
            "/api/workbench/topics/999/chat", json={"message": "hi"}
        ).status_code
        == 404
    )
