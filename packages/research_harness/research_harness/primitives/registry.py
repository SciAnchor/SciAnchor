"""Primitive registry — maps primitive names to specs and implementations."""

from __future__ import annotations

from typing import Any, Callable

from .types import PrimitiveCategory, PrimitiveSpec

PrimitiveImplementation = Callable[..., Any]


PRIMITIVE_REGISTRY: dict[str, PrimitiveSpec] = {}
_IMPLEMENTATIONS: dict[str, PrimitiveImplementation] = {}


def register_primitive(
    spec: PrimitiveSpec,
) -> Callable[[PrimitiveImplementation], PrimitiveImplementation]:
    """Register a primitive spec and the decorated implementation."""

    PRIMITIVE_REGISTRY[spec.name] = spec

    def decorator(fn: PrimitiveImplementation) -> PrimitiveImplementation:
        _IMPLEMENTATIONS[spec.name] = fn
        return fn

    return decorator


def get_primitive_spec(name: str) -> PrimitiveSpec | None:
    return PRIMITIVE_REGISTRY.get(name)


def get_primitive_impl(name: str) -> PrimitiveImplementation | None:
    return _IMPLEMENTATIONS.get(name)


def list_primitives() -> list[PrimitiveSpec]:
    return list(PRIMITIVE_REGISTRY.values())


def list_by_category(category: PrimitiveCategory) -> list[PrimitiveSpec]:
    return [spec for spec in PRIMITIVE_REGISTRY.values() if spec.category == category]


PAPER_SEARCH_SPEC = PrimitiveSpec(
    name="paper_search",
    category=PrimitiveCategory.RETRIEVAL,
    description="Search for papers by query across configured providers",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "topic_id": {"type": "integer"},
            "max_results": {
                "type": "integer",
                "default": 50,
                "description": "Max results. Use ≥50 for Build stage coverage.",
            },
            "year_from": {"type": "integer"},
            "year_to": {"type": "integer"},
            "venue_filter": {"type": "string"},
            "tier_filter": {
                "type": "string",
                "description": "Minimum venue tier filter: ccf_a_star, ccf_a, ccf_b, ccf_c, cas_q1, cas_q2",
            },
            "auto_ingest": {
                "type": "boolean",
                "default": False,
                "description": "When true, auto-ingest top results into the local paper pool",
            },
            "local_only": {
                "type": "boolean",
                "default": False,
                "description": "When true, skip external provider fan-out and use only the local BM25 paper pool",
            },
            "local_embed_rerank": {
                "type": "boolean",
                "default": False,
                "description": "Opt-in dense rerank of the local paper pool (W1). Default off keeps BM25 order contracts stable.",
            },
            "per_provider_limit": {
                "type": "integer",
                "default": 50,
                "description": "Maximum records requested from each enabled external provider",
            },
            "provider_allowlist": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional provider names to allow for this search call",
            },
            "provider_denylist": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional provider names to exclude for this search call",
            },
        },
        "required": ["query"],
    },
    output_type="PaperSearchOutput",
    requires_llm=False,
    idempotent=True,
)

PAPER_INGEST_SPEC = PrimitiveSpec(
    name="paper_ingest",
    category=PrimitiveCategory.RETRIEVAL,
    description="Ingest a paper into the pool by arxiv_id, doi, or pdf_path",
    input_schema={
        "type": "object",
        "properties": {
            "source": {"type": "string"},
            "topic_id": {"type": "integer"},
            "relevance": {"type": "string", "enum": ["high", "medium", "low"]},
            "url": {"type": "string"},
        },
        "required": ["source"],
    },
    output_type="PaperIngestOutput",
    requires_llm=False,
    idempotent=True,
)

PAPER_ACQUIRE_SPEC = PrimitiveSpec(
    name="paper_acquire",
    category=PrimitiveCategory.RETRIEVAL,
    description="Download PDFs, enrich metadata, and build paperindex annotations for screened topic papers",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {
                "type": "integer",
                "description": "Topic ID to acquire papers for",
            },
            "limit": {
                "type": "integer",
                "description": "Optional maximum number of topic papers to acquire.",
            },
            "include_candidates": {
                "type": "boolean",
                "description": "Explicitly include unscreened provider candidates in acquisition.",
                "default": False,
            },
        },
        "required": ["topic_id"],
    },
    output_type="PaperAcquireOutput",
    requires_llm=False,
    idempotent=True,
)

PAPER_SUMMARIZE_SPEC = PrimitiveSpec(
    name="paper_summarize",
    category=PrimitiveCategory.COMPREHENSION,
    description="Generate a focused summary of a paper",
    input_schema={
        "type": "object",
        "properties": {
            "paper_id": {"type": "integer"},
            "focus": {"type": "string"},
        },
        "required": ["paper_id"],
    },
    output_type="SummaryOutput",
    requires_llm=True,
)

CLAIM_EXTRACT_SPEC = PrimitiveSpec(
    name="claim_extract",
    category=PrimitiveCategory.EXTRACTION,
    description="Extract research claims from papers within a topic",
    input_schema={
        "type": "object",
        "properties": {
            "paper_ids": {"type": "array", "items": {"type": "integer"}},
            "topic_id": {"type": "integer"},
            "focus": {"type": "string"},
        },
        "required": ["paper_ids", "topic_id"],
    },
    output_type="ClaimExtractOutput",
    requires_llm=True,
)

EVIDENCE_LINK_SPEC = PrimitiveSpec(
    name="evidence_link",
    category=PrimitiveCategory.EXTRACTION,
    description="Link a claim to supporting evidence, source span, and citation candidate",
    input_schema={
        "type": "object",
        "properties": {
            "claim_id": {"type": "string"},
            "source_type": {"type": "string"},
            "source_id": {"type": "string"},
            "strength": {"type": "string"},
            "notes": {"type": "string"},
            "support_status": {
                "type": "string",
                "enum": [
                    "supports",
                    "partial",
                    "contradicts",
                    "unsupported",
                    "unknown",
                ],
                "default": "unknown",
            },
            "evidence_span": {
                "type": "object",
                "properties": {
                    "paper_id": {"type": "integer"},
                    "section": {"type": "string"},
                    "snippet": {"type": "string"},
                    "page": {"type": "integer"},
                    "start_char": {"type": "integer"},
                    "end_char": {"type": "integer"},
                },
                "additionalProperties": True,
            },
            "citation_candidate": {
                "type": "object",
                "properties": {
                    "paper_id": {"type": "integer"},
                    "identifier": {"type": "string"},
                    "title": {"type": "string"},
                    "doi": {"type": "string"},
                    "arxiv_id": {"type": "string"},
                    "url": {"type": "string"},
                    "source_type": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "additionalProperties": True,
            },
        },
        "required": ["claim_id", "source_type", "source_id"],
    },
    output_type="EvidenceLinkOutput",
    requires_llm=False,
    idempotent=True,
)

GAP_DETECT_SPEC = PrimitiveSpec(
    name="gap_detect",
    category=PrimitiveCategory.ANALYSIS,
    description="Detect research gaps in a topic's literature",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "focus": {"type": "string"},
            "analysis_substrate": {"type": "object"},
        },
        "required": ["topic_id"],
    },
    output_type="GapDetectOutput",
    requires_llm=True,
)

ANALYSIS_SUBSTRATE_BUILD_SPEC = PrimitiveSpec(
    name="analysis_substrate_build",
    category=PrimitiveCategory.ANALYSIS,
    description="Build a survey-authoritative, evidence-anchored analysis substrate",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer", "minimum": 1},
            "query": {"type": "string"},
            "focus": {"type": "string"},
            "anchor_paper_id": {"type": ["integer", "null"], "minimum": 1},
            "max_clusters": {"type": "integer", "minimum": 1, "maximum": 12},
            "max_relations": {"type": "integer", "minimum": 1, "maximum": 48},
        },
        "required": ["topic_id"],
    },
    output_type="AnalysisSubstrateOutput",
    requires_llm=False,
    idempotent=True,
)

GAP_GROUND_VERIFY_SPEC = PrimitiveSpec(
    name="gap_ground_verify",
    category=PrimitiveCategory.VERIFICATION,
    description=(
        "Grounded verification of a candidate gap against retrieved REAL prior "
        "art: v1.1 decomposes the gap into ~6 contribution-level queries "
        "(pre-empting work hides under different terminology; the whole-sentence "
        "query is what missed FB-Bench), runs multi-query retrieval where each "
        "decorrelated query is an independent capture attempt, does "
        "contribution-level comparison, and returns a verdict "
        "(open|occupied|partially_occupied|inconclusive) with evidence and an "
        "explicit retrieval-coverage caveat. The verdict is then gated by "
        "governance_gate: an 'open' (negative-existence) claim backed by too few "
        "independent captures is confidence-discounted or downgraded per the "
        "r(rho) rule. Replaces the pool-only subjective judgment of "
        "gap_detect/gap_cross_verify."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "gap": {
                "type": "string",
                "description": "The candidate gap claim to verify (negative-existence statement).",
            },
            "max_candidates": {"type": "integer", "default": 25},
            "focus": {"type": "string"},
            "governance_alpha": {
                "type": "number",
                "default": 0.1,
                "description": "Error budget for the governance_gate acceptance step.",
            },
            "published_before": {
                "type": "string",
                "description": (
                    "Optional YYYY-MM temporal cutoff: retrieved candidates "
                    "provably published after it are excluded before "
                    "comparison (calibration replays / temporal splits)."
                ),
            },
            "judge_mode": {
                "type": "string",
                "enum": ["single", "panel"],
                "default": "single",
                "description": (
                    "Opt-in NOV02 judge arm. 'single' (default) keeps the "
                    "current one-judge behavior unchanged; 'panel' judges the "
                    "same retrieved candidates from four perspectives "
                    "(coverage / mechanism_equivalence / narrowness ask whether "
                    "the residual is still empty; residual_depth asks whether "
                    "occupying it requires building anything) with an "
                    "explicit residual-narrowness assessment, aggregating "
                    "votes (>=2 occupied -> occupied) and adding judge_votes "
                    "+ narrowness to the output. Retrieval is unchanged."
                ),
            },
        },
        "required": ["topic_id", "gap"],
    },
    output_type="GapGroundVerifyOutput",
    requires_llm=True,
)

