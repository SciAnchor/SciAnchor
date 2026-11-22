"""Focused HTTP tests for the local LLM explain endpoint."""

from __future__ import annotations

import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient


def test_llm_explain_rejects_empty_text():
    from research_harness_mcp.http_api import app

    response = TestClient(app).post("/api/llm/explain", json={"text": "   "})

    assert response.status_code == 400
    assert response.json()["detail"] == "text is required"


def test_llm_explain_uses_mocked_router_and_reports_usage(monkeypatch):
    from research_harness_mcp.http_api import app

    calls: list[dict[str, str]] = []

    class FakeClient:
        def chat_with_usage(self, prompt: str, *, tier: str):
            calls.append({"prompt": prompt, "tier": tier})
            usage = SimpleNamespace(
                provider="fake",
                model="fake-model",
                prompt_tokens=12,
                completion_tokens=4,
            )
            return "explained", usage

    monkeypatch.setitem(
        sys.modules, "llm_router", SimpleNamespace(LLMClient=FakeClient)
    )

    response = TestClient(app).post(
        "/api/llm/explain",
        json={
            "text": "Selected passage",
            "paper_title": "Paper Title",
            "custom_prompt": "Explain precisely.",
            "tier": "light",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "response": "explained",
        "preset_used": None,
        "tier": "light",
        "usage": {
            "provider": "fake",
            "model": "fake-model",
            "prompt_tokens": 12,
            "completion_tokens": 4,
        },
    }
    assert calls == [
        {
            "prompt": 'Explain precisely.\n\nPaper: Paper Title\nPassage:\n"""\nSelected passage\n"""',
            "tier": "light",
        }
    ]
