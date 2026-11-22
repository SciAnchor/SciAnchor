"""Tests for Zotero HTTP API bridge."""

from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path: Path):
    db_path = tmp_path / "zotero-api.db"
    from research_harness.storage.db import Database

    db = Database(db_path)
    db.migrate()
    conn = db.connect()
    try:
        conn.execute("INSERT INTO topics (name, description) VALUES ('demo-topic', '')")
        conn.execute(
            """
            INSERT INTO papers
                (title, authors, year, venue, doi, arxiv_id, url, abstract, status, deep_read)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "Agentic Zotero API Sync",
                json.dumps(["Ada Lovelace"]),
                2026,
                "ICLR",
                "10.1234/zotero-api",
                "2602.99999",
                "https://arxiv.org/abs/2602.99999",
                "A paper for Zotero API sync tests.",
                "pdf_ready",
                1,
            ),
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (1, 1, 'high')"
        )
        conn.commit()
    finally:
        conn.close()

    from research_harness_mcp import http_api

    original = http_api.DB_PATH
    http_api.DB_PATH = db_path
    try:
        yield TestClient(http_api.app)
    finally:
        http_api.DB_PATH = original


def _sse_event_payloads(text: str, event: str) -> list[dict]:
    payloads: list[dict] = []
    current_event = ""
    for line in text.splitlines():
        if line.startswith("event: "):
            current_event = line.removeprefix("event: ").strip()
            continue
        if current_event == event and line.startswith("data: "):
            payloads.append(json.loads(line.removeprefix("data: ")))
    return payloads


def _walk_strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        strings: list[str] = []
        for item in value.values():
            strings.extend(_walk_strings(item))
        return strings
    if isinstance(value, list):
        strings: list[str] = []
        for item in value:
            strings.extend(_walk_strings(item))
        return strings
    return []


class FakeSandboxZoteroClient:
    is_sandbox = True

    def __init__(self) -> None:
        self.collections: dict[tuple[str, str | None], str] = {}
        self.items: dict[str, dict] = {}
        self.notes: dict[str, dict] = {}
        self.created_items: list[dict] = []
        self.updated_items: list[tuple[str, dict]] = []
        self.created_notes: list[tuple[str, str, list[str]]] = []
        self.updated_notes: list[tuple[str, str, list[str]]] = []
        self._next = 1

    def _key(self, prefix: str) -> str:
        key = f"{prefix}{self._next:07d}"[-8:]
        self._next += 1
        return key.upper()

    def find_collection(self, name: str, parent_key: str | None = None) -> str | None:
        return self.collections.get((name, parent_key))

    def create_collection(self, name: str, parent_key: str | None = None) -> str:
        key = self._key("C")
        self.collections[(name, parent_key)] = key
        return key

    def find_item_by_tag(self, tag: str) -> str | None:
        for key, payload in self.items.items():
            if tag in {item["tag"] for item in payload.get("tags", [])}:
                return key
        return None

    def create_item(self, payload: dict) -> str:
        key = self._key("I")
        self.items[key] = dict(payload)
        self.created_items.append(dict(payload))
        return key

    def update_item(self, item_key: str, payload: dict) -> None:
        self.items[item_key] = {**self.items.get(item_key, {}), **payload}
        self.updated_items.append((item_key, dict(payload)))

    def create_note(self, parent_item_key: str, note_html: str, tags: list[str]) -> str:
        key = self._key("N")
        self.notes[key] = {
            "parentItem": parent_item_key,
            "note": note_html,
            "tags": list(tags),
        }
        self.created_notes.append((parent_item_key, note_html, list(tags)))
        return key

    def update_note(
        self, note_key: str, parent_item_key: str, note_html: str, tags: list[str]
    ) -> None:
        self.notes[note_key] = {
            "parentItem": parent_item_key,
            "note": note_html,
            "tags": list(tags),
        }
        self.updated_notes.append((note_key, note_html, list(tags)))

    def add_child_note(
        self,
        key: str,
        parent_item_key: str,
        note_html: str,
        tags: list[str] | None = None,
    ) -> None:
        self.notes[key] = {
            "parentItem": parent_item_key,
            "note": note_html,
            "tags": list(tags or []),
        }

    def list_item_children(self, item_key: str) -> list[dict]:
        children = []
        for key, payload in self.notes.items():
            if payload.get("parentItem") != item_key:
                continue
            children.append(
                {
                    "key": key,
                    "data": {
                        "key": key,
                        "itemType": "note",
                        "parentItem": item_key,
                        "note": payload.get("note", ""),
                        "tags": [{"tag": tag} for tag in payload.get("tags", [])],
                    },
                }
            )
        return children


def test_topic_zotero_sync_push_dry_run(client: TestClient):
    response = client.post(
        "/api/topics/1/zotero-sync",
        json={"direction": "push", "dry_run": True, "limit": 1},
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["output"]["direction"] == "push"
    assert payload["output"]["push"]["planned_count"] == 1
    assert payload["output"]["push"]["records"][0]["title"] == "Agentic Zotero API Sync"
    receipt = payload["output"]["workflow_receipt"]
    assert receipt["schema"] == "rh-zotero-workflow-receipt/v1"
    assert receipt["action_type"] == "sync_rh_papers_to_collection"
    assert receipt["status"] == "dry_run"
    assert receipt["counts"]["papers_planned"] == 1
    assert receipt["counts"]["deep_read_notes"] == 1


def test_topic_zotero_sync_accepts_numeric_library_id(client: TestClient):
    response = client.post(
        "/api/topics/1/zotero-sync",
        json={
            "direction": "push",
            "dry_run": True,
            "limit": 1,
            "library_id": 1,
            "library_type": "user",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["output"]["push"]["planned_count"] == 1
    assert payload["output"]["workflow_receipt"]["action_type"] == (
        "sync_rh_papers_to_collection"
    )


def test_topic_zotero_sync_unknown_topic_404(client: TestClient):
    response = client.post(
        "/api/topics/999/zotero-sync",
        json={"direction": "push", "dry_run": True},
    )

    assert response.status_code == 404


def test_topic_zotero_sync_obeys_optional_token_gate(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("RESEARCH_HARNESS_ZOTERO_CHAT_TOKEN", "secret-token")

    blocked = client.post(
        "/api/topics/1/zotero-sync",
        json={"direction": "push", "dry_run": True, "limit": 1},
    )
    assert blocked.status_code == 401

    allowed = client.post(
        "/api/topics/1/zotero-sync",
        headers={"X-RH-Zotero-Token": "secret-token"},
        json={"direction": "push", "dry_run": True, "limit": 1},
    )
    assert allowed.status_code == 200, allowed.text


def test_topic_zotero_sync_pull_and_both_dry_run_are_deferred_before_client(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    from research_harness_mcp import http_api

    def fail_create_zotero_client(**kwargs):
        raise AssertionError(
            f"deferred dry-run must not create Zotero client: {kwargs}"
        )

    monkeypatch.setattr(
        http_api,
        "_create_zotero_write_client",
        fail_create_zotero_client,
    )

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


@pytest.mark.parametrize("direction", ["pull", "both"])
def test_topic_zotero_sync_pull_and_both_dry_run_use_sandbox_client(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    direction: str,
):
    from research_harness_mcp import http_api

    fake = FakeSandboxZoteroClient()
    fake.add_child_note("USERNOTE1", "ITEM0001", "<p>Sandbox preview note.</p>")
    with http_api.get_db() as conn:
        conn.execute(
            """
            INSERT INTO zotero_item_links (
                paper_id, topic_id, zotero_library_id, zotero_library_type,
                zotero_collection_key, zotero_item_key, zotero_note_key,
                content_hash, last_synced_at
            )
            VALUES (1, 1, 'sandbox', 'user', 'CURRDIR1', 'ITEM0001', 'NOTE0001', 'hash', '')
            """
        )
        conn.commit()

    monkeypatch.setenv("RESEARCH_HARNESS_ZOTERO_SANDBOX_SYNC", "1")
    monkeypatch.setattr(
        http_api,
        "_create_zotero_write_client",
        lambda **_: (fake, "sandbox"),
    )

    response = client.post(
        "/api/topics/1/zotero-sync",
        json={"direction": direction, "dry_run": True, "library_id": "sandbox"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()["output"]
    assert payload["direction"] == direction
    assert payload["pull"]["planned_count"] == 1
    assert payload["pull"]["items"][0]["action"] == "would_import"
    evidence = payload["phase_b_gate_evidence"]
    assert evidence["schema"] == "rh-zotero-phase-b-gate-evidence/v1"
    assert evidence["mode"] == "fake_sandbox"
    assert evidence["intent_plan"]["direction"] == direction
    assert evidence["preview"]["pull"]["planned_count"] == 1
    assert evidence["receipt"]["pull"]["planned_count"] == 1
    assert evidence["rollback_recovery"]["external_writes"] == "fake_sandbox_only"


def test_topic_zotero_sync_non_dry_run_rejects_before_client_without_sandbox(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    from research_harness_mcp import http_api

    def fail_create_zotero_client(**kwargs):
        raise AssertionError(f"real sync must reject before client creation: {kwargs}")

    monkeypatch.delenv("RESEARCH_HARNESS_ZOTERO_SANDBOX_SYNC", raising=False)
    monkeypatch.setattr(
        http_api,
        "_create_zotero_write_client",
        fail_create_zotero_client,
    )

    response = client.post(
        "/api/topics/1/zotero-sync",
        json={"direction": "push", "dry_run": False, "library_id": "sandbox"},
    )

    assert response.status_code == 400
    assert response.json()["detail"].startswith("real Zotero sync/apply is deferred")


def test_topic_zotero_sync_non_dry_run_sandbox_returns_gate_evidence_and_receipt(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    from research_harness_mcp import http_api

    fake = FakeSandboxZoteroClient()
    monkeypatch.setenv("RESEARCH_HARNESS_ZOTERO_SANDBOX_SYNC", "1")
    monkeypatch.setattr(
        http_api,
        "_create_zotero_write_client",
        lambda **_: (fake, "sandbox"),
    )

    response = client.post(
        "/api/topics/1/zotero-sync",
        json={
            "direction": "push",
            "dry_run": False,
            "library_id": "sandbox",
            "target_collection_key": "CURRDIR1",
            "limit": 1,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()["output"]
    assert payload["push"]["dry_run"] is False
    assert payload["push"]["synced_count"] == 1
    assert payload["workflow_receipt"]["status"] == "completed"
    evidence = payload["phase_b_gate_evidence"]
    assert evidence["intent_plan"]["dry_run"] is False
    assert evidence["intent_plan"]["sandbox_required"] is True
    assert evidence["preview"]["push"]["planned_count"] == 1
    assert evidence["receipt"]["workflow_status"] == "completed"
    assert evidence["rollback_recovery"]["local_recovery_tables"] == [
        "zotero_item_links",
        "zotero_import_links",
        "topic_paper_notes",
    ]

    with http_api.get_db() as conn:
        row = conn.execute(
            """
            SELECT zotero_item_key, zotero_collection_key
            FROM zotero_item_links
            WHERE paper_id = 1 AND topic_id = 1
              AND zotero_library_id = 'sandbox'
            """
        ).fetchone()
    assert row is not None
    assert row["zotero_collection_key"] == "CURRDIR1"


def test_zotero_seed_apply_non_dry_run_sandbox_returns_receipt_and_recovery(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    from research_harness_mcp import http_api

    fake = FakeSandboxZoteroClient()

    def fake_ingest(_api, *, source: str, topic_id: int | None, relevance: str):
        del source, relevance
        assert topic_id == 1
        with http_api.get_db() as conn:
            conn.execute(
                """
                INSERT INTO papers
                    (id, title, authors, year, venue, doi, arxiv_id, url,
                     abstract, status, deep_read)
                VALUES (2, 'Sandbox Seed Paper', '[]', 2026, 'ICLR',
                        '10.1234/seed', '', '', 'Seed abstract.', 'pdf_ready', 1)
                """
            )
            conn.execute(
                "INSERT INTO paper_topics (paper_id, topic_id, relevance) "
                "VALUES (2, 1, 'high')"
            )
            conn.commit()
        return {"paper_id": 2}

    monkeypatch.setenv("RESEARCH_HARNESS_ZOTERO_SANDBOX_SYNC", "1")
    monkeypatch.setattr(
        http_api,
        "_create_zotero_write_client",
        lambda **_: (fake, "sandbox"),
    )
    monkeypatch.setattr(http_api, "_ingest_paper_impl", fake_ingest)

    response = client.post(
        "/api/zotero/seed-papers/apply",
        json={
            "query": "sandbox seed",
            "topic_id": 1,
            "candidate_sources": ["10.1234/seed"],
            "target_collection_key": "CURRDIR1",
            "target_collection_name": "demo-topic",
            "target_is_topic_collection": True,
            "library_id": "sandbox",
            "dry_run": False,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()["output"]
    assert payload["paper_ids"] == [2]
    assert payload["push"]["synced_count"] == 1
    assert payload["workflow_receipt"]["status"] == "completed"
    evidence = payload["phase_b_gate_evidence"]
    assert evidence["intent_plan"]["action_type"] == "zotero_seed_paper_search"
    assert evidence["intent_plan"]["dry_run"] is False
    assert evidence["preview"]["push"]["planned_count"] == 1
    assert evidence["receipt"]["workflow_status"] == "completed"
    assert evidence["rollback_recovery"]["external_writes"] == "fake_sandbox_only"


def test_zotero_seed_apply_dry_run_ingest_failure_keeps_dry_run_receipt(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    from research_harness_mcp import http_api

    def failing_ingest(_api, *, source: str, topic_id: int | None, relevance: str):
        del topic_id, relevance
        raise RuntimeError(f"ingest failed for {source}")

    monkeypatch.setattr(http_api, "_ingest_paper_impl", failing_ingest)

    response = client.post(
        "/api/zotero/seed-papers/apply",
        json={
            "query": "dry run failure",
            "topic_id": 1,
            "candidate_sources": ["10.1234/failure"],
            "target_collection_key": "CURRDIR1",
            "target_collection_name": "demo-topic",
            "target_is_topic_collection": True,
            "dry_run": True,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()["output"]
    assert payload["paper_ids"] == []
    assert payload["push"] is None
    receipt = payload["workflow_receipt"]
    assert receipt["status"] == "dry_run"
    assert receipt["summary"] == "将同步 0 篇论文到 Zotero，等待确认。"
    assert receipt["counts"]["failures"] == 1


def test_zotero_seed_apply_non_dry_run_sandbox_skips_provider_postprocess(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
):
    from research_harness_mcp import http_api

    fake = FakeSandboxZoteroClient()
    calls: list[str] = []

    def fake_ingest(_api, *, source: str, topic_id: int | None, relevance: str):
        del source, relevance
        assert topic_id == 1
        with http_api.get_db() as conn:
            conn.execute(
                """
                INSERT INTO papers
                    (id, title, authors, year, venue, doi, arxiv_id, url,
                     abstract, status, deep_read)
                VALUES (3, 'Sandbox Postprocess Boundary', '[]', 2026, 'ICLR',
                        '10.1234/postprocess', '', '', 'Seed abstract.', '', 0)
                """
            )
            conn.execute(
                "INSERT INTO paper_topics (paper_id, topic_id, relevance) "
                "VALUES (3, 1, 'high')"
            )
            conn.commit()
        return {"paper_id": 3}

    def forbidden_tool(name: str, arguments: dict):
        calls.append(name)
        raise AssertionError(f"sandbox seed apply must not run {name}: {arguments}")

    def forbidden_deep_read(*args, **kwargs):
        calls.append("deep_read")
        raise AssertionError("sandbox seed apply must not run deep_read")

    def forbidden_pdf_annotations(*args, **kwargs):
        calls.append("pdf_annotations")
        raise AssertionError("sandbox seed apply must not run pdf annotations")

    monkeypatch.setenv("RESEARCH_HARNESS_ZOTERO_SANDBOX_SYNC", "1")
    monkeypatch.setattr(
        http_api,
        "_create_zotero_write_client",
        lambda **_: (fake, "sandbox"),
    )
    monkeypatch.setattr(http_api, "_ingest_paper_impl", fake_ingest)
    monkeypatch.setattr(http_api, "execute_tool", forbidden_tool)
    monkeypatch.setattr(http_api, "_deep_read_paper_impl", forbidden_deep_read)
    monkeypatch.setattr(
        http_api,
        "_apply_rh_pdf_annotations_for_papers",
        forbidden_pdf_annotations,
    )

    response = client.post(
        "/api/zotero/seed-papers/apply",
        json={
            "query": "sandbox postprocess boundary",
            "topic_id": 1,
            "candidate_sources": ["10.1234/postprocess"],
            "target_collection_key": "CURRDIR1",
            "target_collection_name": "demo-topic",
            "target_is_topic_collection": True,
            "library_id": "sandbox",
            "dry_run": False,
            "request_deep_read": True,
            "request_pdf_attachment": True,
            "request_pdf_annotations": True,
        },
    )

    assert response.status_code == 200, response.text
    assert calls == []
    payload = response.json()["output"]
    assert payload["push"]["synced_count"] == 1
    receipt = payload["workflow_receipt"]
    assert receipt["requested"] == {
        "deep_read": True,
        "pdf_attachment": True,
        "pdf_annotations": True,
    }
    assert receipt["counts"]["failures"] == 0
    assert any(
        "sandbox seed apply deferred provider-backed postprocess" in warning
        for warning in receipt["warnings"]
    )
    evidence = payload["phase_b_gate_evidence"]
    assert evidence["rollback_recovery"]["external_writes"] == "fake_sandbox_only"


def test_zotero_chat_resolves_rh_paper_from_tags(client: TestClient):
    response = client.post(
        "/api/zotero/chat",
        json={
            "message": "这篇论文接下来该怎么读？",
            "item": {
                "zotero_item_key": "ABCD1234",
                "library_id": 1,
                "title": "Agentic Zotero API Sync",
                "creators": ["Ada Lovelace"],
                "year": 2026,
                "doi": "10.1234/zotero-api",
                "tags": [
                    "rh",
                    "rh-paper-id:1",
                    "rh-topic:demo-topic",
                    "rh-deep-read",
                ],
                "abstract": "A paper for Zotero API sync tests.",
            },
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["output"]["matched"]["paper"]["id"] == 1
    assert payload["output"]["matched"]["paper"]["venue_tier"] == "CCF-A*"
    assert payload["output"]["matched"]["topic"]["id"] == 1
    assert "Agentic Zotero API Sync" in payload["output"]["assistant_message"]
    assert payload["output"]["codex_handoff"]["prompt"]
    assert payload["output"]["suggested_actions"][0]["kind"] == "codex_handoff"


def test_zotero_chat_response_does_not_expose_topic_knowledge_snapshot_context(
    client: TestClient,
):
    response = client.post(
        "/api/zotero/chat",
        json={
            "message": "Summarize the RH context for this paper.",
            "item": {
                "zotero_item_key": "ABCD1234",
                "library_id": 1,
                "title": "Agentic Zotero API Sync",
                "tags": [
                    "rh-paper-id:1",
                    "rh-topic:demo-topic",
                ],
            },
        },
    )

    assert response.status_code == 200, response.text
    strings = "\n".join(_walk_strings(response.json())).lower()
    assert "topic_knowledge" not in strings
    assert "topic knowledge" not in strings
    assert "semantic_atoms" not in strings
    assert "semantic_edges" not in strings


def test_zotero_match_returns_paper_level_metadata(client: TestClient):
    response = client.post(
        "/api/zotero/match",
        json={
            "zotero_item_key": "ABCD1234",
            "library_id": 1,
            "title": "Agentic Zotero API Sync",
            "creators": ["Ada Lovelace"],
            "year": 2026,
            "doi": "10.1234/zotero-api",
            "tags": [
                "rh-paper-id:1",
                "rh-topic:demo-topic",
            ],
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()["output"]["matched"]
    assert payload["paper"]["venue"] == "ICLR"
    assert payload["paper"]["venue_tier"] == "CCF-A*"
    assert payload["paper"]["arxiv_id"] == "2602.99999"


def test_zotero_chat_prefers_existing_zotero_item_link(client: TestClient):
    from research_harness_mcp import http_api

    with http_api.get_db() as conn:
        conn.execute(
            """
            INSERT INTO zotero_item_links (
                paper_id, topic_id, zotero_library_id, zotero_library_type,
                zotero_collection_key, zotero_item_key, zotero_note_key,
                content_hash, last_synced_at
            )
            VALUES (1, 1, '1', 'user', 'COLL1234', 'LINK1234', 'NOTE1234', 'hash', '')
            """
        )
        conn.commit()

    response = client.post(
        "/api/zotero/chat",
        json={
            "message": "总结 RH 已知上下文",
            "item": {
                "zotero_item_key": "LINK1234",
                "library_id": 1,
                "title": "Different local title",
                "tags": [],
            },
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()["output"]
    assert payload["matched"]["paper"]["id"] == 1
    assert payload["matched"]["topic"]["name"] == "demo-topic"
    assert payload["matched"]["zotero_link"]["zotero_item_key"] == "LINK1234"


def test_zotero_chat_link_match_filters_library_when_library_is_supplied(
    client: TestClient,
):
    from research_harness_mcp import http_api

    with http_api.get_db() as conn:
        conn.execute(
            """
            INSERT INTO zotero_item_links (
                paper_id, topic_id, zotero_library_id, zotero_library_type,
                zotero_collection_key, zotero_item_key, zotero_note_key,
                content_hash, last_synced_at
            )
            VALUES (1, 1, '2', 'group', 'GROUPCOLL', 'SAMEKEY', 'GROUPNOTE', 'hash', '')
            """
        )
        conn.commit()

    user_library = client.post(
        "/api/zotero/chat",
        json={
            "message": "这篇论文匹配到了什么？",
            "item": {
                "zotero_item_key": "SAMEKEY",
                "library_id": "1",
                "library_type": "user",
                "title": "Unrelated local title",
                "tags": [],
            },
        },
    )
    assert user_library.status_code == 200, user_library.text
    assert user_library.json()["output"]["matched"]["paper"] is None

    group_library = client.post(
        "/api/zotero/chat",
        json={
            "message": "这篇论文匹配到了什么？",
            "item": {
                "zotero_item_key": "SAMEKEY",
                "library_id": "2",
                "library_type": "group",
                "title": "Unrelated local title",
                "tags": [],
            },
        },
    )
    assert group_library.status_code == 200, group_library.text
    matched = group_library.json()["output"]["matched"]
    assert matched["paper"]["id"] == 1
    assert matched["zotero_link"]["zotero_library_type"] == "group"


def test_zotero_chat_optional_token_gate(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("RESEARCH_HARNESS_ZOTERO_CHAT_TOKEN", "secret-token")

    blocked = client.post(
        "/api/zotero/chat",
        json={"message": "ping", "item": {"title": "Untitled"}},
    )
    assert blocked.status_code == 401

    allowed = client.post(
        "/api/zotero/chat",
        headers={"X-RH-Zotero-Token": "secret-token"},
        json={"message": "ping", "item": {"title": "Untitled"}},
    )
    assert allowed.status_code == 200


def test_zotero_chat_rejects_overlong_message(client: TestClient):
    response = client.post(
        "/api/zotero/chat",
        json={"message": "x" * 12001, "item": {"title": "Untitled"}},
    )

    assert response.status_code == 422


def test_zotero_chat_stream_uses_codex_app_server_and_persists_thread(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from research_harness_mcp import http_api
    from research_harness_mcp.codex_app_server import CodexStreamEvent

    calls: list[dict] = []

    def fake_stream_codex_turn(
        *,
        body,
        conversation_id,
        existing_thread_id,
        prompt,
        matched,
        context_payload,
        model,
        image_urls=None,
    ):
        calls.append(
            {
                "body": body,
                "conversation_id": conversation_id,
                "existing_thread_id": existing_thread_id,
                "prompt": prompt,
                "matched": matched,
                "context_payload": context_payload,
                "model": model,
                "image_urls": image_urls,
            }
        )
        yield CodexStreamEvent(
            "started",
            {"thread_id": existing_thread_id or "thread-1", "turn_id": "turn-1"},
        )
        yield CodexStreamEvent("delta", {"text": "第一段"})
        yield CodexStreamEvent("delta", {"text": "，第二段"})
        yield CodexStreamEvent(
            "done", {"thread_id": existing_thread_id or "thread-1", "turn_id": "turn-1"}
        )

    monkeypatch.setattr(http_api, "_stream_zotero_codex_turn", fake_stream_codex_turn)

    first = client.post(
        "/api/zotero/chat/stream",
        json={
            "message": "这篇论文的 RH 贡献是什么？",
            "model": "gpt-5.4-mini",
            "item": {
                "zotero_item_key": "ABCD1234",
                "library_id": 1,
                "title": "Agentic Zotero API Sync",
                "tags": ["rh-paper-id:1"],
                "selected_text": "RH Zotero 选中的实验结果片段",
                "screenshots": ["data:image/png;base64,abc"],
            },
        },
    )

    assert first.status_code == 200, first.text
    assert first.headers["content-type"].startswith("text/event-stream")
    assert "event: ready" in first.text
    assert "event: delta" in first.text
    assert "第一段" in first.text
    assert "，第二段" in first.text
    assert "event: done" in first.text
    assert calls[0]["existing_thread_id"] is None
    assert "这篇论文的 RH 贡献是什么？" in calls[0]["prompt"]
    assert "RH Zotero 选中的实验结果片段" in calls[0]["prompt"]
    assert calls[0]["matched"]["paper"]["id"] == 1
    assert calls[0]["model"] == "gpt-5.4-mini"
    assert calls[0]["image_urls"] == ["data:image/png;base64,abc"]
    assert calls[0]["context_payload"]["kind"] == "paper"
    assert '"model":"gpt-5.4-mini"' in first.text

    second = client.post(
        "/api/zotero/chat/stream",
        json={
            "conversation_id": "zotero-chat-custom",
            "message": "继续上一轮",
            "item": {
                "zotero_item_key": "ABCD1234",
                "library_id": 1,
                "title": "Agentic Zotero API Sync",
                "tags": ["rh-paper-id:1"],
            },
        },
    )
    assert second.status_code == 200, second.text
    third = client.post(
        "/api/zotero/chat/stream",
        json={
            "conversation_id": "zotero-chat-custom",
            "message": "再继续",
            "item": {
                "zotero_item_key": "ABCD1234",
                "library_id": 1,
                "title": "Agentic Zotero API Sync",
                "tags": ["rh-paper-id:1"],
            },
        },
    )
    assert third.status_code == 200, third.text
    assert calls[-1]["existing_thread_id"] == "thread-1"


def test_zotero_chat_stream_forwards_codex_tool_activity_events(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from research_harness_mcp import http_api
    from research_harness_mcp.codex_app_server import CodexStreamEvent

    def fake_stream_codex_turn(**kwargs):
        del kwargs
        yield CodexStreamEvent(
            "started",
            {"thread_id": "thread-1", "turn_id": "turn-1"},
        )
        yield CodexStreamEvent(
            "tool_call",
            {
                "tool": "paper.list",
                "capability": "rh.paper.list",
                "call_id": "call-1",
                "arguments": {"limit": 1},
            },
        )
        yield CodexStreamEvent(
            "tool_result",
            {
                "tool": "paper.list",
                "capability": "rh.paper.list",
                "call_id": "call-1",
                "success": True,
                "status": "completed",
                "message": "Found 1 RH papers",
            },
        )
        yield CodexStreamEvent(
            "approval_request",
            {
                "method": "item/commandExecution/requestApproval",
                "decision": "decline",
            },
        )
        yield CodexStreamEvent("delta", {"text": "工具结果已读。"})
        yield CodexStreamEvent(
            "done",
            {"thread_id": "thread-1", "turn_id": "turn-1"},
        )

    monkeypatch.setattr(http_api, "_stream_zotero_codex_turn", fake_stream_codex_turn)

    response = client.post(
        "/api/zotero/chat/stream",
        json={
            "message": "RH 库里有哪些论文？",
            "item": {
                "library_id": 1,
                "current_directory_key": "CURRDIR1",
                "current_directory_name": "demo-topic",
                "current_directory_path": "Research Harness / demo-topic",
            },
        },
    )

    assert response.status_code == 200, response.text
    assert "event: tool_call" in response.text
    assert '"capability":"rh.paper.list"' in response.text
    assert "event: tool_result" in response.text
    assert '"message":"Found 1 RH papers"' in response.text
    assert "event: approval_request" in response.text
    assert '"decision":"decline"' in response.text
    assert "工具结果已读。" in response.text


def test_zotero_chat_stream_token_gate(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("RESEARCH_HARNESS_ZOTERO_CHAT_TOKEN", "secret-token")

    blocked = client.post(
        "/api/zotero/chat/stream",
        json={"message": "ping", "item": {"title": "Untitled"}},
    )
    assert blocked.status_code == 401


def test_zotero_chat_stream_rejects_unknown_model(client: TestClient):
    response = client.post(
        "/api/zotero/chat/stream",
        json={
            "message": "ping",
            "model": "not-a-real-model",
            "item": {"title": "Untitled"},
        },
    )

    assert response.status_code == 422


def test_zotero_warmup_prewarms_codex_pool(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from research_harness_mcp import http_api

    calls: list[dict] = []

    class FakePool:
        def prewarm(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(http_api, "_zotero_codex_pool", lambda: FakePool())

    response = client.post(
        "/api/zotero/warmup",
        json={"model": "gpt-5.3-codex-spark"},
    )

    assert response.status_code == 202, response.text
    payload = response.json()
    assert payload["status"] == "warming"
    # Primary chat model warmed
    chat_calls = [c for c in calls if c["model"] == "gpt-5.3-codex-spark"]
    assert chat_calls, "chat model must be prewarmed"
    assert chat_calls[0]["effort"] == "low"
    # Translate model (default extra) also prewarmed so first 翻译 click is fast
    translate_calls = [c for c in calls if c["model"] == "gpt-5.4-mini"]
    assert translate_calls, "translate model must be prewarmed alongside chat"
    assert "gpt-5.4-mini" in payload["extra_models"]


def test_zotero_warmup_skips_duplicate_extra_model(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """If the chat model IS the translate model, only warm it once."""

    from research_harness_mcp import http_api

    calls: list[dict] = []

    class FakePool:
        def prewarm(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(http_api, "_zotero_codex_pool", lambda: FakePool())

    response = client.post(
        "/api/zotero/warmup",
        json={"model": "gpt-5.4-mini"},
    )

    assert response.status_code == 202, response.text
    mini_calls = [c for c in calls if c["model"] == "gpt-5.4-mini"]
    assert len(mini_calls) == 1, (
        f"gpt-5.4-mini should be warmed exactly once, got {len(mini_calls)}"
    )


def test_zotero_warmup_drops_unknown_extra_models(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from research_harness_mcp import http_api

    calls: list[dict] = []

    class FakePool:
        def prewarm(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(http_api, "_zotero_codex_pool", lambda: FakePool())

    response = client.post(
        "/api/zotero/warmup",
        json={
            "model": "gpt-5.3-codex-spark",
            "extra_models": ["not-a-model", "gpt-5.4-mini"],
        },
    )

    assert response.status_code == 202, response.text
    extra_models = response.json()["extra_models"]
    assert extra_models == ["gpt-5.4-mini"]


def test_zotero_translate_stream_uses_oneshot_codex_call(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    """Selected-text translation must call Codex with a throwaway thread and
    the cheapest model defaults, with no chat conversation persistence."""

    from research_harness_mcp import http_api
    from research_harness_mcp.codex_app_server import CodexStreamEvent

    captured: dict = {}

    class FakePool:
        def stream_turn(self, **kwargs):
            captured.update(kwargs)
            yield CodexStreamEvent(
                "started", {"thread_id": "ephemeral", "turn_id": "t1"}
            )
            yield CodexStreamEvent("delta", {"text": "你好"})
            yield CodexStreamEvent("delta", {"text": "，世界"})
            yield CodexStreamEvent("done", {})

    monkeypatch.setattr(http_api, "_zotero_codex_pool", lambda: FakePool())

    response = client.post(
        "/api/zotero/translate/stream",
        json={"text": "Hello, world"},
    )

    assert response.status_code == 200, response.text
    body = response.text
    assert "event: ready" in body
    assert '"target_locale":"zh-CN"' in body
    assert "event: delta" in body
    assert "event: done" in body
    assert '"assistant_message":"你好，世界"' in body

    # one-shot: throwaway thread, gpt-5.4-mini default, low effort, no images
    assert captured["existing_thread_id"] is None
    assert captured["model"] == "gpt-5.4-mini"
    assert captured["effort"] == "low"
    assert captured.get("image_urls") in (None, [])
    assert "Hello, world" in captured["prompt"]
    # instructions should keep the LLM in pure-translation mode
    assert "只翻译" in captured["instructions"]
    assert "简体中文" in captured["instructions"]


def test_zotero_translate_stream_rejects_unknown_model(client: TestClient):
    response = client.post(
        "/api/zotero/translate/stream",
        json={"text": "Hello", "model": "not-a-real-model"},
    )

    assert response.status_code == 422


def test_zotero_translate_stream_honors_target_locale(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from research_harness_mcp import http_api
    from research_harness_mcp.codex_app_server import CodexStreamEvent

    captured: dict = {}

    class FakePool:
        def stream_turn(self, **kwargs):
            captured.update(kwargs)
            yield CodexStreamEvent("delta", {"text": "Bonjour"})
            yield CodexStreamEvent("done", {})

    monkeypatch.setattr(http_api, "_zotero_codex_pool", lambda: FakePool())

    response = client.post(
        "/api/zotero/translate/stream",
        json={"text": "Hello", "target_locale": "fr"},
    )

    assert response.status_code == 200, response.text
    assert "Français" in captured["instructions"]
    assert "Français" in captured["prompt"]


def test_zotero_translate_stream_respects_token_gate(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("RESEARCH_HARNESS_ZOTERO_CHAT_TOKEN", "secret-token")

    blocked = client.post(
        "/api/zotero/translate/stream",
        json={"text": "Hello"},
    )
    assert blocked.status_code == 401


def test_zotero_chat_stream_returns_import_preview_for_current_collection(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from research_harness_mcp import http_api

    def should_not_call_codex(**kwargs):
        raise AssertionError(
            "Codex stream should not run for current-collection import preview"
        )

    monkeypatch.setattr(http_api, "_stream_zotero_codex_turn", should_not_call_codex)

    response = client.post(
        "/api/zotero/chat/stream",
        json={
            "message": "把这个主题里精读过的 1 篇论文导入当前目录",
            "requested_action_type": "sync_rh_papers_to_collection",
            "item": {
                "zotero_item_key": "ABCD1234",
                "library_id": 1,
                "title": "Agentic Zotero API Sync",
                "tags": ["rh-paper-id:1", "rh-topic:demo-topic", "rh-deep-read"],
                "current_directory_key": "CURRDIR1",
                "current_directory_name": "自动科研",
                "current_directory_path": "Research Harness / 自动科研",
            },
        },
    )

    assert response.status_code == 200, response.text
    assert "event: ready" in response.text
    assert "event: action_preview" in response.text
    assert "event: done" in response.text
    assert '"topic_id":1' in response.text
    assert '"target_collection_key":"CURRDIR1"' in response.text
    assert '"library_id":"1"' in response.text
    assert '"library_type":"user"' in response.text
    assert '"paper_ids":[1]' in response.text
    assert "导入当前目录" in response.text
    assert '"action_type":"sync_rh_papers_to_collection"' in response.text
    assert '"type":"http_json"' in response.text
    assert '"label":"确认导入"' in response.text


def test_zotero_chat_stream_can_infer_import_topic_from_current_directory(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from research_harness_mcp import http_api

    def should_not_call_codex(**kwargs):
        raise AssertionError(
            "Codex stream should not run for current-directory import preview"
        )

    monkeypatch.setattr(http_api, "_stream_zotero_codex_turn", should_not_call_codex)

    response = client.post(
        "/api/zotero/chat/stream",
        json={
            "message": "把这个主题里精读过的 1 篇论文导入当前目录",
            "requested_action_type": "sync_rh_papers_to_collection",
            "item": {
                "current_directory_key": "CURRDIR1",
                "current_directory_name": "demo-topic",
                "current_directory_path": "Research Harness / demo-topic",
                "library_id": "1",
                "library_type": "user",
            },
        },
    )

    assert response.status_code == 200, response.text
    assert "event: action_preview" in response.text
    assert '"topic_id":1' in response.text
    assert '"paper_ids":[1]' in response.text


def test_zotero_import_preview_maps_local_user_library_to_web_user_id(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from research_harness_mcp import http_api

    def should_not_call_codex(**kwargs):
        raise AssertionError(
            "Codex stream should not run for current-directory import preview"
        )

    monkeypatch.setenv("ZOTERO_LIBRARY_ID", "16929158")
    monkeypatch.setenv("ZOTERO_LIBRARY_TYPE", "user")
    monkeypatch.setattr(http_api, "_stream_zotero_codex_turn", should_not_call_codex)

    response = client.post(
        "/api/zotero/chat/stream",
        json={
            "message": "把这个主题里 1 篇论文导入当前目录",
            "requested_action_type": "sync_rh_papers_to_collection",
            "item": {
                "current_directory_key": "CURRDIR1",
                "current_directory_name": "demo-topic",
                "current_directory_path": "Research Harness / demo-topic",
                "library_id": "1",
                "library_type": "user",
            },
        },
    )

    assert response.status_code == 200, response.text
    assert "event: action_preview" in response.text
    assert '"library_id":"16929158"' in response.text
    assert '"library_type":"user"' in response.text


def test_zotero_import_preview_counts_existing_links_in_current_library_only(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from research_harness_mcp import http_api

    def should_not_call_codex(**kwargs):
        raise AssertionError(
            "Codex stream should not run for current-directory import preview"
        )

    monkeypatch.setattr(http_api, "_stream_zotero_codex_turn", should_not_call_codex)

    with http_api.get_db() as conn:
        conn.execute(
            """
            INSERT INTO zotero_item_links (
                paper_id, topic_id, zotero_library_id, zotero_library_type,
                zotero_collection_key, zotero_item_key, zotero_note_key,
                content_hash, last_synced_at
            )
            VALUES (1, 1, '2', 'group', 'CURRDIR1', 'GROUPITEM', 'GROUPNOTE', 'hash', '')
            """
        )
        conn.commit()

    user_library = client.post(
        "/api/zotero/chat/stream",
        json={
            "message": "把这个主题里 1 篇论文导入当前目录",
            "requested_action_type": "sync_rh_papers_to_collection",
            "item": {
                "current_directory_key": "CURRDIR1",
                "current_directory_name": "demo-topic",
                "current_directory_path": "Research Harness / demo-topic",
                "library_id": "1",
                "library_type": "user",
            },
        },
    )
    assert user_library.status_code == 200, user_library.text
    assert '"known_existing_count":0' in user_library.text

    group_library = client.post(
        "/api/zotero/chat/stream",
        json={
            "message": "把这个主题里 1 篇论文导入当前目录",
            "requested_action_type": "sync_rh_papers_to_collection",
            "item": {
                "current_directory_key": "CURRDIR1",
                "current_directory_name": "demo-topic",
                "current_directory_path": "Research Harness / demo-topic",
                "library_id": "2",
                "library_type": "group",
            },
        },
    )
    assert group_library.status_code == 200, group_library.text
    assert '"known_existing_count":1' in group_library.text


def test_zotero_chat_stream_returns_create_collection_preview_without_codex(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from research_harness_mcp import http_api

    def should_not_call_codex(**kwargs):
        raise AssertionError(
            "Codex stream should not run for collection create previews"
        )

    monkeypatch.setattr(http_api, "_stream_zotero_codex_turn", should_not_call_codex)

    response = client.post(
        "/api/zotero/chat/stream",
        json={
            "message": "在当前 Zotero 目录下新建一个文件夹，叫 AI discovery",
            "requested_action_type": "zotero_create_collection",
            "item": {
                "current_directory_key": "PARENT01",
                "current_directory_name": "Research Harness",
                "current_directory_path": "Research Harness",
                "library_id": "1",
                "library_type": "user",
            },
        },
    )

    assert response.status_code == 200, response.text
    assert "event: action_preview" in response.text
    assert "event: started" not in response.text
    assert '"action_type":"zotero_create_collection"' in response.text
    assert '"handler":"zotero_create_collection"' in response.text
    assert '"collection_name":"AI discovery"' in response.text
    assert '"parent_collection_key":"PARENT01"' in response.text
    assert '"target_label":"Research Harness / AI discovery"' in response.text


def test_zotero_chat_stream_routes_unquoted_create_collection_preview_without_codex(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from research_harness_mcp import http_api

    def should_not_call_codex(**kwargs):
        raise AssertionError(
            "Codex stream should not run for natural-language collection create previews"
        )

    monkeypatch.setattr(http_api, "_stream_zotero_codex_turn", should_not_call_codex)

    response = client.post(
        "/api/zotero/chat/stream",
        json={
            "message": "新建文件夹 RH E2E Write Test 20260606-1354，先预览",
            "item": {
                "current_directory_key": "PARENT01",
                "current_directory_name": "Research Harness",
                "current_directory_path": "Research Harness",
                "library_id": "1",
                "library_type": "user",
            },
        },
    )

    assert response.status_code == 200, response.text
    assert "event: action_preview" in response.text
    assert "event: started" not in response.text
    assert '"action_type":"zotero_create_collection"' in response.text
    assert '"collection_name":"RH E2E Write Test 20260606-1354"' in response.text
    assert '"parent_collection_key":"PARENT01"' in response.text


def test_zotero_import_intent_classifier_avoids_generic_sync_chat():
    from research_harness_mcp import http_api

    assert not http_api._looks_like_zotero_import_request("同步这篇论文和 RH 的关系")
    assert not http_api._looks_like_zotero_import_request("请问这篇论文如何同步到 RH？")
    assert not http_api._looks_like_zotero_import_request("请帮我给 Zotero 添加标签")
    assert not http_api._looks_like_zotero_import_request("给这篇论文添加 Zotero 标签")
    assert http_api._looks_like_zotero_import_request("把这篇论文导入当前目录")


def test_zotero_chat_stream_returns_pdf_attach_action_preview_without_codex(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from research_harness_mcp import http_api

    def should_not_call_codex(**kwargs):
        raise AssertionError(
            "Codex stream should not run for PDF attachment action previews"
        )

    monkeypatch.setattr(http_api, "_stream_zotero_codex_turn", should_not_call_codex)
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% RH test PDF\n")
    monkeypatch.setattr(http_api, "PDF_ROOTS", [tmp_path])
    with http_api.get_db() as conn:
        conn.execute("UPDATE papers SET pdf_path = ? WHERE id = 1", (str(pdf_path),))
        conn.commit()

    response = client.post(
        "/api/zotero/chat/stream",
        json={
            "message": "对当前条目触发同步，下载并附加 PDF，先 dry-run，确认后 apply",
            "requested_action_type": "zotero_attach_pdf",
            "item": {
                "zotero_item_key": "ABCD1234",
                "library_id": 1,
                "title": "Agentic Zotero API Sync",
                "arxiv_id": "2602.99999",
                "tags": ["rh-paper-id:1", "rh-topic:demo-topic"],
            },
        },
    )

    assert response.status_code == 200, response.text
    assert "event: ready" in response.text
    assert "event: done" in response.text
    assert "event: started" not in response.text
    assert "event: action_preview" in response.text
    assert '"action_type":"zotero_attach_pdf"' in response.text
    assert '"handler":"zotero_import_file_attachment"' in response.text
    assert f'"pdf_path":"{str(pdf_path)}"' in response.text
    assert '"parent_item_key":"ABCD1234"' in response.text
    assert "PDF 附件" in response.text


def test_zotero_chat_stream_plans_natural_language_pdf_attach_without_codex(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from research_harness_mcp import http_api

    def should_not_call_codex(**kwargs):
        raise AssertionError("Codex stream should not run for planned PDF writes")

    monkeypatch.setattr(http_api, "_stream_zotero_codex_turn", should_not_call_codex)
    pdf_path = tmp_path / "paper.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% RH test PDF\n")
    monkeypatch.setattr(http_api, "PDF_ROOTS", [tmp_path])
    with http_api.get_db() as conn:
        conn.execute("UPDATE papers SET pdf_path = ? WHERE id = 1", (str(pdf_path),))
        conn.commit()

    response = client.post(
        "/api/zotero/chat/stream",
        json={
            "message": "为当前条目附加 PDF 原文",
            "item": {
                "zotero_item_key": "ABCD1234",
                "library_id": 1,
                "title": "Agentic Zotero API Sync",
                "tags": ["rh-paper-id:1", "rh-topic:demo-topic"],
            },
        },
    )

    assert response.status_code == 200, response.text
    previews = _sse_event_payloads(response.text, "action_preview")
    assert len(previews) == 1
    preview = previews[0]
    assert preview["action_type"] == "zotero_attach_pdf"
    assert preview["capability"] == "rh.zotero.attach_pdf"
    assert preview["preview_id"].startswith("zotero-preview-")
    assert preview["undo_supported"] is True
    assert preview["target_set"]["record_count"] == 1
    assert preview["records"][0]["paper_id"] == 1
    assert preview["apply"]["type"] == "zotero_local"
    assert preview["apply"]["handler"] == "zotero_import_file_attachment"
    assert "event: started" not in response.text


def test_zotero_chat_stream_materializes_missing_pdf_before_single_attach_preview(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from research_harness.acquisition.downloader import DownloadResult
    from research_harness_mcp import http_api

    def should_not_call_codex(**kwargs):
        raise AssertionError("Codex stream should not run for planned PDF writes")

    def fake_download(candidate, output_dir):
        assert candidate.paper_id == 1
        assert candidate.url == "https://openreview.net/forum?id=abc123"
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "1_downloaded.pdf"
        path.write_bytes(b"%PDF-1.4\n% RH downloaded PDF\n")
        return DownloadResult(
            paper_id=candidate.paper_id,
            status="success",
            path=path,
            provider="test-openreview",
        )

    monkeypatch.setattr(http_api, "_stream_zotero_codex_turn", should_not_call_codex)
    monkeypatch.setattr(http_api, "_download_zotero_attachable_pdf", fake_download)
    monkeypatch.setattr(http_api, "PDF_ROOTS", [tmp_path])
    with http_api.get_db() as conn:
        conn.execute(
            "UPDATE papers SET pdf_path = '', url = ? WHERE id = 1",
            ("https://openreview.net/forum?id=abc123",),
        )
        conn.commit()

    response = client.post(
        "/api/zotero/chat/stream",
        json={
            "message": "为当前条目附加 PDF 原文",
            "item": {
                "zotero_item_key": "ABCD1234",
                "library_id": 1,
                "title": "Agentic Zotero API Sync",
                "tags": ["rh-paper-id:1", "rh-topic:demo-topic"],
            },
        },
    )

    assert response.status_code == 200, response.text
    previews = _sse_event_payloads(response.text, "action_preview")
    assert len(previews) == 1
    preview = previews[0]
    assert preview["action_type"] == "zotero_attach_pdf"
    assert preview["planned_count"] == 1
    assert preview["apply"]["handler"] == "zotero_import_file_attachment"
    pdf_path = Path(preview["apply"]["payload"]["pdf_path"])
    assert pdf_path.is_relative_to(tmp_path / "papers")
    assert pdf_path.is_file()

    with http_api.get_db() as conn:
        row = conn.execute(
            "SELECT pdf_path, status FROM papers WHERE id = 1"
        ).fetchone()
    assert Path(row["pdf_path"]) == pdf_path
    assert row["status"] == "downloaded"


def test_zotero_chat_stream_plans_batch_pdf_attach_from_last_preview_targets(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from research_harness_mcp import http_api

    def should_not_call_codex(**kwargs):
        raise AssertionError("Codex stream should not run for batch PDF previews")

    monkeypatch.setattr(http_api, "_stream_zotero_codex_turn", should_not_call_codex)
    monkeypatch.setattr(http_api, "PDF_ROOTS", [tmp_path])
    with http_api.get_db() as conn:
        for paper_id in range(2, 6):
            conn.execute(
                """
                INSERT INTO papers
                    (id, title, authors, year, venue, doi, arxiv_id, url,
                     abstract, pdf_path, status, deep_read)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    paper_id,
                    f"Batch PDF Paper {paper_id}",
                    json.dumps(["Ada Lovelace"]),
                    2026,
                    "ICLR",
                    f"10.1234/batch-{paper_id}",
                    f"2606.10{paper_id:03d}",
                    "",
                    "Batch paper.",
                    "",
                    "pdf_ready",
                    1,
                ),
            )
            conn.execute(
                "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (?, 1, 'high')",
                (paper_id,),
            )
        for paper_id in range(1, 6):
            pdf_path = tmp_path / f"paper-{paper_id}.pdf"
            pdf_path.write_bytes(b"%PDF-1.4\n% RH batch PDF\n")
            conn.execute(
                "UPDATE papers SET pdf_path = ? WHERE id = ?",
                (str(pdf_path), paper_id),
            )
        conn.commit()

    response = client.post(
        "/api/zotero/chat/stream",
        json={
            "message": "给这 5 篇导入 PDF 原文",
            "item": {
                "library_id": "1",
                "current_directory_key": "CURRDIR1",
                "current_directory_name": "demo-topic",
                "current_directory_path": "Research Harness / demo-topic",
                "last_preview_targets": [
                    {
                        "paper_id": paper_id,
                        "zotero_item_key": f"ITEM{paper_id:04d}",
                        "library_id": "1",
                        "title": f"Batch PDF Paper {paper_id}",
                    }
                    for paper_id in range(1, 6)
                ],
            },
        },
    )

    assert response.status_code == 200, response.text
    preview = _sse_event_payloads(response.text, "action_preview")[0]
    assert preview["action_type"] == "zotero_attach_pdf"
    assert preview["capability"] == "rh.zotero.attach_pdf"
    assert preview["planned_count"] == 5
    assert preview["target_set"]["source"] == "last_preview_targets"
    assert preview["target_set"]["record_count"] == 5
    assert preview["blocked_records"] == []
    assert preview["apply"]["handler"] == "zotero_import_file_attachments"
    assert len(preview["apply"]["payload"]["records"]) == 5
    assert "event: started" not in response.text


