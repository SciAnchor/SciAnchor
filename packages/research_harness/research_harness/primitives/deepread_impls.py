"""Deep reading primitive implementations — non-LLM operations.

get_deep_reading: reads stored deep reading note from paper_annotations.
enrich_affiliations: extracts affiliations from PDF emails and author blocks.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Iterable

from .registry import (
    ENRICH_AFFILIATIONS_SPEC,
    GET_DEEP_READING_SPEC,
    register_primitive,
)
from .types import (
    AffiliationOutput,
    CrossPaperLink,
    DeepReadingNote,
    GetDeepReadingOutput,
    IndustrialFeasibility,
)

logger = logging.getLogger(__name__)

# Known email domain -> institution mapping
_DOMAIN_MAP: dict[str, str] = {
    # US universities
    "mit.edu": "MIT",
    "stanford.edu": "Stanford University",
    "berkeley.edu": "UC Berkeley",
    "cmu.edu": "Carnegie Mellon University",
    "harvard.edu": "Harvard University",
    "princeton.edu": "Princeton University",
    "columbia.edu": "Columbia University",
    "yale.edu": "Yale University",
    "cornell.edu": "Cornell University",
    "uchicago.edu": "University of Chicago",
    "umich.edu": "University of Michigan",
    "gatech.edu": "Georgia Institute of Technology",
    "illinois.edu": "UIUC",
    "ucla.edu": "UCLA",
    "washington.edu": "University of Washington",
    "nyu.edu": "New York University",
    "upenn.edu": "University of Pennsylvania",
    "utexas.edu": "UT Austin",
    "wisc.edu": "University of Wisconsin",
    "usc.edu": "University of Southern California",
    "purdue.edu": "Purdue University",
    # UK/EU universities
    "ox.ac.uk": "University of Oxford",
    "cam.ac.uk": "University of Cambridge",
    "imperial.ac.uk": "Imperial College London",
    "ucl.ac.uk": "University College London",
    "ethz.ch": "ETH Zurich",
    "epfl.ch": "EPFL",
    "mpi-inf.mpg.de": "Max Planck Institute",
    "inria.fr": "INRIA",
    # China universities
    "tsinghua.edu.cn": "Tsinghua University",
    "pku.edu.cn": "Peking University",
    "zju.edu.cn": "Zhejiang University",
    "sjtu.edu.cn": "Shanghai Jiao Tong University",
    "ustc.edu.cn": "USTC",
    "nju.edu.cn": "Nanjing University",
    "fudan.edu.cn": "Fudan University",
    "hit.edu.cn": "Harbin Institute of Technology",
    "ruc.edu.cn": "Renmin University of China",
    "buaa.edu.cn": "Beihang University",
    "bit.edu.cn": "Beijing Institute of Technology",
    "xjtu.edu.cn": "Xi'an Jiaotong University",
    "hust.edu.cn": "Huazhong University of Science and Technology",
    "sdu.edu.cn": "Shandong University",
    "nankai.edu.cn": "Nankai University",
    # Other Asia
    "u-tokyo.ac.jp": "University of Tokyo",
    "kaist.ac.kr": "KAIST",
    "snu.ac.kr": "Seoul National University",
    "nus.edu.sg": "National University of Singapore",
    "ntu.edu.sg": "Nanyang Technological University",
    # Tech companies
    "google.com": "Google",
    "deepmind.com": "Google DeepMind",
    "meta.com": "Meta",
    "fb.com": "Meta",
    "microsoft.com": "Microsoft",
    "openai.com": "OpenAI",
    "amazon.com": "Amazon",
    "amazon.science": "Amazon",
    "nvidia.com": "NVIDIA",
    "apple.com": "Apple",
    "anthropic.com": "Anthropic",
    "alibaba-inc.com": "Alibaba",
    "bytedance.com": "ByteDance",
    "tencent.com": "Tencent",
    "baidu.com": "Baidu",
    "jd.com": "JD.com",
    "meituan.com": "Meituan",
    "kuaishou.com": "Kuaishou",
    "huawei.com": "Huawei",
    "samsung.com": "Samsung",
    "salesforce.com": "Salesforce",
    "adobe.com": "Adobe",
    "ibm.com": "IBM",
    "intel.com": "Intel",
}

_AFFILIATION_KEYWORDS = re.compile(
    r"(?:University|Universit(?:y|ies)|Institute|Institution|Laborator(?:y|ies)|College|Department|"
    r"School of|Faculty|Hospital|Research Center|Research Centre|Center for|Centre for|"
    r"Inc\.|Corp\.|Corporation|Ltd\.|Company|"
    r"Google|Microsoft|Meta|Amazon|OpenAI|DeepMind|Alibaba|ByteDance|Tencent|Baidu|Huawei|NVIDIA|"
    r"大学|学院|研究所|实验室|研究院|公司|集团|科技)",
    re.I,
)


def merge_affiliation_lists(
    existing: Iterable[str],
    incoming: Iterable[str],
) -> list[str]:
    """Merge affiliation names case-insensitively while preserving order."""
    merged: list[str] = []
    seen: set[str] = set()
    for value in list(existing) + list(incoming):
        clean = str(value or "").strip()
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(clean)
    return merged


def persist_paper_affiliations(
    db: Any, paper_id: int, incoming: list[str]
) -> list[str]:
    """Merge incoming affiliations into papers.affiliations."""
    if not incoming:
        conn = db.connect()
        try:
            row = conn.execute(
                "SELECT affiliations FROM papers WHERE id = ?", (paper_id,)
            ).fetchone()
            if row is None:
                return []
            existing_raw = row["affiliations"] if "affiliations" in row.keys() else "[]"
            return json.loads(existing_raw) if existing_raw else []
        finally:
            conn.close()

    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT affiliations FROM papers WHERE id = ?", (paper_id,)
        ).fetchone()
        if row is None:
            return []
        existing_raw = row["affiliations"] if "affiliations" in row.keys() else "[]"
        existing = json.loads(existing_raw) if existing_raw else []
        merged = merge_affiliation_lists(existing, incoming)
        if merged != existing:
            conn.execute(
                "UPDATE papers SET affiliations = ? WHERE id = ?",
                (json.dumps(merged, ensure_ascii=False), paper_id),
            )
            conn.commit()
        return merged
    finally:
        conn.close()


def _domain_to_institution(domain: str) -> str:
    """Map email domain to institution, with fallback heuristic."""
    domain = domain.lower().strip()
    if domain in _DOMAIN_MAP:
        return _DOMAIN_MAP[domain]
    # Try matching suffix (e.g., cs.stanford.edu -> stanford.edu)
    parts = domain.split(".")
    for i in range(len(parts) - 1):
        suffix = ".".join(parts[i:])
        if suffix in _DOMAIN_MAP:
            return _DOMAIN_MAP[suffix]
    # Heuristic: use second-level domain as institution name
    if len(parts) >= 2:
        name = parts[-2]
        if name not in ("com", "org", "edu", "ac", "co", "net"):
            return name.replace("-", " ").title()
    return domain


def _extract_explicit_affiliations(text: str) -> list[str]:
    """Extract institution-like lines from the PDF author block."""
    results: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or len(line) < 8 or len(line) > 240:
            continue
        if "@" in line:
            continue
        if not _AFFILIATION_KEYWORDS.search(line):
            continue
        cleaned = re.sub(r"^[\d*,;\s†§]+", "", line).strip()
        cleaned = re.sub(r"\{[^}]+\}", "", cleaned).strip(" ,;")
        if not cleaned or len(cleaned) < 8:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        results.append(cleaned)
    return results


def _affiliations_from_emails(text: str) -> list[str]:
    emails = re.findall(r"[\w.+-]+@[\w.-]+\.\w+", text)
    results: list[str] = []
    seen: set[str] = set()
    for email in emails:
        domain = email.split("@", 1)[1]
        institution = _domain_to_institution(domain)
        key = institution.lower()
        if key not in seen:
            seen.add(key)
            results.append(institution)
    return results


def _parse_deep_reading_note(data: dict[str, Any]) -> DeepReadingNote:
    """Parse a dict into DeepReadingNote, tolerant of missing/malformed fields."""
    feas_raw = data.get("industrial_feasibility", {})
    if not isinstance(feas_raw, dict):
        feas_raw = {}
    feasibility = IndustrialFeasibility(
        viability=str(feas_raw.get("viability", "")).strip(),
        latency_constraints=str(feas_raw.get("latency_constraints", "")).strip(),
        data_requirements=str(feas_raw.get("data_requirements", "")).strip(),
        engineering_challenges=[
            str(c) for c in (feas_raw.get("engineering_challenges") or []) if c
        ],
        deployment_prerequisites=[
            str(p) for p in (feas_raw.get("deployment_prerequisites") or []) if p
        ],
    )

    links: list[CrossPaperLink] = []
    for item in data.get("cross_paper_links") or []:
        if isinstance(item, dict):
            links.append(
                CrossPaperLink(
                    target_paper_id=int(item.get("target_paper_id", 0)),
                    relation_type=str(item.get("relation_type", "")),
                    evidence=str(item.get("evidence", "")),
                )
            )

    return DeepReadingNote(
        algorithm_walkthrough=str(data.get("algorithm_walkthrough", "")),
        limitation_analysis=str(data.get("limitation_analysis", "")),
        reproducibility_assessment=str(data.get("reproducibility_assessment", "")),
        critical_assessment=str(data.get("critical_assessment", "")),
        industrial_feasibility=feasibility,
        research_implications=[
            str(r) for r in (data.get("research_implications") or []) if r
        ],
        cross_paper_links=links,
        author_affiliations=[
            str(a).strip()
            for a in (data.get("author_affiliations") or [])
            if str(a).strip()
        ],
        affiliation_evidence=str(data.get("affiliation_evidence", "")).strip(),
    )


@register_primitive(GET_DEEP_READING_SPEC)
def get_deep_reading(
    *,
    db: Any,
    paper_id: int,
    **_: Any,
) -> GetDeepReadingOutput:
    """Retrieve stored deep reading note from paper_annotations."""
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT content FROM paper_annotations "
            "WHERE paper_id = ? AND section = 'deep_reading'",
            (paper_id,),
        ).fetchone()
        if row is None or not (row["content"] or "").strip():
            return GetDeepReadingOutput(paper_id=paper_id, note=None, found=False)

        data = json.loads(row["content"])
        note = _parse_deep_reading_note(data)
        return GetDeepReadingOutput(paper_id=paper_id, note=note, found=True)
    except (json.JSONDecodeError, KeyError) as exc:
        logger.warning("Failed to parse deep reading for paper %d: %s", paper_id, exc)
        return GetDeepReadingOutput(paper_id=paper_id, note=None, found=False)
    finally:
        conn.close()


@register_primitive(ENRICH_AFFILIATIONS_SPEC)
def enrich_affiliations(
    *,
    db: Any,
    paper_id: int,
    **_: Any,
) -> AffiliationOutput:
    """Extract affiliations from PDF author block emails and institution lines."""
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM papers WHERE id = ?", (paper_id,)).fetchone()
        if row is None:
            return AffiliationOutput(paper_id=paper_id, source="error")

        existing_raw = row["affiliations"] if "affiliations" in row.keys() else "[]"
        existing: list[str] = json.loads(existing_raw) if existing_raw else []

        author_block_text = _get_author_block_text(conn, paper_id, row)
        if not author_block_text:
            return AffiliationOutput(
                paper_id=paper_id,
                affiliations=existing,
                new_affiliations=[],
                source="no_text",
            )

        from_email = _affiliations_from_emails(author_block_text)
        from_author_block = _extract_explicit_affiliations(author_block_text)
        merged_candidates = merge_affiliation_lists(from_email, from_author_block)
        new_affiliations = [
            aff
            for aff in merged_candidates
            if aff.lower() not in {a.lower() for a in existing}
        ]

        merged = merge_affiliation_lists(existing, new_affiliations)
        if merged != existing:
            conn.execute(
                "UPDATE papers SET affiliations = ? WHERE id = ?",
                (json.dumps(merged, ensure_ascii=False), paper_id),
            )
            conn.commit()

        source_parts: list[str] = []
        if from_email:
            source_parts.append("pdf_email_domain")
        if from_author_block:
            source_parts.append("pdf_author_block")
        source = "+".join(source_parts) if source_parts else "pdf_author_block"

        return AffiliationOutput(
            paper_id=paper_id,
            affiliations=merged,
            new_affiliations=new_affiliations,
            source=source,
        )
    finally:
        conn.close()


def _get_author_block_text(
    conn: Any, paper_id: int, paper_row: Any, *, max_pages: int = 2
) -> str:
    """Try to get the first 1-2 pages where author/affiliation blocks usually live."""
    pages = _get_pdf_pages_text(conn, paper_id, paper_row, max_pages=max_pages)
    if not pages:
        return ""
    return "\n".join(str(page) for page in pages if str(page).strip())


def _get_first_page_text(conn: Any, paper_id: int, paper_row: Any) -> str:
    pages = _get_pdf_pages_text(conn, paper_id, paper_row, max_pages=1)
    return str(pages[0]) if pages else ""


def _get_pdf_pages_text(
    conn: Any,
    paper_id: int,
    paper_row: Any,
    *,
    max_pages: int = 2,
) -> list[str]:
    """Try to get page text from paperindex structure artifact or PDF."""
    artifact = conn.execute(
        "SELECT path FROM paper_artifacts "
        "WHERE paper_id = ? AND artifact_type = 'paperindex_structure'",
        (paper_id,),
    ).fetchone()

    if artifact and artifact["path"]:
        structure_path = Path(artifact["path"])
        if structure_path.exists():
            try:
                structure_data = json.loads(structure_path.read_text())
                pages = structure_data.get("raw", {}).get("pages_text", [])
                if pages:
                    return [str(page) for page in pages[:max_pages]]
            except Exception:
                pass

    pdf_path = paper_row["pdf_path"] if "pdf_path" in paper_row.keys() else None
    if pdf_path and Path(pdf_path).exists():
        try:
            from paperindex import PaperIndexer

            structure = PaperIndexer().extract_structure(pdf_path)
            pages = structure.raw.get("pages_text", [])
            if pages:
                return [str(page) for page in pages[:max_pages]]
        except Exception:
            pass

    return []
