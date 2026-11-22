"""Writing pipeline primitive implementations — Sprint 4.

outline_generate (LLM), section_review (LLM + deterministic), section_revise (LLM),
latex_compile (non-LLM).

LLM primitives use stub implementations that return placeholder output.
Real LLM calls are dispatched by execution/llm_primitives.py (same pattern as
code_generate from Sprint 2).
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from ..execution.latex_compiler import (
    assemble_latex,
    authors_to_bibtex,
    compile_latex,
    template_fingerprint,
    _fix_unicode,
)
from ..execution.writing_checks import REVIEW_DIMENSIONS, run_all_checks
from ..orchestrator.models import MIN_FINAL_USABLE_SCREENED_PAPERS
from .registry import (
    LATEX_COMPILE_SPEC,
    OUTLINE_GENERATE_SPEC,
    PAPER_FINALIZE_SPEC,
    PUBLICATION_PACK_BACKFILL_SPEC,
    PUBLICATION_PACK_GENERATE_SPEC,
    PUBLICATION_RUN_SPEC,
    SECTION_REVIEW_SPEC,
    SECTION_REVISE_SPEC,
    VENUE_COMPLIANCE_CHECK_SPEC,
    register_primitive,
)
from .types import (
    DeterministicCheck,
    LatexCompileOutput,
    OutlineGenerateOutput,
    OutlineSectionItem,
    PaperFinalizeOutput,
    PublicationPackBackfillOutput,
    PublicationPackComponent,
    PublicationPackOutput,
    PublicationRunOutput,
    ReviewDimension,
    SectionReviewOutput,
    SectionReviseOutput,
    VenueComplianceCheckOutput,
)

logger = logging.getLogger(__name__)

VENUE_COMPLIANCE_REPORT_SCHEMA_VERSION = "rh.venue_compliance_report.v1"
_AAAI_DISALLOWED_PACKAGES = frozenset(
    {
        "authblk",
        "balance",
        "cjk",
        "float",
        "fontenc",
        "fullpage",
        "geometry",
        "hyperref",
        "minted",
        "multicol",
        "setspace",
        "titlesec",
        "ulem",
        "wrapfig",
    }
)
_AAAI_DISALLOWED_COMMANDS = (
    r"\nocopyright",
    r"\addtolength",
    r"\balance",
    r"\baselinestretch",
    r"\clearpage",
    r"\newpage",
    r"\pagebreak",
    r"\pagestyle",
    r"\baselineskip=",
    r"\write18",
)
_LATEX_COMMENT_RE = re.compile(r"(?<!\\)%.*")
_LATEX_PACKAGE_RE = re.compile(r"\\usepackage(?:\[[^\]]*\])?\{([^}]*)\}")
_LATEX_FILE_COMMAND_RE = re.compile(
    r"\\(includegraphics|input|include)(?:\[[^\]]*\])?\{([^}]+)\}"
)
_LATEX_GRAPHICS_EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg", ".eps")
_LOG_UNDEFINED_CITATION_RE = re.compile(r"[Cc]itation\s+[`']([^`']+)[`'].*undefined")
_LOG_UNDEFINED_REFERENCE_RE = re.compile(r"[Rr]eference\s+[`']([^`']+)[`'].*undefined")
_LOG_MISSING_FILE_RE = re.compile(
    r"(?:File|LaTeX Error:\s*File)\s+[`']([^`']+)[`']\s+not found",
    re.IGNORECASE,
)


@register_primitive(OUTLINE_GENERATE_SPEC)
def outline_generate(
    *,
    topic_id: int,
    template: str = "neurips",
    **_: Any,
) -> OutlineGenerateOutput:
    """Generate paper outline. Stub — real LLM call dispatched by harness."""
    # Default outline structure with word targets
    default_sections = [
        OutlineSectionItem(
            section="introduction", title="Introduction", target_words=900
        ),
        OutlineSectionItem(
            section="related_work", title="Related Work", target_words=800
        ),
        OutlineSectionItem(section="method", title="Method", target_words=1500),
        OutlineSectionItem(
            section="experiments", title="Experiments", target_words=1200
        ),
        OutlineSectionItem(section="results", title="Results", target_words=800),
        OutlineSectionItem(section="discussion", title="Discussion", target_words=600),
        OutlineSectionItem(section="conclusion", title="Conclusion", target_words=300),
    ]
    total = sum(s.target_words for s in default_sections)

    return OutlineGenerateOutput(
        title="",
        abstract_draft="",
        sections=default_sections,
        total_target_words=total,
        model_used="stub",
    )


@register_primitive(SECTION_REVIEW_SPEC)
def section_review(
    *,
    section: str,
    content: str,
    target_words: int = 0,
    target_venue: str = "",
    **_: Any,
) -> SectionReviewOutput:
    """Review a paper section: deterministic checks + LLM scoring stub.

    The deterministic checks (AI boilerplate, weasel words, word count,
    repetition, structure, citations, paragraph development) run immediately.
    LLM-based 13-dim scoring is dispatched by the harness and merged later.
    """
    # Run deterministic checks
    check_results = run_all_checks(content, section, target_words, venue=target_venue)

    deterministic_checks = [
        DeterministicCheck(
            check_name=c.check_name,
            passed=c.passed,
            details=c.details,
            items_found=c.items_found,
        )
        for c in check_results
    ]

    # Stub LLM dimensions (all 0.0 — real scores filled by harness)
    dimensions = [
        ReviewDimension(dimension=dim, score=0.0, comment="")
        for dim in REVIEW_DIMENSIONS
    ]

    # Determine if revision needed based on deterministic checks
    failed_checks = [c for c in check_results if not c.passed]
    suggestions = [c.details for c in failed_checks]

    return SectionReviewOutput(
        section=section,
        overall_score=0.0,
        dimensions=dimensions,
        deterministic_checks=deterministic_checks,
        suggestions=suggestions,
        needs_revision=len(failed_checks) > 0,
        model_used="deterministic_only",
    )


@register_primitive(SECTION_REVISE_SPEC)
def section_revise(
    *,
    section: str,
    content: str,
    review_feedback: str,
    target_words: int = 0,
    **_: Any,
) -> SectionReviseOutput:
    """Revise a paper section based on review feedback. Stub — real LLM call dispatched."""
    return SectionReviseOutput(
        section=section,
        revised_content=content,  # pass-through in stub mode
        changes_made=["Stub: no LLM revision applied"],
        word_count=len(content.split()),
        model_used="stub",
    )


@register_primitive(LATEX_COMPILE_SPEC)
def latex_compile(
    *,
    topic_id: int,
    output_dir: str,
    template: str = "generic",
    sections: dict[str, str] | None = None,
    title: str = "",
    authors: list[str] | None = None,
    abstract: str = "",
    bibliography_entries: list[str] | None = None,
    **_: Any,
) -> LatexCompileOutput:
    """Assemble and compile LaTeX paper."""
    sections = sections or {}
    authors = authors or []

    tex_content, bib_content = assemble_latex(
        title=title,
        authors=authors,
        abstract=abstract,
        sections=sections,
        bibliography_entries=bibliography_entries,
        template=template,
    )

    result = compile_latex(tex_content, bib_content, output_dir)

    return LatexCompileOutput(
        success=result.success,
        pdf_path=result.pdf_path,
        log_summary=result.log_summary,
        warnings=result.warnings,
        errors=result.errors,
        pages=result.pages,
        auto_fixes_applied=result.auto_fixes,
    )


@register_primitive(PAPER_FINALIZE_SPEC)
def paper_finalize(
    *,
    topic_id: int,
    output_dir: str,
    title: str = "",
    authors: list[str] | None = None,
    abstract: str = "",
    sections: dict[str, str] | None = None,
    bibliography_entries: list[str] | None = None,
    template: str = "arxiv",
    **_: Any,
) -> PaperFinalizeOutput:
    """One-shot assemble + compile: sections dict → .tex → .pdf.

    Defaults to ``arxiv`` template (single-column, self-contained). Uses pdflatex
    if available, otherwise tectonic. Returns the generated file paths.
    """
    sections = sections or {}
    authors = authors or []

    tex_content, bib_content = assemble_latex(
        title=title,
        authors=authors,
        abstract=abstract,
        sections=sections,
        bibliography_entries=bibliography_entries,
        template=template,
    )

    result = compile_latex(tex_content, bib_content, output_dir)

    from pathlib import Path as _Path

    tex_path = str(_Path(output_dir) / "paper.tex")
    bib_path = str(_Path(output_dir) / "references.bib") if bib_content else ""

    return PaperFinalizeOutput(
        success=result.success,
        tex_path=tex_path,
        bib_path=bib_path,
        pdf_path=result.pdf_path,
        pages=result.pages,
        word_count=sum(len(v.split()) for v in sections.values()),
        sections_assembled=len(sections),
        warnings=result.warnings,
        errors=result.errors,
        auto_fixes_applied=result.auto_fixes,
        template_used=template,
        validation_errors=sum(
            1 for f in result.validation_findings if f.level == "error"
        ),
        validation_warnings=sum(
            1 for f in result.validation_findings if f.level == "warning"
        ),
    )


_PUBLICATION_COMPONENT_SPECS: dict[str, dict[str, Any]] = {
    "manuscript_sections": {
        "artifact_types": ("draft_pack",),
        "required": True,
        "role": "Drafted paper sections or manuscript text.",
    },
    "evidence_pack": {
        "artifact_types": ("evidence_pack", "claim_set", "claims"),
        "required": True,
        "role": "Claims, evidence links, and source-paper support.",
    },
    "citation_integrity": {
        "artifact_types": (
            "citation_sanitization_report",
            "final_integrity_report",
            "integrity_review_report",
        ),
        "required": False,
        "role": "Citation sanitization and final integrity evidence.",
    },
    "figure_plan": {
        "artifact_types": ("figure_plan",),
        "required": False,
        "role": "Contract-first publication figure plan.",
    },
    "data_availability": {
        "artifact_types": ("data_availability", "data_availability_statement"),
        "required": False,
        "role": "Repository, identifier, and FAIR/data-availability plan.",
    },
    "reviewer_response": {
        "artifact_types": (
            "response_to_review",
            "reviewer_response",
            "rebuttal_response",
        ),
        "required": False,
        "role": "Point-by-point reviewer response or rebuttal draft.",
    },
    "slides_outline": {
        "artifact_types": ("slides_outline", "presentation_pack", "paper_slides"),
        "required": False,
        "role": "Presentation or journal-club slide outline.",
    },
    "final_bundle": {
        "artifact_types": ("final_bundle",),
        "required": False,
        "role": "Assembled paper/export bundle.",
    },
    "process_summary": {
        "artifact_types": ("process_summary", "provenance_review"),
        "required": False,
        "role": "Execution/provenance summary for reviewer handoff.",
    },
    "venue_compliance": {
        "artifact_types": ("venue_compliance_report", "submission_checklist"),
        "required": False,
        "role": "Venue-specific formatting, anonymization, page-limit, and checklist QA.",
    },
}


_PUBLICATION_NEXT_ACTION_TEMPLATES: dict[str, dict[str, str]] = {
    "manuscript_sections": {
        "recommended_tool": "section_draft",
        "action": "Draft or record the manuscript sections as a draft_pack artifact.",
    },
    "evidence_pack": {
        "recommended_tool": "claim_extract",
        "action": "Extract/link claims and record an evidence_pack artifact.",
    },
    "citation_integrity": {
        "recommended_tool": "citation_sanitize",
        "action": "Run citation_sanitize or integrity_check before submission.",
    },
    "figure_plan": {
        "recommended_tool": "figure_plan",
        "action": "Record a figure_plan artifact before producing publication figures.",
    },
    "final_bundle": {
        "recommended_tool": "paper_finalize",
        "action": "Assemble/export the paper and record a final_bundle artifact.",
    },
    "process_summary": {
        "recommended_tool": "provenance-review",
        "action": "Record a process_summary or provenance_review for reviewer handoff.",
    },
    "venue_compliance": {
        "recommended_tool": "venue-compliance-check",
        "action": "Run a venue compliance check before using a venue-specific submission-ready label.",
    },
    "reference_pool_gate": {
        "recommended_tool": "paper_search",
        "action": "Expand the screened paper pool to the final-PDF threshold or mark the bundle as interim.",
    },
}


_PUBLICATION_QA_COMPONENTS: dict[str, str] = {
    "citation_integrity": "citation_integrity",
    "figure_contract": "figure_plan",
    "final_bundle": "final_bundle",
    "provenance_summary": "process_summary",
    "venue_compliance": "venue_compliance",
}


def _topic_exists(db: Any, topic_id: int) -> bool:
    conn = db.connect()
    try:
        row = conn.execute("SELECT id FROM topics WHERE id = ?", (topic_id,)).fetchone()
        return row is not None
    finally:
        conn.close()


def _latest_active_artifacts(db: Any, topic_id: int) -> dict[str, dict[str, Any]]:
    """Return latest active, non-stale artifact per artifact_type."""
    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT id, stage, artifact_type, title, version, payload_json, created_at
            FROM project_artifacts
            WHERE topic_id = ?
              AND status = 'active'
              AND COALESCE(stale, 0) = 0
            ORDER BY datetime(created_at) DESC, id DESC
            """,
            (topic_id,),
        ).fetchall()
    finally:
        conn.close()

    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        artifact_type = str(row["artifact_type"])
        if artifact_type in latest:
            continue
        payload = _parse_payload(row["payload_json"])
        latest[artifact_type] = {
            "id": int(row["id"]),
            "stage": row["stage"] or "",
            "artifact_type": artifact_type,
            "title": row["title"] or "",
            "version": int(row["version"] or 1),
            "payload_keys": sorted(payload.keys()) if isinstance(payload, dict) else [],
            "created_at": row["created_at"] or "",
        }
    return latest


