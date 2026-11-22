"""把论文记录与下载结果投影成内部命令结果；CLI 2.0 再做最小公共投影。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from paperfetch.fulltext.workflow import PaperFileOutcome
from paperfetch.artifacts.store import probe_artifact
from paperfetch.core.contracts_v1 import ArtifactRef
from paperfetch.core.information import (
    compact_route_attempts,
    identity_method_from_status,
    normalize_audit_ref,
    public_download_fact,
    public_fulltext_fact,
    public_parse_fact,
    unescape_public_text,
)
from paperfetch.fulltext.file_parse import FileParseOutcome
from paperfetch.papers.models import PaperRecord


def paper_projection(record: PaperRecord) -> dict[str, Any]:
    """durable 论文投影：lookup / add / download 共用。不含本轮 attempted。"""

    bibliographic = record.bibliographic
    authors = [
        {
            "name": unescape_public_text(author.display_name),
            **({"orcid": author.orcid} if author.orcid else {}),
        }
        for author in bibliographic.authors[:20]
        if unescape_public_text(author.display_name)
    ]
    venue = None
    if bibliographic.venue is not None:
        venue = bibliographic.venue.model_dump(mode="json", exclude_none=True)
        if venue.get("name"):
            venue["name"] = unescape_public_text(venue["name"])
    citation = {
        "title": unescape_public_text(bibliographic.title),
        "authors": authors,
        "author_count": len(bibliographic.authors),
        "authors_truncated": len(bibliographic.authors) > len(authors),
        "publication_date": bibliographic.publication_date,
        "venue": venue,
        "publisher": unescape_public_text(bibliographic.publisher),
        "volume": bibliographic.volume,
        "issue": bibliographic.issue,
        "pages": bibliographic.pages,
        "paper_type": bibliographic.paper_type,
        "license": bibliographic.license,
    }
    identity = record.fulltext.pdf.identity
    return {
        "paper_id": record.paper_id,
        "revision": record.revision,
        "identifiers": record.identifiers.model_dump(mode="json", exclude_none=True),
        "citation": {
            key: value for key, value in citation.items() if value is not None
        },
        "metadata_sources": sorted(
            {source.source for source in record.provenance.sources}
        ),
        "fulltext": public_fulltext_fact(
            pdf_status=record.fulltext.pdf.status,
            pdf_identity_verified=identity is not None,
            pdf_identity_method=identity.method if identity is not None else None,
            pdf_route=record.fulltext.pdf.route,
            parse_status=record.fulltext.parse.status,
        ),
    }


def download_fact_from_outcome(
    record: PaperRecord, outcome: PaperFileOutcome | None
) -> dict[str, Any]:
    if outcome is None:
        return public_download_fact(
            status=record.fulltext.pdf.status,
            route=record.fulltext.pdf.route,
            identity_verified=record.fulltext.pdf.identity is not None,
            identity_method=record.fulltext.pdf.identity.method
            if record.fulltext.pdf.identity
            else None,
        )
    if outcome.pdf is not None:
        status = "available"
        route = outcome.successful_route or record.fulltext.pdf.route
        identity_verified = outcome.identity is not None
        identity_method = (
            outcome.identity.method if outcome.identity is not None else None
        )
    elif outcome.pdf_error is not None:
        status = "failed"
        route = None
        identity_verified = False
        identity_method = None
    else:
        status = record.fulltext.pdf.status
        route = record.fulltext.pdf.route
        identity_verified = record.fulltext.pdf.identity is not None
        identity_method = (
            record.fulltext.pdf.identity.method
            if record.fulltext.pdf.identity
            else None
        )
    return public_download_fact(
        status=status,
        route=route,
        identity_verified=identity_verified,
        identity_method=identity_method,
        attempted=list(outcome.attempted),
        diagnostics=outcome.hop_diagnostics,
    )


def paper_command_data(
    record: PaperRecord,
    *,
    outcome: PaperFileOutcome | None = None,
    persisted: bool | None = None,
    include_download: bool = False,
) -> dict[str, Any]:
    data = paper_projection(record)
    if persisted is not None:
        data["persisted"] = persisted
    if include_download:
        data["download"] = download_fact_from_outcome(record, outcome)
    return data


def paper_file_artifacts(record: PaperRecord, seed_pack: Path) -> list[ArtifactRef]:
    refs: list[ArtifactRef] = []
    for pointer in (record.fulltext.pdf.artifact, record.fulltext.parse.artifact):
        if pointer is None:
            continue
        manifest = probe_artifact(seed_pack, pointer, expected_paper_id=record.paper_id)
        primary_role = (
            "article_pdf" if pointer.kind == "paper_pdf" else "document_markdown"
        )
        primary = next(item for item in manifest.files if item.role == primary_role)
        primary_path = (
            seed_pack / Path(pointer.manifest_path).parent / Path(primary.path)
        ).resolve()
        refs.append(
            ArtifactRef(
                kind=pointer.kind,
                path=str(primary_path),
                manifest_ref=pointer.manifest_path,
                sha256=primary.sha256,
                size_bytes=primary.size_bytes,
            )
        )
    return refs


def parse_item_projection(
    outcome: FileParseOutcome,
) -> tuple[list[ArtifactRef], dict[str, Any]]:
    refs: list[ArtifactRef] = []
    if outcome.markdown_path:
        refs.append(
            ArtifactRef(
                kind="mineru_fulltext",
                path=outcome.markdown_path,
                manifest_ref=outcome.manifest_path,
                sha256=outcome.markdown_sha256,
                size_bytes=outcome.markdown_size_bytes,
            )
        )
    return refs, {
        "parse": public_parse_fact(
            status="available" if outcome.succeeded else "failed",
            identity_bound=False,
            paper_record_written=False,
            input_path=outcome.input_path,
            input_sha256=outcome.input_sha256,
            input_size_bytes=outcome.input_size_bytes,
        ),
    }


def file_item_projection(
    record: PaperRecord,
    outcome: PaperFileOutcome,
    seed_pack: Path,
) -> tuple[list[ArtifactRef], dict[str, Any]]:
    return paper_file_artifacts(record, seed_pack), paper_command_data(
        record,
        outcome=outcome,
        persisted=True,
        include_download=True,
    )


def validation_download_fact(
    entry: dict[str, Any], *, proof: str | None = None
) -> dict[str, Any]:
    downloaded = (
        entry.get("status") == "downloaded"
        or entry.get("download_status") == "downloaded"
    )
    identity_status = entry.get("identity_status")
    return public_download_fact(
        status="available"
        if downloaded and entry.get("identity_verified")
        else (
            "failed"
            if entry.get("status") == "failed" or entry.get("passed") is False
            else "not_attempted"
        ),
        route=entry.get("successful_route") if downloaded else None,
        identity_verified=bool(entry.get("identity_verified")),
        identity_method=identity_method_from_status(identity_status),
        attempted=compact_route_attempts(entry.get("download_attempts")),
        proof=proof,
    )


def command_audit_ref(*refs: str | None, root: str | Path | None = None) -> str | None:
    for ref in refs:
        normalized = normalize_audit_ref(ref, root)
        if normalized:
            return normalized
    return None