GOVERNANCE_GATE_SPEC = PrimitiveSpec(
    name="governance_gate",
    category=PrimitiveCategory.VERIFICATION,
    description=(
        "Correlation-aware acceptance guard for a self-evolving harness. When the "
        "same (or a correlated) model both PRODUCED a candidate finding and now "
        "JUDGES it, its self-grade is contaminated by shared blind spots, so a "
        "'pass' cannot be trusted at face value. Given the generator/judge models, "
        "the judge confidence, the count of external anchors (evidence the judge "
        "did NOT produce), and the measured generator<->judge contamination "
        "correlation rho (default 0.7 from impact-selective memorization), it "
        "discounts the confidence, computes the residual contamination risk, and "
        "returns how many external verifications r(rho) are still required to meet "
        "the error budget — forcing external ground truth when self-governance is "
        "untrustworthy. Deterministic; intended to gate gap_ground_verify / "
        "evidence / self-audit acceptances in the self-evolution loop."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "verdict": {
                "type": "string",
                "description": "Governor's proposed verdict, e.g. open/accept/pass/novel (a positive claim) or occupied/reject.",
            },
            "judge_confidence": {
                "type": "number",
                "default": 0.5,
                "description": "Governor's raw confidence in [0,1].",
            },
            "generator_model": {
                "type": "string",
                "description": "Model that produced the candidate finding.",
            },
            "judge_model": {
                "type": "string",
                "description": "Model now judging the candidate.",
            },
            "external_anchors": {
                "type": "integer",
                "default": 0,
                "description": "Count of independent evidence items the judge model did NOT produce (retrieved real papers, external DB hits, different-model verdicts).",
            },
            "contamination_rho": {
                "type": "number",
                "default": 0.7,
                "description": "Measured generator<->judge error correlation. Default 0.7 (impact-selective memorization).",
            },
            "alpha": {
                "type": "number",
                "default": 0.1,
                "description": "Target residual-error budget.",
            },
            "same_lineage": {
                "type": "boolean",
                "description": "Override: treat generator and judge as correlated (same family/training) even if model names differ.",
            },
        },
        "required": ["verdict"],
    },
    output_type="GovernanceGateOutput",
    requires_llm=False,
    idempotent=True,
)

QUERY_REFINE_SPEC = PrimitiveSpec(
    name="query_refine",
    category=PrimitiveCategory.ANALYSIS,
    description="Generate candidate search queries from the current topic paper pool and known gaps",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "max_candidates": {"type": "integer", "default": 8},
        },
        "required": ["topic_id"],
    },
    output_type="QueryRefineOutput",
    requires_llm=True,
)

ITERATIVE_RETRIEVAL_LOOP_SPEC = PrimitiveSpec(
    name="iterative_retrieval_loop",
    category=PrimitiveCategory.RETRIEVAL,
    description=(
        "Run multi-round paper retrieval until the topic's paper pool converges. "
        "Each round calls query_refine to propose fresh queries, executes paper_search "
        "without auto-ingest, computes the overlap ratio between hits and the existing "
        "pool, ingests only the new papers, and stops when overlap ≥ threshold AND new "
        "papers added < new_paper_floor for `window` consecutive rounds (or when the "
        "per-new-paper cost exceeds budget_per_new_paper_usd, if set)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "max_rounds": {
                "type": "integer",
                "default": 5,
                "description": "Hard cap on retrieval rounds.",
            },
            "convergence_threshold": {
                "type": "number",
                "default": 0.8,
                "description": "Mean round overlap ratio above which a round counts as 'mostly duplicates'.",
            },
            "window": {
                "type": "integer",
                "default": 2,
                "description": "Number of consecutive converged rounds required to stop.",
            },
            "new_paper_floor": {
                "type": "integer",
                "default": 5,
                "description": "A round also counts as converged when fewer than this many new papers are ingested.",
            },
            "queries_per_round": {
                "type": "integer",
                "default": 4,
                "description": "Max fresh queries per round (from query_refine candidates).",
            },
            "max_results_per_query": {
                "type": "integer",
                "default": 30,
                "description": "Paper search max_results per query inside the loop.",
            },
            "budget_per_new_paper_usd": {
                "type": "number",
                "description": "Optional cost-aware stop: abort if cost_per_new_paper exceeds this.",
            },
            "ingest_relevance": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "default": "medium",
                "description": "Relevance tag to apply when ingesting new papers discovered by the loop.",
            },
        },
        "required": ["topic_id"],
    },
    output_type="IterativeRetrievalLoopOutput",
    requires_llm=True,
)

PAPER_COVERAGE_CHECK_SPEC = PrimitiveSpec(
    name="paper_coverage_check",
    category=PrimitiveCategory.ANALYSIS,
    description=(
        "Identify meta_only papers at risk of being unread. "
        "Checks whether abstracts exist, scores full-text necessity via LLM, "
        "and surfaces download hints for high-necessity papers."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "focus": {
                "type": "string",
                "description": "Optional research focus to guide necessity scoring",
            },
        },
        "required": ["topic_id"],
    },
    output_type="CoverageCheckOutput",
    requires_llm=True,
)

BASELINE_IDENTIFY_SPEC = PrimitiveSpec(
    name="baseline_identify",
    category=PrimitiveCategory.EXTRACTION,
    description="Identify baseline methods for comparison in a topic",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "focus": {"type": "string"},
        },
        "required": ["topic_id"],
    },
    output_type="BaselineIdentifyOutput",
    requires_llm=True,
)

COMPETITIVE_LEARNING_SPEC = PrimitiveSpec(
    name="competitive_learning",
    category=PrimitiveCategory.ANALYSIS,
    description="Analyze exemplar papers from target venue to extract writing patterns "
    "(structure, narrative arc, section lengths, transition techniques). "
    "Run before section_draft to learn from top papers.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {
                "type": "integer",
                "description": "Topic to source exemplar papers from",
            },
            "venue": {
                "type": "string",
                "description": "Target venue name (e.g. 'KDD', 'NeurIPS', 'WWW')",
            },
            "paper_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Optional: specific paper IDs to use as exemplars. "
                "If omitted, auto-selects high-cited recent papers from the topic matching the venue.",
            },
            "contributions": {
                "type": "string",
                "description": "Optional: your paper's key contributions, to tailor pattern recommendations.",
            },
        },
        "required": ["topic_id", "venue"],
    },
    output_type="CompetitiveLearningOutput",
    requires_llm=True,
)

SECTION_DRAFT_SPEC = PrimitiveSpec(
    name="section_draft",
    category=PrimitiveCategory.GENERATION,
    description="Draft a paper section using linked evidence. "
    "Uses section-specific prompts for abstract/intro/related_work/method/experiments "
    "with citation quota. "
    "Optionally accepts writing_patterns from competitive_learning for venue-aware drafting.",
    input_schema={
        "type": "object",
        "properties": {
            "section": {"type": "string"},
            "topic_id": {"type": "integer"},
            "evidence_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Paper ids to prioritize in the numbered evidence "
                "list (outline evidence for this section).",
            },
            "outline": {"type": "string"},
            "paper_context": {
                "type": "object",
                "description": "Shared PaperContext dict (core claim, contributions, "
                "gaps, term registry, promises, drafted-section digests) threaded "
                "across sections by the write-stage loop.",
            },
            "writing_patterns": {
                "type": "string",
                "description": "Writing patterns from competitive_learning output. "
                "When provided, drafting follows venue-specific conventions.",
            },
            "max_words": {
                "type": "integer",
                "default": 0,
                "description": "Target word count; 0 uses section-appropriate default "
                "(intro 1500, related_work 2500, method 3000, experiments 3500).",
            },
            "citation_quota": {
                "type": "integer",
                "default": -1,
                "description": "Minimum distinct citations required; -1 uses section-appropriate "
                "default (intro 15, related_work 30, experiments 8).",
            },
        },
        "required": ["section", "topic_id"],
    },
    output_type="SectionDraftOutput",
    requires_llm=True,
)

CONSISTENCY_CHECK_SPEC = PrimitiveSpec(
    name="consistency_check",
    category=PrimitiveCategory.VERIFICATION,
    description=(
        "Check consistency across drafted sections. Pass manuscript section "
        "text in `sections`; the cached topic literature overview is supplied "
        "as reference-only context. Set `refresh_context` to true after the "
        "manuscript scope changes so the cached overview is recompiled instead "
        "of comparing against a stale field summary."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "sections": {"type": "array", "items": {"type": "string"}},
            "refresh_context": {
                "type": "boolean",
                "default": False,
                "description": (
                    "Invalidate the cached topic literature overview before "
                    "checking (use after reruns or scope changes)."
                ),
            },
        },
        "required": ["topic_id"],
    },
    output_type="ConsistencyCheckOutput",
    requires_llm=True,
)


SELECT_SEEDS_SPEC = PrimitiveSpec(
    name="select_seeds",
    category=PrimitiveCategory.RETRIEVAL,
    description=(
        "Select top citation-expansion seeds from the paper pool. "
        "Ranks by composite score: venue tier (0.4) + citation count (0.3) + relevance (0.3). "
        "Returns papers with s2_id or arxiv_id ready for S2 citation/reference expansion."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "top_n": {
                "type": "integer",
                "default": 10,
                "description": "Number of seed papers to return",
            },
            "min_relevance": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "default": "medium",
                "description": "Minimum relevance level to consider",
            },
        },
        "required": ["topic_id"],
    },
    output_type="SelectSeedsOutput",
    requires_llm=False,
    idempotent=True,
)


EXPAND_CITATIONS_SPEC = PrimitiveSpec(
    name="expand_citations",
    category=PrimitiveCategory.RETRIEVAL,
    description=(
        "Expand the paper pool via citation graph traversal on selected seed papers. "
        "Fetches both forward (papers citing the seed) and backward (papers cited by the seed) "
        "directions from Semantic Scholar. Returns rich candidate metadata — venue tier, "
        "citation count, year, abstract — plus decision_guidance to help the model "
        "choose which papers to ingest and how many expansion rounds to run."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "seed_paper_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Local DB paper IDs to use as seeds (from select_seeds output). "
                "If omitted, select_seeds is called automatically with top_n=5.",
            },
            "forward_limit": {
                "type": "integer",
                "default": 50,
                "description": "Max forward candidates per seed (papers that CITE the seed).",
            },
            "backward_limit": {
                "type": "integer",
                "default": 50,
                "description": "Max backward candidates per seed (papers CITED BY the seed).",
            },
        },
        "required": ["topic_id"],
    },
    output_type="ExpandCitationsOutput",
    requires_llm=False,
    idempotent=False,
)


# ---------------------------------------------------------------------------
# Experiment primitives (Sprint 2)
# ---------------------------------------------------------------------------

CODE_GENERATE_SPEC = PrimitiveSpec(
    name="code_generate",
    category=PrimitiveCategory.GENERATION,
    description="Generate experiment code from study spec and topic context.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "study_spec": {
                "type": "string",
                "description": "Study design specification.",
            },
            "iteration": {"type": "integer", "default": 0},
            "previous_code": {"type": "string", "default": ""},
            "previous_metrics": {"type": "object", "default": {}},
            "feedback": {"type": "string", "default": ""},
        },
        "required": ["topic_id", "study_spec"],
    },
    output_type="CodeGenerationOutput",
    requires_llm=True,
)

