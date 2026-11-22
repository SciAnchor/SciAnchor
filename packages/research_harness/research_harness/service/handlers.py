"""Read-only service handlers used by the initial dispatcher skeleton."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research_harness._productization import build_lg10_productization_boundary_payload
from research_harness._selfdev.writing_logic_gate_runtime import (
    section_draft_logic_gate_block,
)
from research_harness.advisory import AdvisoryEngine
from research_harness.config import find_workspace_root
from research_harness.execution.factory import create_backend
from research_harness.execution.tracked import TrackedBackend
from research_harness.knowledge.cross_topic_atlas import (
    CrossTopicAtlasUnavailable,
    build_cross_topic_knowledge_atlas_payload_from_db,
)
from research_harness.knowledge.knowledge_status import (
    KnowledgeStatusUnavailable,
    build_knowledge_status_payload_from_db,
)
from research_harness.knowledge.topic_refresh import (
    refresh_all_topic_knowledge,
    refresh_topic_knowledge,
    topic_exists,
)
from research_harness.knowledge.wiki_context_pack import (
    build_wiki_context_pack_payload_from_db,
)
from research_harness.orchestrator import OrchestratorService
from research_harness.orchestrator.stages import resolve_stage
from research_harness.primitives.types import PrimitiveResult
from research_harness.provenance.recorder import ProvenanceRecorder
from research_harness.skill import (
    build_manifest,
    find_repo_root,
    load_manifest,
    resolve_skill_track_path,
)

from .primitive_contract import primitive_result_to_service_result
from .types import ServiceContext, ServiceResult


LOGGER = logging.getLogger(__name__)

run_codex_review: Any = None
codex_issues_to_objections: Any = None
zotero_resource: Any = None
ZoteroSyncService: Any = None
DEFAULT_ROOT_COLLECTION = "Research Harness"


def topic_list(ctx: ServiceContext, arguments: dict[str, Any]) -> dict[str, Any]:
    del arguments
    conn = ctx.db.connect()
    try:
        rows = conn.execute(
            """
            SELECT
                t.*,
                d.name AS domain_name,
                COUNT(pt.paper_id) AS paper_count
            FROM topics t
            LEFT JOIN domains d ON d.id = t.domain_id
            LEFT JOIN paper_topics pt ON pt.topic_id = t.id
            GROUP BY t.id
            ORDER BY t.created_at DESC, t.id DESC
            """
        ).fetchall()
        return {"topics": [_with_freshness(dict(row)) for row in rows]}
    finally:
        conn.close()


def _resolve_topic_id(conn: Any, topic: Any) -> int | None:
    """Resolve a topic name or numeric ID to a topic id (name wins on collision).

    Agents routinely pass numeric IDs from ``topic list``; matching by name
    only makes ``topic show 50`` fail while ``topic list`` displays id 50.
    """
    value = str(topic).strip()
    row = conn.execute(
        """
        SELECT id FROM topics
        WHERE name = ? OR id = CAST(? AS INTEGER)
        ORDER BY (name = ?) DESC
        LIMIT 1
        """,
        (value, value, value),
    ).fetchone()
    return int(row["id"]) if row else None


def topic_show(ctx: ServiceContext, arguments: dict[str, Any]) -> dict[str, Any]:
    conn = ctx.db.connect()
    try:
        topic_id = _resolve_topic_id(conn, arguments["name"])
        if topic_id is None:
            return {"error": f"Topic not found: {arguments['name']}"}
        row = conn.execute(
            """
            SELECT
                t.*,
                d.name AS domain_name,
                COUNT(pt.paper_id) AS paper_count
            FROM topics t
            LEFT JOIN domains d ON d.id = t.domain_id
            LEFT JOIN paper_topics pt ON pt.topic_id = t.id
            WHERE t.id = ?
            GROUP BY t.id
            """,
            (topic_id,),
        ).fetchone()
        if row is None:
            return {"error": f"Topic not found: {arguments['name']}"}
        return _with_freshness(dict(row))
    finally:
        conn.close()


def paper_list(ctx: ServiceContext, arguments: dict[str, Any]) -> dict[str, Any]:
    topic = arguments.get("topic")
    # BUG-011: paper_list used to return the entire pool (or whole topic) in one
    # unbounded response, which for large pools produced a huge payload that timed
    # out the MCP call. Opt-in limit/offset pagination lets callers bound the
    # response; omitting them preserves the original "return everything" shape.
    raw_limit = arguments.get("limit")
    try:
        limit = int(raw_limit) if raw_limit is not None else None
    except (TypeError, ValueError):
        limit = None
    try:
        offset = max(0, int(arguments.get("offset") or 0))
    except (TypeError, ValueError):
        offset = 0

    conn = ctx.db.connect()
    try:
        if topic:
            topic_id = _resolve_topic_id(conn, topic)
            if topic_id is None:
                return {"error": f"Topic not found: {topic}"}
            total = int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM paper_topics WHERE topic_id = ?",
                    (topic_id,),
                ).fetchone()["n"]
            )
            sql = (
                "SELECT p.*, pt.relevance FROM papers p "
                "JOIN paper_topics pt ON p.id = pt.paper_id "
                "WHERE pt.topic_id = ? ORDER BY p.created_at DESC, p.id DESC"
            )
            params: list[Any] = [topic_id]
        else:
            total = int(
                conn.execute("SELECT COUNT(*) AS n FROM papers").fetchone()["n"]
            )
            sql = "SELECT p.* FROM papers p ORDER BY p.created_at DESC, p.id DESC"
            params = []

        if limit is not None and limit >= 0:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])

        rows = conn.execute(sql, params).fetchall()
        result: dict[str, Any] = {
            "papers": [_paper_row_to_dict(row) for row in rows],
            "total": total,
        }
        if limit is not None:
            result["limit"] = limit
            result["offset"] = offset
            result["has_more"] = offset + len(rows) < total
        return result
    finally:
        conn.close()


def job_status(ctx: ServiceContext, arguments: dict[str, Any]) -> dict[str, Any]:
    """Poll a background job's status/progress/result (BUG-011)."""
    from research_harness.jobs import get_job_status

    job_id = str(arguments.get("job_id") or "").strip()
    if not job_id:
        return {"error": "job_id is required"}
    status = get_job_status(ctx.db, job_id)
    if status is None:
        return {"error": f"Unknown job_id: {job_id}"}
    return status


