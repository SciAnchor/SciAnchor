"""Private multi-step dry-run planning for Topic Knowledge consumption."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass, replace
from typing import Any

from .knowledge_consumption import (
    ADVISORY_KNOWLEDGE_ACTIONS,
    BLOCKED_KNOWLEDGE_ACTIONS,
    EXECUTABLE_KNOWLEDGE_ACTIONS,
    EvidenceAnchor,
    KnowledgeContextPack,
    KnowledgeContextRequest,
    assemble_knowledge_context,
    plan_knowledge_action,
)
from .research_wiki import ResearchWikiExport
from .topic_knowledge_readiness import TopicKnowledgeReadinessReport
from .topic_layer import TopicKnowledgeSnapshot


@dataclass(frozen=True)
class KnowledgeDryRunPlanStep:
    step_index: int
    action_name: str
    mode: str
    required_inputs: dict[str, Any]
    evidence_anchors: tuple[EvidenceAnchor, ...]
    coverage_warnings: tuple[str, ...]
    blocked_reason: str
    dry_run: bool = True

    @property
    def executable(self) -> bool:
        return self.mode == "executable" and not self.blocked_reason


@dataclass(frozen=True)
class KnowledgeDryRunPlanReport:
    topic_id: int
    status: str
    context_pack: KnowledgeContextPack
    steps: tuple[KnowledgeDryRunPlanStep, ...]
    blocked_reason: str
    executable_action_allowlist: tuple[str, ...]
    advisory_action_allowlist: tuple[str, ...]
    forbidden_action_allowlist: tuple[str, ...]
    execution_performed: bool = False


def simulate_private_knowledge_dry_run_plan(
    request: KnowledgeContextRequest,
    *,
    snapshot: TopicKnowledgeSnapshot,
    wiki_export: ResearchWikiExport,
    readiness_report: TopicKnowledgeReadinessReport,
    max_steps: int = 3,
) -> KnowledgeDryRunPlanReport:
    """Build a bounded private plan without executing any tool calls."""

    step_limit = max(0, min(int(max_steps), 3))
    context_pack = assemble_knowledge_context(
        request,
        snapshot=snapshot,
        wiki_export=wiki_export,
        readiness_report=readiness_report,
    )
    if context_pack.degraded:
        return _report(
            request=request,
            context_pack=context_pack,
            steps=(),
            status="blocked",
            blocked_reason=_context_blocked_reason(context_pack),
        )

    steps: list[KnowledgeDryRunPlanStep] = []
    for action_name in _candidate_actions(
        request=request,
        snapshot=snapshot,
        wiki_export=wiki_export,
        readiness_report=readiness_report,
        context_pack=context_pack,
    ):
        if len(steps) >= step_limit:
            break
        step_request = replace(request, action_name=action_name)
        recommendation = plan_knowledge_action(
            step_request,
            snapshot=snapshot,
            wiki_export=wiki_export,
            readiness_report=readiness_report,
            context_pack=context_pack,
        )
        steps.append(
            KnowledgeDryRunPlanStep(
                step_index=len(steps) + 1,
                action_name=recommendation.action_name,
                mode=recommendation.mode,
                required_inputs=dict(recommendation.required_inputs),
                evidence_anchors=recommendation.evidence_anchors,
                coverage_warnings=recommendation.coverage_warnings,
                blocked_reason=recommendation.blocked_reason,
            )
        )
        if recommendation.mode == "blocked":
            break

    blocked_reason = _first_blocked_reason(steps)
    if blocked_reason:
        return _report(
            request=request,
            context_pack=context_pack,
            steps=tuple(steps),
            status="blocked",
            blocked_reason=blocked_reason,
        )
    return _report(
        request=request,
        context_pack=context_pack,
        steps=tuple(steps),
        status="ready" if steps else "blocked",
        blocked_reason="" if steps else "no_candidate_actions",
    )


def knowledge_dry_run_plan_to_dict(
    report: KnowledgeDryRunPlanReport,
) -> dict[str, Any]:
    """Serialize a dry-run report into deterministic plain data."""

    return _plain_dict(report)


def _candidate_actions(
    *,
    request: KnowledgeContextRequest,
    snapshot: TopicKnowledgeSnapshot,
    wiki_export: ResearchWikiExport,
    readiness_report: TopicKnowledgeReadinessReport,
    context_pack: KnowledgeContextPack,
) -> tuple[str, ...]:
    if request.action_name:
        return (request.action_name,)

    known_actions = (
        EXECUTABLE_KNOWLEDGE_ACTIONS
        | ADVISORY_KNOWLEDGE_ACTIONS
        | BLOCKED_KNOWLEDGE_ACTIONS
    )
    raw_actions = snapshot.payload.get("next_actions")
    candidate_actions = raw_actions if isinstance(raw_actions, list) else ()
    actions = [
        str(action) for action in candidate_actions if str(action) in known_actions
    ]
    if not actions:
        actions = [
            action
            for action in readiness_report.next_actions
            if action in known_actions
        ]
    if not actions:
        recommendation = plan_knowledge_action(
            request,
            snapshot=snapshot,
            wiki_export=wiki_export,
            readiness_report=readiness_report,
            context_pack=context_pack,
        )
        actions.append(recommendation.action_name)
    return tuple(dict.fromkeys(actions))


def _context_blocked_reason(context_pack: KnowledgeContextPack) -> str:
    if "snapshot_stale" in context_pack.coverage_warnings:
        return "snapshot_stale"
    if context_pack.blocked_reason:
        return context_pack.blocked_reason
    for warning in context_pack.coverage_warnings:
        if warning:
            return warning
    return "degraded_context"


def _first_blocked_reason(steps: list[KnowledgeDryRunPlanStep]) -> str:
    for step in steps:
        if step.mode == "blocked":
            return step.blocked_reason or "blocked_step"
    return ""


def _report(
    *,
    request: KnowledgeContextRequest,
    context_pack: KnowledgeContextPack,
    steps: tuple[KnowledgeDryRunPlanStep, ...],
    status: str,
    blocked_reason: str,
) -> KnowledgeDryRunPlanReport:
    return KnowledgeDryRunPlanReport(
        topic_id=request.topic_id,
        status=status,
        context_pack=context_pack,
        steps=steps,
        blocked_reason=blocked_reason,
        executable_action_allowlist=tuple(sorted(EXECUTABLE_KNOWLEDGE_ACTIONS)),
        advisory_action_allowlist=tuple(sorted(ADVISORY_KNOWLEDGE_ACTIONS)),
        forbidden_action_allowlist=tuple(sorted(BLOCKED_KNOWLEDGE_ACTIONS)),
        execution_performed=False,
    )


def _plain_dict(value: Any) -> Any:
    if is_dataclass(value):
        return _plain_dict(asdict(value))
    if isinstance(value, tuple):
        return [_plain_dict(item) for item in value]
    if isinstance(value, list):
        return [_plain_dict(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _plain_dict(item) for key, item in value.items()}
    return value