CODE_VALIDATE_SPEC = PrimitiveSpec(
    name="code_validate",
    category=PrimitiveCategory.VERIFICATION,
    description="Validate experiment code: syntax, security, imports. Auto-fix common issues.",
    input_schema={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python code to validate."},
            "auto_fix": {"type": "boolean", "default": True},
            "mode": {
                "type": "string",
                "enum": ["strict", "agent"],
                "default": "strict",
                "description": "Only 'strict' runs: experiments are OS-confined with no network, so 'agent' is refused.",
            },
        },
        "required": ["code"],
    },
    output_type="CodeValidationOutput",
    requires_llm=False,
)

EXPERIMENT_RUN_SPEC = PrimitiveSpec(
    name="experiment_run",
    category=PrimitiveCategory.VERIFICATION,
    description="Run experiment in local sandbox with timeout and metric parsing.",
    input_schema={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "Single-file experiment code (legacy path).",
                "default": "",
            },
            "files": {
                "type": "object",
                "description": "Multi-file {relpath: content}. Overrides `code` when both are supplied.",
                "additionalProperties": {"type": "string"},
            },
            "entry_point": {"type": "string", "default": "main.py"},
            "env_vars": {
                "type": "object",
                "description": "Extra non-secret env vars for the confined child; credential-named variables are refused.",
                "additionalProperties": {"type": "string"},
            },
            "timeout_sec": {"type": "number", "default": 300.0},
            "primary_metric": {"type": "string", "default": ""},
            "canonical_components": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
            },
            "ablation_components": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
            },
            "repeats": {"type": "integer", "minimum": 0, "default": 0},
            "variance_estimates": {
                "type": "array",
                "items": {"type": "number", "minimum": 0},
                "default": [],
            },
            "acceptance_criteria": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
            },
            "evidence_kind": {
                "type": "string",
                "enum": ["", "final", "smoke", "debug", "subset", "mock", "synthetic"],
                "default": "",
            },
            "component_provenance": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "component_family": {"type": "string"},
                        "provenance_tag": {
                            "type": "string",
                            "enum": ["borrowed", "modified", "novel"],
                        },
                        "source_paper_id": {
                            "type": ["integer", "null"],
                        },
                    },
                    "required": [
                        "component_family",
                        "provenance_tag",
                        "source_paper_id",
                    ],
                },
                "default": [],
            },
            "metric_direction": {
                "type": "string",
                "enum": ["maximize", "minimize"],
                "default": "maximize",
            },
        },
    },
    output_type="ExperimentRunOutput",
    requires_llm=False,
)

EXPERIMENT_LOOP_SPEC = PrimitiveSpec(
    name="experiment_loop",
    category=PrimitiveCategory.VERIFICATION,
    description=(
        "Autonomous experiment iteration loop. Repeatedly calls code_generate → "
        "code_validate → experiment_run, records each iteration, and stops on "
        "budget/patience. Each run is OS-confined with no network."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "name": {"type": "string", "default": ""},
            "task_description": {"type": "string"},
            "fixture_files": {
                "type": "object",
                "description": "Fixed scaffold files written every iteration (eval set, scorer).",
                "additionalProperties": {"type": "string"},
            },
            "mutable_entry": {"type": "string", "default": "main.py"},
            "primary_metric": {"type": "string"},
            "direction": {"type": "string", "enum": ["max", "min"], "default": "max"},
            "mode": {
                "type": "string",
                "enum": ["strict", "agent"],
                "default": "strict",
                "description": "Only 'strict' runs: experiments are OS-confined with no network, so 'agent' is refused.",
            },
            "timeout_sec": {"type": "number", "default": 300.0},
            "env_vars": {
                "type": "object",
                "additionalProperties": {"type": "string"},
            },
            "budget": {
                "type": "object",
                "properties": {
                    "max_iterations": {"type": "integer", "default": 10},
                    "max_cost_usd": {"type": "number", "default": 0.0},
                    "max_tokens": {"type": "integer", "default": 0},
                    "patience": {"type": "integer", "default": 3},
                },
            },
        },
        "required": ["topic_id", "task_description", "primary_metric"],
    },
    output_type="ExperimentLoopOutput",
    requires_llm=True,
)

VERIFIED_REGISTRY_BUILD_SPEC = PrimitiveSpec(
    name="verified_registry_build",
    category=PrimitiveCategory.VERIFICATION,
    description="Build verified number registry from experiment metrics.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "metrics": {"type": "object", "description": "Experiment metrics dict."},
            "primary_metric_name": {"type": "string", "default": ""},
        },
        "required": ["topic_id", "metrics"],
    },
    output_type="VerifiedRegistryOutput",
    requires_llm=False,
)

VERIFIED_REGISTRY_CHECK_SPEC = PrimitiveSpec(
    name="verified_registry_check",
    category=PrimitiveCategory.VERIFICATION,
    description="Check numbers against the verified registry whitelist.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "numbers": {"type": "array", "items": {"type": "number"}},
            "tolerance": {"type": "number", "default": 0.01},
        },
        "required": ["topic_id", "numbers"],
    },
    output_type="VerifiedRegistryCheckOutput",
    requires_llm=False,
)


# ---------------------------------------------------------------------------
# Verification primitives (Sprint 3)
# ---------------------------------------------------------------------------

PAPER_VERIFY_NUMBERS_SPEC = PrimitiveSpec(
    name="paper_verify_numbers",
    category=PrimitiveCategory.VERIFICATION,
    description="Verify numbers in paper text against the verified registry whitelist.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "text": {"type": "string", "description": "Paper text (LaTeX or plain)."},
            "section": {
                "type": "string",
                "default": "",
                "description": "Section name for strict/lenient classification.",
            },
            "tolerance": {"type": "number", "default": 0.01},
        },
        "required": ["topic_id", "text"],
    },
    output_type="PaperVerifyOutput",
    requires_llm=False,
)

CITATION_VERIFY_SPEC = PrimitiveSpec(
    name="citation_verify",
    category=PrimitiveCategory.VERIFICATION,
    description="Verify citations against external databases (CrossRef, OpenAlex, S2).",
    input_schema={
        "type": "object",
        "properties": {
            "citations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "authors": {"type": "array", "items": {"type": "string"}},
                        "year": {"type": "integer"},
                        "venue": {"type": "string"},
                        "doi": {"type": "string"},
                    },
                    "required": ["title"],
                },
            },
        },
        "required": ["citations"],
    },
    output_type="CitationVerifyOutput",
    requires_llm=False,
)

CITATION_SANITIZE_SPEC = PrimitiveSpec(
    name="citation_sanitize",
    category=PrimitiveCategory.VERIFICATION,
    description=(
        "Deterministically sanitize Markdown references against the RH topic paper pool. "
        "Removes hallucinated references, repairs unique clipped URLs, deduplicates, "
        "renumbers inline citations, and records hallucinated citations when possible."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "text": {"type": "string", "description": "Markdown text to sanitize."},
            "extra_sources": {
                "type": "array",
                "description": "Additional citable sources outside the topic paper pool.",
                "items": {
                    "type": "object",
                    "properties": {
                        "source_id": {"type": "string"},
                        "title": {"type": "string"},
                        "url": {"type": "string"},
                        "doi": {"type": "string"},
                        "arxiv_id": {"type": "string"},
                        "paper_id": {"type": "integer"},
                    },
                },
                "default": [],
            },
        },
        "required": ["topic_id", "text"],
    },
    output_type="CitationSanitizeOutput",
    requires_llm=False,
    idempotent=True,
)

EVIDENCE_TRACE_SPEC = PrimitiveSpec(
    name="evidence_trace",
    category=PrimitiveCategory.VERIFICATION,
    description="Trace claims through evidence links to papers and verified numbers.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
        },
        "required": ["topic_id"],
    },
    output_type="EvidenceTraceOutput",
    requires_llm=False,
)


# ---------------------------------------------------------------------------
# Writing pipeline primitives (Sprint 4)
# ---------------------------------------------------------------------------

OUTLINE_GENERATE_SPEC = PrimitiveSpec(
    name="outline_generate",
    category=PrimitiveCategory.GENERATION,
    description="Generate paper outline from contributions, evidence pack, and experiment results. "
    "Contribution fallback chain: explicit argument → topics.contributions → writing_architecture artifact. "
    "Set contributions once per topic via topic_set_contributions — then every writing primitive reuses it automatically.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "template": {
                "type": "string",
                "default": "neurips",
                "description": "Conference template.",
            },
            "contributions": {
                "type": "string",
                "default": "",
                "description": "Optional override. Fallback order: this argument → "
                "topics.contributions for this topic → latest writing_architecture "
                "artifact. Declare once via topic_set_contributions to avoid repetition.",
            },
        },
        "required": ["topic_id"],
    },
    output_type="OutlineGenerateOutput",
    requires_llm=True,
)

SECTION_REVIEW_SPEC = PrimitiveSpec(
    name="section_review",
    category=PrimitiveCategory.VERIFICATION,
    description="Review a paper section: 10-dim LLM scoring + deterministic checks (AI phrases, weasel words, word count).",
    input_schema={
        "type": "object",
        "properties": {
            "section": {"type": "string", "description": "Section name."},
            "content": {"type": "string", "description": "Section text to review."},
            "target_words": {"type": "integer", "default": 0},
            "target_venue": {
                "type": "string",
                "default": "",
                "description": "Target venue; caps the abstract band at its abstract limit.",
            },
        },
        "required": ["section", "content"],
    },
    output_type="SectionReviewOutput",
    requires_llm=True,
)

SECTION_REVISE_SPEC = PrimitiveSpec(
    name="section_revise",
    category=PrimitiveCategory.GENERATION,
    description="Revise a paper section based on review feedback.",
    input_schema={
        "type": "object",
        "properties": {
            "section": {"type": "string"},
            "content": {"type": "string", "description": "Current section text."},
            "review_feedback": {
                "type": "string",
                "description": "Review issues to address.",
            },
            "target_words": {"type": "integer", "default": 0},
            "full_manuscript": {
                "type": "boolean",
                "default": False,
                "description": "Revise complete source using bounded exact edits; never truncate input.",
            },
        },
        "required": ["section", "content", "review_feedback"],
    },
    output_type="SectionReviseOutput",
    requires_llm=True,
)

LATEX_COMPILE_SPEC = PrimitiveSpec(
    name="latex_compile",
    category=PrimitiveCategory.GENERATION,
    description="Assemble and compile LaTeX paper with conference template and BibTeX.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "output_dir": {
                "type": "string",
                "description": "Directory for output files.",
            },
            "template": {"type": "string", "default": "neurips"},
            "sections": {
                "type": "object",
                "description": "Section name → content mapping.",
            },
            "title": {"type": "string", "default": ""},
            "authors": {"type": "array", "items": {"type": "string"}, "default": []},
            "abstract": {"type": "string", "default": ""},
            "bibliography_entries": {
                "type": "array",
                "items": {"type": "string"},
                "description": "BibTeX entries.",
            },
        },
        "required": ["topic_id", "output_dir"],
    },
    output_type="LatexCompileOutput",
    requires_llm=False,
)


# ---------------------------------------------------------------------------
# Evolution primitives (Sprint 5)
# ---------------------------------------------------------------------------

