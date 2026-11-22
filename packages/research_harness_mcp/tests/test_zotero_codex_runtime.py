"""Focused tests for Zotero Codex runtime helper extraction."""

from __future__ import annotations

from pathlib import Path
from typing import Any


class _FakePool:
    def __init__(self, *, fail_prewarm: bool = False) -> None:
        self.fail_prewarm = fail_prewarm
        self.prewarm_calls: list[dict[str, Any]] = []
        self.closed = 0

    def prewarm(self, **kwargs: Any) -> None:
        self.prewarm_calls.append(kwargs)
        if self.fail_prewarm:
            raise RuntimeError("prewarm failed")

    def close_all(self) -> None:
        self.closed += 1


class _FakeStreamPool:
    def __init__(self, calls: list[dict[str, Any]]) -> None:
        self.calls = calls

    def stream_turn(self, **kwargs: Any):
        self.calls.append(kwargs)
        yield {"event": "delta", "text": "hello"}
        yield {"event": "done"}


class _FakeLogger:
    def __init__(self) -> None:
        self.info_calls: list[tuple[Any, ...]] = []
        self.warning_calls: list[tuple[Any, ...]] = []

    def info(self, *args: Any, **_kwargs: Any) -> None:
        self.info_calls.append(args)

    def warning(self, *args: Any, **_kwargs: Any) -> None:
        self.warning_calls.append(args)


def test_zotero_codex_runtime_module_imports_and_http_private_names_exist():
    from research_harness_mcp import http_api, zotero_codex_runtime

    assert callable(zotero_codex_runtime.zotero_codex_thread_store)
    assert callable(zotero_codex_runtime.zotero_codex_pool)
    assert callable(zotero_codex_runtime.close_zotero_codex_pool)
    assert callable(zotero_codex_runtime.warm_zotero_codex_pool)
    assert callable(zotero_codex_runtime.save_zotero_codex_thread)
    assert callable(zotero_codex_runtime.stream_zotero_codex_turn)

    assert callable(http_api._zotero_codex_thread_store)
    assert callable(http_api._zotero_codex_pool)
    assert callable(http_api._close_zotero_codex_pool)
    assert callable(http_api._warm_zotero_codex_pool)
    assert callable(http_api._save_zotero_codex_thread)


def test_http_zotero_codex_pool_is_runtime_alias():
    from research_harness_mcp import http_api, zotero_codex_runtime

    assert http_api._zotero_codex_pool is zotero_codex_runtime.zotero_codex_pool


def test_zotero_codex_thread_store_uses_env_override_and_db_default(
    tmp_path: Path,
    monkeypatch,
):
    from research_harness_mcp import zotero_codex_runtime

    db_path = tmp_path / "pool.db"
    override_path = tmp_path / "custom" / "threads.json"
    monkeypatch.setenv(
        "RESEARCH_HARNESS_ZOTERO_CODEX_THREADS_PATH",
        str(override_path),
    )

    override_store = zotero_codex_runtime.zotero_codex_thread_store(db_path=db_path)
    assert override_store.path == override_path

    monkeypatch.delenv("RESEARCH_HARNESS_ZOTERO_CODEX_THREADS_PATH")
    default_store = zotero_codex_runtime.zotero_codex_thread_store(db_path=db_path)
    assert default_store.path == tmp_path / "zotero-codex-threads.json"


def test_zotero_codex_pool_singleton_and_close_reset(monkeypatch):
    from research_harness_mcp import zotero_codex_runtime

    pool = _FakePool()
    monkeypatch.setattr(zotero_codex_runtime, "_ZOTERO_CODEX_POOL", None)
    monkeypatch.setattr(
        zotero_codex_runtime,
        "CodexAppServerPool",
        lambda: pool,
    )

    assert zotero_codex_runtime.zotero_codex_pool() is pool
    assert zotero_codex_runtime.zotero_codex_pool() is pool

    zotero_codex_runtime.close_zotero_codex_pool(log=_FakeLogger())

    assert pool.closed == 1
    assert zotero_codex_runtime._ZOTERO_CODEX_POOL is None


def test_warm_zotero_codex_pool_is_best_effort():
    from research_harness_mcp import zotero_codex_runtime

    pool = _FakePool()
    log = _FakeLogger()
    zotero_codex_runtime.warm_zotero_codex_pool(
        cwd=Path("/tmp/rh-zotero"),
        model="gpt-5.4-mini",
        effort="low",
        service_tier="auto",
        pool_factory=lambda: pool,
        log=log,
    )

    assert pool.prewarm_calls == [
        {
            "cwd": Path("/tmp/rh-zotero"),
            "model": "gpt-5.4-mini",
            "effort": "low",
            "service_tier": "auto",
        }
    ]
    assert log.info_calls

    failing_pool = _FakePool(fail_prewarm=True)
    zotero_codex_runtime.warm_zotero_codex_pool(
        cwd=Path("/tmp/rh-zotero"),
        model="gpt-5.4-mini",
        effort="low",
        service_tier=None,
        pool_factory=lambda: failing_pool,
        log=log,
    )

    assert log.warning_calls


