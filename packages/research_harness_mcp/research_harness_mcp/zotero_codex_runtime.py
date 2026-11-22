"""Zotero Codex app-server runtime helpers for the HTTP bridge."""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Callable

from research_harness_mcp.codex_app_server import (
    CodexAppServerPool,
    ZoteroCodexConversationStore,
)

logger = logging.getLogger(__name__)

_ZOTERO_CODEX_POOL: Any | None = None
_ZOTERO_CODEX_POOL_LOCK = threading.Lock()


def zotero_codex_thread_store(
    *,
    db_path: str | Path,
) -> ZoteroCodexConversationStore:
    store_path = Path(
        os.environ.get("RESEARCH_HARNESS_ZOTERO_CODEX_THREADS_PATH")
        or str(Path(db_path).parent / "zotero-codex-threads.json")
    )
    return ZoteroCodexConversationStore(store_path)


def zotero_codex_pool() -> Any:
    global _ZOTERO_CODEX_POOL
    if _ZOTERO_CODEX_POOL is not None:
        return _ZOTERO_CODEX_POOL
    with _ZOTERO_CODEX_POOL_LOCK:
        if _ZOTERO_CODEX_POOL is None:
            _ZOTERO_CODEX_POOL = CodexAppServerPool()
        return _ZOTERO_CODEX_POOL


def close_zotero_codex_pool(
    *,
    log: logging.Logger | None = None,
) -> None:
    global _ZOTERO_CODEX_POOL
    active_log = log or logger
    pool = _ZOTERO_CODEX_POOL
    _ZOTERO_CODEX_POOL = None
    if pool is not None:
        try:
            pool.close_all()
        except Exception:
            active_log.warning("Failed to close Zotero Codex pool", exc_info=True)


def warm_zotero_codex_pool(
    *,
    cwd: str | Path,
    model: str,
    effort: str,
    service_tier: str | None,
    pool_factory: Callable[[], Any] = zotero_codex_pool,
    log: logging.Logger | None = None,
) -> None:
    active_log = log or logger
    try:
        pool_factory().prewarm(
            cwd=cwd,
            model=model,
            effort=effort,
            service_tier=service_tier,
        )
        active_log.info(
            "Prewarmed Zotero Codex app-server model=%s cwd=%s",
            model,
            cwd,
        )
    except Exception:
        active_log.warning(
            "Failed to prewarm Zotero Codex app-server model=%s cwd=%s",
            model,
            cwd,
            exc_info=True,
        )


def save_zotero_codex_thread(
    *,
    store: Any,
    conversation_id: str,
    thread_id: str,
    matched: dict[str, Any],
    item: Any,
    log: logging.Logger | None = None,
) -> None:
    active_log = log or logger
    paper = matched.get("paper") or {}
    topic = matched.get("topic") or {}
    try:
        store.save_thread(
            conversation_id=conversation_id,
            thread_id=thread_id,
            paper_id=paper.get("id"),
            topic_id=topic.get("id"),
            zotero_item_key=item.zotero_item_key,
        )
    except Exception:
        active_log.warning(
            "Failed to persist Zotero Codex thread mapping", exc_info=True
        )


def stream_zotero_codex_turn(
    *,
    conversation_id: str,
    existing_thread_id: str | None,
    prompt: str,
    model: str,
    image_urls: list[str] | None = None,
    build_instructions: Callable[[], str],
    cwd_provider: Callable[[], str],
    effort_provider: Callable[[], str],
    service_tier_provider: Callable[[], str | None],
    pool_factory: Callable[[], Any] = zotero_codex_pool,
    dynamic_tool_handler_factory: Callable[[], Any],
    log: logging.Logger | None = None,
) -> Any:
    active_log = log or logger
    instructions = build_instructions()
    cwd = cwd_provider()
    effort = effort_provider()
    service_tier = service_tier_provider()
    active_log.info(
        "Streaming Zotero Codex turn conversation=%s model=%s cwd=%s existing_thread=%s",
        conversation_id,
        model,
        cwd,
        bool(existing_thread_id),
    )
    yield from pool_factory().stream_turn(
        cwd=cwd,
        instructions=instructions,
        existing_thread_id=existing_thread_id,
        prompt=prompt,
        model=model,
        effort=effort,
        service_tier=service_tier,
        image_urls=image_urls or None,
        dynamic_tool_handler=dynamic_tool_handler_factory(),
    )
