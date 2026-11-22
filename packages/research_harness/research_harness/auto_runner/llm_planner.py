"""LLM Planner — generates stage_context parameters via one LLM call per stage.

Before each stage's tools execute, the planner reads topic metadata and
previous-stage artifacts from DB, then asks an LLM to produce the correct
parameters for the current stage's tools (as a JSON dict).

Design constraints:
  - One LLM call per stage (cost control)
  - Routes via the medium tier (`LLM_ROUTE_MEDIUM` env override)
  - Idempotent: same DB state → same output
  - Fail-safe: planner error → returns {} without blocking execution
  - init stage skipped (parameters already known)
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from ..orchestrator.service import OrchestratorService
from ..storage.db import Database
from . import checkpoint as ckpt
from .paper_production_context import build_paper_production_runtime_context

logger = logging.getLogger(__name__)

_DOMAIN_ANCHOR_TERMS = frozenset(
    {
        "baseflow",
        "hydrologic",
        "hydrological",
        "infiltration",
        "noah",
        "noah-mp",
        "runoff",
        "streamflow",
        "vic",
    }
)


def plan_stage(
    *,
    db: Database,
    svc: OrchestratorService,
    topic_id: int,
    stage: str,
    checkpoint_data: dict[str, Any],
) -> dict[str, Any]:
    """Generate enriched stage_context for the current stage via LLM.

    Returns a dict to merge into checkpoint_data["stage_context"].
    Returns {} on failure or for stages that don't need planning.
    """
    if stage == "init":
        meta = _gather_topic_meta(db, topic_id)
        planned = {
            "topic_description": meta["description"] or meta["name"],
            "query": meta["description"][:200] or meta["name"],
        }
        return _merge_paper_production_context(
            planned,
            topic_id=topic_id,
            paper_production_context=_paper_production_context_from_meta(
                meta,
                checkpoint_data=checkpoint_data,
            ),
        )

    planners = {
        "build": _plan_build,
        "analyze": _plan_analyze,
        "propose": _plan_propose,
        "experiment": _plan_experiment,
        "write": _plan_write,
    }

    planner_fn = planners.get(stage)
    if planner_fn is None:
        logger.debug("No planner registered for stage '%s'", stage)
        return {}

    meta = _gather_topic_meta(db, topic_id)
    paper_production_context = _paper_production_context_from_meta(
        meta,
        checkpoint_data=checkpoint_data,
    )
    try:
        result = planner_fn(
            db=db,
            svc=svc,
            topic_id=topic_id,
            checkpoint_data=checkpoint_data,
        )
        if not isinstance(result, dict):
            result = {}
        return _merge_paper_production_context(
            result,
            topic_id=topic_id,
            paper_production_context=paper_production_context,
        )
    except Exception as exc:
        logger.warning("Planner failed for stage '%s': %s", stage, exc)
        return _merge_paper_production_context(
            {},
            topic_id=topic_id,
            paper_production_context=paper_production_context,
        )


_PAPER_PRODUCTION_PROTECTED_KEYS = frozenset(
    {
        "target_venue",
        "venue",
        "target_profile",
        "topic_venue_contract",
        "venue_overlay",
        "paper_profile",
        "domain_method_search_profile",
        "paper_plan_requirements",
        "paper_plan_ready",
        "strict_evidence",
        "next_actions",
        "paper_production_context_status",
        "paper_production_context_blockers",
        "paper_production_runtime_context",
    }
)


def _paper_production_context_from_meta(
    meta: dict[str, str],
    *,
    checkpoint_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build deterministic paper-production context from topic metadata."""

    runtime_context = build_paper_production_runtime_context(
        topic=meta["description"] or meta["name"],
        target_venue=meta["target_venue"],
        local_only=_paper_production_local_only(checkpoint_data),
    )
    stage_context = runtime_context.to_stage_context()
    stage_context["paper_production_runtime_context"] = runtime_context.to_dict()
    return stage_context


