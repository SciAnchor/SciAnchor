"""FastAPI route registration for Zotero translation streaming endpoint."""

import logging
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse


logger = logging.getLogger(__name__)


def register_zotero_translate_routes(
    app: FastAPI,
    *,
    zotero_translate_request_model: type[Any],
    require_zotero_chat_token: Callable[[Request], None],
    stream_zotero_codex_translate: Callable[..., Any],
    sse_encode: Callable[[str, dict[str, Any]], str],
) -> None:
    """Register the lightweight one-shot Zotero translation stream route."""

    @app.post("/api/zotero/translate/stream")
    def zotero_translate_stream(
        body: zotero_translate_request_model,
        request: Request,
    ):
        """Stream a lightweight Codex translation for selected text."""

        require_zotero_chat_token(request)
        return StreamingResponse(
            _zotero_translate_sse_stream(
                body=body,
                stream_zotero_codex_translate=stream_zotero_codex_translate,
                sse_encode=sse_encode,
            ),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )


def _zotero_translate_sse_stream(
    *,
    body: Any,
    stream_zotero_codex_translate: Callable[..., Any],
    sse_encode: Callable[[str, dict[str, Any]], str],
):
    full_text: list[str] = []
    yield sse_encode(
        "ready",
        {
            "model": body.model,
            "target_locale": body.target_locale,
            "source_chars": len(body.text),
        },
    )
    try:
        for event in stream_zotero_codex_translate(
            text=body.text,
            model=body.model,
            target_locale=body.target_locale,
            source_locale=body.source_locale,
        ):
            event_data = dict(event.data)
            if event.event == "delta":
                text = str(event_data.get("text") or "")
                if text:
                    full_text.append(text)
                yield sse_encode("delta", {"text": text})
            elif event.event == "done":
                yield sse_encode(
                    "done",
                    {
                        "model": body.model,
                        "assistant_message": "".join(full_text),
                    },
                )
            elif event.event in {"started", "status"}:
                yield sse_encode(event.event, event_data)
    except Exception as exc:  # pragma: no cover - Codex host failures vary
        logger.exception("Zotero Codex translate stream failed")
        yield sse_encode(
            "error",
            {"message": str(exc), "model": body.model},
        )
