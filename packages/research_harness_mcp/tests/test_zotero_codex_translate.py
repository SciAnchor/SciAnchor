"""Focused tests for Zotero Codex translation stream helper extraction."""

from __future__ import annotations

from typing import Any


class _FakePool:
    def __init__(self, calls: list[dict[str, Any]]) -> None:
        self._calls = calls

    def stream_turn(self, **kwargs: Any):
        self._calls.append(kwargs)
        yield {"event": "delta", "text": "bonjour"}
        yield {"event": "done"}


def test_zotero_codex_translate_helper_streams_ephemeral_turn():
    from research_harness_mcp import zotero_codex_translate

    calls: list[dict[str, Any]] = []
    logs: list[tuple[str, tuple[Any, ...]]] = []

    events = list(
        zotero_codex_translate.stream_zotero_codex_translate(
            text=" Hello ",
            model="gpt-5.4-mini",
            target_locale="fr",
            source_locale="en",
            build_instructions=lambda locale: f"instructions:{locale}",
            build_prompt=lambda **kwargs: f"prompt:{kwargs}",
            cwd_provider=lambda: "/repo",
            effort_provider=lambda: "low",
            service_tier_provider=lambda: "default",
            pool_factory=lambda: _FakePool(calls),
            log_info=lambda message, *args: logs.append((message, args)),
        )
    )

    assert events == [
        {"event": "delta", "text": "bonjour"},
        {"event": "done"},
    ]
    assert calls == [
        {
            "cwd": "/repo",
            "instructions": "instructions:fr",
            "existing_thread_id": None,
            "prompt": (
                "prompt:{'text': ' Hello ', 'target_locale': 'fr', "
                "'source_locale': 'en'}"
            ),
            "model": "gpt-5.4-mini",
            "effort": "low",
            "service_tier": "default",
            "image_urls": None,
        }
    ]
    assert logs == [
        (
            "Streaming Zotero Codex translation model=%s cwd=%s chars=%d target=%s",
            ("gpt-5.4-mini", "/repo", 7, "fr"),
        )
    ]


def test_http_api_zotero_codex_translate_wrapper_uses_dynamic_dependencies(
    monkeypatch,
):
    from research_harness_mcp import http_api

    calls: list[dict[str, Any]] = []
    logs: list[tuple[str, tuple[Any, ...]]] = []

    monkeypatch.setattr(
        http_api,
        "_zotero_codex_translate_instructions",
        lambda locale: f"wrapped-instructions:{locale}",
    )
    monkeypatch.setattr(
        http_api,
        "_zotero_codex_translate_prompt",
        lambda **kwargs: f"wrapped-prompt:{kwargs}",
    )
    monkeypatch.setattr(http_api, "_zotero_codex_cwd", lambda: "/wrapped")
    monkeypatch.setattr(http_api, "_zotero_codex_translate_effort", lambda: "medium")
    monkeypatch.setattr(http_api, "_zotero_codex_service_tier", lambda: None)
    monkeypatch.setattr(http_api, "_zotero_codex_pool", lambda: _FakePool(calls))
    monkeypatch.setattr(
        http_api.logger,
        "info",
        lambda message, *args: logs.append((message, args)),
    )

    assert list(
        http_api._stream_zotero_codex_translate(
            text="Text",
            model="model-x",
            target_locale="de",
            source_locale="fr",
        )
    ) == [
        {"event": "delta", "text": "bonjour"},
        {"event": "done"},
    ]
    assert calls == [
        {
            "cwd": "/wrapped",
            "instructions": "wrapped-instructions:de",
            "existing_thread_id": None,
            "prompt": (
                "wrapped-prompt:{'text': 'Text', 'target_locale': 'de', "
                "'source_locale': 'fr'}"
            ),
            "model": "model-x",
            "effort": "medium",
            "service_tier": None,
            "image_urls": None,
        }
    ]
    assert logs == [
        (
            "Streaming Zotero Codex translation model=%s cwd=%s chars=%d target=%s",
            ("model-x", "/wrapped", 4, "de"),
        )
    ]
