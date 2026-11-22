"""Initial service command registry."""

from __future__ import annotations

from typing import Any

from research_harness.primitives.registry import get_primitive_spec

from . import handlers
from .types import ServiceCommand


_COMMON_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
}

_RESEARCH_BINDING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "contract_version": {"type": "string", "enum": ["research_execution.v1"]},
        "execution_mode": {"type": "string", "enum": ["external_simulated"]},
        "execution_id": {
            "type": "string",
            "minLength": 32,
            "maxLength": 32,
            "pattern": "^[0-9a-f]{32}$",
        },
        "topic_id": {"type": "integer", "minimum": 1},
        "ticket_namespace": {"type": "string", "pattern": "\\S"},
        "public_id": {"type": "string", "pattern": "\\S"},
        "title": {"type": "string", "pattern": "\\S"},
        "topic_text": {"type": "string", "pattern": "\\S"},
        "target_journal": {"type": "string", "pattern": "\\S"},
        "rh_db_path": {"type": "string", "pattern": "\\S"},
    },
    "required": [
        "contract_version",
        "execution_mode",
        "execution_id",
        "topic_id",
        "ticket_namespace",
        "public_id",
        "title",
        "topic_text",
        "target_journal",
        "rh_db_path",
    ],
    "additionalProperties": True,
}

_DELIVERY_PAPER_PRODUCTION_SNAPSHOT_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "schema_version": {
            "const": "rh.delivery.paper_production_snapshot.v1",
            "description": "Stable research delivery snapshot envelope schema.",
        },
        "status": {
            "type": "string",
            "enum": ["not_started", "in_progress", "complete", "blocked"],
        },
        "next_artifact": {"type": ["string", "null"]},
        "next_action": {"type": ["string", "null"]},
        "summary": {
            "type": "object",
            "properties": {
                "total": {"type": "integer", "minimum": 0},
                "satisfied": {"type": "integer", "minimum": 0},
                "ready_to_advance": {"type": "integer", "minimum": 0},
                "blocked": {"type": "integer", "minimum": 0},
            },
            "required": ["total", "satisfied", "ready_to_advance", "blocked"],
            "additionalProperties": False,
        },
        "records": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "entry_mode": {"type": "string"},
                    "request": {"type": "string"},
                    "artifact": {"type": "string"},
                    "stage": {"type": "string"},
                    "gate": {"type": "string"},
                    "owner_skill": {"type": "string"},
                    "recording_surface": {"type": "string"},
                    "action": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["satisfied", "ready_to_advance", "blocked"],
                    },
                    "validation_status": {"type": "string"},
                    "promotion_status": {"type": "string"},
                    "blockers": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "entry_mode",
                    "request",
                    "artifact",
                    "stage",
                    "gate",
                    "owner_skill",
                    "recording_surface",
                    "action",
                    "status",
                    "validation_status",
                    "promotion_status",
                    "blockers",
                ],
                "additionalProperties": False,
            },
        },
        "blockers": {"type": "array", "items": {"type": "string"}},
        "dry_run": {"const": True},
        "inputs": {
            "type": "object",
            "properties": {
                "topic_id": {"type": ["integer", "null"]},
                "artifact_states": {
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "explicit": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "resolved": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "sources": {
                            "type": "object",
                            "additionalProperties": {"type": "string"},
                        },
                    },
                    "required": ["topic", "explicit", "resolved", "sources"],
                    "additionalProperties": False,
                },
                "payloads": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "counts": {
                    "type": "object",
                    "properties": {
                        "topic_artifact_states": {"type": "integer", "minimum": 0},
                        "explicit_artifact_states": {"type": "integer", "minimum": 0},
                        "resolved_artifact_states": {"type": "integer", "minimum": 0},
                        "payloads": {"type": "integer", "minimum": 0},
                    },
                    "required": [
                        "topic_artifact_states",
                        "explicit_artifact_states",
                        "resolved_artifact_states",
                        "payloads",
                    ],
                    "additionalProperties": False,
                },
            },
            "required": ["topic_id", "artifact_states", "payloads", "counts"],
            "additionalProperties": False,
        },
    },
    "required": [
        "schema_version",
        "status",
        "next_artifact",
        "next_action",
        "summary",
        "records",
        "blockers",
        "dry_run",
        "inputs",
    ],
    "additionalProperties": False,
}