EXPERIENCE_INGEST_SPEC = PrimitiveSpec(
    name="experience_ingest",
    category=PrimitiveCategory.EXTRACTION,
    description=(
        "V2 unified experience ingestion. Records human edits, review findings, "
        "gold-standard comparisons, or auto-extracted observations into the "
        "experience pipeline. Bridges to V1 lesson store automatically."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "source_kind": {
                "type": "string",
                "enum": [
                    "human_edit",
                    "self_review",
                    "gold_comparison",
                    "auto_extracted",
                ],
            },
            "stage": {"type": "string"},
            "section": {"type": "string"},
            "before_text": {"type": "string"},
            "after_text": {"type": "string"},
            "diff_summary": {"type": "string"},
            "quality_delta": {"type": "number"},
            "topic_id": {"type": "integer"},
            "paper_id": {"type": "integer"},
        },
        "required": ["source_kind", "stage"],
    },
    output_type="ExperienceIngestOutput",
    requires_llm=False,
)

LESSON_EXTRACT_SPEC = PrimitiveSpec(
    name="lesson_extract",
    category=PrimitiveCategory.EXTRACTION,
    description="Extract lessons learned from a completed stage execution.",
    input_schema={
        "type": "object",
        "properties": {
            "stage": {"type": "string", "description": "Stage that just completed."},
            "stage_summary": {
                "type": "string",
                "description": "Summary of what happened.",
            },
            "issues_encountered": {
                "type": "array",
                "items": {"type": "string"},
                "default": [],
            },
        },
        "required": ["stage", "stage_summary"],
    },
    output_type="LessonExtractOutput",
    requires_llm=True,
)

LESSON_OVERLAY_SPEC = PrimitiveSpec(
    name="lesson_overlay",
    category=PrimitiveCategory.SYNTHESIS,
    description="Build prompt overlay from stored lessons for a stage.",
    input_schema={
        "type": "object",
        "properties": {
            "stage": {"type": "string"},
            "store_path": {
                "type": "string",
                "description": "Path to lessons JSONL file.",
            },
            "top_k": {"type": "integer", "default": 5},
        },
        "required": ["stage", "store_path"],
    },
    output_type="LessonOverlayOutput",
    requires_llm=False,
)

STRATEGY_DISTILL_SPEC = PrimitiveSpec(
    name="strategy_distill",
    category=PrimitiveCategory.SYNTHESIS,
    description=(
        "Distill lessons and trajectories into reusable strategies for a stage. "
        "5-phase pipeline: collect, aggregate, distill, quality-gate, persist."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "stage": {
                "type": "string",
                "description": "Stage to distill (e.g. build, analyze)",
            },
            "min_lessons": {"type": "integer", "default": 3},
            "topic_id": {"type": "integer"},
            "force": {"type": "boolean", "default": False},
        },
        "required": ["stage"],
    },
    output_type="StrategyDistillOutput",
    requires_llm=False,  # manages its own LLM calls internally
)

STRATEGY_INJECT_SPEC = PrimitiveSpec(
    name="strategy_inject",
    category=PrimitiveCategory.SYNTHESIS,
    description="Get active strategy overlay text for a stage (for prompt injection).",
    input_schema={
        "type": "object",
        "properties": {
            "stage": {"type": "string"},
            "topic_id": {"type": "integer"},
            "max_strategies": {"type": "integer", "default": 3},
        },
        "required": ["stage"],
    },
    output_type="StrategyInjectOutput",
    requires_llm=False,
)

EXPERIMENT_LOG_SPEC = PrimitiveSpec(
    name="experiment_log",
    category=PrimitiveCategory.EXTRACTION,
    description="Log an experiment result for dual-loop tracking.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "hypothesis": {"type": "string"},
            "primary_metric_name": {"type": "string"},
            "primary_metric_value": {"type": "number"},
            "outcome": {
                "type": "string",
                "enum": ["pending", "success", "partial", "failure"],
            },
            "notes": {"type": "string"},
        },
        "required": ["topic_id", "hypothesis"],
    },
    output_type="ExperimentLogOutput",
    requires_llm=False,
)

META_REFLECT_SPEC = PrimitiveSpec(
    name="meta_reflect",
    category=PrimitiveCategory.ANALYSIS,
    description=(
        "Cross-experiment meta-reflection: analyze patterns and decide "
        "DEEPEN / BROADEN / PIVOT / CONCLUDE."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "force": {"type": "boolean", "default": False},
        },
        "required": ["topic_id"],
    },
    output_type="MetaReflectOutput",
    requires_llm=False,  # manages its own LLM calls internally
)


# ---------------------------------------------------------------------------
# Deep reading primitives
# ---------------------------------------------------------------------------

DEEP_READ_SPEC = PrimitiveSpec(
    name="deep_read",
    category=PrimitiveCategory.COMPREHENSION,
    description=(
        "Critical deep reading of a high-priority paper. "
        "Two-pass analysis: Pass 1 extracts algorithm walkthrough, limitations, "
        "and reproducibility. Pass 2 provides critical assessment, industrial "
        "feasibility, research implications, and cross-paper links. "
        "Stores result in paper_annotations."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "paper_id": {"type": "integer", "description": "Paper ID to deep-read"},
            "topic_id": {
                "type": "integer",
                "description": "Topic ID for cross-paper context",
            },
            "focus": {
                "type": "string",
                "description": "Optional focus area for the reading",
            },
        },
        "required": ["paper_id", "topic_id"],
    },
    output_type="DeepReadingOutput",
    requires_llm=True,
)

GET_DEEP_READING_SPEC = PrimitiveSpec(
    name="get_deep_reading",
    category=PrimitiveCategory.COMPREHENSION,
    description="Retrieve a previously stored deep reading note for a paper.",
    input_schema={
        "type": "object",
        "properties": {
            "paper_id": {"type": "integer", "description": "Paper ID"},
        },
        "required": ["paper_id"],
    },
    output_type="GetDeepReadingOutput",
    requires_llm=False,
    idempotent=True,
)

ENRICH_AFFILIATIONS_SPEC = PrimitiveSpec(
    name="enrich_affiliations",
    category=PrimitiveCategory.EXTRACTION,
    description=(
        "Extract author affiliations from PDF author-block text and email domains "
        "on the first 1-2 pages, then merge with existing paper affiliations. "
        "Updates papers.affiliations."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "paper_id": {"type": "integer", "description": "Paper ID"},
        },
        "required": ["paper_id"],
    },
    output_type="AffiliationOutput",
    requires_llm=False,
    idempotent=True,
)


# ---------------------------------------------------------------------------
# Phase 2: Cross-paper analysis specs
# ---------------------------------------------------------------------------

READING_PRIORITIZE_SPEC = PrimitiveSpec(
    name="reading_prioritize",
    category=PrimitiveCategory.ANALYSIS,
    description="Rank unread papers by priority score (gap relevance, citations, recency)",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "focus": {
                "type": "string",
                "description": "Research focus for gap relevance scoring",
            },
            "limit": {
                "type": "integer",
                "description": "Max papers to return (default 20)",
            },
            "weights": {
                "type": "object",
                "description": "Score weights: gap, citation, recency (default 0.4/0.3/0.3)",
                "properties": {
                    "gap": {"type": "number"},
                    "citation": {"type": "number"},
                    "recency": {"type": "number"},
                },
            },
        },
        "required": ["topic_id"],
    },
    output_type="ReadingPrioritizeOutput",
    requires_llm=False,
)

METHOD_TAXONOMY_SPEC = PrimitiveSpec(
    name="method_taxonomy",
    category=PrimitiveCategory.ANALYSIS,
    description="Build a method taxonomy from compiled summaries, with alias detection",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "focus": {"type": "string"},
        },
        "required": ["topic_id"],
    },
    output_type="MethodTaxonomyOutput",
    requires_llm=True,
)

EXPERIMENT_DESIGN_CHECKLIST_SPEC = PrimitiveSpec(
    name="experiment_design_checklist",
    category=PrimitiveCategory.ANALYSIS,
    description="Generate a template-based experiment design checklist (no LLM)",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "method_name": {"type": "string", "description": "Method being evaluated"},
        },
        "required": ["topic_id"],
    },
    output_type="ExperimentDesignChecklistOutput",
    requires_llm=False,
)

EVIDENCE_MATRIX_SPEC = PrimitiveSpec(
    name="evidence_matrix",
    category=PrimitiveCategory.ANALYSIS,
    description="Build evidence matrix: normalize claims into structured dimensions",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "focus": {"type": "string"},
            "paper_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Optional scoped paper IDs to normalize; useful for core-paper batches.",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of compiled-summary papers to include when paper_ids is omitted.",
            },
        },
        "required": ["topic_id"],
    },
    output_type="EvidenceMatrixOutput",
    requires_llm=True,
)

CONTRADICTION_DETECT_SPEC = PrimitiveSpec(
    name="contradiction_detect",
    category=PrimitiveCategory.ANALYSIS,
    description="Detect contradictions between normalized claims in evidence matrix",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
        },
        "required": ["topic_id"],
    },
    output_type="ContradictionDetectOutput",
    requires_llm=True,
)


# ---------------------------------------------------------------------------
# Phase 3: Quantitative extraction specs
# ---------------------------------------------------------------------------

TABLE_EXTRACT_SPEC = PrimitiveSpec(
    name="table_extract",
    category=PrimitiveCategory.EXTRACTION,
    description="Extract structured tables from paper PDF using vision model",
    input_schema={
        "type": "object",
        "properties": {
            "paper_id": {"type": "integer"},
        },
        "required": ["paper_id"],
    },
    output_type="TableExtractOutput",
    requires_llm=True,
)

FIGURE_INTERPRET_SPEC = PrimitiveSpec(
    name="figure_interpret",
    category=PrimitiveCategory.EXTRACTION,
    description="Interpret figures from paper PDF using vision model",
    input_schema={
        "type": "object",
        "properties": {
            "paper_id": {"type": "integer"},
        },
        "required": ["paper_id"],
    },
    output_type="FigureInterpretOutput",
    requires_llm=True,
)

METRICS_AGGREGATE_SPEC = PrimitiveSpec(
    name="metrics_aggregate",
    category=PrimitiveCategory.ANALYSIS,
    description="Aggregate metrics from tables and compiled summaries with provenance",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
        },
        "required": ["topic_id"],
    },
    output_type="MetricsAggregateOutput",
    requires_llm=False,
)


# ---------------------------------------------------------------------------
# Phase 4: Workflow and export specs
# ---------------------------------------------------------------------------

REBUTTAL_FORMAT_SPEC = PrimitiveSpec(
    name="rebuttal_format",
    category=PrimitiveCategory.GENERATION,
    description="Format a rebuttal letter from review issues and responses",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
        },
        "required": ["topic_id"],
    },
    output_type="RebuttalFormatOutput",
    requires_llm=True,
)

