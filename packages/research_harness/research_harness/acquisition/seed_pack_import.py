"""Seed Pack import adapter: RH's contract boundary with paperfetch.

Research Harness never imports ``paperfetch``. SPC (or any tool that
produces the same seed pack contract) runs out-of-band; this module imports
the resulting pack directory through RH's audited boundary:

- ``seed_papers.jsonl`` -> ``PaperPool.ingest`` plus ``paper_metadata_facts``
  artifacts (field-level provenance, recall hits, and conflicts preserved);
- ``run_report.json``   -> ``external_route_audit`` artifacts with SPC failure
  classes mapped onto RH's stable taxonomy (originals preserved);
- ``pdf/``              -> ``%PDF`` magic + size + sha256 + identity audit,
  and only then a copy into RH's download dir and ``papers.pdf_path``.

Contract mismatches raise :class:`SeedPackContractError` with a deterministic
``reason`` instead of partially importing a pack RH cannot interpret.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..paper_sources import PaperRecord
from ..storage.db import Database
from ..storage.models import Paper
from .._workflow.orchestrator.artifacts import ArtifactManager
from .downloader import MIN_PDF_BYTES
from .metadata import paper_metadata_package_from_record, stable_json
from .pdf_audit import TextExtractor, audit_pdf_identity
from .pdf_cache import pdf_cache_key
from .figure_asset_bridge import (
    FigureAssetBridgeError,
    build_figure_asset_records,
    load_content_list,
)
from .url_validation import assess_pdf_url
from .pipeline import (
    DEFAULT_DOWNLOAD_DIR,
    _annotate_paper,
    _record_event,
    _record_route_audit,
)
from .routes import (
    PDFRouteAttempt,
    PDFRouteAudit,
    PDFRouteCandidate,
    redact_url,
    sha256_file,
)
from research_harness.config import state_path

logger = logging.getLogger(__name__)

SEED_PACK_IMPORT_SCHEMA_VERSION = "rh.seed_pack_import_report.v1"
EXTERNAL_ROUTE_AUDIT_SCHEMA_VERSION = "rh.external_route_audit.v1"
PARSE_ARTIFACT_SCHEMA_VERSION = "rh.paper_parse_artifact.v1"
SUPPORTED_RUN_REPORT_VERSIONS = frozenset(
    {
        "seed-paper-curator.run-report.v1",
        # BUG-014: v3 restructured per-paper download info into final_result{}
        # and transfer_attempts[]; a normalizer flattens it back to the shape the
        # route-audit importer reads. Records import independently, so accepting
        # v3 unblocks packs whose PDFs downloaded/verified fine.
        "seed-paper-curator.run-report.v3",
        # paperfetch is the public SPC; same report shapes under its own name.
        "paperfetch.run-report.v1",
        "paperfetch.run-report.v3",
    }
)
EXTERNAL_ROUTE = "external_seed_pack"
# SPC 1.0 pack layout: manifest.json + papers.jsonl + artifacts/<paper_id>/...
SUPPORTED_MANIFEST_VERSIONS = frozenset({"spc.seed-pack-manifest.v1"})

# SPC failure classes RH understands with confidence. Anything else maps to
# ``external_unmapped``; the original class is always preserved next to the
# mapped one so nothing is lost, only normalized.
SPC_FAILURE_TAXONOMY_MAP = {
    "not_pdf": "not_pdf",
    "too_small": "too_small",
    "timeout": "network_timeout",
    "network_error": "network_timeout",
    "rate_limited": "rate_limited",
    "paywall": "paywall",
    "subscription_required": "subscription_required",
    "publisher_challenge": "browser_challenge",
    "browser_challenge": "browser_challenge",
    "auth_failed": "auth_failed",
    "identity_mismatch": "identity_mismatch",
    "not_found": "http_404",
    "tool_missing": "optional_dependency_missing",
    "flaresolverr_unavailable": "optional_route_unavailable",
    "provider_disabled": "disabled_by_config",
    "not_attempted": "external_not_attempted",
}


class SeedPackContractError(ValueError):
    """Raised when a pack does not satisfy the seed pack contract."""

    def __init__(self, reason: str, detail: str = "") -> None:
        self.reason = reason
        self.detail = detail
        message = reason if not detail else f"{reason}: {detail}"
        super().__init__(message)


def map_spc_failure_class(value: str | None) -> str | None:
    if not value:
        return None
    return SPC_FAILURE_TAXONOMY_MAP.get(value, "external_unmapped")


@dataclass(frozen=True)
class LoadedSeedPack:
    pack_dir: Path
    records: list[dict[str, Any]]
    run_report: dict[str, Any] | None
    manifest: dict[str, Any] | None = None

    @property
    def run_report_version(self) -> str | None:
        if self.run_report is None:
            return None
        return str(self.run_report.get("report_version") or "")


@dataclass
class SeedPackImportReport:
    topic_id: int
    pack_dir: str
    run_report_version: str | None = None
    papers_seen: int = 0
    papers_new: int = 0
    papers_updated: int = 0
    papers_skipped: int = 0
    papers_rejected: list[dict[str, Any]] = field(default_factory=list)
    pdfs_imported: int = 0
    pdfs_skipped_existing: int = 0
    pdfs_missing: int = 0
    pdfs_rejected: list[dict[str, Any]] = field(default_factory=list)
    audits_imported: int = 0
    audits_unmatched: int = 0
    annotated: int = 0
    parse_imported: int = 0
    parse_missing: int = 0
    failure_taxonomies: dict[str, int] = field(default_factory=dict)
    results: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SEED_PACK_IMPORT_SCHEMA_VERSION,
            "topic_id": self.topic_id,
            "pack_dir": self.pack_dir,
            "run_report_version": self.run_report_version,
            "papers_seen": self.papers_seen,
            "papers_new": self.papers_new,
            "papers_updated": self.papers_updated,
            "papers_skipped": self.papers_skipped,
            "papers_rejected": list(self.papers_rejected),
            "pdfs_imported": self.pdfs_imported,
            "pdfs_skipped_existing": self.pdfs_skipped_existing,
            "pdfs_missing": self.pdfs_missing,
            "pdfs_rejected": list(self.pdfs_rejected),
            "audits_imported": self.audits_imported,
            "audits_unmatched": self.audits_unmatched,
            "annotated": self.annotated,
            "parse_imported": self.parse_imported,
            "parse_missing": self.parse_missing,
            "failure_taxonomies": dict(self.failure_taxonomies),
            "results": list(self.results),
        }


def _read_jsonl_records(
    jsonl_path: Path, *, require_title: bool
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_no, line in enumerate(
        jsonl_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SeedPackContractError(
                "seed_papers_invalid_json", f"line {line_no}: {exc.msg}"
            ) from exc
        if not isinstance(record, dict):
            raise SeedPackContractError(
                "record_invalid", f"line {line_no}: record must be an object"
            )
        if require_title and not record.get("title"):
            raise SeedPackContractError(
                "record_invalid", f"line {line_no}: title is required"
            )
        records.append(record)
    return records


def normalize_spc_v1_record(record: dict[str, Any]) -> dict[str, Any]:
    """Flatten one ``spc.paper-record.v1`` record onto the legacy flat shape
    that :func:`paper_record_from_spc` and the pdf/parse importers consume.

    Missing title is *not* rejected here: new-layout packs reject titleless
    records per-record at import time instead of failing the whole pack.
    """
    biblio = record.get("bibliographic") or {}
    identifiers = record.get("identifiers") or {}
    provenance = record.get("provenance") or {}
    fulltext = record.get("fulltext") or {}
    pdf_info = fulltext.get("pdf") or {}
    parse_info = fulltext.get("parse") or {}

    authors: list[dict[str, Any]] = []
    for author in biblio.get("authors") or []:
        if not isinstance(author, dict):
            continue
        name = str(author.get("display_name") or "").strip()
        if not name:
            name = " ".join(
                str(part).strip()
                for part in (author.get("given_name"), author.get("family_name"))
                if part
            ).strip()
        if name:
            authors.append({"name": name})

    year: int | None = None
    date_prefix = str(biblio.get("publication_date") or "")[:4]
    if date_prefix.isdigit():
        year = int(date_prefix)

    venue = biblio.get("venue") or {}
    venue_name = venue.get("name") if isinstance(venue, dict) else venue

    # Carry statuses onto the keys the pdf/parse importers already read;
    # declared artifact ids disambiguate when several art_* dirs coexist.
    fulltext_status: dict[str, Any] = {
        "pdf_status": str(pdf_info.get("status") or ""),
        "parse_status": str(parse_info.get("status") or ""),
    }
    if pdf_info.get("status") == "available":
        fulltext_status["download_status"] = "downloaded"
    if parse_info.get("status") == "available":
        fulltext_status["mineru_status"] = "parsed"
    pdf_artifact = pdf_info.get("artifact") or {}
    if pdf_artifact.get("artifact_id"):
        fulltext_status["pdf_artifact_id"] = str(pdf_artifact["artifact_id"])
    parse_artifact = parse_info.get("artifact") or {}
    if parse_artifact.get("artifact_id"):
        fulltext_status["parse_artifact_id"] = str(parse_artifact["artifact_id"])

    return {
        "paper_id": str(record.get("paper_id") or ""),
        "title": str(biblio.get("title") or ""),
        "authors": authors,
        "year": year,
        "venue": str(venue_name or ""),
        "publisher": str(biblio.get("publisher") or ""),
        "document_type": str(biblio.get("paper_type") or ""),
        "abstract": str(biblio.get("abstract") or ""),
        "doi": str(identifiers.get("doi") or ""),
        "arxiv_id": str(identifiers.get("arxiv_id") or ""),
        "pubmed_id": str(identifiers.get("pubmed_id") or ""),
        "pmc_id": str(identifiers.get("pmc_id") or ""),
        "source_refs": list(provenance.get("sources") or []),
        "fulltext_status": fulltext_status,
    }


def load_seed_pack(pack_dir: str | Path) -> LoadedSeedPack:
    root = Path(pack_dir).expanduser()
    if not root.is_dir():
        raise SeedPackContractError("pack_dir_missing", str(root))

    jsonl_path = root / "seed_papers.jsonl"
    if jsonl_path.is_file():
        records = _read_jsonl_records(jsonl_path, require_title=True)
        run_report: dict[str, Any] | None = None
        report_path = root / "run_report.json"
        if report_path.is_file():
            try:
                run_report = json.loads(report_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise SeedPackContractError("run_report_invalid_json", exc.msg) from exc
            version = str((run_report or {}).get("report_version") or "")
            if version not in SUPPORTED_RUN_REPORT_VERSIONS:
                raise SeedPackContractError("run_report_version_unsupported", version)

        return LoadedSeedPack(pack_dir=root, records=records, run_report=run_report)

    manifest_path = root / "manifest.json"
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SeedPackContractError("manifest_invalid_json", exc.msg) from exc
        version = str((manifest or {}).get("schema_version") or "")
        if version not in SUPPORTED_MANIFEST_VERSIONS:
            raise SeedPackContractError("manifest_version_unsupported", version)
        papers_path = root / "papers.jsonl"
        if not papers_path.is_file():
            raise SeedPackContractError("seed_papers_missing", str(papers_path))
        records = [
            normalize_spc_v1_record(record)
            for record in _read_jsonl_records(papers_path, require_title=False)
        ]
        return LoadedSeedPack(
            pack_dir=root, records=records, run_report=None, manifest=manifest
        )

    raise SeedPackContractError("seed_papers_missing", str(jsonl_path))


def paper_record_from_spc(record: dict[str, Any]) -> PaperRecord:
    """Map one SPC seed record onto RH's ``PaperRecord`` shape.

    Provenance blocks (source refs, recall hits, conflicts, facts) pass
    through untouched. Repro-audit results move into ``curation_signals`` so
    the metadata facts artifact keeps them; they are signals, never scores.
    """
    fulltext = dict(record.get("fulltext_status") or {})
    authors: list[str] = []
    affiliations: list[str] = []
    for author in record.get("authors") or []:
        if not isinstance(author, dict):
            continue
        name = str(author.get("name") or "").strip()
        if name:
            authors.append(name)
        for aff in author.get("affiliations") or []:
            cleaned = str(aff).strip()
            if cleaned and cleaned not in affiliations:
                affiliations.append(cleaned)

    curation = dict(record.get("curation_signals") or {})
    code_url = fulltext.get("extracted_code_url")
    if code_url:
        curation.setdefault("code_url", code_url)
    repro_status = fulltext.get("reproducibility_status")
    if repro_status and repro_status != "unchecked":
        curation["reproducibility_status"] = repro_status
        repo_metadata = fulltext.get("repo_metadata")
        if repo_metadata:
            curation["repo_metadata"] = repo_metadata

    return PaperRecord(
        title=str(record.get("title") or ""),
        authors=authors,
        affiliations=affiliations,
        year=record.get("year"),
        venue=str(record.get("venue") or ""),
        journal=str(record.get("journal") or ""),
        publisher=str(record.get("publisher") or ""),
        document_type=str(record.get("document_type") or ""),
        abstract=str(record.get("abstract") or ""),
        doi=str(record.get("doi") or ""),
        arxiv_id=str(record.get("arxiv_id") or ""),
        s2_id=str(record.get("semantic_scholar_id") or ""),
        openalex_id=str(record.get("openalex_id") or ""),
        pmid=str(record.get("pubmed_id") or ""),
        pmcid=str(record.get("pmc_id") or ""),
        url=str(fulltext.get("pdf_url") or ""),
        provider="seed_pack",
        citation_count=record.get("citation_count"),
        reference_count=record.get("reference_count"),
        source_refs=list(record.get("source_refs") or []),
        recall_hits=list(record.get("recall_hits") or []),
        institution_signals=record.get("institution_signals"),
        fulltext_status=fulltext,
        recorded_facts=dict(record.get("recorded_facts") or {}),
        available_files=dict(record.get("available_files") or {}),
        curation_signals=curation,
        merged_from=list(record.get("merged_from") or []),
        field_conflicts=list(record.get("field_conflicts") or []),
        selection_rank=record.get("selection_rank"),
        selection_bucket=record.get("selection_bucket"),
        selection_basis=list(record.get("selection_basis") or []),
        requires_agent_review=list(record.get("requires_agent_review") or []),
    )


def spc_pdf_key(record: dict[str, Any]) -> str:
    """Reproduce SPC's cache filename key so pack PDFs resolve without SPC."""
    return pdf_cache_key(
        doi=str(record.get("doi") or ""),
        arxiv_id=str(record.get("arxiv_id") or ""),
        title=str(record.get("title") or record.get("paper_id") or ""),
    )


