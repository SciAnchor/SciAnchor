"""Private Topic Knowledge consumption contracts and runtime helpers.

This module keeps the knowledge-driven agent path inside Python. It assembles
evidence context, recommends already-known RH actions, bridges to RunSpec, and
optionally invokes a supplied service object once. It deliberately does not
register MCP, CLI, HTTP, Zotero, storage schema, or orchestrator surface.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
import hashlib
import json
import re
from typing import Any, Callable, Protocol

from research_harness.runtime import RunSpec, RunVisibleInputs, TaskType

from .research_wiki import ResearchWikiExport, ResearchWikiPage
from .research_wiki_insights import (
    ResearchWikiInsightReport,
    find_research_wiki_insights,
)
from .research_wiki_search import search_research_wiki_pages
from .research_wiki_validation import (
    ResearchWikiValidationReport,
    validate_research_wiki_export,
)
from .topic_knowledge_readiness import (
    TopicKnowledgeReadinessReport,
    topic_knowledge_readiness_report_to_dict,
)
from .topic_layer import TopicKnowledgeSnapshot


FORBIDDEN_KNOWLEDGE_RUN_INPUTS = (
    "hidden_gold",
    "benchmark_reference",
    "unreviewed_private_notes",
)
EXECUTABLE_KNOWLEDGE_ACTIONS = frozenset(
    {
        "paper_search",
        "paper_summarize",
        "claim_extract",
        "baseline_identify",
        "consistency_check",
    }
)
ADVISORY_KNOWLEDGE_ACTIONS = frozenset({"gap_detect", "section_draft"})
BLOCKED_KNOWLEDGE_ACTIONS = frozenset({"paper_ingest"})
_WORD_RE = re.compile(r"[a-z0-9]+")


class _InvokableService(Protocol):
    def invoke(
        self,
        command_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> Any: ...


@dataclass(frozen=True)
class KnowledgeContextRequest:
    topic_id: int
    query: str = ""
    action_name: str = ""
    user_brief: str = ""
    max_sections: int = 6
    max_evidence_anchors: int = 12
    max_chars_per_section: int = 700

    def __post_init__(self) -> None:
        if self.topic_id <= 0:
            raise ValueError("topic_id must be positive")
        if self.max_sections < 0:
            raise ValueError("max_sections must be non-negative")
        if self.max_evidence_anchors < 0:
            raise ValueError("max_evidence_anchors must be non-negative")
        if self.max_chars_per_section <= 0:
            raise ValueError("max_chars_per_section must be positive")


@dataclass(frozen=True)
class EvidenceAnchor:
    page_path: str
    paper_id: int | None
    source_type: str
    source_id: str
    source_hash: str
    section_anchor: str
    evidence_snippet: str
    snapshot_artifact_id: int

    @property
    def resolvable(self) -> bool:
        return bool(
            self.page_path
            and self.source_type
            and self.source_id
            and self.source_hash
            and self.evidence_snippet
        )


@dataclass(frozen=True)
class KnowledgeContextSection:
    page_path: str
    title: str
    page_type: str
    excerpt: str
    matched_terms: tuple[str, ...]
    evidence_count: int
    snapshot_artifact_id: int


@dataclass(frozen=True)
class KnowledgeContextPack:
    topic_id: int
    query: str
    action_name: str
    status: str
    readiness_status: str
    snapshot_artifact_id: int
    snapshot_source_hash: str
    artifact_refs: tuple[str, ...]
    sections: tuple[KnowledgeContextSection, ...]
    evidence_anchors: tuple[EvidenceAnchor, ...]
    coverage_warnings: tuple[str, ...]
    blocked_reason: str = ""
    truncated: bool = False

    @property
    def degraded(self) -> bool:
        return self.status == "degraded"


@dataclass(frozen=True)
class KnowledgeActionRecommendation:
    action_name: str
    mode: str
    why: str
    required_inputs: dict[str, Any]
    evidence_anchors: tuple[EvidenceAnchor, ...]
    coverage_warnings: tuple[str, ...]
    blocked_reason: str
    confidence: float


@dataclass(frozen=True)
class KnowledgeExecutionPlan:
    topic_id: int
    action_name: str
    mode: str
    context_pack: KnowledgeContextPack
    recommendation: KnowledgeActionRecommendation
    service_arguments: dict[str, Any]
    artifact_refs: tuple[str, ...]
    blocked_reason: str = ""

    @property
    def executable(self) -> bool:
        return self.mode == "executable" and not self.blocked_reason


@dataclass(frozen=True)
class KnowledgeLoopReport:
    topic_id: int
    before_readiness: dict[str, Any]
    after_readiness: dict[str, Any]
    context_pack: KnowledgeContextPack
    recommendation: KnowledgeActionRecommendation
    execution_plan: KnowledgeExecutionPlan
    service_result: dict[str, Any]
    executed: bool
    evidence_used: tuple[EvidenceAnchor, ...]
    failure_mode: str = ""


def assemble_knowledge_context(
    request: KnowledgeContextRequest,
    *,
    snapshot: TopicKnowledgeSnapshot,
    wiki_export: ResearchWikiExport,
    readiness_report: TopicKnowledgeReadinessReport,
    insight_report: ResearchWikiInsightReport | None = None,
    validation_report: ResearchWikiValidationReport | None = None,
) -> KnowledgeContextPack:
    """Assemble a deterministic private context pack from knowledge artifacts."""

    _validate_common_topic(request, snapshot, wiki_export, readiness_report)
    validation = validation_report or validate_research_wiki_export(wiki_export)
    insights = insight_report or find_research_wiki_insights(wiki_export)
    warnings = _coverage_warnings(snapshot, readiness_report, validation)
    candidate_pages = _candidate_pages(
        request=request,
        wiki_export=wiki_export,
        insight_report=insights,
    )

    sections: list[KnowledgeContextSection] = []
    anchors: list[EvidenceAnchor] = []
    truncated = False
    for page in candidate_pages:
        if len(sections) >= request.max_sections:
            truncated = True
            break
        page_anchors = _page_evidence_anchors(
            page,
            snapshot_artifact_id=snapshot.artifact_id,
        )
        matched_terms = _matched_terms(page, request.query or request.action_name)
        sections.append(
            KnowledgeContextSection(
                page_path=page.relative_path,
                title=page.title,
                page_type=page.page_type,
                excerpt=_excerpt(page, request.max_chars_per_section),
                matched_terms=matched_terms,
                evidence_count=len(page_anchors),
                snapshot_artifact_id=snapshot.artifact_id,
            )
        )
        for anchor in page_anchors:
            if len(anchors) >= request.max_evidence_anchors:
                truncated = True
                break
            anchors.append(anchor)

    anchors = _dedupe_anchors(anchors)
    blocked_reason = ""
    if not anchors:
        blocked_reason = "missing_evidence_anchors"
        warnings = (*warnings, blocked_reason)

    status = "ready"
    if blocked_reason or _is_degraded_warning(warnings):
        status = "degraded"
    return KnowledgeContextPack(
        topic_id=request.topic_id,
        query=request.query,
        action_name=request.action_name,
        status=status,
        readiness_status=readiness_report.status,
        snapshot_artifact_id=snapshot.artifact_id,
        snapshot_source_hash=snapshot.source_hash,
        artifact_refs=(f"artifact:topic_knowledge_snapshot:{snapshot.artifact_id}",),
        sections=tuple(sections),
        evidence_anchors=tuple(anchors[: request.max_evidence_anchors]),
        coverage_warnings=tuple(dict.fromkeys(warnings)),
        blocked_reason=blocked_reason,
        truncated=truncated,
    )


def plan_knowledge_action(
    request: KnowledgeContextRequest,
    *,
    snapshot: TopicKnowledgeSnapshot,
    wiki_export: ResearchWikiExport,
    readiness_report: TopicKnowledgeReadinessReport,
    context_pack: KnowledgeContextPack | None = None,
    validation_report: ResearchWikiValidationReport | None = None,
) -> KnowledgeActionRecommendation:
    """Recommend one existing RH action without calling an LLM."""

    pack = context_pack or assemble_knowledge_context(
        request,
        snapshot=snapshot,
        wiki_export=wiki_export,
        readiness_report=readiness_report,
        validation_report=validation_report,
    )
    action_name = _select_action(request, readiness_report, pack)
    mode, blocked_reason = _action_mode(action_name)
    required_inputs = _required_inputs(
        action_name,
        request=request,
        pack=pack,
    )
    if mode == "executable" and _missing_required_inputs(action_name, required_inputs):
        mode = "blocked"
        blocked_reason = "missing_required_inputs"
    if pack.blocked_reason and mode == "executable":
        mode = "blocked"
        blocked_reason = pack.blocked_reason

    return KnowledgeActionRecommendation(
        action_name=action_name,
        mode=mode,
        why=_recommendation_reason(action_name, readiness_report, pack),
        required_inputs=required_inputs,
        evidence_anchors=pack.evidence_anchors,
        coverage_warnings=pack.coverage_warnings,
        blocked_reason=blocked_reason,
        confidence=_confidence(mode=mode, pack=pack, readiness=readiness_report),
    )


def build_knowledge_execution_plan(
    request: KnowledgeContextRequest,
    *,
    snapshot: TopicKnowledgeSnapshot,
    wiki_export: ResearchWikiExport,
    readiness_report: TopicKnowledgeReadinessReport,
    context_pack: KnowledgeContextPack | None = None,
    recommendation: KnowledgeActionRecommendation | None = None,
    validation_report: ResearchWikiValidationReport | None = None,
) -> KnowledgeExecutionPlan:
    """Freeze an executable private plan from a recommendation."""

    pack = context_pack or assemble_knowledge_context(
        request,
        snapshot=snapshot,
        wiki_export=wiki_export,
        readiness_report=readiness_report,
        validation_report=validation_report,
    )
    rec = recommendation or plan_knowledge_action(
        request,
        snapshot=snapshot,
        wiki_export=wiki_export,
        readiness_report=readiness_report,
        context_pack=pack,
    )
    if rec.action_name in BLOCKED_KNOWLEDGE_ACTIONS:
        raise ValueError(f"{rec.action_name} is not allowed in knowledge execution")
    return KnowledgeExecutionPlan(
        topic_id=request.topic_id,
        action_name=rec.action_name,
        mode=rec.mode,
        context_pack=pack,
        recommendation=rec,
        service_arguments=dict(rec.required_inputs),
        artifact_refs=pack.artifact_refs,
        blocked_reason=rec.blocked_reason,
    )


def knowledge_execution_plan_to_runspec(
    plan: KnowledgeExecutionPlan,
) -> RunSpec:
    """Bridge a private knowledge execution plan into the existing RunSpec."""

    run_id = _stable_id(
        {
            "topic_id": plan.topic_id,
            "action_name": plan.action_name,
            "service_arguments": plan.service_arguments,
            "artifact_refs": plan.artifact_refs,
            "evidence": [
                asdict(anchor) for anchor in plan.context_pack.evidence_anchors
            ],
        }
    )
    return RunSpec(
        run_id=f"knowledge-{run_id}",
        task_type=_task_type_for_action(plan.action_name),
        topic_id=plan.topic_id,
        objective=f"Execute private knowledge-guided action: {plan.action_name}",
        visible_inputs=RunVisibleInputs(
            user_brief={
                "query": plan.context_pack.query,
                "requested_action": plan.context_pack.action_name,
            },
            artifact_refs=plan.artifact_refs,
            literal_inputs={
                "action_name": plan.action_name,
                "mode": plan.mode,
                "service_arguments": dict(plan.service_arguments),
                "evidence_anchors": [
                    asdict(anchor) for anchor in plan.context_pack.evidence_anchors
                ],
                "coverage_warnings": list(plan.context_pack.coverage_warnings),
            },
        ),
        forbidden_inputs=FORBIDDEN_KNOWLEDGE_RUN_INPUTS,
        required_outputs=("service_result", "readiness_delta"),
        capability_policy={
            "allowed_actions": sorted(EXECUTABLE_KNOWLEDGE_ACTIONS),
            "advisory_actions": sorted(ADVISORY_KNOWLEDGE_ACTIONS),
            "blocked_actions": sorted(BLOCKED_KNOWLEDGE_ACTIONS),
        },
        guardrails={
            "public_surface": "forbidden",
            "paper_ingest": "forbidden",
            "single_action": True,
        },
        trace_policy={"record_evidence_anchors": True},
    )


def run_private_knowledge_execution_loop(
    request: KnowledgeContextRequest,
    *,
    snapshot: TopicKnowledgeSnapshot,
    wiki_export: ResearchWikiExport,
    readiness_report: TopicKnowledgeReadinessReport,
    service: _InvokableService,
    refresh_readiness: Callable[[], TopicKnowledgeReadinessReport] | None = None,
) -> KnowledgeLoopReport:
    """Run at most one private knowledge-guided service action."""

    context_pack = assemble_knowledge_context(
        request,
        snapshot=snapshot,
        wiki_export=wiki_export,
        readiness_report=readiness_report,
    )
    recommendation = plan_knowledge_action(
        request,
        snapshot=snapshot,
        wiki_export=wiki_export,
        readiness_report=readiness_report,
        context_pack=context_pack,
    )
    plan = build_knowledge_execution_plan(
        request,
        snapshot=snapshot,
        wiki_export=wiki_export,
        readiness_report=readiness_report,
        context_pack=context_pack,
        recommendation=recommendation,
    )
    before = topic_knowledge_readiness_report_to_dict(readiness_report)
    service_result: dict[str, Any] = {}
    executed = False
    failure_mode = ""
    if plan.executable:
        raw_result = service.invoke(plan.action_name, plan.service_arguments)
        service_result = _plain_dict(raw_result)
        executed = True
    else:
        failure_mode = plan.blocked_reason or recommendation.mode
        service_result = {
            "status": "blocked",
            "summary": failure_mode,
            "command": plan.action_name,
        }

    after_report = (
        refresh_readiness() if refresh_readiness is not None else readiness_report
    )
    after = topic_knowledge_readiness_report_to_dict(after_report)
    return KnowledgeLoopReport(
        topic_id=request.topic_id,
        before_readiness=before,
        after_readiness=after,
        context_pack=context_pack,
        recommendation=recommendation,
        execution_plan=plan,
        service_result=service_result,
        executed=executed,
        evidence_used=plan.context_pack.evidence_anchors,
        failure_mode=failure_mode,
    )


def evaluate_knowledge_quality(
    context_pack: KnowledgeContextPack,
    recommendation: KnowledgeActionRecommendation,
    *,
    expected_action: str = "",
    expected_pages: tuple[str, ...] | list[str] = (),
) -> dict[str, float]:
    """Return seeded internal metrics for knowledge-grounding regressions."""

    anchors = context_pack.evidence_anchors
    resolvable = sum(1 for anchor in anchors if anchor.resolvable)
    section_paths = {section.page_path for section in context_pack.sections}
    expected_page_list = [str(page) for page in expected_pages if str(page)]
    return {
        "anchor_resolvability": _ratio(resolvable, len(anchors)),
        "source_support_precision": _ratio(
            sum(
                1
                for anchor in anchors
                if anchor.source_hash and anchor.evidence_snippet
            ),
            len(anchors),
        ),
        "context_recall": _ratio(
            sum(1 for page in expected_page_list if page in section_paths),
            len(expected_page_list),
        ),
        "action_recommendation_agreement": 1.0
        if expected_action and recommendation.action_name == expected_action
        else 0.0,
        "stale_degraded_detection": 1.0
        if _is_degraded_warning(context_pack.coverage_warnings) == context_pack.degraded
        else 0.0,
        "tool_call_input_correctness": 1.0
        if not _missing_required_inputs(
            recommendation.action_name,
            recommendation.required_inputs,
        )
        else 0.0,
    }


def knowledge_context_pack_to_dict(pack: KnowledgeContextPack) -> dict[str, Any]:
    return _plain_dict(pack)


def knowledge_recommendation_to_dict(
    recommendation: KnowledgeActionRecommendation,
) -> dict[str, Any]:
    return _plain_dict(recommendation)


def knowledge_execution_plan_to_dict(plan: KnowledgeExecutionPlan) -> dict[str, Any]:
    return _plain_dict(plan)


def knowledge_loop_report_to_dict(report: KnowledgeLoopReport) -> dict[str, Any]:
    return _plain_dict(report)


def _validate_common_topic(
    request: KnowledgeContextRequest,
    snapshot: TopicKnowledgeSnapshot,
    wiki_export: ResearchWikiExport,
    readiness_report: TopicKnowledgeReadinessReport,
) -> None:
    if snapshot.topic_id != request.topic_id:
        raise ValueError("snapshot topic_id must match request topic_id")
    if wiki_export.topic_id != request.topic_id:
        raise ValueError("wiki export topic_id must match request topic_id")
    if readiness_report.topic_id != request.topic_id:
        raise ValueError("readiness topic_id must match request topic_id")


def _coverage_warnings(
    snapshot: TopicKnowledgeSnapshot,
    readiness: TopicKnowledgeReadinessReport,
    validation: ResearchWikiValidationReport,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if not snapshot.is_current:
        warnings.append("snapshot_stale")
    if readiness.status != "ready":
        warnings.append(f"readiness_{readiness.status}")
    for issue in validation.issues:
        warnings.append(issue.code)
    return tuple(dict.fromkeys(warnings))


def _candidate_pages(
    *,
    request: KnowledgeContextRequest,
    wiki_export: ResearchWikiExport,
    insight_report: ResearchWikiInsightReport,
) -> list[ResearchWikiPage]:
    pages_by_path = {page.relative_path: page for page in wiki_export.pages}
    ordered_paths: list[str] = []
    if request.query:
        search_result = search_research_wiki_pages(
            wiki_export,
            request.query,
            max_results=max(request.max_sections * 3, request.max_sections),
        )
        ordered_paths.extend(hit.page_path for hit in search_result.hits)

    action_page_types = _action_page_types(request.action_name)
    if action_page_types:
        ordered_paths.extend(
            page.relative_path
            for page in sorted(wiki_export.pages, key=lambda item: item.relative_path)
            if page.page_type in action_page_types
        )

    for insight in insight_report.insights:
        ordered_paths.extend((insight.source_page, insight.target_page))
        ordered_paths.extend(insight.bridge_pages)

    ordered_paths.extend(
        page.relative_path
        for page in sorted(wiki_export.pages, key=lambda item: item.relative_path)
    )
    selected: list[ResearchWikiPage] = []
    seen: set[str] = set()
    for path in ordered_paths:
        if path in seen or path not in pages_by_path:
            continue
        seen.add(path)
        selected.append(pages_by_path[path])
    return selected


def _action_page_types(action_name: str) -> set[str]:
    if action_name == "paper_summarize":
        return {"source", "source_section"}
    if action_name in {"claim_extract", "baseline_identify", "consistency_check"}:
        return {"finding", "methodology", "source_section"}
    return set()


def _page_evidence_anchors(
    page: ResearchWikiPage,
    *,
    snapshot_artifact_id: int,
) -> tuple[EvidenceAnchor, ...]:
    anchors: list[EvidenceAnchor] = []
    sources = page.frontmatter.get("sources")
    if not isinstance(sources, list):
        return ()
    for source in sources:
        if not isinstance(source, dict):
            continue
        source_type = str(source.get("source_type") or "")
        source_id = str(source.get("source_id") or "")
        source_hash = str(source.get("source_hash") or "")
        snippet = str(source.get("evidence_snippet") or "")
        if not source_type or not source_id or not source_hash or not snippet:
            continue
        anchors.append(
            EvidenceAnchor(
                page_path=page.relative_path,
                paper_id=_optional_int(source.get("paper_id")),
                source_type=source_type,
                source_id=source_id,
                source_hash=source_hash,
                section_anchor=str(source.get("section_anchor") or ""),
                evidence_snippet=snippet,
                snapshot_artifact_id=snapshot_artifact_id,
            )
        )
    return tuple(anchors)


def _dedupe_anchors(anchors: list[EvidenceAnchor]) -> list[EvidenceAnchor]:
    by_key: dict[tuple[Any, ...], EvidenceAnchor] = {}
    for anchor in anchors:
        key = (
            anchor.page_path,
            anchor.paper_id,
            anchor.source_type,
            anchor.source_id,
            anchor.source_hash,
            anchor.section_anchor,
            anchor.evidence_snippet,
        )
        by_key.setdefault(key, anchor)
    return [
        by_key[key]
        for key in sorted(
            by_key,
            key=lambda item: tuple(
                "" if value is None else str(value) for value in item
            ),
        )
    ]


def _matched_terms(page: ResearchWikiPage, query: str) -> tuple[str, ...]:
    terms = tuple(dict.fromkeys(_WORD_RE.findall(query.lower())))
    if not terms:
        return ()
    text = " ".join(
        _WORD_RE.findall(f"{page.title} {page.relative_path} {page.body}".lower())
    )
    tokens = set(text.split())
    return tuple(term for term in terms if term in tokens)


def _excerpt(page: ResearchWikiPage, max_chars: int) -> str:
    text = " ".join(page.body.split())
    if len(text) <= max_chars:
        return text
    return text[: max(0, max_chars - 3)].rstrip() + "..."


def _select_action(
    request: KnowledgeContextRequest,
    readiness: TopicKnowledgeReadinessReport,
    pack: KnowledgeContextPack,
) -> str:
    if request.action_name:
        return request.action_name
    for action in readiness.next_actions:
        if (
            action in EXECUTABLE_KNOWLEDGE_ACTIONS
            or action in ADVISORY_KNOWLEDGE_ACTIONS
        ):
            return action
    if pack.degraded:
        return "consistency_check"
    if pack.evidence_anchors:
        return "claim_extract"
    return "paper_search"


def _action_mode(action_name: str) -> tuple[str, str]:
    if action_name in EXECUTABLE_KNOWLEDGE_ACTIONS:
        return "executable", ""
    if action_name in ADVISORY_KNOWLEDGE_ACTIONS:
        return "advisory", "action_gate_deferred"
    if action_name in BLOCKED_KNOWLEDGE_ACTIONS:
        return "blocked", "action_forbidden"
    return "blocked", "invalid_action"


def _required_inputs(
    action_name: str,
    *,
    request: KnowledgeContextRequest,
    pack: KnowledgeContextPack,
) -> dict[str, Any]:
    focus = request.query or request.user_brief
    if action_name == "paper_search":
        return {
            "query": focus,
            "topic_id": request.topic_id,
            "auto_ingest": False,
            "local_only": True,
        }
    if action_name == "paper_summarize":
        paper_id = _first_paper_id(pack.evidence_anchors)
        payload: dict[str, Any] = {"paper_id": paper_id}
        if focus:
            payload["focus"] = focus
        return payload
    if action_name == "claim_extract":
        payload = {
            "paper_ids": _paper_ids(pack.evidence_anchors),
            "topic_id": request.topic_id,
        }
        if focus:
            payload["focus"] = focus
        return payload
    if action_name in {"baseline_identify", "gap_detect"}:
        payload = {"topic_id": request.topic_id}
        if focus:
            payload["focus"] = focus
        return payload
    if action_name == "consistency_check":
        return {
            "topic_id": request.topic_id,
            "sections": [section.page_path for section in pack.sections[:5]],
        }
    if action_name == "section_draft":
        return {
            "topic_id": request.topic_id,
            "section": "related_work",
            "evidence_ids": [
                f"{anchor.source_type}:{anchor.source_id}"
                for anchor in pack.evidence_anchors
            ],
        }
    return {"topic_id": request.topic_id}


def _missing_required_inputs(action_name: str, inputs: dict[str, Any]) -> bool:
    if action_name == "paper_search":
        return not str(inputs.get("query") or "")
    if action_name == "paper_summarize":
        return not isinstance(inputs.get("paper_id"), int)
    if action_name == "claim_extract":
        return not inputs.get("paper_ids") or not isinstance(
            inputs.get("topic_id"), int
        )
    if action_name in {"baseline_identify", "consistency_check", "gap_detect"}:
        return not isinstance(inputs.get("topic_id"), int)
    if action_name == "section_draft":
        return not inputs.get("section") or not isinstance(inputs.get("topic_id"), int)
    if action_name in BLOCKED_KNOWLEDGE_ACTIONS:
        return True
    return action_name not in EXECUTABLE_KNOWLEDGE_ACTIONS | ADVISORY_KNOWLEDGE_ACTIONS


def _recommendation_reason(
    action_name: str,
    readiness: TopicKnowledgeReadinessReport,
    pack: KnowledgeContextPack,
) -> str:
    warning_text = ", ".join(pack.coverage_warnings) or "no coverage warnings"
    return (
        f"{action_name} selected from readiness status {readiness.status}; "
        f"context status {pack.status}; {warning_text}."
    )


def _confidence(
    *,
    mode: str,
    pack: KnowledgeContextPack,
    readiness: TopicKnowledgeReadinessReport,
) -> float:
    if mode == "blocked":
        return 0.0
    base = 0.76 if mode == "executable" else 0.45
    if readiness.status != "ready":
        base -= 0.18
    if pack.degraded:
        base -= 0.16
    if pack.truncated:
        base -= 0.05
    if not pack.evidence_anchors:
        base -= 0.2
    return round(max(0.05, min(0.95, base)), 2)


def _task_type_for_action(action_name: str) -> TaskType:
    if action_name == "paper_search":
        return TaskType.RETRIEVAL
    return TaskType.ANALYSIS


def _is_degraded_warning(warnings: tuple[str, ...]) -> bool:
    return any(
        warning
        in {
            "snapshot_stale",
            "unresolved_wikilink",
            "missing_evidence_anchor",
            "readiness_stale",
            "readiness_needs_attention",
        }
        for warning in warnings
    )


def _first_paper_id(anchors: tuple[EvidenceAnchor, ...]) -> int | None:
    for anchor in anchors:
        if anchor.paper_id is not None:
            return anchor.paper_id
    return None


def _paper_ids(anchors: tuple[EvidenceAnchor, ...]) -> list[int]:
    return list(
        dict.fromkeys(
            anchor.paper_id for anchor in anchors if anchor.paper_id is not None
        )
    )


def _optional_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 1.0
    return round(numerator / denominator, 4)


def _stable_id(payload: dict[str, Any]) -> str:
    raw = json.dumps(_plain_dict(payload), sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _plain_dict(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _plain_dict(value.to_dict())
    if is_dataclass(value):
        return _plain_dict(asdict(value))
    if isinstance(value, tuple):
        return [_plain_dict(item) for item in value]
    if isinstance(value, list):
        return [_plain_dict(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _plain_dict(item) for key, item in value.items()}
    return value