def _latest_active_artifact(
    db: Any, topic_id: int, artifact_types: tuple[str, ...]
) -> dict[str, Any] | None:
    """Return the latest active artifact row and parsed payload for any type."""
    conn = db.connect()
    try:
        placeholders = ", ".join("?" for _ in artifact_types)
        rows = conn.execute(
            f"""
            SELECT id, stage, artifact_type, title, version, payload_json, created_at
            FROM project_artifacts
            WHERE topic_id = ?
              AND status = 'active'
              AND COALESCE(stale, 0) = 0
              AND artifact_type IN ({placeholders})
            ORDER BY datetime(created_at) DESC, id DESC
            """,
            (topic_id, *artifact_types),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return None
    row = rows[0]
    return {
        "id": int(row["id"]),
        "stage": row["stage"] or "",
        "artifact_type": row["artifact_type"] or "",
        "title": row["title"] or "",
        "version": int(row["version"] or 1),
        "payload": _parse_payload(row["payload_json"]),
        "created_at": row["created_at"] or "",
    }


def _parse_payload(payload_json: str | None) -> Any:
    try:
        return json.loads(payload_json or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}


def _select_artifact(
    latest_by_type: dict[str, dict[str, Any]], artifact_types: tuple[str, ...]
) -> dict[str, Any] | None:
    return next(
        (
            latest_by_type[artifact_type]
            for artifact_type in artifact_types
            if artifact_type in latest_by_type
        ),
        None,
    )


def _final_bundle_reference_pool_check(db: Any, topic_id: int) -> dict[str, Any]:
    final_bundle = _latest_active_artifact(db, topic_id, ("final_bundle",))
    if final_bundle is None:
        return {
            "passed": False,
            "severity": "warning",
            "details": "Record a final_bundle before checking final reference-pool readiness.",
        }
    payload = final_bundle.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    evidence = payload.get("reference_pool_evidence")
    if not isinstance(evidence, dict):
        if not str(payload.get("finality_status") or ""):
            return {
                "passed": True,
                "severity": "warning",
                "details": "Reference-pool evidence is not recorded on this legacy final_bundle.",
            }
        evidence = _reference_pool_evidence(db, topic_id)
    if evidence.get("passed") is True:
        return {
            "passed": True,
            "severity": "blocking",
            "details": "Reference pool meets the final-PDF screened-paper threshold.",
            "evidence": evidence,
        }
    if _final_bundle_has_interim_boundary(payload):
        return {
            "passed": True,
            "severity": "blocking",
            "details": "Reference pool is below the final threshold, but the bundle is explicitly interim with boundary metadata.",
            "evidence": evidence,
        }
    minimum = int(evidence.get("minimum_required") or MIN_FINAL_USABLE_SCREENED_PAPERS)
    usable = int(evidence.get("usable_screened_paper_count") or 0)
    return {
        "passed": False,
        "severity": "blocking",
        "details": (
            f"Reference pool has {usable} usable screened paper(s), below the "
            f"final-PDF threshold of {minimum}; mark the bundle interim or expand the pool."
        ),
        "evidence": evidence,
    }


def _final_bundle_has_interim_boundary(payload: dict[str, Any]) -> bool:
    boundary = payload.get("interim_boundary")
    return (
        payload.get("is_interim") is True
        and str(payload.get("finality_status") or "") == "interim_ready"
        and isinstance(boundary, dict)
        and bool(str(boundary.get("statement") or "").strip())
    )


def _publication_text_from_payload(value: Any) -> str:
    """Extract deterministic manuscript text from a draft-like artifact payload."""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n\n".join(
            text
            for text in (_publication_text_from_payload(item) for item in value)
            if text
        )
    if not isinstance(value, dict):
        return ""

    for key in ("text", "content", "markdown", "body", "draft"):
        text = _publication_text_from_payload(value.get(key))
        if text:
            return text

    sections = value.get("sections")
    if isinstance(sections, dict):
        return "\n\n".join(
            text
            for text in (
                _publication_text_from_payload(section)
                for _, section in sorted(sections.items())
            )
            if text
        )
    if isinstance(sections, list):
        return _publication_text_from_payload(sections)
    return ""


def _template_for_target_profile(target_profile: str) -> str:
    profile = target_profile.lower()
    if "aaai" in profile:
        return "aaai"
    if "neurips" in profile:
        return "neurips"
    if "icml" in profile:
        return "icml"
    if "iclr" in profile:
        return "iclr"
    if any(marker in profile for marker in ("acl", "emnlp", "naacl")):
        return "acl"
    return "arxiv"


def _publication_output_dir(db: Any, topic_id: int, target_profile: str) -> Path:
    slug = re.sub(r"[^a-z0-9._-]+", "-", target_profile.lower()).strip("-")
    slug = slug or "publication"
    db_path = Path(getattr(db, "path", getattr(db, "db_path", ".research-harness")))
    return (
        db_path.expanduser().resolve().parent / "outputs" / f"topic-{topic_id}" / slug
    )


def _topic_title(db: Any, topic_id: int) -> str:
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT name FROM topics WHERE id = ?", (topic_id,)
        ).fetchone()
    finally:
        conn.close()
    return str(row["name"]) if row is not None and row["name"] else "Untitled"


def _topic_paper_index(db: Any, topic_id: int) -> list[dict[str, Any]]:
    conn = db.connect()
    try:
        rows = conn.execute(
            """
            SELECT p.id, p.title, p.authors, p.year, p.venue,
                   p.doi, p.arxiv_id, p.url, p.abstract, p.compiled_summary,
                   p.status, p.pdf_path, pt.relevance, pt.screening_status,
                   pt.manuscript_eligible
            FROM papers p
            JOIN paper_topics pt ON p.id = pt.paper_id
            WHERE pt.topic_id = ?
              AND pt.relevance != 'dismissed'
            """,
            (topic_id,),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "id": int(row["id"]),
            "title": str(row["title"] or ""),
            "authors": row["authors"],
            "year": row["year"],
            "venue": str(row["venue"] or ""),
            "doi": str(row["doi"] or ""),
            "arxiv_id": str(row["arxiv_id"] or ""),
            "url": str(row["url"] or ""),
            "abstract": str(row["abstract"] or ""),
            "compiled_summary": str(row["compiled_summary"] or ""),
            "status": str(row["status"] or ""),
            "pdf_path": str(row["pdf_path"] or ""),
            "relevance": str(row["relevance"] or ""),
            "screening_status": str(row["screening_status"] or ""),
            "manuscript_eligible": int(row["manuscript_eligible"] or 0),
        }
        for row in rows
    ]


def _paper_has_stable_source(paper: dict[str, Any]) -> bool:
    return (
        any(
            bool(str(paper.get(key) or "").strip())
            for key in ("doi", "arxiv_id", "url", "venue")
        )
        or paper.get("year") is not None
    )


def _paper_is_screened_manuscript_evidence(paper: dict[str, Any]) -> bool:
    relevance = str(paper.get("relevance") or "").strip().lower()
    if relevance.startswith(("dismissed", "excluded")):
        return False
    if str(paper.get("screening_status") or "") != "screened_in":
        return False
    if int(paper.get("manuscript_eligible") or 0) != 1:
        return False
    has_content = any(
        str(paper.get(key) or "").strip() for key in ("abstract", "compiled_summary")
    ) or (
        str(paper.get("status") or "") == "annotated"
        and bool(str(paper.get("pdf_path") or "").strip())
    )
    return has_content