TOPIC_EXPORT_SPEC = PrimitiveSpec(
    name="topic_export",
    category=PrimitiveCategory.SYNTHESIS,
    description="Export topic overview as structured markdown report",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
        },
        "required": ["topic_id"],
    },
    output_type="TopicExportOutput",
    requires_llm=False,
)

VISUALIZE_TOPIC_SPEC = PrimitiveSpec(
    name="visualize_topic",
    category=PrimitiveCategory.SYNTHESIS,
    description="Generate Mermaid visualizations: paper graph, taxonomy tree, timeline",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "viz_type": {
                "type": "string",
                "enum": ["paper_graph", "taxonomy_tree", "timeline"],
                "description": "Type of visualization to generate",
            },
        },
        "required": ["topic_id", "viz_type"],
    },
    output_type="VisualizationOutput",
    requires_llm=False,
)


DATASET_INDEX_SPEC = PrimitiveSpec(
    name="dataset_index",
    category=PrimitiveCategory.ANALYSIS,
    description="Extract dataset index from compiled summaries (no LLM)",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
        },
        "required": ["topic_id"],
    },
    output_type="DatasetIndexOutput",
    requires_llm=False,
)

AUTHOR_COVERAGE_SPEC = PrimitiveSpec(
    name="author_coverage",
    category=PrimitiveCategory.ANALYSIS,
    description="Check author coverage in the paper pool (no LLM)",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "author_name": {
                "type": "string",
                "description": "Filter by specific author",
            },
        },
        "required": ["topic_id"],
    },
    output_type="AuthorCoverageOutput",
    requires_llm=False,
)


TOPIC_FRAMING_SPEC = PrimitiveSpec(
    name="topic_framing",
    category=PrimitiveCategory.SYNTHESIS,
    description="Analyze project context (README, docs, papers) to generate a structured "
    "topic definition with search queries, scope boundaries, and seed papers.",
    input_schema={
        "type": "object",
        "properties": {
            "context": {
                "type": "string",
                "description": "Concatenated text from project files (README, docs, notes) "
                "for the LLM to analyze.",
            },
        },
        "required": ["context"],
    },
    output_type="TopicFramingOutput",
    requires_llm=True,
)

DIRECTION_RANKING_SPEC = PrimitiveSpec(
    name="direction_ranking",
    category=PrimitiveCategory.ANALYSIS,
    description="Rank candidate research directions by novelty × feasibility × impact "
    "based on detected gaps and extracted claims.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "focus": {"type": "string", "description": "Optional focus area"},
        },
        "required": ["topic_id"],
    },
    output_type="DirectionRankingOutput",
    requires_llm=True,
)

METHOD_LAYER_EXPANSION_SPEC = PrimitiveSpec(
    name="method_layer_expansion",
    category=PrimitiveCategory.RETRIEVAL,
    description="Extract method keywords from a research proposal and generate "
    "cross-domain search queries for method-layer literature.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "proposal": {
                "type": "string",
                "description": "The research proposal text to extract methods from.",
            },
        },
        "required": ["topic_id", "proposal"],
    },
    output_type="MethodLayerExpansionOutput",
    requires_llm=True,
)

WRITING_ARCHITECTURE_SPEC = PrimitiveSpec(
    name="writing_architecture",
    category=PrimitiveCategory.SYNTHESIS,
    description="Design optimal paper structure based on contributions and venue conventions. "
    "Produces section plan with argument strategy, word targets, and evidence mapping.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "contributions": {
                "type": "string",
                "default": "",
                "description": "Description of the paper's key contributions. "
                "Optional: if omitted, falls back to topics.contributions for "
                "this topic. Set once via "
                "topic_set_contributions and all writing primitives reuse it.",
            },
            "writing_patterns": {
                "type": "string",
                "description": "Optional: writing patterns from competitive_learning output.",
            },
            "outline": {
                "type": "string",
                "description": "Optional: existing outline draft to refine.",
            },
            "manuscript_logic_context": {
                "type": "object",
                "description": "Optional frozen science/results context with sections and allowed_evidence; requires a validated raw logic bundle.",
            },
        },
        "required": ["topic_id"],
    },
    output_type="WritingArchitectureOutput",
    requires_llm=True,
)


PAPER_FINALIZE_SPEC = PrimitiveSpec(
    name="paper_finalize",
    category=PrimitiveCategory.GENERATION,
    description="One-shot paper assembly + PDF compilation. Takes section drafts and "
    "produces .tex, references.bib, and .pdf in one call. Prefers pdflatex, falls back "
    "to tectonic. Default template is 'arxiv' (single-column, self-contained).",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "output_dir": {
                "type": "string",
                "description": "Directory to write paper.tex, references.bib, paper.pdf.",
            },
            "title": {"type": "string"},
            "authors": {"type": "array", "items": {"type": "string"}},
            "abstract": {"type": "string"},
            "sections": {
                "type": "object",
                "description": "Map of section_id → LaTeX content (e.g. "
                "{'introduction': '...', 'method': '...'}).",
            },
            "bibliography_entries": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional BibTeX entries.",
            },
            "template": {
                "type": "string",
                "default": "arxiv",
                "description": "Template: arxiv (default, recommended for drafts), aaai, neurips, icml, iclr, acl, generic.",
            },
        },
        "required": ["topic_id", "output_dir"],
    },
    output_type="PaperFinalizeOutput",
    requires_llm=False,
)


FIGURE_PLAN_SPEC = PrimitiveSpec(
    name="figure_plan",
    category=PrimitiveCategory.SYNTHESIS,
    description="Plan figures and tables for a paper based on contributions and outline. "
    "Produces 3-5 figures + 5-8 tables with captions, layouts, and placement hints.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "contributions": {
                "type": "string",
                "default": "",
                "description": "Description of the paper's key contributions. "
                "Optional: if omitted, falls back to topics.contributions for "
                "this topic.",
            },
            "outline": {
                "type": "string",
                "description": "Optional paper outline to inform placement.",
            },
            "target_venue": {
                "type": "string",
                "description": "Target venue (NeurIPS/ICML/KDD/etc.) for styling conventions.",
            },
        },
        "required": ["topic_id"],
    },
    output_type="FigurePlanOutput",
    requires_llm=True,
)


FIGURE_GENERATE_SPEC = PrimitiveSpec(
    name="figure_generate",
    category=PrimitiveCategory.GENERATION,
    description="Generate academic paper figures from figure_plan output using OpenAI GPT Image by default. "
    "Converts figure metadata into optimized prompts and produces PNG images in output_dir "
    "for LaTeX \\includegraphics integration. Skips tables, only processes kind='figure' items. "
    "Legacy fal.ai providers remain available with model='recraft' or model='flux'. "
    "The contract-driven illustration route (Grok Imagine / GPT Image / Gemini, "
    "chosen by configured keys) is selected with model='illustration', or "
    "model='illustration-fake' for deterministic no-network tests.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "items": {
                "type": "array",
                "items": {"type": "object"},
                "description": "FigurePlanItem objects (dicts with figure_id, kind, title, caption, "
                "purpose, data_source, suggested_layout). Only kind='figure' items are processed.",
            },
            "output_dir": {
                "type": "string",
                "description": "Directory to save generated figure PNGs. Must match paper_finalize output_dir.",
            },
            "model": {
                "type": "string",
                "default": "gpt-image-2",
                "description": (
                    "Image generation model. Defaults to OpenAI 'gpt-image-2'; "
                    "legacy fal.ai values 'recraft' and 'flux' are also supported. "
                    "Use 'illustration' for the env-configured illustration "
                    "backends or 'illustration-fake' for deterministic local tests."
                ),
            },
            "evidence_boundary": {
                "type": "string",
                "enum": [
                    "conceptual",
                    "planned_protocol",
                    "evidence_backed",
                    "mixed",
                ],
                "default": "conceptual",
                "description": "Evidence boundary for illustration figure requests.",
            },
            "figure_contract": {
                "type": "object",
                "description": (
                    "Optional explicit figure contract for the illustration route. When omitted, "
                    "figure_generate derives it from each item."
                ),
            },
            "illustration_fake": {
                "type": "boolean",
                "default": False,
                "description": (
                    "Use the deterministic no-network illustration fake provider "
                    "for local tests instead of a configured backend."
                ),
            },
        },
        "required": ["topic_id", "items", "output_dir"],
    },
    output_type="FigureGenerateOutput",
    requires_llm=True,
)


WRITING_PATTERN_EXTRACT_SPEC = PrimitiveSpec(
    name="writing_pattern_extract",
    category=PrimitiveCategory.EXTRACTION,
    description="Extract structural writing patterns from a deeply-read paper. "
    "Analyzes 12 dimensions (abstract hook type, experiment analysis style, etc.) "
    "to build the Universal Writing Skill. Results persist in writing_observations table.",
    input_schema={
        "type": "object",
        "properties": {
            "paper_id": {
                "type": "integer",
                "description": "Paper ID to extract writing patterns from. "
                "Paper should have full text available (PDF downloaded).",
            },
        },
        "required": ["paper_id"],
    },
    output_type="WritingPatternExtractOutput",
    requires_llm=True,
)

TOPIC_SET_CONTRIBUTIONS_SPEC = PrimitiveSpec(
    name="topic_set_contributions",
    category=PrimitiveCategory.ANALYSIS,
    description="Set the authoritative paper contributions on a topic. "
    "Writing primitives (writing_architecture, outline_generate, figure_plan, "
    "competitive_learning) read this as a fallback when their contributions "
    "argument is empty, so you only need to declare contributions ONCE per topic.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "contributions": {
                "type": "string",
                "description": "Full contributions text: paper title, method name, "
                "claim bullets, etc. This is the 'source of truth' for downstream "
                "writing primitives.",
            },
        },
        "required": ["topic_id", "contributions"],
    },
    output_type="TopicSetContributionsOutput",
    requires_llm=False,
)


TOPIC_GET_CONTRIBUTIONS_SPEC = PrimitiveSpec(
    name="topic_get_contributions",
    category=PrimitiveCategory.ANALYSIS,
    description="Read the authoritative paper contributions from a topic.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
        },
        "required": ["topic_id"],
    },
    output_type="TopicSetContributionsOutput",
    requires_llm=False,
)

# Backward-compat aliases
PROJECT_SET_CONTRIBUTIONS_SPEC = TOPIC_SET_CONTRIBUTIONS_SPEC
PROJECT_GET_CONTRIBUTIONS_SPEC = TOPIC_GET_CONTRIBUTIONS_SPEC


WRITING_SKILL_AGGREGATE_SPEC = PrimitiveSpec(
    name="writing_skill_aggregate",
    category=PrimitiveCategory.SYNTHESIS,
    description="Aggregate writing observations into the Universal Writing Skill. "
    "Reads all writing_observations, computes pattern distributions per dimension, "
    "and persists as strategies for automatic injection into section_draft. "
    "Run after extracting patterns from >=10 papers.",
    input_schema={
        "type": "object",
        "properties": {
            "min_papers": {
                "type": "integer",
                "default": 10,
                "description": "Minimum number of papers with observations required to aggregate.",
            },
        },
        "required": [],
    },
    output_type="WritingSkillAggregateOutput",
    requires_llm=False,
)