def _paper_production_local_only(checkpoint_data: dict[str, Any] | None) -> bool:
    if not isinstance(checkpoint_data, dict):
        return False
    policy = checkpoint_data.get("paper_production_run_policy")
    return isinstance(policy, dict) and policy.get("local_only") is True


def _paper_production_policy(checkpoint_data: dict[str, Any] | None) -> dict[str, Any]:
    # Single source of truth for schema membership (entry writes v2; a v1
    # literal here silently dropped the whole policy on live runs).
    if not isinstance(checkpoint_data, dict):
        return {}
    return dict(ckpt.paper_production_policy(checkpoint_data))


def _apply_demo_seed_pool_budget(
    planned: dict[str, Any],
    *,
    checkpoint_data: dict[str, Any],
) -> dict[str, Any]:
    policy = _paper_production_policy(checkpoint_data)
    if policy.get("evidence_boundary") != "demo_limited_seed_pool":
        return planned

    bounded = dict(planned)
    bounded["max_results"] = min(int(bounded.get("max_results") or 40), 40)
    bounded["seed_top_n"] = min(int(bounded.get("seed_top_n") or 5), 5)
    bounded["forward_limit"] = min(int(bounded.get("forward_limit") or 10), 10)
    bounded["backward_limit"] = min(int(bounded.get("backward_limit") or 10), 10)
    bounded["paper_acquire_limit"] = min(
        int(bounded.get("paper_acquire_limit") or 12), 12
    )
    bounded["submission_readiness"] = "not_submission_ready"
    bounded["claim_strength_limit"] = "evidence_limited_demo"
    return bounded


def _merge_paper_production_context(
    planned: dict[str, Any],
    *,
    topic_id: int,
    paper_production_context: dict[str, Any],
) -> dict[str, Any]:
    """Merge planner output without allowing core paper-production context drift."""

    merged = {**paper_production_context, **planned}
    for key in _PAPER_PRODUCTION_PROTECTED_KEYS:
        if key in paper_production_context:
            merged[key] = paper_production_context[key]
    merged["topic_id"] = topic_id
    return merged


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------


def _gather_topic_meta(db: Database, topic_id: int) -> dict[str, str]:
    """Read topic name, description, target_venue from DB."""
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT name, description, target_venue FROM topics WHERE id = ?",
            (topic_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return {"name": "", "description": "", "target_venue": ""}
    return {
        "name": row["name"] or "",
        "description": row["description"] or "",
        "target_venue": row["target_venue"] or "",
    }


def _gather_artifact_payload(
    svc: OrchestratorService,
    topic_id: int,
    stage: str,
    artifact_type: str,
) -> dict[str, Any]:
    """Load the latest artifact payload for a given stage+type."""
    art = svc.get_latest_artifact(topic_id, stage, artifact_type)
    if art is None:
        return {}
    payload_obj = getattr(art, "payload", None)
    if isinstance(payload_obj, dict):
        return payload_obj
    payload = art.payload_json if hasattr(art, "payload_json") else ""
    if not payload:
        return {}
    try:
        return json.loads(payload) if isinstance(payload, str) else payload
    except (json.JSONDecodeError, TypeError):
        return {}


def _get_paper_count(db: Database, topic_id: int) -> int:
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM paper_topics WHERE topic_id = ?",
            (topic_id,),
        ).fetchone()
        return row["cnt"] if row else 0
    finally:
        conn.close()


