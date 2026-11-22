"""MCP convenience tool definitions."""

from __future__ import annotations

from mcp.types import Tool


from .tools_convenience_execution import _execute_convenience

__all__ = ["_CONVENIENCE_TOOLS", "_execute_convenience"]

_CONVENIENCE_TOOLS: dict[str, Tool] = {
    "topic_list": Tool(
        name="topic_list",
        description="List all research topics",
        inputSchema={"type": "object", "properties": {}},
    ),
    "resource_ready_get": Tool(
        name="resource_ready_get",
        description=(
            "Fetch the single active SPC resource-ready binding for a "
            "(topic_id, workflow_ref, host_id) triple"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "RH topic id"},
                "workflow_ref": {
                    "type": "string",
                    "description": "workflow:<name>@<revision>",
                },
                "host_id": {"type": "string", "description": "host:<id>"},
            },
            "required": ["topic_id", "workflow_ref", "host_id"],
        },
    ),
    "deposit_zenodo": Tool(
        name="deposit_zenodo",
        description=(
            "Pack topic code+data, deposit to Zenodo, return code_doi and data_doi. "
            "Prefer token; email+password only mints a PAT via headless login."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {
                    "type": "integer",
                    "description": "RH topic id (used for title/path discovery)",
                },
                "topic_name": {
                    "type": "string",
                    "description": "Topic name if topic_id is unknown",
                },
                "title": {
                    "type": "string",
                    "description": "Deposit title base; defaults to topic name",
                },
                "creator": {
                    "type": "string",
                    "description": 'Author as "Last, First"',
                },
                "email": {
                    "type": "string",
                    "description": "Zenodo email (or set ZENODO_EMAIL)",
                },
                "password": {
                    "type": "string",
                    "description": "Zenodo password (or ZENODO_PASSWORD); prefer token",
                },
                "token": {
                    "type": "string",
                    "description": "Zenodo personal access token (or ZENODO_TOKEN)",
                },
                "code_path": {
                    "type": "string",
                    "description": "Explicit code directory/file path",
                },
                "data_path": {
                    "type": "string",
                    "description": "Explicit data directory/file path",
                },
                "deposit_root": {
                    "type": "string",
                    "description": "Root containing code/ and data/ (or 代码/数据)",
                },
                "sandbox": {
                    "type": "boolean",
                    "description": "Use sandbox.zenodo.org",
                    "default": False,
                },
                "publish": {
                    "type": "boolean",
                    "description": "Publish and register DOIs (false = draft only)",
                    "default": True,
                },
            },
        },
    ),
    "topic_show": Tool(
        name="topic_show",
        description="Show details for a research topic by name",
        inputSchema={
            "type": "object",
            "properties": {"name": {"type": "string", "description": "Topic name"}},
            "required": ["name"],
        },
    ),
    "paper_list": Tool(
        name="paper_list",
        description="List papers, optionally filtered by topic",
        inputSchema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Topic name filter"},
            },
        },
    ),
    "task_list": Tool(
        name="task_list",
        description="List tasks, optionally filtered by topic",
        inputSchema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "Topic name filter"},
                "status": {
                    "type": "string",
                    "description": "Status filter (pending/done/skipped)",
                },
            },
        },
    ),
    "provenance_summary": Tool(
        name="provenance_summary",
        description="Get aggregated provenance statistics (cost, operations, success rate)",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {
                    "type": "integer",
                    "description": "Optional topic ID filter",
                },
            },
        },
    ),
    "provenance_export": Tool(
        name="provenance_export",
        description="Export serialized provenance records for analysis",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {
                    "type": "integer",
                    "description": "Optional topic ID filter",
                },
                "format": {
                    "type": "string",
                    "enum": ["json"],
                    "description": "Serialization format",
                },
            },
        },
    ),
    "provenance_token_report": Tool(
        name="provenance_token_report",
        description=(
            "Long-term token/cost accounting per (backend, model). Groups every "
            "provenance record by agent identity and reports call count, prompt "
            "tokens, completion tokens, total cost and cost-per-call. Optionally "
            "scoped to a single topic for per-paper agent budgeting."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {
                    "type": "integer",
                    "description": "Optional topic ID filter",
                },
            },
        },
    ),
    "paper_dismiss": Tool(
        name="paper_dismiss",
        description=(
            "Record that the user has decided not to read a paper in full. "
            "Stores the dismissal reason in topic_paper_notes and downgrades relevance to 'low'. "
            "Dismissed papers are excluded from future coverage checks and their reasons "
            "are used to calibrate necessity scoring for similar papers."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "paper_id": {
                    "type": "integer",
                    "description": "ID of the paper to dismiss",
                },
                "topic_id": {
                    "type": "integer",
                    "description": "Topic the paper belongs to",
                },
                "reason": {
                    "type": "string",
                    "description": "Why the user is dismissing this paper",
                },
            },
            "required": ["paper_id", "topic_id", "reason"],
        },
    ),
    "decision_log_record": Tool(
        name="decision_log_record",
        description="Record a human or auto decision at a research checkpoint",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer"},
                "stage": {"type": "string", "description": "Stage name (V2 or legacy)"},
                "checkpoint": {
                    "type": "string",
                    "description": "Checkpoint name (e.g. direction_selection)",
                },
                "choice": {"type": "string", "description": "What was decided"},
                "reasoning": {
                    "type": "string",
                    "description": "Why this choice was made",
                },
                "params": {
                    "type": "object",
                    "description": "Parameter snapshot at decision time",
                },
            },
            "required": ["topic_id", "stage", "checkpoint", "choice"],
        },
    ),
    "decision_log_list": Tool(
        name="decision_log_list",
        description="List decision log entries for a topic (useful for writing motivation)",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer"},
                "stage": {"type": "string", "description": "Optional stage filter"},
            },
            "required": ["topic_id"],
        },
    ),
    "search_query_list": Tool(
        name="search_query_list",
        description="List registered search queries with freshness status for a topic",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer"},
            },
            "required": ["topic_id"],
        },
    ),
    "search_query_add": Tool(
        name="search_query_add",
        description="Register a new search query for a topic",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer"},
                "query": {"type": "string"},
                "source": {
                    "type": "string",
                    "description": "user / auto_generated / method_expansion",
                },
            },
            "required": ["topic_id", "query"],
        },
    ),
    "advisory_check": Tool(
        name="advisory_check",
        description="Run heuristic advisory rules and return newly created advisories for a topic",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer"},
            },
            "required": ["topic_id"],
        },
    ),
    "topic_knowledge_status": Tool(
        name="topic_knowledge_status",
        description="Show the current Topic Knowledge status payload for a topic",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {
                    "type": "integer",
                    "description": "Positive RH topic id",
                },
            },
            "required": ["topic_id"],
        },
    ),
    "topic_knowledge_refresh": Tool(
        name="topic_knowledge_refresh",
        description="Refresh Topic Knowledge snapshots for one topic or all topics",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {
                    "type": "integer",
                    "description": "Positive RH topic id",
                },
                "all": {
                    "type": "boolean",
                    "default": False,
                    "description": "Refresh every topic in the local database",
                },
            },
        },
    ),
    "cross_topic_atlas": Tool(
        name="cross_topic_atlas",
        description="Build a cross-topic knowledge atlas from existing snapshots",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_ids": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 2,
                    "description": "Distinct positive RH topic ids",
                },
                "query": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["topic_ids"],
        },
    ),
    "advisory_list": Tool(
        name="advisory_list",
        description="List advisories for a topic",
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer"},
                "level": {
                    "type": "string",
                    "description": "Optional level filter: info or warning",
                },
            },
            "required": ["topic_id"],
        },
    ),
    "advisory_acknowledge": Tool(
        name="advisory_acknowledge",
        description="Mark an advisory as acknowledged",
        inputSchema={
            "type": "object",
            "properties": {
                "advisory_id": {"type": "integer"},
            },
            "required": ["advisory_id"],
        },
    ),
    "zotero_sync": Tool(
        name="zotero_sync",
        description=(
            "Synchronize an RH topic with Zotero as a first-class RH resource. "
            "Use direction=push for RH→Zotero, pull for Zotero→RH notes/annotations, "
            "or both for bidirectional sync. Stable dry-run validation supports "
            "direction=push only and reads only the RH database; pull/both dry-run "
            "and real sync/apply remain deferred because they require Zotero access."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "topic": {"type": "string", "description": "RH topic name"},
                "direction": {
                    "type": "string",
                    "enum": ["push", "pull", "both"],
                    "default": "push",
                },
                "root_collection": {
                    "type": "string",
                    "description": "Top-level Zotero collection for RH-managed topics",
                    "default": "Research Harness",
                },
                "library_id": {
                    "type": "string",
                    "description": "Zotero user/group library ID; defaults to env",
                },
                "library_type": {
                    "type": "string",
                    "enum": ["user", "group"],
                    "default": "user",
                },
                "api_key": {
                    "type": "string",
                    "description": "Zotero API key; defaults to env",
                },
                "api_base": {
                    "type": "string",
                    "description": "Zotero API base URL override",
                },
                "limit": {"type": "integer", "minimum": 1},
                "skip_notes": {
                    "type": "boolean",
                    "description": "Do not create/update RH-generated child notes on push",
                    "default": False,
                },
                "force": {
                    "type": "boolean",
                    "description": "Push even if the RH content hash is unchanged",
                    "default": False,
                },
                "include_rh_generated": {
                    "type": "boolean",
                    "description": "When pulling, also import RH-generated Zotero notes",
                    "default": False,
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "Preview without mutating RH/Zotero",
                    "default": True,
                },
            },
            "required": ["topic"],
        },
    ),
    "paper_purge": Tool(
        name="paper_purge",
        description=(
            "Permanently delete a paper and all its related records from the database. "
            "Use when a paper record is corrupted and causes queries on the entire topic to fail. "
            "This is irreversible — prefer paper_dismiss for normal exclusion."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "paper_id": {
                    "type": "integer",
                    "description": "ID of the paper to permanently delete",
                },
            },
            "required": ["paper_id"],
        },
    ),
    "venue_refresh": Tool(
        name="venue_refresh",
        description=(
            "Refresh venue metadata for papers with stale venues (arXiv.org, empty). "
            "Queries Semantic Scholar for updated venue info. "
            "Use after Build stage to catch papers that were published at conferences after initial ingestion."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "topic_id": {
                    "type": "integer",
                    "description": "Topic ID to refresh venues for",
                },
            },
            "required": ["topic_id"],
        },
    ),
    "domain_list": Tool(
        name="domain_list",
        description="List all research domains with their topic counts",
        inputSchema={"type": "object", "properties": {}},
    ),
    "domain_init": Tool(
        name="domain_init",
        description="Create a new research domain",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Domain name (unique)"},
                "description": {
                    "type": "string",
                    "description": "Short description of the domain",
                },
            },
            "required": ["name"],
        },
    ),
    "domain_show": Tool(
        name="domain_show",
        description="Show details for a research domain including its topics",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Domain name"},
            },
            "required": ["name"],
        },
    ),
}