# ---------------------------------------------------------------------------
# Algorithm design subsystem specs
# ---------------------------------------------------------------------------

DESIGN_BRIEF_EXPAND_SPEC = PrimitiveSpec(
    name="design_brief_expand",
    category=PrimitiveCategory.SYNTHESIS,
    description="Expand a research direction into a formal design brief with "
    "problem definition, constraints, method slots, and blocking questions.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "direction": {
                "type": "string",
                "description": "Research direction from direction_ranking",
            },
            "constraints": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional design constraints",
            },
        },
        "required": ["topic_id", "direction"],
    },
    output_type="DesignBriefOutput",
)

DESIGN_GAP_PROBE_SPEC = PrimitiveSpec(
    name="design_gap_probe",
    category=PrimitiveCategory.ANALYSIS,
    description="Probe a design brief for knowledge gaps that require "
    "targeted literature search or deep reading.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "brief": {
                "type": "object",
                "description": "Design brief from design_brief_expand",
            },
            "method_inventory": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Optional method inventory from method_taxonomy",
            },
        },
        "required": ["topic_id", "brief"],
    },
    output_type="DesignGapProbeOutput",
)

ALGORITHM_CANDIDATE_GENERATE_SPEC = PrimitiveSpec(
    name="algorithm_candidate_generate",
    category=PrimitiveCategory.GENERATION,
    description="Generate 2-3 concrete algorithm candidates with provenance-tagged "
    "components from a design brief and method inventory.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "brief": {
                "type": "object",
                "description": "Design brief from design_brief_expand",
            },
            "gap_probe": {"type": "object", "description": "Gap probe results"},
            "deep_read_notes": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Deep reading notes for relevant papers",
            },
            "analysis_substrate": {"type": "object"},
            "taste_mode": {
                "type": "string",
                "description": "Idea taste mode prior (high_risk_exploration|cross_domain_transfer|conservative_engineering|ambitious_but_implementable|evidence_first).",
            },
        },
        "required": ["topic_id", "brief"],
    },
    output_type="AlgorithmCandidateGenerateOutput",
)

ORIGINALITY_BOUNDARY_CHECK_SPEC = PrimitiveSpec(
    name="originality_boundary_check",
    category=PrimitiveCategory.VERIFICATION,
    description="Check a candidate algorithm against prior art to determine "
    "novelty boundary: novel, incremental, or too_similar.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "candidate": {
                "type": "object",
                "description": "Algorithm candidate to check",
            },
        },
        "required": ["topic_id", "candidate"],
    },
    output_type="OriginalityBoundaryCheckOutput",
)

ALGORITHM_DESIGN_REFINE_SPEC = PrimitiveSpec(
    name="algorithm_design_refine",
    category=PrimitiveCategory.SYNTHESIS,
    description="Refine the best algorithm candidate with originality feedback "
    "into a final research proposal document.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "candidate": {"type": "object", "description": "Best algorithm candidate"},
            "originality_result": {
                "type": "object",
                "description": "Originality check result",
            },
            "feedback": {
                "type": "string",
                "description": "Additional refinement feedback",
            },
            "constraints": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Design constraints",
            },
            "taste_mode": {
                "type": "string",
                "description": "Optional idea taste mode prior carried into refine.",
            },
        },
        "required": ["topic_id", "candidate"],
    },
    output_type="AlgorithmDesignRefineOutput",
)

ALGORITHM_DESIGN_LOOP_SPEC = PrimitiveSpec(
    name="algorithm_design_loop",
    category=PrimitiveCategory.SYNTHESIS,
    description="Iterative algorithm design loop: brief → gap probe → candidates → "
    "originality check → refine, max 3 rounds until convergence.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "direction": {
                "type": "string",
                "description": "Research direction from direction_ranking",
            },
            "max_rounds": {"type": "integer", "default": 3},
            "constraints": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional design constraints",
            },
        },
        "required": ["topic_id", "direction"],
    },
    output_type="AlgorithmDesignLoopOutput",
)

COLD_START_RUN_SPEC = PrimitiveSpec(
    name="cold_start_run",
    category=PrimitiveCategory.SYNTHESIS,
    description=(
        "Check cold-start readiness for a topic. Returns phase progress for "
        "Seed (paper count), Index (cards, deep reads, writing obs), and "
        "Calibrate (gaps, writing dimensions)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "gold_papers": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional seed arXiv IDs or DOIs to bootstrap the topic",
            },
        },
        "required": ["topic_id"],
    },
    output_type="ColdStartProtocolOutput",
    requires_llm=False,
)


PUBLICATION_PACK_GENERATE_SPEC = PrimitiveSpec(
    name="publication_pack_generate",
    category=PrimitiveCategory.GENERATION,
    description=(
        "Assemble an evidence-bound publication pack contract from the latest topic "
        "artifacts. The pack turns draft sections, evidence, citation/integrity "
        "reports, figure plans, response letters, and slide outlines into one "
        "reviewable submission package without inventing unsupported content."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "target_profile": {
                "type": "string",
                "default": "high-impact-general",
                "description": (
                    "Style/profile label for downstream writing and QA, e.g. "
                    "high-impact-general, neurips, acl, medical-journal, thesis."
                ),
            },
            "record_artifact": {
                "type": "boolean",
                "default": False,
                "description": (
                    "When true, record the generated pack as a write-stage "
                    "publication_pack artifact."
                ),
            },
        },
        "required": ["topic_id"],
    },
    output_type="PublicationPackOutput",
    requires_llm=False,
    idempotent=False,
)


PUBLICATION_PACK_BACKFILL_SPEC = PrimitiveSpec(
    name="publication_pack_backfill",
    category=PrimitiveCategory.GENERATION,
    description=(
        "Execute deterministic, non-LLM publication-pack closure actions. "
        "Backfills safe QA artifacts such as citation_sanitization_report, "
        "process_summary, final_bundle, and an updated publication_pack while "
        "leaving evidence/figure generation to their dedicated tools."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "target_profile": {
                "type": "string",
                "default": "high-impact-general",
            },
            "components": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional components/actions to backfill. Defaults to safe "
                    "deterministic closure actions."
                ),
            },
            "record_artifact": {
                "type": "boolean",
                "default": True,
                "description": "Record an updated publication_pack after backfill.",
            },
        },
        "required": ["topic_id"],
    },
    output_type="PublicationPackBackfillOutput",
    requires_llm=False,
    idempotent=False,
)


PUBLICATION_RUN_SPEC = PrimitiveSpec(
    name="publication_run",
    category=PrimitiveCategory.GENERATION,
    description=(
        "Run one deterministic publication-closure cycle over a topic. "
        "This is the one-command publication surface: inventory current "
        "artifacts, backfill safe QA/finalization artifacts, refresh the "
        "publication_pack, and optionally record a publication_run artifact "
        "without generating unsupported scientific content."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "target_profile": {
                "type": "string",
                "default": "high-impact-general",
            },
            "components": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional safe closure components to backfill. Defaults to "
                    "citation_integrity, process_summary, and final_bundle."
                ),
            },
            "record_artifact": {
                "type": "boolean",
                "default": True,
                "description": "Record a finalize-stage publication_run artifact.",
            },
        },
        "required": ["topic_id"],
    },
    output_type="PublicationRunOutput",
    requires_llm=False,
    idempotent=False,
)


VENUE_COMPLIANCE_CHECK_SPEC = PrimitiveSpec(
    name="venue_compliance_check",
    category=PrimitiveCategory.VERIFICATION,
    description=(
        "Run deterministic venue-specific submission checks over the current "
        "publication artifacts. Records a venue_compliance_report that can block "
        "submission-ready labels until template/PDF, page-limit, anonymization, "
        "bibliography, figure, and human-review requirements are satisfied."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "target_profile": {
                "type": "string",
                "default": "AAAI-style",
            },
            "compiled_pdf_path": {
                "type": "string",
                "description": "Optional venue-formatted PDF path to validate.",
            },
            "page_count": {
                "type": "integer",
                "description": "Optional externally measured page count.",
            },
            "page_limit": {
                "type": "integer",
                "description": "Venue page limit; defaults to 7 for AAAI-style profiles.",
            },
            "anonymous": {
                "type": "boolean",
                "description": "Whether anonymization/double-blind checks passed externally.",
            },
            "bibliography_style": {
                "type": "string",
                "description": "Optional bibliography style label, e.g. aaai.",
            },
            "figure_qa_passed": {
                "type": "boolean",
                "description": "Whether final PDF figure placement/legibility passed externally.",
            },
            "human_review_approved": {
                "type": "boolean",
                "description": "Whether final scholarly/human review approved the submission.",
            },
            "record_artifact": {
                "type": "boolean",
                "default": True,
                "description": "Persist the venue_compliance_report artifact.",
            },
        },
        "required": ["topic_id"],
    },
    output_type="VenueComplianceCheckOutput",
    requires_llm=False,
    idempotent=False,
)


RESEARCH_STATE_UPDATE_SPEC = PrimitiveSpec(
    name="research_state_update",
    category=PrimitiveCategory.SYNTHESIS,
    description=(
        "Record durable research-state feedback for later autonomous rounds: "
        "failure reasons, fix records, contradictions, review feedback, evidence "
        "references, and next actions."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "stage": {
                "type": "string",
                "description": "Stage that the update belongs to, e.g. build, analyze, write, finalize.",
            },
            "event_type": {
                "type": "string",
                "default": "progress",
                "description": "Short event class such as failure, fix, contradiction, review, or progress.",
            },
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "failure_reasons": {"type": "array", "items": {"type": "string"}},
            "fix_records": {"type": "array", "items": {"type": "string"}},
            "contradictions": {"type": "array", "items": {"type": "string"}},
            "review_feedback": {"type": "array", "items": {"type": "string"}},
            "evidence_refs": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Artifact, paper, claim, command, or source references.",
            },
            "next_actions": {"type": "array", "items": {"type": "string"}},
            "record_artifact": {
                "type": "boolean",
                "default": True,
                "description": "Persist the update as a research_state_update artifact.",
            },
        },
        "required": ["topic_id", "stage"],
    },
    output_type="ResearchStateUpdateOutput",
    requires_llm=False,
    idempotent=False,
)


# ---------------------------------------------------------------------------
# Exemplar-Anchored Generation (EAG): the modality-agnostic "stand on the
# shoulders of giants" engine — retrieve high-quality published exemplars,
# transfer FORM (structure/style) not CONTENT, plan by analogy, critique.
# ---------------------------------------------------------------------------