def _primitive_description(name: str) -> str:
    spec = get_primitive_spec(name)
    return spec.description if spec is not None else f"Registered primitive {name}."


def _primitive_input_schema(name: str) -> dict[str, Any]:
    spec = get_primitive_spec(name)
    if spec is None:
        return {"type": "object", "properties": {}}
    return spec.input_schema


COMMANDS: tuple[ServiceCommand, ...] = (
    ServiceCommand(
        name="topic_list",
        description="List all Research Harness topics.",
        input_schema={"type": "object", "properties": {}},
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.topic_list,
    ),
    ServiceCommand(
        name="topic_show",
        description="Show one Research Harness topic by name.",
        input_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.topic_show,
    ),
    ServiceCommand(
        name="topic_state",
        description=(
            "Full single-call state picture for one topic: resolved DB and "
            "state trees, orchestrator stage/gate, checkpoint, pending human "
            "decision, blockers, and a computed next action."
        ),
        input_schema={
            "type": "object",
            "properties": {"topic_id": {"type": "integer"}},
            "required": ["topic_id"],
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.topic_state,
    ),
    ServiceCommand(
        name="paper_list",
        description="List papers, optionally filtered by topic name (supports limit/offset paging).",
        input_schema={
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "limit": {"type": "integer", "minimum": 0},
                "offset": {"type": "integer", "minimum": 0},
            },
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.paper_list,
    ),
    ServiceCommand(
        name="job_status",
        description="Poll a background job's status, progress, and result (BUG-011).",
        input_schema={
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        # python/CLI visibility for now; MCP tools/list advertising is a
        # deliberate governance follow-up. Still callable via ResearchService.
        visibility=("python",),
        handler=handlers.job_status,
    ),
    ServiceCommand(
        name="provenance_summary",
        description="Get aggregated provenance statistics.",
        input_schema={
            "type": "object",
            "properties": {"topic_id": {"type": "integer"}},
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.provenance_summary,
    ),
    ServiceCommand(
        name="provenance_export",
        description="Export serialized provenance records.",
        input_schema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer"},
                "format": {"type": "string", "enum": ["json"]},
            },
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.provenance_export,
    ),
    ServiceCommand(
        name="orchestrator_status",
        description="Show read-only orchestrator status for a topic.",
        input_schema={
            "type": "object",
            "properties": {"topic_id": {"type": "integer"}},
            "required": ["topic_id"],
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.orchestrator_status,
    ),
    ServiceCommand(
        name="resource_ready_get",
        description=(
            "Fetch the single active SPC resource-ready binding for a "
            "(topic, workflow_ref, host) triple."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer"},
                "workflow_ref": {"type": "string"},
                "host_id": {"type": "string"},
            },
            "required": ["topic_id", "workflow_ref", "host_id"],
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.resource_ready_get,
    ),
    ServiceCommand(
        name="orchestrator_gate_check",
        description="Check the current or specified orchestrator gate.",
        input_schema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer"},
                "stage": {"type": "string"},
            },
            "required": ["topic_id"],
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.orchestrator_gate_check,
    ),
    ServiceCommand(
        name="orchestrator_resume",
        description="Resume or create an orchestrator run for a topic.",
        input_schema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer"},
                "mode": {"type": "string"},
                "force_stage": {"type": "string"},
                "stop_before": {"type": "string"},
            },
            "required": ["topic_id"],
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp",),
        handler=handlers.orchestrator_resume,
    ),
    ServiceCommand(
        name="orchestrator_advance",
        description="Advance the topic to the next orchestrator stage.",
        input_schema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer"},
                "actor": {"type": "string"},
            },
            "required": ["topic_id"],
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp",),
        handler=handlers.orchestrator_advance,
    ),
    ServiceCommand(
        name="orchestrator_record_artifact",
        description="Record a new artifact for the current orchestrator stage.",
        input_schema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer"},
                "stage": {"type": "string"},
                "artifact_type": {"type": "string"},
                "title": {"type": "string"},
                "payload": {"type": "object"},
                "dependency_artifact_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                },
                "dependency_type": {"type": "string"},
            },
            "required": ["topic_id", "stage", "artifact_type"],
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp",),
        handler=handlers.orchestrator_record_artifact,
    ),
    ServiceCommand(
        name="paper_commit_version",
        description=(
            "Commit one manuscript version atomically: hash the TeX/PDF "
            "files, record draft_pack + final_bundle (+ quality report) with "
            "lineage wired, and reject commits whose declared dependencies "
            "are missing or superseded. Replaces manual shasum + separate "
            "orchestrator_record_artifact calls per version."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer"},
                "tex_path": {"type": "string"},
                "pdf_path": {"type": "string"},
                "stage": {"type": "string"},
                "title": {"type": "string"},
                "quality_report": {"type": "object"},
                "dependency_artifact_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                },
                "notes": {"type": "string"},
                "force_reason": {"type": "string"},
            },
            "required": ["topic_id", "tex_path"],
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp",),
        handler=handlers.paper_commit_version,
    ),
    ServiceCommand(
        name="paper_task_intake",
        description=(
            "Create or resume a durable RH paper-production topic/run from a "
            "natural-language task, record the initial PAPER_PLAN artifact, and "
            "return RH_STATE so chat-only output is not treated as progress."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "task": {"type": "string"},
                "target_venue": {"type": "string"},
                "mode": {
                    "type": "string",
                    "enum": ["explore", "standard", "strict", "demo"],
                },
                "local_only": {"type": "boolean"},
            },
            "required": ["task", "target_venue"],
            "additionalProperties": False,
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.paper_task_intake,
    ),
    ServiceCommand(
        name="topic_init",
        description=(
            "Initialize a new research topic (create or reuse by name) and "
            "return its topic_id for subsequent operations."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "description": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["name"],
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp",),
        handler=handlers.topic_init,
    ),
    ServiceCommand(
        name="paper_production_start",
        description=(
            "Start the paper-production workflow for a topic: prepare "
            "topic/run/checkpoint state with the requested interaction mode "
            "and return the initial status."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer"},
                "target_venue": {"type": "string"},
                "interaction_mode": {
                    "type": "string",
                    "enum": ["autonomous", "checkpoint", "interactive"],
                },
                "paper_mode": {"type": "string", "enum": ["main"]},
                "budget": {"type": "number"},
                "local_only": {"type": "boolean"},
            },
            "required": ["topic_id", "target_venue"],
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp",),
        handler=handlers.paper_production_start,
    ),
    ServiceCommand(
        name="paper_production_pending_decisions",
        description=(
            "Get pending human decision requests for a paper-production "
            "workflow, with options, recommendations, and interaction mode."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer"},
            },
            "required": ["topic_id"],
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp",),
        handler=handlers.paper_production_pending_decisions,
    ),
    ServiceCommand(
        name="paper_production_decide",
        description=(
            "Record a human decision for a paused paper-production workflow; "
            "the choice must match one of the pending options."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer"},
                "choice": {"type": "string"},
                "reasoning": {"type": "string"},
            },
            "required": ["topic_id", "choice"],
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp",),
        handler=handlers.paper_production_decide,
    ),
    ServiceCommand(
        name="paper_production_status",
        description=(
            "Detailed paper-production status: orchestrator state, pending "
            "decisions, and the current interaction mode."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer"},
            },
            "required": ["topic_id"],
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp",),
        handler=handlers.paper_production_status,
    ),
    ServiceCommand(
        name="paper_production_resume",
        description=(
            "Resume a paused paper-production workflow, optionally "
            "auto-applying the recommended pending decision."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer"},
                "auto_approve": {"type": "boolean"},
            },
            "required": ["topic_id"],
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp",),
        handler=handlers.paper_production_resume,
    ),
    ServiceCommand(
        name="paper_production_mode",
        description="Get the current interaction mode for a topic's workflow.",
        input_schema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer"},
            },
            "required": ["topic_id"],
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp",),
        handler=handlers.paper_production_mode,
    ),
    ServiceCommand(
        name="paper_production_set_mode",
        description=(
            "Change the interaction mode for a running workflow "
            "(autonomous, checkpoint, or interactive)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer"},
                "mode": {
                    "type": "string",
                    "enum": ["autonomous", "checkpoint", "interactive"],
                },
            },
            "required": ["topic_id", "mode"],
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp",),
        handler=handlers.paper_production_set_mode,
    ),
    ServiceCommand(
        name="paper_production_export",
        description=(
            "Export generated paper paths from the recorded write-stage "
            "artifacts (draft_pack TeX, final_bundle PDF, and companions)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer"},
                "format": {"type": "string", "enum": ["latex", "pdf", "both"]},
                "include_artifacts": {"type": "boolean"},
            },
            "required": ["topic_id"],
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp",),
        handler=handlers.paper_production_export,
    ),
    ServiceCommand(
        name="adversarial_review",
        description="Run independent adversarial review for an artifact.",
        input_schema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer"},
                "artifact_id": {"type": "integer"},
                "focus": {"type": "string"},
                "evidence_summary": {"type": "string"},
            },
            "required": ["topic_id", "artifact_id"],
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp",),
        handler=handlers.adversarial_review,
    ),
    ServiceCommand(
        name="advisory_check",
        description="Run heuristic advisory rules for a topic.",
        input_schema={
            "type": "object",
            "properties": {"topic_id": {"type": "integer"}},
            "required": ["topic_id"],
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp",),
        handler=handlers.advisory_check,
    ),
    ServiceCommand(
        name="zotero_sync",
        description="Synchronize an RH topic with Zotero as a first-class RH resource.",
        input_schema={
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "direction": {"type": "string"},
                "root_collection": {"type": "string"},
                "library_id": {"type": "string"},
                "library_type": {"type": "string"},
                "api_key": {"type": "string"},
                "api_base": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1},
                "skip_notes": {"type": "boolean"},
                "force": {"type": "boolean"},
                "include_rh_generated": {"type": "boolean"},
                "dry_run": {"type": "boolean"},
            },
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp",),
        handler=handlers.zotero_sync,
    ),
    ServiceCommand(
        name="paperindex_search",
        description="Search structured local paperindex records.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["query"],
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.paperindex_search,
        requires_db=False,
    ),
    ServiceCommand(
        name="skill_list",
        description="List Research Harness workflow skills.",
        input_schema={
            "type": "object",
            "properties": {"category": {"type": "string"}},
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.skill_list,
        requires_db=False,
    ),
    ServiceCommand(
        name="skill_get",
        description="Read one Research Harness workflow skill.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "track": {"type": "string"},
            },
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.skill_get,
        requires_db=False,
    ),
    ServiceCommand(
        name="productization_boundary",
        description="Show the opt-in LG10 public-productization boundary preview.",
        input_schema={
            "type": "object",
            "properties": {
                "experimental_lg10": {
                    "type": "boolean",
                    "default": False,
                },
            },
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp",),
        handler=handlers.productization_boundary,
        requires_db=False,
    ),
    ServiceCommand(
        name="topic_knowledge_status",
        description="Show the current Topic Knowledge status payload for a topic.",
        input_schema={
            "type": "object",
            "properties": {
                "topic_id": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Positive RH topic id",
                },
            },
            "required": ["topic_id"],
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.topic_knowledge_status,
    ),
    ServiceCommand(
        name="topic_knowledge_refresh",
        description="Refresh Topic Knowledge snapshots for one topic or all topics.",
        input_schema={
            "type": "object",
            "properties": {
                "topic_id": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Positive RH topic id",
                },
                "all": {
                    "type": "boolean",
                    "default": False,
                    "description": "Refresh every topic in the local database",
                },
            },
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.topic_knowledge_refresh,
    ),
    ServiceCommand(
        name="wiki_context_pack",
        description=(
            "Build a read-only Research Wiki context-pack preflight payload for a topic."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "topic_id": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Positive RH topic id",
                },
                "query": {"type": "string", "maxLength": 500},
                "action_name": {"type": "string", "maxLength": 80},
                "anchor_paper_id": {"type": "integer", "minimum": 1},
                "max_pages": {"type": "integer", "minimum": 0, "maximum": 20},
                "max_anchors": {"type": "integer", "minimum": 0, "maximum": 80},
            },
            "required": ["topic_id"],
            "additionalProperties": False,
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("python", "cli"),
        handler=handlers.wiki_context_pack,
        validation_policy="strict",
    ),
    ServiceCommand(
        name="delivery_paper_production_snapshot",
        description=(
            "Build the Python-only dry-run research delivery paper-production snapshot "
            "rh.delivery.paper_production_snapshot.v1 from explicit or "
            "topic-derived artifact state, with no artifact writes, no stage "
            "advancement, no orchestrator_record_artifact call, no MCP, no CLI, "
            "and no HTTP transport exposure."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "topic_id": {
                    "type": "integer",
                    "minimum": 1,
                    "description": (
                        "Optional positive RH topic id used only for read-only "
                        "artifact-state lookup."
                    ),
                },
                "artifact_states": {
                    "type": "object",
                    "description": (
                        "Optional explicit artifact-state overrides merged over "
                        "topic-derived state."
                    ),
                    "additionalProperties": True,
                },
                "payloads": {
                    "type": "object",
                    "description": (
                        "Optional payload content used for dry-run readiness "
                        "evaluation."
                    ),
                    "additionalProperties": True,
                },
            },
            "additionalProperties": False,
        },
        output_schema=_DELIVERY_PAPER_PRODUCTION_SNAPSHOT_OUTPUT_SCHEMA,
        visibility=("python",),
        handler=handlers.delivery_paper_production_snapshot,
        validation_policy="strict",
    ),
    ServiceCommand(
        name="cross_topic_atlas",
        description="Build a cross-topic knowledge atlas from existing snapshots.",
        input_schema={
            "type": "object",
            "properties": {
                "topic_ids": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 1},
                    "minItems": 2,
                    "description": "Distinct positive RH topic ids",
                },
                "query": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["topic_ids"],
        },
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.cross_topic_atlas,
    ),
    ServiceCommand(
        name="paper_search",
        description=_primitive_description("paper_search"),
        input_schema=_primitive_input_schema("paper_search"),
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.tracked_primitive_handler("paper_search"),
    ),
    ServiceCommand(
        name="paper_ingest",
        description=_primitive_description("paper_ingest"),
        input_schema=_primitive_input_schema("paper_ingest"),
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.tracked_primitive_handler("paper_ingest"),
    ),
    ServiceCommand(
        name="paper_summarize",
        description=_primitive_description("paper_summarize"),
        input_schema=_primitive_input_schema("paper_summarize"),
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.tracked_primitive_handler("paper_summarize"),
    ),
    ServiceCommand(
        name="claim_extract",
        description=_primitive_description("claim_extract"),
        input_schema=_primitive_input_schema("claim_extract"),
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.tracked_primitive_handler("claim_extract"),
    ),
    ServiceCommand(
        name="evidence_link",
        description=_primitive_description("evidence_link"),
        input_schema=_primitive_input_schema("evidence_link"),
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.tracked_primitive_handler("evidence_link"),
    ),
    ServiceCommand(
        name="gap_detect",
        description=_primitive_description("gap_detect"),
        input_schema=_primitive_input_schema("gap_detect"),
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.tracked_primitive_handler("gap_detect"),
    ),
    ServiceCommand(
        name="baseline_identify",
        description=_primitive_description("baseline_identify"),
        input_schema=_primitive_input_schema("baseline_identify"),
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.tracked_primitive_handler("baseline_identify"),
    ),
    ServiceCommand(
        name="section_draft",
        description=_primitive_description("section_draft"),
        input_schema=_primitive_input_schema("section_draft"),
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.tracked_primitive_handler("section_draft"),
    ),
    ServiceCommand(
        name="figure_generate",
        description=_primitive_description("figure_generate"),
        input_schema=_primitive_input_schema("figure_generate"),
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.tracked_primitive_handler("figure_generate"),
    ),
    ServiceCommand(
        name="consistency_check",
        description=_primitive_description("consistency_check"),
        input_schema=_primitive_input_schema("consistency_check"),
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.tracked_primitive_handler("consistency_check"),
    ),
    ServiceCommand(
        name="exemplar_curate",
        description=_primitive_description("exemplar_curate"),
        input_schema=_primitive_input_schema("exemplar_curate"),
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.tracked_primitive_handler("exemplar_curate"),
    ),
    ServiceCommand(
        name="exemplar_retrieve",
        description=_primitive_description("exemplar_retrieve"),
        input_schema=_primitive_input_schema("exemplar_retrieve"),
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.tracked_primitive_handler("exemplar_retrieve"),
    ),
    ServiceCommand(
        name="exemplar_plan",
        description=_primitive_description("exemplar_plan"),
        input_schema=_primitive_input_schema("exemplar_plan"),
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.tracked_primitive_handler("exemplar_plan"),
    ),
    ServiceCommand(
        name="exemplar_generate",
        description=_primitive_description("exemplar_generate"),
        input_schema=_primitive_input_schema("exemplar_generate"),
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.tracked_primitive_handler("exemplar_generate"),
    ),
    ServiceCommand(
        name="exemplar_critique",
        description=_primitive_description("exemplar_critique"),
        input_schema=_primitive_input_schema("exemplar_critique"),
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.tracked_primitive_handler("exemplar_critique"),
    ),
    ServiceCommand(
        name="figure_suite_plan",
        description=_primitive_description("figure_suite_plan"),
        input_schema=_primitive_input_schema("figure_suite_plan"),
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.tracked_primitive_handler("figure_suite_plan"),
    ),
    ServiceCommand(
        name="figure_suite_render",
        description=_primitive_description("figure_suite_render"),
        input_schema=_primitive_input_schema("figure_suite_render"),
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.tracked_primitive_handler("figure_suite_render"),
    ),
    ServiceCommand(
        name="figure_package",
        description=_primitive_description("figure_package"),
        input_schema=_primitive_input_schema("figure_package"),
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.tracked_primitive_handler("figure_package"),
    ),
    ServiceCommand(
        name="manuscript_review",
        description=_primitive_description("manuscript_review"),
        input_schema=_primitive_input_schema("manuscript_review"),
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.tracked_primitive_handler("manuscript_review"),
    ),
    ServiceCommand(
        name="manuscript_polish",
        description=_primitive_description("manuscript_polish"),
        input_schema=_primitive_input_schema("manuscript_polish"),
        output_schema=_COMMON_OUTPUT_SCHEMA,
        visibility=("public_mcp", "python"),
        handler=handlers.tracked_primitive_handler("manuscript_polish"),
    ),
)

COMMANDS_BY_NAME: dict[str, ServiceCommand] = {
    command.name: command for command in COMMANDS
}
