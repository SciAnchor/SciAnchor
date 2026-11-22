"""FastAPI route registration for Zotero Codex warmup endpoint."""

from pathlib import Path
from typing import Any, Callable

from fastapi import BackgroundTasks, FastAPI, Request


def register_zotero_warmup_routes(
    app: FastAPI,
    *,
    zotero_warmup_request_model: type[Any],
    require_zotero_chat_token: Callable[[Request], None],
    zotero_codex_cwd: Callable[[], Path],
    zotero_codex_effort: Callable[[], str],
    zotero_codex_translate_effort: Callable[[], str],
    zotero_codex_service_tier: Callable[[], str | None],
    warm_zotero_codex_pool: Callable[..., None],
) -> None:
    """Register the local Zotero Codex app-server warmup route."""

    @app.post("/api/zotero/warmup", status_code=202)
    def zotero_warmup(
        body: zotero_warmup_request_model,
        background_tasks: BackgroundTasks,
        request: Request,
    ):
        """Pre-initialize the local Codex app-server used by Zotero chat."""

        require_zotero_chat_token(request)
        cwd = zotero_codex_cwd()
        effort = zotero_codex_effort()
        service_tier = zotero_codex_service_tier()
        background_tasks.add_task(
            warm_zotero_codex_pool,
            cwd=cwd,
            model=body.model,
            effort=effort,
            service_tier=service_tier,
        )

        translate_effort = zotero_codex_translate_effort()
        warmed_extra: list[str] = []
        for extra_model in body.extra_models:
            if extra_model == body.model and translate_effort == effort:
                continue
            background_tasks.add_task(
                warm_zotero_codex_pool,
                cwd=cwd,
                model=extra_model,
                effort=translate_effort,
                service_tier=service_tier,
            )
            warmed_extra.append(extra_model)
        return {
            "status": "warming",
            "model": body.model,
            "extra_models": warmed_extra,
            "cwd": str(cwd),
            "effort": effort,
            "translate_effort": translate_effort,
            "service_tier": service_tier,
        }
