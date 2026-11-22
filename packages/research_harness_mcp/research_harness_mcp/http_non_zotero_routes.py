"""Non-Zotero route composition for the local Research Harness HTTP API."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI

from research_harness_mcp.agents_http import register_agent_routes
from research_harness_mcp.algorithm_candidates_http import (
    register_algorithm_candidate_routes,
)
from research_harness_mcp.audit_http import register_audit_routes
from research_harness_mcp.citation_http import register_citation_routes
from research_harness_mcp.cross_topic_atlas_http import (
    register_cross_topic_atlas_routes,
)
from research_harness_mcp.dashboard_http import register_dashboard_routes
from research_harness_mcp.design_writing_actions_http import (
    register_design_writing_action_routes,
)
from research_harness_mcp.discover_http import register_discover_routes
from research_harness_mcp.domain_detail_http import register_domain_detail_routes
from research_harness_mcp.domain_list_http import register_domain_list_routes
from research_harness_mcp.domain_suggest_http import register_domain_suggest_routes
from research_harness_mcp.domain_write_http import register_domain_write_routes
from research_harness_mcp.experiment_matrix_http import (
    register_experiment_matrix_routes,
)
from research_harness_mcp.experiment_read_http import register_experiment_read_routes
from research_harness_mcp.field_brief_http import register_field_brief_routes
from research_harness_mcp.goal_pool_http import register_goal_pool_routes
from research_harness_mcp.http_models import (
    AdvanceRequest,
    BatchEnrichRequest,
    CreateDomainRequest,
    CreateExperimentRequest,
    CreateTopicRequest,
    DomainDetail,
    DomainSummary,
    ExpansionRequest,
    ForceAdvanceRequest,
    PaginatedResponse,
    PaginationMeta,
    PaperDetail,
    PaperIngestRequest,
    PatchDomainRequest,
    PatchTopicRequest,
    RecordArtifactRequest,
    RollbackRequest,
    TopicDetail,
    TopicSummary,
)
from research_harness_mcp.intake_profile_http import register_intake_profile_routes
from research_harness_mcp.jobs_http import register_job_routes
from research_harness_mcp.llm_explain_http import register_llm_explain_routes
from research_harness_mcp.longtask_http import register_longtask_routes
from research_harness_mcp.memory_http import register_memory_routes
from research_harness_mcp.method_atoms_http import register_method_atoms_routes
from research_harness_mcp.paper_deep_read_http import register_paper_deep_read_routes
from research_harness_mcp.paper_detail_http import register_paper_detail_routes
from research_harness_mcp.paper_enrich_http import register_paper_enrich_routes
from research_harness_mcp.paper_ingest_http import (
    register_paper_enrich_batch_routes,
    register_paper_ingest_routes,
)
from research_harness_mcp.paper_list_http import register_paper_list_routes
from research_harness_mcp.paper_pdf_http import register_paper_pdf_routes
from research_harness_mcp.paper_production_workbench_http import (
    register_workbench_routes,
)
from research_harness_mcp.paper_search_http import register_paper_search_routes
from research_harness_mcp.primitive_actions_http import register_primitive_action_routes
from research_harness_mcp.productization_http import register_productization_routes
from research_harness_mcp.reports_http import register_report_routes
from research_harness_mcp.retrieval_log_http import register_retrieval_log_routes
from research_harness_mcp.rollback_http import register_rollback_routes
from research_harness_mcp.rubric_http import register_rubric_routes
from research_harness_mcp.tiers_http import register_tier_routes
from research_harness_mcp.topic_advance_http import register_topic_advance_routes
from research_harness_mcp.topic_artifact_record_http import (
    register_topic_artifact_record_routes,
)
from research_harness_mcp.topic_candidates_http import register_topic_candidate_routes
from research_harness_mcp.topic_detail_http import register_topic_detail_routes
from research_harness_mcp.topic_experiment_create_http import (
    register_topic_experiment_create_routes,
)
from research_harness_mcp.topic_expansion_http import register_topic_expansion_routes
from research_harness_mcp.topic_force_advance_http import (
    register_topic_force_advance_routes,
)
from research_harness_mcp.topic_gate_http import register_topic_gate_routes
from research_harness_mcp.topic_knowledge_refresh_http import (
    register_topic_knowledge_refresh_routes,
)
from research_harness_mcp.topic_knowledge_status_http import (
    register_topic_knowledge_status_routes,
)
from research_harness_mcp.topic_list_http import register_topic_list_routes
from research_harness_mcp.topic_papers_http import register_topic_paper_routes
from research_harness_mcp.topic_read_http import register_topic_read_routes
from research_harness_mcp.topic_write_http import register_topic_write_routes
from research_harness_mcp.trends_http import register_domain_trends_routes
from research_harness_mcp.venue_http import register_venue_routes
from research_harness_mcp.workbench_chat_http import register_workbench_chat_routes


RouteDeps = Mapping[str, Any]


def _dep(deps: RouteDeps, name: str) -> Any:
    return deps[name]


def register_routes_before_zotero(app: FastAPI, deps: RouteDeps) -> None:
    """Register non-Zotero routes that must precede Zotero route registration."""
    register_productization_routes(app, db_path_provider=_dep(deps, "db_path_provider"))

    register_longtask_routes(app, home_provider=_dep(deps, "longtask_home_provider"))

    register_discover_routes(app, get_db_context=_dep(deps, "get_db_context"))

    register_topic_list_routes(
        app,
        get_db_context=_dep(deps, "get_db_context"),
        invoke_service=_dep(deps, "research_service_invoke"),
        topic_summary_model=TopicSummary,
    )

    register_cross_topic_atlas_routes(
        app,
        invoke_service=_dep(deps, "research_service_invoke"),
    )

    register_topic_knowledge_status_routes(
        app,
        invoke_service=_dep(deps, "research_service_invoke"),
    )

    register_topic_knowledge_refresh_routes(
        app,
        invoke_service=_dep(deps, "research_service_invoke"),
        parse_positive_topic_id=_dep(deps, "parse_positive_topic_id"),
        knowledge_api_error=_dep(deps, "knowledge_api_error"),
        cache_control=_dep(deps, "knowledge_api_cache_control"),
    )

    register_topic_detail_routes(
        app,
        get_db_context=_dep(deps, "get_db_context"),
        invoke_service=_dep(deps, "research_service_invoke"),
        topic_detail_model=TopicDetail,
    )

    register_topic_paper_routes(
        app,
        get_db_context=_dep(deps, "get_db_context"),
        row_to_dict=_dep(deps, "row_to_dict"),
        parse_json_field=_dep(deps, "parse_json_field"),
        paginated_response_model=PaginatedResponse,
        pagination_meta_model=PaginationMeta,
    )

    register_domain_list_routes(
        app,
        get_db_context=_dep(deps, "get_db_context"),
        domain_summary_model=DomainSummary,
    )

    register_domain_trends_routes(
        app,
        get_db_context=_dep(deps, "get_db_context"),
        row_to_dict=_dep(deps, "row_to_dict"),
        parse_json_field=_dep(deps, "parse_json_field"),
    )

    register_domain_detail_routes(
        app,
        get_db_context=_dep(deps, "get_db_context"),
        domain_detail_model=DomainDetail,
        topic_summary_model=TopicSummary,
    )

    register_domain_write_routes(
        app,
        get_db_context=_dep(deps, "get_db_context"),
        domain_summary_model=DomainSummary,
        create_domain_request_model=CreateDomainRequest,
        patch_domain_request_model=PatchDomainRequest,
        now_factory=_dep(deps, "now_factory"),
    )

    register_domain_suggest_routes(app)

    register_topic_candidate_routes(app, get_db_context=_dep(deps, "get_db_context"))

    register_job_routes(
        app,
        get_db_context=_dep(deps, "get_db_context"),
        row_to_dict=_dep(deps, "row_to_dict"),
        parse_json_field=_dep(deps, "parse_json_field"),
    )

    register_paper_list_routes(
        app,
        get_db_context=_dep(deps, "get_db_context"),
        invoke_service=_dep(deps, "research_service_invoke"),
        row_to_dict=_dep(deps, "row_to_dict"),
        parse_json_field=_dep(deps, "parse_json_field"),
        paginated_response_model=PaginatedResponse,
        pagination_meta_model=PaginationMeta,
    )

    register_paper_detail_routes(
        app,
        get_db_context=_dep(deps, "get_db_context"),
        row_to_dict=_dep(deps, "row_to_dict"),
        rows_to_list=_dep(deps, "rows_to_list"),
        parse_json_field=_dep(deps, "parse_json_field"),
        paper_detail_model=PaperDetail,
    )

    register_paper_deep_read_routes(
        app,
        get_db_context=_dep(deps, "get_db_context"),
        api_factory=_dep(deps, "api_factory"),
        deep_read_paper_impl=_dep(deps, "deep_read_paper_impl"),
    )

    register_paper_pdf_routes(
        app,
        get_db_context=_dep(deps, "get_db_context"),
        pdf_roots_provider=_dep(deps, "pdf_roots_provider"),
    )

    register_topic_read_routes(
        app,
        get_db_context=_dep(deps, "get_db_context"),
        row_to_dict=_dep(deps, "row_to_dict"),
        parse_json_field=_dep(deps, "parse_json_field"),
    )

    register_workbench_routes(
        app,
        get_db_context=_dep(deps, "get_db_context"),
        row_to_dict=_dep(deps, "row_to_dict"),
        parse_json_field=_dep(deps, "parse_json_field"),
        create_topic_entry=_dep(deps, "workbench_create_topic"),
    )

    register_workbench_chat_routes(
        app,
        get_db_context=_dep(deps, "get_db_context"),
        row_to_dict=_dep(deps, "row_to_dict"),
        parse_json_field=_dep(deps, "parse_json_field"),
        now_iso=_dep(deps, "now_iso"),
        pending_decisions_provider=_dep(deps, "workbench_pending_decisions"),
        decision_recorder=_dep(deps, "workbench_record_decision"),
        chat_reply_provider=_dep(deps, "workbench_chat_reply"),
    )

    register_topic_artifact_record_routes(
        app,
        record_artifact_request_model=RecordArtifactRequest,
        run_tool=_dep(deps, "run_tool"),
    )

    register_topic_force_advance_routes(
        app,
        force_advance_request_model=ForceAdvanceRequest,
        get_db_context=_dep(deps, "get_db_context"),
    )

    register_audit_routes(
        app,
        db_path_provider=_dep(deps, "db_path_provider"),
        get_db_context=_dep(deps, "get_db_context"),
        row_to_dict=_dep(deps, "row_to_dict"),
        logger=_dep(deps, "logger"),
    )

    register_experiment_read_routes(
        app,
        get_db_context=_dep(deps, "get_db_context"),
        row_to_dict=_dep(deps, "row_to_dict"),
        parse_json_field=_dep(deps, "parse_json_field"),
    )

    register_topic_experiment_create_routes(
        app,
        db_path_provider=_dep(deps, "db_path_provider"),
        create_experiment_request_model=CreateExperimentRequest,
    )

    register_dashboard_routes(
        app,
        db_path_provider=_dep(deps, "db_path_provider"),
        get_db_context=_dep(deps, "get_db_context"),
        rows_to_list=_dep(deps, "rows_to_list"),
        service_factory=_dep(deps, "research_service_factory"),
    )

    register_topic_write_routes(
        app,
        create_topic_request_model=CreateTopicRequest,
        patch_topic_request_model=PatchTopicRequest,
        get_db_context=_dep(deps, "get_db_context"),
        materialize_topic_workspace=_dep(deps, "materialize_topic_workspace"),
        run_tool=_dep(deps, "run_tool"),
        row_to_dict=_dep(deps, "row_to_dict"),
        now_iso=_dep(deps, "now_iso"),
    )

    register_intake_profile_routes(
        app,
        get_db_context=_dep(deps, "get_db_context"),
        row_to_dict=_dep(deps, "row_to_dict"),
        run_tool=_dep(deps, "run_tool"),
    )

    register_field_brief_routes(
        app,
        get_db_context=_dep(deps, "get_db_context"),
        topic_exists=_dep(deps, "topic_exists"),
        db_path_provider=_dep(deps, "db_path_provider"),
    )

    register_goal_pool_routes(
        app,
        get_db_context=_dep(deps, "get_db_context"),
        topic_exists=_dep(deps, "topic_exists"),
        row_to_dict=_dep(deps, "row_to_dict"),
        db_path_provider=_dep(deps, "db_path_provider"),
    )

    register_method_atoms_routes(
        app,
        get_db_context=_dep(deps, "get_db_context"),
        topic_exists=_dep(deps, "topic_exists"),
        row_to_dict=_dep(deps, "row_to_dict"),
        db_path_provider=_dep(deps, "db_path_provider"),
    )

    register_venue_routes(
        app,
        get_db_context=_dep(deps, "get_db_context"),
        topic_exists=_dep(deps, "topic_exists"),
        row_to_dict=_dep(deps, "row_to_dict"),
        db_path_provider=_dep(deps, "db_path_provider"),
    )

    register_experiment_matrix_routes(
        app,
        get_db_context=_dep(deps, "get_db_context"),
        topic_exists=_dep(deps, "topic_exists"),
        row_to_dict=_dep(deps, "row_to_dict"),
        db_path_provider=_dep(deps, "db_path_provider"),
    )

    register_retrieval_log_routes(
        app,
        get_db_context=_dep(deps, "get_db_context"),
        topic_exists=_dep(deps, "topic_exists"),
        row_to_dict=_dep(deps, "row_to_dict"),
        parse_json_field=_dep(deps, "parse_json_field"),
    )

    register_topic_advance_routes(
        app,
        advance_request_model=AdvanceRequest,
        run_tool=_dep(deps, "run_tool"),
    )

    register_topic_gate_routes(
        app,
        db_path_provider=_dep(deps, "db_path_provider"),
        service_factory=_dep(deps, "research_service_factory"),
    )

    register_topic_expansion_routes(
        app,
        expansion_request_model=ExpansionRequest,
        get_db_context=_dep(deps, "get_db_context"),
        topic_exists=_dep(deps, "topic_exists"),
        get_latest_expansion_job=_dep(deps, "get_latest_expansion_job"),
        topic_paper_stats=_dep(deps, "topic_paper_stats"),
        update_expansion_job=_dep(deps, "update_expansion_job"),
        run_expansion_job=_dep(deps, "run_expansion_job"),
        row_to_dict=_dep(deps, "row_to_dict"),
        now_iso=_dep(deps, "now_iso"),
    )

    register_paper_search_routes(
        app,
        api_factory=_dep(deps, "api_factory"),
        search_papers_impl=_dep(deps, "search_papers_impl"),
        get_db_context=_dep(deps, "get_db_context"),
        logger=_dep(deps, "logger"),
    )


def register_routes_after_zotero(app: FastAPI, deps: RouteDeps) -> None:
    """Register non-Zotero routes that historically followed Zotero routes."""
    register_paper_ingest_routes(
        app,
        paper_ingest_request_model=PaperIngestRequest,
        api_factory=_dep(deps, "api_factory"),
        ingest_paper_impl=_dep(deps, "ingest_paper_impl"),
        get_db_context=_dep(deps, "get_db_context"),
    )

    register_paper_enrich_routes(app, get_db_context=_dep(deps, "get_db_context"))

    register_paper_enrich_batch_routes(
        app,
        batch_enrich_request_model=BatchEnrichRequest,
        get_db_context=_dep(deps, "get_db_context"),
    )

    register_primitive_action_routes(app, run_tool=_dep(deps, "run_tool"))

    register_algorithm_candidate_routes(
        app,
        run_tool=_dep(deps, "run_tool"),
        db_path_provider=_dep(deps, "db_path_provider"),
        get_db_context=_dep(deps, "get_db_context"),
    )

    register_design_writing_action_routes(app, run_tool=_dep(deps, "run_tool"))

    register_memory_routes(
        app,
        db_path_provider=_dep(deps, "db_path_provider"),
        logger=_dep(deps, "logger"),
    )

    register_report_routes(
        app,
        db_path_provider=_dep(deps, "db_path_provider"),
        logger=_dep(deps, "logger"),
    )

    register_citation_routes(app, get_db_context=_dep(deps, "get_db_context"))

    register_agent_routes(
        app,
        get_db_context=_dep(deps, "get_db_context"),
        row_to_dict=_dep(deps, "row_to_dict"),
        rows_to_list=_dep(deps, "rows_to_list"),
        parse_json_field=_dep(deps, "parse_json_field"),
        demo_list_entries=_dep(deps, "demo_list_entries"),
        demo_lookup=_dep(deps, "demo_lookup"),
        logger=_dep(deps, "logger"),
    )

    register_tier_routes(
        app,
        get_db_context=_dep(deps, "get_db_context"),
        row_to_dict=_dep(deps, "row_to_dict"),
        rows_to_list=_dep(deps, "rows_to_list"),
    )

    register_rollback_routes(
        app,
        db_path_provider=_dep(deps, "db_path_provider"),
        get_db_context=_dep(deps, "get_db_context"),
        row_to_dict=_dep(deps, "row_to_dict"),
        rollback_request_model=RollbackRequest,
    )

    register_rubric_routes(
        app,
        get_db_context=_dep(deps, "get_db_context"),
        row_to_dict=_dep(deps, "row_to_dict"),
    )

    register_llm_explain_routes(app, logger=_dep(deps, "logger"))
