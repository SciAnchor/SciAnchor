"""SPC 1.0 精简论文事实契约。

论文记录只保存可复用的强标识、书目事实、字段来源和全文终局。
`fulltext.pdf.route` 只记成功下载链路。候选 URL、逐路由尝试、浏览器状态、
评审意见和物理 available_files 属于 audit，不属于该事实源。
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import Field, field_validator, model_validator

from paperfetch.artifacts.models import ArtifactPointer
from paperfetch.core.contracts_v1 import ErrorInfo, StrictContract
from paperfetch.core.information import unescape_public_text


PAPER_RECORD_SCHEMA = "spc.paper-record.v1"
_DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$", re.IGNORECASE)
_ARXIV_PATTERN = re.compile(
    r"^(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z]{2})?/\d{7})(?:v\d+)?$",
    re.IGNORECASE,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_paper_id() -> str:
    """生成可安全用作 Windows/Linux 目录名的论文实体 ID。"""

    return f"spc_{uuid.uuid4().hex}"


class PaperType(str, Enum):
    JOURNAL_ARTICLE = "journal_article"
    PREPRINT = "preprint"
    CONFERENCE_PAPER = "conference_paper"
    BOOK_CHAPTER = "book_chapter"
    OTHER = "other"


class MaterializationStatus(str, Enum):
    NOT_ATTEMPTED = "not_attempted"
    AVAILABLE = "available"
    FAILED = "failed"


class ParseStatus(str, Enum):
    NOT_ATTEMPTED = "not_attempted"
    AVAILABLE = "available"
    FAILED = "failed"


class IdentifierSet(StrictContract):
    doi: str | None = None
    pubmed_id: str | None = None
    pmc_id: str | None = None
    arxiv_id: str | None = None

    @field_validator("doi")
    @classmethod
    def normalize_doi(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
            if normalized.lower().startswith(prefix):
                normalized = normalized[len(prefix) :]
                break
        normalized = normalized.strip().lower()
        if not _DOI_PATTERN.fullmatch(normalized):
            raise ValueError("invalid DOI")
        return normalized

    @field_validator("pubmed_id")
    @classmethod
    def normalize_pubmed_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized.isdigit():
            raise ValueError("invalid PubMed ID")
        return normalized

    @field_validator("pmc_id")
    @classmethod
    def normalize_pmc_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().upper()
        if not re.fullmatch(r"PMC\d+", normalized):
            raise ValueError("invalid PMC ID")
        return normalized

    @field_validator("arxiv_id")
    @classmethod
    def normalize_arxiv_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if normalized.lower().startswith("arxiv:"):
            normalized = normalized[6:].strip()
        if not _ARXIV_PATTERN.fullmatch(normalized):
            raise ValueError("invalid arXiv ID")
        return normalized

    @model_validator(mode="after")
    def require_one_identifier(self) -> "IdentifierSet":
        if not any((self.doi, self.pubmed_id, self.pmc_id, self.arxiv_id)):
            raise ValueError("at least one strong identifier is required")
        return self

    def canonical(self) -> tuple[str, str]:
        for name in ("doi", "pubmed_id", "pmc_id", "arxiv_id"):
            value = getattr(self, name)
            if value:
                return name, value
        raise RuntimeError("identifier set is empty")


class Author(StrictContract):
    display_name: str = Field(min_length=1)
    family_name: str | None = None
    given_name: str | None = None
    orcid: str | None = Field(default=None, pattern=r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")

    @field_validator("display_name", "family_name", "given_name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        return unescape_public_text(value)


class VenueMetadata(StrictContract):
    name: str = Field(min_length=1)
    issn: str | None = None
    eissn: str | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = unescape_public_text(value)
        if not normalized:
            raise ValueError("venue name is required")
        return normalized


class BibliographicMetadata(StrictContract):
    title: str = Field(min_length=1)
    paper_type: PaperType = PaperType.OTHER
    authors: list[Author] = Field(default_factory=list)
    abstract: str | None = None
    publication_date: str | None = Field(
        default=None,
        pattern=r"^\d{4}(?:-(?:0[1-9]|1[0-2])(?:-(?:0[1-9]|[12]\d|3[01]))?)?$",
    )
    venue: VenueMetadata | None = None
    publisher: str | None = None
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    language: str | None = None
    license: str | None = None

    @field_validator(
        "title",
        "abstract",
        "publisher",
        "volume",
        "issue",
        "pages",
        "language",
        "license",
    )
    @classmethod
    def trim_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return unescape_public_text(value)


class SourceSnapshot(StrictContract):
    source_id: str = Field(min_length=1)
    source: str = Field(min_length=1)
    record_id: str | None = None
    retrieved_at: datetime = Field(default_factory=_utc_now)
    payload_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class FieldProvenance(StrictContract):
    field: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1)

    @field_validator("source_ids")
    @classmethod
    def unique_sources(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("source_ids must be unique")
        return value


class MetadataProvenance(StrictContract):
    sources: list[SourceSnapshot] = Field(min_length=1)
    fields: list[FieldProvenance] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_references(self) -> "MetadataProvenance":
        source_ids = [item.source_id for item in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("source_id must be unique")
        known = set(source_ids)
        fields = [item.field for item in self.fields]
        if len(fields) != len(set(fields)):
            raise ValueError("field provenance must be unique")
        unknown = {
            source_id
            for item in self.fields
            for source_id in item.source_ids
            if source_id not in known
        }
        if unknown:
            raise ValueError("field provenance references unknown source")
        return self


class IdentityVerification(StrictContract):
    verified: Literal[True] = True
    method: Literal["doi", "pmc_id", "pubmed_id", "arxiv_id", "title"]
    target: str = Field(min_length=1)
    observed: str = Field(min_length=1)


class PdfTerminal(StrictContract):
    status: MaterializationStatus = MaterializationStatus.NOT_ATTEMPTED
    artifact: ArtifactPointer | None = None
    identity: IdentityVerification | None = None
    route: str | None = None
    error: ErrorInfo | None = None

    @model_validator(mode="after")
    def validate_terminal(self) -> "PdfTerminal":
        if self.status == MaterializationStatus.AVAILABLE.value:
            if self.artifact is None or self.identity is None or self.error is not None:
                raise ValueError(
                    "available PDF requires artifact and verified identity without error"
                )
            if self.artifact.kind != "paper_pdf":
                raise ValueError("PDF terminal must reference paper_pdf artifact")
        elif self.status == MaterializationStatus.FAILED.value:
            if (
                self.artifact is not None
                or self.identity is not None
                or self.route is not None
                or self.error is None
            ):
                raise ValueError(
                    "failed PDF requires one error and no artifact or route"
                )
        elif any((self.artifact, self.identity, self.route, self.error)):
            raise ValueError("not_attempted PDF must not contain terminal evidence")
        return self


class ParseTerminal(StrictContract):
    status: ParseStatus = ParseStatus.NOT_ATTEMPTED
    artifact: ArtifactPointer | None = None
    error: ErrorInfo | None = None

    @model_validator(mode="after")
    def validate_terminal(self) -> "ParseTerminal":
        if self.status == ParseStatus.AVAILABLE.value:
            if self.artifact is None or self.error is not None:
                raise ValueError("available parse requires artifact without error")
            if self.artifact.kind != "mineru_fulltext":
                raise ValueError(
                    "parse terminal must reference mineru_fulltext artifact"
                )
        elif self.status == ParseStatus.FAILED.value:
            if self.artifact is not None or self.error is None:
                raise ValueError("failed parse requires one error and no artifact")
        elif self.artifact is not None or self.error is not None:
            raise ValueError("not_attempted parse must not contain terminal evidence")
        return self


class FulltextState(StrictContract):
    pdf: PdfTerminal = Field(default_factory=PdfTerminal)
    parse: ParseTerminal = Field(default_factory=ParseTerminal)

    @model_validator(mode="after")
    def parse_requires_pdf(self) -> "FulltextState":
        if (
            self.parse.status != ParseStatus.NOT_ATTEMPTED.value
            and self.pdf.status != MaterializationStatus.AVAILABLE.value
        ):
            raise ValueError("parse terminal requires an available verified PDF")
        return self


class PaperRecord(StrictContract):
    schema_version: Literal["spc.paper-record.v1"] = PAPER_RECORD_SCHEMA
    paper_id: str = Field(pattern=r"^spc_[0-9a-f]{32}$")
    revision: int = Field(default=1, ge=1)
    identifiers: IdentifierSet
    bibliographic: BibliographicMetadata
    provenance: MetadataProvenance
    fulltext: FulltextState = Field(default_factory=FulltextState)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def validate_dates(self) -> "PaperRecord":
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("paper timestamps must include timezone")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at must not precede created_at")
        proven_fields = {item.field for item in self.provenance.fields}
        required_fields = {"bibliographic.title"}
        required_fields.update(
            f"identifiers.{name}"
            for name in ("doi", "pubmed_id", "pmc_id", "arxiv_id")
            if getattr(self.identifiers, name) is not None
        )
        if missing := required_fields.difference(proven_fields):
            raise ValueError(
                f"missing provenance for required paper fields: {sorted(missing)}"
            )
        return self
