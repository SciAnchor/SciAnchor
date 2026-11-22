"""Private deterministic evaluation corpus for Topic Knowledge consumption."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .knowledge_consumption import (
    KnowledgeContextRequest,
    assemble_knowledge_context,
    evaluate_knowledge_quality,
    plan_knowledge_action,
)
from .research_wiki import ResearchWikiExport, ResearchWikiPage
from .topic_knowledge_readiness import (
    TopicKnowledgeReadinessReport,
    build_topic_knowledge_readiness_report,
)
from .topic_layer import TopicKnowledgeSnapshot


@dataclass(frozen=True)
class KnowledgeEvaluationCase:
    name: str
    request: KnowledgeContextRequest
    snapshot: TopicKnowledgeSnapshot
    wiki_export: ResearchWikiExport
    readiness_report: TopicKnowledgeReadinessReport
    expected_action: str
    expected_pages: tuple[str, ...]


@dataclass(frozen=True)
class KnowledgeEvaluationOutcome:
    case_name: str
    status: str
    action_name: str
    mode: str
    blocked_reason: str
    required_inputs: dict[str, Any]
    coverage_warnings: tuple[str, ...]
    matched_pages: tuple[str, ...]
    metrics: dict[str, float]


def build_private_knowledge_evaluation_corpus(
    *,
    topic_id: int = 1,
) -> tuple[KnowledgeEvaluationCase, ...]:
    """Return deterministic private fixtures for knowledge quality gates."""

    return (
        _case(
            name="evidence_rich",
            topic_id=topic_id,
            artifact_id=8801,
            query="hybrid retrieval recall",
            next_actions=("claim_extract",),
            expected_action="claim_extract",
            expected_pages=("findings/hybrid-retrieval-improves-recall.md",),
            pages=(
                _page(
                    topic_id=topic_id,
                    path="findings/hybrid-retrieval-improves-recall.md",
                    title="Hybrid retrieval improves recall",
                    page_type="finding",
                    body=(
                        "# Hybrid retrieval improves recall\n\n"
                        "Hybrid retrieval improves recall on ORB with "
                        "[[sources/paper-1|paper evidence]].\n"
                    ),
                    sources=(
                        _source(
                            paper_id=1,
                            source_type="normalized_claims",
                            source_id="rich-claim-1",
                            source_hash="rich-hash-1",
                            snippet="Hybrid retrieval improves recall on ORB.",
                        ),
                    ),
                ),
                _page(
                    topic_id=topic_id,
                    path="sources/paper-1.md",
                    title="Paper 1",
                    page_type="source",
                    body="# Paper 1\n\nSource page for hybrid retrieval recall.\n",
                    sources=(
                        _source(
                            paper_id=1,
                            source_type="paper_card",
                            source_id="paper-1",
                            source_hash="paper-card-hash-1",
                            snippet="Paper card summary covers hybrid retrieval.",
                        ),
                    ),
                ),
            ),
        ),
        _case(
            name="missing_paper_card_or_summary",
            topic_id=topic_id,
            artifact_id=8802,
            query="summarize sparse retrieval",
            next_actions=("paper_summarize",),
            expected_action="paper_summarize",
            expected_pages=("sources/sparse-source.md",),
            coverage={"paper_artifacts": 0, "compiled_summaries": 0},
            pages=(
                _page(
                    topic_id=topic_id,
                    path="sources/sparse-source.md",
                    title="Sparse source without paper card",
                    page_type="source",
                    body=(
                        "# Sparse source without paper card\n\n"
                        "Sparse retrieval has a source stub but no paper id, "
                        "paper card, or compiled summary.\n"
                    ),
                    sources=(
                        _source(
                            paper_id=None,
                            source_type="paper_stub",
                            source_id="sparse-source",
                            source_hash="sparse-source-hash",
                            snippet="Sparse retrieval source is present but not linked.",
                        ),
                    ),
                ),
            ),
        ),
        _case(
            name="contradiction_heavy",
            topic_id=topic_id,
            artifact_id=8803,
            query="hybrid retrieval contradiction",
            next_actions=("consistency_check",),
            expected_action="consistency_check",
            expected_pages=("findings/hybrid-contradiction.md",),
            coverage={"contradictions": 2},
            pages=(
                _page(
                    topic_id=topic_id,
                    path="findings/hybrid-contradiction.md",
                    title="Hybrid retrieval contradiction",
                    page_type="finding",
                    body=(
                        "# Hybrid retrieval contradiction\n\n"
                        "One claim reports recall gains, while another reports "
                        "no recall change for hybrid retrieval.\n"
                    ),
                    sources=(
                        _source(
                            paper_id=1,
                            source_type="contradictions",
                            source_id="contradiction-1",
                            source_hash="contradiction-hash-1",
                            snippet="Hybrid retrieval recall gains conflict.",
                        ),
                    ),
                ),
            ),
        ),
        _case(
            name="weak_unresolved_wikilink",
            topic_id=topic_id,
            artifact_id=8804,
            query="weak evidence retrieval",
            next_actions=("claim_extract",),
            expected_action="claim_extract",
            expected_pages=("findings/weak-evidence.md",),
            pages=(
                _page(
                    topic_id=topic_id,
                    path="findings/weak-evidence.md",
                    title="Weak evidence retrieval",
                    page_type="finding",
                    body=(
                        "# Weak evidence retrieval\n\n"
                        "Weak evidence retrieval depends on "
                        "[[missing/evidence]] and needs source repair.\n"
                    ),
                    sources=(
                        _source(
                            paper_id=2,
                            source_type="normalized_claims",
                            source_id="weak-claim-1",
                            source_hash="weak-hash-1",
                            snippet="Weak evidence retrieval has one usable anchor.",
                        ),
                        _source(
                            paper_id=2,
                            source_type="normalized_claims",
                            source_id="weak-claim-2",
                            source_hash="",
                            snippet="This source is missing a source hash.",
                        ),
                    ),
                ),
            ),
        ),
        _case(
            name="stale_snapshot",
            topic_id=topic_id,
            artifact_id=8805,
            query="stale baseline coverage",
            next_actions=("baseline_identify",),
            expected_action="baseline_identify",
            expected_pages=("methodology/stale-baselines.md",),
            is_current=False,
            pages=(
                _page(
                    topic_id=topic_id,
                    path="methodology/stale-baselines.md",
                    title="Stale baseline coverage",
                    page_type="methodology",
                    body=(
                        "# Stale baseline coverage\n\n"
                        "The stale snapshot has baseline evidence but source "
                        "hashes no longer match the current topic inputs.\n"
                    ),
                    sources=(
                        _source(
                            paper_id=3,
                            source_type="method_atoms",
                            source_id="baseline-1",
                            source_hash="stale-baseline-hash",
                            snippet="Baseline evidence exists in a stale snapshot.",
                        ),
                    ),
                ),
            ),
        ),
    )


def evaluate_private_knowledge_corpus(
    cases: tuple[KnowledgeEvaluationCase, ...]
    | list[KnowledgeEvaluationCase]
    | None = None,
) -> tuple[KnowledgeEvaluationOutcome, ...]:
    """Evaluate the private corpus with existing context and planner metrics."""

    selected_cases = (
        tuple(cases)
        if cases is not None
        else build_private_knowledge_evaluation_corpus()
    )
    outcomes: list[KnowledgeEvaluationOutcome] = []
    for case in selected_cases:
        pack = assemble_knowledge_context(
            case.request,
            snapshot=case.snapshot,
            wiki_export=case.wiki_export,
            readiness_report=case.readiness_report,
        )
        recommendation = plan_knowledge_action(
            case.request,
            snapshot=case.snapshot,
            wiki_export=case.wiki_export,
            readiness_report=case.readiness_report,
            context_pack=pack,
        )
        metrics = dict(
            evaluate_knowledge_quality(
                pack,
                recommendation,
                expected_action=case.expected_action,
                expected_pages=case.expected_pages,
            )
        )
        metrics["source_support_precision"] = _source_support_precision(
            case.wiki_export,
            tuple(section.page_path for section in pack.sections),
        )
        outcomes.append(
            KnowledgeEvaluationOutcome(
                case_name=case.name,
                status=pack.status,
                action_name=recommendation.action_name,
                mode=recommendation.mode,
                blocked_reason=recommendation.blocked_reason,
                required_inputs=dict(recommendation.required_inputs),
                coverage_warnings=pack.coverage_warnings,
                matched_pages=tuple(section.page_path for section in pack.sections),
                metrics={key: metrics[key] for key in sorted(metrics)},
            )
        )
    return tuple(outcomes)


def _case(
    *,
    name: str,
    topic_id: int,
    artifact_id: int,
    query: str,
    next_actions: tuple[str, ...],
    expected_action: str,
    expected_pages: tuple[str, ...],
    pages: tuple[ResearchWikiPage, ...],
    coverage: dict[str, int] | None = None,
    is_current: bool = True,
) -> KnowledgeEvaluationCase:
    snapshot = _snapshot(
        topic_id=topic_id,
        artifact_id=artifact_id,
        next_actions=next_actions,
        coverage=coverage,
        is_current=is_current,
    )
    export = ResearchWikiExport(
        topic_id=topic_id,
        vault_path=Path("/tmp/research-harness-private-knowledge-eval"),
        pages=pages,
        graph={page.relative_path: [] for page in pages},
    )
    readiness = build_topic_knowledge_readiness_report(
        snapshot,
        export,
        search_queries=(query,),
    )
    return KnowledgeEvaluationCase(
        name=name,
        request=KnowledgeContextRequest(
            topic_id=topic_id,
            query=query,
            user_brief=query,
        ),
        snapshot=snapshot,
        wiki_export=export,
        readiness_report=readiness,
        expected_action=expected_action,
        expected_pages=expected_pages,
    )


def _snapshot(
    *,
    topic_id: int,
    artifact_id: int,
    next_actions: tuple[str, ...],
    coverage: dict[str, int] | None,
    is_current: bool,
) -> TopicKnowledgeSnapshot:
    merged_coverage = {
        "paper_count": 1,
        "paper_artifacts": 1,
        "compiled_summaries": 1,
        "normalized_claims": 1,
        "contradictions": 0,
        "semantic_atoms": 3,
        **(coverage or {}),
    }
    source_hash = f"private-eval-source-{artifact_id}"
    return TopicKnowledgeSnapshot(
        topic_id=topic_id,
        artifact_id=artifact_id,
        snapshot_id=artifact_id + 1000,
        source_hash=source_hash,
        current_source_hash=source_hash if is_current else f"{source_hash}-current",
        snapshot_version="topic_knowledge_snapshot.v1",
        payload={
            "coverage": dict(merged_coverage),
            "weak_spots": {},
            "next_actions": list(next_actions),
        },
        source_manifest={"fixture": "private_knowledge_evaluation_corpus"},
        coverage=dict(merged_coverage),
        is_current=is_current,
    )


def _page(
    *,
    topic_id: int,
    path: str,
    title: str,
    page_type: str,
    body: str,
    sources: tuple[dict[str, Any], ...],
) -> ResearchWikiPage:
    return ResearchWikiPage(
        relative_path=path,
        title=title,
        page_type=page_type,
        frontmatter={
            "schema_version": "research_wiki_page.v1",
            "topic_id": topic_id,
            "page_type": page_type,
            "title": title,
            "sources": list(sources),
        },
        body=body,
    )


def _source(
    *,
    paper_id: int | None,
    source_type: str,
    source_id: str,
    source_hash: str,
    snippet: str,
) -> dict[str, Any]:
    source: dict[str, Any] = {
        "source_type": source_type,
        "source_id": source_id,
        "source_hash": source_hash,
        "section_anchor": "results",
        "evidence_snippet": snippet,
    }
    if paper_id is not None:
        source["paper_id"] = paper_id
    return source


def _source_support_precision(
    wiki_export: ResearchWikiExport,
    page_paths: tuple[str, ...],
) -> float:
    pages_by_path = {page.relative_path: page for page in wiki_export.pages}
    total = 0
    supported = 0
    for page_path in page_paths:
        page = pages_by_path.get(page_path)
        if page is None:
            continue
        sources = page.frontmatter.get("sources")
        if not isinstance(sources, list):
            continue
        for source in sources:
            if not isinstance(source, dict):
                continue
            total += 1
            if all(
                str(source.get(key) or "")
                for key in (
                    "source_type",
                    "source_id",
                    "source_hash",
                    "evidence_snippet",
                )
            ):
                supported += 1
    if total <= 0:
        return 1.0
    return round(supported / total, 4)
