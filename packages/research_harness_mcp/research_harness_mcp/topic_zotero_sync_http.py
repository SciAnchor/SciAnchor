"""FastAPI route registration for topic Zotero sync endpoint."""

from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request
from research_harness_mcp.zotero_workflow_receipt import (
    build_zotero_phase_b_gate_evidence as _default_phase_b_gate_evidence,
)


REAL_ZOTERO_SYNC_DEFERRED_DETAIL = (
    "real Zotero sync/apply is deferred; stable Zotero routing only "
    "supports direction=push with dry_run=true"
)
SANDBOX_ZOTERO_SYNC_DETAIL = (
    "Phase B Zotero sync/apply evidence is local fake/sandbox only; set "
    "RESEARCH_HARNESS_ZOTERO_SANDBOX_SYNC=1 and inject a sandbox Zotero "
    "adapter. Real Zotero network sync/apply remains deferred."
)


def _truthy_env(value: str) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _zotero_sandbox_sync_enabled(env_get: Callable[[str, str], str]) -> bool:
    return _truthy_env(env_get("RESEARCH_HARNESS_ZOTERO_SANDBOX_SYNC", ""))


def _is_zotero_sandbox_client(client: Any) -> bool:
    return bool(
        getattr(client, "is_sandbox", False)
        or getattr(client, "sandbox", False)
        or getattr(client, "sandbox_mode", False)
    )