def _get_top_papers(
    db: Database, topic_id: int, limit: int = 50
) -> list[dict[str, Any]]:
    """Get top papers by relevance and citation count."""
    conn = db.connect()
    try:
        rows = conn.execute(
            """SELECT p.id, p.title, p.year, p.venue, p.citation_count,
                      pt.relevance
               FROM papers p
               JOIN paper_topics pt ON p.id = pt.paper_id
               WHERE pt.topic_id = ?
               ORDER BY
                 CASE pt.relevance WHEN 'high' THEN 0
                                   WHEN 'medium' THEN 1 ELSE 2 END,
                 COALESCE(p.citation_count, 0) DESC
               LIMIT ?""",
            (topic_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _get_search_queries(db: Database, topic_id: int) -> list[str]:
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT query FROM search_queries WHERE topic_id = ?",
            (topic_id,),
        ).fetchall()
        return [r["query"] for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


def _get_contributions(db: Database, topic_id: int) -> str:
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT contributions FROM topics WHERE id = ?",
            (topic_id,),
        ).fetchone()
        return (row["contributions"] or "") if row else ""
    finally:
        conn.close()


def _text_blob(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except TypeError:
        return str(value)


def _topic_anchor_terms(*values: Any) -> set[str]:
    text = " ".join(_text_blob(value) for value in values).lower()
    tokens = set(re.findall(r"[a-z][a-z0-9-]{2,}", text))
    stopwords = {
        "and",
        "are",
        "can",
        "data",
        "define",
        "from",
        "how",
        "into",
        "model",
        "paper",
        "research",
        "scenario",
        "source",
        "study",
        "the",
        "this",
        "used",
        "using",
        "what",
        "with",
    }
    return {token for token in tokens if token not in stopwords}


def _baseline_names(payload: dict[str, Any]) -> list[str]:
    baselines = payload.get("baselines")
    if not isinstance(baselines, list):
        return []
    names: list[str] = []
    for item in baselines:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("baseline_id") or "").strip()
        if name:
            names.append(name)
    return names


def _gap_descriptions(payload: dict[str, Any], *, limit: int = 4) -> list[str]:
    gaps = payload.get("gaps")
    if not isinstance(gaps, list):
        return []
    descriptions: list[str] = []
    for item in gaps[:limit]:
        if isinstance(item, dict):
            text = str(item.get("description") or item.get("gap") or "").strip()
        else:
            text = str(item).strip()
        if text:
            descriptions.append(text)
    return descriptions


def _proposal_is_topic_aligned(
    result: dict[str, Any],
    *,
    meta: dict[str, str],
    directions: dict[str, Any],
    baselines: dict[str, Any],
) -> bool:
    """Reject proposals that drop the topic/evidence anchors entirely."""

    if not directions and not baselines:
        return True

    proposal_terms = _topic_anchor_terms(result)
    required_sources = [
        meta.get("name", ""),
        meta.get("description", ""),
        directions,
        baselines,
    ]
    required_terms = _topic_anchor_terms(*required_sources)
    if not required_terms:
        return True

    # Domain-specific acronyms and model names are the strongest drift signal.
    strong_terms = {term for term in required_terms if term in _DOMAIN_ANCHOR_TERMS}
    if strong_terms:
        return bool(proposal_terms & strong_terms)

    return True


def _fallback_proposal_from_analyze(
    *,
    meta: dict[str, str],
    directions: dict[str, Any],
    baselines: dict[str, Any],
) -> dict[str, Any]:
    question = str(directions.get("research_question") or "").strip()
    gap_texts = _gap_descriptions(directions)
    baseline_names = _baseline_names(baselines)
    direction = question or meta["description"] or meta["name"]
    if gap_texts:
        direction = f"{direction} Key gap: {gap_texts[0]}"

    payload = {
        "direction": direction,
        "motivation": (
            "The analyze stage identified a topic-specific gap that should be "
            "turned into a bounded, evidence-grounded proposal rather than a "
            "generic cross-domain direction."
        ),
        "baselines": baseline_names[:8],
        "gaps_addressed": gap_texts,
        "research_question": question or direction,
    }
    study_spec_parts = [
        "Use the analyze-stage paper pool and baseline matrix as the evidence boundary.",
        f"Target venue: {meta.get('target_venue') or 'unspecified venue'}.",
    ]
    if baseline_names:
        study_spec_parts.append(
            "Compare against: " + "; ".join(baseline_names[:5]) + "."
        )
    if gap_texts:
        study_spec_parts.append("Primary validation target: " + gap_texts[0])
    return {
        "artifact_type": "direction_proposal",
        "artifact_title": str(meta["name"] or "Evidence-grounded research direction"),
        "artifact_payload": payload,
        "focus": question or meta["description"] or meta["name"],
        "study_spec": " ".join(study_spec_parts),
        "planner_fallback_reason": "topic_drift_guard",
    }


def _demo_seed_pool_policy(checkpoint_data: dict[str, Any]) -> bool:
    policy = _paper_production_policy(checkpoint_data)
    return (
        policy.get("mode") == "demo"
        and policy.get("evidence_boundary") == "demo_limited_seed_pool"
    )


# ---------------------------------------------------------------------------
# LLM call wrapper
# ---------------------------------------------------------------------------


def _call_planner_llm(prompt: str) -> dict[str, Any]:
    """Call LLM with planner prompt, parse JSON response."""
    from ..execution.llm_primitives import _client_chat, _get_client, _parse_json

    client = _get_client(tier="medium", task_name="stage_planner")
    raw = _client_chat(client, prompt)
    return _parse_json(raw, primitive="stage_planner")


# ---------------------------------------------------------------------------
# Per-stage planners
# ---------------------------------------------------------------------------


def _plan_build(
    *,
    db: Database,
    svc: OrchestratorService,
    topic_id: int,
    checkpoint_data: dict[str, Any],
) -> dict[str, Any]:
    meta = _gather_topic_meta(db, topic_id)
    paper_count = _get_paper_count(db, topic_id)
    existing_queries = _get_search_queries(db, topic_id)

    prompt = f"""You are a paper retrieval planner. Given a research topic, generate a search strategy.

Topic: {meta["name"]}
Description: {meta["description"]}
Current paper count: {paper_count}
Existing queries: {json.dumps(existing_queries[:10], ensure_ascii=False)}

Return a JSON object with these fields:
- "query": primary search query string for paper_search
- "additional_queries": list of 3-5 alternative search queries
- "auto_ingest": true
- "max_results": 500
- "seed_top_n": 10
- "forward_limit": 50
- "backward_limit": 50
- "topic_description": a concise summary of the topic (1-2 sentences)

Return ONLY the JSON object, no extra text."""

    result = _call_planner_llm(prompt)
    if not result.get("query"):
        result["query"] = meta["description"][:200] or meta["name"]
    result.setdefault("auto_ingest", True)
    result.setdefault("max_results", 500)
    result.setdefault("seed_top_n", 10)
    result.setdefault("forward_limit", 50)
    result.setdefault("backward_limit", 50)
    result.setdefault("topic_description", meta["description"][:200])
    return _apply_demo_seed_pool_budget(result, checkpoint_data=checkpoint_data)


def _plan_analyze(
    *,
    db: Database,
    svc: OrchestratorService,
    topic_id: int,
    checkpoint_data: dict[str, Any],
) -> dict[str, Any]:
    meta = _gather_topic_meta(db, topic_id)
    papers = _get_top_papers(db, topic_id, limit=50)
    paper_count = len(papers)

    papers_table = "\n".join(
        f"  {p['id']} | {p['title'][:60]} | {p.get('year', '?')} | "
        f"{p.get('venue', '?')[:20]} | cites={p.get('citation_count', 0)}"
        for p in papers[:30]
    )

    prompt = f"""You are a paper analysis planner. Select papers for deep analysis and define the research focus.

Topic: {meta["name"]} — {meta["description"]}
Paper pool ({paper_count} papers, showing top 30):
{papers_table}

Return a JSON object with:
- "paper_ids": list of 20-30 paper IDs (integers) to analyze via claim_extract
- "focus": a specific research focus string (1-2 sentences) for gap_detect and baseline_identify

Return ONLY the JSON object, no extra text."""

    result = _call_planner_llm(prompt)
    if not result.get("paper_ids"):
        result["paper_ids"] = [p["id"] for p in papers[:25]]
    if not result.get("focus"):
        result["focus"] = meta["description"][:200]
    return result


def _plan_propose(
    *,
    db: Database,
    svc: OrchestratorService,
    topic_id: int,
    checkpoint_data: dict[str, Any],
) -> dict[str, Any]:
    gaps = _gather_artifact_payload(svc, topic_id, "analyze", "gap_detect")
    if not gaps:
        gaps = _gather_artifact_payload(svc, topic_id, "analyze", "evidence_pack")
    # direction_ranking is not in analyze's tool list; fall back to
    # direction_proposal (auto-recorded by analyze from gap_detect output)
    # or evidence_pack as additional context.
    directions = _gather_artifact_payload(svc, topic_id, "analyze", "direction_ranking")
    if not directions:
        directions = _gather_artifact_payload(
            svc, topic_id, "analyze", "direction_proposal"
        )
    baselines = _gather_artifact_payload(svc, topic_id, "analyze", "baseline_identify")
    if not baselines:
        baselines = _gather_artifact_payload(
            svc, topic_id, "analyze", "baseline_matrix"
        )
    meta = _gather_topic_meta(db, topic_id)

    if _demo_seed_pool_policy(checkpoint_data) and (directions or baselines):
        result = _fallback_proposal_from_analyze(
            meta=meta,
            directions=directions,
            baselines=baselines,
        )
        result["planner_fallback_reason"] = "demo_limited_seed_pool"
        return result

    prompt = f"""You are a research direction planner. Synthesize gaps, directions, and baselines into a proposal.

Topic: {meta["name"]}
Description: {meta["description"]}
Target venue: {meta["target_venue"]}

Gaps: {json.dumps(gaps, ensure_ascii=False, default=str)[:2000]}
Directions: {json.dumps(directions, ensure_ascii=False, default=str)[:2000]}
Baselines: {json.dumps(baselines, ensure_ascii=False, default=str)[:1000]}

Return a JSON object with:
- "artifact_type": "direction_proposal"
- "artifact_title": a short title for the research direction
- "artifact_payload": object with keys "direction", "motivation", "baselines", "gaps_addressed", "research_question" (REQUIRED: a concise research question this direction answers)
- "focus": the chosen research focus string
- "study_spec": a brief study design specification (datasets, metrics, baselines, experiment groups)

Return ONLY the JSON object, no extra text."""

    result = _call_planner_llm(prompt)
    if not _proposal_is_topic_aligned(
        result,
        meta=meta,
        directions=directions,
        baselines=baselines,
    ):
        result = _fallback_proposal_from_analyze(
            meta=meta,
            directions=directions,
            baselines=baselines,
        )
    result.setdefault("artifact_type", "direction_proposal")
    result.setdefault("artifact_title", "Research direction proposal")
    # Ensure research_question exists in payload (required by orchestrator invariant)
    payload = result.get("artifact_payload", {})
    if isinstance(payload, dict) and "research_question" not in payload:
        payload["research_question"] = payload.get(
            "direction", "What is the optimal approach?"
        )
    result["artifact_payload"] = payload
    # P0-4: study_spec must be non-empty for the artifact to be recorded.
    # Synthesize from direction if LLM returned empty.
    if not result.get("study_spec"):
        direction = payload.get("direction", "") if isinstance(payload, dict) else ""
        rq = payload.get("research_question", "") if isinstance(payload, dict) else ""
        result["study_spec"] = (
            f"Evaluate the proposed approach ({direction or rq or meta['name']}) "
            f"against baselines on standard benchmarks. "
            f"Metrics: accuracy, efficiency, ablation over key components."
        )
    return result


def _plan_experiment(
    *,
    db: Database,
    svc: OrchestratorService,
    topic_id: int,
    checkpoint_data: dict[str, Any],
) -> dict[str, Any]:
    if _demo_seed_pool_policy(checkpoint_data):
        return {
            "study_spec": (
                "Run a deterministic demo seed-pool smoke experiment that verifies "
                "the RH experiment stage can execute locally, emit bounded smoke "
                "metrics, and produce experiment artifacts without claiming "
                "scientific validity or submission readiness."
            ),
            "primary_metric": "execution_success",
            "experiment_execution_mode": "deterministic_demo_smoke",
            "submission_readiness": "not_submission_ready",
            "claim_strength_limit": "evidence_limited_demo",
            "planner_fallback_reason": "demo_limited_seed_pool",
        }
    proposal = _gather_artifact_payload(svc, topic_id, "propose", "direction_proposal")
    study_spec = _gather_artifact_payload(svc, topic_id, "propose", "study_spec")

    prompt = f"""You are an experiment planner. Design an experiment based on the research direction.

Direction proposal: {json.dumps(proposal, ensure_ascii=False, default=str)[:2000]}
Existing study spec: {json.dumps(study_spec, ensure_ascii=False, default=str)[:1000] or "None yet"}

Return a JSON object with:
- "study_spec": a complete experiment design description (what to implement, datasets, metrics, baselines)
- "primary_metric": the main evaluation metric name (e.g. "accuracy", "f1", "regret")

Return ONLY the JSON object, no extra text."""

    result = _call_planner_llm(prompt)
    result.setdefault("study_spec", "")
    result.setdefault("primary_metric", "")
    return result


def _plan_write(
    *,
    db: Database,
    svc: OrchestratorService,
    topic_id: int,
    checkpoint_data: dict[str, Any],
) -> dict[str, Any]:
    meta = _gather_topic_meta(db, topic_id)
    contributions = _get_contributions(db, topic_id)
    if _demo_seed_pool_policy(checkpoint_data):
        topic = meta["name"] or "Research Harness demo topic"
        venue = meta["target_venue"] or "target venue"
        return {
            "venue": venue,
            "target_profile": f"{venue} demo smoke",
            "title": topic,
            "abstract": (
                "This bounded Research Harness demo manuscript verifies that "
                "the paper-production lane can assemble a PDF from a limited "
                "seed evidence pool. It is not a submission-ready scientific "
                "claim."
            ),
            "authors": ["Research Harness"],
            "contributions": contributions
            or (
                "Demonstrates local paper-production closure from a broad topic, "
                "target venue, bounded evidence pool, smoke experiment output, "
                "and publication package artifacts."
            ),
            "outline": (
                "Abstract; method; deterministic smoke experiment summary; "
                "limitations and submission-readiness boundary."
            ),
            "sections_to_draft": [
                "abstract",
                "method",
                "experiment_summary",
                "limitations",
            ],
            "evidence_ids": [],
            "max_words": 1200,
            "strict_evidence": False,
            "template": "generic",
            "paper_production_closure_mode": "deterministic_pdf_smoke",
            "publication_components": [
                "process_summary",
                "citation_integrity",
                "final_bundle",
                "publication_pack",
            ],
            "record_artifact": True,
            "submission_readiness": "not_submission_ready",
            "claim_strength_limit": "evidence_limited_demo",
            "planner_fallback_reason": "demo_limited_seed_pool",
        }
    experiment = _gather_artifact_payload(
        svc, topic_id, "experiment", "experiment_result"
    )
    proposal = _gather_artifact_payload(svc, topic_id, "propose", "direction_proposal")

    prompt = f"""You are a paper writing planner. Plan the structure and parameters for drafting a research paper.

Topic: {meta["name"]}
Target venue: {meta["target_venue"] or "top AI conference"}
Contributions: {contributions[:1000] or "Not yet defined"}
Experiment results: {json.dumps(experiment, ensure_ascii=False, default=str)[:1500] or "None"}
Direction: {json.dumps(proposal, ensure_ascii=False, default=str)[:1000] or "None"}

Return a JSON object with:
- "venue": target venue name
- "contributions": the paper's contribution statement
- "outline": a brief paper outline (section titles and key points)
- "sections_to_draft": ordered list of section names to write ["introduction", "related_work", "method", "experiments", "conclusion"]
- "evidence_ids": list of evidence/claim IDs to cite (can be empty)

Return ONLY the JSON object, no extra text."""

    result = _call_planner_llm(prompt)
    result.setdefault("venue", meta["target_venue"] or "NeurIPS")
    result.setdefault("contributions", contributions)
    result.setdefault(
        "sections_to_draft",
        [
            "introduction",
            "related_work",
            "method",
            "experiments",
            "conclusion",
        ],
    )
    return result
