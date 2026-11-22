"""Deterministic, survey-authoritative analysis view over Research Wiki pages."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from research_harness.primitives.types import (
    AnalysisSubstrateAgenda,
    AnalysisSubstrateAuthority,
    AnalysisSubstrateCluster,
    AnalysisSubstrateComparisonTable,
    AnalysisSubstrateGuidedQuestion,
    AnalysisSubstrateOutput,
    AnalysisSubstrateRelation,
)

from .research_wiki import ResearchWikiExport
from .research_wiki_insights import ResearchWikiEvidenceAnchor
from .wiki_context_pack import WikiContextPack, WikiContextPage


ANALYSIS_SUBSTRATE_SCHEMA_VERSION = "analysis_substrate.v1"
_RELATION_TYPES = frozenset(
    {"foundation", "extension", "alternative", "complementarity"}
)
_AGENDA_PAGE_TYPES = frozenset({"methodology", "concept", "thesis"})


def build_analysis_substrate(
    *,
    context_pack: WikiContextPack,
    wiki_export: ResearchWikiExport,
    survey_paper_ids: set[int],
    max_clusters: int = 8,
    max_relations: int = 24,
) -> AnalysisSubstrateOutput:
    """Compile an evidence-bound view; only explicit survey papers define axes."""

    pages = {page.page_path: page for page in context_pack.pages}
    survey_pages = tuple(
        page
        for page in context_pack.pages
        if _has_exclusive_survey_authority(page, survey_paper_ids)
    )[:max_clusters]
    capsule_pages = tuple(
        page for page in context_pack.pages if page not in survey_pages
    )
    authority = AnalysisSubstrateAuthority(
        survey_pages=tuple(page.page_path for page in survey_pages),
        supporting_capsule_pages=tuple(page.page_path for page in capsule_pages),
    )
    warning_codes = tuple(
        dict.fromkeys(warning.code for warning in context_pack.warnings)
    )
    if not survey_pages:
        return AnalysisSubstrateOutput(
            schema_version=ANALYSIS_SUBSTRATE_SCHEMA_VERSION,
            topic_id=context_pack.topic_id,
            agenda=AnalysisSubstrateAgenda(),
            authority_hierarchy=authority,
            warnings=(*warning_codes, "survey_authority_unavailable"),
            degraded=True,
            truncated=context_pack.truncated,
        )

    clusters = tuple(
        _build_cluster(index, page, pages, wiki_export.graph)
        for index, page in enumerate(survey_pages, start=1)
    )
    relations = _build_relations(clusters, wiki_export.graph, max_relations)
    tables = _build_comparison_tables(clusters)
    questions = _build_guided_questions(relations)
    return AnalysisSubstrateOutput(
        schema_version=ANALYSIS_SUBSTRATE_SCHEMA_VERSION,
        topic_id=context_pack.topic_id,
        agenda=AnalysisSubstrateAgenda(
            main_problem_axis=survey_pages[0].title,
            survey_derived=True,
            supporting_page_paths=tuple(page.page_path for page in survey_pages),
            evidence_anchors=_anchor_dicts(
                anchor for page in survey_pages for anchor in page.evidence_anchors
            ),
        ),
        authority_hierarchy=authority,
        clusters=clusters,
        relation_graph=relations,
        comparison_tables=tables,
        guided_questions=questions,
        warnings=warning_codes,
        degraded=context_pack.degraded,
        truncated=context_pack.truncated
        or len(survey_pages)
        < len(
            {
                page.page_path
                for page in context_pack.pages
                if _has_exclusive_survey_authority(page, survey_paper_ids)
            }
        ),
    )


def analysis_substrate_to_dict(substrate: AnalysisSubstrateOutput) -> dict[str, Any]:
    """Serialize the frozen contract to JSON-safe plain data."""

    return _plain(asdict(substrate))


def _has_exclusive_survey_authority(
    page: WikiContextPage,
    survey_paper_ids: set[int],
) -> bool:
    paper_ids = {anchor.paper_id for anchor in page.evidence_anchors}
    return (
        page.page_type in _AGENDA_PAGE_TYPES
        and bool(paper_ids)
        and None not in paper_ids
        and paper_ids <= survey_paper_ids
    )


def _build_cluster(
    index: int,
    survey_page: WikiContextPage,
    pages: dict[str, WikiContextPage],
    graph: dict[str, list[str]],
) -> AnalysisSubstrateCluster:
    neighbor_paths = {
        *graph.get(survey_page.page_path, []),
        *(
            source
            for source, targets in graph.items()
            if survey_page.page_path in targets
        ),
    }
    members = (survey_page.page_path,) + tuple(
        path
        for path in sorted(neighbor_paths)
        if path in pages and path != survey_page.page_path
    )
    member_pages = tuple(pages[path] for path in members)
    return AnalysisSubstrateCluster(
        cluster_id=f"cluster-{index}",
        label=survey_page.title,
        summary=survey_page.excerpt,
        member_page_paths=members,
        paper_ids=tuple(
            sorted(
                {
                    anchor.paper_id
                    for page in member_pages
                    for anchor in page.evidence_anchors
                    if anchor.paper_id is not None
                }
            )
        ),
        evidence_anchors=_anchor_dicts(
            anchor for page in member_pages for anchor in page.evidence_anchors
        ),
    )


def _build_relations(
    clusters: tuple[AnalysisSubstrateCluster, ...],
    graph: dict[str, list[str]],
    limit: int,
) -> tuple[AnalysisSubstrateRelation, ...]:
    relations: list[AnalysisSubstrateRelation] = []
    for index, source in enumerate(clusters):
        for target in clusters[index + 1 :]:
            shared = set(source.member_page_paths) & set(target.member_page_paths)
            directly_linked = any(
                target_path in graph.get(source_path, [])
                or source_path in graph.get(target_path, [])
                for source_path in source.member_page_paths
                for target_path in target.member_page_paths
            )
            if not shared and not directly_linked:
                continue
            relation_type = "complementarity"
            if relation_type not in _RELATION_TYPES:
                raise ValueError(f"unsupported relation type: {relation_type}")
            relations.append(
                AnalysisSubstrateRelation(
                    source_cluster_id=source.cluster_id,
                    target_cluster_id=target.cluster_id,
                    relation_type=relation_type,
                    rationale="Survey-defined axes share supporting evidence or a wiki link.",
                    evidence_anchors=_merge_anchor_dicts(
                        source.evidence_anchors, target.evidence_anchors
                    ),
                )
            )
            if len(relations) >= limit:
                return tuple(relations)
    return tuple(relations)


def _build_comparison_tables(
    clusters: tuple[AnalysisSubstrateCluster, ...],
) -> tuple[AnalysisSubstrateComparisonTable, ...]:
    if len(clusters) < 2:
        return ()
    return (
        AnalysisSubstrateComparisonTable(
            table_id="cluster-comparison-1",
            title="Survey-defined analysis axes",
            rows=tuple(
                {
                    "cluster_id": cluster.cluster_id,
                    "label": cluster.label,
                    "summary": cluster.summary,
                    "evidence_anchors": cluster.evidence_anchors,
                }
                for cluster in clusters
            ),
        ),
    )


def _build_guided_questions(
    relations: tuple[AnalysisSubstrateRelation, ...],
) -> tuple[AnalysisSubstrateGuidedQuestion, ...]:
    return tuple(
        AnalysisSubstrateGuidedQuestion(
            question=(
                f"How should {relation.source_cluster_id} and "
                f"{relation.target_cluster_id} be evaluated together?"
            ),
            intent="surface unresolved mechanism or evaluation interactions",
            supporting_cluster_ids=(
                relation.source_cluster_id,
                relation.target_cluster_id,
            ),
            evidence_anchors=relation.evidence_anchors,
        )
        for relation in relations
    )


def _anchor_dicts(
    anchors: Any,
) -> tuple[dict[str, Any], ...]:
    unique: dict[tuple[str, str, str, str], ResearchWikiEvidenceAnchor] = {}
    for anchor in anchors:
        unique.setdefault(anchor.source_key, anchor)
    return tuple(asdict(anchor) for anchor in unique.values())


def _merge_anchor_dicts(
    *groups: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    unique: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for anchor in (anchor for group in groups for anchor in group):
        key = tuple(
            str(anchor.get(name, ""))
            for name in ("source_type", "source_id", "source_hash", "section_anchor")
        )
        unique.setdefault(key, anchor)
    return tuple(unique.values())


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value