def register_topic_zotero_sync_routes(
    app: FastAPI,
    *,
    zotero_sync_request_model: type[Any],
    require_zotero_chat_token: Callable[[Request], None],
    get_db_context: Callable[[], Any],
    db_path_provider: Callable[[], Any],
    zotero_api_library_id: Callable[[str | int | None, str], str],
    create_zotero_write_client: Callable[..., tuple[Any, str]],
    build_zotero_workflow_receipt: Callable[..., dict[str, Any]],
    zotero_sync_service_factory: Callable[..., Any],
    env_get: Callable[[str, str], str],
    build_zotero_phase_b_gate_evidence: Callable[
        ..., dict[str, Any]
    ] = _default_phase_b_gate_evidence,
) -> None:
    """Register the topic-level Zotero sync route with injected dependencies."""

    @app.post("/api/topics/{topic_id}/zotero-sync")
    def sync_topic_zotero(
        topic_id: int,
        body: zotero_sync_request_model,
        request: Request,
    ):
        """Synchronize a topic with Zotero via the HTTP API.

        Push dry-run is safe without Zotero credentials. Pull dry-run still
        needs Zotero read access because it previews actual Zotero content.
        """

        require_zotero_chat_token(request)

        with get_db_context() as conn:
            topic = conn.execute(
                "SELECT id, name FROM topics WHERE id = ?", (topic_id,)
            ).fetchone()
            if topic is None:
                raise HTTPException(status_code=404, detail="Topic not found")

        sandbox_sync_enabled = _zotero_sandbox_sync_enabled(env_get)
        if not body.dry_run and not sandbox_sync_enabled:
            raise HTTPException(
                status_code=400,
                detail=REAL_ZOTERO_SYNC_DEFERRED_DETAIL,
            )
        if (
            body.dry_run
            and body.direction in {"pull", "both"}
            and not sandbox_sync_enabled
        ):
            raise HTTPException(
                status_code=400,
                detail=(
                    "stable Zotero dry-run only supports direction=push; "
                    f"{body.direction} dry-run requires Zotero read access and "
                    "remains deferred"
                ),
            )

        library_type = body.library_type or env_get("ZOTERO_LIBRARY_TYPE", "user")
        library_id = zotero_api_library_id(body.library_id, library_type)
        client = None
        needs_zotero_client = (not body.dry_run) or body.direction in {"pull", "both"}
        if needs_zotero_client:
            try:
                client, library_id = create_zotero_write_client(
                    library_id=library_id,
                    library_type=library_type,
                    api_key=body.api_key or env_get("ZOTERO_API_KEY", ""),
                    api_base=body.api_base or env_get("ZOTERO_API_BASE", ""),
                    desktop_library_id=body.library_id,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if not _is_zotero_sandbox_client(client):
                raise HTTPException(
                    status_code=400,
                    detail=SANDBOX_ZOTERO_SYNC_DETAIL,
                )

        topic_name = topic["name"]
        service = zotero_sync_service_factory(
            db_path=db_path_provider(),
            client=client,
            library_id=library_id,
            library_type=library_type,
        )
        push_result = None
        pull_result = None
        push_preview = None
        pull_preview = None
        push_kwargs = {
            "root_collection": body.root_collection,
            "topic_collection_name": body.topic_collection_name
            or body.target_collection_name,
            "target_collection_key": body.target_collection_key,
            "parent_collection_key": body.parent_collection_key,
            "include_notes": not body.skip_notes,
            "limit": body.limit,
            "force": body.force,
            "paper_ids": body.paper_ids,
        }
        pull_kwargs = {
            "limit": body.limit,
            "include_rh_generated": body.include_rh_generated,
        }
        if not body.dry_run and body.direction in {"push", "both"}:
            push_preview = service.sync_topic(
                topic_name,
                dry_run=True,
                **push_kwargs,
            )
        if not body.dry_run and body.direction == "pull":
            pull_preview = service.pull_topic(
                topic_name,
                dry_run=True,
                **pull_kwargs,
            )
        if body.direction in {"push", "both"}:
            push_result = service.sync_topic(
                topic_name,
                dry_run=body.dry_run,
                **push_kwargs,
            )
            if body.dry_run:
                push_preview = push_result
        if body.direction in {"pull", "both"}:
            if not body.dry_run and pull_preview is None:
                pull_preview = service.pull_topic(
                    topic_name,
                    dry_run=True,
                    **pull_kwargs,
                )
            pull_result = service.pull_topic(
                topic_name,
                dry_run=body.dry_run,
                **pull_kwargs,
            )
            if body.dry_run:
                pull_preview = pull_result

        workflow_receipt = (
            build_zotero_workflow_receipt(
                action_type="sync_rh_papers_to_collection",
                topic_id=topic_id,
                topic_name=topic_name,
                push_result=push_result,
                target_collection_key=body.target_collection_key,
                parent_collection_key=body.parent_collection_key,
                target_collection_name=body.target_collection_name
                or body.topic_collection_name
                or topic_name,
                target_collection_path=body.target_collection_path or "",
                include_notes=not body.skip_notes,
                request_deep_read=False,
                request_pdf_attachment=False,
                request_pdf_annotations=False,
            )
            if push_result is not None
            else None
        )
        sandbox_adapter = bool(client and _is_zotero_sandbox_client(client))
        phase_b_gate_evidence = None
        if sandbox_adapter or (not body.dry_run) or body.direction in {"pull", "both"}:
            phase_b_gate_evidence = build_zotero_phase_b_gate_evidence(
                action_type="sync_rh_papers_to_collection",
                topic_id=topic_id,
                topic_name=topic_name,
                direction=body.direction,
                dry_run=body.dry_run,
                sandbox_adapter=sandbox_adapter,
                push_preview=push_preview,
                pull_preview=pull_preview,
                push_result=push_result,
                pull_result=pull_result,
                workflow_receipt=workflow_receipt,
                paper_ids=body.paper_ids,
            )

        output = {
            "topic_id": topic_id,
            "topic": topic_name,
            "direction": body.direction,
            "dry_run": body.dry_run,
            "push": push_result.to_dict() if push_result is not None else None,
            "pull": pull_result.to_dict() if pull_result is not None else None,
            "workflow_receipt": workflow_receipt,
        }
        if phase_b_gate_evidence is not None:
            output["phase_b_gate_evidence"] = phase_b_gate_evidence

        return {
            "status": "success",
            "summary": f"Zotero {body.direction} sync completed for topic {topic_id}",
            "output": output,
        }