_EXEMPLAR_UNIT_TYPES = [
    "skeleton",
    "intro_arc",
    "abstract",
    "style",
    "figure",
    "figure_suite",
    "result_figure_suite",  # deprecated alias of figure_suite (pilot name)
    # EAG-Ladder L1 section arcs + L2 paragraph craft
    "related_work_arc",
    "method_arc",
    "experiment_arc",
    "discussion_arc",
    "paragraph_moves",
    "abstract_moves",
    "intro_moves",
    "discussion_moves",
    "domain_register",
]

EXEMPLAR_CURATE_SPEC = PrimitiveSpec(
    name="exemplar_curate",
    category=PrimitiveCategory.ANALYSIS,
    description="Build/grow a quality-gated exemplar library from a topic's papers. "
    "Extracts the abstracted FORM of one unit_type (skeleton | intro_arc | abstract | "
    "style | figure_suite; architecture figures route to figure_generate) per paper "
    "and keeps only high-quality, target-venue exemplars. For figure_suite the "
    "evidence is the paper's figure captions (plus optional VLM figure analyses) and it "
    "captures the whole-paper figure plan (roles, chart archetypes, composition, "
    "paper_type). Run before exemplar_plan.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "unit_type": {"type": "string", "enum": _EXEMPLAR_UNIT_TYPES},
            "venue_profile": {
                "type": "object",
                "description": "Resolved venue profile: venue, exemplar_family, prose_register, "
                "structure; selects the discipline pool and generation contract.",
            },
            "target_venue": {"type": "string"},
            "paper_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Optional exemplar paper ids; else auto-selects from the topic pool.",
            },
            "min_quality": {
                "type": "number",
                "description": "Quality-gate threshold 0-10 (default 7).",
            },
            "max_papers": {
                "type": "integer",
                "description": "Max candidate papers to judge (default 8).",
            },
            "min_tier_score": {
                "type": "integer",
                "description": "Min venue_tier_score for auto-selected sources "
                "(default 85 = CCF-A or CAS-Q1). 0 disables. Ignored when paper_ids set.",
            },
        },
        "required": ["topic_id", "unit_type"],
    },
    output_type="ExemplarCurateOutput",
    requires_llm=True,
)

EXEMPLAR_RETRIEVE_SPEC = PrimitiveSpec(
    name="exemplar_retrieve",
    category=PrimitiveCategory.RETRIEVAL,
    description="Rank curated exemplars for a target artifact by STRUCTURE > TOPIC "
    "(structure-first principle): same form/intent beats same topic. Returns top-k.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "unit_type": {"type": "string", "enum": _EXEMPLAR_UNIT_TYPES},
            "venue_profile": {
                "type": "object",
                "description": "Resolved venue profile: venue, exemplar_family, prose_register, "
                "structure; selects the discipline pool and generation contract.",
            },
            "target_venue": {"type": "string"},
            "target_content": {
                "type": "string",
                "description": "This paper's method/content to match.",
            },
            "target_intent": {
                "type": "string",
                "description": "Optional intent/caption for the artifact.",
            },
            "units": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Exemplar units (e.g. exemplar_curate output). Optional when exemplar_units rows exist for topic_id+unit_type.",
            },
            "top_k": {
                "type": "integer",
                "description": "Number of exemplars to return (default 3).",
            },
            "use_embed_rank": {
                "type": "boolean",
                "description": "Dense FORM shortlist via retrieve-then-rerank before LLM rank (default: on when db present).",
            },
        },
        "required": ["unit_type", "target_content"],
    },
    output_type="ExemplarRetrieveOutput",
    requires_llm=True,
)

EXEMPLAR_PLAN_SPEC = PrimitiveSpec(
    name="exemplar_plan",
    category=PrimitiveCategory.SYNTHESIS,
    description="Produce a FORM-ONLY generation plan for THIS paper's artifact by "
    "structural analogy to retrieved exemplars — transfer skeleton/arc/style, never "
    "verbatim wording or claims. Feeds section_draft. Enforces form-not-content.",
    input_schema={
        "type": "object",
        "properties": {
            "register_lexicon": {
                "type": "object",
                "description": "Track A domain register (from build_register_lexicon over a "
                "domain_register pack): canonical field terms to reuse verbatim; exempt from the "
                "overlap gate; non-canonical synonyms are flagged.",
            },
            "topic_id": {"type": "integer"},
            "unit_type": {"type": "string", "enum": _EXEMPLAR_UNIT_TYPES},
            "venue_profile": {
                "type": "object",
                "description": "Resolved venue profile: venue, exemplar_family, prose_register, "
                "structure; selects the discipline pool and generation contract.",
            },
            "target_venue": {"type": "string"},
            "target_content": {
                "type": "string",
                "description": "This paper's method/content/contributions.",
            },
            "retrieved_units": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Exemplar units from exemplar_retrieve.",
            },
        },
        "required": ["unit_type", "target_content", "retrieved_units"],
    },
    output_type="ExemplarPlanOutput",
    requires_llm=True,
)

EXEMPLAR_CRITIQUE_SPEC = PrimitiveSpec(
    name="exemplar_critique",
    category=PrimitiveCategory.VERIFICATION,
    description="Form-not-content (anti-plagiarism) gate: deterministic n-gram overlap "
    "of a generated draft against the source exemplars; fails on excess verbatim reuse.",
    input_schema={
        "type": "object",
        "properties": {
            "register_lexicon": {
                "type": "object",
                "description": "Track A domain register (from build_register_lexicon over a "
                "domain_register pack): canonical field terms to reuse verbatim; exempt from the "
                "overlap gate; non-canonical synonyms are flagged.",
            },
            "draft_text": {"type": "string"},
            "exemplar_texts": {"type": "array", "items": {"type": "string"}},
            "max_overlap": {
                "type": "number",
                "description": "Max allowed n-gram overlap fraction (default 0.18).",
            },
        },
        "required": ["draft_text", "exemplar_texts"],
    },
    output_type="ExemplarCritiqueOutput",
    requires_llm=False,
    idempotent=True,
)

EXEMPLAR_GENERATE_SPEC = PrimitiveSpec(
    name="exemplar_generate",
    category=PrimitiveCategory.GENERATION,
    description="Evaluator-optimizer loop: plan by analogy → draft the artifact following "
    "the FORM-only plan (own words) → run the anti-plagiarism critique gate → revise if it "
    "fails. Reuses exemplar_plan and exemplar_critique. Pilot: skeleton | intro_arc.",
    input_schema={
        "type": "object",
        "properties": {
            "register_lexicon": {
                "type": "object",
                "description": "Track A domain register (from build_register_lexicon over a "
                "domain_register pack): canonical field terms to reuse verbatim; exempt from the "
                "overlap gate; non-canonical synonyms are flagged.",
            },
            "topic_id": {"type": "integer"},
            "unit_type": {"type": "string", "enum": _EXEMPLAR_UNIT_TYPES},
            "venue_profile": {
                "type": "object",
                "description": "Resolved venue profile: venue, exemplar_family, prose_register, "
                "structure; selects the discipline pool and generation contract.",
            },
            "target_venue": {"type": "string"},
            "target_content": {"type": "string"},
            "retrieved_units": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Exemplar units (from exemplar_retrieve).",
            },
            "plan": {
                "type": "object",
                "description": "Optional precomputed exemplar_plan; else computed.",
            },
            "exemplar_texts": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Source texts to guard against verbatim reuse.",
            },
            "section": {
                "type": "string",
                "description": "Prose section for the section_draft backend (e.g. 'introduction').",
            },
            "backend": {
                "type": "string",
                "enum": ["auto", "self", "section_draft"],
                "description": "auto: use RH section_draft (evidence-grounded) when a section + "
                "drafting-ready topic are available, else the self-contained drafter.",
            },
            "max_rounds": {
                "type": "integer",
                "description": "Max draft↔critique rounds (default 2).",
            },
            "max_overlap": {
                "type": "number",
                "description": "Max allowed n-gram overlap (default 0.18).",
            },
            "quality_targets": {
                "description": "Optional venue writing-polish targets "
                "(list of QualityTarget dicts, or a serialized venue_prescription). "
                "When set, the generate loop revises on deterministic misses.",
            },
        },
        "required": ["unit_type", "target_content"],
    },
    output_type="ExemplarGenerateOutput",
    requires_llm=True,
)

FIGURE_SUITE_RENDER_SPEC = PrimitiveSpec(
    name="figure_suite_render",
    category=PrimitiveCategory.GENERATION,
    description="Deterministically render an exemplar-planned figure suite "
    "(exemplar_plan unit_type=figure_suite) from recorded experiment records: "
    "composed multi-panel figures with per-discipline style profiles (stem_conference | "
    "nature_family | social_humanities | biomed_omics). FORM comes from the spec; every "
    "rendered number comes from the records — panels without matching records are skipped "
    "and reported in provenance, never invented. Optional critique runs deterministic "
    "sanity checks plus a VLM readability/composition review when a vision backend is "
    "configured.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "spec": {
                "type": "object",
                "description": "Suite spec: exemplar_plan output (plan wrapper accepted) "
                "with figures[].panels[].chart from the supported chart kinds.",
            },
            "records": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Plain experiment records (observed logs or reported "
                "baselines).",
            },
            "output_dir": {"type": "string"},
            "suite_id": {
                "type": "string",
                "description": "Filename prefix (default 'experiment').",
            },
            "formats": {
                "type": "array",
                "items": {"type": "string", "enum": ["png", "pdf", "svg"]},
            },
            "claim_boundary": {
                "type": "string",
                "description": "Recorded evidence boundary, e.g. "
                "observed_or_reported_results.",
            },
            "style_profile": {
                "type": "string",
                "enum": [
                    "stem_conference",
                    "nature_family",
                    "social_humanities",
                    "biomed_omics",
                ],
                "description": "Override the spec's discipline style profile.",
            },
            "critique": {
                "type": "boolean",
                "description": "Run deterministic (and, when configured, VLM) critique "
                "on the rendered figures.",
            },
        },
        "required": ["spec", "records", "output_dir"],
    },
    output_type="FigureSuiteRenderOutput",
    requires_llm=False,
)

FIGURE_SUITE_PLAN_SPEC = PrimitiveSpec(
    name="figure_suite_plan",
    category=PrimitiveCategory.SYNTHESIS,
    description="Two-phase whole-paper figure contract. source=matrix (design, v1): "
    "ground on a planned inventory (explicit matrix, or the topic's goal_pool / "
    "experiment_result), curate figure_suite exemplars, and plan the "
    "paper's figure suite by analogy — returning a renderable spec, a bidirectional "
    "matrix-coverage check (panels without data / experiments without a panel), per-panel "
    "logging requirements for the run phase, and a generative-pipeline export for "
    "figure_generate. source=records (reconcile, v2): diff a prior design spec against "
    "actual records, pruning unfeedable figures. Transfers FORM only; never invents data.",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "target_content": {
                "type": "string",
                "description": "This paper's contributions/method (the plan target).",
            },
            "source": {
                "type": "string",
                "enum": ["matrix", "records"],
                "description": "matrix: design v1 from a planned inventory; "
                "records: reconcile a prior_plan against observed records into v2.",
            },
            "records": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Observed experiment records (v2 reconcile, or explicit v1 grounding).",
            },
            "matrix_json": {
                "type": "object",
                "description": "Explicit planned matrix {datasets,methods,metric} or {cells:[...]}.",
            },
            "prior_plan": {
                "type": "object",
                "description": "The v1 design spec to reconcile (required for source=records).",
            },
            "paper_type": {"type": "string", "enum": ["empirical", "survey"]},
            "style_profile": {
                "type": "string",
                "enum": [
                    "stem_conference",
                    "nature_family",
                    "social_humanities",
                    "biomed_omics",
                ],
            },
            "top_k": {"type": "integer"},
            "min_quality": {"type": "number"},
            "max_papers": {"type": "integer"},
        },
        "required": ["target_content"],
    },
    output_type="FigureSuitePlanOutput",
    requires_llm=False,
)

