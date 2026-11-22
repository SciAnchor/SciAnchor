"""Zotero Codex translation stream helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def stream_zotero_codex_translate(
    *,
    text: str,
    model: str,
    target_locale: str,
    source_locale: str = "",
    build_instructions: Callable[[str], str],
    build_prompt: Callable[..., str],
    cwd_provider: Callable[[], str],
    effort_provider: Callable[[], str],
    service_tier_provider: Callable[[], str | None],
    pool_factory: Callable[[], Any],
    log_info: Callable[..., Any],
) -> Any:
    instructions = build_instructions(target_locale)
    prompt = build_prompt(
        text=text,
        target_locale=target_locale,
        source_locale=source_locale,
    )
    cwd = cwd_provider()
    effort = effort_provider()
    service_tier = service_tier_provider()
    log_info(
        "Streaming Zotero Codex translation model=%s cwd=%s chars=%d target=%s",
        model,
        cwd,
        len(text),
        target_locale,
    )
    # One-shot: no existing_thread_id, no thread save. The pool still reuses
    # the initialized app-server client across calls, but each translation gets
    # a fresh ephemeral thread that is never persisted.
    yield from pool_factory().stream_turn(
        cwd=cwd,
        instructions=instructions,
        existing_thread_id=None,
        prompt=prompt,
        model=model,
        effort=effort,
        service_tier=service_tier,
        image_urls=None,
    )
