"""FastAPI route registration for Zotero seed-paper apply endpoint."""

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


def register_zotero_seed_apply_routes(
    app: FastAPI,
    *,
    zotero_seed_paper_apply_request_model: type[Any],
    require_zotero_chat_token: Callable[[Request], None],
    get_db_context: Callable[[], Any],
    db_path_provider: Callable[[], Any],
    last_zotero_path_segment: Callable[[str], str],
    get_or_create_zotero_seed_topic: Callable[..., tuple[int, bool]],
    research_api_factory: Callable[[], Any],
    find_paper_id_in_topic_by_source: Callable[[Any, int, str], int | None],
    ingest_paper_impl: Callable[..., dict[str, Any]],
    deep_read_paper_impl: Callable[..., dict[str, Any]],
    run_tool: Callable[[str, dict[str, Any]], dict[str, Any]],
    apply_rh_pdf_annotations_for_papers: Callable[..., list[dict[str, Any]]],
    zotero_api_library_id: Callable[[str | int | None, str], str],
    create_zotero_write_client: Callable[..., tuple[Any, str]],
    build_zotero_workflow_receipt: Callable[..., dict[str, Any]],
    zotero_sync_service_factory: Callable[..., Any],
    env_get: Callable[[str, str], str],
    build_zotero_phase_b_gate_evidence: Callable[
        ..., dict[str, Any]
    ] = _default_phase_b_gate_evidence,
) -> None:
    """Register the explicit Zotero seed-paper confirmation route."""

    @app.post("/api/zotero/seed-papers/apply")
    def apply_zotero_seed_papers(
        body: zotero_seed_paper_apply_request_model,
        request: Request,
    ):
        """Ingest previewed seed papers and push them to a Zotero collection."""

        require_zotero_chat_token(request)
        if not body.candidate_sources:
            raise HTTPException(status_code=400, detail="candidate_sources is required")
        if not body.target_collection_key:
            raise HTTPException(
                status_code=400, detail="target_collection_key is required"
            )
        sandbox_sync_enabled = _zotero_sandbox_sync_enabled(env_get)
        if not body.dry_run and not sandbox_sync_enabled:
            raise HTTPException(
                status_code=400,
                detail=REAL_ZOTERO_SYNC_DEFERRED_DETAIL,
            )
        parent_collection_key = (
            body.parent_collection_key
            or ("" if body.target_is_topic_collection else body.target_collection_key)
        ).strip()

        topic_name = (
            body.topic_name
            or last_zotero_path_segment(body.target_collection_path)
            or body.target_collection_name
            or body.query
        ).strip()
        if not topic_name:
            raise HTTPException(
                status_code=400, detail="topic_name could not be inferred"
            )

        library_type = body.library_type or env_get("ZOTERO_LIBRARY_TYPE", "user")
        library_id = zotero_api_library_id(body.library_id, library_type)
        client = None
        if not body.dry_run:
            try:
                client, library_id = create_zotero_write_client(
                    library_id=library_id,
                    library_type=library_type,
                    api_key=env_get("ZOTERO_API_KEY", ""),
                    api_base=env_get("ZOTERO_API_BASE", ""),
                    desktop_library_id=body.library_id,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if not _is_zotero_sandbox_client(client):
                raise HTTPException(
                    status_code=400,
                    detail=SANDBOX_ZOTERO_SYNC_DETAIL,
                )
        sandbox_adapter = bool(client and _is_zotero_sandbox_client(client))

        topic_id, created_topic = get_or_create_zotero_seed_topic(
            topic_id=body.topic_id,
            topic_name=topic_name,
            description=body.topic_description
            or (
                "Created from Zotero collection bootstrap.\n\n"
                f"Initial query: {body.query}\n"
                f"Collection: {body.target_collection_path or body.target_collection_name}"
            ),
        )

        api = research_api_factory()
        paper_ids: list[int] = []
        ingest_errors: list[dict[str, str]] = []
        for source in body.candidate_sources:
            with get_db_context() as conn:
                existing_id = find_paper_id_in_topic_by_source(conn, topic_id, source)
            if existing_id:
                paper_ids.append(existing_id)
                continue
            try:
                ingest_out = ingest_paper_impl(
                    api,
                    source=source,
                    topic_id=topic_id,
                    relevance="high",
                )
                paper_id = int(ingest_out.get("paper_id", 0) or 0)
                if paper_id:
                    paper_ids.append(paper_id)
            except Exception as exc:  # pragma: no cover - provider failures vary
                ingest_errors.append({"source": source, "error": str(exc)[:1000]})

        paper_ids = list(dict.fromkeys(paper_ids))
        postprocess_errors: list[dict[str, str]] = []
        postprocess_warnings: list[str] = []
        pdf_annotation_receipts: list[dict[str, Any]] = []
        effective_request_pdf_attachment = (
            body.request_pdf_attachment or body.request_pdf_annotations
        )
        if paper_ids and not body.dry_run:
            sandbox_deferred_steps: list[str] = []
            if sandbox_adapter and effective_request_pdf_attachment:
                sandbox_deferred_steps.append("paper_acquire")
            if sandbox_adapter and body.request_deep_read:
                sandbox_deferred_steps.append("deep_read")
            if sandbox_adapter and body.request_pdf_annotations:
                sandbox_deferred_steps.append("pdf_annotations")
            if sandbox_deferred_steps:
                postprocess_warnings.append(
                    "sandbox seed apply deferred provider-backed postprocess "
                    f"steps: {', '.join(sandbox_deferred_steps)}"
                )
            if effective_request_pdf_attachment and not sandbox_adapter:
                try:
                    run_tool("paper_acquire", {"topic_id": topic_id})
                except Exception as exc:  # pragma: no cover - external providers vary
                    postprocess_errors.append(
                        {"step": "paper_acquire", "error": str(exc)[:1000]}
                    )
            if body.request_deep_read and not sandbox_adapter:
                for paper_id in paper_ids:
                    try:
                        deep_read_paper_impl(
                            api,
                            paper_id=paper_id,
                            topic_id=topic_id,
                            focus=body.query,
                        )
                    except Exception as exc:  # pragma: no cover - providers vary
                        postprocess_errors.append(
                            {
                                "step": "deep_read",
                                "paper_id": str(paper_id),
                                "error": str(exc)[:1000],
                            }
                        )
            if body.request_pdf_annotations and not sandbox_adapter:
                try:
                    pdf_annotation_receipts = apply_rh_pdf_annotations_for_papers(
                        paper_ids=paper_ids,
                        topic_id=topic_id,
                        topic_name=topic_name,
                        focus=body.query,
                    )
                except Exception as exc:  # pragma: no cover - defensive guard
                    postprocess_errors.append(
                        {"step": "pdf_annotations", "error": str(exc)[:1000]}
                    )

        push_result = None
        push_preview = None
        if paper_ids:
            service = zotero_sync_service_factory(
                db_path=db_path_provider(),
                client=client,
                library_id=library_id,
                library_type=library_type,
            )
            sync_kwargs = {
                "topic_collection_name": topic_name,
                "target_collection_key": body.target_collection_key
                if body.target_is_topic_collection
                else None,
                "parent_collection_key": parent_collection_key,
                "include_notes": True,
                "paper_ids": paper_ids,
            }
            if not body.dry_run:
                push_preview = service.sync_topic(
                    topic_name,
                    dry_run=True,
                    **sync_kwargs,
                )
            push_result = service.sync_topic(
                topic_name,
                dry_run=body.dry_run,
                **sync_kwargs,
            )
            if body.dry_run:
                push_preview = push_result
        workflow_receipt = build_zotero_workflow_receipt(
            action_type="zotero_seed_paper_search",
            topic_id=topic_id,
            topic_name=topic_name,
            push_result=push_result,
            target_collection_key="",
            parent_collection_key=parent_collection_key,
            target_collection_name=topic_name,
            target_collection_path=(
                f"{body.target_collection_path} / {topic_name}"
                if body.target_collection_path
                else topic_name
            ),
            include_notes=True,
            request_deep_read=body.request_deep_read,
            request_pdf_attachment=effective_request_pdf_attachment,
            request_pdf_annotations=body.request_pdf_annotations,
            dry_run=body.dry_run,
            ingest_errors=ingest_errors,
            postprocess_errors=postprocess_errors,
            postprocess_warnings=postprocess_warnings,
            pdf_annotation_receipts=pdf_annotation_receipts,
        )
        phase_b_gate_evidence = None
        if sandbox_adapter or not body.dry_run:
            phase_b_gate_evidence = build_zotero_phase_b_gate_evidence(
                action_type="zotero_seed_paper_search",
                topic_id=topic_id,
                topic_name=topic_name,
                direction="push",
                dry_run=body.dry_run,
                sandbox_adapter=sandbox_adapter,
                push_preview=push_preview,
                push_result=push_result,
                workflow_receipt=workflow_receipt,
                candidate_sources_count=len(body.candidate_sources),
                paper_ids=paper_ids,
            )

        output = {
            "topic_id": topic_id,
            "topic_name": topic_name,
            "created_topic": created_topic,
            "query": body.query,
            "paper_ids": paper_ids,
            "ingested_count": len(paper_ids),
            "ingest_errors": ingest_errors,
            "postprocess_errors": postprocess_errors,
            "pdf_annotation_receipts": pdf_annotation_receipts,
            "push": push_result.to_dict() if push_result is not None else None,
            "workflow_receipt": workflow_receipt,
        }
        if postprocess_warnings:
            output["postprocess_warnings"] = postprocess_warnings
        if phase_b_gate_evidence is not None:
            output["phase_b_gate_evidence"] = phase_b_gate_evidence

        return {
            "status": "success",
            "summary": f"Seed papers applied to topic {topic_id}",
            "output": output,
        }
