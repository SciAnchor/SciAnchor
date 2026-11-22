"""FastAPI HTTP API for research-harness local integrations.

Wraps the SQLite pool.db as JSON endpoints with pagination, search, and CORS.
Write/action endpoints delegate to MCP tool handlers via execute_tool().
Run standalone: python -m research_harness_mcp.http_api
"""

from __future__ import annotations

import logging
import os
import sqlite3
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from research_harness.api import ResearchAPI
from research_harness.demo import list_entries as demo_list_entries
from research_harness.demo import lookup as demo_lookup
from research_harness.service import ResearchService
from research_harness.storage.db import Database
from research_harness_mcp import __version__ as _MCP_VERSION
from research_harness_mcp import db_http as _db_http
from research_harness_mcp import http_models as _http_models
from research_harness_mcp import http_non_zotero_routes as _http_non_zotero_routes
from research_harness_mcp import knowledge_http as _knowledge_http
from research_harness_mcp import longtask_auth_http as _longtask_auth_http
from research_harness_mcp import http_auth as _http_auth
from research_harness_mcp import http_helpers as _http_helpers
from research_harness_mcp import pdf_roots as _pdf_roots
from research_harness_mcp import topic_expansion_job as _topic_expansion_job
from research_harness_mcp import topic_workspace_http as _topic_workspace_http
from research_harness_mcp.topic_zotero_sync_http import (
    register_topic_zotero_sync_routes,
)
from research_harness_mcp import tool_execution_http as _tool_execution_http
from research_harness_mcp import zotero_action_preview as _zotero_action_preview
from research_harness_mcp import zotero_attachment_targets as _zotero_attachment_targets
from research_harness_mcp import (
    zotero_capability_previews as _zotero_capability_previews,
)
from research_harness_mcp import zotero_capability_broker as _zotero_capability_broker
from research_harness_mcp import zotero_chat_actions as _zotero_chat_actions
from research_harness_mcp import zotero_chat_auth as _zotero_chat_auth
from research_harness_mcp import zotero_chat_intent as _zotero_chat_intent
from research_harness_mcp import zotero_chat_match as _zotero_chat_match
from research_harness_mcp import zotero_chat_responses as _zotero_chat_responses
from research_harness_mcp import zotero_collection_actions as _zotero_collection_actions
from research_harness_mcp import (
    zotero_codex_dynamic_tools as _zotero_codex_dynamic_tools,
)
from research_harness_mcp import zotero_codex_output as _zotero_codex_output
from research_harness_mcp import zotero_codex_prompts as _zotero_codex_prompts
from research_harness_mcp import zotero_codex_runtime as _zotero_codex_runtime
from research_harness_mcp import zotero_codex_settings as _zotero_codex_settings
from research_harness_mcp import zotero_codex_translate as _zotero_codex_translate
from research_harness_mcp import zotero_codex_tooling as _zotero_codex_tooling
from research_harness_mcp import zotero_identity as _zotero_identity
from research_harness_mcp import zotero_models_http as _zotero_models_http
from research_harness_mcp import zotero_pdf_annotations as _zotero_pdf_annotations
from research_harness_mcp import zotero_pdf_attachment as _zotero_pdf_attachment
from research_harness_mcp import zotero_pdf_paths as _zotero_pdf_paths
from research_harness_mcp import zotero_seed_preview as _zotero_seed_preview
from research_harness_mcp import zotero_seed_topic as _zotero_seed_topic
from research_harness_mcp import zotero_sync_actions as _zotero_sync_actions
from research_harness_mcp import zotero_topic_lookup as _zotero_topic_lookup
from research_harness_mcp import zotero_translate_prompts as _zotero_translate_prompts
from research_harness_mcp import zotero_write_access as _zotero_write_access
from research_harness_mcp import zotero_write_plan as _zotero_write_plan
from research_harness_mcp import zotero_workflow_receipt as _zotero_workflow_receipt
from research_harness_mcp import topic_expansion_helpers as _topic_expansion_helpers
from research_harness_mcp.zotero_chat_http import register_zotero_chat_routes
from research_harness_mcp.zotero_chat_stream_http import (
    register_zotero_chat_stream_routes,
    sse_encode as _zotero_chat_stream_sse_encode,
)
from research_harness_mcp.zotero_models_http import (
    ZoteroChatItemContext,
    ZoteroChatRequest,
    ZoteroChatTargetRef,
    ZoteroSeedPaperApplyRequest,
    ZoteroSyncRequest,
    ZoteroTranslateRequest,
    ZoteroWarmupRequest,
)
from research_harness_mcp.zotero_seed_apply_http import (
    register_zotero_seed_apply_routes,
)
from research_harness_mcp.zotero_translate_http import register_zotero_translate_routes
from research_harness_mcp.zotero_warmup_http import register_zotero_warmup_routes
from research_harness_mcp.tools import execute_tool
from research_harness_mcp.zotero_capabilities import (
    CapabilityResult,
    ZoteroCapabilityBroker,
    result_to_dynamic_tool_response,
    zotero_capability_paper_list,
    zotero_capability_paper_search,
    zotero_execute_read_tool,
)

PaginationMeta = _http_models.PaginationMeta
PaginatedResponse = _http_models.PaginatedResponse
DomainSummary = _http_models.DomainSummary
DomainDetail = _http_models.DomainDetail
CreateDomainRequest = _http_models.CreateDomainRequest
PatchDomainRequest = _http_models.PatchDomainRequest
PatchTopicRequest = _http_models.PatchTopicRequest
TopicSummary = _http_models.TopicSummary
TopicDetail = _http_models.TopicDetail
PaperDetail = _http_models.PaperDetail
RecordArtifactRequest = _http_models.RecordArtifactRequest
ForceAdvanceRequest = _http_models.ForceAdvanceRequest
CreateExperimentRequest = _http_models.CreateExperimentRequest
CreateTopicRequest = _http_models.CreateTopicRequest
AdvanceRequest = _http_models.AdvanceRequest
ExpansionRequest = _http_models.ExpansionRequest
PaperIngestRequest = _http_models.PaperIngestRequest
BatchEnrichRequest = _http_models.BatchEnrichRequest
RollbackRequest = _http_models.RollbackRequest