def test_zotero_chat_stream_requested_pdf_attach_uses_last_preview_targets_in_collection(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from research_harness_mcp import http_api

    def should_not_call_codex(**kwargs):
        raise AssertionError("Codex stream should not run for requested batch PDF")

    monkeypatch.setattr(http_api, "_stream_zotero_codex_turn", should_not_call_codex)
    monkeypatch.setattr(http_api, "PDF_ROOTS", [tmp_path])
    pdf_path = tmp_path / "paper-1.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% RH batch PDF\n")
    with http_api.get_db() as conn:
        conn.execute("UPDATE papers SET pdf_path = ? WHERE id = 1", (str(pdf_path),))
        conn.commit()

    response = client.post(
        "/api/zotero/chat/stream",
        json={
            "message": "给这篇导入 PDF 原文",
            "requested_action_type": "zotero_attach_pdf",
            "item": {
                "library_id": "1",
                "current_directory_key": "CURRDIR1",
                "current_directory_name": "demo-topic",
                "current_directory_path": "Research Harness / demo-topic",
                "last_preview_targets": [
                    {
                        "paper_id": 1,
                        "zotero_item_key": "ITEM0001",
                        "library_id": "1",
                        "title": "Agentic Zotero API Sync",
                    }
                ],
            },
        },
    )

    assert response.status_code == 200, response.text
    preview = _sse_event_payloads(response.text, "action_preview")[0]
    assert preview["action_type"] == "zotero_attach_pdf"
    assert preview["planned_count"] == 1
    assert preview["target_set"]["source"] == "last_preview_targets"
    assert preview["apply"]["handler"] == "zotero_import_file_attachments"
    assert preview["apply"]["payload"]["records"][0]["parent_item_key"] == "ITEM0001"