def provenance_summary(
    ctx: ServiceContext, arguments: dict[str, Any]
) -> dict[str, Any]:
    recorder = ProvenanceRecorder(ctx.db)
    topic_id = arguments.get("topic_id")
    summary = recorder.summarize(topic_id=topic_id)
    return asdict(summary)


def provenance_export(ctx: ServiceContext, arguments: dict[str, Any]) -> dict[str, Any]:
    fmt = arguments.get("format", "json")
    if fmt != "json":
        return {"error": f"Unsupported format: {fmt}"}

    recorder = ProvenanceRecorder(ctx.db)
    topic_id = arguments.get("topic_id")
    records = recorder.list_records(topic_id=topic_id, limit=10000)
    return {"format": fmt, "records": [asdict(record) for record in records]}


def resource_ready_get(
    ctx: ServiceContext, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Fetch the single active SPC resource-ready binding for a topic/workflow/host."""
    from research_harness.acquisition.resource_ready import (
        compute_binding_key,
        get_ready,
        ready_status_summary,
    )

    topic_id = arguments["topic_id"]
    workflow_ref = arguments["workflow_ref"]
    host_id = arguments["host_id"]
    result = get_ready(ctx.db, topic_id, workflow_ref, host_id)
    if result is None:
        return {
            "found": False,
            "binding_key": compute_binding_key(topic_id, workflow_ref, host_id),
            "workflow_ref": workflow_ref,
            "host_id": host_id,
        }
    return ready_status_summary(result)


def orchestrator_status(
    ctx: ServiceContext, arguments: dict[str, Any]
) -> dict[str, Any]:
    svc = OrchestratorService(ctx.db)
    status = svc.get_status(arguments["topic_id"])
    return dict(status)


def orchestrator_gate_check(
    ctx: ServiceContext, arguments: dict[str, Any]
) -> dict[str, Any]:
    stage = arguments.get("stage")
    details = OrchestratorService(ctx.db).check_gate_details(
        arguments["topic_id"],
        stage=resolve_stage(stage) if stage else None,
    )
    return dict(details)


def orchestrator_resume(
    ctx: ServiceContext, arguments: dict[str, Any]
) -> dict[str, Any]:
    svc = OrchestratorService(ctx.db)
    force_stage = arguments.get("force_stage")
    if force_stage:
        force_stage = resolve_stage(force_stage)
    stop_before = arguments.get("stop_before")
    if stop_before:
        stop_before = resolve_stage(stop_before)

    run = svc.resume_run(
        topic_id=arguments["topic_id"],
        mode=arguments.get("mode", "standard"),
        force_stage=force_stage,
        stop_before=stop_before,
    )
    inferred = svc.infer_stage_from_artifacts(arguments["topic_id"])
    result = {
        "success": True,
        "run_id": run.id,
        "topic_id": run.topic_id,
        "current_stage": run.current_stage,
        "inferred_stage": inferred,
        "stage_status": run.stage_status,
    }
    if run.stop_before:
        result["stop_before"] = run.stop_before
    return result


def orchestrator_advance(
    ctx: ServiceContext, arguments: dict[str, Any]
) -> dict[str, Any]:
    return OrchestratorService(ctx.db).advance(
        arguments["topic_id"],
        actor=arguments.get("actor", "system"),
    )


def orchestrator_record_artifact(
    ctx: ServiceContext, arguments: dict[str, Any]
) -> dict[str, Any]:
    stage = resolve_stage(arguments["stage"])
    artifact = OrchestratorService(ctx.db).record_artifact(
        topic_id=arguments["topic_id"],
        stage=stage,
        artifact_type=arguments["artifact_type"],
        title=arguments.get("title", ""),
        payload=arguments.get("payload"),
        dependency_artifact_ids=arguments.get("dependency_artifact_ids"),
        dependency_type=arguments.get("dependency_type", "consumed_by"),
    )
    return {
        "success": True,
        "artifact_id": artifact.id,
        "version": artifact.version,
        "stage": artifact.stage,
        "type": artifact.artifact_type,
    }


def paper_commit_version(
    ctx: ServiceContext, arguments: dict[str, Any]
) -> dict[str, Any]:
    stage = resolve_stage(arguments.get("stage", "write"))
    return OrchestratorService(ctx.db).commit_manuscript_version(
        topic_id=arguments["topic_id"],
        tex_path=arguments["tex_path"],
        pdf_path=arguments.get("pdf_path", ""),
        stage=stage,
        title=arguments.get("title", ""),
        quality_report=arguments.get("quality_report"),
        dependency_artifact_ids=arguments.get("dependency_artifact_ids"),
        notes=arguments.get("notes", ""),
        force_reason=arguments.get("force_reason", ""),
    )


def topic_init(ctx: ServiceContext, arguments: dict[str, Any]) -> dict[str, Any]:
    from research_harness.auto_runner import hitl_commands

    return hitl_commands.topic_init(
        ctx.db,
        name=arguments["name"],
        description=arguments.get("description", ""),
        tags=arguments.get("tags"),
    )


def paper_production_start(
    ctx: ServiceContext, arguments: dict[str, Any]
) -> dict[str, Any]:
    from research_harness.auto_runner import hitl_commands

    return hitl_commands.paper_production_start(
        ctx.db,
        topic_id=arguments["topic_id"],
        target_venue=arguments["target_venue"],
        interaction_mode=arguments.get("interaction_mode", "checkpoint"),
        paper_mode=arguments.get("paper_mode", "main"),
        budget=float(arguments.get("budget", 100.0)),
        local_only=bool(arguments.get("local_only", False)),
    )


def paper_production_pending_decisions(
    ctx: ServiceContext, arguments: dict[str, Any]
) -> dict[str, Any]:
    from research_harness.auto_runner import hitl_commands

    del ctx  # checkpoint-file based; no db access needed
    return hitl_commands.paper_production_pending_decisions(arguments["topic_id"])


def paper_production_decide(
    ctx: ServiceContext, arguments: dict[str, Any]
) -> dict[str, Any]:
    from research_harness.auto_runner import hitl_commands

    return hitl_commands.paper_production_decide(
        ctx.db,
        topic_id=arguments["topic_id"],
        choice=arguments["choice"],
        reasoning=arguments.get("reasoning", ""),
    )


def paper_production_status(
    ctx: ServiceContext, arguments: dict[str, Any]
) -> dict[str, Any]:
    from research_harness.auto_runner import hitl_commands

    return hitl_commands.paper_production_status(ctx.db, topic_id=arguments["topic_id"])


def topic_state(ctx: ServiceContext, arguments: dict[str, Any]) -> dict[str, Any]:
    from research_harness.auto_runner.topic_state import topic_state as topic_state_core

    payload = topic_state_core(ctx.db, topic=arguments["topic_id"])
    next_action = payload.get("next_action") or {}
    status = "success" if isinstance(payload.get("topic"), dict) else "error"
    return {
        "status": status,
        "summary": str(next_action.get("summary") or "topic state collected"),
        "output": payload,
        "next_actions": [str(item) for item in next_action.get("commands") or []],
    }


def paper_production_resume(
    ctx: ServiceContext, arguments: dict[str, Any]
) -> dict[str, Any]:
    from research_harness.auto_runner import hitl_commands

    return hitl_commands.paper_production_resume(
        ctx.db,
        topic_id=arguments["topic_id"],
        auto_approve=bool(arguments.get("auto_approve", False)),
    )


def paper_production_mode(
    ctx: ServiceContext, arguments: dict[str, Any]
) -> dict[str, Any]:
    from research_harness.auto_runner import hitl_commands

    del ctx
    return hitl_commands.paper_production_mode(arguments["topic_id"])


def paper_production_set_mode(
    ctx: ServiceContext, arguments: dict[str, Any]
) -> dict[str, Any]:
    from research_harness.auto_runner import hitl_commands

    del ctx
    return hitl_commands.paper_production_set_mode(
        arguments["topic_id"], mode=arguments["mode"]
    )


def paper_production_export(
    ctx: ServiceContext, arguments: dict[str, Any]
) -> dict[str, Any]:
    from research_harness.auto_runner import hitl_commands

    return hitl_commands.paper_production_export(
        ctx.db,
        topic_id=arguments["topic_id"],
        format=arguments.get("format", "both"),
        include_artifacts=bool(arguments.get("include_artifacts", True)),
    )


def paper_task_intake(ctx: ServiceContext, arguments: dict[str, Any]) -> dict[str, Any]:
    from research_harness.auto_runner.paper_production_entry import (
        prepare_paper_production_entry,
    )

    return prepare_paper_production_entry(
        db=ctx.db,
        topic=arguments["task"],
        target_venue=arguments["target_venue"],
        mode=arguments.get("mode", "standard"),
        local_only=bool(arguments.get("local_only", False)),
    )


def adversarial_review(
    ctx: ServiceContext, arguments: dict[str, Any]
) -> dict[str, Any]:
    svc = OrchestratorService(ctx.db)
    review_runner, issue_converter = _adversarial_review_helpers()

    topic_id = arguments["topic_id"]
    artifact_id = arguments["artifact_id"]
    focus = arguments.get("focus", "")
    evidence_summary = arguments.get("evidence_summary", "")

    run = svc.get_run(topic_id)
    if run is None:
        return {"success": False, "error": "No orchestrator run found for this topic"}

    artifact = svc._artifact_manager.get(artifact_id)
    if artifact is None:
        return {"success": False, "error": f"Artifact {artifact_id} not found"}

    artifact_content = json.dumps(artifact.payload, ensure_ascii=False, indent=2)[:3000]
    if evidence_summary:
        full_evidence = f"{evidence_summary}\n\nArtifact content:\n{artifact_content}"
    else:
        full_evidence = f"Artifact content:\n{artifact_content}"

    review = review_runner(
        artifact_path=Path(artifact.path)
        if artifact.path
        else Path(f"artifact_{artifact_id}"),
        stage=run.current_stage,
        focus=focus or f"Review {artifact.artifact_type} artifact",
        evidence_summary=full_evidence,
    )
    if not review.get("success"):
        return {
            "success": False,
            "error": f"Adversarial review failed: {review.get('error', 'unknown')}",
            "backend": review.get("backend", "unknown"),
        }

    objections = issue_converter(review.get("issues", []))
    proposal_snapshot = {
        "artifact_id": artifact_id,
        "artifact_type": artifact.artifact_type,
        "stage": artifact.stage,
        "title": artifact.title,
        "content_preview": artifact_content[:1000],
    }
    round_result = svc.run_adversarial_round(
        topic_id=topic_id,
        target_artifact_id=artifact_id,
        proposal_snapshot=proposal_snapshot,
        objections=[
            {
                "category": objection.get("category", "general"),
                "severity": objection.get("severity", "minor"),
                "target": objection.get("target", ""),
                "reasoning": objection.get("reasoning", ""),
                "suggested_fix": objection.get("suggested_fix", ""),
            }
            for objection in objections
        ],
    )

    scores = review.get("scores", {})
    if scores and round_result.get("success"):
        resolve_result = svc.resolve_adversarial_round(
            topic_id=topic_id,
            round_artifact_id=round_result["artifact_id"],
            scores=scores,
            notes=review.get("notes", ""),
        )
    else:
        resolve_result = {}

    return {
        "success": True,
        "verdict": review.get("verdict", ""),
        "issues_count": len(objections),
        "critical_count": sum(
            1 for objection in objections if objection.get("severity") == "critical"
        ),
        "major_count": sum(
            1 for objection in objections if objection.get("severity") == "major"
        ),
        "scores": scores,
        "notes": review.get("notes", ""),
        "round_artifact_id": round_result.get("artifact_id"),
        "resolution_artifact_id": resolve_result.get("artifact_id"),
        "backend": review.get("backend", "unknown"),
        "model": review.get("model", ""),
        "stage": run.current_stage,
    }


def advisory_check(ctx: ServiceContext, arguments: dict[str, Any]) -> dict[str, Any]:
    engine = AdvisoryEngine(ctx.db)
    advisories = engine.run(topic_id=int(arguments["topic_id"]))
    return {
        "advisories": [asdict(item) for item in advisories],
        "count": len(advisories),
    }


def topic_knowledge_status(
    ctx: ServiceContext, arguments: dict[str, Any]
) -> dict[str, Any]:
    topic_id = int(arguments["topic_id"])
    try:
        return build_knowledge_status_payload_from_db(ctx.db, topic_id=topic_id)
    except KnowledgeStatusUnavailable as exc:
        return {
            "error": exc.public_message,
            "error_code": exc.code,
        }


def topic_knowledge_refresh(
    ctx: ServiceContext, arguments: dict[str, Any]
) -> dict[str, Any]:
    if bool(arguments.get("all", False)):
        return refresh_all_topic_knowledge(ctx.db)

    topic_id = arguments.get("topic_id")
    if topic_id is None:
        return {
            "error": "topic_id is required unless all=true",
            "error_code": "INVALID_ARGUMENT",
        }

    topic_id = int(topic_id)
    if not topic_exists(ctx.db, topic_id):
        return {
            "error": f"topic {topic_id} not found",
            "error_code": "topic_not_found",
        }

    result = refresh_topic_knowledge(ctx.db, topic_id=topic_id)
    if result.get("status") == "failed":
        return {
            "error": f"topic knowledge refresh failed for topic {topic_id}",
            "error_code": "topic_knowledge_refresh_failed",
            **result,
        }
    return result


def wiki_context_pack(ctx: ServiceContext, arguments: dict[str, Any]) -> dict[str, Any]:
    topic_id = int(arguments["topic_id"])
    if not topic_exists(ctx.db, topic_id):
        return {
            "schema_version": "wiki_context_pack.v1",
            "topic_id": topic_id,
            "paper_wiki_status": "unavailable",
            "status_reason": "topic_not_found",
            "unavailable_reasons": [f"topic {topic_id} not found"],
            "warnings": [],
            "preflight": {
                "priority_evidence_layer": "",
                "fallback_allowed": True,
                "fallback_must_be_declared": True,
            },
            "pages": [],
        }

    return build_wiki_context_pack_payload_from_db(
        ctx.db,
        topic_id=topic_id,
        query=str(arguments.get("query") or "").strip(),
        action_name=str(arguments.get("action_name") or "").strip(),
        anchor_paper_id=arguments.get("anchor_paper_id"),
        max_pages=int(arguments.get("max_pages", 8)),
        max_anchors=int(arguments.get("max_anchors", 24)),
    )


def delivery_paper_production_snapshot(
    ctx: ServiceContext,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    from research_harness._selfdev.delivery_protocol import (
        build_delivery_paper_production_snapshot,
        build_default_delivery_protocol_fixture,
    )

    topic_id = arguments.get("topic_id")
    artifact_states = arguments.get("artifact_states")
    payloads = arguments.get("payloads")
    explicit_artifact_states = (
        dict(artifact_states) if isinstance(artifact_states, Mapping) else {}
    )
    topic_artifact_states = _load_delivery_artifact_states_from_topic(ctx, topic_id)
    resolved_artifact_states = _merge_delivery_artifact_states(
        topic_artifact_states,
        explicit_artifact_states,
    )
    payload_inputs = dict(payloads) if isinstance(payloads, Mapping) else {}
    snapshot = build_delivery_paper_production_snapshot(
        build_default_delivery_protocol_fixture(),
        artifact_states=resolved_artifact_states,
        payloads=payload_inputs,
    )
    payload = snapshot.to_dict()
    return {
        "schema_version": "rh.delivery.paper_production_snapshot.v1",
        "status": payload["status"],
        "next_artifact": payload["next_artifact"],
        "next_action": payload["next_action"],
        "summary": payload["summary"],
        "records": payload["records"],
        "blockers": payload["blockers"],
        "dry_run": True,
        "inputs": _delivery_snapshot_input_summary(
            topic_id=topic_id,
            topic_states=topic_artifact_states,
            explicit_states=explicit_artifact_states,
            resolved_states=resolved_artifact_states,
            payloads=payload_inputs,
        ),
    }


def cross_topic_atlas(ctx: ServiceContext, arguments: dict[str, Any]) -> dict[str, Any]:
    topic_ids = tuple(dict.fromkeys(int(item) for item in arguments["topic_ids"]))
    if len(topic_ids) < 2:
        return {
            "error": "at least two distinct topic ids are required",
            "error_code": "invalid_topic_ids",
        }

    max_results = int(arguments.get("max_results", 10))
    try:
        return build_cross_topic_knowledge_atlas_payload_from_db(
            ctx.db,
            topic_ids=topic_ids,
            query=str(arguments.get("query") or "").strip(),
            max_results=max_results,
        )
    except CrossTopicAtlasUnavailable as exc:
        return {
            "error": exc.public_message,
            "error_code": exc.code,
        }


def _load_delivery_artifact_states_from_topic(
    ctx: ServiceContext,
    topic_id: Any,
) -> dict[str, str]:
    if topic_id is None:
        return {}

    states: dict[str, str] = {}
    for artifact in OrchestratorService(ctx.db).list_artifacts(int(topic_id)):
        artifact_name = _normalize_delivery_artifact_name(artifact.artifact_type)
        if artifact_name:
            states.setdefault(artifact_name, "stale" if artifact.stale else "active")
    return states


def _merge_delivery_artifact_states(
    topic_states: dict[str, str],
    explicit_states: dict[str, Any] | None,
) -> dict[str, str]:
    merged = {
        normalized_key: str(value)
        for key, value in topic_states.items()
        if (normalized_key := _normalize_delivery_artifact_name(key))
    }
    merged.update(
        {
            normalized_key: str(value)
            for key, value in (explicit_states or {}).items()
            if (normalized_key := _normalize_delivery_artifact_name(key))
        }
    )
    return merged


def _normalize_delivery_artifact_name(value: str) -> str:
    return str(value).strip().replace("-", "_").replace(" ", "_").upper()


def _delivery_snapshot_input_summary(
    *,
    topic_id: Any,
    topic_states: dict[str, str],
    explicit_states: dict[str, Any],
    resolved_states: dict[str, str],
    payloads: dict[str, Any],
) -> dict[str, Any]:
    topic_keys = _sorted_delivery_artifact_keys(topic_states)
    explicit_keys = _sorted_delivery_artifact_keys(explicit_states)
    resolved_keys = _sorted_delivery_artifact_keys(resolved_states)
    explicit_key_set = set(explicit_keys)
    return {
        "topic_id": int(topic_id) if topic_id is not None else None,
        "artifact_states": {
            "topic": topic_keys,
            "explicit": explicit_keys,
            "resolved": resolved_keys,
            "sources": {
                key: "explicit" if key in explicit_key_set else "topic"
                for key in resolved_keys
            },
        },
        "payloads": _sorted_delivery_artifact_keys(payloads),
        "counts": {
            "topic_artifact_states": len(topic_keys),
            "explicit_artifact_states": len(explicit_keys),
            "resolved_artifact_states": len(resolved_keys),
            "payloads": len(_sorted_delivery_artifact_keys(payloads)),
        },
    }


def _sorted_delivery_artifact_keys(values: Mapping[str, Any]) -> list[str]:
    return sorted(
        {
            normalized_key
            for key in values
            if (normalized_key := _normalize_delivery_artifact_name(key))
        }
    )


def paperindex_search(ctx: ServiceContext, arguments: dict[str, Any]) -> dict[str, Any]:
    del ctx
    from paperindex import PaperIndexer

    ws = find_workspace_root()
    library_root = str(ws / ".paperindex") if ws else ".paperindex"
    results = PaperIndexer().search(
        arguments["query"],
        library_root=library_root,
        limit=arguments.get("limit", 5),
    )
    return {"results": [result.to_dict() for result in results]}


def skill_list(ctx: ServiceContext, arguments: dict[str, Any]) -> dict[str, Any]:
    del ctx
    data = _manifest_dict()
    category = arguments.get("category")
    if category:
        return {
            **data,
            "skills": [
                skill for skill in data["skills"] if skill.get("category") == category
            ],
        }
    return data


def skill_get(ctx: ServiceContext, arguments: dict[str, Any]) -> dict[str, Any]:
    del ctx
    name = arguments.get("name")
    if not name:
        return {"error": "missing required argument: name"}

    root = _skills_root()
    try:
        manifest = load_manifest(root)
    except FileNotFoundError:
        manifest = build_manifest(root)

    record = manifest.get(name)
    if record is None:
        return {
            "error": f"unknown skill: {name}",
            "available": manifest.names(),
        }

    skill_md_path = root / record.skill_md
    try:
        skill_md_text = skill_md_path.read_text(encoding="utf-8")
    except OSError as exc:
        return {"error": f"could not read {skill_md_path}: {exc}"}

    response: dict[str, Any] = {
        "name": record.name,
        "path": record.path,
        "skill_md_path": record.skill_md,
        "description": record.description,
        "tracks": list(record.tracks),
        "content": skill_md_text,
    }

    track = arguments.get("track")
    if track:
        track_path = resolve_skill_track_path(root, record, track)
        if track_path is not None:
            response["track"] = {
                "name": track,
                "path": str(track_path.relative_to(root.resolve())),
                "content": track_path.read_text(encoding="utf-8"),
            }
        else:
            response["track_error"] = (
                f"track '{track}' not found for skill '{name}'; "
                f"available: {record.tracks}"
            )

    return response


def productization_boundary(
    ctx: ServiceContext, arguments: dict[str, Any]
) -> dict[str, Any]:
    del ctx
    if arguments.get("experimental_lg10") is not True:
        return {
            "error": "pass experimental_lg10=true to view the LG10 boundary",
            "code": "lg10_opt_in_required",
        }
    return build_lg10_productization_boundary_payload(scope="public-mcp-opt-in-preview")


def zotero_sync(ctx: ServiceContext, arguments: dict[str, Any]) -> dict[str, Any]:
    topic = str(arguments.get("topic") or "").strip()
    if not topic:
        return {"error": "topic is required"}

    direction = str(arguments.get("direction") or "push").strip()
    if direction not in {"push", "pull", "both"}:
        return {"error": "direction must be one of: push, pull, both"}

    dry_run = bool(arguments.get("dry_run", True))
    deferred_error = _zotero_stable_dry_run_deferred_error(
        direction=direction,
        dry_run=dry_run,
    )
    if deferred_error:
        return {"error": deferred_error}

    resource_module, sync_service_cls, root_collection = _zotero_sync_dependencies()

    library_id = str(arguments.get("library_id") or os.getenv("ZOTERO_LIBRARY_ID", ""))
    library_type = str(
        arguments.get("library_type") or os.getenv("ZOTERO_LIBRARY_TYPE", "user")
    )
    if library_type not in {"user", "group"}:
        return {"error": "library_type must be 'user' or 'group'"}

    client = None
    needs_zotero_client = (not dry_run) or direction in {"pull", "both"}
    if needs_zotero_client:
        client = resource_module.create_zotero_resource_from_env(
            library_id=library_id,
            library_type=library_type,
            api_key=str(arguments.get("api_key") or os.getenv("ZOTERO_API_KEY", "")),
            base_url=str(arguments.get("api_base") or os.getenv("ZOTERO_API_BASE", "")),
        )

    limit_value = arguments.get("limit")
    limit = int(limit_value) if limit_value is not None else None
    service = sync_service_cls(
        db_path=ctx.db.path,
        client=client,
        library_id=library_id,
        library_type=library_type,
    )

    push_result = None
    pull_result = None
    if direction in {"push", "both"}:
        push_result = service.sync_topic(
            topic,
            root_collection=str(arguments.get("root_collection") or root_collection),
            include_notes=not bool(arguments.get("skip_notes", False)),
            dry_run=dry_run,
            limit=limit,
            force=bool(arguments.get("force", False)),
        )
    if direction in {"pull", "both"}:
        pull_result = service.pull_topic(
            topic,
            dry_run=dry_run,
            limit=limit,
            include_rh_generated=bool(arguments.get("include_rh_generated", False)),
        )

    return {
        "topic": topic,
        "direction": direction,
        "dry_run": dry_run,
        "push": push_result.to_dict() if push_result is not None else None,
        "pull": pull_result.to_dict() if pull_result is not None else None,
    }


def _zotero_stable_dry_run_deferred_error(
    *,
    direction: str,
    dry_run: bool,
) -> str:
    if not dry_run:
        return (
            "real Zotero sync/apply is deferred; stable Zotero routing only "
            "supports direction=push with dry_run=true"
        )
    if direction in {"pull", "both"}:
        return (
            "stable Zotero dry-run only supports direction=push; "
            f"{direction} dry-run requires Zotero read access and remains deferred"
        )
    return ""


def _adversarial_review_helpers() -> tuple[Any, Any]:
    global codex_issues_to_objections, run_codex_review

    if run_codex_review is None or codex_issues_to_objections is None:
        from research_harness.auto_runner.codex_bridge import (
            codex_issues_to_objections as imported_issue_converter,
            run_codex_review as imported_review_runner,
        )

        if run_codex_review is None:
            run_codex_review = imported_review_runner
        if codex_issues_to_objections is None:
            codex_issues_to_objections = imported_issue_converter

    return run_codex_review, codex_issues_to_objections


def _zotero_sync_dependencies() -> tuple[Any, Any, str]:
    global DEFAULT_ROOT_COLLECTION, ZoteroSyncService, zotero_resource

    if zotero_resource is None:
        from research_harness import zotero_resource as imported_resource

        zotero_resource = imported_resource
    if ZoteroSyncService is None:
        from research_harness.zotero_sync import (
            DEFAULT_ROOT_COLLECTION as imported_root_collection,
            ZoteroSyncService as imported_sync_service,
        )

        DEFAULT_ROOT_COLLECTION = imported_root_collection
        ZoteroSyncService = imported_sync_service

    return zotero_resource, ZoteroSyncService, DEFAULT_ROOT_COLLECTION


def registered_primitive_handler(name: str) -> Any:
    """Return a service handler for primitives registered before MCP routing."""

    def _handler(ctx: ServiceContext, arguments: dict[str, Any]) -> dict[str, Any]:
        del ctx
        return {
            "error": (
                "Primitive service command is registered but execution remains on "
                "the existing primitive transport path."
            ),
            "error_code": "COMMAND_NOT_ROUTED",
            "registered_only": True,
            "primitive": name,
            "arguments": dict(arguments),
        }

    return _handler


def tracked_primitive_handler(name: str) -> Any:
    """Return a service handler for gate-approved tracked primitive routing."""

    def _handler(ctx: ServiceContext, arguments: dict[str, Any]) -> Any:
        primitive_arguments = arguments
        if name == "section_draft":
            gate_result = _section_draft_logic_gate_result(ctx, arguments)
            if gate_result is not None:
                return gate_result
            primitive_arguments = dict(arguments)
            primitive_arguments.pop("paper_plan", None)

        result = _execute_tracked_primitive(ctx, name, primitive_arguments)
        service_result = primitive_result_to_service_result(
            result,
            orch_state=_try_get_orch_state(ctx, primitive_arguments.get("topic_id")),
        )
        if name == "paper_search" and result.success:
            freshness_status = _update_paper_search_freshness(ctx, primitive_arguments)
            if freshness_status["status"] == "failed":
                service_result = replace(
                    service_result,
                    metadata={
                        **service_result.metadata,
                        "freshness_update_status": freshness_status["status"],
                        "freshness_update_error": freshness_status["error"],
                    },
                )
        return service_result

    return _handler


def _section_draft_logic_gate_result(
    ctx: ServiceContext,
    arguments: dict[str, Any],
) -> ServiceResult | None:
    explicit = arguments.get("paper_plan")
    paper_plan = explicit if isinstance(explicit, Mapping) else None
    block = section_draft_logic_gate_block(
        db=ctx.db,
        section=arguments.get("section"),
        topic_id=arguments.get("topic_id"),
        paper_plan=paper_plan,
    )
    if block is None:
        return None

    return ServiceResult(
        command="section_draft",
        status="error",
        summary=block.message,
        output=block.output_payload(),
        error=block.error_payload(),
        recovery_hint=block.recovery_hint,
        metadata={
            "primitive": "section_draft",
            "provenance_recorded_by": "not_started",
            "guard": "manuscript_logic_gate",
        },
    )


def _execute_tracked_primitive(
    ctx: ServiceContext,
    name: str,
    arguments: dict[str, Any],
) -> PrimitiveResult:
    if ctx.db is None:
        return PrimitiveResult(
            primitive=name,
            success=False,
            output={},
            error="Database is required for tracked primitive execution",
        )

    backend_name = os.environ.get("RESEARCH_HARNESS_BACKEND") or os.environ.get(
        "RESEARCH_HUB_BACKEND", "research_harness"
    )
    inner = create_backend(backend_name, db=ctx.db)
    recorder = ProvenanceRecorder(ctx.db)
    backend = TrackedBackend(inner=inner, recorder=recorder)
    return backend.execute(name, **arguments)


def _try_get_orch_state(
    ctx: ServiceContext,
    topic_id: int | None,
) -> dict[str, Any] | None:
    if ctx.db is None or topic_id is None:
        return None
    try:
        status = OrchestratorService(ctx.db).get_status(topic_id)
        if "error" in status:
            return None
        return status
    except Exception:
        return None


def _update_paper_search_freshness(
    ctx: ServiceContext,
    arguments: dict[str, Any],
) -> dict[str, str]:
    if ctx.db is None:
        return {"status": "skipped", "reason": "db_unavailable"}

    topic_id = arguments.get("topic_id")
    if not topic_id:
        return {"status": "skipped", "reason": "topic_id_missing"}

    conn = ctx.db.connect()
    try:
        conn.execute(
            "UPDATE topics SET last_search_at = datetime('now') WHERE id = ?",
            (topic_id,),
        )
        query_text = arguments.get("query", "")
        if query_text:
            conn.execute(
                """INSERT INTO search_query_registry (topic_id, query, source, last_searched_at)
                   VALUES (?, ?, 'auto_generated', datetime('now'))
                   ON CONFLICT(topic_id, query) DO UPDATE SET last_searched_at = datetime('now')""",
                (topic_id, query_text),
            )
        conn.commit()
        return {"status": "updated"}
    except Exception:
        LOGGER.warning(
            "paper_search freshness update failed for topic_id=%s",
            topic_id,
            exc_info=True,
        )
        return {
            "status": "failed",
            "error": "paper_search freshness update failed",
        }
    finally:
        conn.close()


def _with_freshness(topic: dict[str, Any]) -> dict[str, Any]:
    last_search = topic.get("last_search_at") or ""
    if not last_search:
        return {
            **topic,
            "days_since_last_search": None,
            "freshness_status": "never_searched",
        }

    try:
        last_dt = datetime.fromisoformat(str(last_search).replace("Z", "+00:00"))
        delta = (datetime.now(timezone.utc) - last_dt).days
    except (TypeError, ValueError):
        return {
            **topic,
            "days_since_last_search": None,
            "freshness_status": "unknown",
        }

    warn_days = topic.get("freshness_warn_days", 7)
    stale_days = topic.get("freshness_stale_days", 30)
    if delta >= stale_days:
        status = "stale"
    elif delta >= warn_days:
        status = "warn"
    else:
        status = "fresh"
    return {**topic, "days_since_last_search": delta, "freshness_status": status}


def _paper_row_to_dict(row: Any) -> dict[str, Any]:
    paper = dict(row)
    for field_name in ("authors", "affiliations"):
        value = paper.get(field_name)
        if not isinstance(value, str):
            continue
        try:
            parsed = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            parsed = []
        paper[field_name] = parsed if isinstance(parsed, list) else []
    return paper


def _skills_root() -> Any:
    return find_repo_root()


def _manifest_dict() -> dict[str, Any]:
    root = _skills_root()
    try:
        manifest = load_manifest(root)
    except FileNotFoundError:
        manifest = build_manifest(root)
    return manifest.to_dict()
