"""Public MCP tool surface contracts.

This module is the explicit agent-facing MCP contract. Internal primitives can
remain registered in Research Harness, but only names listed here are advertised
through ``tools/list``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mcp.types import Tool


@dataclass(frozen=True)
class PublicToolContract:
    name: str
    description: str
    output_schema: dict[str, Any]
    error_examples: tuple[dict[str, str], ...]


PUBLIC_MCP_TOOL_NAMES: tuple[str, ...] = (
    "topic_list",
    "topic_show",
    "topic_init",  # NEW: Create topic without CLI
    "topic_state",  # Unified single-call topic introspection (rh.topic_state.v1)
    "paper_search",
    "paper_ingest",
    "paper_list",
    "paper_summarize",
    "claim_extract",
    "evidence_link",
    "gap_detect",
    "baseline_identify",
    "section_draft",
    "figure_generate",
    "consistency_check",
    "orchestrator_status",
    "orchestrator_resume",
    "orchestrator_advance",
    "orchestrator_gate_check",
    "orchestrator_record_artifact",
    "paper_commit_version",
    "paper_task_intake",
    "adversarial_review",
    "advisory_check",
    "provenance_summary",
    "provenance_export",
    "zotero_sync",
    "paperindex_search",
    # Human-in-the-loop decision tools (v2, works with Claude Code and Codex)
    "paper_production_pending_decisions",
    "paper_production_decide",
    # Complete workflow tools for pure CLI usage
    "paper_production_start",  # NEW: Start workflow without CLI
    "paper_production_status",  # NEW: Enhanced status with mode info
    "paper_production_resume",  # NEW: Resume with auto-approve option
    "paper_production_mode",  # NEW: Get current interaction mode
    "paper_production_set_mode",  # NEW: Change mode mid-workflow
    "paper_production_export",  # NEW: Export generated paper
    "skill_list",
    "skill_get",
    "productization_boundary",
    "topic_knowledge_status",
    "topic_knowledge_refresh",
    "cross_topic_atlas",
    # Exemplar-Anchored Generation (EAG): reference-grounded, form-not-content
    "exemplar_curate",
    "exemplar_retrieve",
    "exemplar_plan",
    "exemplar_generate",
    "exemplar_critique",
    "figure_suite_plan",  # two-phase whole-paper figure contract (design/reconcile)
    "figure_suite_render",  # deterministic execution of EAG figure suites
    "figure_package",  # one evidence-bound Figure Package (top-one, fake provider)
    # Final-draft polish (终稿打磨)
    "manuscript_review",
    "manuscript_polish",
    "resource_ready_get",
    "deposit_zenodo",
)


_COMMON_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["success", "error", "warning"]},
        "summary": {"type": "string"},
        "output": {"type": "object"},
        "next_actions": {"type": "array", "items": {"type": "string"}},
        "artifacts": {"type": "array", "items": {"type": "object"}},
        "recovery_hint": {"type": "string"},
    },
    "required": ["status", "summary", "output", "next_actions"],
}


_TOOL_GUIDANCE: dict[str, tuple[str, str]] = {
    "resource_ready_get": (
        "fetch the single active SPC resource-ready binding for a (topic_id, workflow_ref, host_id) "
        "triple after paperfetch has prepared workflow resources",
        "import a new workflow_ready report or trigger preparation; this only reads an existing binding, "
        "use the rh resource import-spc-ready CLI to record one",
    ),
    "deposit_zenodo": (
        "pack a topic's code and data packages, upload them to Zenodo, and return separate code/data DOIs "
        "(token preferred; email+password may mint a short-lived PAT via headless login)",
        "edit Zenodo metadata after publish or manage non-Zenodo repositories; pass deposit_root or "
        "code_path/data_path when auto-discovery cannot find the package",
    ),
    "topic_list": (
        "discover existing Research Harness topics before choosing a topic_id or resuming a workflow",
        "perform paper search or modify topic state; use paper_search or orchestrator tools after selecting a topic",
    ),
    "topic_show": (
        "inspect one known topic by name before attaching papers, claims, or artifacts to it",
        "list all available topics; use topic_list when the topic name is unknown",
    ),
    "topic_state": (
        "get the full resume picture for one topic in a single call: resolved DB/state trees, "
        "orchestrator stage and gate, checkpoint, pending decision, blockers, and a computed next_action",
        "list topics or mutate state; use topic_list to discover ids, then follow next_action commands",
    ),
    "topic_init": (
        "create a new research topic directly from Claude Code or Codex without using the CLI",
        "list or inspect existing topics; use topic_list or topic_show for that",
    ),
    "paper_search": (
        "search external providers or the local paper pool for candidate papers tied to a research question",
        "ingest a known paper identifier directly; use paper_ingest when you already have the DOI, arXiv ID, URL, or PDF",
    ),
    "paper_ingest": (
        "add a known DOI, arXiv ID, URL, or local PDF to the managed paper pool with topic context",
        "run broad discovery from a natural-language query; use paper_search first for that workflow",
    ),
    "paper_list": (
        "review papers already in the local pool, optionally scoped to one topic",
        "discover unseen literature from remote sources; use paper_search for retrieval",
    ),
    "paper_summarize": (
        "summarize one known paper with a clear focus after it has been ingested",
        "extract cross-paper claims or topic-wide evidence; use claim_extract for that",
    ),
    "claim_extract": (
        "extract structured research claims from selected ingested papers under a topic",
        "link an already identified claim to evidence; use evidence_link for explicit links",
    ),
    "evidence_link": (
        "record a support relationship between a known claim and a known source artifact or paper",
        "infer new claims from papers; use claim_extract before linking evidence",
    ),
    "gap_detect": (
        "analyze a topic paper pool and extracted claims to identify research gaps",
        "bootstrap an empty topic; run paper_search, paper_ingest, and claim_extract first",
    ),
    "baseline_identify": (
        "identify baseline methods or systems that a topic should compare against",
        "draft prose or run experiments; use section_draft or experiment tools after baselines are known",
    ),
    "section_draft": (
        "draft an evidence-constrained paper section using topic artifacts and linked evidence",
        "perform final bundle assembly or PDF validation; use publication and review tools for that",
    ),
    "figure_generate": (
        "generate paper-ready figure assets from figure_plan items, including an explicit illustration fake provider route for local validation",
        "make quality or publication-readiness claims from generated images without review, provenance, and evidence checks",
    ),
    "consistency_check": (
        "check drafted sections for contradictions, unsupported claims, and citation consistency",
        "create new draft content; use section_draft before running consistency checks",
    ),
    "exemplar_curate": (
        "build a quality-gated exemplar library slice (skeleton|intro_arc|related_work_arc|method_arc|experiment_arc|discussion_arc|paragraph_moves|abstract|style|figure_suite) from a topic's papers by extracting each paper's abstracted FORM and keeping only high-quality target-venue exemplars",
        "draft prose or copy exemplar content; exemplar_curate transfers structure/style, never wording",
    ),
    "exemplar_retrieve": (
        "rank curated exemplars for a target artifact by structure over topic (same form beats same topic) and return the top few",
        "curate new exemplars; run exemplar_curate first",
    ),
    "exemplar_plan": (
        "produce a FORM-only generation plan (skeleton or introduction move-map) for THIS paper by structural analogy to retrieved exemplars, never reusing their wording or claims; pass register_lexicon to bind it to the field's canonical terminology",
        "generate final prose; use exemplar_generate or section_draft with this plan as the outline",
    ),
    "exemplar_generate": (
        "run the plan-draft-critique-revise loop to draft a section following the exemplar-derived form, using section_draft (evidence-grounded) when the topic is drafting-ready; with register_lexicon the draft keeps the field's canonical terms",
        "bypass the overlap gate or reuse exemplar text; the critique step enforces form-not-content",
    ),
    "exemplar_critique": (
        "check a draft for verbatim n-gram overlap against source exemplars (the form-not-content / anti-plagiarism gate); with register_lexicon, canonical field terms are exempt and non-canonical synonyms are flagged",
        "assess factual correctness or citations; use consistency_check for that",
    ),
    "figure_suite_plan": (
        "design (source=matrix) or reconcile (source=records) the whole-paper figure contract: ground on a planned inventory (matrix or goal_pool/experiment_result), plan the figure suite by analogy to exemplars, and return the spec plus bidirectional matrix coverage, per-panel logging requirements, and a generative-pipeline export",
        "render figures or invent data; use figure_suite_render to draw and figure_generate for generative figures — this only plans/reconciles form",
    ),
    "figure_suite_render": (
        "deterministically render an exemplar-planned figure suite (exemplar_plan unit_type=figure_suite) from recorded experiment records as composed multi-panel figures with discipline style profiles",
        "generate architecture/method figures or invent data for missing panels; use figure_generate for generative figures — panels without matching records are skipped and reported",
    ),
    "figure_package": (
        "build one evidence-bound Figure Package from a FigureTask: intake, sufficiency, top-one opportunity, figure–caption form, design/caption contracts, then deterministic or fake-provider render and caption QA",
        "render a whole-paper suite or invent numeric charts; use figure_suite_plan/render for suites and recorded records for quantitative panels — the public path does not accept a real image provider",
    ),
    "manuscript_review": (
        "produce a multi-angle reviewer critique (methods/statistics, domain, editorial/format) of a full manuscript as prioritized, actionable findings with severity",
        "rewrite the manuscript; manuscript_review only diagnoses. Apply fixes with section_revise / exemplar tools",
    ),
    "manuscript_polish": (
        "run the orchestrated final-draft polish: reviewer critique + deterministic section checks + consistency_check, returning prioritized findings and a submission-readiness verdict (ready|needs_revision|blocked)",
        "declare a manuscript submission-ready while it returns blocked/needs_revision, or skip it before final bundle assembly",
    ),
    "orchestrator_status": (
        "inspect the current stage, gates, and artifacts for an orchestrated research run",
        "advance stages or write artifacts; use orchestrator_advance or orchestrator_record_artifact",
    ),
    "orchestrator_resume": (
        "resume or create the orchestrated workflow for an existing topic without restarting from scratch",
        "run one isolated primitive when no workflow state is needed; call the specific paper or analysis tool instead",
    ),
    "orchestrator_advance": (
        "move an orchestrated run to its next valid stage after required artifacts and gates are ready",
        "force progress around failed gates; inspect orchestrator_gate_check and record missing artifacts first",
    ),
    "orchestrator_gate_check": (
        "evaluate whether the current stage has enough evidence and artifacts to proceed",
        "record the artifact that satisfies a gate; use orchestrator_record_artifact for durable writes",
    ),
    "orchestrator_record_artifact": (
        "persist a meaningful research output, decision, report, or bundle into the topic artifact lineage",
        "store temporary scratch notes or private files; keep only durable, reusable outputs in artifacts",
    ),
    "paper_commit_version": (
        "commit one manuscript version atomically: hash TeX/PDF, record draft_pack + final_bundle (+ quality report) with lineage, rejecting superseded dependencies",
        "record standalone non-manuscript artifacts or scratch notes; use orchestrator_record_artifact for single artifacts",
    ),
    "paper_task_intake": (
        "turn a natural-language paper-production request into a durable RH topic, run, checkpoint, initial PAPER_PLAN artifact, and RH_STATE payload",
        "treat chat-only planning as workflow progress; use this entrypoint when a paper task must become resumable state",
    ),
    "adversarial_review": (
        "run an independent challenge/review pass on a proposal, draft, or research decision",
        "perform simple formatting edits or deterministic validation; use consistency_check for local checks",
    ),
    "advisory_check": (
        "run lightweight workflow advisories that identify missing evidence, stale artifacts, or risky next steps",
        "perform a full gate transition or stage advance; use orchestrator_gate_check or orchestrator_advance for that",
    ),
    "provenance_summary": (
        "inspect aggregate tool usage, cost, and success statistics for a topic or database",
        "retrieve full raw provenance records; use provenance_export when detailed records are needed",
    ),
    "provenance_export": (
        "export detailed provenance records for audit, debugging, or publication-package evidence",
        "get a quick cost/status overview; use provenance_summary for compact inspection",
    ),
    "zotero_sync": (
        "synchronize a Research Harness topic with Zotero collections, notes, and annotations",
        "search remote literature providers; use paper_search for discovery before syncing",
    ),
    "paperindex_search": (
        "search structured local PDF annotations and paperindex cards for already acquired papers",
        "query remote scholarly databases; use paper_search when the paper is not in the local pool",
    ),
    "skill_list": (
        "discover installed Research Harness workflow skills available to an agent host",
        "execute a research primitive or inspect a paper; call the relevant MCP tool instead",
    ),
    "skill_get": (
        "read the instructions for one named workflow skill before running that user-facing workflow",
        "look up arbitrary repository files; use normal file access when not reading a skill package",
    ),
    "productization_boundary": (
        "inspect the LG10 public-productization boundary after explicitly opting in to the preview",
        "treat LG8/LG9 completion as permission to implement new public surfaces; every surface still needs a gate-approved slice",
    ),
    "topic_knowledge_status": (
        "inspect the current derived Topic Knowledge readiness, coverage, warnings, and next actions for a topic",
        "create or refresh the snapshot; use topic_knowledge_refresh when the status is missing or stale",
    ),
    "topic_knowledge_refresh": (
        "refresh the rebuildable Topic Knowledge snapshot for one topic, or all topics when explicitly requested",
        "ingest papers or change canonical evidence; use paper_ingest, claim_extract, or related tools for canonical source changes",
    ),
    "cross_topic_atlas": (
        "find evidence-bound links between two or more topics from existing Topic Knowledge snapshots",
        "bootstrap missing snapshots; refresh the relevant topics first with topic_knowledge_refresh",
    ),
    "paper_production_pending_decisions": (
        "check if a paper production workflow is waiting for a human decision with AI recommendations",
        "make the decision; use paper_production_decide after reviewing pending decision options",
    ),
    "paper_production_decide": (
        "make a decision for a paused paper production workflow after reviewing options",
        "check status or list decisions; use paper_production_pending_decisions first to see options",
    ),
    "paper_production_start": (
        "start the complete 6-stage paper production workflow directly from Claude Code or Codex",
        "resume an already-started workflow; use paper_production_resume for that",
    ),
    "paper_production_status": (
        "get detailed workflow status including stage, gates, decisions, mode, cost, and next actions",
        "start a new workflow; use paper_production_start when no workflow exists yet",
    ),
    "paper_production_resume": (
        "resume a paused workflow after making a decision or fixing blockers",
        "check what's blocking first; use paper_production_status to diagnose before resuming",
    ),
    "paper_production_mode": (
        "get the current interaction mode (autonomous/checkpoint/interactive) for a workflow",
        "change the mode; use paper_production_set_mode to switch modes",
    ),
    "paper_production_set_mode": (
        "change interaction mode mid-workflow between autonomous, checkpoint, and interactive",
        "start with a specific mode; pass interaction_mode to paper_production_start instead",
    ),
    "paper_production_export": (
        "export the generated paper LaTeX, PDF, figures, and intermediate artifacts",
        "check if workflow is complete first; use paper_production_status to verify",
    ),
}


def _error_examples(name: str) -> tuple[dict[str, str], ...]:
    return (
        {
            "error": "MISSING_REQUIRED_ARGUMENT",
            "message": f"{name} could not run because a required input was omitted.",
            "suggestion": "Inspect the inputSchema for this tool and retry with every required field populated.",
        },
        {
            "error": "INVALID_TOPIC_CONTEXT",
            "message": f"{name} received a topic reference that does not exist or is not usable for this operation.",
            "suggestion": "Call topic_list or topic_show first, then retry with the canonical topic name or topic_id.",
        },
    )


def _description(name: str, when_to_use: str, when_not_to_use: str) -> str:
    return (
        f"When to use: {when_to_use}. "
        f"When not to use: {when_not_to_use}. "
        "This is part of the contracted public MCP surface; lower-level helpers "
        "may exist internally but are not the preferred agent entrypoint."
    )


def _build_contract(name: str) -> PublicToolContract:
    when_to_use, when_not_to_use = _TOOL_GUIDANCE[name]
    return PublicToolContract(
        name=name,
        description=_description(name, when_to_use, when_not_to_use),
        output_schema=dict(_COMMON_OUTPUT_SCHEMA),
        error_examples=_error_examples(name),
    )


PUBLIC_MCP_TOOL_CONTRACTS: dict[str, PublicToolContract] = {
    name: _build_contract(name) for name in PUBLIC_MCP_TOOL_NAMES
}


def public_tool_definitions(all_tools: list[Tool]) -> list[Tool]:
    """Return contracted public tool definitions in stable display order."""

    tools_by_name = {tool.name: tool for tool in all_tools}
    missing = [name for name in PUBLIC_MCP_TOOL_NAMES if name not in tools_by_name]
    if missing:
        missing_text = ", ".join(missing)
        raise RuntimeError(
            f"public MCP tool contract references missing tools: {missing_text}"
        )

    public_tools: list[Tool] = []
    for name in PUBLIC_MCP_TOOL_NAMES:
        source_tool = tools_by_name[name]
        contract = PUBLIC_MCP_TOOL_CONTRACTS[name]
        public_tools.append(
            Tool(
                name=source_tool.name,
                description=contract.description,
                inputSchema=source_tool.inputSchema,
            )
        )
    return public_tools