_default_zotero_codex_model = _zotero_models_http.default_zotero_codex_model
_validate_zotero_codex_model = _zotero_models_http.validate_zotero_codex_model
_require_zotero_chat_token = _zotero_chat_auth.require_zotero_chat_token
_sse_encode = _zotero_chat_stream_sse_encode
_zotero_execute_read_tool = zotero_execute_read_tool
_build_zotero_workflow_receipt = _zotero_workflow_receipt.build_zotero_workflow_receipt
_build_zotero_phase_b_gate_evidence = (
    _zotero_workflow_receipt.build_zotero_phase_b_gate_evidence
)
_zotero_push_result_dict = _zotero_workflow_receipt.zotero_push_result_dict
_zotero_workflow_receipt_summary = (
    _zotero_workflow_receipt.zotero_workflow_receipt_summary
)
_zotero_workflow_receipt_steps = _zotero_workflow_receipt.zotero_workflow_receipt_steps
_looks_like_zotero_create_collection_request = (
    _zotero_chat_intent.looks_like_zotero_create_collection_request
)
_extract_zotero_create_collection_name = (
    _zotero_chat_intent.extract_zotero_create_collection_name
)
_clean_zotero_collection_name = _zotero_chat_intent.clean_zotero_collection_name
_looks_like_unsupported_zotero_write_request = (
    _zotero_chat_intent.looks_like_unsupported_zotero_write_request
)
_looks_like_zotero_pdf_attachment_request = (
    _zotero_chat_intent.looks_like_zotero_pdf_attachment_request
)
_looks_like_zotero_import_request = _zotero_chat_intent.looks_like_zotero_import_request
_looks_like_zotero_metadata_edit_request = (
    _zotero_chat_intent.looks_like_zotero_metadata_edit_request
)
_last_zotero_path_segment = _zotero_chat_intent.last_zotero_path_segment
_zotero_names_equal = _zotero_chat_intent.zotero_names_equal
_looks_like_zotero_seed_search_request = (
    _zotero_chat_intent.looks_like_zotero_seed_search_request
)
_zotero_seed_request_flags = _zotero_chat_intent.zotero_seed_request_flags
_zotero_explicit_seed_topic_name = _zotero_chat_intent.zotero_explicit_seed_topic_name
_zotero_seed_search_query = _zotero_chat_intent.zotero_seed_search_query
_is_zotero_seed_placeholder_phrase = (
    _zotero_chat_intent.is_zotero_seed_placeholder_phrase
)
_extract_explicit_topic_id = _zotero_chat_intent.extract_explicit_topic_id
_message_targets_current_paper_only = (
    _zotero_chat_intent.message_targets_current_paper_only
)
_message_targets_deep_read_only = _zotero_chat_intent.message_targets_deep_read_only
_extract_zotero_import_count = _zotero_chat_intent.extract_zotero_import_count
_simple_chinese_number = _zotero_chat_intent.simple_chinese_number
_looks_like_zotero_directory_capability_question = (
    _zotero_chat_intent.looks_like_zotero_directory_capability_question
)
_finalize_zotero_action_preview = _zotero_action_preview.finalize_zotero_action_preview
_zotero_preview_target_source = _zotero_action_preview.zotero_preview_target_source
_unique_zotero_preview_warnings = _zotero_action_preview.unique_zotero_preview_warnings
_zotero_available_actions = _zotero_action_preview.zotero_available_actions
_normalize_zotero_chat_tags = _zotero_identity.normalize_zotero_chat_tags
_extract_rh_paper_id_tag = _zotero_identity.extract_rh_paper_id_tag
_extract_rh_topic_tag = _zotero_identity.extract_rh_topic_tag
_normalize_zotero_library_id = _zotero_identity.normalize_zotero_library_id
_normalize_doi = _zotero_identity.normalize_doi
_normalize_arxiv_id = _zotero_identity.normalize_arxiv_id
_normalize_title_for_match = _zotero_identity.normalize_title_for_match
_truncate_text = _zotero_identity.truncate_text
_infer_zotero_import_topic = _zotero_topic_lookup.infer_zotero_import_topic
_zotero_directory_topic_hints = _zotero_topic_lookup.zotero_directory_topic_hints
_find_zotero_topic_by_name = _zotero_topic_lookup.find_zotero_topic_by_name
_count_existing_zotero_collection_links = (
    _zotero_topic_lookup.count_existing_zotero_collection_links
)
_zotero_api_library_id = _zotero_write_access.zotero_api_library_id
_create_zotero_write_client = _zotero_write_access.create_zotero_write_client
_zotero_write_adapter = _zotero_write_access.zotero_write_adapter
_zotero_attachment_target_refs = (
    _zotero_attachment_targets.zotero_attachment_target_refs
)
_message_targets_last_preview = _zotero_attachment_targets.message_targets_last_preview
_zotero_attachment_target_source_for_plan = (
    _zotero_attachment_targets.zotero_attachment_target_source_for_plan
)
_unsupported_zotero_write_message = (
    _zotero_chat_responses.unsupported_zotero_write_message
)
_zotero_chat_suggested_actions = _zotero_chat_responses.zotero_chat_suggested_actions
_stable_zotero_chat_conversation_id = (
    _zotero_chat_responses.stable_zotero_chat_conversation_id
)
_resolve_zotero_chat_match = _zotero_chat_match.resolve_zotero_chat_match
_find_zotero_linked_paper = _zotero_chat_match.find_zotero_linked_paper
_find_paper_topic_for_chat = _zotero_chat_match.find_paper_topic_for_chat
_find_paper_by_bibliographic_context = (
    _zotero_chat_match.find_paper_by_bibliographic_context
)
_find_paper_by_field = _zotero_chat_match.find_paper_by_field
_zotero_chat_match_payload = _zotero_chat_match.zotero_chat_match_payload
_build_zotero_chat_assistant_message = (
    _zotero_chat_match.build_zotero_chat_assistant_message
)
_zotero_context_payload = _zotero_chat_match.zotero_context_payload
_zotero_codex_translate_effort = _zotero_translate_prompts.zotero_codex_translate_effort
_locale_label = _zotero_translate_prompts.locale_label
_zotero_codex_translate_instructions = (
    _zotero_translate_prompts.zotero_codex_translate_instructions
)
_zotero_codex_translate_prompt = _zotero_translate_prompts.zotero_codex_translate_prompt
_zotero_codex_cwd = _zotero_codex_settings.zotero_codex_cwd
_zotero_codex_effort = _zotero_codex_settings.zotero_codex_effort
_zotero_codex_service_tier = _zotero_codex_settings.zotero_codex_service_tier
_zotero_codex_base_instructions = _zotero_codex_settings.zotero_codex_base_instructions
_zotero_capability_mode = _zotero_codex_tooling.zotero_capability_mode
_normalize_zotero_codex_tool_name = (
    _zotero_codex_tooling.normalize_zotero_codex_tool_name
)
_coerce_codex_tool_arguments = _zotero_codex_tooling.coerce_codex_tool_arguments
_coerce_zotero_capability_count = _zotero_codex_tooling.coerce_zotero_capability_count
_codex_output_requests_seed_import_preview = (
    _zotero_codex_tooling.codex_output_requests_seed_import_preview
)
_zotero_seed_search_timeout_seconds = (
    _zotero_seed_preview.zotero_seed_search_timeout_seconds
)
_zotero_seed_candidate_preview = _zotero_seed_preview.zotero_seed_candidate_preview

logger = logging.getLogger(__name__)
# Ensure expansion-worker logs reach the console. Without this, uvicorn
# configures its own access logger at INFO but leaves application modules
# at WARNING with no root handler, so our logger.info() calls get swallowed.
_APP_LOG_HANDLER: logging.Handler | None = None
if not logging.getLogger().handlers:
    _APP_LOG_HANDLER = logging.StreamHandler()
    _APP_LOG_HANDLER.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logging.getLogger().addHandler(_APP_LOG_HANDLER)
    logging.getLogger().setLevel(logging.INFO)
logger.setLevel(logging.INFO)
logging.getLogger("research_harness").setLevel(logging.INFO)
logging.getLogger("research_harness_mcp").setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# DB path resolution
# ---------------------------------------------------------------------------

_DEFAULT_DB_PATH = Path(__file__).resolve().parents[3] / ".research-harness" / "pool.db"

DB_PATH = Path(os.environ.get("RESEARCH_HARNESS_DB_PATH") or str(_DEFAULT_DB_PATH))

