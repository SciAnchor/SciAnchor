"""Private Research Wiki graph insight helpers.

The functions in this module score evidence-bound page connections from the
local Research Wiki projection. They do not write storage rows or expose a
public transport surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .research_wiki import ResearchWikiExport, ResearchWikiPage


@dataclass(frozen=True)
class ResearchWikiEvidenceAnchor:
    page_path: str
    paper_id: int | None
    source_type: str
    source_id: str
    source_hash: str
    section_anchor: str
    evidence_snippet: str

    @property
    def source_key(self) -> tuple[str, str, str, str]:
        return (
            self.source_type,
            self.source_id,
            self.source_hash,
            self.section_anchor,
        )

    @property
    def source_family_key(self) -> tuple[str, str, str]:
        return (
            self.source_type,
            self.source_id,
            self.source_hash,
        )


@dataclass(frozen=True)
class ResearchWikiInsight:
    insight_type: str
    source_page: str
    target_page: str
    score: float
    rationale: str
    bridge_pages: tuple[str, ...]
    evidence: tuple[ResearchWikiEvidenceAnchor, ...]


@dataclass(frozen=True)
class ResearchWikiInsightReport:
    topic_id: int
    insights: tuple[ResearchWikiInsight, ...]


def research_wiki_insight_report_to_dict(
    report: ResearchWikiInsightReport,
) -> dict[str, Any]:
    """Serialize a Research Wiki insight report into deterministic plain data."""

    insights: list[dict[str, Any]] = []
    for rank, insight in enumerate(report.insights, start=1):
        insights.append(
            {
                "rank": rank,
                "insight_type": insight.insight_type,
                "score": insight.score,
                "source_page": insight.source_page,
                "target_page": insight.target_page,
                "bridge_pages": list(insight.bridge_pages),
                "rationale": insight.rationale,
                "evidence": [
                    _evidence_anchor_to_dict(anchor) for anchor in insight.evidence
                ],
            }
        )
    return {
        "topic_id": report.topic_id,
        "insight_count": len(report.insights),
        "insights": insights,
    }


def render_research_wiki_insight_report_markdown(
    report: ResearchWikiInsightReport,
) -> str:
    """Render a deterministic Markdown summary for private wiki bundles."""

    data = research_wiki_insight_report_to_dict(report)
    lines = [
        "# Research Wiki Insights",
        "",
        f"- Topic id: {data['topic_id']}",
        f"- Insight count: {data['insight_count']}",
        "",
    ]
    if not data["insights"]:
        lines.extend(["- none", ""])
        return "\n".join(lines).rstrip() + "\n"

    for insight in data["insights"]:
        lines.extend(
            [
                f"## {insight['rank']}. {insight['insight_type']}",
                "",
                f"- Score: {insight['score']:.2f}",
                (
                    f"- Page pair: `{insight['source_page']}` -> "
                    f"`{insight['target_page']}`"
                ),
                f"- Bridge pages: {_format_bridge_pages(insight['bridge_pages'])}",
                f"- Rationale: {insight['rationale']}",
                "",
                "### Evidence Anchors",
                "",
            ]
        )
        evidence = insight["evidence"]
        if not evidence:
            lines.extend(["- none", ""])
            continue
        for anchor in evidence:
            lines.append(f"- {_format_evidence_anchor(anchor)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def find_research_wiki_insights(
    export: ResearchWikiExport,
    *,
    max_results: int = 20,
) -> ResearchWikiInsightReport:
    """Return deterministic, evidence-bound Research Wiki graph insights."""

    pages = {page.relative_path: page for page in export.pages}
    page_anchors = {
        page.relative_path: _page_evidence_anchors(page) for page in export.pages
    }
    source_pages = _source_pages(page_anchors)
    source_family_pages = _source_family_pages(page_anchors)

    insights: dict[tuple[str, str, str, tuple[str, ...]], ResearchWikiInsight] = {}
    for insight in _shared_source_anchor_insights(
        pages=pages,
        page_anchors=page_anchors,
        source_pages=source_pages,
        graph=export.graph,
    ):
        _keep_best(insights, insight)
    for insight in _shared_evaluation_context_insights(
        pages=pages,
        page_anchors=page_anchors,
        source_pages=source_pages,
        source_family_pages=source_family_pages,
        graph=export.graph,
    ):
        _keep_best(insights, insight)

    ranked = sorted(
        insights.values(),
        key=lambda item: (
            -item.score,
            item.source_page,
            item.target_page,
            item.insight_type,
        ),
    )
    return ResearchWikiInsightReport(
        topic_id=export.topic_id,
        insights=tuple(ranked[: max(0, int(max_results))]),
    )


def _evidence_anchor_to_dict(anchor: ResearchWikiEvidenceAnchor) -> dict[str, Any]:
    return {
        "page_path": anchor.page_path,
        "paper_id": anchor.paper_id,
        "source_type": anchor.source_type,
        "source_id": anchor.source_id,
        "source_hash": anchor.source_hash,
        "section_anchor": anchor.section_anchor,
        "evidence_snippet": anchor.evidence_snippet,
    }


def _format_bridge_pages(bridge_pages: list[str]) -> str:
    if not bridge_pages:
        return "none"
    return ", ".join(f"`{page}`" for page in bridge_pages)


def _format_evidence_anchor(anchor: dict[str, Any]) -> str:
    source = f"{anchor['source_type']}:{anchor['source_id']}"
    section = str(anchor.get("section_anchor") or "")
    if section:
        source = f"{source}#{section}"
    paper = anchor.get("paper_id")
    paper_label = f"paper {paper}" if paper is not None else "no paper"
    return (
        f"`{anchor['page_path']}` {source} "
        f"({paper_label}, hash {anchor['source_hash']}): "
        f"{anchor['evidence_snippet']}"
    )


def _shared_source_anchor_insights(
    *,
    pages: dict[str, ResearchWikiPage],
    page_anchors: dict[str, tuple[ResearchWikiEvidenceAnchor, ...]],
    source_pages: dict[tuple[str, str, str, str], set[str]],
    graph: dict[str, list[str]],
) -> list[ResearchWikiInsight]:
    insights: list[ResearchWikiInsight] = []
    for source_key, page_paths in sorted(source_pages.items()):
        if len(page_paths) < 2:
            continue
        ordered = sorted(page_paths)
        for index, source_page in enumerate(ordered):
            for target_page in ordered[index + 1 :]:
                if _directly_linked(source_page, target_page, graph):
                    continue
                evidence = _shared_evidence(
                    source_page,
                    target_page,
                    page_anchors,
                    source_key=source_key,
                )
                if not evidence:
                    continue
                source_title = pages[source_page].title
                target_title = pages[target_page].title
                insights.append(
                    ResearchWikiInsight(
                        insight_type="shared_source_anchor",
                        source_page=source_page,
                        target_page=target_page,
                        score=round(0.72 + min(len(evidence), 5) * 0.02, 2),
                        rationale=(
                            f"{source_title} and {target_title} share the same "
                            "RH source anchor without a direct wiki edge."
                        ),
                        bridge_pages=(),
                        evidence=evidence,
                    )
                )
    return insights


def _shared_evaluation_context_insights(
    *,
    pages: dict[str, ResearchWikiPage],
    page_anchors: dict[str, tuple[ResearchWikiEvidenceAnchor, ...]],
    source_pages: dict[tuple[str, str, str, str], set[str]],
    source_family_pages: dict[tuple[str, str, str], set[str]],
    graph: dict[str, list[str]],
) -> list[ResearchWikiInsight]:
    method_pages = sorted(
        path for path, page in pages.items() if page.page_type == "methodology"
    )
    page_contexts = {
        page_path: _inferred_concept_contexts(
            page_path,
            page_anchors=page_anchors,
            source_pages=source_pages,
            source_family_pages=source_family_pages,
            graph=graph,
        )
        for page_path in method_pages
    }

    insights: list[ResearchWikiInsight] = []
    for index, source_page in enumerate(method_pages):
        for target_page in method_pages[index + 1 :]:
            bridge_pages = tuple(
                sorted(page_contexts[source_page] & page_contexts[target_page])
            )
            if not bridge_pages:
                continue
            evidence = _page_pair_evidence(source_page, target_page, page_anchors)
            if not evidence:
                continue
            insights.append(
                ResearchWikiInsight(
                    insight_type="shared_evaluation_context",
                    source_page=source_page,
                    target_page=target_page,
                    score=round(min(0.95, 0.78 + len(bridge_pages) * 0.03), 2),
                    rationale=(
                        f"{pages[source_page].title} and {pages[target_page].title} "
                        "are not directly linked but share evidence-bound concept context."
                    ),
                    bridge_pages=bridge_pages,
                    evidence=evidence,
                )
            )
    return insights


def _inferred_concept_contexts(
    page_path: str,
    *,
    page_anchors: dict[str, tuple[ResearchWikiEvidenceAnchor, ...]],
    source_pages: dict[tuple[str, str, str, str], set[str]],
    source_family_pages: dict[tuple[str, str, str], set[str]],
    graph: dict[str, list[str]],
) -> set[str]:
    contexts: set[str] = set()
    for anchor in page_anchors.get(page_path, ()):
        for sibling_page in source_pages.get(anchor.source_key, set()):
            for linked_page in graph.get(sibling_page, []):
                if linked_page.startswith("concepts/"):
                    contexts.add(linked_page)
        for family_page in source_family_pages.get(anchor.source_family_key, set()):
            if family_page.startswith("concepts/"):
                contexts.add(family_page)
            for linked_page in graph.get(family_page, []):
                if linked_page.startswith("concepts/"):
                    contexts.add(linked_page)
    return contexts


def _page_evidence_anchors(
    page: ResearchWikiPage,
) -> tuple[ResearchWikiEvidenceAnchor, ...]:
    sources = page.frontmatter.get("sources")
    if not isinstance(sources, list):
        return ()
    anchors: list[ResearchWikiEvidenceAnchor] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        source_type = str(source.get("source_type") or "")
        source_id = str(source.get("source_id") or "")
        source_hash = str(source.get("source_hash") or "")
        evidence_snippet = str(source.get("evidence_snippet") or "")
        if not source_type or not source_id or not source_hash or not evidence_snippet:
            continue
        paper_id = source.get("paper_id")
        anchors.append(
            ResearchWikiEvidenceAnchor(
                page_path=page.relative_path,
                paper_id=int(paper_id) if isinstance(paper_id, int) else None,
                source_type=source_type,
                source_id=source_id,
                source_hash=source_hash,
                section_anchor=str(source.get("section_anchor") or ""),
                evidence_snippet=evidence_snippet,
            )
        )
    return tuple(
        sorted(
            anchors,
            key=lambda anchor: (
                anchor.page_path,
                anchor.source_type,
                anchor.source_id,
                anchor.source_hash,
                anchor.section_anchor,
                anchor.evidence_snippet,
            ),
        )
    )


def _source_pages(
    page_anchors: dict[str, tuple[ResearchWikiEvidenceAnchor, ...]],
) -> dict[tuple[str, str, str, str], set[str]]:
    source_pages: dict[tuple[str, str, str, str], set[str]] = {}
    for page_path, anchors in page_anchors.items():
        for anchor in anchors:
            source_pages.setdefault(anchor.source_key, set()).add(page_path)
    return source_pages


def _source_family_pages(
    page_anchors: dict[str, tuple[ResearchWikiEvidenceAnchor, ...]],
) -> dict[tuple[str, str, str], set[str]]:
    source_pages: dict[tuple[str, str, str], set[str]] = {}
    for page_path, anchors in page_anchors.items():
        for anchor in anchors:
            source_pages.setdefault(anchor.source_family_key, set()).add(page_path)
    return source_pages


def _shared_evidence(
    source_page: str,
    target_page: str,
    page_anchors: dict[str, tuple[ResearchWikiEvidenceAnchor, ...]],
    *,
    source_key: tuple[str, str, str, str],
) -> tuple[ResearchWikiEvidenceAnchor, ...]:
    anchors = [
        anchor
        for anchor in page_anchors.get(source_page, ())
        + page_anchors.get(target_page, ())
        if anchor.source_key == source_key
    ]
    return _dedupe_anchors(anchors)


def _page_pair_evidence(
    source_page: str,
    target_page: str,
    page_anchors: dict[str, tuple[ResearchWikiEvidenceAnchor, ...]],
) -> tuple[ResearchWikiEvidenceAnchor, ...]:
    return _dedupe_anchors(
        [*page_anchors.get(source_page, ()), *page_anchors.get(target_page, ())]
    )


def _dedupe_anchors(
    anchors: list[ResearchWikiEvidenceAnchor],
) -> tuple[ResearchWikiEvidenceAnchor, ...]:
    by_key: dict[tuple[object, ...], ResearchWikiEvidenceAnchor] = {}
    ordered = sorted(
        anchors,
        key=lambda anchor: (
            anchor.paper_id,
            anchor.source_type,
            anchor.source_id,
            anchor.source_hash,
            anchor.section_anchor,
            anchor.evidence_snippet,
            anchor.page_path,
        ),
    )
    for anchor in ordered:
        key = (
            anchor.paper_id,
            anchor.source_type,
            anchor.source_id,
            anchor.source_hash,
            anchor.section_anchor,
            anchor.evidence_snippet,
        )
        by_key.setdefault(key, anchor)
    return tuple(
        by_key[key] for key in sorted(by_key, key=lambda item: tuple(map(str, item)))
    )


def _directly_linked(
    source_page: str, target_page: str, graph: dict[str, list[str]]
) -> bool:
    return target_page in set(graph.get(source_page, [])) or source_page in set(
        graph.get(target_page, [])
    )


def _keep_best(
    insights: dict[tuple[str, str, str, tuple[str, ...]], ResearchWikiInsight],
    insight: ResearchWikiInsight,
) -> None:
    key = (
        insight.insight_type,
        insight.source_page,
        insight.target_page,
        insight.bridge_pages,
    )
    current = insights.get(key)
    if current is None or insight.score > current.score:
        insights[key] = insight