FIGURE_PACKAGE_SPEC = PrimitiveSpec(
    name="figure_package",
    category=PrimitiveCategory.GENERATION,
    description=(
        "Build one evidence-bound Figure Package from a FigureTask: intake, "
        "sufficiency, top-one opportunity, figure–caption exemplar form, "
        "design/caption contracts, then deterministic or fake-provider render "
        "and caption QA. Default output is a single package, not a whole-paper "
        "suite. Numeric charts require recorded records. The public path does "
        "not accept a real image provider."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "task": {
                "type": "object",
                "description": "FigureTask payload (schema rh.figure_task.v1).",
            },
            "output_dir": {
                "type": "string",
                "description": "Directory for rendered assets.",
            },
            "units": {
                "type": "array",
                "items": {"type": "object"},
                "description": "Optional figure–caption exemplar units.",
            },
            "figure_id": {
                "type": "string",
                "description": "Optional figure id override (default fig:1).",
            },
        },
        "required": ["task", "output_dir"],
    },
    output_type="FigurePackageOutput",
    requires_llm=False,
)


# ---------------------------------------------------------------------------
# Final-draft polish (终稿打磨): first-class reviewer-style manuscript polish.
# ---------------------------------------------------------------------------

MANUSCRIPT_REVIEW_SPEC = PrimitiveSpec(
    name="manuscript_review",
    category=PrimitiveCategory.ANALYSIS,
    description="Multi-angle reviewer critique of a full manuscript (methods/statistics, "
    "domain, editorial/format) producing PRIORITIZED, ACTIONABLE findings with severity. "
    "The reviewer-style pass RH lacked; used by manuscript_polish.",
    input_schema={
        "type": "object",
        "properties": {
            "manuscript": {"type": "string", "description": "Full manuscript text."},
            "topic_id": {"type": "integer"},
            "angles": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Reviewer angles (default methods_stats, domain, editorial).",
            },
            "venue": {"type": "string"},
        },
        "required": ["manuscript"],
    },
    output_type="ManuscriptReviewOutput",
    requires_llm=True,
)

MANUSCRIPT_UNIFY_SPEC = PrimitiveSpec(
    name="manuscript_unify",
    category=PrimitiveCategory.SYNTHESIS,
    description="Whole-manuscript unification pass (writing tier): rewrite section "
    "seams into real transitions, enforce term-registry wording verbatim, remove "
    "cross-section duplication and true AI cliches while preserving standard "
    "academic register, citations, and every number. Fail-closed: a deterministic "
    "gate (citation markers + numbers preserved, bounded length drift) rejects the "
    "rewrite and returns the original when violated.",
    input_schema={
        "type": "object",
        "properties": {
            "manuscript": {"type": "string", "description": "Full manuscript text."},
            "topic_id": {"type": "integer"},
            "term_registry": {
                "type": "array",
                "items": {"type": "object"},
                "description": "[{term, definition}] to enforce verbatim.",
            },
            "style_card": {
                "type": "string",
                "description": "Optional anchor-exemplar style card (form only).",
            },
            "venue": {"type": "string"},
        },
        "required": ["manuscript"],
    },
    output_type="ManuscriptUnifyOutput",
    requires_llm=True,
)

MANUSCRIPT_POLISH_SPEC = PrimitiveSpec(
    name="manuscript_polish",
    category=PrimitiveCategory.VERIFICATION,
    description="Orchestrated final-draft polish: run manuscript_review + reuse "
    "deterministic section_review checks + consistency_check, synthesize prioritized "
    "findings, and return a submission-readiness verdict (ready|needs_revision|blocked) "
    "that gates 'submission-ready'.",
    input_schema={
        "type": "object",
        "properties": {
            "manuscript": {"type": "string", "description": "Full manuscript text."},
            "sections": {
                "type": "object",
                "description": "Optional {name: text} for per-section checks.",
            },
            "topic_id": {"type": "integer"},
            "venue": {"type": "string"},
            "run_consistency": {
                "type": "boolean",
                "description": "Reuse consistency_check (default true).",
            },
            "run_deterministic": {
                "type": "boolean",
                "description": "Reuse section_review deterministic checks (default true).",
            },
            "workspace_root": {
                "type": "string",
                "description": "Optional project root for deterministic source-fidelity path/function audit.",
            },
            "composition_contract": {
                "type": "object",
                "description": "Optional {allowed_citation_keys, required_citation_keys} for bidirectional citation discipline.",
            },
        },
        "required": ["manuscript"],
    },
    output_type="ManuscriptPolishOutput",
    requires_llm=True,
)


LOGIC_TREE_BUILD_SPEC = PrimitiveSpec(
    name="logic_tree_build",
    category=PrimitiveCategory.SYNTHESIS,
    description="Build the manuscript's claim-logic tree (core claim -> supporting "
    "claims -> evidence leaves anchored to topic papers) from the paper plan and "
    "extracted claims. Each node carries per-section obligations so drafting can be "
    "conditioned on WHAT each section must establish while EAG contracts condition "
    "HOW it reads (form x logic factorization).",
    input_schema={
        "type": "object",
        "properties": {
            "topic_id": {"type": "integer"},
            "target_content": {
                "type": "string",
                "description": "Contributions/claims summary; falls back to the topic's paper plan.",
            },
            "max_nodes": {
                "type": "integer",
                "description": "Tree size cap (default 18).",
            },
        },
        "required": ["topic_id"],
    },
    output_type="LogicTreeOutput",
    requires_llm=True,
)


for spec in (
    EXEMPLAR_CURATE_SPEC,
    EXEMPLAR_RETRIEVE_SPEC,
    EXEMPLAR_PLAN_SPEC,
    EXEMPLAR_CRITIQUE_SPEC,
    EXEMPLAR_GENERATE_SPEC,
    MANUSCRIPT_REVIEW_SPEC,
    MANUSCRIPT_UNIFY_SPEC,
    MANUSCRIPT_POLISH_SPEC,
    TOPIC_SET_CONTRIBUTIONS_SPEC,
    TOPIC_GET_CONTRIBUTIONS_SPEC,
    SELECT_SEEDS_SPEC,
    EXPAND_CITATIONS_SPEC,
    PAPER_SEARCH_SPEC,
    PAPER_INGEST_SPEC,
    PAPER_ACQUIRE_SPEC,
    PAPER_SUMMARIZE_SPEC,
    CLAIM_EXTRACT_SPEC,
    EVIDENCE_LINK_SPEC,
    GAP_DETECT_SPEC,
    ANALYSIS_SUBSTRATE_BUILD_SPEC,
    GAP_GROUND_VERIFY_SPEC,
    PAPER_COVERAGE_CHECK_SPEC,
    BASELINE_IDENTIFY_SPEC,
    COMPETITIVE_LEARNING_SPEC,
    SECTION_DRAFT_SPEC,
    CONSISTENCY_CHECK_SPEC,
    CODE_GENERATE_SPEC,
    CODE_VALIDATE_SPEC,
    EXPERIMENT_RUN_SPEC,
    EXPERIMENT_LOOP_SPEC,
    VERIFIED_REGISTRY_BUILD_SPEC,
    VERIFIED_REGISTRY_CHECK_SPEC,
    PAPER_VERIFY_NUMBERS_SPEC,
    CITATION_VERIFY_SPEC,
    CITATION_SANITIZE_SPEC,
    EVIDENCE_TRACE_SPEC,
    OUTLINE_GENERATE_SPEC,
    SECTION_REVIEW_SPEC,
    SECTION_REVISE_SPEC,
    LATEX_COMPILE_SPEC,
    LESSON_EXTRACT_SPEC,
    EXPERIENCE_INGEST_SPEC,
    LESSON_OVERLAY_SPEC,
    STRATEGY_DISTILL_SPEC,
    STRATEGY_INJECT_SPEC,
    EXPERIMENT_LOG_SPEC,
    META_REFLECT_SPEC,
    DEEP_READ_SPEC,
    GET_DEEP_READING_SPEC,
    ENRICH_AFFILIATIONS_SPEC,
    READING_PRIORITIZE_SPEC,
    METHOD_TAXONOMY_SPEC,
    EXPERIMENT_DESIGN_CHECKLIST_SPEC,
    EVIDENCE_MATRIX_SPEC,
    CONTRADICTION_DETECT_SPEC,
    DATASET_INDEX_SPEC,
    AUTHOR_COVERAGE_SPEC,
    TABLE_EXTRACT_SPEC,
    FIGURE_INTERPRET_SPEC,
    METRICS_AGGREGATE_SPEC,
    REBUTTAL_FORMAT_SPEC,
    TOPIC_EXPORT_SPEC,
    VISUALIZE_TOPIC_SPEC,
    ITERATIVE_RETRIEVAL_LOOP_SPEC,
    TOPIC_FRAMING_SPEC,
    DIRECTION_RANKING_SPEC,
    METHOD_LAYER_EXPANSION_SPEC,
    WRITING_ARCHITECTURE_SPEC,
    WRITING_PATTERN_EXTRACT_SPEC,
    WRITING_SKILL_AGGREGATE_SPEC,
    FIGURE_PLAN_SPEC,
    FIGURE_GENERATE_SPEC,
    PAPER_FINALIZE_SPEC,
    PUBLICATION_PACK_GENERATE_SPEC,
    PUBLICATION_PACK_BACKFILL_SPEC,
    PUBLICATION_RUN_SPEC,
    VENUE_COMPLIANCE_CHECK_SPEC,
    RESEARCH_STATE_UPDATE_SPEC,
    DESIGN_BRIEF_EXPAND_SPEC,
    DESIGN_GAP_PROBE_SPEC,
    ALGORITHM_CANDIDATE_GENERATE_SPEC,
    ORIGINALITY_BOUNDARY_CHECK_SPEC,
    ALGORITHM_DESIGN_REFINE_SPEC,
    ALGORITHM_DESIGN_LOOP_SPEC,
    COLD_START_RUN_SPEC,
    LOGIC_TREE_BUILD_SPEC,
):
    PRIMITIVE_REGISTRY[spec.name] = spec