LONGTASK_HOME = Path(
    os.environ.get("RESEARCH_HARNESS_LONGTASK_HOME")
    or str(DB_PATH.parent.parent / ".longrun")
)

_CORS_ALLOWED_ORIGINS = _knowledge_http._CORS_ALLOWED_ORIGINS
_KNOWLEDGE_API_CACHE_CONTROL = _knowledge_http._KNOWLEDGE_API_CACHE_CONTROL
_KNOWLEDGE_API_TOKEN_ENV = _knowledge_http._KNOWLEDGE_API_TOKEN_ENV
_configured_cors_origins = _knowledge_http._configured_cors_origins
_is_knowledge_api_path = _knowledge_http._is_knowledge_api_path
_knowledge_api_cors_headers = _knowledge_http._knowledge_api_cors_headers
_knowledge_api_error_response = _knowledge_http._knowledge_api_error_response
_knowledge_api_token_candidates = _knowledge_http._knowledge_api_token_candidates
_knowledge_api_token_matches = _knowledge_http._knowledge_api_token_matches
_parse_cross_topic_max_results = _knowledge_http._parse_cross_topic_max_results
_parse_positive_topic_id = _knowledge_http._parse_positive_topic_id


def _materialize_topic_workspace_http(
    *,
    topic_id: int,
    topic_name: str,
    description: str = "",
    target_venue: str = "",
    deadline: str = "",
    domain_name: str | None = None,
) -> str | None:
    return _topic_workspace_http.materialize_topic_workspace_http(
        db_path=DB_PATH,
        topic_id=topic_id,
        topic_name=topic_name,
        description=description,
        target_venue=target_venue,
        deadline=deadline,
        domain_name=domain_name,
    )


# ---------------------------------------------------------------------------
# Allowed PDF roots (for /api/papers/{id}/pdf — guards against path traversal
# from arbitrary pdf_path values stored in the DB)
# ---------------------------------------------------------------------------


_default_pdf_roots = _pdf_roots.default_pdf_roots
PDF_ROOTS = _pdf_roots.configured_pdf_roots()


def get_db():
    """Yield a sqlite3 connection with Row factory and WAL mode."""
    return _db_http.open_http_db(DB_PATH)


_row_to_dict = _http_helpers.row_to_dict
_rows_to_list = _http_helpers.rows_to_list
_parse_json_field = _http_helpers.parse_json_field


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------


_http_auth.enforce_direct_asgi_bind_argv(sys.argv)


def _close_zotero_codex_pool() -> None:
    _zotero_codex_runtime.close_zotero_codex_pool(log=logger)


@asynccontextmanager
async def app_lifespan(_app: FastAPI):
    # Match the CLI's env autoload so provider-readiness gates answer the
    # same over HTTP as they do for `rh` commands.
    from research_harness.env_bootstrap import ensure_default_env_loaded

    ensure_default_env_loaded()
    try:
        yield
    finally:
        _close_zotero_codex_pool()