def _contained_file(candidate: Path, root: Path) -> Path | None:
    """Resolve ``candidate`` and return it only if it is a file inside ``root``."""
    try:
        resolved = candidate.resolve()
    except OSError:
        return None
    if not resolved.is_relative_to(root):
        return None
    return resolved if resolved.is_file() else None


def _resolve_artifact_file(
    pack_dir: Path,
    record: dict[str, Any],
    *,
    kind_dir: str,
    filename: str,
    artifact_id_key: str,
) -> Path | None:
    """Locate ``artifacts/<paper_id>/<kind_dir>/art_*/<filename>`` (SPC 1.0).

    The artifact id the record declares wins; otherwise sorted order keeps the
    pick deterministic (artifact-level manifests carry no validity flag today).
    """
    spc_id = str(record.get("paper_id") or "")
    if not spc_id:
        return None
    art_dir = pack_dir / "artifacts" / spc_id / kind_dir
    if not art_dir.is_dir():
        return None
    fulltext = record.get("fulltext_status") or {}
    preferred = str(fulltext.get(artifact_id_key) or "")
    candidates = sorted(art_dir.glob(f"*/{filename}"))
    if preferred:
        candidates.sort(key=lambda path: path.parent.name != preferred)
    root = pack_dir.resolve()
    for candidate in candidates:
        resolved = _contained_file(candidate, root)
        if resolved is not None:
            return resolved
    return None


