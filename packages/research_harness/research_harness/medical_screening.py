"""Medical literature screening helpers.

These heuristics are intentionally conservative. They structure PubMed search
results for human screening, but do not claim journal quartile or final
inclusion/exclusion decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .paper_sources import PaperRecord


_WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class ScreeningRow:
    pmid: str
    pmcid: str
    doi: str
    title: str
    authors: list[str]
    year: int | None
    journal: str
    abstract: str
    publication_types: list[str]
    mesh_terms: list[str]
    exposure_tags: list[str]
    life_stage_tags: list[str]
    outcome_tags: list[str]
    evidence_type: str
    priority_tier: str
    priority_reason: str
    journal_quartile_status: str
    pubmed_url: str
    pmc_url: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "pmid": self.pmid,
            "pmcid": self.pmcid,
            "doi": self.doi,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "journal": self.journal,
            "abstract": self.abstract,
            "publication_types": self.publication_types,
            "mesh_terms": self.mesh_terms,
            "exposure_tags": self.exposure_tags,
            "life_stage_tags": self.life_stage_tags,
            "outcome_tags": self.outcome_tags,
            "evidence_type": self.evidence_type,
            "priority_tier": self.priority_tier,
            "priority_reason": self.priority_reason,
            "journal_quartile_status": self.journal_quartile_status,
            "pubmed_url": self.pubmed_url,
            "pmc_url": self.pmc_url,
        }


def screening_row(record: PaperRecord) -> ScreeningRow:
    publication_types = _concept_values(record, "publication_type")
    mesh_terms = _concept_values(record, "mesh")
    text = " ".join([record.title, record.abstract, " ".join(mesh_terms)]).lower()
    evidence_type = _evidence_type(publication_types, text)
    priority_tier, priority_reason = _priority(record, evidence_type)
    pmc_url = (
        f"https://pmc.ncbi.nlm.nih.gov/articles/{record.pmcid}/" if record.pmcid else ""
    )
    return ScreeningRow(
        pmid=record.pmid,
        pmcid=record.pmcid,
        doi=record.doi,
        title=record.title,
        authors=list(record.authors),
        year=record.year,
        journal=record.venue,
        abstract=record.abstract,
        publication_types=publication_types,
        mesh_terms=mesh_terms,
        exposure_tags=_tag_text(
            text,
            {
                "heat": ("heat", "temperature", "thermal", "hot"),
                "air_pollution": ("air pollution", "pm2", "pm2.5", "ozone", "smog"),
                "wildfire": ("wildfire", "bushfire", "smoke"),
                "flood": ("flood", "hurricane", "cyclone", "storm"),
                "climate_change": ("climate change", "global warming"),
                "extreme_weather": ("extreme weather", "disaster"),
            },
        ),
        life_stage_tags=_tag_text(
            text,
            {
                "pregnancy": ("pregnan", "maternal", "prenatal", "antenatal"),
                "newborn": ("newborn", "neonat", "infant"),
                "child": ("child", "children", "pediatric", "paediatric"),
                "adolescent": ("adolescent", "youth"),
            },
        ),
        outcome_tags=_tag_text(
            text,
            {
                "preterm_birth": ("preterm", "premature birth"),
                "birth_weight": (
                    "birth weight",
                    "low birthweight",
                    "small for gestational",
                ),
                "stillbirth": ("stillbirth", "fetal death"),
                "hypertensive_disorders": ("preeclampsia", "hypertension"),
                "respiratory": ("asthma", "respiratory", "wheeze"),
                "mental_health": ("depression", "anxiety", "mental health"),
                "mortality": ("mortality", "death"),
            },
        ),
        evidence_type=evidence_type,
        priority_tier=priority_tier,
        priority_reason=priority_reason,
        journal_quartile_status="needs_external_verification",
        pubmed_url=record.url,
        pmc_url=pmc_url,
    )


def _concept_values(record: PaperRecord, kind: str) -> list[str]:
    values: list[str] = []
    for concept in record.concepts:
        if not isinstance(concept, dict) or concept.get("kind") != kind:
            continue
        value = str(concept.get("display_name") or "").strip()
        if value:
            values.append(value)
    return list(dict.fromkeys(values))


def _evidence_type(publication_types: list[str], text: str) -> str:
    values = {item.lower() for item in publication_types}
    if "systematic review" in values or "meta-analysis" in values:
        return "systematic_review"
    if "randomized controlled trial" in values or "clinical trial" in values:
        return "trial"
    if "review" in values:
        return "narrative_review"
    if any(term in text for term in ("cohort", "case-control", "case control")):
        return "observational_study"
    if "cross-sectional" in text or "cross sectional" in text:
        return "cross_sectional_study"
    return "primary_or_unclear"


def _priority(record: PaperRecord, evidence_type: str) -> tuple[str, str]:
    reasons: list[str] = []
    score = 0
    if record.year and record.year >= 2015:
        score += 1
        reasons.append("recent")
    if record.doi:
        score += 1
        reasons.append("doi")
    if record.abstract:
        score += 1
        reasons.append("abstract")
    if evidence_type in {"systematic_review", "trial", "observational_study"}:
        score += 1
        reasons.append(evidence_type)
    if record.pmcid:
        score += 1
        reasons.append("pmc_full_text")

    if score >= 4:
        return "high", ", ".join(reasons)
    if score >= 2:
        return "medium", ", ".join(reasons)
    return "low", ", ".join(reasons) or "limited metadata"


def _tag_text(text: str, rules: dict[str, tuple[str, ...]]) -> list[str]:
    tokens = set(_WORD_RE.findall(text))
    tags: list[str] = []
    for tag, needles in rules.items():
        for needle in needles:
            if " " in needle:
                if needle in text:
                    tags.append(tag)
                    break
            elif needle in tokens or any(token.startswith(needle) for token in tokens):
                tags.append(tag)
                break
    return tags