app = FastAPI(
    title="Research Harness API",
    description="REST API for the research-harness pool.db — read endpoints + write/action endpoints via MCP tools",
    version=_MCP_VERSION,
    lifespan=app_lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def sensitive_route_token_middleware(request: Request, call_next):
    """Optional global token gate for sensitive local HTTP routes."""
    return await _http_auth.sensitive_route_token_middleware(request, call_next)


@app.middleware("http")
async def longtask_admin_token_middleware(request: Request, call_next):
    """Optional local admin token gate for LongTask HTTP endpoints."""
    return await _longtask_auth_http.longtask_admin_token_middleware(request, call_next)


@app.middleware("http")
async def knowledge_api_beta_token_middleware(request: Request, call_next):
    """Optional beta token gate for read-only Topic Knowledge HTTP endpoints."""
    return await _knowledge_http.knowledge_api_beta_token_middleware(request, call_next)


def __getattr__(name: str) -> Any:
    if name == "_knowledge_api_error":
        return _knowledge_http._knowledge_api_error_response
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ===========================================================================
# WRITE / ACTION ENDPOINTS
# ===========================================================================
#
# These endpoints mutate state — either via raw SQL INSERT or by delegating
# to MCP tool handlers through execute_tool(name, arguments).
# ---------------------------------------------------------------------------


def _run_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return _tool_execution_http.run_tool(
        name,
        arguments,
        execute_tool_fn=execute_tool,
        logger=logger,
    )


_now_iso = _http_helpers.now_iso
_serialize_result = _http_helpers.serialize_result
_topic_exists = _http_helpers.topic_exists


def _search_papers_impl(
    api: ResearchAPI, *, query: str, topic_id: int | None = None, max_results: int = 50
) -> dict[str, Any]:
    return _topic_expansion_helpers.search_papers_impl(
        api,
        query=query,
        topic_id=topic_id,
        max_results=max_results,
        serialize_result=_serialize_result,
    )


def _ingest_paper_impl(
    api: ResearchAPI,
    *,
    source: str,
    topic_id: int | None = None,
    relevance: str = "medium",
) -> dict[str, Any]:
    return _topic_expansion_helpers.ingest_paper_impl(
        api,
        source=source,
        topic_id=topic_id,
        relevance=relevance,
        serialize_result=_serialize_result,
    )


def _deep_read_paper_impl(
    api: ResearchAPI, *, paper_id: int, topic_id: int, focus: str = ""
) -> dict[str, Any]:
    return _topic_expansion_helpers.deep_read_paper_impl(
        paper_id=paper_id,
        topic_id=topic_id,
        focus=focus,
        execute_tool_fn=execute_tool,
        get_db_context=get_db,
        serialize_result=_serialize_result,
    )


def _expansion_job_is_cancelled(job_id: int) -> bool:
    return _topic_expansion_helpers.expansion_job_is_cancelled(
        job_id,
        get_db_context=get_db,
    )


def _update_expansion_job(
    conn: sqlite3.Connection,
    job_id: int,
    *,
    status: str | None = None,
    current_round: int | None = None,
    papers_fetched: int | None = None,
    papers_deep_read: int | None = None,
    last_error: str | None = None,
) -> None:
    _topic_expansion_helpers.update_expansion_job(
        conn,
        job_id,
        now_iso=_now_iso,
        status=status,
        current_round=current_round,
        papers_fetched=papers_fetched,
        papers_deep_read=papers_deep_read,
        last_error=last_error,
    )


_pick_candidate_source = _topic_expansion_helpers.pick_candidate_source
_find_paper_id_in_topic_by_source = (
    _topic_expansion_helpers.find_paper_id_in_topic_by_source
)


def _get_or_create_zotero_seed_topic(
    *, topic_id: int | None, topic_name: str, description: str
) -> tuple[int, bool]:
    return _zotero_seed_topic.get_or_create_zotero_seed_topic(
        topic_id=topic_id,
        topic_name=topic_name,
        description=description,
        get_db_context=get_db,
        materialize_topic_workspace=_materialize_topic_workspace_http,
        run_tool=_run_tool,
        now_iso=_now_iso,
        missing_topic_error=lambda missing_topic_id: HTTPException(
            status_code=404,
            detail=f"Topic {missing_topic_id} not found",
        ),
        bootstrap_exception_types=(HTTPException,),
        log_warning=logger.warning,
    )


_paper_already_in_topic = _topic_expansion_helpers.paper_already_in_topic
_build_expansion_query = _topic_expansion_helpers.build_expansion_query
_get_latest_expansion_job = _topic_expansion_helpers.latest_expansion_job
_topic_paper_stats = _topic_expansion_helpers.topic_paper_stats
_deep_read_provider_pool = _topic_expansion_helpers.deep_read_provider_pool
_expansion_deep_read_concurrency = (
    _topic_expansion_helpers.expansion_deep_read_concurrency
)
_expansion_deep_read_paper_timeout = (
    _topic_expansion_helpers.expansion_deep_read_paper_timeout
)


def _run_expansion_job(job_id: int, topic_id: int) -> None:
    _topic_expansion_job.run_expansion_job(
        job_id,
        topic_id,
        db_path=DB_PATH,
        api_factory=lambda *, db_path: ResearchAPI(db_path=db_path),
        get_db_context=get_db,
        update_expansion_job=_update_expansion_job,
        expansion_job_is_cancelled=_expansion_job_is_cancelled,
        build_expansion_query=_build_expansion_query,
        search_papers_impl=_search_papers_impl,
        ingest_paper_impl=_ingest_paper_impl,
        deep_read_paper_impl=_deep_read_paper_impl,
        pick_candidate_source=_pick_candidate_source,
        paper_already_in_topic=_paper_already_in_topic,
        deep_read_provider_pool=_deep_read_provider_pool,
        expansion_deep_read_concurrency=_expansion_deep_read_concurrency,
        expansion_deep_read_paper_timeout=_expansion_deep_read_paper_timeout,
        logger_obj=logger,
    )


def _workbench_pending_decisions(topic_id: int) -> dict[str, Any]:
    from research_harness_mcp.tools_decision import paper_production_pending_decisions

    return paper_production_pending_decisions(topic_id)


def _workbench_record_decision(
    topic_id: int, choice: str, reasoning: str
) -> dict[str, Any]:
    from research_harness.auto_runner.runner import decide_human_checkpoint

    return decide_human_checkpoint(
        topic_id,
        choice=choice,
        reasoning=reasoning,
        db=Database(DB_PATH),
        actor="web",
    )


def _workbench_chat_reply(prompt: str) -> str:
    from llm_router.client import LLMClient

    return LLMClient().chat(prompt)


def _workbench_create_topic(
    *,
    name: str,
    description: str,
    target_venue: str,
    deadline: str,
    mode: str,
) -> dict[str, Any]:
    """Create a new topic plus orchestrator run/checkpoint for the workbench.

    Reuses the same entry path as ``rh`` so the new study is immediately
    visible in the workbench's topic list and paper-production runs. The
    entry path stores ``description`` as the topic name, so any caller-supplied
    description/deadline is applied afterwards.
    """
    from research_harness.auto_runner.paper_production_entry import (
        prepare_paper_production_entry,
    )

    db = Database(DB_PATH)
    result = prepare_paper_production_entry(
        db=db,
        topic=name,
        target_venue=target_venue,
        mode=mode,
    )
    topic_id = int(result["topic"]["id"])
    if description or deadline:
        conn = db.connect()
        try:
            if description:
                conn.execute(
                    "UPDATE topics SET description = ? WHERE id = ?",
                    (description, topic_id),
                )
                result["topic"]["description"] = description
            if deadline:
                conn.execute(
                    "UPDATE topics SET deadline = ? WHERE id = ?",
                    (deadline, topic_id),
                )
                result["topic"]["deadline"] = deadline
            conn.commit()
        finally:
            conn.close()
    return result


def _non_zotero_route_deps() -> dict[str, Any]:
    return {
        "api_factory": lambda: ResearchAPI(db_path=DB_PATH),
        "database_factory": lambda: Database(DB_PATH),
        "db_path_provider": lambda: DB_PATH,
        "deep_read_paper_impl": lambda api, **kwargs: _deep_read_paper_impl(
            api, **kwargs
        ),
        "demo_list_entries": demo_list_entries,
        "demo_lookup": demo_lookup,
        "get_db_context": lambda: get_db(),
        "get_latest_expansion_job": _get_latest_expansion_job,
        "ingest_paper_impl": lambda api, **kwargs: _ingest_paper_impl(api, **kwargs),
        "knowledge_api_cache_control": _KNOWLEDGE_API_CACHE_CONTROL,
        "knowledge_api_error": _knowledge_http._knowledge_api_error_response,
        "logger": logger,
        "longtask_home_provider": lambda: LONGTASK_HOME,
        "materialize_topic_workspace": (
            lambda **kwargs: _materialize_topic_workspace_http(**kwargs)
        ),
        "now_factory": lambda: datetime.now(timezone.utc),
        "now_iso": _now_iso,
        "parse_json_field": _parse_json_field,
        "parse_positive_topic_id": _parse_positive_topic_id,
        "pdf_roots_provider": lambda: PDF_ROOTS,
        "research_service_factory": lambda db_path: ResearchService(db=db_path),
        "research_service_invoke": (
            lambda command_name, arguments: ResearchService(db=DB_PATH).invoke(
                command_name,
                arguments,
            )
        ),
        "row_to_dict": _row_to_dict,
        "rows_to_list": _rows_to_list,
        "run_expansion_job": lambda job_id, topic_id: _run_expansion_job(
            job_id, topic_id
        ),
        "run_tool": lambda name, arguments: _run_tool(name, arguments),
        "search_papers_impl": lambda api, **kwargs: _search_papers_impl(api, **kwargs),
        "topic_exists": _topic_exists,
        "topic_paper_stats": _topic_paper_stats,
        "update_expansion_job": _update_expansion_job,
        "workbench_chat_reply": _workbench_chat_reply,
        "workbench_create_topic": _workbench_create_topic,
        "workbench_pending_decisions": _workbench_pending_decisions,
        "workbench_record_decision": _workbench_record_decision,
    }


_http_non_zotero_routes.register_routes_before_zotero(app, _non_zotero_route_deps())


def _create_zotero_sync_service(**kwargs: Any) -> Any:
    from research_harness.zotero_sync import ZoteroSyncService

    return ZoteroSyncService(**kwargs)


register_topic_zotero_sync_routes(
    app,
    zotero_sync_request_model=ZoteroSyncRequest,
    require_zotero_chat_token=lambda request: _require_zotero_chat_token(request),
    get_db_context=get_db,
    db_path_provider=lambda: DB_PATH,
    zotero_api_library_id=lambda value, library_type: _zotero_api_library_id(
        value, library_type
    ),
    create_zotero_write_client=lambda **kwargs: _create_zotero_write_client(**kwargs),
    build_zotero_workflow_receipt=lambda **kwargs: _build_zotero_workflow_receipt(
        **kwargs
    ),
    build_zotero_phase_b_gate_evidence=lambda **kwargs: (
        _build_zotero_phase_b_gate_evidence(**kwargs)
    ),
    zotero_sync_service_factory=lambda **kwargs: _create_zotero_sync_service(**kwargs),
    env_get=lambda key, default="": os.getenv(key, default),
)


register_zotero_seed_apply_routes(
    app,
    zotero_seed_paper_apply_request_model=ZoteroSeedPaperApplyRequest,
    require_zotero_chat_token=lambda request: _require_zotero_chat_token(request),
    get_db_context=get_db,
    db_path_provider=lambda: DB_PATH,
    last_zotero_path_segment=lambda path: _last_zotero_path_segment(path),
    get_or_create_zotero_seed_topic=lambda **kwargs: _get_or_create_zotero_seed_topic(
        **kwargs
    ),
    research_api_factory=lambda: ResearchAPI(db_path=DB_PATH),
    find_paper_id_in_topic_by_source=lambda conn, topic_id, source: (
        _find_paper_id_in_topic_by_source(conn, topic_id, source)
    ),
    ingest_paper_impl=lambda api, **kwargs: _ingest_paper_impl(api, **kwargs),
    deep_read_paper_impl=lambda api, **kwargs: _deep_read_paper_impl(api, **kwargs),
    run_tool=lambda name, arguments: execute_tool(name, arguments),
    apply_rh_pdf_annotations_for_papers=lambda **kwargs: (
        _apply_rh_pdf_annotations_for_papers(**kwargs)
    ),
    zotero_api_library_id=lambda value, library_type: _zotero_api_library_id(
        value, library_type
    ),
    create_zotero_write_client=lambda **kwargs: _create_zotero_write_client(**kwargs),
    build_zotero_workflow_receipt=lambda **kwargs: _build_zotero_workflow_receipt(
        **kwargs
    ),
    build_zotero_phase_b_gate_evidence=lambda **kwargs: (
        _build_zotero_phase_b_gate_evidence(**kwargs)
    ),
    zotero_sync_service_factory=lambda **kwargs: _create_zotero_sync_service(**kwargs),
    env_get=lambda key, default="": os.getenv(key, default),
)


register_zotero_chat_routes(
    app,
    zotero_chat_request_model=ZoteroChatRequest,
    zotero_chat_item_context_model=ZoteroChatItemContext,
    require_zotero_chat_token=lambda request: _require_zotero_chat_token(request),
    get_db_context=get_db,
    resolve_zotero_chat_match=lambda conn, item: _resolve_zotero_chat_match(conn, item),
    build_zotero_codex_handoff_prompt=lambda body, matched: (
        _build_zotero_codex_handoff_prompt(body, matched)
    ),
    build_zotero_chat_assistant_message=lambda body, matched: (
        _build_zotero_chat_assistant_message(body, matched)
    ),
    zotero_context_payload=lambda body, matched: _zotero_context_payload(body, matched),
    zotero_available_actions=lambda context, matched: _zotero_available_actions(
        context, matched
    ),
    stable_zotero_chat_conversation_id=lambda body, matched: (
        _stable_zotero_chat_conversation_id(body, matched)
    ),
    zotero_chat_suggested_actions=lambda matched: _zotero_chat_suggested_actions(
        matched
    ),
)


register_zotero_warmup_routes(
    app,
    zotero_warmup_request_model=ZoteroWarmupRequest,
    require_zotero_chat_token=lambda request: _require_zotero_chat_token(request),
    zotero_codex_cwd=lambda: _zotero_codex_cwd(),
    zotero_codex_effort=lambda: _zotero_codex_effort(),
    zotero_codex_translate_effort=lambda: _zotero_codex_translate_effort(),
    zotero_codex_service_tier=lambda: _zotero_codex_service_tier(),
    warm_zotero_codex_pool=lambda **kwargs: _warm_zotero_codex_pool(**kwargs),
)


register_zotero_translate_routes(
    app,
    zotero_translate_request_model=ZoteroTranslateRequest,
    require_zotero_chat_token=lambda request: _require_zotero_chat_token(request),
    stream_zotero_codex_translate=lambda **kwargs: _stream_zotero_codex_translate(
        **kwargs
    ),
    sse_encode=lambda event, payload: _sse_encode(event, payload),
)


def _stream_zotero_codex_translate(
    *,
    text: str,
    model: str,
    target_locale: str,
    source_locale: str = "",
) -> Any:
    yield from _zotero_codex_translate.stream_zotero_codex_translate(
        text=text,
        model=model,
        target_locale=target_locale,
        source_locale=source_locale,
        build_instructions=_zotero_codex_translate_instructions,
        build_prompt=_zotero_codex_translate_prompt,
        cwd_provider=_zotero_codex_cwd,
        effort_provider=_zotero_codex_translate_effort,
        service_tier_provider=_zotero_codex_service_tier,
        pool_factory=_zotero_codex_pool,
        log_info=logger.info,
    )


register_zotero_chat_stream_routes(
    app,
    zotero_chat_request_model=ZoteroChatRequest,
    require_zotero_chat_token=lambda request: _require_zotero_chat_token(request),
    get_db_context=get_db,
    resolve_zotero_chat_match=lambda conn, item: _resolve_zotero_chat_match(conn, item),
    stable_zotero_chat_conversation_id=lambda body, matched: (
        _stable_zotero_chat_conversation_id(body, matched)
    ),
    zotero_codex_thread_store=lambda: _zotero_codex_thread_store(),
    build_zotero_codex_turn_prompt=lambda body, matched, is_followup: (
        _build_zotero_codex_turn_prompt(
            body,
            matched,
            is_followup=is_followup,
        )
    ),
    zotero_context_payload=lambda body, matched: _zotero_context_payload(body, matched),
    zotero_available_actions=lambda context, matched: _zotero_available_actions(
        context, matched
    ),
    zotero_chat_suggested_actions=lambda matched: _zotero_chat_suggested_actions(
        matched
    ),
    plan_zotero_write_intent=lambda **kwargs: _plan_zotero_write_intent(**kwargs),
    maybe_prepare_zotero_chat_action=lambda body, matched: (
        _maybe_prepare_zotero_chat_action(body, matched)
    ),
    preview_zotero_write_plan=lambda **kwargs: _preview_zotero_write_plan(**kwargs),
    stream_zotero_codex_turn=lambda **kwargs: _stream_zotero_codex_turn(**kwargs),
    save_zotero_codex_thread=lambda **kwargs: _save_zotero_codex_thread(**kwargs),
    maybe_prepare_zotero_codex_output_action=lambda **kwargs: (
        _maybe_prepare_zotero_codex_output_action(**kwargs)
    ),
    extract_zotero_import_count=lambda message: _extract_zotero_import_count(message),
    sse_encode=lambda event, payload: _sse_encode(event, payload),
)


def _plan_zotero_write_intent(
    *,
    body: ZoteroChatRequest,
    matched: dict[str, Any],
    context_payload: dict[str, Any],
) -> dict[str, Any]:
    return _zotero_write_plan.plan_zotero_write_intent(
        body=body,
        matched=matched,
        context_payload=context_payload,
        zotero_capability_mode=_zotero_capability_mode,
        looks_like_zotero_create_collection_request=(
            _looks_like_zotero_create_collection_request
        ),
        extract_zotero_create_collection_name=_extract_zotero_create_collection_name,
        looks_like_zotero_seed_search_request=_looks_like_zotero_seed_search_request,
        extract_zotero_import_count=_extract_zotero_import_count,
        zotero_seed_request_flags=_zotero_seed_request_flags,
        zotero_explicit_seed_topic_name=_zotero_explicit_seed_topic_name,
        zotero_seed_search_query=_zotero_seed_search_query,
        zotero_attachment_target_source_for_plan=(
            _zotero_attachment_target_source_for_plan
        ),
        looks_like_zotero_pdf_attachment_request=(
            _looks_like_zotero_pdf_attachment_request
        ),
        looks_like_zotero_import_request=_looks_like_zotero_import_request,
        looks_like_unsupported_zotero_write_request=(
            _looks_like_unsupported_zotero_write_request
        ),
        unsupported_zotero_write_message=_unsupported_zotero_write_message,
    )


def _preview_zotero_write_plan(
    *,
    body: ZoteroChatRequest,
    matched: dict[str, Any],
    context_payload: dict[str, Any],
    plan: dict[str, Any],
) -> CapabilityResult:
    return _zotero_write_plan.preview_zotero_write_plan(
        body=body,
        matched=matched,
        context_payload=context_payload,
        plan=plan,
        build_zotero_capability_broker=_build_zotero_capability_broker,
        zotero_capability_mode=_zotero_capability_mode,
    )


def _zotero_codex_thread_store():
    return _zotero_codex_runtime.zotero_codex_thread_store(db_path=DB_PATH)


_zotero_codex_pool = _zotero_codex_runtime.zotero_codex_pool


def _warm_zotero_codex_pool(
    *,
    cwd: str | Path,
    model: str,
    effort: str,
    service_tier: str | None,
) -> None:
    _zotero_codex_runtime.warm_zotero_codex_pool(
        cwd=cwd,
        model=model,
        effort=effort,
        service_tier=service_tier,
        pool_factory=_zotero_codex_pool,
        log=logger,
    )


def _save_zotero_codex_thread(
    *,
    store: Any,
    conversation_id: str,
    thread_id: str,
    matched: dict[str, Any],
    item: ZoteroChatItemContext,
) -> None:
    _zotero_codex_runtime.save_zotero_codex_thread(
        store=store,
        conversation_id=conversation_id,
        thread_id=thread_id,
        matched=matched,
        item=item,
        log=logger,
    )


def _stream_zotero_codex_turn(
    *,
    body: ZoteroChatRequest,
    conversation_id: str,
    existing_thread_id: str | None,
    prompt: str,
    matched: dict[str, Any],
    context_payload: dict[str, Any],
    model: str,
    image_urls: list[str] | None = None,
) -> Any:
    yield from _zotero_codex_runtime.stream_zotero_codex_turn(
        conversation_id=conversation_id,
        existing_thread_id=existing_thread_id,
        prompt=prompt,
        model=model,
        image_urls=image_urls,
        build_instructions=_zotero_codex_base_instructions,
        cwd_provider=_zotero_codex_cwd,
        effort_provider=_zotero_codex_effort,
        service_tier_provider=_zotero_codex_service_tier,
        pool_factory=_zotero_codex_pool,
        dynamic_tool_handler_factory=lambda: _zotero_codex_dynamic_tool_handler(
            body=body,
            matched=matched,
            context_payload=context_payload,
        ),
        log=logger,
    )


def _zotero_codex_dynamic_tool_handler(
    *,
    body: ZoteroChatRequest,
    matched: dict[str, Any],
    context_payload: dict[str, Any],
):
    return _zotero_codex_dynamic_tools.zotero_codex_dynamic_tool_handler(
        body=body,
        matched=matched,
        context_payload=context_payload,
        build_zotero_capability_broker=_build_zotero_capability_broker,
        zotero_capability_mode=_zotero_capability_mode,
        normalize_zotero_codex_tool_name=_normalize_zotero_codex_tool_name,
        coerce_codex_tool_arguments=_coerce_codex_tool_arguments,
        capability_result_cls=CapabilityResult,
        result_to_dynamic_tool_response=result_to_dynamic_tool_response,
    )


def _build_zotero_capability_broker(
    *,
    body: ZoteroChatRequest,
    matched: dict[str, Any],
    context_payload: dict[str, Any],
) -> ZoteroCapabilityBroker:
    return _zotero_capability_broker.build_zotero_capability_broker(
        body=body,
        matched=matched,
        context_payload=context_payload,
        zotero_capability_paper_list=_zotero_capability_paper_list,
        zotero_capability_paper_search=_zotero_capability_paper_search,
        zotero_preview_seed_import=_zotero_preview_seed_import,
        zotero_preview_create_collection=_zotero_preview_create_collection,
        zotero_preview_sync_papers=_zotero_preview_sync_papers,
        zotero_preview_attach_pdf=_zotero_preview_attach_pdf,
        zotero_execute_read_tool=_zotero_execute_read_tool,
    )


def _zotero_capability_paper_list(
    args: dict[str, Any],
    _context: dict[str, Any],
) -> dict[str, Any]:
    return zotero_capability_paper_list(
        args,
        _context,
        get_db_context=get_db,
        parse_json_field=_parse_json_field,
    )


def _zotero_capability_paper_search(
    args: dict[str, Any],
    _context: dict[str, Any],
) -> dict[str, Any]:
    return zotero_capability_paper_search(
        args,
        _context,
        api_factory=lambda: ResearchAPI(db_path=DB_PATH),
        search_papers_impl=_search_papers_impl,
    )


def _zotero_preview_seed_import(
    *,
    body: ZoteroChatRequest,
    matched: dict[str, Any],
    args: dict[str, Any],
) -> dict[str, Any]:
    return _zotero_capability_previews.zotero_preview_seed_import(
        body=body,
        matched=matched,
        args=args,
        last_zotero_path_segment=_last_zotero_path_segment,
        coerce_zotero_capability_count=_coerce_zotero_capability_count,
        build_zotero_seed_papers_preview=_build_zotero_seed_papers_preview,
    )


def _zotero_preview_create_collection(
    *,
    body: ZoteroChatRequest,
    matched: dict[str, Any],
    args: dict[str, Any],
) -> dict[str, Any]:
    return _zotero_capability_previews.zotero_preview_create_collection(
        body=body,
        matched=matched,
        args=args,
        prepare_zotero_create_collection_action=(
            _prepare_zotero_create_collection_action
        ),
    )


def _zotero_preview_sync_papers(
    *,
    body: ZoteroChatRequest,
    matched: dict[str, Any],
    args: dict[str, Any],
) -> dict[str, Any]:
    return _zotero_capability_previews.zotero_preview_sync_papers(
        body=body,
        matched=matched,
        args=args,
        maybe_prepare_zotero_chat_action=_maybe_prepare_zotero_chat_action,
    )


def _zotero_preview_attach_pdf(
    *,
    body: ZoteroChatRequest,
    matched: dict[str, Any],
    args: dict[str, Any],
) -> dict[str, Any]:
    return _zotero_capability_previews.zotero_preview_attach_pdf(
        body=body,
        matched=matched,
        args=args,
        zotero_attachment_target_refs=_zotero_attachment_target_refs,
        prepare_zotero_pdf_attachment_action=_prepare_zotero_pdf_attachment_action,
    )


def _maybe_prepare_zotero_codex_output_action(
    *,
    body: ZoteroChatRequest,
    matched: dict[str, Any],
    assistant_text: str,
    context_payload: dict[str, Any],
) -> dict[str, Any] | None:
    return _zotero_codex_output.maybe_prepare_zotero_codex_output_action(
        body=body,
        matched=matched,
        assistant_text=assistant_text,
        context_payload=context_payload,
        zotero_capability_mode=_zotero_capability_mode,
        codex_output_requests_seed_import_preview=(
            _codex_output_requests_seed_import_preview
        ),
        extract_zotero_import_count=_extract_zotero_import_count,
        zotero_preview_seed_import=_zotero_preview_seed_import,
    )


def _build_zotero_codex_turn_prompt(
    body: ZoteroChatRequest,
    matched: dict[str, Any],
    *,
    is_followup: bool,
) -> str:
    return _zotero_codex_prompts.build_zotero_codex_turn_prompt(
        body,
        matched,
        is_followup=is_followup,
        build_zotero_capability_broker=_build_zotero_capability_broker,
    )


def _build_zotero_codex_handoff_prompt(
    body: ZoteroChatRequest, matched: dict[str, Any]
) -> str:
    return _zotero_codex_prompts.build_zotero_codex_handoff_prompt(
        body,
        matched,
        build_zotero_capability_broker=_build_zotero_capability_broker,
    )


def _prepare_zotero_seed_papers_action(
    body: ZoteroChatRequest, matched: dict[str, Any]
) -> dict[str, Any] | None:
    return _zotero_seed_preview.prepare_zotero_seed_papers_action(
        body=body,
        matched=matched,
        looks_like_zotero_seed_search_request=_looks_like_zotero_seed_search_request,
        zotero_explicit_seed_topic_name=_zotero_explicit_seed_topic_name,
        build_zotero_seed_papers_preview=_build_zotero_seed_papers_preview,
    )


def _build_zotero_seed_papers_preview(
    *,
    body: ZoteroChatRequest,
    matched: dict[str, Any],
    topic_name: str = "",
    query: str | None = None,
    requested_count: int | None = None,
    request_flags: dict[str, bool] | None = None,
) -> dict[str, Any]:
    return _zotero_seed_preview.build_zotero_seed_papers_preview(
        body=body,
        matched=matched,
        topic_name=topic_name,
        query=query,
        requested_count=requested_count,
        request_flags=request_flags,
        get_db=get_db,
        find_zotero_topic_by_name=_find_zotero_topic_by_name,
        infer_zotero_import_topic=_infer_zotero_import_topic,
        last_zotero_path_segment=_last_zotero_path_segment,
        zotero_seed_search_query=_zotero_seed_search_query,
        extract_zotero_import_count=_extract_zotero_import_count,
        zotero_names_equal=_zotero_names_equal,
        research_api_factory=lambda: ResearchAPI(db_path=DB_PATH),
        search_papers_impl=_search_papers_impl,
        seed_search_timeout_seconds=_zotero_seed_search_timeout_seconds,
        pick_candidate_source=_pick_candidate_source,
        seed_candidate_preview=_zotero_seed_candidate_preview,
        zotero_api_library_id=_zotero_api_library_id,
        zotero_seed_request_flags=_zotero_seed_request_flags,
        finalize_zotero_action_preview=_finalize_zotero_action_preview,
    )


def _prepare_zotero_create_collection_action(
    body: ZoteroChatRequest, matched: dict[str, Any]
) -> dict[str, Any] | None:
    return _zotero_collection_actions.prepare_zotero_create_collection_action(
        body,
        matched,
        looks_like_zotero_create_collection_request=(
            _looks_like_zotero_create_collection_request
        ),
        zotero_context_payload=_zotero_context_payload,
        extract_zotero_create_collection_name=_extract_zotero_create_collection_name,
        normalize_zotero_library_id=_normalize_zotero_library_id,
        finalize_zotero_action_preview=_finalize_zotero_action_preview,
    )


def _prepare_zotero_sync_papers_action(
    body: ZoteroChatRequest,
    matched: dict[str, Any],
    *,
    action_type: str,
) -> dict[str, Any] | None:
    from research_harness.zotero_sync import (
        _record_preview,
        filter_sync_records_by_paper_ids,
        load_topic_sync_records,
    )

    return _zotero_sync_actions.prepare_zotero_sync_papers_action(
        body,
        matched,
        action_type=action_type,
        get_db=get_db,
        infer_zotero_import_topic=_infer_zotero_import_topic,
        load_topic_sync_records=load_topic_sync_records,
        filter_sync_records_by_paper_ids=filter_sync_records_by_paper_ids,
        record_preview=_record_preview,
        message_targets_current_paper_only=_message_targets_current_paper_only,
        message_targets_deep_read_only=_message_targets_deep_read_only,
        extract_zotero_import_count=_extract_zotero_import_count,
        zotero_api_library_id=_zotero_api_library_id,
        count_existing_zotero_collection_links=(
            _count_existing_zotero_collection_links
        ),
        finalize_zotero_action_preview=_finalize_zotero_action_preview,
    )


def _maybe_prepare_zotero_chat_action(
    body: ZoteroChatRequest, matched: dict[str, Any]
) -> dict[str, Any] | None:
    return _zotero_chat_actions.maybe_prepare_zotero_chat_action(
        body,
        matched,
        extract_zotero_import_count=_extract_zotero_import_count,
        zotero_seed_request_flags=_zotero_seed_request_flags,
        zotero_explicit_seed_topic_name=_zotero_explicit_seed_topic_name,
        zotero_seed_search_query=_zotero_seed_search_query,
        zotero_preview_seed_import=_zotero_preview_seed_import,
        zotero_context_payload=_zotero_context_payload,
        zotero_attachment_target_source_for_plan=(
            _zotero_attachment_target_source_for_plan
        ),
        zotero_attachment_target_refs=_zotero_attachment_target_refs,
        prepare_zotero_pdf_attachment_action=_prepare_zotero_pdf_attachment_action,
        prepare_zotero_create_collection_action=(
            _prepare_zotero_create_collection_action
        ),
        zotero_available_actions=_zotero_available_actions,
        sync_papers_action_types=_zotero_sync_actions.SYNC_PAPERS_ACTION_TYPES,
        prepare_zotero_sync_papers_action=_prepare_zotero_sync_papers_action,
    )


def _prepare_zotero_pdf_attachment_action(
    body: ZoteroChatRequest,
    matched: dict[str, Any],
    *,
    target_refs: list[ZoteroChatTargetRef] | None = None,
    target_source: str = "",
) -> dict[str, Any] | None:
    return _zotero_pdf_attachment.prepare_zotero_pdf_attachment_action(
        body,
        matched,
        target_refs=target_refs,
        target_source=target_source,
        looks_like_zotero_pdf_attachment_request=(
            _looks_like_zotero_pdf_attachment_request
        ),
        get_db_context=get_db,
        ensure_zotero_attachable_pdf=ensure_zotero_attachable_pdf,
        normalize_zotero_library_id=_normalize_zotero_library_id,
        finalize_zotero_action_preview=_finalize_zotero_action_preview,
        prepare_zotero_pdf_attachment_batch_action=(
            _prepare_zotero_pdf_attachment_batch_action
        ),
    )


ZoteroAttachablePdf = _zotero_pdf_attachment.ZoteroAttachablePdf
_zotero_paper_has_download_source = (
    _zotero_pdf_attachment.zotero_paper_has_download_source
)
_download_zotero_attachable_pdf = _zotero_pdf_attachment.download_zotero_attachable_pdf


def ensure_zotero_attachable_pdf(
    conn: sqlite3.Connection, paper_id: int
) -> ZoteroAttachablePdf:
    return _zotero_pdf_attachment.ensure_zotero_attachable_pdf(
        conn,
        paper_id,
        db_path=DB_PATH,
        trusted_pdf_path_for_zotero=_trusted_pdf_path_for_zotero,
        trusted_pdf_roots_for_zotero=_trusted_pdf_roots_for_zotero,
        download_zotero_attachable_pdf=_download_zotero_attachable_pdf,
        logger=logger,
    )


def _zotero_attachable_pdf_download_dir() -> tuple[Path | None, str | None]:
    return _zotero_pdf_attachment.zotero_attachable_pdf_download_dir(
        db_path=DB_PATH,
        trusted_pdf_roots_for_zotero=_trusted_pdf_roots_for_zotero,
    )


def _prepare_zotero_pdf_attachment_batch_action(
    *,
    body: ZoteroChatRequest,
    matched: dict[str, Any],
    target_refs: list[ZoteroChatTargetRef],
    target_source: str,
) -> dict[str, Any]:
    return _zotero_pdf_attachment.prepare_zotero_pdf_attachment_batch_action(
        body=body,
        matched=matched,
        target_refs=target_refs,
        target_source=target_source,
        get_db_context=get_db,
        resolve_zotero_attachment_target=_resolve_zotero_attachment_target,
        ensure_zotero_attachable_pdf=ensure_zotero_attachable_pdf,
        normalize_zotero_library_id=_normalize_zotero_library_id,
        finalize_zotero_action_preview=_finalize_zotero_action_preview,
    )


def _resolve_zotero_attachment_target(
    conn: sqlite3.Connection, target: ZoteroChatTargetRef
) -> dict[str, Any]:
    return _zotero_attachment_targets.resolve_zotero_attachment_target(
        conn,
        target,
        normalize_zotero_chat_tags=_normalize_zotero_chat_tags,
        extract_rh_paper_id_tag=_extract_rh_paper_id_tag,
        resolve_zotero_chat_match=_resolve_zotero_chat_match,
    )


def _trusted_pdf_roots_for_zotero() -> tuple[list[Path], str | None]:
    return _zotero_pdf_paths.trusted_pdf_roots_for_zotero(PDF_ROOTS)


def _trusted_pdf_path_for_zotero(raw: str) -> tuple[Path | None, str | None]:
    return _zotero_pdf_paths.trusted_pdf_path_for_zotero(raw, PDF_ROOTS)


_ANNOTATION_TOOL_CACHE = _zotero_pdf_annotations.ANNOTATION_TOOL_CACHE
_ZOTERO_ANNOTATION_PROFILE = _zotero_pdf_annotations.ZOTERO_ANNOTATION_PROFILE
_ZOTERO_ANNOTATION_MARKER = _zotero_pdf_annotations.ZOTERO_ANNOTATION_MARKER
_ZOTERO_ANNOTATION_SPECS = _zotero_pdf_annotations.ZOTERO_ANNOTATION_SPECS


def _apply_rh_pdf_annotations_for_papers(
    *,
    paper_ids: list[int],
    topic_id: int,
    topic_name: str,
    focus: str = "",
) -> list[dict[str, Any]]:
    return _zotero_pdf_annotations.apply_rh_pdf_annotations_for_papers(
        paper_ids=paper_ids,
        topic_id=topic_id,
        topic_name=topic_name,
        focus=focus,
        load_paper_rows=_zotero_annotation_paper_rows,
        apply_rh_pdf_annotations_for_paper=_apply_rh_pdf_annotations_for_paper,
        record_zotero_pdf_annotation_artifact=(_record_zotero_pdf_annotation_artifact),
    )


def _zotero_annotation_paper_rows(paper_ids: list[int]) -> dict[int, dict[str, Any]]:
    return _zotero_pdf_annotations.zotero_annotation_paper_rows(
        paper_ids,
        get_db_context=get_db,
    )


def _apply_rh_pdf_annotations_for_paper(
    *,
    paper: dict[str, Any],
    topic_id: int,
    topic_name: str,
    focus: str,
) -> dict[str, Any]:
    return _zotero_pdf_annotations.apply_rh_pdf_annotations_for_paper(
        paper=paper,
        topic_id=topic_id,
        topic_name=topic_name,
        focus=focus,
        trusted_pdf_path_for_zotero=_trusted_pdf_path_for_zotero,
        build_zotero_pdf_annotation_plan=_build_zotero_pdf_annotation_plan,
        validate_zotero_annotation_plan=_validate_zotero_annotation_plan,
        zotero_pdf_annotation_plan_path=_zotero_pdf_annotation_plan_path,
        backup_pdf_for_zotero_annotations=_backup_pdf_for_zotero_annotations,
        reset_rh_pdf_annotations=_reset_rh_pdf_annotations,
        apply_zotero_pdf_annotation_plan=_apply_zotero_pdf_annotation_plan,
        count_rh_pdf_annotations=_count_rh_pdf_annotations,
        logger=logger,
    )


_zotero_pdf_annotation_skip_receipt = (
    _zotero_pdf_annotations.zotero_pdf_annotation_skip_receipt
)


_build_zotero_pdf_annotation_plan = (
    _zotero_pdf_annotations.build_zotero_pdf_annotation_plan
)
_extract_zotero_pdf_anchor_candidates = (
    _zotero_pdf_annotations.extract_zotero_pdf_anchor_candidates
)
_normalize_zotero_pdf_anchor = _zotero_pdf_annotations.normalize_zotero_pdf_anchor
_validate_zotero_annotation_plan = (
    _zotero_pdf_annotations.validate_zotero_annotation_plan
)
_reset_rh_pdf_annotations = _zotero_pdf_annotations.reset_rh_pdf_annotations
_apply_zotero_pdf_annotation_plan = (
    _zotero_pdf_annotations.apply_zotero_pdf_annotation_plan
)
_load_annotation_tool_module = _zotero_pdf_annotations.load_annotation_tool_module


def _zotero_pdf_annotation_plan_path(topic_id: int, paper_id: int) -> Path:
    return _zotero_pdf_annotations.zotero_pdf_annotation_plan_path(
        db_path=DB_PATH,
        topic_id=topic_id,
        paper_id=paper_id,
    )


_backup_pdf_for_zotero_annotations = (
    _zotero_pdf_annotations.backup_pdf_for_zotero_annotations
)
_count_rh_pdf_annotations = _zotero_pdf_annotations.count_rh_pdf_annotations


def _record_zotero_pdf_annotation_artifact(
    *,
    topic_id: int,
    topic_name: str,
    receipts: list[dict[str, Any]],
) -> None:
    return _zotero_pdf_annotations.record_zotero_pdf_annotation_artifact(
        topic_id=topic_id,
        topic_name=topic_name,
        receipts=receipts,
        execute_tool=execute_tool,
        logger=logger,
    )


_http_non_zotero_routes.register_routes_after_zotero(app, _non_zotero_route_deps())


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    # Ensure our own module-level loggers (e.g. research_harness_mcp.http_api,
    # expansion worker) actually emit at INFO level. Without this uvicorn only
    # configures its own loggers and ours stay silent.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("research_harness_mcp").setLevel(logging.INFO)
    logging.getLogger("research_harness").setLevel(logging.INFO)

    # Restrict reload watcher to the Python package so large local-only trees
    # do not trigger spurious reloads during development.
    _package_dir = str(Path(__file__).resolve().parent)

    host = _http_auth.resolve_http_bind_host()
    uvicorn.run(
        "research_harness_mcp.http_api:app",
        host=host,
        port=int(os.environ.get("RESEARCH_HARNESS_HTTP_PORT", "8000")),
        reload=True,
        reload_dirs=[_package_dir],
    )