def _latest_paper_pool_snapshot_ref(db: Any, topic_id: int) -> dict[str, Any] | None:
    conn = db.connect()
    try:
        row = conn.execute(
            """
            SELECT id, artifact_type, stage, title
            FROM project_artifacts
            WHERE topic_id = ? AND artifact_type = 'paper_pool_snapshot'
                  AND status = 'active'
            ORDER BY version DESC, id DESC LIMIT 1
            """,
            (topic_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {
        "artifact_id": int(row["id"]),
        "artifact_type": str(row["artifact_type"] or ""),
        "stage": str(row["stage"] or ""),
        "title": str(row["title"] or ""),
    }


def _reference_pool_evidence(
    db: Any,
    topic_id: int,
    *,
    minimum_required: int = MIN_FINAL_USABLE_SCREENED_PAPERS,
) -> dict[str, Any]:
    papers = _topic_paper_index(db, topic_id)
    usable = [
        paper
        for paper in papers
        if str(paper.get("title") or "").strip()
        and _paper_has_stable_source(paper)
        and _paper_is_screened_manuscript_evidence(paper)
    ]
    deficit = max(0, minimum_required - len(usable))
    source_artifacts = []
    snapshot = _latest_paper_pool_snapshot_ref(db, topic_id)
    if snapshot is not None:
        source_artifacts.append(snapshot)
    return {
        "schema_version": "rh.schema.evidence.reference_pool.v0",
        "method": "topic_linked_paper_metadata_scan",
        "minimum_required": minimum_required,
        "usable_screened_paper_count": len(usable),
        "linked_paper_count": len(papers),
        "deficit": deficit,
        "passed": deficit == 0,
        "usable_criteria": {
            "title_required": True,
            "stable_source_fields": ["doi", "arxiv_id", "url", "venue", "year"],
            "dismissed_topic_links_excluded": True,
            "screening_status_required": "screened_in",
            "manuscript_eligible_required": True,
            "substantive_content_required": [
                "abstract",
                "compiled_summary",
                "annotated_pdf",
            ],
        },
        "source_artifacts": source_artifacts,
    }


def _interim_boundary(reference_evidence: dict[str, Any]) -> dict[str, Any]:
    minimum = int(reference_evidence.get("minimum_required") or 0)
    usable = int(reference_evidence.get("usable_screened_paper_count") or 0)
    return {
        "title": "Interim Draft Boundary",
        "reason": "reference_pool_below_final_threshold",
        "statement": (
            f"This PDF is an interim draft because RH has {usable} usable screened "
            f"paper(s), below the final-manuscript threshold of {minimum}."
        ),
    }


def _normalize_title_for_match(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def _reference_title(reference: str) -> str:
    text = re.sub(r"^\s*\[\d+\]\s*", "", reference).strip()
    if ". " in text:
        return text.split(". ", 1)[0].strip()
    return text


def _bibtex_escape(value: str) -> str:
    # Specials first: _fix_unicode emits TeX commands whose backslashes and
    # braces must survive.
    return _fix_unicode(
        value.replace("\\", r"\textbackslash{}")
        .replace("{", r"\{")
        .replace("}", r"\}")
        .replace("&", r"\&")
    )


def _reference_year(reference: str) -> str:
    match = re.search(r"\b(19|20)\d{2}\b", reference)
    return match.group(0) if match else ""


def _reference_url(reference: str) -> str:
    match = re.search(r"https?://\S+", reference)
    return match.group(0).rstrip(".,)") if match else ""


def _find_matching_paper(
    reference: str, paper_index: list[dict[str, Any]]
) -> dict[str, Any] | None:
    ref_title = _normalize_title_for_match(_reference_title(reference))
    if not ref_title:
        return None
    best: tuple[int, dict[str, Any] | None] = (0, None)
    for paper in paper_index:
        title = _normalize_title_for_match(str(paper.get("title") or ""))
        if not title:
            continue
        if ref_title == title:
            return paper
        if ref_title in title or title in ref_title:
            score = min(len(ref_title), len(title))
            if score > best[0]:
                best = (score, paper)
    return best[1]


def _references_to_bibtex(references: Any, *, db: Any, topic_id: int) -> list[str]:
    if not isinstance(references, list):
        return []
    paper_index = _topic_paper_index(db, topic_id)
    entries: list[str] = []
    for index, raw in enumerate(references, start=1):
        reference = str(raw).strip()
        if not reference:
            continue
        ref_number_match = re.match(r"^\s*\[(\d+)\]", reference)
        ref_number = int(ref_number_match.group(1)) if ref_number_match else index
        key = f"ref{ref_number}"
        paper = _find_matching_paper(reference, paper_index)
        title = _reference_title(reference)
        year = _reference_year(reference)
        venue = ""
        doi = ""
        url = _reference_url(reference)
        authors = ""
        arxiv_id = ""
        if paper is not None:
            title = str(paper.get("title") or title)
            year = str(paper.get("year") or year)
            venue = str(paper.get("venue") or "")
            doi = str(paper.get("doi") or "")
            arxiv_id = str(paper.get("arxiv_id") or "")
            url = str(paper.get("url") or url)
            authors = authors_to_bibtex(str(paper.get("authors") or ""))
        fields = [f"  title = {{{_bibtex_escape(title)}}}"]
        if authors and authors != "Anonymous":
            fields.append(f"  author = {{{_bibtex_escape(authors)}}}")
        if year:
            fields.append(f"  year = {{{year}}}")
        if venue:
            fields.append(f"  howpublished = {{{_bibtex_escape(venue)}}}")
        if doi:
            fields.append(f"  doi = {{{_bibtex_escape(doi)}}}")
        if arxiv_id:
            fields.append(f"  eprint = {{{_bibtex_escape(arxiv_id)}}}")
        if url:
            fields.append(f"  url = {{{_bibtex_escape(url)}}}")
        entries.append("@misc{" + key + ",\n" + ",\n".join(fields) + "\n}")
    return entries


def _expand_citation_numbers(raw: str) -> list[str]:
    """The numbers inside one bracket, as bibliography keys — or nothing.

    A bibliography is numbered from one, so a bracket holding a zero is prose and
    not a citation list: ``[0, 1]`` is an interval, and reading it as one used to
    invent ``ref0`` and drop the interval on the way. The whole bracket is refused
    together, because a bracket is one thing.
    """
    numbers: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        range_match = re.match(r"^(\d+)\s*(?:--|-)\s*(\d+)$", part)
        if range_match:
            start = int(range_match.group(1))
            end = int(range_match.group(2))
            if start < 1:
                return []
            if start <= end and end - start <= 50:
                numbers.extend(range(start, end + 1))
            continue
        if part.isdigit():
            if int(part) < 1:
                return []
            numbers.append(int(part))
    seen: set[int] = set()
    ordered = []
    for number in numbers:
        if number not in seen:
            seen.add(number)
            ordered.append(f"ref{number}")
    return ordered


def _normalize_numbered_citations_to_natbib(text: str) -> str:
    citation_pattern = re.compile(
        r"(?<![\\\w}])"
        r"\[((?:\d+\s*(?:--|-)\s*\d+|\d+)"
        r"(?:\s*,\s*(?:\d+\s*(?:--|-)\s*\d+|\d+))*)\]"
    )
    latex_option_lines = (
        r"\begin{",
        r"\end{",
        r"\includegraphics",
        r"\bibliography",
        r"\bibliographystyle",
    )

    # Math on the line: $$...$$, $...$ (unescaped), \(...\) and \[...\]. An integer bracket in math is an
    # interval or an index set, never a citation list.
    # ponytail: math spanning lines is not seen; the drafter writes intervals inline.
    math_pattern = re.compile(
        r"(?<!\\)\$\$.*?\$\$|(?<!\\)\$(?:\\.|[^$\\])*\$|\\\((?:.*?)\\\)|\\\[.*?\\\]"
    )

    def rewrite(line: str) -> str:
        spans = [m.span() for m in math_pattern.finditer(line)]

        def repl(match: re.Match[str]) -> str:
            if any(start <= match.start() < end for start, end in spans):
                return match.group(0)
            keys = _expand_citation_numbers(match.group(1))
            if not keys:
                return match.group(0)
            return r"\citep{" + ",".join(keys) + "}"

        return citation_pattern.sub(repl, line)

    normalized_lines = []
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if stripped.startswith("[") or any(
            marker in line for marker in latex_option_lines
        ):
            normalized_lines.append(line)
            continue
        normalized_lines.append(rewrite(line))
    return "".join(normalized_lines)


def _resolve_existing_path(path_value: str, db: Any) -> Path | None:
    if not path_value:
        return None
    raw = Path(path_value).expanduser()
    candidates = [raw]
    if not raw.is_absolute():
        candidates.append(Path.cwd() / raw)
        db_path = Path(getattr(db, "path", getattr(db, "db_path", ".")))
        candidates.append(db_path.expanduser().resolve().parent / raw)
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return None


def _latex_escape_caption(text: str) -> str:
    replacements = [
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
    ]
    for old, new in replacements:
        text = text.replace(old, new)
    return text


def _planned_figure_items(plan_payload: Any) -> list[dict[str, Any]]:
    if not isinstance(plan_payload, dict):
        return []
    raw_items = plan_payload.get("items") or plan_payload.get("figures") or []
    if not isinstance(raw_items, list):
        return []
    items: list[dict[str, Any]] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "figure").lower()
        if "table" in kind:
            continue
        items.append(raw)
    return items


def _collect_publication_figures(
    *,
    db: Any,
    topic_id: int,
    output_dir: Path,
) -> list[dict[str, Any]]:
    plan = _latest_active_artifact(db, topic_id, ("figure_plan",))
    asset = _latest_active_artifact(db, topic_id, ("figure_asset",))
    plan_payload = plan.get("payload") if plan is not None else {}
    asset_payload = asset.get("payload") if asset is not None else {}
    planned_items = _planned_figure_items(plan_payload)
    if not planned_items and isinstance(asset_payload, dict):
        planned_items = [asset_payload]

    figures: list[dict[str, Any]] = []
    used_names: set[str] = set()
    for index, item in enumerate(planned_items, start=1):
        if not isinstance(item, dict):
            continue
        asset_path = str(item.get("asset_path") or "")
        if not asset_path and isinstance(asset_payload, dict):
            asset_path = str(asset_payload.get("asset_path") or "")
        source_path = _resolve_existing_path(asset_path, db)
        if source_path is None:
            continue
        stem = source_path.stem
        suffix = source_path.suffix or ".png"
        target_name = f"{stem}{suffix}"
        counter = 2
        while target_name in used_names:
            target_name = f"{stem}-{counter}{suffix}"
            counter += 1
        used_names.add(target_name)
        target_path = output_dir / target_name
        output_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
        figure_id = str(item.get("figure_id") or f"fig:auto-{index}")
        caption = str(
            item.get("caption")
            or item.get("title")
            or "Research Harness publication figure."
        )
        figures.append(
            {
                "figure_id": figure_id,
                "source_path": str(source_path),
                "copied_path": str(target_path),
                "latex_path": target_name,
                "caption": caption,
                "plan_artifact_id": int(plan["id"]) if plan is not None else 0,
                "asset_artifact_id": int(asset["id"]) if asset is not None else 0,
            }
        )
    return figures


def _figure_latex_block(figures: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for figure in figures:
        label = re.sub(r"[^A-Za-z0-9:._-]+", "-", str(figure["figure_id"]))
        caption = _latex_escape_caption(str(figure["caption"]))
        path = str(figure["latex_path"])
        blocks.append(
            "\n".join(
                [
                    r"\begin{figure*}[t]",
                    r"\centering",
                    rf"\includegraphics[width=0.78\textwidth]{{{path}}}",
                    rf"\caption{{{caption}}}",
                    rf"\label{{{label}}}",
                    r"\end{figure*}",
                ]
            )
        )
    return "\n\n".join(blocks)


def _inject_figures_into_sections(
    sections: dict[str, str], figures: list[dict[str, Any]]
) -> dict[str, str]:
    if not figures:
        return sections
    figure_block = _figure_latex_block(figures)
    updated = dict(sections)
    preferred_keys = ("method", "methodology", "approach", "introduction")
    target_key = next((key for key in preferred_keys if key in updated), "")
    if not target_key:
        target_key = next(iter(updated), "")
    if not target_key:
        return sections
    content = updated[target_key]
    if r"\includegraphics" in content:
        return updated
    anchor = "Research Harness implements"
    if anchor in content:
        updated[target_key] = content.replace(anchor, f"{figure_block}\n\n{anchor}", 1)
    else:
        updated[target_key] = f"{figure_block}\n\n{content}"
    return updated


def _pdf_figure_evidence(
    *,
    pdf_path: str,
    expected_figures: int,
    figures: list[dict[str, Any]],
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "passed": False,
        "expected_figures": expected_figures,
        "detected_images": 0,
        "method": "pymupdf_get_images",
        "figure_ids": [str(item["figure_id"]) for item in figures],
    }
    if not pdf_path or expected_figures <= 0:
        evidence["reason"] = "No compiled PDF or expected figures."
        return evidence
    try:
        import fitz

        doc = fitz.open(pdf_path)
        image_pages: list[int] = []
        image_count = 0
        for page_index, page in enumerate(doc, start=1):
            images = page.get_images(full=True)
            if images:
                image_pages.append(page_index)
                image_count += len(images)
        evidence.update(
            {
                "detected_images": image_count,
                "image_pages": image_pages,
                "page_count": len(doc),
                "passed": image_count >= expected_figures,
            }
        )
    except Exception as exc:
        evidence.update(
            {
                "method": "asset_copy_and_pdf_exists_fallback",
                "passed": Path(pdf_path).exists()
                and all(Path(str(item["copied_path"])).exists() for item in figures),
                "warning": str(exc),
            }
        )
    return evidence


def _anonymization_evidence(
    *, authors: list[str], tex_path: str, target_profile: str
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "passed": False,
        "target_profile": target_profile,
        "authors": authors,
        "checks": [],
    }
    anonymous_author = not authors or all(
        str(author).strip().lower() in {"anonymous", "anonymous authors"}
        for author in authors
    )
    evidence["checks"].append(
        {
            "check": "anonymous_author_block",
            "passed": anonymous_author,
            "details": "Author list is anonymous or empty.",
        }
    )

    tex = ""
    if tex_path and Path(tex_path).exists():
        tex = Path(tex_path).read_text(encoding="utf-8", errors="replace")
    identity_patterns = [
        r"\\thanks\b",
        r"\\affiliation\b",
        r"\\institute\b",
        r"\\email\b",
        r"\bAcknowledg(e)?ments?\b",
        r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}",
    ]
    identity_hits = [
        pattern
        for pattern in identity_patterns
        if tex and re.search(pattern, tex, re.IGNORECASE)
    ]
    no_identity_hits = not identity_hits
    evidence["checks"].append(
        {
            "check": "no_identity_macros_or_email",
            "passed": no_identity_hits,
            "details": "No author affiliation, email, thanks, or acknowledgments markers found.",
            "hits": identity_hits,
        }
    )
    evidence["passed"] = anonymous_author and no_identity_hits
    return evidence


def _bibliography_style_evidence(
    *,
    template: str,
    bibliography_entries: list[str],
    tex_path: str,
    warnings: list[str],
    errors: list[str],
    target_profile: str,
) -> dict[str, Any]:
    tex = ""
    if tex_path and Path(tex_path).exists():
        tex = Path(tex_path).read_text(encoding="utf-8", errors="replace")
    target = target_profile.lower()
    style_match = re.search(r"\\bibliographystyle\{([^}]+)\}", tex)
    style = style_match.group(1) if style_match else ""
    citation_count = len(re.findall(r"\\cite[tp]?\{", tex))
    bibliography_call = bool(re.search(r"\\bibliography\{[^}]+\}", tex))
    empty_bibliography_warning = any(
        "Empty `thebibliography' environment" in warning for warning in warnings
    )
    undefined_citation_warnings = [
        warning
        for warning in warnings
        if "Citation `" in warning and "undefined" in warning
    ]
    has_compile_errors = bool(errors)
    style_label = (
        "aaai-author-year-compatible"
        if "aaai" in target and template == "aaai" and style in {"plainnat", "aaai"}
        else style
    )
    passed = (
        bool(bibliography_entries)
        and citation_count > 0
        and bibliography_call
        and bool(style_label)
        and not empty_bibliography_warning
        and not undefined_citation_warnings
        and not has_compile_errors
    )
    return {
        "passed": passed,
        "target_profile": target_profile,
        "template": template,
        "style": style,
        "style_label": style_label,
        "official_aaai_style": style.startswith("aaai"),
        "bibliography_entries": len(bibliography_entries),
        "citation_commands": citation_count,
        "bibliography_call": bibliography_call,
        "empty_bibliography_warning": empty_bibliography_warning,
        "undefined_citation_warnings": len(undefined_citation_warnings),
        "compile_errors": len(errors),
    }


def _extract_latex_citation_keys(tex: str) -> list[str]:
    keys: list[str] = []
    for match in re.finditer(r"\\cite[a-zA-Z*]*\{([^}]+)\}", tex):
        for raw_key in match.group(1).split(","):
            key = raw_key.strip()
            if key and key not in keys:
                keys.append(key)
    return keys


def _extract_bibtex_keys(bibliography_entries: list[str]) -> list[str]:
    keys: list[str] = []
    for entry in bibliography_entries:
        match = re.search(r"@\w+\{\s*([^,\s]+)\s*,", entry)
        if match:
            key = match.group(1).strip()
            if key and key not in keys:
                keys.append(key)
    return keys


def _citation_integrity_evidence(
    *,
    bibliography_entries: list[str],
    tex_path: str,
    warnings: list[str],
    errors: list[str],
) -> dict[str, Any]:
    tex = ""
    if tex_path and Path(tex_path).exists():
        tex = Path(tex_path).read_text(encoding="utf-8", errors="replace")
    citation_keys = _extract_latex_citation_keys(tex)
    bib_keys = _extract_bibtex_keys(bibliography_entries)
    bib_key_set = set(bib_keys)
    citation_key_set = set(citation_keys)
    missing_bib_keys = [key for key in citation_keys if key not in bib_key_set]
    unused_bib_keys = [key for key in bib_keys if key not in citation_key_set]
    undefined_citation_warnings = [
        warning
        for warning in warnings
        if "Citation `" in warning and "undefined" in warning
    ]
    passed = (
        bool(citation_keys)
        and bool(bib_keys)
        and not missing_bib_keys
        and not undefined_citation_warnings
        and not errors
    )
    return {
        "passed": passed,
        "method": "latex_citation_keys_vs_bibtex_entries",
        "citation_key_count": len(citation_keys),
        "bib_entry_count": len(bib_keys),
        "missing_bib_keys": missing_bib_keys,
        "unused_bib_keys": unused_bib_keys,
        "undefined_citation_warnings": len(undefined_citation_warnings),
        "compile_errors": len(errors),
    }


def _content_page_evidence(pdf_path: str) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "full_pages": 0,
        "content_pages": 0,
        "references_start_page": 0,
        "method": "pymupdf_text_scan",
    }
    if not pdf_path or not Path(pdf_path).exists():
        evidence["reason"] = "No compiled PDF available."
        return evidence
    try:
        import fitz

        doc = fitz.open(pdf_path)
        evidence["full_pages"] = len(doc)
        references_start_page = 0
        content_pages = len(doc)
        for index, page in enumerate(doc, start=1):
            text = page.get_text("text")
            match = re.search(r"(?m)^\s*References\s*$", text)
            if not match:
                continue
            references_start_page = index
            before = text[: match.start()].strip()
            # If references share a page with technical content, that page
            # remains part of the technical page count.
            content_pages = index if before else index - 1
            break
        evidence.update(
            {
                "content_pages": content_pages,
                "references_start_page": references_start_page,
            }
        )
    except Exception as exc:
        evidence["reason"] = str(exc)
    return evidence


def _compiled_final_bundle_payload(
    *,
    db: Any,
    topic_id: int,
    target_profile: str,
) -> dict[str, Any] | None:
    draft = _latest_active_artifact(db, topic_id, ("draft_pack",))
    if draft is None or not isinstance(draft.get("payload"), dict):
        return None

    payload = draft["payload"]
    raw_sections = payload.get("sections")
    if not isinstance(raw_sections, dict):
        return None
    sections = {
        str(key): str(value)
        for key, value in raw_sections.items()
        if str(value).strip()
    }
    if not sections:
        return None

    abstract = str(payload.get("abstract") or "")
    if not abstract and "abstract" in sections:
        abstract = sections.pop("abstract")
    references = payload.get("references")
    bibliography_entries = (
        payload.get("bibliography_entries")
        if isinstance(payload.get("bibliography_entries"), list)
        else _references_to_bibtex(references, db=db, topic_id=topic_id)
    )
    if bibliography_entries:
        abstract = _normalize_numbered_citations_to_natbib(abstract)
        sections = {
            key: _normalize_numbered_citations_to_natbib(value)
            for key, value in sections.items()
        }

    raw_authors = payload.get("authors")
    authors = (
        [str(author) for author in raw_authors if str(author).strip()]
        if isinstance(raw_authors, list)
        else []
    )
    if not authors and _is_venue_specific_profile(target_profile):
        authors = ["Anonymous"]

    template = _template_for_target_profile(target_profile)
    output_dir = _publication_output_dir(db, topic_id, target_profile)
    figures = _collect_publication_figures(
        db=db,
        topic_id=topic_id,
        output_dir=output_dir,
    )
    sections = _inject_figures_into_sections(sections, figures)
    finalized = paper_finalize(
        topic_id=topic_id,
        output_dir=str(output_dir),
        title=str(payload.get("title") or _topic_title(db, topic_id)),
        authors=authors,
        abstract=abstract,
        sections=sections,
        bibliography_entries=bibliography_entries,
        template=template,
    )
    compiled = asdict(finalized)
    figure_evidence = _pdf_figure_evidence(
        pdf_path=finalized.pdf_path,
        expected_figures=len(figures),
        figures=figures,
    )
    anonymization = _anonymization_evidence(
        authors=authors,
        tex_path=finalized.tex_path,
        target_profile=target_profile,
    )
    bibliography_evidence = _bibliography_style_evidence(
        template=template,
        bibliography_entries=bibliography_entries,
        tex_path=finalized.tex_path,
        warnings=finalized.warnings,
        errors=finalized.errors,
        target_profile=target_profile,
    )
    citation_evidence = _citation_integrity_evidence(
        bibliography_entries=bibliography_entries,
        tex_path=finalized.tex_path,
        warnings=finalized.warnings,
        errors=finalized.errors,
    )
    page_evidence = _content_page_evidence(finalized.pdf_path)
    reference_pool = _reference_pool_evidence(db, topic_id)
    finality_status = "final_ready" if reference_pool["passed"] else "interim_ready"
    status = "ready" if finalized.success else "failed"
    if finalized.success and finality_status == "interim_ready":
        status = "ready_interim"
    full_pages = _as_positive_int(page_evidence.get("full_pages")) or finalized.pages
    content_pages = (
        _as_positive_int(page_evidence.get("content_pages")) or finalized.pages
    )
    pages = finalized.pages or full_pages
    if pages and not compiled.get("pages"):
        compiled["pages"] = pages
    return {
        "status": status,
        "finality_status": finality_status if finalized.success else "blocked",
        "is_interim": finalized.success and finality_status == "interim_ready",
        "interim_boundary_page_required": finalized.success
        and finality_status == "interim_ready",
        "interim_boundary": (
            _interim_boundary(reference_pool)
            if finalized.success and finality_status == "interim_ready"
            else {}
        ),
        "target_profile": target_profile,
        "template": template,
        "template_fingerprint": template_fingerprint(template),
        "source_draft_artifact_id": int(draft["id"]),
        "output_dir": str(output_dir),
        "tex_path": finalized.tex_path,
        "bib_path": finalized.bib_path,
        "compiled_pdf_path": finalized.pdf_path,
        "pages": pages,
        "content_pages": content_pages,
        "full_pages": full_pages,
        "word_count": finalized.word_count,
        "sections_assembled": finalized.sections_assembled,
        "warnings": finalized.warnings,
        "errors": finalized.errors,
        "auto_fixes_applied": finalized.auto_fixes_applied,
        "validation_errors": finalized.validation_errors,
        "validation_warnings": finalized.validation_warnings,
        "figure_assets": figures,
        "figure_placement_evidence": figure_evidence,
        "anonymization_evidence": anonymization,
        "citation_integrity_evidence": citation_evidence,
        "bibliography_style_evidence": bibliography_evidence,
        "reference_pool_evidence": reference_pool,
        "page_limit_evidence": page_evidence,
        "paper_finalize": compiled,
    }


def _build_publication_components(
    latest_by_type: dict[str, dict[str, Any]],
) -> dict[str, PublicationPackComponent]:
    components: dict[str, PublicationPackComponent] = {}
    for name, spec in _PUBLICATION_COMPONENT_SPECS.items():
        selected = _select_artifact(latest_by_type, spec["artifact_types"])
        if selected is None:
            components[name] = PublicationPackComponent(
                name=name,
                role=spec["role"],
                required=bool(spec["required"]),
                status="missing",
                artifact_type=spec["artifact_types"][0],
                notes="No active artifact found for this publication-pack slot.",
            )
            continue

        components[name] = PublicationPackComponent(
            name=name,
            role=spec["role"],
            required=bool(spec["required"]),
            status="present",
            artifact_type=selected["artifact_type"],
            artifact_id=int(selected["id"]),
            title=selected["title"],
            source_stage=selected["stage"],
            notes=f"Using latest active {selected['artifact_type']} v{selected['version']}.",
        )
    return components


def _source_artifacts_from_components(
    components: dict[str, PublicationPackComponent],
) -> list[dict[str, Any]]:
    seen: set[int] = set()
    source_artifacts: list[dict[str, Any]] = []
    for component in components.values():
        if component.status != "present" or component.artifact_id in seen:
            continue
        seen.add(component.artifact_id)
        source_artifacts.append(
            {
                "component": component.name,
                "artifact_id": component.artifact_id,
                "artifact_type": component.artifact_type,
                "stage": component.source_stage,
                "title": component.title,
            }
        )
    return source_artifacts


def _publication_contract(target_profile: str) -> dict[str, Any]:
    required = [
        name
        for name, spec in _PUBLICATION_COMPONENT_SPECS.items()
        if bool(spec["required"])
    ]
    optional = [
        name
        for name, spec in _PUBLICATION_COMPONENT_SPECS.items()
        if not bool(spec["required"])
    ]
    return {
        "artifact_type": "publication_pack",
        "target_profile": target_profile,
        "required_components": required,
        "optional_components": optional,
        "must_trace_claims_to": ["paper_id", "claim_id", "artifact_id"],
        "quality_gates": [
            "citation_sanitize",
            "integrity_check",
            "adversarial_review",
            "provenance_review",
            "venue_compliance_check",
        ],
        "generation_policy": {
            "unsupported_claims": "flag_do_not_smooth",
            "citation_policy": "only_current_topic_or_explicit_sources",
            "figure_policy": "contract_first_before_plotting",
            "style_profile_policy": "profile_guides_style_not_evidence",
        },
    }


def _is_venue_specific_profile(target_profile: str) -> bool:
    profile = target_profile.lower()
    return any(
        marker in profile
        for marker in (
            "aaai",
            "neurips",
            "iclr",
            "icml",
            "acl",
            "emnlp",
            "cvpr",
            "kdd",
            "sigir",
            "www",
        )
    )


def _venue_compliance_status(db: Any, topic_id: int) -> tuple[bool, str]:
    artifact = _latest_active_artifact(
        db, topic_id, ("venue_compliance_report", "submission_checklist")
    )
    if artifact is None:
        return False, "missing"
    payload = artifact.get("payload")
    if not isinstance(payload, dict):
        return False, "failed"
    if payload.get("passed") is True:
        return True, "passed"
    status = str(payload.get("status") or payload.get("decision") or "").lower()
    passed = status in {"pass", "passed", "ready", "submission_ready"}
    return passed, "passed" if passed else "failed"


def _publication_orchestrator_readiness(db: Any, topic_id: int) -> dict[str, Any]:
    """Return a submission-facing readiness check from the latest run state.

    Submission-facing publication-pack calls fail closed without an orchestrator
    lifecycle. If a run exists, unresolved upstream stages or non-pass gate states
    must prevent a submission-ready label even when write-stage files are present.
    """

    conn = db.connect()
    try:
        row = conn.execute(
            """
            SELECT current_stage, stage_status, gate_status
            FROM orchestrator_runs
            WHERE topic_id = ?
            ORDER BY id DESC LIMIT 1
            """,
            (topic_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return {
            "check": "orchestrator_readiness",
            "passed": False,
            "lifecycle_verified": False,
            "severity": "blocking",
            "details": (
                "No orchestrator run found; lifecycle readiness is unverified and "
                "submission readiness is blocked."
            ),
        }

    stage = str(row["current_stage"] or "")
    status = str(row["stage_status"] or "")
    gate = str(row["gate_status"] or "")
    stage_ready = stage in {"write", "finalize", "done", "complete", "completed"}
    status_ready = status not in {"blocked", "failed", "error"}
    gate_decision = gate
    if stage in {"write", "finalize"}:
        try:
            from ..orchestrator.transitions import GateEvaluator

            gate_decision = GateEvaluator(db).evaluate(topic_id, "write")
        except Exception:
            gate_decision = gate or "unknown"
    gate_ready = gate_decision in {"pass", "passed", "ready", "complete", "completed"}
    passed = stage_ready and status_ready and gate_ready
    details = (
        "Latest orchestrator run is at a write/finalize-ready stage."
        if passed
        else (
            "Latest orchestrator run is not publication-ready "
            f"(stage={stage or 'unknown'}, status={status or 'unknown'}, "
            f"gate={gate_decision or 'unset'})."
        )
    )
    return {
        "check": "orchestrator_readiness",
        "passed": passed,
        "lifecycle_verified": passed,
        "severity": "blocking",
        "details": details,
    }


def _final_bundle_payload_check(db: Any, topic_id: int) -> dict[str, Any]:
    artifact = _latest_active_artifact(db, topic_id, ("final_bundle",))
    if artifact is None:
        return {
            "passed": False,
            "details": "Record a final_bundle before treating the pack as submission-ready.",
        }
    payload = (
        artifact.get("payload") if isinstance(artifact.get("payload"), dict) else {}
    )
    pdf_path = str(
        payload.get("compiled_pdf_path")
        or payload.get("pdf_path")
        or payload.get("pdf")
        or ""
    ).strip()
    if not pdf_path:
        return {
            "passed": False,
            "details": "Final bundle is present but has no compiled PDF path.",
        }
    finality_status = str(payload.get("finality_status") or payload.get("status") or "")
    if finality_status == "blocked":
        return {
            "passed": False,
            "details": "Final bundle payload is explicitly blocked.",
        }
    path = Path(pdf_path)
    if path.exists() and path.is_file() and path.stat().st_size > 0:
        return {
            "passed": True,
            "details": "Final bundle payload references an existing non-empty PDF.",
        }
    compile_evidence = payload.get("compile_evidence") or payload.get(
        "page_limit_evidence"
    )
    if isinstance(compile_evidence, dict) and compile_evidence.get("passed") is True:
        return {
            "passed": True,
            "details": "Final bundle payload includes passing compile evidence.",
        }
    return {
        "passed": False,
        "details": "Final bundle PDF path is not verified as an existing non-empty file.",
    }


def _publication_qa_checks(
    db: Any,
    topic_id: int,
    target_profile: str,
    components: dict[str, PublicationPackComponent],
    missing_required: list[str],
) -> list[dict[str, Any]]:
    citation_present = components["citation_integrity"].status == "present"
    figure_present = components["figure_plan"].status == "present"
    final_bundle_present = components["final_bundle"].status == "present"
    process_summary_present = components["process_summary"].status == "present"
    venue_specific = _is_venue_specific_profile(target_profile)
    venue_passed_raw, venue_state = _venue_compliance_status(db, topic_id)
    venue_passed = (not venue_specific) or venue_passed_raw
    reference_pool_check = _final_bundle_reference_pool_check(db, topic_id)
    final_bundle_check = _final_bundle_payload_check(db, topic_id)
    return [
        {
            "check": "required_components",
            "passed": not missing_required,
            "severity": "blocking",
            "details": (
                "Required manuscript and evidence artifacts are present."
                if not missing_required
                else f"Missing required components: {', '.join(missing_required)}"
            ),
        },
        {
            "check": "traceability_contract",
            "passed": components["manuscript_sections"].status == "present"
            and components["evidence_pack"].status == "present",
            "severity": "blocking",
            "details": "Draft claims must trace to paper_id, claim_id, and artifact_id.",
        },
        {
            "check": "citation_integrity",
            "passed": citation_present,
            "severity": "warning",
            "details": (
                "Citation/integrity report is available."
                if citation_present
                else "Run citation_sanitize or integrity_check before submission."
            ),
        },
        {
            "check": "figure_contract",
            "passed": figure_present,
            "severity": "warning",
            "details": (
                "Figure plan is available."
                if figure_present
                else "Create a figure_plan before producing publication figures."
            ),
        },
        {
            "check": "final_bundle",
            "passed": final_bundle_present and bool(final_bundle_check["passed"]),
            "severity": "blocking",
            "details": str(final_bundle_check["details"]),
        },
        {
            "check": "provenance_summary",
            "passed": process_summary_present,
            "severity": "warning",
            "details": (
                "Process/provenance summary is available."
                if process_summary_present
                else "Record a process_summary or provenance_review for reviewer handoff."
            ),
        },
        _publication_orchestrator_readiness(db, topic_id),
        {
            "check": "venue_compliance",
            "passed": venue_passed,
            "severity": "blocking" if venue_specific else "info",
            "details": (
                "Venue compliance is not required for this generic profile."
                if not venue_specific
                else (
                    "Venue-specific formatting/checklist report is available and passing."
                    if venue_passed
                    else (
                        "Latest venue compliance report is present but not passing; "
                        "resolve its findings before using a venue-specific "
                        "submission-ready label."
                        if venue_state == "failed"
                        else "Run an AAAI/venue compliance check before using a "
                        "venue-specific submission-ready label."
                    )
                )
            ),
        },
        {
            "check": "reference_pool_gate",
            "passed": bool(reference_pool_check["passed"]),
            "severity": str(reference_pool_check["severity"]),
            "details": str(reference_pool_check["details"]),
            "evidence": reference_pool_check.get("evidence", {}),
        },
    ]


def _publication_next_actions(
    *,
    components: dict[str, PublicationPackComponent],
    missing_required: list[str],
    qa_checks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return deterministic follow-up actions for missing pack obligations."""
    actions: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add_action(component_name: str, severity: str, reason: str) -> None:
        if component_name in seen:
            return
        seen.add(component_name)
        component = components.get(component_name)
        spec = _PUBLICATION_COMPONENT_SPECS.get(component_name, {})
        artifact_types = spec.get("artifact_types", ())
        artifact_type = (
            str(artifact_types[0])
            if isinstance(artifact_types, tuple) and artifact_types
            else component.artifact_type
            if component is not None
            else ""
        )
        template = _PUBLICATION_NEXT_ACTION_TEMPLATES.get(component_name, {})
        actions.append(
            {
                "component": component_name,
                "artifact_type": artifact_type,
                "recommended_tool": template.get("recommended_tool", ""),
                "severity": severity,
                "action": template.get(
                    "action",
                    f"Record or refresh the {component_name} publication-pack component.",
                ),
                "reason": reason,
            }
        )

    for component_name in missing_required:
        component = components.get(component_name)
        add_action(
            component_name,
            "blocking",
            component.notes
            if component is not None and component.notes
            else f"Required component is missing: {component_name}.",
        )

    for check in qa_checks:
        if check.get("passed"):
            continue
        component_name = _PUBLICATION_QA_COMPONENTS.get(str(check.get("check", "")))
        if not component_name:
            continue
        add_action(
            component_name,
            str(check.get("severity") or "warning"),
            str(check.get("details") or ""),
        )

    return actions


def _source_entry(artifact: dict[str, Any] | None, component: str) -> dict[str, Any]:
    if artifact is None:
        return {
            "component": component,
            "status": "missing",
        }
    return {
        "component": component,
        "artifact_id": int(artifact["id"]),
        "artifact_type": artifact["artifact_type"],
        "stage": artifact["stage"],
        "title": artifact["title"],
    }


def _payload_status_passed(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("passed") is True:
        return True
    status = str(payload.get("status") or payload.get("decision") or "").lower()
    return status in {"pass", "passed", "ready", "submission_ready", "approved"}


def _first_payload_value(payload: Any, keys: set[str]) -> Any:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in keys and value not in (None, ""):
                return value
        for value in payload.values():
            found = _first_payload_value(value, keys)
            if found not in (None, ""):
                return found
    elif isinstance(payload, list):
        for item in payload:
            found = _first_payload_value(item, keys)
            if found not in (None, ""):
                return found
    return None


def _as_positive_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.isdigit() and int(value) > 0:
        return int(value)
    return 0


def _default_page_limit(target_profile: str) -> int:
    profile = target_profile.lower()
    if "aaai" in profile:
        return 7
    if any(marker in profile for marker in ("acl", "emnlp", "naacl")):
        return 8
    if any(marker in profile for marker in ("neurips", "iclr", "icml")):
        return 9
    return 0


def _compliance_check(
    *,
    check: str,
    passed: bool,
    finding: str,
    action: str,
    artifact_id: int = 0,
) -> dict[str, Any]:
    return {
        "check": check,
        "passed": passed,
        "severity": "none" if passed else "blocking",
        "finding": finding,
        "action": "" if passed else action,
        "artifact_id": artifact_id,
    }


def _unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        normalized = str(value).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


def _strip_latex_comments(src: str) -> str:
    return "\n".join(_LATEX_COMMENT_RE.sub("", line) for line in src.splitlines())


def _read_optional_text(path_value: str) -> str:
    if not path_value:
        return ""
    try:
        path = Path(path_value).expanduser()
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _venue_disallowed_packages(target_profile: str) -> frozenset[str]:
    profile = target_profile.lower()
    if "aaai" in profile or "iaai" in profile:
        return _AAAI_DISALLOWED_PACKAGES
    return frozenset()


def _venue_disallowed_commands(target_profile: str) -> tuple[str, ...]:
    profile = target_profile.lower()
    if "aaai" in profile or "iaai" in profile:
        return _AAAI_DISALLOWED_COMMANDS
    return (r"\write18",)


def _payload_path(payload: dict[str, Any], names: tuple[str, ...]) -> str:
    for name in names:
        value = payload.get(name)
        if isinstance(value, str) and value.strip():
            return value
    paper_finalize = payload.get("paper_finalize")
    if isinstance(paper_finalize, dict):
        for name in names:
            value = paper_finalize.get(name)
            if isinstance(value, str) and value.strip():
                return value
    return ""


def _infer_latex_log_path(payload: dict[str, Any], tex_path: str) -> str:
    log_path = _payload_path(payload, ("log_path", "latex_log_path"))
    if log_path:
        return log_path
    output_dir = _payload_path(payload, ("output_dir",))
    if output_dir:
        return str(Path(output_dir).expanduser() / "paper.log")
    return str(Path(tex_path).expanduser().with_suffix(".log")) if tex_path else ""


def _latex_reference_exists(
    *,
    command: str,
    raw_path: str,
    tex_dir: Path,
) -> bool:
    if not raw_path or raw_path.startswith(("http://", "https://")):
        return True
    if any(marker in raw_path for marker in ("{", "}", "\\")):
        return True

    path = Path(raw_path).expanduser()
    base = path if path.is_absolute() else tex_dir / path
    candidates = [base]
    if not base.suffix:
        if command == "includegraphics":
            candidates.extend(
                base.with_suffix(suffix) for suffix in _LATEX_GRAPHICS_EXTENSIONS
            )
        else:
            candidates.append(base.with_suffix(".tex"))
    return any(candidate.exists() for candidate in candidates)


def _latex_source_missing_files(tex: str, tex_dir: Path) -> list[str]:
    missing: list[str] = []
    for match in _LATEX_FILE_COMMAND_RE.finditer(tex):
        command = match.group(1)
        raw_path = match.group(2).strip()
        if not _latex_reference_exists(
            command=command,
            raw_path=raw_path,
            tex_dir=tex_dir,
        ):
            missing.append(raw_path)
    return _unique_strings(missing)


def _latex_source_lint(
    *,
    final_bundle_payload: dict[str, Any],
    target_profile: str,
) -> dict[str, Any]:
    tex_path = _payload_path(final_bundle_payload, ("tex_path",))
    log_path = _infer_latex_log_path(final_bundle_payload, tex_path)
    tex = _strip_latex_comments(_read_optional_text(tex_path))
    log = _read_optional_text(log_path)
    disallowed_packages = _venue_disallowed_packages(target_profile)
    disallowed_commands = _venue_disallowed_commands(target_profile)

    package_hits: list[str] = []
    for match in _LATEX_PACKAGE_RE.finditer(tex):
        for raw_package in match.group(1).split(","):
            package = raw_package.strip().lower()
            if package in disallowed_packages:
                package_hits.append(package)

    command_hits: list[str] = []
    for command in disallowed_commands:
        if command.endswith("="):
            found = command in tex
        else:
            found = re.search(re.escape(command) + r"(?![A-Za-z])", tex) is not None
        if found:
            command_hits.append(command)

    tex_dir = Path(tex_path).expanduser().parent if tex_path else Path.cwd()
    source_missing = _latex_source_missing_files(tex, tex_dir)
    log_missing = _LOG_MISSING_FILE_RE.findall(log)
    undefined_citations = _LOG_UNDEFINED_CITATION_RE.findall(log)
    undefined_references = _LOG_UNDEFINED_REFERENCE_RE.findall(log)
    overfull_warnings = [
        line.strip()
        for line in log.splitlines()
        if re.search(r"Overfull \\[hv]box", line)
    ]
    blocking = bool(
        package_hits
        or command_hits
        or source_missing
        or log_missing
        or undefined_citations
        or undefined_references
    )
    return {
        "passed": not blocking,
        "tex_path": tex_path,
        "log_path": log_path,
        "disallowed_packages": _unique_strings(package_hits),
        "disallowed_commands": _unique_strings(command_hits),
        "missing_files": _unique_strings([*source_missing, *log_missing]),
        "undefined_citations": _unique_strings(undefined_citations),
        "undefined_references": _unique_strings(undefined_references),
        "overfull_box_warnings": _unique_strings(overfull_warnings),
    }


def _infer_compiled_pdf_path(
    final_bundle: dict[str, Any] | None,
    compiled_pdf_path: str,
) -> str:
    if compiled_pdf_path:
        return compiled_pdf_path
    if final_bundle is None:
        return ""
    payload = final_bundle.get("payload")
    found = _first_payload_value(
        payload,
        {
            "compiled_pdf_path",
            "pdf_path",
            "paper_pdf",
            "submission_pdf",
            "pdf",
        },
    )
    if isinstance(found, str):
        return found
    path = str(final_bundle.get("path") or "")
    return path if path.lower().endswith(".pdf") else ""


def _infer_page_count(
    final_bundle: dict[str, Any] | None,
    page_count: int | None,
) -> int:
    explicit = _as_positive_int(page_count)
    if explicit:
        return explicit
    if final_bundle is None:
        return 0
    found = _first_payload_value(
        final_bundle.get("payload"),
        {"page_count", "pages", "compiled_pages"},
    )
    return _as_positive_int(found)


def _references_excluded_from_page_limit(target_profile: str) -> bool:
    profile = target_profile.lower()
    return any(marker in profile for marker in ("aaai", "iaai"))


def _infer_technical_page_count(
    final_bundle: dict[str, Any] | None,
    page_count: int | None,
    target_profile: str,
) -> tuple[int, dict[str, Any]]:
    if page_count is not None:
        explicit = _as_positive_int(page_count)
        return explicit, {"source": "explicit_page_count", "content_pages": explicit}
    if final_bundle is None:
        return 0, {}
    payload = final_bundle.get("payload")
    if not isinstance(payload, dict):
        return 0, {}
    evidence = payload.get("page_limit_evidence")
    if _references_excluded_from_page_limit(target_profile) and isinstance(
        evidence, dict
    ):
        content_pages = _as_positive_int(evidence.get("content_pages"))
        if content_pages:
            return content_pages, evidence
    pages = _infer_page_count(final_bundle, page_count)
    return pages, {"source": "compiled_pages", "content_pages": pages}


def _final_bundle_has_compiled_pdf(final_bundle: dict[str, Any] | None) -> bool:
    pdf_path = _infer_compiled_pdf_path(final_bundle, "")
    return bool(pdf_path) and Path(pdf_path).expanduser().exists()


def _final_bundle_has_figure_evidence(final_bundle: dict[str, Any] | None) -> bool:
    if final_bundle is None:
        return False
    payload = final_bundle.get("payload")
    if not isinstance(payload, dict):
        return False
    evidence = payload.get("figure_placement_evidence")
    return isinstance(evidence, dict) and evidence.get("passed") is True


def _final_bundle_has_submission_evidence(final_bundle: dict[str, Any] | None) -> bool:
    if final_bundle is None:
        return False
    payload = final_bundle.get("payload")
    if not isinstance(payload, dict):
        return False
    if payload.get("status") == "failed":
        return False
    if payload.get("errors"):
        return False
    finalize_payload = payload.get("paper_finalize")
    if isinstance(finalize_payload, dict) and finalize_payload.get("errors"):
        return False
    required = (
        "page_limit_evidence",
        "anonymization_evidence",
        "bibliography_style_evidence",
    )
    if not all(isinstance(payload.get(key), dict) for key in required):
        return False
    return (
        payload["anonymization_evidence"].get("passed") is True
        and payload["bibliography_style_evidence"].get("passed") is True
        and _as_positive_int(payload["page_limit_evidence"].get("content_pages")) > 0
    )


def _final_bundle_has_pdf_quality_regression(
    final_bundle: dict[str, Any] | None,
) -> bool:
    if final_bundle is None:
        return False
    payload = final_bundle.get("payload")
    if not isinstance(payload, dict):
        return False

    paper_finalize_payload = payload.get("paper_finalize")
    if not isinstance(paper_finalize_payload, dict):
        paper_finalize_payload = {}

    tex_path = str(
        payload.get("tex_path") or paper_finalize_payload.get("tex_path") or ""
    )
    pdf_path = _infer_compiled_pdf_path(final_bundle, "")
    output_dir = str(payload.get("output_dir") or "")
    log_path = str(
        payload.get("log_path") or paper_finalize_payload.get("log_path") or ""
    )
    if not log_path:
        if output_dir:
            log_path = str(Path(output_dir) / "paper.log")
        elif tex_path:
            log_path = str(Path(tex_path).with_suffix(".log"))

    if not tex_path and not log_path:
        return False

    from ..evolution.harness import scan_pdf_quality_bundle

    signal = scan_pdf_quality_bundle(
        tex_path=tex_path,
        pdf_path=pdf_path,
        log_path=log_path,
        topic_id=int(final_bundle.get("topic_id") or 0),
        target_profile=str(payload.get("target_profile") or ""),
        artifact_id=int(final_bundle.get("id") or 0),
    )
    recompile_repairable = {
        "invalid_utf8",
        "latex_error",
        "malformed_latex_command",
        "missing_pdf",
        "missing_tex",
        "undefined_citation",
        "undefined_control_sequence",
    }
    return any(issue.category in recompile_repairable for issue in signal.issues)


def _final_bundle_has_page_metadata_gap(final_bundle: dict[str, Any] | None) -> bool:
    if final_bundle is None:
        return False
    payload = final_bundle.get("payload")
    if not isinstance(payload, dict):
        return False
    if _as_positive_int(payload.get("pages")):
        return False
    page_evidence = payload.get("page_limit_evidence")
    if not isinstance(page_evidence, dict):
        return False
    return bool(
        _as_positive_int(page_evidence.get("full_pages"))
        or _as_positive_int(page_evidence.get("content_pages"))
    )


def _final_bundle_has_template_policy_gap(
    final_bundle: dict[str, Any] | None,
    target_profile: str,
) -> bool:
    if final_bundle is None:
        return False
    payload = final_bundle.get("payload")
    if not isinstance(payload, dict):
        return False
    template = _template_for_target_profile(target_profile)
    return payload.get("template_fingerprint") != template_fingerprint(template)


def _artifact_newer_than(
    source: dict[str, Any] | None, target: dict[str, Any] | None
) -> bool:
    if source is None or target is None:
        return False
    source_created = str(source.get("created_at") or "")
    target_created = str(target.get("created_at") or "")
    if source_created and target_created and source_created != target_created:
        return source_created > target_created
    return int(source.get("id") or 0) > int(target.get("id") or 0)


def _final_bundle_needs_venue_refresh(
    db: Any, topic_id: int, target_profile: str
) -> bool:
    if not _is_venue_specific_profile(target_profile):
        return False
    final_bundle = _latest_active_artifact(db, topic_id, ("final_bundle",))
    draft = _latest_active_artifact(db, topic_id, ("draft_pack",))
    if _artifact_newer_than(draft, final_bundle):
        return True
    if not _final_bundle_has_compiled_pdf(final_bundle):
        return True
    if not _final_bundle_has_submission_evidence(final_bundle):
        return True
    if _final_bundle_has_template_policy_gap(final_bundle, target_profile):
        return True
    if _final_bundle_has_page_metadata_gap(final_bundle):
        return True
    if _final_bundle_has_pdf_quality_regression(final_bundle):
        return True
    figure_plan = _latest_active_artifact(db, topic_id, ("figure_plan",))
    figure_asset = _latest_active_artifact(db, topic_id, ("figure_asset",))
    if _artifact_newer_than(figure_plan, final_bundle) or _artifact_newer_than(
        figure_asset, final_bundle
    ):
        return True
    has_figure_input = figure_plan is not None or figure_asset is not None
    return has_figure_input and not _final_bundle_has_figure_evidence(final_bundle)


@register_primitive(VENUE_COMPLIANCE_CHECK_SPEC)
def venue_compliance_check(
    *,
    db: Any,
    topic_id: int,
    target_profile: str = "AAAI-style",
    compiled_pdf_path: str = "",
    page_count: int | None = None,
    page_limit: int | None = None,
    anonymous: bool | None = None,
    bibliography_style: str = "",
    figure_qa_passed: bool | None = None,
    human_review_approved: bool | None = None,
    record_artifact: bool = True,
    **_: Any,
) -> VenueComplianceCheckOutput:
    """Run deterministic venue compliance checks and optionally persist the report."""
    if not _topic_exists(db, topic_id):
        raise ValueError(f"Topic not found: {topic_id}")

    draft = _latest_active_artifact(db, topic_id, ("draft_pack",))
    citation = _latest_active_artifact(
        db,
        topic_id,
        ("citation_sanitization_report", "final_integrity_report"),
    )
    final_bundle = _latest_active_artifact(db, topic_id, ("final_bundle",))
    figure_plan = _latest_active_artifact(db, topic_id, ("figure_plan",))
    figure_asset = _latest_active_artifact(db, topic_id, ("figure_asset",))
    scholarly_review = _latest_active_artifact(
        db,
        topic_id,
        ("scholarly_review_report", "review_bundle", "final_integrity_report"),
    )

    source_artifacts = [
        _source_entry(draft, "manuscript_sections"),
        _source_entry(citation, "citation_integrity"),
        _source_entry(final_bundle, "final_bundle"),
        _source_entry(figure_plan, "figure_plan"),
        _source_entry(figure_asset, "figure_asset"),
        _source_entry(scholarly_review, "scholarly_review"),
    ]

    checks: list[dict[str, Any]] = []
    draft_sections = {}
    if draft is not None and isinstance(draft.get("payload"), dict):
        sections = draft["payload"].get("sections")
        if isinstance(sections, dict):
            draft_sections = {k: v for k, v in sections.items() if str(v).strip()}
    checks.append(
        _compliance_check(
            check="manuscript_sections",
            passed=bool(draft_sections),
            finding=(
                "Draft sections are present."
                if draft_sections
                else "No active draft_pack with concrete sections was found."
            ),
            action="Record or refresh draft_pack sections before venue submission QA.",
            artifact_id=int(draft["id"]) if draft is not None else 0,
        )
    )

    final_bundle_payload = (
        final_bundle.get("payload") if final_bundle is not None else {}
    )
    if not isinstance(final_bundle_payload, dict):
        final_bundle_payload = {}
    latex_lint = _latex_source_lint(
        final_bundle_payload=final_bundle_payload,
        target_profile=target_profile,
    )
    citation_payload = citation.get("payload") if citation is not None else {}
    removed_count = (
        _as_positive_int(citation_payload.get("removed_count"))
        if isinstance(citation_payload, dict)
        else 0
    )
    citation_passed = citation is not None and removed_count == 0
    if isinstance(citation_payload, dict) and citation_payload.get("status") == "fail":
        citation_passed = False
    final_citation_evidence = (
        final_bundle_payload.get("citation_integrity_evidence")
        if isinstance(final_bundle_payload, dict)
        else None
    )
    if isinstance(final_citation_evidence, dict):
        citation_passed = (
            citation_passed and final_citation_evidence.get("passed") is True
        )
    checks.append(
        _compliance_check(
            check="citation_integrity",
            passed=citation_passed,
            finding=(
                "Citation QA artifact has zero removals and final bundle citation keys resolve against BibTeX entries."
                if citation_passed and isinstance(final_citation_evidence, dict)
                else "Citation sanitization/integrity artifact is present with zero removed citations."
                if citation_passed
                else (
                    "Citation QA artifact is missing."
                    if citation is None
                    else "Final bundle citation keys do not resolve against BibTeX entries."
                    if isinstance(final_citation_evidence, dict)
                    and final_citation_evidence.get("passed") is not True
                    else f"Citation QA removed {removed_count} citation(s) or did not pass."
                )
            ),
            action="Run citation_sanitize/integrity_check and resolve removed or hallucinated citations.",
            artifact_id=int(citation["id"]) if citation is not None else 0,
        )
    )

    final_bundle_failed = False
    if isinstance(final_bundle_payload, dict):
        final_bundle_failed = final_bundle_payload.get("status") == "failed" or bool(
            final_bundle_payload.get("errors")
        )
        finalize_payload = final_bundle_payload.get("paper_finalize")
        if isinstance(finalize_payload, dict) and finalize_payload.get("errors"):
            final_bundle_failed = True

    pdf_path = _infer_compiled_pdf_path(final_bundle, compiled_pdf_path)
    pdf_exists = bool(pdf_path) and Path(pdf_path).expanduser().exists()
    latex_compile_success = pdf_exists and not final_bundle_failed
    checks.append(
        _compliance_check(
            check="venue_pdf_compile",
            passed=latex_compile_success,
            finding=(
                f"Venue-formatted PDF exists: {pdf_path}"
                if latex_compile_success
                else "Venue-formatted PDF exists but the final bundle records compile errors."
                if pdf_exists
                else "No compiled venue-formatted PDF artifact was found."
            ),
            action="Compile the refreshed manuscript with the target venue template and record the PDF path.",
            artifact_id=int(final_bundle["id"]) if final_bundle is not None else 0,
        )
    )

    effective_page_limit = page_limit or _default_page_limit(target_profile)
    pages, page_evidence = _infer_technical_page_count(
        final_bundle, page_count, target_profile
    )
    full_pages = _as_positive_int(page_evidence.get("full_pages"))
    references_start = _as_positive_int(page_evidence.get("references_start_page"))
    page_passed = pages > 0 and (
        effective_page_limit <= 0 or pages <= effective_page_limit
    )
    checks.append(
        _compliance_check(
            check="page_limit",
            passed=page_passed,
            finding=(
                (
                    f"Compiled paper has {pages} technical-content page(s), "
                    f"within limit {effective_page_limit}; full PDF has "
                    f"{full_pages or pages} page(s), references start on page "
                    f"{references_start}."
                )
                if page_passed
                and effective_page_limit > 0
                and _references_excluded_from_page_limit(target_profile)
                else (
                    f"Compiled paper has {pages} page(s), within limit {effective_page_limit}."
                    if page_passed and effective_page_limit > 0
                    else f"Compiled paper has {pages} page(s)."
                    if page_passed
                    else (
                        "No compiled page count is available."
                        if pages <= 0
                        else f"Compiled paper has {pages} page(s), exceeding limit {effective_page_limit}."
                    )
                )
            ),
            action="Measure the venue-template PDF page count and reduce the manuscript if it exceeds the limit.",
            artifact_id=int(final_bundle["id"]) if final_bundle is not None else 0,
        )
    )

    lint_blocking_kinds = [
        label
        for label, values in (
            ("disallowed packages", latex_lint["disallowed_packages"]),
            ("disallowed commands", latex_lint["disallowed_commands"]),
            ("missing files", latex_lint["missing_files"]),
            ("undefined citations", latex_lint["undefined_citations"]),
            ("undefined references", latex_lint["undefined_references"]),
        )
        if values
    ]
    lint_warning_count = len(latex_lint["overfull_box_warnings"])
    checks.append(
        _compliance_check(
            check="venue_source_lint",
            passed=bool(latex_lint["passed"]),
            finding=(
                "LaTeX source/log lint passed"
                + (
                    f" with {lint_warning_count} overfull box warning(s)."
                    if lint_warning_count
                    else "."
                )
                if latex_lint["passed"]
                else "LaTeX source/log lint found "
                + ", ".join(lint_blocking_kinds)
                + (
                    f" and {lint_warning_count} overfull box warning(s)."
                    if lint_warning_count
                    else "."
                )
            ),
            action=(
                "Remove disallowed venue packages/commands, resolve missing "
                "LaTeX inputs, and fix undefined citations or references."
            ),
            artifact_id=int(final_bundle["id"]) if final_bundle is not None else 0,
        )
    )

    anonymization_evidence = final_bundle_payload.get("anonymization_evidence")
    inferred_anonymous = (
        isinstance(anonymization_evidence, dict)
        and anonymization_evidence.get("passed") is True
    )
    anonymization_passed = anonymous is True or (
        anonymous is None and inferred_anonymous
    )
    checks.append(
        _compliance_check(
            check="anonymization",
            passed=anonymization_passed,
            finding=(
                "Anonymization/double-blind checklist was marked as passed."
                if anonymous is True
                else "Deterministic anonymization evidence is passing."
                if anonymization_passed
                else "No passing anonymization/double-blind checklist was provided."
            ),
            action="Run the target venue anonymization and submission checklist.",
        )
    )

    target = target_profile.lower()
    style = bibliography_style.lower().strip()
    bibliography_evidence = (
        final_bundle_payload.get("bibliography_style_evidence")
        if isinstance(final_bundle_payload, dict)
        else None
    )
    inferred_style = (
        isinstance(bibliography_evidence, dict)
        and bibliography_evidence.get("passed") is True
        and str(bibliography_evidence.get("style_label") or "").strip()
    )
    bibliography_passed = (
        bool(style)
        and (
            style in target or target in style or ("aaai" in target and "aaai" in style)
        )
    ) or bool(inferred_style)
    style_label = (
        bibliography_style
        if bibliography_style
        else str(bibliography_evidence.get("style_label") or "")
        if isinstance(bibliography_evidence, dict)
        else ""
    )
    checks.append(
        _compliance_check(
            check="bibliography_style",
            passed=bibliography_passed,
            finding=(
                f"Bibliography style is marked as {style_label}."
                if bibliography_passed
                else "No target-venue bibliography style validation was provided."
            ),
            action="Validate BibTeX and bibliography style under the target venue template.",
        )
    )

    figure_evidence = (
        final_bundle_payload.get("figure_placement_evidence")
        if isinstance(final_bundle_payload, dict)
        else None
    )
    figure_passed = figure_qa_passed is True
    if figure_qa_passed is None and isinstance(figure_evidence, dict):
        figure_passed = figure_evidence.get("passed") is True
    has_figure_artifact = figure_asset is not None or figure_plan is not None
    checks.append(
        _compliance_check(
            check="figure_placement",
            passed=figure_passed,
            finding=(
                "Figure placement and legibility in the compiled PDF were marked as passed."
                if figure_qa_passed is True
                else "Compiled PDF contains planned figure asset(s) with deterministic placement evidence."
                if figure_passed
                else (
                    "Figure artifacts exist, but compiled-PDF placement and legibility were not verified."
                    if has_figure_artifact
                    else "No figure plan or figure asset is available for venue QA."
                )
            ),
            action="Verify figure placement, caption readability, and legibility in the compiled venue PDF.",
            artifact_id=int(figure_asset["id"])
            if figure_asset is not None
            else int(figure_plan["id"])
            if figure_plan is not None
            else 0,
        )
    )

    human_passed = human_review_approved is True
    scholarly_review_stale = False
    if human_review_approved is None and scholarly_review is not None:
        scholarly_review_stale = _artifact_newer_than(
            final_bundle, scholarly_review
        ) or _artifact_newer_than(draft, scholarly_review)
        human_passed = (
            _payload_status_passed(scholarly_review.get("payload"))
            and not scholarly_review_stale
        )
    checks.append(
        _compliance_check(
            check="human_scholarly_review",
            passed=human_passed,
            finding=(
                "Final scholarly/human review is approved."
                if human_passed
                else "Final scholarly/human review is stale relative to the current manuscript or final bundle."
                if scholarly_review_stale
                else "No final scholarly/human review approval is recorded."
            ),
            action="Run final human or independent scholarly review and record approval.",
            artifact_id=int(scholarly_review["id"])
            if scholarly_review is not None
            else 0,
        )
    )

    blocking_findings = [check for check in checks if not check["passed"]]
    next_actions = [
        str(check["action"]) for check in blocking_findings if check.get("action")
    ]
    blockers = [
        f"{check['check']}:failed"
        for check in blocking_findings
        if str(check.get("check") or "").strip()
    ]
    output = VenueComplianceCheckOutput(
        topic_id=topic_id,
        target_profile=target_profile,
        status="pass" if not blocking_findings else "fail",
        passed=not blocking_findings,
        checks=checks,
        blocking_findings=blocking_findings,
        next_actions=next_actions,
        source_artifacts=source_artifacts,
        schema_version=VENUE_COMPLIANCE_REPORT_SCHEMA_VERSION,
        latex_compile_success=latex_compile_success,
        disallowed_packages=latex_lint["disallowed_packages"],
        disallowed_commands=latex_lint["disallowed_commands"],
        missing_files=latex_lint["missing_files"],
        undefined_citations=latex_lint["undefined_citations"],
        undefined_references=latex_lint["undefined_references"],
        overfull_box_warnings=latex_lint["overfull_box_warnings"],
        main_text_page_count=pages if pages > 0 else None,
        page_limit=effective_page_limit if effective_page_limit > 0 else None,
        references_appendix_excluded=_references_excluded_from_page_limit(
            target_profile
        )
        or references_start > 0,
        blockers=blockers,
    )

    if not record_artifact:
        return output

    from ..orchestrator.artifacts import ArtifactManager

    artifact_manager = ArtifactManager(db)
    artifact = artifact_manager.record(
        topic_id=topic_id,
        stage="write",
        artifact_type="venue_compliance_report",
        title=f"Venue Compliance Report ({target_profile})",
        payload=asdict(output),
        metadata={
            "generated_by": "venue_compliance_check",
            "target_profile": target_profile,
            "status": output.status,
            "blocking_count": len(blocking_findings),
        },
    )
    dependency_ids = {
        int(item["artifact_id"])
        for item in source_artifacts
        if isinstance(item.get("artifact_id"), int) and item["artifact_id"] > 0
    }
    for artifact_id in sorted(dependency_ids):
        artifact_manager.add_dependency(
            from_artifact_id=artifact_id,
            to_artifact_id=artifact.id,
            dependency_type="consumed_by",
        )
    output = replace(output, venue_compliance_report_artifact_id=artifact.id)
    conn = db.connect()
    try:
        conn.execute(
            """
            UPDATE project_artifacts
            SET payload_json = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (json.dumps(asdict(output), ensure_ascii=False), artifact.id),
        )
        conn.commit()
    finally:
        conn.close()
    return output


@register_primitive(PUBLICATION_PACK_GENERATE_SPEC)
def publication_pack_generate(
    *,
    db: Any,
    topic_id: int,
    target_profile: str = "high-impact-general",
    record_artifact: bool = False,
    **_: Any,
) -> PublicationPackOutput:
    """Build a publication-pack contract from the latest topic artifacts.

    This is intentionally deterministic and non-generative: it inventories the
    evidence-bearing artifacts RH already has, then records what is present,
    what is missing, and which checks must run before submission-facing output.
    """
    if not _topic_exists(db, topic_id):
        raise ValueError(f"Topic not found: {topic_id}")

    latest_by_type = _latest_active_artifacts(db, topic_id)
    components = _build_publication_components(latest_by_type)
    missing_required = [
        name
        for name, component in components.items()
        if component.required and component.status != "present"
    ]
    missing_optional = [
        name
        for name, component in components.items()
        if not component.required and component.status != "present"
    ]
    source_artifacts = _source_artifacts_from_components(components)
    contract = _publication_contract(target_profile)
    qa_checks = _publication_qa_checks(
        db=db,
        topic_id=topic_id,
        target_profile=target_profile,
        components=components,
        missing_required=missing_required,
    )
    next_actions = _publication_next_actions(
        components=components,
        missing_required=missing_required,
        qa_checks=qa_checks,
    )
    provenance_map = {
        name: {
            "artifact_id": component.artifact_id,
            "artifact_type": component.artifact_type,
            "status": component.status,
        }
        for name, component in components.items()
    }
    qa_by_name = {str(check.get("check") or ""): check for check in qa_checks}
    artifact_review_ready = not missing_required
    layout_review_ready = artifact_review_ready and bool(
        qa_by_name.get("final_bundle", {}).get("passed")
    )
    scientific_review_ready = (
        artifact_review_ready
        and bool(qa_by_name.get("traceability_contract", {}).get("passed"))
        and bool(qa_by_name.get("reference_pool_gate", {}).get("passed"))
    )
    lifecycle_closed = bool(
        qa_by_name.get("orchestrator_readiness", {}).get("lifecycle_verified")
    )
    submission_ready = (
        artifact_review_ready
        and layout_review_ready
        and scientific_review_ready
        and lifecycle_closed
        and all(bool(check["passed"]) for check in qa_checks)
    )

    output = PublicationPackOutput(
        topic_id=topic_id,
        target_profile=target_profile,
        ready_for_review=artifact_review_ready,
        artifact_review_ready=artifact_review_ready,
        layout_review_ready=layout_review_ready,
        scientific_review_ready=scientific_review_ready,
        lifecycle_closed=lifecycle_closed,
        submission_ready=submission_ready,
        components=components,
        source_artifacts=source_artifacts,
        missing_required=missing_required,
        missing_optional=missing_optional,
        qa_checks=qa_checks,
        next_actions=next_actions,
        contract=contract,
        provenance_map=provenance_map,
    )

    if not record_artifact:
        return output

    from ..orchestrator.artifacts import ArtifactManager

    artifact = ArtifactManager(db).record(
        topic_id=topic_id,
        stage="write",
        artifact_type="publication_pack",
        title=f"Publication Pack ({target_profile})",
        payload=asdict(output),
        metadata={"generated_by": "publication_pack_generate"},
    )
    if artifact is None:
        return output
    output = replace(output, publication_pack_artifact_id=artifact.id)
    conn = db.connect()
    try:
        conn.execute(
            """
            UPDATE project_artifacts
            SET payload_json = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (json.dumps(asdict(output), ensure_ascii=False), artifact.id),
        )
        conn.commit()
    finally:
        conn.close()
    return output


_SAFE_PUBLICATION_BACKFILL_COMPONENTS = (
    "citation_integrity",
    "process_summary",
    "final_bundle",
)


@register_primitive(PUBLICATION_PACK_BACKFILL_SPEC)
def publication_pack_backfill(
    *,
    db: Any,
    topic_id: int,
    target_profile: str = "high-impact-general",
    components: list[str] | tuple[str, ...] | None = None,
    record_artifact: bool = True,
    **_: Any,
) -> PublicationPackBackfillOutput:
    """Execute deterministic publication-pack closure actions.

    This primitive intentionally avoids inventing scientific content. It only
    backfills local, evidence-bound artifacts that can be produced without an
    LLM: citation sanitization, process summary, final bundle, and an updated
    publication_pack. Missing evidence/manuscript and figure-planning work is
    reported as remaining next actions for dedicated primitives or humans.
    """
    if not _topic_exists(db, topic_id):
        raise ValueError(f"Topic not found: {topic_id}")

    requested = tuple(components or _SAFE_PUBLICATION_BACKFILL_COMPONENTS)
    before = publication_pack_generate(
        db=db,
        topic_id=topic_id,
        target_profile=target_profile,
        record_artifact=False,
    )
    created_artifacts: list[dict[str, Any]] = []
    skipped_actions: list[dict[str, Any]] = []

    def record_created(component: str, artifact: Any) -> None:
        created_artifacts.append(
            {
                "component": component,
                "artifact_id": int(getattr(artifact, "id", 0)),
                "artifact_type": str(getattr(artifact, "artifact_type", "")),
                "stage": str(getattr(artifact, "stage", "")),
                "title": str(getattr(artifact, "title", "")),
            }
        )

    def skip(component: str, reason: str) -> None:
        skipped_actions.append({"component": component, "reason": reason})

    if before.missing_required:
        skip(
            "required_components",
            "Cannot backfill submission QA until manuscript_sections and evidence_pack are present.",
        )
        return PublicationPackBackfillOutput(
            topic_id=topic_id,
            target_profile=target_profile,
            created_count=0,
            created_artifacts=[],
            skipped_actions=skipped_actions,
            publication_pack_artifact_id=0,
            ready_for_review=before.ready_for_review,
            submission_ready=before.submission_ready,
            remaining_next_actions=before.next_actions,
        )

    from ..orchestrator.artifacts import ArtifactManager
    from ..orchestrator.integrity import FinalizeManager
    from .verification_impls import citation_sanitize

    artifact_manager = ArtifactManager(db)

    for component in requested:
        existing = before.components.get(component)
        if existing is not None and existing.status == "present":
            refresh_compiled_bundle = (
                component == "final_bundle"
                and _final_bundle_needs_venue_refresh(db, topic_id, target_profile)
            )
            refresh_citation_integrity = False
            if component == "citation_integrity":
                draft = _latest_active_artifact(db, topic_id, ("draft_pack",))
                citation = _latest_active_artifact(
                    db,
                    topic_id,
                    ("citation_sanitization_report", "final_integrity_report"),
                )
                refresh_citation_integrity = _artifact_newer_than(draft, citation)
            if not refresh_compiled_bundle and not refresh_citation_integrity:
                skip(component, "already_present")
                continue

        if component == "citation_integrity":
            draft = _latest_active_artifact(db, topic_id, ("draft_pack",))
            draft_text = (
                _publication_text_from_payload(draft.get("payload"))
                if draft is not None
                else ""
            )
            if not draft_text:
                skip(component, "No draft_pack text available to sanitize.")
                continue
            result = citation_sanitize(db=db, topic_id=topic_id, text=draft_text)
            artifact = artifact_manager.record(
                topic_id=topic_id,
                stage="write",
                artifact_type="citation_sanitization_report",
                title="Citation Sanitization Report",
                payload=asdict(result),
                metadata={
                    "generated_by": "publication_pack_backfill",
                    "valid_count": result.valid_count,
                    "removed_count": result.removed_count,
                },
            )
            record_created(component, artifact)
            continue

        if component == "process_summary":
            artifact = FinalizeManager(db).create_process_summary(topic_id)
            record_created(component, artifact)
            continue

        if component == "final_bundle":
            compiled_payload = (
                _compiled_final_bundle_payload(
                    db=db,
                    topic_id=topic_id,
                    target_profile=target_profile,
                )
                if _is_venue_specific_profile(target_profile)
                else None
            )
            if compiled_payload is not None:
                artifact = artifact_manager.record(
                    topic_id=topic_id,
                    stage="finalize",
                    artifact_type="final_bundle",
                    title=f"Compiled Final Bundle ({target_profile})",
                    payload=compiled_payload,
                    metadata={
                        "generated_by": "publication_pack_backfill",
                        "target_profile": target_profile,
                        "template": compiled_payload.get("template", ""),
                        "pages": compiled_payload.get("pages", 0),
                    },
                )
            else:
                artifact = FinalizeManager(db).create_final_bundle(topic_id)
            record_created(component, artifact)
            continue

        skip(component, "Requires a dedicated non-backfill primitive or human input.")

    after = publication_pack_generate(
        db=db,
        topic_id=topic_id,
        target_profile=target_profile,
        record_artifact=record_artifact,
    )
    if after.publication_pack_artifact_id > 0:
        created_artifacts.append(
            {
                "component": "publication_pack",
                "artifact_id": after.publication_pack_artifact_id,
                "artifact_type": "publication_pack",
                "stage": "write",
                "title": f"Publication Pack ({target_profile})",
            }
        )

    return PublicationPackBackfillOutput(
        topic_id=topic_id,
        target_profile=target_profile,
        created_count=len(created_artifacts),
        created_artifacts=created_artifacts,
        skipped_actions=skipped_actions,
        publication_pack_artifact_id=after.publication_pack_artifact_id,
        ready_for_review=after.ready_for_review,
        submission_ready=after.submission_ready,
        remaining_next_actions=after.next_actions,
    )


def _publication_run_status(
    pack: PublicationPackOutput, blocking_checks: list[dict[str, Any]]
) -> str:
    if pack.submission_ready:
        return "submission_ready"
    if not pack.ready_for_review:
        return "missing_required"
    if blocking_checks:
        return "blocked"
    return "review_ready_qa_pending"


@register_primitive(PUBLICATION_RUN_SPEC)
def publication_run(
    *,
    db: Any,
    topic_id: int,
    target_profile: str = "high-impact-general",
    components: list[str] | tuple[str, ...] | None = None,
    record_artifact: bool = True,
    **_: Any,
) -> PublicationRunOutput:
    """Run the deterministic one-command publication closure path.

    This primitive intentionally does not draft missing science or synthesize
    figures. It turns the existing topic state into a reviewable publication
    package by executing only safe closure actions, then records the resulting
    readiness state for resumption.
    """
    if not _topic_exists(db, topic_id):
        raise ValueError(f"Topic not found: {topic_id}")

    backfill = publication_pack_backfill(
        db=db,
        topic_id=topic_id,
        target_profile=target_profile,
        components=components,
        record_artifact=record_artifact,
    )
    pack = publication_pack_generate(
        db=db,
        topic_id=topic_id,
        target_profile=target_profile,
        record_artifact=False,
    )
    blocking_checks = [
        check
        for check in pack.qa_checks
        if not bool(check.get("passed")) and check.get("severity") == "blocking"
    ]

    output = PublicationRunOutput(
        topic_id=topic_id,
        target_profile=target_profile,
        publication_pack_artifact_id=backfill.publication_pack_artifact_id,
        ready_for_review=pack.ready_for_review,
        submission_ready=pack.submission_ready,
        status=_publication_run_status(pack, blocking_checks),
        created_artifacts=backfill.created_artifacts,
        skipped_actions=backfill.skipped_actions,
        missing_required=pack.missing_required,
        missing_optional=pack.missing_optional,
        qa_checks=pack.qa_checks,
        blocking_checks=blocking_checks,
        next_actions=pack.next_actions,
        source_artifacts=pack.source_artifacts,
        provenance_map=pack.provenance_map,
    )

    if not record_artifact:
        return output

    from ..orchestrator.artifacts import ArtifactManager

    artifact_manager = ArtifactManager(db)
    artifact = artifact_manager.record(
        topic_id=topic_id,
        stage="finalize",
        artifact_type="publication_run",
        title=f"Publication Run ({target_profile})",
        payload=asdict(output),
        metadata={
            "generated_by": "publication_run",
            "status": output.status,
            "ready_for_review": output.ready_for_review,
            "submission_ready": output.submission_ready,
        },
    )
    if artifact is None:
        return output

    output = replace(output, publication_run_artifact_id=artifact.id)
    conn = db.connect()
    try:
        conn.execute(
            """
            UPDATE project_artifacts
            SET payload_json = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (json.dumps(asdict(output), ensure_ascii=False), artifact.id),
        )
        conn.commit()
    finally:
        conn.close()

    dependency_ids: set[int] = set()
    for item in [*pack.source_artifacts, *backfill.created_artifacts]:
        artifact_id = item.get("artifact_id") if isinstance(item, dict) else None
        if isinstance(artifact_id, int) and artifact_id != artifact.id:
            dependency_ids.add(artifact_id)
    for artifact_id in sorted(dependency_ids):
        artifact_manager.add_dependency(
            from_artifact_id=artifact_id,
            to_artifact_id=artifact.id,
            dependency_type="consumed_by",
        )

    return output
