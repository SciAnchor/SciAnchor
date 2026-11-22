"""PDF identity audit helpers for acquired papers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
from typing import Callable

from ..paper_sources import normalize_title


TextExtractor = Callable[[Path], str]


@dataclass(frozen=True)
class PDFAuditResult:
    paper_id: int
    title: str
    pdf_path: str
    status: str
    reason: str
    title_overlap: float
    doi_match: bool
    pmid_match: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "paper_id": self.paper_id,
            "title": self.title,
            "pdf_path": self.pdf_path,
            "status": self.status,
            "reason": self.reason,
            "title_overlap": self.title_overlap,
            "doi_match": self.doi_match,
            "pmid_match": self.pmid_match,
        }


def audit_pdf_identity(
    *,
    paper_id: int,
    title: str,
    doi: str = "",
    pmid: str = "",
    arxiv_id: str = "",
    pmcid: str = "",
    pdf_path: str,
    text_extractor: TextExtractor | None = None,
) -> PDFAuditResult:
    path = Path(pdf_path).expanduser()
    if not path.exists():
        return PDFAuditResult(
            paper_id=paper_id,
            title=title,
            pdf_path=str(path),
            status="missing",
            reason="pdf file missing",
            title_overlap=0.0,
            doi_match=False,
            pmid_match=False,
        )

    extractor = text_extractor or (lambda path: extract_pdf_text(path, max_pages=1))
    text = extractor(path)
    if not text.strip():
        return PDFAuditResult(
            paper_id=paper_id,
            title=title,
            pdf_path=str(path),
            status="suspect",
            reason="no extractable PDF text",
            title_overlap=0.0,
            doi_match=False,
            pmid_match=False,
        )

    # Identity belongs to the paper header, never to its reference list.
    text = re.split(
        r"(?im)^\s*(?:[0-9]+[.\s]+)?(?:references|bibliography)\s*$",
        text[:12000],
        maxsplit=1,
    )[0]
    normalized_text = normalize_title(text)
    normalized_title = normalize_title(title)
    title_overlap = _title_overlap(normalized_title, normalized_text)
    title_phrase_match = bool(normalized_title and normalized_title in normalized_text)
    distinctive_overlap = _title_overlap(
        _distinctive_title_text(normalized_title), normalized_text
    )
    doi_value = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE)
    doi_match = bool(
        doi_value
        and re.search(
            rf"(?<![a-z0-9]){re.escape(doi_value)}(?![a-z0-9/_-]|\.[a-z0-9])",
            text,
            re.IGNORECASE,
        )
    )
    pmid_match = bool(pmid and re.search(rf"\b{re.escape(pmid)}\b", text))

    title_match = title_phrase_match or (
        title_overlap >= 0.7 and distinctive_overlap >= 0.5
    )

    # A shared title cannot establish that this is the requested paper version.
    arxiv_pattern = re.escape(arxiv_id) + (
        r"(?:v\d+)?" if not re.search(r"v\d+$", arxiv_id) else ""
    )
    arxiv_match = bool(
        arxiv_id
        and re.search(
            rf"(?<![\w.]){arxiv_pattern}(?![\w.])",
            text,
            re.IGNORECASE,
        )
    )
    pmcid_match = bool(
        pmcid and re.search(rf"\b{re.escape(pmcid)}\b", text, re.IGNORECASE)
    )
    identifier_match = (
        doi_match
        if doi
        else arxiv_match
        if arxiv_id
        else pmid_match
        if pmid
        else pmcid_match
    )
    has_identifier = bool(doi or pmid or arxiv_id or pmcid)
    version_conflict = bool(
        arxiv_id and re.search(r"v\d+$", arxiv_id) and not arxiv_match
    )
    if (
        has_identifier
        and identifier_match
        and not version_conflict
        and (not title or title_match)
    ):
        signals: list[str] = []
        if doi_match:
            signals.append("DOI")
        if pmid_match:
            signals.append("PMID")
        if pmcid_match:
            signals.append("PMCID")
        if arxiv_match:
            signals.append("arXiv")
        if title_match:
            signals.append("title")
        return PDFAuditResult(
            paper_id=paper_id,
            title=title,
            pdf_path=str(path),
            status="verified",
            reason="matched " + "/".join(signals),
            title_overlap=round(title_overlap, 3),
            doi_match=doi_match,
            pmid_match=pmid_match,
        )

    return PDFAuditResult(
        paper_id=paper_id,
        title=title,
        pdf_path=str(path),
        status="suspect",
        reason="arxiv_version_mismatch"
        if version_conflict
        else "no title/DOI/PMID signal in extracted PDF text",
        title_overlap=round(title_overlap, 3),
        doi_match=False,
        pmid_match=False,
    )


def extract_pdf_text(path: Path, *, max_pages: int = 20) -> str:
    text = _extract_with_pymupdf(path, max_pages=max_pages)
    if text:
        return text
    text = _extract_with_pypdf(path, max_pages=max_pages)
    if text:
        return text
    text = _extract_with_pdftotext(path, max_pages=max_pages)
    if text:
        return text
    return ""


def _title_overlap(normalized_title: str, normalized_text: str) -> float:
    if not normalized_title or not normalized_text:
        return 0.0
    title_tokens = [token for token in normalized_title.split() if len(token) > 3]
    if not title_tokens:
        return 0.0
    text_tokens = set(normalized_text.split())
    matches = sum(1 for token in title_tokens if token in text_tokens)
    return matches / len(title_tokens)


def _distinctive_title_text(normalized_title: str) -> str:
    generic = {
        "the",
        "and",
        "for",
        "with",
        "from",
        "into",
        "that",
        "this",
        "effects",
        "effect",
        "impact",
        "impacts",
        "climate",
        "change",
        "health",
        "human",
        "public",
        "review",
        "systematic",
        "analysis",
        "association",
        "associations",
        "outcomes",
        "outcome",
    }
    return " ".join(
        token
        for token in normalized_title.split()
        if len(token) > 3 and token not in generic
    )


def _normalize_identifier(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def _extract_with_pymupdf(path: Path, *, max_pages: int = 20) -> str:
    try:
        import fitz  # type: ignore
    except Exception:
        return ""
    try:
        with fitz.open(path) as doc:
            return "\n".join(page.get_text("text") for page in doc[:max_pages])
    except Exception:
        return ""


def _extract_with_pypdf(path: Path, *, max_pages: int = 20) -> str:
    reader_cls = None
    try:
        from pypdf import PdfReader as reader_cls  # type: ignore
    except Exception:
        try:
            from PyPDF2 import PdfReader as reader_cls  # type: ignore
        except Exception:
            return ""
    try:
        reader = reader_cls(str(path))
        return "\n".join(
            (page.extract_text() or "") for page in reader.pages[:max_pages]
        )
    except Exception:
        return ""


def _extract_with_pdftotext(path: Path, *, max_pages: int = 20) -> str:
    try:
        result = subprocess.run(
            ["pdftotext", "-f", "1", "-l", str(max_pages), "-layout", str(path), "-"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout
