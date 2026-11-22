"""Private in-memory Cross-Topic Knowledge Atlas helpers.

This module derives rebuildable serendipity links from caller-provided Topic
Knowledge snapshots and optional Research Wiki exports. It does not read or
write storage and does not register any public transport surface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Iterable

from research_harness.storage.db import Database

from .research_wiki import ResearchWikiExport, build_research_wiki_export
from .topic_layer import TopicKnowledgeSnapshot, get_latest_topic_knowledge_snapshot


CROSS_TOPIC_KNOWLEDGE_ATLAS_SCHEMA_VERSION = "cross_topic_knowledge_atlas.v1"
CROSS_TOPIC_LINK_TYPES: tuple[str, ...] = (
    "method_transfers_to_gap",
    "shared_failure_mode",
    "metric_or_dataset_bridge",
    "claim_conflict_across_topics",
    "abstraction_match",
    "baseline_migration",
)

_TERM_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}
_ABSTRACTION_TERMS: dict[str, tuple[str, ...]] = {
    "budget_control": (
        "allocate",
        "allocation",
        "budget",
        "cap",
        "caps",
        "context",
        "limit",
        "limits",
        "pacing",
        "quota",
        "schedule",
        "scheduling",
        "spend",
        "token",
    ),
    "provenance_control": (
        "audit",
        "checkpoint",
        "checkpoints",
        "drift",
        "evidence",
        "hash",
        "hashes",
        "ledger",
        "ledgers",
        "lineage",
        "provenance",
        "source",
        "trace",
    ),
    "evaluation_bridge": (
        "benchmark",
        "baseline",
        "baselines",
        "dataset",
        "datasets",
        "evaluation",
        "metric",
        "metrics",
        "precision",
        "recall",
    ),
    "failure_mode": (
        "degraded",
        "drift",
        "failure",
        "missing",
        "stale",
        "unresolved",
        "weak",
    ),
}


@dataclass(frozen=True)
class CrossTopicEvidenceAnchor:
    topic_id: int
    page_path: str
    source_type: str
    source_id: str
    source_hash: str
    evidence_snippet: str


@dataclass(frozen=True)
class CrossTopicKnowledgeLink:
    link_type: str
    source_topic_id: int
    target_topic_id: int
    score: float
    source_label: str
    target_label: str
    explanation: str
    evidence_summary: tuple[str, ...]
    source_ids: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CrossTopicKnowledgeAtlas:
    schema_version: str
    topic_ids: tuple[int, ...]
    links: tuple[CrossTopicKnowledgeLink, ...]
    warnings: tuple[str, ...] = ()


class CrossTopicAtlasUnavailable(RuntimeError):
    code = "cross_topic_atlas_unavailable"

    def __init__(self, topic_ids: tuple[int, ...]):
        self.topic_ids = topic_ids
        topic_list = ", ".join(str(topic_id) for topic_id in topic_ids)
        self.public_message = (
            f"cross-topic atlas is unavailable for topic ids: {topic_list}"
        )
        super().__init__(self.public_message)


@dataclass(frozen=True)
class _TopicProfile:
    topic_id: int
    snapshot: TopicKnowledgeSnapshot
    covered: dict[str, tuple[str, ...]]
    coverage: dict[str, Any]
    anchors: tuple[CrossTopicEvidenceAnchor, ...]
    abstractions: tuple[str, ...]
    evidence_strength: float

    @property
    def methods(self) -> tuple[str, ...]:
        return self.covered.get("methods", ())

    @property
    def gaps(self) -> tuple[str, ...]:
        payload_gaps = self.covered.get("gaps", ())
        state = self.snapshot.payload.get("research_state")
        if not isinstance(state, dict):
            return payload_gaps
        state_gaps = _text_tuple(state.get("open_gaps"))
        return _dedupe_text((*payload_gaps, *state_gaps))

    @property
    def claims(self) -> tuple[str, ...]:
        payload_claims = self.covered.get("claims", ())
        state = self.snapshot.payload.get("research_state")
        if not isinstance(state, dict):
            return payload_claims
        state_claims = _text_tuple(state.get("high_confidence_claims"))
        return _dedupe_text((*payload_claims, *state_claims))

    @property
    def datasets(self) -> tuple[str, ...]:
        return self.covered.get("datasets", ())

    @property
    def metrics(self) -> tuple[str, ...]:
        return self.covered.get("metrics", ())

    @property
    def baselines(self) -> tuple[str, ...]:
        return self.covered.get("baselines", ())

    @property
    def tasks(self) -> tuple[str, ...]:
        return self.covered.get("tasks", ())


def build_cross_topic_knowledge_atlas(
    snapshots: Iterable[TopicKnowledgeSnapshot],
    *,
    wiki_exports: Iterable[ResearchWikiExport] | None = None,
    max_links: int = 20,
) -> CrossTopicKnowledgeAtlas:
    """Build a private deterministic atlas from in-memory topic snapshots."""

    snapshot_tuple = tuple(
        snapshot
        for snapshot in snapshots
        if isinstance(snapshot, TopicKnowledgeSnapshot)
    )
    profiles = _profiles(snapshot_tuple, tuple(wiki_exports or ()))
    topic_ids = tuple(profile.topic_id for profile in profiles)
    if len(topic_ids) < 2 or max_links <= 0:
        return CrossTopicKnowledgeAtlas(
            schema_version=CROSS_TOPIC_KNOWLEDGE_ATLAS_SCHEMA_VERSION,
            topic_ids=topic_ids,
            links=(),
            warnings=(),
        )

    links = [
        *_method_transfer_links(profiles),
        *_shared_failure_links(profiles),
        *_metric_or_dataset_links(profiles),
        *_claim_conflict_links(profiles),
        *_abstraction_match_links(profiles),
        *_baseline_migration_links(profiles),
    ]
    ranked = sorted(
        _dedupe_links(links),
        key=lambda link: (
            -link.score,
            link.link_type,
            link.source_topic_id,
            link.target_topic_id,
            link.source_label,
            link.target_label,
        ),
    )
    return CrossTopicKnowledgeAtlas(
        schema_version=CROSS_TOPIC_KNOWLEDGE_ATLAS_SCHEMA_VERSION,
        topic_ids=topic_ids,
        links=tuple(ranked[: max(0, int(max_links))]),
        warnings=(),
    )


def rank_cross_topic_serendipity_links(
    atlas: CrossTopicKnowledgeAtlas,
    query: str | None = None,
    *,
    max_results: int = 10,
) -> tuple[CrossTopicKnowledgeLink, ...]:
    """Return atlas links ranked for optional query relevance."""

    query_terms = _terms(query or "")
    ranked = sorted(
        atlas.links,
        key=lambda link: (
            -_query_adjusted_score(link, query_terms),
            -link.score,
            link.link_type,
            link.source_topic_id,
            link.target_topic_id,
            link.source_label,
            link.target_label,
        ),
    )
    return tuple(ranked[: max(0, int(max_results))])


def cross_topic_knowledge_atlas_to_dict(
    atlas: CrossTopicKnowledgeAtlas,
) -> dict[str, Any]:
    """Serialize the private atlas into deterministic plain data."""

    return {
        "schema_version": atlas.schema_version,
        "topic_ids": list(atlas.topic_ids),
        "link_count": len(atlas.links),
        "warnings": list(atlas.warnings),
        "links": [
            {
                "rank": index,
                "link_type": link.link_type,
                "source_topic_id": link.source_topic_id,
                "target_topic_id": link.target_topic_id,
                "score": link.score,
                "source_label": link.source_label,
                "target_label": link.target_label,
                "explanation": link.explanation,
                "evidence_summary": list(link.evidence_summary),
                "source_ids": list(link.source_ids),
                "warnings": list(link.warnings),
                "metadata": dict(link.metadata),
            }
            for index, link in enumerate(atlas.links, start=1)
        ],
    }


def build_cross_topic_knowledge_atlas_payload_from_db(
    db: Database,
    *,
    topic_ids: tuple[int, ...],
    query: str = "",
    max_links: int = 20,
    max_results: int = 10,
) -> dict[str, Any]:
    """Build public-safe local CLI payload from existing snapshots only."""

    snapshots: list[TopicKnowledgeSnapshot] = []
    missing_topic_ids: list[int] = []
    for topic_id in topic_ids:
        snapshot = get_latest_topic_knowledge_snapshot(
            db,
            topic_id,
            require_current=False,
        )
        if snapshot is None:
            missing_topic_ids.append(topic_id)
            continue
        snapshots.append(snapshot)
    if missing_topic_ids:
        raise CrossTopicAtlasUnavailable(tuple(missing_topic_ids))

    wiki_exports = tuple(
        build_research_wiki_export(
            db,
            snapshot.topic_id,
            require_current=False,
        )
        for snapshot in snapshots
    )
    atlas = build_cross_topic_knowledge_atlas(
        tuple(snapshots),
        wiki_exports=wiki_exports,
        max_links=max(max_links, max_results),
    )
    ranked_links = rank_cross_topic_serendipity_links(
        atlas,
        query=query,
        max_results=max_results,
    )
    payload_atlas = CrossTopicKnowledgeAtlas(
        schema_version=atlas.schema_version,
        topic_ids=atlas.topic_ids,
        links=ranked_links,
        warnings=atlas.warnings,
    )
    payload = cross_topic_knowledge_atlas_to_dict(payload_atlas)
    payload["query"] = query
    return payload


def _profiles(
    snapshots: tuple[TopicKnowledgeSnapshot, ...],
    wiki_exports: tuple[ResearchWikiExport, ...],
) -> tuple[_TopicProfile, ...]:
    exports_by_topic = {
        export.topic_id: export
        for export in wiki_exports
        if isinstance(export, ResearchWikiExport)
    }
    profiles: list[_TopicProfile] = []
    seen_topic_ids: set[int] = set()
    for snapshot in snapshots:
        if snapshot.topic_id in seen_topic_ids:
            continue
        seen_topic_ids.add(snapshot.topic_id)
        covered = _covered_values(snapshot)
        anchors = _wiki_anchors(exports_by_topic.get(snapshot.topic_id))
        abstractions = _abstractions_for_values(
            value for values in covered.values() for value in values
        )
        evidence_strength = _evidence_strength(snapshot, anchors)
        profiles.append(
            _TopicProfile(
                topic_id=snapshot.topic_id,
                snapshot=snapshot,
                covered=covered,
                coverage=dict(snapshot.coverage or {}),
                anchors=anchors,
                abstractions=abstractions,
                evidence_strength=evidence_strength,
            )
        )
    return tuple(profiles)


def _method_transfer_links(
    profiles: tuple[_TopicProfile, ...],
) -> list[CrossTopicKnowledgeLink]:
    links: list[CrossTopicKnowledgeLink] = []
    for source in profiles:
        for target in profiles:
            if source.topic_id == target.topic_id:
                continue
            for method in source.methods:
                for gap in target.gaps:
                    shared_abstractions = _shared_abstractions(method, gap)
                    lexical_overlap = _lexical_overlap(method, gap)
                    incompatible = _task_incompatible(
                        source,
                        target,
                        shared_abstractions=shared_abstractions,
                        lexical_overlap=lexical_overlap,
                    )
                    links.append(
                        _link(
                            link_type="method_transfers_to_gap",
                            source=source,
                            target=target,
                            source_label=method,
                            target_label=gap,
                            base_score=0.46,
                            shared_abstractions=shared_abstractions,
                            lexical_overlap=lexical_overlap,
                            incompatible=incompatible,
                            explanation=(
                                f"Method '{method}' from topic {source.topic_id} "
                                f"may address gap '{gap}' in topic {target.topic_id}."
                            ),
                        )
                    )
    return links


def _shared_failure_links(
    profiles: tuple[_TopicProfile, ...],
) -> list[CrossTopicKnowledgeLink]:
    links: list[CrossTopicKnowledgeLink] = []
    for source, target in _profile_pairs(profiles):
        source_failures = _failure_labels(source)
        target_failures = _failure_labels(target)
        for source_label in source_failures:
            for target_label in target_failures:
                shared_abstractions = tuple(
                    abstraction
                    for abstraction in _shared_abstractions(source_label, target_label)
                    if abstraction == "failure_mode"
                )
                if not shared_abstractions:
                    continue
                links.append(
                    _link(
                        link_type="shared_failure_mode",
                        source=source,
                        target=target,
                        source_label=source_label,
                        target_label=target_label,
                        base_score=0.42,
                        shared_abstractions=shared_abstractions,
                        lexical_overlap=_lexical_overlap(source_label, target_label),
                        incompatible=False,
                        explanation=(
                            f"Topics {source.topic_id} and {target.topic_id} share "
                            f"failure mode '{shared_abstractions[0]}'."
                        ),
                    )
                )
    return links


def _metric_or_dataset_links(
    profiles: tuple[_TopicProfile, ...],
) -> list[CrossTopicKnowledgeLink]:
    links: list[CrossTopicKnowledgeLink] = []
    for source, target in _profile_pairs(profiles):
        for source_label in (*source.datasets, *source.metrics):
            for target_label in (*target.datasets, *target.metrics):
                lexical_overlap = _lexical_overlap(source_label, target_label)
                shared_abstractions = _shared_abstractions(source_label, target_label)
                if (
                    lexical_overlap == 0.0
                    and "evaluation_bridge" not in shared_abstractions
                ):
                    continue
                links.append(
                    _link(
                        link_type="metric_or_dataset_bridge",
                        source=source,
                        target=target,
                        source_label=source_label,
                        target_label=target_label,
                        base_score=0.4,
                        shared_abstractions=shared_abstractions,
                        lexical_overlap=lexical_overlap,
                        incompatible=False,
                        explanation=(
                            f"Evaluation context '{source_label}' in topic "
                            f"{source.topic_id} may bridge to '{target_label}' "
                            f"in topic {target.topic_id}."
                        ),
                    )
                )
    return links


def _claim_conflict_links(
    profiles: tuple[_TopicProfile, ...],
) -> list[CrossTopicKnowledgeLink]:
    links: list[CrossTopicKnowledgeLink] = []
    for source, target in _profile_pairs(profiles):
        for source_claim in source.claims:
            for target_claim in target.claims:
                lexical_overlap = _lexical_overlap(source_claim, target_claim)
                if lexical_overlap < 0.2 or not _opposite_polarity(
                    source_claim, target_claim
                ):
                    continue
                links.append(
                    _link(
                        link_type="claim_conflict_across_topics",
                        source=source,
                        target=target,
                        source_label=source_claim,
                        target_label=target_claim,
                        base_score=0.5,
                        shared_abstractions=_shared_abstractions(
                            source_claim, target_claim
                        ),
                        lexical_overlap=lexical_overlap,
                        incompatible=False,
                        explanation=(
                            f"Claims in topics {source.topic_id} and "
                            f"{target.topic_id} appear to conflict."
                        ),
                    )
                )
    return links


def _abstraction_match_links(
    profiles: tuple[_TopicProfile, ...],
) -> list[CrossTopicKnowledgeLink]:
    links: list[CrossTopicKnowledgeLink] = []
    for source, target in _profile_pairs(profiles):
        shared = tuple(
            abstraction
            for abstraction in source.abstractions
            if abstraction in set(target.abstractions)
        )
        if not shared:
            continue
        source_label = _representative_label(source)
        target_label = _representative_label(target)
        links.append(
            _link(
                link_type="abstraction_match",
                source=source,
                target=target,
                source_label=source_label,
                target_label=target_label,
                base_score=0.34,
                shared_abstractions=shared,
                lexical_overlap=_lexical_overlap(source_label, target_label),
                incompatible=False,
                explanation=(
                    f"Topics {source.topic_id} and {target.topic_id} share "
                    f"abstraction(s) {', '.join(shared)} despite different wording."
                ),
            )
        )
    return links


def _baseline_migration_links(
    profiles: tuple[_TopicProfile, ...],
) -> list[CrossTopicKnowledgeLink]:
    links: list[CrossTopicKnowledgeLink] = []
    for source in profiles:
        if not source.baselines:
            continue
        for target in profiles:
            if source.topic_id == target.topic_id or target.baselines:
                continue
            target_labels = target.gaps or target.methods or target.claims
            for baseline in source.baselines:
                for target_label in target_labels:
                    links.append(
                        _link(
                            link_type="baseline_migration",
                            source=source,
                            target=target,
                            source_label=baseline,
                            target_label=target_label,
                            base_score=0.34,
                            shared_abstractions=_shared_abstractions(
                                baseline, target_label
                            ),
                            lexical_overlap=_lexical_overlap(baseline, target_label),
                            incompatible=False,
                            explanation=(
                                f"Baseline '{baseline}' from topic "
                                f"{source.topic_id} may seed baseline coverage "
                                f"for topic {target.topic_id}."
                            ),
                        )
                    )
    return links


def _link(
    *,
    link_type: str,
    source: _TopicProfile,
    target: _TopicProfile,
    source_label: str,
    target_label: str,
    base_score: float,
    shared_abstractions: tuple[str, ...],
    lexical_overlap: float,
    incompatible: bool,
    explanation: str,
) -> CrossTopicKnowledgeLink:
    score = base_score
    score += (source.evidence_strength + target.evidence_strength) / 2.0
    score += min(0.18, len(shared_abstractions) * 0.09)
    score += 0.07 if source.topic_id != target.topic_id else 0.0
    score += _novelty_bonus(
        lexical_overlap=lexical_overlap,
        shared_abstractions=shared_abstractions,
    )
    warnings = [
        warning
        for warning in (
            "source_snapshot_stale" if not source.snapshot.is_current else "",
            "target_snapshot_stale" if not target.snapshot.is_current else "",
        )
        if warning
    ]
    if incompatible:
        warnings.append("incompatible_task_context")
        score -= 0.32
        if lexical_overlap >= 0.35:
            warnings.append("lexical_overlap_without_transfer")
            score -= 0.22
    if not source.snapshot.is_current:
        score -= 0.18
    if not target.snapshot.is_current:
        score -= 0.18

    evidence = _evidence_summary(source, target, source_label, target_label)
    metadata = {
        "lexical_overlap": round(lexical_overlap, 3),
        "shared_abstractions": list(shared_abstractions),
    }
    return CrossTopicKnowledgeLink(
        link_type=link_type,
        source_topic_id=source.topic_id,
        target_topic_id=target.topic_id,
        score=round(max(0.0, min(score, 1.0)), 3),
        source_label=source_label,
        target_label=target_label,
        explanation=_explanation_with_abstractions(explanation, shared_abstractions),
        evidence_summary=tuple(item[0] for item in evidence),
        source_ids=tuple(item[1] for item in evidence),
        warnings=tuple(dict.fromkeys(warnings)),
        metadata=metadata,
    )


def _evidence_summary(
    source: _TopicProfile,
    target: _TopicProfile,
    source_label: str,
    target_label: str,
) -> tuple[tuple[str, str], ...]:
    source_evidence = _best_anchor_summary(source, source_label)
    target_evidence = _best_anchor_summary(target, target_label)
    return (source_evidence, target_evidence)


def _best_anchor_summary(
    profile: _TopicProfile,
    label: str,
) -> tuple[str, str]:
    label_terms = _terms(label)
    ranked = sorted(
        profile.anchors,
        key=lambda anchor: (
            -len(label_terms & _terms(anchor.evidence_snippet)),
            anchor.page_path,
            anchor.source_type,
            anchor.source_id,
        ),
    )
    if ranked:
        anchor = ranked[0]
        summary = (
            f"topic {profile.topic_id} `{anchor.page_path}` "
            f"{anchor.source_type}:{anchor.source_id}: "
            f"{_shorten(anchor.evidence_snippet)}"
        )
        source_id = f"{anchor.source_type}:{anchor.source_id}"
        return summary, source_id
    snapshot_ref = f"topic_knowledge_snapshot:{profile.snapshot.artifact_id}"
    return (
        f"topic {profile.topic_id} {snapshot_ref}: {_shorten(label)}",
        snapshot_ref,
    )


def _profiles_by_topic(
    profiles: tuple[_TopicProfile, ...],
) -> dict[int, _TopicProfile]:
    return {profile.topic_id: profile for profile in profiles}


def _profile_pairs(
    profiles: tuple[_TopicProfile, ...],
) -> Iterable[tuple[_TopicProfile, _TopicProfile]]:
    for index, source in enumerate(profiles):
        for target in profiles[index + 1 :]:
            yield source, target


def _covered_values(snapshot: TopicKnowledgeSnapshot) -> dict[str, tuple[str, ...]]:
    raw = snapshot.payload.get("covered")
    covered = raw if isinstance(raw, dict) else {}
    return {
        key: _text_tuple(value) for key, value in covered.items() if _text_tuple(value)
    }


def _wiki_anchors(
    export: ResearchWikiExport | None,
) -> tuple[CrossTopicEvidenceAnchor, ...]:
    if export is None:
        return ()
    anchors: list[CrossTopicEvidenceAnchor] = []
    for page in export.pages:
        sources = page.frontmatter.get("sources")
        if not isinstance(sources, list):
            continue
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
                CrossTopicEvidenceAnchor(
                    topic_id=export.topic_id,
                    page_path=page.relative_path,
                    source_type=source_type,
                    source_id=source_id,
                    source_hash=source_hash,
                    evidence_snippet=snippet,
                )
            )
    return tuple(
        sorted(
            anchors,
            key=lambda anchor: (
                anchor.topic_id,
                anchor.page_path,
                anchor.source_type,
                anchor.source_id,
                anchor.source_hash,
            ),
        )
    )


def _evidence_strength(
    snapshot: TopicKnowledgeSnapshot,
    anchors: tuple[CrossTopicEvidenceAnchor, ...],
) -> float:
    coverage = snapshot.coverage or {}
    semantic_atoms = _int(coverage.get("semantic_atoms"))
    claims = _int(coverage.get("normalized_claims"))
    gaps = _int(coverage.get("gaps"))
    cards = _int(coverage.get("paper_cards") or coverage.get("paper_artifacts"))
    score = 0.0
    score += min(semantic_atoms, 8) * 0.01
    score += min(claims + gaps, 4) * 0.02
    score += min(cards, 2) * 0.015
    score += min(len(anchors), 3) * 0.035
    return round(min(score, 0.24), 3)


def _failure_labels(profile: _TopicProfile) -> tuple[str, ...]:
    labels = [
        label
        for label in (*profile.gaps, *profile.claims)
        if "failure_mode" in _abstractions_for_values((label,))
    ]
    weak_spots = profile.snapshot.payload.get("weak_spots")
    if isinstance(weak_spots, dict):
        labels.extend(
            key
            for key, value in weak_spots.items()
            if value and "failure_mode" in _abstractions_for_values((key,))
        )
    return _dedupe_text(tuple(labels))


def _representative_label(profile: _TopicProfile) -> str:
    for values in (profile.methods, profile.gaps, profile.claims):
        if values:
            return values[0]
    return f"topic {profile.topic_id}"


def _task_incompatible(
    source: _TopicProfile,
    target: _TopicProfile,
    *,
    shared_abstractions: tuple[str, ...],
    lexical_overlap: float,
) -> bool:
    if shared_abstractions:
        return False
    if lexical_overlap < 0.25:
        return False
    if not source.tasks or not target.tasks:
        return False
    source_task_terms = _terms(" ".join(source.tasks))
    target_task_terms = _terms(" ".join(target.tasks))
    if not source_task_terms or not target_task_terms:
        return False
    return not bool(source_task_terms & target_task_terms)


def _opposite_polarity(source_claim: str, target_claim: str) -> bool:
    positive = {"gain", "gains", "improve", "improves", "higher", "reduce", "reduces"}
    negative = {"decrease", "decreases", "harm", "harms", "lower", "no", "worse"}
    source_terms = _terms(source_claim)
    target_terms = _terms(target_claim)
    return bool(source_terms & positive and target_terms & negative) or bool(
        target_terms & positive and source_terms & negative
    )


def _shared_abstractions(source_label: str, target_label: str) -> tuple[str, ...]:
    source_abstractions = set(_abstractions_for_values((source_label,)))
    target_abstractions = set(_abstractions_for_values((target_label,)))
    return tuple(
        abstraction for abstraction in sorted(source_abstractions & target_abstractions)
    )


def _abstractions_for_values(values: Iterable[str]) -> tuple[str, ...]:
    all_terms = set().union(*(_terms(value) for value in values), set())
    abstractions = [
        name for name, markers in _ABSTRACTION_TERMS.items() if all_terms & set(markers)
    ]
    return tuple(sorted(abstractions))


def _lexical_overlap(source_label: str, target_label: str) -> float:
    source_terms = _terms(source_label)
    target_terms = _terms(target_label)
    if not source_terms or not target_terms:
        return 0.0
    return len(source_terms & target_terms) / len(source_terms | target_terms)


def _novelty_bonus(
    *,
    lexical_overlap: float,
    shared_abstractions: tuple[str, ...],
) -> float:
    if not shared_abstractions:
        return 0.0
    if lexical_overlap <= 0.2:
        return 0.14
    if lexical_overlap <= 0.35:
        return 0.08
    return 0.02


def _query_adjusted_score(
    link: CrossTopicKnowledgeLink,
    query_terms: set[str],
) -> float:
    if not query_terms:
        return link.score
    text_terms = _terms(
        " ".join(
            (
                link.link_type,
                link.source_label,
                link.target_label,
                link.explanation,
            )
        )
    )
    return link.score + min(len(query_terms & text_terms) * 0.03, 0.12)


def _dedupe_links(
    links: Iterable[CrossTopicKnowledgeLink],
) -> tuple[CrossTopicKnowledgeLink, ...]:
    by_key: dict[tuple[object, ...], CrossTopicKnowledgeLink] = {}
    for link in links:
        key = (
            link.link_type,
            link.source_topic_id,
            link.target_topic_id,
            link.source_label,
            link.target_label,
        )
        current = by_key.get(key)
        if current is None or link.score > current.score:
            by_key[key] = link
    return tuple(by_key.values())


def _explanation_with_abstractions(
    explanation: str,
    shared_abstractions: tuple[str, ...],
) -> str:
    if not shared_abstractions:
        return explanation
    return f"{explanation} Shared abstraction(s): {', '.join(shared_abstractions)}."


def _text_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return _dedupe_text(tuple(str(item).strip() for item in value if str(item).strip()))


def _dedupe_text(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: dict[str, str] = {}
    for value in values:
        key = " ".join(value.lower().split())
        if key:
            seen.setdefault(key, value)
    return tuple(seen[key] for key in sorted(seen))


def _terms(value: str) -> set[str]:
    return {
        term
        for term in _TERM_RE.findall(str(value or "").lower())
        if len(term) > 1 and term not in _STOPWORDS
    }


def _shorten(value: str, *, max_chars: int = 140) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 3].rstrip()}..."


def _int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
