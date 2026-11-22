"""Private evidence-grounded innovation opportunity helpers.

The report produced here is an advisory bridge from Research Wiki context packs
and Cross-Topic Atlas links into candidate research storylines. It is
deterministic, dependency-free, and does not expose public transport behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any

from .cross_topic_atlas import (
    CrossTopicKnowledgeAtlas,
    CrossTopicKnowledgeLink,
    rank_cross_topic_serendipity_links,
)
from .research_wiki_insights import ResearchWikiEvidenceAnchor
from .wiki_context_pack import WikiContextPack, WikiContextPage


INNOVATION_OPPORTUNITY_REPORT_SCHEMA_VERSION = "innovation_opportunity_report.v1"
_WORD_RE = re.compile(r"[a-z0-9]+")
_DEFAULT_ABSTRACT_CHALLENGE = "under-specified_challenge"
_PROOF_WARNING = "cross-domain analogy is inspiration, not proof of novelty"


@dataclass(frozen=True)
class CrossDomainAnalogy:
    link_type: str
    source_topic_id: int
    target_topic_id: int
    score: float
    source_label: str
    target_label: str
    shared_abstractions: tuple[str, ...]
    transfer_mechanism: str
    evidence_summary: tuple[str, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class InnovationOpportunity:
    opportunity_id: str
    support_level: str
    anchor_observation: str
    observed_problem: str
    abstract_challenge: str
    in_domain_context: tuple[str, ...]
    cross_domain_analogies: tuple[CrossDomainAnalogy, ...]
    transfer_mechanism: str
    proposed_storyline: str
    testable_hypothesis: str
    novelty_risks: tuple[str, ...]
    evidence_anchors: tuple[ResearchWikiEvidenceAnchor, ...]
    derivation: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class InnovationOpportunityReport:
    schema_version: str
    topic_id: int
    query: str
    anchor_paper_id: int | None
    opportunities: tuple[InnovationOpportunity, ...]
    warnings: tuple[str, ...] = ()


def build_innovation_opportunity_report(
    *,
    topic_id: int,
    context_pack: WikiContextPack,
    atlas: CrossTopicKnowledgeAtlas | None = None,
    query: str = "",
    anchor_paper_id: int | None = None,
    max_opportunities: int = 3,
    max_analogies: int = 3,
) -> InnovationOpportunityReport:
    """Build a private ``innovation_opportunity_report.v1``."""

    normalized_query = " ".join(str(query or context_pack.query or "").split())
    pages = _rank_context_pages(context_pack.pages, normalized_query)
    if max_opportunities <= 0:
        selected_pages: tuple[WikiContextPage, ...] = ()
    else:
        selected_pages = tuple(pages[: max(0, int(max_opportunities))])

    atlas_links = _ranked_links(
        atlas=atlas,
        topic_id=topic_id,
        query=normalized_query,
        max_results=max(1, int(max_opportunities) * max(1, int(max_analogies))),
    )

    opportunities = tuple(
        _build_opportunity(
            index=index,
            page=page,
            topic_id=topic_id,
            links=_matching_links(
                page,
                atlas_links,
                max_analogies=max(0, int(max_analogies)),
            ),
        )
        for index, page in enumerate(selected_pages, start=1)
    )
    warnings = []
    if context_pack.degraded:
        warnings.append("context_pack_degraded")
    if context_pack.truncated:
        warnings.append("context_pack_truncated")
    if atlas is not None:
        warnings.extend(atlas.warnings)

    return InnovationOpportunityReport(
        schema_version=INNOVATION_OPPORTUNITY_REPORT_SCHEMA_VERSION,
        topic_id=topic_id,
        query=normalized_query,
        anchor_paper_id=anchor_paper_id,
        opportunities=opportunities,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def innovation_opportunity_report_to_dict(
    report: InnovationOpportunityReport,
) -> dict[str, Any]:
    """Serialize an opportunity report into deterministic public-safe data."""

    return {
        "schema_version": report.schema_version,
        "topic_id": report.topic_id,
        "query": report.query,
        "anchor_paper_id": report.anchor_paper_id,
        "opportunity_count": len(report.opportunities),
        "warnings": list(report.warnings),
        "opportunities": [
            _opportunity_to_dict(opportunity) for opportunity in report.opportunities
        ],
    }


def render_innovation_opportunity_report_markdown(
    report: InnovationOpportunityReport,
) -> str:
    """Render a concise deterministic Markdown report."""

    lines = [
        "# Innovation Opportunity Report",
        "",
        f"- Topic id: {report.topic_id}",
        f"- Query: {report.query or '(none)'}",
        f"- Opportunity count: {len(report.opportunities)}",
        "",
    ]
    if report.warnings:
        lines.append("## Warnings")
        lines.append("")
        lines.extend(f"- {warning}" for warning in report.warnings)
        lines.append("")

    for index, opportunity in enumerate(report.opportunities, start=1):
        lines.extend(
            [
                f"## {index}. {opportunity.anchor_observation}",
                "",
                f"- Support: {opportunity.support_level}",
                f"- Abstract challenge: {opportunity.abstract_challenge}",
                f"- Observed problem: {opportunity.observed_problem}",
                f"- Transfer mechanism: {opportunity.transfer_mechanism}",
                f"- Testable hypothesis: {opportunity.testable_hypothesis}",
                "",
                "### Storyline",
                "",
                opportunity.proposed_storyline,
                "",
                "### Novelty risks",
                "",
            ]
        )
        lines.extend(f"- {risk}" for risk in opportunity.novelty_risks)
        lines.append("")
        if opportunity.cross_domain_analogies:
            lines.append("### Cross-domain analogies")
            lines.append("")
            for analogy in opportunity.cross_domain_analogies:
                lines.append(
                    f"- {analogy.link_type}: {analogy.transfer_mechanism} "
                    f"(score={analogy.score:.2f})"
                )
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _build_opportunity(
    *,
    index: int,
    page: WikiContextPage,
    topic_id: int,
    links: tuple[CrossTopicKnowledgeLink, ...],
) -> InnovationOpportunity:
    analogies = tuple(_cross_domain_analogy(link) for link in links)
    evidence_anchors = page.evidence_anchors
    abstract_challenge = _abstract_challenge(page, links)
    observed_problem = _observed_problem(page)
    anchor_observation = page.title or page.page_path
    support_level = _support_level(page, links)
    transfer_mechanism = _primary_transfer_mechanism(analogies, abstract_challenge)
    novelty_risks = _novelty_risks(
        evidence_anchors=evidence_anchors,
        links=links,
        support_level=support_level,
    )
    proposed_storyline = _storyline(
        anchor_observation=anchor_observation,
        observed_problem=observed_problem,
        abstract_challenge=abstract_challenge,
        analogies=analogies,
    )
    return InnovationOpportunity(
        opportunity_id=f"topic-{topic_id}-opportunity-{index}",
        support_level=support_level,
        anchor_observation=anchor_observation,
        observed_problem=observed_problem,
        abstract_challenge=abstract_challenge,
        in_domain_context=_in_domain_context(page),
        cross_domain_analogies=analogies,
        transfer_mechanism=transfer_mechanism,
        proposed_storyline=proposed_storyline,
        testable_hypothesis=_testable_hypothesis(
            abstract_challenge=abstract_challenge,
            observed_problem=observed_problem,
            transfer_mechanism=transfer_mechanism,
        ),
        novelty_risks=novelty_risks,
        evidence_anchors=evidence_anchors,
        derivation=_derivation(page=page, links=links, analogies=analogies),
    )


def _rank_context_pages(
    pages: tuple[WikiContextPage, ...],
    query: str,
) -> list[WikiContextPage]:
    query_terms = _terms(query)
    return sorted(
        pages,
        key=lambda page: (
            -_page_priority(page),
            -_query_overlap(page, query_terms),
            -len(page.evidence_anchors),
            -page.score,
            page.page_path,
        ),
    )


def _page_priority(page: WikiContextPage) -> int:
    if page.page_type == "finding":
        return 4
    if page.page_type == "methodology":
        return 3
    if page.page_type == "source_section":
        return 2
    return 1


def _query_overlap(page: WikiContextPage, query_terms: set[str]) -> int:
    if not query_terms:
        return 0
    page_terms = _terms(
        " ".join(
            (
                page.title,
                page.page_path,
                page.excerpt,
                " ".join(page.matched_terms),
            )
        )
    )
    return len(query_terms & page_terms)


def _ranked_links(
    *,
    atlas: CrossTopicKnowledgeAtlas | None,
    topic_id: int,
    query: str,
    max_results: int,
) -> tuple[CrossTopicKnowledgeLink, ...]:
    if atlas is None:
        return ()
    ranked = rank_cross_topic_serendipity_links(
        atlas,
        query=query,
        max_results=max_results,
    )
    return tuple(
        link
        for link in ranked
        if link.source_topic_id == topic_id or link.target_topic_id == topic_id
    )


def _matching_links(
    page: WikiContextPage,
    links: tuple[CrossTopicKnowledgeLink, ...],
    *,
    max_analogies: int,
) -> tuple[CrossTopicKnowledgeLink, ...]:
    if max_analogies <= 0:
        return ()
    page_terms = _terms(
        " ".join(
            (
                page.title,
                page.page_path,
                page.excerpt,
                " ".join(page.matched_terms),
            )
        )
    )
    ranked = sorted(
        links,
        key=lambda link: (
            -_link_page_overlap(link, page_terms),
            -link.score,
            link.link_type,
            link.source_topic_id,
            link.target_topic_id,
        ),
    )
    matched = [
        link
        for link in ranked
        if _link_page_overlap(link, page_terms) > 0 or _shared_abstractions(link)
    ]
    return tuple(matched[:max_analogies])


def _link_page_overlap(link: CrossTopicKnowledgeLink, page_terms: set[str]) -> int:
    link_terms = _terms(
        " ".join((link.source_label, link.target_label, link.explanation))
    )
    return len(page_terms & link_terms)


def _cross_domain_analogy(link: CrossTopicKnowledgeLink) -> CrossDomainAnalogy:
    shared_abstractions = _shared_abstractions(link)
    abstraction = (
        shared_abstractions[0] if shared_abstractions else _DEFAULT_ABSTRACT_CHALLENGE
    )
    return CrossDomainAnalogy(
        link_type=link.link_type,
        source_topic_id=link.source_topic_id,
        target_topic_id=link.target_topic_id,
        score=link.score,
        source_label=link.source_label,
        target_label=link.target_label,
        shared_abstractions=shared_abstractions,
        transfer_mechanism=(
            f"transfer {abstraction} from {link.source_label} to {link.target_label}"
        ),
        evidence_summary=link.evidence_summary,
        warnings=link.warnings,
    )


def _abstract_challenge(
    page: WikiContextPage,
    links: tuple[CrossTopicKnowledgeLink, ...],
) -> str:
    for link in links:
        abstractions = _shared_abstractions(link)
        if abstractions:
            return abstractions[0]
    page_terms = _terms(" ".join((page.title, page.excerpt, page.page_path)))
    if {"provenance", "evidence"} & page_terms:
        return "provenance_control"
    if {"budget", "token", "context"} & page_terms:
        return "budget_control"
    if {"baseline", "metric", "evaluation", "recall"} & page_terms:
        return "evaluation_bridge"
    if {"failure", "weak", "stale", "drift"} & page_terms:
        return "failure_mode"
    return _DEFAULT_ABSTRACT_CHALLENGE


def _abstract_challenge_derivation(
    page: WikiContextPage,
    links: tuple[CrossTopicKnowledgeLink, ...],
) -> str:
    for link in links:
        if _shared_abstractions(link):
            return "cross_topic_shared_abstraction"
    page_terms = _terms(" ".join((page.title, page.excerpt, page.page_path)))
    if (
        {"provenance", "evidence"} & page_terms
        or {"budget", "token", "context"} & page_terms
        or {"baseline", "metric", "evaluation", "recall"} & page_terms
        or {"failure", "weak", "stale", "drift"} & page_terms
    ):
        return "heuristic_keyword_mapping"
    return "default_unspecified_challenge"


def _observed_problem(page: WikiContextPage) -> str:
    if page.excerpt:
        return page.excerpt
    if page.evidence_anchors:
        return page.evidence_anchors[0].evidence_snippet
    return page.title or page.page_path


def _observed_problem_derivation(page: WikiContextPage) -> str:
    if page.excerpt:
        return "wiki_page_excerpt"
    if page.evidence_anchors:
        return "evidence_anchor_snippet"
    return "wiki_page_title_or_path"


def _support_level(
    page: WikiContextPage,
    links: tuple[CrossTopicKnowledgeLink, ...],
) -> str:
    has_anchor = bool(page.evidence_anchors)
    strong_link = any(link.score >= 0.65 and not link.warnings for link in links)
    weak_link = bool(links)
    if has_anchor and strong_link:
        return "evidence_bound"
    if has_anchor or weak_link:
        return "weakly_supported"
    return "speculative"


def _primary_transfer_mechanism(
    analogies: tuple[CrossDomainAnalogy, ...],
    abstract_challenge: str,
) -> str:
    if analogies:
        return analogies[0].transfer_mechanism
    return f"no cross-domain transfer selected for {abstract_challenge}"


def _novelty_risks(
    *,
    evidence_anchors: tuple[ResearchWikiEvidenceAnchor, ...],
    links: tuple[CrossTopicKnowledgeLink, ...],
    support_level: str,
) -> tuple[str, ...]:
    risks = [_PROOF_WARNING]
    for link in links:
        risks.extend(link.warnings)
        if link.score < 0.5:
            risks.append("cross-domain analogy is weak")
    if not evidence_anchors:
        risks.append("insufficient evidence anchors")
    if support_level == "speculative":
        risks.append("speculative opportunity requires paper-backed validation")
    return tuple(dict.fromkeys(risks))


def _storyline(
    *,
    anchor_observation: str,
    observed_problem: str,
    abstract_challenge: str,
    analogies: tuple[CrossDomainAnalogy, ...],
) -> str:
    if analogies:
        analogy = analogies[0]
        return (
            f"{anchor_observation} exposes {abstract_challenge}: "
            f"{observed_problem} A related solution pattern, "
            f"{analogy.source_label}, suggests {analogy.transfer_mechanism}. "
            "The resulting idea should be tested as a hypothesis, not assumed "
            "as novelty."
        )
    return (
        f"{anchor_observation} exposes {abstract_challenge}: {observed_problem} "
        "The opportunity is currently in-domain only and needs stronger "
        "evidence before it should drive a method claim."
    )


def _testable_hypothesis(
    *,
    abstract_challenge: str,
    observed_problem: str,
    transfer_mechanism: str,
) -> str:
    return (
        f"If {abstract_challenge} is addressed by {transfer_mechanism}, "
        f"then the observed problem should decrease: {_shorten(observed_problem)}"
    )


def _in_domain_context(page: WikiContextPage) -> tuple[str, ...]:
    values = [page.excerpt]
    values.extend(anchor.evidence_snippet for anchor in page.evidence_anchors)
    return tuple(dict.fromkeys(value for value in values if value))


def _derivation(
    *,
    page: WikiContextPage,
    links: tuple[CrossTopicKnowledgeLink, ...],
    analogies: tuple[CrossDomainAnalogy, ...],
) -> dict[str, str]:
    return {
        "anchor_observation": "wiki_page_title" if page.title else "wiki_page_path",
        "observed_problem": _observed_problem_derivation(page),
        "abstract_challenge": _abstract_challenge_derivation(page, links),
        "transfer_mechanism": "cross_topic_analogy"
        if analogies
        else "no_cross_topic_transfer",
        "proposed_storyline": "derived_advisory_synthesis",
        "testable_hypothesis": "derived_advisory_hypothesis",
    }


def _shared_abstractions(link: CrossTopicKnowledgeLink) -> tuple[str, ...]:
    raw = link.metadata.get("shared_abstractions")
    if not isinstance(raw, list):
        return ()
    return tuple(str(item) for item in raw if str(item).strip())


def _opportunity_to_dict(opportunity: InnovationOpportunity) -> dict[str, Any]:
    return {
        "artifact_role": "advisory_compiled_view",
        "opportunity_id": opportunity.opportunity_id,
        "support_level": opportunity.support_level,
        "anchor_observation": opportunity.anchor_observation,
        "observed_problem": opportunity.observed_problem,
        "abstract_challenge": opportunity.abstract_challenge,
        "in_domain_context": list(opportunity.in_domain_context),
        "cross_domain_analogies": [
            _analogy_to_dict(analogy) for analogy in opportunity.cross_domain_analogies
        ],
        "transfer_mechanism": opportunity.transfer_mechanism,
        "proposed_storyline": opportunity.proposed_storyline,
        "testable_hypothesis": opportunity.testable_hypothesis,
        "novelty_risks": list(opportunity.novelty_risks),
        "evidence_anchors": [
            _evidence_anchor_to_dict(anchor) for anchor in opportunity.evidence_anchors
        ],
        "derivation": dict(opportunity.derivation),
    }


def _analogy_to_dict(analogy: CrossDomainAnalogy) -> dict[str, Any]:
    return {
        "link_type": analogy.link_type,
        "source_topic_id": analogy.source_topic_id,
        "target_topic_id": analogy.target_topic_id,
        "score": analogy.score,
        "source_label": analogy.source_label,
        "target_label": analogy.target_label,
        "shared_abstractions": list(analogy.shared_abstractions),
        "transfer_mechanism": analogy.transfer_mechanism,
        "evidence_summary": list(analogy.evidence_summary),
        "warnings": list(analogy.warnings),
    }


def _evidence_anchor_to_dict(
    anchor: ResearchWikiEvidenceAnchor,
) -> dict[str, Any]:
    return {
        "page_path": anchor.page_path,
        "paper_id": anchor.paper_id,
        "source_type": anchor.source_type,
        "source_id": anchor.source_id,
        "source_hash": anchor.source_hash,
        "section_anchor": anchor.section_anchor,
        "evidence_snippet": anchor.evidence_snippet,
    }


def _terms(value: str) -> set[str]:
    return set(_WORD_RE.findall(str(value or "").lower()))


def _shorten(value: str, limit: int = 180) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."