def _resolve_pack_pdf(pack_dir: Path, record: dict[str, Any]) -> Path | None:
    """Locate the record's PDF inside the pack; never follow paths outside it."""
    # SPC 1.0 layout first: artifacts/<paper_id>/pdf/art_*/article.pdf.
    resolved = _resolve_artifact_file(
        pack_dir,
        record,
        kind_dir="pdf",
        filename="article.pdf",
        artifact_id_key="pdf_artifact_id",
    )
    if resolved is not None:
        return resolved
    pdf_dir = pack_dir / "pdf"
    if not pdf_dir.is_dir():
        return None
    names = [f"{spc_pdf_key(record)}.pdf"]
    local_path = str((record.get("fulltext_status") or {}).get("local_path") or "")
    if local_path:
        basename = Path(local_path).name
        if basename and basename not in names:
            names.append(basename)
    root = pack_dir.resolve()
    for name in names:
        resolved = _contained_file(pdf_dir / name, root)
        if resolved is not None:
            return resolved
    return None


def _slugify_title(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
    return slug[:60] or "paper"


def _paper_from_record(record: PaperRecord) -> Paper:
    return Paper(
        title=record.title,
        authors=list(record.authors),
        affiliations=list(record.affiliations),
        year=record.year,
        venue=record.venue,
        abstract=record.abstract,
        doi=record.doi,
        arxiv_id=record.arxiv_id,
        s2_id=record.s2_id,
        pmid=record.pmid,
        pmcid=record.pmcid,
        url=record.url,
    )


def _replace_paper_artifact(
    conn: Any, paper_id: int, artifact_type: str, payload: dict[str, Any]
) -> None:
    conn.execute(
        "DELETE FROM paper_artifacts WHERE paper_id = ? AND artifact_type = ?",
        (paper_id, artifact_type),
    )
    conn.execute(
        "INSERT INTO paper_artifacts (paper_id, artifact_type, path, metadata)"
        " VALUES (?, ?, '', ?)",
        (paper_id, artifact_type, stable_json(payload)),
    )


def _reject_pdf(
    db: Database,
    report: SeedPackImportReport,
    *,
    paper_id: int,
    spc_paper_id: str,
    reason: str,
    pdf_path: Path,
    detail: str = "",
) -> None:
    report.pdfs_rejected.append(
        {"paper_id": paper_id, "spc_paper_id": spc_paper_id, "reason": reason}
    )
    audit = PDFRouteAudit(
        paper_id=paper_id,
        candidates=[
            PDFRouteCandidate(route=EXTERNAL_ROUTE, source="seed_pack", priority=0)
        ],
        attempts=[
            PDFRouteAttempt(
                route=EXTERNAL_ROUTE,
                error_class=reason,
                error=detail or reason,
                decision_reason="seed_pack_pdf_rejected",
                diagnostics={"pack_pdf": pdf_path.name},
            )
        ],
        failure_taxonomy=reason,
    )
    _record_route_audit(db, paper_id, audit)
    _record_event(
        db,
        paper_id,
        "download_fail",
        detail=f"seed pack pdf rejected: {reason}",
        provider="seed_pack",
    )


def _import_pdf(
    db: Database,
    pack: LoadedSeedPack,
    record: dict[str, Any],
    paper_id: int,
    *,
    download_path: Path,
    artifacts_path: Path,
    report: SeedPackImportReport,
    annotate: bool,
    text_extractor: TextExtractor | None,
) -> None:
    fulltext = record.get("fulltext_status") or {}
    spc_paper_id = str(record.get("paper_id") or "")
    pdf_path = _resolve_pack_pdf(pack.pack_dir, record)
    if pdf_path is None:
        if fulltext.get("download_status") == "downloaded":
            report.pdfs_missing += 1
        return

    source_url = fulltext.get("resolved_pdf_url") or fulltext.get("pdf_url")
    url_ownership = assess_pdf_url(str(record.get("doi") or ""), source_url)
    if url_ownership == "suspect_non_pdf":
        _reject_pdf(
            db,
            report,
            paper_id=paper_id,
            spc_paper_id=spc_paper_id,
            reason="not_pdf",
            pdf_path=pdf_path,
            detail="non_pdf_url_pattern",
        )
        return

    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT pdf_path FROM papers WHERE id = ?", (paper_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is not None and (row["pdf_path"] or "").strip():
        report.pdfs_skipped_existing += 1
        return

    try:
        with pdf_path.open("rb") as handle:
            prefix = handle.read(1024)
        size = pdf_path.stat().st_size
    except OSError as exc:
        _reject_pdf(
            db,
            report,
            paper_id=paper_id,
            spc_paper_id=spc_paper_id,
            reason="not_pdf",
            pdf_path=pdf_path,
            detail=str(exc),
        )
        return
    if not prefix.startswith(b"%PDF"):
        _reject_pdf(
            db,
            report,
            paper_id=paper_id,
            spc_paper_id=spc_paper_id,
            reason="not_pdf",
            pdf_path=pdf_path,
        )
        return
    if size < MIN_PDF_BYTES:
        _reject_pdf(
            db,
            report,
            paper_id=paper_id,
            spc_paper_id=spc_paper_id,
            reason="too_small",
            pdf_path=pdf_path,
            detail=f"{size} bytes",
        )
        return

    audit_result = audit_pdf_identity(
        paper_id=paper_id,
        title=str(record.get("title") or ""),
        doi=str(record.get("doi") or ""),
        pmid=str(record.get("pubmed_id") or ""),
        arxiv_id=str(record.get("arxiv_id") or ""),
        pmcid=str(record.get("pmc_id") or ""),
        pdf_path=str(pdf_path),
        text_extractor=text_extractor,
    )
    if audit_result.status != "verified":
        _reject_pdf(
            db,
            report,
            paper_id=paper_id,
            spc_paper_id=spc_paper_id,
            reason="identity_mismatch",
            pdf_path=pdf_path,
            detail=audit_result.reason,
        )
        return

    sha256 = sha256_file(pdf_path)
    download_path.mkdir(parents=True, exist_ok=True)
    target = (
        download_path
        / f"{paper_id}_{_slugify_title(str(record.get('title') or ''))}.pdf"
    )
    shutil.copy2(pdf_path, target)

    conn = db.connect()
    try:
        conn.execute(
            "UPDATE papers SET pdf_path = ?, pdf_hash = ?, status = 'downloaded'"
            " WHERE id = ?",
            (str(target), sha256, paper_id),
        )
        conn.commit()
    finally:
        conn.close()

    resolved_url = redact_url(
        fulltext.get("resolved_pdf_url") or fulltext.get("pdf_url")
    )
    audit = PDFRouteAudit(
        paper_id=paper_id,
        candidates=[
            PDFRouteCandidate(
                route=EXTERNAL_ROUTE,
                url=resolved_url,
                source="seed_pack",
                priority=0,
            )
        ],
        attempts=[
            PDFRouteAttempt(
                route=EXTERNAL_ROUTE,
                url=resolved_url,
                bytes_downloaded=size,
                decision_reason="imported_from_seed_pack",
                diagnostics={
                    "pack_pdf": pdf_path.name,
                    "spc_paper_id": spc_paper_id,
                    "identity_audit": audit_result.reason,
                    "url_ownership": url_ownership,
                },
            )
        ],
        successful_route=EXTERNAL_ROUTE,
        resolved_pdf_url=resolved_url,
        sha256=sha256,
        local_path=str(target),
    )
    _record_route_audit(db, paper_id, audit)
    _record_event(db, paper_id, "download_ok", provider="seed_pack")
    report.pdfs_imported += 1

    if annotate:
        if _annotate_paper(db, paper_id, target, artifacts_path):
            _record_event(db, paper_id, "annotate_ok")
            report.annotated += 1
        else:
            _record_event(db, paper_id, "annotate_fail")


def _resolve_pack_markdown(pack_dir: Path, record: dict[str, Any]) -> Path | None:
    """Locate the record's parsed full.md inside the pack's mineru/ tree.

    SPC lays out ``mineru/{doi_with_underscores}/full.md``; the absolute
    ``mineru_markdown_path`` in fulltext_status belongs to the producing
    machine and is never trusted — only pack-relative resolution counts.
    Archives are deliberately not extracted here: RH consumes pre-extracted
    markdown only, so no zip handling surface exists at the boundary.
    """
    # SPC 1.0 layout first: artifacts/<paper_id>/fulltext/art_*/document.md.
    resolved = _resolve_artifact_file(
        pack_dir,
        record,
        kind_dir="fulltext",
        filename="document.md",
        artifact_id_key="parse_artifact_id",
    )
    if resolved is not None:
        return resolved
    mineru_dir = pack_dir / "mineru"
    if not mineru_dir.is_dir():
        return None
    fulltext = record.get("fulltext_status") or {}
    dir_names: list[str] = []
    doi = str(record.get("doi") or "").strip()
    if doi:
        dir_names.append(doi.replace("/", "_").replace("\\", "_"))
    extracted = str(fulltext.get("mineru_extracted_dir") or "")
    if extracted:
        basename = Path(extracted).name
        if basename and basename not in dir_names:
            dir_names.append(basename)
    root = pack_dir.resolve()
    for name in dir_names:
        candidate = mineru_dir / name / "full.md"
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if not resolved.is_relative_to(root):
            continue
        if resolved.is_file():
            return resolved
    return None


def _import_parse_artifact(
    db: Database,
    pack: LoadedSeedPack,
    record: dict[str, Any],
    paper_id: int,
    *,
    artifacts_path: Path,
    report: SeedPackImportReport,
) -> None:
    fulltext = record.get("fulltext_status") or {}
    markdown = _resolve_pack_markdown(pack.pack_dir, record)
    if markdown is None:
        if fulltext.get("mineru_status") == "parsed":
            report.parse_missing += 1
        return

    target_dir = artifacts_path / "parse" / str(paper_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / "full.md"
    shutil.copy2(markdown, target)

    # The MinerU content list (heading pages / per-page text) rides along when
    # the pack has it; paperindex's MinerUArtifactParser uses it for real page
    # numbers and works markdown-only without it.
    # SPC 1.0 fulltext artifacts spell it ``content-list.json``.
    content_list_target = ""
    for candidate in sorted(markdown.parent.glob("*content_list.json")) + sorted(
        markdown.parent.glob("content-list.json")
    ):
        copied = target_dir / "content_list.json"
        shutil.copy2(candidate, copied)
        content_list_target = str(copied)
        break

    warnings: list[str] = []
    figure_assets: dict[str, Any] | None = None
    if content_list_target:
        try:
            figure_assets = build_figure_asset_records(
                content_list=load_content_list(content_list_target),
                markdown=target.read_text(encoding="utf-8"),
                source_dir=markdown.parent,
                dest_dir=target_dir,
                parser_name="mineru",
                parser_version=str(
                    fulltext.get("mineru_version")
                    or fulltext.get("parser_version")
                    or ""
                ),
            )
        except FigureAssetBridgeError as exc:
            warnings.append(str(exc))

    payload = {
        "schema_version": PARSE_ARTIFACT_SCHEMA_VERSION,
        "paper_id": paper_id,
        "provider": "mineru",
        "status": "parsed",
        "origin": "seed_pack",
        "markdown_path": str(target),
        "content_list_path": content_list_target,
        "parse_quality": str(fulltext.get("parse_quality") or "unknown"),
        "sha256": sha256_file(target),
        "figure_assets": figure_assets,
        "warnings": warnings,
        "errors": [],
    }
    conn = db.connect()
    try:
        _replace_paper_artifact(conn, paper_id, "paper_parse_artifact", payload)
        conn.commit()
    finally:
        conn.close()
    _record_event(db, paper_id, "parse_artifact_imported", provider="seed_pack")
    report.parse_imported += 1


def _external_audit_payload(
    entry: dict[str, Any], report_version: str | None
) -> dict[str, Any]:
    def _mapped_attempt(attempt: dict[str, Any]) -> dict[str, Any]:
        external_class = attempt.get("error_class")
        return {
            "route": f"spc:{attempt.get('route') or 'unknown'}",
            "url": redact_url(attempt.get("url")),
            "host": attempt.get("host"),
            "status_code": attempt.get("status_code"),
            "content_type": attempt.get("content_type"),
            "error_class": map_spc_failure_class(external_class),
            "external_error_class": external_class,
            "skipped": bool(attempt.get("skipped")),
            "duration_ms": attempt.get("duration_ms"),
            "queue_ms": attempt.get("queue_ms"),
            "diagnostics": attempt.get("diagnostics") or {},
        }

    def _mapped_error(error: dict[str, Any]) -> dict[str, Any]:
        external_class = error.get("error_class") or error.get("error")
        return {
            "route": f"spc:{error.get('route') or 'unknown'}",
            "error_class": map_spc_failure_class(external_class),
            "external_error_class": external_class,
            "error": error.get("error"),
        }

    external_taxonomy = entry.get("failure_taxonomy")
    return {
        "schema_version": EXTERNAL_ROUTE_AUDIT_SCHEMA_VERSION,
        "origin": "seed_pack",
        "source_report_version": report_version,
        "spc_paper_id": entry.get("paper_id"),
        "doi": entry.get("doi"),
        "arxiv_id": entry.get("arxiv_id"),
        "download_status": entry.get("download_status"),
        "cache_hit": bool(entry.get("cache_hit")),
        "attempted_routes": [
            f"spc:{route}" for route in entry.get("attempted_routes") or []
        ],
        "successful_route": (
            f"spc:{entry['successful_route']}"
            if entry.get("successful_route")
            else None
        ),
        "resolved_pdf_url": redact_url(entry.get("resolved_pdf_url")),
        "failure_taxonomy": map_spc_failure_class(external_taxonomy),
        "external_failure_taxonomy": external_taxonomy,
        "route_errors": [
            _mapped_error(error)
            for error in entry.get("route_errors") or []
            if isinstance(error, dict)
        ],
        "download_attempts": [
            _mapped_attempt(attempt)
            for attempt in entry.get("download_attempts") or []
            if isinstance(attempt, dict)
        ],
    }


def _normalize_run_report_entry(
    entry: dict[str, Any], version: str | None
) -> dict[str, Any]:
    """Flatten a v3 paper entry to the flat shape ``_external_audit_payload``
    reads (BUG-014). v1 entries pass through unchanged.
    """
    if not str(version or "").endswith(".v3"):
        return entry
    final_result = entry.get("final_result") or {}
    attempts = [
        a for a in (entry.get("transfer_attempts") or []) if isinstance(a, dict)
    ]

    def _attempt(a: dict[str, Any]) -> dict[str, Any]:
        diagnostics = a.get("diagnostics") or {}
        return {
            "route": a.get("route"),
            "url": diagnostics.get("url"),
            "host": diagnostics.get("host"),
            "status_code": diagnostics.get("status_code"),
            "content_type": diagnostics.get("content_type"),
            "error_class": a.get("error_class"),
            "skipped": a.get("outcome") == "skipped",
            "duration_ms": a.get("elapsed_ms") or a.get("duration_ms"),
            "queue_ms": a.get("queue_ms"),
            "diagnostics": diagnostics,
        }

    merged = dict(entry)
    merged.update(
        {
            "download_status": final_result.get("download_status"),
            "successful_route": final_result.get("successful_route"),
            "resolved_pdf_url": final_result.get("resolved_pdf_url"),
            "failure_taxonomy": final_result.get("failure_taxonomy"),
            "cache_hit": final_result.get("cache_hit"),
            "attempted_routes": [a.get("route") for a in attempts if a.get("route")],
            "download_attempts": [_attempt(a) for a in attempts],
            "route_errors": [
                {
                    "route": a.get("route"),
                    "error_class": a.get("error_class"),
                    "error": a.get("message"),
                }
                for a in attempts
                if a.get("outcome") not in ("success", None)
            ],
        }
    )
    return merged


def _import_run_report_audits(
    db: Database,
    pack: LoadedSeedPack,
    spc_to_rh: dict[str, int],
    doi_to_rh: dict[str, int],
    report: SeedPackImportReport,
) -> None:
    assert pack.run_report is not None
    version = pack.run_report_version
    for raw_entry in pack.run_report.get("papers") or []:
        if not isinstance(raw_entry, dict):
            continue
        entry = _normalize_run_report_entry(raw_entry, version)
        paper_id = spc_to_rh.get(str(entry.get("paper_id") or ""))
        if paper_id is None:
            doi = str(entry.get("doi") or "").strip().lower()
            paper_id = doi_to_rh.get(doi) if doi else None
        if paper_id is None:
            report.audits_unmatched += 1
            continue
        payload = _external_audit_payload(entry, version)
        conn = db.connect()
        try:
            _replace_paper_artifact(conn, paper_id, "external_route_audit", payload)
            conn.commit()
        finally:
            conn.close()
        _record_event(
            db,
            paper_id,
            "external_route_audit",
            detail=stable_json(
                {
                    "successful_route": payload["successful_route"],
                    "failure_taxonomy": payload["failure_taxonomy"],
                    "external_failure_taxonomy": payload["external_failure_taxonomy"],
                }
            ),
            provider="seed_pack",
        )
        report.audits_imported += 1
        mapped = payload["failure_taxonomy"]
        if mapped:
            report.failure_taxonomies[mapped] = (
                report.failure_taxonomies.get(mapped, 0) + 1
            )


def import_seed_pack(
    db: Database,
    pack_dir: str | Path,
    topic_id: int,
    *,
    download_dir: str | Path | None = None,
    artifacts_root: str | Path | None = None,
    screening_status: str = "candidate",
    relevance: str = "medium",
    annotate: bool = True,
    limit: int | None = None,
    text_extractor: TextExtractor | None = None,
) -> SeedPackImportReport:
    """Import an SPC seed pack directory into RH for one topic.

    Papers land as ``candidate`` by default: seed packs are curated recall,
    not screening decisions, so RH's own screening flow keeps ownership.
    """
    from ..core.paper_pool import PaperIdentityConflict, PaperPool

    pack = load_seed_pack(pack_dir)
    report = SeedPackImportReport(
        topic_id=topic_id,
        pack_dir=str(pack.pack_dir),
        run_report_version=pack.run_report_version,
    )
    download_path = Path(download_dir or DEFAULT_DOWNLOAD_DIR)
    artifacts_path = Path(artifacts_root) if artifacts_root else state_path("artifacts")

    records = pack.records if limit is None else pack.records[: max(0, limit)]
    spc_to_rh: dict[str, int] = {}
    doi_to_rh: dict[str, int] = {}
    ingested: list[tuple[dict[str, Any], int]] = []

    conn = db.connect()
    try:
        pool = PaperPool(conn)
        for record in records:
            spc_id = str(record.get("paper_id") or "")
            report.papers_seen += 1
            if not str(record.get("title") or "").strip():
                # New-layout packs may carry a few titleless records; reject
                # each one instead of failing the whole pack.
                report.papers_skipped += 1
                report.papers_rejected.append(
                    {"spc_paper_id": spc_id, "title": "", "reason": "title_missing"}
                )
                continue
            paper_record = paper_record_from_spc(record)
            paper = _paper_from_record(paper_record)
            existed = pool._find_existing(paper) is not None
            try:
                paper_id = pool.ingest(
                    paper,
                    topic_id=topic_id,
                    relevance=relevance,
                    screening_status=screening_status,
                    screening_reason="seed pack import",
                    candidate_source="seed_pack",
                )
            except PaperIdentityConflict as exc:
                # One unimportable record must never abort a whole pack: the
                # ingest rolled itself back, so skip this one and report why.
                report.papers_skipped += 1
                report.papers_rejected.append(
                    {
                        "spc_paper_id": spc_id,
                        "title": paper_record.title,
                        "reason": "identity_conflict",
                        "field": exc.field,
                        "value": exc.value,
                        "detail": str(exc),
                    }
                )
                logger.warning(
                    "seed pack record %s skipped: papers.%s already belongs to "
                    "another pool row",
                    spc_id or paper_record.title,
                    exc.field,
                )
                continue
            facts = paper_metadata_package_from_record(paper_record)
            _replace_paper_artifact(conn, paper_id, "paper_metadata_facts", facts)
            conn.commit()

            if existed:
                report.papers_updated += 1
            else:
                report.papers_new += 1
            if spc_id:
                spc_to_rh[spc_id] = paper_id
            if paper_record.doi:
                doi_to_rh.setdefault(paper_record.doi.strip().lower(), paper_id)
            ingested.append((record, paper_id))
            report.results.append(
                {
                    "paper_id": paper_id,
                    "spc_paper_id": spc_id,
                    "title": paper_record.title,
                    "existed": existed,
                }
            )
    finally:
        conn.close()

    for record, paper_id in ingested:
        _record_event(db, paper_id, "seed_pack_ingest", provider="seed_pack")
        _import_pdf(
            db,
            pack,
            record,
            paper_id,
            download_path=download_path,
            artifacts_path=artifacts_path,
            report=report,
            annotate=annotate,
            text_extractor=text_extractor,
        )
        _import_parse_artifact(
            db,
            pack,
            record,
            paper_id,
            artifacts_path=artifacts_path,
            report=report,
        )

    if pack.run_report is not None:
        _import_run_report_audits(db, pack, spc_to_rh, doi_to_rh, report)

    artifact = ArtifactManager(db).record(
        topic_id=topic_id,
        stage="acquisition",
        artifact_type="seed_pack_import_report",
        title=f"Seed pack import: {pack.pack_dir.name}",
        payload=report.to_dict(),
        metadata={
            "contract": pack.run_report_version
            or (pack.manifest or {}).get("schema_version")
            or "seed_papers_only",
            "rh_schema_version": SEED_PACK_IMPORT_SCHEMA_VERSION,
        },
    )
    if artifact.id is None:
        logger.warning("failed to record seed_pack_import_report artifact")

    return report