def test_zotero_chat_stream_blocks_missing_or_untrusted_batch_pdf_records(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from research_harness.acquisition.downloader import DownloadResult
    from research_harness_mcp import http_api

    def should_not_call_codex(**kwargs):
        raise AssertionError("Codex stream should not run for guarded PDF previews")

    def fake_download(candidate, output_dir):
        assert candidate.paper_id == 3
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "3_downloaded.pdf"
        path.write_bytes(b"%PDF-1.4\n% RH downloaded PDF\n")
        return DownloadResult(
            paper_id=candidate.paper_id,
            status="success",
            path=path,
            provider="test-openreview",
        )

    untrusted_dir = tmp_path / "outside"
    trusted_dir = tmp_path / "trusted"
    trusted_dir.mkdir()
    untrusted_dir.mkdir()
    monkeypatch.setattr(http_api, "_stream_zotero_codex_turn", should_not_call_codex)
    monkeypatch.setattr(http_api, "_download_zotero_attachable_pdf", fake_download)
    monkeypatch.setattr(http_api, "PDF_ROOTS", [tmp_path])
    good_pdf = trusted_dir / "paper-1.pdf"
    good_pdf.write_bytes(b"%PDF-1.4\n% trusted\n")
    untrusted_pdf = tmp_path.parent / f"{tmp_path.name}-outside.pdf"
    untrusted_pdf.write_bytes(b"%PDF-1.4\n% untrusted\n")
    with http_api.get_db() as conn:
        conn.execute("UPDATE papers SET pdf_path = ? WHERE id = 1", (str(good_pdf),))
        conn.execute(
            """
            INSERT INTO papers
                (id, title, authors, year, venue, doi, arxiv_id, url,
                 abstract, pdf_path, status, deep_read)
            VALUES (2, 'Untrusted PDF Paper', '[]', 2026, '', NULL, NULL, '', '', ?, 'pdf_ready', 0)
            """,
            (str(untrusted_pdf),),
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (2, 1, 'high')"
        )
        conn.execute(
            """
            INSERT INTO papers
                (id, title, authors, year, venue, doi, arxiv_id, url,
                 abstract, pdf_path, status, deep_read)
            VALUES (3, 'Missing PDF Paper', '[]', 2026, '', NULL, NULL, 'https://openreview.net/forum?id=abc123', '', '', 'pdf_ready', 0)
            """
        )
        conn.execute(
            "INSERT INTO paper_topics (paper_id, topic_id, relevance) VALUES (3, 1, 'high')"
        )
        conn.commit()

    response = client.post(
        "/api/zotero/chat/stream",
        json={
            "message": "给这 3 篇导入 PDF 原文",
            "item": {
                "library_id": "1",
                "last_preview_targets": [
                    {"paper_id": 1, "zotero_item_key": "ITEM0001", "library_id": "1"},
                    {"paper_id": 2, "zotero_item_key": "ITEM0002", "library_id": "1"},
                    {"paper_id": 3, "zotero_item_key": "ITEM0003", "library_id": "1"},
                ],
            },
        },
    )

    assert response.status_code == 200, response.text
    preview = _sse_event_payloads(response.text, "action_preview")[0]
    assert preview["planned_count"] == 2
    assert {record["paper_id"] for record in preview["records"]} == {1, 3}
    assert len(preview["apply"]["payload"]["records"]) == 2
    assert {record["paper_id"] for record in preview["blocked_records"]} == {2}
    assert any("允许的 RH PDF 根目录" in warning for warning in preview["warnings"])
    assert "可写 2" in preview["message"]
    assert "下载失败 1" in preview["message"]


def test_zotero_chat_stream_blocks_downloaded_pdf_outside_trusted_roots(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from research_harness.acquisition.downloader import DownloadResult
    from research_harness_mcp import http_api

    def should_not_call_codex(**kwargs):
        raise AssertionError("Codex stream should not run for guarded PDF previews")

    outside_dir = tmp_path.parent / f"{tmp_path.name}-download-outside"
    outside_dir.mkdir()

    def fake_download(candidate, output_dir):
        del output_dir
        path = outside_dir / "downloaded.pdf"
        path.write_bytes(b"%PDF-1.4\n% outside trusted roots\n")
        return DownloadResult(
            paper_id=candidate.paper_id,
            status="success",
            path=path,
            provider="test-outside",
        )

    monkeypatch.setattr(http_api, "_stream_zotero_codex_turn", should_not_call_codex)
    monkeypatch.setattr(http_api, "_download_zotero_attachable_pdf", fake_download)
    monkeypatch.setattr(http_api, "PDF_ROOTS", [tmp_path])
    with http_api.get_db() as conn:
        conn.execute(
            "UPDATE papers SET pdf_path = '', url = ? WHERE id = 1",
            ("https://openreview.net/forum?id=outside",),
        )
        conn.commit()

    response = client.post(
        "/api/zotero/chat/stream",
        json={
            "message": "给这篇导入 PDF 原文",
            "item": {
                "library_id": "1",
                "last_preview_targets": [
                    {"paper_id": 1, "zotero_item_key": "ITEM0001", "library_id": "1"}
                ],
            },
        },
    )

    assert response.status_code == 200, response.text
    preview = _sse_event_payloads(response.text, "action_preview")[0]
    assert preview["planned_count"] == 0
    assert preview["records"] == []
    assert preview["apply"]["payload"]["records"] == []
    assert preview["blocked_records"][0]["paper_id"] == 1
    assert "允许的 RH PDF 根目录" in preview["blocked_records"][0]["reason"]

    with http_api.get_db() as conn:
        row = conn.execute("SELECT pdf_path FROM papers WHERE id = 1").fetchone()
    assert row["pdf_path"] == ""


def test_zotero_chat_stream_redownloads_untrusted_recorded_pdf_before_preview(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from research_harness.acquisition.downloader import DownloadResult
    from research_harness_mcp import http_api

    def should_not_call_codex(**kwargs):
        raise AssertionError("Codex stream should not run for planned PDF writes")

    outside_dir = tmp_path.parent / f"{tmp_path.name}-recorded-outside"
    outside_dir.mkdir()
    untrusted_pdf = outside_dir / "recorded.pdf"
    untrusted_pdf.write_bytes(b"%PDF-1.4\n% recorded outside root\n")

    def fake_download(candidate, output_dir):
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "1_redownloaded.pdf"
        path.write_bytes(b"%PDF-1.4\n% trusted redownload\n")
        return DownloadResult(
            paper_id=candidate.paper_id,
            status="success",
            path=path,
            provider="test-redownload",
        )

    monkeypatch.setattr(http_api, "_stream_zotero_codex_turn", should_not_call_codex)
    monkeypatch.setattr(http_api, "_download_zotero_attachable_pdf", fake_download)
    monkeypatch.setattr(http_api, "PDF_ROOTS", [tmp_path])
    with http_api.get_db() as conn:
        conn.execute(
            "UPDATE papers SET pdf_path = ?, url = ? WHERE id = 1",
            (str(untrusted_pdf), "https://openreview.net/forum?id=redownload"),
        )
        conn.commit()

    response = client.post(
        "/api/zotero/chat/stream",
        json={
            "message": "为当前条目附加 PDF 原文",
            "item": {
                "zotero_item_key": "ABCD1234",
                "library_id": 1,
                "title": "Agentic Zotero API Sync",
                "tags": ["rh-paper-id:1", "rh-topic:demo-topic"],
            },
        },
    )

    assert response.status_code == 200, response.text
    preview = _sse_event_payloads(response.text, "action_preview")[0]
    pdf_path = Path(preview["apply"]["payload"]["pdf_path"])
    assert pdf_path != untrusted_pdf
    assert pdf_path.is_relative_to(tmp_path / "papers")
    assert pdf_path.is_file()


def test_zotero_chat_stream_pdf_attach_requires_item_context_before_paper_match(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from research_harness_mcp import http_api

    def should_not_call_codex(**kwargs):
        raise AssertionError("Codex stream should not run for guarded PDF writes")

    monkeypatch.setattr(http_api, "_stream_zotero_codex_turn", should_not_call_codex)

    response = client.post(
        "/api/zotero/chat/stream",
        json={
            "message": "下载并附加 PDF 到 Zotero，确认后 apply",
            "requested_action_type": "zotero_attach_pdf",
            "item": {
                "current_directory_key": "EMPTYDIR",
                "current_directory_name": "demo-topic",
                "current_directory_path": "Research Harness / demo-topic",
                "library_id": "1",
                "library_type": "user",
            },
        },
    )

    assert response.status_code == 200, response.text
    assert "event: started" not in response.text
    assert "要附加 PDF，请先选中一个具体 Zotero 条目" in response.text


def test_zotero_chat_stream_returns_structured_unsupported_write_without_codex(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from research_harness_mcp import http_api

    def should_not_call_codex(**kwargs):
        raise AssertionError("Codex stream should not run for unsupported writes")

    monkeypatch.setattr(http_api, "_stream_zotero_codex_turn", should_not_call_codex)

    response = client.post(
        "/api/zotero/chat/stream",
        json={
            "message": "给当前论文添加 Zotero 标签 methodology",
            "item": {
                "zotero_item_key": "ABCD1234",
                "library_id": 1,
                "title": "Agentic Zotero API Sync",
                "tags": ["rh-paper-id:1", "rh-topic:demo-topic"],
            },
        },
    )

    assert response.status_code == 200, response.text
    unsupported = _sse_event_payloads(response.text, "unsupported_write")
    assert len(unsupported) == 1
    assert unsupported[0]["kind"] == "unsupported_write"
    assert unsupported[0]["capability"] is None
    assert "还没有接入侧边栏确认按钮" in unsupported[0]["message"]
    done = _sse_event_payloads(response.text, "done")[0]
    assert done["unsupported_write"] is True
    assert done["action_preview"] is False
    assert "event: started" not in response.text


def test_zotero_unsupported_write_intent_classifier_catches_pdf_attachment():
    from research_harness_mcp import http_api

    assert http_api._looks_like_unsupported_zotero_write_request(
        "对当前条目 SG97W99P 同步，下载并附加 PDF"
    )
    assert http_api._looks_like_unsupported_zotero_write_request(
        "给这篇论文添加 Zotero 标签"
    )
    assert not http_api._looks_like_unsupported_zotero_write_request(
        "这篇论文为什么值得读？"
    )
    assert not http_api._looks_like_unsupported_zotero_write_request(
        "把这篇论文导入当前目录"
    )


def test_zotero_chat_ready_payload_reports_context_and_actions(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from research_harness_mcp import http_api
    from research_harness_mcp.codex_app_server import CodexStreamEvent

    def fake_stream_codex_turn(**kwargs):
        del kwargs
        yield CodexStreamEvent(
            "done",
            {"thread_id": "thread-ready", "turn_id": "turn-ready"},
        )

    monkeypatch.setattr(http_api, "_stream_zotero_codex_turn", fake_stream_codex_turn)

    response = client.post(
        "/api/zotero/chat/stream",
        json={
            "message": "这个目录可以怎么推进？",
            "item": {
                "library_id": 1,
                "current_directory_key": "CURRDIR1",
                "current_directory_name": "demo-topic",
                "current_directory_path": "Research Harness / demo-topic",
            },
        },
    )

    assert response.status_code == 200, response.text
    assert '"kind":"collection"' in response.text
    assert "init_topic_from_collection" in response.text
    assert "sync_rh_missing_papers_to_collection" in response.text


def test_zotero_chat_stream_returns_seed_paper_preview_for_empty_collection(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from research_harness_mcp import http_api

    def fake_search(api, *, query, topic_id=None, max_results=50):
        assert topic_id == 1
        assert query == "demo-topic"
        assert max_results == 3
        return {
            "papers": [
                {
                    "title": "Seed Paper One",
                    "authors": ["Ada Lovelace"],
                    "year": 2026,
                    "venue": "ICLR",
                    "doi": "10.1234/seed-one",
                    "arxiv_id": "",
                    "url": "https://example.test/seed-one",
                    "snippet": "A seed paper.",
                    "citation_count": 12,
                },
                {
                    "title": "Seed Paper Two",
                    "authors": ["Grace Hopper"],
                    "year": 2025,
                    "venue": "NeurIPS",
                    "doi": "",
                    "arxiv_id": "2501.00002",
                    "url": "https://arxiv.org/abs/2501.00002",
                    "snippet": "Another seed paper.",
                    "citation_count": 24,
                },
            ],
            "provider_errors": [],
        }

    def should_not_call_codex(**kwargs):
        raise AssertionError(
            "Codex stream should not run for deterministic seed previews"
        )

    monkeypatch.setattr(http_api, "_search_papers_impl", fake_search)
    monkeypatch.setattr(http_api, "_stream_zotero_codex_turn", should_not_call_codex)

    response = client.post(
        "/api/zotero/chat/stream",
        json={
            "message": "帮我找到最开始的 3 篇种子论文",
            "requested_action_type": "zotero_seed_paper_search",
            "item": {
                "current_directory_key": "EMPTYDIR",
                "current_directory_name": "demo-topic",
                "current_directory_path": "Research Harness / demo-topic",
                "library_id": "1",
                "library_type": "user",
            },
        },
    )

    assert response.status_code == 200, response.text
    assert "event: ready" in response.text
    assert "event: action_preview" in response.text
    assert "event: done" in response.text
    assert "event: started" not in response.text
    action_preview = next(
        line
        for line in response.text.splitlines()
        if line.startswith("data: {")
        and '"action_type":"zotero_seed_paper_search"' in line
    )
    assert '"action_type":"zotero_seed_paper_search"' in response.text
    assert '"query":"demo-topic"' in action_preview
    assert '"topic_id":1' in action_preview
    assert '"target_collection_key":"EMPTYDIR"' in action_preview
    assert '"target_collection_path":"Research Harness / demo-topic"' in action_preview
    assert '"target_label":"Research Harness / demo-topic"' in action_preview
    assert '"target_is_topic_collection":true' in action_preview
    assert '"candidate_sources":["10.1234/seed-one","2501.00002"]' in action_preview
    assert '"path":"/api/zotero/seed-papers/apply"' in action_preview
    assert "Seed Paper One" in action_preview
    assert "入库并导入" in action_preview


def test_zotero_seed_preview_uses_current_folder_direction_for_generic_phrase(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from research_harness_mcp import http_api
    from research_harness_mcp.codex_app_server import CodexStreamEvent

    def fake_search(api, *, query, topic_id=None, max_results=50):
        assert topic_id is None
        assert query == "多模态时序预测"
        assert max_results == 5
        return {
            "papers": [
                {
                    "title": "Multimodal Forecasting Seed",
                    "authors": ["Ada Lovelace"],
                    "year": 2026,
                    "doi": "10.1234/multimodal-seed",
                }
            ],
            "provider_errors": [],
        }

    codex_called = False

    def fake_stream_codex_turn(**kwargs):
        nonlocal codex_called
        del kwargs
        codex_called = True
        yield CodexStreamEvent(
            "started",
            {"thread_id": "thread-1", "turn_id": "turn-1"},
        )

    monkeypatch.setattr(http_api, "_search_papers_impl", fake_search)
    monkeypatch.setattr(http_api, "_stream_zotero_codex_turn", fake_stream_codex_turn)

    response = client.post(
        "/api/zotero/chat/stream",
        json={
            "message": "围绕当前文件夹的研究方向推荐 5 篇起步文献，先给候选预览。",
            "item": {
                "current_directory_key": "MULTI001",
                "current_directory_name": "多模态时序预测",
                "current_directory_path": "Research Harness / 多模态时序预测",
                "library_id": "1",
                "library_type": "user",
            },
        },
    )

    assert response.status_code == 200, response.text
    preview_event = next(
        line
        for line in response.text.splitlines()
        if line.startswith("data: {")
        and '"action_type":"zotero_seed_paper_search"' in line
    )
    assert codex_called is False
    assert "event: action_preview" in response.text
    assert "event: started" not in response.text
    assert "event: tool_call" not in response.text
    assert "event: tool_result" not in response.text
    assert '"capability":"rh.zotero.prepare_seed_import"' in preview_event
    assert '"query":"多模态时序预测"' in preview_event
    assert '"topic_name":"多模态时序预测"' in preview_event
    assert '"target_collection_name":"多模态时序预测"' in preview_event
    assert '"target_label":"Research Harness / 多模态时序预测"' in preview_event
    assert '"target_is_topic_collection":true' in preview_event
    assert "推荐 5 篇起步文献" not in preview_event


def test_zotero_chat_stream_returns_seed_builder_assistant_message_without_codex(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from research_harness_mcp import http_api

    def should_not_call_codex(**kwargs):
        raise AssertionError(
            "Codex stream should not run when seed preview builder returns a message"
        )

    monkeypatch.setattr(http_api, "_stream_zotero_codex_turn", should_not_call_codex)

    response = client.post(
        "/api/zotero/chat/stream",
        json={
            "message": "帮我找到最开始的 3 篇种子论文",
            "item": {
                "current_directory_name": "demo-topic",
                "library_id": "1",
                "library_type": "user",
            },
        },
    )

    assert response.status_code == 200, response.text
    assert "event: action_preview" not in response.text
    assert "event: unsupported_write" not in response.text
    assert "event: started" not in response.text
    assert "could not build an action preview" not in response.text
    done = _sse_event_payloads(response.text, "done")[0]
    assert done["assistant_message"] == (
        "要让 RH 为新目录找种子论文，请先在左侧选中一个具体 Zotero 目录。"
    )
    assert done["action_preview"] is False
    assert done.get("unsupported_write") is not True


def test_zotero_write_planner_creates_clickable_seed_preview_without_codex_hint(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from research_harness_mcp import http_api
    from research_harness_mcp.codex_app_server import CodexStreamEvent

    def fake_search(api, *, query, topic_id=None, max_results=50):
        assert topic_id is None
        assert query == "多模态时序预测"
        assert max_results == 5
        return {
            "papers": [
                {
                    "title": "Multimodal Forecasting Seed",
                    "authors": ["Ada Lovelace"],
                    "year": 2026,
                    "doi": "10.1234/multimodal-seed",
                }
            ],
            "provider_errors": [],
        }

    codex_called = False

    def fake_stream_codex_turn(**kwargs):
        nonlocal codex_called
        del kwargs
        codex_called = True
        yield CodexStreamEvent(
            "started",
            {"thread_id": "thread-1", "turn_id": "turn-1"},
        )
        yield CodexStreamEvent(
            "delta",
            {
                "text": (
                    "我已经识别出这里需要 seed import 候选预览（action_preview），"
                    "你确认后再导入到当前 Zotero 文件夹。"
                )
            },
        )
        yield CodexStreamEvent("done", {"thread_id": "thread-1", "turn_id": "turn-1"})

    monkeypatch.setattr(http_api, "_search_papers_impl", fake_search)
    monkeypatch.setattr(http_api, "_stream_zotero_codex_turn", fake_stream_codex_turn)

    response = client.post(
        "/api/zotero/chat/stream",
        json={
            "message": "围绕当前文件夹的研究方向推荐 5 篇起步文献，先给候选预览。",
            "item": {
                "current_directory_key": "MULTI001",
                "current_directory_name": "多模态时序预测",
                "current_directory_path": "Research Harness / 多模态时序预测",
                "library_id": "1",
                "library_type": "user",
            },
        },
    )

    assert response.status_code == 200, response.text
    assert codex_called is False
    assert "event: action_preview" in response.text
    assert "event: delta" not in response.text
    assert "event: tool_call" not in response.text
    assert "event: tool_result" not in response.text
    assert '"synthetic":true' not in response.text
    assert '"capability":"rh.zotero.prepare_seed_import"' in response.text
    assert '"action_type":"zotero_seed_paper_search"' in response.text
    assert '"query":"多模态时序预测"' in response.text
    assert '"target_label":"Research Harness / 多模态时序预测"' in response.text
    assert '"action_preview":true' in response.text


def test_zotero_chat_stream_prefers_seed_preview_for_new_topic_with_pdf_sync_words(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from research_harness_mcp import http_api

    def fake_search(api, *, query, topic_id=None, max_results=50):
        assert query == "topic phrase"
        assert max_results == 5
        return {
            "papers": [
                {
                    "title": f"Topic Seed {index}",
                    "authors": ["Ada Lovelace"],
                    "year": 2026,
                    "doi": f"10.1234/topic-seed-{index}",
                }
                for index in range(1, 6)
            ],
            "provider_errors": [],
        }

    def should_not_call_codex(**kwargs):
        raise AssertionError("Codex stream should not run for seed previews")

    monkeypatch.setattr(http_api, "_search_papers_impl", fake_search)
    monkeypatch.setattr(http_api, "_stream_zotero_codex_turn", should_not_call_codex)

    response = client.post(
        "/api/zotero/chat/stream",
        json={
            "message": (
                "我想做一个新的研究方向 topic phrase，你来进行rh的初始化，"
                "推荐第一批论文（至少五篇），完成精读，把pdf和笔记同步到zotero端。"
            ),
            "requested_action_type": "zotero_seed_paper_search",
            "item": {
                "current_directory_key": "EMPTYDIR",
                "current_directory_name": "Research Harness",
                "current_directory_path": "Research Harness",
                "library_id": "1",
                "library_type": "user",
            },
        },
    )

    assert response.status_code == 200, response.text
    assert "event: action_preview" in response.text
    assert '"action_type":"zotero_seed_paper_search"' in response.text
    assert '"action_type":"zotero_attach_pdf"' not in response.text
    assert '"query":"topic phrase"' in response.text
    assert '"planned_count":5' in response.text
    assert '"request_deep_read":true' in response.text
    assert '"request_pdf_attachment":true' in response.text
    assert '"request_pdf_annotations":false' in response.text


def test_zotero_chat_stream_uses_explicit_new_direction_as_topic_collection(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from research_harness_mcp import http_api

    def fake_search(api, *, query, topic_id=None, max_results=50):
        assert topic_id is None
        assert query == "science discovery"
        assert max_results == 5
        return {
            "papers": [
                {
                    "title": "Science Discovery Seed",
                    "authors": ["Ada Lovelace"],
                    "year": 2026,
                    "doi": "10.1234/science-discovery-seed",
                }
            ],
            "provider_errors": [],
        }

    def should_not_call_codex(**kwargs):
        raise AssertionError("Codex stream should not run for seed previews")

    monkeypatch.setattr(http_api, "_search_papers_impl", fake_search)
    monkeypatch.setattr(http_api, "_stream_zotero_codex_turn", should_not_call_codex)

    response = client.post(
        "/api/zotero/chat/stream",
        json={
            "message": (
                "我想做一个新的研究方向 science discovery，"
                "推荐第一批论文，并同步 PDF 和笔记到 Zotero。"
            ),
            "requested_action_type": "zotero_seed_paper_search",
            "item": {
                "current_directory_key": "PARENT01",
                "current_directory_name": "Research Harness",
                "current_directory_path": "Research Harness",
                "library_id": "1",
                "library_type": "user",
            },
        },
    )

    assert response.status_code == 200, response.text
    action_preview = next(
        line
        for line in response.text.splitlines()
        if line.startswith("data: {")
        and '"action_type":"zotero_seed_paper_search"' in line
    )
    assert "event: action_preview" in response.text
    assert '"query":"science discovery"' in action_preview
    assert '"topic_name":"science discovery"' in action_preview
    assert '"target_collection_name":"science discovery"' in action_preview
    assert '"parent_collection_key":"PARENT01"' in action_preview
    assert '"target_label":"Research Harness / science discovery"' in action_preview
    assert '"target_collection_name":"Research Harness"' not in action_preview


def test_zotero_seed_paper_apply_defers_connector_for_local_desktop_library(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from research_harness import zotero_resource
    from research_harness_mcp import http_api

    calls: list[dict] = []

    class FakeZoteroClient:
        def __init__(self) -> None:
            self.items: dict[str, dict] = {}
            self.notes: dict[str, dict] = {}

        def find_collection(self, name, parent_key=None):
            return None

        def create_collection(self, name, parent_key=None):
            return "NEWCOLL"

        def find_item_by_tag(self, tag):
            return None

        def create_item(self, payload):
            self.items["ITEMKEY1"] = dict(payload)
            return "ITEMKEY1"

        def update_item(self, item_key, payload):
            self.items[item_key] = dict(payload)

        def create_note(self, parent_item_key, note_html, tags):
            self.notes["NOTEKEY1"] = {
                "parentItem": parent_item_key,
                "note": note_html,
                "tags": list(tags),
            }
            return "NOTEKEY1"

        def update_note(self, note_key, parent_item_key, note_html, tags):
            self.notes[note_key] = {
                "parentItem": parent_item_key,
                "note": note_html,
                "tags": list(tags),
            }

        def list_item_children(self, item_key):
            return []

    def fake_create_zotero_resource(**kwargs):
        calls.append(kwargs)
        return FakeZoteroClient()

    monkeypatch.delenv("ZOTERO_API_KEY", raising=False)
    monkeypatch.delenv("ZOTERO_ADAPTER", raising=False)
    monkeypatch.setattr(
        zotero_resource,
        "create_zotero_resource",
        fake_create_zotero_resource,
    )
    monkeypatch.setattr(
        http_api,
        "_ingest_paper_impl",
        lambda api, *, source, topic_id, relevance: {"paper_id": 1},
    )

    response = client.post(
        "/api/zotero/seed-papers/apply",
        json={
            "query": "demo-topic",
            "topic_id": 1,
            "candidate_sources": ["10.1234/zotero-api"],
            "target_collection_key": "CURRDIR1",
            "target_collection_name": "demo-topic",
            "target_collection_path": "Research Harness / demo-topic",
            "library_id": "1",
            "library_type": "user",
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
    assert calls == []


def test_zotero_seed_paper_apply_defers_pdf_annotation_postprocess(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    from research_harness import zotero_resource
    from research_harness_mcp import http_api

    calls: list[dict] = []

    class FakeZoteroClient:
        def find_collection(self, name, parent_key=None):
            return "TOPICCOLL"

        def create_collection(self, name, parent_key=None):
            raise AssertionError("collection already exists")

        def find_item_by_tag(self, tag):
            return None

        def create_item(self, payload):
            return "ITEMKEY1"

        def update_item(self, item_key, payload):
            raise AssertionError("item should be created")

        def create_note(self, parent_item_key, note_html, tags):
            return "NOTEKEY1"

        def update_note(self, note_key, parent_item_key, note_html, tags):
            raise AssertionError("note should be created")

        def list_item_children(self, item_key):
            return []

    monkeypatch.delenv("ZOTERO_API_KEY", raising=False)
    monkeypatch.delenv("ZOTERO_ADAPTER", raising=False)
    monkeypatch.setattr(
        zotero_resource,
        "create_zotero_resource",
        lambda **kwargs: FakeZoteroClient(),
    )
    monkeypatch.setattr(
        http_api,
        "_ingest_paper_impl",
        lambda api, *, source, topic_id, relevance: {"paper_id": 1},
    )

    def fake_execute_tool(name, arguments):
        calls.append({"name": name, "arguments": dict(arguments)})
        if name == "paper_acquire":
            return {"success": True, "downloaded": 1}
        raise AssertionError(f"unexpected tool call: {name}")

    def fake_apply_annotations(*, paper_ids, topic_id, topic_name, focus):
        calls.append(
            {
                "name": "pdf_annotations",
                "paper_ids": list(paper_ids),
                "topic_id": topic_id,
                "topic_name": topic_name,
                "focus": focus,
            }
        )
        return [
            {
                "status": "completed",
                "paper_id": 1,
                "title": "Agentic Zotero API Sync",
                "profile": "zotero-content-primitives-v2",
                "planned_count": 19,
                "applied_count": 19,
                "verified_count": 19,
                "missing_count": 0,
                "missing": [],
                "plan_path": "/tmp/annotation-plan.json",
                "pdf_path": "/tmp/paper.pdf",
            }
        ]

    monkeypatch.setattr(http_api, "execute_tool", fake_execute_tool)
    monkeypatch.setattr(
        http_api,
        "_apply_rh_pdf_annotations_for_papers",
        fake_apply_annotations,
    )

    response = client.post(
        "/api/zotero/seed-papers/apply",
        json={
            "query": "demo-topic",
            "topic_id": 1,
            "candidate_sources": ["10.1234/zotero-api"],
            "target_collection_key": "CURRDIR1",
            "target_collection_name": "demo-topic",
            "target_collection_path": "Research Harness / demo-topic",
            "library_id": "1",
            "library_type": "user",
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
    assert calls == []


def test_apply_rh_pdf_annotations_for_papers_writes_verified_pdf_annotations(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    from research_harness_mcp import http_api

    pdf_path = tmp_path / "paper.pdf"
    doc = fitz.open()
    page = doc.new_page()
    y = 72
    for index in range(1, 20):
        page.insert_text(
            (72, y),
            f"Anchor sentence {index} describes the method evidence boundary for testing.",
        )
        y += 24
    doc.save(pdf_path)
    doc.close()

    with http_api.get_db() as conn:
        conn.execute("UPDATE papers SET pdf_path = ? WHERE id = 1", (str(pdf_path),))
        conn.commit()

    monkeypatch.setattr(http_api, "PDF_ROOTS", [tmp_path])
    monkeypatch.setattr(
        http_api,
        "_record_zotero_pdf_annotation_artifact",
        lambda *args, **kwargs: None,
    )

    receipts = http_api._apply_rh_pdf_annotations_for_papers(
        paper_ids=[1],
        topic_id=1,
        topic_name="demo-topic",
        focus="agentic zotero testing",
    )

    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt["status"] == "completed"
    assert receipt["profile"] == "zotero-content-primitives-v2"
    assert receipt["planned_count"] == 19
    assert receipt["applied_count"] == 19
    assert receipt["missing_count"] == 0
    assert receipt["verified_count"] == 19
    assert Path(receipt["plan_path"]).exists()

    annotated = fitz.open(pdf_path)
    annotation_count = 0
    for page in annotated:
        annot = page.first_annot
        while annot:
            if "RH-PHD-v2" in str((annot.info or {}).get("content") or ""):
                annotation_count += 1
            annot = annot.next
    annotated.close()
    assert annotation_count == 19


def test_zotero_seed_search_intent_classifier_catches_initial_folder_requests():
    from research_harness_mcp import http_api

    assert http_api._looks_like_zotero_seed_search_request("帮我找到最开始的几篇文章")
    assert http_api._looks_like_zotero_seed_search_request(
        "这个空目录先推荐 5 篇 seed papers"
    )
    assert http_api._looks_like_zotero_seed_search_request(
        "我想做一个新的研究方向 topic phrase，推荐第一批论文，pdf和笔记同步到zotero端"
    )
    assert not http_api._looks_like_zotero_seed_search_request(
        "把这个主题里精读过的 3 篇论文导入当前目录"
    )
    flags = http_api._zotero_seed_request_flags("推荐第一批论文，并给 PDF 做高亮批注")
    assert flags["request_pdf_attachment"] is True
    assert flags["request_pdf_annotations"] is True


def test_zotero_import_count_parses_multi_character_chinese_numbers():
    from research_harness_mcp import http_api

    assert http_api._extract_zotero_import_count("导入十二篇论文到当前目录") == 12
    assert http_api._extract_zotero_import_count("导入二十篇论文到当前目录") == 20
    assert http_api._extract_zotero_import_count("导入二十三篇论文到当前目录") == 23
