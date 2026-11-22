"""Focused HTTP tests for primitive analysis/writing action routes."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_analysis_and_writing_routes_dispatch_tool_arguments(monkeypatch):
    from research_harness_mcp import http_api

    calls: list[tuple[str, dict]] = []

    def fake_run_tool(name: str, arguments: dict):
        calls.append((name, arguments))
        return {"status": "success", "tool": name, "arguments": arguments}

    monkeypatch.setattr(http_api, "_run_tool", fake_run_tool)
    client = TestClient(http_api.app)

    responses = [
        client.post("/api/topics/5/gaps", json={"focus": "retrieval"}),
        client.post(
            "/api/topics/5/claims",
            json={"paper_ids": [1, 2], "focus": "evidence"},
        ),
        client.post(
            "/api/topics/5/section-draft",
            json={"section": "Related Work", "outline": "Plan", "max_words": 900},
        ),
        client.post(
            "/api/topics/5/publication-pack/backfill",
            json={"components": [" citation ", "citation", "", "x" * 130]},
        ),
    ]

    assert [response.status_code for response in responses] == [200, 200, 200, 200]
    assert calls == [
        ("gap_detect", {"topic_id": 5, "focus": "retrieval"}),
        (
            "claim_extract",
            {"topic_id": 5, "paper_ids": [1, 2], "focus": "evidence"},
        ),
        (
            "section_draft",
            {
                "section": "Related Work",
                "topic_id": 5,
                "outline": "Plan",
                "max_words": 900,
            },
        ),
        (
            "publication_pack_backfill",
            {
                "topic_id": 5,
                "target_profile": "high-impact-general",
                "record_artifact": True,
                "components": ["citation", "x" * 120],
            },
        ),
    ]


def test_design_code_and_writing_routes_dispatch_tool_arguments(monkeypatch):
    from research_harness_mcp import http_api

    calls: list[tuple[str, dict]] = []

    def fake_run_tool(name: str, arguments: dict):
        calls.append((name, arguments))
        return {"status": "success", "tool": name, "arguments": arguments}

    monkeypatch.setattr(http_api, "_run_tool", fake_run_tool)
    client = TestClient(http_api.app)

    responses = [
        client.post(
            "/api/topics/7/algorithm-design-loop",
            json={"focus": "ablation", "max_rounds": 2},
        ),
        client.post(
            "/api/topics/7/competitive-learning",
            json={"venue": "ICLR", "focus": "retrieval"},
        ),
        client.post("/api/topics/7/design-brief", json={"focus": "latency"}),
        client.post(
            "/api/topics/7/code-generate",
            json={"spec": "train model", "focus": "cpu"},
        ),
        client.post(
            "/api/topics/7/section-review",
            json={"section": "Methods", "content": "Draft"},
        ),
        client.post(
            "/api/topics/7/section-revise",
            json={"section": "Methods", "content": "Draft", "feedback": "Tighten"},
        ),
        client.post(
            "/api/topics/7/consistency-check",
            json={"sections": ["intro", "methods"]},
        ),
        client.post("/api/topics/7/writing-pattern", json={"paper_id": 11}),
        client.post(
            "/api/topics/7/writing-architecture",
            json={"template": "acl"},
        ),
    ]

    assert [response.status_code for response in responses] == [200] * 9
    assert calls == [
        (
            "algorithm_design_loop",
            {"topic_id": 7, "max_rounds": 2, "focus": "ablation"},
        ),
        (
            "competitive_learning",
            {"topic_id": 7, "venue": "ICLR", "focus": "retrieval"},
        ),
        ("design_brief_expand", {"topic_id": 7, "direction": "latency"}),
        ("code_generate", {"topic_id": 7, "spec": "train model", "focus": "cpu"}),
        (
            "section_review",
            {"topic_id": 7, "section": "Methods", "content": "Draft"},
        ),
        (
            "section_revise",
            {
                "topic_id": 7,
                "section": "Methods",
                "content": "Draft",
                "feedback": "Tighten",
            },
        ),
        (
            "consistency_check",
            {"topic_id": 7, "sections": ["intro", "methods"]},
        ),
        ("writing_pattern_extract", {"topic_id": 7, "paper_id": 11}),
        ("writing_architecture", {"topic_id": 7, "template": "acl"}),
    ]


def test_design_brief_requires_direction_or_focus(monkeypatch):
    from research_harness_mcp import http_api

    calls: list[tuple[str, dict]] = []

    def fake_run_tool(name: str, arguments: dict):
        calls.append((name, arguments))
        return {"status": "success"}

    monkeypatch.setattr(http_api, "_run_tool", fake_run_tool)
    response = TestClient(http_api.app).post(
        "/api/topics/7/design-brief",
        json={},
    )

    assert response.status_code == 422
    assert calls == []