def test_save_zotero_codex_thread_persists_best_effort_metadata():
    from research_harness_mcp import zotero_codex_runtime

    saved: list[dict[str, Any]] = []

    class Store:
        def save_thread(self, **kwargs: Any) -> None:
            saved.append(kwargs)

    class Item:
        zotero_item_key = "ABCD1234"

    zotero_codex_runtime.save_zotero_codex_thread(
        store=Store(),
        conversation_id="conv-1",
        thread_id="thread-1",
        matched={"paper": {"id": 7}, "topic": {"id": 3}},
        item=Item(),
        log=_FakeLogger(),
    )

    assert saved == [
        {
            "conversation_id": "conv-1",
            "thread_id": "thread-1",
            "paper_id": 7,
            "topic_id": 3,
            "zotero_item_key": "ABCD1234",
        }
    ]


def test_http_warm_wrapper_preserves_existing_pool_monkeypatch(monkeypatch):
    from research_harness_mcp import http_api

    pool = _FakePool()
    monkeypatch.setattr(http_api, "_zotero_codex_pool", lambda: pool)

    http_api._warm_zotero_codex_pool(
        cwd=Path("/tmp/rh-zotero-http"),
        model="gpt-5.4-mini",
        effort="low",
        service_tier=None,
    )

    assert pool.prewarm_calls == [
        {
            "cwd": Path("/tmp/rh-zotero-http"),
            "model": "gpt-5.4-mini",
            "effort": "low",
            "service_tier": None,
        }
    ]


def test_stream_zotero_codex_turn_uses_ephemeral_runtime_dependencies():
    from research_harness_mcp import zotero_codex_runtime

    calls: list[dict[str, Any]] = []
    log = _FakeLogger()
    tool_handler = object()

    events = list(
        zotero_codex_runtime.stream_zotero_codex_turn(
            conversation_id="conv-1",
            existing_thread_id="thread-1",
            prompt="prompt text",
            model="gpt-5.4-mini",
            image_urls=[],
            build_instructions=lambda: "instructions",
            cwd_provider=lambda: "/repo",
            effort_provider=lambda: "medium",
            service_tier_provider=lambda: "default",
            pool_factory=lambda: _FakeStreamPool(calls),
            dynamic_tool_handler_factory=lambda: tool_handler,
            log=log,
        )
    )

    assert events == [{"event": "delta", "text": "hello"}, {"event": "done"}]
    assert calls == [
        {
            "cwd": "/repo",
            "instructions": "instructions",
            "existing_thread_id": "thread-1",
            "prompt": "prompt text",
            "model": "gpt-5.4-mini",
            "effort": "medium",
            "service_tier": "default",
            "image_urls": None,
            "dynamic_tool_handler": tool_handler,
        }
    ]
    assert log.info_calls == [
        (
            "Streaming Zotero Codex turn conversation=%s model=%s cwd=%s existing_thread=%s",
            "conv-1",
            "gpt-5.4-mini",
            "/repo",
            True,
        )
    ]


def test_http_stream_turn_wrapper_uses_dynamic_dependencies(monkeypatch):
    from research_harness_mcp import http_api

    calls: list[dict[str, Any]] = []
    log_calls: list[tuple[Any, ...]] = []
    tool_handler = object()

    monkeypatch.setattr(http_api, "_zotero_codex_base_instructions", lambda: "base")
    monkeypatch.setattr(http_api, "_zotero_codex_cwd", lambda: "/wrapped")
    monkeypatch.setattr(http_api, "_zotero_codex_effort", lambda: "high")
    monkeypatch.setattr(http_api, "_zotero_codex_service_tier", lambda: None)
    monkeypatch.setattr(http_api, "_zotero_codex_pool", lambda: _FakeStreamPool(calls))
    monkeypatch.setattr(
        http_api,
        "_zotero_codex_dynamic_tool_handler",
        lambda **_kwargs: tool_handler,
    )
    monkeypatch.setattr(
        http_api.logger,
        "info",
        lambda *args: log_calls.append(args),
    )

    events = list(
        http_api._stream_zotero_codex_turn(
            body=object(),
            conversation_id="conv-2",
            existing_thread_id=None,
            prompt="hello",
            matched={"paper": {"id": 1}},
            context_payload={"kind": "paper"},
            model="model-y",
            image_urls=["image://one"],
        )
    )

    assert events == [{"event": "delta", "text": "hello"}, {"event": "done"}]
    assert calls == [
        {
            "cwd": "/wrapped",
            "instructions": "base",
            "existing_thread_id": None,
            "prompt": "hello",
            "model": "model-y",
            "effort": "high",
            "service_tier": None,
            "image_urls": ["image://one"],
            "dynamic_tool_handler": tool_handler,
        }
    ]
    assert log_calls == [
        (
            "Streaming Zotero Codex turn conversation=%s model=%s cwd=%s existing_thread=%s",
            "conv-2",
            "model-y",
            "/wrapped",
            False,
        )
    ]
